# cloud_client.py - Todo lo que la app guarda o lee en Supabase, salvo las llamadas.
# Sesión de usuario, amigos, presencia, chat, stickers, deseados, opiniones, publicaciones
# y perfil. Los métodos devuelven {"exito": True, ...} o {"exito": False, "error": "..."}
# para que la interfaz pueda mostrar el mensaje. Los permisos reales los aplica Supabase (RLS).
import hashlib
import os
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from dotenv import load_dotenv
from supabase import create_client, Client
from supabase.lib.client_options import SyncClientOptions

from pathlib import Path

from . import cifrado, gifs, session_store
from .boxart import analizar_titulo

# El .env se busca junto a este archivo, sin importar desde dónde se ejecute la app
RUTA_ENV = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(RUTA_ENV)

# OJO: getenv recibe el NOMBRE de la variable (como está escrito en el .env), no su valor.
# Los valores reales van únicamente en el archivo .env.
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def clave_juego(identificativo, titulo):
    """Identifica un juego igual para todos los usuarios: consola + título normalizado
    (sin región, versión ni mayúsculas), así 'Silent Hill (USA)' y 'Silent Hill' coinciden."""
    base, _ = analizar_titulo(titulo or "")
    return f"{identificativo}|{base or (titulo or '').lower()}"


