import subprocess
import os
import db_local

def ejecutar_juego(juego_id):
    """
    Busca un juego por su ID en la base de datos local y ejecuta
    el emulador configurado pasándole la ruta de la ROM.
    """
    # 1. Obtener la información del juego desde la DB
    with db_local.obtener_conexion() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT j.titulo, j.ruta_rom, c.nombre, c.ruta_emulador
            FROM juegos j
            JOIN consolas c ON j.consola_id = c.id
            WHERE j.id = ?;
        """, (juego_id,))
        resultado = cursor.fetchone()

    if not resultado:
        print(f"[ERROR] No se encontró el juego con ID {juego_id}.")
        return False

    titulo, ruta_rom, nombre_consola, ruta_emulador = resultado

    # 2. Validar que exista el archivo ROM
    if not os.path.exists(ruta_rom):
        print(f"[ERROR] El archivo de la ROM no existe en la ruta: {ruta_rom}")
        return False

    # 3. Validar si hay un emulador configurado para esta consola
    if not ruta_emulador or not os.path.exists(ruta_emulador):
        print(f"[ADVERTENCIA] No hay emulador configurado para {nombre_consola}.")
        print(f"Ruta intentada: '{ruta_emulador}'")
        print(f"Por favor asigná la ruta del emulador en la base de datos o en la configuración.")
        return False

    # 4. Lanzar el proceso del emulador
    print(f"[LAUNCHER] Iniciando '{titulo}' en {nombre_consola}...")
    try:
        # Pasa el ejecutable del emulador y la ruta de la ROM como argumentos
        subprocess.Popen([ruta_emulador, ruta_rom])
        return True
    except Exception as e:
        print(f"[ERROR] Falló la ejecución del emulador: {e}")
        return False

if __name__ == "__main__":
    db_local.inicializar_db_local()
    print("Módulo Launcher listo para recibir comandos.")