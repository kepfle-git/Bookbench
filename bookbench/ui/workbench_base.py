# -*- coding: utf-8 -*-
"""
workbench_base.py - Gemeinsames der Unterseiten der KOReader-Werkbank (Qt; Tk-Vorlage: _Seite, _Wahl,
_gleich und _zahl_oder_leer in tk/workbench_plugins.py).

  Seite           eine Unterseite in der linken Spalte des Bereichs Vorschau: scrollbar, Kopf (Hinweis),
                  Stand-Zeile (Entwurf/wie im Profil), aufklappbare Abschnitte (offen/zu je Plugin und
                  Abschnitt in werkbank_abschnitte), Reiter (seit 2.2: _reiter() vor den Abschnitten, gewählter
                  Reiter in werkbank_reiter, Punkt am Reiter über reiter_geaendert()), verzögertes Ausführen
                  (_planen)
                  Schnittstelle für den Bereich: ungespeichert(), fragen_ob_verwerfen(), zuruecksetzen(),
                  neu_laden(), in_kopie(ko), nach_start(), beim_zeigen(), beim_verlassen(), speichern(),
                  verwerfen(), stand_zeigen()
  Wahl            Klappliste mit festen Werten [(wert, N_("Text"))]: wert() / setzen(wert)
  symbolschrift() KOReaders symbols.ttf als Ausweichschrift für Nerd-Font-Symbole (privater Unicode-
                  Bereich): Qt zeichnet sie dann direkt im Textfeld (in Tk waren es kleine Bilder)

Entwürfe wirken erst nur in der Werkbank (Wegwerf-Kopie des Profils); "Ins Profil speichern" behält sie.
"""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QRegularExpressionValidator
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QTabBar,
                               QToolButton, QVBoxLayout, QWidget)

from bookbench.i18n import _
from bookbench.preview import plugins as kpl
from bookbench.ui import dialogs, theme

BREITE = 360                                      # Breite der Hinweise (wie im Tk-Programm)