# Cliente único de Supabase; recuerda el usuario con la sesión iniciada.
class CloudClient:
    # Conecta al crear el objeto; la sesión se abre más tarde.
    def __init__(self):
        self.client: Client = None
        self.usuario_actual = None
        self._email_recordar = None   # correo con confirmación de "Recuérdame" pendiente
        self.llaves = cifrado.Llaves(self)
        self.conectar()

    def conectar(self):
        """Inicializa la conexión con el proyecto de Supabase."""
        try:
            if SUPABASE_URL and SUPABASE_KEY:
                self.client = create_client(SUPABASE_URL, SUPABASE_KEY)
                print("[CLOUD] Conexión exitosa con Supabase.")
            else:
                faltan = [n for n, v in (("SUPABASE_URL", SUPABASE_URL), ("SUPABASE_KEY", SUPABASE_KEY)) if not v]
                print(f"[CLOUD ADVERTENCIA] Falta(n) {', '.join(faltan)}. "
                      f"Se buscó el .env en: {RUTA_ENV} (existe: {RUTA_ENV.exists()})")
        except Exception as e:
            print(f"[CLOUD ERROR] Falló la conexión con Supabase: {e}")

    def registrar_usuario(self, email, password, username):
        """Registra un nuevo usuario en Supabase."""
        if not self.client:
            return {"exito": False, "error": "No hay conexión con la nube."}
        try:
            respuesta = self.client.auth.sign_up({
                "email": email,
                "password": password,
                "options": {
                    "data": {
                        "username": username
                    }
                }
            })
            if respuesta.user:
                self.usuario_actual = respuesta.user
                user_data = {
                    "id": respuesta.user.id,
                    "email": respuesta.user.email,
                    "user_metadata": respuesta.user.user_metadata
                }
                return {"exito": True, "usuario": user_data}
            return {"exito": False, "error": "No se pudo crear el usuario."}
        except Exception as e:
            return {"exito": False, "error": str(e)}

    # Datos del usuario que se envían a la interfaz.
    @staticmethod
    def _datos_usuario(user):
        return {"id": user.id, "email": user.email, "user_metadata": user.user_metadata}

    def iniciar_sesion(self, email, password, recordar=False):
        """Inicia sesión con correo y contraseña en Supabase.
        Si 'recordar' está activo se envía un código de confirmación al correo; la
        sesión solo se guarda en el equipo cuando ese código se verifica."""
        if not self.client:
            return {"exito": False, "error": "No hay conexión con la nube."}
        try:
            respuesta = self.client.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            if not respuesta.user:
                return {"exito": False, "error": "Credenciales inválidas."}

            self.usuario_actual = respuesta.user
            resultado = {"exito": True, "usuario": self._datos_usuario(respuesta.user),
                         "requiere_codigo": False}
            if recordar:
                envio = self._enviar_codigo_recordar(email)
                if envio is True:
                    resultado["requiere_codigo"] = True
                else:
                    resultado["aviso"] = envio
            else:
                session_store.borrar("sesion")   # sin "Recuérdame" no se conserva nada
            return resultado
        except Exception as e:
            return {"exito": False, "error": str(e)}

    def verificar_contrasena(self, password):
        """Devuelve None si es correcta o el error a mostrar. Usa un cliente aparte para no tocar la sesión abierta."""
        try:
            aparte = create_client(SUPABASE_URL, SUPABASE_KEY, options=SyncClientOptions(
                auto_refresh_token=False, persist_session=False))
            aparte.auth.sign_in_with_password({"email": self.usuario_actual.email, "password": password or ""})
            return None
        except Exception as e:
            if "invalid login" in str(e).lower():
                return "La contraseña no es correcta."
            return self._error_social(e)

    # --- SESIÓN RECORDADA ("Recuérdame") ---

    def _enviar_codigo_recordar(self, email):
        """Envía por correo un código de un solo uso. True si salió bien; si no, un texto de error."""
        try:
            self.client.auth.sign_in_with_otp({
                "email": email,
                "options": {"should_create_user": False}
            })
            self._email_recordar = email
            return True
        except Exception as e:
            return f"No se pudo enviar el correo de confirmación ({e}). Entraste igual, pero no se recordará la sesión."

    # Vuelve a enviar el código al mismo correo.
    def reenviar_codigo_recordar(self):
        if not self._email_recordar:
            return {"exito": False, "error": "No hay una confirmación pendiente."}
        envio = self._enviar_codigo_recordar(self._email_recordar)
        return {"exito": True} if envio is True else {"exito": False, "error": envio}

    def confirmar_recordar(self, codigo):
        """Verifica el código del correo y, si es válido, guarda la sesión en este equipo."""
        if not self.client or not self._email_recordar:
            return {"exito": False, "error": "No hay una confirmación pendiente."}
        try:
            r = self.client.auth.verify_otp({
                "email": self._email_recordar,
                "token": (codigo or "").strip(),
                "type": "email"
            })
            sesion = r.session or self.client.auth.get_session()
            if not r.user or not sesion:
                return {"exito": False, "error": "Código inválido o vencido."}
            self.usuario_actual = r.user
            session_store.guardar("sesion", {
                "refresh_token": sesion.refresh_token,
                "email": self._email_recordar
            })
            self._email_recordar = None
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": f"Código inválido o vencido ({e})."}

    def restaurar_sesion(self):
        """Al abrir la app: entra solo si hay una sesión recordada y todavía es válida."""
        datos = session_store.cargar("sesion")
        if not self.client or not datos or not datos.get("refresh_token"):
            return {"exito": False}
        try:
            r = self.client.auth.refresh_session(datos["refresh_token"])
            if r.user and r.session:
                self.usuario_actual = r.user
                # Supabase rota el refresh token: hay que guardar el nuevo
                session_store.guardar("sesion", {
                    "refresh_token": r.session.refresh_token,
                    "email": datos.get("email", "")
                })
                return {"exito": True, "usuario": self._datos_usuario(r.user)}
            return {"exito": False}
        except Exception as e:
            texto = str(e).lower()
            if "refresh token" in texto or "invalid" in texto or "expired" in texto:
                session_store.borrar("sesion")   # ya no sirve: se pide login normal
            return {"exito": False, "error": str(e)}

    # Borra la presencia, cierra la sesión y olvida la sesión recordada.
    def cerrar_sesion(self):
        self.limpiar_jugando()
        try:
            if self.client:
                self.client.auth.sign_out()
        except Exception:
            pass
        session_store.borrar("sesion")
        self.usuario_actual = None
        self._email_recordar = None
        return {"exito": True}

    # --- SOCIAL: AMIGOS Y "JUGANDO AHORA" ---

    VIGENCIA_PRESENCIA_HORAS = 8   # pasado este tiempo se ignora un "jugando" que quedó colgado

    # Convierte un error técnico en un mensaje comprensible.
    @staticmethod
    def _error_social(e):
        texto = str(e)
        bajo = texto.lower()
        if "does not exist" in bajo or "could not find the table" in bajo or "schema cache" in bajo or "pgrst205" in bajo:
            return "Faltan las tablas de Social en Supabase."
        if "jwt expired" in bajo or "invalid jwt" in bajo or "pgrst303" in bajo:
            return "Tu sesión venció. Cerrá sesión y volvé a iniciarla."
        if "permission denied" in bajo or "row-level security" in bajo or "42501" in bajo:
            return "Supabase rechazó la operación por permisos."
        if any(x in bajo for x in ("name resolution", "connecterror", "connection", "timed out",
                                   "timeout", "unreachable", "temporary failure")):
            return "No se pudo conectar con el servidor. Revisá tu conexión a internet."
        return texto

    # Id del usuario actual, o None sin sesión.
    def _yo(self):
        return self.usuario_actual.id if self.usuario_actual else None

    # Devuelve el error a mostrar si falta conexión o sesión; si no, None.
    def _requiere_sesion(self):
        if not self.client:
            return {"exito": False, "error": "No hay conexión con la nube (revisá el archivo .env)."}
        if not self.usuario_actual:
            return {"exito": False, "error": "Debes iniciar sesión."}
        return None

    def _amistades(self):
        """Filas de 'friendships' donde participa el usuario actual."""
        yo = self._yo()
        res = self.client.table("friendships") \
            .select("id, requester_id, addressee_id, status") \
            .or_(f"requester_id.eq.{yo},addressee_id.eq.{yo}") \
            .execute()
        return res.data or []

    # Nombre y foto de varios usuarios de una sola vez.
    def _perfiles_por_id(self, ids):
        if not ids:
            return {}
        res = self.client.table("profiles").select("id, username, avatar_url").in_("id", list(ids)).execute()
        return {p["id"]: p for p in (res.data or [])}

    def _vigente(self, desde):
        """False para un aviso viejo que quedó colgado (por ejemplo tras un cierre brusco)."""
        try:
            momento = datetime.fromisoformat(str(desde).replace("Z", "+00:00"))
        except ValueError:
            return False
        return datetime.now(timezone.utc) - momento < timedelta(hours=self.VIGENCIA_PRESENCIA_HORAS)

    def _presencias(self, ids):
        """{user_id: {titulo, consola}} de los amigos que están jugando ahora."""
        if not ids:
            return {}
        try:
            res = self.client.table("presencia").select("user_id, titulo, consola, desde") \
                .in_("user_id", list(ids)).execute()
        except Exception as e:
            print(f"[SOCIAL] Sin datos de presencia: {e}")
            return {}
        return {r["user_id"]: {"titulo": r["titulo"], "consola": r.get("consola", "")}
                for r in res.data or [] if self._vigente(r["desde"])}

    def _en_llamada(self, ids):
        """Amigos que están en una llamada (Supabase solo devuelve los que lo comparten)."""
        if not ids:
            return set()
        try:
            res = self.client.table("presencia_llamada").select("user_id, desde") \
                .in_("user_id", list(ids)).execute()
        except Exception as e:
            print(f"[SOCIAL] Sin datos de llamadas: {e}")
            return set()
        return {r["user_id"] for r in res.data or [] if self._vigente(r["desde"])}

    def contar_solicitudes(self):
        """Cantidad de solicitudes de amistad recibidas sin responder (para la insignia)."""
        if not self.client or not self.usuario_actual:
            return {"exito": False, "solicitudes": 0}
        try:
            res = self.client.table("friendships").select("id") \
                .eq("addressee_id", self._yo()).eq("status", "pending").execute()
            return {"exito": True, "solicitudes": len(res.data or [])}
        except Exception as e:
            return {"exito": False, "solicitudes": 0, "error": self._error_social(e)}

    def obtener_social(self):
        """Amigos (con lo que están jugando), solicitudes recibidas y solicitudes enviadas."""
        error = self._requiere_sesion()
        if error:
            return error
        try:
            yo = self._yo()
            filas = self._amistades()
            otros = [f["addressee_id"] if f["requester_id"] == yo else f["requester_id"] for f in filas]
            perfiles = self._perfiles_por_id(otros)
            aceptados = [o for f, o in zip(filas, otros) if f["status"] == "accepted"]
            presencias = self._presencias(aceptados)
            en_llamada = self._en_llamada(aceptados)

            amigos, recibidas, enviadas = [], [], []
            for f, otro in zip(filas, otros):
                p = perfiles.get(otro, {})
                item = {
                    "friendship_id": f["id"],
                    "user_id": otro,
                    "username": p.get("username") or "Usuario",
                    "avatar_url": p.get("avatar_url") or "",
                }
                if f["status"] == "accepted":
                    item["jugando"] = presencias.get(otro)
                    item["en_llamada"] = otro in en_llamada
                    amigos.append(item)
                elif f["requester_id"] == yo:
                    enviadas.append(item)
                else:
                    recibidas.append(item)

            # Primero los que están jugando o en llamada, después por orden alfabético
            amigos.sort(key=lambda a: (a["jugando"] is None and not a["en_llamada"], a["username"].lower()))
            return {"exito": True, "amigos": amigos, "recibidas": recibidas, "enviadas": enviadas}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    def buscar_usuarios(self, texto):
        """Busca usuarios por nombre e indica la relación actual con cada uno."""
        error = self._requiere_sesion()
        if error:
            return error
        texto = (texto or "").replace("%", "").strip()
        if len(texto) < 2:
            return {"exito": True, "usuarios": []}
        try:
            yo = self._yo()
            res = self.client.table("profiles").select("id, username, avatar_url") \
                .ilike("username", f"%{texto}%").neq("id", yo).limit(20).execute()
            bloqueados = self._ids_con_bloqueo()

            relaciones = {}
            for f in self._amistades():
                otro = f["addressee_id"] if f["requester_id"] == yo else f["requester_id"]
                if f["status"] == "accepted":
                    relaciones[otro] = ("amigos", f["id"])
                elif f["requester_id"] == yo:
                    relaciones[otro] = ("enviada", f["id"])
                else:
                    relaciones[otro] = ("recibida", f["id"])

            usuarios = []
            for p in res.data or []:
                if p["id"] in bloqueados:
                    continue
                relacion, fid = relaciones.get(p["id"], ("ninguna", None))
                usuarios.append({
                    "user_id": p["id"],
                    "username": p.get("username") or "",
                    "avatar_url": p.get("avatar_url") or "",
                    "relacion": relacion,
                    "friendship_id": fid,
                })
            return {"exito": True, "usuarios": usuarios}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    def obtener_perfil_social(self, user_id):
        """Perfil de otro usuario con la relación actual (amigos, solicitud enviada/recibida)
        y lo que está jugando (solo si son amigos)."""
        error = self._requiere_sesion()
        if error:
            return error
        try:
            yo = self._yo()
            res = self.client.table("profiles").select("id, username, bio, avatar_url") \
                .eq("id", user_id).execute()
            if not res.data or user_id in self._ids_con_bloqueo():
                return {"exito": False, "error": "No se encontró ese usuario."}
            p = res.data[0]

            relacion, fid = ("yo" if user_id == yo else "ninguna"), None
            if user_id != yo:
                for f in self._amistades():
                    if user_id in (f["requester_id"], f["addressee_id"]):
                        fid = f["id"]
                        if f["status"] == "accepted":
                            relacion = "amigos"
                        elif f["requester_id"] == yo:
                            relacion = "enviada"
                        else:
                            relacion = "recibida"
                        break

            jugando = self._presencias([user_id]).get(user_id) if relacion == "amigos" else None
            en_llamada = relacion == "amigos" and user_id in self._en_llamada([user_id])
            recientes, en_comun = self._historial_con_amigo(yo, user_id) if relacion == "amigos" else ([], [])
            deseados = self.obtener_deseados_de(user_id) if relacion == "amigos" else []
            return {
                "exito": True,
                "perfil": {
                    "user_id": p["id"],
                    "username": p.get("username") or "Usuario",
                    "bio": p.get("bio") or "",
                    "avatar_url": p.get("avatar_url") or "",
                },
                "relacion": relacion,
                "friendship_id": fid,
                "jugando": jugando,
                "en_llamada": en_llamada,
                "recientes": recientes,
                "en_comun": en_comun,
                "deseados": deseados,
            }
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    # Si la otra persona ya te envió una solicitud, se acepta directamente.
    def enviar_solicitud_amistad(self, user_id):
        error = self._requiere_sesion()
        if error:
            return error
        try:
            yo = self._yo()
            if user_id == yo:
                return {"exito": False, "error": "No podés agregarte a vos mismo."}
            existentes = [f for f in self._amistades() if user_id in (f["requester_id"], f["addressee_id"])]
            if existentes:
                f = existentes[0]
                if f["status"] == "accepted":
                    return {"exito": False, "error": "Ya son amigos."}
                if f["requester_id"] == yo:
                    return {"exito": False, "error": "Ya le enviaste una solicitud."}
                return self.responder_solicitud_amistad(f["id"], True)   # ya te había escrito: se acepta
            self.client.table("friendships").insert({
                "requester_id": yo, "addressee_id": user_id, "status": "pending"
            }).execute()
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    # Solo la persona que recibió la solicitud puede responderla.
    def responder_solicitud_amistad(self, friendship_id, aceptar):
        error = self._requiere_sesion()
        if error:
            return error
        try:
            yo = self._yo()
            tabla = self.client.table("friendships")
            if aceptar:
                tabla.update({"status": "accepted"}).eq("id", friendship_id).eq("addressee_id", yo).execute()
            else:
                tabla.delete().eq("id", friendship_id).eq("addressee_id", yo).execute()
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    def eliminar_amistad(self, friendship_id):
        """Quita un amigo o cancela una solicitud enviada."""
        error = self._requiere_sesion()
        if error:
            return error
        try:
            self.client.table("friendships").delete().eq("id", friendship_id).execute()
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    # --- BLOQUEAR Y DENUNCIAR ---

    MOTIVOS_DENUNCIA = ("acoso", "spam", "contenido", "suplantacion", "otro")
    LIMITE_DETALLE_DENUNCIA = 500

    # Usuarios con un bloqueo en cualquier sentido. Si falla la consulta no se oculta a nadie
    # en la búsqueda, pero Supabase igual impide la amistad, el chat y las llamadas.
    def _ids_con_bloqueo(self):
        try:
            return set(self.client.rpc("ids_con_bloqueo").execute().data or [])
        except Exception as e:
            print(f"[SOCIAL] Sin datos de bloqueos: {e}")
            return set()

    # Bloquea a un usuario y elimina la amistad o solicitud que hubiera entre ambos.
    def bloquear_usuario(self, user_id):
        error = self._requiere_sesion()
        if error:
            return error
        if user_id == self._yo():
            return {"exito": False, "error": "No podés bloquearte a vos mismo."}
        try:
            self.client.rpc("bloquear_usuario", {"p_usuario": user_id}).execute()
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    # Quita un bloqueo propio. La amistad no vuelve: hay que enviar otra solicitud.
    def desbloquear_usuario(self, user_id):
        error = self._requiere_sesion()
        if error:
            return error
        try:
            self.client.table("bloqueos").delete().eq("bloqueador", self._yo()).eq("bloqueado", user_id).execute()
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    # Usuarios que bloqueaste, para la sección Privacidad.
    def obtener_bloqueados(self):
        error = self._requiere_sesion()
        if error:
            return error
        try:
            filas = self.client.table("bloqueos").select("bloqueado") \
                .eq("bloqueador", self._yo()).order("creado_en", desc=True).execute().data or []
            perfiles = self._perfiles_por_id([f["bloqueado"] for f in filas])
            return {"exito": True, "bloqueados": [{
                "user_id": f["bloqueado"],
                "username": perfiles.get(f["bloqueado"], {}).get("username") or "Usuario",
                "avatar_url": perfiles.get(f["bloqueado"], {}).get("avatar_url") or "",
            } for f in filas]}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    # Registra una denuncia para revisarla en el panel de Supabase. No avisa a la persona denunciada.
    def denunciar_usuario(self, user_id, motivo, detalle=""):
        error = self._requiere_sesion()
        if error:
            return error
        detalle = (detalle or "").strip()
        if user_id == self._yo():
            return {"exito": False, "error": "No podés denunciarte a vos mismo."}
        if motivo not in self.MOTIVOS_DENUNCIA:
            return {"exito": False, "error": "Elegí un motivo."}
        if len(detalle) > self.LIMITE_DETALLE_DENUNCIA:
            return {"exito": False, "error": f"El detalle es demasiado largo (máximo {self.LIMITE_DETALLE_DENUNCIA} caracteres)."}
        try:
            nueva = self.client.rpc("denunciar_usuario", {
                "p_usuario": user_id, "p_motivo": motivo, "p_detalle": detalle}).execute().data
            return {"exito": True, "ya_existia": nueva is False}
        except Exception as e:
            if "demasiadas denuncias" in str(e).lower():
                return {"exito": False, "error": "Enviaste demasiadas denuncias hoy. Probá de nuevo mañana."}
            return {"exito": False, "error": self._error_social(e)}

    # --- CHAT (mensajes entre amigos aceptados) ---

    LIMITE_MENSAJE = 1000
    _COLUMNAS_MENSAJE = "id, de, para, tipo, contenido, adjunto, creado_en, leido_en"

    # Da a un mensaje el formato que espera la interfaz.
    def _mensaje_para_ui(self, m):
        return {
            **self._abierto_para_ui(m),
            "id": m["id"],
            "mio": m["de"] == self._yo(),
            "creado_en": m.get("creado_en"),
            "leido": bool(m.get("leido_en")),
        }

    def _abierto_para_ui(self, m):
        abierto = self.llaves.abrir(m)
        return {"tipo": abierto.get("tipo", "texto"), "contenido": abierto.get("contenido", "")}

    # Filtro de PostgREST: mensajes entre tú y ese amigo, en cualquier dirección.
    def _filtro_par(self, amigo):
        yo = self._yo()
        return f"and(de.eq.{yo},para.eq.{amigo}),and(de.eq.{amigo},para.eq.{yo})"

    # Texto corto del último mensaje en la lista de chats.
    @staticmethod
    def _resumen_mensaje(m):
        tipo = m.get("tipo", "texto")
        if tipo == "texto":
            return m.get("contenido", "")
        return {"imagen": "📷 Imagen", "sticker": "Sticker", "gif": "GIF",
                "publicacion": "📰 Publicación"}.get(tipo, "Mensaje")

    # Ids de tus amigos con la solicitud aceptada.
    def _amigos_aceptados(self):
        yo = self._yo()
        return [f["addressee_id"] if f["requester_id"] == yo else f["requester_id"]
                for f in self._amistades() if f["status"] == "accepted"]

    def resumen_social(self):
        """Datos livianos para las insignias: solicitudes pendientes y mensajes sin leer de amigos."""
        if not self.client or not self.usuario_actual:
            return {"exito": False, "solicitudes": 0, "mensajes": 0}
        solicitudes = self.contar_solicitudes().get("solicitudes", 0)
        mensajes = 0
        try:
            amigos = set(self._amigos_aceptados())
            res = self.client.table("mensajes").select("de") \
                .eq("para", self._yo()).is_("leido_en", "null").limit(1000).execute()
            mensajes = sum(1 for r in (res.data or []) if r["de"] in amigos)
        except Exception as e:
            print(f"[SOCIAL] Sin datos de mensajes: {self._error_social(e)}")
        return {"exito": True, "solicitudes": solicitudes, "mensajes": mensajes}

    def obtener_conversaciones(self):
        """Un renglón por amigo: último mensaje, cuántos sin leer y si está jugando."""
        error = self._requiere_sesion()
        if error:
            return error
        try:
            yo = self._yo()
            amigos = self._amigos_aceptados()
            perfiles = self._perfiles_por_id(amigos)
            presencias = self._presencias(amigos)
            en_llamada = self._en_llamada(amigos)

            res = self.client.table("mensajes").select(self._COLUMNAS_MENSAJE) \
                .or_(f"de.eq.{yo},para.eq.{yo}").order("id", desc=True).limit(300).execute()
            ultimos = {}
            for m in res.data or []:                       # vienen del más nuevo al más viejo
                otro = m["para"] if m["de"] == yo else m["de"]
                ultimos.setdefault(otro, m)

            sin_leer = Counter()
            res2 = self.client.table("mensajes").select("de") \
                .eq("para", yo).is_("leido_en", "null").limit(1000).execute()
            for r in res2.data or []:
                sin_leer[r["de"]] += 1

            conversaciones = []
            for amigo in amigos:
                p = perfiles.get(amigo, {})
                u = ultimos.get(amigo)
                conversaciones.append({
                    "user_id": amigo,
                    "username": p.get("username") or "Usuario",
                    "avatar_url": p.get("avatar_url") or "",
                    "jugando": presencias.get(amigo),
                    "en_llamada": amigo in en_llamada,
                    "no_leidos": sin_leer.get(amigo, 0),
                    "ultimo": {"id": u["id"], "mio": u["de"] == yo, "texto": self._resumen_mensaje(self.llaves.abrir(u)),
                               "creado_en": u.get("creado_en")} if u else None,
                })
            conversaciones.sort(key=lambda c: (c["ultimo"] is None, -(c["ultimo"]["id"] if c["ultimo"] else 0),
                                               c["username"].lower()))
            return {"exito": True, "conversaciones": conversaciones}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    def marcar_leidos(self, amigo_id):
        """Marca como leídos los mensajes que ese amigo te envió."""
        if not self.client or not self.usuario_actual:
            return
        try:
            self.client.table("mensajes") \
                .update({"leido_en": datetime.now(timezone.utc).isoformat()}) \
                .eq("de", amigo_id).eq("para", self._yo()).is_("leido_en", "null").execute()
        except Exception as e:
            print(f"[SOCIAL] No se pudo marcar como leído: {self._error_social(e)}")

    def obtener_mensajes(self, amigo_id, antes_id=None, limite=40):
        """Mensajes de la conversación (los últimos, o los anteriores a 'antes_id')."""
        error = self._requiere_sesion()
        if error:
            return error
        try:
            consulta = self.client.table("mensajes").select(self._COLUMNAS_MENSAJE) \
                .or_(self._filtro_par(amigo_id)).order("id", desc=True).limit(limite)
            if antes_id:
                consulta = consulta.lt("id", antes_id)
            filas = list(reversed(consulta.execute().data or []))
            if not antes_id:
                self.marcar_leidos(amigo_id)
            return {"exito": True, "mensajes": [self._mensaje_para_ui(m) for m in filas],
                    "hay_mas": len(filas) >= limite}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    def sincronizar_chat(self, amigo_id, ultimo_id, ids_pendientes):
        """Una consulta periódica: mensajes nuevos del amigo y cuáles de los míos ya vio."""
        error = self._requiere_sesion()
        if error:
            return error
        try:
            res = self.client.table("mensajes").select(self._COLUMNAS_MENSAJE) \
                .or_(self._filtro_par(amigo_id)).gt("id", ultimo_id or 0).order("id").limit(100).execute()
            nuevos = res.data or []
            if any(m["de"] != self._yo() for m in nuevos):
                self.marcar_leidos(amigo_id)

            vistos = []
            if ids_pendientes:
                res2 = self.client.table("mensajes").select("id, leido_en") \
                    .in_("id", list(ids_pendientes)).execute()
                vistos = [r["id"] for r in (res2.data or []) if r.get("leido_en")]
            return {"exito": True, "nuevos": [self._mensaje_para_ui(m) for m in nuevos], "vistos": vistos}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    # Inserción común: todo mensaje se cifra aquí. La base solo ve el tipo "cifrado", no si es texto, imagen o GIF.
    def _insertar_mensaje(self, amigo_id, tipo, contenido, adjunto=None, llave=None):
        try:
            res = self.client.table("mensajes").insert({
                "de": self._yo(), "para": amigo_id, "tipo": "cifrado", "adjunto": adjunto,
                "contenido": self.llaves.cifrar(amigo_id, tipo, contenido, llave),
            }).execute()
            fila = (res.data or [None])[0]
            if not fila:
                return {"exito": False, "error": "No se pudo enviar el mensaje."}
            return {"exito": True, "mensaje": self._mensaje_para_ui(fila)}
        except cifrado.SinLlave as e:
            return {"exito": False, "error": str(e), "falta_mi_llave": e.propia}
        except Exception as e:
            bajo = str(e).lower()
            if "row-level security" in bajo or "42501" in bajo:
                return {"exito": False, "error": "No podés escribirle a esta persona (¿siguen siendo amigos?)."}
            return {"exito": False, "error": self._error_social(e)}

    # Valida el texto y lo envía.
    def enviar_mensaje(self, amigo_id, texto):
        error = self._requiere_sesion()
        if error:
            return error
        texto = (texto or "").strip()
        if not texto:
            return {"exito": False, "error": "Escribí un mensaje."}
        if len(texto) > self.LIMITE_MENSAJE:
            return {"exito": False, "error": f"El mensaje es demasiado largo (máximo {self.LIMITE_MENSAJE} caracteres)."}
        return self._insertar_mensaje(amigo_id, "texto", texto)

    def enviar_gif(self, amigo_id, url):
        """Un GIF viaja como su dirección de internet (solo servidores de KLIPY)."""
        error = self._requiere_sesion()
        if error:
            return error
        if not gifs.url_permitida(url):
            return {"exito": False, "error": "Ese GIF no es válido."}
        return self._insertar_mensaje(amigo_id, "gif", url)

    # --- IMÁGENES Y STICKERS (espacio privado "chat" de Supabase Storage) ---

    BUCKET_CHAT = "chat"
    MIME_CIFRADO = "application/octet-stream"   # el espacio del chat solo acepta archivos cifrados
    MAX_STICKERS = 60

    # Traduce los errores de subida de imágenes.
    def _error_subida(self, e):
        bajo = str(e).lower()
        if "bucket not found" in bajo or ("bucket" in bajo and "not found" in bajo):
            return "Falta crear el espacio de imágenes en Supabase."
        if "payload too large" in bajo or "exceeded" in bajo or "413" in bajo:
            return "La imagen es demasiado pesada."
        if "mime" in bajo or "not supported" in bajo or "invalid" in bajo and "type" in bajo:
            return "Ese tipo de archivo no está permitido (usá PNG, JPG o WEBP)."
        return self._error_social(e)

    # Sube un archivo al espacio privado del chat, sin reemplazar otro.
    def _subir_a_chat(self, ruta, datos, mime):
        self.client.storage.from_(self.BUCKET_CHAT).upload(
            path=ruta, file=datos, file_options={"content-type": mime, "upsert": "false"})

    # Sube el archivo cifrado y crea el mensaje con su llave; si el mensaje falla, borra el archivo.
    def _enviar_adjunto(self, amigo_id, tipo, datos):
        ruta = f"{self._yo()}/cifrados/{uuid.uuid4().hex}.bin"
        llave, cifrados = cifrado.cifrar_archivo(datos)
        try:
            self._subir_a_chat(ruta, cifrados, self.MIME_CIFRADO)
        except Exception as e:
            return {"exito": False, "error": self._error_subida(e)}
        resultado = self._insertar_mensaje(amigo_id, tipo, ruta, adjunto=ruta, llave=llave)
        if not resultado.get("exito"):
            try:   # no dejar el archivo huérfano si el mensaje no se pudo enviar
                self.client.storage.from_(self.BUCKET_CHAT).remove([ruta])
            except Exception:
                pass
        return resultado

    def enviar_imagen(self, amigo_id, datos):
        error = self._requiere_sesion()
        if error:
            return error
        return self._enviar_adjunto(amigo_id, "imagen", datos)

    def guardar_sticker(self, datos):
        """Sube el sticker a tu carpeta y lo suma a tu colección."""
        error = self._requiere_sesion()
        if error:
            return error
        try:
            existentes = self.client.table("stickers_usuario").select("id").eq("user_id", self._yo()).execute()
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}
        if len(existentes.data or []) >= self.MAX_STICKERS:
            return {"exito": False, "error": f"Llegaste al máximo de {self.MAX_STICKERS} stickers: quitá alguno para crear otro."}

        ruta = f"{self._yo()}/stickers/{uuid.uuid4().hex}.bin"
        try:
            self._subir_a_chat(ruta, self.llaves.cifrar_propio(datos), self.MIME_CIFRADO)
            res = self.client.table("stickers_usuario").insert({"user_id": self._yo(), "ruta": ruta}).execute()
            fila = (res.data or [None])[0]
            return {"exito": True, "sticker": {"id": fila["id"] if fila else None, "ruta": ruta}}
        except cifrado.SinLlave as e:
            return {"exito": False, "error": str(e), "falta_mi_llave": True}
        except Exception as e:
            return {"exito": False, "error": self._error_subida(e)}

    # Tus stickers, del más nuevo al más viejo.
    def obtener_stickers(self):
        error = self._requiere_sesion()
        if error:
            return error
        try:
            res = self.client.table("stickers_usuario").select("id, ruta, creado_en").eq("user_id", self._yo()).execute()
            filas = sorted(res.data or [], key=lambda r: r.get("creado_en") or "", reverse=True)
            return {"exito": True, "stickers": [{"id": r["id"], "ruta": r["ruta"]} for r in filas]}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    def eliminar_sticker(self, sticker_id):
        """Lo saca de tu colección y borra su archivo: cada envío ya tiene su propia copia."""
        error = self._requiere_sesion()
        if error:
            return error
        try:
            res = self.client.table("stickers_usuario").delete().eq("id", sticker_id).eq("user_id", self._yo()).execute()
            rutas = [r["ruta"] for r in res.data or []]
            if rutas:
                self.client.storage.from_(self.BUCKET_CHAT).remove(rutas)
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    # Solo permite enviar stickers de tu propia carpeta.
    def enviar_sticker(self, amigo_id, ruta):
        error = self._requiere_sesion()
        if error:
            return error
        if not (ruta or "").startswith(f"{self._yo()}/stickers/"):
            return {"exito": False, "error": "Ese sticker no es tuyo."}
        # shortcut: cada envío sube una copia cifrada; si el espacio se vuelve un problema, reutilizarla por amigo
        datos = self.descargar_imagen_chat(ruta)
        if not datos:
            return {"exito": False, "error": "No se pudo abrir ese sticker."}
        return self._enviar_adjunto(amigo_id, "sticker", datos)

    def descargar_imagen_chat(self, ruta):
        """Imagen o sticker del chat ya descifrado, o None."""
        datos = self._bajar_archivo_chat(ruta)
        return self.llaves.descifrar_archivo(ruta, datos) if datos else None

    def _bajar_archivo_chat(self, ruta):
        """Bytes tal como están guardados. La copia en cache/chat/<usuario>/ sigue cifrada."""
        if not self.client or not self.usuario_actual or not ruta:
            return None
        carpeta = os.path.join("cache", "chat", self._yo())
        archivo = os.path.join(carpeta, hashlib.sha1(ruta.encode("utf-8")).hexdigest() + ".bin")
        try:
            if os.path.isfile(archivo):
                with open(archivo, "rb") as f:
                    return f.read()
        except OSError:
            pass
        try:
            datos = self.client.storage.from_(self.BUCKET_CHAT).download(ruta)
        except Exception as e:
            print(f"[CHAT] No se pudo descargar la imagen: {self._error_subida(e)}")
            return None
        if datos and len(datos) <= 8 * 1024 * 1024:
            try:
                os.makedirs(carpeta, exist_ok=True)
                with open(archivo + ".part", "wb") as f:
                    f.write(datos)
                os.replace(archivo + ".part", archivo)
            except OSError:
                pass
        return datos

    def establecer_jugando(self, titulo, consola):
        """Publica (solo para tus amigos) a qué estás jugando."""
        if not self.client or not self.usuario_actual:
            return
        try:
            self.client.table("presencia").upsert({
                "user_id": self._yo(),
                "titulo": titulo,
                "consola": consola,
                "desde": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            print(f"[SOCIAL] No se pudo publicar la actividad: {self._error_social(e)}")

    # Borra tu aviso de "jugando ahora".
    def limpiar_jugando(self):
        if not self.client or not self.usuario_actual:
            return
        try:
            self.client.table("presencia").delete().eq("user_id", self._yo()).execute()
        except Exception as e:
            print(f"[SOCIAL] No se pudo limpiar la actividad: {self._error_social(e)}")

    # --- HISTORIAL DE JUEGOS (visible solo para tus amigos) ---

    def registrar_jugada(self, identificativo, titulo, consola):
        """Suma una partida al historial: cuenta las veces y guarda la última vez."""
        if not self.client or not self.usuario_actual:
            return
        try:
            self.client.rpc("registrar_jugada", {
                "p_clave": clave_juego(identificativo, titulo),
                "p_titulo": titulo,
                "p_consola": consola,
                "p_identificativo": identificativo,
            }).execute()
        except Exception as e:
            print(f"[SOCIAL] No se pudo registrar la partida: {self._error_social(e)}")

    def borrar_historial(self):
        """Borra de la nube el historial propio (al desactivar la opción de privacidad)."""
        if not self.client or not self.usuario_actual:
            return
        try:
            self.client.table("juegos_jugados").delete().eq("user_id", self._yo()).execute()
        except Exception as e:
            print(f"[SOCIAL] No se pudo borrar el historial: {self._error_social(e)}")

    def _historial_con_amigo(self, yo, amigo):
        """(recientes del amigo, juegos en común). Una sola consulta: Supabase solo devuelve
        las filas propias y las de amigos, y las de un amigo solo si comparte su historial."""
        try:
            res = self.client.table("juegos_jugados") \
                .select("user_id, clave, titulo, consola, identificativo, veces, ultima_vez") \
                .in_("user_id", [yo, amigo]).execute()
        except Exception as e:
            print(f"[SOCIAL] Sin historial disponible: {self._error_social(e)}")
            return [], []
        filas = res.data or []
        mios = {r["clave"] for r in filas if r["user_id"] == yo}
        suyos = sorted((r for r in filas if r["user_id"] == amigo),
                       key=lambda r: r.get("ultima_vez") or "", reverse=True)
        recientes = [{"titulo": r["titulo"], "consola": r.get("consola", ""),
                      "identificativo": r.get("identificativo", ""),
                      "veces": r.get("veces", 1), "ultima_vez": r.get("ultima_vez")} for r in suyos[:8]]
        en_comun = sorted(({"titulo": r["titulo"], "consola": r.get("consola", ""),
                            "identificativo": r.get("identificativo", "")}
                           for r in suyos if r["clave"] in mios), key=lambda j: j["titulo"].lower())
        return recientes, en_comun

    def obtener_mi_actividad(self, limite=6):
        """Mis juegos jugados recientemente y mi lista de deseados (para mi perfil)."""
        error = self._requiere_sesion()
        if error:
            return error
        recientes, deseados = [], []
        try:
            res = self.client.table("juegos_jugados") \
                .select("titulo, consola, identificativo, veces, ultima_vez") \
                .eq("user_id", self._yo()).execute()
            filas = sorted(res.data or [], key=lambda r: r.get("ultima_vez") or "", reverse=True)
            recientes = [{"titulo": r["titulo"], "consola": r.get("consola", ""),
                          "identificativo": r.get("identificativo", ""),
                          "veces": r.get("veces", 1), "ultima_vez": r.get("ultima_vez")} for r in filas[:limite]]
        except Exception as e:
            print(f"[SOCIAL] Sin historial propio: {self._error_social(e)}")
        try:
            deseados = self._lista_deseados_de(self._yo())[:limite]
        except Exception as e:
            print(f"[SOCIAL] Sin lista de deseados propia: {self._error_social(e)}")
        return {"exito": True, "recientes": recientes, "deseados": deseados}

    def obtener_amigos_que_jugaron(self, identificativo, titulo):
        """Amigos que ya jugaron este juego (con cuántas veces y cuándo fue la última)."""
        if not self.client or not self.usuario_actual:
            return []
        try:
            res = self.client.table("juegos_jugados").select("user_id, veces, ultima_vez") \
                .eq("clave", clave_juego(identificativo, titulo)).neq("user_id", self._yo()).execute()
            filas = res.data or []
            perfiles = self._perfiles_por_id([f["user_id"] for f in filas])
            lista = [{
                "user_id": f["user_id"],
                "username": perfiles.get(f["user_id"], {}).get("username") or "Usuario",
                "avatar_url": perfiles.get(f["user_id"], {}).get("avatar_url") or "",
                "veces": f.get("veces", 1),
                "ultima_vez": f.get("ultima_vez"),
            } for f in filas]
            lista.sort(key=lambda a: a["ultima_vez"] or "", reverse=True)
            return lista
        except Exception as e:
            print(f"[SOCIAL] No se pudo consultar quién jugó este juego: {self._error_social(e)}")
            return []

    def obtener_amigos_con_deseado(self, identificativo, titulo):
        """Amigos que tienen este juego en su lista de deseados (solo los que la comparten)."""
        if not self.client or not self.usuario_actual:
            return []
        try:
            res = self.client.table("lista_deseados").select("user_id, agregado_en") \
                .eq("clave", clave_juego(identificativo, titulo)).neq("user_id", self._yo()).execute()
            filas = res.data or []
            perfiles = self._perfiles_por_id([f["user_id"] for f in filas])
            lista = [{
                "user_id": f["user_id"],
                "username": perfiles.get(f["user_id"], {}).get("username") or "Usuario",
                "avatar_url": perfiles.get(f["user_id"], {}).get("avatar_url") or "",
                "agregado_en": f.get("agregado_en"),
            } for f in filas]
            lista.sort(key=lambda a: a["agregado_en"] or "", reverse=True)
            return lista
        except Exception as e:
            print(f"[SOCIAL] No se pudo consultar quién lo desea: {self._error_social(e)}")
            return []

    # --- LISTA DE DESEADOS (visible solo para tus amigos, si la compartís) ---

    # Agrega un juego a tu lista si todavía no está.
    def agregar_deseado(self, identificativo, titulo, consola, publica=True):
        error = self._requiere_sesion()
        if error:
            return error
        titulo = (titulo or "").strip()
        if not identificativo or not titulo:
            return {"exito": False, "error": "Elegí la consola y escribí el nombre del juego."}
        try:
            clave = clave_juego(identificativo, titulo)
            ya = self.client.table("lista_deseados").select("clave") \
                .eq("user_id", self._yo()).eq("clave", clave).execute()
            if ya.data:
                return {"exito": False, "error": f'"{titulo}" ya está en tu lista.'}
            self.client.table("lista_deseados").upsert({
                "user_id": self._yo(),
                "clave": clave,
                "titulo": titulo,
                "consola": consola or "",
                "identificativo": identificativo,
                "publica": bool(publica),
            }).execute()
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    # Quita un juego de tu lista.
    def quitar_deseado(self, clave):
        error = self._requiere_sesion()
        if error:
            return error
        try:
            self.client.table("lista_deseados").delete().eq("user_id", self._yo()).eq("clave", clave).execute()
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    # Lista de un usuario; Supabase solo devuelve lo que puedes ver.
    def _lista_deseados_de(self, user_id):
        res = self.client.table("lista_deseados") \
            .select("clave, titulo, consola, identificativo, agregado_en").eq("user_id", user_id).execute()
        filas = res.data or []
        filas.sort(key=lambda r: r.get("agregado_en") or "", reverse=True)
        return filas

    # Tu lista de deseados completa.
    def obtener_mis_deseados(self):
        error = self._requiere_sesion()
        if error:
            return error
        try:
            return {"exito": True, "deseados": self._lista_deseados_de(self._yo())}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    def obtener_deseados_de(self, user_id):
        """Lista de un amigo (Supabase solo devuelve lo que él comparte)."""
        try:
            return self._lista_deseados_de(user_id)[:30]
        except Exception as e:
            print(f"[SOCIAL] Sin lista de deseados disponible: {self._error_social(e)}")
            return []

    def actualizar_visibilidad_deseados(self, publica):
        """Cambia de golpe la visibilidad de toda tu lista (ajuste de privacidad)."""
        error = self._requiere_sesion()
        if error:
            return error
        try:
            self.client.table("lista_deseados").update({"publica": bool(publica)}).eq("user_id", self._yo()).execute()
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    # --- OPINIONES DE JUEGOS (las ven tus amigos si las dejás visibles) ---

    # Publica tu opinión; si está vacía, la retira de la nube.
    def publicar_opinion(self, identificativo, titulo, consola, puntuacion, texto, publica=True):
        error = self._requiere_sesion()
        if error:
            return error
        try:
            clave = clave_juego(identificativo, titulo)
            if not puntuacion and not (texto or "").strip():
                # Opinión vacía: se retira de la nube
                self.client.table("opiniones_juegos").delete().eq("user_id", self._yo()).eq("clave", clave).execute()
            else:
                self.client.table("opiniones_juegos").upsert({
                    "user_id": self._yo(),
                    "clave": clave,
                    "titulo": titulo,
                    "consola": consola or "",
                    "identificativo": identificativo,
                    "puntuacion": int(puntuacion or 0),
                    "texto": texto or "",
                    "publica": bool(publica),
                    "actualizado_en": datetime.now(timezone.utc).isoformat(),
                }).execute()
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

    def obtener_opiniones_amigos(self, identificativo, titulo):
        """Opiniones que tus amigos dejaron (y compartieron) de este juego."""
        if not self.client or not self.usuario_actual:
            return []
        try:
            res = self.client.table("opiniones_juegos") \
                .select("user_id, puntuacion, texto, actualizado_en") \
                .eq("clave", clave_juego(identificativo, titulo)).neq("user_id", self._yo()).execute()
            filas = res.data or []
            perfiles = self._perfiles_por_id([f["user_id"] for f in filas])
            lista = [{
                "user_id": f["user_id"],
                "username": perfiles.get(f["user_id"], {}).get("username") or "Usuario",
                "avatar_url": perfiles.get(f["user_id"], {}).get("avatar_url") or "",
                "puntuacion": f.get("puntuacion", 0),
                "texto": f.get("texto", ""),
                "actualizado_en": f.get("actualizado_en"),
            } for f in filas]
            lista.sort(key=lambda a: a["actualizado_en"] or "", reverse=True)
            return lista
        except Exception as e:
            print(f"[SOCIAL] No se pudieron cargar las opiniones: {self._error_social(e)}")
            return []

    # --- PUBLICACIONES (públicas: las ve cualquier usuario con sesión) ---

    BUCKET_PUBLICACIONES = "publicaciones"
    LIMITE_PUBLICACION = 2000
    LIMITE_COMENTARIO = 500
    POR_PAGINA_PUBLICACIONES = 15
    REACCIONES = ("like", "dislike")

    # Traduce los errores propios de las publicaciones.
    def _error_publicaciones(self, e):
        bajo = str(e).lower()
        falta_algo = any(x in bajo for x in ("does not exist", "could not find", "schema cache", "pgrst202", "pgrst205"))
        if falta_algo and ("publicaciones" in bajo or "alternar_reaccion" in bajo):
            return "Faltan las tablas de Publicaciones en Supabase."
        if "bucket" in bajo and "not found" in bajo:
            return "Falta crear el espacio de imágenes de Publicaciones."
        if "payload too large" in bajo or "exceeded" in bajo or "413" in bajo:
            return "La imagen es demasiado pesada."
        if "mime" in bajo and ("not supported" in bajo or "not allowed" in bajo):
            return "Ese tipo de archivo no está permitido (usá PNG, JPG o WEBP)."
        return self._error_social(e)

    def _url_media(self, fila):
        """Dirección para mostrar la imagen/GIF de una publicación ('' si no es válida)."""
        tipo, media = fila.get("tipo_media"), fila.get("media")
        if not media:
            return ""
        if tipo == "gif":
            return media if gifs.url_permitida(media) else ""
        if tipo == "imagen" and SUPABASE_URL:
            ruta = "/".join(quote(parte, safe="") for parte in media.split("/"))
            return f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{self.BUCKET_PUBLICACIONES}/{ruta}"
        return ""

    # Da a una publicación el formato que espera la interfaz.
    def _publicacion_para_ui(self, f):
        url = self._url_media(f)
        return {
            "id": f["id"],
            "autor_id": f["autor_id"],
            "mia": f["autor_id"] == self._yo(),
            "username": f.get("username") or "Usuario",
            "avatar_url": f.get("avatar_url") or "",
            "texto": f.get("texto") or "",
            "tipo_media": (f.get("tipo_media") or "") if url else "",
            "media_url": url,
            "creado_en": f.get("creado_en"),
            "likes": f.get("likes") or 0,
            "dislikes": f.get("dislikes") or 0,
            "compartidos": f.get("compartidos") or 0,
            "comentarios": f.get("comentarios") or 0,
            "mi_like": bool(f.get("mi_like")),
            "mi_dislike": bool(f.get("mi_dislike")),
            "mi_compartido": bool(f.get("mi_compartido")),
        }

    # Llama a la función listar_publicaciones de Supabase.
    def _consultar_publicaciones(self, antes_id=None, autor_id=None, pub_id=None):
        res = self.client.rpc("listar_publicaciones", {
            "p_antes": int(antes_id) if antes_id else None,
            "p_limite": self.POR_PAGINA_PUBLICACIONES,
            "p_autor": autor_id or None,
            "p_id": int(pub_id) if pub_id else None,
        }).execute()
        return res.data or []

    # Vuelve a leer una publicación para tener sus contadores al día.
    def _devolver_publicacion(self, pub_id, **extra):
        filas = self._consultar_publicaciones(pub_id=pub_id)
        if not filas:
            return {"exito": False, "no_existe": True, "error": "Esa publicación ya no existe."}
        return {"exito": True, "publicacion": self._publicacion_para_ui(filas[0]), **extra}

    def obtener_publicaciones(self, antes_id=None, autor_id=None):
        """Publicaciones de todos, de la más nueva a la más vieja (o solo las de 'autor_id')."""
        error = self._requiere_sesion()
        if error:
            return error
        try:
            filas = self._consultar_publicaciones(antes_id=antes_id, autor_id=autor_id)
            return {"exito": True,
                    "publicaciones": [self._publicacion_para_ui(f) for f in filas],
                    "hay_mas": len(filas) >= self.POR_PAGINA_PUBLICACIONES}
        except Exception as e:
            return {"exito": False, "error": self._error_publicaciones(e)}

    # Una publicación por su id.
    def obtener_publicacion(self, pub_id):
        error = self._requiere_sesion()
        if error:
            return error
        try:
            return self._devolver_publicacion(pub_id)
        except Exception as e:
            return {"exito": False, "error": self._error_publicaciones(e)}

    def crear_publicacion(self, texto, imagen=None, gif_url=None):
        """'imagen' es (bytes, mime, extension) ya preparada; 'gif_url' una dirección de KLIPY.
        Una publicación lleva como máximo una imagen o un GIF."""
        error = self._requiere_sesion()
        if error:
            return error
        texto = (texto or "").strip()
        if len(texto) > self.LIMITE_PUBLICACION:
            return {"exito": False, "error": f"El texto es demasiado largo (máximo {self.LIMITE_PUBLICACION} caracteres)."}
        if gif_url and not gifs.url_permitida(gif_url):
            return {"exito": False, "error": "Ese GIF no es válido."}
        if not texto and not gif_url and not imagen:
            return {"exito": False, "error": "Escribí algo o agregá una imagen o un GIF."}

        tipo_media, media, subida = None, None, None
        try:
            if gif_url:
                tipo_media, media = "gif", gif_url
            elif imagen:
                datos, mime, extension = imagen
                subida = f"{self._yo()}/{uuid.uuid4().hex}.{extension}"
                self.client.storage.from_(self.BUCKET_PUBLICACIONES).upload(
                    path=subida, file=datos, file_options={"content-type": mime, "upsert": "false"})
                tipo_media, media = "imagen", subida

            res = self.client.table("publicaciones").insert({
                "autor_id": self._yo(), "texto": texto, "tipo_media": tipo_media, "media": media,
            }).execute()
            fila = (res.data or [None])[0]
            if not fila:
                raise RuntimeError("No se pudo publicar.")
            return self._devolver_publicacion(fila["id"])
        except Exception as e:
            if subida:   # no dejar la imagen huérfana si la publicación no se pudo crear
                try:
                    self.client.storage.from_(self.BUCKET_PUBLICACIONES).remove([subida])
                except Exception:
                    pass
            return {"exito": False, "error": self._error_publicaciones(e)}

    # Comprueba que sea tuya y borra también su imagen.
    def eliminar_publicacion(self, pub_id):
        error = self._requiere_sesion()
        if error:
            return error
        try:
            res = self.client.table("publicaciones").select("id, tipo_media, media") \
                .eq("id", pub_id).eq("autor_id", self._yo()).execute()
            if not res.data:
                return {"exito": False, "error": "No se encontró la publicación (o no es tuya)."}
            fila = res.data[0]
            self.client.table("publicaciones").delete().eq("id", pub_id).eq("autor_id", self._yo()).execute()
            if fila.get("tipo_media") == "imagen" and fila.get("media"):
                try:
                    self.client.storage.from_(self.BUCKET_PUBLICACIONES).remove([fila["media"]])
                except Exception as e:
                    print(f"[PUBLICACIONES] No se pudo borrar la imagen: {self._error_publicaciones(e)}")
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": self._error_publicaciones(e)}

    def alternar_reaccion(self, pub_id, tipo):
        """Like / dislike como interruptor (dar y quitar). Devuelve la publicación con contadores al día."""
        error = self._requiere_sesion()
        if error:
            return error
        if tipo not in self.REACCIONES:
            return {"exito": False, "error": "Reacción no válida."}
        try:
            self.client.rpc("alternar_reaccion", {"p_publicacion": int(pub_id), "p_tipo": tipo}).execute()
            return self._devolver_publicacion(pub_id)
        except Exception as e:
            bajo = str(e).lower()
            if "foreign key" in bajo or "23503" in bajo:   # la publicación se borró mientras tanto
                return {"exito": False, "no_existe": True, "error": "Esa publicación ya no existe."}
            return {"exito": False, "error": self._error_publicaciones(e)}

    def compartir_publicacion(self, pub_id, amigos_ids):
        """La envía por chat a los amigos elegidos y, si salió a alguno, suma tu 'compartido'."""
        error = self._requiere_sesion()
        if error:
            return error
        ids = [a for a in dict.fromkeys(amigos_ids or []) if isinstance(a, str) and a]
        if not ids:
            return {"exito": False, "error": "Elegí al menos un amigo."}
        try:
            existe = self._devolver_publicacion(pub_id)
            if not existe.get("exito"):
                return existe
            validos = set(self._amigos_aceptados())
            enviados, fallidos, ultimo_error = 0, 0, ""
            for amigo in ids:
                if amigo not in validos:
                    fallidos += 1
                    ultimo_error = "Solo podés compartir con tus amigos."
                    continue
                r = self._insertar_mensaje(amigo, "publicacion", str(int(pub_id)))
                if r.get("exito"):
                    enviados += 1
                else:
                    fallidos += 1
                    ultimo_error = r.get("error", "")
            if enviados == 0:
                return {"exito": False, "error": ultimo_error or "No se pudo enviar la publicación."}

            ya = self.client.table("publicaciones_reacciones").select("tipo") \
                .eq("publicacion_id", pub_id).eq("user_id", self._yo()).eq("tipo", "compartir").execute()
            if not ya.data:
                self.client.table("publicaciones_reacciones").insert({
                    "publicacion_id": int(pub_id), "user_id": self._yo(), "tipo": "compartir"}).execute()
            return self._devolver_publicacion(pub_id, enviados=enviados, fallidos=fallidos)
        except Exception as e:
            return {"exito": False, "error": self._error_publicaciones(e)}

    def quitar_compartido(self, pub_id):
        """Quita tu 'compartido' (baja el contador). Los mensajes que ya enviaste por chat quedan."""
        error = self._requiere_sesion()
        if error:
            return error
        try:
            self.client.table("publicaciones_reacciones").delete() \
                .eq("publicacion_id", pub_id).eq("user_id", self._yo()).eq("tipo", "compartir").execute()
            return self._devolver_publicacion(pub_id)
        except Exception as e:
            return {"exito": False, "error": self._error_publicaciones(e)}

    # --- PUBLICACIONES: COMENTARIOS ---

    # Comentarios de una publicación con el nombre de cada autor.
    def obtener_comentarios(self, pub_id):
        error = self._requiere_sesion()
        if error:
            return error
        try:
            res = self.client.table("publicaciones_comentarios").select("id, autor_id, texto, creado_en") \
                .eq("publicacion_id", pub_id).order("id").limit(200).execute()
            filas = res.data or []
            perfiles = self._perfiles_por_id({f["autor_id"] for f in filas})
            yo = self._yo()
            return {"exito": True, "comentarios": [{
                "id": f["id"],
                "autor_id": f["autor_id"],
                "username": perfiles.get(f["autor_id"], {}).get("username") or "Usuario",
                "avatar_url": perfiles.get(f["autor_id"], {}).get("avatar_url") or "",
                "texto": f.get("texto") or "",
                "creado_en": f.get("creado_en"),
                "mio": f["autor_id"] == yo,
            } for f in filas]}
        except Exception as e:
            return {"exito": False, "error": self._error_publicaciones(e)}

    # Valida el texto, guarda el comentario y devuelve los contadores.
    def comentar_publicacion(self, pub_id, texto):
        error = self._requiere_sesion()
        if error:
            return error
        texto = (texto or "").strip()
        if not texto:
            return {"exito": False, "error": "Escribí un comentario."}
        if len(texto) > self.LIMITE_COMENTARIO:
            return {"exito": False, "error": f"El comentario es demasiado largo (máximo {self.LIMITE_COMENTARIO} caracteres)."}
        try:
            res = self.client.table("publicaciones_comentarios").insert({
                "publicacion_id": int(pub_id), "autor_id": self._yo(), "texto": texto}).execute()
            fila = (res.data or [None])[0]
            if not fila:
                return {"exito": False, "error": "No se pudo comentar."}
            yo = self._perfiles_por_id([self._yo()]).get(self._yo(), {})
            comentario = {
                "id": fila["id"], "autor_id": self._yo(),
                "username": yo.get("username") or "Usuario", "avatar_url": yo.get("avatar_url") or "",
                "texto": fila.get("texto") or texto, "creado_en": fila.get("creado_en"), "mio": True,
            }
            return self._devolver_publicacion(pub_id, comentario=comentario)
        except Exception as e:
            bajo = str(e).lower()
            if "foreign key" in bajo or "23503" in bajo:
                return {"exito": False, "no_existe": True, "error": "Esa publicación ya no existe."}
            return {"exito": False, "error": self._error_publicaciones(e)}

    def eliminar_comentario(self, comentario_id, pub_id):
        """Podés borrar tus comentarios y los que te hicieron en tus publicaciones."""
        error = self._requiere_sesion()
        if error:
            return error
        try:
            res = self.client.table("publicaciones_comentarios").delete().eq("id", comentario_id).execute()
            if not res.data:
                return {"exito": False, "error": "No podés borrar ese comentario."}
            return self._devolver_publicacion(pub_id)
        except Exception as e:
            return {"exito": False, "error": self._error_publicaciones(e)}

    # --- FUNCIONES DE PERFIL DE USUARIO ---

    def obtener_perfil(self, user_id=None):
        """Obtiene el perfil extendido (bio, avatar, etc.) desde la tabla 'profiles'."""
        if not self.client:
            return {"exito": False, "error": "Sin conexión a Supabase."}
        
        target_id = user_id or (self.usuario_actual.id if self.usuario_actual else None)
        if not target_id:
            return {"exito": False, "error": "No hay sesión activa."}

        try:
            res = self.client.table("profiles").select("*").eq("id", target_id).execute()
            if res.data and len(res.data) > 0:
                return {"exito": True, "perfil": res.data[0]}
            return {"exito": False, "error": "Perfil no encontrado."}
        except Exception as e:
            return {"exito": False, "error": str(e)}

    def actualizar_perfil(self, bio="", username=None):
        """Actualiza la biografía y/o el nombre de usuario manteniendo intactos los demás campos."""
        if not self.client or not self.usuario_actual:
            return {"exito": False, "error": "Debes iniciar sesión."}

        try:
            datos_actualizar = {}
            if bio is not None:
                datos_actualizar["bio"] = bio
            if username:
                datos_actualizar["username"] = username

            # Actualizar en la base de datos
            self.client.table("profiles").update(datos_actualizar).eq("id", self.usuario_actual.id).execute()
            
            # Obtener y retornar la versión actualizada
            return self.obtener_perfil()
        except Exception as e:
            return {"exito": False, "error": str(e)}

    def cambiar_username(self, nuevo_username):
        """Cambia el username verificando previamente que no esté ocupado por otro usuario."""
        if not self.client or not self.usuario_actual:
            return {"exito": False, "error": "Debes iniciar sesión."}

        nuevo_username = nuevo_username.strip()
        if not nuevo_username:
            return {"exito": False, "error": "El nombre de usuario no puede estar vacío."}

        try:
            # 1. Comprobar si el username ya existe en otro perfil
            res_existente = self.client.table("profiles")\
                .select("id")\
                .eq("username", nuevo_username)\
                .neq("id", self.usuario_actual.id)\
                .execute()

            if res_existente.data and len(res_existente.data) > 0:
                return {"exito": False, "error": f"El nombre de usuario '{nuevo_username}' ya está en uso por otro usuario."}

            # 2. Si está libre, actualizar en la tabla profiles
            self.client.table("profiles")\
                .update({"username": nuevo_username})\
                .eq("id", self.usuario_actual.id)\
                .execute()

            # 3. Retornar el perfil actualizado
            return self.obtener_perfil()
        except Exception as e:
            return {"exito": False, "error": str(e)}

    # Sube tu foto; ?t=... evita que se siga mostrando la versión anterior en caché.
    def subir_avatar(self, ruta_imagen_local):
        if not self.client or not self.usuario_actual:
            return {"exito": False, "error": "Debes iniciar sesión."}

        if not os.path.exists(ruta_imagen_local):
            return {"exito": False, "error": "El archivo de imagen no existe."}

        try:
            nombre_archivo = f"avatar_{self.usuario_actual.id}.png"
            
            with open(ruta_imagen_local, 'rb') as f:
                self.client.storage.from_("avatars").upload(
                    file=f,
                    path=nombre_archivo,
                    file_options={"x-upsert": "true", "content-type": "image/png"}
                )

            # Obtener URL pública con parametro de tiempo para refrescar cache
            url_base = self.client.storage.from_("avatars").get_public_url(nombre_archivo)
            url_publica = f"{url_base}?t={int(os.path.getmtime(ruta_imagen_local))}"

            # Guardar la URL en el perfil
            self.client.table("profiles").update({"avatar_url": url_publica}).eq("id", self.usuario_actual.id).execute()

            # Retornar objeto completo de perfil actualizado
            res_perfil = self.obtener_perfil()
            return {"exito": True, "avatar_url": url_publica, "perfil": res_perfil.get("perfil", {})}
        except Exception as e:
            return {"exito": False, "error": str(e)}

