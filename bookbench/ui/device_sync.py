# -*- coding: utf-8 -*-
"""
device_sync.py - Abschnitt "Bücher: Rechner ↔ E-Reader" im Bereich E-Reader (seit 2.1-beta3). Logik in core/sync.py.

  AbgleichTeil      Mixin für EReaderBereich (ui/area_device.py): Zustand, Abschnitt, Vergleichen, Abgleichen
      Kopf:    verknüpfte Bibliothek, letzter Abgleich; Knöpfe Verknüpfen …/Neue Bibliothek vom E-Reader …,
               Vergleichen, n abgleichen
      Liste:   Buch | Stand | Aktion (Auswahlfeld) | Rechner | E-Reader, Haken je Zeile
      darunter: Unterschiede der gewählten Zeile (bei geändert/Konflikt: Metadaten, Kapitel, Dateien im EPUB)

Verglichen wird beim Anstecken (Ergebnis in der Statuszeile und als Marken abgleich/konflikt in der Seitenleiste
von E-Reader und Bibliothek), nach dem Speichern in der Bibliothek und auf Knopfdruck.
"""
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from bookbench.core import book_import as bi
from bookbench.core import sync
from bookbench.device import device as kg
from bookbench.i18n import N_, _, ngettext
from bookbench.ui import dialogs, threads

ZUSTAND_TEXT = {"neu_rechner": N_("new on the computer"), "neu_reader": N_("only on the e-reader"),
                "rechner_geaendert": N_("changed on the computer"), "reader_geaendert": N_("changed on the e-reader"),
                "konflikt": N_("changed on both sides"), "reader_geloescht": N_("deleted on the e-reader"),
                "rechner_geloescht": N_("deleted on the computer")}
AKTION_TEXT = {"zum_reader": N_("→ to the e-reader"), "zum_rechner": N_("← to the computer"),
               "loeschen_reader": N_("Delete on the e-reader"), "loeschen_rechner": N_("Delete on the computer"),
               "nichts": N_("Leave as it is")}
FELD_TEXT = {"titel": N_("Title"), "autoren": N_("Authors"), "autor_sort": N_("Author sort"), "reihe": N_("Series"),
             "nummer": N_("Number"), "verlag": N_("Publisher"), "sprache": N_("Language"), "isbn": N_("ISBN"),
             "datum": N_("Date"), "schlagwoerter": N_("Tags"), "klappentext": N_("Blurb"),
             "untertitel": N_("Subtitle")}


def _stand(st):
    if not st:
        return "–"
    return f"{kg.groesse_text(st[0])}, {datetime.fromtimestamp(st[1]).strftime('%d.%m.%Y %H:%M')}"


