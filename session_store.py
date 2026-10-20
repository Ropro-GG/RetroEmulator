"""
session_store.py - Guarda datos sensibles fuera de la base de datos y del código:
  - la sesión recordada de Supabase ("Recuérdame")
  - las credenciales de RetroAchievements

Usa el llavero del sistema si está disponible (paquete opcional 'keyring':
pip install keyring) y, si no, un archivo con permisos 600 en la carpeta de
configuración del usuario (~/.config/RetroEmulator/ en Linux).
"""
import json
import os

try:
    import keyring
except Exception:  # keyring no instalado
    keyring = None

SERVICIO = "RetroEmulator"


def _carpeta():
    base = (os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME")
            or os.path.join(os.path.expanduser("~"), ".config"))
    return os.path.join(base, "RetroEmulator")


def _ruta(nombre):
    return os.path.join(_carpeta(), f"{nombre}.json")


def _borrar_archivo(nombre):
    try:
        os.remove(_ruta(nombre))
    except OSError:
        pass


def guardar(nombre, datos):
    """Guarda un dict bajo 'nombre'. Devuelve True si se pudo guardar."""
    texto = json.dumps(datos)
    if keyring is not None:
        try:
            keyring.set_password(SERVICIO, nombre, texto)
            _borrar_archivo(nombre)
            return True
        except Exception:
            pass  # sin llavero disponible: se usa el archivo

    try:
        os.makedirs(_carpeta(), exist_ok=True)
        ruta = _ruta(nombre)
        fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
        os.chmod(ruta, 0o600)
        return True
    except OSError as e:
        print(f"[STORE] No se pudo guardar '{nombre}': {e}")
        return False


def cargar(nombre):
    """Devuelve el dict guardado bajo 'nombre' o None."""
    if keyring is not None:
        try:
            texto = keyring.get_password(SERVICIO, nombre)
            if texto:
                return json.loads(texto)
        except Exception:
            pass
    try:
        with open(_ruta(nombre), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def borrar(nombre):
    if keyring is not None:
        try:
            keyring.delete_password(SERVICIO, nombre)
        except Exception:
            pass
    _borrar_archivo(nombre)
