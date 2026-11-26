# -*- coding: utf-8 -*-
"""
workbench_shelves.py - Fenster „Neues Regal“ für die Bookshelf-Seite der Werkbank (seit 2.2-beta4). Logik in
preview/plugins.py (REGAL_QUELLEN, neues_regal, sammlungen, ordner_vom_reader).

  RegalFenster   Name, Quelle (ganze Bibliothek, zuletzt gelesen, Ordner, eigene Sammlung, Stapel je Reihe …),
                 bei Ordner/Sammlung die Auswahl dazu, Ansicht. ergebnis(tabs) -> neues Regal (dict)
"""
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QGridLayout, QLabel, QLineEdit, QVBoxLayout

from bookbench.i18n import _
from bookbench.preview import plugins as kpl
from bookbench.ui.workbench_base import Wahl, hinweis


class RegalFenster(QDialog):
    def __init__(self, eltern, ordner=(), sammlungen=()):
        super().__init__(eltern)
        self.setWindowTitle(_("New shelf"))
        self.resize(520, 300)
        self._name_eigen = False
        lay = QVBoxLayout(self)
        g = QGridLayout()
        g.addWidget(QLabel(_("Source")), 0, 0)
        self.quelle = QComboBox()
        for art, text, __ in kpl.REGAL_QUELLEN:
            self.quelle.addItem(_(text), art)
        self.quelle.currentIndexChanged.connect(lambda *a: self._quelle_gewechselt())
        g.addWidget(self.quelle, 0, 1)
        self.ziel_text = QLabel("")
        g.addWidget(self.ziel_text, 1, 0)
        self.ordner = QComboBox()
        self.ordner.setEditable(True)
        self.ordner.addItems(list(ordner))
        self.ordner.setCurrentText("")
        self.ordner.lineEdit().setPlaceholderText("/mnt/onboard/…")
        self.ordner.currentTextChanged.connect(lambda *a: self._ziel_gewechselt())
        g.addWidget(self.ordner, 1, 1)
        self.sammlung = QComboBox()
        self.sammlung.setEditable(True)
        self.sammlung.addItems(list(sammlungen))
        self.sammlung.currentTextChanged.connect(lambda *a: self._ziel_gewechselt())
        g.addWidget(self.sammlung, 2, 1)
        g.addWidget(QLabel(_("Name")), 3, 0)
        self.name = QLineEdit()
        self.name.textEdited.connect(self._name_bearbeitet)
        g.addWidget(self.name, 3, 1)
        g.addWidget(QLabel(_("View")), 4, 0)
        self.ansicht = Wahl(kpl.ANSICHTEN, lambda: None)
        g.addWidget(self.ansicht, 4, 1)
        g.setColumnStretch(1, 1)
        lay.addLayout(g)
        self.ordner_hinweis = hinweis(_("Folders of the connected e-reader that hold books; type a path for any other "
                                        "folder (as on the e-reader)."))
        lay.addWidget(self.ordner_hinweis)
        lay.addWidget(hinweis(_("Sorting and filters as Bookshelf sets them for a new shelf; change them in Bookshelf "
                                "if needed.")))
        lay.addStretch(1)
        self.knoepfe = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.knoepfe.accepted.connect(self.accept)
        self.knoepfe.rejected.connect(self.reject)
        lay.addWidget(self.knoepfe)
        self._quelle_gewechselt()

    def _art(self):
        i = self.quelle.currentIndex()
        return kpl.REGAL_QUELLEN[i] if 0 <= i < len(kpl.REGAL_QUELLEN) else kpl.REGAL_QUELLEN[0]

    def quelle_waehlen(self, art):
        i = self.quelle.findData(art)
        if i >= 0:
            self.quelle.setCurrentIndex(i)

    def _quelle_gewechselt(self):
        __, __, braucht = self._art()
        self.ziel_text.setText(_("Folder") if braucht == "ordner" else _("Collection") if braucht == "sammlung" else "")
        self.ziel_text.setVisible(braucht is not None)
        self.ordner.setVisible(braucht == "ordner")
        self.ordner_hinweis.setVisible(braucht == "ordner")
        self.sammlung.setVisible(braucht == "sammlung")
        self._ziel_gewechselt()

    def _kennung(self):
        __, __, braucht = self._art()
        if braucht == "ordner":
            t = self.ordner.currentText().strip()
            return "/" if t == "/" else t.rstrip("/")
        if braucht == "sammlung":
            return self.sammlung.currentText().strip()
        return None

    def _ziel_gewechselt(self):
        if not self._name_eigen:                  # Name folgt der Quelle, bis man ihn selbst ändert (wie Bookshelf)
            art, text, braucht = self._art()
            k = self._kennung()
            self.name.setText((k.rsplit("/", 1)[-1] if braucht == "ordner" else k) if k else _(text))
        __, __, braucht = self._art()
        ok = bool(self.name.text().strip()) and (braucht is None or bool(self._kennung()))
        self.knoepfe.button(QDialogButtonBox.Ok).setEnabled(ok)

    def _name_bearbeitet(self, text):
        self._name_eigen = bool(text.strip())
        self._ziel_gewechselt()

    def ergebnis(self, tabs):
        art, __, __ = self._art()
        tab = kpl.neues_regal(tabs, self.name.text().strip(), art, self._kennung())
        if self.ansicht.wert():
            tab["view_mode"] = self.ansicht.wert()
        return tab
