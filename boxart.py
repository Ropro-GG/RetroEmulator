import base64
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import get_close_matches
from pathlib import Path

CARPETA_ROMS_BASE = "roms"
CARPETA_BOXARTS = os.path.join(CARPETA_ROMS_BASE, "boxarts")
CARPETA_CACHE = os.path.join(CARPETA_BOXARTS, ".cache")

URL_BASE = "https://thumbnails.libretro.com"
TIPO_IMAGEN = "Named_Boxarts"
USER_AGENT = "Mozilla/5.0 (RetroEmulator)"
TTL_INDICE = 14 * 24 * 3600      # listado con datos
TTL_INDICE_VACIO = 7 * 24 * 3600  # sistema sin listado / inexistente
MAX_HILOS = 8

# Carpetas de Libretro por consola (clave = "identificativo" de la tabla consolas).
# Se prueban en orden; las que no existan en el servidor simplemente se ignoran.
SISTEMAS = {
    "odyssey2001": ["Magnavox - Odyssey2"],
    "atari2600": ["Atari - 2600"],
    "intellivision": ["Mattel - Intellivision"],
    "colecovision": ["Coleco - ColecoVision"],
    "vectrex": ["GCE - Vectrex"],
    "atari5200": ["Atari - 5200"],
    "channelf": ["Fairchild - Channel F"],
    "nes": ["Nintendo - Nintendo Entertainment System"],
    "fds": ["Nintendo - Family Computer Disk System", "Nintendo - Famicom Disk System"],
    "sms": ["Sega - Master System - Mark III"],
    "sg1000": ["Sega - SG-1000"],
    "atari7800": ["Atari - 7800"],
    "pcengine": ["NEC - PC Engine - TurboGrafx 16"],
    "neogeo": ["SNK - Neo Geo", "FBNeo - Arcade Games"],
    "segacd": ["Sega - Mega-CD - Sega CD"],
    "cdi": ["Philips - CD-i"],
    "neogeocd": ["SNK - Neo Geo CD"],
    "snes": ["Nintendo - Super Nintendo Entertainment System"],
    "genesis": ["Sega - Mega Drive - Genesis"],
    "sega32x": ["Sega - 32X"],
    "jagr": ["Atari - Jaguar"],
    "3do": ["The 3DO Company - 3DO"],
    "pcfx": ["NEC - PC-FX"],
    "cd32": ["Commodore - CD32"],
    "psx": ["Sony - PlayStation"],
    "n64": ["Nintendo - Nintendo 64"],
    "saturn": ["Sega - Saturn"],
    "dreamcast": ["Sega - Dreamcast"],
    "ps2": ["Sony - PlayStation 2"],
    "gamecube": ["Nintendo - GameCube"],
    "xbox": ["Microsoft - Xbox"],
    "ps3": ["Sony - PlayStation 3"],
    "xbox360": ["Microsoft - Xbox 360"],
    "wii": ["Nintendo - Wii"],
    "wiiu": ["Nintendo - Wii U"],
    "gb": ["Nintendo - Game Boy"],
    "gbc": ["Nintendo - Game Boy Color"],
    "gba": ["Nintendo - Game Boy Advance"],
    "vb": ["Nintendo - Virtual Boy"],
    "gamecom": ["Tiger - Game.com"],
    "nomad": ["Sega - Mega Drive - Genesis"],
    "ngp": ["SNK - Neo Geo Pocket"],
    "ngpc": ["SNK - Neo Geo Pocket Color"],
    "ws": ["Bandai - WonderSwan"],
    "wsc": ["Bandai - WonderSwan Color"],
    "nds": ["Nintendo - Nintendo DS"],
    "3ds": ["Nintendo - Nintendo 3DS"],
    "psp": ["Sony - PlayStation Portable"],
    "psvita": ["Sony - PlayStation Vita"],
}

# Preferencia de región cuando el nombre de la ROM no la indica
PREFERENCIA_REGION = ["world", "usa", "europe", "japan"]
_TAGS_MALOS = {"beta", "proto", "prototype", "demo", "sample", "unl", "pirate", "hack", "aftermarket", "kiosk"}

