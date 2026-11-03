"""Regresiones de la revisión del 2026-11-03. Ejecutar: python -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_local
import launcher
import scanner


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
        self.ids = [j["id"] for j in db_local.obtener_juegos_por_consola(self.consola)]
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


if __name__ == "__main__":
    unittest.main()
