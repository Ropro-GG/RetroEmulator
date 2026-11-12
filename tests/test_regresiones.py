# Pruebas de errores ya corregidos, para que no vuelvan a aparecer.
"""Regresiones de la revisión del 2026-11-03. Ejecutar: python -m unittest discover -s tests"""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nucleo import boxart, catalogo, cifrado, db_local, launcher, noticias, scanner


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


class NivelDelPerfil(unittest.TestCase):
    def test_nivel_insignias_y_mas_jugados(self):
        from nucleo.cloud_client import resumen_perfil
        vacio = resumen_perfil([], 0)
        self.assertEqual((vacio["nivel"], vacio["insignias"], vacio["mas_jugados"]), (0, [], []))
        filas = [{"titulo": "A", "veces": 3, "segundos": 7200}, {"titulo": "B", "veces": 10, "segundos": 0}, {"titulo": "C", "veces": 1, "segundos": 60}]
        r = resumen_perfil(filas, 2)
        # 3 juegos (300) + 14 sesiones (140) + 2 horas (40) + 2 opiniones (100) = 580 XP: nivel 2 (300), el 3 pide 600
        self.assertEqual((r["xp"], r["nivel"], r["xp_nivel"], r["xp_siguiente"]), (580, 2, 300, 600))
        self.assertEqual([(i["nombre"], i["grado"]) for i in r["insignias"]], [("Jugador", 1), ("Dedicación", 1), ("Constancia", 1), ("Crítico", 1)])
        self.assertEqual([j["titulo"] for j in r["mas_jugados"]], ["A", "C", "B"])


class AvisosDeLogros(unittest.TestCase):
    def test_solo_se_anuncian_los_nuevos_y_se_valida_lo_que_llega(self):
        from nucleo import ra_client
        a = {"AchievementID": "7", "Title": "Uno", "Points": 10, "GameTitle": "Juego", "BadgeName": "12345", "HardcoreMode": 1}
        logro = ra_client.logro_reciente(a)
        self.assertEqual((logro["id"], logro["puntos"], logro["hardcore"], logro["badge_url"]),
                         (7, 10, True, "https://media.retroachievements.org/Badge/12345.png"))
        self.assertEqual(ra_client.logro_reciente({**a, "BadgeName": "../x"})["badge_url"], "")
        self.assertIsNone(ra_client.logro_reciente({"Title": "sin id"}))
        vistos = {7}   # ya estaba antes de abrir el juego
        b = ra_client.logro_reciente({**a, "AchievementID": 8})
        self.assertEqual(ra_client.nuevos([logro, b], vistos), [b])
        self.assertEqual(ra_client.nuevos([logro, b], vistos), [])   # cada logro se anuncia una sola vez


class AvisoSobreElJuego(unittest.TestCase):
    def test_el_html_del_aviso_escapa_lo_que_llega(self):
        import gui_app
        pagina = gui_app.html_aviso_logro({"titulo": "<script>x</script>", "juego": "A & B", "puntos": "7", "badge_url": ""})
        self.assertNotIn("<script>x", pagina)
        self.assertIn("&lt;script&gt;", pagina)
        self.assertIn("A &amp; B", pagina)
        self.assertIn("+7 pts", pagina)

    def test_los_puntos_de_logros_suman_al_nivel(self):
        from nucleo.cloud_client import resumen_perfil
        r = resumen_perfil([], 0, 650)
        self.assertEqual((r["xp"], r["nivel"], r["puntos_ra"]), (650, 3, 650))   # el nivel 3 pide 600
        self.assertEqual([(i["nombre"], i["grado"], i["detalle"]) for i in r["insignias"]], [("Cazador de logros", 2, "500+ puntos de logros")])


class GuiasDeLaComunidad(unittest.TestCase):
    def test_validar_guia(self):
        from nucleo.cloud_client import CloudClient
        validar = CloudClient.validar_guia
        yo = CloudClient.__new__(CloudClient)
        self.assertIsNone(validar(yo, "Título", "Paso 1", 5))
        self.assertIn("título", validar(yo, "   ", "Texto", 0))
        self.assertIn("contenido", validar(yo, "Título", "  ", 0))
        self.assertIn("120", validar(yo, "x" * 121, "Texto", 0))
        self.assertIn("20000", validar(yo, "Título", "x" * 20001, 0))
        self.assertIn("5", validar(yo, "Título", "Texto", 6))


class DenunciarPublicaciones(unittest.TestCase):
    def test_se_adjunta_la_publicacion_solo_si_es_de_la_persona_denunciada(self):
        from nucleo.cloud_client import CloudClient
        yo = CloudClient.__new__(CloudClient)
        fila = {"id": 5, "autor_id": "otro", "texto": "Paso 1", "tipo": "guia", "titulo": "Mi guía", "juego": "Super Metroid",
                "imagenes": ["otro/a.png"], "tipo_media": None, "media": None, "creado_en": "2026-11-12"}
        with mock.patch.object(CloudClient, "_consultar_publicaciones", return_value=[fila]), \
             mock.patch.object(CloudClient, "_yo", return_value="yo"), \
             mock.patch.object(CloudClient, "_url_imagen", side_effect=lambda r: "https://x/" + r), \
             mock.patch.object(CloudClient, "_copiar_imagen_publica", return_value="yo/" + "a" * 32 + ".png"):
            self.assertEqual(yo._adjuntos_de_publicacion("alguien-mas", 5), [])
            adjuntos = yo._adjuntos_de_publicacion("otro", 5)
        self.assertEqual([a["tipo"] for a in adjuntos], ["guia", "imagen"])
        self.assertIn('Guía en Comunidad de "Super Metroid": Mi guía', adjuntos[0]["contenido"])
        self.assertTrue(adjuntos[1]["archivo"].startswith("yo/"))