_RE_DISCO = re.compile(r'\s*[\(\[\{]\s*(?:disc|disk|cd)\s*\w+[^\)\]\}]*[\)\]\}]', re.IGNORECASE)
_RE_NUMERO = re.compile(r'^(?:\d+|[ivx]+)$')
_RE_CARACTERES_LIBRETRO = re.compile(r'[&*/:`<>?\\|]')

_indices = {}
_lock_indices = threading.RLock()
_red_caida = threading.Event()


# ----------------------------------------------------------------------------
# Utilidades de nombres
# ----------------------------------------------------------------------------

def nombre_libretro(nombre):
    """Libretro reemplaza estos caracteres por '_' en los nombres de sus archivos."""
    return _RE_CARACTERES_LIBRETRO.sub('_', nombre).strip()


def _archivo_seguro(nombre):
    """Nombre válido en Windows/Linux/Mac."""
    limpio = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', nombre).strip(' .')
    return limpio[:150] or "sin_nombre"


def _analizar(nombre):
    """Devuelve (clave_de_titulo, set_de_etiquetas) de un nombre de ROM o de carátula.

    La clave ignora etiquetas, acentos, mayúsculas, puntuación y el ", The" final.
    Las etiquetas son lo que va entre paréntesis/corchetes: región, disco, revisión...
    """
    tags = set()
    for grupo in re.findall(r'[\(\[]([^\)\]]*)[\)\]]', nombre):
        for t in grupo.split(','):
            t = t.strip().lower()
            if t:
                tags.add(t)

    base = re.sub(r'[\(\[][^\)\]]*[\)\]]', ' ', nombre)
    base = unicodedata.normalize("NFKD", base)
    base = "".join(c for c in base if not unicodedata.combining(c)).lower()
    base = base.replace("&", " and ").replace("_", " ")
    base = re.sub(r'^(.+?),\s*(the|a|an)(?=\s*(?:-|:|$))(.*)$', r'\2 \1\3', base.strip())
    base = base.replace("'", "").replace("\u2019", "")
    base = re.sub(r'[^a-z0-9]+', ' ', base).strip()
    return base, tags


def _firma_numerica(clave):
    """Números y romanos del título: evita confundir 'VII' con 'VIII' o '2' con '3'."""
    return frozenset(t for t in clave.split() if _RE_NUMERO.match(t))


def _puntuar(tags_rom, tags_cand):
    puntos = 10 * len(tags_rom & tags_cand)
    for i, region in enumerate(PREFERENCIA_REGION):
        if region in tags_cand:
            puntos += len(PREFERENCIA_REGION) - i
            break
    if tags_cand & _TAGS_MALOS:
        puntos -= 5
    return puntos


# ----------------------------------------------------------------------------
# Red
# ----------------------------------------------------------------------------

