# -*- coding: utf-8 -*-
"""
area_collections.py - Bereich Sammlungen (seit 2.4-beta2): KOReaders Sammlungen der geöffneten Bibliothek
bzw. des E-Readers bearbeiten. Logik: core/book_collections.py.

  links       die Sammlungen (Favoriten zuerst), Neu, Umbenennen, Löschen
  rechts      die Einträge der gewählten Sammlung in Lesereihenfolge: Bücher, dazu grau Platzhalter aus einer
              eingefügten Leseordnung (Geschichte in einer Anthologie, nicht gefunden); Ziehen, Hoch/Runter,
              Bücher hinzufügen, Entfernen, nach Reihennummer sortieren, Platzhalter einem Buch zuordnen
  Speichern   sofort (wie Wörterbuch und E-Reader): Bibliothek auf dem Rechner → .bookbench/library.json, später
              mit dem Abgleich auf den Reader; E-Reader direkt → settings/collection.lua (vorher Sicherung)
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from bookbench.core import book_collections as kco
from bookbench.core import library as kd
from bookbench.core import listing
from bookbench.core import reading
from bookbench.core import series as kse
from bookbench.i18n import N_, _, ngettext
from bookbench.ui import dialogs, theme
from bookbench.ui.area import Bereich
from bookbench.ui.panes import Teiler

ROLLE = Qt.UserRole


def anzeigename(name):
    return _("Favorites") if name == kco.FAVORITEN else name


class _Eintraege(QTreeWidget):
    """Liste der Einträge; Ziehen verschiebt (nur oberste Ebene), danach meldet sie die neue Reihenfolge."""
    verschoben = None

    def dropEvent(self, ev):
        super().dropEvent(ev)
        if self.verschoben:
            self.verschoben()


class SammlungenBereich(Bereich):
    kennung = "sammlungen"
    titel = N_("Collections")
    symbol = "sammlungen"

    def __init__(self, app):
        super().__init__(app)
        self.sammlungen = []
        self.gewaehlt = None                # Name der gezeigten Sammlung
        self.ort, self.wurzel = None, None
        self._fuer = None                   # Ordner, für den self.sammlungen geladen ist
        self.fehler = ""

    # ================================================================ Laden
    def laden(self, still=False):
        self._stand_fuer = None
        self._fuer = self.app.ordner
        self.ort, self.wurzel = kco.ort(self.app.ordner)
        self.fehler = ""
        try:
            self.sammlungen = kco.laden(self.app.ordner)
        except Exception as ex:                       # kaputte collection.lua: nichts anfassen
            self.sammlungen, self.fehler = [], str(ex)
        if self.gewaehlt not in [s["name"] for s in self.sammlungen]:
            self.gewaehlt = self.sammlungen[0]["name"] if self.sammlungen else None

    def _aktuell(self):
        if self._fuer != self.app.ordner:
            self.laden()

    def _speichern(self, geaendert=None, geloescht=()):
        """Sofort schreiben; collection.lua auf dem Reader vorher sichern."""
        def sichern(p):
            kd.sicherung_anlegen(p, self.app.e["sicherungsordner"], int(self.app.e["sicherungen_anzahl"]))
        try:
            kco.speichern(self.app.ordner, self.sammlungen, geaendert, geloescht, sichern)
        except Exception as ex:
            dialogs.fehler(self.app, self.name(), _("The collections could not be saved."), str(ex))
            return False
        kobo = self.app.bereich_obj("kobo")
        if self.ort == "bibliothek" and kobo is not None and hasattr(kobo, "abgleich_nach_speichern"):
            kobo.abgleich_nach_speichern(self.app.ordner)
        reihen = self.app.bereich_obj("reihen")
        if reihen is not None:
            reihen._neu_noetig = True                   # Sammlungsreihen in der Reihen-Übersicht
        self.app._zaehler()
        return True

    # ================================================================ Aufbau
    def bauen(self):
        self._aktuell()
        teiler = Teiler(self.app, "sammlungen", 240)
        links = QWidget()
        ll = QVBoxLayout(links)
        ll.setContentsMargins(2, 4, 0, 4)
        ll.addWidget(QLabel(_("Collections:")))
        self.liste = QListWidget()
        self.liste.currentItemChanged.connect(self._gewaehlt)
        self.liste.setContextMenuPolicy(Qt.CustomContextMenu)
        self.liste.customContextMenuRequested.connect(self._listenmenue)
        ll.addWidget(self.liste, 1)
        z = QHBoxLayout()
        self.k_neu = QPushButton(_("New …"))
        self.k_neu.clicked.connect(lambda: self.neue_sammlung())
        self.k_umbenennen = QPushButton(_("Rename …"))
        self.k_umbenennen.clicked.connect(self.umbenennen)
        self.k_loeschen = QPushButton(_("Delete"))
        self.k_loeschen.clicked.connect(self.loeschen)
        for k in (self.k_neu, self.k_umbenennen, self.k_loeschen):
            z.addWidget(k)
        ll.addLayout(z)
        teiler.addWidget(links)

        rechts = QWidget()
        rl = QVBoxLayout(rechts)
        rl.setContentsMargins(6, 4, 0, 4)
        self.kopf = QLabel("")
        f = self.kopf.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.15)
        self.kopf.setFont(f)
        rl.addWidget(self.kopf)
        zo = QHBoxLayout()
        self.ort_text = QLabel("")
        self.ort_text.setProperty("rolle", "hinweis")
        self.ort_text.setWordWrap(True)
        zo.addWidget(self.ort_text, 1)
        self.k_patch = QPushButton(_("Install patch"))
        self.k_patch.setToolTip(_("Copy 2-bookbench-collections.lua into koreader/patches on the e-reader (replaces "
                                  "2-bookbench-stories.lua)"))
        self.k_patch.clicked.connect(self.patch_installieren)
        zo.addWidget(self.k_patch)
        rl.addLayout(zo)
        # seit 2.4-beta6: Cover-Tafel rechts (wie im Bereich Metadaten), Metadaten/Einträge mit Teiler
        koerper = Teiler(self.app, "sammlung_cover", 230, fest="rechts", minimum=140)
        mitte = QWidget()
        ml = QVBoxLayout(mitte)
        ml.setContentsMargins(0, 0, 6, 0)
        oben_unten = Teiler(self.app, "sammlung_meta", lambda: self.meta_kasten.sizeHint().height() + 6,
                            ausrichtung=Qt.Vertical, minimum=70)
        oben_unten.addWidget(self._meta_bauen())
        unten = QWidget()
        ul = QVBoxLayout(unten)
        ul.setContentsMargins(0, 0, 0, 0)
        b = self.baum = _Eintraege()
        b.setHeaderLabels([_("No."), _("Title"), _("Series"), _("Read status")])
        b.setRootIsDecorated(False)
        b.setUniformRowHeights(True)
        b.setSelectionMode(QAbstractItemView.ExtendedSelection)
        b.setDragDropMode(QAbstractItemView.InternalMove)
        b.setDefaultDropAction(Qt.MoveAction)
        b.verschoben = self._nach_ziehen
        breiten = self.app.e.get("sammlung_spalten") or {}
        for i, (k, std) in enumerate((("nr", 50), ("titel", 340), ("reihe", 220))):
            b.setColumnWidth(i, int(breiten.get(k, std)))
        b.header().sectionResized.connect(self._breite)
        b.itemDoubleClicked.connect(self._doppelklick)
        b.itemSelectionChanged.connect(self._knoepfe_anpassen)
        b.setContextMenuPolicy(Qt.CustomContextMenu)
        b.customContextMenuRequested.connect(self._menue)
        weg = QAction(b)
        weg.setShortcut(QKeySequence(Qt.Key_Delete))
        weg.setShortcutContext(Qt.WidgetShortcut)
        weg.triggered.connect(self.entfernen)
        b.addAction(weg)
        ul.addWidget(b, 1)
        z = QHBoxLayout()
        self.k_hoch = QPushButton(_("Move up"))
        self.k_hoch.clicked.connect(lambda: self.verschieben(-1))
        self.k_runter = QPushButton(_("Move down"))
        self.k_runter.clicked.connect(lambda: self.verschieben(1))
        self.k_dazu = QPushButton(_("Add books …"))
        self.k_dazu.clicked.connect(self.buecher_dazu)
        self.k_weg = QPushButton(_("Remove"))
        self.k_weg.clicked.connect(self.entfernen)
        self.k_geschichte = QPushButton(_("Add story …"))
        self.k_geschichte.setToolTip(_("A story inside an anthology (an entry of its table of contents)"))
        self.k_geschichte.clicked.connect(lambda: self.geschichte_dazu())
        self.k_zuordnen = QPushButton(_("Choose …"))
        self.k_zuordnen.setToolTip(_("Replace the selected placeholder with a book or a story of the library"))
        self.k_zuordnen.clicked.connect(self.zuordnen)
        self.k_sortieren = QPushButton(_("Sort by series number"))
        self.k_sortieren.clicked.connect(self.nach_nummer)
        for k in (self.k_dazu, self.k_geschichte, self.k_zuordnen, self.k_weg):
            z.addWidget(k)
        z.addStretch(1)
        ul.addLayout(z)
        z2 = QHBoxLayout()
        for k in (self.k_hoch, self.k_runter):
            z2.addWidget(k)
        z2.addStretch(1)
        z2.addWidget(self.k_sortieren)
        ul.addLayout(z2)
        oben_unten.addWidget(unten)
        oben_unten.setStretchFactor(1, 1)
        ml.addWidget(oben_unten, 1)
        koerper.addWidget(mitte)
        from bookbench.ui.collection_cover import SammlungCover
        self.cover = SammlungCover(self)
        koerper.addWidget(self.cover)
        koerper.setStretchFactor(0, 1)
        rl.addWidget(koerper, 1)
        teiler.addWidget(rechts)
        self.seite = teiler
        self._fuellen()
        return teiler

    # ================================================================ Metadaten der Sammlung (seit 2.4-beta4)
    def _meta_bauen(self):
        """Reihe, Nummer, Klappentext und Cover der gewählten Sammlung; „Übernehmen“ speichert sofort."""
        kasten = QWidget()
        lay = QHBoxLayout(kasten)
        lay.setContentsMargins(0, 4, 0, 4)
        g = QGridLayout()
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(4)
        g.addWidget(QLabel(_("Series:")), 0, 0)
        self.m_reihe = QComboBox()
        self.m_reihe.setEditable(True)
        self.m_reihe.lineEdit().setPlaceholderText(_("(none) - e.g. Horus Heresy Omnibus"))
        self.m_reihe.setMinimumWidth(240)
        g.addWidget(self.m_reihe, 0, 1)
        g.addWidget(QLabel(_("Number:")), 0, 2)
        from bookbench.ui.area_metadata import _Nummer       # wie die Reihennummer im Bereich Metadaten
        self.m_nummer = _Nummer()
        self.m_nummer.setFixedWidth(80)
        g.addWidget(self.m_nummer, 0, 3)
        g.addWidget(QLabel(_("Blurb:")), 1, 0, Qt.AlignTop)
        self.m_text = QPlainTextEdit()
        self.m_text.setMinimumHeight(48)
        self.m_text.setPlaceholderText(_("Shown in KOReader under “About this collection” (patch needed)"))
        g.addWidget(self.m_text, 1, 1, 1, 3)
        g.setRowStretch(1, 1)
        g.setColumnStretch(1, 1)
        lay.addLayout(g, 1)
        k = QVBoxLayout()
        self.k_meta = QPushButton(_("Apply"))
        self.k_meta.setToolTip(_("Save series, number and blurb of this collection"))
        self.k_meta.clicked.connect(self.meta_uebernehmen)
        k.addWidget(self.k_meta)
        k.addStretch(1)
        lay.addLayout(k)
        self.meta_kasten = kasten
        return kasten

    def _meta_zeigen(self):
        s = self._sammlung()
        self.meta_kasten.setEnabled(s is not None and self.ort is not None)
        m = (s or {}).get("meta") or {}
        reihen = sorted({(x.get("meta") or {}).get("reihe", "") for x in self.sammlungen} - {""}, key=str.casefold)
        self.m_reihe.blockSignals(True)
        self.m_reihe.clear()
        self.m_reihe.addItems(reihen)
        self.m_reihe.setCurrentText(m.get("reihe", ""))
        self.m_reihe.blockSignals(False)
        self.m_nummer.setText(m.get("nummer", ""))
        self.m_text.setPlainText(m.get("klappentext", ""))
        if hasattr(self, "cover"):
            self.cover.anzeigen()

    def cover_pfad(self):
        """Pfad des Covers der gewählten Sammlung oder None (für die Cover-Tafel)."""
        s = self._sammlung()
        return self._cover_pfad((s or {}).get("meta") or {}) if s else None

    def cover_setzen(self, daten):
        self._cover_setzen(daten)

    def _cover_pfad(self, m):
        if not m.get("cover") or self.ort is None:
            return None
        p = kco.cover_ordner(self.ort, self.wurzel) / m["cover"]
        return p if p.is_file() else None

    def meta_uebernehmen(self):
        s = self._sammlung()
        if s is None:
            return
        m = dict(s.get("meta") or {})
        m["reihe"] = self.m_reihe.currentText().strip()
        m["nummer"] = self.m_nummer.text().strip().replace(",", ".") if m["reihe"] else ""
        m["klappentext"] = self.m_text.toPlainText().strip()
        s["meta"] = {k: v for k, v in m.items() if v}
        if not s["meta"]:
            s.pop("meta")
        self._speichern([s["name"]])
        self._listentext()
        self._meta_zeigen()
        self.app.status.set(_("Collection “{name}” saved.").format(name=anzeigename(s["name"])))

    def _cover_setzen(self, daten):
        s = self._sammlung()
        if s is None:
            return
        m = dict(s.get("meta") or {})
        if daten:
            name = kco.cover_name(s["name"], daten)
            ordner = kco.cover_ordner(self.ort, self.wurzel)
            try:
                ordner.mkdir(parents=True, exist_ok=True)
                (ordner / name).write_bytes(daten)
            except OSError as ex:
                dialogs.fehler(self.app, self.name(), _("The cover could not be saved."), str(ex))
                return
            m["cover"] = name
        else:
            m.pop("cover", None)
        s["meta"] = m
        if not m:
            s.pop("meta")
        self._speichern([s["name"]])
        self._meta_zeigen()

    def cover_vom_buch(self):
        s = self._sammlung()
        if s is None:
            return
        buecher = self._buch_von()
        drin = [buecher[e["rel"]] for e in s["eintraege"] if e.get("rel") in buecher]
        if not drin:
            self.app.status.set(_("No book of this collection is in the opened folder."))
            return
        from bookbench.ui.collection_windows import BuchWahlFenster
        f = BuchWahlFenster(self.app, list(dict.fromkeys(drin)), _("Cover from which book?"), mehrere=False)
        self._fenster_offen = f
        if f.exec() != QDialog.Accepted or not f.gewaehlt():
            return
        daten = kd.cover_lesen(f.gewaehlt()[0].pfad)
        if not daten:
            self.app.status.set(_("This book has no cover."))
            return
        self._cover_setzen(daten)

    def werkzeug(self):
        return [("neu", _("New collection …"), lambda: self.neue_sammlung(),
                 _("A new, empty collection")),
                ("einfuegen", _("Paste reading order …"), self.leseordnung,
                 _("Create a collection from a pasted list, e.g. an omnibus of heresyomnibus.com"))]

    def zaehler(self):
        self._aktuell()
        n = len(self.sammlungen)
        return str(n) if n else ""

    def beim_zeigen(self):
        self.neu_zeichnen()

    def neu_zeichnen(self):
        """Nach dem Einlesen und nach einem Abgleich: frisch von der Platte (die Dateien sind klein)."""
        self.laden()
        if self.seite is not None:
            self._fuellen()

    def buch_geaendert(self, b):
        pass

    # ================================================================ Anzeige
    def _buch_von(self):
        """{rel: Buch} der geladenen Bücher, relativ zur Wurzel der Sammlungen."""
        erg = {}
        if self.wurzel is None:
            return erg
        w = Path(self.wurzel).resolve()
        for b in self.app.buecher:
            try:
                erg[Path(b.pfad).resolve().relative_to(w).as_posix()] = b
            except (ValueError, OSError):
                pass
        return erg

    def _fuellen(self):
        self.liste.blockSignals(True)
        self.liste.clear()
        for s in self.sammlungen:
            it = QListWidgetItem(self._listenname(s))
            it.setData(ROLLE, s["name"])
            self.liste.addItem(it)
            if s["name"] == self.gewaehlt:
                self.liste.setCurrentItem(it)
        self.liste.blockSignals(False)
        if self.ort is None:
            text = _("Collections live in a library on this computer (File > New library from e-reader, or Add "
                     "books) or directly on the e-reader. Open one of them.") if self.app.ordner else \
                _("Open a library or the e-reader.")
        elif self.ort == "bibliothek":
            text = _("Saved in the library on this computer; the sync in the E-reader area takes them to the e-reader.")
        else:
            text = _("Saved directly on the e-reader (KOReader's collection.lua, backed up before each change). "
                     "KOReader reads it on its next start.")
        if self.fehler:
            text = _("The collections could not be read: {fehler}").format(fehler=self.fehler)
        elif self._braucht_patch():
            if self.ort == "reader" and not self._patch_da():
                text += " " + _("⚠ Stories, series and covers of collections need the patch 2-bookbench-collections "
                                "on the e-reader (Install patch).")
            elif self.ort == "bibliothek":
                text += " " + _("Stories, series and covers of collections need the patch 2-bookbench-collections on "
                                "the e-reader (Preview > Patches, or open the e-reader here and install it).")
        self.ort_text.setText(text)
        self.k_patch.setVisible(self.ort == "reader" and not self._patch_da() and self._braucht_patch())
        self.k_neu.setEnabled(self.ort is not None and not self.fehler)
        self._eintraege_fuellen()

    def _sammlung(self):
        return kco.finden(self.sammlungen, self.gewaehlt) if self.gewaehlt else None

    def _eintraege_fuellen(self, waehlen=()):
        s = self._sammlung()
        b = self.baum
        b.clear()
        self.kopf.setText(anzeigename(s["name"]) if s else "")
        self._meta_zeigen()
        if s is None:
            self._knoepfe_anpassen()
            return
        buecher = self._buch_von()
        grau = QBrush(QColor(theme.farben()["hinweis"]))
        for i, e in enumerate(s["eintraege"]):
            it = QTreeWidgetItem()
            it.setData(0, ROLLE, i)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
            it.setText(0, str(i + 1))
            it.setTextAlignment(0, int(Qt.AlignRight | Qt.AlignVCenter))
            x = buecher.get(e["rel"]) if e.get("rel") else None
            if kco.geschichte(e):
                it.setText(1, e.get("titel") or e["toc"])
                buch = x.titel if x is not None else (e.get("buch") or Path(e["rel"]).stem)
                it.setText(2, _("story in {buch}").format(buch=buch))
                it.setToolTip(1, _("“{toc}” in the table of contents of {buch}").format(toc=e["toc"], buch=buch)
                              + ("" if x is not None else "\n" + _("This file is not in the opened folder: {pfad}")
                                 .format(pfad=e["rel"])))
                it.setText(3, self._geschichte_stand(e))
                if x is not None:
                    it.buch_geschichte = x
            elif x is not None:
                it.buch = x
                it.setText(1, x.titel or x.name)
                it.setToolTip(1, str(x.pfad))
                r, n = kse.reihe_nummer(x)
                ende = kse.bis(x)
                it.setText(2, f"{r} {n}{'–' + ende if ende else ''}".strip() if r else "")
                it.setText(3, reading.status_text(getattr(x, "lesen", None)))
            else:
                if e.get("rel"):
                    text, tipp = Path(e["rel"]).stem, _("This file is not in the opened folder: {pfad}").format(
                        pfad=e["rel"])
                elif e.get("fremd"):
                    text, tipp = Path(e["fremd"]).stem, _("Outside the e-reader's main storage (e.g. SD card): {pfad}"
                                                          ).format(pfad=e["fremd"])
                elif e.get("kuerzel"):
                    text = e.get("titel", "")
                    tipp = _("Story in an anthology ({kuerzel}), not found in the tables of contents of the "
                             "library. “Choose …” picks the anthology and its entry.").format(kuerzel=e["kuerzel"])
                    it.setText(2, _("in anthology {kuerzel}").format(kuerzel=e["kuerzel"]))
                else:
                    text = e.get("titel", "")
                    tipp = _("Not found in the library. Choose the book with “Choose …”.")
                    it.setText(2, _("not found"))
                it.setText(1, text + (f" - {e['autor']}" if e.get("autor") else ""))
                it.setToolTip(1, tipp)
                for sp in range(4):
                    it.setForeground(sp, grau)
                    f = it.font(sp)
                    f.setItalic(True)
                    it.setFont(sp, f)
            b.addTopLevelItem(it)
            if i in waehlen:
                it.setSelected(True)
        self._knoepfe_anpassen()

    def _braucht_patch(self):
        return any(s.get("meta") or any(kco.geschichte(e) for e in s["eintraege"]) for s in self.sammlungen)

    def fortschritt(self, s):
        """(gelesen, gesamt, bekannt) einer Sammlung aus dem Lesestand ihrer Bücher und Geschichten (Reihen-Übersicht)."""
        buecher = self._buch_von()
        gelesen = gesamt = 0
        bekannt = False
        for e in s["eintraege"]:
            if kco.geschichte(e):
                gesamt += 1
                st = self._geschichte_stand(e)
                bekannt = bekannt or bool(st) or self.ort == "reader"
                gelesen += st == _("finished")
            elif e.get("rel") in buecher:
                gesamt += 1
                le = getattr(buecher[e["rel"]], "lesen", None)
                if le is not None:
                    bekannt = True
                    gelesen += le.get("status") == "complete"
        return gelesen, gesamt, bekannt

    def _patch_da(self):
        if self.ort != "reader":
            return True
        ordner = kco.lua_pfad(self.wurzel).parent.parent / "patches"
        return (ordner / kco.PATCH).is_file() and not (ordner / kco.PATCH_ALT).is_file()

    def patch_installieren(self):
        import shutil
        from bookbench.preview.koreader_settings import MITGEBRACHT_ORDNER
        ziel = kco.lua_pfad(self.wurzel).parent.parent / "patches"
        try:
            ziel.mkdir(parents=True, exist_ok=True)
            shutil.copy2(MITGEBRACHT_ORDNER / kco.PATCH, ziel / kco.PATCH)
            (ziel / kco.PATCH_ALT).unlink(missing_ok=True)        # Vorgänger bis 2.4-beta3
        except OSError as ex:
            dialogs.fehler(self.app, self.name(), _("The patch could not be copied."), str(ex))
            return
        self.app.status.set(_("Patch 2-bookbench-collections copied to the e-reader; restart KOReader."))
        self._fuellen()

    def _geschichte_stand(self, e):
        """Lesestand einer Geschichte aus der Stand-Datei des Patches (nur mit dem E-Reader direkt)."""
        if self.ort != "reader":
            return ""
        if not hasattr(self, "_stand") or self._stand_fuer != self._fuer:
            try:
                self._stand = kco.geschichten_stand(self.wurzel)[0]
            except Exception:
                self._stand = {}
            self._stand_fuer = self._fuer
        st = self._stand.get(kco.stand_schluessel(self.wurzel, e)) or {}
        if st.get("status") == "complete":
            return _("finished")
        if isinstance(st.get("percent"), (int, float)):
            return f"{round(st['percent'] * 100)} %"
        return ""

    def _knoepfe_anpassen(self):
        s = self._sammlung()
        gew = self._gewaehlte_indizes()
        an = s is not None
        self.k_umbenennen.setEnabled(an and s["name"] != kco.FAVORITEN)
        self.k_loeschen.setEnabled(an and s["name"] != kco.FAVORITEN)
        self.k_dazu.setEnabled(an)
        self.k_geschichte.setEnabled(an)
        self.k_sortieren.setEnabled(an and len(s["eintraege"]) > 1)
        for k in (self.k_hoch, self.k_runter, self.k_weg):
            k.setEnabled(an and bool(gew))
        platz = len(gew) == 1 and an and not s["eintraege"][gew[0]].get("rel") and not s["eintraege"][gew[0]].get("fremd")
        self.k_zuordnen.setEnabled(platz)

    def _gewaehlte_indizes(self):
        if self.seite is None:
            return []
        return sorted(it.data(0, ROLLE) for it in self.baum.selectedItems())

    def _gewaehlt(self, it, __):
        if it is not None:
            self.gewaehlt = it.data(ROLLE)
            self._eintraege_fuellen()

    def _breite(self, i, __, neu):
        keys = ("nr", "titel", "reihe")
        if i < len(keys):
            self.app.e.setdefault("sammlung_spalten", {})[keys[i]] = neu

    # ================================================================ Sammlungen
    def _bereit(self):
        self._aktuell()
        if self.ort is None or self.fehler:
            self.app.status.set(_("Collections need a library on this computer or the e-reader (open one first)."))
            return False
        return True

    def neue_sammlung(self, eintraege=(), name=None):
        """Neue Sammlung (Name fragen, falls keiner); Rückgabe der Name oder None."""
        if not self._bereit():
            return None
        if name is None:
            name = dialogs.eingabe(self.app, _("New collection"), _("Name:"))
            if not name or not name.strip():
                return None
        name = kco.name_frei(self.sammlungen, name.strip())
        kco.neu(self.sammlungen, name, eintraege)
        if not self._speichern([name]):
            self.sammlungen = [s for s in self.sammlungen if s["name"] != name]
            return None
        self.gewaehlt = name
        if self.seite is not None:
            self._fuellen()
        self.app.status.set(_("Collection “{name}” created.").format(name=name))
        return name

    def umbenennen(self):
        s = self._sammlung()
        if s is None or s["name"] == kco.FAVORITEN:
            return
        neu = dialogs.eingabe(self.app, _("Rename collection"), _("Name:"), s["name"])
        if not neu or not neu.strip() or neu.strip() == s["name"]:
            return
        alt = s["name"]
        s["name"] = kco.name_frei([x for x in self.sammlungen if x is not s], neu.strip())
        self.gewaehlt = s["name"]
        self._speichern([s["name"]], [alt])
        self._fuellen()

    def loeschen(self):
        s = self._sammlung()
        if s is None or s["name"] == kco.FAVORITEN:
            return
        if not dialogs.frage(self.app, self.name(), _("Delete the collection “{name}”? The books stay where they are."
                                                      ).format(name=s["name"]), standard=False):
            return
        self.sammlungen.remove(s)
        self.gewaehlt = self.sammlungen[0]["name"] if self.sammlungen else None
        self._speichern([], [s["name"]])
        self._fuellen()

    def leseordnung(self):
        if not self._bereit():
            return
        from bookbench.ui.collection_windows import LeseordnungFenster
        f = LeseordnungFenster(self.app, self.app, self.wurzel)
        self._fenster_offen = f                        # für Tests
        if f.exec() != QDialog.Accepted:
            return
        name = self.neue_sammlung(f.eintraege(), f.name())
        if name:
            self.app.bereich_zeigen(self.kennung)

    def _listenmenue(self, pos):
        m = QMenu(self.liste)
        m.addAction(_("New collection …"), lambda: self.neue_sammlung())
        m.addAction(_("Paste reading order …"), self.leseordnung)
        it = self.liste.itemAt(pos)
        if it is not None and it.data(ROLLE) != kco.FAVORITEN:
            self.liste.setCurrentItem(it)
            m.addSeparator()
            m.addAction(_("Rename …"), self.umbenennen)
            m.addAction(_("Delete"), self.loeschen)
        self._menue_offen = m
        m.popup(self.liste.viewport().mapToGlobal(pos))

    # ================================================================ Einträge
    def _geaendert(self, waehlen=()):
        s = self._sammlung()
        kco.manuell(s)
        self._speichern([s["name"]])
        self._listentext()
        self._eintraege_fuellen(waehlen)

    @staticmethod
    def _listenname(s):
        m = s.get("meta") or {}
        reihe = f"  ·  {m['reihe']}" + (f" #{m['nummer']}" if m.get("nummer") else "") if m.get("reihe") else ""
        return f"{anzeigename(s['name'])}  ({len(s['eintraege'])}){reihe}"

    def _listentext(self):
        for i in range(self.liste.count()):
            it = self.liste.item(i)
            s = kco.finden(self.sammlungen, it.data(ROLLE))
            if s is not None:
                it.setText(self._listenname(s))

    def _nach_ziehen(self):
        s = self._sammlung()
        if s is None:
            return
        reihenfolge = [self.baum.topLevelItem(i).data(0, ROLLE) for i in range(self.baum.topLevelItemCount())]
        if reihenfolge == list(range(len(s["eintraege"]))):
            return
        gew = {it.data(0, ROLLE) for it in self.baum.selectedItems()}
        s["eintraege"] = [s["eintraege"][i] for i in reihenfolge]
        self._geaendert([n for n, i in enumerate(reihenfolge) if i in gew])

    def verschieben(self, richtung):
        s = self._sammlung()
        gew = self._gewaehlte_indizes()
        if s is None or not gew:
            return
        e = s["eintraege"]
        if (richtung < 0 and gew[0] == 0) or (richtung > 0 and gew[-1] == len(e) - 1):
            return
        for i in (gew if richtung < 0 else reversed(gew)):
            e[i + richtung], e[i] = e[i], e[i + richtung]
        self._geaendert([i + richtung for i in gew])

    def entfernen(self):
        s = self._sammlung()
        gew = self._gewaehlte_indizes()
        if s is None or not gew:
            return
        s["eintraege"] = [e for i, e in enumerate(s["eintraege"]) if i not in gew]
        self._geaendert()
        self.app.status.set(ngettext("{n} entry removed from the collection (the book stays).",
                                     "{n} entries removed from the collection (the books stay).", len(gew))
                            .format(n=len(gew)))

    def _rels(self, buecher):
        w = Path(self.wurzel).resolve()
        erg = []
        for b in buecher:
            try:
                erg.append(Path(b.pfad).resolve().relative_to(w).as_posix())
            except (ValueError, OSError):
                pass
        return erg

    def buecher_dazu(self):
        s = self._sammlung()
        if s is None:
            return
        from bookbench.ui.collection_windows import BuchWahlFenster
        f = BuchWahlFenster(self.app, self.app.buecher, _("Add books to “{name}”").format(name=anzeigename(s["name"])))
        self._fenster_offen = f
        if f.exec() != QDialog.Accepted:
            return
        self.hinzufuegen(s["name"], f.gewaehlt())

    def hinzufuegen(self, name, buecher):
        """Bücher hinten an die Sammlung name (von Bibliothek, Reihen und hier)."""
        if not self._bereit():
            return 0
        s = kco.finden(self.sammlungen, name)
        if s is None:
            return 0
        n = kco.hinzufuegen(s, self._rels(buecher))
        if n:
            self.gewaehlt = name
            kco.manuell(s)
            self._speichern([name])
            if self.seite is not None:
                self._fuellen()
        self.app.status.set(ngettext("{n} book added to “{name}”.", "{n} books added to “{name}”.", n)
                            .format(n=n, name=anzeigename(name)) if n else
                            _("Already in “{name}”.").format(name=anzeigename(name)))
        return n

    def zuordnen(self):
        s = self._sammlung()
        gew = self._gewaehlte_indizes()
        if s is None or len(gew) != 1:
            return
        e = s["eintraege"][gew[0]]
        if e.get("kuerzel"):                         # Geschichte in einer Anthologie
            self.geschichte_dazu(gew[0], e.get("titel", ""))
            return
        from bookbench.ui.collection_windows import BuchWahlFenster
        f = BuchWahlFenster(self.app, self.app.buecher, _("Book for “{titel}”").format(titel=e.get("titel", "")),
                            mehrere=False)
        f.such.setText(e.get("titel", ""))
        self._fenster_offen = f
        if f.exec() != QDialog.Accepted or not f.gewaehlt():
            return
        rel = self._rels(f.gewaehlt()[:1])
        if rel:
            s["eintraege"][gew[0]] = {"rel": rel[0]}
            self._geaendert([gew[0]])

    def geschichte_dazu(self, ersetzen=None, vorschlag=""):
        """Geschichte aus einer Anthologie hinten anhängen bzw. den Platzhalter ersetzen bei Index ersetzen."""
        s = self._sammlung()
        if s is None:
            return
        from bookbench.ui.collection_windows import GeschichteFenster
        f = GeschichteFenster(self.app, self.app.buecher, self.wurzel, vorschlag)
        self._fenster_offen = f
        if f.exec() != QDialog.Accepted:
            return
        try:
            e = f.eintrag()
        except ValueError:                           # Buch liegt nicht unter der Wurzel
            e = None
        if e is None:
            return
        if ersetzen is not None:
            s["eintraege"][ersetzen] = e
            self._geaendert([ersetzen])
        else:
            s["eintraege"].append(e)
            self._geaendert([len(s["eintraege"]) - 1])
        self.app.status.set(_("Story “{titel}” added.").format(titel=e["titel"]))

    def nach_nummer(self):
        """Nach Reihe und Nummer sortieren (Bücher ohne Reihe und Platzhalter behalten ihre Folge am Ende)."""
        s = self._sammlung()
        if s is None:
            return
        buecher = self._buch_von()

        def schl(paar):
            i, e = paar
            x = buecher.get(e.get("rel") or "")
            if x is None:
                return (1, "", 0, i)
            r, n = kse.reihe_nummer(x)
            return (0 if r else 1, r.casefold(), listing.nr(n), i)
        s["eintraege"] = [e for __, e in sorted(enumerate(s["eintraege"]), key=schl)]
        self._geaendert()

    def _doppelklick(self, it, __):
        if getattr(it, "buch", None) is not None:
            self.app.buch_oeffnen(it.buch)
        elif getattr(it, "buch_geschichte", None) is not None:
            self.app.buch_oeffnen(it.buch_geschichte)

    def _menue(self, pos):
        it = self.baum.itemAt(pos)
        if it is None:
            return
        if not it.isSelected():
            self.baum.clearSelection()
            it.setSelected(True)
        m = QMenu(self.baum)
        x = getattr(it, "buch", None)
        if x is not None and len(self._gewaehlte_indizes()) == 1:
            for k, text in self.app.oeffnen_ziele():
                m.addAction(_("Open in {ziel}").format(ziel=_(text)) if k != "koreader" else _("Start in KOReader"),
                            lambda k=k: self.app.buch_oeffnen(x, k))
            m.addAction(_("Show in Library"), lambda: (self.app.bereich_zeigen("bibliothek"),
                                                        self.app.bibliothek.auswaehlen(x)))
            m.addSeparator()
        if self.k_zuordnen.isEnabled():
            m.addAction(_("Choose …"), self.zuordnen)
        m.addAction(_("Move up"), lambda: self.verschieben(-1))
        m.addAction(_("Move down"), lambda: self.verschieben(1))
        m.addAction(_("Remove"), self.entfernen)
        self._menue_offen = m
        m.popup(self.baum.viewport().mapToGlobal(pos))

    # ================================================================ von anderen Bereichen
    def menue_hinzufuegen(self, menue, buecher):
        """Untermenü „Zu Sammlung hinzufügen“ für Bibliothek und Reihen."""
        self._aktuell()
        unter = menue.addMenu(ngettext("Add to collection", "Add {n} books to collection", len(buecher))
                              .format(n=len(buecher)))
        if self.ort is None or self.fehler:
            unter.setEnabled(False)
            unter.setToolTip(_("Collections need a library on this computer or the e-reader."))
            return unter
        for s in self.sammlungen:
            unter.addAction(anzeigename(s["name"]), lambda n=s["name"]: self.hinzufuegen(n, buecher))
        if self.sammlungen:
            unter.addSeparator()
        unter.addAction(_("New collection …"), lambda: self.neue_sammlung([{"rel": r} for r in self._rels(buecher)]))
        return unter

    def aus_reihe(self, r):
        """Sammlung mit den Büchern einer Reihe in Nummernfolge (Name = Reihe)."""
        if not self._bereit():
            return None
        name = self.neue_sammlung([{"rel": x} for x in self._rels(r.buecher)], r.name)
        if name:
            self.app.bereich_zeigen(self.kennung)
        return name
