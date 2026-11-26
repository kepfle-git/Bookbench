# -*- coding: utf-8 -*-
"""
cleaner_window.py - Fenster "Werbezeilen entfernen" (seit 2.1). Logik in core/cleaner.py.

Kleine Funktion ohne eigenen Bereich: Bearbeiten > Werbezeilen entfernen … (alle Bücher) oder Rechtsklick auf ein
Buch in der Bibliothek (nur dieses). Das Fenster sucht im Hilfsthread, zeigt je Buch die Fundstellen mit
Umgebung und was entfernt würde (ganzer Container oder nur der Text), alles angehakt. "Entfernen" schreibt die
Bücher sofort neu (vorher Sicherung) und liest sie neu ein. Bücher mit ungespeicherten Änderungen werden
ausgelassen: erst speichern oder verwerfen, sonst würden zwei Stände durcheinander geraten.

  CleanerFenster(app, buecher)
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QTreeWidgetItemIterator, QVBoxLayout)

from bookbench.core import cleaner
from bookbench.i18n import _, ngettext
from bookbench.ui import dialogs
from bookbench.ui import threads


class CleanerFenster(QDialog):
    def __init__(self, app, buecher):
        super().__init__(app)
        self.app = app
        self.buecher = [b for b in buecher if not b.fehler]
        self.funde = {}                     # id(buch) -> [Fund]
        self.gesperrt = set()               # id(buch) mit ungespeicherten Änderungen
        self._laeuft = False
        self._still = False
        self.setWindowTitle(_("Remove advert text"))
        self.resize(980, 600)
        lay = QVBoxLayout(self)
        kopf = QHBoxLayout()
        self.muster_text = QLabel("")
        self.muster_text.setWordWrap(True)
        self.muster_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        kopf.addWidget(self.muster_text, 1)
        k = QPushButton(_("Patterns …"))
        k.setToolTip(_("Settings > Books > Advert text"))
        k.clicked.connect(self.muster_aendern)
        kopf.addWidget(k)
        lay.addLayout(kopf)
        self.baum = QTreeWidget()
        self.baum.setHeaderLabels([_("Found"), _("Removes"), _("File")])
        self.baum.setColumnWidth(0, 560)
        self.baum.setColumnWidth(1, 190)
        self.baum.itemChanged.connect(self._haken)
        lay.addWidget(self.baum, 1)
        hinweis = QLabel(_("Whole container: the element around the text is removed too, because nothing else is in it. "
                           "Text only: the text stands in a paragraph with other content, only the text goes. A backup "
                           "is made before each book is written. KOReader may shift a bookmark in the same chapter "
                           "by a line."))
        hinweis.setProperty("rolle", "hinweis")
        hinweis.setWordWrap(True)
        lay.addWidget(hinweis)
        unten = QHBoxLayout()
        self.zusammenfassung = QLabel("")
        unten.addWidget(self.zusammenfassung, 1)
        self.k_suchen = QPushButton(_("Search again"))
        self.k_suchen.clicked.connect(self.suchen)
        unten.addWidget(self.k_suchen)
        self.ok = QPushButton("")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.entfernen)
        unten.addWidget(self.ok)
        k = QPushButton(_("Close"))
        k.clicked.connect(self.close)
        unten.addWidget(k)
        lay.addLayout(unten)
        self.suchen()

    # ================================================================ Suchen
    def _muster_zeilen(self):
        return [m for m in (self.app.e.get("cleaner_muster") or []) if m.strip()]

    def muster_aendern(self):
        self.app.einstellungen("cleaner")
        self.suchen()

    def suchen(self):
        if self._laeuft:
            return
        zeilen = self._muster_zeilen()
        self.muster_text.setText(_("Patterns: {muster}").format(muster="   ".join(zeilen) or "–"))
        self.baum.clear()
        self.funde = {}
        try:
            muster = cleaner.muster_kompilieren(zeilen)
        except ValueError as e:
            self.zusammenfassung.setText("⚠ " + _("Pattern not valid: {fehler}").format(fehler=e))
            self._zaehlen()
            return
        if not muster:
            self.zusammenfassung.setText(_("No patterns set."))
            self._zaehlen()
            return
        self.gesperrt = {id(b) for b in self.buecher if b.stand() in ("rot", "gelb")}
        self._laeuft = True
        self._zaehlen()
        buecher = list(self.buecher)

        def arbeit():
            erg = {}
            for i, b in enumerate(buecher, 1):
                if i % 10 == 1:
                    text = _("Searching … {i}/{n}").format(i=i, n=len(buecher))
                    threads.im_hauptthread(lambda t=text: self.zusammenfassung.setText(t))
                try:
                    f = cleaner.suchen(b.pfad, muster)
                except Exception:
                    f = []
                if f:
                    erg[id(b)] = f
            threads.im_hauptthread(lambda: self._gefunden(erg))
        threads.starten(arbeit)

    def _gefunden(self, erg):
        self._laeuft = False
        self.funde = erg
        self._still = True
        for b in self.buecher:
            fs = erg.get(id(b))
            if not fs:
                continue
            gesperrt = id(b) in self.gesperrt
            oben = QTreeWidgetItem(self.baum)
            oben.setText(0, b.titel + "  –  " + ngettext("{n} place", "{n} places", len(fs)).format(n=len(fs)))
            oben.setData(0, Qt.UserRole, id(b))
            f0 = oben.font(0)
            f0.setBold(True)
            oben.setFont(0, f0)
            if gesperrt:
                oben.setText(1, _("unsaved changes"))
                oben.setToolTip(0, _("This book has changes that are not saved yet. Save or discard them first, "
                                     "then search again."))
                oben.setDisabled(True)
                for f in fs:
                    f.an = False
            else:
                oben.setFlags(oben.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                oben.setCheckState(0, Qt.Checked)
            for f in fs:
                it = QTreeWidgetItem(oben)
                vor, treffer, nach = f.kontext
                it.setText(0, f"…{vor} ⟦{treffer}⟧ {nach}…")
                it.setToolTip(0, f.treffer)
                it.setText(1, _("text only") if f.art == "text" else _("whole <{tag}>").format(tag=f.art))
                it.setText(2, f.datei.rsplit("/", 1)[-1])
                it.setToolTip(2, f.datei)
                it.setData(0, Qt.UserRole, (id(b), fs.index(f)))
                if not gesperrt:
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(0, Qt.Checked)
            oben.setExpanded(len(erg) <= 20)
        self._still = False
        self._zaehlen()

    def _haken(self, it, spalte):
        if self._still or spalte != 0:
            return
        d = it.data(0, Qt.UserRole)
        if isinstance(d, tuple):
            self.funde[d[0]][d[1]].an = it.checkState(0) == Qt.Checked
        self._zaehlen()

    def _zaehlen(self):
        n = sum(1 for fs in self.funde.values() for f in fs if f.an)
        buecher = sum(1 for fs in self.funde.values() if any(f.an for f in fs))
        self.ok.setText(ngettext("Remove {n} place", "Remove {n} places", n).format(n=n))
        self.ok.setEnabled(bool(n) and not self._laeuft)
        self.k_suchen.setEnabled(not self._laeuft)
        if self._laeuft:
            return
        gesamt = sum(len(fs) for fs in self.funde.values())
        if not self.funde and self._muster_zeilen() and not self.zusammenfassung.text().startswith("⚠"):
            self.zusammenfassung.setText(ngettext("Nothing found in {n} book.", "Nothing found in {n} books.",
                                                  len(self.buecher)).format(n=len(self.buecher)))
        elif self.funde:
            text = ngettext("{n} place", "{n} places", gesamt).format(n=gesamt) + " " + ngettext(
                "in {n} book", "in {n} books", len(self.funde)).format(n=len(self.funde))
            text += ", " + ngettext("{n} book checked", "{n} books checked", buecher).format(n=buecher)
            gesperrt = sum(1 for k in self.funde if k in self.gesperrt)
            if gesperrt:
                text += ", " + ngettext("{n} skipped (unsaved changes)", "{n} skipped (unsaved changes)",
                                        gesperrt).format(n=gesperrt)
            self.zusammenfassung.setText(text + ".")

    # ================================================================ Entfernen
    def entfernen(self):
        a = self.app
        auftrag = [(b, self.funde[id(b)]) for b in self.buecher
                   if id(b) in self.funde and id(b) not in self.gesperrt and any(f.an for f in self.funde[id(b)])]
        if not auftrag or self._laeuft:
            return
        grund = a._nicht_erreichbar([b for b, __ in auftrag])
        if grund:
            dialogs.warnung(self, _("Remove advert text"), grund)
            return
        n = sum(1 for __, fs in auftrag for f in fs if f.an)
        if not dialogs.frage(self, _("Remove advert text"), ngettext(
                "Remove {n} place from {b} book? The book is written right away (a backup is made first).",
                "Remove {n} places from {b} books? The books are written right away (a backup is made first).",
                n).format(n=n, b=len(auftrag))):
            return
        self._laeuft = True
        self._zaehlen()
        ordner, anzahl = a.e["sicherungsordner"], int(a.e["sicherungen_anzahl"])

        def arbeit():
            fertig, fehler, stellen = [], [], 0
            for i, (b, fs) in enumerate(auftrag, 1):
                text = _("Removing advert text … {i}/{n}").format(i=i, n=len(auftrag))
                threads.im_hauptthread(lambda t=text: self.zusammenfassung.setText(t))
                try:
                    stellen += cleaner.anwenden(b.pfad, fs, ordner, anzahl)
                    fertig.append(b)
                except Exception as e:
                    fehler.append(f"{b.pfad.name}: {e}")
            threads.im_hauptthread(lambda: self._fertig(fertig, fehler, stellen))
        threads.starten(arbeit)

    def _fertig(self, fertig, fehler, stellen):
        self._laeuft = False
        a = self.app
        neu = [a.buch_nachladen(b) for b in fertig]
        self.buecher = [next((x for x in neu if x.pfad == b.pfad), b) for b in self.buecher]
        text = ngettext("{n} place removed", "{n} places removed", stellen).format(n=stellen) + " " + ngettext(
            "from {b} book, backups in {ordner}.", "from {b} books, backups in {ordner}.", len(fertig)).format(
            b=len(fertig), ordner=a.e["sicherungsordner"])
        a.status.set(text)
        if fehler:
            dialogs.fehler(self, _("Remove advert text"), _("Not changed:"), "\n".join(fehler))
        self.suchen()

    def angehakt(self):
        """Für Tests: [((id(buch), Index), angehakt)] aller Fundzeilen."""
        erg = []
        it = QTreeWidgetItemIterator(self.baum)
        while it.value():
            d = it.value().data(0, Qt.UserRole)
            if isinstance(d, tuple):
                erg.append((d, it.value().checkState(0) == Qt.Checked))
            it += 1
        return erg
