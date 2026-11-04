"""
cifrado.py - Llaves del cifrado de extremo a extremo de los chats.

Cada cuenta tiene un par de llaves que sale de una frase de 12 palabras:
  - la llave pública se guarda en Supabase, para que otros puedan cifrar mensajes para ti;
  - la privada no sale nunca de este equipo; se recupera en otro escribiendo la frase.
Si alguien pierde la frase y todos sus equipos, nadie puede recuperar sus chats: no hay copia en el servidor.
"""
import base64
import json
import re
import secrets
import unicodedata

from mnemonic import Mnemonic
from nacl.encoding import Base64Encoder, RawEncoder
from nacl.exceptions import CryptoError
from nacl.hash import blake2b
from nacl.public import Box, PrivateKey, PublicKey
from nacl.secret import SecretBox

from . import db_local, gifs, session_store

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


class LlaveCambiada(SinLlave):
    """La llave publicada de un amigo no es la aceptada: podría ser un cambio legítimo o alguien haciéndose pasar por él."""


TIPOS_ADJUNTO = ("imagen", "sticker")
ILEGIBLE_OTRA_FRASE = "🔒 No se puede leer este mensaje: se cifró con otra frase de recuperación."
ILEGIBLE_SIN_FRASE = "🔒 Escribí tu frase de recuperación para leer este mensaje."
ILEGIBLE_DANADO = "🔒 No se puede leer este mensaje: llegó dañado o alterado."
ILEGIBLES = (ILEGIBLE_OTRA_FRASE, ILEGIBLE_SIN_FRASE, ILEGIBLE_DANADO)


def _b64(datos):
    return Base64Encoder.encode(datos).decode()


def codigo_seguridad(id_a, publica_a, id_b, publica_b):
    """30 dígitos, iguales para ambas personas. Si coinciden por otra vía, nadie reemplazó las llaves."""
    partes = sorted((f"{id_a}:{publica_a}", f"{id_b}:{publica_b}"))
    resumen = blake2b("|".join(partes).encode(), digest_size=32, person=b"retroemu-codigo", encoder=RawEncoder)
    digitos = str(int.from_bytes(resumen, "big") % 10 ** 30).zfill(30)
    return " ".join(digitos[i:i + 5] for i in range(0, 30, 5))


def _contenido_valido(de, tipo, contenido):
    """Lo que trae un mensaje viene de otra persona, y el servidor ya no puede revisarlo: se revisa aquí."""
    if not isinstance(contenido, str):
        return False
    if tipo == "texto":
        return True
    if tipo == "gif":
        return gifs.url_permitida(contenido)
    if tipo == "publicacion":
        return re.fullmatch(r"[0-9]{1,18}", contenido) is not None
    if tipo in TIPOS_ADJUNTO:
        return re.fullmatch(re.escape(str(de)) + r"/cifrados/[0-9a-f]{32}\.bin", contenido) is not None
    return False


def cifrar_archivo(datos):
    """Cifra un archivo con una llave nueva, que viaja dentro del mensaje. Devuelve (llave, datos cifrados)."""
    llave = secrets.token_bytes(SecretBox.KEY_SIZE)
    return llave, bytes(SecretBox(llave).encrypt(datos))


def cifrar_para(privada, su_publica, de, tipo, contenido, llave=None):
    """Arma el texto que se guarda: 'e1:llave del emisor:llave del receptor:datos cifrados'.
    Lleva ambas llaves para seguir legible aunque alguien cambie su frase más adelante."""
    campos = {"de": de, "tipo": tipo, "contenido": contenido}
    if llave:
        campos["llave"] = _b64(llave)
    interior = json.dumps(campos, ensure_ascii=False).encode()
    datos = Box(privada, PublicKey(su_publica, Base64Encoder)).encrypt(interior)
    return f"e1:{_b64(bytes(privada.public_key))}:{su_publica}:{_b64(bytes(datos))}"


