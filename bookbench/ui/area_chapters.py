# -*- coding: utf-8 -*-
"""
area_chapters.py - Bereich Kapitel (Qt): Bücherliste links, Inhaltsverzeichnis rechts als echter Baum
(Eintrag, Neu, Hinweis), darunter der Buchtext an der gewählten Stelle.

  KapitelBereich   Bereich (ui/area.py)
    uebernehmen(), alle_uebernehmen(), vorschlaege(), original(), ebene(+1/-1), auswaehlen(b)

Baum statt gezeichneter Linien (Tk: baumlinien()): die Ebenen sind die echte Struktur des QTreeWidget,
Höher/Tiefer hängt Einträge also wirklich um. Bearbeitet wird nur die Spalte Neu (Doppelklick, F2);
Entf = Original, Tab/Umschalt+Tab (oder Alt+→/←) = Ebene tiefer/höher.
"""
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QSplitter,
                               QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator,
                               QVBoxLayout, QWidget)

from bookbench.core import library as kd
from bookbench.core import listing
from bookbench.core import markers as km
from bookbench.i18n import N_, _, ngettext
from bookbench.ui import cover_view
from bookbench.ui import theme
from bookbench.ui.area import Bereich
from bookbench.ui.booklist import BuchListe
from bookbench.ui.panes import Teiler

ALT, NEU, HINWEIS = 0, 1, 2


class _NurNeu(QStyledItemDelegate):
    """Bearbeiten nur in der Spalte Neu; das Feld startet mit dem neuen bzw. dem alten Namen, und das
    Ergebnis geht an den Bereich (der setzt Entwurf, Zeile und Status)."""

    def __init__(self, bereich):
        super().__init__()
        self.bereich = bereich

    def createEditor(self, eltern, opt, index):
        if index.column() != NEU:
            return None
        return QLineEdit(eltern)

    def setEditorData(self, editor, index):
        it = self.bereich.baum.itemFromIndex(index)
        editor.setText(it.text(NEU) or self.bereich.titel_von(it))
        editor.selectAll()

    def setModelData(self, editor, modell, index):
        it = self.bereich.baum.itemFromIndex(index)
        self.bereich.zeile_setzen(it.data(ALT, Qt.UserRole), editor.text().strip())


class _Baum(QTreeWidget):
    def __init__(self, bereich):
        super().__init__()
        self.bereich = bereich

    def keyPressEvent(self, ev):
        k, mod = ev.key(), ev.modifiers()
        if self.state() == QAbstractItemView.EditingState:
            return super().keyPressEvent(ev)
        if k == Qt.Key_Tab or (k == Qt.Key_Right and mod & Qt.AltModifier):
            self.bereich.ebene(1)
        elif k == Qt.Key_Backtab or (k == Qt.Key_Left and mod & Qt.AltModifier):
            self.bereich.ebene(-1)
        elif k == Qt.Key_Delete:
            self.bereich.zeilen_original()
        else:
            super().keyPressEvent(ev)

    def focusNextPrevChild(self, weiter):
        return False                                    # Tab gehört den Ebenen, nicht dem Fokuswechsel


