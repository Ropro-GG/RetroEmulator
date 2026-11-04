# gui_app.py - Punto de entrada de RetroEmulator.
# Crea la ventana con pywebview, carga ui/index.html y publica la clase API.
# Cada método público de API se puede llamar desde JavaScript como
# window.pywebview.api.nombre_del_metodo(...), y su resultado vuelve como una promesa.
# Esta clase casi no tiene lógica: valida lo básico y delega en los módulos de nucleo/.
import webview
from webview import FileDialog
import json
import os
import threading
import sys
import webbrowser
from urllib.parse import urlparse

from nucleo import boxart, db_local, gifs, imagenes, launcher, ra_client, scanner
from nucleo.cloud_client import CloudClient
from nucleo.db_local import LocalDB
from nucleo.llamadas_cloud import Llamadas

VERSION = "BETA v1"
DESARROLLADOR = "Rocco Flores"
URL_GITHUB = "https://github.com/Ropro-GG/RetroEmulator"
HOSTS_PERMITIDOS = {"github.com", "retroachievements.org"}

# Métodos que la interfaz puede llamar. Los que empiezan con "_" no se exponen a JavaScript.
class API:
    # Crea los servicios una sola vez; la ventana se asigna después con set_window.
    def __init__(self):
        self.db = LocalDB()
        self.cloud = CloudClient()
        self._llamadas = Llamadas(self.cloud)   # '_' = no se expone al JS
        self._llaves = self.cloud.llaves
        self.window = None
        self._juegos_activos = 0          # emuladores abiertos desde el launcher
        self._imagen_elegida = ""         # archivo que elegiste para enviar o convertir en sticker
        self._imagen_publicacion = ""     # imagen elegida para la publicación que estás escribiendo
        self._lock_juegos = threading.Lock()

    # Guarda la ventana: hace falta para abrir los selectores de archivos.
    def set_window(self, window):
        self.window = window

    def _establecer_cuenta(self, resultado):
        """Registra qué cuenta está activa para separar los datos por cuenta en este equipo."""
        if resultado and resultado.get("exito"):
            uid = (resultado.get("usuario") or {}).get("id")
            if uid:
                db_local.establecer_usuario(uid)
                if db_local.adoptar_datos_antiguos(uid):
                    ra_client.adoptar_credenciales_antiguas(uid)

    # Crea la cuenta y la deja activa en este equipo.
    def registrar_usuario(self, email, password, username):
        resultado = self.cloud.registrar_usuario(email, password, username)
        self._establecer_cuenta(resultado)
        return resultado

    def _limpiar_presencia_vieja(self, resultado):
        """Al entrar, borra un 'jugando ahora' que haya quedado colgado (por ejemplo tras un cierre brusco)."""
        if resultado and resultado.get("exito") and self._juegos_activos == 0:
            threading.Thread(target=self.cloud.limpiar_jugando, daemon=True).start()

    # Entra con correo y contraseña; "recordar" inicia la confirmación por correo.
    def iniciar_sesion(self, email, password, recordar=False):
        resultado = self.cloud.iniciar_sesion(email, password, recordar)
        self._establecer_cuenta(resultado)
        self._limpiar_presencia_vieja(resultado)
        return resultado

    # Verifica el código del correo para recordar la sesión en este equipo.
    def confirmar_recordar(self, codigo):
        return self.cloud.confirmar_recordar(codigo)

    # Pide otro código de confirmación.
    def reenviar_codigo_recordar(self):
        return self.cloud.reenviar_codigo_recordar()

    # Al abrir la app, entra solo si había una sesión recordada y sigue siendo válida.
    def restaurar_sesion(self):
        resultado = self.cloud.restaurar_sesion()
        self._establecer_cuenta(resultado)
        self._limpiar_presencia_vieja(resultado)
        return resultado

    # Sale de la cuenta y olvida lo que dependía de ella.
    def cerrar_sesion(self):
        resultado = self.cloud.cerrar_sesion()
        db_local.establecer_usuario("")   # nada de la cuenta anterior queda activo
        self._imagen_elegida = ""
        self._imagen_publicacion = ""
        self._llaves.olvidar_en_pantalla()     # una frase en pantalla no debe pasar a otra cuenta
        return resultado

    # Si esta cuenta ya tiene sus llaves en este equipo o falta crearlas o recuperarlas.
    def llaves_estado(self):
        return self._llaves.estado()

    # Crea una frase de recuperación para mostrarla; reemplazar=True es para quien la perdió.
    def llaves_generar(self, reemplazar=False):
        return self._llaves.generar(reemplazar)

    # Activa la frase mostrada, si el usuario la escribe bien.
    def llaves_confirmar(self, texto):
        return self._llaves.confirmar(texto)

    # Trae las llaves a este equipo con una frase ya existente.
    def llaves_recuperar(self, texto):
        return self._llaves.recuperar(texto)

    # Muestra la frase de este equipo, después de comprobar la contraseña.
    def llaves_ver_frase(self, password):
        return self._llaves.ver_frase(password)

    # Olvida la frase al cerrar la ventana que la muestra.
    def llaves_cerrar(self):
        self._llaves.olvidar_en_pantalla()

    # Guarda la frase en pantalla en el archivo que elija el usuario. Solo el usuario decide la ruta.
    def llaves_guardar_archivo(self):
        texto = self._llaves.texto_para_archivo()
        if not texto or not self.window:
            return {"exito": False, "error": "No hay ninguna frase para guardar."}
        ruta = self.window.create_file_dialog(FileDialog.SAVE, save_filename="frase-retroemulator.txt")
        if isinstance(ruta, (list, tuple)):
            ruta = ruta[0] if ruta else ""
        if not ruta:
            return {"exito": False, "error": "cancelado"}
        try:
            fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(texto)
        except OSError as e:
            return {"exito": False, "error": f"No se pudo guardar el archivo: {e}"}
        return {"exito": True}

    # Perfil propio, o el de otro usuario si se indica su id.
    def obtener_perfil(self, user_id=None):
        return self.cloud.obtener_perfil(user_id)

    # Guarda la biografía y, si se indica, el nombre.
    def actualizar_perfil(self, bio, username=None):
        return self.cloud.actualizar_perfil(bio, username)

    # Cambia el nombre comprobando que no esté ocupado.
    def cambiar_username(self, nuevo_username):
        return self.cloud.cambiar_username(nuevo_username)

    def seleccionar_foto_avatar(self):
        """Abre el selector nativo usando FileDialog.OPEN sin advertencias."""
        if not self.window:
            return {"exito": False, "error": "Ventana no inicializada."}
            
        file_types = ('Archivos de Imagen (*.png;*.jpg;*.jpeg;*.webp)', 'Todos los archivos (*.*)')
        result = self.window.create_file_dialog(FileDialog.OPEN, allow_multiple=False, file_types=file_types)
        
        if result and len(result) > 0:
            ruta_imagen = result[0]
            return self.cloud.subir_avatar(ruta_imagen)
        return {"exito": False, "error": "No se seleccionó ninguna imagen."}

    def escanear_roms(self):
        """Lanza el escaneo (juegos + carátulas) en segundo plano."""
        iniciado = scanner.iniciar_escaneo()
        return {"exito": True, "ya_en_curso": not iniciado}

    def obtener_estado_escaneo(self):
        """La interfaz lo consulta periódicamente para mostrar el progreso."""
        return scanner.estado_escaneo()

    def obtener_portada_data_uri(self, ruta_portada):
        """Plan B si el webview no puede abrir la imagen por file://."""
        return boxart.leer_como_data_uri(ruta_portada)

    def obtener_juegos_filtrados(self, texto_busqueda="", consola_id=None):
        """Retorna juegos filtrados por búsqueda y/o consola para pywebview."""
        juegos = self.db.obtener_juegos_filtrados(texto_busqueda, consola_id)
        for juego in juegos:
            juego["portada_url"] = boxart.ruta_a_uri(juego.get("portada_path"))
        return juegos

    def obtener_consolas(self):
        """Retorna las consolas registradas para llenar el selector/filtro de la UI."""
        return self.db.obtener_consolas()

    def lanzar_juego(self, game_id, variante=False):
        """'variante' = el usuario ya eligió una versión/disco en el selector."""
        return launcher.ejecutar_juego(
            game_id, al_iniciar=self._al_iniciar_juego, al_cerrar=self._al_cerrar_juego, variante=variante)

    def _al_iniciar_juego(self, titulo, consola):
        """Avisa a tus amigos a qué jugás (si no lo desactivaste en Privacidad)."""
        with self._lock_juegos:
            self._juegos_activos += 1
        if db_local.obtener_config_usuario("compartir_actividad", "1") == "1":
            self.cloud.establecer_jugando(titulo, consola)
        if db_local.obtener_config_usuario("compartir_historial", "1") == "1":
            identificativo = db_local.obtener_identificativo_por_consola(consola)
            self.cloud.registrar_jugada(identificativo, titulo, consola)

    # Se llama cuando un emulador se cierra (desde el hilo que lo vigila).
    def _al_cerrar_juego(self):
        # Solo se borra el aviso cuando ya no queda ningún emulador abierto
        with self._lock_juegos:
            self._juegos_activos = max(0, self._juegos_activos - 1)
            quedan = self._juegos_activos
        if quedan == 0:
            self.cloud.limpiar_jugando()

    # --- SOCIAL ---

    # Amigos, solicitudes recibidas y solicitudes enviadas.
    def obtener_social(self):
        return self.cloud.obtener_social()

    def obtener_resumen_social(self):
        """Datos livianos para las insignias: solicitudes pendientes y mensajes sin leer."""
        return self.cloud.resumen_social()

    # --- CHAT ---

    # Lista de chats: último mensaje y cantidad sin leer.
    def obtener_conversaciones(self):
        return self.cloud.obtener_conversaciones()

    # Mensajes de un chat; "antes_id" trae los anteriores a ese mensaje.
    def obtener_mensajes(self, amigo_id, antes_id=None):
        return self.cloud.obtener_mensajes(amigo_id, antes_id)

    # Consulta periódica: mensajes nuevos y cuáles de los míos ya se vieron.
    def sincronizar_chat(self, amigo_id, ultimo_id, ids_pendientes):
        return self.cloud.sincronizar_chat(amigo_id, ultimo_id, ids_pendientes or [])

    # Envía un mensaje de texto.
    def enviar_mensaje(self, amigo_id, texto):
        return self.cloud.enviar_mensaje(amigo_id, texto)

    # --- CHAT: IMÁGENES Y STICKERS ---

    def _elegir_archivo_imagen(self):
        """Selector de imagen compartido. Devuelve (ruta, vista, None) o (None, None, error)."""
        if not self.window:
            return None, None, {"exito": False, "error": "Ventana no inicializada."}
        if not imagenes.disponible():
            return None, None, {"exito": False, "error": "Falta instalar Pillow: ejecutá  pip install pillow  y reiniciá el launcher."}
        resultado = self.window.create_file_dialog(
            FileDialog.OPEN, allow_multiple=False,
            file_types=('Imágenes (*.png;*.jpg;*.jpeg;*.webp;*.bmp)', 'Todos los archivos (*.*)'))
        if not resultado:
            return None, None, {"exito": False, "error": "cancelado"}
        ruta = resultado[0]
        try:
            vista = imagenes.miniatura_data_uri(ruta)
        except imagenes.ErrorImagen as e:
            return None, None, {"exito": False, "error": str(e)}
        return ruta, vista, None

    def seleccionar_imagen(self):
        """Abre el selector de archivos. Queda guardada la ruta elegida (Python no acepta rutas desde la página)."""
        ruta, vista, error = self._elegir_archivo_imagen()
        if error:
            return error
        self._imagen_elegida = ruta
        return {"exito": True, "nombre": os.path.basename(ruta), "vista": vista}

    # Olvida la imagen elegida sin enviarla.
    def descartar_imagen(self):
        self._imagen_elegida = ""
        return {"exito": True}

    # Reduce la imagen elegida, le quita los metadatos y la envía.
    def enviar_imagen(self, amigo_id):
        if not self._imagen_elegida:
            return {"exito": False, "error": "Primero elegí una imagen."}
        try:
            datos, mime, extension = imagenes.preparar_para_chat(self._imagen_elegida)
        except imagenes.ErrorImagen as e:
            return {"exito": False, "error": str(e)}
        resultado = self.cloud.enviar_imagen(amigo_id, datos, mime, extension)
        if resultado.get("exito"):
            self._imagen_elegida = ""
        return resultado

    # Genera la vista previa del sticker con las opciones actuales.
    def previsualizar_sticker(self, forma, ajuste, contorno):
        if not self._imagen_elegida:
            return {"exito": False, "error": "Primero elegí una imagen."}
        try:
            return {"exito": True, "vista": imagenes.vista_sticker(self._imagen_elegida, forma, ajuste, contorno)}
        except imagenes.ErrorImagen as e:
            return {"exito": False, "error": str(e)}

    # Crea el sticker definitivo y lo suma a tu colección.
    def crear_sticker(self, forma, ajuste, contorno):
        if not self._imagen_elegida:
            return {"exito": False, "error": "Primero elegí una imagen."}
        try:
            datos, mime, extension = imagenes.crear_sticker(self._imagen_elegida, forma, ajuste, contorno)
        except imagenes.ErrorImagen as e:
            return {"exito": False, "error": str(e)}
        return self.cloud.guardar_sticker(datos, mime, extension)

    # Stickers de tu colección.
    def obtener_stickers(self):
        return self.cloud.obtener_stickers()

    # Quita un sticker de tu colección.
    def eliminar_sticker(self, sticker_id):
        return self.cloud.eliminar_sticker(sticker_id)

    # Envía uno de tus stickers por el chat.
    def enviar_sticker(self, amigo_id, ruta):
        return self.cloud.enviar_sticker(amigo_id, ruta)

    # --- CHAT: GIFS Y EMOJIS ---

    def buscar_gifs(self, texto, pagina=1):
        """Busca en KLIPY (sin texto devuelve los GIFs del momento)."""
        try:
            resultado = gifs.buscar(texto, pagina, db_local.usuario_id())
        except gifs.ErrorGifs as e:
            return {"exito": False, "error": str(e)}
        except Exception:
            return {"exito": False, "error": "No se pudieron buscar GIFs. Probá de nuevo en un momento."}
        return {"exito": True, **resultado}

    # Envía un GIF de KLIPY por el chat.
    def enviar_gif(self, amigo_id, url):
        return self.cloud.enviar_gif(amigo_id, url)

    # Últimos emojis usados en esta cuenta.
    def obtener_emojis_recientes(self):
        try:
            lista = json.loads(db_local.obtener_config_usuario("emojis_recientes", "[]"))
        except ValueError:
            lista = []
        return [e for e in lista if isinstance(e, str)][:24]

    # Pone un emoji al principio de los recientes (máximo 24).
    def registrar_emoji_reciente(self, emoji):
        if not isinstance(emoji, str) or not emoji or len(emoji) > 16:
            return {"exito": False}
        lista = [e for e in self.obtener_emojis_recientes() if e != emoji]
        lista.insert(0, emoji)
        db_local.guardar_config_usuario("emojis_recientes", json.dumps(lista[:24], ensure_ascii=False))
        return {"exito": True}

    def obtener_imagen_chat(self, ruta):
        """Imagen o sticker de un mensaje, listo para mostrar (data URI), o None."""
        datos = self.cloud.descargar_imagen_chat(ruta)
        return imagenes.a_data_uri(datos) or None if datos else None

    # --- PUBLICACIONES ---

    # Elige la imagen de la publicación que se está escribiendo.
    def seleccionar_imagen_publicacion(self):
        ruta, vista, error = self._elegir_archivo_imagen()
        if error:
            return error
        self._imagen_publicacion = ruta
        return {"exito": True, "nombre": os.path.basename(ruta), "vista": vista}

    # Olvida la imagen elegida para la publicación.
    def descartar_imagen_publicacion(self):
        self._imagen_publicacion = ""
        return {"exito": True}

    def crear_publicacion(self, texto, gif_url=None):
        """Publica texto + (una imagen elegida antes, o un GIF de KLIPY). Es pública para todos."""
        imagen = None
        if not gif_url and self._imagen_publicacion:
            try:
                imagen = imagenes.preparar_para_chat(self._imagen_publicacion)
            except imagenes.ErrorImagen as e:
                return {"exito": False, "error": str(e)}
        resultado = self.cloud.crear_publicacion(texto, imagen, gif_url)
        if resultado.get("exito"):
            self._imagen_publicacion = ""
        return resultado

    # Página del feed; "autor_id" filtra por autor.
    def obtener_publicaciones(self, antes_id=None, autor_id=None):
        return self.cloud.obtener_publicaciones(antes_id, autor_id)

    # Una sola publicación.
    def obtener_publicacion(self, pub_id):
        return self.cloud.obtener_publicacion(pub_id)

    # Borra una publicación propia y su imagen.
    def eliminar_publicacion(self, pub_id):
        return self.cloud.eliminar_publicacion(pub_id)

    # Da o quita un me gusta / no me gusta.
    def alternar_reaccion(self, pub_id, tipo):
        return self.cloud.alternar_reaccion(pub_id, tipo)

    # Envía una publicación por chat a los amigos elegidos.
    def compartir_publicacion(self, pub_id, amigos_ids):
        return self.cloud.compartir_publicacion(pub_id, amigos_ids or [])

    # Quita tu "compartido"; los mensajes ya enviados quedan.
    def quitar_compartido(self, pub_id):
        return self.cloud.quitar_compartido(pub_id)

    # Comentarios de una publicación.
    def obtener_comentarios(self, pub_id):
        return self.cloud.obtener_comentarios(pub_id)

    # Agrega un comentario.
    def comentar_publicacion(self, pub_id, texto):
        return self.cloud.comentar_publicacion(pub_id, texto)

    # Borra un comentario (tuyo, o de una publicación tuya).
    def eliminar_comentario(self, comentario_id, pub_id):
        return self.cloud.eliminar_comentario(comentario_id, pub_id)

    # Busca usuarios por nombre.
    def buscar_usuarios(self, texto):
        return self.cloud.buscar_usuarios(texto)

    # Perfil de otro usuario y su relación contigo.
    def obtener_perfil_social(self, user_id):
        return self.cloud.obtener_perfil_social(user_id)

    # Envía una solicitud de amistad.
    def enviar_solicitud_amistad(self, user_id):
        return self.cloud.enviar_solicitud_amistad(user_id)

    # Acepta o rechaza una solicitud recibida.
    def responder_solicitud_amistad(self, friendship_id, aceptar):
        return self.cloud.responder_solicitud_amistad(friendship_id, aceptar)

    # Quita a un amigo o cancela una solicitud enviada.
    def eliminar_amistad(self, friendship_id):
        return self.cloud.eliminar_amistad(friendship_id)

    # --- BLOQUEAR Y DENUNCIAR ---

    # Bloquea a un usuario y elimina la amistad entre ambos.
    def bloquear_usuario(self, user_id):
        return self.cloud.bloquear_usuario(user_id)

    # Quita un bloqueo; para volver a ser amigos hace falta otra solicitud.
    def desbloquear_usuario(self, user_id):
        return self.cloud.desbloquear_usuario(user_id)

    # Lista de usuarios bloqueados, para Privacidad.
    def obtener_bloqueados(self):
        return self.cloud.obtener_bloqueados()

    # Registra una denuncia, que se revisa en el panel de Supabase.
    def denunciar_usuario(self, user_id, motivo, detalle=""):
        return self.cloud.denunciar_usuario(user_id, motivo, detalle)

    # --- LISTA DE DESEADOS ---

    def buscar_titulos(self, identificativo, texto):
        """Sugerencias de títulos de una consola (para agregar a deseados)."""
        nombre = db_local.obtener_nombre_consola(identificativo)
        return boxart.buscar_titulos(identificativo, nombre, texto)

    # Tu lista de deseados.
    def obtener_mis_deseados(self):
        return self.cloud.obtener_mis_deseados()

    def agregar_deseado(self, identificativo, titulo):
        """Solo se aceptan juegos que existan en el catálogo de la consola; se guarda con su nombre oficial."""
        nombre = db_local.obtener_nombre_consola(identificativo)
        if not (titulo or "").strip():
            return {"exito": False, "error": "Escribí el nombre del juego y elegí uno de los sugeridos."}
        oficial, motivo = boxart.validar_titulo(identificativo, nombre, titulo)
        if not oficial:
            mensajes = {
                "no_existe": f'No encontramos "{(titulo or "").strip()}" en el catálogo de {nombre}. '
                             'Elegí uno de los juegos sugeridos.',
                "sin_conexion": "No se pudo consultar el catálogo (sin conexión). Probá de nuevo en un momento.",
                "sin_catalogo": "Todavía no hay catálogo de juegos para esta consola.",
            }
            return {"exito": False, "error": mensajes.get(motivo, "No se pudo verificar el juego.")}
        publica = db_local.obtener_config_usuario("compartir_deseados", "1") == "1"
        return self.cloud.agregar_deseado(identificativo, oficial, nombre, publica)

    def obtener_consolas_catalogo(self):
        """Solo las consolas que tienen catálogo de juegos (para elegir en la lista de deseados)."""
        con_catalogo = boxart.consolas_con_catalogo()
        return [c for c in self.db.obtener_consolas() if c["identificativo"] in con_catalogo]

    def obtener_portada_juego(self, identificativo, titulo):
        """Carátula de un juego por título (también para juegos que no tenés)."""
        nombre = db_local.obtener_nombre_consola(identificativo)
        ruta = boxart.portada_de_juego(identificativo, nombre, titulo)
        url = boxart.ruta_a_uri(ruta) if ruta else ""
        return {"url": url, "path": ruta} if url else None

    # Juegos recientes y deseados para tu perfil.
    def obtener_mi_actividad(self):
        return self.cloud.obtener_mi_actividad()

    # Quita un juego de tu lista de deseados.
    def quitar_deseado(self, clave):
        return self.cloud.quitar_deseado(clave)

    # --- PRIVACIDAD ---

    def obtener_privacidad(self):
        """Ajustes de privacidad de la cuenta actual (cada cuenta tiene los suyos)."""
        return {
            "actividad": db_local.obtener_config_usuario("compartir_actividad", "1") == "1",
            "historial": db_local.obtener_config_usuario("compartir_historial", "1") == "1",
            "deseados": db_local.obtener_config_usuario("compartir_deseados", "1") == "1",
        }

    # Ajuste de Privacidad: mostrar a qué juegas y si estás en una llamada.
    def guardar_compartir_actividad(self, activo):
        db_local.guardar_config_usuario("compartir_actividad", "1" if activo else "0")
        if not activo:
            self.cloud.limpiar_jugando()   # se borra lo que ya estuviera publicado
        self._llamadas.actualizar_presencia()   # "en llamada" sigue el mismo ajuste
        return {"exito": True}

    def guardar_compartir_deseados(self, activo):
        """La visibilidad se aplica en Supabase a toda tu lista (y a lo que agregues después)."""
        resultado = self.cloud.actualizar_visibilidad_deseados(activo)
        if resultado.get("exito"):
            db_local.guardar_config_usuario("compartir_deseados", "1" if activo else "0")
        return resultado

    # Ajuste de Privacidad: compartir el historial; al apagarlo se borra el publicado.
    def guardar_compartir_historial(self, activo):
        db_local.guardar_config_usuario("compartir_historial", "1" if activo else "0")
        if not activo:
            self.cloud.borrar_historial()   # se borra lo que ya estuviera publicado
        return {"exito": True}

    # --- CONFIGURACIÓN: RUTAS Y EMULADORES ---

    # Carpetas de la app y consolas con juegos, para Configuración.
    def obtener_config_rutas(self):
        return {
            "roms_base": os.path.abspath(boxart.CARPETA_ROMS_BASE),
            "boxarts": os.path.abspath(boxart.CARPETA_BOXARTS),
            "consolas": db_local.obtener_consolas_con_juegos(),
        }

    def seleccionar_ejecutable_emulador(self):
        """Abre el selector de archivos y devuelve la ruta elegida ('' si se cancela)."""
        if not self.window:
            return ""
        resultado = self.window.create_file_dialog(
            FileDialog.OPEN, allow_multiple=False,
            file_types=('Todos los archivos (*.*)',))
        return resultado[0] if resultado else ""

    # Guarda el emulador de una consola, comprobando que exista y se pueda ejecutar.
    def guardar_ruta_emulador(self, consola_id, ruta):
        ruta = os.path.expanduser((ruta or "").strip())
        if ruta:
            if not os.path.isfile(ruta):
                return {"exito": False, "error": "Ese archivo no existe."}
            if not os.access(ruta, os.X_OK):
                return {"exito": False, "error": "El archivo no tiene permiso de ejecución (en Linux: chmod +x)."}
        db_local.actualizar_rutas_consola(consola_id, ruta_emulador=ruta)
        return {"exito": True, "ruta": ruta}

    # --- CONFIGURACIÓN: INFORMACIÓN ---

    # Datos de la sección Información.
    def obtener_info_launcher(self):
        return {
            "version": VERSION,
            "desarrollador": DESARROLLADOR,
            "juegos": db_local.contar_juegos(),
            "emuladores": db_local.contar_emuladores(),
            "github": URL_GITHUB,
        }

    def abrir_enlace(self, url):
        """Abre un enlace en el navegador (solo sitios de la lista permitida)."""
        try:
            partes = urlparse(url)
            if partes.scheme == "https" and partes.hostname in HOSTS_PERMITIDOS:
                webbrowser.open(url)
                return {"exito": True}
        except ValueError:
            pass
        return {"exito": False, "error": "Enlace no permitido."}

    # --- DETALLE DE JUEGO ---

    # Datos de un juego para su pantalla de detalle.
    def obtener_detalle_juego(self, game_id):
        juego = db_local.obtener_juego_detalle(game_id)
        if not juego:
            return {"exito": False, "error": "No se encontró el juego."}
        juego["portada_url"] = boxart.ruta_a_uri(juego.get("portada_path"))
        juego["opinion"] = db_local.obtener_opinion(juego["consola_id"], juego["titulo"])
        return {"exito": True, "juego": juego}

    def guardar_opinion(self, game_id, puntuacion, texto, publica=True):
        """Guarda la opinión en tu equipo y la publica para tus amigos (si la dejás visible)."""
        juego = db_local.obtener_juego_detalle(game_id)
        if not juego:
            return {"exito": False, "error": "No se encontró el juego."}
        db_local.guardar_opinion(juego["consola_id"], juego["titulo"], puntuacion, texto, publica)
        publicada = self.cloud.publicar_opinion(
            juego["identificativo"], juego["titulo"], juego["consola"],
            puntuacion, texto, publica)
        if not publicada.get("exito"):
            return {"exito": True, "aviso": publicada.get("error")}
        return {"exito": True}

    # Logros de RetroAchievements de un juego.
    def obtener_logros_juego(self, game_id):
        juego = db_local.obtener_juego_detalle(game_id)
        if not juego:
            return {"exito": False, "motivo": "error", "error": "No se encontró el juego."}
        return ra_client.obtener_logros(juego["identificativo"], juego["consola_id"], juego["titulo"])

    def obtener_amigos_juego(self, game_id):
        """Amigos que jugaron o desean este juego, y sus opiniones."""
        juego = db_local.obtener_juego_detalle(game_id)
        if not juego:
            return {"exito": False, "jugaron": [], "deseado": []}
        return {
            "exito": True,
            "jugaron": self.cloud.obtener_amigos_que_jugaron(juego["identificativo"], juego["titulo"]),
            "deseado": self.cloud.obtener_amigos_con_deseado(juego["identificativo"], juego["titulo"]),
            "opiniones": self.cloud.obtener_opiniones_amigos(juego["identificativo"], juego["titulo"]),
        }

    # --- RETROACHIEVEMENTS ---

    # Indica si hay una cuenta de RetroAchievements conectada.
    def obtener_estado_ra(self):
        return ra_client.estado_credenciales()

    # Prueba las credenciales de RetroAchievements y las guarda si funcionan.
    def guardar_credenciales_ra(self, usuario, api_key):
        return ra_client.guardar_credenciales(usuario, api_key)

    # Desconecta la cuenta de RetroAchievements.
    def borrar_credenciales_ra(self):
        return ra_client.borrar_credenciales()

    # --- LLAMADAS (la conexión de audio va por ui/llamadas.js; esto solo habla con Supabase) ---
    def obtener_config_llamadas(self):
        return self._llamadas.config_realtime()

    # Cierra llamadas que quedaron abiertas tras un cierre brusco.
    def limpiar_llamadas_colgadas(self):
        return self._llamadas.limpiar_colgadas()

    def obtener_audio_llamadas(self):
        """Micrófono y altavoz elegidos en este equipo ('' = el predeterminado del sistema)."""
        return {"mic": db_local.obtener_config("audio_mic", ""),
                "altavoz": db_local.obtener_config("audio_altavoz", "")}

    # Guarda el micrófono y el altavoz elegidos (por nombre).
    def guardar_audio_llamadas(self, mic, altavoz):
        if not all(isinstance(v, str) and len(v) <= 200 for v in (mic, altavoz)):
            return {"exito": False, "error": "Dispositivo no válido."}
        db_local.guardar_config("audio_mic", mic)
        db_local.guardar_config("audio_altavoz", altavoz)
        return {"exito": True}

    # Inicia una llamada; los amigos invitados reciben el timbre.
    def crear_llamada(self, amigo_ids, con_video=False):
        return self._llamadas.crear_llamada(amigo_ids, con_video)

    # Datos de una llamada y quién participa.
    def obtener_llamada(self, llamada_id):
        return self._llamadas.obtener_llamada(llamada_id)

    # Acepta o rechaza una invitación.
    def responder_llamada(self, llamada_id, aceptar):
        return self._llamadas.responder_llamada(llamada_id, aceptar)

    # Sale de una llamada; si no queda nadie, se cierra.
    def salir_llamada(self, llamada_id, terminar=False):
        return self._llamadas.salir_llamada(llamada_id, terminar)

    # Llamadas terminadas con un amigo, para mostrarlas en el chat.
    def obtener_historial_llamadas(self, amigo_id):
        return self._llamadas.historial_con(amigo_id)

    # Agrega amigos a una llamada en curso (máximo 6 personas).
    def invitar_a_llamada(self, llamada_id, amigo_ids):
        return self._llamadas.invitar(llamada_id, amigo_ids)


