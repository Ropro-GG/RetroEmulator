"""
aplicar_fase4.py - Videollamadas y llamadas grupales: botones de video (🎥) y método para agregar gente a una llamada.

Uso (en la carpeta raíz de RetroEmulator, después de aplicar_fase3.py):
    python aplicar_fase4.py

Hace una copia .bak antes de tocar cada archivo y se puede repetir sin duplicar cambios.
"""
import os
import shutil
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))

CAMBIOS = {
    "gui_app.py": [
        ("    def obtener_historial_llamadas(self, amigo_id):\n        return self._llamadas.historial_con(amigo_id)\n",
         "    def obtener_historial_llamadas(self, amigo_id):\n        return self._llamadas.historial_con(amigo_id)\n\n"
         "    def invitar_a_llamada(self, llamada_id, amigo_ids):\n        return self._llamadas.invitar(llamada_id, amigo_ids)\n",
         "def invitar_a_llamada"),
    ],
    os.path.join("ui", "app.js"): [
        ("            botonIcono('📞', 'Llamada de voz', () => llamarAmigo(u.user_id, u.username)),\n",
         "            botonIcono('📞', 'Llamada de voz', () => llamarAmigo(u.user_id, u.username)),\n"
         "            botonIcono('🎥', 'Videollamada', () => llamarAmigo(u.user_id, u.username, true)),\n",
         "'Videollamada'"),
    ],
    os.path.join("ui", "index.html"): [
        ('<button class="chat-icono" title="Llamada de voz" onclick="llamarAmigoChat()">📞</button>',
         '<button class="chat-icono" title="Llamada de voz" onclick="llamarAmigoChat()">📞</button>\n'
         '                                    <button class="chat-icono" title="Videollamada" onclick="llamarAmigoChat(true)">🎥</button>',
         "llamarAmigoChat(true)"),
    ],
}

COMPROBAR = (
    (os.path.join("ui", "llamadas.js"), "function llAbrirInvitar(", "llamadas.js"),
    (os.path.join("ui", "llamadas.css"), ".llamada-invitar", "llamadas.css"),
    ("llamadas_cloud.py", "def invitar(", "llamadas_cloud.py"),
)


def main():
    problemas = 0
    for rel, cambios in CAMBIOS.items():
        ruta = os.path.join(RAIZ, rel)
        if not os.path.isfile(ruta):
            print(f"[!] No encuentro {rel}")
            problemas += 1
            continue
        with open(ruta, encoding="utf-8") as f:
            texto = f.read()
        nuevo, aplicados, saltados, faltan = texto, 0, 0, []
        for viejo, reemplazo, marca in cambios:
            if marca in nuevo:
                saltados += 1
            elif nuevo.count(viejo) == 1:
                nuevo = nuevo.replace(viejo, reemplazo)
                aplicados += 1
            else:
                faltan.append(viejo.strip().splitlines()[0][:70])
        if faltan:
            problemas += 1
            print(f"[!] {rel}: no se tocó. No encontré (o aparece más de una vez): {faltan}")
            continue
        if aplicados:
            shutil.copyfile(ruta, ruta + ".bak")
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(nuevo)
        print(f"[ok] {rel}: {aplicados} cambio(s) aplicado(s), {saltados} ya estaban")
    for archivo, marca, que in COMPROBAR:
        ruta = os.path.join(RAIZ, archivo)
        if not os.path.isfile(ruta):
            print(f"[!] Falta copiar {que}")
            problemas += 1
        else:
            with open(ruta, encoding="utf-8") as f:
                if marca not in f.read():
                    print(f"[!] {que} es una versión anterior: copiá la nueva.")
                    problemas += 1
    sys.exit(1 if problemas else 0)


if __name__ == "__main__":
    main()
