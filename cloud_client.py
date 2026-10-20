import os
import mimetypes
from dotenv import load_dotenv
from supabase import create_client, Client

import session_store

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

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
                print("[CLOUD ADVERTENCIA] No se encontraron SUPABASE_URL o SUPABASE_KEY en el archivo .env.")
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
        try:
            if self.client:
                self.client.auth.sign_out()
        except Exception:
            pass
        session_store.borrar("sesion")
        self.usuario_actual = None
        self._email_recordar = None
        return {"exito": True}

    # --- AMIGOS (se desarrollará más adelante) ---

    def obtener_amigos_que_jugaron(self, titulo, consola):
        """TODO: consultar en Supabase qué amigos del usuario jugaron este juego."""
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