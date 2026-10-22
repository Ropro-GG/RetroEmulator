import os
import mimetypes
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from supabase import create_client, Client

import session_store
from pathlib import Path

from boxart import analizar_titulo

# El .env se busca junto a este archivo, sin importar desde dónde se ejecute la app
RUTA_ENV = Path(__file__).resolve().parent / ".env"
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


class CloudClient:
    def __init__(self):
        self.client: Client = None
        self.usuario_actual = None
        self._email_recordar = None   # correo con confirmación de "Recuérdame" pendiente
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
    # Requiere las tablas de supabase_social.sql (friendships y presencia).

    VIGENCIA_PRESENCIA_HORAS = 8   # pasado este tiempo se ignora un "jugando" que quedó colgado

    @staticmethod
    def _error_social(e):
        texto = str(e)
        bajo = texto.lower()
        if "does not exist" in bajo or "could not find the table" in bajo or "schema cache" in bajo or "pgrst205" in bajo:
            return "Faltan las tablas de Social en Supabase. Ejecutá el archivo supabase_social.sql en el SQL Editor."
        if "jwt expired" in bajo or "invalid jwt" in bajo or "pgrst303" in bajo:
            return "Tu sesión venció. Cerrá sesión y volvé a iniciarla."
        if "permission denied" in bajo or "row-level security" in bajo or "42501" in bajo:
            return "Supabase rechazó la operación por permisos. Ejecutá la versión más reciente de supabase_social.sql."
        if any(x in bajo for x in ("name resolution", "connecterror", "connection", "timed out",
                                   "timeout", "unreachable", "temporary failure")):
            return "No se pudo conectar con el servidor. Revisá tu conexión a internet."
        return texto

    def _yo(self):
        return self.usuario_actual.id if self.usuario_actual else None

    def _requiere_sesion(self):
        if not self.client or not self.usuario_actual:
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

    def _perfiles_por_id(self, ids):
        if not ids:
            return {}
        res = self.client.table("profiles").select("id, username, avatar_url").in_("id", list(ids)).execute()
        return {p["id"]: p for p in (res.data or [])}

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
        ahora = datetime.now(timezone.utc)
        vigentes = {}
        for r in res.data or []:
            try:
                desde = datetime.fromisoformat(str(r["desde"]).replace("Z", "+00:00"))
            except ValueError:
                continue
            if ahora - desde < timedelta(hours=self.VIGENCIA_PRESENCIA_HORAS):
                vigentes[r["user_id"]] = {"titulo": r["titulo"], "consola": r.get("consola", "")}
        return vigentes

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
                    amigos.append(item)
                elif f["requester_id"] == yo:
                    enviadas.append(item)
                else:
                    recibidas.append(item)

            # Primero los que están jugando, después por orden alfabético
            amigos.sort(key=lambda a: (a["jugando"] is None, a["username"].lower()))
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
            if not res.data:
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
            recientes, en_comun = self._historial_con_amigo(yo, user_id) if relacion == "amigos" else ([], [])
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
                "recientes": recientes,
                "en_comun": en_comun,
            }
        except Exception as e:
            return {"exito": False, "error": self._error_social(e)}

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

    def limpiar_jugando(self):
        if not self.client or not self.usuario_actual:
            return
        try:
            self.client.table("presencia").delete().eq("user_id", self._yo()).execute()
        except Exception as e:
            print(f"[SOCIAL] No se pudo limpiar la actividad: {self._error_social(e)}")

    # --- HISTORIAL DE JUEGOS (visible solo para tus amigos) ---
    # Requiere la tabla y la función de supabase_social.sql (juegos_jugados / registrar_jugada).

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
                .select("user_id, clave, titulo, consola, veces, ultima_vez") \
                .in_("user_id", [yo, amigo]).execute()
        except Exception as e:
            print(f"[SOCIAL] Sin historial disponible: {self._error_social(e)}")
            return [], []
        filas = res.data or []
        mios = {r["clave"] for r in filas if r["user_id"] == yo}
        suyos = sorted((r for r in filas if r["user_id"] == amigo),
                       key=lambda r: r.get("ultima_vez") or "", reverse=True)
        recientes = [{"titulo": r["titulo"], "consola": r.get("consola", ""),
                      "veces": r.get("veces", 1), "ultima_vez": r.get("ultima_vez")} for r in suyos[:8]]
        en_comun = sorted(({"titulo": r["titulo"], "consola": r.get("consola", "")}
                           for r in suyos if r["clave"] in mios), key=lambda j: j["titulo"].lower())
        return recientes, en_comun

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

    def obtener_amigos_con_deseado(self, titulo, consola):
        """TODO: consultar en Supabase qué amigos tienen este juego en su lista de deseados."""
        return []

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

if __name__ == "__main__":
    cliente = CloudClient()