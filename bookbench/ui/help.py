# -*- coding: utf-8 -*-
"""
help.py - Hilfefenster (Qt): Suche und Gliederung links, Text rechts, Zurück, Pfad über dem Text.
Die Texte stehen in ui/help_topics.py; Auszeichnung: **fett**, Aufzählungen mit "-", [[kennung]] als
Verweis (anklickbar, zeigt den Titel des Ziels).

  HilfeFenster(app)   zeige(kennung) springt hin; aktuelles_thema()

Der Text wird als HTML in einen QTextBrowser gesetzt; Verweise sind Links "thema:<kennung>", die das
Fenster selbst auswertet (setOpenLinks(False)). Suchtreffer bekommen einen gelben Hintergrund.
"""
import html
import re

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QKeySequence, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter, QTextBrowser,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from bookbench.i18n import _, ngettext
from bookbench.ui import help_topics as ht
from bookbench.ui import theme
from bookbench.version import PROGRAMM

TREFFER = {"hell": "#f5d76e", "dunkel": "#7a6420"}


class HilfeFenster(QDialog):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.setWindowTitle(f"{PROGRAMM} - " + _("Help"))
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(980, 620)
        self.setMinimumSize(640, 380)
        self.themen = ht.themen()
        self.titel = {k: t for __, k, t, __ in self.themen}
        self.eltern = {k: e for e, k, __, __ in self.themen}
        self.verlauf = []
        self._aktuell = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        teiler = QSplitter(Qt.Horizontal)
        lay.addWidget(teiler)

        links = QWidget()
        ll = QVBoxLayout(links)
        ll.setContentsMargins(0, 0, 0, 0)
        z = QHBoxLayout()
        z.addWidget(QLabel(_("Search:")))
        self.suche = QLineEdit()
        self.suche.setClearButtonEnabled(True)
        z.addWidget(self.suche, 1)
        ll.addLayout(z)
        self.baum = QTreeWidget()
        self.baum.setHeaderHidden(True)
        self.baum.setUniformRowHeights(True)
        ll.addWidget(self.baum, 1)
        self.treffer_text = QLabel("")
        self.treffer_text.setProperty("rolle", "hinweis")
        ll.addWidget(self.treffer_text)
        teiler.addWidget(links)

        rechts = QWidget()
        rl = QVBoxLayout(rechts)
        rl.setContentsMargins(0, 0, 0, 0)
        oben = QHBoxLayout()
        self.zurueck_knopf = QPushButton("← " + _("Back"))
        self.zurueck_knopf.setEnabled(False)
        self.zurueck_knopf.clicked.connect(self.zurueck)
        oben.addWidget(self.zurueck_knopf)
        self.pfad = QLabel("")
        self.pfad.setProperty("rolle", "hinweis")
        oben.addWidget(self.pfad, 1)
        rl.addLayout(oben)
        self.text = QTextBrowser()
        self.text.setOpenLinks(False)
        self.text.anchorClicked.connect(self._link)
        rl.addWidget(self.text, 1)
        teiler.addWidget(rechts)
        teiler.setSizes([290, 690])
        teiler.setStretchFactor(1, 1)

        self._baum_fuellen()
        self.baum.currentItemChanged.connect(lambda it, __: self._anzeigen())
        self.suche.textChanged.connect(self._suchen)
        self.suche.returnPressed.connect(self._erster_treffer)
        QShortcut(QKeySequence("Alt+Left"), self, activated=self.zurueck)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: (self.suche.setFocus(), self.suche.selectAll()))
        self.farben()

    # -- Gliederung ---------------------------------------------------------------------------
    def _baum_fuellen(self, nur=None):
        self.baum.blockSignals(True)
        self.baum.clear()
        self.eintraege = {}
        for eltern, kennung, titel, __ in self.themen:
            if nur is not None and kennung not in nur:
                continue
            oben = self.eintraege.get(eltern) if nur is None else None
            it = QTreeWidgetItem(oben or self.baum, [titel])
            it.setData(0, Qt.UserRole, kennung)
            self.eintraege[kennung] = it
            if nur is None and not eltern:
                it.setExpanded(True)
        self.baum.blockSignals(False)

    def farben(self):
        f = theme.farben()
        self.text.document().setDefaultStyleSheet(
            f"a {{ color: {f['akzent']}; }} h2 {{ margin-bottom: 8px; }} li {{ margin-bottom: 2px; }}")
        if self._aktuell:
            self._anzeigen(merken=False)

    # -- Suche --------------------------------------------------------------------------------
    def _suchen(self):
        such = self.suche.text().strip().casefold()
        if not such:
            self._baum_fuellen()
            self.treffer_text.setText("")
            if self.verlauf:
                self.zeige(self.verlauf[-1], merken=False)
            return
        woerter = such.split()
        treffer = [k for __, k, t, x in self.themen
                   if all(w in (t + " " + ht.klartext(x, self.titel)).casefold() for w in woerter)]
        self._baum_fuellen(set(treffer))
        self.treffer_text.setText(ngettext("{n} topic found", "{n} topics found", len(treffer)).format(n=len(treffer))
                                  if treffer else _("Nothing found."))
        if treffer:
            ziel = self._aktuell if self._aktuell in treffer else treffer[0]
            self.baum.blockSignals(True)
            self.baum.setCurrentItem(self.eintraege[ziel])
            self.baum.blockSignals(False)
            self._anzeigen(merken=False)

    def _erster_treffer(self):
        if self.baum.topLevelItemCount():
            self.baum.setCurrentItem(self.baum.topLevelItem(0))
            self.baum.setFocus()

    # -- Anzeige ------------------------------------------------------------------------------
    def aktuelles_thema(self):
        return self._aktuell

    def zeige(self, thema, merken=True):
        if thema not in self.titel:                      # z. B. einst_allgemein: Gruppen ohne eigenes Thema
            thema = "einstellungen" if thema.startswith("einst_") else self.themen[0][1]
        if self.suche.text() and thema not in self.eintraege:
            self.suche.blockSignals(True)
            self.suche.clear()
            self.suche.blockSignals(False)
            self._baum_fuellen()
            self.treffer_text.setText("")
        it = self.eintraege.get(thema)
        if it is None:
            return
        self._merken = merken
        self.baum.blockSignals(True)
        self.baum.setCurrentItem(it)
        self.baum.blockSignals(False)
        self.baum.scrollToItem(it)
        self._anzeigen(merken)

    def zurueck(self):
        if len(self.verlauf) > 1:
            self.verlauf.pop()
            self.zeige(self.verlauf.pop())

    def _link(self, url: QUrl):
        if url.scheme() == "thema":
            self.zeige(url.path())

    def _pfad(self, kennung):
        teile, k = [], self.eltern.get(kennung)
        while k:
            teile.insert(0, self.titel.get(k, k))
            k = self.eltern.get(k)
        return " › ".join(teile)

    def html(self, kennung):
        """HTML eines Themas (Überschrift, Absätze, Aufzählungen, fett, Verweise)."""
        thema = next(t for t in self.themen if t[1] == kennung)
        __, __, titel, text = thema
        teile, liste = [f"<h2>{html.escape(titel)}</h2>"], False
        for zeile in text.strip("\n").split("\n"):
            punkt = zeile.startswith("- ")
            if punkt and not liste:
                teile.append("<ul>")
                liste = True
            elif not punkt and liste:
                teile.append("</ul>")
                liste = False
            inhalt = self._inline(zeile[2:] if punkt else zeile)
            if punkt:
                teile.append(f"<li>{inhalt}</li>")
            elif zeile.strip():
                teile.append(f"<p>{inhalt}</p>")
        if liste:
            teile.append("</ul>")
        return "\n".join(teile)

    def _inline(self, zeile):
        erg = []
        for i, teil in enumerate(re.split(r"\*\*(.+?)\*\*", zeile)):
            stuecke = []
            for j, stueck in enumerate(ht.VERWEIS.split(teil)):
                if j % 2:
                    stuecke.append(f'<a href="thema:{stueck}">{html.escape(self.titel.get(stueck, stueck))}</a>')
                else:
                    stuecke.append(html.escape(stueck))
            s = "".join(stuecke)
            erg.append(f"<b>{s}</b>" if i % 2 else s)
        return "".join(erg)

    def _anzeigen(self, merken=None):
        it = self.baum.currentItem()
        if it is None:
            return
        kennung = it.data(0, Qt.UserRole)
        merken = getattr(self, "_merken", True) if merken is None else merken
        if merken and (not self.verlauf or self.verlauf[-1] != kennung):
            self.verlauf.append(kennung)
        self._merken = True
        self._aktuell = kennung
        self.zurueck_knopf.setEnabled(len(self.verlauf) > 1)
        self.pfad.setText(self._pfad(kennung))
        self.text.setHtml(self.html(kennung))
        self._markieren()

    def _markieren(self):
        """Suchwörter gelb hinterlegen (ExtraSelections: ändern den Text nicht) und zum ersten springen."""
        doc = self.text.document()
        sel, erster = [], None
        farbe = TREFFER[theme.modus()]
        for w in self.suche.text().strip().split():
            c = QTextCursor(doc)
            while True:
                c = doc.find(w, c, QTextDocument.FindFlag(0))
                if c.isNull():
                    break
                ex = QTextBrowser.ExtraSelection()
                ex.cursor = c
                ex.format.setBackground(QColor(farbe))
                sel.append(ex)
                if erster is None or c.position() < erster.position():
                    erster = QTextCursor(c)
        self.text.setExtraSelections(sel)
        if erster is not None:
            erster.clearSelection()                       # sonst überdeckt die Auswahl das Gelb
            self.text.setTextCursor(erster)
            self.text.ensureCursorVisible()
        else:
            self.text.moveCursor(QTextCursor.Start)
