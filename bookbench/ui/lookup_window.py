# -*- coding: utf-8 -*-
"""
lookup_window.py - Fenster „Metadaten nachschlagen“ (seit 2.3-beta2), wie Calibres „Metadaten herunterladen“.
Logik in core/meta_lookup.py.

Oben die Suche (Titel, Autor, ISBN, Sprache), vorbelegt aus dem Buch; links die Treffer von Google Books und Open
Library mit kleinem Cover, rechts je Feld Aktuell ↔ Treffer mit Haken, darunter Klappentext und Cover. Vorbelegt
sind nur die Haken, wo das Buch nichts hat; was schon steht, wird nur auf Wunsch überschrieben.
Übernehmen trägt die angehakten Werte wie das Formular ein (gelb, Strg+S speichert), den Klappentext als
übernommen, das Cover über die Cover-Tafel (Format und Größe wie dort eingestellt).

Mehrere Bücher: Durchlauf - „Übernehmen und weiter“ (Strg+Enter) bzw. „Überspringen“ geht zum nächsten.
Sprache „wie das Buch“ ist die Vorgabe aus Einstellungen > Bücher > Klappentexte; eine andere Sprache als die des
Buchs sucht ohne ISBN und nur Ausgaben in dieser Sprache.

  NachschlagFenster(app, bereich, buecher)      bereich = MetadatenBereich; open() zeigt es (modal, nicht blockierend)
"""
from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from bookbench.core import markers as km
from bookbench.core import meta_lookup as kml
from bookbench.core import metadata as kme
from bookbench.i18n import _, ngettext
from bookbench.ui import threads

FELDER = ("titel", "autoren", "verlag", "datum", "sprache", "isbn", "schlagwoerter")
KLAPPENTEXT, COVER, UNTERTITEL = "_klappentext", "_cover", "_untertitel"
VORSCHAU = QSize(46, 70)


