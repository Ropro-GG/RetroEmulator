import os
import re
import urllib.request
import urllib.parse
import urllib.error
import db_local

CARPETA_ROMS_BASE = "roms"
CARPETA_BOXARTS = os.path.join(CARPETA_ROMS_BASE, "boxarts")

def crear_estructura_carpetas():
    """Crea la carpeta global 'roms/', la de carátulas y las subcarpetas por consola[cite: 7]."""
    if not os.path.exists(CARPETA_ROMS_BASE):
        os.makedirs(CARPETA_ROMS_BASE)
    if not os.path.exists(CARPETA_BOXARTS):
        os.makedirs(CARPETA_BOXARTS)

    consolas = db_local.obtener_consolas()
    for consola in consolas:
        ruta_consola = os.path.join(CARPETA_ROMS_BASE, consola["identificativo"])
        if not os.path.exists(ruta_consola):
            os.makedirs(ruta_consola)
        
        if not consola["ruta_roms"]:
            db_local.actualizar_rutas_consola(consola["id"], ruta_roms=ruta_consola)

def extraer_nombre_para_thumbnail(nombre_archivo):
    """
    Conserva la región (ej: (USA)), pero remueve cualquier etiqueta de disco 
    (ej: (Disc 1), (CD 2)) para que juegos complejos encuentren su carátula[cite: 7].
    """
    nombre_sin_disco = re.sub(r'[\(\[\{]\s*(?:disc|disk|cd)\s*\d+.*?[\)\]\}]', '', nombre_archivo, flags=re.IGNORECASE)
    nombre_limpio = nombre_sin_disco.replace('_', ' ')
    nombre_limpio = nombre_limpio.replace('/', '-').replace('\\', '-')
    return ' '.join(nombre_limpio.split()).strip()