def descifrar_de(privada, de, guardado, adjunto=None, adjuntos=None):
    """Devuelve (tipo, contenido). Ambos sentidos comparten clave: 'de' adentro impide presentar
    un mensaje mío como si lo hubiera escrito la otra persona. La llave de un archivo se anota en 'adjuntos'."""
    try:
        version, emisor, receptor, datos = guardado.split(":")
        mia = _b64(bytes(privada.public_key))
        if version != "e1" or mia not in (emisor, receptor):
            return "texto", ILEGIBLE_OTRA_FRASE
        otra = receptor if mia == emisor else emisor
        interior = json.loads(Box(privada, PublicKey(otra, Base64Encoder)).decrypt(datos, encoder=Base64Encoder))
        return _interior_valido(interior, de, adjunto, adjuntos)
    except (ValueError, KeyError, TypeError, CryptoError, AttributeError):
        return "texto", ILEGIBLE_DANADO


def _interior_valido(interior, de, adjunto, adjuntos):
    """(tipo, contenido) del mensaje ya abierto, si coincide con la fila y su contenido es válido."""
    tipo, contenido = interior["tipo"], interior["contenido"]
    if interior["de"] == de and _contenido_valido(de, tipo, contenido):
        if tipo not in TIPOS_ADJUNTO:
            return tipo, contenido
        if contenido == adjunto:
            llave = base64.b64decode(interior["llave"], validate=True)
            if adjuntos is not None:
                adjuntos[contenido] = llave
            return tipo, contenido
    return "texto", ILEGIBLE_DANADO


def cifrar_para_grupo(privada, publicas, de, grupo, tipo, contenido, llave=None):
    """Cifra con una llave nueva y la guarda aparte para cada persona: quien entra después no lee lo anterior
    y quien sale no lee lo nuevo. Cada copia va sellada por el emisor, así nadie del grupo puede imitarlo.
    Devuelve ('e2:llave del emisor:datos', {usuario: 'su llave:copia sellada'})."""
    campos = {"de": de, "grupo": grupo, "tipo": tipo, "contenido": contenido}
    if llave:
        campos["llave"] = _b64(llave)
    secreta = secrets.token_bytes(SecretBox.KEY_SIZE)
    datos = SecretBox(secreta).encrypt(json.dumps(campos, ensure_ascii=False).encode())
    copias = {usuario: f"{publica}:{_b64(bytes(Box(privada, PublicKey(publica, Base64Encoder)).encrypt(secreta)))}"
              for usuario, publica in publicas.items()}
    return f"e2:{_b64(bytes(privada.public_key))}:{_b64(bytes(datos))}", copias


def descifrar_de_grupo(privada, yo, de, grupo, guardado, copias, adjunto=None, adjuntos=None):
    """Devuelve (tipo, contenido). 'grupo' adentro impide reenviar un mensaje a otro grupo."""
    try:
        version, emisor, datos = guardado.split(":")
        mi_publica, copia = copias[yo].split(":")
        if version != "e2":
            return "texto", ILEGIBLE_DANADO
        if mi_publica != _b64(bytes(privada.public_key)):
            return "texto", ILEGIBLE_OTRA_FRASE
        secreta = Box(privada, PublicKey(emisor, Base64Encoder)).decrypt(copia, encoder=Base64Encoder)
        interior = json.loads(SecretBox(secreta).decrypt(datos, encoder=Base64Encoder))
        if interior["grupo"] != grupo:
            return "texto", ILEGIBLE_DANADO
        return _interior_valido(interior, de, adjunto, adjuntos)
    except (ValueError, KeyError, TypeError, CryptoError, AttributeError):
        return "texto", ILEGIBLE_DANADO


