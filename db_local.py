import sqlite3
import os

DB_NAME = "retrolauncher_local.db"

def obtener_conexion():
    """Crea y retorna una conexión a la base de datos local SQLite."""
    conexion = sqlite3.connect(DB_NAME)
    conexion.execute("PRAGMA foreign_keys = ON;")
    return conexion

def inicializar_db_local():
    """Crea las tablas locales si no existen y puebla consolas por defecto."""
    with obtener_conexion() as conn:
        cursor = conn.cursor()
        
        # Tabla de consolas soportadas y sus rutas locales
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS consolas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE,
                identificativo TEXT NOT NULL UNIQUE,
                extensiones TEXT NOT NULL,
                ruta_emulador TEXT DEFAULT '',
                ruta_roms TEXT DEFAULT ''
            );
        """)

        # Tabla de juegos encontrados localmente
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS juegos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                consola_id INTEGER NOT NULL,
                titulo TEXT NOT NULL,
                ruta_rom TEXT NOT NULL UNIQUE,
                portada_path TEXT DEFAULT '',
                favorito INTEGER DEFAULT 0,
                FOREIGN KEY (consola_id) REFERENCES consolas (id) ON DELETE CASCADE
            );
        """)

        # Configuración general de la PC (carpetas base, temas, etc.)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS configuracion (
                clave TEXT PRIMARY KEY,
                valor TEXT NOT NULL
            );
        """)

        # Insertar lista completa de consolas retro si la tabla está vacía
        cursor.execute("SELECT COUNT(*) FROM consolas;")
        if cursor.fetchone()[0] == 0:
            consolas_base = [
                # 1ª Generación
                ("Magnavox Odyssey", "odyssey", ".bin,.rom"),
                ("Atari Home Pong", "pong", ".bin"),
                ("Magnavox Odyssey 2001", "odyssey2001", ".bin"),
                ("Magnavox Odyssey 4000", "odyssey4000", ".bin"),

                # 2ª Generación
                ("Atari 2600", "atari2600", ".a26,.bin"),
                ("Intellivision", "intellivision", ".int,.bin"),
                ("ColecoVision", "colecovision", ".col,.bin"),
                ("Bally Astrocade", "astrocade", ".bin"),
                ("RCA Studio II / ARC-2001", "rcastudio2", ".bin"),
                ("APF MP100", "apf1000", ".bin"),
                ("Vectrex", "vectrex", ".vec,.bin"),
                ("Atari 5200", "atari5200", ".a52,.bin"),
                ("Fairchild Channel F", "channelf", ".bin"),

                # 3ª Generación
                ("Nintendo Entertainment System (NES)", "nes", ".nes,.zip"),
                ("Famicom Disk System", "fds", ".fds"),
                ("Sega Master System", "sms", ".sms"),
                ("Sega SG-1000", "sg1000", ".sg"),
                ("Atari 7800", "atari7800", ".a78,.bin"),
                ("Atari XEGS", "atarixegs", ".atr,.bin"),
                ("NEC PC-6001", "pc6001", ".cas,.p6"),
                ("Amstrad GX4000", "gx4000", ".cpr,.bin"),
                ("TurboGrafx-16 / PC Engine", "pcengine", ".pce"),
                ("SNK Neo Geo AES/MVS", "neogeo", ".zip,.neo"),
                ("Sega CD / Mega-CD", "segacd", ".iso,.cue,.chd"),
                ("Philips CD-i", "cdi", ".iso,.cue,.chd"),
                ("SNK Neo Geo CD", "neogeocd", ".iso,.cue,.chd"),

                # 4ª Generación
                ("Super Nintendo (SNES)", "snes", ".sfc,.smc,.zip"),
                ("Sega Genesis / Mega Drive", "genesis", ".gen,.md,.zip"),
                ("Sega 32X", "sega32x", ".32x"),
                ("Atari Jaguar", "jagr", ".jag"),
                ("3DO Interactive Multiplayer", "3do", ".iso,.cue,.chd"),
                ("NEC PC-FX", "pcfx", ".iso,.cue,.chd"),
                ("Fujitsu FM Towns Marty", "fmtowns", ".iso,.cue"),
                ("Commodore Amiga CD32", "cd32", ".iso,.cue,.chd"),
                ("Bandai Apple Pippin", "pippin", ".iso"),

                # 5ª / 6ª / 7ª Generación
                ("Sony PlayStation (PS1)", "psx", ".iso,.bin,.cue,.pbp,.chd"),
                ("Nintendo 64", "n64", ".z64,.n64,.v64"),
                ("Sega Saturn", "saturn", ".iso,.cue,.chd"),
                ("Sega Dreamcast", "dreamcast", ".cdi,.gdi,.chd"),
                ("Sony PlayStation 2 (PS2)", "ps2", ".iso,.gz,.chd"),
                ("Nintendo GameCube", "gamecube", ".iso,.gcm,.rvz,.gcz"),
                ("Microsoft Xbox", "xbox", ".iso"),
                ("Sony PlayStation 3 (PS3)", "ps3", ".iso,.pkg"),
                ("Microsoft Xbox 360", "xbox360", ".iso,.xex"),
                ("Nintendo Wii", "wii", ".iso,.wbfs,.rvz"),
                ("Nintendo Wii U", "wiiu", ".rpx,.wud,.wux"),

                # Portátiles / Handhelds
                ("Nintendo Game Boy", "gb", ".gb"),
                ("Nintendo Game Boy Color", "gbc", ".gbc"),
                ("Nintendo Game Boy Advance", "gba", ".gba"),
                ("Nintendo Virtual Boy", "vb", ".vb"),
                ("Tiger Game.com", "gamecom", ".bin"),
                ("Sega Genesis Nomad", "nomad", ".gen,.md"),
                ("SNK Neo Geo Pocket", "ngp", ".ngp"),
                ("SNK Neo Geo Pocket Color", "ngpc", ".ngc"),
                ("Bandai WonderSwan", "ws", ".ws"),
                ("Bandai WonderSwan Color", "wsc", ".wsc"),
                ("Nintendo DS", "nds", ".nds"),
                ("Nintendo 3DS", "3ds", ".3ds,.cia"),
                ("Sony PlayStation Portable (PSP)", "psp", ".iso,.cso,.pbp"),
                ("Sony PlayStation Vita", "psvita", ".vpk,.zip")
            ]
            
            cursor.executemany("""
                INSERT INTO consolas (nombre, identificativo, extensiones)
                VALUES (?, ?, ?);
            """, consolas_base)
            
        conn.commit()

# --- FUNCIONES DE GESTIÓN DE CONSOLAS ---

def obtener_consolas():
    """Retorna todas las consolas registradas."""
    with obtener_conexion() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, nombre, identificativo, extensiones, ruta_emulador, ruta_roms FROM consolas;")
        filas = cursor.fetchall()
        return [
            {
                "id": r[0],
                "nombre": r[1],
                "identificativo": r[2],
                "extensiones": r[3],
                "ruta_emulador": r[4],
                "ruta_roms": r[5]
            } for r in filas
        ]

def actualizar_rutas_consola(consola_id, ruta_emulador=None, ruta_roms=None):
    """Actualiza la ubicación del emulador o carpeta de ROMs de una consola."""
    with obtener_conexion() as conn:
        cursor = conn.cursor()
        if ruta_emulador is not None:
            cursor.execute("UPDATE consolas SET ruta_emulador = ? WHERE id = ?;", (ruta_emulador, consola_id))
        if ruta_roms is not None:
            cursor.execute("UPDATE consolas SET ruta_roms = ? WHERE id = ?;", (ruta_roms, consola_id))
        conn.commit()

# --- FUNCIONES DE GESTIÓN DE JUEGOS ---

def registrar_juego(consola_id, titulo, ruta_rom, portada_path=""):
    """Inserta un juego en la base de datos si la ruta no existe."""
    with obtener_conexion() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO juegos (consola_id, titulo, ruta_rom, portada_path)
            VALUES (?, ?, ?, ?);
        """, (consola_id, titulo, ruta_rom, portada_path))
        conn.commit()

def obtener_juegos_por_consola(consola_id):
    """Retorna la lista de juegos pertenecientes a una consola."""
    with obtener_conexion() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, titulo, ruta_rom, portada_path, favorito FROM juegos WHERE consola_id = ?;", (consola_id,))
        filas = cursor.fetchall()
        return [
            {
                "id": r[0],
                "titulo": r[1],
                "ruta_rom": r[2],
                "portada_path": r[3],
                "favorito": bool(r[4])
            } for r in filas
        ]

if __name__ == "__main__":
    # Si ejecutás este script directamente, recreará la DB con la lista actualizada
    inicializar_db_local()
    print("Base de datos local actualizada e inicializada con todas las consolas.")
