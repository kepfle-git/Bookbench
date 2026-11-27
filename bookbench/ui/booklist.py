# -*- coding: utf-8 -*-
"""
booklist.py - schmale Bücherliste links in Kapitel und Metadaten (Qt-Gegenstück zu tk/list_filter.py,
den Listen in tk/app.py und dem Statusstreifen tk/markers.MarkenStreifen).

  BuchListe(app, filter, marken_fn, mehrfach=False)
      Kopf "Bücher:" (bei aktivem Filter "Bücher: 3 von 12"), Suchfeld mit ×, Filterauswahl, Liste.
      Rechts in jeder Zeile der Statusstreifen: Punkt für den Stand (geändert/übernommen/gespeichert)
      und die Piktogramme aus marken_fn(b) (Einstellung status_liste, je Ort abschaltbar: "listen").
      filter = [(kennung, N_("Text"), prüfung)], der erste ist "alle".
    gewaehlt            Signal(buch oder None) - auch, wenn das Programm wählt
    mehrere             Signal([buch]) - Auswahl mit Strg/Umschalt geändert (nur mit mehrfach=True, seit 2.3-beta1)
    ausgewaehlt()       gewählte Bücher in der Reihenfolge der Liste (ohne mehrfach: [aktuell()] bzw. [])
    mehrere_waehlen(bb) diese Bücher wählen (die sichtbaren); bleibt über fuellen() erhalten
    fuellen(buecher)    neu füllen (Reihenfolge wie übergeben), bisheriges Buch bleibt gewählt bzw. das
                        nächste passende (listing.nachfolger)
    waehlen(b)          Buch wählen; ist es weggefiltert, werden Suche und Filter zurückgesetzt
    aktuell(), fokus(), zustand()/wiederherstellen(z)   Suchtext, Filter und Buch über einen Neuaufbau
    neu_zeichnen()      nur Streifen und Tooltips (Stand eines Buchs geändert)

Tooltip: der ganze Name, wenn er abgeschnitten ist, dazu die Texte der Marken.
"""
from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFontMetrics, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QStyle, QStyledItemDelegate, QToolTip, QVBoxLayout, QWidget)

from bookbench.core import listing
from bookbench.core import markers as km
from bookbench.i18n import _
from bookbench.ui import markers as mk
from bookbench.ui import theme

SCHRITT = 16


class _Streifen(QStyledItemDelegate):
    """Zeichnet den Eintrag wie üblich, rechts darüber Punkt und Piktogramme."""

    def __init__(self, liste):
        super().__init__(liste)
        self.liste = liste

    def breite(self, b):
        return SCHRITT * (1 + len(self.liste.marken(b))) + 4 if self.liste.streifen_an() else 0

    def paint(self, m, opt, index):
        b = index.data(Qt.UserRole)
        rechts = self.breite(b) if b is not None else 0
        o = type(opt)(opt)
        self.initStyleOption(o, index)
        o.rect = QRect(opt.rect.x(), opt.rect.y(), opt.rect.width() - rechts, opt.rect.height())
        # Hintergrund der ganzen Zeile (Auswahl), Text nur links vom Streifen
        style = opt.widget.style() if opt.widget else None
        voll = type(opt)(opt)
        self.initStyleOption(voll, index)
        voll.text = ""
        style.drawControl(QStyle.CE_ItemViewItem, voll, m, opt.widget)
        o.backgroundBrush = QColor(Qt.transparent)
        o.state &= ~QStyle.State_HasFocus
        style.drawControl(QStyle.CE_ItemViewItem, o, m, opt.widget)
        if not rechts:
            return
        x = opt.rect.right() - rechts + 2
        y = opt.rect.y() + (opt.rect.height() - 14) // 2
        stand = b.stand()
        if stand:
            m.drawPixmap(x, y, mk.bild("punkt", theme.MARK[theme.modus()][stand]))
        for i, (k, __) in enumerate(self.liste.marken(b)):
            m.drawPixmap(x + SCHRITT * (i + 1), y, mk.bild(k))

    def sizeHint(self, opt, index):
        s = super().sizeHint(opt, index)
        return QSize(s.width(), max(s.height(), 20))