# Pasos para crear, recuperar y publicar las llaves de la cuenta activa.
class Llaves:
    # Reutiliza la sesión de CloudClient.
    def __init__(self, cloud):
        self.cloud = cloud
        self.pendiente = None   # (entropía, reemplazar): frase mostrada que aún no se confirmó
        self.visible = None     # entropía de "Ver mi frase", ya verificada con la contraseña
        self._privada = None    # (cuenta, llave): evita ir al llavero por cada mensaje
        self.adjuntos = {}      # ruta -> llave de los archivos de los mensajes ya abiertos; nunca llega al JS
        self._senal = (None, {})   # (llamada, {amigo: llave}): evita consultar la llave en cada señal

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

    def _publicada(self, amigo):
        res = self.cloud.client.table("profiles").select("llave_publica").eq("id", amigo).execute()
        return res.data[0]["llave_publica"] if res.data else None

    def _actual_o_primera(self, amigo, publicada):
        """La llave aceptada de ese amigo. La primera que se ve se acepta sola: no hay con qué compararla."""
        conocidas = db_local.llaves_de_amigo(self.cloud._yo(), amigo)
        if not conocidas:
            db_local.aceptar_llave_amigo(self.cloud._yo(), amigo, publicada)
            return publicada
        return next((llave for llave, (actual, _) in conocidas.items() if actual), None)

    def _llave_no_aceptada(self, mensaje, privada):
        """True si el mensaje usa otra llave que las aceptadas. Con ella se podría falsificar en ambos sentidos."""
        try:
            yo = self.cloud._yo()
            amigo = mensaje["para"] if mensaje["de"] == yo else mensaje["de"]
            _, emisor, receptor, _ = mensaje["contenido"].split(":")
            otra = receptor if _b64(bytes(privada.public_key)) == emisor else emisor
            publicada = None if db_local.llaves_de_amigo(yo, amigo) else self._publicada(amigo)
            if publicada:
                self._actual_o_primera(amigo, publicada)
            return otra not in db_local.llaves_de_amigo(yo, amigo)
        except Exception as e:
            print(f"[CIFRADO] No se pudo revisar la llave: {e}")   # sin conexión no hay con qué comparar
            return False

    def estado_amigo(self, amigo):
        """'confirmada', 'cambio' o 'sin_llave', con el código de seguridad de la llave publicada."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        try:
            publicada = self._publicada(amigo)
            if not publicada:
                return {"exito": True, "estado": "sin_llave", "verificada": False, "codigo": None}
            actual = self._actual_o_primera(amigo, publicada)
            conocida = db_local.llaves_de_amigo(self.cloud._yo(), amigo).get(publicada, (False, False))
            return {"exito": True, "estado": "confirmada" if actual == publicada else "cambio",
                    "verificada": actual == publicada and conocida[1], "codigo": self._codigo(amigo, publicada)}
        except Exception as e:
            return {"exito": False, "error": self.cloud._error_social(e)}

    def _codigo(self, amigo, publica):
        privada = self._privada_actual()
        return codigo_seguridad(self.cloud._yo(), _b64(bytes(privada.public_key)), amigo, publica) if privada else None

    def _publicada_con_codigo(self, amigo, codigo):
        """La llave publicada, solo si sigue siendo la del código que vio el usuario."""
        publicada = self._publicada(amigo)
        if not publicada or not codigo or self._codigo(amigo, publicada) != codigo:
            raise SinLlave("La llave volvió a cambiar. Revisá el código de nuevo.")
        return publicada

    def aceptar_amigo(self, amigo, codigo):
        """Acepta la llave nueva de un amigo. Solo lo hace el usuario, y queda sin verificar."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        try:
            db_local.aceptar_llave_amigo(self.cloud._yo(), amigo, self._publicada_con_codigo(amigo, codigo))
            return {"exito": True}
        except SinLlave as e:
            return {"exito": False, "error": str(e)}
        except Exception as e:
            return {"exito": False, "error": self.cloud._error_social(e)}

    def verificar_amigo(self, amigo, codigo, verificada):
        """Recuerda si el usuario comparó el código. Solo sirve para la llave ya aceptada."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        try:
            publicada = self._publicada_con_codigo(amigo, codigo)
            if self._actual_o_primera(amigo, publicada) != publicada:
                return {"exito": False, "error": "Primero aceptá la llave nueva."}
            db_local.marcar_llave_verificada(self.cloud._yo(), amigo, publicada, verificada)
            return {"exito": True}
        except SinLlave as e:
            return {"exito": False, "error": str(e)}
        except Exception as e:
            return {"exito": False, "error": self.cloud._error_social(e)}

    def _publica_de_llamada(self, llamada, amigo):
        """Llave aceptada de quien participa. Si cambió, la llamada no se conecta hasta aceptarla en el chat."""
        if self._senal[0] != llamada:
            self._senal = (llamada, {})
        conocidas = self._senal[1]
        if amigo not in conocidas:
            publicada = self._publicada(amigo)
            if not publicada:
                raise SinLlave("Una persona de la llamada todavía no activó sus mensajes privados.")
            if self._actual_o_primera(amigo, publicada) != publicada:
                raise LlaveCambiada("La llave de una persona de la llamada cambió. Revisá el aviso en su chat.")
            conocidas[amigo] = publicada
        return conocidas[amigo]

    def _caja_de_llamada(self, llamada, amigo):
        privada = self._privada_actual()
        if not privada:
            raise SinLlave("Para hacer llamadas, primero activá tu frase de recuperación.", propia=True)
        return Box(privada, PublicKey(self._publica_de_llamada(llamada, amigo), Base64Encoder))

    def sellar_senal(self, llamada, amigo, datos):
        """Sella los datos de conexión para una persona. Incluyen la huella que protege el audio y el video:
        si el servidor pudiera cambiarla, podría ponerse en medio de la llamada."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        try:
            interior = json.dumps({"llamada": llamada, "de": self.cloud._yo(), "para": amigo, "datos": datos}).encode()
            return {"exito": True, "sellada": _b64(bytes(self._caja_de_llamada(llamada, amigo).encrypt(interior)))}
        except SinLlave as e:
            return {"exito": False, "error": str(e), "falta_mi_llave": e.propia}
        except Exception as e:
            return {"exito": False, "error": self.cloud._error_social(e)}

    def abrir_senal(self, llamada, de, sellada):
        """Devuelve los datos si vienen de esa persona, para mí y para esta llamada."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        try:
            interior = json.loads(self._caja_de_llamada(llamada, de).decrypt(sellada, encoder=Base64Encoder))
            if (interior["llamada"], interior["de"], interior["para"]) != (llamada, de, self.cloud._yo()):
                return {"exito": False, "error": "Se rechazó una señal que no era para esta llamada."}
            return {"exito": True, "datos": interior["datos"]}
        except SinLlave as e:
            return {"exito": False, "error": str(e), "falta_mi_llave": e.propia}
        except (CryptoError, ValueError, KeyError, TypeError):
            return {"exito": False, "error": "Se rechazó una señal alterada o de otra persona."}
        except Exception as e:
            return {"exito": False, "error": self.cloud._error_social(e)}

    def _llave_propia(self):
        """Llave de lo que solo ve su dueño (la colección de stickers). Cambia junto con la frase."""
        privada = self._privada_actual()
        if not privada:
            raise SinLlave("Para guardar stickers, primero activá tu frase de recuperación.", propia=True)
        return blake2b(bytes(privada), digest_size=SecretBox.KEY_SIZE, person=b"retroemu-sticker", encoder=RawEncoder)

    def cifrar_propio(self, datos):
        return bytes(SecretBox(self._llave_propia()).encrypt(datos))

    def descifrar_archivo(self, ruta, datos):
        """Los archivos viejos (sin .bin) se devuelven como están. None si no se puede abrir."""
        if not ruta.endswith(".bin"):
            return datos
        try:
            llave = self._llave_propia() if "/stickers/" in ruta else self.adjuntos[ruta]
            return SecretBox(llave).decrypt(datos)
        except (KeyError, SinLlave, CryptoError, ValueError, TypeError):
            return None

    def cifrar(self, amigo, tipo, contenido, llave=None):
        """Cifra para ese amigo con su llave publicada. Sin llaves no se envía: nunca cae a texto sin cifrar."""
        privada = self._privada_actual()
        if not privada:
            raise SinLlave("Para enviar mensajes, primero activá tu frase de recuperación.", propia=True)
        su_publica = self._publicada(amigo)
        if not su_publica:
            raise SinLlave("Esta persona todavía no activó sus mensajes privados. Pedile que actualice la app.")
        if self._actual_o_primera(amigo, su_publica) != su_publica:
            raise LlaveCambiada("La llave de esta persona cambió. Revisá el aviso del chat antes de enviar.")
        return cifrar_para(privada, su_publica, self.cloud._yo(), tipo, contenido, llave)

    def abrir(self, mensaje):
        """El mensaje listo para mostrar: si está cifrado, reemplaza su tipo y contenido por los reales."""
        if mensaje.get("tipo") != "cifrado":
            return mensaje
        privada = self._privada_actual()
        tipo, contenido = descifrar_de(privada, mensaje["de"], mensaje["contenido"], mensaje.get("adjunto"), self.adjuntos) \
            if privada else ("texto", ILEGIBLE_SIN_FRASE)
        legible = contenido not in ILEGIBLES
        return {**mensaje, "tipo": tipo, "contenido": contenido,
                "alerta_llave": legible and self._llave_no_aceptada(mensaje, privada)}

    def cifrar_grupo(self, grupo, miembros, tipo, contenido, llave=None):
        """Solo cifra para llaves aceptadas: quien tiene una llave sin aceptar o sin activar no recibe este mensaje."""
        privada = self._privada_actual()
        if not privada:
            raise SinLlave("Para enviar mensajes, primero activá tu frase de recuperación.", propia=True)
        yo = self.cloud._yo()
        filas = self.cloud.client.table("profiles").select("id, llave_publica").in_("id", miembros).execute().data or []
        publicas = {f["id"]: f["llave_publica"] for f in filas if f["id"] != yo and f.get("llave_publica")
                    and self._actual_o_primera(f["id"], f["llave_publica"]) == f["llave_publica"]}
        if not publicas:
            raise SinLlave("Nadie más del grupo puede recibir mensajes privados todavía.")
        publicas[yo] = _b64(bytes(privada.public_key))
        return cifrar_para_grupo(privada, publicas, yo, grupo, tipo, contenido, llave)

    def abrir_grupo(self, mensaje):
        """El mensaje de grupo listo para mostrar. Avisa si el emisor usó una llave que no se aceptó en este equipo."""
        privada = self._privada_actual()
        if not privada:
            return {**mensaje, "tipo": "texto", "contenido": ILEGIBLE_SIN_FRASE, "alerta_llave": False}
        yo, de = self.cloud._yo(), mensaje.get("de")
        tipo, contenido = descifrar_de_grupo(privada, yo, de, mensaje["grupo_id"], mensaje["contenido"],
                                             mensaje.get("llaves") or {}, mensaje.get("adjunto"), self.adjuntos)
        alerta = False
        if contenido not in ILEGIBLES and de != yo:
            try:
                publicada = None if db_local.llaves_de_amigo(yo, de) else self._publicada(de)
                if publicada:
                    self._actual_o_primera(de, publicada)
                alerta = mensaje["contenido"].split(":")[1] not in db_local.llaves_de_amigo(yo, de)
            except Exception as e:
                print(f"[CIFRADO] No se pudo revisar la llave: {e}")   # sin conexión no hay con qué comparar
        return {**mensaje, "tipo": tipo, "contenido": contenido, "alerta_llave": alerta}

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

    def cambiar_frase(self, password):
        """Empieza a cambiar la frase. Pide la contraseña porque los mensajes anteriores dejarán de poder leerse."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        error = self.cloud.verificar_contrasena(password)
        if error:
            return {"exito": False, "error": error}
        return self.generar(reemplazar=True)

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
