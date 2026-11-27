# -*- coding: utf-8 -*-
"""
area_library.py - Bereich Bibliothek (Qt): Tabelle aller Bücher mit Suche, Filter, Statusspalte.

  BibliothekModell   QAbstractTableModel über app.buecher; Spalte 0 = Status (Punkt und Piktogramme),
                     danach listing.SPALTEN. Sortiert und filtert selbst (gleiche Schlüssel wie bisher:
                     Reihe nach Reihe/Nummer/Titel, Cover nach Pixelhöhe, Status nach Zahl der Marken).
  Spalten            Reihenfolge, Ein-/Ausblenden, Breiten und Sortierung über QHeaderView, gemerkt wie
                     in der Tk-Fassung: "spalten" {kennung: px, "#0": px Statusspalte, nur wenn gezogen},
                     "spalten_reihe" [sichtbare Kennungen] (None = Standard), "status_spalte", "sortierung"
  BibliothekBereich  Bereich (ui/area.py)

Was Qt hier abnimmt (in Tk ~300 Zeilen table_columns.py): Spalten ziehen und verschieben kann der
QHeaderView selbst; es bleibt nur, die Statusspalte vorn festzuhalten und alles zu merken.
"""
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
                               QTableView, QVBoxLayout, QWidget)

from bookbench.core import listing
from bookbench.core import markers as km
from bookbench.i18n import N_, _, ngettext
from bookbench.ui import markers as mk
from bookbench.ui import theme
from bookbench.ui.area import Bereich

MINDEST = 40


class BibliothekModell(QAbstractTableModel):
    def __init__(self, bereich):
        super().__init__()
        self.bereich = bereich
        self.app = bereich.app
        self.zeilen = []
        self.kennungen = ["status"] + [c for c, __, __ in listing.SPALTEN]

    def rowCount(self, eltern=QModelIndex()):
        return 0 if eltern.isValid() else len(self.zeilen)

    def columnCount(self, eltern=QModelIndex()):
        return 0 if eltern.isValid() else len(self.kennungen)

    def headerData(self, abschnitt, richtung, rolle=Qt.DisplayRole):
        if richtung != Qt.Horizontal or rolle != Qt.DisplayRole:
            return None
        if abschnitt == 0:
            return _("Status")
        return _(listing.SPALTEN[abschnitt - 1][1])

    def marken(self, b):
        return [m for m in km.sortiert(km.bibliothek(b, self.app.e)) if km.sichtbar(self.app.e, "tabelle", m[0])]

    def data(self, index, rolle=Qt.DisplayRole):
        if not index.isValid():
            return None
        b = self.zeilen[index.row()]
        spalte = self.kennungen[index.column()]
        if rolle == Qt.UserRole:
            return b
        if spalte == "status":
            if rolle == Qt.DecorationRole:
                return mk.status_bild(b.stand(), [k for k, __ in self.marken(b)])
            if rolle == Qt.ToolTipRole:
                return "\n".join(t for __, t in self.marken(b)) or None
        elif rolle == Qt.DisplayRole:
            return str(listing.zelle(b, spalte))
        elif rolle == Qt.ToolTipRole and spalte in ("titel", "kapitel"):
            return str(listing.zelle(b, spalte))
        if rolle == Qt.TextAlignmentRole and spalte == "nummer":
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if rolle == Qt.BackgroundRole and b.fehler:
            return QColor(theme.WARNZEILE[theme.modus()])
        return None

    def sort(self, spalte, ordnung=Qt.AscendingOrder):
        self.app.e["sortierung"] = [self.kennungen[spalte], ordnung == Qt.DescendingOrder]
        self.neu()

    def neu(self):
        """Filtern und sortieren nach den Einstellungen; Auswahl bleibt (Bereich merkt das Buch)."""
        spalte, rueck = self.app.e.get("sortierung") or ["reihe", False]
        if spalte not in self.kennungen:
            spalte = "reihe"
        self.beginResetModel()
        self.zeilen = [b for b in listing.sortiert(self.app.buecher, spalte, bool(rueck), self.app.e)
                       if self.bereich.passt(b)]
        self.endResetModel()

    def zeile_von(self, b):
        try:
            return self.zeilen.index(b)
        except ValueError:
            return -1

    def buch_geaendert(self, b):
        z = self.zeile_von(b)
        if z >= 0:
            self.dataChanged.emit(self.index(z, 0), self.index(z, self.columnCount() - 1))


