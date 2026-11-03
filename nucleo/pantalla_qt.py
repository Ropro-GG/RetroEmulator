# pantalla_qt.py - Permite compartir pantalla en Linux, donde la app usa Qt WebEngine.
# Solo se usa con Qt: en Windows, WebView2 ya trae su propio selector.
#
# Por qué hace falta: pywebview arranca Chromium con --use-fake-ui-for-media-stream, deniega el
# permiso de captura de pantalla y no atiende la señal con la que Qt pide elegir qué compartir.
# Además, su manejador de permisos falla con PyQt6 (pasa un entero donde se espera un enum); la
# opción anterior lo ocultaba, así que al quitarla hay que reemplazar también ese manejador.
# Estos cambios se aplican a pywebview sin modificar sus archivos; requirements.txt fija su versión
# porque dependen de cómo funciona por dentro.
from qtpy.QtCore import QModelIndex, QPersistentModelIndex, Qt
from qtpy.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from qtpy.QtWidgets import (QDialog, QDialogButtonBox, QListWidget, QListWidgetItem, QTabWidget,
                            QVBoxLayout)
from webview.platforms import qt as qt_pywebview

_OPCION_INCOMPATIBLE = "--use-fake-ui-for-media-stream"
# Lo único que la app puede usar; cualquier otro permiso se deniega, como hacía pywebview.
# La captura de pantalla no es silenciosa: Qt solo la pide después de usar el selector.
_PERMITIDOS = (QWebEnginePage.Feature.MediaAudioCapture,
               QWebEnginePage.Feature.MediaVideoCapture,
               QWebEnginePage.Feature.MediaAudioVideoCapture,
               QWebEnginePage.Feature.DesktopVideoCapture,
               QWebEnginePage.Feature.DesktopAudioVideoCapture)

_ESTILO = """
QDialog, QTabWidget::pane, QListWidget { background: #1F2833; color: #C5C6C7; border: 1px solid #45A29E; }
QTabBar::tab { background: #141722; color: #C5C6C7; padding: 8px 18px; }
QTabBar::tab:selected { background: #45A29E; color: #0B0C10; }
QListWidget::item { padding: 8px; }
QListWidget::item:selected { background: #45A29E; color: #0B0C10; }
QPushButton { background: #141722; color: #fff; border: 1px solid #45A29E; border-radius: 6px; padding: 7px 16px; }
QPushButton:hover, QPushButton:focus { border-color: #66FCF1; }
"""


class _Selector(QDialog):
    """Ventana para elegir qué compartir: una pantalla completa o una ventana."""

    def __init__(self, solicitud, padre=None):
        super().__init__(padre)
        self.setWindowTitle("Compartir pantalla")
        self.setStyleSheet(_ESTILO)
        self.resize(460, 380)
        self.pestanas = QTabWidget()
        self.pantallas = self._lista(solicitud.screensModel(), "Pantalla")
        self.ventanas = self._lista(solicitud.windowsModel(), "Ventana")
        self.pestanas.addTab(self.pantallas, "Pantallas")
        self.pestanas.addTab(self.ventanas, "Ventanas")
        botones = QDialogButtonBox()
        self.compartir = botones.addButton("Compartir", QDialogButtonBox.ButtonRole.AcceptRole)
        botones.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        self.pestanas.currentChanged.connect(self._actualizar_boton)
        disenio = QVBoxLayout(self)
        disenio.addWidget(self.pestanas)
        disenio.addWidget(botones)
        self._actualizar_boton()

    def _lista(self, modelo, respaldo):
        # Índices persistentes: la lista de ventanas puede cambiar mientras este diálogo está abierto
        lista = QListWidget()
        for fila in range(modelo.rowCount()):
            indice = modelo.index(fila, 0)
            item = QListWidgetItem(modelo.data(indice, Qt.ItemDataRole.DisplayRole) or f"{respaldo} {fila + 1}")
            item.setData(Qt.ItemDataRole.UserRole, QPersistentModelIndex(indice))
            lista.addItem(item)
        if lista.count():
            lista.setCurrentRow(0)
        lista.currentItemChanged.connect(lambda *_: self._actualizar_boton())
        lista.itemDoubleClicked.connect(lambda *_: self.accept())
        return lista

    def _actualizar_boton(self, *_):
        self.compartir.setEnabled(self.pestanas.currentWidget().currentItem() is not None)

    def eleccion(self):
        """(es_pantalla, índice elegido), o None si esa ventana se cerró mientras tanto."""
        lista = self.pestanas.currentWidget()
        persistente = lista.currentItem().data(Qt.ItemDataRole.UserRole)
        return (lista is self.pantallas, QModelIndex(persistente)) if persistente.isValid() else None


def _mostrar_selector(solicitud, padre):
    """Muestra el selector. Sin elegir nada, JavaScript recibe NotAllowedError y no comparte."""
    try:
        dialogo = _Selector(solicitud, padre)
        eleccion = dialogo.eleccion() if dialogo.exec() == QDialog.DialogCode.Accepted else None
        if eleccion is None:
            solicitud.cancel()
        elif eleccion[0]:
            solicitud.selectScreen(eleccion[1])
        else:
            solicitud.selectWindow(eleccion[1])
    except Exception as e:   # PyQt cierra toda la app ante un error aquí: cortaría la llamada en curso
        print(f"[LLAMADAS] Error en el selector de pantalla: {e}")
        solicitud.cancel()


def activar():
    """Aplica los cambios. Debe llamarse antes de crear la ventana."""
    # Se lee todo antes de cambiar nada: si otra versión de pywebview no lo tiene, esto falla aquí,
    # la app sigue como estaba y las llamadas funcionan, solo que sin compartir pantalla.
    agregar_opciones = qt_pywebview.environ_append
    pagina = qt_pywebview.BrowserView.WebPage
    crear_pagina = pagina.__init__
    pagina.onFeaturePermissionRequested  # noqa: B018
    QWebEnginePage.desktopMediaRequested  # noqa: B018

    def sin_opcion_incompatible(variable, *valores):
        agregar_opciones(variable, *[v for v in valores if v != _OPCION_INCOMPATIBLE])

    def crear(self, *args, **kwargs):
        crear_pagina(self, *args, **kwargs)
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.ScreenCaptureEnabled, True)
        self.desktopMediaRequested.connect(lambda solicitud: _mostrar_selector(solicitud, self.parent()))

    def permiso(self, url, funcion):
        politica = QWebEnginePage.PermissionPolicy
        self.setFeaturePermission(url, funcion, politica.PermissionGrantedByUser if funcion in _PERMITIDOS
                                  else politica.PermissionDeniedByUser)

    qt_pywebview.environ_append = sin_opcion_incompatible
    pagina.__init__ = crear
    pagina.onFeaturePermissionRequested = permiso
