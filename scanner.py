import os
import re
import threading

import boxart
import db_local
from boxart import CARPETA_ROMS_BASE, CARPETA_BOXARTS

# Estado compartido que la interfaz consulta mientras el escaneo corre en segundo plano
ESTADO = {
    "activo": False,
    "fase": "",
    "juegos": 0,
    "portadas_total": 0,
    "portadas_hechas": 0,
    "portadas_ok": 0,
}
_lock_escaneo = threading.Lock()

_RE_DISCO = re.compile(r'[\(\[\{](?:disc|disk|cd)\s*([0-9a-z])[\)\]\}]', re.IGNORECASE)


def crear_estructura_carpetas():
    """Crea 'roms/', 'roms/boxarts/' y una subcarpeta por consola."""
    os.makedirs(CARPETA_BOXARTS, exist_ok=True)

    for consola in db_local.obtener_consolas():
        ruta_consola = os.path.join(CARPETA_ROMS_BASE, consola["identificativo"])
        os.makedirs(ruta_consola, exist_ok=True)

        if not consola["ruta_roms"]:
            db_local.actualizar_rutas_consola(consola["id"], ruta_roms=ruta_consola)


def es_pista_de_audio(nombre_archivo):
    nombre_lower = nombre_archivo.lower()
    patron_track = re.search(r'[\(\[\{\-_ ]track\s*\d+[\)\]\} ]', nombre_lower, re.IGNORECASE)
    patron_audio = re.search(r'\(audio\)', nombre_lower, re.IGNORECASE)

    if "track" in nombre_lower or "audio" in nombre_lower:
        if "track 1" in nombre_lower or "track 01" in nombre_lower or "track1" in nombre_lower:
            return False
        return True

    return bool(patron_track or patron_audio)


def limpiar_titulo(nombre):
    nombre_limpio = re.sub(r'[\(\[\{].*?[\)\]\}]', '', nombre)
    nombre_limpio = nombre_limpio.replace('_', ' ')
    return ' '.join(nombre_limpio.split()).strip()


def generar_m3u_para_multidisco(directorio, archivos_consola):
    discos_por_juego = {}
    tiene_cue = any(f.lower().endswith('.cue') for f in archivos_consola)

    for archivo in archivos_consola:
        if es_pista_de_audio(archivo):
            continue
        _, ext = os.path.splitext(archivo)
        ext_lower = ext.lower()

        if ext_lower not in ['.cue', '.iso', '.chd', '.bin', '.gdi', '.pbp']:
            continue
        if tiene_cue and ext_lower == '.bin':
            continue

        if _RE_DISCO.search(archivo):
            titulo_base = limpiar_titulo(os.path.splitext(archivo)[0])
            discos_por_juego.setdefault(titulo_base, []).append(archivo)

    m3u_creados = []
    for titulo, discos in discos_por_juego.items():
        if len(discos) > 1:
            cues_o_chds = [d for d in discos if d.lower().endswith(('.cue', '.chd', '.iso', '.pbp'))]
            discos_finales = cues_o_chds if cues_o_chds else discos
            discos_finales.sort()

            ruta_m3u = os.path.join(directorio, f"{titulo}.m3u")
            if not os.path.exists(ruta_m3u):
                with open(ruta_m3u, 'w', encoding='utf-8') as f:
                    for disco in discos_finales:
                        f.write(f"{disco}\n")
            m3u_creados.append(ruta_m3u)

    return m3u_creados


def _primer_disco_m3u(ruta_m3u):
    """Nombre (sin extensión) del primer disco de una lista .m3u: conserva la región,
    que el título limpio del .m3u ya no tiene. Sirve para encontrar mejor la carátula."""
    try:
        with open(ruta_m3u, encoding="utf-8", errors="ignore") as f:
            for linea in f:
                linea = linea.strip()
                if linea and not linea.startswith("#"):
                    return os.path.splitext(os.path.basename(linea))[0]
    except OSError:
        pass
    return ""


def _portada_valida(ruta):
    return bool(ruta) and os.path.isfile(ruta) and os.path.getsize(ruta) > 100


