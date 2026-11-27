# -*- coding: utf-8 -*-
"""
collection_windows.py - Fenster für den Bereich Sammlungen (seit 2.4-beta2).

  BuchWahlFenster(eltern, buecher, titel, mehrere=True)   .gewaehlt() -> [Buch]
      Bücherliste mit Suche (Titel, Reihe, Autor); Doppelklick nimmt ein Buch sofort
  LeseordnungFenster(eltern, app, name="")                .name(), .eintraege() -> [Eintrag]
      Leseordnung einfügen (z. B. von heresyomnibus.com kopiert): Bookbench liest Nummer, Titel, Kürzel, Autor
      und zeigt gleich, welches Buch es jeweils gefunden hat; Platzhalter für Geschichten in Anthologien
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QSplitter, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from bookbench.core import book_collections as kco
from bookbench.core import listing
from bookbench.i18n import _, ngettext
from bookbench.ui import theme


def _knoepfe(fenster, ok_text):
    k = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    k.button(QDialogButtonBox.Ok).setText(ok_text)
    k.accepted.connect(fenster.accept)
    k.rejected.connect(fenster.reject)
    return k


def _hinweis(text):
    lab = QLabel(text)
    lab.setProperty("rolle", "hinweis")
    lab.setWordWrap(True)
    return lab


def buch_text(b):
    reihe = f"  ·  {b.reihe} {b.nummer}".rstrip() if b.reihe else ""
    return f"{b.titel or b.name}{reihe}"


class BuchWahlFenster(QDialog):
    def __init__(self, eltern, buecher, titel, mehrere=True):
        super().__init__(eltern)
        self.setWindowTitle(titel)
        self.resize(560, 560)
        lay = QVBoxLayout(self)
        self.such = QLineEdit()
        self.such.setPlaceholderText(_("Title, series, author …"))
        self.such.setClearButtonEnabled(True)
        self.such.textChanged.connect(self._filtern)
        lay.addWidget(self.such)
        self.liste = QListWidget()
        self.liste.setSelectionMode(QAbstractItemView.ExtendedSelection if mehrere else
                                    QAbstractItemView.SingleSelection)
        for b in listing.links_sortiert([b for b in buecher if not b.fehler]):
            it = QListWidgetItem(buch_text(b))
            it.setData(Qt.UserRole, b)
            it.setToolTip(str(b.pfad))
            self.liste.addItem(it)
        self.liste.itemDoubleClicked.connect(lambda *a: self.accept())
        lay.addWidget(self.liste, 1)
        if mehrere:
            lay.addWidget(_hinweis(_("Ctrl+click or Shift+click selects several books.")))
        lay.addWidget(_knoepfe(self, _("Choose")))
        self.such.setFocus()

    def _filtern(self, text):
        t = text.strip().casefold()
        for i in range(self.liste.count()):
            it = self.liste.item(i)
            it.setHidden(not listing.such_passt(it.data(Qt.UserRole), t))

    def gewaehlt(self):
        return [self.liste.item(i).data(Qt.UserRole) for i in range(self.liste.count())
                if self.liste.item(i).isSelected() and not self.liste.item(i).isHidden()]


class LeseordnungFenster(QDialog):
    def __init__(self, eltern, app, wurzel, name=""):
        super().__init__(eltern)
        self.app, self.wurzel = app, wurzel
        self._erg = []
        self.setWindowTitle(_("Paste a reading order"))
        self.resize(900, 620)
        lay = QVBoxLayout(self)
        z = QHBoxLayout()
        z.addWidget(QLabel(_("Collection:")))
        self.name_feld = QLineEdit(name)
        self.name_feld.setPlaceholderText(_("Name of the new collection, e.g. Heresy Rising"))
        z.addWidget(self.name_feld, 1)
        lay.addLayout(z)
        lay.addWidget(_hinweis(_("Paste the list, one entry per line, e.g. “2. The Wolf of Ash and Fire (EoT) by "
                                 "Graham McNeill”. Number, the short name of an anthology in brackets and “by …” "
                                 "are optional. Each line is matched to a book of the library.")))
        teil = QSplitter(Qt.Horizontal)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(_("Paste here (Ctrl+V)"))
        self.text.textChanged.connect(lambda: self._zeit.start())
        teil.addWidget(self.text)
        rechts = QWidget()
        rl = QVBoxLayout(rechts)
        rl.setContentsMargins(0, 0, 0, 0)
        self.baum = QTreeWidget()
        self.baum.setHeaderLabels([_("No."), _("From the list"), _("Book in the library")])
        self.baum.setRootIsDecorated(False)
        self.baum.setColumnWidth(0, 40)
        self.baum.setColumnWidth(1, 230)
        rl.addWidget(self.baum, 1)
        self.zusammen = _hinweis("")
        rl.addWidget(self.zusammen)
        teil.addWidget(rechts)
        teil.setSizes([360, 520])
        lay.addWidget(teil, 1)
        self.knoepfe = _knoepfe(self, _("Create collection"))
        lay.addWidget(self.knoepfe)
        self._zeit = QTimer(self)
        self._zeit.setSingleShot(True)
        self._zeit.setInterval(250)
        self._zeit.timeout.connect(self.erkennen)
        self.name_feld.textChanged.connect(lambda *a: self._knopf())
        self.erkennen()

    def erkennen(self):
        zeilen = kco.leseordnung_lesen(self.text.toPlainText())
        self._erg = kco.zuordnen(zeilen, self.app.buecher, self.wurzel)
        self.baum.clear()
        grau = QBrush(QColor(theme.farben()["hinweis"]))
        gefunden = geschichten = fehlt = 0
        for i, (e, z, b) in enumerate(self._erg, 1):
            von = z["titel"] + (f" ({z['kuerzel']})" if z["kuerzel"] else "") + (f" - {z['autor']}" if z["autor"] else "")
            if b is not None and e.get("toc"):
                ziel = _("story “{toc}” in {buch}").format(toc=e["toc"], buch=b.titel or b.name)
                gefunden += 1
            elif b is not None:
                ziel = buch_text(b)
                gefunden += 1
            elif z["kuerzel"]:
                ziel = _("story ({kuerzel}) not found in an anthology - placeholder").format(kuerzel=z["kuerzel"])
                geschichten += 1
            else:
                ziel = _("not found - placeholder, choose the book later")
                fehlt += 1
            it = QTreeWidgetItem(self.baum, [z["nr"] or str(i), von, ziel])
            it.setToolTip(1, von)
            it.setToolTip(2, str(b.pfad) if b is not None else ziel)
            if b is None:
                it.setForeground(2, grau)
        teile = [ngettext("{n} found", "{n} found", gefunden).format(n=gefunden)]
        if geschichten:
            teile.append(ngettext("{n} story not found in the anthologies", "{n} stories not found in the anthologies",
                                  geschichten).format(n=geschichten))
        if fehlt:
            teile.append(ngettext("{n} not found", "{n} not found", fehlt).format(n=fehlt))
        self.zusammen.setText(", ".join(teile) + (". " + _("Placeholders keep their place in the order; “Choose …” "
                                                             "fills them in later.") if geschichten or fehlt else ".")
                              if self._erg else "")
        self._knopf()

    def _knopf(self):
        self.knoepfe.button(QDialogButtonBox.Ok).setEnabled(bool(self._erg) and bool(self.name_feld.text().strip()))

    def name(self):
        return self.name_feld.text().strip()

    def eintraege(self):
        return [e for e, __, __ in self._erg]


class GeschichteFenster(QDialog):
    """Geschichte in einer Anthologie wählen (seit 2.4-beta3): links das Buch, rechts sein Inhaltsverzeichnis.
    Ein Eintrag = die Geschichte reicht bis zum nächsten Eintrag derselben oder einer höheren Ebene; mehrere
    zusammenhängende Einträge = von erstem bis letztem. Die Suche findet Bücher auch über Einträge ihres
    Inhaltsverzeichnisses."""

    def __init__(self, eltern, buecher, wurzel, vorschlag=""):
        super().__init__(eltern)
        self.wurzel = wurzel
        self.setWindowTitle(_("Story in an anthology"))
        self.resize(900, 600)
        lay = QVBoxLayout(self)
        self.such = QLineEdit(vorschlag)
        self.such.setPlaceholderText(_("Search books and their tables of contents …"))
        self.such.setClearButtonEnabled(True)
        self.such.textChanged.connect(self._filtern)
        lay.addWidget(self.such)
        teil = QSplitter(Qt.Horizontal)
        self.liste = QListWidget()
        for b in listing.links_sortiert([b for b in buecher if not b.fehler and getattr(b, "zeilen", None)]):
            it = QListWidgetItem(buch_text(b))
            it.setData(Qt.UserRole, b)
            it.setToolTip(str(b.pfad))
            self.liste.addItem(it)
        self.liste.currentItemChanged.connect(self._buch)
        teil.addWidget(self.liste)
        self.toc = QListWidget()
        self.toc.setSelectionMode(QAbstractItemView.ContiguousSelection)
        self.toc.itemSelectionChanged.connect(self._eintrag)
        teil.addWidget(self.toc)
        teil.setSizes([340, 540])
        lay.addWidget(teil, 1)
        z = QHBoxLayout()
        z.addWidget(QLabel(_("Title:")))
        self.titel = QLineEdit()
        self.titel.setPlaceholderText(_("as in the table of contents"))
        z.addWidget(self.titel, 1)
        lay.addLayout(z)
        lay.addWidget(_hinweis(_("The story runs to the next entry of the same or a higher level. Select several "
                                 "entries in a row for a story with parts. KOReader shows it in the collection with "
                                 "the patch 2-bookbench-collections.")))
        self.knoepfe = _knoepfe(self, _("Add story"))
        lay.addWidget(self.knoepfe)
        self._titel_auto = ""
        self._filtern(vorschlag)
        if vorschlag:
            treffer = kco.geschichte_finden(vorschlag, buecher)
            if treffer is not None:
                self.waehlen(treffer[0], treffer[1], treffer[2])
        self._knopf()

    def _filtern(self, text):
        t = text.strip().casefold()
        erster = None
        for i in range(self.liste.count()):
            it = self.liste.item(i)
            b = it.data(Qt.UserRole)
            passt = not t or listing.such_passt(b, t) or any(t in x[1].casefold() for x in kco.toc_eintraege(b))
            it.setHidden(not passt)
            if passt and erster is None:
                erster = it
        if erster is not None and (self.liste.currentItem() is None or self.liste.currentItem().isHidden()):
            self.liste.setCurrentItem(erster)

    def _buch(self, it, __=None):
        self.toc.clear()
        if it is None:
            return
        t = self.such.text().strip().casefold()
        for i, titel, tiefe, nr in kco.toc_eintraege(it.data(Qt.UserRole)):
            e = QListWidgetItem("    " * max(0, tiefe - 1) + (titel or "–"))
            e.setData(Qt.UserRole, (i, titel, tiefe, nr))
            self.toc.addItem(e)
            if t and t in titel.casefold() and not self.toc.selectedItems():
                e.setSelected(True)
                self.toc.scrollToItem(e)
        self._knopf()

    def _eintrag(self):
        gew = self.gewaehlt_toc()
        if gew and (not self.titel.text() or self.titel.text() == self._titel_auto):
            self._titel_auto = gew[0][1]
            self.titel.setText(self._titel_auto)
        self._knopf()

    def _knopf(self):
        self.knoepfe.button(QDialogButtonBox.Ok).setEnabled(bool(self.gewaehlt_toc()))

    def gewaehlt_toc(self):
        return sorted(it.data(Qt.UserRole) for it in self.toc.selectedItems())

    def waehlen(self, b, toc, nr):
        for i in range(self.liste.count()):
            if self.liste.item(i).data(Qt.UserRole) is b:
                self.liste.item(i).setHidden(False)
                self.liste.setCurrentRow(i)
                break
        self.toc.clearSelection()
        for i in range(self.toc.count()):
            d = self.toc.item(i).data(Qt.UserRole)
            if d[1] == toc and d[3] == nr:
                self.toc.item(i).setSelected(True)
                self.toc.scrollToItem(self.toc.item(i))
                break

    def eintrag(self):
        it = self.liste.currentItem()
        gew = self.gewaehlt_toc()
        if it is None or not gew:
            return None
        erster, letzter = gew[0], gew[-1]
        ende = (letzter[1], letzter[3]) if len(gew) > 1 else None
        return kco.geschichte_eintrag(it.data(Qt.UserRole), erster[1], erster[3], self.wurzel,
                                      self.titel.text().strip() or erster[1], ende)