class AbgleichTeil:
    def abgleich_init(self):
        self.ab_bib = None               # verknüpfte Bibliothek (Path) für den angeschlossenen Reader
        self.ab_eintraege = []           # [sync.Eintrag]
        self.ab_stand = None             # Zeitpunkt des letzten Vergleichs
        self._ab_laeuft = False
        self._ab_melden = False          # nach dem Vergleich in der Statuszeile melden (beim Anstecken)
        self._ab_details = {}            # rel -> [(Art, Text)]
        self._ab_vorab = ""              # Meldung vor der Zusammenfassung (nach dem Abgleichen)

    # ================================================================ Abschnitt
    def abgleich_bauen(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 6)
        t = QLabel(_("Books: computer ↔ e-reader"))
        t.setProperty("rolle", "abschnitt")
        lay.addWidget(t)
        kopf = QHBoxLayout()
        self.ab_info = QLabel("")
        self.ab_info.setProperty("rolle", "hinweis")
        self.ab_info.setWordWrap(True)
        self.ab_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        kopf.addWidget(self.ab_info, 1)
        self.ab_k_verknuepfen = QPushButton(_("Link library …"))
        self.ab_k_verknuepfen.setToolTip(_("Choose the library on this computer that belongs to this e-reader"))
        self.ab_k_verknuepfen.clicked.connect(self.abgleich_verknuepfen)
        kopf.addWidget(self.ab_k_verknuepfen)
        self.ab_k_neu = QPushButton(_("New library from e-reader …"))
        self.ab_k_neu.clicked.connect(lambda: self.app.bibliothek_vom_reader())
        kopf.addWidget(self.ab_k_neu)
        self.ab_k_vergleichen = QPushButton(_("Compare"))
        self.ab_k_vergleichen.clicked.connect(lambda: self.abgleich_vergleichen())
        kopf.addWidget(self.ab_k_vergleichen)
        self.ab_k_los = QPushButton("")
        self.ab_k_los.clicked.connect(self.abgleichen)
        kopf.addWidget(self.ab_k_los)
        lay.addLayout(kopf)
        self.ab_baum = QTreeWidget()
        self.ab_baum.setRootIsDecorated(False)
        self.ab_baum.setUniformRowHeights(True)
        self.ab_baum.setHeaderLabels([_("Book"), _("State"), _("Action"), _("Computer"), _("E-reader")])
        for i, breite in enumerate((330, 170, 190, 150)):
            self.ab_baum.setColumnWidth(i, breite)
        self.ab_baum.itemChanged.connect(self._ab_haken)
        self.ab_baum.currentItemChanged.connect(lambda *a: self._ab_details_zeigen())
        lay.addWidget(self.ab_baum, 1)
        self.ab_unterschiede = QLabel("")
        self.ab_unterschiede.setWordWrap(True)
        self.ab_unterschiede.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.ab_unterschiede.setProperty("rolle", "hinweis")
        lay.addWidget(self.ab_unterschiede)
        self._ab_still = False
        return w

    def abgleich_zeigen(self):
        if self.seite is None or not hasattr(self, "ab_baum"):
            return
        verbunden = bool(self.wurzel)
        if not verbunden:
            text = _("Connect the e-reader to compare its books with a library on this computer.")
        elif self.ab_bib is None:
            text = _("No library on this computer is linked to this e-reader yet. Link one (e.g. the library "
                     "you created with New library from e-reader), or create one now.")
        else:
            zuletzt = sync.basis_lesen(self.ab_bib).get("zuletzt")
            text = _("Library: {ordner}").format(ordner=self.ab_bib)
            if zuletzt:
                text += "  ·  " + _("last synced {zeit}").format(zeit=zuletzt)
            if self._ab_laeuft:
                text += "  ·  " + _("comparing …")
            elif self.ab_stand and not self.ab_eintraege:
                text += "  ·  " + _("everything is in sync")
        self.ab_info.setText(text)
        self.ab_k_verknuepfen.setVisible(verbunden)
        self.ab_k_verknuepfen.setText(_("Link library …") if self.ab_bib is None else _("Other library …"))
        self.ab_k_neu.setVisible(verbunden and self.ab_bib is None)
        self.ab_k_vergleichen.setEnabled(verbunden and self.ab_bib is not None and not self._ab_laeuft)
        self._ab_liste()

    def _ab_liste(self):
        self._ab_still = True
        aktuell = self.ab_baum.currentItem().data(0, Qt.UserRole) if self.ab_baum.currentItem() else None
        self.ab_baum.clear()
        for i, e in enumerate(self.ab_eintraege):
            it = QTreeWidgetItem(self.ab_baum)
            it.setData(0, Qt.UserRole, i)
            it.setText(0, e.rel)
            it.setToolTip(0, e.rel)
            it.setText(1, _(ZUSTAND_TEXT[e.zustand]))
            it.setText(3, _stand(e.rechner))
            it.setText(4, _stand(e.reader))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked if e.an else Qt.Unchecked)
            box = QComboBox()
            for a in sync.AKTIONEN[e.zustand]:
                box.addItem(_(AKTION_TEXT[a]), a)
            box.setCurrentIndex(max(0, box.findData(e.aktion)))
            box.activated.connect(lambda __, e=e, box=box, it=it: self._ab_aktion(e, box.currentData(), it))
            self.ab_baum.setItemWidget(it, 2, box)
            if i == aktuell:
                self.ab_baum.setCurrentItem(it)
        self._ab_still = False
        self._ab_zaehlen()
        self._ab_details_zeigen()

    def _ab_aktion(self, e, aktion, it):
        e.aktion = aktion
        e.an = aktion != "nichts"
        self._ab_still = True
        it.setCheckState(0, Qt.Checked if e.an else Qt.Unchecked)
        self._ab_still = False
        self._ab_zaehlen()

    def _ab_haken(self, it, spalte):
        if self._ab_still or spalte != 0:
            return
        e = self.ab_eintraege[it.data(0, Qt.UserRole)]
        e.an = it.checkState(0) == Qt.Checked
        if e.an and e.aktion == "nichts":                 # Haken bei "So lassen": erste echte Aktion nehmen
            e.aktion = next((a for a in sync.AKTIONEN[e.zustand] if a != "nichts"), "nichts")
            box = self.ab_baum.itemWidget(it, 2)
            box.setCurrentIndex(max(0, box.findData(e.aktion)))
        self._ab_zaehlen()

    def _ab_zu_tun(self):
        return [e for e in self.ab_eintraege if e.an and e.aktion != "nichts"]

    def _ab_zaehlen(self):
        n = len(self._ab_zu_tun())
        self.ab_k_los.setText(ngettext("Sync {n} book", "Sync {n} books", n).format(n=n))
        self.ab_k_los.setEnabled(bool(n) and not self._ab_laeuft and bool(self.wurzel))
        self.ab_k_los.setVisible(self.ab_bib is not None)

    def _ab_details_zeigen(self):
        it = self.ab_baum.currentItem()
        if it is None:
            self.ab_unterschiede.setText(_("Select a row to see what differs.") if self.ab_eintraege else "")
            return
        e = self.ab_eintraege[it.data(0, Qt.UserRole)]
        if e.zustand not in ("konflikt", "rechner_geaendert", "reader_geaendert"):
            self.ab_unterschiede.setText(self._ab_erklaerung(e))
            return
        if e.rel in self._ab_details:
            self.ab_unterschiede.setText(self._ab_details_text(e, self._ab_details[e.rel]))
            return
        self.ab_unterschiede.setText(_("Looking for differences …"))
        bib, reader = self.ab_bib, self.wurzel

        def arbeit():
            try:
                u = sync.unterschiede(bib / e.rel, reader / e.rel)
            except Exception as ex:
                u = [("info", str(ex))]
            self._ab_details[e.rel] = u
            threads.im_hauptthread(lambda: self._ab_details_zeigen() if self.ab_baum.currentItem() is it else None)
        threads.starten(arbeit)

    def _ab_erklaerung(self, e):
        return {"neu_rechner": _("New in the library; not on the e-reader yet."),
                "neu_reader": _("On the e-reader, not in the library (e.g. copied there by hand or with Calibre)."),
                "reader_geloescht": _("Was synced before and has since been deleted on the e-reader. Delete it on "
                                      "the computer too, or put it back on the e-reader."),
                "rechner_geloescht": _("Was synced before and has since been deleted on the computer. Delete it on "
                                       "the e-reader too (its KOReader data stays), or bring it back."),
                }.get(e.zustand, "")

    def _ab_details_text(self, e, u):
        if not u:
            return _("Same metadata and chapters; only the file differs (e.g. text cleaned or packed differently).")
        zeilen, dateien = [], []
        for art, x in u:
            if art == "meta":
                feld, a, b = x
                zeilen.append(_("{feld}: computer “{a}” · e-reader “{b}”").format(
                    feld=_(FELD_TEXT[feld]) if feld in FELD_TEXT else feld, a=a or "–", b=b or "–"))
            elif art == "kapitel":
                nr, a, b = x
                if nr == "anzahl":
                    zeilen.append(_("Chapters: {a} on the computer, {b} on the e-reader").format(a=a, b=b))
                else:
                    zeilen.append(_("Chapter {nr}: computer “{a}” · e-reader “{b}”").format(nr=nr, a=a, b=b))
            elif art == "datei":
                dateien.append(x[0].rsplit("/", 1)[-1])
            else:
                zeilen.append(str(x))
        if dateien:
            zeilen.append(ngettext("{n} file in the EPUB differs: {namen}", "{n} files in the EPUB differ: {namen}",
                                   len(dateien)).format(n=len(dateien), namen=", ".join(dateien[:8])
                                                        + (" …" if len(dateien) > 8 else "")))
        kopf = _("Differences:") if e.zustand != "konflikt" else _("Changed on both sides. Differences:")
        return kopf + "\n" + "\n".join(zeilen[:14]) + ("\n…" if len(zeilen) > 14 else "")

    # ================================================================ Verknüpfen, Vergleichen
    def abgleich_reader_neu(self):
        """Reader gewählt/angesteckt/abgezogen: Verknüpfung suchen, vergleichen."""
        self.ab_eintraege, self.ab_stand, self._ab_details = [], None, {}
        self.ab_bib = sync.verknuepft(self.app.e, self.info, self.wurzel) if self.wurzel else None
        if self.wurzel and self.ab_bib is None and self.app.ordner and bi.ist_bibliothek(self.app.ordner):
            d = bi.bibliothek_lesen(self.app.ordner).get("reader") or {}      # library.json kennt den Reader schon
            if d.get("seriennummer") and d.get("seriennummer") == self.info.get("seriennummer"):
                sync.verknuepfen(self.app.e, Path(self.app.ordner), self.info, self.wurzel)
                self.ab_bib = Path(self.app.ordner)
        self.abgleich_zeigen()
        self.app._zaehler()
        if self.ab_bib is not None:
            self.abgleich_vergleichen(melden=True)

    def abgleich_verknuepfen(self):
        if not self.wurzel:
            return
        start = self.app.ordner if self.app.ordner and not kg.ist_geraet(self.app.ordner) else str(Path.home())
        ordner = dialogs.ordner(self.app, _("Library on this computer for this e-reader"), start)
        if not ordner:
            return
        self.verknuepfen_mit(Path(ordner))

    def verknuepfen_mit(self, ordner):
        try:
            Path(ordner).resolve().relative_to(Path(self.wurzel).resolve())
            dialogs.warnung(self.app, self.name(), _("Choose a folder on this computer, not on the e-reader."))
            return False
        except ValueError:
            pass
        if not bi.ist_bibliothek(ordner) and not dialogs.frage(self.app, self.name(), _(
                "{ordner} is not a Bookbench library yet. Use it as the library for this e-reader?").format(
                ordner=ordner)):
            return False
        sync.verknuepfen(self.app.e, Path(ordner), self.info, self.wurzel)
        self.ab_bib = Path(ordner)
        self.ab_eintraege, self._ab_details = [], {}
        self.abgleich_vergleichen()
        return True

    def abgleich_vergleichen(self, melden=False):
        if not self.wurzel or self.ab_bib is None or self._ab_laeuft:
            return
        self._ab_laeuft = True
        self._ab_melden = melden
        self.abgleich_zeigen()
        bib, reader = self.ab_bib, self.wurzel

        def arbeit():
            def schritt(i, n, rel):
                text = _("Comparing books with the e-reader … {i}/{n}").format(i=i, n=n)
                threads.im_hauptthread(lambda: self.app.status.set(text))
            try:
                erg = sync.vergleichen(bib, reader, schritt)
                fehler = ""
            except OSError as ex:
                erg, fehler = [], str(ex)
            threads.im_hauptthread(lambda: self._ab_verglichen(bib, reader, erg, fehler))
        threads.starten(arbeit)

    def _ab_verglichen(self, bib, reader, erg, fehler):
        self._ab_laeuft = False
        if bib != self.ab_bib or reader != self.wurzel:
            return
        self.ab_eintraege, self.ab_stand, self._ab_details = erg, time.time(), {}
        self.abgleich_zeigen()
        self.app._zaehler()
        vorab, self._ab_vorab = self._ab_vorab, ""
        if fehler:
            self.app.status.set(_("Comparing failed: {fehler}").format(fehler=fehler))
        else:
            self.app.status.set((vorab + " " if vorab else "") + self.abgleich_zusammenfassung())

    def abgleich_zusammenfassung(self):
        if not self.ab_eintraege:
            return _("Library and e-reader are in sync.")
        zahl = {}
        for e in self.ab_eintraege:
            zahl[e.zustand] = zahl.get(e.zustand, 0) + 1
        teile = []
        hin = zahl.get("neu_rechner", 0) + zahl.get("rechner_geaendert", 0)
        her = zahl.get("neu_reader", 0) + zahl.get("reader_geaendert", 0)
        weg = zahl.get("reader_geloescht", 0) + zahl.get("rechner_geloescht", 0)
        if hin:
            teile.append(ngettext("{n} to the e-reader", "{n} to the e-reader", hin).format(n=hin))
        if her:
            teile.append(ngettext("{n} to the computer", "{n} to the computer", her).format(n=her))
        if zahl.get("konflikt"):
            teile.append(ngettext("{n} changed on both sides", "{n} changed on both sides", zahl["konflikt"])
                         .format(n=zahl["konflikt"]))
        if weg:
            teile.append(ngettext("{n} deleted on one side", "{n} deleted on one side", weg).format(n=weg))
        return _("Sync with the e-reader: {teile} (E-reader area).").format(teile=", ".join(teile))

    def abgleich_marken(self):
        """[(kennung, anzahl)] für die Seitenleiste (E-Reader und Bibliothek)."""
        if not self.wurzel or self.ab_bib is None:
            return []
        konflikt = sum(1 for e in self.ab_eintraege if e.zustand == "konflikt")
        offen = sum(1 for e in self.ab_eintraege if e.zustand != "konflikt")
        return [m for m in (("konflikt", konflikt), ("abgleich", offen)) if m[1]]

    def abgleich_nach_speichern(self, pfad):
        """Die Oberfläche hat unter pfad gespeichert: liegt das in der verknüpften Bibliothek, neu vergleichen."""
        try:
            if self.ab_bib is not None and self.wurzel and Path(pfad).resolve() == self.ab_bib.resolve():
                self.abgleich_vergleichen()
        except OSError:
            pass

    # ================================================================ Abgleichen
    def abgleichen(self):
        if not self._bereit() or self.ab_bib is None:
            return
        zu_tun = self._ab_zu_tun()
        if not zu_tun:
            self.app.status.set(_("Nothing checked to sync."))
            return
        a = self.app
        offen_hier = a.ordner and Path(a.ordner).resolve() == self.ab_bib.resolve()
        if offen_hier:                                   # Bücher mit ungespeicherten Änderungen nicht überschreiben
            nach_pfad = {str(Path(b.pfad).resolve()): b for b in a.buecher}
            gesperrt = [e for e in zu_tun if e.aktion in ("zum_rechner", "loeschen_rechner")
                        and (b := nach_pfad.get(str((self.ab_bib / e.rel).resolve()))) is not None
                        and b.stand() in ("rot", "gelb")]
            if gesperrt:
                dialogs.warnung(a, self.name(), ngettext(
                    "{n} book has unsaved changes in the library and would be overwritten or deleted. Save or "
                    "discard first:", "{n} books have unsaved changes in the library and would be overwritten or "
                    "deleted. Save or discard first:", len(gesperrt)).format(n=len(gesperrt)),
                    "\n".join(e.rel for e in gesperrt))
                return
        loeschen = [e for e in zu_tun if e.aktion.startswith("loeschen")]
        text = ngettext("Sync {n} book? Files that are overwritten or deleted are backed up first.",
                        "Sync {n} books? Files that are overwritten or deleted are backed up first.",
                        len(zu_tun)).format(n=len(zu_tun))
        if loeschen:
            text += "\n\n" + ngettext("{n} of them is deleted:", "{n} of them are deleted:", len(loeschen)).format(
                n=len(loeschen)) + "\n" + "\n".join(e.rel for e in loeschen[:10]) + ("\n…" if len(loeschen) > 10 else "")
        if not dialogs.frage(a, self.name(), text, standard=not loeschen):
            return
        bib, reader = self.ab_bib, self.wurzel
        rechner_seite = any(e.aktion in ("zum_rechner", "loeschen_rechner") for e in zu_tun)
        reader_seite = any(e.aktion in ("zum_reader", "loeschen_reader") for e in zu_tun)
        ordner, anzahl = a.e["sicherungsordner"], int(a.e["sicherungen_anzahl"])

        def arbeit():
            def schritt(i, n, e):
                text = _("Syncing … {i}/{n}: {buch}").format(i=i, n=n, buch=Path(e.rel).name)
                threads.im_hauptthread(lambda: a.status.set(text))
            erledigt, fehler = sync.ausfuehren(bib, reader, zu_tun, ordner, anzahl, schritt)
            if fehler:
                details = "\n".join(f"{r}: {t}" for r, t in fehler)
                threads.im_hauptthread(lambda: dialogs.fehler(a, self.name(), _("Not synced:"), details))
            self._ab_vorab = ngettext("{n} book synced.", "{n} books synced.", len(erledigt)).format(n=len(erledigt))
            return self._ab_vorab + (" " + _("Backups in {ordner}.").format(ordner=ordner) if erledigt else "")

        def nachher():
            if reader_seite:
                self.geschrieben = True
            if rechner_seite and offen_hier and not a.offen():
                a.laden(str(bib))                     # Bibliothek neu einlesen (Zwischenspeicher: nur Geändertes)
            self.abgleich_vergleichen()
        a.hintergrund(self.name(), arbeit, nachher)
