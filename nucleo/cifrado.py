"""
cifrado.py - Llaves del cifrado de extremo a extremo de los chats.

Cada cuenta tiene un par de llaves que sale de una frase de 12 palabras:
  - la llave pública se guarda en Supabase, para que otros puedan cifrar mensajes para ti;
  - la privada no sale nunca de este equipo; se recupera en otro escribiendo la frase.
Si alguien pierde la frase y todos sus equipos, nadie puede recuperar sus chats: no hay copia en el servidor.
"""
import secrets
import unicodedata

from mnemonic import Mnemonic
from nacl.encoding import Base64Encoder, RawEncoder
from nacl.hash import blake2b
from nacl.public import PrivateKey

from . import session_store

_BIP39 = Mnemonic("spanish")


# Permite escribir la frase sin acentos y con cualquier combinación de mayúsculas.
def _sin_acentos(palabra):
    return "".join(c for c in unicodedata.normalize("NFD", palabra) if not unicodedata.combining(c)).lower()


_PALABRAS = {_sin_acentos(p): p for p in _BIP39.wordlist}


def frase_de(entropia):
    """Las 12 palabras que representan 16 bytes aleatorios."""
    return [unicodedata.normalize("NFC", p) for p in _BIP39.to_mnemonic(entropia).split()]


def entropia_de(texto):
    """Convierte la frase escrita en sus 16 bytes. La última palabra detecta errores de tipeo (ValueError)."""
    palabras = (texto or "").split()
    if len(palabras) != 12:
        raise ValueError("La frase debe tener 12 palabras.")
    try:
        return bytes(_BIP39.to_entropy(" ".join(_PALABRAS[_sin_acentos(p)] for p in palabras)))
    except KeyError:
        raise ValueError("Hay una palabra que no pertenece a la lista. Revisá lo que escribiste.") from None
    except ValueError:
        raise ValueError("La frase no es válida. Revisá las palabras y su orden.") from None


def privada_de(entropia):
    """La llave privada de esa frase. La frase ya es aleatoria (128 bits): no hace falta un derivado lento."""
    return PrivateKey(blake2b(entropia, digest_size=32, person=b"retroemu-chat", encoder=RawEncoder))


def publica_de(entropia):
    """La llave pública de esa frase, en base64, como se guarda en Supabase."""
    return privada_de(entropia).public_key.encode(Base64Encoder).decode()


# Pasos para crear, recuperar y publicar las llaves de la cuenta activa.
class Llaves:
    # Reutiliza la sesión de CloudClient.
    def __init__(self, cloud):
        self.cloud = cloud
        self.pendiente = None   # (entropía, reemplazar): frase mostrada que aún no se confirmó

    # Se separa por cuenta. Cerrar sesión no la borra: sin ella, quien perdió la frase perdería sus chats.
    def _nombre(self):
        return f"llave_{self.cloud._yo()}"

    def _local(self):
        try:
            return bytes.fromhex(session_store.cargar(self._nombre())["entropia"])
        except (TypeError, KeyError, ValueError):
            return None

    def _guardar(self, entropia):
        return session_store.guardar(self._nombre(), {"entropia": entropia.hex()})

    def _en_servidor(self):
        res = self.cloud.client.table("profiles").select("llave_publica").eq("id", self.cloud._yo()).execute()
        return res.data[0]["llave_publica"] if res.data else None

    # Sin 'reemplazar' nunca pisa una llave existente: otro equipo pudo crearla mientras tanto.
    def _publicar(self, publica, reemplazar=False):
        consulta = self.cloud.client.table("profiles").update({"llave_publica": publica}).eq("id", self.cloud._yo())
        if not reemplazar:
            consulta = consulta.is_("llave_publica", "null")
        return bool(consulta.execute().data)

    def estado(self):
        """'lista', 'crear' o 'recuperar'. Si no se puede leer el servidor falla: sin conexión no se crea nada."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        try:
            servidor = self._en_servidor()
            local = self._local()
            if local and not servidor:
                self._publicar(publica_de(local))   # si falla, se reintenta en el próximo inicio
                return {"exito": True, "estado": "lista"}
            if local and publica_de(local) == servidor:
                return {"exito": True, "estado": "lista"}
            if servidor:
                return {"exito": True, "estado": "recuperar", "cambio": bool(local)}
            return {"exito": True, "estado": "crear"}
        except Exception as e:
            return {"exito": False, "error": self.cloud._error_social(e)}

    def generar(self, reemplazar=False):
        """Crea una frase nueva y la devuelve para mostrarla. No cambia nada hasta confirmarla."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        entropia = secrets.token_bytes(16)
        self.pendiente = (entropia, bool(reemplazar))
        return {"exito": True, "palabras": frase_de(entropia)}

    def confirmar(self, texto):
        """Activa la frase cuando el usuario demuestra que la anotó."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        if not self.pendiente:
            return {"exito": False, "error": "Volvé a empezar: no hay ninguna frase pendiente."}
        entropia, reemplazar = self.pendiente
        try:
            if entropia_de(texto) != entropia:
                return {"exito": False, "error": "La frase no coincide con la que te mostramos."}
        except ValueError as e:
            return {"exito": False, "error": str(e)}
        try:
            # Primero se publica: si falla no cambió nada, y si luego falla el guardado, la frase anotada lo repara.
            if not self._publicar(publica_de(entropia), reemplazar):
                self.pendiente = None
                return {"exito": False, "error": "Esta cuenta ya tiene una frase creada en otro equipo. Reiniciá la app y escribila."}
        except Exception as e:
            return {"exito": False, "error": self.cloud._error_social(e)}
        self.pendiente = None
        if not self._guardar(entropia):
            return {"exito": False, "error": "No se pudo guardar la llave en este equipo. Reiniciá la app y escribí tu frase."}
        return {"exito": True}

    def recuperar(self, texto):
        """Trae la llave a este equipo, solo si la frase corresponde a la publicada."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        try:
            entropia = entropia_de(texto)
        except ValueError as e:
            return {"exito": False, "error": str(e)}
        try:
            if publica_de(entropia) != self._en_servidor():
                return {"exito": False, "error": "Esa frase no corresponde a esta cuenta."}
        except Exception as e:
            return {"exito": False, "error": self.cloud._error_social(e)}
        if not self._guardar(entropia):
            return {"exito": False, "error": "No se pudo guardar la llave en este equipo."}
        return {"exito": True}
