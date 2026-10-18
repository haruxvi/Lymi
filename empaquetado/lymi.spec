# -*- mode: python -*-
# Receta de PyInstaller: una carpeta con la ventana (`lymi`) y la terminal (`lymi-cli`).
#
# Se construye en cada sistema; PyInstaller no compila para otro:
#     uv sync --extra escritorio --extra empaquetar
#     uv run pyinstaller empaquetado/lymi.spec --noconfirm
#
# Solo va el motor Qt WebEngine: WebView2 (Microsoft) y los demas motores de pywebview
# quedan fuera del paquete, asi un `--motor edge` no puede activarse por accidente.

import sys
from pathlib import Path

RAIZ = Path(SPECPATH).parent
EMP = RAIZ / "empaquetado"
WIN, MAC = sys.platform == "win32", sys.platform == "darwin"

DATOS = [
    (str(RAIZ / "src/lymi/ui/static"), "lymi/ui/static"),
    (str(RAIZ / "src/lymi/ledger/schema.sql"), "lymi/ledger"),
    (str(RAIZ / "workflows"), "workflows"),
    (str(RAIZ / "agencias"), "agencias"),
    (str(RAIZ / "LICENSE"), "."),
    (str(RAIZ / "THIRD_PARTY_NOTICES.md"), "."),
]
FUERA = [
    "clr", "clr_loader", "pythonnet",
    "webview.platforms.winforms", "webview.platforms.edgechromium", "webview.platforms.mshtml",
    "webview.platforms.cef", "webview.platforms.gtk", "webview.platforms.cocoa", "webview.platforms.android",
    "tkinter", "PyQt5", "PyQt6", "PySide2",
]
OCULTOS = ["webview.platforms.qt", "qtpy", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore",
           "PySide6.QtWebChannel", "PySide6.QtNetwork"]
ICONO = str(EMP / ("lymi.ico" if WIN else "lymi.icns" if MAC else "lymi.png"))


import fnmatch

# Lo que PyInstaller arrastra de PySide6 y la ventana no usa: QML, 3D, graficos y las
# traducciones de Qt (la ventana solo necesita las de Chromium en espanol e ingles).
# Medido: de 602 MB a lo que queda tras este filtro. Qt WebEngine mismo no se toca.
SOBRA = [
    "PySide6/qml/*", "PySide6/translations/qt_*", "PySide6/translations/qtbase_*",
    "PySide6/translations/assistant_*", "PySide6/translations/designer_*", "PySide6/translations/linguist_*",
    "PySide6/translations/qtdeclarative_*", "PySide6/translations/qtmultimedia_*", "PySide6/translations/qtserialport_*",
    "PySide6/translations/qtwebsockets_*", "PySide6/translations/qtconnectivity_*", "PySide6/translations/qtlocation_*",
    "PySide6/translations/qthelp_*", "PySide6/translations/qtwebengine_[!l]*",
    "PySide6/*Qt63D*", "PySide6/*Qt6Quick3D*", "PySide6/*Qt6QuickControls2*", "PySide6/*Qt6QuickDialogs2*",
    "PySide6/*Qt6QuickTemplates2*", "PySide6/*Qt6Graphs*", "PySide6/*Qt6Charts*", "PySide6/*Qt6DataVisualization*",
    "PySide6/*Qt6Multimedia*", "PySide6/*Qt6SpatialAudio*", "PySide6/*Qt6Designer*", "PySide6/*Qt6Help*",
    "PySide6/*Qt6Sensors*", "PySide6/*Qt6SerialPort*", "PySide6/*Qt6Bluetooth*", "PySide6/*Qt6Nfc*",
    "PySide6/*Qt6RemoteObjects*", "PySide6/*Qt6Scxml*", "PySide6/*Qt6StateMachine*", "PySide6/*Qt6TextToSpeech*",
    "PySide6/*Qt6VirtualKeyboard*", "PySide6/*Qt6Quick3DPhysics*", "PySide6/*Qt6HttpServer*",
]
IDIOMAS_WEB = ("es.pak", "es-419.pak", "en-US.pak")


def _sobra(destino):
    destino = destino.replace("\\", "/")
    if "qtwebengine_locales/" in destino:
        return not destino.endswith(IDIOMAS_WEB)
    return any(fnmatch.fnmatch(destino, patron) for patron in SOBRA)


def analizar(script):
    a = Analysis(
        [str(EMP / script)], pathex=[str(RAIZ / "src")], datas=DATOS, hiddenimports=OCULTOS,
        excludes=FUERA, noarchive=False,
    )
    a.binaries = [b for b in a.binaries if not _sobra(b[0])]
    a.datas = [d for d in a.datas if not _sobra(d[0])]
    return a


ventana = analizar("ventana.py")
consola = analizar("consola.py")
exe_ventana = EXE(
    PYZ(ventana.pure), ventana.scripts, [], exclude_binaries=True, name="lymi", console=False,
    icon=ICONO, upx=False,
)
exe_consola = EXE(
    PYZ(consola.pure), consola.scripts, [], exclude_binaries=True, name="lymi-cli", console=True,
    icon=ICONO, upx=False,
)
carpeta = COLLECT(
    exe_ventana, ventana.binaries, ventana.datas,
    exe_consola, consola.binaries, consola.datas,
    name="lymi", upx=False,
)
if MAC:
    app = BUNDLE(
        carpeta, name="lymi.app", icon=ICONO, bundle_identifier="dev.lymi.app",
        info_plist={"NSHighResolutionCapable": True, "LSApplicationCategoryType": "public.app-category.productivity"},
    )
