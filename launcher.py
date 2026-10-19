import subprocess
import os
import db_local

def ejecutar_juego(juego_id):
    """
    Busca un juego por su ID. Si hay otros juegos con exactamente el mismo título 
    (ej. varios discos o versiones), retorna las opciones para que el usuario elija.
    """
    with db_local.obtener_conexion() as conn:
        cursor = conn.cursor()
        
        # 1. Obtener el título y la consola del juego seleccionado
        cursor.execute("""
            SELECT j.titulo, j.ruta_rom, c.nombre, c.ruta_emulador, j.consola_id
            FROM juegos j
            JOIN consolas c ON j.consola_id = c.id
            WHERE j.id = ?;
        """, (juego_id,))
        resultado = cursor.fetchone()

        if not resultado:
            return {"exito": False, "error": f"No se encontró el juego con ID {juego_id}."}

        titulo, ruta_rom, nombre_consola, ruta_emulador, consola_id = resultado

        # 2. Buscar si hay otros juegos con el mismo título en la misma consola (ej: multidiscos o variantes)
        cursor.execute("""
            SELECT j.id, j.titulo, j.ruta_rom, c.ruta_emulador
            FROM juegos j
            JOIN consolas c ON j.consola_id = c.id
            WHERE j.titulo = ? AND j.consola_id = ?;
        """, (titulo, consola_id))
        coincidencias = cursor.fetchall()

    # Si hay múltiples variantes o discos con el mismo nombre, devolvemos la lista para elegir
    if len(coincidencias) > 1:
        opciones = []
        for c_id, c_titulo, c_ruta, c_emul in coincidencias:
            # Extraer un nombre descriptivo (ej: Disc 1, Disc 2, etc.) del nombre del archivo o ruta
            nombre_archivo = os.path.basename(c_ruta)
            opciones.append({
                "id": c_id,
                "titulo": c_titulo,
                "ruta_rom": c_ruta,
                "descripcion": nombre_archivo
            })
        return {"exito": False, "requiere_seleccion": True, "opciones": opciones}

    # 3. Validar existencia de la ROM
    if not os.path.exists(ruta_rom):
        return {"exito": False, "error": f"El archivo de la ROM no existe: {ruta_rom}"}

    # 4. Validar emulador
    if not ruta_emulador or not os.path.exists(ruta_emulador):
        return {"exito": False, "error": f"No hay emulador configurado para {nombre_consola}."}

    # 5. Lanzar el proceso
    try:
        subprocess.Popen([ruta_emulador, ruta_rom])
        return {"exito": True}
    except Exception as e:
        return {"exito": False, "error": f"Falló la ejecución del emulador: {e}"}

class GameLauncher:
    def lanzar_por_id(self, juego_id):
        return ejecutar_juego(juego_id)