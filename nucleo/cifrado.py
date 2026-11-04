"""
cifrado.py - Llaves del cifrado de extremo a extremo de los chats.

Cada cuenta tiene un par de llaves que sale de una frase de 12 palabras:
  - la llave pública se guarda en Supabase, para que otros puedan cifrar mensajes para ti;
  - la privada no sale nunca de este equipo; se recupera en otro escribiendo la frase.
Si alguien pierde la frase y todos sus equipos, nadie puede recuperar sus chats: no hay copia en el servidor.
"""
import json
import secrets
import unicodedata

from mnemonic import Mnemonic
from nacl.encoding import Base64Encoder, RawEncoder
from nacl.exceptions import CryptoError
from nacl.hash import blake2b
from nacl.public import Box, PrivateKey, PublicKey

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


class SinLlave(Exception):
    """Falta una llave para enviar el mensaje. 'propia' indica que falta activar la de este equipo."""
    def __init__(self, texto, propia=False):
        super().__init__(texto)
        self.propia = propia


TIPOS_CIFRADOS = ("texto",)   # lo que trae un mensaje viene de otra persona: solo se aceptan estos tipos
ILEGIBLE_OTRA_FRASE = "🔒 No se puede leer este mensaje: se cifró con otra frase de recuperación."
ILEGIBLE_SIN_FRASE = "🔒 Escribí tu frase de recuperación para leer este mensaje."
ILEGIBLE_DANADO = "🔒 No se puede leer este mensaje: llegó dañado o alterado."


def _b64(datos):
    return Base64Encoder.encode(datos).decode()


def cifrar_para(privada, su_publica, de, tipo, contenido):
    """Arma el texto que se guarda: 'e1:llave del emisor:llave del receptor:datos cifrados'.
    Lleva ambas llaves para seguir legible aunque alguien cambie su frase más adelante."""
    interior = json.dumps({"de": de, "tipo": tipo, "contenido": contenido}, ensure_ascii=False).encode()
    datos = Box(privada, PublicKey(su_publica, Base64Encoder)).encrypt(interior)
    return f"e1:{_b64(bytes(privada.public_key))}:{su_publica}:{_b64(bytes(datos))}"


def descifrar_de(privada, de, guardado):
    """Devuelve (tipo, contenido). Ambos sentidos comparten clave: 'de' adentro impide presentar
    un mensaje mío como si lo hubiera escrito la otra persona."""
    try:
        version, emisor, receptor, datos = guardado.split(":")
        mia = _b64(bytes(privada.public_key))
        if version != "e1" or mia not in (emisor, receptor):
            return "texto", ILEGIBLE_OTRA_FRASE
        otra = receptor if mia == emisor else emisor
        interior = json.loads(Box(privada, PublicKey(otra, Base64Encoder)).decrypt(datos, encoder=Base64Encoder))
        if interior["de"] == de and interior["tipo"] in TIPOS_CIFRADOS and isinstance(interior["contenido"], str):
            return interior["tipo"], interior["contenido"]
    except (ValueError, KeyError, TypeError, CryptoError, AttributeError):
        pass
    return "texto", ILEGIBLE_DANADO


# Pasos para crear, recuperar y publicar las llaves de la cuenta activa.
class Llaves:
    # Reutiliza la sesión de CloudClient.
    def __init__(self, cloud):
        self.cloud = cloud
        self.pendiente = None   # (entropía, reemplazar): frase mostrada que aún no se confirmó
        self.visible = None     # entropía de "Ver mi frase", ya verificada con la contraseña
        self._privada = None    # (cuenta, llave): evita ir al llavero por cada mensaje

    # Se separa por cuenta. Cerrar sesión no la borra: sin ella, quien perdió la frase perdería sus chats.
    def _nombre(self):
        return f"llave_{self.cloud._yo()}"

    def _local(self):
        try:
            return bytes.fromhex(session_store.cargar(self._nombre())["entropia"])
        except (TypeError, KeyError, ValueError):
            return None

    def _guardar(self, entropia):
        self._privada = None
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

    def _privada_actual(self):
        if not self._privada or self._privada[0] != self.cloud._yo():
            local = self._local()
            self._privada = (self.cloud._yo(), privada_de(local) if local else None)
        return self._privada[1]

    def cifrar(self, amigo, tipo, contenido):
        """Cifra para ese amigo con su llave publicada. Sin llaves no se envía: nunca cae a texto sin cifrar."""
        privada = self._privada_actual()
        if not privada:
            raise SinLlave("Para enviar mensajes, primero activá tu frase de recuperación.", propia=True)
        res = self.cloud.client.table("profiles").select("llave_publica").eq("id", amigo).execute()
        su_publica = res.data[0]["llave_publica"] if res.data else None
        if not su_publica:
            raise SinLlave("Esta persona todavía no activó sus mensajes privados. Pedile que actualice la app.")
        return cifrar_para(privada, su_publica, self.cloud._yo(), tipo, contenido)

    def abrir(self, mensaje):
        """El mensaje listo para mostrar: si está cifrado, reemplaza su tipo y contenido por los reales."""
        if mensaje.get("tipo") != "cifrado":
            return mensaje
        privada = self._privada_actual()
        tipo, contenido = descifrar_de(privada, mensaje["de"], mensaje["contenido"]) if privada else ("texto", ILEGIBLE_SIN_FRASE)
        return {**mensaje, "tipo": tipo, "contenido": contenido}

    def ver_frase(self, password):
        """Las 12 palabras de este equipo. Pide la contraseña porque dan acceso a todos los chats."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        local = self._local()
        if not local:
            return {"exito": False, "error": "Esta cuenta no tiene una frase activa en este equipo."}
        error = self.cloud.verificar_contrasena(password)
        if error:
            return {"exito": False, "error": error}
        self.visible = local
        return {"exito": True, "palabras": frase_de(local)}

    def texto_para_archivo(self):
        """Contenido del archivo con la frase en pantalla, o None si no hay ninguna."""
        entropia = self.pendiente[0] if self.pendiente else self.visible
        if not entropia:
            return None
        lineas = [f"{i:2}. {p}" for i, p in enumerate(frase_de(entropia), 1)]
        return ("Frase de recuperación de RetroEmulator\n"
                "Quien tenga estas palabras puede leer tus chats. No se las des a nadie.\n\n"
                + "\n".join(lineas) + "\n")

    def olvidar_en_pantalla(self):
        self.pendiente = self.visible = None

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
