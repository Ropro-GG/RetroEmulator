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
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

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
# shortcut: se guarda solo mientras la app está abierta; pasarlo a disco si al reabrirla siguen llegando avisos 429
_respuestas = {}      # pedido -> (momento, respuesta)
_pausa_hasta = {}     # sitio -> momento en que se le puede volver a pedir


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
    """Año, género, desarrollador y editor. Si no se pueden bajar, el catálogo sigue funcionando sin ellos.
    Los cuatro archivos (y el completo de PS1/PS2) se bajan a la vez."""
    with ThreadPoolExecutor(max_workers=5) as hilos:
        completos = hilos.submit(_datos_completos, sistema) if sistema in DATS_COMPLETOS else None
        por_campo = dict(zip(_CAMPOS.values(), hilos.map(lambda campo: _dato(sistema, campo), _CAMPOS)))
    if completos:
        for campo, valores in completos.result().items():
            for clave, valor in valores.items():
                por_campo[_CAMPOS[campo]].setdefault(clave, valor)
    return por_campo


def _dato(sistema, campo):
    """Un archivo de libretro-database (genre, developer...), guardado 14 días."""
    ruta = os.path.join(boxart.CARPETA_CACHE, "datos_" + boxart._archivo_seguro(f"{sistema}_{campo}") + ".json")
    if os.path.isfile(ruta) and time.time() - os.path.getmtime(ruta) < TTL_DATOS:
        datos = boxart._leer_json(ruta)
        if datos is not None:
            return datos
    try:
        crudo = boxart._http_get(f"{URL_DATOS}/{campo}/{urllib.parse.quote(sistema)}.dat", timeout=30, reintentos=2)
        datos = leer_dat(crudo.decode("utf-8", errors="ignore"), campo) if crudo else {}
        os.makedirs(boxart.CARPETA_CACHE, exist_ok=True)
        boxart._guardar_json(ruta, datos)
        return datos
    except Exception as e:
        print(f"[CATALOGO] Sin datos de {campo} para {sistema}: {e}")
        return {}


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
        juego["genero"] = traducir_generos(juego["genero"])
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
    """Un juego puede tener varios géneros: "Board /Card, Shogi" -> Board, Card, Shogi. "N/A" es que no hay dato."""
    return [g.strip() for g in re.split(r"[,/&]", (texto or "").replace("N/A", "")) if _clave_genero(g)]


# Todos los géneros de libretro-database al 2026-11-11. Uno nuevo se muestra en inglés hasta sumarlo aquí.
_GENEROS_ES = {
    "Action": "Acción", "Sports": "Deportes", "Platform": "Plataformas", "Adventure": "Aventura", "Role-playing (RPG)": "Rol (RPG)",
    "Racing": "Carreras", "Strategy": "Estrategia", "Puzzle": "Puzle", "Simulation": "Simulación", "Shooter": "Disparos",
    "Board": "Juego de mesa", "Fighting": "Lucha", "Shoot'em Up": "Shoot 'em up", "Gambling": "Apuestas", "Beat'em Up": "Beat 'em up",
    "Educational": "Educativo", "Compilation": "Recopilación", "Miscellaneous": "Varios", "Various": "Varios", "Quiz": "Preguntas",
    "Music": "Música", "Mini Games": "Minijuegos", "Hunting and Fishing": "Caza y pesca", "Card": "Cartas", "Mahjong": "Mahjong",
    "Pinball": "Pinball", "Dancing": "Baile", "Sports with Animals": "Deportes con animales", "Gun": "Pistola de luz",
    "Lightgun Shooter": "Pistola de luz", "Basketball": "Básquet", "Shogi": "Shogi", "Casual Game": "Casual", "Data": "Datos",
    "Football": "Fútbol", "Adult": "Adultos", "Tennis": "Tenis", "Pictures": "Imágenes", "Picture": "Imágenes", "Wrestling": "Lucha libre",
    "Boxing": "Boxeo", "Survival Horror": "Survival horror", "Interactive Comic": "Cómic interactivo", "Party": "Fiesta", "Chess": "Ajedrez",
    "Breakout": "Rompeladrillos", "Interactive Movie": "Película interactiva", "Demo": "Demo", "Constructing": "Construcción",
    "Building": "Construcción", "Colouring Book": "Para colorear", "Colouring Game": "Para colorear", "Thinking": "Ingenio",
    "Sound Novel": "Novela sonora", "Visual Novel": "Novela visual", "Sing": "Karaoke", "Rhythm": "Ritmo", "Dating": "Citas",
    "Action role-playing": "Rol de acción", "hack and slash": "Hack and slash", "Flight Simulator": "Simulador de vuelo",
    "Cooking": "Cocina", "Breeding": "Crianza", "Tetris": "Tetris", "Videos": "Videos", "Video": "Videos", "Go": "Go",
    "Arcade": "Arcade", "Browser": "Navegador", "Email": "Correo", "PDA": "Agenda", "Utility": "Utilidad", "Tarot": "Tarot",
}
_GENEROS_ES = {_clave_genero(en): es for en, es in _GENEROS_ES.items()}


def traducir_generos(texto):
    """"Board /Card" -> "Juego de mesa, Cartas", sin repetir los que significan lo mismo."""
    return ", ".join(dict.fromkeys(_GENEROS_ES.get(_clave_genero(g), g) for g in generos_de(texto)))


