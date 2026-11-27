# -*- coding: utf-8 -*-
"""
area_series.py - Bereich Reihen (seit 2.4-beta1): alle Reihen der Bibliothek als aufklappbare Liste mit
Bänden, fehlenden Nummern, doppelten Nummern und Lesestand. Logik: core/series.py.

  Zeilen      Reihe (Name, Nummern von–bis, Autoren, „3 von 7 gelesen“, als Nächstes, was fehlt);
              darunter die Bücher nach Nummer und, grau dazwischen, die fehlenden Nummern
  Befehle     Reihe durchnummerieren (geht über die Massenbearbeitung im Bereich Metadaten, mit Vorschau),
              Bücher der Reihe in Metadaten bearbeiten, in der Bibliothek zeigen; Doppelklick auf ein Buch
              öffnet es wie in der Bibliothek
  Zustand     Suchtext, Filter, aufgeklappte Reihen, gewählte Zeile (über den Neuaufbau hinweg)
"""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from bookbench.core import markers as km
from bookbench.core import reading
from bookbench.core import series as kse
from bookbench.i18n import N_, _, ngettext
from bookbench.ui import markers as mk
from bookbench.ui import theme
from bookbench.ui.area import Bereich

SPALTEN = (("titel", N_("Series / title"), 300), ("nummer", N_("No."), 70), ("autor", N_("Author"), 170),
           ("gelesen", N_("Read status"), 120), ("naechstes", N_("Next"), 200), ("fehlt", N_("Missing"), 200))
ROLLE = Qt.UserRole


