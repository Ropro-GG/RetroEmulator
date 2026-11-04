"""
noticias.py - Titulares de sitios de gaming retro, leídos de sus feeds RSS o Atom.

Lo que llega de un feed no es de confianza: se quita el HTML y solo se aceptan enlaces https del mismo sitio.
De cada nota se muestra el título y un resumen corto, con enlace al original.
"""
import html
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

FUENTES = (
    ("RetroRGB", "https://www.retrorgb.com/feed/"),
    ("Libretro", "https://www.libretro.com/index.php/feed/"),
    ("Hackaday", "https://hackaday.com/tag/retrocomputing/feed/"),
)
# En espera: desde la red pública actual no se pudieron probar. Para activar uno, comprobarlo y pasarlo a FUENTES.
FUENTES_EN_ESPERA = (
    ("RetroManiac", "https://retromaniac.es/feed/"),
    ("VidaExtra Retro", "https://www.vidaextra.com/tag/retro/rss2.xml"),
    ("Time Extension", "https://www.timeextension.com/feeds/latest"),
    ("Retro Dodo", "https://retrododo.com/feed/"),
    ("Retro Gamer", "https://www.retrogamer.net/feed/"),
    ("Racketboy", "https://www.racketboy.com/feed"),
    ("Hardcore Gaming 101", "https://hardcoregaming101.net/feed/"),
    ("RetroPie", "https://retropie.org.uk/feed/"),
)


def _sin_www(host):
    return (host or "").removeprefix("www.")


# Cada sitio puede enlazar sus notas con www o sin él
HOSTS = {h for _, url in FUENTES for h in (_sin_www(urlparse(url).hostname), "www." + _sin_www(urlparse(url).hostname))}
_ATOM = "{http://www.w3.org/2005/Atom}"
_MEDIA = "{http://search.yahoo.com/mrss/}"
_CONTENIDO = "{http://purl.org/rss/1.0/modules/content/}encoded"
_MAX_BYTES = 2 * 1024 * 1024
_MAX_POR_FUENTE = 15
_MAX_TOTAL = 40
_LARGO_RESUMEN = 220
_VIGENCIA_S = 30 * 60
_ESPERA_FORZADA_S = 60   # "Actualizar" no puede insistirle a los sitios más que esto


def _texto_plano(contenido, largo=None):
    """Quita el HTML, incluso el que venía escapado dentro del feed."""
    texto = html.unescape(contenido or "")
    texto = re.sub(r"<(script|style)\b.*?</\1\s*>", " ", texto, flags=re.I | re.S)
    texto = html.unescape(re.sub(r"<[^>]*>", " ", texto))
    texto = re.sub(r"\s+", " ", texto).strip()
    if largo and len(texto) > largo:
        texto = texto[:largo].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"
    return texto


def _fecha_iso(texto):
    """Fecha en formato ISO y UTC, o None si no se entiende."""
    texto = (texto or "").strip()
    try:
        fecha = parsedate_to_datetime(texto)
    except (TypeError, ValueError):
        try:
            fecha = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        except ValueError:
            return None
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    return fecha.astimezone(timezone.utc).isoformat()


def _enlace_atom(entrada):
    for enlace in entrada.findall(_ATOM + "link"):
        if enlace.get("rel", "alternate") == "alternate":
            return enlace.get("href")
    return None


def _imagen_valida(url):
    """Solo https, sin avatares de autor ni emojis."""
    url = html.unescape(url or "").strip()
    if not url.startswith("https://") or "gravatar.com" in url or "/smilies/" in url:
        return ""
    return re.sub(r"-\d+x\d+(\.\w+)$", r"\1", url)   # WordPress publica miniaturas: se pide la imagen completa