def listar(identificativo, nombre_consola, texto="", genero="", pagina=1):
    _, juegos = _lista(identificativo, nombre_consola)
    if juegos is None:
        return {"exito": False, "error": "No se pudo cargar el catálogo de esta consola. Revisá tu conexión."}
    palabras = boxart.analizar_titulo(texto or "")[0].split()
    nombres = {}
    for j in juegos:
        for g in generos_de(j["genero"]):
            nombres.setdefault(_clave_genero(g), g)
    generos = sorted(nombres.values(), key=lambda g: unicodedata.normalize("NFD", g.casefold()))   # "Básquet" va antes que "Boxeo"
    buscado = _clave_genero(genero or "")
    hallados = [j for j in juegos if (not buscado or buscado in map(_clave_genero, generos_de(j["genero"])))
                and all(p in j["clave"] for p in palabras)]
    pagina = max(1, int(pagina or 1))
    corte = hallados[(pagina - 1) * POR_PAGINA:pagina * POR_PAGINA]
    return {"exito": True, "juegos": corte, "total": len(hallados), "generos": generos, "hay_mas": pagina * POR_PAGINA < len(hallados)}


def portada(identificativo, nombre_consola, titulo):
    """Dirección de la carátula de un juego, o '' si no está en el catálogo.
    Usa solo el listado de carátulas: armar la lista completa baja también año, género y editor, y tarda mucho más."""
    clave = boxart.analizar_titulo(titulo or "")[0]
    for sistema in boxart.SISTEMAS.get(identificativo) or [nombre_consola]:
        indice = boxart._indice_para_ui(sistema)
        buenas = [o for o in (indice.por_clave.get(clave) or []) if not (o[1] & boxart._TAGS_MALOS)] if indice else []
        if buenas:   # la misma elección que _armar_lista
            return boxart._url_sistema(sistema) + urllib.parse.quote(indice._mejor(buenas, set())) + ".png"
    return ""


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


class SitioOcupado(Exception):
    """El sitio pidió esperar (HTTP 429) y todavía no hay una respuesta guardada para mostrar."""


def _espera(retry_after):
    try:
        return min(3600, max(60, int(retry_after)))
    except (TypeError, ValueError):
        return 600   # sin indicación, diez minutos


def _con_cache(sitio, pedido, pedir):
    """Cada pedido se repite como mucho una vez por hora. Si el sitio responde 429, se lo deja tranquilo
    el tiempo que pida y mientras tanto se muestra la última respuesta, aunque sea vieja."""
    momento, guardada = _respuestas.get(pedido, (0.0, None))
    if guardada is not None and time.time() - momento < TTL_GRATIS:
        return guardada
    if time.time() < _pausa_hasta.get(sitio, 0):
        if guardada is not None:
            return guardada
        raise SitioOcupado(sitio)
    try:
        respuesta = pedir()
    except urllib.error.HTTPError as e:
        if e.code != 429:
            raise
        _pausa_hasta[sitio] = time.time() + _espera(e.headers.get("Retry-After") if e.headers else None)
        print(f"[CATALOGO] {sitio} pidió esperar: se le vuelve a consultar en unos minutos.")
        if guardada is not None:
            return guardada
        raise SitioOcupado(sitio)
    _respuestas[pedido] = (time.time(), respuesta)
    return respuesta


def _pedir_gratis(plataforma, pagina=1):
    parametros = urllib.parse.urlencode({"typetag": "game", "platform": plataforma, "page": int(pagina)})
    datos = _con_cache("Homebrew Hub", ("hh", plataforma, int(pagina)),
                       lambda: json.loads(_pedir(f"{URL_HOMEBREW}/api/search?{parametros}") or b"{}"))
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
    url = f"{URL_ITCH}{ETIQUETAS_ITCH[plataforma]}.xml?page={int(pagina)}"
    return _con_cache("itch.io", ("itch", plataforma, int(pagina)), lambda: leer_itch(_pedir(url) or b"<rss/>"))


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
    except SitioOcupado as e:
        return {"exito": False, "error": f"{e} pidió esperar unos minutos antes de volver a consultarlo. Probá más tarde."}
    except Exception as e:
        print(f"[CATALOGO] Sin juegos gratis: {e}")
        return {"exito": False, "error": "No se pudieron cargar los juegos gratis. Revisá tu conexión."}


def gratis_recientes(limite=12):
    """Los últimos agregados de todas las consolas, para la portada. Usa las mismas respuestas guardadas que las listas."""
    def de(plataforma):
        try:
            return _pedir_gratis(plataforma)[0]
        except SitioOcupado:
            return []   # pidió esperar: la pausa evita insistir
        except Exception as e:
            print(f"[CATALOGO] Sin juegos gratis de {plataforma}: {e}")
            return []

    with ThreadPoolExecutor(max_workers=len(PLATAFORMAS_GRATIS)) as hilos:   # cada consulta tarda 1-2 s: van a la vez
        juegos = [j for lista in hilos.map(de, PLATAFORMAS_GRATIS) for j in lista]
    juegos.sort(key=lambda j: j["agregado"], reverse=True)
    return juegos[:limite]
