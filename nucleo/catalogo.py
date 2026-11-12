"""
catalogo.py - Datos de la tienda del Catálogo. No vende ni descarga juegos.

Títulos y carátulas: listados de Libretro (boxart.py). Año, género y desarrollador: libretro-database.
Descripciones: Wikipedia. Juegos gratis: Homebrew Hub (base comunitaria de homebrew) e itch.io, por etiquetas.
Todo lo que llega de internet se muestra como texto y sus enlaces se comprueban aquí y en abrir_enlace.
"""
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import boxart, noticias

POR_PAGINA = 48
TTL_DATOS = 14 * 24 * 3600
TTL_GRATIS = 3600
URL_DATOS = "https://raw.githubusercontent.com/libretro/libretro-database/master/metadat"
URL_HOMEBREW = "https://hh3.gbdev.io"
PAGINA_HOMEBREW = "https://hh.gbdev.io/game/"
PLATAFORMAS_GRATIS = ("GB", "GBC", "GBA", "NES")
URL_ITCH = "https://itch.io/games/free/"
# itch.io corta si se le piden varias listas seguidas: se pide una sola por acción y se recuerda una hora
ETIQUETAS_ITCH = {"itch-homebrew": "tag-homebrew", "itch-gb": "tag-gb-studio", "itch-nes": "tag-nes", "itch-snes": "tag-snes"}
JUEGOS_POR_LISTA_ITCH = 30
HOSTS = {"hh.gbdev.io", "es.wikipedia.org", "en.wikipedia.org"}
_CAMPOS = {"genre": "genero", "developer": "desarrollador", "publisher": "editor", "releaseyear": "anio"}
# Sin carpeta genre/: libretro tiene un archivo aparte con todos los datos de cada juego
DATS_COMPLETOS = ("Sony - PlayStation", "Sony - PlayStation 2")
_AGENTE = "RetroEmulator/1.0 (https://github.com/Ropro-GG/RetroEmulator)"   # Wikipedia exige identificarse
_NO_ES_UN_JUEGO = re.compile(r"franquicia|franchise|\bsaga\b|serie de videojuegos|video game series")
_lock = threading.Lock()
_listas = {}          # sistema -> juegos ya armados
_descripciones = {}   # clave -> descripción (o None si no hay)
_gratis = (0.0, [])   # (momento, portada de juegos gratis)
_itch = {}            # (etiqueta, página) -> (momento, juegos)


def es_enlace_de_itch(host):
    return host == "itch.io" or (host or "").endswith(".itch.io")


def leer_dat(texto, campo):
    """Convierte un archivo de libretro-database en {título normalizado: valor}."""
    datos = {}
    for nombre, valor in re.findall(r'comment "([^"\n]+)"\s+' + campo + r' "?([^"\n]+)"?', texto):
        clave = boxart.analizar_titulo(nombre)[0]
        if clave:
            datos.setdefault(clave, valor.strip())
    return datos


def leer_dat_completo(texto):
    """Archivo con un bloque por juego (name, genre, developer...). Devuelve {campo: {título normalizado: valor}}."""
    datos = {campo: {} for campo in _CAMPOS}
    for nombre, cuerpo in re.findall(r'^game \(\s*name "([^"\n]+)"(.*?)^\)', texto, flags=re.M | re.S):
        clave = boxart.analizar_titulo(nombre)[0]
        for campo, valor in re.findall(r'^\t(' + "|".join(_CAMPOS) + r') "?([^"\n]+)"?$', cuerpo, flags=re.M):
            if clave:
                datos[campo].setdefault(clave, valor.strip())
    return datos


def _datos_completos(sistema):
    ruta = os.path.join(boxart.CARPETA_CACHE, "datos_" + boxart._archivo_seguro(sistema) + "_completo.json")
    if os.path.isfile(ruta) and time.time() - os.path.getmtime(ruta) < TTL_DATOS:
        return boxart._leer_json(ruta) or {}
    try:
        crudo = boxart._http_get(f"{URL_DATOS}/{urllib.parse.quote(sistema)}.dat", timeout=60, reintentos=2)
        datos = leer_dat_completo(crudo.decode("utf-8", errors="ignore")) if crudo else {}
        os.makedirs(boxart.CARPETA_CACHE, exist_ok=True)
        boxart._guardar_json(ruta, datos)
        return datos
    except Exception as e:
        print(f"[CATALOGO] Sin datos completos para {sistema}: {e}")
        return {}


