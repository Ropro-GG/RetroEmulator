"""
gifs.py - Buscador de GIFs con la API de KLIPY.

Cómo funciona:
  1. Escribís una búsqueda en el chat; el launcher le pregunta a KLIPY (desde Python, con tu clave).
  2. KLIPY responde con una lista; cada resultado trae las direcciones de internet de su imagen
     en varios tamaños y formatos.
  3. Al elegir un GIF, el mensaje guarda SOLO la dirección de la imagen (nunca tu clave).
     Quien lo recibe la carga directamente desde el servidor de KLIPY.

La clave va en el archivo .env:   KLIPY_API_KEY=tu_clave
Por seguridad solo se aceptan direcciones https de klipy.com / klipy.co.
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # python-dotenv no instalado: se usa lo que ya haya en el entorno
    pass

URL_BASE = "https://api.klipy.com/api/v1"
HOSTS_PERMITIDOS = ("klipy.com", "klipy.co")
POR_PAGINA = 24
TTL_CACHE = 300          # los mismos resultados se reutilizan 5 minutos (menos consultas a KLIPY)
USER_AGENT = "RetroEmulator/BETA-v1"

_cache = {}              # (consulta, pagina) -> (momento, resultado)


# Error con un mensaje listo para mostrar.
class ErrorGifs(Exception):
    pass


# Clave de KLIPY leída del .env.
def _clave():
    return (os.getenv("KLIPY_API_KEY") or "").strip()


# Indica si hay una clave configurada.
def configurado():
    return bool(_clave())


def url_permitida(url):
    """Solo https y solo servidores de KLIPY (evita que un mensaje apunte a cualquier sitio)."""
    if not isinstance(url, str) or not url or len(url) > 1000:
        return False
    # Sin espacios, saltos de línea, caracteres de control ni símbolos que no van en una dirección
    # (el analizador de URL de Python descarta en silencio los saltos de línea, por eso se revisa antes)
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 or c in '<>"\'`\\' for c in url):
        return False
    try:
        partes = urllib.parse.urlparse(url)
        puerto = partes.port
    except ValueError:
        return False
    host = (partes.hostname or "").lower()
    return (partes.scheme == "https" and bool(host)
            and partes.username is None and partes.password is None and puerto in (None, 443)
            and any(host == h or host.endswith("." + h) for h in HOSTS_PERMITIDOS))


def _url_de(archivos, tamanos, formatos):
    """Primera dirección válida entre los tamaños y formatos indicados."""
    for tamano in tamanos:
        for formato in formatos:
            candidato = (archivos.get(tamano) or {}).get(formato)
            url = candidato.get("url") if isinstance(candidato, dict) else None
            if url and url_permitida(url):
                return url
    for formato in formatos:   # por si la respuesta no separa por tamaños
        candidato = archivos.get(formato)
        url = candidato.get("url") if isinstance(candidato, dict) else None
        if url and url_permitida(url):
            return url
    return ""


# Reduce un resultado de KLIPY a lo que usa la app; descarta los no válidos.
def _normalizar(item):
    if not isinstance(item, dict):
        return None
    archivos = item.get("file") or item.get("files") or {}
    if not isinstance(archivos, dict):
        return None
    url = _url_de(archivos, ("md", "hd", "sm"), ("gif", "webp"))      # la que se envía al chat
    if not url:
        return None
    return {
        "id": str(item.get("id") or item.get("slug") or url),
        "titulo": item.get("title") or "GIF",
        "miniatura": _url_de(archivos, ("xs", "sm", "md"), ("jpg", "webp", "gif")) or url,
        "vista": _url_de(archivos, ("sm", "xs", "md"), ("gif", "webp")) or url,   # animada, liviana
        "url": url,
    }


# Hace la consulta a KLIPY y devuelve el JSON.
def _pedir(consulta, pagina, customer_id=None):
    clave = _clave()
    tipo = "search" if consulta else "trending"
    parametros = {"per_page": POR_PAGINA, "page": pagina}
    if consulta:
        parametros["q"] = consulta
    if customer_id:
        parametros["customer_id"] = customer_id
    url = f"{URL_BASE}/{urllib.parse.quote(clave, safe='')}/gifs/{tipo}?{urllib.parse.urlencode(parametros)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def buscar(consulta, pagina=1, usuario_id=""):
    """Devuelve {"gifs": [...], "hay_mas": bool}. Sin consulta devuelve los GIFs del momento (trending)."""
    if not configurado():
        raise ErrorGifs("Falta la clave de KLIPY: agregá  KLIPY_API_KEY=tu_clave  al archivo .env y reiniciá el launcher.")
    consulta = (consulta or "").strip()[:80]
    pagina = max(1, int(pagina or 1))

    guardado = _cache.get((consulta, pagina))
    if guardado and time.time() - guardado[0] < TTL_CACHE:
        return guardado[1]

    try:
        try:
            datos = _pedir(consulta, pagina)
        except urllib.error.HTTPError as e:
            cuerpo = ""
            try:
                cuerpo = e.read().decode("utf-8", "ignore").lower()
            except Exception:
                pass
            if e.code in (400, 422) and "customer" in cuerpo and usuario_id:
                # Si KLIPY exige un identificador de usuario se manda uno anónimo (nunca el real)
                anonimo = hashlib.sha256(("retroemulator:" + usuario_id).encode()).hexdigest()[:32]
                datos = _pedir(consulta, pagina, customer_id=anonimo)
            else:
                raise
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ErrorGifs("KLIPY rechazó la clave. Revisá KLIPY_API_KEY en el archivo .env.")
        if e.code == 429:
            raise ErrorGifs("Demasiadas búsquedas seguidas en KLIPY. Esperá un momento.")
        raise ErrorGifs(f"KLIPY respondió con el error {e.code}.")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ErrorGifs("No se pudo conectar con KLIPY. Revisá tu conexión a internet.")
    except ValueError:
        raise ErrorGifs("Respuesta inesperada de KLIPY.")

    if isinstance(datos, dict) and datos.get("result") is False:
        raise ErrorGifs(str(datos.get("message") or datos.get("error") or "KLIPY no pudo atender la búsqueda."))

    cuerpo = datos.get("data", datos) if isinstance(datos, dict) else datos
    if isinstance(cuerpo, dict):
        crudos, hay_mas = cuerpo.get("data", []), bool(cuerpo.get("has_next"))
    else:
        crudos, hay_mas = (cuerpo or []), len(cuerpo or []) >= POR_PAGINA
    gifs = [g for g in (_normalizar(i) for i in (crudos if isinstance(crudos, list) else [])) if g]

    resultado = {"gifs": gifs, "hay_mas": hay_mas}
    _cache[(consulta, pagina)] = (time.time(), resultado)
    if len(_cache) > 200:   # no crecer sin límite
        _cache.pop(next(iter(_cache)))
    return resultado
