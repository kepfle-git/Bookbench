# -*- coding: utf-8 -*-
"""
workbench_conditions.py - Fenster für eine Bedingung in einer Bookends-Zeile (seit 2.2-beta3). Logik in
preview/bookends_conditions.py.

  BedingungFenster   Teile (nicht, Feld, Vergleich, Wert) mit „alle“ (and) oder „eine“ (or), darunter der fertige
                     Ausdruck; „Als Text bearbeiten“ für alles, was die Teile nicht fassen (Klammern, and und or
                     gemischt). Dann- und Sonst-Text. ergebnis() -> (ausdruck, dann, sonst)
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QPushButton, QToolButton, QVBoxLayout, QWidget)

from bookbench.i18n import N_, _
from bookbench.preview import bookends_conditions as bc
from bookbench.ui.workbench_base import hinweis, mit_symbolen

VERGLEICH_TEXT = ((None, N_("has a value")), ("=", "="), ("!=", "≠"), ("<", "<"), (">", ">"), ("<=", "≤"), (">=", "≥"))
EIGENES = "\0eigen"


class _Teil(QWidget):
    def __init__(self, fenster, teil):
        super().__init__()
        self.fenster = fenster
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.nicht = QCheckBox(_("not"))
        self.feld = QComboBox()
        self.feld.setMinimumContentsLength(22)
        self.feld.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for f, __, __, beschreibung in fenster.felder:
            self.feld.addItem(f"{beschreibung}  [{f}]", f)
        self.feld.addItem(_("Other field …"), EIGENES)
        self.vergleich = QComboBox()
        for w, t in VERGLEICH_TEXT:
            self.vergleich.addItem(_(t), w)
        self.wert = QLineEdit()
        self.wert.setMinimumWidth(70)
        weg = QToolButton()
        weg.setText("✕")
        weg.setToolTip(_("Remove this part"))
        weg.clicked.connect(lambda: fenster.teil_entfernen(self))
        for w in (self.nicht, self.feld, self.vergleich, self.wert, weg):
            lay.addWidget(w)
        lay.setStretch(1, 1)
        lay.setStretch(3, 1)
        self.setzen(teil)
        self.nicht.toggled.connect(lambda *a: fenster.geaendert())
        self.feld.activated.connect(self._feld_gewaehlt)
        self.vergleich.activated.connect(lambda *a: self._vergleich_gewaehlt())
        self.wert.textEdited.connect(lambda *a: fenster.geaendert())

    def setzen(self, t):
        self.nicht.setChecked(bool(t.get("nicht")))
        f = t.get("feld") or (self.fenster.felder[0][0] if self.fenster.felder else "")
        i = self.feld.findData(f)
        if i < 0:
            self.feld.insertItem(self.feld.count() - 1, f, f)
            i = self.feld.count() - 2
        self.feld.setCurrentIndex(i)
        self.vergleich.setCurrentIndex(max(0, self.vergleich.findData(t.get("vergleich"))))
        wert = t.get("wert") or ""
        if wert.startswith('"') and wert.endswith('"') and len(wert) >= 2:
            wert = wert[1:-1]
        self.wert.setText(wert)
        self._wert_zeigen()

    def _wert_zeigen(self):
        mit = self.vergleich.currentData() is not None
        self.wert.setEnabled(mit)
        beispiel = next((b for f, __, b, __ in self.fenster.felder if f == self.feld.currentData()), None)
        self.wert.setPlaceholderText(beispiel or "")

    def _feld_gewaehlt(self, i):
        if self.feld.itemData(i) == EIGENES:
            name, ok = QInputDialog.getText(self, _("Other field"), _("Field name (for example calibre{mood}):"))
            name = (name or "").strip()
            if ok and name:
                self.feld.insertItem(self.feld.count() - 1, name, name)
                self.feld.setCurrentIndex(self.feld.count() - 2)
            else:
                self.feld.setCurrentIndex(0)
        else:                                     # Vergleich und Beispielwert des Katalogs vorschlagen
            f = next((x for x in self.fenster.felder if x[0] == self.feld.itemData(i)), None)
            if f and not self.wert.text():
                self.vergleich.setCurrentIndex(max(0, self.vergleich.findData(f[1])))
        self._wert_zeigen()
        self.fenster.geaendert()

    def _vergleich_gewaehlt(self):
        self._wert_zeigen()
        self.fenster.geaendert()

    def teil(self):
        v = self.vergleich.currentData()
        return {"nicht": self.nicht.isChecked(), "feld": self.feld.currentData() or "",
                "vergleich": v, "wert": self.wert.text().strip() if v else None}


class BedingungFenster(QDialog):
    def __init__(self, eltern, felder, ausdruck="", dann="", sonst=None, familie=None, neu=True):
        super().__init__(eltern)
        self.felder = felder
        self.setWindowTitle(_("New condition") if neu else _("Edit condition"))
        self.resize(640, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(_("Show the text if")))
        self.verkn = QComboBox()
        self.verkn.addItem(_("all of these apply (and)"), "and")
        self.verkn.addItem(_("one of these applies (or)"), "or")
        self.verkn.activated.connect(lambda *a: self.geaendert())
        lay.addWidget(self.verkn, 0, Qt.AlignLeft)
        self.teile_rahmen = QWidget()
        self.teile_lay = QVBoxLayout(self.teile_rahmen)
        self.teile_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.teile_rahmen)
        self.plus = QPushButton(_("Add part"))
        self.plus.clicked.connect(lambda: self.teil_neu({}))
        lay.addWidget(self.plus, 0, Qt.AlignLeft)
        self.teile = []
        g = QGridLayout()
        self.roh_an = QCheckBox(_("Edit as text"))
        self.roh_an.toggled.connect(self._roh_umschalten)
        g.addWidget(self.roh_an, 0, 0)
        self.roh = QLineEdit()
        self.roh.textEdited.connect(lambda *a: self._pruefen())
        g.addWidget(self.roh, 0, 1)
        g.addWidget(QLabel(_("Then")), 1, 0)
        self.dann = QLineEdit(dann)
        g.addWidget(self.dann, 1, 1)
        self.sonst_an = QCheckBox(_("Otherwise"))
        self.sonst_an.toggled.connect(lambda an: self.sonst.setEnabled(an))
        g.addWidget(self.sonst_an, 2, 0)
        self.sonst = QLineEdit(sonst or "")
        g.addWidget(self.sonst, 2, 1)
        lay.addLayout(g)
        for f in (self.roh, self.dann, self.sonst):
            mit_symbolen(f, familie)
        self.meldung = hinweis("")
        lay.addWidget(self.meldung)
        lay.addWidget(hinweis(_("Operators: = equal, ≠ not equal, < > ≤ ≥ for numbers and times (22:00). \"has a "
                                "value\" is true if the field is not empty (for example a series). Text with spaces "
                                "gets quotes. Nested conditions and tokens stay as text in Then/Otherwise.")))
        lay.addStretch(1)
        self.knoepfe = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.knoepfe.accepted.connect(self.accept)
        self.knoepfe.rejected.connect(self.reject)
        lay.addWidget(self.knoepfe)
        self.sonst_an.setChecked(sonst is not None)
        self.sonst.setEnabled(sonst is not None)
        z = bc.zerlegen(ausdruck) if ausdruck else {"verknuepfung": "and", "teile": [{}]}
        if z is None:                             # Klammern / and und or gemischt: nur als Text
            self.roh.setText(ausdruck)
            self.roh_an.setChecked(True)
            self.meldung.setText(_("This condition uses brackets or mixes and/or; edit it as text."))
        else:
            self.roh.setText(ausdruck)
            self._roh_umschalten(False)           # baut die Teile aus dem Ausdruck
        self.geaendert()

    # -- Teile
    def teil_neu(self, t, melden=True):
        w = _Teil(self, t)
        self.teile.append(w)
        self.teile_lay.addWidget(w)
        if melden:
            self.geaendert()

    def teil_entfernen(self, w):
        if len(self.teile) <= 1:
            return
        self.teile.remove(w)
        w.setParent(None)
        w.deleteLater()
        self.geaendert()

    def _zerlegt(self):
        return {"verknuepfung": self.verkn.currentData(), "teile": [t.teil() for t in self.teile]}

    def geaendert(self):
        if not self.roh_an.isChecked():
            self.roh.setText(bc.bauen(self._zerlegt()) if self.teile else "")
        self._pruefen()

    def _roh_umschalten(self, an):
        if not an:
            z = bc.zerlegen(self.roh.text()) if self.roh.text().strip() else {"verknuepfung": "and", "teile": [{}]}
            if z is None:
                self.roh_an.blockSignals(True)
                self.roh_an.setChecked(True)
                self.roh_an.blockSignals(False)
                self.meldung.setText(_("This condition uses brackets or mixes and/or; edit it as text."))
                an = True
            else:
                for w in self.teile:
                    w.setParent(None)
                    w.deleteLater()
                self.teile = []
                self.verkn.setCurrentIndex(max(0, self.verkn.findData(z["verknuepfung"])))
                for t in z["teile"]:
                    self.teil_neu(t, melden=False)
                self.meldung.setText("")
        for w in (self.verkn, self.teile_rahmen, self.plus):
            w.setVisible(not an)
        self.roh.setReadOnly(not an)
        self._pruefen()

    def _pruefen(self):
        text = self.roh.text().strip()
        ok = bool(text) and "[" not in text and "]" not in text
        if self.roh_an.isChecked() and text and not ok:
            self.meldung.setText(_("The condition must not contain [ or ]."))
        elif not self.roh_an.isChecked():
            leer = any(t.teil()["vergleich"] and not t.teil()["wert"] for t in self.teile)
            ok = ok and not leer
            self.meldung.setText(_("A comparison needs a value.") if leer else "")
        self.knoepfe.button(QDialogButtonBox.Ok).setEnabled(ok)

    def ergebnis(self):
        return (self.roh.text().strip(), self.dann.text(),
                self.sonst.text() if self.sonst_an.isChecked() else None)
