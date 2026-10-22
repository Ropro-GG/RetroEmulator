import sqlite3
import os

import contexto

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

        # Opiniones del usuario sobre sus juegos (una por juego y consola)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS opiniones (
                consola_id INTEGER NOT NULL,
                titulo TEXT NOT NULL,
                puntuacion INTEGER DEFAULT 0,
                texto TEXT DEFAULT '',
                actualizado TEXT DEFAULT '',
                PRIMARY KEY (consola_id, titulo)
            );
        """)

        # Opiniones por cuenta (la tabla 'opiniones' anterior queda solo como origen de migración)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS opiniones_cuenta (
                usuario_id TEXT NOT NULL,
                consola_id INTEGER NOT NULL,
                titulo TEXT NOT NULL,
                puntuacion INTEGER DEFAULT 0,
                texto TEXT DEFAULT '',
                actualizado TEXT DEFAULT '',
                PRIMARY KEY (usuario_id, consola_id, titulo)
            );
        """)

        # Coincidencias entre juegos locales y juegos de RetroAchievements
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ra_juegos (
                consola_id INTEGER NOT NULL,
                titulo TEXT NOT NULL,
                ra_game_id INTEGER NOT NULL,
                PRIMARY KEY (consola_id, titulo)
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
        # Upsert: si el juego ya existe se actualiza el título, pero una portada
        # ya guardada nunca se pisa con un valor vacío.
        cursor.execute("""
            INSERT INTO juegos (consola_id, titulo, ruta_rom, portada_path)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(ruta_rom) DO UPDATE SET
                consola_id = excluded.consola_id,
                titulo = excluded.titulo,
                portada_path = CASE WHEN excluded.portada_path <> ''
                                    THEN excluded.portada_path
                                    ELSE juegos.portada_path END;
        """, (consola_id, titulo, ruta_rom, portada_path))
        conn.commit()

def actualizar_portada(ruta_rom, portada_path):
    """Guarda la ruta de la carátula descargada para un juego."""
    with obtener_conexion() as conn:
        conn.execute("UPDATE juegos SET portada_path = ? WHERE ruta_rom = ?;", (portada_path, ruta_rom))
        conn.commit()

def obtener_mapa_portadas():
    """Retorna {ruta_rom: portada_path} para saber qué juegos ya tienen carátula."""
    with obtener_conexion() as conn:
        return dict(conn.execute("SELECT ruta_rom, portada_path FROM juegos;").fetchall())

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

# --- DETALLE, OPINIONES, CONFIGURACIÓN Y LOGROS ---

def obtener_juego_detalle(juego_id):
    """Datos de un juego (agrupando variantes/discos del mismo título y consola)."""
    with obtener_conexion() as conn:
        fila = conn.execute("""
            SELECT j.id, j.titulo, j.consola_id, c.nombre, c.identificativo,
                   (SELECT MAX(j2.portada_path) FROM juegos j2
                     WHERE j2.titulo = j.titulo AND j2.consola_id = j.consola_id),
                   (SELECT COUNT(*) FROM juegos j3
                     WHERE j3.titulo = j.titulo AND j3.consola_id = j.consola_id)
            FROM juegos j JOIN consolas c ON j.consola_id = c.id
            WHERE j.id = ?;
        """, (juego_id,)).fetchone()
    if not fila:
        return None
    return {
        "id": fila[0], "titulo": fila[1], "consola_id": fila[2], "consola": fila[3],
        "identificativo": fila[4], "portada_path": fila[5] or "", "total_variantes": fila[6],
    }

def obtener_opinion(consola_id, titulo):
    """Opinión de la cuenta que tiene la sesión iniciada."""
    with obtener_conexion() as conn:
        fila = conn.execute(
            "SELECT puntuacion, texto FROM opiniones_cuenta WHERE usuario_id = ? AND consola_id = ? AND titulo = ?;",
            (contexto.usuario_id(), consola_id, titulo)).fetchone()
    return {"puntuacion": fila[0], "texto": fila[1]} if fila else None

def guardar_opinion(consola_id, titulo, puntuacion, texto):
    puntuacion = max(0, min(5, int(puntuacion or 0)))
    with obtener_conexion() as conn:
        conn.execute("""
            INSERT INTO opiniones_cuenta (usuario_id, consola_id, titulo, puntuacion, texto, actualizado)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(usuario_id, consola_id, titulo) DO UPDATE SET
                puntuacion = excluded.puntuacion,
                texto = excluded.texto,
                actualizado = excluded.actualizado;
        """, (contexto.usuario_id(), consola_id, titulo, puntuacion, texto or ""))
        conn.commit()

def obtener_identificativo_por_consola(nombre):
    """Identificativo ('psx', 'nes'...) a partir del nombre de la consola."""
    with obtener_conexion() as conn:
        fila = conn.execute("SELECT identificativo FROM consolas WHERE nombre = ?;", (nombre,)).fetchone()
    return fila[0] if fila else ""

def obtener_consolas_con_juegos():
    """Solo las consolas que ya tienen juegos escaneados (para configurar su emulador)."""
    with obtener_conexion() as conn:
        filas = conn.execute("""
            SELECT c.id, c.nombre, c.identificativo, c.ruta_roms, c.ruta_emulador,
                   COUNT(DISTINCT j.titulo)
            FROM consolas c JOIN juegos j ON j.consola_id = c.id
            GROUP BY c.id ORDER BY c.nombre ASC;
        """).fetchall()
    return [{"id": f[0], "nombre": f[1], "identificativo": f[2], "ruta_roms": f[3],
             "ruta_emulador": f[4], "total_juegos": f[5]} for f in filas]

def contar_juegos():
    """Cantidad de juegos distintos (los mismos que muestra el catálogo)."""
    with obtener_conexion() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM (SELECT 1 FROM juegos GROUP BY titulo, consola_id);").fetchone()[0]

def contar_emuladores():
    """Cantidad de emuladores distintos configurados."""
    with obtener_conexion() as conn:
        return conn.execute(
            "SELECT COUNT(DISTINCT ruta_emulador) FROM consolas WHERE ruta_emulador <> '';").fetchone()[0]

def obtener_ra_juego(consola_id, titulo):
    with obtener_conexion() as conn:
        fila = conn.execute(
            "SELECT ra_game_id FROM ra_juegos WHERE consola_id = ? AND titulo = ?;",
            (consola_id, titulo)).fetchone()
    return fila[0] if fila else 0

def guardar_ra_juego(consola_id, titulo, ra_game_id):
    with obtener_conexion() as conn:
        conn.execute("""
            INSERT INTO ra_juegos (consola_id, titulo, ra_game_id) VALUES (?, ?, ?)
            ON CONFLICT(consola_id, titulo) DO UPDATE SET ra_game_id = excluded.ra_game_id;
        """, (consola_id, titulo, ra_game_id))
        conn.commit()

# --- AJUSTES SIMPLES (tabla 'configuracion') ---

def obtener_config(clave, defecto=""):
    with obtener_conexion() as conn:
        fila = conn.execute("SELECT valor FROM configuracion WHERE clave = ?;", (clave,)).fetchone()
    return fila[0] if fila else defecto

def guardar_config(clave, valor):
    with obtener_conexion() as conn:
        conn.execute("""
            INSERT INTO configuracion (clave, valor) VALUES (?, ?)
            ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor;
        """, (clave, str(valor)))
        conn.commit()

# --- AJUSTES POR CUENTA ---

def _clave_usuario(clave):
    return f"u:{contexto.usuario_id()}:{clave}"

def obtener_config_usuario(clave, defecto=""):
    """Ajuste personal de la cuenta con sesión iniciada (no se comparte entre cuentas)."""
    return obtener_config(_clave_usuario(clave), defecto)

def guardar_config_usuario(clave, valor):
    guardar_config(_clave_usuario(clave), valor)

def adoptar_datos_antiguos(usuario_id):
    """Antes los ajustes y opiniones eran de todo el equipo. La primera cuenta que entra
    después de esta actualización se queda con lo que ya existía; el resto empieza limpio.
    Devuelve True si hizo la migración."""
    if not usuario_id or obtener_config("migracion_cuentas_v1", ""):
        return False
    with obtener_conexion() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO opiniones_cuenta
                (usuario_id, consola_id, titulo, puntuacion, texto, actualizado)
            SELECT ?, consola_id, titulo, puntuacion, texto, actualizado FROM opiniones;
        """, (usuario_id,))
        fila = conn.execute("SELECT valor FROM configuracion WHERE clave = 'compartir_actividad';").fetchone()
        if fila:
            conn.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES (?, ?);",
                         (f"u:{usuario_id}:compartir_actividad", fila[0]))
        conn.commit()
    guardar_config("migracion_cuentas_v1", usuario_id)
    return True

class LocalDB:
    def __init__(self):
        inicializar_db_local()

    def obtener_todos_los_juegos(self):
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT MIN(j.id) as id, j.titulo, j.ruta_rom, j.portada_path, j.favorito, c.nombre
                FROM juegos j
                JOIN consolas c ON j.consola_id = c.id
                GROUP BY j.titulo, j.consola_id;
            """)
            filas = cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "title": r[1],
                    "ruta_rom": r[2],
                    "portada_path": r[3],
                    "favorito": bool(r[4]),
                    "console": r[5]
                } for r in filas
            ]

    def obtener_consolas(self):
        """Retorna la lista de consolas registradas en la base de datos local."""
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        cursor.execute("SELECT id, nombre, identificativo, extensiones, ruta_roms FROM consolas ORDER BY nombre ASC")
        filas = cursor.fetchall()
        conexion.close()

        consolas = []
        for fila in filas:
            consolas.append({
                "id": fila[0],
                "nombre": fila[1],
                "identificativo": fila[2],
                "extensiones": fila[3],
                "ruta_roms": fila[4]
            })
        return consolas

    def obtener_juegos_filtrados(self, texto_busqueda="", consola_id=None):
        """Retorna los juegos aplicando filtros por nombre y/o consola agrupados, incluyendo portada."""
        conexion = obtener_conexion()
        cursor = conexion.cursor()

        query = """
            SELECT MIN(j.id) as id, j.titulo, j.ruta_rom, j.consola_id, c.nombre AS nombre_consola, COUNT(j.id) as total_variantes, MAX(j.portada_path) as portada_path
            FROM juegos j
            JOIN consolas c ON j.consola_id = c.id
            WHERE 1=1
        """
        parametros = []

        if consola_id and str(consola_id).lower() != "todas":
            query += " AND j.consola_id = ?"
            parametros.append(consola_id)

        if texto_busqueda:
            query += " AND j.titulo LIKE ?"
            parametros.append(f"%{texto_busqueda.strip()}%")

        query += " GROUP BY j.titulo, j.consola_id ORDER BY j.titulo ASC"

        cursor.execute(query, parametros)
        filas = cursor.fetchall()
        conexion.close()

        juegos = []
        for fila in filas:
            juegos.append({
                "id": fila[0],
                "titulo": fila[1],
                "nombre": fila[1],
                "ruta_rom": fila[2],
                "consola_id": fila[3],
                "nombre_consola": fila[4],
                "total_variantes": fila[5],
                "portada_path": fila[6]
            })

        return juegos

if __name__ == "__main__":
    inicializar_db_local()
    print("Base de datos local actualizada e inicializada con todas las consolas.")