class BannerDelPerfil(unittest.TestCase):
    def test_la_imagen_se_recorta_a_3_por_1_sin_metadatos(self):
        from nucleo import imagenes
        if not imagenes.disponible():
            self.skipTest("Pillow no instalado")
        from PIL import Image
        import io
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "foto.png")
            Image.new("RGBA", (800, 900), (255, 0, 0, 128)).save(ruta)
            datos = imagenes.preparar_banner(ruta)
        img = Image.open(io.BytesIO(datos))
        self.assertEqual((img.format, img.size, img.info.get("exif")), ("JPEG", (1500, 500), None))


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
        self.vigilar = launcher._vigilar
        launcher._vigilar = lambda *args: None   # sin proceso real no hay nada que vigilar ni medir

    def tearDown(self):
        launcher.subprocess.Popen = self.popen
        launcher._vigilar = self.vigilar
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


def setUpModule():
    # Las pruebas de llaves no deben tocar la base real del equipo
    carpeta = tempfile.mkdtemp()
    parche = mock.patch.object(db_local, "DB_NAME", os.path.join(carpeta, "pruebas.db"))
    parche.start()
    unittest.addModuleCleanup(parche.stop)
    db_local.inicializar_db_local()


class ConexionConSupabase(unittest.TestCase):
    def test_usa_http1_y_cada_peticion_lleva_la_sesion_actual(self):
        import httpx
        from nucleo import cloud_client
        recibidas = []

        def responder(peticion):
            recibidas.append(peticion)
            return httpx.Response(200, json=[])

        with mock.patch.object(cloud_client, "SUPABASE_URL", "https://x.supabase.co"), \
                mock.patch.object(cloud_client, "SUPABASE_KEY", "publica"):
            cloud = cloud_client.CloudClient()
        http = cloud.client.options.httpx_client
        self.assertEqual(type(http._transport).__name__, "HTTPTransport")
        self.assertFalse(http._transport._pool._http2)
        http._transport = httpx.MockTransport(responder)

        cloud.client.table("profiles").select("id").execute()
        sesion = mock.Mock(access_token="token-de-sesion")
        cloud.client._listen_to_auth_events("SIGNED_IN", sesion)
        cloud.client.table("mensajes").select("id").execute()
        cloud.client.storage.from_("chat").list("carpeta")

        self.assertEqual(str(recibidas[0].url).split("?")[0], "https://x.supabase.co/rest/v1/profiles")
        self.assertEqual(recibidas[0].headers["apikey"], "publica")
        self.assertEqual(str(recibidas[1].url).split("?")[0], "https://x.supabase.co/rest/v1/mensajes")
        self.assertEqual(recibidas[1].headers["authorization"], "Bearer token-de-sesion")
        self.assertTrue(str(recibidas[2].url).startswith("https://x.supabase.co/storage/v1/"))
        self.assertEqual(recibidas[2].headers["authorization"], "Bearer token-de-sesion")


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

    def _adjunto(self, tipo="imagen", ruta=None, llave=b"k" * 32):
        ruta = ruta or "ana/cifrados/" + "a" * 32 + ".bin"
        return ruta, cifrado.cifrar_para(self.ana, self.publica_beto, "ana", tipo, ruta, llave)

    def test_gif_y_publicacion_se_revisan_al_abrirlos(self):
        for tipo, bueno, malo in (("gif", "https://static.klipy.com/a.gif", "https://malo.example/a.gif"),
                                  ("publicacion", "42", "42; drop table")):
            g = cifrado.cifrar_para(self.ana, self.publica_beto, "ana", tipo, bueno)
            self.assertEqual(cifrado.descifrar_de(self.beto, "ana", g), (tipo, bueno))
            g = cifrado.cifrar_para(self.ana, self.publica_beto, "ana", tipo, malo)
            self.assertEqual(cifrado.descifrar_de(self.beto, "ana", g)[1], cifrado.ILEGIBLE_DANADO)

    def test_un_adjunto_solo_vale_si_es_del_emisor_y_coincide_con_la_fila(self):
        ruta, g = self._adjunto()
        adjuntos = {}
        self.assertEqual(cifrado.descifrar_de(self.beto, "ana", g, ruta, adjuntos), ("imagen", ruta))
        self.assertEqual(adjuntos, {ruta: b"k" * 32})
        self.assertEqual(cifrado.descifrar_de(self.beto, "ana", g, "ana/cifrados/otro.bin")[1], cifrado.ILEGIBLE_DANADO)
        ajena = "beto/cifrados/" + "a" * 32 + ".bin"
        _, g = self._adjunto(ruta=ajena)
        self.assertEqual(cifrado.descifrar_de(self.beto, "ana", g, ajena)[1], cifrado.ILEGIBLE_DANADO)

    def test_un_archivo_se_abre_solo_con_su_llave_y_el_viejo_queda_igual(self):
        llaves = cifrado.Llaves(_CuentaFalsa())
        llave, sobre = cifrado.cifrar_archivo(b"imagen secreta")
        self.assertNotIn(b"imagen secreta", sobre)
        ruta = "ana/cifrados/x.bin"
        self.assertIsNone(llaves.descifrar_archivo(ruta, sobre))
        llaves.adjuntos[ruta] = llave
        self.assertEqual(llaves.descifrar_archivo(ruta, sobre), b"imagen secreta")
        llaves.adjuntos[ruta] = b"z" * 32
        self.assertIsNone(llaves.descifrar_archivo(ruta, sobre))
        self.assertEqual(llaves.descifrar_archivo("ana/stickers/viejo.png", b"png"), b"png")

    def test_los_stickers_guardados_dependen_de_la_frase(self):
        llaves = cifrado.Llaves(_CuentaFalsa())
        ruta = "u1/stickers/x.bin"
        with mock.patch.object(cifrado.session_store, "cargar", return_value={"entropia": bytes(16).hex()}):
            sobre = llaves.cifrar_propio(b"sticker")
            self.assertNotIn(b"sticker", sobre)
            self.assertEqual(llaves.descifrar_archivo(ruta, sobre), b"sticker")
        llaves._privada = None
        with mock.patch.object(cifrado.session_store, "cargar", return_value={"entropia": bytes(range(16)).hex()}):
            self.assertIsNone(llaves.descifrar_archivo(ruta, sobre))

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
            abierto = llaves.abrir({"tipo": "cifrado", "contenido": self._de_ana("hola"), "de": "ana", "para": "u1"})
        self.assertEqual((abierto["tipo"], abierto["contenido"]), ("texto", "hola"))
        with mock.patch.object(cifrado.session_store, "cargar", return_value=None):
            llaves._privada = None
            abierto = llaves.abrir({"tipo": "cifrado", "contenido": self._de_ana(), "de": "ana", "para": "u1"})
        self.assertEqual(abierto["contenido"], cifrado.ILEGIBLE_SIN_FRASE)


