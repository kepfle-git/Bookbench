# -*- coding: utf-8 -*-
"""
app.py - Hauptfenster von Bookbench (Qt, seit 2.0; die Tk-Fassung bis 1.4 liegt in bookbench/tk/).
Gestaltung nach dem Designleitfaden des Keller-Nietprogramm-Tools, Seitenleiste nach 5a.

  Menüleiste     Datei, (Bereichsmenüs), Ansicht, Hilfe
  Werkzeugleiste links die Aktionen des aktuellen Bereichs, rechts Öffnen, Neu einlesen, Speichern, Hilfe
  Seitenleiste   ui/sidebar.py, Marken je Bereich (core/markers, ui/markers)
  Hinweisleiste  nur sichtbar, wenn der geöffnete Ordner nicht mehr da ist
  Statuszeile    kurze Rückmeldungen (self.status.set(text) wie im Tk-Programm)

Zustand und Oberfläche sind getrennt: App hält Bücher, Ordner, Einstellungen und die Bereichs-
Objekte (ui/area.py); oberflaeche_bauen() baut Menü, Werkzeugleiste und Seiten neu und kann jederzeit
wieder aufgerufen werden - so wirkt ein Sprachwechsel sofort, ohne Neustart und ohne dass offene
Änderungen verloren gehen.

Langsames läuft im Hilfsthread (hintergrund(); ui/threads.py), die Oberfläche fasst nur der
Hauptthread an.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from bookbench.i18n import N_, _, ngettext  # noqa: E402  (zuerst: legt die Sprache fest)
from bookbench import i18n

from PySide6.QtCore import QEvent, QLibraryInfo, QLocale, QObject, QSize, Qt, QTimer, QTranslator
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QSizePolicy, QStackedWidget, QToolBar, QToolButton, QVBoxLayout, QWidget)

from bookbench.core import blurbs
from bookbench.core import library as kd
from bookbench.core import markers as km
from bookbench.core import settings as kei
from bookbench.preview import emulator as kv
from bookbench.ui import area as kar
from bookbench.ui import area_chapters as kch
from bookbench.ui import area_library as kbi
from bookbench.ui import area_device as kdev
from bookbench.ui import area_dictionary as kwo
from bookbench.ui import area_metadata as kme
from bookbench.ui import dialogs
from bookbench.ui import help_topics
from bookbench.ui import markers as kmk
from bookbench.ui import sidebar as ksb
from bookbench.ui import theme
from bookbench.ui import threads
from bookbench.version import PROGRAMM, VERSION

DARSTELLUNGEN = (("hell", N_("Light")), ("dunkel", N_("Dark")), ("system", N_("Like the system")))


class StatusText:
    """Wie die StringVar der Statuszeile im Tk-Programm: status.set(text), status.get()."""

    def __init__(self):
        self.text = ""
        self.label = None

    def set(self, text):
        self.text = text or ""
        if self.label is not None:
            self.label.setText(self.text)

    def get(self):
        return self.text


class TooltipFilter(QObject):
    """Einstellung tooltips aus: Tooltip-Ereignisse im ganzen Programm schlucken."""
    an = True

    def eventFilter(self, obj, ev):
        return ev.type() == QEvent.ToolTip and not self.an


def kuerzel_verteilen(leiste):
    """Alt-Kürzel der Menüleiste ohne Doppelte: jedes Menü bekommt den ersten noch freien Buchstaben
    seiner (übersetzten) Beschriftung (englisch kollidieren sonst „Edit“ und „E-reader“)."""
    vergeben = set()
    for a in leiste.actions():
        text = a.text().replace("&", "")
        for pos, zeichen in enumerate(text):
            if zeichen.isalnum() and zeichen.lower() not in vergeben:
                vergeben.add(zeichen.lower())
                a.setText(text[:pos] + "&" + text[pos:])
                break
        else:
            a.setText(text)


class App(QMainWindow):
    def __init__(self, ordner=None, bereich=None, buch=None, geometrie=None):
        super().__init__()
        self._start_buch = buch
        self._popen = subprocess.Popen           # Tests ersetzen das, um den Neustart abzufangen
        self.e = kei.laden()
        blurbs.GOOGLE_KEY = self.e.get("google_key", "") or ""     # auch fürs Cover-Nachschlagen
        zuletzt = self.e.get("bereich_zuletzt")      # wird beim ersten Bereichswechsel überschrieben
        self.status = StatusText()
        self.status.set(_("Open a folder (Ctrl+O)."))
        self.buecher = []                    # [kd.Buch]
        self.nach_schluessel = {}
        self.ordner = None
        self.calibre_wurzel, self.calibre_eintraege = None, []
        self.entscheidungen = kd.json_laden(kd.ENTSCHEIDUNGEN)
        self.cache = kd.json_laden(kd.KLAPPENTEXT_CACHE)
        self._arbeit = None                  # Name der laufenden Hintergrundarbeit
        self._ordner_weg = False
        self._hilfe = None
        self.tooltips = TooltipFilter(self)
        QApplication.instance().installEventFilter(self.tooltips)
        from bookbench.ui import updates as kup
        self.updates = kup.Updates(self)     # Suche nach neuen Versionen (ui/updates.py)

        # Bereiche: leben so lange wie das Fenster; bis sie umgezogen sind, Platzhalter
        fertig = {"bibliothek": kbi.BibliothekBereich, "kapitel": kch.KapitelBereich,
                  "metadaten": kme.MetadatenBereich, "woerterbuch": kwo.WoerterbuchBereich,
                  "kobo": kdev.EReaderBereich}
        self.bereiche = [fertig[k](self) if k in fertig else kar.Platzhalter(self, k, t, s, beta)
                         for k, t, s, beta in kar.BEREICHE if k != "vorschau" or kv.verfuegbar()]
        self.bibliothek = self.bereich_obj("bibliothek")
        self.kapitel = self.bereich_obj("kapitel")
        self.metadaten = self.bereich_obj("metadaten")
        self.woerterbuch = self.bereich_obj("woerterbuch")
        self.kobo = self.bereich_obj("kobo")
        self.vorschau = None                 # wie im Tk-Programm: None, wo es keine Vorschau gibt
        self._aktuell = "bibliothek"

        self.setWindowIcon(self._programmsymbol())
        self.setMinimumSize(860, 520)
        self._geometrie_setzen(geometrie or self.e.get("fenster") or kei.STANDARD["fenster"])
        self.darstellung = self.e.get("darstellung") or "system"
        theme.anwenden(QApplication.instance(), self.darstellung)
        self._tooltips_anwenden()
        self.oberflaeche_bauen()
        QShortcut(QKeySequence("Ctrl+B"), self, activated=lambda: self.leiste.umschalten())
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.suche_fokus)
        for taste in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(taste), self, activated=self.uebernehmen)
        for i in range(9):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self.leiste.nummer(i))

        start = ordner or (self.e.get("ordner") if self.e.get("start_ordner", True) else None)
        if start and Path(start).is_dir():
            QTimer.singleShot(50, lambda: self.laden(start))
        if not bereich and self.e.get("start_bereich") == "zuletzt":
            bereich = zuletzt
        self.bereich_zeigen(bereich or "bibliothek")
        QTimer.singleShot(4000, self.updates.automatisch)     # nach dem Start, damit das Fenster schon steht

    # ================================================================ Rahmen
    @staticmethod
    def _programmsymbol():
        p = Path(__file__).resolve().parent / "ui" / "bookbench.png"
        return QIcon(str(p)) if p.is_file() else QIcon(theme.seitenleiste("bibliothek", True))

    def _geometrie_setzen(self, text):
        """"1200x760" oder "1200x760+10+20" (Format des Tk-Programms, so bleibt die Einstellung)."""
        try:
            groesse, __, ort = text.partition("+")
            w, h = (int(x) for x in groesse.split("x"))
            self.resize(w, h)
            if ort:
                x, __, y = ort.partition("+")
                self.move(int(x), int(y))
        except (ValueError, AttributeError):
            self.resize(1200, 760)

    def geometrie(self, mit_ort=False):
        g = f"{self.width()}x{self.height()}"
        return g + f"+{self.x()}+{self.y()}" if mit_ort else g

    def bereich_obj(self, kennung):
        return next((b for b in self.bereiche if b.kennung == kennung), None)

    def oberflaeche_bauen(self):
        """Menü, Werkzeugleiste, Seitenleiste und Seiten (neu) aufbauen. Zustand der Bereiche bleibt."""
        zustaende = {b.kennung: b.zustand() for b in self.bereiche if b.seite is not None}
        self._menue()
        self._werkzeugleiste()
        mitte = QWidget()
        aussen = QVBoxLayout(mitte)
        aussen.setContentsMargins(0, 0, 0, 0)
        aussen.setSpacing(0)
        self._hinweisleiste_bauen(aussen)
        innen = QHBoxLayout()
        innen.setContentsMargins(0, 0, 0, 0)
        innen.setSpacing(0)
        aussen.addLayout(innen, 1)
        self.leiste = ksb.Seitenleiste(ausgeklappt=bool(self.e.get("navi_ausgeklappt", True)),
                                       offen=self.e.get("navi_offen") or [])
        self.leiste.gewaehlt.connect(lambda k, kind: self.bereich_zeigen(k, kind or None))
        self.leiste.zustand_geaendert.connect(lambda k, w: self.e.__setitem__("navi_" + k, w))
        innen.addWidget(self.leiste)
        self.stapel = QStackedWidget()
        rand = QWidget()
        rl = QVBoxLayout(rand)
        rl.setContentsMargins(8, 4, 8, 0)
        rl.addWidget(self.stapel)
        innen.addWidget(rand, 1)
        for b in self.bereiche:
            b.seite = b.bauen()
            self.stapel.addWidget(b.seite)
            if b.kennung in zustaende:
                b.wiederherstellen(zustaende[b.kennung])
        self.setCentralWidget(mitte)
        if self.status.label is None:
            self.status.label = QLabel(self.status.get())
            self.status.label.setContentsMargins(6, 2, 6, 2)
            self.statusBar().addWidget(self.status.label, 1)
            self.statusBar().setSizeGripEnabled(True)
        self._ordner_weg_zeigen()
        self.bereich_zeigen(self._aktuell)
        self._zaehler()

    # -- Menü --------------------------------------------------------------------------
    def _menue(self):
        leiste = self.menuBar()
        leiste.clear()
        m = leiste.addMenu(_("File"))
        m.addAction(_("Open folder …"), QKeySequence("Ctrl+O"), self.ordner_oeffnen)
        self._zuletzt = m.addMenu(_("Recently opened"))
        self._zuletzt.aboutToShow.connect(self._zuletzt_fuellen)
        m.addAction(_("Reload"), QKeySequence("F5"), self.neu_einlesen)
        m.addAction(_("Close library"), self.bibliothek_schliessen)
        m.addSeparator()
        m.addAction(_("Save"), QKeySequence("Ctrl+S"), self.speichern)
        m.addSeparator()
        m.addAction(_("Import from Calibre library …"), self.calibre_importieren)
        m.addSeparator()
        m.addAction(_("Settings …"), lambda: self.einstellungen())
        m.addSeparator()
        m.addAction(_("Quit"), self.close)
        b = leiste.addMenu(_("Edit"))
        act = b.addAction(_("Apply"), self.uebernehmen)
        act.setShortcut(QKeySequence("Ctrl+Return"))
        act.setShortcutContext(Qt.WidgetShortcut)           # die Taste fängt der QShortcut im Fenster
        b.addAction(_("Apply all chapter suggestions"), lambda: self.kapitel.alle_uebernehmen())
        b.addSeparator()
        b.addAction(_("Chapters: restore suggestions"), lambda: self._kapitel_aktion("vorschlaege"))
        b.addAction(_("Chapters: restore original"), lambda: self._kapitel_aktion("original"))
        b.addAction(_("Chapters: level up") + "\t" + _("Shift+Tab"), lambda: self._kapitel_aktion("ebene", -1))
        b.addAction(_("Chapters: level down") + "\tTab", lambda: self._kapitel_aktion("ebene", 1))
        b.addSeparator()
        b.addAction(_("Look up blurb"), self.klappentext_nachschlagen)
        b.addAction(_("Look up all missing blurbs"), self.klappentexte_alle)
        b.addSeparator()
        b.addAction(_("Cover from file …"), lambda: self.cover_aktion("aus_datei"))
        b.addAction(_("Look up cover"), lambda: self.cover_aktion("nachschlagen"))
        b.addAction(_("Look up all missing covers"), lambda: self.cover_aktion("alle_ohne"))
        b.addAction(_("Show cover large"), lambda: self.cover_aktion("gross"))
        b.addSeparator()
        b.addAction(_("Take series and blurbs from Calibre"), self.calibre_uebernehmen)
        b.addAction(_("Metadata from Calibre (this book)"), lambda: self.metadaten_aktion("alle_von_calibre"))
        b.addAction(_("Fill metadata gaps from Calibre"), lambda: self.metadaten.luecken_fuellen())
        for b in self.bereiche:
            b.menue(leiste)
        a = leiste.addMenu(_("View"))
        gruppe = QActionGroup(a)
        self._darstellungs_aktionen = {}
        for wert, text in DARSTELLUNGEN:
            act = a.addAction(_(text), lambda w=wert: self.darstellung_setzen(w))
            act.setCheckable(True)
            act.setChecked(self.darstellung == wert)
            gruppe.addAction(act)
            self._darstellungs_aktionen[wert] = act
        a.addSeparator()
        act = a.addAction(_("Sidebar on/off"), lambda: self.leiste.umschalten())
        act.setShortcut(QKeySequence("Ctrl+B"))
        act.setShortcutContext(Qt.WidgetShortcut)           # die Taste fängt der QShortcut im Fenster
        self._schalter_aktion(a, _("Status in the lists"), "status_liste")
        sp = a.addMenu(_("Library columns"))
        sp.aboutToShow.connect(lambda: self.bibliothek.menue_fuellen(sp))
        self._schalter_aktion(a, "Cover", "cover")
        self._schalter_aktion(a, "Tooltips", "tooltips", self._tooltips_anwenden)
        h = leiste.addMenu(_("Help"))
        h.addAction(_("Help"), QKeySequence("F1"), self.hilfe)
        h.addAction(_("Check for updates …"), lambda: self.updates.pruefen(von_hand=True))
        h.addSeparator()
        h.addAction(_("About"), self.ueber)
        kuerzel_verteilen(leiste)

    def _schalter_aktion(self, menue, text, schl, nachher=None):
        act = menue.addAction(text)
        act.setCheckable(True)
        act.setChecked(bool(self.e.get(schl, kei.STANDARD[schl])))

        def umschalten(an):
            self.e[schl] = an
            if nachher:
                nachher()
            self._alles_neu_zeichnen()
        act.toggled.connect(umschalten)
        return act

    def _zuletzt_fuellen(self):
        self._zuletzt.clear()
        for o in self.e.get("letzte_ordner", [])[:8]:
            self._zuletzt.addAction(o, lambda o=o: self._zuletzt_oeffnen(o))
        if not self.e.get("letzte_ordner"):
            self._zuletzt.addAction(_("(empty)")).setEnabled(False)

    def _zuletzt_oeffnen(self, ordner):
        if self._aenderungen_verwerfen_ok():
            self.laden(ordner)

    def ueber(self):
        QMessageBox.about(self, _("About"), f"<b>{PROGRAMM} {VERSION}</b><br><br>" + _(
            "Chapter names, blurbs and settings for KOReader on the e-reader.") + "<br><br>"
            + _("Interface: Qt {qt} (PySide6), style {stil}.").format(
                qt=__import__("PySide6").__version__, stil=theme.stilname()))

    # -- Werkzeugleiste --------------------------------------------------------------------
    def _werkzeugleiste(self):
        """Designleitfaden 2.: links die Aktionen des Bereichs, rechts die globalen Knöpfe - Öffnen,
        Neu einlesen und Speichern gelten für alle Bereiche und stehen deshalb rechts, vor Hilfe."""
        alt = getattr(self, "wz", None)
        if alt is not None:
            self.removeToolBar(alt)
            alt.deleteLater()
        wz = self.wz = QToolBar(_("Toolbar"))
        wz.setObjectName("werkzeugleiste")
        wz.setMovable(False)
        wz.setFloatable(False)
        wz.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        wz.setIconSize(QSize(20, 20))
        wz.setContextMenuPolicy(Qt.PreventContextMenu)
        self.addToolBar(wz)
        self._wz_bereich = []
        abstand = QWidget()
        abstand.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._wz_abstand = wz.addWidget(abstand)
        wz.addSeparator()
        self._wz_global = []
        for eintrag in (
                ("oeffnen", _("Open"), self.ordner_oeffnen, _("Open books folder (Ctrl+O)")),
                ("neu_laden", _("Reload"), self.neu_einlesen, _("Reload folder (F5)")),
                ("speichern", _("Save"), self.speichern, _("Write applied changes to the files, with backup (Ctrl+S)")),
                None,
                ("hilfe", _("Help"), self.hilfe, _("Help for the current area (F1)"))):
            if eintrag is None:
                wz.addSeparator()
                continue
            symbol, text, fn, tipp = eintrag
            act = wz.addAction(theme.symbol(symbol), text, fn)
            act.setToolTip(tipp)
            act.symbol = symbol
            self._wz_global.append(act)

    def _wz_bereich_bauen(self):
        for a in self._wz_bereich:
            self.wz.removeAction(a)
            a.deleteLater()
        self._wz_bereich = []
        b = self.bereich_obj(self._aktuell)
        for eintrag in (b.werkzeug() if b else []):
            if eintrag is None:
                a = QAction(self.wz)
                a.setSeparator(True)
            else:
                symbol, text, fn, tipp = eintrag[:4]
                a = QAction(theme.symbol(symbol), text, self.wz)
                a.symbol = symbol
                a.setToolTip(tipp)
                if len(eintrag) > 4:                     # Knopf mit Menü (z. B. Ergänzen ▾)
                    menue = QMenu(self.wz)
                    for punkt in eintrag[4]:
                        if punkt is None:
                            menue.addSeparator()
                        else:
                            menue.addAction(punkt[0], punkt[1])
                    a.setMenu(menue)
                    a.menue = menue
                else:
                    a.triggered.connect(lambda __=False, fn=fn: fn())
            self.wz.insertAction(self._wz_abstand, a)
            if a.menu() is not None:
                knopf = self.wz.widgetForAction(a)
                if knopf is not None:
                    knopf.setPopupMode(QToolButton.InstantPopup)
            self._wz_bereich.append(a)

    def _symbole_auffrischen(self):
        for a in self._wz_global + self._wz_bereich:
            if getattr(a, "symbol", None):
                a.setIcon(theme.symbol(a.symbol))

    # -- Hinweisleiste -----------------------------------------------------------------------
    def _hinweisleiste_bauen(self, lay):
        """Leiste unter der Werkzeugleiste, nur sichtbar, wenn der geöffnete Ordner nicht mehr da ist
        (ordner_pruefen); Farbe wie Warnzeilen."""
        h = self.hinweisleiste = QFrame()
        h.setObjectName("hinweisleiste")
        hl = QHBoxLayout(h)
        hl.setContentsMargins(8, 4, 8, 4)
        self.hinweis_text = QLabel("")
        self.hinweis_text.setWordWrap(True)
        hl.addWidget(self.hinweis_text, 1)
        k = QPushButton(_("Close library"))
        k.clicked.connect(lambda: self.bibliothek_schliessen())
        hl.addWidget(k)
        rand = QWidget()
        rl = QVBoxLayout(rand)
        rl.setContentsMargins(8, 4, 8, 0)
        rl.addWidget(h)
        self._hinweis_rand = rand
        lay.addWidget(rand)
        self._hinweis_faerben()

    def _hinweis_faerben(self):
        self.hinweisleiste.setStyleSheet(f"QFrame#hinweisleiste {{ background: {theme.WARNZEILE[theme.modus()]}; }}"
                                         f"QFrame#hinweisleiste QLabel {{ color: {theme.farben()['fg']}; }}")

    def ordner_pruefen(self):
        """Ist der geöffnete Ordner noch da? Sonst Hinweisleiste (Bibliothek bleibt sichtbar, Speichern
        verweigert _nicht_erreichbar). Aufgerufen bei jeder Gerätesuche (Bereich E-Reader)."""
        weg = bool(self.ordner) and not self._arbeit and not Path(self.ordner).is_dir()
        if weg == self._ordner_weg:
            return
        self._ordner_weg = weg
        self._ordner_weg_zeigen()
        if not weg and self.ordner:
            self.status.set(_("The folder {ordner} is reachable again.").format(ordner=self.ordner))

    def _ordner_weg_zeigen(self):
        if self._ordner_weg:
            self.hinweis_text.setText("⚠ " + _(
                "The folder {ordner} is no longer reachable (e-reader unplugged?). The library stays visible, "
                "but saving only works again once the folder is back.").format(ordner=self.ordner))
        self._hinweis_rand.setVisible(self._ordner_weg)

    # ================================================================ Bereiche
    def _bereich(self):
        return self._aktuell

    def bereich_zeigen(self, kennung, kind=None):
        alias = {"klappentexte": "metadaten", "cover": "metadaten"}
        kennung = alias.get(kennung, kennung)
        b = self.bereich_obj(kennung) or self.bereiche[0]
        wechsel = b.kennung != self._aktuell
        if wechsel and getattr(self, "kapitel", None) is not None and self.kapitel.seite is not None:
            self.kapitel._bearbeitung_beenden()
        self._aktuell = b.kennung
        self.e["bereich_zuletzt"] = b.kennung
        if b.seite is not None:
            self.stapel.setCurrentWidget(b.seite)
        self.leiste.waehlen(b.kennung, kind)
        self._wz_bereich_bauen()
        if wechsel or kind:
            b.beim_zeigen()

    def oeffnen_ziele(self):
        """[(Kennung, Text)] der Ziele für den Doppelklick in der Bibliothek; Vorschau und KOReader nur,
        wo es die Vorschau gibt."""
        ziele = (("kapitel", N_("Chapters")), ("metadaten", N_("Metadata")), ("vorschau", N_("Preview")),
                 ("koreader", N_("KOReader (start the preview)")))
        return [(k, t) for k, t in ziele if k in ("kapitel", "metadaten") or kv.verfuegbar()]

    # ================================================================ Bücher laden und speichern
    def ordner_oeffnen(self):
        if not self._aenderungen_verwerfen_ok():
            return
        o = dialogs.ordner(self, _("Open books folder"), self.e.get("ordner") or str(Path.home()))
        if o:
            self.laden(o)

    def neu_einlesen(self):
        if self.ordner and self._aenderungen_verwerfen_ok():
            self.laden(self.ordner)

    def laden(self, ordner):
        if self._arbeit:
            self.status.set(_("Still running: {arbeit}.").format(arbeit=self._arbeit))
            return
        ordner = str(Path(ordner))
        self.ordner = ordner
        self.e["ordner"] = ordner
        letzte = [o for o in self.e.get("letzte_ordner", []) if o != ordner]
        self.e["letzte_ordner"] = [ordner] + letzte[:7]
        self._arbeit = _("Reading")
        self.buecher, self.nach_schluessel = [], {}
        self._alles_neu_zeichnen()
        einst = (self.e["max_sub"], self.e["caps"], dict(self.entscheidungen), self.e["sicherungsordner"])
        calibre = bool(self.e.get("calibre_an", True))

        def arbeit():
            dateien = kd.buecher_finden(ordner, ausnehmen=[einst[3]])
            ergebnis = []
            for i, f in enumerate(dateien, 1):
                if i % 5 == 1:
                    text = _("Reading books … {i}/{n}").format(i=i, n=len(dateien))
                    threads.im_hauptthread(lambda t=text: self.status.set(t))
                ergebnis.append(kd.buch_laden(f, einst[0], einst[1], einst[2]))
            wurzel, eintraege = kd.calibre_finden(ordner) if calibre else (None, [])
            kd.calibre_zuordnen(ergebnis, wurzel, eintraege)
            threads.im_hauptthread(lambda: self._geladen((ergebnis, wurzel, eintraege)))
        threads.starten(arbeit)

    def _geladen(self, daten):
        buecher, self.calibre_wurzel, self.calibre_eintraege = daten
        self.buecher = buecher
        self.nach_schluessel = {b.schluessel: b for b in buecher}
        doppelt = {}
        for b in buecher:                                 # gleiche Titel in den Listen unterscheidbar machen
            doppelt[b.titel] = doppelt.get(b.titel, 0) + 1
        for b in buecher:
            if doppelt[b.titel] > 1:
                b.titel_anzeige = f"{b.titel} ({b.pfad.name})"
        self._arbeit = None
        self._alles_neu_zeichnen()
        self.ordner_pruefen()
        if self._start_buch:                 # nach einem Neustart (Update): Buch wieder wählen
            b = next((x for x in buecher if str(x.pfad) == str(self._start_buch)), None)
            if b:
                self.bibliothek.auswaehlen(b)
                self.kapitel.auswaehlen(b)
            self._start_buch = None
        fehler = sum(1 for b in buecher if b.fehler)
        sicherung = Path(self.e["sicherungsordner"]).resolve()
        hinweis = " " + _("The backup folder is inside the books folder - better put it elsewhere (Settings).") \
            if Path(self.ordner).resolve() in sicherung.parents else ""
        cal = sum(1 for b in buecher if b.calibre)
        cal_text = " " + ngettext("Calibre data for {n} book ({ordner}).", "Calibre data for {n} books ({ordner}).", cal)\
            .format(n=cal, ordner=self.calibre_wurzel) if cal else \
            (" " + _("metadata.calibre found, but it matches no book.") if self.calibre_eintraege else "")
        self.status.set(ngettext("{n} book read.", "{n} books read.", len(buecher)).format(n=len(buecher))
                        + (" " + _("{n} not readable.").format(n=fehler) if fehler else "")
                        + cal_text + hinweis)

    def bibliothek_schliessen(self, still=False):
        """Geöffneten Ordner schließen (ungespeicherte Änderungen nach Rückfrage verwerfen)."""
        if self._arbeit or not self.ordner:
            return
        if not still and not self._aenderungen_verwerfen_ok():
            return
        self.ordner = None
        self.buecher, self.nach_schluessel = [], {}
        self.calibre_wurzel, self.calibre_eintraege = None, []
        self._ordner_weg = True                      # damit ordner_pruefen die Leiste wegnimmt
        self.ordner_pruefen()
        self._alles_neu_zeichnen()
        if not still:
            self.status.set(_("Library closed."))

    def _nicht_erreichbar(self, buecher):
        """Text, wenn der Ordner bzw. Bücher daraus nicht mehr da sind (E-Reader ausgeworfen oder
        Kabel gezogen), sonst None. Die Änderungen bleiben im Speicher; nach dem erneuten Anstecken
        (gleicher Pfad) geht Speichern wieder."""
        fehlen = [b for b in buecher if not b.pfad.is_file()]
        if not fehlen and (not self.ordner or Path(self.ordner).is_dir()):
            return None
        text = _("The folder {ordner} is no longer reachable (e-reader ejected or unplugged?). Nothing was saved.") \
            .format(ordner=self.ordner) if self.ordner and not Path(self.ordner).is_dir() else \
            ngettext("{n} book file is missing, e.g. {datei}. Nothing was saved.",
                     "{n} book files are missing, e.g. {datei}. Nothing was saved.", len(fehlen)) \
            .format(n=len(fehlen), datei=fehlen[0].pfad)
        return text + "\n\n" + _("The changes are kept as long as Bookbench is open. Connect the e-reader "
                                  "again and save, or discard them with Reload.")

    def speichern(self):
        self.kapitel._bearbeitung_beenden()
        faellig = [b for b in self.buecher if b.neu or b.klappentext_neu is not None or b.reihe_neu is not None
                   or b.tiefen_neu is not None or b.cover_neu is not None or b.meta_neu is not None]
        rot = sum(1 for b in self.buecher if b.stand() == "rot")
        if not faellig:
            self.status.set(_("Nothing to save.") + (" " + ngettext("{n} book with changes not yet applied.",
                                                                   "{n} books with changes not yet applied.", rot)
                                                     .format(n=rot) if rot else ""))
            return
        grund = self._nicht_erreichbar(faellig)
        if grund:
            dialogs.warnung(self, _("Save"), grund)
            self.status.set(_("Not saved: the books are not reachable."))
            return
        ok, fehler = 0, []
        for b in faellig:
            try:
                kd.speichern(b, self.e["sicherungsordner"], int(self.e["sicherungen_anzahl"]))
            except Exception as e:
                fehler.append(f"{b.name}: {e}")
                continue
            neu = kd.buch_laden(b.pfad, self.e["max_sub"], self.e["caps"], self.entscheidungen)
            kd.calibre_zuordnen([neu], self.calibre_wurzel, self.calibre_eintraege)
            neu.gespeichert = True
            if b.klappentext_quelle and b.klappentext_neu is not None:
                neu.klappentext_quelle = b.klappentext_quelle
            neu.entwurf, neu.klappentext_entwurf, neu.meta_entwurf = b.entwurf, b.klappentext_entwurf, b.meta_entwurf
            if b.tiefen_entwurf is not None and len(neu.zeilen) == len(b.tiefen_entwurf):
                neu.tiefen_entwurf = b.tiefen_entwurf
            neu.titel_anzeige = getattr(b, "titel_anzeige", None)
            self.buecher[self.buecher.index(b)] = neu
            self.nach_schluessel[neu.schluessel] = neu
            ok += 1
        self._alles_neu_zeichnen()
        kobo = self.bereich_obj("kobo")
        if ok and hasattr(kobo, "vermerken"):
            kobo.vermerken(self.ordner)
        if fehler:
            dialogs.fehler(self, _("Save"), _("Not saved:") + "\n\n" + "\n".join(fehler))
        self.status.set(ngettext("{n} book saved, backups in {ordner}.", "{n} books saved, backups in {ordner}.", ok)
                        .format(n=ok, ordner=self.e["sicherungsordner"]) +
                        (" " + _("{n} with changes not yet applied.").format(n=rot) if rot else ""))

    def offen(self):
        return sum(1 for b in self.buecher if b.stand() in ("rot", "gelb"))

    def _aenderungen_verwerfen_ok(self):
        offen = self.offen()
        return not offen or dialogs.frage(
            self, _("Changes"), ngettext("{n} book has unsaved changes. Discard them?",
                                         "{n} books have unsaved changes. Discard them?", offen).format(n=offen),
            standard=False)

    # ================================================================ Hilfsthread
    def hintergrund(self, name, arbeit, nachher=None):
        """arbeit() im Hilfsthread; ihr Rückgabetext (oder die Fehlermeldung) kommt in die
        Statuszeile, danach läuft nachher() im Hauptthread."""
        if self._arbeit:
            self.status.set(_("Still running: {arbeit}.").format(arbeit=self._arbeit))
            return
        self._arbeit = name
        self.status.set(f"{name} …")

        def lauf():
            try:
                text = arbeit()
            except Exception as e:                      # Meldung statt stillem Abbruch
                text = str(e) if isinstance(e, RuntimeError) else f"{name}: " + _("error ({fehler})").format(fehler=e)

            def fertig():
                self._arbeit = None
                if text:
                    self.status.set(text)
                if nachher:
                    nachher()
            threads.im_hauptthread(fertig)
        threads.starten(lauf)

    # ================================================================ Anzeige
    def _alles_neu_zeichnen(self):
        for b in self.bereiche:
            b.neu_zeichnen()
        self._zaehler()

    alles_neu_zeichnen = _alles_neu_zeichnen

    def buch_geaendert(self, b, baum=False):
        """Ein Buch hat sich geändert: Zeile der Bibliothek, Streifen, Baum (baum=True), Zähler, Titel."""
        for x in self.bereiche:
            if hasattr(x, "buch_geaendert"):
                x.buch_geaendert(b, baum) if x is self.kapitel else x.buch_geaendert(b)
        self._zaehler()

    # -- Aktionen über Bereiche hinweg --------------------------------------------------------
    def uebernehmen(self):
        """Strg+Enter: Übernehmen im aktuellen Bereich."""
        b = self.bereich_obj(self._aktuell)
        if hasattr(b, "uebernehmen"):
            b.uebernehmen()
        else:
            self.status.set(_("Apply: choose a book in the Chapters or Blurbs area."))

    def suche_fokus(self):
        """Strg+F: Suchfeld des aktuellen Bereichs, sonst das der Bibliothek."""
        b = self.bereich_obj(self._aktuell)
        if not hasattr(b, "suche_fokus"):
            self.bereich_zeigen("bibliothek")
            b = self.bibliothek
        b.suche_fokus()

    def _kapitel_aktion(self, name, *args):
        """Menü Bearbeiten: in den Bereich Kapitel wechseln (mit dem gewählten Buch) und ausführen."""
        if self._aktuell != "kapitel":
            b = self.gewaehltes_buch()
            self.bereich_zeigen("kapitel")
            if b:
                self.kapitel.auswaehlen(b)
        getattr(self.kapitel, name)(*args)

    def gewaehltes_buch(self):
        b = self.bereich_obj(self._aktuell)
        return getattr(b, "buch", None) or self.bibliothek.buch

    def buch_oeffnen(self, b, ziel=None):
        """Buch aus der Bibliothek öffnen: Kapitel, Metadaten, Vorschau oder gleich in KOReader
        (Einstellung buch_oeffnen). Noch nicht umgezogene Bereiche: Kapitel mit Hinweis."""
        ziel = ziel or self.e.get("buch_oeffnen") or "kapitel"
        bereich = "vorschau" if ziel == "koreader" else ziel
        obj = hinweis = self.bereich_obj(bereich)
        if obj is None or isinstance(obj, kar.Platzhalter):
            obj = self.kapitel
        self.bereich_zeigen(obj.kennung)
        obj.auswaehlen(b)
        if isinstance(hinweis, kar.Platzhalter):
            self.status.set(_("{bereich} moves to the new interface in {version}; opened in Chapters.")
                            .format(bereich=hinweis.name(), version=hinweis.kommt_in))

    def _bereich_mit_buch(self, kennung):
        """In einen Bereich wechseln und dort das gerade gewählte Buch zeigen (Befehle aus dem Menü)."""
        if self._aktuell != kennung:
            b = self.gewaehltes_buch()
            self.bereich_zeigen(kennung)
            if b:
                self.bereich_obj(kennung).auswaehlen(b)
        return self.bereich_obj(kennung)

    def cover_aktion(self, name):
        """Menü: Cover-Befehl im Bereich Metadaten (mit dem gewählten Buch); alle_ohne ohne Wechsel."""
        if name == "alle_ohne":
            if self.metadaten.seite is not None:
                self.metadaten.cover.alle_ohne()
            return
        getattr(self._bereich_mit_buch("metadaten").cover, name)()

    def metadaten_aktion(self, name):
        getattr(self._bereich_mit_buch("metadaten"), name)()

    # -- Klappentexte nachschlagen (core/blurb_lookup im Hilfsthread) -------------------------
    def klappentext_nachschlagen(self):
        b = self.metadaten.buch if self._aktuell == "metadaten" else None
        if not b:
            self.status.set(_("Look up: choose a book in the Metadata area."))
            return
        self._nachschlagen_starten([b], einzeln=True)

    def klappentexte_alle(self):
        # Bücher, für die Calibre eine Beschreibung hat, nicht nachschlagen (dafür gibt es "Aus Calibre")
        offen = [b for b in self.buecher if not km.klappentext_aktuell(b).strip() and not b.fehler
                 and not (b.calibre and b.calibre.get("comments"))]
        if not offen:
            self.status.set(_("All books have a blurb."))
            return
        self._nachschlagen_starten(offen)

    def _nachschlagen_starten(self, buecher, einzeln=False):
        from bookbench.core import blurb_lookup as kbl
        if self._arbeit:
            self.status.set(_("Still running: {arbeit}.").format(arbeit=self._arbeit))
            return
        plan = kbl.plan(buecher, self.cache, self.e)
        mit_claude, mit_frei = kbl.zaehlen(plan)
        client, ohne_schluessel = None, False
        if mit_claude:
            client, fehler = kbl.api_client(self.e)
            if client is None:
                if not mit_frei:                    # ohne Schlüssel nur meckern, wenn es sonst nichts zu tun gibt
                    dialogs.fehler(self, _("Look up"), fehler)
                    return
                plan, mit_claude, ohne_schluessel = kbl.ohne_claude(plan), 0, True
        if not einzeln and mit_claude and not dialogs.frage(
                self, _("Look up all"),
                ngettext("{n} book without a blurb.", "{n} books without a blurb.", len(plan)).format(n=len(plan))
                + "\n" + (_("The free sources are asked first; Claude only for what they do not have.") + "\n"
                          if mit_frei else "")
                + ngettext("At most {n} book goes to Claude: up to about {kosten} $.",
                           "At most {n} books go to Claude: up to about {kosten} $.", mit_claude)
                .format(n=mit_claude, kosten=f"{mit_claude * float(self.e.get('kt_kosten', 0.015)):.2f}")
                + "\n\n" + _("Start?")):
            return
        kbl.einstellungen_anwenden(self.e)
        e = dict(self.e)

        def melden(text):
            threads.im_hauptthread(lambda: self.status.set(text))

        def ergebnis(b, schl, eintrag):
            def im_haupt():
                if eintrag is not None:
                    self.cache[schl] = eintrag
                    kd.json_speichern(kd.KLAPPENTEXT_CACHE, self.cache)
                self._klappentext_ergebnis(b.schluessel)
            threads.im_hauptthread(im_haupt)

        self.hintergrund(_("Looking up blurbs"),
                         lambda: kbl.ausfuehren(plan, client, e, melden, ergebnis, ohne_schluessel))

    def _klappentext_ergebnis(self, schluessel):
        from bookbench.core import blurb_lookup as kbl
        b = self.nach_schluessel.get(schluessel)
        if not b:
            return
        treffer = self.cache.get(kbl.schluessel(b)) or {}
        if treffer.get("blurb"):
            b.klappentext_entwurf = treffer["blurb"]
            b.klappentext_quelle = treffer.get("source", "")
            self.status.set(f"{b.name}: " + _("blurb found ({quelle}), not yet applied.")
                            .format(quelle=blurbs.source_name(b.klappentext_quelle) or "?"))
        else:
            self.status.set(f"{b.name}: " + _("no blurb found.")
                            + (f" ({b.kt_nachschlag})" if getattr(b, "kt_nachschlag", "") else ""))
        self.buch_geaendert(b)
        if b is self.metadaten.buch and self.metadaten.seite is not None:
            self.metadaten.klappentext.anzeigen()
            self.metadaten.aktualisieren()

    def calibre_importieren(self):
        """Einmaliger Import aus einer Calibre-Bibliothek (ui/calibre_import)."""
        if not self.buecher:
            self.status.set(_("Open a folder with books first, then import from Calibre."))
            return None
        from bookbench.ui import calibre_import as kci
        d = self._import_dialog = kci.ImportDialog(self)
        d.show()
        return d

    def _calibre_aus(self):
        """True (mit Hinweis), wenn der Calibre-Abgleich abgeschaltet ist (Einstellungen > Bücher > Calibre)."""
        if self.e.get("calibre_an", True):
            return False
        self.status.set(_("The Calibre comparison is switched off (Settings > Books > Calibre)."))
        return True

    def calibre_uebernehmen(self):
        """Reihe/Nummer und Klappentext aus metadata.calibre übernehmen - nur, wo das EPUB nichts hat."""
        if self._calibre_aus():
            return
        if not self.calibre_eintraege:
            self.status.set(_("No metadata.calibre found (it is in the root folder of the e-reader when Calibre "
                              "transfers the books). Open the folder on the e-reader or copy the file into the books folder."))
            return
        reihen = texte = 0
        for b in self.buecher:
            reihe, text = kd.calibre_vorschlag(b)
            if reihe:
                b.reihe_neu = reihe
                b.reihe, b.nummer = reihe
                reihen += 1
            if text:
                b.klappentext_neu = text
                b.klappentext_quelle = "Calibre"
                texte += 1
        self._alles_neu_zeichnen()
        self.status.set(_("Taken from Calibre: {reihen} series, {texte} blurbs - not yet saved (Ctrl+S).")
                        .format(reihen=reihen, texte=texte)
                        if reihen or texte else _("Nothing to take from Calibre; the EPUBs already have everything."))

    def bibliothek_marken(self, b):
        """Marken in der Bibliothek: alles, was die Bereiche melden (Kapitel und Metadaten)."""
        return km.bibliothek(b, self.e)

    def _seitenleiste_marken(self, b):
        """[(kennung, anzahl)] eines Bereichs: die Bereiche liefern sie selbst; Bibliothek und Kapitel
        hier, solange es sie nur als Platzhalter gibt."""
        return [] if isinstance(b, kar.Platzhalter) else b.marken()

    def _zaehler(self):
        """Seitenleiste (Marken je Bereich) und Fenstertitel."""
        if not hasattr(self, "leiste"):
            return
        eintraege = []
        for b in self.bereiche:
            marken = [(k, n) for k, n in self._seitenleiste_marken(b) if km.sichtbar(self.e, "seitenleiste", k)]
            eintraege.append({"id": b.kennung, "name": b.name(), "symbol": b.symbol, "marken": marken,
                              "zaehler": b.zaehler(), "kinder": b.kinder()})
        self.leiste.setzen(eintraege)
        self.setWindowTitle(f"{PROGRAMM} {VERSION}" + (" *" if self.offen() else ""))

    # -- Darstellung ----------------------------------------------------------------------
    def darstellung_setzen(self, wert):
        self.darstellung = self.e["darstellung"] = wert
        theme.anwenden(QApplication.instance(), wert)
        kmk.leeren()
        self._symbole_auffrischen()
        self._hinweis_faerben()
        if self._hilfe is not None:
            self._hilfe.farben()
        act = self._darstellungs_aktionen.get(wert)
        if act and not act.isChecked():
            act.setChecked(True)
        self._alles_neu_zeichnen()
        self.leiste.update()

    def _tooltips_anwenden(self):
        self.tooltips.an = bool(self.e.get("tooltips", True))
        QApplication.instance().styleHints().setToolTipWakeUpDelay(int(self.e.get("tooltip_verzoegerung", 600)))

    # ================================================================ Sprache
    def sprache_setzen(self, code):
        """Neue Sprache sofort: Übersetzung umstellen, Oberfläche neu aufbauen. Bücher, offene Änderungen,
        Bereich und Auswahl bleiben (Zustand liegt außerhalb der Widgets)."""
        self.kapitel._bearbeitung_beenden()
        i18n.einstellen(code)
        qt_uebersetzung(QApplication.instance())
        hilfe_offen = self._hilfe.aktuelles_thema() if self._hilfe is not None and self._hilfe.isVisible() else None
        if self._hilfe is not None:
            self._hilfe.close()
            self._hilfe = None
        self.oberflaeche_bauen()
        if hilfe_offen:
            self.hilfe_zeigen(hilfe_offen)
        self.status.set(_("Language: {sprache}").format(sprache=i18n.SPRACHEN.get(i18n.aktiv(), i18n.aktiv())))

    # ================================================================ Einstellungen
    def einstellungen(self, seite=None):
        from bookbench.ui import settings as kst
        kst.EinstellungsDialog(self, seite).exec()

    def einstellungen_geaendert(self, sprache_alt=None):
        """Nach OK im Einstellungsdialog (oder Import/Zurücksetzen): alles anwenden und speichern."""
        blurbs.GOOGLE_KEY = self.e.get("google_key", "") or ""
        if self.leiste.ausgeklappt != bool(self.e.get("navi_ausgeklappt", True)):
            self.leiste.umschalten()
        self._tooltips_anwenden()
        neu = self.e.get("sprache") or "auto"
        if sprache_alt is not None and neu != sprache_alt:
            self.darstellung = self.e.get("darstellung") or "system"
            theme.anwenden(QApplication.instance(), self.darstellung)
            kmk.leeren()
            self.sprache_setzen(neu)                 # baut ohnehin alles neu
        else:
            self.oberflaeche_bauen()                 # Menüs (Haken), Werkzeugleiste, Bereiche
            self.darstellung_setzen(self.e.get("darstellung") or "system")
        kei.speichern(self.e)
        self.status.set(_("Settings saved. Chapter settings apply after reloading (F5)."))

    # ================================================================ Hilfe
    def hilfe_zeigen(self, kennung):
        """Hilfe mit einem bestimmten Thema öffnen (z. B. aus den Einstellungen)."""
        from bookbench.ui import help as khi
        if self._hilfe is None:
            f = self._hilfe = khi.HilfeFenster(self)
            # beim Schließen vergessen - aber nur, wenn inzwischen kein neues Fenster da ist (Sprachwechsel)
            f.destroyed.connect(lambda *a, f=f: setattr(self, "_hilfe", None) if self._hilfe is f else None)
        self._hilfe.zeige(kennung)
        self._hilfe.show()
        self._hilfe.raise_()
        self._hilfe.activateWindow()

    def hilfe(self):
        b = self.bereich_obj(self._aktuell)
        self.hilfe_zeigen(help_topics.thema(b.hilfe_thema() if b else "ueberblick"))

    # ================================================================ Beenden
    def neu_starten(self):
        """Bookbench neu starten (nach einem Update unter Linux), mit Ordner, Bereich und Fenster.
        Fragt nichts mehr; offene Änderungen vorher klären (schliessen_ok)."""
        start = Path(__file__).resolve().parent.parent / "start.py"
        befehl = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(start)]
        if self.ordner:
            befehl.append(self.ordner)
        befehl += ["--bereich", self._aktuell, "--geometrie", self.geometrie(mit_ort=True)]
        b = self.gewaehltes_buch()
        if b:
            befehl += ["--buch", str(b.pfad)]
        self._einstellungen_sichern()
        self._popen(befehl)
        self._ohne_rueckfrage = True
        self.close()

    def _einstellungen_sichern(self):
        if not self.isMaximized() and not self.isFullScreen():
            self.e["fenster"] = self.geometrie()
        try:
            kei.speichern(self.e)
        except OSError:
            pass

    def schliessen_ok(self):
        """Darf Bookbench jetzt zugehen? Fragt nach ungespeicherten Büchern und dem, was die Bereiche
        offen haben (Beenden, Update)."""
        offen = self.offen()
        if offen and not dialogs.frage(
                self, _("Quit"), ngettext("{n} book has unsaved changes. Quit anyway?",
                                          "{n} books have unsaved changes. Quit anyway?", offen).format(n=offen),
                standard=False):
            return False
        return all(b.schliessen_ok() for b in self.bereiche)

    def closeEvent(self, ev):
        if not getattr(self, "_ohne_rueckfrage", False) and not self.schliessen_ok():
            ev.ignore()
            return
        if not getattr(self, "_ohne_rueckfrage", False):
            self._einstellungen_sichern()
        for b in self.bereiche:
            b.beenden()
        if self._hilfe is not None:
            self._hilfe.close()
        ev.accept()


_uebersetzer = {}


def qt_uebersetzung(app):
    """Qt-eigene Texte (OK, Abbrechen, Ja/Nein, Dateidialog) in der Sprache von Bookbench."""
    alt = _uebersetzer.pop("qt", None)
    if alt is not None:
        app.removeTranslator(alt)
    code = i18n.aktiv()
    if code == "en":
        return
    t = QTranslator(app)
    if t.load(QLocale(code), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(t)
        _uebersetzer["qt"] = t


def anwendung(argv=None):
    """QApplication mit Name, Übersetzung und Hilfsthread-Boten (auch für Tests)."""
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv[:1])
    app.setApplicationName(PROGRAMM)
    app.setApplicationVersion(VERSION)
    app.setDesktopFileName("bookbench")          # Wayland: Fenster gehört zu bookbench.desktop (Symbol)
    theme.merken_beim_start(app)
    threads.einrichten()
    qt_uebersetzung(app)
    return app


def main():
    ap = argparse.ArgumentParser(description=f"{PROGRAMM} {VERSION}")
    ap.add_argument("ordner", nargs="?", help=_("books folder to open"))
    ap.add_argument("--bereich", help=argparse.SUPPRESS)        # für den Neustart nach einem Update
    ap.add_argument("--buch", help=argparse.SUPPRESS)
    ap.add_argument("--geometrie", help=argparse.SUPPRESS)
    a = ap.parse_args()
    app = anwendung()
    w = App(a.ordner, a.bereich, a.buch, a.geometrie)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    main()