def _imagen_de(item, *textos):
    """Una sola imagen por nota: la que declara el feed o, si no, la primera del texto."""
    candidatas = [e.get("url") for e in item.findall(_MEDIA + "thumbnail")]
    candidatas += [e.get("url") for e in item.findall(_MEDIA + "content") if (e.get("medium") or e.get("type", "")).startswith("image")]
    candidatas += [e.get("url") for e in item.findall("enclosure") if e.get("type", "").startswith("image/")]
    candidatas += [e.get("href") for e in item.findall(_ATOM + "link") if e.get("rel") == "enclosure" and e.get("type", "").startswith("image/")]
    for texto in textos:
        candidatas += re.findall(r"""<img\b[^>]*?\bsrc=["']([^"']+)""", html.unescape(texto or ""), flags=re.I)
    return next(filter(None, map(_imagen_valida, candidatas)), "")


def leer_feed(datos, fuente, host):
    """Convierte un feed RSS o Atom en notas. Rechaza DOCTYPE y entidades: no hacen falta y permiten ataques al XML."""
    if b"<!DOCTYPE" in datos[:4096].upper() or b"<!ENTITY" in datos.upper():
        raise ValueError("Feed con DOCTYPE o entidades")
    raiz = ET.fromstring(datos)
    notas = []
    es_atom = raiz.tag == _ATOM + "feed"
    for item in raiz.iter(_ATOM + "entry" if es_atom else "item"):
        if es_atom:
            titulo, enlace = item.findtext(_ATOM + "title"), _enlace_atom(item)
            resumen = item.findtext(_ATOM + "summary") or item.findtext(_ATOM + "content")
            fecha = item.findtext(_ATOM + "published") or item.findtext(_ATOM + "updated")
            imagen = _imagen_de(item, item.findtext(_ATOM + "content"), item.findtext(_ATOM + "summary"))
        else:
            titulo, enlace = item.findtext("title"), item.findtext("link")
            resumen, fecha = item.findtext("description"), item.findtext("pubDate")
            imagen = _imagen_de(item, item.findtext(_CONTENIDO), resumen)
        titulo, enlace = _texto_plano(titulo, 200), (enlace or "").strip()
        try:
            partes = urlparse(enlace)
        except ValueError:
            continue
        if not titulo or partes.scheme != "https" or _sin_www(partes.hostname) != _sin_www(host):
            continue
        notas.append({"titulo": titulo, "resumen": _texto_plano(resumen, _LARGO_RESUMEN), "enlace": enlace,
                      "fuente": fuente, "fecha": _fecha_iso(fecha), "imagen": imagen})
        if len(notas) >= _MAX_POR_FUENTE:
            break
    return notas


def _descargar(url):
    """Trae el feed sin aceptar respuestas enormes."""
    datos = b""
    with httpx.stream("GET", url, timeout=10, follow_redirects=True, headers={"User-Agent": "RetroEmulator/1.0"}) as r:
        r.raise_for_status()
        for parte in r.iter_bytes():
            datos += parte
            if len(datos) > _MAX_BYTES:
                raise ValueError("Feed demasiado grande")
    return datos


_lock = threading.Lock()
_por_fuente = {}   # fuente -> notas de la última lectura correcta
_leido_en = 0.0


def _actualizar_fuente(fuente, url):
    try:
        _por_fuente[fuente] = leer_feed(_descargar(url), fuente, urlparse(url).hostname)
    except Exception as e:   # un sitio caído no debe dejar sin noticias a los demás
        print(f"[NOTICIAS] No se pudo leer {fuente}: {e}")


def obtener(forzar=False):
    """Notas de todas las fuentes, de la más nueva a la más vieja. Si un sitio falla, se conserva su última lectura."""
    global _leido_en
    with _lock:
        edad = time.monotonic() - _leido_en
        if not _leido_en or edad > (_ESPERA_FORZADA_S if forzar else _VIGENCIA_S):
            with ThreadPoolExecutor(max_workers=len(FUENTES)) as hilos:
                list(hilos.map(lambda f: _actualizar_fuente(*f), FUENTES))
            _leido_en = time.monotonic()
        notas = [n for lista in _por_fuente.values() for n in lista]
    notas.sort(key=lambda n: n["fecha"] or "", reverse=True)
    return notas[:_MAX_TOTAL]