class _Tabelle(QTableView):
    """QTableView, das Größenänderungen meldet (Spalten einpassen, solange keine gezogen wurde)."""
    groesse = None

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.groesse:
            self.groesse()


class BibliothekBereich(Bereich):
    kennung = "bibliothek"
    titel = N_("Library")
    symbol = "bibliothek"

    def __init__(self, app):
        super().__init__(app)
        self.such, self.filter_kennung, self.buch = "", "alle", None
        self.modell = BibliothekModell(self)
        self.std = {c: w for c, __, w in listing.SPALTEN}

    # ================================================================ Aufbau
    def bauen(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 4, 0, 4)
        oben = QHBoxLayout()
        oben.addWidget(QLabel(_("Search:")))
        self.suchfeld = QLineEdit(self.such)
        self.suchfeld.setClearButtonEnabled(True)
        self.suchfeld.setFixedWidth(260)
        self.suchfeld.setPlaceholderText(_("Title, series, author …"))
        self.suchfeld.textChanged.connect(self._suche)
        esc = QAction(self.suchfeld)                     # Esc im Feld: Suche und Filter leeren
        esc.setShortcut(QKeySequence(Qt.Key_Escape))
        esc.setShortcutContext(Qt.WidgetShortcut)
        esc.triggered.connect(lambda: (self.suchfeld.clear(), self.filterwahl.setCurrentIndex(0)))
        self.suchfeld.addAction(esc)
        oben.addWidget(self.suchfeld)
        oben.addSpacing(14)
        oben.addWidget(QLabel(_("Filter:")))
        self.filterwahl = QComboBox()
        for k, text, __ in listing.FILTER:
            self.filterwahl.addItem(_(text), k)
        self.filterwahl.setCurrentIndex(max(0, self.filterwahl.findData(self.filter_kennung)))
        self.filterwahl.currentIndexChanged.connect(self._filter)
        oben.addWidget(self.filterwahl)
        oben.addStretch(1)
        self.zaehler_text = QLabel("")
        self.zaehler_text.setProperty("rolle", "hinweis")
        oben.addWidget(self.zaehler_text)
        lay.addLayout(oben)

        t = self.tabelle = _Tabelle()
        t.setModel(self.modell)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.ExtendedSelection)      # seit 2.3-beta1: mehrere für die Metadaten
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setAlternatingRowColors(False)
        t.setShowGrid(False)
        t.setWordWrap(False)
        t.setIconSize(QSize(200, 16))
        t.verticalHeader().hide()
        t.verticalHeader().setDefaultSectionSize(22)
        t.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        k = self.kopf = t.horizontalHeader()
        k.setSectionsMovable(True)
        k.setHighlightSections(False)
        k.setStretchLastSection(False)
        k.setSectionResizeMode(QHeaderView.Interactive)
        k.setMinimumSectionSize(26)
        k.setContextMenuPolicy(Qt.CustomContextMenu)
        k.customContextMenuRequested.connect(self._kopfmenue)
        t.setContextMenuPolicy(Qt.CustomContextMenu)
        t.customContextMenuRequested.connect(self._zeilenmenue)
        t.doubleClicked.connect(lambda i: self.app.buch_oeffnen(self.modell.zeilen[i.row()]))
        oeffnen = QAction(t)
        oeffnen.setShortcuts([QKeySequence(Qt.Key_Return), QKeySequence(Qt.Key_Enter)])
        oeffnen.setShortcutContext(Qt.WidgetShortcut)
        oeffnen.triggered.connect(lambda: self.buch and self.app.buch_oeffnen(self.buch))
        t.addAction(oeffnen)
        lay.addWidget(t, 1)
        self.seite = w
        self._intern = True
        self.modell.neu()
        self._spalten_anwenden()
        # erst den Pfeil setzen, dann sortieren lassen: setSortingEnabled sortiert sofort nach dem Pfeil
        spalte, rueck = self.app.e.get("sortierung") or ["reihe", False]
        k.setSortIndicator(self.modell.kennungen.index(spalte) if spalte in self.modell.kennungen else 2,
                           Qt.DescendingOrder if rueck else Qt.AscendingOrder)
        t.setSortingEnabled(True)
        k.sectionMoved.connect(self._verschoben)
        k.sectionResized.connect(self._breite_gezogen)
        t.selectionModel().currentRowChanged.connect(self._auswahl)
        self._intern = False
        self._eingepasst = bool(self.app.e.get("spalten"))
        self._zaehler()
        t.groesse = self._erste_groesse
        QTimer.singleShot(0, self._erste_groesse)
        return w

    def werkzeug(self):
        if self.app.e.get("calibre_an", True):
            return [("uebernehmen", _("Series and blurbs from Calibre"), self.app.calibre_uebernehmen,
                     _("Take series, number and blurb from metadata.calibre where the EPUB lacks them"))]
        return []

    def marken(self):
        erg = [("unlesbar", sum(1 for b in self.app.buecher if b.fehler)), ("ungespeichert", self.app.offen())]
        kobo = self.app.bereich_obj("kobo")                # Abgleich mit dem Reader, wenn diese Bibliothek verknüpft ist
        if self.app.ordner and getattr(kobo, "ab_bib", None) is not None:
            try:
                if Path(self.app.ordner).resolve() == kobo.ab_bib.resolve():
                    erg = kobo.abgleich_marken() + erg
            except OSError:
                pass
        return erg

    def zaehler(self):
        """Anzahl der Bücher in der Seitenleiste (bis 1.4 nur ohne Marken, seit 2.2-beta5 immer, grau vor den Marken)."""
        n = len(self.app.buecher)
        return str(n) if n else ""

    def zustand(self):
        return {"buch": self.buch}

    def wiederherstellen(self, z):
        if z.get("buch") is not None:
            self.auswaehlen(z["buch"])

    def suche_fokus(self):
        self.suchfeld.setFocus()
        self.suchfeld.selectAll()

    # ================================================================ Filter und Anzeige
    def passt(self, b):
        such = self.such.strip().casefold()
        if not listing.such_passt(b, such):
            return False
        pruefung = next((p for k, __, p in listing.FILTER if k == self.filter_kennung), None)
        return pruefung is None or bool(pruefung(b))

    def _suche(self, text):
        self.such = text
        self.neu_zeichnen()

    def _filter(self, *a):
        self.filter_kennung = self.filterwahl.currentData() or "alle"
        self.neu_zeichnen()

    def neu_zeichnen(self):
        """Liste neu (Bücher geladen, Filter, Sortierung); das gewählte Buch bleibt gewählt."""
        if self.seite is None:
            return
        b = self.buch
        if b is not None and b not in self.app.buecher:
            b = next((x for x in self.app.buecher if x.schluessel == b.schluessel), None)
        self._intern = True
        self.modell.neu()
        self._status_breite()
        self._intern = False
        self.buch = None
        if b is not None:
            self.auswaehlen(b, still=True)
        self._zaehler()

    def buch_geaendert(self, b):
        self.modell.buch_geaendert(b)

    def _zaehler(self):
        n, gesamt = len(self.modell.zeilen), len(self.app.buecher)
        self.zaehler_text.setText(ngettext("{n} of {gesamt} book", "{n} of {gesamt} books", gesamt)
                                  .format(n=n, gesamt=gesamt) + f"  ·  {self.app.ordner}" if gesamt else "")

    def auswaehlen(self, b, still=False):
        z = self.modell.zeile_von(b)
        if z < 0:
            return
        self.tabelle.selectRow(z)
        self.tabelle.scrollTo(self.modell.index(z, 1))
        self.buch = b
        if not still:
            self._auswahl(self.modell.index(z, 0), None)

    def _auswahl(self, index, __):
        if not index.isValid():
            return
        b = self.buch = self.modell.zeilen[index.row()]
        zusatz = [b.fehler] if b.fehler else []
        if b.reihe_neu is not None:
            zusatz.append(_("series applied, not yet saved"))
        elif b.reihe_quelle == "Calibre":
            zusatz.append(_("Series from metadata.calibre, not in the EPUB - \"From Calibre\" applies it"))
        elif b.reihe_quelle:
            zusatz.append(_("Series from the {quelle} data, not in the EPUB").format(quelle=b.reihe_quelle))
        self.app.status.set(" - ".join([b.pfad.name] + zusatz))

    def ausgewaehlt(self):
        """Gewählte Bücher in der Reihenfolge der Tabelle."""
        if self.seite is None:
            return []
        zeilen = sorted({i.row() for i in self.tabelle.selectionModel().selectedRows()})
        return [self.modell.zeilen[z] for z in zeilen if 0 <= z < len(self.modell.zeilen)]

    def _zeilenmenue(self, pos):
        index = self.tabelle.indexAt(pos)
        if not index.isValid():
            return
        b = self.modell.zeilen[index.row()]
        auswahl = self.ausgewaehlt()
        if b not in auswahl:                      # Rechtsklick neben die Auswahl: nur dieses Buch
            self.tabelle.selectRow(index.row())
            auswahl = [b]
        standard = self.app.e.get("buch_oeffnen") or "kapitel"
        m = QMenu(self.tabelle)
        for k, text in self.app.oeffnen_ziele():
            a = m.addAction(_("Open in {ziel}").format(ziel=_(text)) if k != "koreader" else _("Start in KOReader"),
                            lambda k=k: self.app.buch_oeffnen(b, k))
            if k == standard:
                a.setShortcut(QKeySequence(Qt.Key_Return))       # zeigt "Eingabe" als Hinweis auf den Doppelklick
                f = a.font()
                f.setBold(True)
                a.setFont(f)
        m.addSeparator()
        m.addAction(ngettext("Look up metadata …", "Look up metadata of {n} books …", len(auswahl))
                    .format(n=len(auswahl)), lambda: self.app.metadaten_nachschlagen(auswahl))
        if len(auswahl) > 1:
            m.addAction(ngettext("Edit metadata of {n} book", "Edit metadata of {n} books", len(auswahl))
                        .format(n=len(auswahl)), lambda: self.app.metadaten_mehrere(auswahl))
            m.addAction(ngettext("Remove advert text from {n} book …", "Remove advert text from {n} books …",
                                 len(auswahl)).format(n=len(auswahl)), lambda: self.app.cleaner(auswahl))
        else:
            m.addAction(_("Remove advert text …"), lambda: self.app.cleaner([b]))
        self._menue_offen = m                                     # für Tests
        m.popup(self.tabelle.viewport().mapToGlobal(pos))

    # ================================================================ Spalten
    def sichtbar(self):
        reihe = self.app.e.get("spalten_reihe")
        alle = [c for c, __, __ in listing.SPALTEN]
        if not reihe:
            return [c for c in alle if c not in listing.SPALTEN_AUS]
        erg = [c for c in reihe if c in alle]
        return erg or [c for c in alle if c not in listing.SPALTEN_AUS]

    def status_an(self):
        return bool(self.app.e.get("status_spalte", True))

    def _spalten_anwenden(self):
        k, kenn = self.kopf, self.modell.kennungen
        breiten = self.app.e.get("spalten") or {}
        reihe = self.sichtbar()
        for i, c in enumerate(kenn[1:], 1):
            try:
                w = max(MINDEST, int(breiten.get(c, self.std[c])))
            except (TypeError, ValueError):
                w = self.std[c]
            k.resizeSection(i, w)
            k.setSectionHidden(i, c not in reihe)
        # Reihenfolge: Status vorn, dann die sichtbaren in ihrer Reihenfolge, dann die ausgeblendeten
        ziel = ["status"] + reihe + [c for c in kenn[1:] if c not in reihe]
        for pos, c in enumerate(ziel):
            von = k.visualIndex(kenn.index(c))
            if von != pos:
                k.moveSection(von, pos)
        k.setSectionHidden(0, not self.status_an())
        self._status_breite()

    def _status_noetig(self):
        n = max((len(self.modell.marken(b)) for b in self.app.buecher), default=0)
        return max(42, mk.GROESSE * (1 + n) + 10)

    def _status_breite(self):
        if not self.status_an():
            return
        gemerkt = (self.app.e.get("spalten") or {}).get("#0")
        try:
            w = int(gemerkt) if gemerkt else self._status_noetig()
        except (TypeError, ValueError):
            w = 42
        alt = self._intern
        self._intern = True
        self.kopf.resizeSection(0, max(26, w))
        self._intern = alt

    def _reihe_merken(self):
        k, kenn = self.kopf, self.modell.kennungen
        reihe = [kenn[k.logicalIndex(v)] for v in range(1, k.count()) if not k.isSectionHidden(k.logicalIndex(v))]
        standard = [c for c, __, __ in listing.SPALTEN if c not in listing.SPALTEN_AUS]
        self.app.e["spalten_reihe"] = None if reihe == standard else reihe

    def _verschoben(self, logisch, alt, neu):
        if self._intern:
            return
        self._intern = True
        if self.kopf.visualIndex(0) != 0:                 # Status bleibt vorn
            self.kopf.moveSection(self.kopf.visualIndex(0), 0)
        self._intern = False
        self._reihe_merken()

    def _breite_gezogen(self, logisch, alt, neu):
        if self._intern:
            return
        self._eingepasst = True
        breiten = self.app.e.setdefault("spalten", {})
        for i, c in enumerate(self.modell.kennungen[1:], 1):
            breiten[c] = self.kopf.sectionSize(i)
        if logisch == 0:
            breiten["#0"] = neu

    def _erste_groesse(self):
        """Ohne gemerkte Breiten einpassen - beim ersten Anzeigen und bei jeder Größenänderung, bis eine
        Spalte gezogen wird (die Seitenleiste kann nach dem Laden breiter werden)."""
        breite = self.tabelle.viewport().width()
        if not self._eingepasst and breite > 100 and breite != getattr(self, "_breite", 0):
            self._breite = breite
            self.einpassen(merken=False)

    def einpassen(self, merken=True):
        """Sichtbare Spalten im Verhältnis ihrer Breiten auf die Fensterbreite bringen."""
        k = self.kopf
        platz = self.tabelle.viewport().width() - (k.sectionSize(0) if self.status_an() else 0) - 2
        sichtbar = [i for i in range(1, k.count()) if not k.isSectionHidden(i)]
        jetzt = [k.sectionSize(i) for i in sichtbar]
        summe = sum(jetzt)
        if platz < MINDEST * len(sichtbar) or not summe:
            return
        neu = [max(MINDEST, int(w * platz / summe)) for w in jetzt]
        neu[0] += platz - sum(neu)
        self._intern = True
        for i, w in zip(sichtbar, neu):
            k.resizeSection(i, max(MINDEST, w))
        self._intern = False
        if merken:
            self._breite_gezogen(-1, 0, 0)

    def umschalten(self, spalte):
        reihe = self.sichtbar()
        if spalte in reihe:
            if len(reihe) == 1:
                return
            reihe.remove(spalte)
        else:
            alle = [c for c, __, __ in listing.SPALTEN]
            vorher = alle[:alle.index(spalte)]
            pos = max((reihe.index(c) + 1 for c in vorher if c in reihe), default=0)
            reihe.insert(pos, spalte)
        standard = [c for c in [c for c, __, __ in listing.SPALTEN] if c not in listing.SPALTEN_AUS]
        self.app.e["spalten_reihe"] = None if reihe == standard else reihe
        self._intern = True
        self._spalten_anwenden()
        self._intern = False

    def verschieben(self, spalte, richtung):
        reihe = self.sichtbar()
        i = reihe.index(spalte)
        j = i + richtung
        if not 0 <= j < len(reihe):
            return
        reihe[i], reihe[j] = reihe[j], reihe[i]
        self.app.e["spalten_reihe"] = reihe
        self._intern = True
        self._spalten_anwenden()
        self._intern = False

    def status_umschalten(self):
        self.app.e["status_spalte"] = not self.status_an()
        self._intern = True
        self.kopf.setSectionHidden(0, not self.status_an())
        self._status_breite()
        self._intern = False

    def zuruecksetzen(self):
        self.app.e["spalten"] = {}
        self.app.e["spalten_reihe"] = None
        self.app.e["status_spalte"] = True
        self._intern = True
        self._spalten_anwenden()
        self._intern = False
        self._eingepasst = False
        self.einpassen(merken=False)

    def sortieren(self, spalte, umgekehrt):
        self.kopf.setSortIndicator(self.modell.kennungen.index(spalte),
                                   Qt.DescendingOrder if umgekehrt else Qt.AscendingOrder)

    def menue_fuellen(self, m, spalte=None):
        """Kopf-Kontextmenü (spalte = Spalte unter der Maus) bzw. Ansicht > Spalten der Bibliothek."""
        m.clear()
        reihe = self.sichtbar()
        namen = {c: _(t) for c, t, __ in listing.SPALTEN}
        if spalte in reihe:
            i = reihe.index(spalte)
            name = namen[spalte]
            m.addAction(_("Sort ascending"), lambda: self.sortieren(spalte, False))
            m.addAction(_("Sort descending"), lambda: self.sortieren(spalte, True))
            m.addSeparator()
            m.addAction(_("Move \"{name}\" left").format(name=name), lambda: self.verschieben(spalte, -1)) \
                .setEnabled(i > 0)
            m.addAction(_("Move \"{name}\" right").format(name=name), lambda: self.verschieben(spalte, 1)) \
                .setEnabled(i < len(reihe) - 1)
            m.addAction(_("Hide \"{name}\"").format(name=name), lambda: self.umschalten(spalte)) \
                .setEnabled(len(reihe) > 1)
            m.addSeparator()
        a = m.addAction(_("Status"), self.status_umschalten)
        a.setCheckable(True)
        a.setChecked(self.status_an())
        for c, __, __ in listing.SPALTEN:
            a = m.addAction(namen[c], lambda c=c: self.umschalten(c))
            a.setCheckable(True)
            a.setChecked(c in reihe)
            a.setEnabled(not (c in reihe and len(reihe) == 1))
        m.addSeparator()
        m.addAction(_("Fit columns to the window"), self.einpassen)
        m.addAction(_("Reset columns"), self.zuruecksetzen)

    def _kopfmenue(self, pos):
        i = self.kopf.logicalIndexAt(pos)
        spalte = self.modell.kennungen[i] if i > 0 else None
        m = QMenu(self.kopf)
        self.menue_fuellen(m, spalte)
        self._kopfmenue_offen = m
        m.popup(self.kopf.mapToGlobal(pos))