def _datos_de(sistema):
    """Año, género, desarrollador y editor. Si no se pueden bajar, el catálogo sigue funcionando sin ellos."""
    salida = {}
    for campo, nombre in _CAMPOS.items():
        ruta = os.path.join(boxart.CARPETA_CACHE, "datos_" + boxart._archivo_seguro(f"{sistema}_{campo}") + ".json")
        datos = None
        if os.path.isfile(ruta) and time.time() - os.path.getmtime(ruta) < TTL_DATOS:
            datos = boxart._leer_json(ruta)
        if datos is None:
            try:
                crudo = boxart._http_get(f"{URL_DATOS}/{campo}/{urllib.parse.quote(sistema)}.dat", timeout=30, reintentos=2)
                datos = leer_dat(crudo.decode("utf-8", errors="ignore"), campo) if crudo else {}
                os.makedirs(boxart.CARPETA_CACHE, exist_ok=True)
                boxart._guardar_json(ruta, datos)
            except Exception as e:
                print(f"[CATALOGO] Sin datos de {campo} para {sistema}: {e}")
                datos = {}
        salida[nombre] = datos
    if sistema in DATS_COMPLETOS:
        for campo, valores in _datos_completos(sistema).items():
            for clave, valor in valores.items():
                salida[_CAMPOS[campo]].setdefault(clave, valor)
    return salida


def _armar_lista(indice, datos, url_base):
    """Una entrada por título, sin betas, hacks ni copias piratas."""
    juegos = []
    for clave, opciones in indice.por_clave.items():
        buenas = [o for o in opciones if not (o[1] & boxart._TAGS_MALOS)]
        if not buenas:
            continue
        nombre = indice._mejor(buenas, set())
        juego = {"titulo": boxart._titulo_limpio(nombre), "clave": clave, "archivo": nombre,
                 "portada": url_base + urllib.parse.quote(nombre) + ".png"}
        for campo, valores in datos.items():
            juego[campo] = valores.get(clave, "")
        juegos.append(juego)
    juegos.sort(key=lambda j: j["titulo"].casefold())
    return juegos


def _lista(identificativo, nombre_consola):
    """Juegos de una consola. Solo se recuerda si se pudo leer: sin conexión se vuelve a intentar."""
    for sistema in boxart.SISTEMAS.get(identificativo) or [nombre_consola]:
        with _lock:
            if sistema not in _listas:
                indice = boxart._indice_para_ui(sistema)
                if indice:
                    _listas[sistema] = _armar_lista(indice, _datos_de(sistema), boxart._url_sistema(sistema))
            if _listas.get(sistema):
                return sistema, _listas[sistema]
    return None, None


def _clave_genero(genero):
    return re.sub(r"\W", "", genero.casefold())   # "Beat 'em up" y "Beat'em Up" son el mismo


def generos_de(texto):
    """Un juego puede tener varios géneros: "Board /Card, Shogi" -> Board, Card, Shogi."""
    return [g.strip() for g in re.split(r"[,/]", texto or "") if _clave_genero(g)]


def listar(identificativo, nombre_consola, texto="", genero="", pagina=1):
    _, juegos = _lista(identificativo, nombre_consola)
    if juegos is None:
        return {"exito": False, "error": "No se pudo cargar el catálogo de esta consola. Revisá tu conexión."}
    palabras = boxart.analizar_titulo(texto or "")[0].split()
    nombres = {}
    for j in juegos:
        for g in generos_de(j["genero"]):
            nombres.setdefault(_clave_genero(g), g)
    generos = sorted(nombres.values(), key=str.casefold)
    buscado = _clave_genero(genero or "")
    hallados = [j for j in juegos if (not buscado or buscado in map(_clave_genero, generos_de(j["genero"])))
                and all(p in j["clave"] for p in palabras)]
    pagina = max(1, int(pagina or 1))
    corte = hallados[(pagina - 1) * POR_PAGINA:pagina * POR_PAGINA]
    return {"exito": True, "juegos": corte, "total": len(hallados), "generos": generos, "hay_mas": pagina * POR_PAGINA < len(hallados)}


def portada(identificativo, nombre_consola, titulo):
    """Dirección de la carátula de un juego, o '' si no está en el catálogo."""
    _, juegos = _lista(identificativo, nombre_consola)
    clave = boxart.analizar_titulo(titulo or "")[0]
    return next((j["portada"] for j in juegos or [] if j["clave"] == clave), "")


def _articulo(texto):
    """Título normalizado de un artículo, sin aclaraciones como '(videojuego)'."""
    return boxart.analizar_titulo(re.sub(r"\s*\(.*?\)\s*$", "", texto or ""))[0]


