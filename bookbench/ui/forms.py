# -*- coding: utf-8 -*-
"""
forms.py - Bausteine für Formularseiten (Einstellungen, später Metadaten und Werkbank): Überschrift,
Abschnitt, Hinweis unter jedem Feld, Schalter, Feld, Zahl, Auswahl. Gleiche Abstände überall, damit
Seiten aus verschiedenen Bereichen gleich aussehen (wie die _schalter/_feld/... des Tk-Dialogs).

  Werte            {schlüssel: (lesen, schreiben)} der Eingaben; lesen(schlüssel), alle(), setzen(...)
  Formular(werte)  QWidget mit senkrechtem Aufbau; jede Eingabe trägt sich unter ihrem Schlüssel in
                   werte ein. Methoden geben das Eingabe-Widget zurück.

Einzug: Hinweise und Eingaben unter einer Beschriftung rücken um EINZUG ein (wie im Tk-Programm).
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget)

EINZUG = 22


class Werte:
    def __init__(self):
        self.felder = {}

    def eintragen(self, schl, lesen, schreiben):
        self.felder[schl] = (lesen, schreiben)

    def lesen(self, schl, standard=None):
        return self.felder[schl][0]() if schl in self.felder else standard

    def setzen(self, schl, wert):
        if schl in self.felder:
            self.felder[schl][1](wert)

    def alle(self):
        return {k: f[0]() for k, f in self.felder.items()}

    def __contains__(self, schl):
        return schl in self.felder


def label(text, rolle=None, umbruch=False):
    lab = QLabel(text)
    if rolle:
        lab.setProperty("rolle", rolle)
    if umbruch:
        lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse if rolle == "hinweis" else Qt.NoTextInteraction)
    return lab


class Formular(QWidget):
    def __init__(self, werte=None, rand=(16, 4, 12, 8), hinweis_breite=560):
        super().__init__()
        self.werte = werte if werte is not None else Werte()
        self.hinweis_breite = hinweis_breite
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(*rand)
        self.lay.setSpacing(2)
        self.lay.setAlignment(Qt.AlignTop)

    # -- Text ---------------------------------------------------------------------------------
    def _rein(self, w, einzug=0, abstand_unten=0):
        if einzug or abstand_unten:
            h = QHBoxLayout()
            h.setContentsMargins(einzug, 0, 0, abstand_unten)
            h.addWidget(w, 1 if isinstance(w, QLabel) and w.wordWrap() else 0)
            if not (isinstance(w, QLabel) and w.wordWrap()):
                h.addStretch(1)
            self.lay.addLayout(h)
        else:
            self.lay.addWidget(w)
        return w

    def ueberschrift(self, text, oben=0):
        if oben:
            self.lay.addSpacing(oben)
        w = self._rein(label(text, "ueberschrift"))
        self.lay.addSpacing(6)
        return w

    def abschnitt(self, text):
        self.lay.addSpacing(6)
        return self._rein(label(text, "abschnitt"))

    def text(self, text, einzug=0):
        return self._rein(label(text, umbruch=True), einzug)

    def hinweis(self, text, einzug=EINZUG):
        lab = label(text, "hinweis", umbruch=True)
        lab.setMaximumWidth(self.hinweis_breite)
        return self._rein(lab, einzug, abstand_unten=8)

    def zeile(self, einzug=EINZUG):
        """Leere Zeile (QHBoxLayout) für eigene Widgets, linksbündig."""
        h = QHBoxLayout()
        h.setContentsMargins(einzug, 0, 0, 0)
        h.setSpacing(6)
        self.lay.addLayout(h)
        return h

    def widget(self, w, einzug=EINZUG):
        h = QHBoxLayout()
        h.setContentsMargins(einzug, 0, 0, 0)
        h.addWidget(w, 1)
        self.lay.addLayout(h)
        return w

    def dehnen(self):
        self.lay.addStretch(1)

    # -- Eingaben -------------------------------------------------------------------------------
    def schalter(self, schl, text, hinweis=None, wert=False):
        cb = QCheckBox(text)
        cb.setChecked(bool(wert))
        self.werte.eintragen(schl, cb.isChecked, lambda w: cb.setChecked(bool(w)))
        self._rein(cb)
        if hinweis:
            self.hinweis(hinweis)
        return cb

    def feld(self, schl, text, hinweis=None, wert="", breite=40, verdeckt=False, knopf=None):
        if text:
            self._rein(label(text))
        h = self.zeile()
        f = QLineEdit(str(wert or ""))
        f.setMinimumWidth(breite * 8)
        if verdeckt:
            f.setEchoMode(QLineEdit.Password)
        h.addWidget(f, 1 if knopf else 0)
        if knopf:
            k = QPushButton(knopf[0])
            k.clicked.connect(knopf[1])
            h.addWidget(k)
        else:
            h.addStretch(1)
        self.werte.eintragen(schl, lambda: f.text().strip(), lambda w: f.setText(str(w or "")))
        if hinweis:
            self.hinweis(hinweis)
        return f

    def zahl(self, schl, text, hinweis=None, wert=0, von=0, bis=100, schritt=1, nachkomma=None):
        h = self.zeile(0)
        h.addWidget(label(text))
        if nachkomma is not None or isinstance(schritt, float):
            sp = QDoubleSpinBox()
            sp.setDecimals(nachkomma if nachkomma is not None else 2)
            sp.setRange(float(von), float(bis))
            sp.setSingleStep(float(schritt))
            sp.setValue(float(wert or 0))
            self.werte.eintragen(schl, sp.value, lambda w: sp.setValue(float(w or 0)))
        else:
            sp = QSpinBox()
            sp.setRange(int(von), int(bis))
            sp.setSingleStep(int(schritt))
            sp.setValue(int(wert or 0))
            self.werte.eintragen(schl, sp.value, lambda w: sp.setValue(int(w or 0)))
        sp.setMinimumWidth(90)
        h.addWidget(sp)
        h.addStretch(1)
        if hinweis:
            self.hinweis(hinweis)
        return sp

    def auswahl(self, schl, werte, hinweis=None, wert=None, einzug=0):
        """Radioknöpfe untereinander: werte = [(wert, text)]."""
        gruppe = QButtonGroup(self)
        knoepfe = {}
        for w, text in werte:
            rb = QRadioButton(text)
            gruppe.addButton(rb)
            knoepfe[w] = rb
            self._rein(rb, einzug)
        if wert in knoepfe:
            knoepfe[wert].setChecked(True)
        elif knoepfe:
            next(iter(knoepfe.values())).setChecked(True)

        def lesen():
            return next((w for w, rb in knoepfe.items() if rb.isChecked()), wert)

        def schreiben(neu):
            if neu in knoepfe:
                knoepfe[neu].setChecked(True)
        self.werte.eintragen(schl, lesen, schreiben)
        if hinweis:
            self.hinweis(hinweis)
        gruppe.knoepfe = knoepfe
        return gruppe

    def knopf(self, text, fn, zeile=None):
        k = QPushButton(text)
        k.clicked.connect(fn)
        if zeile is None:
            zeile = self.zeile()
            zeile.addWidget(k)
            zeile.addStretch(1)
        else:
            zeile.addWidget(k)
        return k
