# -*- mode: python ; coding: utf-8 -*-
# ======================================================================
#  PyInstaller-Bauplan für Bookbench (wird von build_windows.bat aufgerufen;
#  von Hand im Ordner packaging:  python -m PyInstaller --noconfirm --clean bookbench.spec ).
#  Ergebnis: dist\Bookbench\Bookbench.exe (Ordner, kein onefile: startet schneller,
#  Windows Defender prüft nicht bei jedem Start ein frisch entpacktes Archiv).
#
#  Seit 2.0 Qt (PySide6-Essentials) statt Tk: tkinter und die Tk-Bausteine aus bookbench/keller (außer
#  keller_icons) kommen nicht mit; von den Qt-Übersetzungen nur Deutsch
#  (Englisch braucht keine), von den Qt-Modulen nur, was Bookbench importiert (QtCore, QtGui, QtWidgets) -
#  die übrigen der Essentials (Qml, Quick, Designer, Sql …) schließt EXCLUDES ausdrücklich aus.
#  Zusatzpakete (Pillow, wordfreq, requests, mwparserfromhell, anthropic) kommen mit,
#  wenn sie im bauenden Python installiert sind; wordfreq braucht seine Datendateien, davon
#  aber nur die Wortlisten der Sprachen in WORDFREQ_SPRACHEN (alle zusammen ca. 60 MB, darunter
#  5 MB chinesisches Wörterbuch für jieba; Bookbench fragt nur Englisch ab).
# ======================================================================
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

WURZEL = os.path.abspath(os.path.join(SPECPATH, ".."))
BOOK = os.path.join(WURZEL, "bookbench")

WORDFREQ_SPRACHEN = {"en"}                         # zipf_frequency(..., "en") in bookbench/dictionary
QT_SPRACHEN = ("_de.qm",)                          # Qt-eigene Texte (OK, Abbrechen, Dateidialog)
EXCLUDES = ["tkinter", "_tkinter", "keller_theme", "keller_streifen", "keller_navigation",
            "matplotlib", "numpy.tests", "pytest",
            "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
            "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtHelp",
            "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
            "PySide6.QtConcurrent", "PySide6.QtDBus", "PySide6.QtXml", "PySide6.QtSvgWidgets"]


def _behalten(ziel):
    teile = ziel.replace("\\", "/").split("/")
    if teile[:2] == ["wordfreq", "data"] and len(teile) == 3:
        name = teile[2]
        sprache = name.split(".")[0].split("_", 1)[-1] if name.startswith(("large_", "small_")) else ""
        return sprache in WORDFREQ_SPRACHEN
    if "translations" in teile and teile[-1].endswith(".qm"):
        return teile[-1].startswith("qtbase") and teile[-1].endswith(QT_SPRACHEN)
    return True


def _vorhanden(paket):
    try:
        __import__(paket)
        return True
    except Exception:
        return False


datas = [
    (os.path.join(BOOK, "locale"), os.path.join("bookbench", "locale")),
    (os.path.join(BOOK, "ui", "bookbench.png"), os.path.join("bookbench", "ui")),
]
if _vorhanden("wordfreq"):
    datas += collect_data_files("wordfreq")

# bookbench lädt manches erst bei Bedarf
hidden = [m for m in collect_submodules("bookbench")
          if not m.startswith(("bookbench.keller.keller_theme", "bookbench.keller.keller_streifen",
                               "bookbench.keller.keller_navigation"))]

a = Analysis(
    [os.path.join(WURZEL, "start.py")],
    pathex=[WURZEL, os.path.join(BOOK, "keller")],
    datas=datas,
    hiddenimports=hidden,
    excludes=EXCLUDES,
    noarchive=False,
)
vorher = len(a.datas)
a.datas = [e for e in a.datas if _behalten(e[0])]
print(f"bookbench.spec: {vorher - len(a.datas)} Qt-Übersetzungen und wordfreq-Listen weggelassen")

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Bookbench",
    icon=os.path.join(SPECPATH, "bookbench.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="Bookbench")