class _Liste(QListWidget):
    def __init__(self, eltern):
        super().__init__()
        self.eltern = eltern
        self.setMouseTracking(True)

    def viewportEvent(self, ev):
        if ev.type() == ev.Type.ToolTip:
            it = self.itemAt(ev.pos())
            text = self.eltern.tipp(it) if it else ""
            if text:
                QToolTip.showText(ev.globalPos(), text, self)
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(ev)


class BuchListe(QWidget):
    gewaehlt = Signal(object)
    mehrere = Signal(list)

    def __init__(self, app, filter, marken_fn=None, ort="listen", mehrfach=False):
        super().__init__()
        self.app, self.filter, self.marken_fn, self.ort = app, list(filter), marken_fn, ort
        self.mehrfach = mehrfach
        self.alle = []                          # Reihenfolge wie zuletzt übergeben
        self._buch = None
        self._still = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.kopf = QLabel(_("Books:"))
        lay.addWidget(self.kopf)
        self.such = QLineEdit()
        self.such.setPlaceholderText(_("Search:").rstrip(":") + " …")
        self.such.setClearButtonEnabled(True)
        self.such.textChanged.connect(self._geaendert)
        esc = QAction(self.such)                         # Esc im Feld: Suche und Filter leeren
        esc.setShortcut(QKeySequence(Qt.Key_Escape))
        esc.setShortcutContext(Qt.WidgetShortcut)
        esc.triggered.connect(self.zuruecksetzen)
        self.such.addAction(esc)
        z = QHBoxLayout()
        z.setContentsMargins(0, 0, 0, 0)
        z.addWidget(self.such)
        lay.addLayout(z)
        self.wahl = None
        if len(self.filter) > 1:
            self.wahl = QComboBox()
            for k, text, __ in self.filter:
                self.wahl.addItem(_(text), k)
            self.wahl.currentIndexChanged.connect(self._geaendert)
            lay.addWidget(self.wahl)
        self.liste = _Liste(self)
        self.liste.setSelectionMode(QAbstractItemView.ExtendedSelection if mehrfach
                                    else QAbstractItemView.SingleSelection)
        self.liste.setUniformItemSizes(True)
        self.liste.setTextElideMode(Qt.ElideRight)
        self.liste.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.liste.setItemDelegate(_Streifen(self))
        self.liste.currentItemChanged.connect(self._auswahl)
        if mehrfach:
            self.liste.itemSelectionChanged.connect(self._auswahl_mehr)
        lay.addWidget(self.liste, 1)

    # -- Einstellungen ----------------------------------------------------------------------
    def streifen_an(self):
        return bool(self.app.e.get("status_liste", True))

    def marken(self, b):
        if not self.marken_fn or b is None:
            return []
        return [m for m in km.sortiert(self.marken_fn(b)) if km.sichtbar(self.app.e, self.ort, m[0])]

    # -- Filter -----------------------------------------------------------------------------
    def kennung(self):
        return self.wahl.currentData() if self.wahl is not None else self.filter[0][0]

    def aktiv(self):
        return bool(self.such.text().strip()) or self.kennung() != self.filter[0][0]

    def passt(self, b):
        if not listing.such_passt(b, self.such.text().strip().casefold()):
            return False
        pruefung = next((p for k, __, p in self.filter if k == self.kennung()), None)
        return pruefung is None or bool(pruefung(b))

    def setzen(self, kennung=None, such=None):
        self._still = True
        try:
            if kennung is not None and self.wahl is not None:
                self.wahl.setCurrentIndex(max(0, self.wahl.findData(kennung)))
            if such is not None:
                self.such.setText(such)
        finally:
            self._still = False
        self._geaendert()

    def zuruecksetzen(self):
        if self.aktiv():
            self.setzen(self.filter[0][0], "")

    def _geaendert(self, *a):
        if not self._still:
            self.fuellen(self.alle)

    # -- Liste ------------------------------------------------------------------------------
    def fuellen(self, buecher, vorher=None):
        mehr = [b.schluessel for b in self.ausgewaehlt()] if self.mehrfach else []
        self.alle = list(buecher)
        vorher = vorher if vorher is not None else self._buch
        if vorher is not None and vorher not in self.alle:    # nach Neu einlesen/Speichern: gleiches Buch neu
            vorher = next((b for b in self.alle if b.schluessel == vorher.schluessel), None)
        sichtbar = [b for b in self.alle if self.passt(b)]
        self.liste.blockSignals(True)
        self.liste.clear()
        for b in sichtbar:
            it = QListWidgetItem(listing.anzeigename(b))
            it.setData(Qt.UserRole, b)
            self.liste.addItem(it)
        self.liste.blockSignals(False)
        self.kopf.setText(_("Books: {n} of {gesamt}").format(n=len(sichtbar), gesamt=len(self.alle))
                          if self.aktiv() else _("Books:"))
        ziel = listing.nachfolger(self.alle, vorher, self.passt) if vorher is not None else None
        if ziel is None and vorher is not None and sichtbar:
            ziel = sichtbar[0]
        self._setzen_auf(ziel)
        if len(mehr) > 1:
            self._markieren(set(mehr), "schluessel")

    def _markieren(self, kennungen, attr=None):
        """Einträge mit diesen Büchern (bzw. Schlüsseln) zusätzlich wählen, ohne das aktuelle zu ändern."""
        self.liste.blockSignals(True)
        for i in range(self.liste.count()):
            it = self.liste.item(i)
            b = it.data(Qt.UserRole)
            if (getattr(b, attr) if attr else id(b)) in kennungen:
                it.setSelected(True)
        self.liste.blockSignals(False)
        self.mehrere.emit(self.ausgewaehlt())

    def ausgewaehlt(self):
        if not self.mehrfach:
            return [self._buch] if self._buch is not None else []
        return [self.liste.item(i).data(Qt.UserRole) for i in range(self.liste.count())
                if self.liste.item(i).isSelected()]

    def mehrere_waehlen(self, buecher):
        buecher = [b for b in buecher if b in self.alle]
        if not buecher:
            return
        if any(self._eintrag(b) is None for b in buecher) and self.aktiv():
            self._still = True
            self.such.clear()
            if self.wahl is not None:
                self.wahl.setCurrentIndex(0)
            self._still = False
            self.fuellen(self.alle, buecher[0])
        self._setzen_auf(buecher[0])
        if self.mehrfach and len(buecher) > 1:
            self._markieren({id(b) for b in buecher})

    def _auswahl_mehr(self):
        self.mehrere.emit(self.ausgewaehlt())

    def _setzen_auf(self, b):
        it = self._eintrag(b)
        self.liste.blockSignals(True)
        if self.mehrfach:                       # sonst bleibt eine Mehrfachauswahl stehen, wenn it schon aktuell ist
            self.liste.clearSelection()
        self.liste.setCurrentItem(it)
        if it is not None and self.mehrfach:
            it.setSelected(True)
        if it is not None:
            self.liste.scrollToItem(it)
        self.liste.blockSignals(False)
        self._buch = b if it is not None else None
        self.gewaehlt.emit(self._buch)

    def _eintrag(self, b):
        if b is None:
            return None
        for i in range(self.liste.count()):
            if self.liste.item(i).data(Qt.UserRole) is b:
                return self.liste.item(i)
        return None

    def waehlen(self, b):
        if self._eintrag(b) is None and self.aktiv() and b in self.alle:
            self._still = True
            self.such.clear()
            if self.wahl is not None:
                self.wahl.setCurrentIndex(0)
            self._still = False
            self.fuellen(self.alle, b)
            return
        if self._eintrag(b) is not None:
            self._setzen_auf(b)

    def _auswahl(self, it, __):
        self._buch = it.data(Qt.UserRole) if it else None
        self.gewaehlt.emit(self._buch)

    def aktuell(self):
        return self._buch

    def fokus(self):
        self.such.setFocus()
        self.such.selectAll()

    def neu_zeichnen(self):
        self.liste.viewport().update()

    def tipp(self, it):
        b = it.data(Qt.UserRole)
        teile = []
        name = it.text()
        rect = self.liste.visualItemRect(it)
        breite = rect.width() - self.liste.itemDelegate().breite(b) - 8
        if QFontMetrics(self.liste.font()).horizontalAdvance(name) > breite:
            teile.append(name)
        teile += [t for __, t in self.marken(b)]
        return "\n".join(teile)

    def zustand(self):
        return {"such": self.such.text(), "filter": self.kennung(), "buch": self._buch}

    def wiederherstellen(self, z):
        self._still = True
        self.such.setText(z.get("such") or "")
        if self.wahl is not None:
            self.wahl.setCurrentIndex(max(0, self.wahl.findData(z.get("filter"))))
        self._still = False
        self._buch = z.get("buch")