def gleich(a, b):
    """Gleichheit ohne Pythons True == 1 und False == 0 (Bookshelf unterscheidet false und 0)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def zahl_oder_leer(text):
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    w = float(text)
    return int(w) if w.is_integer() else w


def zahlfeld(fn, negativ=False, breite=52):
    """Zahlenfeld, das leer bleiben darf (leer = Vorgabe); fn bei jeder Eingabe."""
    e = QLineEdit()
    e.setValidator(QRegularExpressionValidator(QRegularExpression((r"-?" if negativ else "") + r"\d{0,4}([.,]\d{0,2})?"), e))
    e.setFixedWidth(breite)
    e.textEdited.connect(lambda *a: fn())
    return e


def zeile(*widgets, stretch=True):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        if isinstance(x, str):
            x = QLabel(x)
        lay.addWidget(x)
    if stretch:
        lay.addStretch(1)
    return w


class _Hinweis(QLabel):
    """Umbrechender Hinweis mit Höchstbreite, der nie abgeschnitten wird: das Layout fragt die Höhe für die
    Breite der Zelle ab, das Label bricht aber bei seiner Höchstbreite um (mehr Zeilen)."""

    def heightForWidth(self, breite):
        return super().heightForWidth(min(breite, self.maximumWidth()))


def hinweis(text, breite=None):
    lab = _Hinweis(text)
    lab.setProperty("rolle", "hinweis")
    lab.setWordWrap(True)
    if breite:
        lab.setMaximumWidth(breite)
    return lab


_symbol_familien = {}


def symbolschrift(profil, befund):
    """Familienname von KOReaders symbols.ttf (einmal geladen) oder None."""
    pfad = kpl.symbolschrift(profil, befund)
    if not pfad:
        return None
    schl = str(pfad)
    if schl not in _symbol_familien:
        i = QFontDatabase.addApplicationFont(schl)
        fam = QFontDatabase.applicationFontFamilies(i) if i >= 0 else []
        _symbol_familien[schl] = fam[0] if fam else None
    return _symbol_familien[schl]


def mit_symbolen(widget, familie, mono=False):
    """Schrift eines Textfelds mit der Symbolschrift als Ausweichschrift."""
    f = QFontDatabase.systemFont(QFontDatabase.FixedFont) if mono else QFont(widget.font())
    if familie:
        f.setFamilies(list(f.families() or [f.family()]) + [familie])
    widget.setFont(f)


class Wahl(QComboBox):
    """Klappliste mit festen Werten [(wert, Text)] (Text als N_ markiert, übersetzt beim Füllen)."""

    def __init__(self, optionen, befehl, breite=None):
        super().__init__()
        self._still = False
        self.optionen(optionen)
        if breite:
            self.setMinimumContentsLength(breite)
        self.currentIndexChanged.connect(lambda *a: None if self._still else befehl())

    def optionen(self, optionen):
        self._still = True
        self._optionen = list(optionen)
        self.clear()
        for __, t in self._optionen:
            self.addItem(_(t))
        self._still = False

    def wert(self):
        i = self.currentIndex()
        if 0 <= i < len(self._optionen):
            return self._optionen[i][0]
        return self._optionen[0][0] if self._optionen else None

    def setzen(self, wert, aktiv=None):
        self._still = True
        i = next((n for n, (w, __) in enumerate(self._optionen) if w == wert), 0)
        self.setCurrentIndex(i if self._optionen else -1)
        self._still = False
        if aktiv is not None:
            self.setEnabled(aktiv)


class Seite:
    """Gemeinsames: Fläche mit Scrollbalken, Kopf, Stand-Zeile, Entwurf."""
    plugin = ""                                   # Kennung der Unterseite (auch für werkbank_abschnitte)
    titel = ""                                    # N_(): Name in Seitenleiste und Meldungen

    def __init__(self, bereich):
        self.bereich = bereich
        self.app = bereich.app
        self.rahmen = None
        self.info = None
        self.abschnitte = {}
        self.reiter = []                          # [(kennung, titel, widget)] seit 2.2
        self.reiter_von = {}                      # Abschnitt -> Reiter
        self.reiterleiste = None
        self._takt = QTimer()
        self._takt.setSingleShot(True)
        self._takt_fn = None
        self._takt.timeout.connect(self._ausfuehren)

    def name(self):
        return _(self.titel)

    # -- Aufbau (bei jedem Neuaufbau der Oberfläche) -----------------------------------------
    def bauen(self):
        """Fläche bauen; die Unterklassen hängen ihre Abschnitte mit _abschnitt() an self.lay."""
        flaeche = QScrollArea()
        flaeche.setWidgetResizable(True)
        flaeche.setFrameShape(QFrame.NoFrame)
        flaeche.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        innen = QWidget()
        self.lay = QVBoxLayout(innen)
        self.lay.setContentsMargins(0, 0, 10, 8)
        self.lay.setSpacing(2)
        self.kopf = hinweis("")
        self.lay.addWidget(self.kopf)
        self.stand = QLabel("")
        self.stand.setWordWrap(True)
        self.lay.addWidget(self.stand)
        self.lay.addSpacing(6)
        self.abschnitte = {}
        self.reiter, self.reiter_von, self.reiterleiste = [], {}, None
        self.lay_oben = self.lay
        self.inhalt_bauen()
        self.lay = self.lay_oben
        if self.reiter:
            self._reiter_zeigen(self.app.e.get("werkbank_reiter", {}).get(self.plugin), oben=False)
        self.lay.addStretch(1)
        flaeche.setWidget(innen)
        self.rahmen = flaeche
        return flaeche

    def inhalt_bauen(self):
        pass

    # -- Reiter (seit 2.2) -----------------------------------------------------------------------
    def _reiter(self, kennung, titel):
        """Neuer Reiter; alle folgenden _abschnitt()/_flaeche() landen darin. Beim ersten Aufruf kommt die
        Reiterleiste unter den Kopf. Nur der gewählte Reiter ist sichtbar (die Höhe folgt ihm)."""
        if self.reiterleiste is None:
            leiste = self.reiterleiste = QTabBar()
            leiste.setExpanding(False)
            leiste.setDrawBase(True)
            leiste.setUsesScrollButtons(True)
            leiste.currentChanged.connect(self._reiter_gewechselt)
            self.lay_oben.addSpacing(4)
            self.lay_oben.addWidget(leiste)
        seite = QWidget()
        lay = QVBoxLayout(seite)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.setSpacing(2)
        self.reiter.append((kennung, titel, seite))
        self.reiterleiste.blockSignals(True)
        self.reiterleiste.addTab(titel)
        self.reiterleiste.blockSignals(False)
        self.lay_oben.addWidget(seite)
        self.lay = lay
        return seite

    def _reiter_gewechselt(self, i):
        if 0 <= i < len(self.reiter):
            self._reiter_zeigen(self.reiter[i][0])

    def _reiter_zeigen(self, kennung, oben=True):
        kennungen = [k for k, __, __ in self.reiter]
        if kennung not in kennungen:
            kennung = kennungen[0]
        i = kennungen.index(kennung)
        for n, (__, __, w) in enumerate(self.reiter):
            w.setVisible(n == i)
        if self.reiterleiste.currentIndex() != i:
            self.reiterleiste.blockSignals(True)
            self.reiterleiste.setCurrentIndex(i)
            self.reiterleiste.blockSignals(False)
        self.app.e.setdefault("werkbank_reiter", {})[self.plugin] = kennung
        if oben and self.rahmen is not None:
            self.rahmen.verticalScrollBar().setValue(0)

    def reiter_waehlen(self, kennung):
        if self.reiter:
            self._reiter_zeigen(kennung)

    def gewaehlter_reiter(self):
        if not self.reiter:
            return None
        return self.reiter[max(0, self.reiterleiste.currentIndex())][0]

    def reiter_geaendert(self):
        """Kennungen der Reiter mit ungespeicherten Änderungen (Unterklassen)."""
        return set()

    def _reiter_marken(self):
        if not self.reiter:
            return
        geaendert = self.reiter_geaendert() if self.ungespeichert() else set()
        rot = QColor(theme.MARK[theme.modus()]["rot"])
        for n, (k, titel, __) in enumerate(self.reiter):
            an = k in geaendert
            self.reiterleiste.setTabText(n, f"{titel} ●" if an else titel)
            self.reiterleiste.setTabTextColor(n, rot if an else QColor())
            self.reiterleiste.setTabToolTip(n, _("Unsaved changes on this tab") if an else "")

    def _flaeche(self, kennung):
        """Inhalt ohne Kopf (für einen Reiter mit nur einem Teil). Gibt das Widget zurück (ohne Layout)."""
        inhalt = QWidget()
        self.lay.addWidget(inhalt)
        self.abschnitte[kennung] = (None, inhalt)
        if self.reiter:
            self.reiter_von[kennung] = self.reiter[-1][0]
        return inhalt

    def _abschnitt(self, kennung, titel, offen=True):
        """Aufklappbarer Abschnitt; offen/zu je Plugin und Abschnitt in werkbank_abschnitte. Gibt das Widget
        für den Inhalt zurück (ohne Layout)."""
        zustand = self.app.e.setdefault("werkbank_abschnitte", {})
        schl = f"{self.plugin}.{kennung}"
        knopf = QToolButton()
        knopf.setText(titel)
        knopf.setCheckable(True)
        knopf.setChecked(bool(zustand.get(schl, offen)))
        knopf.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        knopf.setAutoRaise(True)
        knopf.setStyleSheet("QToolButton { font-weight: bold; }")
        inhalt = QWidget()
        inhalt.setContentsMargins(8, 0, 0, 4)

        def zeigen(an):
            self.app.e.setdefault("werkbank_abschnitte", {})[schl] = bool(an)
            knopf.setArrowType(Qt.DownArrow if an else Qt.RightArrow)
            inhalt.setVisible(bool(an))
        knopf.toggled.connect(zeigen)
        self.lay.addSpacing(4)
        self.lay.addWidget(knopf)
        self.lay.addWidget(inhalt)
        zeigen(knopf.isChecked())
        self.abschnitte[kennung] = (knopf, inhalt)
        if self.reiter:
            self.reiter_von[kennung] = self.reiter[-1][0]
        return inhalt

    def aufklappen(self, kennung, an=True):
        """Abschnitt auf- bzw. zuklappen; beim Aufklappen auch seinen Reiter wählen."""
        if kennung not in self.abschnitte:
            return
        if an and kennung in self.reiter_von:
            self.reiter_waehlen(self.reiter_von[kennung])
        knopf = self.abschnitte[kennung][0]
        if knopf is not None:
            knopf.setChecked(an)

    def nur_grau(self):
        """True, wenn das nachgebildete Gerät keinen Farbbildschirm hat (Farben dann als % Schwarz, seit 2.2)."""
        try:
            return not self.bereich.bildschirm().get("farbe", True)
        except Exception:                                 # ohne Profil/Gerät: wie Farbe
            return False

    @property
    def ko(self):
        return kpl.ko_ordner(self.bereich.profil)

    def gebaut(self):
        return self.rahmen is not None

    # -- Ablauf --------------------------------------------------------------------------------
    def _planen(self, ms, fn):
        self._takt_fn = fn
        self._takt.start(ms)

    def _ausfuehren(self):
        fn, self._takt_fn = self._takt_fn, None
        if fn:
            fn()

    def ungespeichert(self):
        return False

    def zuruecksetzen(self):
        """Neues Profil: Entwurf und geladenen Stand vergessen (beim nächsten Zeigen neu lesen)."""

    def neu_laden(self):
        pass

    def in_kopie(self, ko):
        pass

    def nach_start(self):
        pass

    def beim_zeigen(self):
        pass

    def beim_verlassen(self):
        pass

    def speichern(self):
        return False

    def verwerfen(self):
        pass

    def fragen_ob_verwerfen(self):
        """Vor dem Neuladen (Profil vom E-Reader usw.): True = weitermachen."""
        if not self.ungespeichert():
            return True
        a = dialogs.frage3(self.app, self.name(), _("The {plugin} settings have unsaved changes. Save them in the "
                                                    "profile first?").format(plugin=self.name()))
        if a is None:
            return False
        if a:
            self.speichern()
        return True

    def verwerfen_ok(self):
        return dialogs.frage(self.app, self.name(), _("Discard the unsaved changes?"))

    def stand_zeigen(self):
        if not self.gebaut():
            return
        if self.ungespeichert():
            self.stand.setText(_("● Unsaved changes - so far only in the picture. \"Save to profile\" keeps them."))
            self.stand.setStyleSheet(f"color: {theme.MARK[theme.modus()]['rot']};")
        else:
            self.stand.setText(_("Same as in the profile. \"To the e-reader …\" in the toolbar writes it to the "
                                 "e-reader."))
            self.stand.setStyleSheet("")
        self._reiter_marken()
        self.bereich.kinder_geaendert()
