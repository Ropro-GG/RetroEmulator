"""
llamadas_cloud.py - Parte de las llamadas que habla con Supabase desde Python.

Se encarga de crear la llamada, invitar amigos, aceptar/rechazar y salir.
El audio, el video y las señales de conexión (WebRTC) viajan por el JS (ui/llamadas.js), no por aquí.
"""
from datetime import datetime, timezone

from . import cloud_client, db_local


# Fecha y hora actual en UTC, en el formato de la base de datos.
def _ahora():
    return datetime.now(timezone.utc).isoformat()


# Operaciones de llamadas en Supabase; la conexión de audio y video va en ui/llamadas.js.
class Llamadas:
    # Reutiliza la sesión de CloudClient.
    def __init__(self, cloud):
        self.cloud = cloud          # instancia de CloudClient (reutiliza su sesión)
        self.activa = None          # llamada en la que estoy (para salir de ella al cerrar la app)

    # -- utilidades -------------------------------------------------------
    def _error(self, e):
        texto = str(e)
        bajo = texto.lower()
        print(f"[LLAMADAS] Error de Supabase: {texto}")      # queda en la terminal para depurar
        if "llamada" in bajo and ("does not exist" in bajo or "pgrst205" in bajo or "42p01" in bajo):
            return "Faltan las tablas de Llamadas en Supabase."
        if "invitar_a_llamada" in bajo and ("could not find" in bajo or "does not exist" in bajo or "pgrst202" in bajo):
            return "Falta actualizar las llamadas en Supabase."
        if "maximo 6" in bajo:
            return "Una llamada admite hasta 6 personas."
        if "la llamada ya termino" in bajo or "no estas en esa llamada" in bajo:
            return "Esa llamada ya no está disponible."
        if "42501" in bajo or "row-level security" in bajo or "permission denied" in bajo:
            return "Supabase rechazó la operación de llamadas por permisos. Detalle: " + texto[:240]
        return self.cloud._error_social(e)

    # Atajo para consultar una tabla.
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

    # -- "en llamada" para los amigos ---------------------------------------
    def actualizar_presencia(self):
        """Publica o borra 'en llamada' según la llamada actual y el ajuste de Privacidad.
        Un fallo acá nunca debe afectar a la llamada."""
        yo = self.cloud._yo()
        if not self.cloud.client or not yo:
            return
        try:
            tabla = self._tabla("presencia_llamada")
            if self.activa and db_local.obtener_config_usuario("compartir_actividad", "1") == "1":
                tabla.upsert({"user_id": yo, "desde": _ahora()}).execute()
            else:
                tabla.delete().eq("user_id", yo).execute()
        except Exception as e:
            print(f"[LLAMADAS] No se pudo actualizar 'en llamada': {e}")

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
            self.activa = llamada_id
            self.actualizar_presencia()
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

    # Registra la respuesta; quien atiende primero marca el inicio de la llamada.
    def responder_llamada(self, llamada_id, aceptar):
        error = self.cloud._requiere_sesion()
        if error:
            return error
        yo = self.cloud._yo()
        try:
            if aceptar:
                # Si quien llama colgó justo antes de atender, no se revive una llamada terminada
                fila = self._tabla("llamadas").select("estado").eq("id", llamada_id).limit(1).execute().data
                if not fila or fila[0]["estado"] == "terminada":
                    return {"exito": False, "error": "Esa llamada ya terminó."}
            self._tabla("llamada_participantes") \
                .update({"estado": "unido" if aceptar else "rechazado"}) \
                .eq("llamada_id", llamada_id).eq("usuario_id", yo).execute()
            if aceptar:
                # La primera persona que atiende marca el inicio real de la llamada
                self._tabla("llamadas").update({"estado": "en_curso", "inicio_en": _ahora()}) \
                    .eq("id", llamada_id).is_("inicio_en", "null").neq("estado", "terminada").execute()
                self.activa = llamada_id
                self.actualizar_presencia()
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
            if self.activa == llamada_id:
                self.activa = None
                self.actualizar_presencia()
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": self._error(e)}

    def salir_activa(self):
        """Al cerrar la app en plena llamada: sale de ella para que no quede abierta para siempre."""
        if self.activa:
            self.salir_llamada(self.activa)

    def limpiar_colgadas(self):
        """Al entrar a la cuenta no puedo estar en ninguna llamada: cierra las que quedaron
        abiertas por un corte de luz o un cierre forzado.
        shortcut: con la misma cuenta abierta en dos equipos saca al otro de la llamada en la base;
        si eso llega a importar, hace falta un latido periódico por participante."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        yo = self.cloud._yo()
        self.activa = None
        self.actualizar_presencia()
        try:
            filas = self._tabla("llamada_participantes").select("llamada_id") \
                .eq("usuario_id", yo).eq("estado", "unido").execute().data or []
            for f in filas:
                llamada_id = f["llamada_id"]
                self._tabla("llamada_participantes").update({"estado": "salio"}) \
                    .eq("llamada_id", llamada_id).eq("usuario_id", yo).execute()
                quedan = self._tabla("llamada_participantes").select("usuario_id") \
                    .eq("llamada_id", llamada_id).eq("estado", "unido").execute().data
                if quedan:
                    continue
                datos = self._tabla("llamadas").select("creada_en, inicio_en") \
                    .eq("id", llamada_id).limit(1).execute().data
                if datos:
                    # No se sabe cuándo se cortó: mejor 0 s en el registro que horas inventadas
                    fin = datos[0].get("inicio_en") or datos[0]["creada_en"]
                    self._tabla("llamadas").update({"estado": "terminada", "terminada_en": fin}) \
                        .eq("id", llamada_id).neq("estado", "terminada").execute()
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": self._error(e)}

    def historial_con(self, amigo_id, limite=40):
        """Llamadas ya terminadas en las que participaron vos y este amigo, para mostrarlas
        como registro dentro del chat (duración, horarios y cuántas personas hubo)."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        yo = self.cloud._yo()
        try:
            # Solo se ven las filas de llamadas en las que estoy, así que esto ya es "con vos"
            filas = self._tabla("llamada_participantes").select("llamada_id") \
                .eq("usuario_id", amigo_id).order("invitado_en", desc=True).limit(300).execute().data or []
            ids = list(dict.fromkeys(f["llamada_id"] for f in filas))
            if not ids:
                return {"exito": True, "llamadas": []}
            llamadas = self._tabla("llamadas") \
                .select("id, creador_id, con_video, creada_en, inicio_en, terminada_en") \
                .in_("id", ids).eq("estado", "terminada") \
                .order("terminada_en", desc=True).limit(int(limite)).execute().data or []
            if not llamadas:
                return {"exito": True, "llamadas": []}
            partes = self._tabla("llamada_participantes").select("llamada_id, usuario_id, estado") \
                .in_("llamada_id", [l["id"] for l in llamadas]).execute().data or []

            # Convierte un texto a fecha; devuelve None si no es válido.
            def fecha(texto):
                try:
                    return datetime.fromisoformat(texto)
                except (TypeError, ValueError):
                    return None

            salida = []
            for l in llamadas:
                suyas = [p for p in partes if p["llamada_id"] == l["id"]]
                inicio, fin = fecha(l.get("inicio_en")), fecha(l.get("terminada_en"))
                if inicio:
                    resultado = "completada"
                elif any(p["estado"] == "rechazado" for p in suyas):
                    resultado = "rechazada"
                else:
                    resultado = "sin_respuesta"
                salida.append({
                    "id": l["id"],
                    "resultado": resultado,
                    "yo_llame": l["creador_id"] == yo,
                    "con_video": bool(l.get("con_video")),
                    "rechazada_por_mi": any(p["usuario_id"] == yo and p["estado"] == "rechazado" for p in suyas),
                    "duracion_s": max(0, int((fin - inicio).total_seconds())) if inicio and fin else 0,
                    "inicio": l.get("inicio_en") or l.get("creada_en"),
                    "fin": l.get("terminada_en") or l.get("creada_en"),
                    "personas": sum(1 for p in suyas if p["estado"] in ("unido", "salio")),
                })
            return {"exito": True, "llamadas": salida}
        except Exception as e:
            return {"exito": False, "error": self._error(e)}

    def invitar(self, llamada_id, amigo_ids):
        """Agrega amigos a una llamada en la que ya estás (máx. 6 personas)."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        yo = self.cloud._yo()
        ids = [i for i in dict.fromkeys(amigo_ids or []) if i and i != yo]
        if not ids:
            return {"exito": False, "error": "Elegí a quién invitar."}
        try:
            validos = set(self.cloud._amigos_aceptados())
            if any(i not in validos for i in ids):
                return {"exito": False, "error": "Solo podés invitar a tus amigos."}
            self.cloud.client.rpc("invitar_a_llamada", {"p_llamada": llamada_id, "p_usuarios": ids}).execute()
            return {"exito": True}
        except Exception as e:
            return {"exito": False, "error": self._error(e)}