def elegir_articulos(resultados, clave):
    """Resultados con exactamente ese título; primero los que aclaran que son el videojuego."""
    hallados = [r["title"] for r in resultados if _articulo(r.get("title")) == clave]
    return sorted(hallados, key=lambda t: not re.search(r"\((video ?juego|video game)", t, re.I))


def resumen_valido(resumen, palabra, idioma):
    """Texto y enlace del resumen, solo si habla de un videojuego y el enlace es de Wikipedia."""
    enlace = ((resumen.get("content_urls") or {}).get("desktop") or {}).get("page", "")
    extracto = (resumen.get("extract") or "").strip()
    tema = f"{resumen.get('description') or ''} {extracto}".lower()
    if resumen.get("type") != "standard" or palabra not in tema or not enlace.startswith(f"https://{idioma}.wikipedia.org/"):
        return None
    if _NO_ES_UN_JUEGO.search(tema[:200]):   # la ficha es de un juego, no de toda su saga
        return None
    return {"texto": extracto, "enlace": enlace, "idioma": idioma}


def _buscar_descripcion(titulo, clave):
    for idioma, palabra, consulta in (("es", "videojuego", "videojuego"), ("en", "video game", "video game")):
        base = f"https://{idioma}.wikipedia.org"
        parametros = urllib.parse.urlencode({"action": "query", "list": "search", "format": "json", "srlimit": 5,
                                             "srsearch": f'"{titulo}" {consulta}'})
        crudo = _pedir(f"{base}/w/api.php?{parametros}")
        for hallado in elegir_articulos((json.loads(crudo).get("query") or {}).get("search") or [], clave) if crudo else []:
            crudo_resumen = _pedir(f"{base}/api/rest_v1/page/summary/{urllib.parse.quote(hallado.replace(' ', '_'), safe='')}")
            descripcion = resumen_valido(json.loads(crudo_resumen), palabra, idioma) if crudo_resumen else None
            if descripcion:
                return descripcion
    return None


def _pedir(url):
    pedido = urllib.request.Request(url, headers={"User-Agent": _AGENTE})
    try:
        with urllib.request.urlopen(pedido, timeout=10) as r:
            return r.read(3 * 1024 * 1024)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _descripcion(titulo, clave):
    if clave not in _descripciones:
        try:
            _descripciones[clave] = _buscar_descripcion(titulo, clave)
        except Exception as e:   # sin red no se recuerda: se vuelve a intentar al reabrir la ficha
            print(f"[CATALOGO] Sin descripción de {titulo}: {e}")
            return None
    return _descripciones[clave]


def ficha(identificativo, nombre_consola, titulo):
    sistema, juegos = _lista(identificativo, nombre_consola)
    if juegos is None:
        return {"exito": False, "error": "No se pudo cargar el catálogo de esta consola. Revisá tu conexión."}
    clave = boxart.analizar_titulo(titulo or "")[0]
    juego = next((j for j in juegos if j["clave"] == clave), None)
    if not juego:
        return {"exito": False, "error": "Ese juego no está en el catálogo."}
    base = f"{boxart.URL_BASE}/{urllib.parse.quote(sistema)}"
    archivo = urllib.parse.quote(juego["archivo"]) + ".png"
    return {"exito": True, "juego": {**juego, "identificativo": identificativo, "consola": nombre_consola,
                                     # Como en Steam, el visor arranca con imágenes del juego; la caja va al final
                                     "imagenes": [{"src": f"{base}/Named_Snaps/{archivo}", "etiqueta": "En juego"},
                                                  {"src": f"{base}/Named_Titles/{archivo}", "etiqueta": "Pantalla de título"},
                                                  {"src": juego["portada"], "etiqueta": "Caja"}],
                                     "descripcion": _descripcion(juego["titulo"], clave)}}


