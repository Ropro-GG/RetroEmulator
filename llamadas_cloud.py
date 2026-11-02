"""
llamadas_cloud.py - Parte de las llamadas que habla con Supabase desde Python.

Se encarga de crear la llamada, invitar amigos, aceptar/rechazar y salir.
Los audios y las señales de conexión (WebRTC) viajan por el JS (ui/llamadas.js),
no por aquí. Requiere supabase_llamadas.sql y supabase_llamadas_fase2.sql.
"""
from datetime import datetime, timezone

import cloud_client


def _ahora():
    return datetime.now(timezone.utc).isoformat()


class Llamadas:
    def __init__(self, cloud):
        self.cloud = cloud          # instancia de CloudClient (reutiliza su sesión)

    # -- utilidades -------------------------------------------------------
    def _error(self, e):
        bajo = str(e).lower()
        if "llamada" in bajo and ("does not exist" in bajo or "pgrst205" in bajo or "42p01" in bajo):
            return "Faltan las tablas de Llamadas en Supabase. Ejecutá supabase_llamadas.sql en el SQL Editor."
        return self.cloud._error_social(e)

    def _tabla(self, nombre):
        return self.cloud.client.table(nombre)

    # -- configuración para el JS (Realtime) -------------------------------
    def config_realtime(self):
        """URL, clave pública y token de la sesión actual, para que el JS escuche Realtime.
        La clave debe ser la 'anon/publishable' de Supabase (nunca la service_role)."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        try:
            sesion = self.cloud.client.auth.get_session()
            if not sesion or not sesion.access_token:
                return {"exito": False, "error": "No hay sesión activa."}
            return {
                "exito": True,
                "url": cloud_client.SUPABASE_URL,
                "anon_key": cloud_client.SUPABASE_KEY,
                "token": sesion.access_token,
                "user_id": self.cloud._yo(),
            }
        except Exception as e:
            return {"exito": False, "error": self._error(e)}

    # -- llamadas ----------------------------------------------------------
    def crear_llamada(self, amigo_ids, con_video=False):
        error = self.cloud._requiere_sesion()
        if error:
            return error
        yo = self.cloud._yo()
        ids = [i for i in dict.fromkeys(amigo_ids or []) if i and i != yo]
        if not ids:
            return {"exito": False, "error": "Elegí a quién llamar."}
        try:
            if any(i not in set(self.cloud._amigos_aceptados()) for i in ids):
                return {"exito": False, "error": "Solo podés llamar a tus amigos."}
            fila = self._tabla("llamadas").insert({"creador_id": yo, "con_video": bool(con_video)}).execute()
            llamada_id = fila.data[0]["id"]
            self._tabla("llamada_participantes").insert(
                {"llamada_id": llamada_id, "usuario_id": yo, "estado": "unido", "invitado_por": yo}).execute()
            self._tabla("llamada_participantes").insert(
                [{"llamada_id": llamada_id, "usuario_id": i, "estado": "invitado", "invitado_por": yo}
                 for i in ids]).execute()
            return {"exito": True, "llamada_id": llamada_id}
        except Exception as e:
            return {"exito": False, "error": self._error(e)}

    def obtener_llamada(self, llamada_id):
        """Datos de una llamada y de sus participantes (para mostrar quién llama)."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        try:
            fila = self._tabla("llamadas").select("id, creador_id, estado, con_video, creada_en") \
                .eq("id", llamada_id).limit(1).execute().data
            if not fila:
                return {"exito": False, "error": "La llamada ya no existe."}
            partes = self._tabla("llamada_participantes").select("usuario_id, estado") \
                .eq("llamada_id", llamada_id).execute().data or []
            perfiles = self.cloud._perfiles_por_id([p["usuario_id"] for p in partes])
            return {
                "exito": True,
                "llamada": fila[0],
                "participantes": [{
                    "user_id": p["usuario_id"],
                    "estado": p["estado"],
                    "username": (perfiles.get(p["usuario_id"]) or {}).get("username", ""),
                    "avatar_url": (perfiles.get(p["usuario_id"]) or {}).get("avatar_url", ""),
                } for p in partes],
            }
        except Exception as e:
            return {"exito": False, "error": self._error(e)}

    def responder_llamada(self, llamada_id, aceptar):
        error = self.cloud._requiere_sesion()
        if error:
            return error
        yo = self.cloud._yo()
        try:
            self._tabla("llamada_participantes") \
                .update({"estado": "unido" if aceptar else "rechazado"}) \
                .eq("llamada_id", llamada_id).eq("usuario_id", yo).execute()
            if aceptar:
                self._tabla("llamadas").update({"estado": "en_curso"}) \
                    .eq("id", llamada_id).eq("estado", "sonando").execute()
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": self._error(e)}

    def salir_llamada(self, llamada_id, terminar=False):
        """Marca que saliste. Si ya no queda nadie unido (o 'terminar'), la llamada se cierra."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        yo = self.cloud._yo()
        try:
            self._tabla("llamada_participantes").update({"estado": "salio"}) \
                .eq("llamada_id", llamada_id).eq("usuario_id", yo).execute()
            quedan = self._tabla("llamada_participantes").select("usuario_id") \
                .eq("llamada_id", llamada_id).eq("estado", "unido").execute().data or []
            if terminar or not quedan:
                self._tabla("llamadas").update({"estado": "terminada", "terminada_en": _ahora()}) \
                    .eq("id", llamada_id).neq("estado", "terminada").execute()
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": self._error(e)}
