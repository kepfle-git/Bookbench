# -*- coding: utf-8 -*-
"""
duplicates_window.py - Fenster "Duplikate suchen" (seit 2.4-beta5). Logik in core/duplicates.py.

Bearbeiten > Duplikate suchen … (Bibliothek). Sucht im Hilfsthread (Prüfsummen nur für Dateien gleicher Größe),
zeigt je Gruppe die Fassungen mit Ordner, Format, Größe, Datum, Lesestand, Kapitelzustand und Cover. Nichts ist
zum Löschen vorausgewählt. "Löschen" fragt nach, sichert jede Datei, stellt Sammlungs-Einträge auf eine behaltene
Fassung derselben Gruppe um und liest die Bibliothek neu ein. Bücher mit ungespeicherten Änderungen lassen sich
nicht anhaken.

  DuplikateFenster(app)
"""
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

from bookbench.core import duplicates as kdu
from bookbench.core import reading
from bookbench.i18n import N_, _, ngettext
from bookbench.ui import dialogs, threads

GRUND_TEXT = {"uuid": N_("same Calibre ID"), "isbn": N_("same ISBN"), "titel": N_("same title and author"),
              "datei": N_("same file content")}


def _groesse(n):
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, round(n / 1024))} kB"


class DuplikateFenster(QDialog):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.gruppen = []
        self._laeuft = False
        self._still = False
        self.setWindowTitle(_("Find duplicates"))
        self.resize(1040, 600)
        lay = QVBoxLayout(self)
        kopf = QHBoxLayout()
        self.info = QLabel("")
        self.info.setWordWrap(True)
        kopf.addWidget(self.info, 1)
        self.pruef = QCheckBox(_("Also compare file contents"))
        self.pruef.setToolTip(_("Finds copies under another name too; reads every file that has the size of another "
                                "one (slower on the e-reader)"))
        self.pruef.setChecked(True)
        self.pruef.toggled.connect(lambda *a: self.suchen())
        kopf.addWidget(self.pruef)
        lay.addLayout(kopf)
        b = self.baum = QTreeWidget()
        b.setHeaderLabels([_("Book / file"), _("Format"), _("Size"), _("Changed"), _("Read status"), _("Chapters"),
                           _("Cover")])
        for i, w in enumerate((420, 70, 70, 90, 90, 140)):
            b.setColumnWidth(i, w)
        b.itemChanged.connect(self._haken)
        b.itemDoubleClicked.connect(self._doppelklick)
        lay.addWidget(b, 1)
        hinweis = QLabel(_("Nothing is checked. Check the copies you want to delete; each one is backed up first. "
                           "Collections that contain a deleted copy get a kept copy of the same group instead. "
                           "KOReader's data next to a book (.sdr: reading position, highlights) stays."))
        hinweis.setWordWrap(True)
        hinweis.setProperty("rolle", "hinweis")
        lay.addWidget(hinweis)
        z = QHBoxLayout()
        self.k_zeigen = QPushButton(_("Show in Library"))
        self.k_zeigen.clicked.connect(self.zeigen)
        z.addWidget(self.k_zeigen)
        z.addStretch(1)
        self.k_loeschen = QPushButton("")
        self.k_loeschen.clicked.connect(self.loeschen)
        z.addWidget(self.k_loeschen)
        k = QPushButton(_("Close"))
        k.clicked.connect(self.close)
        z.addWidget(k)
        lay.addLayout(z)
        self._zaehlen()
        self.suchen()

    # ================================================================ Suchen
    def suchen(self):
        if self._laeuft:
            return
        self._laeuft = True
        self.baum.clear()
        self.info.setText(_("Searching …"))
        buecher, pruef = list(self.app.buecher), self.pruef.isChecked()

        def arbeit():
            def schritt(i, n):
                threads.im_hauptthread(lambda: self.info.setText(
                    _("Comparing file contents … {i}/{n}").format(i=i, n=n)))
            erg = kdu.gruppen(buecher, pruef, schritt)
            threads.im_hauptthread(lambda: self._gefunden(erg))
        threads.starten(arbeit)

    def _gefunden(self, gruppen):
        self._laeuft = False
        self.gruppen = gruppen
        self._fuellen()

    def _fuellen(self):
        self._still = True
        b = self.baum
        b.clear()
        wurzel = Path(self.app.ordner or ".")
        for g in self.gruppen:
            oben = QTreeWidgetItem(b, [g.titel])
            f = oben.font(0)
            f.setBold(True)
            oben.setFont(0, f)
            oben.setFirstColumnSpanned(True)
            oben.setText(0, f"{g.titel}  -  " + ", ".join(_(GRUND_TEXT[x]) for x in kdu.GRUENDE if x in g.gruende))
            for x in g.buecher:
                inf = kdu.info(x)
                try:
                    rel = Path(x.pfad).relative_to(wurzel).as_posix()
                except ValueError:
                    rel = str(x.pfad)
                it = QTreeWidgetItem(oben, [rel, inf["format"], _groesse(inf["groesse"]),
                                            time.strftime("%Y-%m-%d", time.localtime(inf["zeit"])) if inf["zeit"] else "",
                                            reading.status_text(getattr(x, "lesen", None)),
                                            x.fehler or x.kapitel_zustand(),
                                            f"{x.cover_info[0]} × {x.cover_info[1]}" if x.cover_info else "-"])
                it.buch = x
                it.setToolTip(0, str(x.pfad))
                gesperrt = x.stand() in ("rot", "gelb")
                if not gesperrt:
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(0, Qt.Unchecked)
                else:
                    it.setFlags(it.flags() & ~Qt.ItemIsUserCheckable)
                    it.setDisabled(True)
                    it.setToolTip(0, _("Unsaved changes: save or discard them first."))
            oben.setExpanded(True)
        self._still = False
        n = len(self.gruppen)
        self.info.setText(ngettext("{n} group of the same book found among {b} books.",
                                   "{n} groups of the same book found among {b} books.", n).format(
            n=n, b=len(self.app.buecher)) if n else _("No duplicates among {b} books.").format(b=len(self.app.buecher)))
        self._zaehlen()

    # ================================================================ Bedienung
    def angehakt(self):
        erg = []
        for i in range(self.baum.topLevelItemCount()):
            oben = self.baum.topLevelItem(i)
            for j in range(oben.childCount()):
                it = oben.child(j)
                if it.checkState(0) == Qt.Checked:
                    erg.append(it.buch)
        return erg

    def _haken(self, it, spalte):
        if not self._still and spalte == 0:
            self._zaehlen()

    def _zaehlen(self):
        n = len(self.angehakt())
        self.k_loeschen.setText(ngettext("Delete {n} copy …", "Delete {n} copies …", n).format(n=n))
        self.k_loeschen.setEnabled(n > 0 and not self._laeuft)

    def _doppelklick(self, it, __):
        if getattr(it, "buch", None) is not None:
            self.app.bereich_zeigen("bibliothek")
            self.app.bibliothek.auswaehlen(it.buch)

    def zeigen(self):
        it = self.baum.currentItem()
        if it is not None:
            self._doppelklick(it, 0)

    def loeschen(self):
        weg = self.angehakt()
        if not weg:
            return
        ganz = [g for g in self.gruppen if all(x in weg for x in g.buecher)]
        text = ngettext("Delete {n} copy? It is backed up first.", "Delete {n} copies? Each one is backed up first.",
                        len(weg)).format(n=len(weg)) + "\n\n" + "\n".join(str(x.pfad.name) for x in weg[:12])
        if ganz:
            text += "\n\n" + ngettext("⚠ {n} book would be gone completely (all its copies are checked).",
                                      "⚠ {n} books would be gone completely (all their copies are checked).",
                                      len(ganz)).format(n=len(ganz))
        if not dialogs.frage(self, self.windowTitle(), text, standard=False):
            return
        a = self.app
        # Sammlungen: gelöschte Fassung → erste behaltene derselben Gruppe
        from bookbench.core import book_collections as kbc
        art, wurzel = kbc.ort(a.ordner)
        ersatz = {}
        if art is not None:
            def rel(x):
                try:
                    return Path(x.pfad).resolve().relative_to(Path(wurzel).resolve()).as_posix()
                except (ValueError, OSError):
                    return None
            for g in self.gruppen:
                bleibt = next((x for x in g.buecher if x not in weg), None)
                for x in g.buecher:
                    if x in weg and rel(x):
                        ersatz[rel(x)] = rel(bleibt) if bleibt is not None else None
        geloescht, fehler = kdu.loeschen(weg, a.e["sicherungsordner"], int(a.e["sicherungen_anzahl"]))
        n_s = 0
        try:
            def sichern(p):
                from bookbench.core import library as kd
                kd.sicherung_anlegen(p, a.e["sicherungsordner"], int(a.e["sicherungen_anzahl"]))
            n_s = kbc.umhaengen(a.ordner, ersatz, sichern) if ersatz else 0
        except Exception as ex:
            fehler.append((None, str(ex)))
        if fehler:
            dialogs.fehler(self, self.windowTitle(), _("Not everything could be deleted:"),
                           "\n".join(f"{x.pfad.name if x else ''}: {t}" for x, t in fehler))
        a.status.set(ngettext("{n} copy deleted (backup in {ordner}).", "{n} copies deleted (backup in {ordner}).",
                              len(geloescht)).format(n=len(geloescht), ordner=a.e["sicherungsordner"])
                     + (" " + ngettext("{n} collection entry changed.", "{n} collection entries changed.", n_s)
                        .format(n=n_s) if n_s else ""))
        if geloescht and not a.offen():
            a.laden(a.ordner)
        elif geloescht:                                  # ungespeicherte Änderungen: nicht neu einlesen, nur austragen
            a.buecher = [x for x in a.buecher if x not in geloescht]
            a.alles_neu_zeichnen()
        self.close()