def _elegir_motor():
    """Linux: Qt WebEngine (Chromium) porque WebKitGTK no trae WebRTC en muchas distros.
    Windows: motor por defecto (WebView2, también Chromium)."""
    if sys.platform.startswith("linux"):
        try:
            from qtpy import QtWebEngineWidgets  # noqa: F401
        except Exception:
            print("[LLAMADAS] Falta Qt WebEngine: pip install PyQt6 PyQt6-WebEngine qtpy. "
                  "Sin él, las llamadas no funcionan en Linux.")
            return None
        try:
            from nucleo import pantalla_qt
            pantalla_qt.activar()
        except Exception as e:   # las llamadas siguen funcionando aunque no se pueda compartir pantalla
            print(f"[LLAMADAS] Compartir pantalla no disponible: {e}")
        return "qt"
    return None


# Prepara la carpeta de trabajo, crea la ventana y deja la app funcionando hasta que se cierre.
def main():
    # La base local, las ROMs y la caché usan rutas relativas: desde otra carpeta aparecerían vacías
    raiz = os.path.dirname(os.path.abspath(__file__))
    os.chdir(raiz)
    api = API()
    html_path = os.path.join(raiz, 'ui', 'index.html')

    window = webview.create_window(
        title='RetroEmulator',
        url=html_path,
        js_api=api,
        width=1024,
        height=720,
        resizable=True
    )
    api.set_window(window)
    # RETRO_DEBUG=1 abre las herramientas de desarrollo (en Qt abre una ventana extra)
    webview.start(debug=os.environ.get("RETRO_DEBUG") == "1", gui=_elegir_motor(), http_server=True)
    api._llamadas.salir_activa()  # ni una llamada abierta
    api.cloud.limpiar_jugando()   # ni un "jugando ahora" publicado

if __name__ == '__main__':
    main()