class ReihenBereich(Bereich):
    kennung = "reihen"
    titel = N_("Book series")            # „Series“ allein ist schon „Reihe“ (Spalte, Feld)
    symbol = "reihen"

    def __init__(self, app):
        super().__init__(app)
        self.such, self.filter_kennung = "", "alle"
        self.offen = set()                 # aufgeklappte Reihen (Schlüssel)
        self.gewaehlt = None               # ("reihe", schluessel) oder ("buch", buch.schluessel)
        self.liste = []                    # [Reihe] nach Filter (bzw. Bücher bei „ohne Reihe“)
        self._neu_noetig = False

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
        self.suchfeld.setPlaceholderText(_("Series, title, author …"))
        self.suchfeld.textChanged.connect(self._suche)
        esc = QAction(self.suchfeld)
        esc.setShortcut(QKeySequence(Qt.Key_Escape))
        esc.setShortcutContext(Qt.WidgetShortcut)
        esc.triggered.connect(lambda: (self.suchfeld.clear(), self.filterwahl.setCurrentIndex(0)))
        self.suchfeld.addAction(esc)
        oben.addWidget(self.suchfeld)
        oben.addSpacing(14)
        oben.addWidget(QLabel(_("Filter:")))
        self.filterwahl = QComboBox()
        for k, text, __ in kse.FILTER:
            self.filterwahl.addItem(_(text), k)
        self.filterwahl.setCurrentIndex(max(0, self.filterwahl.findData(self.filter_kennung)))
        self.filterwahl.currentIndexChanged.connect(self._filter)
        oben.addWidget(self.filterwahl)
        oben.addSpacing(14)
        for text, fn in ((_("Expand all"), lambda: self._alle(True)), (_("Collapse all"), lambda: self._alle(False))):
            k = QPushButton(text)
            k.clicked.connect(fn)
            oben.addWidget(k)
        oben.addStretch(1)
        self.zaehler_text = QLabel("")
        self.zaehler_text.setProperty("rolle", "hinweis")
        oben.addWidget(self.zaehler_text)
        lay.addLayout(oben)

        b = self.baum = QTreeWidget()
        b.setColumnCount(len(SPALTEN))
        b.setHeaderLabels([_(t) for __, t, __ in SPALTEN])
        b.setSelectionMode(QAbstractItemView.ExtendedSelection)     # seit 2.4-beta2: mehrere verschieben
        b.setUniformRowHeights(True)
        b.setAlternatingRowColors(False)
        b.setExpandsOnDoubleClick(True)
        kopf = b.header()
        kopf.setStretchLastSection(True)
        kopf.setSectionsMovable(False)
        breiten = self.app.e.get("reihen_spalten") or {}
        for i, (k, __, std) in enumerate(SPALTEN[:-1]):
            b.setColumnWidth(i, int(breiten.get(k, std)))
        kopf.sectionResized.connect(self._breite_gezogen)
        b.itemExpanded.connect(lambda it: self._klappen(it, True))
        b.itemCollapsed.connect(lambda it: self._klappen(it, False))
        b.currentItemChanged.connect(self._auswahl)
        b.itemDoubleClicked.connect(self._doppelklick)
        b.setContextMenuPolicy(Qt.CustomContextMenu)
        b.customContextMenuRequested.connect(self._menue)
        oeffnen = QAction(b)
        oeffnen.setShortcuts([QKeySequence(Qt.Key_Return), QKeySequence(Qt.Key_Enter)])
        oeffnen.setShortcutContext(Qt.WidgetShortcut)
        oeffnen.triggered.connect(self._eingabe)
        b.addAction(oeffnen)
        lay.addWidget(b, 1)
        self.seite = w
        self._fuellen()
        return w

    def werkzeug(self):
        return [("nummern", _("Number series …"), self.durchnummerieren,
                 _("Number the books of the selected series again (with preview, in the Metadata area)"))]

    def marken(self):
        return [("luecke", sum(1 for r in kse.reihen(self.app.buecher) if r.luecken))]

    def zaehler(self):
        n = len(kse.reihen(self.app.buecher))
        return str(n) if n else ""

    def zustand(self):
        return {}

    def suche_fokus(self):
        self.suchfeld.setFocus()
        self.suchfeld.selectAll()

    def beim_zeigen(self):
        if self._neu_noetig:
            self.neu_zeichnen()

    def neu_zeichnen(self):
        if self.seite is not None:
            self._fuellen()

    def buch_geaendert(self, b):
        """Reihe oder Nummer kann sich geändert haben: neu aufbauen, sobald der Bereich zu sehen ist."""
        self._neu_noetig = True
        if self.seite is not None and self.app._bereich() == self.kennung:
            QTimer.singleShot(0, self.beim_zeigen)

    # ================================================================ Liste
    def _suche(self, text):
        self.such = text
        self._fuellen()

    def _filter(self, *a):
        self.filter_kennung = self.filterwahl.currentData() or "alle"
        self._fuellen()

    def _fuellen(self):
        self._neu_noetig = False
        such = self.such.strip().casefold()
        b = self.baum
        b.blockSignals(True)
        b.clear()
        alle = kse.reihen(self.app.buecher)
        if self.filter_kennung == "ohne_reihe":
            from bookbench.core import listing
            self.liste = [x for x in kse.ohne_reihe(self.app.buecher) if listing.such_passt(x, such)]
            for x in self.liste:
                b.addTopLevelItem(self._buch_zeile(x, None))
        else:
            pruefung = next((p for k, __, p in kse.FILTER if k == self.filter_kennung), None)
            self.liste = [r for r in alle if kse.passt(r, such) and (pruefung is None or pruefung(r))]
            for r in self.liste:
                b.addTopLevelItem(self._reihe_zeile(r))
        aktuell = None
        for i in range(b.topLevelItemCount()):
            it = b.topLevelItem(i)
            art, schl = it.data(0, ROLLE)
            if art == "reihe":
                it.setExpanded(schl in self.offen or bool(such and len(self.liste) <= 3))
                for j in range(it.childCount()):
                    kind = it.child(j)
                    if kind.childCount():          # Sammelband: enthaltene Bände gleich zeigen
                        kind.setExpanded(True)
                    if self.gewaehlt and kind.data(0, ROLLE) == self.gewaehlt:
                        aktuell = kind
            if self.gewaehlt and (art, schl) == self.gewaehlt:
                aktuell = it
        b.blockSignals(False)
        if aktuell is not None:
            b.setCurrentItem(aktuell)
            b.scrollToItem(aktuell)
        self._zaehler(alle)

    def _reihe_zeile(self, r):
        it = QTreeWidgetItem()
        schl = kse._schluessel(r.name)
        it.setData(0, ROLLE, ("reihe", schl))
        it.reihe = r
        it.setText(0, r.name)
        f = it.font(0)
        f.setBold(True)
        it.setFont(0, f)
        it.setToolTip(0, r.name)
        it.setText(1, r.spanne)
        it.setTextAlignment(1, int(Qt.AlignRight | Qt.AlignVCenter))
        it.setText(2, ", ".join(r.autoren[:2]) + (" …" if len(r.autoren) > 2 else ""))
        it.setToolTip(2, " & ".join(r.autoren))
        it.setText(3, self._gelesen_reihe(r))
        if r.naechstes is not None:
            nr = kse.reihe_nummer(r.naechstes)[1]
            nr = f"{nr}: " if nr else ""
            it.setText(4, nr + r.naechstes.titel)
            it.setToolTip(4, it.text(4))
        it.setText(5, self._fehlt_text(r))
        it.setToolTip(5, self._fehlt_text(r, lang=True))
        if r.luecken and km.sichtbar(self.app.e, "listen", "luecke"):
            it.setIcon(0, mk.bild("luecke"))
        for x in self._mit_luecken(r):
            it.addChild(x)
        return it

    def _mit_luecken(self, r):
        """Zeilen der Bücher, dazwischen grau die fehlenden Nummern (an der Stelle, wo sie fehlen)."""
        from bookbench.core import listing
        zeilen, offen = [], list(r.luecken)
        for x in r.buecher:
            z = listing.nr(kse.reihe_nummer(x)[1])
            while offen and offen[0][0] < z:
                zeilen.append(self._luecke_zeile(*offen.pop(0)))
            zeilen.append(self._buch_zeile(x, r))
        zeilen += [self._luecke_zeile(*l) for l in offen]
        return zeilen

    def _buch_zeile(self, x, r):
        it = QTreeWidgetItem()
        it.setData(0, ROLLE, ("buch", x.schluessel))
        it.buch = x
        it.setText(0, x.titel or x.name)
        it.setToolTip(0, str(x.pfad))
        nummer = kse.reihe_nummer(x)[1]
        ende = kse.bis(x)
        it.setText(1, f"{nummer}–{ende}" if ende else (nummer or ("–" if r is not None else "")))
        it.setTextAlignment(1, int(Qt.AlignRight | Qt.AlignVCenter))
        it.setText(2, x.autor or "")
        e = getattr(x, "lesen", None)
        it.setText(3, reading.status_text(e))
        if e is not None:
            it.setToolTip(3, reading.beschreibung(e))
        if r is not None:
            hinweis = []
            if not nummer:
                hinweis.append(_("no number"))
            elif kse._zahl(nummer) is not None and kse.nummer_text(kse._zahl(nummer)) in r.doppelt:
                hinweis.append(_("number twice"))
            it.setText(5, ", ".join(hinweis))
            if r.naechstes is x:
                it.setText(4, _("next"))
                for s in range(len(SPALTEN)):
                    f = it.font(s)
                    f.setBold(True)
                    it.setFont(s, f)
        if x.stand():
            it.setIcon(0, mk.status_bild(x.stand(), []))
        if ende and r is not None:                 # Sammelband: enthaltene Bände darunter
            nummern = kse.enthalten(x)
            namen = kse.baende(x, len(nummern))
            for i, n in enumerate(nummern):
                it.addChild(self._band_zeile(n, namen[i] if namen else ""))
        return it

    def _band_zeile(self, nummer, name):
        it = QTreeWidgetItem()
        it.setData(0, ROLLE, ("band", str(nummer)))
        it.setFlags(Qt.ItemIsEnabled)
        it.setText(0, name or _("in this collection"))
        it.setToolTip(0, _("Contained in the collection above. Names are guessed from its table of contents."))
        it.setText(1, str(nummer))
        it.setTextAlignment(1, int(Qt.AlignRight | Qt.AlignVCenter))
        grau = QBrush(QColor(theme.farben()["hinweis"]))
        for s in range(2):
            it.setForeground(s, grau)
        return it

    def _luecke_zeile(self, von, bis):
        it = QTreeWidgetItem()
        it.setData(0, ROLLE, ("luecke", f"{von}-{bis}"))
        it.setFlags(Qt.ItemIsEnabled)
        it.setText(0, ngettext("missing", "missing ({n})", bis - von + 1).format(n=bis - von + 1))
        it.setText(1, str(von) if von == bis else f"{von}–{bis}")
        it.setTextAlignment(1, int(Qt.AlignRight | Qt.AlignVCenter))
        grau = QBrush(QColor(theme.farben()["hinweis"]))
        for s in range(2):
            it.setForeground(s, grau)
            f = it.font(s)
            f.setItalic(True)
            it.setFont(s, f)
        return it

    @staticmethod
    def _gelesen_reihe(r):
        if not r.gelesen_bekannt:
            return ""
        return _("{n} of {gesamt} finished").format(n=r.fertig, gesamt=len(r.buecher))

    @staticmethod
    def _fehlt_text(r, lang=False):
        teile = []
        if r.luecken:
            teile.append(kse.luecken_text(r.luecken) if not lang else
                         ngettext("{n} number missing: {liste}", "{n} numbers missing: {liste}", r.fehlend())
                         .format(n=r.fehlend(), liste=kse.luecken_text(r.luecken)))
        if r.doppelt:
            teile.append(_("twice: {liste}").format(liste=", ".join(r.doppelt)))
        if r.ohne_nummer:
            teile.append(ngettext("{n} without number", "{n} without number", len(r.ohne_nummer))
                         .format(n=len(r.ohne_nummer)))
        return ("\n" if lang else "  ·  ").join(teile)

    def _zaehler(self, alle):
        if self.filter_kennung == "ohne_reihe":
            n = len(self.liste)
            text = ngettext("{n} book without series", "{n} books without series", n).format(n=n)
        else:
            mit = sum(1 for r in alle if r.luecken)
            text = ngettext("{n} of {gesamt} series", "{n} of {gesamt} series", len(alle)).format(
                n=len(self.liste), gesamt=len(alle))
            if mit:
                text += "  ·  " + ngettext("{n} with gaps", "{n} with gaps", mit).format(n=mit)
        self.zaehler_text.setText(text if self.app.buecher else "")

    # ================================================================ Bedienung
    def _klappen(self, it, auf):
        art, schl = it.data(0, ROLLE)
        if art == "reihe":
            (self.offen.add if auf else self.offen.discard)(schl)

    def _alle(self, auf):
        for i in range(self.baum.topLevelItemCount()):
            self.baum.topLevelItem(i).setExpanded(auf)

    def _breite_gezogen(self, i, __, neu):
        if i < len(SPALTEN) - 1:
            self.app.e.setdefault("reihen_spalten", {})[SPALTEN[i][0]] = neu

    def _auswahl(self, it, __):
        if it is None:
            return
        self.gewaehlt = it.data(0, ROLLE)
        r = self.reihe_von(it)
        if getattr(it, "buch", None) is not None:
            x = it.buch
            teile = [x.pfad.name]
            if getattr(x, "lesen", None) is not None:
                teile.append(reading.beschreibung(x.lesen))
            self.app.status.set(" - ".join(t for t in teile if t))
        elif r is not None:
            text = ngettext("{name}: {n} book", "{name}: {n} books", len(r.buecher)).format(name=r.name,
                                                                                          n=len(r.buecher))
            fehlt = self._fehlt_text(r)
            self.app.status.set(text + (f" - {fehlt}" if fehlt else ""))

    @staticmethod
    def reihe_von(it):
        while it is not None and not hasattr(it, "reihe"):
            it = it.parent()
        return getattr(it, "reihe", None)

    def gewaehlte_reihe(self):
        return self.reihe_von(self.baum.currentItem()) if self.seite is not None else None

    def _doppelklick(self, it, __):
        if getattr(it, "buch", None) is not None:
            self.app.buch_oeffnen(it.buch)

    def _eingabe(self):
        it = self.baum.currentItem()
        if it is None:
            return
        if getattr(it, "buch", None) is not None:
            self.app.buch_oeffnen(it.buch)
        else:
            it.setExpanded(not it.isExpanded())

    def ausgewaehlte_buecher(self):
        """Gewählte Bücher; eine gewählte Reihe zählt mit allen ihren Büchern (ohne Doppelte, in Listenfolge)."""
        erg = []
        for it in self.baum.selectedItems():
            for x in ([it.buch] if getattr(it, "buch", None) is not None else
                      list(it.reihe.buecher) if hasattr(it, "reihe") else []):
                if x not in erg:
                    erg.append(x)
        return erg

    def _menue(self, pos):
        it = self.baum.itemAt(pos)
        if it is None or it.data(0, ROLLE)[0] in ("luecke", "band"):
            return
        if not it.isSelected():                   # Rechtsklick neben die Auswahl: nur diese Zeile
            self.baum.setCurrentItem(it)
        m = QMenu(self.baum)
        auswahl = self.ausgewaehlte_buecher()
        if len(self.baum.selectedItems()) > 1 and len(auswahl) > 1:     # mehrere Zeilen: Befehle für alle
            m.addAction(ngettext("Move {n} book to series …", "Move {n} books to series …", len(auswahl))
                        .format(n=len(auswahl)), lambda: self.app.in_reihe_verschieben(auswahl))
            m.addAction(ngettext("Edit metadata of {n} book", "Edit metadata of {n} books", len(auswahl))
                        .format(n=len(auswahl)), lambda: self.app.metadaten_mehrere(auswahl))
            self.app.sammlungen.menue_hinzufuegen(m, auswahl)
            self._menue_offen = m
            m.popup(self.baum.viewport().mapToGlobal(pos))
            return
        x = getattr(it, "buch", None)
        if x is not None:
            standard = self.app.e.get("buch_oeffnen") or "kapitel"
            for k, text in self.app.oeffnen_ziele():
                a = m.addAction(_("Open in {ziel}").format(ziel=_(text)) if k != "koreader" else _("Start in KOReader"),
                                lambda k=k: self.app.buch_oeffnen(x, k))
                if k == standard:
                    f = a.font()
                    f.setBold(True)
                    a.setFont(f)
            m.addAction(_("Show in Library"), lambda: self.in_bibliothek(buch=x))
            m.addAction(_("Move to series …"), lambda: self.app.in_reihe_verschieben([x]))
            self.app.sammlungen.menue_hinzufuegen(m, [x])
            m.addSeparator()
        r = self.reihe_von(it)
        if r is not None:
            m.addAction(_("Number series …"), lambda: self.durchnummerieren(r))
            m.addAction(ngettext("Edit metadata of {n} book", "Edit metadata of {n} books", len(r.buecher))
                        .format(n=len(r.buecher)), lambda: self.app.metadaten_mehrere(r.buecher))
            m.addAction(_("Show series in Library"), lambda: self.in_bibliothek(reihe=r))
            if x is None:
                m.addAction(_("Move whole series …"), lambda: self.app.in_reihe_verschieben(r.buecher))
                m.addAction(_("Collection from series"), lambda: self.app.sammlungen.aus_reihe(r))
                self.app.sammlungen.menue_hinzufuegen(m, r.buecher)
        self._menue_offen = m                     # für Tests
        m.popup(self.baum.viewport().mapToGlobal(pos))

    # ================================================================ Befehle
    def durchnummerieren(self, r=None):
        """Bücher der Reihe in der Reihenfolge ihrer Nummern im Bereich Metadaten wählen und dort
        „Reihe durchnummerieren“ öffnen (Vorschau, dann gelb; gespeichert wird mit Strg+S)."""
        r = r or self.gewaehlte_reihe()
        if r is None:
            self.app.status.set(_("Choose a series first."))
            return
        if len(r.buecher) < 2:
            self.app.status.set(_("This series has only one book."))
            return
        self.app.metadaten_mehrere(r.buecher)
        self.app.metadaten.durchnummerieren()

    def in_bibliothek(self, reihe=None, buch=None):
        bib = self.app.bibliothek
        self.app.bereich_zeigen("bibliothek")
        if reihe is not None:
            bib.filterwahl.setCurrentIndex(0)
            bib.suchfeld.setText(reihe.name)
            if reihe.buecher:
                bib.auswaehlen(reihe.buecher[0])
        elif buch is not None:
            bib.suchfeld.clear()
            bib.filterwahl.setCurrentIndex(0)
            bib.auswaehlen(buch)

    def auswaehlen(self, b):
        """Buch (oder seine Reihe) wählen und aufklappen."""
        if b is None:
            return
        reihe = kse.reihe_nummer(b)[0]
        if reihe.strip():
            self.offen.add(kse._schluessel(reihe))
        self.gewaehlt = ("buch", b.schluessel)
        if self.seite is not None:
            self._fuellen()
