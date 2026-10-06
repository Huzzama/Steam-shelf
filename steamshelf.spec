# PyInstaller spec for Steam Shelf (Windows and Linux): one folder, dist/SteamShelf/.
#
#     python tools/build.py            (runs this, then the installer / AppImage)
#     pyinstaller steamshelf.spec      (just the folder)
#
# One executable serves every mode (the app, --agent, --prompt): the agent is the
# same binary started again, which is what shelf.launch.self_command does when frozen.
import sys
from pathlib import Path

ROOT = Path(SPECPATH)
VERSION = (ROOT / "VERSION").read_text().strip()
ICON = str(ROOT / "assets" / ("icon.ico" if sys.platform == "win32" else "icon.png"))

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "locales"), "locales"),
        (str(ROOT / "assets"), "assets"),
        (str(ROOT / "VERSION"), "."),
    ],
    hiddenimports=["shelf.win32", "shelf.linux"],           # imported by name at run time (shelf.host)
    excludes=["tkinter", "unittest", "pydoc", "numpy",       # Pillow pulls numpy in; we never use it
              "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL", "PySide6.QtPdf",
              "PySide6.QtSvgWidgets"],           # QtSvg itself is used (icons)
    noarchive=False,
)

# Qt pieces PyInstaller's hooks drag in that the app never loads (~90 MB on Linux)
_DROP = ("Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6Network", "Qt6OpenGL", "Qt6SvgWidgets", "Qt6Sql", "Qt6Test", "Qt6Xml",
         "Qt6Concurrent", "Qt6PrintSupport", "Qt6VirtualKeyboard", "Qt6Labs", "Qt6Designer", "Qt6Help",
         "Qt6WebEngine", "Qt6Multimedia", "Qt6Positioning", "Qt6Sensors", "Qt6SerialPort", "Qt6Bluetooth",
         "Qt6Charts", "Qt6DataVisualization", "Qt6Nfc", "Qt6RemoteObjects", "Qt6Scxml", "Qt6StateMachine",
         "Qt6TextToSpeech", "Qt6WebChannel", "Qt6WebSockets", "Qt6WebView", "Qt6Http", "Qt6Graphs", "Qt6Spatial",
         "Qt6Quick3D", "Qt6ShaderTools", "Qt6Location", "Qt6Examples", "Qt6Core5", "Qt6Uic",
         "/translations/", "\\translations\\", "/qml/", "\\qml\\", "numpy")


def _keep(entry):
    name = entry[0].replace("\\", "/")
    return not any(d.replace("\\", "/") in name for d in _DROP)


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="SteamShelf",
    icon=ICON,
    console=False,                   # the agent and the card must never pop a console window
    disable_windowed_traceback=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SteamShelf", upx=False)
