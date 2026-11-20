# -*- mode: python ; coding: utf-8 -*-
# ======================================================================
#  PyInstaller-Bauplan für Bookbench (wird von build_windows.bat aufgerufen;
#  von Hand im Ordner packaging:  python -m PyInstaller --noconfirm --clean bookbench.spec ).
#  Ergebnis: dist\Bookbench\Bookbench.exe (Ordner, kein onefile: startet schneller,
#  Windows Defender prüft nicht bei jedem Start ein frisch entpacktes Archiv).
#
#  Wie beim Keller-Tool fliegen die Tcl/Tk-Dateien fremder Sprachen, Zeitzonen und
#  Zeichensätze raus; behalten werden Deutsch und Englisch (Knöpfe der Tk-Dialoge).
#  Zusatzpakete (Pillow, wordfreq, requests, mwparserfromhell, anthropic) kommen mit,
#  wenn sie im bauenden Python installiert sind; wordfreq braucht seine Datendateien.
# ======================================================================
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

WURZEL = os.path.abspath(os.path.join(SPECPATH, ".."))
BOOK = os.path.join(WURZEL, "bookbench")

BEHALTEN_MSGS = {"de.msg", "en.msg", "en_gb.msg"}
BEHALTEN_TZ = {"Europe/Berlin", "UTC", "GMT", "Etc/UTC", "Etc/GMT"}
BEHALTEN_ENC = {"ascii.enc", "cp1252.enc", "cp850.enc", "cp437.enc", "iso8859-1.enc", "iso8859-15.enc",
                "utf-8.enc"}


def _behalten(ziel):
    teile = ziel.replace("\\", "/").split("/")
    if len(teile) < 3 or teile[0] not in ("_tcl_data", "_tk_data"):
        return True
    rest = "/".join(teile[2:])
    if teile[1] == "msgs":
        return rest in BEHALTEN_MSGS
    if teile[0] == "_tcl_data" and teile[1] == "tzdata":
        return rest in BEHALTEN_TZ
    if teile[0] == "_tcl_data" and teile[1] == "encoding":
        return rest in BEHALTEN_ENC
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

# bookbench lädt manches erst bei Bedarf; die keller_*.py liegen ohne Paketnamen in bookbench/keller
hidden = collect_submodules("bookbench") + ["keller_theme", "keller_icons", "keller_streifen", "keller_navigation"]

a = Analysis(
    [os.path.join(WURZEL, "start.py")],
    pathex=[WURZEL, os.path.join(BOOK, "keller")],
    datas=datas,
    hiddenimports=hidden,
    excludes=["matplotlib", "numpy.tests", "pytest"],
    noarchive=False,
)
vorher = len(a.datas)
a.datas = [e for e in a.datas if _behalten(e[0])]
print(f"bookbench.spec: {vorher - len(a.datas)} Tcl/Tk-Sprach-/Länderdateien weggelassen")

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
