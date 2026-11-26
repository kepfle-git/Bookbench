# -*- coding: utf-8 -*-
"""
workbench_colors.py - Bausteine für Farben in der Werkbank (seit 2.2-beta2), vor allem für Bookends.

  FarbFeld        Knopf mit Farbfeld; Klick öffnet ein Menü: Farbe wählen …, Vorgabe, ggf. Durchsichtig.
                  Wert in Bookends'/Bookshelfs Speicherform ({hex}/{grey}), None = Vorgabe, False = durchsichtig
  BalkenFarben    „Eigene Farben und Striche“ eines Balkens (colors bzw. line_bar_colors[i]): Haken, darunter
                  die Farben, Striche umkehren, Strichhöhe/-breite, Rahmendicke (nur sichtbar, wenn an)
  Markierungen    Markierung oben/unten eines Balkens (markers bzw. line_bar_markers[i]): Art, darunter Stil,
                  Größe, Versatz, Farbe (nur bei einer Art)

Auf Geräten ohne Farbbildschirm (grau() liefert True) wird statt einer Farbe ein Grauton in % Schwarz gewählt, wie
in Bookends' eigenem Menü, und vorhandene Farben erscheinen so grau, wie der Reader sie zeigt (Rec. 601, wie Bookends).

Die Teile kennen die Vorlage nicht: holen() liefert den aktuellen Wert, setzen(wert) schreibt ihn in den
Entwurf (die Seite plant danach das Bild). fuellen() zeigt holen() an.
"""
import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QGridLayout, QInputDialog, QLabel, QMenu, QPushButton,
                               QVBoxLayout, QWidget)

from bookbench.i18n import _
from bookbench.preview import plugins as kpl
from bookbench.ui.workbench_base import Wahl, hinweis, zahl_oder_leer, zahlfeld


def grau_hex(h):
    """#RRGGBB -> Grauton, wie ihn ein Schwarzweiß-Bildschirm zeigt (Rec. 601, wie Bookends' parseColorValue)."""
    h = h.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    l = int(0.299 * r + 0.587 * g + 0.114 * b + 0.5)
    return f"#{l:02X}{l:02X}{l:02X}"


def grau_waehlen(eltern, alt_hex=None):
    """Grauton als % Schwarz abfragen (0 = weiß, 100 = schwarz); #RRGGBB oder None."""
    alt = grau_hex(alt_hex) if alt_hex else "#404040"
    pct = round((255 - int(alt[1:3], 16)) * 100 / 255)
    wert, ok = QInputDialog.getInt(eltern, _("Grey"), _("% black (0 = white, 100 = black). The e-reader shows greys "
                                                         "only."), pct, 0, 100, 5)
    if not ok:
        return None
    g = 255 - round(wert * 255 / 100)
    return f"#{g:02X}{g:02X}{g:02X}"


class FarbFeld(QPushButton):
    def __init__(self, befehl, durchsichtig=False, vorgabe_text=None, grau=None):
        super().__init__("")
        self._grau = grau or (lambda: False)
        self._wert = None
        self._befehl = befehl
        self._durchsichtig = durchsichtig
        self._vorgabe_text = vorgabe_text
        self.setFixedSize(64, 22)
        self.clicked.connect(self._menue)

    def wert(self):
        return copy.deepcopy(self._wert)

    def setzen(self, w):
        self._wert = copy.deepcopy(w)
        h = kpl.farbe_hex(w) if w is not False else None
        if w is False:
            self.setText("⌀")
            self.setStyleSheet("")
            self.setToolTip(_("transparent"))
        elif h:
            zeigen = grau_hex(h) if self._grau() else h
            self.setText("")
            self.setStyleSheet(f"QPushButton {{ background: {zeigen}; border: 1px solid #888; }}")
            self.setToolTip(h if zeigen == h else _("{farbe}, on this e-reader {grau}").format(farbe=h, grau=zeigen))
        else:
            self.setText("-")
            self.setStyleSheet("")
            self.setToolTip(_("Default") + (f" ({self._vorgabe_text})" if self._vorgabe_text else ""))

    def _menue(self):
        m = QMenu(self)
        m.addAction(_("Choose grey …") if self._grau() else _("Choose colour …"), self.waehlen)
        m.addAction(_("Default") + (f" ({self._vorgabe_text})" if self._vorgabe_text else ""),
                    lambda: self._neu(None))
        if self._durchsichtig:
            m.addAction(_("Transparent"), lambda: self._neu(False))
        m.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def waehlen(self):
        alt = kpl.farbe_hex(self._wert) if self._wert is not False else None
        if self._grau():
            h = grau_waehlen(self.window(), alt)
            if h:
                self._neu(kpl.farbe_wert(h))
            return
        erg = QColorDialog.getColor(QColor(alt or "#808080"), self.window(), _("Colour"))
        if erg.isValid():
            self._neu(kpl.farbe_wert(erg.name()))

    def _neu(self, w):
        self.setzen(w)
        self._befehl()