def juego_gratis(entrada):
    """Pasa una entrada de Homebrew Hub al formato de la tienda, o None si sus datos no son confiables."""
    slug, carpeta = entrada.get("slug") or "", entrada.get("basepath") or ""
    if not re.fullmatch(r"[\w.-]+", slug) or not re.fullmatch(r"[\w.-]+", carpeta) or not entrada.get("title"):
        return None
    base = f"{URL_HOMEBREW}/static/{carpeta}/entries/{slug}/"
    imagenes = [base + urllib.parse.quote(s) for s in entrada.get("screenshots") or [] if isinstance(s, str) and ".." not in s]
    itch = next((w for w in entrada.get("website") or [] if isinstance(w, str) and w.startswith("https://")
                 and es_enlace_de_itch(urllib.parse.urlparse(w).hostname)), "")
    return {"titulo": str(entrada["title"])[:120], "desarrollador": str(entrada.get("developer") or "")[:120],
            "plataforma": str(entrada.get("platform") or "")[:10], "fecha": str(entrada.get("date") or "")[:10],
            "descripcion": str(entrada.get("description") or "")[:2000], "generos": [str(t)[:30] for t in entrada.get("tags") or []][:6],
            "licencia": str(entrada.get("license") or "")[:40], "portada": imagenes[0] if imagenes else "", "capturas": imagenes[:6],
            "enlace": PAGINA_HOMEBREW + slug, "itch": itch, "agregado": str(entrada.get("firstadded_date") or "")}


def _pedir_gratis(plataforma, pagina=1):
    parametros = urllib.parse.urlencode({"typetag": "game", "platform": plataforma, "page": int(pagina)})
    datos = json.loads(_pedir(f"{URL_HOMEBREW}/api/search?{parametros}") or b"{}")
    return [j for j in map(juego_gratis, datos.get("entries") or []) if j], int(datos.get("page_total") or 1)


def leer_itch(datos):
    """Convierte una lista de itch.io al formato de la tienda. Solo juegos a $0 con enlace e imagen de itch.io."""
    juegos = []
    for item in noticias.leer_xml(datos).iter("item"):
        enlace, imagen = (item.findtext("link") or "").strip(), (item.findtext("imageurl") or "").strip()
        partes = urllib.parse.urlparse(enlace)
        titulo = html.unescape(item.findtext("plainTitle") or "").strip()
        if not titulo or partes.scheme != "https" or not es_enlace_de_itch(partes.hostname) or item.findtext("price") != "$0.00":
            continue
        if not imagen.startswith("https://img.itch.zone/"):
            imagen = ""
        fecha = noticias._fecha_iso(item.findtext("pubDate")) or ""
        juegos.append({"titulo": titulo[:120], "desarrollador": partes.hostname.split(".")[0][:120], "plataforma": "itch",
                       "fecha": fecha[:10], "descripcion": noticias._texto_plano(item.findtext("description"), 2000),
                       "generos": [], "licencia": "", "portada": imagen, "capturas": [imagen] if imagen else [],
                       "enlace": enlace, "itch": "", "agregado": fecha})
    return juegos


def _pedir_itch(plataforma, pagina=1):
    pedido = (plataforma, int(pagina))
    momento, juegos = _itch.get(pedido, (0.0, []))
    if not juegos or time.time() - momento >= TTL_GRATIS:
        juegos = leer_itch(_pedir(f"{URL_ITCH}{ETIQUETAS_ITCH[plataforma]}.xml?page={int(pagina)}") or b"<rss/>")
        _itch[pedido] = (time.time(), juegos)
    return juegos


def gratis(plataforma, pagina=1):
    """Una página de juegos gratis de una consola o de una etiqueta de itch.io."""
    if plataforma not in PLATAFORMAS_GRATIS and plataforma not in ETIQUETAS_ITCH:
        return {"exito": False, "error": "Consola no válida."}
    try:
        if plataforma in ETIQUETAS_ITCH:
            juegos = _pedir_itch(plataforma, pagina)
            return {"exito": True, "juegos": juegos, "hay_mas": len(juegos) >= JUEGOS_POR_LISTA_ITCH}
        juegos, total = _pedir_gratis(plataforma, pagina)
        return {"exito": True, "juegos": juegos, "hay_mas": int(pagina) < total}
    except Exception as e:
        print(f"[CATALOGO] Sin juegos gratis: {e}")
        return {"exito": False, "error": "No se pudieron cargar los juegos gratis. Revisá tu conexión."}


def gratis_recientes(limite=12):
    """Los últimos agregados de todas las consolas, para la portada. Se guardan una hora."""
    global _gratis
    if _gratis[1] and time.time() - _gratis[0] < TTL_GRATIS:
        return _gratis[1]
    juegos = []
    for plataforma in PLATAFORMAS_GRATIS:
        try:
            juegos += _pedir_gratis(plataforma)[0]
        except Exception as e:
            print(f"[CATALOGO] Sin juegos gratis de {plataforma}: {e}")
    juegos.sort(key=lambda j: j["agregado"], reverse=True)
    if juegos:
        _gratis = (time.time(), juegos[:limite])
    return juegos[:limite]
