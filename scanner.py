import os
import re
import db_local

CARPETA_ROMS_BASE = "roms"

def crear_estructura_carpetas():
    """Crea la carpeta global 'roms/' y las subcarpetas por consola."""
    if not os.path.exists(CARPETA_ROMS_BASE):
        os.makedirs(CARPETA_ROMS_BASE)

    consolas = db_local.obtener_consolas()
    for consola in consolas:
        ruta_consola = os.path.join(CARPETA_ROMS_BASE, consola["identificativo"])
        if not os.path.exists(ruta_consola):
            os.makedirs(ruta_consola)
        
        if not consola["ruta_roms"]:
            db_local.actualizar_rutas_consola(consola["id"], ruta_roms=ruta_consola)

def es_pista_de_audio(nombre_archivo):
    """Filtra pistas secundarias de audio."""
    patron_track = re.search(r'\(track\s*\d+\)', nombre_archivo, re.IGNORECASE)
    patron_audio = re.search(r'\(audio\)', nombre_archivo, re.IGNORECASE)
    return bool(patron_track or patron_audio)

def limpiar_titulo(nombre):
    """Limpia etiquetas como (USA), (Disc 1), etc."""
    nombre_limpio = re.sub(r'[\(\[\{].*?[\)\]\}]', '', nombre)
    nombre_limpio = nombre_limpio.replace('_', ' ')
    return ' '.join(nombre_limpio.split()).strip()

def generar_m3u_para_multidisco(directorio, archivos_consola):
    """
    Agrupa archivos de varios discos y genera un archivo .m3u automático.
    Retorna una lista con las rutas de los archivos .m3u generados.
    """
    discos_por_juego = {}

    for archivo in archivos_consola:
        if es_pista_de_audio(archivo):
            continue

        # Detectar extensión válida de imagen (evitar meter .txt o .db)
        _, ext = os.path.splitext(archivo)
        if ext.lower() not in ['.cue', '.iso', '.chd', '.bin', '.gdi', '.pbp']:
            continue

        # Si hay .cue y .bin con el mismo nombre, preferimos el .cue
        match_disco = re.search(r'[\(\[\{](?:disc|disk|cd)\s*([0-9]|a-z)[\)\]\}]', archivo, re.IGNORECASE)
        if match_disco:
            titulo_base = limpiar_titulo(os.path.splitext(archivo)[0])
            if titulo_base not in discos_por_juego:
                discos_por_juego[titulo_base] = []
            discos_por_juego[titulo_base].append(archivo)

    m3u_creados = []
    
    for titulo, discos in discos_por_juego.items():
        # Si tiene 2 o más discos, generamos la lista .m3u
        if len(discos) > 1:
            # Filtrar si hay duplicados bin/cue (priorizar .cue o .chd sobre .bin)
            cues_o_chds = [d for d in discos if d.lower().endswith(('.cue', '.chd', '.iso', '.pbp'))]
            discos_finales = cues_o_chds if cues_o_chds else discos
            discos_finales.sort()

            ruta_m3u = os.path.join(directorio, f"{titulo}.m3u")
            
            # Escribir el archivo .m3u si no existe
            if not os.path.exists(ruta_m3u):
                with open(ruta_m3u, 'w', encoding='utf-8') as f:
                    for disco in discos_finales:
                        f.write(f"{disco}\n")
                print(f"[MULTIDISCO] Creado playlist: {titulo}.m3u")

            m3u_creados.append(ruta_m3u)

    return m3u_creados

def escanear_consola(consola):
    """Escanea carpetas gestionando archivos individuales y multidiscos .m3u."""
    ruta_roms = consola.get("ruta_roms")
    if not ruta_roms or not os.path.exists(ruta_roms):
        return 0

    extensiones_validas = [ext.strip().lower() for ext in consola["extensiones"].split(",")]
    if ".m3u" not in extensiones_validas:
        extensiones_validas.append(".m3u")

    juegos_registrados = 0

    for raiz, _, archivos in os.walk(ruta_roms):
        # 1. Intentar generar .m3u si hay discos sueltos en esta carpeta
        generar_m3u_para_multidisco(raiz, archivos)

        # 2. Registrar ROMs (si existe un .m3u en la carpeta, omitimos los discos individuales)
        tiene_m3u = any(f.endswith('.m3u') for f in archivos)

        for archivo in archivos:
            _, ext = os.path.splitext(archivo)
            
            if ext.lower() in extensiones_validas:
                if es_pista_de_audio(archivo):
                    continue

                # Si ya creamos un .m3u para este grupo de discos, no registramos los discos sueltos
                match_disco = re.search(r'[\(\[\{](?:disc|disk|cd)\s*([0-9]|a-z)[\)\]\}]', archivo, re.IGNORECASE)
                if tiene_m3u and match_disco and not archivo.endswith('.m3u'):
                    continue

                ruta_completa = os.path.join(raiz, archivo)
                nombre_base, _ = os.path.splitext(archivo)
                titulo = limpiar_titulo(nombre_base)

                db_local.registrar_juego(
                    consola_id=consola["id"],
                    titulo=titulo,
                    ruta_rom=ruta_completa
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

if __name__ == "__main__":
    db_local.inicializar_db_local()
    print("Ejecutando escáner con soporte nativo para multidiscos (.m3u)...")
    total = escanear_todo()
    print(f"Escaneo finalizado. Juegos listos para jugar: {total}")