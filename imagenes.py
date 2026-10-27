"""
imagenes.py - Imágenes del chat y stickers (usa Pillow: pip install pillow).

  - preparar_para_chat(): achica la foto (máx. 1280 px), la vuelve a guardar sin metadatos
    (se pierden EXIF/GPS, por privacidad) y la deja por debajo del límite de subida.
  - crear_sticker(): imagen cuadrada de 512x512 con fondo transparente, forma a elección
    (redondeado, círculo o cuadrado), recorte o imagen entera y contorno blanco opcional.

Todo se procesa en tu equipo; recién después se sube a Supabase.
"""
import base64
import io
import os

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, features
except Exception:  # Pillow no instalado
    Image = None

MAX_ARCHIVO = 15 * 1024 * 1024      # tamaño máximo del archivo elegido
MAX_SUBIDA = 5 * 1024 * 1024        # límite del bucket "chat" en Supabase
LADOS_CHAT = (1280, 1024, 800, 640)  # se prueba de mayor a menor hasta que entre en el límite
LADO_STICKER = 512

FORMAS = ("redondeado", "circulo", "cuadrado")
AJUSTES = ("recortar", "ajustar")


class ErrorImagen(Exception):
    pass


def disponible():
    return Image is not None


def _abrir(ruta):
    if Image is None:
        raise ErrorImagen("Falta instalar Pillow: ejecutá  pip install pillow  y reiniciá el launcher.")
    try:
        if os.path.getsize(ruta) > MAX_ARCHIVO:
            raise ErrorImagen("La imagen pesa más de 15 MB.")
        img = Image.open(ruta)
        img.load()
    except ErrorImagen:
        raise
    except Exception:
        raise ErrorImagen("No se pudo leer el archivo como imagen (probá con PNG, JPG o WEBP).")
    return ImageOps.exif_transpose(img)   # respeta la orientación de las fotos de celular


def _tiene_transparencia(img):
    return img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)


def _data_uri(datos, mime):
    return f"data:{mime};base64," + base64.b64encode(datos).decode("ascii")


def miniatura_data_uri(ruta, lado=420):
    """Vista previa liviana de un archivo para mostrar en pantalla."""
    img = _abrir(ruta)
    img.thumbnail((lado, lado), Image.LANCZOS)
    salida = io.BytesIO()
    if _tiene_transparencia(img):
        img.convert("RGBA").save(salida, "PNG")
        return _data_uri(salida.getvalue(), "image/png")
    img.convert("RGB").save(salida, "JPEG", quality=85)
    return _data_uri(salida.getvalue(), "image/jpeg")


def preparar_para_chat(ruta):
    """Devuelve (bytes, mime, extension) lista para subir."""
    original = _abrir(ruta)
    alfa = _tiene_transparencia(original)
    for lado in LADOS_CHAT:
        img = original.copy()
        img.thumbnail((lado, lado), Image.LANCZOS)
        salida = io.BytesIO()
        if alfa:
            img.convert("RGBA").save(salida, "PNG", optimize=True)
            mime, ext = "image/png", "png"
        else:
            img.convert("RGB").save(salida, "JPEG", quality=85, optimize=True)
            mime, ext = "image/jpeg", "jpg"
        if salida.tell() <= MAX_SUBIDA:
            return salida.getvalue(), mime, ext
    raise ErrorImagen("La imagen es demasiado pesada incluso después de achicarla.")


def _construir_sticker(img, forma, ajuste, contorno):
    L = LADO_STICKER
    margen = 14 if contorno else 0
    interior = L - 2 * margen
    img = img.convert("RGBA")

    if ajuste == "recortar":
        contenido = ImageOps.fit(img, (interior, interior), Image.LANCZOS, centering=(0.5, 0.5))
    else:
        contenido = img.copy()
        contenido.thumbnail((interior, interior), Image.LANCZOS)
    w, h = contenido.size

    if forma in ("redondeado", "circulo"):
        mascara = Image.new("L", (w, h), 0)
        dibujo = ImageDraw.Draw(mascara)
        if forma == "circulo":
            dibujo.ellipse((0, 0, w - 1, h - 1), fill=255)
        else:
            dibujo.rounded_rectangle((0, 0, w - 1, h - 1), radius=int(min(w, h) * 0.2), fill=255)
        contenido.putalpha(ImageChops.multiply(contenido.getchannel("A"), mascara))

    lienzo = Image.new("RGBA", (L, L), (0, 0, 0, 0))
    lienzo.alpha_composite(contenido, ((L - w) // 2, (L - h) // 2))

    if contorno:
        # Contorno blanco redondeado: se difumina la silueta y se corta con un umbral
        silueta = lienzo.getchannel("A").filter(ImageFilter.GaussianBlur(margen / 1.75))
        silueta = silueta.point(lambda v: 255 if v > 10 else 0).filter(ImageFilter.GaussianBlur(0.8))
        capa = Image.new("RGBA", (L, L), (255, 255, 255, 0))
        capa.putalpha(silueta)
        capa.alpha_composite(lienzo)
        lienzo = capa
    return lienzo


def crear_sticker(ruta, forma="redondeado", ajuste="recortar", contorno=True):
    """Devuelve (bytes, mime, extension) del sticker de 512x512 con fondo transparente."""
    forma = forma if forma in FORMAS else "redondeado"
    ajuste = ajuste if ajuste in AJUSTES else "recortar"
    sticker = _construir_sticker(_abrir(ruta), forma, ajuste, bool(contorno))
    salida = io.BytesIO()
    if features.check("webp"):
        sticker.save(salida, "WEBP", quality=90, method=4)
        return salida.getvalue(), "image/webp", "webp"
    sticker.save(salida, "PNG", optimize=True)
    return salida.getvalue(), "image/png", "png"


def vista_sticker(ruta, forma, ajuste, contorno):
    datos, mime, _ = crear_sticker(ruta, forma, ajuste, contorno)
    return _data_uri(datos, mime)


def tipo_mime(datos):
    """Tipo de imagen según los primeros bytes (para armar el data URI)."""
    if datos[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if datos[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "image/webp"
    if datos[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return ""


def a_data_uri(datos):
    mime = tipo_mime(datos or b"")
    return _data_uri(datos, mime) if mime else ""
