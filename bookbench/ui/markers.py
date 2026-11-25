# -*- coding: utf-8 -*-
"""
markers.py - Marken zeichnen (Qt): Piktogramme in der Farbe ihrer Stufe, Statusbild aus Punkt und
Piktogrammen. Was die Marken bedeuten und welche ein Buch hat: core/markers.py.

  farbe(stufe)            fehler rot, pruefen orange, fehlt grau, info Akzent, offen gelb
  bild(kennung, farbe)    QPixmap des Piktogramms (ui/icons.MARKEN), eingefärbt, zwischengespeichert
  status_bild(stand, kennungen)   Punkt für den Stand (rot/gelb/grün oder Lücke) und die Piktogramme
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap

from bookbench.core.markers import ARTEN
from bookbench.ui import icons as ksy
from bookbench.ui import theme

SCHWERE = ("fehler", "pruefen", "offen", "fehlt", "info")
GROESSE = 16                      # px je Piktogramm (die PNGs sind 14 px mit Rand)
_cache = {}


def farbe(stufe):
    m = theme.modus()
    if stufe == "fehler":
        return theme.WARN[m]
    if stufe == "pruefen":
        return theme.PRUEFEN[m]
    if stufe == "offen":
        return theme.MARK[m]["gelb"]
    f = theme.farben()
    return f["akzent"] if stufe == "info" else f["hinweis"]


def farbe_von(kennung):
    return farbe(ARTEN[kennung][0]) if kennung in ARTEN else farbe("fehlt")


def schwerste(kennungen):
    stufen = [ARTEN[k][0] for k in kennungen if k in ARTEN]
    return min(stufen, key=SCHWERE.index) if stufen else None


def bild(kennung, f=None):
    f = f or farbe_von(kennung)
    schl = (kennung, f)
    if schl not in _cache:
        _cache[schl] = theme.eingefaerbt(theme.pixmap(ksy.MARKEN[kennung]), f) if kennung in ksy.MARKEN else QPixmap()
    return _cache[schl]


def status_bild(stand, kennungen):
    """Bild für Statusspalten: Punkt (stand = "rot"/"gelb"/"gruen"/None), daneben je Marke ein Piktogramm."""
    schl = ("status", stand, tuple(kennungen), theme.modus())
    if schl in _cache:
        return _cache[schl]
    pm = QPixmap(GROESSE + GROESSE * len(kennungen), GROESSE)
    pm.fill(Qt.transparent)
    m = QPainter(pm)
    if stand:
        m.drawPixmap(1, 1, bild("punkt", theme.MARK[theme.modus()][stand]))
    for i, k in enumerate(kennungen):
        if k in ksy.MARKEN:
            m.drawPixmap(GROESSE + 1 + GROESSE * i, 1, bild(k))
    m.end()
    _cache[schl] = pm
    return pm


def leeren():
    """Nach einem Wechsel der Darstellung: Farben neu."""
    _cache.clear()