def _http_get(url, timeout=15, reintentos=3):
    """Devuelve los bytes, o None si el recurso no existe (404/403/410).
    Reintenta con espera creciente ante errores temporales; si se agotan, lanza el error."""
    ultimo = None
    for intento in range(reintentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                return None
            ultimo = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            ultimo = e
        if intento < reintentos - 1:
            time.sleep(0.6 * (2 ** intento))
    raise ultimo


def _es_imagen(datos):
    return bool(datos) and len(datos) > 100 and (datos[:8] == b"\x89PNG\r\n\x1a\n" or datos[:3] == b"\xff\xd8\xff")


def _url_sistema(sistema):
    return f"{URL_BASE}/{urllib.parse.quote(sistema)}/{TIPO_IMAGEN}/"


def _descargar_listado(sistema):
    """Lista de archivos .png disponibles para un sistema, o None si no hay listado."""
    datos = _http_get(_url_sistema(sistema), timeout=30, reintentos=2)
    if not datos:
        return None
    texto = datos.decode("utf-8", errors="ignore")
    nombres = set()
    for href in re.findall(r'href="([^"]+?\.png)"', texto, flags=re.IGNORECASE):
        nombre = urllib.parse.unquote(html.unescape(href)).rsplit("/", 1)[-1]
        if nombre:
            nombres.add(nombre)
    return sorted(nombres) or None


# ----------------------------------------------------------------------------
# Índice local (listado cacheado + búsqueda)
# ----------------------------------------------------------------------------

class _Indice:
    def __init__(self, sistema, archivos):
        self.sistema = sistema
        self.por_nombre = {}
        self.por_minusculas = {}
        self.por_clave = {}
        self.por_prefijo = {}
        for archivo in archivos:
            nombre = archivo[:-4]  # sin ".png"
            self.por_nombre[nombre] = archivo
            self.por_minusculas.setdefault(nombre.lower(), nombre)
            clave, tags = _analizar(nombre)
            if clave:
                self.por_clave.setdefault(clave, []).append((nombre, tags))
        for clave in self.por_clave:
            self.por_prefijo.setdefault(clave[:4], []).append(clave)

    @staticmethod
    def _mejor(opciones, tags_rom):
        return min(opciones, key=lambda o: (-_puntuar(tags_rom, o[1]), len(o[0]), o[0]))[0]

    def buscar(self, candidatos, tags_rom):
        """Devuelve el nombre (sin .png) de la mejor carátula, o None."""
        for c in candidatos:                      # 1) exacto
            n = nombre_libretro(c)
            if n in self.por_nombre:
                return n
        for c in candidatos:                      # 2) sin mayúsculas
            n = self.por_minusculas.get(nombre_libretro(c).lower())
            if n:
                return n
        for c in candidatos:                      # 3) mismo título base
            clave, _ = _analizar(c)
            if clave and clave in self.por_clave:
                return self._mejor(self.por_clave[clave], tags_rom)
        for c in candidatos:                      # 4) aproximado y seguro
            clave, _ = _analizar(c)
            if not clave:
                continue
            posibles = self.por_prefijo.get(clave[:4], [])
            for cercana in get_close_matches(clave, posibles, n=3, cutoff=0.88):
                if _firma_numerica(cercana) == _firma_numerica(clave):
                    return self._mejor(self.por_clave[cercana], tags_rom)
        return None


def _leer_json(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _guardar_json(ruta, datos):
    try:
        tmp = ruta + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f)
        os.replace(tmp, ruta)
    except OSError as e:
        print(f"[BOXART] No se pudo guardar caché: {e}")


def _cargar_indice(sistema):
    os.makedirs(CARPETA_CACHE, exist_ok=True)
    ruta = os.path.join(CARPETA_CACHE, _archivo_seguro(sistema) + ".json")
    cache = _leer_json(ruta)
    ahora = time.time()

    if cache:
        ttl = TTL_INDICE if cache.get("archivos") else TTL_INDICE_VACIO
        if ahora - cache.get("ts", 0) < ttl:
            return _Indice(sistema, cache["archivos"]) if cache.get("archivos") else None

    try:
        archivos = _descargar_listado(sistema)
    except Exception as e:
        print(f"[BOXART] Sin conexión para '{sistema}': {e}")
        _red_caida.set()
        if cache and cache.get("archivos"):   # mejor un listado viejo que ninguno
            return _Indice(sistema, cache["archivos"])
        return None

    _guardar_json(ruta, {"ts": ahora, "archivos": archivos or []})
    if archivos:
        print(f"[BOXART] Listado de '{sistema}': {len(archivos)} carátulas")
        return _Indice(sistema, archivos)
    return None


def obtener_indice(sistema):
    with _lock_indices:
        if sistema not in _indices:
            _indices[sistema] = _cargar_indice(sistema)
        return _indices[sistema]


# ----------------------------------------------------------------------------
# Descarga
# ----------------------------------------------------------------------------

def _bajar(ident, sistema, nombre):
    """Descarga una carátula a roms/boxarts/ (o reutiliza la que ya está). '' si falla."""
    destino = os.path.join(CARPETA_BOXARTS, f"{ident}__{_archivo_seguro(nombre)}.png")
    if os.path.isfile(destino) and os.path.getsize(destino) > 100:
        return destino

    url = f"{_url_sistema(sistema)}{urllib.parse.quote(nombre)}.png"
    datos = _http_get(url)
    if not _es_imagen(datos):
        return ""

    tmp = f"{destino}.{threading.get_ident()}.part"
    with open(tmp, "wb") as f:
        f.write(datos)
    os.replace(tmp, destino)
    return destino


def _candidatos(trabajo):
    nombre = trabajo["nombre_rom"]
    crudos = [nombre, nombre.replace("_", " "), _RE_DISCO.sub("", nombre).strip()]
    crudos.extend(trabajo.get("alternos") or [])
    crudos.append(trabajo.get("titulo", ""))
    vistos, lista = set(), []
    for c in crudos:
        c = " ".join((c or "").split())
        if c and c.lower() not in vistos:
            vistos.add(c.lower())
            lista.append(c)
    return lista


def resolver_portada(trabajo):
    """Busca y descarga la carátula de un juego. Devuelve la ruta local o ''."""
    if _red_caida.is_set():
        return ""
    ident = trabajo["identificativo"]
    candidatos = _candidatos(trabajo)
    tags_rom = _analizar(candidatos[0])[1]

    for sistema in SISTEMAS.get(ident) or [trabajo["consola"]]:
        indice = obtener_indice(sistema)
        if indice:
            hallado = indice.buscar(candidatos, tags_rom)
            if hallado:
                ruta = _bajar(ident, sistema, hallado)
                if ruta:
                    return ruta
        elif not _red_caida.is_set():
            # El servidor no dio listado: se intenta por nombre exacto
            for c in candidatos:
                ruta = _bajar(ident, sistema, nombre_libretro(c))
                if ruta:
                    return ruta
    return ""


def _resolver_seguro(trabajo):
    try:
        return resolver_portada(trabajo)
    except Exception as e:
        print(f"[BOXART] Error con '{trabajo.get('nombre_rom')}': {e}")
        return ""


def descargar_lote(trabajos, al_terminar=None, al_avanzar=None):
    """Procesa muchos juegos en paralelo.

    trabajos: lista de dicts con: identificativo, consola, nombre_rom, titulo, ruta_rom,
              y opcionalmente 'alternos' (otros nombres para buscar).
    al_terminar(ruta_rom, portada_path): se llama por cada carátula conseguida.
    al_avanzar(hechos, exitosos): se llama tras cada juego procesado.
    Devuelve la cantidad de carátulas conseguidas.
    """
    os.makedirs(CARPETA_CACHE, exist_ok=True)   # crea roms/boxarts y su caché
    if not trabajos:
        return 0

    _red_caida.clear()
    with _lock_indices:
        for k in [k for k, v in _indices.items() if v is None]:
            del _indices[k]

    # Se cargan primero los listados principales (uno por consola), antes de paralelizar
    for t in trabajos:
        obtener_indice((SISTEMAS.get(t["identificativo"]) or [t["consola"]])[0])

    hechos = exitosos = 0
    with ThreadPoolExecutor(max_workers=MAX_HILOS) as pool:
        futuros = {pool.submit(_resolver_seguro, t): t for t in trabajos}
        for fut in as_completed(futuros):
            t = futuros[fut]
            ruta = fut.result()
            hechos += 1
            if ruta:
                exitosos += 1
                if al_terminar:
                    al_terminar(t["ruta_rom"], ruta)
            if al_avanzar:
                al_avanzar(hechos, exitosos)
    print(f"[BOXART] Carátulas conseguidas: {exitosos}/{hechos}")
    return exitosos


# ----------------------------------------------------------------------------
# Puente con la interfaz
# ----------------------------------------------------------------------------

def ruta_a_uri(ruta):
    """file:// absoluto de una carátula local ('' si no existe)."""
    if not ruta:
        return ""
    ruta_abs = os.path.abspath(ruta)
    return Path(ruta_abs).as_uri() if os.path.isfile(ruta_abs) else ""


def leer_como_data_uri(ruta):
    """Plan B para la UI: la imagen embebida en base64 (solo archivos dentro de roms/boxarts)."""
    try:
        ruta_abs = os.path.abspath(ruta)
        base = os.path.abspath(CARPETA_BOXARTS)
        if os.path.commonpath([ruta_abs, base]) != base or not os.path.isfile(ruta_abs):
            return ""
        with open(ruta_abs, "rb") as f:
            datos = f.read()
        mime = "image/jpeg" if datos[:3] == b"\xff\xd8\xff" else "image/png"
        return f"data:{mime};base64," + base64.b64encode(datos).decode("ascii")
    except (ValueError, OSError):
        return ""


# API pública para otros módulos (ra_client)
analizar_titulo = _analizar
firma_numerica = _firma_numerica
