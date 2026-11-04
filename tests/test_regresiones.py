# Pruebas de errores ya corregidos, para que no vuelvan a aparecer.
"""Regresiones de la revisión del 2026-11-03. Ejecutar: python -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nucleo import cifrado, db_local, launcher, scanner


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


class _TablaFalsa:
    def __init__(self, cuenta):
        self.cuenta, self.datos, self.solo_vacia = cuenta, None, False

    def select(self, *_):
        return self

    def update(self, datos):
        self.datos = datos
        return self

    def eq(self, *_):
        return self

    def is_(self, *_):
        self.solo_vacia = True
        return self

    def execute(self):
        c = self.cuenta
        if c.sin_red:
            raise ConnectionError("connection")
        if self.datos is None:
            return mock.Mock(data=[{"llave_publica": c.publica}])
        if self.solo_vacia and c.publica:
            return mock.Mock(data=[])
        c.publica = self.datos["llave_publica"]
        return mock.Mock(data=[self.datos])


class _CuentaFalsa:
    def __init__(self):
        self.publica, self.sin_red = None, False
        self.client = mock.Mock()
        self.client.table = lambda _: _TablaFalsa(self)

    def _yo(self):
        return "u1"

    def _requiere_sesion(self):
        return None

    def _error_social(self, e):
        return str(e)


class LlavesDeCifrado(unittest.TestCase):
    def setUp(self):
        self.guardado = {}
        for nombre, falso in (("cargar", self.guardado.get),
                              ("guardar", lambda n, d: self.guardado.__setitem__(n, d) or True)):
            parche = mock.patch.object(cifrado.session_store, nombre, falso)
            parche.start()
            self.addCleanup(parche.stop)
        self.cuenta = _CuentaFalsa()
        self.llaves = cifrado.Llaves(self.cuenta)

    def _crear(self):
        palabras = self.llaves.generar()["palabras"]
        self.assertTrue(self.llaves.confirmar(" ".join(palabras))["exito"])
        return " ".join(palabras)

    def test_la_misma_frase_da_la_misma_llave_y_acepta_escribirla_sin_acentos(self):
        entropia = bytes(range(16))
        frase = " ".join(cifrado.frase_de(entropia))
        self.assertEqual(cifrado.entropia_de(cifrado._sin_acentos(frase).upper()), entropia)
        self.assertEqual(cifrado.publica_de(cifrado.entropia_de(frase)), cifrado.publica_de(entropia))
        self.assertNotEqual(cifrado.publica_de(entropia), cifrado.publica_de(bytes(16)))

    def test_detecta_palabras_de_mas_cambiadas_o_en_otro_orden(self):
        palabras = cifrado.frase_de(bytes(range(16)))
        for mala in (palabras[:11], ["xyz"] + palabras[1:], palabras[::-1]):
            with self.assertRaises(ValueError):
                cifrado.entropia_de(" ".join(mala))

    def test_crear_exige_confirmar_antes_de_publicar_o_guardar(self):
        self.assertEqual(self.llaves.estado()["estado"], "crear")
        palabras = self.llaves.generar()["palabras"]
        self.assertFalse(self.llaves.confirmar(" ".join(palabras[::-1]))["exito"])
        self.assertIsNone(self.cuenta.publica)
        self.assertEqual(self.guardado, {})
        self.assertTrue(self.llaves.confirmar(" ".join(palabras))["exito"])
        self.assertEqual(self.llaves.estado()["estado"], "lista")
        self.assertNotIn(" ".join(palabras), str(self.cuenta.publica))

    def test_otro_equipo_pide_la_frase_y_rechaza_una_ajena(self):
        frase = self._crear()
        self.guardado.clear()
        self.assertEqual(self.llaves.estado(), {"exito": True, "estado": "recuperar", "cambio": False})
        ajena = " ".join(cifrado.frase_de(bytes(16)))
        self.assertFalse(self.llaves.recuperar(ajena)["exito"])
        self.assertEqual(self.guardado, {})
        self.assertTrue(self.llaves.recuperar(frase)["exito"])
        self.assertEqual(self.llaves.estado()["estado"], "lista")

    def test_sin_conexion_no_ofrece_crear_llaves(self):
        self.cuenta.sin_red = True
        self.assertFalse(self.llaves.estado()["exito"])

    def test_dos_equipos_a_la_vez_no_se_pisan_la_llave(self):
        palabras = self.llaves.generar()["palabras"]
        self.cuenta.publica = "llave-de-otro-equipo"
        self.assertFalse(self.llaves.confirmar(" ".join(palabras))["exito"])
        self.assertEqual(self.cuenta.publica, "llave-de-otro-equipo")
        self.assertEqual(self.guardado, {})

    def test_perdi_mi_frase_reemplaza_y_el_equipo_viejo_lo_detecta(self):
        self._crear()
        vieja = dict(self.guardado)
        palabras = self.llaves.generar(reemplazar=True)["palabras"]
        self.assertTrue(self.llaves.confirmar(" ".join(palabras))["exito"])
        self.assertEqual(self.llaves.estado()["estado"], "lista")
        self.guardado.update(vieja)
        self.assertEqual(self.llaves.estado(), {"exito": True, "estado": "recuperar", "cambio": True})

    def test_cambiar_la_frase_exige_contrasena_y_confirmarla(self):
        self._crear()
        anterior = self.cuenta.publica
        self.cuenta.verificar_contrasena = lambda clave: None if clave == "buena" else "La contraseña no es correcta."
        self.assertFalse(self.llaves.cambiar_frase("mala")["exito"])
        self.assertIsNone(self.llaves.pendiente)
        palabras = self.llaves.cambiar_frase("buena")["palabras"]
        self.assertEqual(self.cuenta.publica, anterior)     # sin confirmar no cambió nada
        self.assertTrue(self.llaves.confirmar(" ".join(palabras))["exito"])
        self.assertNotEqual(self.cuenta.publica, anterior)
        self.assertEqual(self.llaves.estado()["estado"], "lista")

    def test_una_llave_local_sin_publicar_se_publica_y_no_se_reemplaza(self):
        frase = self._crear()
        self.cuenta.publica = None
        self.assertEqual(self.llaves.estado()["estado"], "lista")
        self.assertEqual(self.cuenta.publica, cifrado.publica_de(cifrado.entropia_de(frase)))


class MensajesCifrados(unittest.TestCase):
    def setUp(self):
        self.ana, self.beto = cifrado.privada_de(bytes(16)), cifrado.privada_de(bytes(range(16)))
        self.publica_beto = cifrado._b64(bytes(self.beto.public_key))

    def _de_ana(self, contenido="¡Hola! 🎮\ncon \"comillas\""):
        return cifrado.cifrar_para(self.ana, self.publica_beto, "ana", "texto", contenido)

    def test_lo_leen_emisor_y_receptor_y_el_servidor_no_ve_el_texto(self):
        guardado = self._de_ana("secreto")
        self.assertNotIn("secreto", guardado)
        self.assertEqual(cifrado.descifrar_de(self.beto, "ana", guardado), ("texto", "secreto"))
        self.assertEqual(cifrado.descifrar_de(self.ana, "ana", guardado), ("texto", "secreto"))

    def test_un_tercero_o_una_frase_vieja_no_pueden_leerlo(self):
        otro = cifrado.privada_de(b"x" * 16)
        self.assertEqual(cifrado.descifrar_de(otro, "ana", self._de_ana()), ("texto", cifrado.ILEGIBLE_OTRA_FRASE))

    def test_alterarlo_o_atribuirlo_a_otro_lo_rechaza(self):
        g = self._de_ana()
        alterado = g[:-6] + ("AAAA" if g[-6:-2] != "AAAA" else "BBBB") + g[-2:]
        self.assertEqual(cifrado.descifrar_de(self.beto, "ana", alterado)[1], cifrado.ILEGIBLE_DANADO)
        self.assertEqual(cifrado.descifrar_de(self.ana, "beto", g)[1], cifrado.ILEGIBLE_DANADO)
        self.assertEqual(cifrado.descifrar_de(self.beto, "ana", "basura")[1], cifrado.ILEGIBLE_DANADO)

    def test_no_acepta_un_tipo_desconocido_escondido_adentro(self):
        g = cifrado.cifrar_para(self.ana, self.publica_beto, "ana", "imagen", "ruta-ajena")
        self.assertEqual(cifrado.descifrar_de(self.beto, "ana", g)[1], cifrado.ILEGIBLE_DANADO)

    def test_el_mensaje_mas_largo_entra_en_el_limite_de_la_base(self):
        peor = '"' * 1000                                 # cada comilla se duplica en el JSON
        self.assertLess(len(self._de_ana(peor)), 10000)
        peor = "🎮" * 1000
        self.assertLess(len(self._de_ana(peor)), 10000)

    def test_sin_llave_no_se_envia_y_nunca_cae_a_texto_sin_cifrar(self):
        cuenta = _CuentaFalsa()
        llaves = cifrado.Llaves(cuenta)
        with mock.patch.object(cifrado.session_store, "cargar", return_value=None):
            with self.assertRaises(cifrado.SinLlave) as propia:
                llaves.cifrar("beto", "texto", "hola")
        self.assertTrue(propia.exception.propia)
        with mock.patch.object(cifrado.session_store, "cargar", return_value={"entropia": bytes(16).hex()}):
            llaves._privada = None
            with self.assertRaises(cifrado.SinLlave) as ajena:      # el amigo no tiene llave publicada
                llaves.cifrar("beto", "texto", "hola")
        self.assertFalse(ajena.exception.propia)

    def test_abrir_no_toca_los_mensajes_viejos_y_descifra_los_nuevos(self):
        llaves = cifrado.Llaves(_CuentaFalsa())
        viejo = {"tipo": "texto", "contenido": "hola", "de": "ana"}
        self.assertIs(llaves.abrir(viejo), viejo)
        with mock.patch.object(cifrado.session_store, "cargar", return_value={"entropia": bytes(range(16)).hex()}):
            abierto = llaves.abrir({"tipo": "cifrado", "contenido": self._de_ana("hola"), "de": "ana"})
        self.assertEqual((abierto["tipo"], abierto["contenido"]), ("texto", "hola"))
        with mock.patch.object(cifrado.session_store, "cargar", return_value=None):
            llaves._privada = None
            abierto = llaves.abrir({"tipo": "cifrado", "contenido": self._de_ana(), "de": "ana"})
        self.assertEqual(abierto["contenido"], cifrado.ILEGIBLE_SIN_FRASE)


if __name__ == "__main__":
    unittest.main()
