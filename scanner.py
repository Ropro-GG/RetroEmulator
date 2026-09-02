import os
import re
import db_local

CARPETA_ROMS_BASE = "roms"

def crear_estructura_carpetas():
    """
    Crea la carpeta global 'roms/' y una subcarpeta por cada consola.
    """
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
    """
    Detecta si el archivo es un 'Track' secundario de audio o datos adicionales.
    Ejemplo: 'Game (Track 2).bin' -> True
    """
    patron_track = re.search(r'\(track\s*\d+\)', nombre_archivo, re.IGNORECASE)
    patron_audio = re.search(r'\(audio\)', nombre_archivo, re.IGNORECASE)
    return bool(patron_track or patron_audio)

def extraer_titulo_y_disco(nombre_archivo):
    """
    Separa el título base del juego y detecta el número de disco si existe.
    Ejemplo: 'Final Fantasy VII (USA) (Disc 1).bin' -> ('Final Fantasy VII', 1)
             'Super Mario World.sfc' -> ('Super Mario World', 1)
    """
    nombre, _ = os.path.splitext(nombre_archivo)
    
    # Buscar patrones de disco como (Disc 1), (Disk 2), (CD 1), (Disc A)
    match_disco = re.search(r'[\(\[\{](?:disc|disk|cd)\s*([0-9]|a-z)[\)\]\}]', nombre, re.IGNORECASE)
    
    num_disco = 1
    if match_disco:
        val = match_disco.group(1)
        num_disco = int(val) if val.isdigit() else (ord(val.lower()) - 96)

    # Limpiar tags como (USA), [!], etc.
    nombre_limpio = re.sub(r'[\(\[\{].*?[\)\]\}]', '', nombre)
    nombre_limpio = nombre_limpio.replace('_', ' ')
    nombre_limpio = ' '.join(nombre_limpio.split()).strip()

    return nombre_limpio or nombre, num_disco

def escanear_consola(consola):
    """
    Escanea la carpeta de una consola agrupando discos y filtrando tracks de audio.
    """
    ruta_roms = consola.get("ruta_roms")
    if not ruta_roms or not os.path.exists(ruta_roms):
        return 0

    extensiones_validas = [
        ext.strip().lower() 
        for ext in consola["extensiones"].split(",")
    ]

    # Diccionario para agrupar multidiscos: { "Titulo Juego": (ruta_primer_disco, disco_mas_bajo) }
    juegos_agrupados = {}

    for raiz, _, archivos in os.walk(ruta_roms):
        for archivo in archivos:
            _, ext = os.path.splitext(archivo)
            
            if ext.lower() in extensiones_validas:
                # 1. Ignorar archivos que sean pistas secundarias de audio
                if es_pista_de_audio(archivo):
                    continue

                ruta_completa = os.path.join(raiz, archivo)
                titulo_base, num_disco = extraer_titulo_y_disco(archivo)

                # 2. Agrupar multidiscos (guardar o conservar la ruta del Disco 1)
                if titulo_base not in juegos_agrupados:
                    juegos_agrupados[titulo_base] = (ruta_completa, num_disco)
                else:
                    # Si ya existía pero encontramos el Disco 1 (o un disco menor), actualizamos la ruta principal
                    _, disco_previo = juegos_agrupados[titulo_base]
                    if num_disco < disco_previo:
                        juegos_agrupados[titulo_base] = (ruta_completa, num_disco)

    # Registrar en la base de datos la lista consolidada
    juegos_registrados = 0
    for titulo, (ruta_rom, _) in juegos_agrupados.items():
        db_local.registrar_juego(
            consola_id=consola["id"],
            titulo=titulo,
            ruta_rom=ruta_rom
        )
        juegos_registrados += 1

    return juegos_registrados

def escanear_todo():
    """Asegura que existan las carpetas y escanea todas las consolas."""
    crear_estructura_carpetas()
    consolas = db_local.obtener_consolas()
    total_encontrados = 0

    for consola in consolas:
        encontrados = escanear_consola(consola)
        total_encontrados += encontrados

    return total_encontrados

if __name__ == "__main__":
    db_local.inicializar_db_local()
    print("Inicializando carpetas de ROMs y ejecutando escáner mejorado...")
    total = escanear_todo()
    print(f"Escaneo finalizado. Total de juegos únicos registrados: {total}")