class IdentidadDeAmigos(unittest.TestCase):
    def setUp(self):
        self.mia = bytes(range(16))
        guardada = {"entropia": self.mia.hex()}
        parche = mock.patch.object(cifrado.session_store, "cargar", return_value=guardada)
        parche.start()
        self.addCleanup(parche.stop)
        self.cuenta = _CuentaFalsa()
        self.cuenta._yo = lambda: f"yo-{self.id()}"     # cada prueba con su propia cuenta en la base local
        self.yo = self.cuenta._yo()
        self.llaves = cifrado.Llaves(self.cuenta)
        self.amigo = cifrado.privada_de(bytes(16))
        self.publica_amigo = cifrado._b64(bytes(self.amigo.public_key))
        self.cuenta.publica = self.publica_amigo
        self.intruso = cifrado.privada_de(b"i" * 16)
        self.publica_intruso = cifrado._b64(bytes(self.intruso.public_key))

    def _mensaje_de(self, privada, texto="hola"):
        mia = cifrado._b64(bytes(cifrado.privada_de(self.mia).public_key))
        return {"tipo": "cifrado", "de": "amigo", "para": self.yo, "contenido": cifrado.cifrar_para(privada, mia, "amigo", "texto", texto)}

    def test_el_codigo_es_igual_para_ambos_y_cambia_con_la_llave(self):
        a = cifrado.codigo_seguridad("u1", "A", "u2", "B")
        self.assertEqual(a, cifrado.codigo_seguridad("u2", "B", "u1", "A"))
        self.assertNotEqual(a, cifrado.codigo_seguridad("u1", "A", "u2", "C"))
        self.assertRegex(a, r"^(\d{5} ){5}\d{5}$")

    def test_la_primera_llave_se_acepta_sola_y_un_cambio_frena_el_envio(self):
        self.assertTrue(self.llaves.cifrar("amigo", "texto", "hola").startswith("e1:"))
        self.assertEqual(self.llaves.estado_amigo("amigo")["estado"], "confirmada")
        self.cuenta.publica = self.publica_intruso
        with self.assertRaises(cifrado.LlaveCambiada):
            self.llaves.cifrar("amigo", "texto", "secreto")
        self.assertEqual(self.llaves.estado_amigo("amigo")["estado"], "cambio")

    def test_volver_a_una_llave_vieja_tambien_avisa(self):
        self.llaves.estado_amigo("amigo")
        self.cuenta.publica = self.publica_intruso
        self.llaves.aceptar_amigo("amigo", self.llaves.estado_amigo("amigo")["codigo"])
        self.cuenta.publica = self.publica_amigo
        self.assertEqual(self.llaves.estado_amigo("amigo")["estado"], "cambio")

    def test_aceptar_exige_el_codigo_vigente_y_quita_la_verificacion(self):
        codigo = self.llaves.estado_amigo("amigo")["codigo"]
        self.assertTrue(self.llaves.verificar_amigo("amigo", codigo, True)["exito"])
        self.assertTrue(self.llaves.estado_amigo("amigo")["verificada"])
        self.cuenta.publica = self.publica_intruso
        self.assertFalse(self.llaves.estado_amigo("amigo")["verificada"])
        self.assertFalse(self.llaves.aceptar_amigo("amigo", codigo)["exito"])
        nuevo = self.llaves.estado_amigo("amigo")["codigo"]
        self.assertFalse(self.llaves.verificar_amigo("amigo", nuevo, True)["exito"])   # sin aceptar antes
        self.assertTrue(self.llaves.aceptar_amigo("amigo", nuevo)["exito"])
        estado = self.llaves.estado_amigo("amigo")
        self.assertEqual((estado["estado"], estado["verificada"]), ("confirmada", False))

    def test_un_mensaje_con_llave_ajena_avisa_y_los_aceptados_no(self):
        self.llaves.estado_amigo("amigo")
        self.assertFalse(self.llaves.abrir(self._mensaje_de(self.amigo))["alerta_llave"])
        self.assertTrue(self.llaves.abrir(self._mensaje_de(self.intruso))["alerta_llave"])

    def test_un_mensaje_falso_como_si_fuera_mio_tambien_avisa(self):
        self.llaves.estado_amigo("amigo")
        mia = cifrado._b64(bytes(cifrado.privada_de(self.mia).public_key))
        falso = cifrado.cifrar_para(self.intruso, mia, self.yo, "texto", "yo no escribí esto")
        abierto = self.llaves.abrir({"tipo": "cifrado", "de": self.yo, "para": "amigo", "contenido": falso})
        self.assertEqual(abierto["contenido"], "yo no escribí esto")
        self.assertTrue(abierto["alerta_llave"])

    def test_los_mensajes_con_una_llave_ya_aceptada_siguen_sin_avisar(self):
        self.llaves.estado_amigo("amigo")
        self.cuenta.publica = self.publica_intruso
        self.llaves.aceptar_amigo("amigo", self.llaves.estado_amigo("amigo")["codigo"])
        self.assertFalse(self.llaves.abrir(self._mensaje_de(self.amigo))["alerta_llave"])

    def test_sin_conexion_no_rompe_la_lectura(self):
        self.cuenta.sin_red = True
        abierto = self.llaves.abrir(self._mensaje_de(self.amigo, "hola"))
        self.assertEqual(abierto["contenido"], "hola")
        self.assertFalse(abierto["alerta_llave"])