class KapitelBereich(Bereich):
    kennung = "kapitel"
    titel = N_("Chapters")
    symbol = "kapitel"

    def __init__(self, app):
        super().__init__(app)
        self.buch = None
        self._liste_zustand = {}

    # ================================================================ Aufbau
    def bauen(self):
        teiler = Teiler(self.app, "kapitel", 300)
        self.liste = BuchListe(self.app, listing.kapitel_filter(), km.kapitel)
        self.liste.gewaehlt.connect(self._buch_gewaehlt)
        teiler.addWidget(self.liste)

        rechts = QWidget()
        rl = QVBoxLayout(rechts)
        rl.setContentsMargins(10, 0, 0, 0)
        kopf = QHBoxLayout()
        self.cover = QLabel()
        self.cover.setCursor(Qt.PointingHandCursor)
        self.cover.mousePressEvent = lambda ev: cover_view.gross(self.app, self.buch)
        kopf.addWidget(self.cover, 0, Qt.AlignTop)
        texte = QVBoxLayout()
        self.kopf = QLabel(_("Choose a book on the left."))
        self.kopf.setProperty("rolle", "ueberschrift")
        self.info = QLabel("")
        self.info.setProperty("rolle", "hinweis")
        self.info.setWordWrap(True)
        texte.addWidget(self.kopf)
        texte.addWidget(self.info)
        texte.addStretch(1)
        kopf.addLayout(texte, 1)
        rl.addLayout(kopf)

        unten = QSplitter(Qt.Vertical)
        unten.setChildrenCollapsible(False)
        b = self.baum = _Baum(self)
        b.setColumnCount(3)
        b.setHeaderLabels([_("Entry"), _("New"), _("Note")])
        b.setSelectionMode(QAbstractItemView.ExtendedSelection)
        b.setUniformRowHeights(True)
        b.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        b.setItemDelegate(_NurNeu(self))
        b.setAllColumnsShowFocus(True)
        b.header().setStretchLastSection(True)
        b.setColumnWidth(ALT, 260)
        b.setColumnWidth(NEU, 260)
        b.currentItemChanged.connect(lambda it, __: self._zeile(it))
        b.itemDoubleClicked.connect(lambda it, spalte: b.editItem(it, NEU))
        unten.addWidget(b)
        tw = QWidget()
        tl = QVBoxLayout(tw)
        tl.setContentsMargins(0, 6, 0, 0)
        tl.addWidget(QLabel(_("In the book at this point:")))
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        tl.addWidget(self.text)
        unten.addWidget(tw)
        unten.setStretchFactor(0, 4)
        unten.setStretchFactor(1, 1)
        rl.addWidget(unten, 1)
        teiler.addWidget(rechts)
        teiler.setStretchFactor(1, 1)
        self.seite = teiler
        if self._liste_zustand:
            self.liste.wiederherstellen(self._liste_zustand)
        self.liste.fuellen(listing.links_sortiert(self.app.buecher), self.buch)
        return teiler

    def werkzeug(self):
        return [("uebernehmen", _("Apply"), self.uebernehmen, _("Apply the New column for this book (Ctrl+Enter)")),
                ("pruefen", _("Apply all"), self.alle_uebernehmen,
                 _("Apply the suggestions of all books without questionable entries")),
                None,
                ("ausruecken", _("Up"), lambda: self.ebene(-1),
                 _("Move the selected entries with their sub-entries one level up (Shift+Tab)")),
                ("einruecken", _("Down"), lambda: self.ebene(1),
                 _("Move the selected entries with their sub-entries one level down (Tab)")),
                None,
                ("rueckgaengig", _("Suggestions"), self.vorschlaege, _("Reset the book to the suggestions")),
                ("zurueckschreiben", _("Original"), self.original, _("Reset the book to the unchanged table of contents"))]

    def marken(self):
        return [m for m in km.zaehlen(self.app.buecher, km.kapitel) if m[0] != "unlesbar"]

    def zustand(self):
        return {"liste": self.liste.zustand()}

    def wiederherstellen(self, z):
        self._liste_zustand = z.get("liste") or {}
        self.liste.wiederherstellen(self._liste_zustand)
        self.liste.fuellen(listing.links_sortiert(self.app.buecher), self.buch)

    def suche_fokus(self):
        self.liste.fokus()

    def beim_zeigen(self):
        if self.buch is None and self.liste.liste.count():
            self.liste.waehlen(self.liste.liste.item(0).data(Qt.UserRole))

    def neu_zeichnen(self):
        """Bücher neu (Laden, Speichern, Alle übernehmen): Liste füllen, bisheriges Buch bleibt."""
        if self.seite is None:
            return
        self.liste.fuellen(listing.links_sortiert(self.app.buecher), self.buch)
        self._cover_zeigen()

    def buch_geaendert(self, b, baum=False):
        self.liste.neu_zeichnen()
        if baum and b is self.buch:
            self._anzeigen(behalten=True)

    def auswaehlen(self, b):
        self.liste.waehlen(b)

    # ================================================================ Anzeige
    def _buch_gewaehlt(self, b):
        if b is not self.buch:
            cover_view.gross_schliessen(ausser=b)
        self.buch = b
        self._anzeigen()

    def _cover_zeigen(self):
        b = self.buch
        pm = cover_view.bild(b, int(self.app.e.get("cover_kopf_hoehe") or 96)) \
            if b is not None and self.app.e.get("cover", True) else None
        self.cover.setVisible(pm is not None)
        if pm is not None:
            self.cover.setPixmap(pm)

    def titel_von(self, it):
        return self.buch.zeilen[it.data(ALT, Qt.UserRole)][1]

    def _anzeigen(self, behalten=False):
        b = self.buch
        auswahl = self._auswahl() if behalten else []
        oben = self.baum.verticalScrollBar().value() if behalten else 0
        self.baum.blockSignals(True)
        self.baum.clear()
        self.text.clear()
        self._cover_zeigen()
        if b is None:
            self.kopf.setText(_("Choose a book on the left."))
            self.info.setText("")
            self.baum.blockSignals(False)
            return
        self.kopf.setText(b.name)
        teile = [x for x in (b.autor, f"{b.reihe} {b.nummer}".strip()) if x] + [b.pfad.name]
        if b.uebersprungen:
            teile.append(_("No suggestions: {grund}").format(grund=b.uebersprungen))
        if b.fehler:
            teile.append(b.fehler)
        self.info.setText("  ·  ".join(teile))
        aktuell, tiefen = b.aktuelle_titel(), b.aktuelle_tiefen()
        warn, ohne = QColor(theme.WARNZEILE[theme.modus()]), QColor(theme.OHNEZEILE[theme.modus()])
        stapel = []
        self.eintraege = []
        for i, (tiefe, titel, href, k) in enumerate(b.zeilen):
            neu = aktuell.get(k, "")
            kand = b.kandidaten.get(k)
            hinweis = "; ".join(kand["reasons"]) if kand and kand["reasons"] and k not in b.neu else ""
            farbe = warn if hinweis else None
            if not hinweis and kand and (not neu or neu == titel):
                hinweis, farbe = _("number only, no name found"), ohne    # zählt in "ok (n ohne Namen)"
            if tiefen[i] != tiefe:
                hinweis = "; ".join(x for x in (_("Level {alt} → {neu}").format(alt=tiefe, neu=tiefen[i]), hinweis)
                                    if x)
            while stapel and stapel[-1][0] >= tiefen[i]:
                stapel.pop()
            it = QTreeWidgetItem(stapel[-1][1] if stapel else self.baum, [titel, neu if neu != titel else "", hinweis])
            it.setData(ALT, Qt.UserRole, i)
            it.setFlags(it.flags() | Qt.ItemIsEditable)
            if hinweis:
                it.setToolTip(HINWEIS, hinweis)
            it.setToolTip(ALT, titel)
            if farbe:
                for c in range(3):
                    it.setBackground(c, farbe)
            stapel.append((tiefen[i], it))
            self.eintraege.append(it)
        self.baum.setRootIsDecorated(any(self.baum.topLevelItem(j).childCount()
                                         for j in range(self.baum.topLevelItemCount())))
        self.baum.expandAll()
        for i in auswahl:
            if i < len(self.eintraege):
                self.eintraege[i].setSelected(True)
        if auswahl and auswahl[0] < len(self.eintraege):
            self.baum.setCurrentItem(self.eintraege[auswahl[0]], NEU, QItemSelectionModel.NoUpdate)
        self.baum.blockSignals(False)
        if behalten:
            self.baum.verticalScrollBar().setValue(oben)
        else:
            self.app.status.set(f"{b.name}: " + ngettext("{n} entry", "{n} entries", len(b.zeilen)).format(
                n=len(b.zeilen)) + ", " + ngettext("{n} suggestion.", "{n} suggestions.", len(b.vorschlag)).format(
                n=len(b.vorschlag)))

    def _auswahl(self):
        return sorted(it.data(ALT, Qt.UserRole) for it in self.baum.selectedItems())

    def _zeile(self, it):
        b = self.buch
        if not (b and it):
            return
        tiefe, titel, href, k = b.zeilen[it.data(ALT, Qt.UserRole)]
        self.text.setPlainText("\n".join(kd.textanfang(b, href)))
        if it.text(HINWEIS):
            self.app.status.set(f"{titel}: {it.text(HINWEIS)}")

    # ================================================================ Bearbeiten
    def zeile_setzen(self, index, text):
        b = self.buch
        if b is None:
            return
        tiefe, titel, href, k = b.zeilen[index]
        aktuell = b.aktuelle_titel()
        alt = aktuell.get(k, titel)
        neu = text or titel
        if neu == alt:
            return
        if b.entwurf is None:
            b.entwurf = dict(aktuell)
        if neu == titel:
            b.entwurf.pop(k, None)
        else:
            b.entwurf[k] = neu
        if index < len(self.eintraege):
            self.eintraege[index].setText(NEU, neu if neu != titel else "")
        self.app.buch_geaendert(b)
        self.app.status.set(f"{titel}: " + _("changed, not yet applied (Ctrl+Enter)."))

    def zeilen_original(self):
        for i in self._auswahl() if self.buch else ():
            self.zeile_setzen(i, "")

    def ebene(self, richtung):
        """Markierte Einträge samt Untereinträgen eine Ebene tiefer (+1) oder höher (-1)."""
        b = self.buch
        if self.app._bereich() != "kapitel" or not b:
            return
        sel = self._auswahl()
        if not sel:
            self.app.status.set(_("Select entries in the table, then Tab (down) or Shift+Tab (up)."))
            return
        if b.ebenen_sperre:
            self.app.status.set(f"{b.name}: " + _("levels cannot be changed - {grund}.").format(grund=b.ebenen_sperre))
            return
        try:
            neu = kd.ebenen_verschieben(b.aktuelle_tiefen(), sel, richtung)
        except ValueError as e:
            self.app.status.set((_("Cannot move down: {grund}.") if richtung > 0 else _("Cannot move up: {grund}."))
                                .format(grund=e))
            return
        basis = b.tiefen_neu if b.tiefen_neu is not None else b.original_tiefen()
        b.tiefen_entwurf = None if neu == basis else neu
        self.app.buch_geaendert(b, baum=True)
        self.app.status.set((ngettext("{n} entry moved down (with sub-entries), not yet applied (Ctrl+Enter).",
                                      "{n} entries moved down (with sub-entries), not yet applied (Ctrl+Enter).", len(sel))
                             if richtung > 0 else
                             ngettext("{n} entry moved up (with sub-entries), not yet applied (Ctrl+Enter).",
                                      "{n} entries moved up (with sub-entries), not yet applied (Ctrl+Enter).", len(sel)))
                            .format(n=len(sel)))

    def _bearbeitung_beenden(self):
        """Offenes Eingabefeld übernehmen (vor Übernehmen, Bereichswechsel, Sprachwechsel)."""
        w = self.baum.focusWidget() if self.seite is not None else None
        if isinstance(w, QLineEdit) and w.parent() is self.baum.viewport():
            self.baum.commitData(w)
            self.baum.closeEditor(w, QStyledItemDelegate.NoHint)

    def _kapitel_uebernehmen(self, b):
        original = {z[3]: z[1] for z in b.zeilen}
        b.neu = {k: v for k, v in b.aktuelle_titel().items() if v != original.get(k)}
        b.entwurf = None
        if b.tiefen_entwurf is not None:
            b.tiefen_neu = None if b.tiefen_entwurf == b.original_tiefen() else b.tiefen_entwurf
            b.tiefen_entwurf = None
        for kand in b.kandidaten.values():              # entschieden = nicht mehr fragwürdig
            kand["reasons"] = []
        kd.entscheidungen_merken(b, self.app.entscheidungen)

    def uebernehmen(self):
        self._bearbeitung_beenden()
        b = self.buch
        if not b:
            self.app.status.set(_("Apply: choose a book in the Chapters or Blurbs area."))
            return
        self._kapitel_uebernehmen(b)
        kd.json_speichern(kd.ENTSCHEIDUNGEN, self.app.entscheidungen)
        self.app.buch_geaendert(b, baum=True)
        self.app.status.set(f"{b.name}: " + ngettext("{n} chapter name applied, not yet saved.",
                                                      "{n} chapter names applied, not yet saved.", len(b.neu))
                            .format(n=len(b.neu)))

    def alle_uebernehmen(self):
        self._bearbeitung_beenden()
        n = 0
        for b in self.app.buecher:
            if b.vorschlag and b.entwurf is None and b.tiefen_entwurf is None and not b.warnung() and not b.neu:
                self._kapitel_uebernehmen(b)
                n += 1
        kd.json_speichern(kd.ENTSCHEIDUNGEN, self.app.entscheidungen)
        self.app.alles_neu_zeichnen()
        if self.buch is not None:
            self._anzeigen(behalten=True)
        offen = sum(1 for b in self.app.buecher if b.warnung())
        self.app.status.set(ngettext("Suggestions of {n} book applied.", "Suggestions of {n} books applied.", n)
                            .format(n=n) + (" " + ngettext("Please check {n} book with questionable entries one by one.",
                                                           "Please check {n} books with questionable entries one by one.",
                                                           offen).format(n=offen) if offen else ""))

    def vorschlaege(self):
        b = self.buch
        if b:
            b.entwurf, b.neu = None, {}
            b.tiefen_entwurf = b.tiefen_neu = None
            self.app.buch_geaendert(b, baum=True)
            self.app.status.set(f"{b.name}: " + _("reset to the suggestions."))

    def original(self):
        b = self.buch
        if b:
            b.entwurf = {}
            b.tiefen_entwurf = b.original_tiefen() if b.aktuelle_tiefen() != b.original_tiefen() else None
            self.app.buch_geaendert(b, baum=True)
            self.app.status.set(f"{b.name}: " + _("original restored, not yet applied."))

    def schliessen_ok(self):
        self._bearbeitung_beenden()
        return True


def alle_eintraege(baum):
    """Alle Einträge eines QTreeWidget in Reihenfolge (für Tests)."""
    erg, it = [], QTreeWidgetItemIterator(baum)
    while it.value():
        erg.append(it.value())
        it += 1
    return erg