class BalkenFarben(QWidget):
    """colors-Tabelle eines Balkens; None = Bookends' Farben je Stil."""

    def __init__(self, holen, setzen, grau=None):
        super().__init__()
        self.holen, self.setzen_fn = holen, setzen
        self._laden = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.an = QCheckBox(_("Own colours and ticks"))
        self.an.toggled.connect(self._an_geaendert)
        lay.addWidget(self.an)
        self.rahmen = QWidget()
        g = QGridLayout(self.rahmen)
        g.setContentsMargins(16, 0, 0, 0)
        self.farben, self.zahlen = {}, {}
        r = 0
        for feld, text in kpl.BALKEN_FARBEN:
            g.addWidget(QLabel(_(text)), r, 0)
            self.farben[feld] = FarbFeld(self._uebernehmen, durchsichtig=True, vorgabe_text=_("per style"), grau=grau)
            g.addWidget(self.farben[feld], r, 1, Qt.AlignLeft)
            r += 1
        self.umkehren = QCheckBox(_("Invert the tick colour on the read part"))
        self.umkehren.toggled.connect(lambda *a: self._uebernehmen())
        g.addWidget(self.umkehren, r, 0, 1, 3)
        r += 1
        for feld, text, vorgabe in kpl.BALKEN_FARBEN_ZAHLEN:
            g.addWidget(QLabel(_(text)), r, 0)
            self.zahlen[feld] = zahlfeld(self._uebernehmen)
            g.addWidget(self.zahlen[feld], r, 1, Qt.AlignLeft)
            g.addWidget(hinweis(_("empty = {wert}").format(wert=vorgabe)), r, 2)
            r += 1
        g.setColumnStretch(2, 1)
        lay.addWidget(self.rahmen)

    def fuellen(self, aktiv=True):
        self._laden = True
        try:
            c = self.holen()
            self.an.setChecked(c is not None)
            self.an.setEnabled(aktiv)
            self.rahmen.setVisible(c is not None)
            c = c or {}
            for feld, f in self.farben.items():
                f.setzen(c.get(feld))
            self.umkehren.setChecked(c.get("invert_read_ticks") is not False)
            for feld, f in self.zahlen.items():
                w = c.get(feld)
                f.setText("" if w is None else str(w))
        finally:
            self._laden = False

    def _an_geaendert(self, an):
        if self._laden:
            return
        self.setzen_fn({} if an else None)
        self.fuellen()

    def _uebernehmen(self):
        if self._laden or not self.an.isChecked():
            return
        c = dict(self.holen() or {})
        for feld, f in self.farben.items():
            w = f.wert()
            if w is None:
                c.pop(feld, None)
            else:
                c[feld] = w
        if self.umkehren.isChecked():
            c.pop("invert_read_ticks", None)
        else:
            c["invert_read_ticks"] = False
        try:
            for feld, f in self.zahlen.items():
                w = zahl_oder_leer(f.text())
                vorgabe = next(v for k, __, v in kpl.BALKEN_FARBEN_ZAHLEN if k == feld)
                if w is None or w == vorgabe and feld == "tick_height_pct":
                    c.pop(feld, None)
                else:
                    c[feld] = int(w)
        except ValueError:
            return
        self.setzen_fn(c)