class TiendaDelCatalogo(unittest.TestCase):
    def test_lee_los_datos_de_libretro_sin_importar_la_region(self):
        dat = """game (\n\tcomment "Super Metroid (Japan, USA) (En,Ja)"\n\treleaseyear "1994"\n\trom ( crc 1 )\n)
game (\n\tcomment "Legend of Zelda, The (USA)"\n\treleaseyear "1992"\n\trom ( crc 2 )\n)"""
        self.assertEqual(catalogo.leer_dat(dat, "releaseyear"), {"super metroid": "1994", "the legend of zelda": "1992"})

    def test_la_lista_oculta_hacks_y_betas_y_elige_una_version(self):
        indice = boxart._Indice("X", ["Juego (USA).png", "Juego (Beta).png", "Otro (Proto).png", "Abc (Japan).png"])
        juegos = catalogo._armar_lista(indice, {"genero": {"juego": "Action"}}, "https://x/")
        self.assertEqual([(j["titulo"], j["genero"]) for j in juegos], [("Abc", ""), ("Juego", "Acción")])   # se traduce al armar la lista
        self.assertEqual(juegos[1]["portada"], "https://x/Juego%20%28USA%29.png")

    def test_wikipedia_solo_vale_si_coincide_el_titulo_y_habla_de_un_videojuego(self):
        self.assertEqual(catalogo.elegir_articulos([{"title": "Metroid"}, {"title": "Silent Hill (franquicia)"}, {"title": "Silent Hill (videojuego)"}], "silent hill"),
                         ["Silent Hill (videojuego)", "Silent Hill (franquicia)"])
        self.assertEqual(catalogo.elegir_articulos([{"title": "Metroid"}], "super metroid"), [])
        bueno = {"type": "standard", "extract": "Es un videojuego.", "content_urls": {"desktop": {"page": "https://es.wikipedia.org/wiki/X"}}}
        self.assertEqual(catalogo.resumen_valido(bueno, "videojuego", "es")["texto"], "Es un videojuego.")
        self.assertIsNone(catalogo.resumen_valido({**bueno, "extract": "Es un río."}, "videojuego", "es"))
        self.assertIsNone(catalogo.resumen_valido({**bueno, "extract": "Es una franquicia de videojuegos."}, "videojuego", "es"))
        self.assertIsNone(catalogo.resumen_valido({**bueno, "type": "disambiguation"}, "videojuego", "es"))
        self.assertIsNone(catalogo.resumen_valido({**bueno, "content_urls": {"desktop": {"page": "https://mal.com/x"}}}, "videojuego", "es"))

    def test_juego_gratis_comprueba_lo_que_llega_de_internet(self):
        base = {"slug": "a_b-c", "basepath": "database-gb", "title": "T", "platform": "GB", "screenshots": ["c d.png", "../x.png"],
                "website": ["http://a.itch.io/x", "https://malitch.io/x", "https://autor.itch.io/juego"]}
        j = catalogo.juego_gratis(base)
        self.assertEqual(j["portada"], "https://hh3.gbdev.io/static/database-gb/entries/a_b-c/c%20d.png")
        self.assertEqual(len(j["capturas"]), 1)
        self.assertEqual(j["itch"], "https://autor.itch.io/juego")
        self.assertEqual(j["enlace"], "https://hh.gbdev.io/game/a_b-c")
        self.assertIsNone(catalogo.juego_gratis({**base, "slug": "../malo"}))
        self.assertIsNone(catalogo.juego_gratis({**base, "basepath": "x/y"}))

    def test_generos_compuestos_se_separan_y_unifican(self):
        self.assertEqual(catalogo.generos_de("Board /Card, Shogi"), ["Board", "Card", "Shogi"])
        juegos = [{"titulo": t, "clave": t.lower(), "genero": g} for t, g in (("A", "Beat'em Up, Fighting"), ("B", "Beat 'em up"), ("C", ""))]
        with mock.patch.object(catalogo, "_lista", return_value=("s", juegos)):
            res = catalogo.listar("x", "x", genero="beat 'em up")
        self.assertEqual(res["generos"], ["Beat'em Up", "Fighting"])
        self.assertEqual([j["titulo"] for j in res["juegos"]], ["A", "B"])

    def test_generos_en_espanol(self):
        self.assertEqual(catalogo.traducir_generos("Board /Card, Gun, Lightgun Shooter"), "Juego de mesa, Cartas, Pistola de luz")
        self.assertEqual(catalogo.traducir_generos("N/A"), "")
        self.assertEqual(catalogo.traducir_generos("Mahjong & Puzzle, Nuevo"), "Mahjong, Puzle, Nuevo")   # uno desconocido queda igual

    def test_leer_dat_completo_toma_los_datos_de_cada_bloque(self):
        texto = 'clrmamepro (\n\tname "x"\n)\n\ngame (\n\tname "Silent Hill (USA)"\n\tdescription "a \\"b\\""\n\tdeveloper "Konami"\n\treleaseyear "1999"\n\tgenre "Horror"\n' \
                '\trom (\n\t\tname "Silent Hill (USA).cue"\n\t)\n)\n\ngame (\n\tname "Otro (Japan)"\n\tgenre "RPG"\n)\n'
        datos = catalogo.leer_dat_completo(texto)
        self.assertEqual(datos["genre"], {"silent hill": "Horror", "otro": "RPG"})
        self.assertEqual((datos["developer"], datos["releaseyear"], datos["publisher"]), ({"silent hill": "Konami"}, {"silent hill": "1999"}, {}))

    def test_si_un_sitio_pide_esperar_no_se_insiste(self):
        import urllib.error
        catalogo._respuestas.clear()
        catalogo._pausa_hasta.clear()
        pedidos = []

        def pedir_429():
            pedidos.append(1)
            raise urllib.error.HTTPError("u", 429, "Too Many Requests", {"Retry-After": "120"}, None)

        with self.assertRaises(catalogo.SitioOcupado):
            catalogo._con_cache("sitio", "a", pedir_429)
        with self.assertRaises(catalogo.SitioOcupado):
            catalogo._con_cache("sitio", "b", pedir_429)   # durante la pausa ni se intenta
        self.assertEqual(len(pedidos), 1)
        self.assertAlmostEqual(catalogo._pausa_hasta["sitio"] - time.time(), 120, delta=5)
        catalogo._pausa_hasta.clear()
        self.assertEqual(catalogo._con_cache("sitio", "a", lambda: "datos"), "datos")
        catalogo._respuestas["a"] = (0.0, "vieja")   # vencida: se vuelve a pedir, y con 429 se usa la vieja
        self.assertEqual(catalogo._con_cache("sitio", "a", pedir_429), "vieja")
        catalogo._pausa_hasta["itch.io"] = time.time() + 60
        with mock.patch.object(catalogo, "_pedir", side_effect=AssertionError("no debe pedir")):
            self.assertIn("pidió esperar", catalogo.gratis("itch-gb")["error"])   # pausa activa y sin respuesta guardada
        catalogo._respuestas.clear()
        catalogo._pausa_hasta.clear()

    def test_leer_itch_solo_acepta_juegos_gratis_de_itch(self):
        item = """<item><plainTitle>{t}</plainTitle><link>{l}</link><price>{p}</price><imageurl>{i}</imageurl>
                  <description>Hecho para &lt;b&gt;NES&lt;/b&gt;</description><pubDate>Tue, 15 Nov 2016 16:17:31 GMT</pubDate></item>"""
        bueno = dict(t="L&amp;#039;Abbaye", l="https://autor.itch.io/juego", p="$0.00", i="https://img.itch.zone/a.png")
        xml = "<rss><channel>" + item.format(**bueno) + item.format(**{**bueno, "p": "$5.00"}) \
            + item.format(**{**bueno, "l": "https://malitch.io/x"}) + item.format(**{**bueno, "i": "https://mal.com/a.png", "t": "Sin imagen"}) + "</channel></rss>"
        juegos = catalogo.leer_itch(xml.encode())
        self.assertEqual([j["titulo"] for j in juegos], ["L'Abbaye", "Sin imagen"])
        self.assertEqual((juegos[0]["desarrollador"], juegos[0]["descripcion"], juegos[0]["fecha"]), ("autor", "Hecho para NES", "2016-11-15"))
        self.assertEqual(juegos[1]["capturas"], [])
        with self.assertRaises(ValueError):
            catalogo.leer_itch(b'<!DOCTYPE x [<!ENTITY a "b">]><rss/>')

    def test_logros_encuentra_el_juego_aunque_cambie_el_nombre(self):
        from nucleo import ra_client
        lista = [{"ID": 1, "Title": "MediEvil II", "NumAchievements": 5}, {"ID": 2, "Title": "Crash Team Racing", "NumAchievements": 5},
                 {"ID": 3, "Title": "Mega Man X", "NumAchievements": 5}, {"ID": 4, "Title": "Pac-Man", "NumAchievements": 5},
                 {"ID": 5, "Title": "Alfa | Beta Gamma", "NumAchievements": 5}]
        ra_client._indices.pop(12, None)
        with mock.patch.object(ra_client, "_lista_juegos", return_value=lista):
            buscar = lambda t: (ra_client.buscar_juego("psx", t) or {}).get("ID")
            self.assertEqual(buscar("MediEvil 2 (Europe)"), 1)
            self.assertEqual(buscar("CTR - Crash Team Racing (USA)"), 2)
            self.assertEqual(buscar("Beta Gamma (Japan)"), 5)
            self.assertIsNone(buscar("Mega Man 10"))
            self.assertIsNone(buscar("Ms. Pac-Man"))   # con menos de tres palabras no se empareja por contención
        ra_client._indices.pop(12, None)

    def test_tiempo_de_juego_por_cuenta(self):
        with tempfile.TemporaryDirectory() as carpeta, mock.patch.object(db_local, "DB_NAME", os.path.join(carpeta, "x.db")):
            db_local.inicializar_db_local()
            consola = db_local.LocalDB().obtener_consolas()[0]["id"]
            db_local.registrar_juego(consola, "Juego", os.path.join(carpeta, "a.bin"))
            with mock.patch.object(db_local, "usuario_id", return_value="yo"):
                db_local.sumar_tiempo("yo", consola, "Juego", 0)
                db_local.sumar_tiempo("yo", consola, "Juego", 90.6)
                db_local.sumar_tiempo("otro", consola, "Juego", 500)
                self.assertEqual(db_local.obtener_tiempo(consola, "Juego")["segundos"], 90)
                juego = db_local.LocalDB().obtener_juegos_filtrados("", consola)[0]
                self.assertEqual(juego["segundos"], 90)
                self.assertTrue(juego["ultima_vez"])

    def test_coleccion_sin_archivo(self):
        with tempfile.TemporaryDirectory() as carpeta, mock.patch.object(db_local, "DB_NAME", os.path.join(carpeta, "x.db")):
            db_local.inicializar_db_local()
            consola = db_local.LocalDB().obtener_consolas()[0]["id"]
            juego = db_local.agregar_a_coleccion(consola, "psx", "Juego")
            self.assertTrue(db_local.obtener_juego_detalle(juego)["sin_archivo"])
            self.assertTrue(launcher.ejecutar_juego(juego)["sin_archivo"])
            rom = os.path.join(carpeta, "Juego.bin")
            open(rom, "w").close()
            db_local.registrar_juego(consola, "Juego", rom)   # ya estaba escaneado: la entrada sin archivo sobra
            self.assertFalse(db_local.obtener_juego_detalle(juego)["sin_archivo"])
            self.assertIn("emulador", launcher.ejecutar_juego(juego)["error"])   # usa el archivo real
            real = db_local.asignar_archivo(juego, rom)
            self.assertNotEqual(real, juego)
            self.assertIsNone(db_local.obtener_juego_detalle(juego))
            juego = db_local.agregar_a_coleccion(consola, "psx", "Juego")
            db_local.quitar_de_coleccion(consola, "Juego")
            self.assertIsNone(db_local.obtener_juego_detalle(juego))
            with db_local.obtener_conexion() as conn:   # el escaneado sigue
                self.assertEqual(conn.execute("SELECT ruta_rom FROM juegos;").fetchall(), [(rom,)])

    def test_solo_se_abren_enlaces_de_itch_reales(self):
        for host, esperado in (("itch.io", True), ("autor.itch.io", True), ("malitch.io", False), (None, False)):
            self.assertEqual(catalogo.es_enlace_de_itch(host), esperado, host)


