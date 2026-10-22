import webview
from webview import FileDialog
import os
import threading
from db_local import LocalDB
from scanner import ROMScanner
from launcher import GameLauncher
from cloud_client import CloudClient
import boxart
import db_local
import ra_client
import contexto
import webbrowser
from urllib.parse import urlparse

VERSION = "BETA v1"
DESARROLLADOR = "Rocco Flores"
URL_GITHUB = "https://github.com/Ropro-GG/RetroEmulator"
HOSTS_PERMITIDOS = {"github.com", "retroachievements.org"}

class API:
    def __init__(self):
        self.db = LocalDB()
        self.scanner = ROMScanner()
        self.launcher = GameLauncher()
        self.cloud = CloudClient()
        self.window = None
        self._juegos_activos = 0          # emuladores abiertos desde el launcher
        self._lock_juegos = threading.Lock()

    def set_window(self, window):
        self.window = window

    def _establecer_cuenta(self, resultado):
        """Registra qué cuenta está activa para separar los datos por cuenta en este equipo."""
        if resultado and resultado.get("exito"):
            uid = (resultado.get("usuario") or {}).get("id")
            if uid:
                contexto.establecer(uid)
                if db_local.adoptar_datos_antiguos(uid):
                    ra_client.adoptar_credenciales_antiguas(uid)

    def registrar_usuario(self, email, password, username):
        resultado = self.cloud.registrar_usuario(email, password, username)
        self._establecer_cuenta(resultado)
        return resultado

    def _limpiar_presencia_vieja(self, resultado):
        """Al entrar, borra un 'jugando ahora' que haya quedado colgado (por ejemplo tras un cierre brusco)."""
        if resultado and resultado.get("exito") and self._juegos_activos == 0:
            threading.Thread(target=self.cloud.limpiar_jugando, daemon=True).start()

    def iniciar_sesion(self, email, password, recordar=False):
        resultado = self.cloud.iniciar_sesion(email, password, recordar)
        self._establecer_cuenta(resultado)
        self._limpiar_presencia_vieja(resultado)
        return resultado

    def confirmar_recordar(self, codigo):
        return self.cloud.confirmar_recordar(codigo)

    def reenviar_codigo_recordar(self):
        return self.cloud.reenviar_codigo_recordar()

    def restaurar_sesion(self):
        resultado = self.cloud.restaurar_sesion()
        self._establecer_cuenta(resultado)
        self._limpiar_presencia_vieja(resultado)
        return resultado

    def cerrar_sesion(self):
        resultado = self.cloud.cerrar_sesion()
        contexto.establecer("")   # nada de la cuenta anterior queda activo
        return resultado

    def obtener_perfil(self, user_id=None):
        return self.cloud.obtener_perfil(user_id)

    def actualizar_perfil(self, bio, username=None):
        return self.cloud.actualizar_perfil(bio, username)

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
        iniciado = self.scanner.iniciar()
        return {"exito": True, "ya_en_curso": not iniciado}

    def obtener_estado_escaneo(self):
        """La interfaz lo consulta periódicamente para mostrar el progreso."""
        return self.scanner.estado()

    def obtener_portada_data_uri(self, ruta_portada):
        """Plan B si el webview no puede abrir la imagen por file://."""
        return boxart.leer_como_data_uri(ruta_portada)

    def obtener_juegos(self):
        return self.db.obtener_todos_los_juegos()

    def obtener_juegos_filtrados(self, texto_busqueda="", consola_id=None):
        """Retorna juegos filtrados por búsqueda y/o consola para pywebview."""
        juegos = self.db.obtener_juegos_filtrados(texto_busqueda, consola_id)
        for juego in juegos:
            juego["portada_url"] = boxart.ruta_a_uri(juego.get("portada_path"))
        return juegos

    def obtener_consolas(self):
        """Retorna las consolas registradas para llenar el selector/filtro de la UI."""
        return self.db.obtener_consolas()

    def lanzar_juego(self, game_id):
        return self.launcher.lanzar_por_id(
            game_id, al_iniciar=self._al_iniciar_juego, al_cerrar=self._al_cerrar_juego)

    def _al_iniciar_juego(self, titulo, consola):
        """Avisa a tus amigos a qué jugás (si no lo desactivaste en Privacidad)."""
        with self._lock_juegos:
            self._juegos_activos += 1
        if db_local.obtener_config_usuario("compartir_actividad", "1") == "1":
            self.cloud.establecer_jugando(titulo, consola)
        if db_local.obtener_config_usuario("compartir_historial", "1") == "1":
            identificativo = db_local.obtener_identificativo_por_consola(consola)
            self.cloud.registrar_jugada(identificativo, titulo, consola)

    def _al_cerrar_juego(self):
        # Solo se borra el aviso cuando ya no queda ningún emulador abierto
        with self._lock_juegos:
            self._juegos_activos = max(0, self._juegos_activos - 1)
            quedan = self._juegos_activos
        if quedan == 0:
            self.cloud.limpiar_jugando()

    # --- SOCIAL ---

    def obtener_social(self):
        return self.cloud.obtener_social()

    def obtener_resumen_social(self):
        """Datos livianos para la insignia de la pestaña SOCIAL."""
        return self.cloud.contar_solicitudes()

    def buscar_usuarios(self, texto):
        return self.cloud.buscar_usuarios(texto)

    def obtener_perfil_social(self, user_id):
        return self.cloud.obtener_perfil_social(user_id)

    def enviar_solicitud_amistad(self, user_id):
        return self.cloud.enviar_solicitud_amistad(user_id)

    def responder_solicitud_amistad(self, friendship_id, aceptar):
        return self.cloud.responder_solicitud_amistad(friendship_id, aceptar)

    def eliminar_amistad(self, friendship_id):
        return self.cloud.eliminar_amistad(friendship_id)

    # --- PRIVACIDAD ---

    def obtener_privacidad(self):
        """Ajustes de privacidad de la cuenta actual (cada cuenta tiene los suyos)."""
        return {
            "actividad": db_local.obtener_config_usuario("compartir_actividad", "1") == "1",
            "historial": db_local.obtener_config_usuario("compartir_historial", "1") == "1",
        }

    def guardar_compartir_actividad(self, activo):
        db_local.guardar_config_usuario("compartir_actividad", "1" if activo else "0")
        if not activo:
            self.cloud.limpiar_jugando()   # se borra lo que ya estuviera publicado
        return {"exito": True}

    def guardar_compartir_historial(self, activo):
        db_local.guardar_config_usuario("compartir_historial", "1" if activo else "0")
        if not activo:
            self.cloud.borrar_historial()   # se borra lo que ya estuviera publicado
        return {"exito": True}

    # --- CONFIGURACIÓN: RUTAS Y EMULADORES ---

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

    def obtener_detalle_juego(self, game_id):
        juego = db_local.obtener_juego_detalle(game_id)
        if not juego:
            return {"exito": False, "error": "No se encontró el juego."}
        juego["portada_url"] = boxart.ruta_a_uri(juego.get("portada_path"))
        juego["opinion"] = db_local.obtener_opinion(juego["consola_id"], juego["titulo"])
        return {"exito": True, "juego": juego}

    def guardar_opinion(self, game_id, puntuacion, texto):
        juego = db_local.obtener_juego_detalle(game_id)
        if not juego:
            return {"exito": False, "error": "No se encontró el juego."}
        db_local.guardar_opinion(juego["consola_id"], juego["titulo"], puntuacion, texto)
        return {"exito": True}

    def obtener_logros_juego(self, game_id):
        juego = db_local.obtener_juego_detalle(game_id)
        if not juego:
            return {"exito": False, "motivo": "error", "error": "No se encontró el juego."}
        return ra_client.obtener_logros(juego["identificativo"], juego["consola_id"], juego["titulo"])

    def obtener_amigos_juego(self, game_id):
        """Pendiente de desarrollar: hoy devuelve listas vacías."""
        juego = db_local.obtener_juego_detalle(game_id)
        if not juego:
            return {"exito": False, "jugaron": [], "deseado": []}
        return {
            "exito": True,
            "jugaron": self.cloud.obtener_amigos_que_jugaron(juego["identificativo"], juego["titulo"]),
            "deseado": self.cloud.obtener_amigos_con_deseado(juego["titulo"], juego["consola"]),
        }

    # --- RETROACHIEVEMENTS ---

    def obtener_estado_ra(self):
        return ra_client.estado_credenciales()

    def guardar_credenciales_ra(self, usuario, api_key):
        return ra_client.guardar_credenciales(usuario, api_key)

    def borrar_credenciales_ra(self):
        return ra_client.borrar_credenciales()

def main():
    api = API()
    html_path = os.path.join(os.path.dirname(__file__), 'ui', 'index.html')
    
    window = webview.create_window(
        title='RetroEmulator',
        url=f'file://{html_path}',
        js_api=api,
        width=1024,
        height=720,
        resizable=True
    )
    api.set_window(window)
    webview.start(debug=True)
    api.cloud.limpiar_jugando()   # al cerrar el launcher no queda un "jugando ahora" publicado

if __name__ == '__main__':
    main()