import webview
from webview import FileDialog
import os
import threading
from db_local import LocalDB
from scanner import ROMScanner
from launcher import GameLauncher
from cloud_client import CloudClient
import boxart

class API:
    def __init__(self):
        self.db = LocalDB()
        self.scanner = ROMScanner()
        self.launcher = GameLauncher()
        self.cloud = CloudClient()
        self.window = None

    def set_window(self, window):
        self.window = window

    def registrar_usuario(self, email, password, username):
        return self.cloud.registrar_usuario(email, password, username)

    def iniciar_sesion(self, email, password):
        return self.cloud.iniciar_sesion(email, password)

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
        return self.launcher.lanzar_por_id(game_id)

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

if __name__ == '__main__':
    main()