def _pixmap(daten, groesse=VORSCHAU):
    p = QPixmap()
    if daten and p.loadFromData(daten):
        return p.scaled(groesse, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return None


def untertitel_feld(e):
    """Eigenes Feld für den Untertitel (Suchname mit subtitle/untertitel), sonst None."""
    for spalte, name in km.meta_eigene(e):
        if any(w in (spalte + " " + name).casefold() for w in ("subtitle", "untertitel")):
            return spalte
    return None


class NachschlagFenster(QDialog):
    def __init__(self, app, bereich, buecher):
        super().__init__(app)
        self.app, self.bereich = app, bereich
        self.buecher = [b for b in buecher if not b.fehler]
        self.i = 0
        self.treffer = []
        self.lauf = 0                       # Nummer der Suche; ältere Ergebnisse werden verworfen
        self.erledigt = 0
        self.zeilen = []                    # [(Kennung, Feld oder None)] der Vergleichstabelle
        self.setWindowTitle(_("Look up metadata"))
        self.setModal(True)
        self.resize(1100, 680)
        lay = QVBoxLayout(self)
        self.kopf = QLabel("")
        self.kopf.setProperty("rolle", "abschnitt")
        lay.addWidget(self.kopf)

        r = QGridLayout()
        self.titel, self.autor, self.isbn = QLineEdit(), QLineEdit(), QLineEdit()
        r.addWidget(QLabel(_("Title:")), 0, 0)
        r.addWidget(self.titel, 0, 1)
        r.addWidget(QLabel(_("Author:")), 0, 2)
        r.addWidget(self.autor, 0, 3)
        r.addWidget(QLabel("ISBN:"), 1, 0)
        self.isbn.setMaximumWidth(180)
        r.addWidget(self.isbn, 1, 1, Qt.AlignLeft)
        r.addWidget(QLabel(_("Language:")), 1, 2)
        z = QHBoxLayout()
        self.sprache = QComboBox()
        z.addWidget(self.sprache)
        self.k_suchen = QPushButton(_("Search"))
        self.k_suchen.clicked.connect(self.suchen)
        z.addWidget(self.k_suchen)
        z.addStretch(1)
        r.addLayout(z, 1, 3)
        r.setColumnStretch(1, 1)
        r.setColumnStretch(3, 1)
        lay.addLayout(r)
        for w in (self.titel, self.autor, self.isbn):
            w.returnPressed.connect(self.suchen)
        self.sprache.currentIndexChanged.connect(lambda *a: self._sprache_hinweis())
        self.sprach_hinweis = QLabel("")
        self.sprach_hinweis.setProperty("rolle", "hinweis")
        lay.addWidget(self.sprach_hinweis)

        teiler = QSplitter(Qt.Horizontal)
        self.liste = QListWidget()
        self.liste.setIconSize(VORSCHAU)
        self.liste.setSpacing(2)
        self.liste.currentRowChanged.connect(self._treffer_gewaehlt)
        teiler.addWidget(self.liste)
        rechts = QWidget()
        rl = QVBoxLayout(rechts)
        rl.setContentsMargins(6, 0, 0, 0)
        self.tabelle = QTableWidget(0, 4)
        self.tabelle.setHorizontalHeaderLabels(["", _("Field"), _("Now"), _("Hit")])
        self.tabelle.verticalHeader().hide()
        self.tabelle.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabelle.setSelectionMode(QAbstractItemView.NoSelection)
        self.tabelle.setWordWrap(True)
        k = self.tabelle.horizontalHeader()
        k.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        k.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        k.setSectionResizeMode(2, QHeaderView.Stretch)
        k.setSectionResizeMode(3, QHeaderView.Stretch)
        self.tabelle.setIconSize(VORSCHAU)
        self.tabelle.cellClicked.connect(self._zelle)
        rl.addWidget(self.tabelle, 1)
        self.k_link = QPushButton(_("Open the hit's page"))
        self.k_link.clicked.connect(self._link)
        z = QHBoxLayout()
        z.addWidget(self.k_link)
        z.addStretch(1)
        rl.addLayout(z)
        teiler.addWidget(rechts)
        teiler.setSizes([360, 740])
        lay.addWidget(teiler, 1)
        hinweis = QLabel(_("Ticked values are applied like the form (yellow, Ctrl+S saves). Only fields the book "
                           "lacks are ticked at first; click a row to tick or untick it."))
        hinweis.setProperty("rolle", "hinweis")
        hinweis.setWordWrap(True)
        lay.addWidget(hinweis)

        unten = QHBoxLayout()
        self.stand = QLabel("")
        self.stand.setWordWrap(True)
        unten.addWidget(self.stand, 1)
        self.k_weiter = QPushButton(_("Skip"))
        self.k_weiter.clicked.connect(self.ueberspringen)
        unten.addWidget(self.k_weiter)
        self.k_ok = QPushButton("")
        self.k_ok.setDefault(False)
        self.k_ok.setAutoDefault(False)
        self.k_ok.clicked.connect(self.uebernehmen)
        unten.addWidget(self.k_ok)
        k = QPushButton(_("Close"))
        k.setAutoDefault(False)
        k.clicked.connect(self.close)
        unten.addWidget(k)
        lay.addLayout(unten)
        for taste in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(taste), self, activated=self.uebernehmen)
        mehrere = len(self.buecher) > 1
        self.k_weiter.setVisible(mehrere)
        self.k_ok.setText(_("Apply and next") if mehrere else _("Apply"))
        self.buch_zeigen()

    # ================================================================ Buch und Suche
    def buch(self):
        return self.buecher[self.i] if 0 <= self.i < len(self.buecher) else None

    def buch_zeigen(self):
        b = self.buch()
        if b is None:
            self.close()
            return
        w = km.meta_aktuell(b)
        if len(self.buecher) > 1:
            self.kopf.setText(_("Book {i} of {n}: {name}").format(i=self.i + 1, n=len(self.buecher), name=b.titel))
        else:
            self.kopf.setText(b.titel)
        self.titel.setText(w.get("titel", "") or b.titel)
        self.autor.setText(kme.liste(w.get("autoren", "") or b.autor)[0] if (w.get("autoren") or b.autor) else "")
        self.isbn.setText(w.get("isbn", ""))
        buchsprache = kme.sprache_kurz(w.get("sprache", "") or b.sprache or "").split("-")[0]
        self.sprache.blockSignals(True)
        self.sprache.clear()
        for k, text in kml.SPRACHEN:
            name = _(text)
            if k == "buch":
                name += f" ({buchsprache})" if buchsprache else ""
            self.sprache.addItem(name, k)
        vorgabe = self.app.e.get("nachschlag_sprache", "buch")
        self.sprache.setCurrentIndex(max(0, self.sprache.findData(vorgabe)))
        self.sprache.blockSignals(False)
        self._sprache_hinweis()
        self.suchen()

    def _sprache(self):
        b = self.buch()
        w = km.meta_aktuell(b) if b else {}
        return kml.sprache_fuer(w.get("sprache", "") or (b.sprache if b else ""), self.sprache.currentData())

    def _sprache_hinweis(self):
        sp, abweichend = self._sprache()
        self.sprach_hinweis.setText(_("Another language than the book's: searched without the ISBN, only editions "
                                      "in this language. Its title may differ - type it above if nothing turns up.")
                                    if abweichend else "")
        self.isbn.setEnabled(not abweichend)

    def suchen(self):
        b = self.buch()
        if b is None:
            return
        self.lauf += 1
        lauf = self.lauf
        titel, autor, isbn = self.titel.text().strip(), self.autor.text().strip(), self.isbn.text().strip()
        sp, abweichend = self._sprache()
        self.treffer = []
        self.liste.clear()
        self.tabelle.setRowCount(0)
        self._knoepfe()
        self.stand.setText(_("Searching …"))
        from bookbench.core import blurb_lookup as kbl
        kbl.einstellungen_anwenden(self.app.e)                # eigener Google-Schlüssel

        def arbeit():
            bericht = []
            erg = kml.suchen(titel, autor, isbn, sp, abweichend, bericht=bericht)
            threads.im_hauptthread(lambda: self._gefunden(lauf, erg, bericht))
            for i, t in enumerate(erg):
                daten = kml.bild_laden(t.get("vorschau"))
                if daten:
                    threads.im_hauptthread(lambda i=i, d=daten: self._vorschau(lauf, i, d))
        threads.starten(arbeit)

    def _gefunden(self, lauf, erg, bericht):
        if lauf != self.lauf:
            return
        self.treffer = erg
        for t in erg:
            w = t["werte"]
            zeile2 = ", ".join(x for x in (w.get("verlag"), w.get("datum"), w.get("sprache")) if x)
            it = QListWidgetItem(f"{w.get('titel') or '?'}\n{w.get('autoren', '')}\n{zeile2}  ·  {t['quelle']}")
            it.setToolTip(t.get("link", ""))
            it.setSizeHint(QSize(0, VORSCHAU.height() + 8))
            self.liste.addItem(it)
        teile = []
        for name, n, fehler in bericht:
            teile.append(f"{name}: " + (fehler if fehler else ngettext("{n} hit", "{n} hits", n).format(n=n)))
        self.stand.setText("; ".join(teile) + ("." if teile else "") +
                           ("" if erg else " " + _("Change title or author, or try another language.")))
        if erg:
            self.liste.setCurrentRow(0)
        self._knoepfe()

    def _vorschau(self, lauf, i, daten):
        if lauf != self.lauf or i >= self.liste.count():
            return
        p = _pixmap(daten)
        if p is not None:
            self.liste.item(i).setIcon(QIcon(p))
            self.treffer[i]["vorschau_daten"] = daten
            if i == self.liste.currentRow():
                self._cover_zelle()

    # ================================================================ Vergleich
    def aktueller_treffer(self):
        i = self.liste.currentRow()
        return self.treffer[i] if 0 <= i < len(self.treffer) else None

    def _felder(self):
        felder = [f for f in FELDER if f in km.meta_felder(self.app.e)]
        ut = untertitel_feld(self.app.e)
        return felder, ut

    def _treffer_gewaehlt(self, *a):
        b, t = self.buch(), self.aktueller_treffer()
        self.tabelle.setRowCount(0)
        self.zeilen = []
        if b is None or t is None:
            self._knoepfe()
            return
        jetzt = km.meta_aktuell(b)
        felder, ut = self._felder()
        reihen = [(f, f, km.meta_name(f, self.app.e), jetzt.get(f, ""), t["werte"].get(f, "")) for f in felder]
        if ut:
            reihen.insert(1, (UNTERTITEL, ut, km.meta_name(ut, self.app.e), jetzt.get(ut, ""), t.get("untertitel", "")))
        kt_jetzt = km.klappentext_aktuell(b).strip()
        reihen.append((KLAPPENTEXT, None, _("Blurb"), kt_jetzt, t.get("klappentext", "")))
        reihen.append((COVER, None, _("Cover"), "", t.get("cover", "")))
        kt_min = int(self.app.e.get("kt_min", 80))
        for kennung, feld, name, alt, neu in reihen:
            z = self.tabelle.rowCount()
            self.tabelle.insertRow(z)
            self.zeilen.append((kennung, feld))
            haken = QTableWidgetItem()
            gleich = bool(neu) and feld is not None and kme.gleich(feld, alt, neu)
            if kennung == COVER:
                an = bool(neu) and km.cover_fehlt(b)
            elif kennung == KLAPPENTEXT:
                an = bool(neu) and not alt and len(neu) >= kt_min
            else:
                an = bool(neu) and not kme._norm(alt) and not gleich
            haken.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled if neu and not gleich else Qt.NoItemFlags)
            haken.setCheckState(Qt.Checked if an else Qt.Unchecked)
            self.tabelle.setItem(z, 0, haken)
            self.tabelle.setItem(z, 1, QTableWidgetItem(name))
            if kennung in (KLAPPENTEXT,):
                a, n = self._kurz(alt), self._kurz(neu)
            else:
                a, n = alt, neu
            ia, ineu = QTableWidgetItem(a or "–"), QTableWidgetItem((n or "–") + ("  (=)" if gleich else ""))
            if kennung == KLAPPENTEXT:
                ia.setToolTip(self._tipp(alt))
                ineu.setToolTip(self._tipp(neu))
            self.tabelle.setItem(z, 2, ia)
            self.tabelle.setItem(z, 3, ineu)
        self._cover_zelle()
        self.tabelle.resizeRowsToContents()
        self._knoepfe()

    @staticmethod
    def _kurz(text, n=220):
        text = " ".join((text or "").split())
        return text if len(text) <= n else text[:n].rstrip() + " …"

    @staticmethod
    def _tipp(text):
        import html
        return "<p>" + html.escape(text or "").replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>" if text else ""

    def _cover_zelle(self):
        b, t = self.buch(), self.aktueller_treffer()
        z = next((i for i, (k, __) in enumerate(self.zeilen) if k == COVER), None)
        if z is None or b is None or t is None:
            return
        alt = self.bereich.cover.aktuelle_bytes(b) if hasattr(self.bereich, "cover") else None
        pa = _pixmap(alt)
        ia = self.tabelle.item(z, 2)
        if pa is not None:
            ia.setIcon(QIcon(pa))
            ia.setText(f"{b.cover_info[0]} × {b.cover_info[1]}" if b.cover_info else "")
        pn = _pixmap(t.get("vorschau_daten"))
        if pn is not None:
            self.tabelle.item(z, 3).setIcon(QIcon(pn))
            self.tabelle.item(z, 3).setText(_("from {quelle}").format(quelle=t["quelle"]))
        self.tabelle.setRowHeight(z, VORSCHAU.height() + 6)

    def _zelle(self, zeile, spalte):
        it = self.tabelle.item(zeile, 0)
        if it is not None and spalte != 0 and it.flags() & Qt.ItemIsUserCheckable:
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)

    def angehakt(self):
        return [self.zeilen[z] for z in range(self.tabelle.rowCount())
                if self.tabelle.item(z, 0) and self.tabelle.item(z, 0).checkState() == Qt.Checked]

    def haken_setzen(self, kennung, an=True):
        """Für Tests und Tastatur: Haken einer Zeile (Feld oder _klappentext/_cover/_untertitel) setzen."""
        for z, (k, __) in enumerate(self.zeilen):
            if k == kennung and self.tabelle.item(z, 0).flags() & Qt.ItemIsUserCheckable:
                self.tabelle.item(z, 0).setCheckState(Qt.Checked if an else Qt.Unchecked)

    def _knoepfe(self):
        self.k_ok.setEnabled(self.aktueller_treffer() is not None)
        self.k_link.setEnabled(bool(self.aktueller_treffer() and self.aktueller_treffer().get("link")))

    def _link(self):
        t = self.aktueller_treffer()
        if t and t.get("link"):
            QDesktopServices.openUrl(QUrl(t["link"]))

    # ================================================================ Übernehmen
    def uebernehmen(self):
        b, t = self.buch(), self.aktueller_treffer()
        if b is None or t is None:
            return
        gewaehlt = self.angehakt()
        if gewaehlt:
            werte = km.meta_aktuell(b)
            geaendert = False
            for kennung, feld in gewaehlt:
                if kennung == UNTERTITEL:
                    werte[feld], geaendert = t.get("untertitel", ""), True
                elif feld is not None:
                    werte[feld], geaendert = t["werte"].get(feld, ""), True
            if geaendert:
                self.bereich.uebernehmen(b, werte, mit_klappentext=False)
            if any(k == KLAPPENTEXT for k, __ in gewaehlt) and t.get("klappentext"):
                b.klappentext_entwurf = None
                b.klappentext_neu = None if t["klappentext"].strip() == b.klappentext.strip() else t["klappentext"].strip()
                b.klappentext_quelle = t.get("link", "") or t["quelle"]
                self.app.buch_geaendert(b)
            if any(k == COVER for k, __ in gewaehlt) and t.get("cover"):
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    daten = kml.bild_laden(t["cover"]) or t.get("vorschau_daten")
                finally:
                    QApplication.restoreOverrideCursor()
                if daten:
                    self.bereich.cover.einsetzen(b, daten, t["quelle"])
                else:
                    self.app.status.set(f"{b.name}: " + _("the cover could not be downloaded."))
            self.erledigt += 1
        self.app.status.set(f"{b.name}: " + (ngettext("{n} value applied, not yet saved (Ctrl+S).",
                                                       "{n} values applied, not yet saved (Ctrl+S).", len(gewaehlt))
                                              .format(n=len(gewaehlt)) if gewaehlt else _("nothing ticked, unchanged.")))
        self.weiter()

    def ueberspringen(self):
        self.weiter()

    def weiter(self):
        self.i += 1
        if self.i >= len(self.buecher):
            if len(self.buecher) > 1:
                self.app.status.set(ngettext("Look-up done: {erledigt} of {n} book changed, not yet saved (Ctrl+S).",
                                             "Look-up done: {erledigt} of {n} books changed, not yet saved (Ctrl+S).",
                                             len(self.buecher)).format(erledigt=self.erledigt, n=len(self.buecher)))
            self.close()
            return
        self.buch_zeigen()

    def closeEvent(self, ev):
        self.lauf += 1                                    # laufende Suchen verwerfen
        if self.bereich.seite is not None:
            self.bereich.anzeigen()
        super().closeEvent(ev)