class Markierungen(QWidget):
    """markers-Tabelle eines Balkens: {top: {type, style, size, offset, color}, bottom: …}; fehlt = aus."""

    def __init__(self, holen, setzen, grau=None):
        super().__init__()
        self.holen, self.setzen_fn = holen, setzen
        self._laden = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.teile = {}
        for platz, text in kpl.MARKEN_PLAETZE:
            g = QGridLayout()
            art = Wahl(kpl.MARKEN_ARTEN, lambda p=platz: self._uebernehmen(p))
            g.addWidget(QLabel(_(text)), 0, 0)
            g.addWidget(art, 0, 1, 1, 3, Qt.AlignLeft)
            unter = QWidget()
            ul = QGridLayout(unter)
            ul.setContentsMargins(16, 0, 0, 0)
            stil = Wahl(kpl.MARKEN_STILE, lambda p=platz: self._uebernehmen(p))
            groesse = zahlfeld(lambda p=platz: self._uebernehmen(p))
            versatz = zahlfeld(lambda p=platz: self._uebernehmen(p), negativ=True)
            farbe = FarbFeld(lambda p=platz: self._uebernehmen(p), vorgabe_text=_("black"), grau=grau)
            ul.addWidget(QLabel(_("Style")), 0, 0)
            ul.addWidget(stil, 0, 1, Qt.AlignLeft)
            ul.addWidget(QLabel(_("Colour")), 0, 2)
            ul.addWidget(farbe, 0, 3, Qt.AlignLeft)
            ul.addWidget(QLabel(_("Size (%)")), 1, 0)
            ul.addWidget(groesse, 1, 1, Qt.AlignLeft)
            ul.addWidget(QLabel(_("Offset (px)")), 1, 2)
            ul.addWidget(versatz, 1, 3, Qt.AlignLeft)
            ul.setColumnStretch(4, 1)
            g.addWidget(unter, 1, 0, 1, 4)
            g.setColumnStretch(3, 1)
            lay.addLayout(g)
            self.teile[platz] = {"art": art, "stil": stil, "groesse": groesse, "versatz": versatz, "farbe": farbe,
                                 "unter": unter}

    def fuellen(self, aktiv=True):
        self._laden = True
        try:
            m = self.holen() or {}
            for platz, t in self.teile.items():
                s = m.get(platz) or {}
                typ = s.get("type") or "off"
                t["art"].setzen(typ, aktiv=aktiv)
                t["unter"].setVisible(typ != "off")
                t["stil"].setzen("solid" if s.get("style") == "solid" else "chevron")
                t["groesse"].setText(str(s.get("size", 50)))
                t["versatz"].setText(str(s.get("offset", 0)))
                t["farbe"].setzen(s.get("color"))
        finally:
            self._laden = False

    def _uebernehmen(self, platz):
        if self._laden:
            return
        m = copy.deepcopy(self.holen() or {})
        t = self.teile[platz]
        typ = t["art"].wert()
        if typ == "off":
            m.pop(platz, None)
        else:
            s = m.get(platz) or {"size": 50, "offset": 0}
            s["type"] = typ
            if t["stil"].wert() == "solid":
                s["style"] = "solid"
            else:
                s.pop("style", None)
            try:
                g = zahl_oder_leer(t["groesse"].text())
                v = zahl_oder_leer(t["versatz"].text())
            except ValueError:
                return
            s["size"] = int(g) if g is not None else 50
            s["offset"] = int(v) if v is not None else 0
            f = t["farbe"].wert()
            if f is None:
                s.pop("color", None)
            else:
                s["color"] = f
            m[platz] = s
        self.setzen_fn(m or None)
        t["unter"].setVisible(typ != "off")
