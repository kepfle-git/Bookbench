# -*- coding: utf-8 -*-
"""
bulk_edit.py - Fenster der Massenbearbeitung (seit 2.3-beta1). Logik in core/bulk_edit.py, Ablauf im
Bereich Metadaten (Werkzeugleiste „Mehrere Bücher ▾“ und Übernehmen mit mehreren gewählten Büchern).

  VorschauFenster(eltern, aenderungen, namen, warnungen)   exec() == Accepted → übernehmen
      aenderungen = [(buch, [(feld, alt, neu)])] aus core/bulk_edit.aenderungen, namen = {feld: Bezeichnung}
  NummerierenFenster(eltern, reihe, anzahl)                 .werte() -> (reihe, start, schritt)
  ErsetzenFenster(eltern, felder, werte_liste)              .werte() -> (feld, suche, ersatz, regex, gross)
      felder = [(feld, Bezeichnung)], werte_liste = [{feld: text}] der Bücher (für die Trefferzahl)
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout, QLabel,
                               QLineEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from bookbench.core import bulk_edit as kbe
from bookbench.i18n import _, ngettext


def _knoepfe(fenster, ok_text):
    k = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    k.button(QDialogButtonBox.Ok).setText(ok_text)
    k.accepted.connect(fenster.accept)
    k.rejected.connect(fenster.reject)
    return k


def _hinweis(text):
    lab = QLabel(text)
    lab.setProperty("rolle", "hinweis")
    lab.setWordWrap(True)
    return lab


class VorschauFenster(QDialog):
    """Was sich ändert: je Buch eine Zeile, darunter Feld | Bisher | Neu. Übernehmen = gelb, nicht gespeichert."""

    def __init__(self, eltern, aenderungen, namen, warnungen=()):
        super().__init__(eltern)
        self.setWindowTitle(_("Changes for several books"))
        self.resize(860, 520)
        lay = QVBoxLayout(self)
        felder = sum(len(z) for __, z in aenderungen)
        lay.addWidget(QLabel(ngettext("{felder} values change in {n} book:", "{felder} values change in {n} books:",
                                      len(aenderungen)).format(felder=felder, n=len(aenderungen))))
        self.baum = QTreeWidget()
        self.baum.setHeaderLabels([_("Book / field"), _("Before"), _("New")])
        self.baum.setColumnWidth(0, 300)
        self.baum.setColumnWidth(1, 250)
        for b, zeilen in aenderungen:
            oben = QTreeWidgetItem(self.baum, [b.titel])
            f = oben.font(0)
            f.setBold(True)
            oben.setFont(0, f)
            oben.setToolTip(0, b.pfad.name)
            for feld, alt, neu in zeilen:
                it = QTreeWidgetItem(oben, [namen.get(feld, feld), alt or "–", neu or "–"])
                it.setToolTip(1, alt)
                it.setToolTip(2, neu)
            oben.setExpanded(True)
        lay.addWidget(self.baum, 1)
        for w in warnungen:
            lay.addWidget(_hinweis("⚠ " + w))
        lay.addWidget(_hinweis(_("Apply puts the values into the books like the form does (shown as applied, not "
                                 "saved). Ctrl+S saves them, with a backup of each file; Discard restores a book.")))
        lay.addWidget(_knoepfe(self, _("Apply")))


class NummerierenFenster(QDialog):
    def __init__(self, eltern, reihe, anzahl):
        super().__init__(eltern)
        self.setWindowTitle(_("Number series"))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(ngettext("Numbers {n} book in the order of the list.",
                                      "Numbers {n} books in the order of the list.", anzahl).format(n=anzahl)))
        r = QGridLayout()
        r.addWidget(QLabel(_("Series:")), 0, 0)
        self.reihe = QLineEdit(reihe or "")
        self.reihe.setPlaceholderText(_("(keep each book's series)"))
        self.reihe.setMinimumWidth(280)
        r.addWidget(self.reihe, 0, 1)
        r.addWidget(QLabel(_("Start at:")), 1, 0)
        self.start = self._zahl(1)
        r.addWidget(self.start, 1, 1, Qt.AlignLeft)
        r.addWidget(QLabel(_("Step:")), 2, 0)
        self.schritt = self._zahl(1)
        self.schritt.setMinimum(0.01)
        r.addWidget(self.schritt, 2, 1, Qt.AlignLeft)
        lay.addLayout(r)
        lay.addWidget(_hinweis(_("Sort or filter the list first if the order is not right. Step 0.5 gives "
                                 "1, 1.5, 2 …")))
        lay.addWidget(_knoepfe(self, _("Preview …")))

    @staticmethod
    def _zahl(wert):
        z = QDoubleSpinBox()
        z.setRange(0, 99999)
        z.setDecimals(2)
        z.setValue(wert)
        z.setFixedWidth(100)
        return z

    def werte(self):
        return self.reihe.text().strip(), self.start.value(), self.schritt.value()


class ErsetzenFenster(QDialog):
    def __init__(self, eltern, felder, werte_liste):
        super().__init__(eltern)
        self.werte_liste = werte_liste
        self.setWindowTitle(_("Search and replace"))
        lay = QVBoxLayout(self)
        r = QGridLayout()
        r.addWidget(QLabel(_("Field:")), 0, 0)
        self.feld = QComboBox()
        for f, name in felder:
            self.feld.addItem(name, f)
        r.addWidget(self.feld, 0, 1, Qt.AlignLeft)
        r.addWidget(QLabel(_("Search:")), 1, 0)
        self.suche = QLineEdit()
        self.suche.setMinimumWidth(320)
        r.addWidget(self.suche, 1, 1)
        r.addWidget(QLabel(_("Replace with:")), 2, 0)
        self.ersatz = QLineEdit()
        r.addWidget(self.ersatz, 2, 1)
        lay.addLayout(r)
        self.regex = QCheckBox(_("Regular expression (\\1 in the replacement inserts a group)"))
        lay.addWidget(self.regex)
        self.gross = QCheckBox(_("Match case"))
        lay.addWidget(self.gross)
        self.stand = QLabel("")
        lay.addWidget(self.stand)
        self.knoepfe = _knoepfe(self, _("Preview …"))
        lay.addWidget(self.knoepfe)
        for w in (self.suche, self.ersatz):
            w.textChanged.connect(self._zaehlen)
        for w in (self.regex, self.gross):
            w.toggled.connect(self._zaehlen)
        self.feld.currentIndexChanged.connect(self._zaehlen)
        self._zaehlen()

    def werte(self):
        return (self.feld.currentData(), self.suche.text(), self.ersatz.text(), self.regex.isChecked(),
                self.gross.isChecked())

    def _zaehlen(self, *a):
        feld, suche, ersatz, regex, gross = self.werte()
        ok = self.knoepfe.button(QDialogButtonBox.Ok)
        fehler = kbe.muster_fehler(suche, regex)
        if fehler:
            self.stand.setText("⚠ " + _("Expression not valid: {fehler}").format(fehler=fehler))
            ok.setEnabled(False)
            return
        n = sum(1 for w in self.werte_liste if kbe.ersetzen(w.get(feld, ""), suche, ersatz, regex, gross)[1])
        self.stand.setText(ngettext("Found in {n} book.", "Found in {n} books.", n).format(n=n) if suche else "")
        ok.setEnabled(bool(n))
