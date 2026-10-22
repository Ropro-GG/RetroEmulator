"""
contexto.py - Cuenta que tiene la sesión iniciada en esta ejecución.

Sirve para separar los datos por cuenta cuando se comparte el mismo equipo:
las configuraciones personales (privacidad), las opiniones y las credenciales de
RetroAchievements se guardan con el id de usuario, así al cambiar de cuenta no se
mezclan. Los juegos, los emuladores y las carátulas siguen siendo del equipo.
"""
import threading

_lock = threading.Lock()
_usuario_id = ""


def establecer(usuario_id):
    global _usuario_id
    with _lock:
        _usuario_id = usuario_id or ""


def usuario_id():
    with _lock:
        return _usuario_id