def descargar_portada(nombre_archivo_rom, titulo_limpio, nombre_consola):
    """
    Descarga la carátula utilizando consola, juego y región, omitiendo los discos[cite: 7].
    """
    libretro_map = {
        "Sony PlayStation (PS1)": "Sony - PlayStation",
        "Super Nintendo (SNES)": "Nintendo - Super Nintendo Entertainment System",
        "Nintendo Entertainment System (NES)": "Nintendo - Nintendo Entertainment System",
        "Sega Genesis / Mega Drive": "Sega - Mega Drive - Genesis",
        "Nintendo 64": "Nintendo - Nintendo 64",
        "Nintendo Game Boy Advance": "Nintendo - Game Boy Advance",
        "Nintendo Game Boy Color": "Nintendo - Game Boy Color",
        "Nintendo Game Boy": "Nintendo - Game Boy",
        "Sony PlayStation Portable (PSP)": "Sony - PlayStation Portable",
        "Sega Dreamcast": "Sega - Dreamcast",
        "Sega Saturn": "Sega - Saturn",
        "Nintendo GameCube": "Nintendo - GameCube"
    }

    carpeta_sistema = libretro_map.get(nombre_consola, nombre_consola)
    
    nombre_con_region = extraer_nombre_para_thumbnail(nombre_archivo_rom)
    candidatos_busqueda = [nombre_con_region, titulo_limpio]
    
    nombre_archivo_img = f"{nombre_consola.replace(' ', '_')}_{nombre_con_region}.png"
    ruta_local_img = os.path.join(CARPETA_BOXARTS, nombre_archivo_img)

    # Si ya existe un archivo válido (mayor a 100 bytes), se reutiliza
    if os.path.exists(ruta_local_img) and os.path.getsize(ruta_local_img) > 100:
        return ruta_local_img

    headers = {'User-Agent': 'Mozilla/5.0'}

    for candidato in candidatos_busqueda:
        url_api = f"https://thumbnails.libretro.com/{urllib.parse.quote(carpeta_sistema)}/Named_Boxarts/{urllib.parse.quote(candidato)}.png"
        try:
            req = urllib.request.Request(url_api, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as respuesta:
                contenido = respuesta.read()
                if len(contenido) > 100:
                    with open(ruta_local_img, 'wb') as f:
                        f.write(contenido)
                    print(f"[BOXART ÉXITO] Descargada: '{candidato}' para {nombre_consola}")
                    return ruta_local_img
        except Exception:
            continue

    return ""

def es_pista_de_audio(nombre_archivo):
    nombre_lower = nombre_archivo.lower()
    patron_track = re.search(r'[\(\[\{\-_ ]track\s*\d+[\)\]\} ]', nombre_lower, re.IGNORECASE)
    patron_audio = re.search(r'\(audio\)', nombre_lower, re.IGNORECASE)
    
    if "track" in nombre_lower or "audio" in nombre_lower:
        if "track 1" in nombre_lower or "track 01" in nombre_lower or "track1" in nombre_lower:
            return False
        return True

    return bool(patron_track or patron_audio)

def limpiar_titulo(nombre):
    nombre_limpio = re.sub(r'[\(\[\{].*?[\)\]\}]', '', nombre)
    nombre_limpio = nombre_limpio.replace('_', ' ')
    return ' '.join(nombre_limpio.split()).strip()

def generar_m3u_para_multidisco(directorio, archivos_consola):
    discos_por_juego = {}
    tiene_cue = any(f.lower().endswith('.cue') for f in archivos_consola)

    for archivo in archivos_consola:
        if es_pista_de_audio(archivo):
            continue
        _, ext = os.path.splitext(archivo)
        ext_lower = ext.lower()

        if ext_lower not in ['.cue', '.iso', '.chd', '.bin', '.gdi', '.pbp']:
            continue
        if tiene_cue and ext_lower == '.bin':
            continue

        match_disco = re.search(r'[\(\[\{](?:disc|disk|cd)\s*([0-9]|a-z)[\)\]\}]', archivo, re.IGNORECASE)
        if match_disco:
            titulo_base = limpiar_titulo(os.path.splitext(archivo)[0])
            if titulo_base not in discos_por_juego:
                discos_por_juego[titulo_base] = []
            discos_por_juego[titulo_base].append(archivo)

    m3u_creados = []
    for titulo, discos in discos_por_juego.items():
        if len(discos) > 1:
            cues_o_chds = [d for d in discos if d.lower().endswith(('.cue', '.chd', '.iso', '.pbp'))]
            discos_finales = cues_o_chds if cues_o_chds else discos
            discos_finales.sort()

            ruta_m3u = os.path.join(directorio, f"{titulo}.m3u")
            if not os.path.exists(ruta_m3u):
                with open(ruta_m3u, 'w', encoding='utf-8') as f:
                    for disco in discos_finales:
                        f.write(f"{disco}\n")
            m3u_creados.append(ruta_m3u)

    return m3u_creados

def escanear_consola(consola):
    ruta_roms = consola.get("ruta_roms")
    if not ruta_roms or not os.path.exists(ruta_roms):
        return 0

    extensiones_validas = [ext.strip().lower() for ext in consola["extensiones"].split(",")]
    if ".m3u" not in extensiones_validas:
        extensiones_validas.append(".m3u")

    juegos_registrados = 0

    for raiz, _, archivos in os.walk(ruta_roms):
        generar_m3u_para_multidisco(raiz, archivos)

        tiene_m3u = any(f.lower().endswith('.m3u') for f in archivos)
        tiene_cue = any(f.lower().endswith('.cue') for f in archivos)

        for archivo in archivos:
            _, ext = os.path.splitext(archivo)
            ext_lower = ext.lower()
            
            if ext_lower in extensiones_validas:
                if es_pista_de_audio(archivo):
                    continue
                if tiene_cue and ext_lower == ".bin":
                    continue

                match_disco = re.search(r'[\(\[\{](?:disc|disk|cd)\s*([0-9]|a-z)[\)\]\}]', archivo, re.IGNORECASE)
                if tiene_m3u and match_disco and not ext_lower == '.m3u':
                    continue

                ruta_completa = os.path.join(raiz, archivo)
                nombre_base, _ = os.path.splitext(archivo)
                
                titulo_para_ui = limpiar_titulo(nombre_base)
                portada_path = descargar_portada(nombre_base, titulo_para_ui, consola["nombre"])

                db_local.registrar_juego(
                    consola_id=consola["id"],
                    titulo=titulo_para_ui,
                    ruta_rom=ruta_completa,
                    portada_path=portada_path
                )
                juegos_registrados += 1

    return juegos_registrados

def escanear_todo():
    crear_estructura_carpetas()
    consolas = db_local.obtener_consolas()
    total_encontrados = 0

    for consola in consolas:
        encontrados = escanear_consola(consola)
        total_encontrados += encontrados

    return total_encontrados

class ROMScanner:
    def escanear(self):
        return escanear_todo()

if __name__ == "__main__":
    db_local.inicializar_db_local()
    total = escanear_todo()
    print(f"Escaneo finalizado. Juegos listos: {total}")