"""
ra_client.py - Cliente mínimo de la Web API de RetroAchievements (RA).

Qué hace:
  - Guarda usuario + Web API Key de RA (en session_store, nunca en la base de datos).
  - Encuentra el juego de RA que corresponde a un juego local (por título normalizado,
    reutilizando el normalizador de boxart.py) y recuerda la coincidencia en la BD.
  - Trae la lista de logros del juego con el progreso del usuario.

Qué NO hace: desbloquear logros. Eso lo hace el emulador (RetroArch, DuckStation,
PCSX2, PPSSPP, Dolphin...) con tu sesión de RA iniciada. El launcher solo lee el progreso.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from difflib import get_close_matches

import boxart
import contexto
import db_local
import session_store

API_URL = "https://retroachievements.org/API/"
MEDIA_URL = "https://media.retroachievements.org"
CARPETA_CACHE = os.path.join("cache", "retroachievements")
TTL_LISTA = 7 * 24 * 3600
USER_AGENT = "RetroEmulator/BETA-v1"

# identificativo de la consola (tabla consolas) -> ID de consola en RetroAchievements
CONSOLAS_RA = {
    "genesis": 1, "nomad": 1, "n64": 2, "snes": 3, "gb": 4, "gba": 5, "gbc": 6, "nes": 7,
    "pcengine": 8, "segacd": 9, "sega32x": 10, "sms": 11, "psx": 12, "ngp": 14, "ngpc": 14,
    "gamecube": 16, "jagr": 17, "nds": 18, "wii": 19, "wiiu": 20, "ps2": 21,
    "atari2600": 25, "vb": 28, "sg1000": 33, "saturn": 39, "dreamcast": 40, "psp": 41,
    "cdi": 42, "3do": 43, "colecovision": 44, "intellivision": 45, "vectrex": 46,
    "pcfx": 49, "atari5200": 50, "atari7800": 51, "ws": 53, "wsc": 53, "neogeocd": 56,
    "channelf": 57, "fmtowns": 58, "3ds": 62, "fds": 81,
}

_indices = {}


class ErrorRA(Exception):
    pass


class SinCredenciales(ErrorRA):
    pass


# ----------------------------------------------------------------------------
# Credenciales
# ----------------------------------------------------------------------------

def _nombre_credenciales():
    """Las credenciales son de cada cuenta de la app: no se mezclan al cambiar de usuario."""
    uid = contexto.usuario_id()
    return f"retroachievements_{uid}" if uid else None


def adoptar_credenciales_antiguas(usuario_id):
    """Antes las credenciales eran de todo el equipo: se pasan a la cuenta que entra primero."""
    legado = session_store.cargar("retroachievements")
    if legado:
        nuevo = f"retroachievements_{usuario_id}"
        if not session_store.cargar(nuevo):
            session_store.guardar(nuevo, legado)
        session_store.borrar("retroachievements")


def obtener_credenciales():
    nombre = _nombre_credenciales()
    c = session_store.cargar(nombre) if nombre else None
    if c and c.get("usuario") and c.get("api_key"):
        return c
    return None


def estado_credenciales():
    c = obtener_credenciales()
    return {"configurado": bool(c), "usuario": c["usuario"] if c else ""}


def guardar_credenciales(usuario, api_key):
    """Prueba las credenciales contra RA y, si funcionan, las guarda."""
    usuario, api_key = (usuario or "").strip(), (api_key or "").strip()
    if not usuario or not api_key:
        return {"exito": False, "error": "Completá usuario y Web API Key."}
    try:
        perfil = _pedir("API_GetUserProfile.php",
                        cred={"usuario": usuario, "api_key": api_key}, u=usuario)
    except ErrorRA as e:
        return {"exito": False, "error": str(e)}
    if not isinstance(perfil, dict) or "User" not in perfil:
        return {"exito": False, "error": "No se encontró ese usuario en RetroAchievements."}
    nombre = _nombre_credenciales()
    if not nombre:
        return {"exito": False, "error": "Iniciá sesión para guardar tus credenciales."}
    if not session_store.guardar(nombre, {"usuario": usuario, "api_key": api_key}):
        return {"exito": False, "error": "No se pudieron guardar las credenciales en este equipo."}
    return {"exito": True, "usuario": perfil.get("User", usuario)}


def borrar_credenciales():
    nombre = _nombre_credenciales()
    if nombre:
        session_store.borrar(nombre)
    return {"exito": True}


# ----------------------------------------------------------------------------
# Red
# ----------------------------------------------------------------------------

def _pedir(endpoint, cred=None, **params):
    cred = cred or obtener_credenciales()
    if not cred:
        raise SinCredenciales("Falta conectar tu cuenta de RetroAchievements.")
    params = {"z": cred["usuario"], "y": cred["api_key"], **params}
    url = f"{API_URL}{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ErrorRA("RetroAchievements rechazó las credenciales (revisá usuario y Web API Key).")
        if e.code == 429:
            raise ErrorRA("Demasiadas consultas a RetroAchievements; probá de nuevo en un momento.")
        raise ErrorRA(f"RetroAchievements respondió con el error {e.code}.")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ErrorRA("No se pudo conectar con RetroAchievements.")
    except ValueError:
        raise ErrorRA("Respuesta inesperada de RetroAchievements.")


# ----------------------------------------------------------------------------
# Búsqueda del juego
# ----------------------------------------------------------------------------

def _lista_juegos(consola_ra):
    """Juegos de RA con logros para una consola (cacheado 7 días en disco)."""
    os.makedirs(CARPETA_CACHE, exist_ok=True)
    ruta = os.path.join(CARPETA_CACHE, f"consola_{consola_ra}.json")
    cache = None
    try:
        with open(ruta, encoding="utf-8") as f:
            cache = json.load(f)
        if cache.get("juegos") and time.time() - cache.get("ts", 0) < TTL_LISTA:
            return cache["juegos"]
    except (OSError, ValueError):
        cache = None

    try:
        datos = _pedir("API_GetGameList.php", i=consola_ra, f=1)
    except SinCredenciales:
        raise
    except ErrorRA:
        if cache and cache.get("juegos"):   # mejor una lista vieja que ninguna
            return cache["juegos"]
        raise

    juegos = [{"ID": g["ID"], "Title": g.get("Title", ""), "NumAchievements": g.get("NumAchievements", 0)}
              for g in (datos if isinstance(datos, list) else []) if isinstance(g, dict) and g.get("ID")]
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "juegos": juegos}, f)
    except OSError:
        pass
    return juegos


def _indice(consola_ra):
    if consola_ra not in _indices:
        por_clave = {}
        for g in _lista_juegos(consola_ra):
            titulo = g["Title"]
            if titulo.startswith("~") or "[Subset" in titulo:   # hacks, homebrew y subsets
                continue
            clave, _ = boxart.analizar_titulo(titulo)
            if clave and (clave not in por_clave or g["NumAchievements"] > por_clave[clave]["NumAchievements"]):
                por_clave[clave] = g
        prefijos = {}
        for clave in por_clave:
            prefijos.setdefault(clave[:4], []).append(clave)
        _indices[consola_ra] = (por_clave, prefijos)
    return _indices[consola_ra]


def buscar_juego(identificativo, titulo):
    """Devuelve el juego de RA que corresponde al título local, o None."""
    consola_ra = CONSOLAS_RA.get(identificativo)
    if not consola_ra:
        return None
    por_clave, prefijos = _indice(consola_ra)
    clave, _ = boxart.analizar_titulo(titulo)
    if not clave:
        return None
    if clave in por_clave:
        return por_clave[clave]
    for cercana in get_close_matches(clave, prefijos.get(clave[:4], []), n=3, cutoff=0.9):
        if boxart.firma_numerica(cercana) == boxart.firma_numerica(clave):
            return por_clave[cercana]
    return None


# ----------------------------------------------------------------------------
# Logros
# ----------------------------------------------------------------------------

def obtener_logros(identificativo, consola_id, titulo):
    """Logros del juego con el progreso del usuario.
    Si no se puede, devuelve {"exito": False, "motivo": ...} con motivo en:
    sin_credenciales | consola_no_soportada | sin_logros | error."""
    cred = obtener_credenciales()
    if not cred:
        return {"exito": False, "motivo": "sin_credenciales"}
    if identificativo not in CONSOLAS_RA:
        return {"exito": False, "motivo": "consola_no_soportada"}

    try:
        ra_id = db_local.obtener_ra_juego(consola_id, titulo)
        if not ra_id:
            juego = buscar_juego(identificativo, titulo)
            if not juego:
                return {"exito": False, "motivo": "sin_logros"}
            ra_id = juego["ID"]
            db_local.guardar_ra_juego(consola_id, titulo, ra_id)
        datos = _pedir("API_GetGameInfoAndUserProgress.php", u=cred["usuario"], g=ra_id)
    except SinCredenciales:
        return {"exito": False, "motivo": "sin_credenciales"}
    except ErrorRA as e:
        return {"exito": False, "motivo": "error", "error": str(e)}

    crudos = datos.get("Achievements") if isinstance(datos, dict) else None
    crudos = list(crudos.values()) if isinstance(crudos, dict) else []
    crudos.sort(key=lambda a: (a.get("DisplayOrder", 0), a.get("ID", 0)))

    logros = []
    for a in crudos:
        fecha = a.get("DateEarnedHardcore") or a.get("DateEarned") or ""
        badge = a.get("BadgeName", "")
        logros.append({
            "id": a.get("ID"),
            "titulo": a.get("Title", ""),
            "descripcion": a.get("Description", ""),
            "puntos": a.get("Points", 0) or 0,
            "obtenido": bool(fecha),
            "hardcore": bool(a.get("DateEarnedHardcore")),
            "fecha": fecha,
            "badge_url": f"{MEDIA_URL}/Badge/{badge}{'' if fecha else '_lock'}.png" if badge else "",
        })

    if not logros:
        return {"exito": False, "motivo": "sin_logros"}

    return {
        "exito": True,
        "ra_id": ra_id,
        "titulo": datos.get("Title", titulo),
        "url": f"https://retroachievements.org/game/{ra_id}",
        "total": len(logros),
        "obtenidos": sum(1 for l in logros if l["obtenido"]),
        "puntos_total": sum(l["puntos"] for l in logros),
        "puntos_obtenidos": sum(l["puntos"] for l in logros if l["obtenido"]),
        "logros": logros,
    }
