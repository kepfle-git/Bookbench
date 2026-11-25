# -*- coding: utf-8 -*-
"""
theme.py - Darstellung der Qt-Oberfläche: hell, dunkel oder wie das System; Farben und Symbole.

  PALETTE          Farben hell/dunkel aus dem Keller-Designleitfaden (Werte wie keller_theme.PALETTE,
                   hier kopiert: keller_theme braucht tkinter)
  anwenden(app, darstellung)   "hell"/"dunkel": Stil Fusion mit den Keller-Farben; "system": Stil und
                   Farben, die Qt beim Start gewählt hat (unter KDE mit System-PySide6 Breeze). Gibt
                   "hell" oder "dunkel" zurück (bei "system" nach der Helligkeit des Fensters).
  farben()         Farben der aktuellen Darstellung (bei "system" aus der Qt-Palette abgeleitet) - für
                   alles, was selbst zeichnet (Seitenleiste, Marken, Warnzeilen)
  dunkel()         ist die aktuelle Darstellung dunkel?
  pixmap(b64), eingefaerbt(pixmap, farbe)
  symbol(name)     QIcon der Werkzeugleiste (keller_icons + ui/icons.WZ_*), passend zu hell/dunkel
  seitenleiste(kennung, aktiv)   QPixmap der Seitenleiste (ui/icons.HELL/DUNKEL)

Warum Fusion für hell/dunkel: nur Fusion nimmt eine Palette vollständig an; System-Stile (Breeze,
windows11) zeichnen teils mit eigenen Farben. Gleicher Stil in beiden Modi heißt außerdem gleiche
Abstände - beim Umschalten ändern sich nur die Farben (wie bei clam im Tk-Programm).
"""
import base64

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QStyleFactory

from bookbench.keller import keller_icons as kic          # nur base64-PNGs, kein tkinter
from bookbench.ui import icons as ksy

PALETTE = {
    "hell": {
        "bg": "#f0f0f0", "fg": "#000000", "feld": "#ffffff", "feld_fg": "#000000",
        "sel": "#0078d7", "sel_fg": "#ffffff", "rahmen": "#b4b4b4",
        "kopf": "#e6e6e6", "hinweis": "#666666", "akzent": "#0078d7",
        "deaktiviert": "#8a8a8a", "knopf": "#e1e1e1", "knopf_aktiv": "#e5f1fb",
        "tabellenkopf": "#dddddd",
    },
    "dunkel": {
        "bg": "#2b2d30", "fg": "#dfe1e5", "feld": "#1e1f22", "feld_fg": "#dfe1e5",
        "sel": "#2f5a8f", "sel_fg": "#ffffff", "rahmen": "#43454a",
        "kopf": "#3c3f41", "hinweis": "#9aa0a6", "akzent": "#4a88c7",
        "deaktiviert": "#6f737a", "knopf": "#3c3f41", "knopf_aktiv": "#4a4d52",
        "tabellenkopf": "#3c3f41",
    },
}
# Stände (Punkt im Statusstreifen) und Warnfarben wie im Tk-Programm
MARK = {"hell": {"rot": "#d9534f", "gelb": "#e8a317", "gruen": "#4caf50", "warn": "#d9534f"},
        "dunkel": {"rot": "#d9534f", "gelb": "#e8a317", "gruen": "#4caf50", "warn": "#ff6b61"}}
WARN = {"hell": "#d9534f", "dunkel": "#ff6b61"}              # Fehler (Marke "fehler", rotes ⚠)
PRUEFEN = {"hell": "#d9822b", "dunkel": "#f0a548"}           # Marken der Stufe "pruefen"
WARNZEILE = {"hell": "#f6c9c9", "dunkel": "#6b2b2b"}
OHNEZEILE = {"hell": "#fbeec9", "dunkel": "#4f4220"}         # nur Nummer, kein Name: dezenter als Warnung

_start = {}                       # Stil und Palette beim Start (für "system")
_zustand = {"darstellung": "system", "modus": "hell"}


def stilname(stil=None):
    """Name eines QStyle ("fusion", "breeze", "windows11"); name() ist nach setStyle manchmal leer."""
    stil = stil or QApplication.instance().style()
    return stil.name() or stil.objectName() or stil.metaObject().className().removeprefix("Q").removesuffix("Style").lower()


def merken_beim_start(app):
    """Einmal nach dem Anlegen der QApplication: was Qt von sich aus gewählt hat."""
    _start["stil"] = stilname(app.style())
    _start["palette"] = QPalette(app.palette())


