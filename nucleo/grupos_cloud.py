"""
grupos_cloud.py - Grupos de amigos: miembros, invitaciones y chat cifrado.

Para reutilizar el chat existente, un grupo se identifica en él como 'grupo:<id>', en lugar del id de un amigo.
Las reglas de quién puede hacer qué están en la base (supabase/cambios.sql).
"""
from . import cifrado

PREFIJO = "grupo:"
_COLUMNAS = "id, grupo_id, de, contenido, llaves, adjunto, creado_en"
_ERRORES = {
    "solo el creador puede invitar": "Solo quien administra el grupo puede invitar.",
    "solo el creador puede quitar": "Solo quien administra el grupo puede quitar personas.",
    "maximo 20": "Un grupo admite hasta 20 personas.",
    "solo podes invitar": "Solo podés invitar a tus amigos.",
    "no estas en ese grupo": "Ya no estás en ese grupo.",
    "invitacion ya no esta": "Esa invitación ya no está disponible.",
    "grupos_nombre_check": "El nombre debe tener entre 1 y 50 caracteres.",
}


def es_chat_de_grupo(chat_id):
    return str(chat_id or "").startswith(PREFIJO)


def id_de_chat(chat_id):
    return str(chat_id)[len(PREFIJO):]


class Grupos:
    def __init__(self, cloud):
        self.cloud = cloud

    def _error(self, e):
        bajo = str(e).lower()
        print(f"[GRUPOS] Error de Supabase: {e}")
        for clave, texto in _ERRORES.items():
            if clave in bajo:
                return texto
        return self.cloud._error_social(e)

    def _tabla(self, nombre):
        return self.cloud.client.table(nombre)

    def _rpc(self, funcion, **parametros):
        """Ejecuta una operación de la base con el formato de respuesta de la interfaz."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        try:
            return {"exito": True, "dato": self.cloud.client.rpc(funcion, parametros).execute().data}
        except Exception as e:
            return {"exito": False, "error": self._error(e)}

    def _mis_filas(self):
        return self._tabla("grupo_miembros").select("grupo_id, estado, leido_hasta") \
            .eq("usuario_id", self.cloud._yo()).execute().data or []

    def _miembros(self, grupo):
        filas = self._tabla("grupo_miembros").select("usuario_id").eq("grupo_id", grupo).eq("estado", "miembro").execute().data
        return [f["usuario_id"] for f in filas or []]

    def _nombres(self, grupos):
        filas = self._tabla("grupos").select("id, nombre, creador_id").in_("id", list(grupos)).execute().data or [] if grupos else []
        return {f["id"]: f for f in filas}

    def _sin_leer(self, grupo, leido_hasta):
        """Cuenta solo lo que sí puedo leer: la base oculta lo que no fue cifrado para mí."""
        return self._tabla("mensajes_grupo").select("id", count="exact").eq("grupo_id", grupo) \
            .gt("id", leido_hasta).neq("de", self.cloud._yo()).limit(1).execute().count or 0

    def resumen(self):
        """Invitaciones pendientes y mensajes sin leer, para las insignias."""
        filas = self._mis_filas()
        return {"invitaciones": sum(1 for f in filas if f["estado"] == "invitado"),
                "mensajes": sum(self._sin_leer(f["grupo_id"], f["leido_hasta"]) for f in filas if f["estado"] == "miembro")}

    def listar(self):
        """Mis grupos y mis invitaciones."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        try:
            filas = self._mis_filas()
            datos = self._nombres({f["grupo_id"] for f in filas})
            perfiles = self.cloud._perfiles_por_id({d["creador_id"] for d in datos.values() if d.get("creador_id")})
            salida = {"miembro": [], "invitado": []}
            for f in filas:
                d = datos.get(f["grupo_id"])
                if d:
                    salida[f["estado"]].append({
                        "id": d["id"], "chat_id": PREFIJO + d["id"], "nombre": d["nombre"],
                        "soy_creador": d.get("creador_id") == self.cloud._yo(),
                        "creador": (perfiles.get(d.get("creador_id")) or {}).get("username") or "Alguien",
                    })
            salida["miembro"].sort(key=lambda g: g["nombre"].lower())
            return {"exito": True, "grupos": salida["miembro"], "invitaciones": salida["invitado"]}
        except Exception as e:
            return {"exito": False, "error": self._error(e)}

    def crear(self, nombre, amigo_ids):
        res = self._rpc("crear_grupo", p_nombre=(nombre or "").strip(), p_usuarios=list(amigo_ids or []))
        return {"exito": True, "chat_id": PREFIJO + res["dato"]} if res.get("exito") else res

    def invitar(self, chat_id, amigo_ids):
        return self._rpc("invitar_a_grupo", p_grupo=id_de_chat(chat_id), p_usuarios=list(amigo_ids or []))

    def responder(self, grupo_id, aceptar):
        return self._rpc("responder_invitacion_grupo", p_grupo=grupo_id, p_aceptar=bool(aceptar))

    def quitar(self, chat_id, usuario_id):
        return self._rpc("quitar_de_grupo", p_grupo=id_de_chat(chat_id), p_usuario=usuario_id)

    def salir(self, chat_id):
        return self._rpc("salir_de_grupo", p_grupo=id_de_chat(chat_id))

    def miembros_con_perfil(self, chat_id):
        """Personas del grupo y el estado de su llave, para la ventana de miembros y el aviso del chat."""
        error = self.cloud._requiere_sesion()
        if error:
            return error
        try:
            grupo, yo = id_de_chat(chat_id), self.cloud._yo()
            filas = self._tabla("grupo_miembros").select("usuario_id, estado").eq("grupo_id", grupo).execute().data or []
            perfiles = self.cloud._perfiles_por_id([f["usuario_id"] for f in filas])
            datos = self._nombres({grupo}).get(grupo) or {}
            miembros = []
            for f in filas:
                u = f["usuario_id"]
                estado = self.cloud.llaves.estado_amigo(u) if u != yo and f["estado"] == "miembro" else {}
                p = perfiles.get(u) or {}
                miembros.append({"user_id": u, "username": p.get("username") or "Usuario", "avatar_url": p.get("avatar_url") or "",
                                 "estado": f["estado"], "es_creador": u == datos.get("creador_id"), "soy_yo": u == yo,
                                 "llave": estado.get("estado")})
            miembros.sort(key=lambda m: (not m["es_creador"], m["estado"] != "miembro", m["username"].lower()))
            return {"exito": True, "nombre": datos.get("nombre", ""), "soy_creador": datos.get("creador_id") == yo, "miembros": miembros}
        except Exception as e:
            return {"exito": False, "error": self._error(e)}

    # --- Chat -------------------------------------------------------------------------------------

    def conversaciones(self):
        """Un renglón por grupo, con el mismo formato que los chats con amigos."""
        filas = [f for f in self._mis_filas() if f["estado"] == "miembro"]
        datos = self._nombres({f["grupo_id"] for f in filas})
        salida = []
        for f in filas:
            d = datos.get(f["grupo_id"])
            if not d:
                continue
            ultimo = self._tabla("mensajes_grupo").select(_COLUMNAS).eq("grupo_id", d["id"]).order("id", desc=True).limit(1).execute().data
            salida.append({
                "user_id": PREFIJO + d["id"], "es_grupo": True, "username": d["nombre"], "avatar_url": "",
                "jugando": None, "en_llamada": False, "no_leidos": self._sin_leer(d["id"], f["leido_hasta"]),
                "ultimo": self._resumen(ultimo[0]) if ultimo else None,
            })
        salida.sort(key=lambda c: (c["ultimo"] is None, -(c["ultimo"]["id"] if c["ultimo"] else 0), c["username"].lower()))
        return salida

    def _resumen(self, fila):
        abierto = self.cloud.llaves.abrir_grupo(fila)
        return {"id": fila["id"], "mio": fila["de"] == self.cloud._yo(), "texto": self.cloud._resumen_mensaje(abierto),
                "creado_en": fila.get("creado_en")}

    def _para_ui(self, filas):
        perfiles = self.cloud._perfiles_por_id({f["de"] for f in filas if f.get("de")})
        salida = []
        for f in filas:
            abierto = self.cloud.llaves.abrir_grupo(f)
            salida.append({"id": f["id"], "tipo": abierto["tipo"], "contenido": abierto["contenido"],
                           "alerta_llave": abierto["alerta_llave"], "mio": f["de"] == self.cloud._yo(),
                           "autor": (perfiles.get(f.get("de")) or {}).get("username") or "Usuario",
                           "creado_en": f.get("creado_en"), "en_grupo": True})
        return salida

    def _marcar_leido(self, grupo, filas):
        if filas:
            self.cloud.client.rpc("marcar_grupo_leido", {"p_grupo": grupo, "p_hasta": max(f["id"] for f in filas)}).execute()

    def mensajes(self, chat_id, antes_id, limite):
        grupo = id_de_chat(chat_id)
        try:
            consulta = self._tabla("mensajes_grupo").select(_COLUMNAS).eq("grupo_id", grupo).order("id", desc=True).limit(limite)
            if antes_id:
                consulta = consulta.lt("id", antes_id)
            filas = list(reversed(consulta.execute().data or []))
            if not antes_id:
                self._marcar_leido(grupo, filas)
            return {"exito": True, "mensajes": self._para_ui(filas), "hay_mas": len(filas) >= limite}
        except Exception as e:
            return {"exito": False, "error": self._error(e)}

    def sincronizar(self, chat_id, ultimo_id):
        grupo = id_de_chat(chat_id)
        try:
            filas = self._tabla("mensajes_grupo").select(_COLUMNAS).eq("grupo_id", grupo) \
                .gt("id", ultimo_id or 0).order("id").limit(100).execute().data or []
            self._marcar_leido(grupo, filas)
            return {"exito": True, "nuevos": self._para_ui(filas), "vistos": []}
        except Exception as e:
            return {"exito": False, "error": self._error(e)}

    def insertar(self, chat_id, tipo, contenido, adjunto=None, llave=None):
        grupo = id_de_chat(chat_id)
        try:
            miembros = self._miembros(grupo)
            if self.cloud._yo() not in miembros:
                return {"exito": False, "error": "Ya no estás en este grupo."}
            cifrado_, copias = self.cloud.llaves.cifrar_grupo(grupo, miembros, tipo, contenido, llave)
            filas = self._tabla("mensajes_grupo").insert({"grupo_id": grupo, "de": self.cloud._yo(), "contenido": cifrado_,
                                                          "llaves": copias, "adjunto": adjunto}).execute().data
            if not filas:
                return {"exito": False, "error": "No se pudo enviar el mensaje."}
            return {"exito": True, "mensaje": self._para_ui(filas)[0]}
        except cifrado.SinLlave as e:
            return {"exito": False, "error": str(e), "falta_mi_llave": e.propia}
        except Exception as e:
            bajo = str(e).lower()
            if "row-level security" in bajo or "42501" in bajo:
                return {"exito": False, "error": "Ya no estás en este grupo."}
            return {"exito": False, "error": self._error(e)}
