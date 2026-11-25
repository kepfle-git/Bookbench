# -*- coding: utf-8 -*-
"""
cover_view.py - Titelbilder anzeigen (Qt): klein in Kopfzeilen, groß in einem eigenen Fenster.

  bild(b, hoehe)        QPixmap des Covers in der Höhe (zwischengespeichert) oder None; das neue
                        Cover (b.cover_neu), falls es eins gibt. Qt liest JPEG und PNG selbst - Pillow
                        braucht es zum Anzeigen nicht mehr (nur noch zum Umrechnen beim Einsetzen).
  GrossFenster          Cover so groß, wie der Bildschirm erlaubt; Klick, Esc oder zweiter Klick auf
                        das kleine Cover schließt es (gross(b) schaltet um)
  gross(eltern, b)      großes Cover zeigen bzw. schließen; gross_schliessen(ausser=b)
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from bookbench.core import library as kd
from bookbench.version import PROGRAMM

_cache = {}
_fenster = {"offen": None}


def daten(b):
    return b.cover_neu if b.cover_neu is not None else kd.cover_lesen(b.pfad)


def bild(b, hoehe=None):
    if b is None:
        return None
    try:
        stempel = b.pfad.stat().st_mtime
    except OSError:
        return None
    schl = (str(b.pfad), stempel, hoehe, id(b.cover_neu) if b.cover_neu is not None else None)
    if schl not in _cache:
        roh = daten(b)
        pm = QPixmap()
        if not roh or not pm.loadFromData(roh):
            _cache[schl] = None
        else:
            _cache[schl] = pm.scaledToHeight(hoehe, Qt.SmoothTransformation) if hoehe else pm
    return _cache[schl]


class GrossFenster(QDialog):
    def __init__(self, eltern, b):
        super().__init__(eltern)
        self.buch = b
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(f"{b.name} - {PROGRAMM}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        pm = bild(b)
        flaeche = QGuiApplication.primaryScreen().availableGeometry()
        if pm is not None and (pm.height() > flaeche.height() - 80 or pm.width() > flaeche.width() - 40):
            pm = pm.scaled(flaeche.width() - 40, flaeche.height() - 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        lab = QLabel()
        if pm is not None:
            lab.setPixmap(pm)
        lab.setCursor(Qt.PointingHandCursor)
        lay.addWidget(lab)
        lab.mousePressEvent = lambda ev: self.close()

    def closeEvent(self, ev):
        if _fenster["offen"] is self:
            _fenster["offen"] = None
        super().closeEvent(ev)


def gross(eltern, b):
    offen = _fenster["offen"]
    if offen is not None:
        gleich = offen.buch is b
        offen.close()
        if gleich:
            return None
    if b is None or bild(b) is None:
        return None
    f = _fenster["offen"] = GrossFenster(eltern, b)
    f.show()
    return f


def gross_schliessen(ausser=None):
    offen = _fenster["offen"]
    if offen is not None and offen.buch is not ausser:
        offen.close()
