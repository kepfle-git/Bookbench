# -*- coding: utf-8 -*-
"""
import_window.py - Fenster "Bücher hinzufügen" (seit 2.1). Logik in core/book_import.py.

  ImportFenster(app)       nicht modal; .hinzufuegen(pfade) nimmt weitere Dateien/Ordner (auch per Ziehen)
      oben:   Ziel (geöffnete Bibliothek), Ordnerschema mit "Ändern …" (Einstellungen > Bibliothek)
      Liste:  Aktion (Auswahlfeld) | Titel | Autor | Reihe | Nr. | Ziel bzw. Duplikat
      rechts: Metadaten des gewählten Buchs prüfen/ändern (Titel, Autoren, Sortiername, Reihe, Nummer, ISBN);
              das Ziel nach Schema rechnet sofort mit
      unten:  "n Bücher hinzufügen" - kopiert im Hilfsthread, danach liest die Bibliothek neu ein
              (dank Einlese-Zwischenspeicher nur die neuen Bücher)
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from bookbench.core import book_import as bi
from bookbench.core import folder_scheme as fs
from bookbench.device import device as kg
from bookbench.i18n import N_, _, ngettext
from bookbench.ui import dialogs
from bookbench.ui import threads

AKTION_TEXT = {"neu": N_("Add"), "ueberspringen": N_("Skip"), "ersetzen": N_("Replace existing"),
               "beide": N_("Keep both")}
GRUND_TEXT = {"uuid": N_("same Calibre ID"), "isbn": N_("same ISBN"), "titel": N_("same title and author"),
              "liste": N_("twice in this list"), "selbst": N_("already in the library")}
FELDER = (("titel", N_("Title:")), ("autoren", N_("Authors:")), ("autor_sort", N_("Author sort:")),
          ("reihe", N_("Series:")), ("nummer", N_("Number:")), ("isbn", N_("ISBN:")))
SPALTEN = (N_("Action"), N_("Title"), N_("Author"), N_("Series"), N_("No."), N_("Target"))


def schema_fuer(app):
    """(Vorlage, Herkunftstext) für die geöffnete Bibliothek: aus library.json, sonst aus den vorhandenen Büchern
    erkannt (wenn mindestens die Hälfte passt), sonst die Vorgabe aus den Einstellungen."""
    gespeichert = bi.bibliothek_lesen(app.ordner).get("ordnerschema") if app.ordner else ""
    if gespeichert:
        return gespeichert, _("saved for this library")
    vorgabe = app.e.get("ordnerschema") or fs.STANDARD
    if app.buecher:
        v, n, gesamt = fs.erkennen(app.buecher, app.ordner)
        if gesamt and n * 2 >= gesamt:
            return v, _("detected: {n} of {gesamt} books are stored like this").format(n=n, gesamt=gesamt)
    return vorgabe, _("default from the settings")


class ImportFenster(QDialog):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.setWindowTitle(_("Add books"))
        self.resize(1120, 640)
        self.setAcceptDrops(True)
        self.eintraege = []
        self.zeilen = {}                       # id(eintrag) -> QTreeWidgetItem
        self._laeuft = False
        self.vorlage, self.herkunft = schema_fuer(app)

        lay = QVBoxLayout(self)
        self.ziel_text = QLabel("")
        self.ziel_text.setWordWrap(True)
        lay.addWidget(self.ziel_text)
        zs = QHBoxLayout()
        self.schema_text = QLabel("")
        self.schema_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        zs.addWidget(self.schema_text, 1)
        k = QPushButton(_("Change …"))
        k.setToolTip(_("Settings > Books > Library and import"))
        k.clicked.connect(self.schema_aendern)
        zs.addWidget(k)
        lay.addLayout(zs)
        self.geraet_hinweis = QLabel("")
        self.geraet_hinweis.setProperty("rolle", "hinweis")
        self.geraet_hinweis.setWordWrap(True)
        lay.addWidget(self.geraet_hinweis)

        teiler = QSplitter(Qt.Horizontal)
        links = QWidget()
        ll = QVBoxLayout(links)
        ll.setContentsMargins(0, 0, 0, 0)
        self.tabelle = QTreeWidget()
        self.tabelle.setHeaderLabels([_(s) for s in SPALTEN])
        self.tabelle.setRootIsDecorated(False)
        self.tabelle.setUniformRowHeights(True)
        self.tabelle.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for i, w in enumerate((140, 190, 130, 130, 40, 300)):
            self.tabelle.setColumnWidth(i, w)
        self.tabelle.itemSelectionChanged.connect(self.auswahl_zeigen)
        ll.addWidget(self.tabelle, 1)
        self.leer = QLabel(_("Drag EPUB files or folders here, or use the buttons below."))
        self.leer.setProperty("rolle", "hinweis")
        self.leer.setAlignment(Qt.AlignCenter)
        ll.addWidget(self.leer)
        teiler.addWidget(links)

        rechts = QWidget()
        rl = QVBoxLayout(rechts)
        rl.setContentsMargins(8, 0, 0, 0)
        t = QLabel(_("Check metadata"))
        t.setProperty("rolle", "abschnitt")
        rl.addWidget(t)
        form = QFormLayout()
        self.felder = {}
        for schl, text in FELDER:
            f = QLineEdit()
            f.textEdited.connect(lambda __, s=schl: self.feld_geaendert(s))
            form.addRow(_(text), f)
            self.felder[schl] = f
        rl.addLayout(form)
        self.dup_text = QLabel("")
        self.dup_text.setWordWrap(True)
        rl.addWidget(self.dup_text)
        self.pfad_text = QLabel("")
        self.pfad_text.setWordWrap(True)
        self.pfad_text.setProperty("rolle", "hinweis")
        self.pfad_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rl.addWidget(self.pfad_text)
        hinweis = QLabel(_("Changes here are written into the copy in the library; the original file stays "
                           "untouched. Everything else can be edited afterwards in the Metadata area."))
        hinweis.setProperty("rolle", "hinweis")
        hinweis.setWordWrap(True)
        rl.addWidget(hinweis)
        rl.addStretch(1)
        teiler.addWidget(rechts)
        teiler.setStretchFactor(0, 3)
        teiler.setStretchFactor(1, 1)
        teiler.setSizes([800, 320])
        lay.addWidget(teiler, 1)

        self.zusammenfassung = QLabel("")
        self.zusammenfassung.setProperty("rolle", "hinweis")
        lay.addWidget(self.zusammenfassung)
        unten = QHBoxLayout()
        for text, fn in ((_("Add files …"), self.dateien_waehlen), (_("Add folder …"), self.ordner_waehlen),
                         (_("Remove from list"), self.entfernen)):
            k = QPushButton(text)
            k.clicked.connect(fn)
            unten.addWidget(k)
        self.aktion_alle = QComboBox()
        self.aktion_alle.addItem(_("Set action for selected …"), "")
        for k_, t_ in AKTION_TEXT.items():
            self.aktion_alle.addItem(_(t_), k_)
        self.aktion_alle.activated.connect(self._aktion_fuer_auswahl)
        unten.addWidget(self.aktion_alle)
        unten.addStretch(1)
        self.ok = QPushButton("")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.ausfuehren)
        unten.addWidget(self.ok)
        k = QPushButton(_("Close"))
        k.clicked.connect(self.close)
        unten.addWidget(k)
        lay.addLayout(unten)
        self.kopf_zeigen()
        self.zaehlen()
        self.auswahl_zeigen()

    # ================================================================ Kopf
    def kopf_zeigen(self):
        a = self.app
        self.ziel_text.setText(_("Into the library: <b>{ordner}</b>").format(ordner=a.ordner or "–"))
        self.schema_text.setText(_("Folder scheme: {vorlage}  ({herkunft})").format(vorlage=self.vorlage,
                                                                                   herkunft=self.herkunft))
        auf_geraet = bool(a.ordner) and kg.ist_geraet(a.ordner)
        self.geraet_hinweis.setText(_(
            "The open library is the e-reader itself: books are copied straight onto it. To keep the main copy on "
            "this computer, create a library there first (File > New library from e-reader …).") if auf_geraet else "")
        self.geraet_hinweis.setVisible(auf_geraet)

    def schema_aendern(self):
        self.app.einstellungen("bibliothek")
        self.vorlage, self.herkunft = schema_fuer(self.app)
        self.kopf_zeigen()
        for e in self.eintraege:
            bi.ziel_berechnen(e, self.vorlage)
            self._zeile(e)
        self.auswahl_zeigen()

    # ================================================================ Dateien
    def dateien_waehlen(self):
        from PySide6.QtWidgets import QFileDialog
        start = self.app.e.get("import_quelle") or str(Path.home())
        dateien, __ = QFileDialog.getOpenFileNames(self, _("Add books"), start, _("E-books") + " (*.epub *.kepub)")
        if dateien:
            self.app.e["import_quelle"] = str(Path(dateien[0]).parent)
            self.hinzufuegen(dateien)

    def ordner_waehlen(self):
        o = dialogs.ordner(self, _("Add books from folder"), self.app.e.get("import_quelle") or str(Path.home()))
        if o:
            self.app.e["import_quelle"] = o
            self.hinzufuegen([o])

    def hinzufuegen(self, pfade):
        """Dateien/Ordner einlesen (Hilfsthread) und an die Liste hängen."""
        if self._laeuft:
            return
        self._laeuft = True
        self.zusammenfassung.setText(_("Reading …"))
        schon = {str(Path(e.quelle).resolve()) for e in self.eintraege}
        vorhandene = [b for b in self.app.buecher if not b.fehler]
        wurzel, vorlage = self.app.ordner, self.vorlage
        bisher = [e for e in self.eintraege]

        def arbeit():
            dateien = [d for d in bi.dateien_sammeln(pfade) if str(Path(d).resolve()) not in schon]
            neu = bi.planen(dateien, vorhandene, wurzel, vorlage)
            for e in neu:                            # Duplikate gegenüber dem, was schon in der Liste steht
                if not e.duplikat and not e.buch.fehler:
                    w, grund = bi.duplikat(e.buch, [x.buch for x in bisher if not x.buch.fehler])
                    if w is not None:
                        e.duplikat, e.grund, e.aktion = w, "liste", "ueberspringen"
            threads.im_hauptthread(lambda: self._dazu(neu))
        threads.starten(arbeit)

    def _dazu(self, neu):
        self._laeuft = False
        self.eintraege += neu
        for e in neu:
            self._zeile(e)
        if neu and not self.tabelle.selectedItems():
            self.zeilen[id(neu[0])].setSelected(True)
        self.zaehlen()
        if not neu:
            self.zusammenfassung.setText(_("No new EPUB or KEPUB files found."))

    def entfernen(self):
        weg = {id(e) for e in self._gewaehlt()}
        for e in [e for e in self.eintraege if id(e) in weg]:
            it = self.zeilen.pop(id(e))
            self.tabelle.takeTopLevelItem(self.tabelle.indexOfTopLevelItem(it))
        self.eintraege = [e for e in self.eintraege if id(e) not in weg]
        self.zaehlen()

    # ================================================================ Ziehen
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        pfade = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        if pfade:
            self.hinzufuegen(pfade)
            ev.acceptProposedAction()

    # ================================================================ Liste
    def _aktionen(self, e):
        if e.buch.fehler:
            return ["ueberspringen"]
        if e.grund == "selbst":
            return ["ueberspringen"]
        if e.duplikat is None:
            return ["neu", "ueberspringen"]
        if e.grund == "liste":
            return ["ueberspringen", "beide"]
        return ["ueberspringen", "ersetzen", "beide"]

    def _zeile(self, e):
        it = self.zeilen.get(id(e))
        if it is None:
            it = QTreeWidgetItem(self.tabelle)
            it.setData(0, Qt.UserRole, id(e))
            self.zeilen[id(e)] = it
            box = QComboBox()
            for a in self._aktionen(e):
                box.addItem(_(AKTION_TEXT[a]), a)
            box.setCurrentIndex(max(0, box.findData(e.aktion)))
            box.activated.connect(lambda __, e=e, box=box: self._aktion_gesetzt(e, box.currentData()))
            box.setEnabled(box.count() > 1)
            self.tabelle.setItemWidget(it, 0, box)
        w = e.werte()
        it.setText(1, w.get("titel") or e.quelle.name)
        it.setText(2, w.get("autoren", ""))
        it.setText(3, w.get("reihe", ""))
        it.setText(4, w.get("nummer", "") if w.get("reihe") else "")
        it.setText(5, self._ziel_text(e))
        it.setToolTip(5, it.text(5))
        it.setToolTip(1, str(e.quelle))

    def _ziel_text(self, e):
        if e.buch.fehler:
            return "⚠ " + _("not readable ({fehler})").format(fehler=e.buch.fehler)
        dup = ""
        if e.duplikat is not None:
            dup = "⧉ " + _(GRUND_TEXT.get(e.grund, "")) + ": " + self._dup_name(e)
        if e.aktion == "ueberspringen":
            return dup or "–"
        if e.aktion == "ersetzen":
            return "↻ " + self._dup_name(e)
        return "→ " + e.ziel + ("   (" + dup + ")" if dup else "")

    def _dup_name(self, e):
        d = e.duplikat
        try:
            return Path(d.pfad).relative_to(self.app.ordner).as_posix()
        except (ValueError, TypeError):
            return str(getattr(d, "pfad", ""))

    def _aktion_gesetzt(self, e, aktion):
        e.aktion = aktion
        self._zeile(e)
        self.zaehlen()
        self.auswahl_zeigen()

    def _aktion_fuer_auswahl(self, i):
        aktion = self.aktion_alle.itemData(i)
        self.aktion_alle.setCurrentIndex(0)
        if not aktion:
            return
        for e in self._gewaehlt():
            if aktion in self._aktionen(e):
                e.aktion = aktion
                box = self.tabelle.itemWidget(self.zeilen[id(e)], 0)
                box.setCurrentIndex(max(0, box.findData(aktion)))
                self._zeile(e)
        self.zaehlen()

    def _gewaehlt(self):
        ids = {it.data(0, Qt.UserRole) for it in self.tabelle.selectedItems()}
        return [e for e in self.eintraege if id(e) in ids]

    def zaehlen(self):
        n = sum(1 for e in self.eintraege if e.aktion in ("neu", "beide", "ersetzen"))
        self.ok.setText(ngettext("Add {n} book", "Add {n} books", n).format(n=n))
        self.ok.setEnabled(bool(n) and bool(self.app.ordner) and not self._laeuft)
        dup = sum(1 for e in self.eintraege if e.duplikat is not None)
        kaputt = sum(1 for e in self.eintraege if e.buch.fehler)
        self.leer.setVisible(not self.eintraege)
        if self.eintraege:
            self.zusammenfassung.setText(
                ngettext("{n} file in the list", "{n} files in the list", len(self.eintraege)).format(n=len(self.eintraege))
                + (", " + ngettext("{n} possible duplicate", "{n} possible duplicates", dup).format(n=dup) if dup else "")
                + (", " + ngettext("{n} not readable", "{n} not readable", kaputt).format(n=kaputt) if kaputt else "")
                + ".")
        else:
            self.zusammenfassung.setText("")

    # ================================================================ Metadaten des gewählten Buchs
    def auswahl_zeigen(self):
        g = self._gewaehlt()
        e = g[0] if len(g) == 1 else None
        for schl, f in self.felder.items():
            f.setEnabled(e is not None and not e.buch.fehler)
            f.setText(e.werte().get(schl, "") if e is not None else "")
            f.setPlaceholderText("")
        if e is None:
            self.dup_text.setText(ngettext("{n} books selected.", "{n} books selected.", len(g)).format(n=len(g))
                                  if g else "")
            self.pfad_text.setText("")
            return
        if e.duplikat is not None:
            d = e.duplikat
            self.dup_text.setText("⧉ " + _("Possible duplicate ({grund}): {titel} – {pfad}").format(
                grund=_(GRUND_TEXT.get(e.grund, "")), titel=getattr(d, "titel", ""), pfad=self._dup_name(e))
                + ("\n" + _("Replace keeps the file name of the existing book, so KOReader keeps the reading "
                            "position and highlights.") if e.grund not in ("liste", "selbst") else ""))
        else:
            self.dup_text.setText("")
        self._pfad_zeigen(e)

    def _pfad_zeigen(self, e):
        text = _("From: {quelle}").format(quelle=e.quelle)
        if e.aktion != "ueberspringen" or e.duplikat is None:
            text += "\n" + self._ziel_text(e)
        self.pfad_text.setText(text)
        self.felder["autor_sort"].setPlaceholderText(fs.sortiername(e.werte().get("autoren", "")))

    def feld_geaendert(self, schl):
        g = self._gewaehlt()
        if len(g) != 1:
            return
        e = g[0]
        neu = self.felder[schl].text().strip()
        alt = (e.buch.meta or {}).get(schl, "")
        if schl == "titel":
            alt = alt or e.buch.titel
        if neu == alt:
            e.aenderung.pop(schl, None)
        else:
            e.aenderung[schl] = neu
        bi.ziel_berechnen(e, self.vorlage)
        self._zeile(e)
        self._pfad_zeigen(e)

    # ================================================================ Ausführen
    def ausfuehren(self):
        a = self.app
        if not a.ordner or self._laeuft:
            return
        zu_tun = [e for e in self.eintraege if e.aktion in ("neu", "beide", "ersetzen")]
        ersetzen = sum(1 for e in zu_tun if e.aktion == "ersetzen")
        if ersetzen and not dialogs.frage(self, _("Add books"), ngettext(
                "{n} existing book will be replaced (a backup is made first). Continue?",
                "{n} existing books will be replaced (a backup is made first). Continue?", ersetzen).format(n=ersetzen)):
            return
        if not a._aenderungen_verwerfen_ok():
            return
        self._laeuft = True
        self.ok.setEnabled(False)
        wurzel, sicherung, anzahl = a.ordner, a.e["sicherungsordner"], int(a.e["sicherungen_anzahl"])
        vorlage = self.vorlage
        speichern_schema = not kg.ist_geraet(wurzel) and not bi.bibliothek_lesen(wurzel).get("ordnerschema")

        def arbeit():
            def schritt(i, n, e):
                text = _("Adding books … {i}/{n}").format(i=i, n=n)
                threads.im_hauptthread(lambda: a.status.set(text))
            fertig, fehler = bi.ausfuehren(zu_tun, wurzel, sicherung, anzahl, schritt)
            if fertig and speichern_schema:          # Schema merken, damit es nicht jedes Mal neu erkannt wird
                d = bi.bibliothek_lesen(wurzel)
                d["ordnerschema"] = vorlage
                try:
                    bi.bibliothek_schreiben(wurzel, d)
                except OSError:
                    pass
            threads.im_hauptthread(lambda: self._fertig(fertig, fehler))
        threads.starten(arbeit)

    def _fertig(self, fertig, fehler):
        self._laeuft = False
        a = self.app
        text = ngettext("{n} book added.", "{n} books added.", len(fertig)).format(n=len(fertig))
        if fehler:
            dialogs.warnung(self, _("Add books"), text + "\n\n" + ngettext(
                "{n} file failed:", "{n} files failed:", len(fehler)).format(n=len(fehler)),
                "\n".join(f"{n}: {t}" for n, t in fehler))
        erledigt = {id(e) for e in self.eintraege if e.ergebnis}
        for e in [e for e in self.eintraege if id(e) in erledigt]:
            it = self.zeilen.pop(id(e))
            self.tabelle.takeTopLevelItem(self.tabelle.indexOfTopLevelItem(it))
        self.eintraege = [e for e in self.eintraege if id(e) not in erledigt]
        self.zaehlen()
        a.nach_import = list(fertig)
        a.laden(a.ordner)
        a.status.set(text)
        if not any(e.aktion in ("neu", "beide", "ersetzen") for e in self.eintraege):
            self.close()                         # übrig sind nur übersprungene (Duplikate, unlesbare)