class FeedsDeNoticias(unittest.TestCase):
    def test_rss_quita_html_y_solo_acepta_enlaces_https_del_sitio(self):
        xml = b"""<?xml version="1.0"?><rss><channel>
            <item><title>Uno &amp;amp; dos</title><link>https://a.com/1</link>
              <description><![CDATA[<p>Hola <script>alert(1)</script><b>mundo</b></p>]]></description>
              <pubDate>Wed, 04 Nov 2026 17:32:31 +0000</pubDate></item>
            <item><title>Malo</title><link>javascript:alert(1)</link></item>
            <item><title>Otro sitio</title><link>https://b.com/1</link></item>
            <item><title>Http</title><link>http://a.com/1</link></item>
        </channel></rss>"""
        notas = noticias.leer_feed(xml, "A", "a.com")
        self.assertEqual(len(notas), 1)
        self.assertEqual((notas[0]["titulo"], notas[0]["resumen"], notas[0]["enlace"]), ("Uno & dos", "Hola mundo", "https://a.com/1"))
        self.assertEqual(notas[0]["fecha"], "2026-11-04T17:32:31+00:00")

    def test_acepta_el_mismo_sitio_con_o_sin_www_y_se_puede_abrir(self):
        xml = b"<rss><channel><item><title>T</title><link>https://retrorgb.com/1</link></item></channel></rss>"
        self.assertEqual(len(noticias.leer_feed(xml, "R", "www.retrorgb.com")), 1)
        self.assertLessEqual({"retrorgb.com", "www.retrorgb.com"}, noticias.HOSTS)

    def test_elige_una_sola_imagen_https_y_evita_avatares(self):
        xml = b"""<rss xmlns:media="http://search.yahoo.com/mrss/"><channel>
            <item><title>Declarada</title><link>https://a.com/1</link>
              <media:content url="https://secure.gravatar.com/a.jpg" medium="image"/>
              <media:content url="https://a.com/foto.jpg" medium="image"/>
              <description><![CDATA[<img src="https://a.com/otra.jpg">]]></description></item>
            <item><title>Texto</title><link>https://a.com/2</link>
              <description>&lt;img class="x" src="https://a.com/up/f-150x150.png"&gt;&lt;img src="https://a.com/2.png"&gt;</description></item>
            <item><title>Insegura</title><link>https://a.com/3</link>
              <description><![CDATA[<img src="http://a.com/m.png"><img src="javascript:alert(1)">]]></description></item>
        </channel></rss>"""
        notas = noticias.leer_feed(xml, "A", "a.com")
        self.assertEqual([n["imagen"] for n in notas], ["https://a.com/foto.jpg", "https://a.com/up/f.png", ""])

    def test_atom_y_fecha_invalida(self):
        xml = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>T</title>
            <link rel="self" href="https://a.com/yo"/><link href="https://a.com/2"/>
            <summary>S</summary><published>no es fecha</published></entry></feed>"""
        self.assertEqual(noticias.leer_feed(xml, "A", "a.com"),
                         [{"titulo": "T", "resumen": "S", "enlace": "https://a.com/2", "fuente": "A", "fecha": None, "imagen": ""}])

    def test_rechaza_entidades_y_recorta_el_resumen(self):
        with self.assertRaises(ValueError):
            noticias.leer_feed(b'<!DOCTYPE r [<!ENTITY a "b">]><rss></rss>', "A", "a.com")
        self.assertLessEqual(len(noticias._texto_plano("palabra " * 100, 220)), 221)


class MensajesDeGrupo(unittest.TestCase):
    def setUp(self):
        self.ana, self.beto, self.intruso = (cifrado.privada_de(bytes([i]) * 16) for i in (1, 2, 3))
        self.publicas = {"ana": self._pub(self.ana), "beto": self._pub(self.beto)}

    @staticmethod
    def _pub(privada):
        return cifrado._b64(bytes(privada.public_key))

    def _enviar(self, tipo="texto", contenido="hola", publicas=None, grupo="g1"):
        return cifrado.cifrar_para_grupo(self.ana, publicas or self.publicas, "ana", grupo, tipo, contenido)

    def test_lo_leen_los_miembros_y_el_servidor_no_ve_el_texto(self):
        guardado, copias = self._enviar(contenido="secreto")
        self.assertNotIn("secreto", guardado + str(copias))
        for privada, yo in ((self.ana, "ana"), (self.beto, "beto")):
            self.assertEqual(cifrado.descifrar_de_grupo(privada, yo, "ana", "g1", guardado, copias), ("texto", "secreto"))

    def test_quien_no_estaba_al_enviarlo_no_puede_leerlo(self):
        guardado, copias = self._enviar()
        self.assertEqual(cifrado.descifrar_de_grupo(self.intruso, "intruso", "ana", "g1", guardado, copias)[1], cifrado.ILEGIBLE_DANADO)
        # Ni copiando la llave de otro miembro: esa copia está sellada para esa persona
        copias["intruso"] = copias["beto"]
        self.assertIn(cifrado.descifrar_de_grupo(self.intruso, "intruso", "ana", "g1", guardado, copias)[1], cifrado.ILEGIBLES)

    def test_no_se_puede_mover_a_otro_grupo_ni_cambiar_de_autor(self):
        guardado, copias = self._enviar()
        self.assertEqual(cifrado.descifrar_de_grupo(self.beto, "beto", "ana", "otro", guardado, copias)[1], cifrado.ILEGIBLE_DANADO)
        self.assertEqual(cifrado.descifrar_de_grupo(self.beto, "beto", "intruso", "g1", guardado, copias)[1], cifrado.ILEGIBLE_DANADO)

    def test_un_miembro_no_puede_imitar_a_otro(self):
        # El intruso firma con su llave pero dice ser Ana, publicando la llave de Ana: no abre
        guardado, copias = cifrado.cifrar_para_grupo(self.intruso, self.publicas, "ana", "g1", "texto", "falso")
        partes = guardado.split(":")
        falso = f"e2:{self.publicas['ana']}:{partes[2]}"
        self.assertEqual(cifrado.descifrar_de_grupo(self.beto, "beto", "ana", "g1", falso, copias)[1], cifrado.ILEGIBLE_DANADO)

    def test_otra_frase_lo_dice_y_un_adjunto_debe_coincidir(self):
        guardado, copias = self._enviar()
        nueva = cifrado.privada_de(b"n" * 16)
        self.assertEqual(cifrado.descifrar_de_grupo(nueva, "beto", "ana", "g1", guardado, copias)[1], cifrado.ILEGIBLE_OTRA_FRASE)
        ruta = "ana/cifrados/" + "0" * 32 + ".bin"
        guardado, copias = cifrado.cifrar_para_grupo(self.ana, self.publicas, "ana", "g1", "imagen", ruta, b"k" * 32)
        adjuntos = {}
        self.assertEqual(cifrado.descifrar_de_grupo(self.beto, "beto", "ana", "g1", guardado, copias, ruta, adjuntos), ("imagen", ruta))
        self.assertEqual(adjuntos[ruta], b"k" * 32)
        self.assertEqual(cifrado.descifrar_de_grupo(self.beto, "beto", "ana", "g1", guardado, copias, "otra", {})[1], cifrado.ILEGIBLE_DANADO)

    def test_el_mensaje_mas_largo_de_un_grupo_lleno_entra_en_los_limites_de_la_base(self):
        publicas = {f"{i:036d}": self.publicas["beto"] for i in range(20)}
        guardado, copias = self._enviar(contenido="ñ" * 1000, publicas=publicas)
        self.assertLessEqual(len(guardado), 10000)
        self.assertLessEqual(len(__import__("json").dumps(copias)), 20000)


class SenalesDeLlamada(unittest.TestCase):
    def setUp(self):
        self.parches = {"ana": bytes(16), "beto": bytes(range(16)), "intruso": b"i" * 16}
        self.publicas = {n: cifrado.publica_de(e) for n, e in self.parches.items()}
        self.ana, self.beto, self.intruso = (self._persona(n) for n in ("ana", "beto", "intruso"))

    def _persona(self, nombre):
        cuenta = _CuentaFalsa()
        cuenta._yo = lambda: f"{self.id()}-{nombre}"
        llaves = cifrado.Llaves(cuenta)
        llaves._privada = (cuenta._yo(), cifrado.privada_de(self.parches[nombre]))
        llaves._publicada = lambda amigo: self.publicas[amigo.rsplit("-", 1)[1]]
        return llaves

    def _id(self, nombre):
        return f"{self.id()}-{nombre}"

    def test_llega_entera_y_solo_a_su_destinatario(self):
        s = self.ana.sellar_senal("c1", self._id("beto"), "datos-sdp")["sellada"]
        self.assertNotIn("datos-sdp", s)
        self.assertEqual(self.beto.abrir_senal("c1", self._id("ana"), s), {"exito": True, "datos": "datos-sdp"})
        self.assertFalse(self.intruso.abrir_senal("c1", self._id("ana"), s)["exito"])

    def test_rechaza_otra_llamada_otro_emisor_y_alteraciones(self):
        s = self.ana.sellar_senal("c1", self._id("beto"), "x")["sellada"]
        self.assertFalse(self.beto.abrir_senal("c2", self._id("ana"), s)["exito"])
        self.assertFalse(self.beto.abrir_senal("c1", self._id("intruso"), s)["exito"])
        self.assertFalse(self.beto.abrir_senal("c1", self._id("ana"), s[:-6] + "AAAA" + s[-2:])["exito"])
        self.assertFalse(self.beto.abrir_senal("c1", self._id("ana"), "basura")["exito"])

    def test_no_se_puede_devolver_una_senal_a_quien_la_envio(self):
        s = self.ana.sellar_senal("c1", self._id("beto"), "x")["sellada"]
        self.assertFalse(self.ana.abrir_senal("c1", self._id("beto"), s)["exito"])

    def test_si_la_llave_cambio_la_llamada_no_conecta(self):
        self.ana.estado_amigo(self._id("beto"))
        self.publicas["beto"] = self.publicas["intruso"]
        self.assertFalse(self.ana.sellar_senal("c1", self._id("beto"), "x")["exito"])
        self.assertFalse(self.ana.abrir_senal("c1", self._id("beto"), "AAAA")["exito"])


class AdjuntosDeDenuncia(unittest.TestCase):
    class Consulta:
        def __init__(self, filas):
            self.filas = filas

        def __getattr__(self, _):
            return lambda *a, **k: self

        def execute(self):
            return mock.Mock(data=self.filas)

    def _cliente(self, filas):
        from nucleo.cloud_client import CloudClient
        cloud = CloudClient.__new__(CloudClient)
        cloud.usuario_actual = type("U", (), {"id": "yo"})()
        cloud.client = mock.Mock()
        cloud.client.table = lambda _: self.Consulta(filas)
        cloud.llaves = cifrado.Llaves(cloud)
        cloud.llaves.abrir = lambda m: m
        cloud.descargar_imagen_chat = lambda ruta: b"\x89PNG\r\n\x1a\n" if "buena" in ruta else b"no es imagen"
        return cloud

    def test_copia_el_texto_y_las_imagenes_a_un_espacio_aparte(self):
        filas = [{"id": 1, "de": "otro", "para": "yo", "tipo": "texto", "contenido": "insulto", "creado_en": "t"},
                 {"id": 2, "de": "otro", "para": "yo", "tipo": "imagen", "contenido": "otro/cifrados/buena.bin", "creado_en": "t"},
                 {"id": 3, "de": "otro", "para": "yo", "tipo": "sticker", "contenido": "otro/cifrados/falsa.bin", "creado_en": "t"},
                 {"id": 4, "de": "otro", "para": "yo", "tipo": "texto", "contenido": cifrado.ILEGIBLE_OTRA_FRASE, "creado_en": "t"}]
        cloud = self._cliente(filas)
        cloud.client.rpc = mock.Mock(return_value=self.Consulta(True))
        self.assertTrue(cloud.denunciar_usuario("otro", "acoso", "", [1, 2, 3, 4])["exito"])
        adjuntos = cloud.client.rpc.call_args[0][1]["p_adjuntos"]
        self.assertEqual([(a["tipo"], a["contenido"]) for a in adjuntos],
                         [("texto", "insulto"), ("imagen", None), ("sticker", None)])
        self.assertRegex(adjuntos[1]["archivo"], r"^yo/[0-9a-f]{32}\.png$")
        self.assertIsNone(adjuntos[2]["archivo"])                    # lo que no es una imagen no se sube
        cloud.client.storage.from_.assert_called_once_with("denuncias")
        self.assertNotIn("cifrados", str(adjuntos))

    def test_si_falla_subir_una_imagen_no_se_envia_una_denuncia_incompleta(self):
        cloud = self._cliente([{"id": 2, "de": "otro", "para": "yo", "tipo": "imagen", "contenido": "otro/cifrados/buena.bin", "creado_en": "t"}])
        cloud.client.rpc = mock.Mock()
        cloud.client.storage.from_.return_value.upload.side_effect = RuntimeError("connection")
        self.assertFalse(cloud.denunciar_usuario("otro", "acoso", "", [2])["exito"])
        cloud.client.rpc.assert_not_called()

    def test_sin_elegir_no_se_adjunta_nada_y_hay_un_limite(self):
        cloud = self._cliente([{"id": 1, "de": "otro", "para": "yo", "tipo": "texto", "contenido": "privado", "creado_en": "t"}])
        cloud.client.rpc = mock.Mock(return_value=self.Consulta(True))
        cloud.denunciar_usuario("otro", "acoso")
        self.assertEqual(cloud.client.rpc.call_args[0][1]["p_adjuntos"], [])
        self.assertFalse(cloud.denunciar_usuario("otro", "acoso", "", list(range(21)))["exito"])

    def test_listar_para_denunciar_no_marca_nada_como_leido(self):
        cloud = self._cliente([{"id": 1, "de": "otro", "para": "yo", "tipo": "texto", "contenido": "hola", "creado_en": "t"}])
        with mock.patch.object(cloud, "marcar_leidos") as marcar:
            res = cloud.mensajes_para_denunciar("otro")
        marcar.assert_not_called()
        self.assertEqual(res["mensajes"][0]["texto"], "hola")


if __name__ == "__main__":
    unittest.main()
