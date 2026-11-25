# -*- coding: utf-8 -*-
"""
transfer_window.py - Fenster "Auf den E-Reader" der KOReader-Werkbank (Qt; Tk-Vorlage tk/transfer_window.py):
zeigt, was im Vorschau-Profil anders ist als auf dem angeschlossenen E-Reader (preview/transfer.py), mit
Haken je Datei bzw. Einstellung, und schreibt das Gewählte nach einer Sicherung auf den E-Reader.

  Haken      übertragen ja/nein (Klick in den Haken, Leertaste, "An/aus")
  ⚠          Konflikt: auch auf dem E-Reader seit dem Holen geändert - nicht vorausgewählt
  Nie        gewählte Einstellungen nie mehr anbieten (Einstellung rueckweg_nie)
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from bookbench.i18n import N_, _, ngettext
from bookbench.preview import transfer as ktr
from bookbench.ui import dialogs
from bookbench.ui.workbench_base import hinweis

STATUS = {"neu": N_("new"), "geaendert": N_("changed"), "entfernt": N_("removed")}


class TransferFenster(QDialog):
    def __init__(self, bereich):
        app = bereich.app
        super().__init__(app)
        self.bereich, self.app = bereich, app
        self.setWindowTitle(_("To the e-reader"))
        self.resize(900, 560)
        self.eintraege = []
        lay = QVBoxLayout(self)
        self.kopf = QLabel("")
        self.kopf.setWordWrap(True)
        lay.addWidget(self.kopf)
        self.baum = QTreeWidget()
        self.baum.setHeaderLabels([_("Item"), _("Change"), _("Profile"), _("E-reader")])
        self.baum.setSelectionMode(QAbstractItemView.ExtendedSelection)
        k = self.baum.header()
        k.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in (1, 2, 3):
            k.setSectionResizeMode(i, QHeaderView.Interactive)
            self.baum.setColumnWidth(i, 170)
        self.baum.itemChanged.connect(self._haken)
        self.baum.keyPressEvent = self._taste
        lay.addWidget(self.baum, 1)
        z = QHBoxLayout()
        for text, fn in ((_("On/off"), self.umschalten), (_("All"), lambda: self.alle(True)),
                         (_("None"), lambda: self.alle(False)), (_("Suggestion"), self.vorschlag),
                         (_("Never offer"), self.nie)):
            b = QPushButton(text)
            b.clicked.connect(lambda *a, fn=fn: fn())
            z.addWidget(b)
        z.addStretch(1)
        self.knopf = QPushButton(_("Transfer"))
        self.knopf.setDefault(True)
        self.knopf.clicked.connect(self.uebertragen)
        z.addWidget(self.knopf)
        ab = QPushButton(_("Cancel"))
        ab.clicked.connect(self.reject)
        z.addWidget(ab)
        lay.addLayout(z)
        self.hinweis = hinweis("")
        lay.addWidget(self.hinweis)
        self._still = False
        self.laden()

    def _taste(self, ev):
        if ev.key() == Qt.Key_Space:
            self.umschalten()
        else:
            QTreeWidget.keyPressEvent(self.baum, ev)

    def laden(self):
        b = self.bereich
        self.wurzel = self.app.kobo.wurzel
        self.eintraege = ktr.vergleichen(b.profil, self.wurzel, self.app.e.get("rueckweg_nie") or ())
        self.items = []
        self._still = True
        self.baum.clear()
        gruppen = {}
        for n, e in enumerate(self.eintraege):
            if e["bereich"] not in gruppen:
                g = QTreeWidgetItem([ktr.bereich_name(e["bereich"])])
                self.baum.addTopLevelItem(g)
                g.setExpanded(True)
                gruppen[e["bereich"]] = g
            status = _(STATUS[e["status"]]) + ("  ⚠ " + _("conflict") if e["konflikt"] else "")
            it = QTreeWidgetItem([e["name"], status, str(e["profil"]), str(e["geraet"])])
            it.setData(0, Qt.UserRole, n)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked if e["vorschlag"] else Qt.Unchecked)
            gruppen[e["bereich"]].addChild(it)
            self.items.append(it)
        self._still = False
        self._zaehlen()
        if not ktr.hat_basis(b.profil):
            basis = _("The profile was taken before 1.4-beta6, so Bookbench does not know what was on the e-reader "
                      "then: profile and e-reader are compared directly. Check every item; only areas Bookbench has "
                      "changed are preselected. Taking the profile again fixes this.")
        else:
            basis = _("Shown is what changed in the profile since it was taken from the e-reader. ⚠ = changed on the "
                      "e-reader too since then - not preselected.")
        if not self.eintraege:
            self.kopf.setText(_("Nothing to transfer: the profile matches the e-reader.") + "\n" + basis)
        else:
            self.kopf.setText(ngettext("{n} difference between the preview profile and the e-reader.",
                                       "{n} differences between the preview profile and the e-reader.",
                                       len(self.eintraege)).format(n=len(self.eintraege)) + "\n" + basis)
        self.hinweis.setText(_("Before writing, the KOReader settings of the e-reader are backed up (E-reader area > "
                               "backups). KOReader reads the files at its next start - eject the e-reader afterwards. "
                               "Device-specific settings (screen, Wi-Fi, frontlight, paths) are never offered."))

    def _an(self):
        return [self.eintraege[it.data(0, Qt.UserRole)] for it in self.items if it.checkState(0) == Qt.Checked]

    def _zaehlen(self):
        n = len(self._an())
        self.knopf.setText(_("Transfer ({n})").format(n=n))
        self.knopf.setEnabled(bool(n))

    def _haken(self, *a):
        if not self._still:
            self._zaehlen()

    def _gewaehlt(self):
        erg = []
        for it in self.baum.selectedItems():
            if it.data(0, Qt.UserRole) is None:
                erg += [it.child(i) for i in range(it.childCount())]
            elif it not in erg:
                erg.append(it)
        return erg

    def _setzen(self, items, an):
        self._still = True
        for it in items:
            it.setCheckState(0, Qt.Checked if an else Qt.Unchecked)
        self._still = False
        self._zaehlen()

    def umschalten(self):
        items = self._gewaehlt()
        if items:
            self._setzen(items, not all(it.checkState(0) == Qt.Checked for it in items))

    def alle(self, an):
        self._setzen(self.items, an)

    def vorschlag(self):
        self._still = True
        for it in self.items:
            it.setCheckState(0, Qt.Checked if self.eintraege[it.data(0, Qt.UserRole)]["vorschlag"] else Qt.Unchecked)
        self._still = False
        self._zaehlen()

    def nie(self):
        namen = [self.eintraege[it.data(0, Qt.UserRole)]["name"] for it in self._gewaehlt()
                 if self.eintraege[it.data(0, Qt.UserRole)]["art"] == "schluessel"]
        if not namen:
            self.app.status.set(_("\"Never offer\" works for KOReader settings (keys), not for files."))
            return
        liste = list(self.app.e.get("rueckweg_nie") or [])
        self.app.e["rueckweg_nie"] = sorted(set(liste) | set(namen))
        self.laden()

    def uebertragen(self):
        auswahl = self._an()
        if not auswahl:
            return
        wurzel = self.app.kobo.wurzel
        if not wurzel or not wurzel.exists():
            dialogs.warnung(self, _("To the e-reader"), _("No e-reader connected."))
            return
        konflikte = sum(1 for e in auswahl if e["konflikt"])
        frage = ngettext("Write {n} item to the e-reader?", "Write {n} items to the e-reader?", len(auswahl)).format(
            n=len(auswahl))
        if konflikte:
            frage += "\n\n" + ngettext("{n} of them was changed on the e-reader too; that change is lost.",
                                      "{n} of them were changed on the e-reader too; those changes are lost.",
                                      konflikte).format(n=konflikte)
        if not dialogs.frage(self, _("To the e-reader"), frage):
            return
        a, k, profil = self.app, self.app.kobo, self.bereich.profil
        ziel, info = k.sicherungsordner(), dict(k.info or {})
        anzahl = int(a.e.get("kobo_sicherungen_anzahl") or 10)

        def arbeit():
            n, sicherung = ktr.uebertragen(profil, wurzel, auswahl, ziel, info, anzahl)
            text = ngettext("{n} item written to the e-reader.", "{n} items written to the e-reader.", n).format(n=n)
            if sicherung:
                text += " " + _("Backup before: {name}.").format(name=sicherung.name)
            return text + " " + _("Eject the e-reader; KOReader reads the changes at its next start.")

        def nachher():
            k.geschrieben = True
            k.anzeigen()
            self.bereich.anzeigen()
        k.geschrieben = True
        a.hintergrund(_("To the e-reader"), arbeit, nachher=nachher)
        self.accept()