def anwenden(app, darstellung):
    if not _start:
        merken_beim_start(app)
    if darstellung not in ("hell", "dunkel"):
        darstellung = "system"
        app.setStyle(QStyleFactory.create(_start["stil"]) or QStyleFactory.create("Fusion"))
        app.setPalette(_start["palette"])
        modus = "dunkel" if app.palette().color(QPalette.Window).lightness() < 128 else "hell"
    else:
        modus = darstellung
        app.setStyle(QStyleFactory.create("Fusion"))
        p = PALETTE[modus]
        pal = QPalette()
        for rolle, schl in ((QPalette.Window, "bg"), (QPalette.WindowText, "fg"), (QPalette.Base, "feld"),
                            (QPalette.AlternateBase, "kopf"), (QPalette.Text, "feld_fg"),
                            (QPalette.Button, "knopf"), (QPalette.ButtonText, "fg"),
                            (QPalette.Highlight, "sel"), (QPalette.HighlightedText, "sel_fg"),
                            (QPalette.ToolTipBase, "kopf"), (QPalette.ToolTipText, "fg"),
                            (QPalette.PlaceholderText, "hinweis"), (QPalette.Mid, "rahmen"),
                            (QPalette.Link, "akzent"), (QPalette.LinkVisited, "akzent"),
                            (QPalette.BrightText, "sel_fg")):
            pal.setColor(rolle, QColor(p[schl]))
        for rolle in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            pal.setColor(QPalette.Disabled, rolle, QColor(p["deaktiviert"]))
        app.setPalette(pal)
    _zustand.update(darstellung=darstellung, modus=modus)
    f = farben()
    app.setStyleSheet(
        f"QLabel[rolle=hinweis] {{ color: {f['hinweis']}; }}"
        "QLabel[rolle=ueberschrift] { font-size: 12pt; font-weight: bold; }"
        "QLabel[rolle=abschnitt] { font-weight: bold; }"
        f"QLabel[rolle=verweis] {{ color: {f['akzent']}; font-weight: bold; }}"
        f"QToolTip {{ color: {f['fg']}; background: {f['kopf']}; border: 1px solid {f['rahmen']}; padding: 2px 4px; }}")
    return modus


def modus():
    return _zustand["modus"]


def dunkel():
    return _zustand["modus"] == "dunkel"


def _mischen(a, b, anteil):
    a, b = QColor(a), QColor(b)
    return QColor(round(a.red() + (b.red() - a.red()) * anteil), round(a.green() + (b.green() - a.green()) * anteil),
                  round(a.blue() + (b.blue() - a.blue()) * anteil)).name()


def farben():
    """Farben wie PALETTE; bei "system" aus der Palette, die gerade gilt."""
    if _zustand["darstellung"] in ("hell", "dunkel"):
        return dict(PALETTE[_zustand["darstellung"]])
    pal = QApplication.instance().palette()
    c = lambda rolle, gruppe=QPalette.Active: pal.color(gruppe, rolle).name()      # noqa: E731
    bg = c(QPalette.Window)
    return {"bg": bg, "fg": c(QPalette.WindowText), "feld": c(QPalette.Base), "feld_fg": c(QPalette.Text),
            "sel": c(QPalette.Highlight), "sel_fg": c(QPalette.HighlightedText), "rahmen": c(QPalette.Mid),
            "kopf": _mischen(bg, c(QPalette.WindowText), 0.05), "hinweis": c(QPalette.PlaceholderText),
            "akzent": c(QPalette.Highlight), "deaktiviert": c(QPalette.Text, QPalette.Disabled),
            "knopf": c(QPalette.Button), "knopf_aktiv": _mischen(bg, c(QPalette.Highlight), 0.15),
            "tabellenkopf": c(QPalette.Button)}


def pixmap(b64):
    p = QPixmap()
    p.loadFromData(base64.b64decode(b64))
    return p


def eingefaerbt(pm, farbe):
    """Einfarbiges Piktogramm (Alpha bleibt) in einer anderen Farbe."""
    neu = QPixmap(pm.size())
    neu.setDevicePixelRatio(pm.devicePixelRatio())
    neu.fill(Qt.transparent)
    m = QPainter(neu)
    m.drawPixmap(0, 0, pm)
    m.setCompositionMode(QPainter.CompositionMode_SourceIn)
    m.fillRect(neu.rect(), QColor(farbe))
    m.end()
    return neu


_cache = {}


def symbol(name):
    """Werkzeugleisten-Symbol (dieselben PNGs wie im Tk-Programm, Designleitfaden); leeres QIcon, wenn
    es den Namen nicht gibt."""
    d = dunkel()
    schl = ("wz", name, d)
    if schl not in _cache:
        satz = dict(kic.DUNKEL, **ksy.WZ_DUNKEL) if d else dict(kic.HELL, **ksy.WZ_HELL)
        _cache[schl] = QIcon(pixmap(satz[name])) if name in satz else QIcon()
    return _cache[schl]


def seitenleiste(kennung, aktiv=False):
    d = dunkel()
    schl = ("nav", kennung, aktiv, d)
    if schl not in _cache:
        satz = ksy.DUNKEL if d else ksy.HELL
        name = kennung + ("_aktiv" if aktiv else "")
        _cache[schl] = pixmap(satz.get(name) or satz.get(kennung) or "")
    return _cache[schl]
