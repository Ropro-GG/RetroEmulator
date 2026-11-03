# Pruebas de errores ya corregidos, para que no vuelvan a aparecer.
"""Regresiones de la revisión del 2026-11-03. Ejecutar: python -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nucleo import db_local, launcher, scanner


class PistasDeAudio(unittest.TestCase):
    def test_juegos_con_la_palabra_track_o_audio_no_son_pistas(self):
        for nombre in ("Track & Field (USA).cue", "Soundtrack Hero (USA).iso", "Audiosurf (USA).iso"):
            self.assertFalse(scanner.es_pista_de_audio(nombre), nombre)

    def test_pista_1_es_de_datos_y_las_demas_de_audio(self):
        for nombre in ("Juego (Track 1).bin", "Juego (Track 01).bin", "Juego - Track1.bin"):
            self.assertFalse(scanner.es_pista_de_audio(nombre), nombre)
        for nombre in ("Juego (Track 2).bin", "Juego (Track 10).bin", "Juego Track 02.bin", "Juego (Audio).bin"):
            self.assertTrue(scanner.es_pista_de_audio(nombre), nombre)


class Escaneo(unittest.TestCase):
    def test_multidisco_se_registra_como_m3u_en_el_primer_escaneo(self):
        with tempfile.TemporaryDirectory() as carpeta:
            for disco in ("Juego (USA) (Disc 1).chd", "Juego (USA) (Disc 2).chd"):
                open(os.path.join(carpeta, disco), "w").close()
            registrados = []
            original = db_local.registrar_juego
            db_local.registrar_juego = lambda consola_id, titulo, ruta_rom: registrados.append(ruta_rom)
            try:
                consola = {"id": 1, "ruta_roms": carpeta, "extensiones": ".chd",
                           "identificativo": "psx", "nombre": "PS1"}
                scanner.escanear_consola(consola, {}, [])
            finally:
                db_local.registrar_juego = original
            self.assertEqual([os.path.basename(r) for r in registrados], ["Juego.m3u"])


class ElegirVariante(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db_original = db_local.DB_NAME
        db_local.DB_NAME = os.path.join(self.dir.name, "prueba.db")
        db_local.inicializar_db_local()
        self.rom_a = os.path.join(self.dir.name, "a.rom")
        self.rom_b = os.path.join(self.dir.name, "b.rom")
        open(self.rom_a, "w").close()
        open(self.rom_b, "w").close()
        self.consola = db_local.obtener_consolas()[0]["id"]
        db_local.actualizar_rutas_consola(self.consola, ruta_emulador=sys.executable)
        db_local.registrar_juego(self.consola, "Juego", self.rom_a)
        db_local.registrar_juego(self.consola, "Juego", self.rom_b)
        self.ids = [f[0] for f in db_local.obtener_conexion().execute("SELECT id FROM juegos ORDER BY id")]
        # El "emulador" no debe abrir nada de verdad
        self.popen = launcher.subprocess.Popen
        self.lanzados = []
        launcher.subprocess.Popen = lambda args: self.lanzados.append(args)

    def tearDown(self):
        launcher.subprocess.Popen = self.popen
        db_local.DB_NAME = self.db_original
        self.dir.cleanup()

    def test_sin_elegir_pide_seleccion(self):
        res = launcher.ejecutar_juego(self.ids[0])
        self.assertTrue(res.get("requiere_seleccion"))
        self.assertEqual(self.lanzados, [])

    def test_la_variante_elegida_se_abre(self):
        res = launcher.ejecutar_juego(self.ids[1], variante=True)
        self.assertTrue(res["exito"])
        self.assertEqual(self.lanzados, [[sys.executable, self.rom_b]])


class PresenciaEnLlamada(unittest.TestCase):
    """Con la privacidad desactivada nunca debe publicarse 'en llamada'."""

    class Tabla:
        def __init__(self):
            self.ops = []

        def upsert(self, fila):
            self.ops.append("publica")
            return self

        def delete(self):
            self.ops.append("borra")
            return self

        def eq(self, *_):
            return self

        def execute(self):
            return self

    def preparar(self, compartir, activa):
        from nucleo import llamadas_cloud
        tabla = self.Tabla()
        cloud = type("Cloud", (), {"_yo": lambda s: "yo", "client": type("C", (), {"table": lambda s, n: tabla})()})()
        ll = llamadas_cloud.Llamadas(cloud)
        ll.activa = activa
        original = db_local.obtener_config_usuario
        db_local.obtener_config_usuario = lambda clave, defecto="": compartir
        self.addCleanup(setattr, db_local, "obtener_config_usuario", original)
        ll.actualizar_presencia()
        return tabla.ops

    def test_en_llamada_y_compartiendo_publica(self):
        self.assertEqual(self.preparar("1", "x"), ["publica"])

    def test_privacidad_desactivada_no_publica(self):
        self.assertEqual(self.preparar("0", "x"), ["borra"])

    def test_sin_llamada_borra(self):
        self.assertEqual(self.preparar("1", None), ["borra"])


class BloquearYDenunciar(unittest.TestCase):
    """Validaciones y búsqueda; las reglas que protegen de verdad están en Supabase."""

    class Respuesta:
        def __init__(self, data):
            self.data = data

        def execute(self):
            return self

    def cliente(self, ids_bloqueados=()):
        from nucleo.cloud_client import CloudClient
        cloud = CloudClient.__new__(CloudClient)
        cloud.usuario_actual = type("U", (), {"id": "yo"})()
        self.llamadas_rpc = []

        class Cliente:
            def rpc(_, nombre, parametros=None):
                self.llamadas_rpc.append(nombre)
                if nombre == "ids_con_bloqueo":
                    return self.Respuesta(list(ids_bloqueados))
                return self.Respuesta(True)
        cloud.client = Cliente()
        return cloud

    def test_no_se_puede_denunciar_ni_bloquear_a_uno_mismo(self):
        cloud = self.cliente()
        self.assertFalse(cloud.denunciar_usuario("yo", "spam")["exito"])
        self.assertFalse(cloud.bloquear_usuario("yo")["exito"])
        self.assertEqual(self.llamadas_rpc, [])

    def test_denuncia_exige_motivo_valido_y_limita_el_detalle(self):
        cloud = self.cliente()
        self.assertFalse(cloud.denunciar_usuario("otro", "inventado")["exito"])
        self.assertFalse(cloud.denunciar_usuario("otro", "spam", "x" * 501)["exito"])
        self.assertEqual(self.llamadas_rpc, [])
        self.assertTrue(cloud.denunciar_usuario("otro", "spam", "x" * 500)["exito"])

    def test_perfil_de_usuario_con_bloqueo_no_se_muestra(self):
        cloud = self.cliente(["otro"])
        respuesta = self.Respuesta([{"id": "otro", "username": "x"}])

        class Tabla:
            def select(_, *a): return _
            def eq(_, *a): return _
            def execute(_): return respuesta
        cloud.client.table = lambda nombre: Tabla()
        self.assertFalse(cloud.obtener_perfil_social("otro")["exito"])


class CompartirPantalla(unittest.TestCase):
    def setUp(self):
        try:
            from nucleo import pantalla_qt
        except Exception as e:
            self.skipTest(f"Sin Qt: {e}")
        self.pq = pantalla_qt

    def test_solo_autoriza_microfono_camara_y_pantalla(self):
        funciones = self.pq.QWebEnginePage.Feature
        for permitida in (funciones.MediaAudioCapture, funciones.MediaVideoCapture, funciones.DesktopVideoCapture):
            self.assertIn(permitida, self.pq._PERMITIDOS)
        for denegada in (funciones.Geolocation, funciones.Notifications, funciones.MouseLock):
            self.assertNotIn(denegada, self.pq._PERMITIDOS)

    def test_quita_la_opcion_que_impide_capturar_y_conserva_las_demas(self):
        wq, pagina = self.pq.qt_pywebview, self.pq.qt_pywebview.BrowserView.WebPage
        recibido = []
        originales = wq.environ_append, pagina.__init__, pagina.onFeaturePermissionRequested
        def restaurar():
            wq.environ_append, pagina.__init__, pagina.onFeaturePermissionRequested = originales
        self.addCleanup(restaurar)
        wq.environ_append = lambda variable, *valores: recibido.extend(valores)
        self.pq.activar()
        wq.environ_append("X", "--use-fake-ui-for-media-stream", "--otra")
        self.assertEqual(recibido, ["--otra"])


if __name__ == "__main__":
    unittest.main()