def escanear_consola(consola, mapa_portadas, trabajos_portada):
    """Registra los juegos de una consola y agrega a 'trabajos_portada' los que
    todavía no tienen una carátula válida en disco."""
    ruta_roms = consola.get("ruta_roms")
    if not ruta_roms or not os.path.exists(ruta_roms):
        return 0

    extensiones_validas = [ext.strip().lower() for ext in consola["extensiones"].split(",")]
    if ".m3u" not in extensiones_validas:
        extensiones_validas.append(".m3u")

    juegos_registrados = 0

    for raiz, _, archivos in os.walk(ruta_roms):
        generar_m3u_para_multidisco(raiz, archivos)

        tiene_m3u = any(f.lower().endswith('.m3u') for f in archivos)
        tiene_cue = any(f.lower().endswith('.cue') for f in archivos)

        for archivo in archivos:
            nombre_base, ext = os.path.splitext(archivo)
            ext_lower = ext.lower()

            if ext_lower not in extensiones_validas:
                continue
            if es_pista_de_audio(archivo):
                continue
            if tiene_cue and ext_lower == ".bin":
                continue
            if tiene_m3u and _RE_DISCO.search(archivo) and ext_lower != '.m3u':
                continue

            ruta_completa = os.path.join(raiz, archivo)
            titulo_para_ui = limpiar_titulo(nombre_base)

            # Se registra el juego YA (el catálogo aparece rápido); la carátula llega después
            db_local.registrar_juego(
                consola_id=consola["id"],
                titulo=titulo_para_ui,
                ruta_rom=ruta_completa,
            )
            juegos_registrados += 1

            if not _portada_valida(mapa_portadas.get(ruta_completa, "")):
                alternos = []
                if ext_lower == ".m3u":
                    primero = _primer_disco_m3u(ruta_completa)
                    if primero:
                        alternos.append(primero)
                trabajos_portada.append({
                    "identificativo": consola["identificativo"],
                    "consola": consola["nombre"],
                    "nombre_rom": nombre_base,
                    "titulo": titulo_para_ui,
                    "ruta_rom": ruta_completa,
                    "alternos": alternos,
                })

    return juegos_registrados


def _ejecutar_escaneo():
    crear_estructura_carpetas()
    mapa_portadas = db_local.obtener_mapa_portadas()
    trabajos = []
    total = 0

    ESTADO["fase"] = "Buscando juegos…"
    for consola in db_local.obtener_consolas():
        total += escanear_consola(consola, mapa_portadas, trabajos)
        ESTADO["juegos"] = total

    ESTADO.update(fase="Descargando carátulas…", portadas_total=len(trabajos),
                  portadas_hechas=0, portadas_ok=0)

    def al_avanzar(hechos, exitosos):
        ESTADO["portadas_hechas"] = hechos
        ESTADO["portadas_ok"] = exitosos

    boxart.descargar_lote(trabajos, db_local.actualizar_portada, al_avanzar)
    return total


def escanear_todo():
    """Escaneo completo (bloqueante). Seguro de llamar desde consola o desde un hilo."""
    with _lock_escaneo:
        ESTADO.update(activo=True, fase="", juegos=0, portadas_total=0,
                      portadas_hechas=0, portadas_ok=0)
        try:
            return _ejecutar_escaneo()
        finally:
            ESTADO.update(activo=False, fase="")


def iniciar_escaneo():
    """Lanza el escaneo en segundo plano. Devuelve False si ya había uno en curso."""
    if ESTADO["activo"]:
        return False
    ESTADO["activo"] = True  # se reserva antes de arrancar el hilo

    def tarea():
        try:
            total = escanear_todo()
            print(f"[ESCANEO] Finalizado. Juegos encontrados: {total}")
        except Exception as e:
            print(f"[ESCANEO ERROR] {e}")
            ESTADO.update(activo=False, fase="")

    threading.Thread(target=tarea, daemon=True).start()
    return True


def estado_escaneo():
    return dict(ESTADO)


class ROMScanner:
    def escanear(self):
        return escanear_todo()

    def iniciar(self):
        return iniciar_escaneo()

    def estado(self):
        return estado_escaneo()


if __name__ == "__main__":
    db_local.inicializar_db_local()
    total = escanear_todo()
    print(f"Escaneo finalizado. Juegos listos: {total}")
