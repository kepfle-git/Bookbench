# -*- coding: utf-8 -*-
"""
workbench_plugins.py - Unterseiten Bookends und Bookshelf der KOReader-Werkbank (Qt; Tk-Vorlage
tk/workbench_plugins.py). Nur Oberfläche; Dateiformate und Logik in preview/plugins.py, KOReader-Steuerung in
preview/workbench.py.

Ablauf (für beide gleich): Änderungen sind erst ein Entwurf und wirken nur in der Werkbank (Wegwerf-Kopie des
Profils). "Ins Profil speichern" schreibt sie ins Vorschau-Profil, "Verwerfen" liest das Profil neu. Bei jedem
Neustart der Werkbank schreibt in_kopie() die Entwürfe in die neue Kopie.

  Bookends    jede Änderung nach kurzer Pause sofort im Bild (Befehl "bookends <datei>", < 0,2 s)
  Bookshelf   Änderung -> Neustart der Werkbank auf dem Startbildschirm (~1,2 s)

Nerd-Font-Symbole zeigt Qt über KOReaders symbols.ttf als Ausweichschrift direkt im Textfeld (in Tk waren es
kleine Bilder). Entwurf und Auswahl hängen an der Seite, nicht an den Widgets (Sprachwechsel ohne Neustart).
"""
import copy
import re

from PySide6.QtCore import QEvent, QObject, QRegularExpression, Qt
from PySide6.QtGui import QFont, QRegularExpressionValidator, QTextCursor
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton, QRadioButton,
                               QScrollArea, QSizePolicy, QSpinBox, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from bookbench.i18n import N_, _
from bookbench.preview import plugins as kpl
from bookbench.ui import dialogs
from bookbench.ui.workbench_base import (BREITE, Seite, Wahl, gleich, hinweis, mit_symbolen, symbolschrift,
                                         zahl_oder_leer)

PAUSE_BOOKENDS = 350                              # ms nach der letzten Eingabe, dann ins Bild
PAUSE_BOOKSHELF = 900                             # ms, dann Neustart (länger: kostet ~1,2 s)

# Bookshelfs Standard-Einträge im Startmenü (bookshelf_start_menu_model.lua DEFAULTS, Aktionen ohne Module);
# zum Wiederherstellen. Die Beschriftung wird in Bookbenchs Sprache gespeichert, wie Bookshelf es auch tut.
STARTMENUE_STANDARD = (
    {"type": "action", "label": N_("Reading calendar"), "icon": "", "action": {"stats_calendar_view": True}},
    {"type": "action", "label": N_("Bookmark browser"), "icon": "", "action": {"bookmark_browser": True}},
    {"type": "action", "label": N_("Screenshot"), "icon": "", "action": {"screenshot": True}},
    {"type": "action", "label": N_("Frontlight"), "icon": "",
     "menu_path": [{"id": "setting"}, {"id": "frontlight"}]},
    {"type": "action", "label": N_("Full screen refresh"), "icon": "", "action": {"full_refresh": True}},
    {"type": "action", "label": N_("Battery statistics"), "icon": "", "action": {"battery_statistics": True}},
    {"type": "action", "label": N_("Wi-Fi connection"), "icon": "",
     "menu_path": [{"id": "setting"}, {"id": "network"}, {"id": "network_wifi"}], "menu_toggle": True},
    {"type": "action", "label": N_("Night mode"), "icon": "",
     "menu_path": [{"id": "setting"}, {"id": "night_mode"}], "menu_toggle": True},
    {"type": "action", "label": N_("Close book"), "icon": "", "menu_path": [{"id": "filemanager"}],
     "scope": "reader"},
    {"type": "action", "label": N_("Sleep"), "icon": "", "action": {"suspend": True}},
)


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


class _Fokus(QObject):
    """Merkt das zuletzt benutzte Textfeld (Token und Sonderzeichen werden dort eingefügt)."""

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.FocusIn:
            self.fn(obj)
        return False


class _SymbolSeite(Seite):
    def symbolfamilie(self):
        return symbolschrift(self.bereich.profil, self.bereich.befund)


# ====================================================================== Bookends
class BookendsSeite(_SymbolSeite):
    plugin = kpl.BOOKENDS
    titel = "Bookends"

    def __init__(self, bereich):
        super().__init__(bereich)
        self.datei = None                         # Dateiname der gezeigten Vorlage
        self.daten = None                         # Entwurf (dict)
        self.gespeichert = None                   # Stand im Profil (dict) bzw. None bei neuer Vorlage
        self.stand_profil = {"an": False, "aktiv": None}
        self.an = False                           # Entwurf: Bookends an
        self.aktiv_neu = None                     # im Entwurf zur aktiven Vorlage gemacht
        self._namen = {}                          # Anzeigename -> Datei
        self._zeile = None                        # (pos, nr) für Stil/Größe
        self._fokus_pos = "tc"                    # zuletzt benutztes Textfeld
        self.pos_wahl = None                      # im Schema gewählte Position (seit 2.2)
        self.balken_nr = 1
        self._laden = False
        self._symbolfenster = None

    # ------------------------------------------------------------------ Aufbau
    def inhalt_bauen(self):
        familie = self.symbolfamilie()
        self._fokus_filter = _Fokus(self._fokus_gesetzt)
        # -- über den Reitern: Vorlage und an/aus (gilt für alle Reiter)
        oben = QWidget()
        ol = QHBoxLayout(oben)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.addWidget(QLabel(_("Preset")))
        self.wahl = QComboBox()
        self.wahl.activated.connect(lambda *a: self._wahl_gewechselt())
        ol.addWidget(self.wahl, 1)
        self.an_knopf = QCheckBox(_("Bookends switched on"))
        self.an_knopf.toggled.connect(self._an_geaendert)
        ol.addWidget(self.an_knopf)
        self.lay.addWidget(oben)

        # == Reiter Zeilen
        self._reiter("zeilen", _("Lines"))
        i = self._flaeche("zeilen")
        lay = QVBoxLayout(i)
        lay.setContentsMargins(0, 0, 0, 0)
        self.token_knopf = QToolButton()
        self.token_knopf.setText(_("Insert token"))
        self.token_knopf.setPopupMode(QToolButton.InstantPopup)
        self.token_menue = QMenu(self.token_knopf)
        self.token_knopf.setMenu(self.token_menue)
        sym = QPushButton(_("Special characters …"))
        sym.clicked.connect(self.symbole_zeigen)
        lay.addWidget(zeile(self.token_knopf, sym))
        lay.addWidget(hinweis(_("Choose a position on the page; one line per row, tokens like %title or %page_num "
                                "are filled in by Bookends. The extra margin moves only this position away from the "
                                "edge (px), not the whole header or footer."), BREITE))
        lay.addWidget(self._schema_bauen())
        self.texte, self.rand, self.pos_rahmen = {}, {}, {}
        for pos, name in kpl.POSITIONEN:
            rahmen = QWidget()
            rl = QVBoxLayout(rahmen)
            rl.setContentsMargins(0, 4, 0, 0)
            rl.setSpacing(lay.spacing())
            kopf = QLabel(_(name))
            kopf.setProperty("rolle", "abschnitt")
            rl.addWidget(kopf)
            g = QGridLayout()
            oben_ = pos.startswith("t")
            felder = [("v_offset", _("Extra top margin") if oben_ else _("Extra bottom margin"))]
            if kpl.mit_seitenrand(pos):
                felder.append(("h_offset", _("Extra left margin") if pos.endswith("l") else _("Extra right margin")))
            for r, (feld, text) in enumerate(felder):
                g.addWidget(QLabel(text), r, 0)
                f = self.rand[(pos, feld)] = zahlfeld(lambda p=pos: self._rand_geaendert(p), breite=46)
                g.addWidget(f, r, 1)
                g.addWidget(hinweis("px"), r, 2)
            g.setColumnStretch(3, 1)
            rl.addLayout(g)
            t = QPlainTextEdit()
            t.setLineWrapMode(QPlainTextEdit.NoWrap)
            mit_symbolen(t, familie)
            t.textChanged.connect(lambda p=pos: self._text_geaendert(p))
            t.cursorPositionChanged.connect(lambda p=pos: self._zeile_gewaehlt(p))
            t.installEventFilter(self._fokus_filter)
            t.setProperty("position", pos)
            self._hoehe(t, 1)
            rl.addWidget(t)
            self.texte[pos] = t
            self.pos_rahmen[pos] = rahmen
            lay.addWidget(rahmen)

        # -- gewählte Zeile
        i = self._abschnitt("zeile", _("Selected line"))
        lay = QVBoxLayout(i)
        lay.setContentsMargins(0, 0, 0, 0)
        self.zeile_kopf = QLabel(_("Click into a line above."))
        lay.addWidget(self.zeile_kopf)
        self.stil = QComboBox()
        self.stil.addItems([_(t) for __, t in kpl.STILE])
        self.stil.activated.connect(lambda *a: self._zeilenwerte_uebernehmen())
        self.groesse = zahlfeld(self._zeilenwerte_uebernehmen)
        lay.addWidget(zeile(_("Style"), self.stil, _("Size"), self.groesse))
        self.gross = QCheckBox(_("Capitals"))
        self.gross.toggled.connect(lambda *a: self._zeilenwerte_uebernehmen())
        self.seiten = Wahl(kpl.SEITEN, self._zeilenwerte_uebernehmen)
        lay.addWidget(zeile(self.gross, _("Show on"), self.seiten))
        self.versatz = {}
        teile = [_("Move line")]
        for feld, text in (("line_h_nudge", _("← →")), ("line_v_nudge", _("↑ ↓"))):
            sp = self.versatz[feld] = QSpinBox()
            sp.setRange(-999, 999)
            sp.valueChanged.connect(lambda *a: self._zeilenwerte_uebernehmen())
            teile += [text, sp]
        k = QPushButton(_("Back to 0"))
        k.clicked.connect(self._versatz_zurueck)
        lay.addWidget(zeile(*teile, k))
        # Balken in der Zeile (Token %bar)
        self.zbalken_kopf = QLabel("")
        lay.addWidget(self.zbalken_kopf)
        self.zb = {"art": Wahl(kpl.BALKEN_ARTEN, self._zeilenbalken_uebernehmen),
                   "striche": Wahl(kpl.BALKEN_STRICHE, self._zeilenbalken_uebernehmen),
                   "stil": Wahl(kpl.BALKEN_STILE, self._zeilenbalken_uebernehmen),
                   "richtung": Wahl(kpl.RICHTUNGEN[:2], self._zeilenbalken_uebernehmen)}
        self.zb_rahmen = QWidget()                     # nur sichtbar, wenn die Zeile einen Balken hat
        zl = QVBoxLayout(self.zb_rahmen)
        zl.setContentsMargins(0, 0, 0, 0)
        zl.setSpacing(lay.spacing())
        zl.addWidget(zeile(self.zb["art"], self.zb["striche"]))
        zl.addWidget(zeile(self.zb["stil"], self.zb["richtung"]))
        self.zb_dicke = {}
        teile = []
        for feld, text in (("dicke", _("Thickness")), ("ungelesen", _("unread"))):
            self.zb_dicke[feld] = zahlfeld(self._zeilenbalken_uebernehmen)
            teile += [text, self.zb_dicke[feld]]
        zl.addWidget(zeile(*teile, hinweis("px")))
        lay.addWidget(self.zb_rahmen)
        self.zbalken_knopf = QPushButton("")
        self.zbalken_knopf.clicked.connect(self._zeilenbalken_umschalten)
        lay.addWidget(self.zbalken_knopf, 0, Qt.AlignLeft)
        lay.addWidget(hinweis(_("Empty size = the general font size. Move line in pixels: negative = left or up. Empty "
                                "thickness = as high as the text; empty unread = like read. Font per line, colours "
                                "and markers of a bar and conditions in the text stay as they are."), BREITE))

        # == Reiter Fortschrittsbalken über die ganze Breite
        self._reiter("balken", _("Progress bars"))
        i = self._flaeche("balken")
        lay = QVBoxLayout(i)
        lay.setContentsMargins(0, 0, 0, 0)
        self.balken_wahl = QComboBox()
        self.balken_wahl.activated.connect(self._balken_gewaehlt)
        self.balken_an = QCheckBox(_("Switched on"))
        self.balken_an.toggled.connect(lambda *a: self._balken_uebernehmen())
        lay.addWidget(zeile(self.balken_wahl, self.balken_an))
        self.bb = {"type": Wahl(kpl.BALKEN_ARTEN, self._balken_uebernehmen),
                   "chapter_ticks": Wahl(kpl.BALKEN_STRICHE, self._balken_uebernehmen),
                   "style": Wahl(kpl.BALKEN_STILE, self._balken_uebernehmen),
                   "direction": Wahl(kpl.RICHTUNGEN, self._balken_uebernehmen),
                   "v_anchor": Wahl(kpl.ANKER, self._balken_anker)}
        self.bb_kante = QLabel(_("Edge"))
        self.bb_rahmen = QWidget()                     # nur sichtbar, wenn der gewählte Balken eingeschaltet ist
        bl = QVBoxLayout(self.bb_rahmen)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(lay.spacing())
        bl.addWidget(zeile(self.bb["type"], self.bb["chapter_ticks"]))
        bl.addWidget(zeile(self.bb["style"], self.bb["direction"]))
        bl.addWidget(zeile(self.bb_kante, self.bb["v_anchor"]))
        self.bb_zahl, self.bb_zahl_text = {}, {}
        g = QGridLayout()
        for r, felder in enumerate(((("height", _("Thickness")), ("unread_height", _("unread"))),
                                    (("margin_v", _("Distance from the edge")),),
                                    (("margin_left", _("Margin left")), ("margin_right", _("right"))))):
            for c, (feld, text) in enumerate(felder):
                lb = self.bb_zahl_text[feld] = QLabel(text)
                g.addWidget(lb, r, c * 2)
                self.bb_zahl[feld] = zahlfeld(self._balken_uebernehmen, negativ=feld == "margin_v")
                g.addWidget(self.bb_zahl[feld], r, c * 2 + 1)
        g.setColumnStretch(4, 1)
        bl.addLayout(g)
        lay.addWidget(self.bb_rahmen)
        self.balken_text = hinweis("", BREITE)
        lay.addWidget(self.balken_text)

        # == Reiter Vorlage: verwalten, Name, allgemeine Werte
        self._reiter("vorlage", _("Preset"))
        i = self._abschnitt("vorlage", _("Preset"))
        lay = QVBoxLayout(i)
        lay.setContentsMargins(0, 0, 0, 0)
        knoepfe = []
        for text, fn in ((_("New"), self.neu), (_("Duplicate"), self.duplizieren), (_("Delete"), self.loeschen)):
            k = QPushButton(text)
            k.clicked.connect(lambda *a, fn=fn: fn())
            knoepfe.append(k)
        lay.addWidget(zeile(*knoepfe))
        self.aktiv_text = hinweis("", BREITE)
        lay.addWidget(self.aktiv_text)
        self.aktiv_knopf = QPushButton(_("Make active"))
        self.aktiv_knopf.clicked.connect(self.aktiv_machen)
        lay.addWidget(self.aktiv_knopf, 0, Qt.AlignLeft)
        g = QGridLayout()
        self.name_feld, self.beschr_feld = QLineEdit(), QLineEdit()
        for r, (text, f) in enumerate(((_("Name"), self.name_feld), (_("Description"), self.beschr_feld))):
            g.addWidget(QLabel(text), r, 0)
            g.addWidget(f, r, 1)
            f.textEdited.connect(lambda *a: self._kopf_geaendert())
        lay.addLayout(g)

        # -- allgemein
        i = self._abschnitt("allgemein", _("General"))
        lay = QVBoxLayout(i)
        lay.setContentsMargins(0, 0, 0, 0)
        g = QGridLayout()
        self.allg = {}
        for r, (schl, text, vorgabe) in enumerate(kpl.ALLGEMEIN):
            g.addWidget(QLabel(_(text)), r, 0)
            self.allg[schl] = zahlfeld(self._allgemein_geaendert)
            g.addWidget(self.allg[schl], r, 1)
            g.addWidget(hinweis(_("empty = {wert}").format(wert=vorgabe if vorgabe is not None else
                                                           _("size of KOReader's status bar"))), r, 2)
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        self.kuerzen = {}
        self.kuerzen_gruppe = QButtonGroup(i)
        for wert, text in kpl.KUERZEN:
            r = self.kuerzen[wert] = QRadioButton(_(text))
            r.toggled.connect(lambda an: an and self._allgemein_geaendert())
            self.kuerzen_gruppe.addButton(r)
            lay.addWidget(r)
        if self.info:
            self._kopf_zeigen()
            self._tokens_fuellen()
        self._formular_fuellen()

    # ------------------------------------------------------------------ Positionsschema (seit 2.2)
    def _schema_bauen(self):
        """Kleine Seite mit den sechs Positionen (3 oben, 3 unten); Knopf zeigt die erste Zeile."""
        rahmen = QFrame()
        rahmen.setFrameShape(QFrame.StyledPanel)
        rahmen.setMaximumWidth(BREITE)
        g = QGridLayout(rahmen)
        g.setContentsMargins(6, 6, 6, 6)
        g.setSpacing(4)
        self.schema_gruppe = QButtonGroup(rahmen)
        self.schema_gruppe.setExclusive(True)
        self.schema_knoepfe = {}
        for n, (pos, name) in enumerate(kpl.POSITIONEN):
            k = QToolButton()
            k.setCheckable(True)
            k.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            k.setToolTip(_(name))
            k.clicked.connect(lambda *a, p=pos: self.position_waehlen(p))
            self.schema_gruppe.addButton(k)
            self.schema_knoepfe[pos] = k
            g.addWidget(k, 0 if n < 3 else 2, n % 3)
        mitte = hinweis(_("page text"))
        mitte.setAlignment(Qt.AlignCenter)
        mitte.setMinimumHeight(34)
        g.addWidget(mitte, 1, 0, 1, 3)
        for c in range(3):
            g.setColumnStretch(c, 1)
        return rahmen

    def _schema_text(self, pos):
        z = [x for x in kpl.zeilen(self.daten or {}, pos) if x.strip()]
        if not z:
            return "–"
        k = self.schema_knoepfe[pos]
        text = k.fontMetrics().elidedText(z[0].strip(), Qt.ElideRight, max(40, (BREITE - 40) // 3 - 14))
        return text + (f" +{len(z) - 1}" if len(z) > 1 else "")

    def _schema_fuellen(self):
        if not self.gebaut():
            return
        if self.pos_wahl not in kpl.POS_KENNUNGEN:
            d = self.daten or {}
            self.pos_wahl = next((p for p in kpl.POS_KENNUNGEN if any(x.strip() for x in kpl.zeilen(d, p))), "tc")
        for pos, k in self.schema_knoepfe.items():
            k.setText(self._schema_text(pos))
            k.setChecked(pos == self.pos_wahl)
            f = k.font()
            f.setBold(pos == self.pos_wahl)
            k.setFont(f)
        for pos, r in self.pos_rahmen.items():
            r.setVisible(pos == self.pos_wahl)

    def position_waehlen(self, pos):
        """Position im Schema wählen: nur ihr Text und Rand sind zu sehen; die Zeile unter dem Cursor gilt."""
        self.pos_wahl = pos
        self._fokus_pos = pos
        self._schema_fuellen()
        if self.gebaut():
            self._zeile_gewaehlt(pos)

    def reiter_geaendert(self):
        if self.daten is None:
            return set()
        d, g = self.daten, self.gespeichert or {}
        erg = set()
        if (d.get("positions") or {}) != (g.get("positions") or {}):
            erg.add("zeilen")
        if kpl.balken_liste(d) != kpl.balken_liste(g):
            erg.add("balken")
        rest = {k for k in set(d) | set(g) if k not in ("positions", "progress_bars") and d.get(k) != g.get(k)}
        if rest or self.gespeichert is None or self.an != bool(self.stand_profil["an"]) or self.aktiv_neu:
            erg.add("vorlage")
        return erg

    def _hoehe(self, t, zeilen):
        z = max(2, min(6, zeilen + 1))
        t.setFixedHeight(t.fontMetrics().lineSpacing() * z + 12)

    def _fokus_gesetzt(self, obj):
        pos = obj.property("position")
        if pos:
            self._fokus_pos = pos

    def zuruecksetzen(self):
        self.datei = self.daten = self.gespeichert = None
        self.aktiv_neu = None

    # ------------------------------------------------------------------ Laden
    def _kopf_zeigen(self):
        if self.gebaut() and self.info:
            self.kopf.setText(_("Bookends {version} in the profile. Changes show in the picture at once.").format(
                version=self.info["version"] or "?"))

    def neu_laden(self, datei=None):
        """Vorlagen und Stand aus dem Profil lesen; datei: diese zeigen (sonst die bisherige/aktive)."""
        self.info = kpl.erkennen(self.bereich.profil).get(kpl.BOOKENDS)
        if not self.info:
            return
        self._kopf_zeigen()
        self.stand_profil = kpl.bookends_stand(self.ko)
        self.aktiv_neu = None
        self.an = bool(self.stand_profil["an"])
        self._tokens_fuellen()
        vl = kpl.vorlagen(self.ko)
        self._namen = {}
        for v in vl:
            name = v["name"] if v["name"] not in self._namen else f"{v['name']} ({v['datei']})"
            self._namen[name] = v["datei"]
        datei = datei or self.datei or self.stand_profil["aktiv"]
        if datei not in self._namen.values():
            datei = self.stand_profil["aktiv"] if self.stand_profil["aktiv"] in self._namen.values() else (
                vl[0]["datei"] if vl else None)
        self._vorlage_zeigen(datei)

    def _anzeige(self, datei):
        for n, d in self._namen.items():
            if d == datei:
                return n
        return (self.daten or {}).get("name") or datei

    def _vorlage_zeigen(self, datei, daten=None):
        self.datei = datei
        if datei and daten is None:
            try:
                daten = kpl.vorlage_lesen(self.ko, datei)
                self.gespeichert = copy.deepcopy(daten)
            except (OSError, ValueError) as e:
                self.app.status.set(_("Preset {datei} could not be read: {fehler}").format(datei=datei, fehler=e))
                daten, self.gespeichert = None, None
        elif daten is not None:
            self.gespeichert = None                # neu, noch nicht im Profil
        self.daten = daten
        self._zeile = None
        self._formular_fuellen()

    def _formular_fuellen(self):
        if not self.gebaut():
            return
        self._laden = True
        try:
            self.an_knopf.setChecked(self.an)
            werte = list(self._namen)
            if self.datei and self.datei not in self._namen.values():      # neue, noch nicht gespeicherte
                werte.append(self._anzeige(self.datei))
            self.wahl.clear()
            self.wahl.addItems(werte)
            self.wahl.setCurrentIndex(werte.index(self._anzeige(self.datei)) if self.datei else -1)
            d = self.daten or {}
            self.name_feld.setText(d.get("name") or "")
            self.beschr_feld.setText(d.get("description") or "")
            for pos, t in self.texte.items():
                z = kpl.zeilen(d, pos)
                t.setPlainText("\n".join(z))
                t.setReadOnly(self.daten is None)
                self._hoehe(t, len(z))
            for schl, f in self.allg.items():
                w = kpl.allgemein(d, schl)
                f.setText("" if w is None else str(w))
            for (pos, feld), f in self.rand.items():
                w = kpl.positionswert(d, pos, feld)
                f.setText("" if not w else str(w))
            self.kuerzen.get(kpl.allgemein(d, "truncation_priority") or "center", self.kuerzen["center"]).setChecked(True)
            self._schema_fuellen()
            self._zeile_zeigen()
            self._balken_zeigen()
        finally:
            self._laden = False
        self._aktiv_zeigen()
        self.stand_zeigen()

    def _aktiv_zeigen(self):
        if not self.gebaut():
            return
        aktiv = self.aktiv_neu or self.stand_profil["aktiv"]
        if not self.datei:
            text = _("No preset in the profile. \"New\" makes one.")
        elif self.datei == aktiv:
            text = _("This is the active preset (Bookends uses it on the e-reader).")
        else:
            text = _("Not active: on the e-reader Bookends uses \"{name}\". The picture shows this one.").format(
                name=self._anzeige(aktiv) if aktiv else "?")
        self.aktiv_text.setText(text)
        self.aktiv_knopf.setEnabled(bool(self.datei and self.datei != aktiv))

    def _tokens_fuellen(self):
        if not self.gebaut():
            return
        m = self.token_menue
        m.clear()
        gruppen = {}
        for gruppe, token, beschreibung in kpl.tokens(self.info["ordner"]) if self.info else []:
            if gruppe.lower() == "all":
                continue
            if gruppe not in gruppen:
                gruppen[gruppe] = m.addMenu(gruppe)
            gruppen[gruppe].addAction(f"{token}  -  {beschreibung}", lambda t=token: self._einfuegen(t))
        self.token_knopf.setEnabled(bool(gruppen))

    # ------------------------------------------------------------------ Bearbeiten
    def ungespeichert(self):
        if self.daten is None:
            return False
        if self.gespeichert is None or self.daten != self.gespeichert:
            return True
        return self.an != bool(self.stand_profil["an"]) or bool(self.aktiv_neu)

    def _an_geaendert(self, an):
        if self._laden:
            return
        self.an = bool(an)
        self._geaendert()

    def _einfuegen(self, token):
        if self.daten is None or not self.gebaut():
            return
        t = self.texte.get(self._fokus_pos) or self.texte["tc"]
        t.insertPlainText(token)
        t.setFocus()

    def symbole_zeigen(self):
        """Fenster mit den Sonderzeichen aus Bookends' Katalog; Klick fügt ins zuletzt benutzte Feld ein."""
        if self._symbolfenster is not None and self._symbolfenster.isVisible():
            self._symbolfenster.raise_()
            return
        gruppen = kpl.symbole(self.info["ordner"]) if self.info else []
        if not gruppen:
            self.app.status.set(_("This Bookends version has no list of special characters."))
            return
        self._symbolfenster = SymbolFenster(self, gruppen)
        self._symbolfenster.show()

    def _text_geaendert(self, pos):
        if self._laden or self.daten is None:
            return
        t = self.texte[pos]
        z = t.toPlainText().split("\n")
        while z and not z[-1].strip():
            z.pop()
        if z != kpl.zeilen(self.daten, pos):
            kpl.zeilen_setzen(self.daten, pos, z)
            self._hoehe(t, len(z))
            self._schema_fuellen()
            self._zeile_gewaehlt(pos, neu_zeigen=True)
            self._geaendert()

    def _zeile_gewaehlt(self, pos, neu_zeigen=False):
        if self._laden:
            return
        t = self.texte[pos]
        self._fokus_pos = pos
        nr = t.textCursor().blockNumber() + 1
        neu = (pos, nr) if self.daten is not None and nr <= len(kpl.zeilen(self.daten, pos)) else None
        if neu != self._zeile or neu_zeigen:
            self._zeile = neu
            self._zeile_zeigen()

    def zeile_waehlen(self, pos, nr):
        """Zeile wählen wie mit einem Klick hinein (Tests)."""
        if pos != self.pos_wahl:
            self.position_waehlen(pos)
        t = self.texte[pos]
        c = t.textCursor()
        c.movePosition(QTextCursor.Start)
        c.movePosition(QTextCursor.NextBlock, QTextCursor.MoveAnchor, nr - 1)
        t.setTextCursor(c)
        self._zeile_gewaehlt(pos)

    def _zeile_zeigen(self):
        alt, self._laden = self._laden, True
        try:
            felder = (self.stil, self.groesse, self.gross, *self.versatz.values())
            if not self._zeile:
                self.zeile_kopf.setText(_("Click into a line above."))
                for w in felder:
                    w.setEnabled(False)
                self.stil.setCurrentIndex(-1)
                self.groesse.clear()
                self.gross.setChecked(False)
                for sp in self.versatz.values():
                    sp.setValue(0)
                self.seiten.setzen(None, aktiv=False)
                self._zeilenbalken_zeigen()
                return
            pos, nr = self._zeile
            name = dict(kpl.POSITIONEN)[pos]
            self.zeile_kopf.setText(_("{position}, line {nr}").format(position=_(name), nr=nr))
            for w in felder:
                w.setEnabled(True)
            for feld, sp in self.versatz.items():
                sp.setValue(int(kpl.zeilenwert(self.daten, pos, feld, nr) or 0))
            stil = kpl.zeilenwert(self.daten, pos, "line_style", nr) or "regular"
            self.stil.setCurrentIndex(max(0, next((n for n, (k, __) in enumerate(kpl.STILE) if k == stil), 0)))
            g = kpl.zeilenwert(self.daten, pos, "line_font_size", nr)
            self.groesse.setText("" if g is None else str(g))
            self.gross.setChecked(bool(kpl.zeilenwert(self.daten, pos, "line_uppercase", nr)))
            self.seiten.setzen(kpl.zeilenwert(self.daten, pos, "line_page_filter", nr), aktiv=True)
            self._zeilenbalken_zeigen()
        finally:
            self._laden = alt

    def _zeilentext(self):
        if not self._zeile or self.daten is None:
            return ""
        pos, nr = self._zeile
        z = kpl.zeilen(self.daten, pos)
        return z[nr - 1] if nr <= len(z) else ""

    def _zeilenbalken_zeigen(self):
        """Balken-Felder der gewählten Zeile; nur bedienbar, wenn die Zeile %bar enthält."""
        alt, self._laden = self._laden, True
        try:
            mit = kpl.hat_balken(self._zeilentext())
            self.zbalken_kopf.setText(_("Bar in this line") if mit else _("No bar in this line (token %bar)."))
            self.zbalken_knopf.setText(_("Remove bar") if mit else _("Insert bar"))
            self.zbalken_knopf.setEnabled(bool(self._zeile))
            self.zb_rahmen.setVisible(mit)
            werte = kpl.zeilenbalken(self.daten, *self._zeile) if mit else {}
            for k, w in self.zb.items():
                w.setzen(werte.get(k), aktiv=mit)
            if mit:
                self.zb["striche"].setEnabled(werte["art"] == "book" and werte["stil"] != "pacman")
                self.zb["richtung"].setEnabled(werte["stil"] not in ("radial", "radial_hollow"))
            for k, f in self.zb_dicke.items():
                w = werte.get(k)
                if k == "ungelesen" and w is None:
                    w = werte.get("dicke")
                f.setText("" if w is None else str(w))
                f.setEnabled(mit)
        finally:
            self._laden = alt

    def _zeilenbalken_umschalten(self):
        """%bar in die gewählte Zeile setzen bzw. herausnehmen (Leerzeichen wie Bookends' Knopf „Bar“)."""
        if not self._zeile or self.daten is None:
            return
        pos, nr = self._zeile
        z = kpl.zeilen(self.daten, pos)
        t = z[nr - 1]
        if kpl.hat_balken(t):
            t = re.sub(r"\s*%bar\s*", " ", t).strip()
        else:
            t = (t + " %bar").strip()
        z[nr - 1] = t
        kpl.zeilen_setzen(self.daten, pos, z)
        self._laden = True
        try:
            self.texte[pos].setPlainText("\n".join(z))
        finally:
            self._laden = False
        self._schema_fuellen()
        self._zeilenbalken_zeigen()
        self._geaendert()

    def _zeilenbalken_uebernehmen(self):
        if self._laden or not self._zeile or self.daten is None or not kpl.hat_balken(self._zeilentext()):
            return
        werte = {k: w.wert() for k, w in self.zb.items()}
        try:
            for k, f in self.zb_dicke.items():
                g = zahl_oder_leer(f.text())
                werte[k] = None if g is None else int(g)
        except ValueError:
            return
        kpl.zeilenbalken_setzen(self.daten, *self._zeile, werte)
        self.zb["striche"].setEnabled(werte["art"] == "book" and werte["stil"] != "pacman")
        self.zb["richtung"].setEnabled(werte["stil"] not in ("radial", "radial_hollow"))
        self._geaendert()

    # ------------------------------------------------------------------ Balken über die ganze Breite
    def _balken_zeigen(self):
        alt, self._laden = self._laden, True
        try:
            d = self.daten or {}
            self.balken_wahl.clear()
            for n in range(1, kpl.BALKEN_ANZAHL + 1):
                b = kpl.balken(d, n)
                self.balken_wahl.addItem(_("Bar {nr}").format(nr=n) + (
                    " ✓ " + _(dict(kpl.ANKER)[b.get("v_anchor", "bottom")]) if b.get("enabled") else ""))
            nr = self.balken_nr
            self.balken_wahl.setCurrentIndex(nr - 1)
            b = kpl.balken(d, nr)
            an = bool(b.get("enabled")) and self.daten is not None
            self.balken_an.setChecked(bool(b.get("enabled")))
            self.balken_an.setEnabled(self.daten is not None)
            self.bb_rahmen.setVisible(an)
            rund = b.get("style") in ("radial", "radial_hollow")
            for feld, w in self.bb.items():
                if feld == "direction":
                    w.optionen([o for o in kpl.RICHTUNGEN if o[0] in kpl.balken_richtungen(b)])
                    w.setzen(kpl.balken_richtung(b), aktiv=an and not rund)
                else:
                    w.setzen(b.get(feld), aktiv=an)
            self.bb["chapter_ticks"].setEnabled(an and b.get("type") == "book" and b.get("style") != "pacman")
            relativ = b.get("band_offset") is not None and not kpl.balken_senkrecht(b)
            senkrecht = kpl.balken_senkrecht(b)
            self.bb_zahl_text["height"].setText(_("Diameter") if rund else _("Thickness"))
            self.bb_zahl_text["margin_v"].setText(_("Distance from the line text") if relativ else
                                                  _("Distance from the edge"))
            self.bb_zahl_text["margin_left"].setText(_("Margin top") if senkrecht else _("Margin left"))
            self.bb_zahl_text["margin_right"].setText(_("bottom") if senkrecht else _("right"))
            for feld, f in self.bb_zahl.items():
                if feld == "margin_v" and relativ:
                    w = b.get("band_offset")
                elif feld == "unread_height":
                    w = b.get("unread_height", b.get("height"))
                else:
                    w = b.get(feld)
                f.setText("" if w is None else str(w))
                f.setEnabled(an)
            for lab in list(self.bb_zahl_text.values()) + [self.bb_kante]:
                lab.setEnabled(an)
            self.balken_text.setText(_("Up to {n} bars across the page. Colours, markers and \"Position relative to "
                                       "line text\" stay as they are; switch those on the e-reader.")
                                     .format(n=kpl.BALKEN_ANZAHL))
        finally:
            self._laden = alt

    def _balken_gewaehlt(self, i):
        self.balken_nr = i + 1
        self._balken_zeigen()

    def _balken_uebernehmen(self):
        if self._laden or self.daten is None:
            return
        nr = self.balken_nr
        b = kpl.balken(self.daten, nr)
        werte = {"enabled": True if self.balken_an.isChecked() else False}
        for feld in ("type", "chapter_ticks", "style"):
            werte[feld] = self.bb[feld].wert()
        stil = werte["style"]
        richtung = self.bb["direction"].wert()
        probe = {**b, **werte}
        moeglich = kpl.balken_richtungen(probe)
        if richtung not in moeglich:
            richtung = moeglich[0] if moeglich else None
        vorgabe = "ttb" if kpl.balken_senkrecht(probe) else "ltr"
        werte["direction"] = None if richtung in (None, vorgabe) else richtung
        relativ = b.get("band_offset") is not None and not kpl.balken_senkrecht(b)
        try:
            for feld, f in self.bb_zahl.items():
                g = zahl_oder_leer(f.text())
                g = None if g is None else int(g)
                if feld == "margin_v" and relativ:
                    werte["band_offset"] = g or 0
                elif feld == "unread_height":
                    dicke = werte.get("height", b.get("height"))
                    werte[feld] = None if g is None or g == dicke else g
                elif feld == "height":
                    werte[feld] = g if g is not None else (60 if stil in ("radial", "radial_hollow") else 20)
                else:
                    werte[feld] = g or 0
        except ValueError:
            return
        kpl.balken_aendern(self.daten, nr, **werte)
        self._balken_zeigen()
        self._geaendert()

    def _balken_anker(self):
        if self._laden or self.daten is None:
            return
        kpl.balken_anker_setzen(self.daten, self.balken_nr, self.bb["v_anchor"].wert())
        self._balken_zeigen()
        self._geaendert()

    def _zeilenwerte_uebernehmen(self):
        if self._laden or not self._zeile or self.daten is None:
            return
        pos, nr = self._zeile
        i = self.stil.currentIndex()
        stil = kpl.STILE[i][0] if 0 <= i < len(kpl.STILE) else "regular"
        kpl.zeilenwert_setzen(self.daten, pos, "line_style", nr, None if stil == "regular" else stil)
        try:
            g = zahl_oder_leer(self.groesse.text())
        except ValueError:
            return
        kpl.zeilenwert_setzen(self.daten, pos, "line_font_size", nr, g)
        kpl.zeilenwert_setzen(self.daten, pos, "line_uppercase", nr, True if self.gross.isChecked() else None)
        for feld, sp in self.versatz.items():
            kpl.zeilenwert_setzen(self.daten, pos, feld, nr, sp.value() or None)    # 0 = kein Eintrag, wie Bookends
        kpl.zeilenwert_setzen(self.daten, pos, "line_page_filter", nr, self.seiten.wert())
        self._geaendert()

    def _versatz_zurueck(self):
        self._laden = True
        for sp in self.versatz.values():
            sp.setValue(0)
        self._laden = False
        self._zeilenwerte_uebernehmen()

    def _rand_geaendert(self, pos):
        if self._laden or self.daten is None:
            return
        for (p, feld), f in self.rand.items():
            if p != pos:
                continue
            try:
                w = zahl_oder_leer(f.text())
            except ValueError:
                return
            kpl.positionswert_setzen(self.daten, pos, feld, int(w) if w else None)
        self._geaendert()

    def _allgemein_geaendert(self):
        if self._laden or self.daten is None:
            return
        for schl, f in self.allg.items():
            try:
                kpl.allgemein_setzen(self.daten, schl, zahl_oder_leer(f.text()))
            except ValueError:
                return
        k = next((w for w, r in self.kuerzen.items() if r.isChecked()), "center")
        kpl.allgemein_setzen(self.daten, "truncation_priority", None if k == "center" and
                             kpl.allgemein(self.gespeichert or {}, "truncation_priority") is None else k)
        self._geaendert()

    def _kopf_geaendert(self):
        if self._laden or self.daten is None:
            return
        for schl, f in (("name", self.name_feld), ("description", self.beschr_feld)):
            w = f.text().strip()
            if w:
                self.daten[schl] = w
            else:
                self.daten.pop(schl, None)
        self._geaendert(bild=False)

    def _geaendert(self, bild=True):
        if self._laden:
            return
        self.stand_zeigen()
        if bild:
            self._planen(PAUSE_BOOKENDS, self.ins_bild)

    # ------------------------------------------------------------------ Werkbank
    def in_kopie(self, ko):
        """Vor dem Start der Werkbank: Entwurf in die Wegwerf-Kopie (Bookends lädt beim Start die aktive Vorlage)."""
        if self.daten is None or not self.datei:
            return
        kpl.vorlage_schreiben(ko, self.datei, self.daten)
        kpl.bookends_setzen(ko, an=self.an, aktiv=self.datei)

    def ins_bild(self):
        """Entwurf in die laufende Werkbank: Vorlage schreiben, übernehmen lassen, neues Bild."""
        wb = self.bereich.werkbank
        if self.daten is None or not self.datei:
            return
        if self.bereich.modus() != "lesen":
            if self.bereich.unterseite() == self.plugin:  # nur von der eigenen Seite aus die Ansicht wechseln
                self.bereich.modus_setzen("lesen")        # startet neu, in_kopie() bringt den Entwurf mit
            return
        if not (wb and wb.laeuft() and wb.bereit):
            return                                        # beim nächsten Start über in_kopie()
        kpl.vorlage_schreiben(wb.ko, self.datei, self.daten)
        wb.bookends_an(self.an)
        wb.bookends(self.datei)
        wb.bild()
        self.bereich._takt_planen()

    def beim_zeigen(self):
        if self.daten is None:
            self.neu_laden()
        if self.bereich.modus() != "lesen":
            self.bereich.modus_setzen("lesen")

    # ------------------------------------------------------------------ Vorlagen
    def _wahl_gewechselt(self):
        datei = self._namen.get(self.wahl.currentText())
        if datei == self.datei or datei is None:
            return
        if not self._verwerfen_erlaubt():
            self._formular_fuellen()
            return
        self.aktiv_neu = None
        self.an = bool(self.stand_profil["an"])
        self._vorlage_zeigen(datei)
        self.ins_bild()

    def vorlage_waehlen(self, name):
        """Vorlage über ihren Anzeigenamen wählen (Tests)."""
        if self.gebaut():
            self.wahl.setCurrentText(name)
        self._wahl_gewechselt()

    def _verwerfen_erlaubt(self):
        if not self.ungespeichert():
            return True
        a = dialogs.frage3(self.app, "Bookends", _("The preset \"{name}\" has unsaved changes. Save them in the "
                                                   "profile?").format(name=self._anzeige(self.datei)))
        if a is None:
            return False
        if a:
            self.speichern()
        return True

    def neu(self, vorlage=None):
        if not self.info or not self._verwerfen_erlaubt():
            return
        name = dialogs.eingabe(self.app, _("New preset"), _("Name of the new preset:"),
                               _("{name} (copy)").format(name=vorlage["name"]) if (vorlage or {}).get("name") else "")
        if not name or not name.strip():
            return
        daten = copy.deepcopy(vorlage) if vorlage else kpl.leere_vorlage(name.strip())
        daten["name"] = name.strip()
        datei = kpl.dateiname(self.ko, name.strip())
        self._vorlage_zeigen(datei, daten)
        self.stand_zeigen()
        self.ins_bild()

    def duplizieren(self):
        if self.daten is not None:
            self.neu(self.daten)

    def loeschen(self):
        if not self.datei:
            return
        if self.gespeichert is None:                      # nur Entwurf: einfach weg
            self.datei = self.daten = None
            self.neu_laden()
            self.ins_bild()
            return
        if not dialogs.frage(self.app, "Bookends", _("Delete the preset \"{name}\" from the profile?").format(
                name=self._anzeige(self.datei))):
            return
        try:
            (kpl.vorlagen_ordner(self.ko) / self.datei).unlink()
        except OSError as e:
            self.app.status.set(str(e))
            return
        if self.stand_profil["aktiv"] == self.datei:
            rest = kpl.vorlagen(self.ko)
            kpl.einstellungen_schreiben(kpl.bookends_datei(self.ko), {
                "active_preset_filename": rest[0]["datei"] if rest else None,
                "manual_active_preset_filename": rest[0]["datei"] if rest else None})
        kpl._profil_geaendert(self.bereich.profil, "bookends")
        self.app.status.set(_("Preset deleted from the profile."))
        self.datei = self.daten = None
        self.neu_laden()
        self.bereich.werkbank_starten(still=True)

    def aktiv_machen(self):
        if self.datei:
            self.aktiv_neu = self.datei
            self._aktiv_zeigen()
            self.stand_zeigen()

    # ------------------------------------------------------------------ Speichern
    def speichern(self):
        if self.daten is None or not self.datei:
            return False
        kpl.vorlage_schreiben(self.ko, self.datei, self.daten)
        kpl.bookends_setzen(self.ko, an=self.an, aktiv=self.aktiv_neu)
        kpl._profil_geaendert(self.bereich.profil, "bookends")
        self.app.status.set(_("Bookends preset \"{name}\" saved in the profile.").format(name=self._anzeige(self.datei)))
        self.neu_laden(self.datei)
        return True

    def verwerfen(self):
        if self.ungespeichert() and not self.verwerfen_ok():
            return
        datei = self.datei if self.gespeichert is not None else None
        self.datei = self.daten = None
        self.neu_laden(datei)
        self.ins_bild()


class SymbolFenster(QDialog):
    """Sonderzeichen aus Bookends' Katalog (menu/icons_catalogue.lua), nach Gruppen. Bleibt offen; jeder Klick
    fügt an der Schreibmarke des zuletzt benutzten Zeilenfelds ein."""
    SPALTEN = 10

    def __init__(self, seite, gruppen):
        super().__init__(seite.app)
        self.seite, self.gruppen = seite, gruppen
        self.setWindowTitle(_("Special characters"))
        self.resize(480, 440)
        lay = QVBoxLayout(self)
        self.gruppe = QComboBox()
        self.gruppe.addItems([g for g, __ in gruppen])
        self.gruppe.currentIndexChanged.connect(lambda *a: self.fuellen())
        lay.addWidget(zeile(_("Group"), self.gruppe))
        self.flaeche = QScrollArea()
        self.flaeche.setWidgetResizable(True)
        lay.addWidget(self.flaeche, 1)
        self.familie = seite.symbolfamilie()
        self.text = hinweis("")
        if not self.familie:
            self.text.setText(_("KOReader's symbol font (nerdfonts/symbols.ttf) was not found: symbols show as names. "
                                "Take the profile from the e-reader to get its fonts."))
        lay.addWidget(self.text)
        self.fuellen()

    def fuellen(self):
        innen = QWidget()
        g = QGridLayout(innen)
        g.setSpacing(2)
        liste = dict(self.gruppen).get(self.gruppe.currentText(), [])
        schrift = QFont(self.font())
        schrift.setPointSize(14)
        if self.familie:
            schrift.setFamilies(list(schrift.families() or [schrift.family()]) + [self.familie])
        self.knoepfe = []
        for n, (ch, name, einfuegen) in enumerate(liste):
            k = QToolButton()
            k.setText(ch if (self.familie or not kpl.ist_symbol(ch)) else name[:6])
            k.setFont(schrift)
            k.setFixedSize(38, 38)
            tipp = name + (f"  ({einfuegen})" if einfuegen != ch else "")
            k.setToolTip(tipp)
            k.clicked.connect(lambda *a, w=einfuegen, t=tipp: (self.seite._einfuegen(w), self.text.setText(t)))
            g.addWidget(k, n // self.SPALTEN, n % self.SPALTEN)
            self.knoepfe.append(k)
        g.setRowStretch(len(liste) // self.SPALTEN + 1, 1)
        self.flaeche.setWidget(innen)


# ====================================================================== Bookshelf
def _baum(spalten=1, hoehe=8):
    b = QTreeWidget()
    b.setColumnCount(spalten)
    b.setHeaderHidden(True)
    b.setRootIsDecorated(False)
    b.setMinimumHeight(hoehe * 20 + 6)
    b.setMaximumHeight(hoehe * 24 + 6)
    if spalten > 1:
        b.header().setStretchLastSection(False)
        b.header().setSectionResizeMode(0, QHeaderView.Stretch)
        b.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
    return b


def _gewaehlt_id(baum):
    it = baum.currentItem()
    return it.data(0, Qt.UserRole) if it else None


def _waehlen(baum, kennung):
    if not kennung:
        return
    for it in _alle_items(baum):
        if it.data(0, Qt.UserRole) == kennung:
            baum.setCurrentItem(it)
            baum.scrollToItem(it)
            return


def _alle_items(baum):
    stapel = [baum.topLevelItem(i) for i in range(baum.topLevelItemCount())]
    while stapel:
        it = stapel.pop(0)
        yield it
        stapel[0:0] = [it.child(i) for i in range(it.childCount())]


def _leeren(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            _leeren(it.layout())


def _menueknopf(text):
    k = QToolButton()
    k.setText(text)
    k.setPopupMode(QToolButton.InstantPopup)
    k.setMenu(QMenu(k))
    return k


class BookshelfSeite(_SymbolSeite):
    plugin = kpl.BOOKSHELF
    titel = "Bookshelf"

    def __init__(self, bereich):
        super().__init__(bereich)
        self.datei_werte = None                   # settings.lua im Profil (dict), None = nicht geladen
        self.aenderungen = {}                     # Entwurf: Schlüssel -> Wert (None = löschen)
        self._laden = False
        self.hero_kennung = "metadata"
        self.auswahl = {}                         # Liste -> gewählte Kennung (übersteht den Neuaufbau)
        self._deko = {}

    # ------------------------------------------------------------------ Aufbau
    def inhalt_bauen(self):
        self.felder = {}                          # Schlüssel -> Widget (feste Auswahl, Schalter)
        self.wahlen = {}                          # Name -> (QComboBox, [(wert, text)], holen(), setzen(wert))
        self.farb_felder = {}
        self.familie = self.symbolfamilie()
        self.lay.addWidget(hinweis(_("Bookshelf has no way to reload its settings while running: after a change the "
                                     "workbench restarts on the start screen (about a second)."), BREITE))
        self.lay.addWidget(QLabel(_("Start screen shows:")))
        self.start_gruppe = QButtonGroup(self.rahmen)
        self.start_knopf = {}
        for wert, text in (("beispiel", _("sample books")), ("bibliothek", _("the opened library"))):
            r = self.start_knopf[wert] = QRadioButton(text)
            r.setStyleSheet("QRadioButton { margin-left: 12px; }")
            r.toggled.connect(lambda an, w=wert: an and self.bereich.startbuecher_setzen(w))
            self.start_gruppe.addButton(r)
            self.lay.addWidget(r)
        self.startbuecher_zeigen(beim_bauen=True)

        def gitter(i):
            g = QGridLayout(i)
            g.setContentsMargins(0, 0, 0, 0)
            g.setColumnStretch(1, 1)
            return g
        def feste(gruppe, offen=False):
            gtext = dict(kpl.BOOKSHELF_GRUPPEN)[gruppe]
            g = gitter(self._abschnitt(gruppe, _(gtext), offen=offen))
            r = 0
            for schl, gr, text, art, vorgabe, wahl in kpl.BOOKSHELF_WERTE:
                if gr != gruppe:
                    continue
                if art == "an":
                    w = QCheckBox(_(text))
                    w.toggled.connect(lambda *a, s=schl: self._wert_geaendert(s))
                    g.addWidget(w, r, 0, 1, 2)
                elif art == "zahl":
                    g.addWidget(QLabel(_(text)), r, 0)
                    w = zahlfeld(lambda s=schl: self._wert_geaendert(s))
                    g.addWidget(w, r, 1, Qt.AlignLeft)
                else:
                    g.addWidget(QLabel(_(text)), r, 0)
                    w = QComboBox()
                    w.addItems([_(t) for __, t in wahl])
                    w.activated.connect(lambda *a, s=schl: self._wert_geaendert(s))
                    g.addWidget(w, r, 1, Qt.AlignLeft)
                self.felder[schl] = w
                r += 1

        # == Reiter (seit 2.2)
        self._reiter("aussehen", _("Appearance"))
        self.g_theme = gitter(self._abschnitt("theme", _("Themes")))
        self.g_hintergrund = gitter(self._abschnitt("hintergrund", _("Wallpaper"), offen=False))
        self.g_brett = gitter(self._abschnitt("brett", _("Plank"), offen=False))
        self.g_deko = gitter(self._abschnitt("deko", _("Decoration (ornaments)"), offen=False))
        self._farben_bauen(gitter(self._abschnitt("farben", _("Colours"), offen=False)))
        self._reiter("start", _("Home"))
        self._hero_bauen(self._abschnitt("hero", _("Top panel")))
        self._module_bauen(self._abschnitt("module", _("Modules in the top panel"), offen=False))
        self._reiter("navigation", _("Navigation"))
        self._menue_bauen(self._abschnitt("startmenue", _("Start menu")))
        self._regale_bauen(self._abschnitt("regale", _("Shelves"), offen=False))
        feste("leisten")
        self._reiter("anordnung", _("Layout"))
        feste("anordnung", offen=True)
        for gruppe in ("schrift", "cover", "anzeige"):
            feste(gruppe)

        # -- alle Schlüssel
        self._reiter("alle", _("All"))
        i = self._flaeche("alle")
        lay = QVBoxLayout(i)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(hinweis(_("For everything not on the other tabs. Double-click a simple value to change it; tables "
                                "(shelves, modules) only on the other tabs or in Bookshelf itself. \"Default\" "
                                "removes the key, then Bookshelf's default applies."), BREITE))
        self.baum = _baum(2, 10)
        self.baum.setHeaderHidden(False)
        self.baum.setHeaderLabels([_("Key"), _("Value")])
        self.baum.itemDoubleClicked.connect(lambda *a: self.schluessel_bearbeiten())
        self.baum.currentItemChanged.connect(lambda *a: self._merken("alle", self.baum))
        lay.addWidget(self.baum)
        k1, k2 = QPushButton(_("Change …")), QPushButton(_("Default"))
        k1.clicked.connect(self.schluessel_bearbeiten)
        k2.clicked.connect(self.schluessel_loeschen)
        lay.addWidget(zeile(k1, k2))
        if self.info:
            self._kopf_zeigen()
        if self.datei_werte is not None:
            self._dynamisch_bauen()
            self._formular_fuellen()

    def startbuecher_zeigen(self, beim_bauen=False):
        if not (beim_bauen or self.gebaut()):              # beim Bauen ist rahmen noch nicht gesetzt
            return
        wert = self.app.e.get("werkbank_startbuecher") or "beispiel"
        for w, r in self.start_knopf.items():
            r.blockSignals(True)
            r.setChecked(w == wert)
            r.blockSignals(False)

    def _merken(self, name, baum):
        if not self._laden:
            self.auswahl[name] = _gewaehlt_id(baum)

    # ------------------------------------------------------------------ Oberer Bereich (Hero-Karte)
    def _hero_bauen(self, i):
        lay = QVBoxLayout(i)
        lay.setContentsMargins(0, 0, 0, 0)
        self.hero_modus = Wahl(kpl.HERO_MODUS, self._hero_modus_geaendert)
        lay.addWidget(zeile(_("Shows"), self.hero_modus))
        lay.addWidget(hinweis(_("Lines of the hero card (the current book):")))
        self.hero_wahl = QComboBox()
        self.hero_wahl.activated.connect(self._hero_gewaehlt)
        self.hero_an = QCheckBox(_("Shown"))
        self.hero_an.toggled.connect(lambda *a: self._hero_uebernehmen())
        lay.addWidget(zeile(self.hero_wahl, self.hero_an))
        self.hero_text = QPlainTextEdit()
        self.hero_text.setFixedHeight(self.hero_text.fontMetrics().lineSpacing() * 2 + 14)
        mit_symbolen(self.hero_text, self.familie)
        self.hero_text.textChanged.connect(self._hero_uebernehmen)
        lay.addWidget(self.hero_text)
        self.hero_token = _menueknopf(_("Insert token"))
        self.hero_untertitel = QPushButton(_("Subtitle"))
        self.hero_untertitel.clicked.connect(self._hero_untertitel)
        k = QPushButton(_("Default"))
        k.clicked.connect(self._hero_zuruecksetzen)
        lay.addWidget(zeile(self.hero_token, self.hero_untertitel, k))
        self.hero_groesse = zahlfeld(self._hero_uebernehmen, breite=44)
        self.hero_ausrichtung = Wahl(kpl.HERO_AUSRICHTUNG, self._hero_uebernehmen)
        lay.addWidget(zeile(_("Size"), self.hero_groesse, self.hero_ausrichtung))
        self.hero_fett, self.hero_gross = QCheckBox(_("Bold")), QCheckBox(_("Capitals"))
        for c in (self.hero_fett, self.hero_gross):
            c.toggled.connect(lambda *a: self._hero_uebernehmen())
        lay.addWidget(zeile(self.hero_fett, self.hero_gross))
        self.hero_tags_rahmen = QWidget()
        g = QGridLayout(self.hero_tags_rahmen)
        g.setContentsMargins(0, 0, 0, 0)
        self.hero_tags = {}
        for n, (feld, text) in enumerate(kpl.HERO_TAGS):
            c = self.hero_tags[feld] = QCheckBox(_(text))
            c.toggled.connect(lambda *a: self._hero_uebernehmen())
            g.addWidget(c, n // 3, n % 3)
        self.hero_zeilen = zahlfeld(self._hero_uebernehmen, breite=36)
        g.addWidget(zeile(_("Rows at most"), self.hero_zeilen), 2, 0, 1, 3)
        lay.addWidget(self.hero_tags_rahmen)
        self.hero_hinweis = hinweis("", BREITE)
        lay.addWidget(self.hero_hinweis)

    def _hero_werte(self):
        """Einstellungen mit Entwurf, für hero_zeile()."""
        return {"hero_regions": self._wert("hero_regions")}

    def _hero_wahl_fuellen(self):
        w = self._hero_werte()
        self.hero_wahl.blockSignals(True)
        self.hero_wahl.clear()
        self.hero_wahl.addItems([_(t) + ("" if kpl.hero_zeile(w, k).get("disabled") else "  ✓")
                                 for k, t in kpl.HERO_ZEILEN])
        self.hero_wahl.setCurrentIndex([k for k, __ in kpl.HERO_ZEILEN].index(self.hero_kennung))
        self.hero_wahl.blockSignals(False)

    def _hero_fuellen(self):
        alt, self._laden = self._laden, True
        try:
            w = self._hero_werte()
            self.hero_modus.setzen(self._wert("hero_area_mode", "currently_reading"))
            self._hero_wahl_fuellen()
            kennung = self.hero_kennung
            z = kpl.hero_zeile(w, kennung)
            self.hero_an.setChecked(not z.get("disabled"))
            mit_text = kennung not in kpl.HERO_OHNE_VORLAGE
            self.hero_text.setPlainText((z.get("template") or "") if mit_text else "")
            self.hero_text.setReadOnly(not mit_text)
            self.hero_text.setEnabled(mit_text)
            for knopf in (self.hero_token, self.hero_untertitel, self.hero_fett):
                knopf.setEnabled(mit_text)
            fs = z.get("font_size", "")
            self.hero_groesse.setText("" if fs in ("", None) else str(fs))
            self.hero_ausrichtung.setzen(z.get("alignment", "left"))
            self.hero_fett.setChecked(bool(z.get("bold")))
            self.hero_gross.setChecked(bool(z.get("uppercase")))
            self.hero_gross.setEnabled(mit_text and kennung != "description")
            self.hero_tags_rahmen.setVisible(kennung == "tags")
            if kennung == "tags":
                for feld, c in self.hero_tags.items():
                    c.setChecked(z.get(feld, True) is not False)
                self.hero_zeilen.setText(str(z.get("max_rows", 2)))
            text = {
                "rating": _("Stars to tap; only on/off, size and alignment."),
                "tags": _("Buttons for author, series, collections, genres and folder, each can be hidden."),
                "metadata": _("An extra line between author and description; Bookshelf puts the series here by "
                              "default. \"Subtitle\" puts the book's subtitle here (needs the Bookbench patch "
                              "2-bookbench-subtitle, page Patches)."),
            }.get(kennung, _("Tokens like in Bookshelf's line editor, [if:token]…[/if] shows a part only if the token "
                             "has a value. Empty = the line is left out."))
            if mit_text and "%subtitle" in self._hero_text_lesen() and not self._untertitel_patch():
                text += "\n" + _("⚠ %subtitle needs the patch 2-bookbench-subtitle in the profile (page Patches).")
            self.hero_hinweis.setText(text)
            self._hero_token_menue_fuellen()
        finally:
            self._laden = alt

    def _untertitel_patch(self):
        return (self.ko / "patches" / "2-bookbench-subtitle.lua").is_file()

    def _hero_token_menue_fuellen(self):
        m = self.hero_token.menu()
        m.clear()
        gruppen = {}
        tokens = list(kpl.bookshelf_tokens(self.info["ordner"])) if self.info else []
        tokens.append(("Bookbench", "%subtitle", _("Subtitle from the EPUB (needs the Bookbench patch)")))
        for gruppe, token, text in tokens:
            if gruppe not in gruppen:
                gruppen[gruppe] = m.addMenu(gruppe)
            gruppen[gruppe].addAction(f"{token}  –  {text}", lambda t=token: self._hero_einfuegen(t))

    def _hero_einfuegen(self, token):
        if self.hero_text.isReadOnly():
            return
        self.hero_text.insertPlainText(token)
        self.hero_text.setFocus()

    def _hero_untertitel(self):
        """Untertitel in die Zeile setzen (Metadata: ersetzt die Reihe; sonst ans Ende)."""
        if self.hero_kennung == "metadata":
            text = kpl.HERO_UNTERTITEL
        else:
            text = (self._hero_text_lesen() + " " + kpl.HERO_UNTERTITEL).strip()
        self.hero_text.setPlainText(text)

    def _hero_text_lesen(self):
        return self.hero_text.toPlainText().strip("\n")

    def _hero_gewaehlt(self, i):
        self.hero_kennung = kpl.HERO_ZEILEN[i][0]
        self._hero_fuellen()

    def hero_waehlen(self, kennung):
        self.hero_kennung = kennung
        self._hero_fuellen()

    def _hero_uebernehmen(self):
        if self._laden or self.datei_werte is None:
            return
        k = self.hero_kennung
        felder = {"disabled": None if self.hero_an.isChecked() else True}
        try:
            g = zahl_oder_leer(self.hero_groesse.text())
        except ValueError:
            return
        felder["font_size"] = None if g is None else int(g)
        felder["alignment"] = self.hero_ausrichtung.wert()
        if k not in kpl.HERO_OHNE_VORLAGE:
            felder["template"] = self._hero_text_lesen()
            felder["bold"] = bool(self.hero_fett.isChecked())
            if k != "description":
                felder["uppercase"] = bool(self.hero_gross.isChecked())
        if k == "tags":
            for feld, c in self.hero_tags.items():
                felder[feld] = bool(c.isChecked())
            try:
                n = zahl_oder_leer(self.hero_zeilen.text())
            except ValueError:
                return
            felder["max_rows"] = None if n is None else max(1, min(5, int(n)))
        neu = kpl.hero_aendern(self._hero_werte(), k, **felder)
        self._hero_setzen(neu)

    def _hero_setzen(self, neu):
        """hero_regions als Ganzes in den Entwurf (ohne das Formular neu zu füllen, damit das Textfeld beim
        Tippen den Cursor behält)."""
        im_profil = (self.datei_werte or {}).get("hero_regions")
        if gleich(neu, im_profil):
            self.aenderungen.pop("hero_regions", None)
        else:
            self.aenderungen["hero_regions"] = neu
        self._hero_wahl_fuellen()
        self.stand_zeigen()
        self._planen(PAUSE_BOOKSHELF, self.ins_bild)

    def _hero_zuruecksetzen(self):
        if self.datei_werte is None:
            return
        neu = kpl.hero_zuruecksetzen(self._hero_werte(), self.hero_kennung)
        im_profil = (self.datei_werte or {}).get("hero_regions")
        if gleich(neu, im_profil):
            self.aenderungen.pop("hero_regions", None)
        else:
            self.aenderungen["hero_regions"] = neu
        self._formular_fuellen()
        self._planen(PAUSE_BOOKSHELF, self.ins_bild)

    def _hero_modus_geaendert(self):
        if self._laden or self.datei_werte is None:
            return
        self._setzen("hero_area_mode", self.hero_modus.wert(), "currently_reading")

    # ------------------------------------------------------------------ Listen: Module, Startmenü, Regale
    def _knoepfe(self, lay, knoepfe, spalten=3):
        g = QGridLayout()
        erg = {}
        for n, (text, fn) in enumerate(knoepfe):
            if fn is None:
                w = _menueknopf(text)
                w.setSizePolicy(QPushButton().sizePolicy())
            else:
                w = QPushButton(text)
                w.clicked.connect(lambda *a, fn=fn: fn())
            g.addWidget(w, n // spalten, n % spalten)
            erg[text] = w
        lay.addLayout(g)
        return erg

    def _liste_setzen(self, schl, neu, zaehler=None, waehlen=None):
        if zaehler is not None:
            self.aenderungen[zaehler[0]] = zaehler[1]
        for name in ("module", "menue", "regale"):
            if waehlen:
                self.auswahl[name] = waehlen
        self._setzen(schl, neu, neu_bauen=schl == "tabs")

    # -- Module im oberen Bereich
    def _module_bauen(self, i):
        lay = QVBoxLayout(i)
        lay.setContentsMargins(0, 0, 0, 0)
        self.mod_hinweis = hinweis("", BREITE)
        lay.addWidget(self.mod_hinweis)
        self.mod_baum = _baum(2, 6)
        self.mod_baum.currentItemChanged.connect(lambda *a: (self._merken("module", self.mod_baum),
                                                             self._mod_position_zeigen()))
        lay.addWidget(self.mod_baum)
        k = self._knoepfe(lay, ((_("Add"), None), (_("Up"), lambda: self._mod_schieben(-1)),
                                (_("Down"), lambda: self._mod_schieben(1)), (_("Remove"), self._mod_entfernen)))
        self.mod_neu = k[_("Add")]
        self.mod_auto = QCheckBox(_("Place automatically"))
        self.mod_auto.toggled.connect(lambda *a: self._mod_position_uebernehmen())
        lay.addWidget(self.mod_auto)
        g = QGridLayout()
        self.mod_pos = {}
        for n, (feld, text) in enumerate(zip(kpl.POSITION, (_("Page"), _("Column"), _("Row"), _("Width"),
                                                             _("Height")))):
            g.addWidget(QLabel(text), n // 3, (n % 3) * 2)
            sp = self.mod_pos[feld] = QSpinBox()
            sp.setRange(1, 12)
            sp.valueChanged.connect(lambda *a: self._mod_position_uebernehmen())
            g.addWidget(sp, n // 3, (n % 3) * 2 + 1)
        g.setColumnStretch(6, 1)
        lay.addLayout(g)
        lay.addWidget(hinweis(_("Positions in grid cells. The top panel has 1 or 2 rows and 2 to 8 columns, depending "
                                "on the screen; Bookshelf moves a module that does not fit or overlaps another. Modules "
                                "that need a choice (action, shelf, ornament) are added in Bookshelf."), BREITE))

    def _modulnamen(self):
        if not hasattr(self, "_mod_namen") and self.info:
            self._mod_namen = kpl.micromodule(self.info["ordner"])
        return getattr(self, "_mod_namen", [])

    def _mod_liste(self):
        w = self._wert(kpl.MODULE_SCHLUESSEL[0])
        return w if isinstance(w, list) else None

    def _mod_fuellen(self):
        liste = self._mod_liste()
        b = self.mod_baum
        b.clear()
        titel = {m["key"]: _(m["titel"]) for m in self._modulnamen()}
        for e in liste or []:
            if not isinstance(e, dict) or not e.get("id"):
                continue
            at = e.get("at")
            pos = (_("page {seite}: {spalte}/{reihe}, {w}×{h}").format(
                seite=at.get("page"), spalte=at.get("col"), reihe=at.get("row"), w=at.get("w"), h=at.get("h"))
                   if isinstance(at, dict) else _("automatic"))
            it = QTreeWidgetItem([titel.get(e.get("module"), e.get("module", "?")), pos])
            it.setData(0, Qt.UserRole, e["id"])
            b.addTopLevelItem(it)
        _waehlen(b, self.auswahl.get("module"))
        da = liste is not None
        self.mod_hinweis.setText("" if da else _("Bookshelf has not set up the modules yet: open the top panel's "
                                                 "modules once on the e-reader."))
        self.mod_neu.setEnabled(da)
        m = self.mod_neu.menu()
        m.clear()
        for mod in self._modulnamen():
            if mod["key"] in kpl.MODULE_MIT_EINRICHTUNG:
                continue
            m.addAction(f"{_(mod['titel'])}  –  {_(mod['text'])}" if mod["text"] else _(mod["titel"]),
                        lambda k=mod["key"]: self._mod_hinzufuegen(k))
        self._mod_position_zeigen()

    def _mod_position_zeigen(self):
        alt, self._laden = self._laden, True
        try:
            l, n = kpl.eintrag_suchen(self._mod_liste() or [], _gewaehlt_id(self.mod_baum))
            e = l[n] if l is not None else None
            at = e.get("at") if e else None
            self.mod_auto.setChecked(e is not None and not isinstance(at, dict))
            self.mod_auto.setEnabled(e is not None)
            for feld, sp in self.mod_pos.items():
                sp.setValue(int(at.get(feld, 1)) if isinstance(at, dict) else 1)
                sp.setEnabled(isinstance(at, dict))
        finally:
            self._laden = alt

    def _mod_position_uebernehmen(self):
        if self._laden:
            return
        kennung = _gewaehlt_id(self.mod_baum)
        liste = self._mod_liste()
        if not kennung or liste is None:
            return
        if self.mod_auto.isChecked():
            neu = kpl.aendern(liste, kennung, at=None)
        else:
            neu = kpl.aendern(liste, kennung, at={feld: max(1, min(12, sp.value())) for feld, sp in self.mod_pos.items()})
        self._liste_setzen(kpl.MODULE_SCHLUESSEL[0], neu, waehlen=kennung)

    def _mod_hinzufuegen(self, modul):
        liste = self._mod_liste()
        if liste is None:
            return
        werte = dict(self.datei_werte or {})
        werte.update({k: v for k, v in self.aenderungen.items() if v is not None})
        kennung, zaehler = kpl.neue_id(werte, kpl.MODULE_SCHLUESSEL[1], kpl.MODULE_SCHLUESSEL[2])
        neu = copy.deepcopy(liste) + [{"id": kennung, "type": "module", "module": modul}]
        self._liste_setzen(kpl.MODULE_SCHLUESSEL[0], neu, (kpl.MODULE_SCHLUESSEL[1], zaehler), waehlen=kennung)

    def _mod_schieben(self, schritt):
        kennung, liste = _gewaehlt_id(self.mod_baum), self._mod_liste()
        if kennung and liste is not None:
            self._liste_setzen(kpl.MODULE_SCHLUESSEL[0], kpl.verschieben(liste, kennung, schritt), waehlen=kennung)

    def _mod_entfernen(self):
        kennung, liste = _gewaehlt_id(self.mod_baum), self._mod_liste()
        if kennung and liste is not None:
            self._liste_setzen(kpl.MODULE_SCHLUESSEL[0], kpl.entfernen(liste, kennung))

    # -- Startmenü
    def _menue_bauen(self, i):
        lay = QVBoxLayout(i)
        lay.setContentsMargins(0, 0, 0, 0)
        self.menue_hinweis = hinweis("", BREITE)
        lay.addWidget(self.menue_hinweis)
        self.menue_baum = _baum(1, 9)
        self.menue_baum.setRootIsDecorated(True)
        self.menue_baum.itemDoubleClicked.connect(lambda *a: self._menue_umbenennen())
        self.menue_baum.currentItemChanged.connect(lambda *a: self._merken("menue", self.menue_baum))
        lay.addWidget(self.menue_baum)
        k = self._knoepfe(lay, ((_("Add"), None), (_("Up"), lambda: self._menue_schieben(-1)),
                                (_("Down"), lambda: self._menue_schieben(1)), (_("Folder"), None),
                                (_("Rename …"), self._menue_umbenennen), (_("Remove"), self._menue_entfernen)))
        self.menue_neu, self.menue_ordner = k[_("Add")], k[_("Folder")]
        lay.addWidget(hinweis(_("A folder holds entries, one level deep as in Bookshelf. New entries are Bookshelf's "
                                "standard ones; other actions and icons are set in Bookshelf's start menu editor."),
                              BREITE))

    def _menue_liste(self):
        w = self._wert(kpl.STARTMENUE_SCHLUESSEL[0])
        return w if isinstance(w, list) else None

    def _menue_text(self, e, titel):
        art = e.get("type")
        if art == "divider":
            return "──────────"
        if art == "module":
            return "▣ " + titel.get(e.get("module"), e.get("module", "?"))
        return str(e.get("label") or "?")

    def _menue_fuellen(self):
        liste = self._menue_liste()
        b = self.menue_baum
        b.clear()
        titel = {m["key"]: _(m["titel"]) for m in self._modulnamen()}
        ordner = []
        for e in liste or []:
            if not isinstance(e, dict) or not e.get("id"):
                continue
            it = QTreeWidgetItem([self._menue_text(e, titel)])
            it.setData(0, Qt.UserRole, e["id"])
            b.addTopLevelItem(it)
            if e.get("type") == "folder":
                ordner.append(e)
                for c in e.get("children") or []:
                    if isinstance(c, dict) and c.get("id"):
                        ci = QTreeWidgetItem([self._menue_text(c, titel)])
                        ci.setData(0, Qt.UserRole, c["id"])
                        it.addChild(ci)
                it.setExpanded(True)
        _waehlen(b, self.auswahl.get("menue"))
        da = liste is not None
        self.menue_hinweis.setText("" if da else _("Bookshelf has not set up its start menu yet: open it once on the "
                                                   "e-reader."))
        for knopf in (self.menue_neu, self.menue_ordner):
            knopf.setEnabled(da)
        m = self.menue_neu.menu()
        m.clear()
        m.addAction(_("Folder …"), self._menue_neuer_ordner)
        m.addAction(_("Divider"), lambda: self._menue_neu({"type": "divider"}))
        mm = m.addMenu(_("Module"))
        for mod in self._modulnamen():
            if mod["nur_oben"]:
                continue
            mm.addAction(_(mod["titel"]), lambda k=mod["key"]: self._menue_neu({"type": "module", "module": k}))
        sm = m.addMenu(_("Standard entry"))
        for vorlage in STARTMENUE_STANDARD:
            sm.addAction(_(vorlage["label"]), lambda v=vorlage: self._menue_neu({**copy.deepcopy(v),
                                                                                "label": _(v["label"])}))
        om = self.menue_ordner.menu()
        om.clear()
        for o in ordner:
            om.addAction(_("Into \"{name}\"").format(name=o.get("label", "?")),
                         lambda k=o["id"]: self._menue_in_ordner(k))
        om.addAction(_("Out of the folder"), lambda: self._menue_in_ordner(None))

    def _menue_neu(self, eintrag):
        liste = self._menue_liste()
        if liste is None:
            return
        werte = dict(self.datei_werte or {})
        werte.update({k: v for k, v in self.aenderungen.items() if v is not None})
        kennung, zaehler = kpl.neue_id(werte, kpl.STARTMENUE_SCHLUESSEL[1], kpl.STARTMENUE_SCHLUESSEL[2])
        neu = copy.deepcopy(liste)
        e = {"id": kennung, **eintrag}
        sel = _gewaehlt_id(self.menue_baum)
        l, n = kpl.eintrag_suchen(neu, sel) if sel else (None, None)
        if l is not None and (l is neu or e["type"] not in ("folder", "divider")):
            l.insert(n + 1, e)                    # hinter dem gewählten Eintrag, in seiner Ebene
        else:
            neu.append(e)
        self._liste_setzen(kpl.STARTMENUE_SCHLUESSEL[0], neu, (kpl.STARTMENUE_SCHLUESSEL[1], zaehler), waehlen=kennung)

    def _menue_neuer_ordner(self):
        name = dialogs.eingabe(self.app, _("Start menu"), _("Name of the folder:"))
        if name and name.strip():
            self._menue_neu({"type": "folder", "label": name.strip(), "children": []})

    def _menue_umbenennen(self):
        kennung, liste = _gewaehlt_id(self.menue_baum), self._menue_liste()
        if not kennung or liste is None:
            return
        l, n = kpl.eintrag_suchen(liste, kennung)
        if l is None or l[n].get("type") not in ("action", "folder"):
            self.app.status.set(_("Only entries and folders have a name."))
            return
        name = dialogs.eingabe(self.app, _("Start menu"), _("New name:"), l[n].get("label", ""))
        if name and name.strip():
            self._liste_setzen(kpl.STARTMENUE_SCHLUESSEL[0], kpl.aendern(liste, kennung, label=name.strip()),
                               waehlen=kennung)

    def _menue_schieben(self, schritt):
        kennung, liste = _gewaehlt_id(self.menue_baum), self._menue_liste()
        if kennung and liste is not None:
            self._liste_setzen(kpl.STARTMENUE_SCHLUESSEL[0], kpl.verschieben(liste, kennung, schritt), waehlen=kennung)

    def _menue_in_ordner(self, ordner):
        kennung, liste = _gewaehlt_id(self.menue_baum), self._menue_liste()
        if kennung and liste is not None:
            neu = kpl.in_ordner(liste, kennung, ordner)
            if neu == liste:
                self.app.status.set(_("Folders and dividers stay at the top level."))
                return
            self._liste_setzen(kpl.STARTMENUE_SCHLUESSEL[0], neu, waehlen=kennung)

    def _menue_entfernen(self):
        kennung, liste = _gewaehlt_id(self.menue_baum), self._menue_liste()
        if not kennung or liste is None:
            return
        l, n = kpl.eintrag_suchen(liste, kennung)
        if l is not None and l[n].get("type") == "folder" and l[n].get("children") and not dialogs.frage(
                self.app, _("Start menu"), _("Remove the folder with its {n} entries?").format(n=len(l[n]["children"]))):
            return
        self._liste_setzen(kpl.STARTMENUE_SCHLUESSEL[0], kpl.entfernen(liste, kennung))

    # -- Regale
    def _regale_bauen(self, i):
        lay = QVBoxLayout(i)
        lay.setContentsMargins(0, 0, 0, 0)
        self.regal_hinweis = hinweis("", BREITE)
        lay.addWidget(self.regal_hinweis)
        self.regal_baum = _baum(2, 8)
        self.regal_baum.itemDoubleClicked.connect(lambda *a: self._regal_umschalten())
        self.regal_baum.currentItemChanged.connect(lambda *a: (self._merken("regale", self.regal_baum),
                                                               self._regal_ansicht_zeigen()))
        lay.addWidget(self.regal_baum)
        k = self._knoepfe(lay, ((_("On/off"), self._regal_umschalten), (_("Up"), lambda: self._regal_schieben(-1)),
                                (_("Down"), lambda: self._regal_schieben(1)), (_("Rename …"), self._regal_umbenennen),
                                (_("Add"), None), (_("Remove"), self._regal_entfernen)))
        self.regal_neu = k[_("Add")]
        self.regal_knoepfe = list(k.values())
        self.regal_ansicht = Wahl(kpl.ANSICHTEN, self._regal_ansicht_uebernehmen)
        lay.addWidget(zeile(_("Shown as"), self.regal_ansicht))
        lay.addWidget(hinweis(_("☑ shown as a button above the shelf, ☐ hidden. Sorting, filters and new shelves from "
                                "collections or folders are set in Bookshelf; removed standard shelves can be added "
                                "again here."), BREITE))

    def _regal_liste(self):
        w = self._wert("tabs")
        return w if isinstance(w, list) else None

    def _regale_fuellen(self):
        liste = self._regal_liste()
        b = self.regal_baum
        b.clear()
        ansichten = dict(kpl.ANSICHTEN)
        for e in liste or []:
            if not isinstance(e, dict) or not e.get("id"):
                continue
            text = ("☐ " if e.get("enabled") is False else "☑ ") + str(e.get("label") or e["id"])
            it = QTreeWidgetItem([text, _(ansichten.get(e.get("view_mode"), ansichten[None]))])
            it.setData(0, Qt.UserRole, e["id"])
            b.addTopLevelItem(it)
        _waehlen(b, self.auswahl.get("regale"))
        da = liste is not None
        self.regal_hinweis.setText("" if da else _("Bookshelf still uses its standard shelves; change them once on the "
                                                   "e-reader, then they can be edited here."))
        for knopf in self.regal_knoepfe:
            knopf.setEnabled(da)
        m = self.regal_neu.menu()
        m.clear()
        vorhanden = {e.get("id") for e in liste or [] if isinstance(e, dict)}
        fehlend = [r for r in kpl.REGALE_EINGEBAUT if r["id"] not in vorhanden]
        for r in fehlend:
            m.addAction(_(r["label"]), lambda r=r: self._regal_hinzufuegen(r))
        if not fehlend:
            m.addAction(_("All standard shelves are there.")).setEnabled(False)
        self._regal_ansicht_zeigen()

    def _regal_ansicht_zeigen(self):
        alt, self._laden = self._laden, True
        try:
            l, n = kpl.eintrag_suchen(self._regal_liste() or [], _gewaehlt_id(self.regal_baum))
            self.regal_ansicht.setzen(l[n].get("view_mode") if l is not None else None, aktiv=l is not None)
        finally:
            self._laden = alt

    def _regal_ansicht_uebernehmen(self):
        kennung, liste = _gewaehlt_id(self.regal_baum), self._regal_liste()
        if self._laden or not kennung or liste is None:
            return
        self._liste_setzen("tabs", kpl.aendern(liste, kennung, view_mode=self.regal_ansicht.wert()), waehlen=kennung)

    def _regal_umschalten(self):
        kennung, liste = _gewaehlt_id(self.regal_baum), self._regal_liste()
        if not kennung or liste is None:
            return
        l, n = kpl.eintrag_suchen(liste, kennung)
        an = l[n].get("enabled") is not False
        if an and sum(1 for e in liste if isinstance(e, dict) and e.get("enabled") is not False) <= 1:
            self.app.status.set(_("At least one shelf stays shown."))
            return
        self._liste_setzen("tabs", kpl.aendern(liste, kennung, enabled=not an), waehlen=kennung)

    def _regal_schieben(self, schritt):
        kennung, liste = _gewaehlt_id(self.regal_baum), self._regal_liste()
        if kennung and liste is not None:
            self._liste_setzen("tabs", kpl.verschieben(liste, kennung, schritt), waehlen=kennung)

    def _regal_umbenennen(self):
        kennung, liste = _gewaehlt_id(self.regal_baum), self._regal_liste()
        if not kennung or liste is None:
            return
        l, n = kpl.eintrag_suchen(liste, kennung)
        name = dialogs.eingabe(self.app, _("Shelves"), _("New name:"), l[n].get("label", ""))
        if name and name.strip():
            self._liste_setzen("tabs", kpl.aendern(liste, kennung, label=name.strip()), waehlen=kennung)

    def _regal_hinzufuegen(self, vorlage):
        liste = self._regal_liste()
        if liste is None:
            return
        neu = copy.deepcopy(liste) + [{**copy.deepcopy(vorlage), "label": _(vorlage["label"]), "enabled": True}]
        self._liste_setzen("tabs", neu, waehlen=vorlage["id"])

    def _regal_entfernen(self):
        kennung, liste = _gewaehlt_id(self.regal_baum), self._regal_liste()
        if not kennung or liste is None:
            return
        if len([e for e in liste if isinstance(e, dict)]) <= 1:
            self.app.status.set(_("At least one shelf stays shown."))
            return
        if not dialogs.frage(self.app, _("Shelves"), _("Remove the shelf? Standard shelves can be added again; your own "
                                                       "(collections, folders) only in Bookshelf.")):
            return
        self._liste_setzen("tabs", kpl.entfernen(liste, kennung))

    # ------------------------------------------------------------------ Theme und Dekoration
    def _wahl(self, g, r, name, text, optionen, holen, setzen):
        """Auswahlliste mit Werten: optionen [(wert, text)] (Text schon übersetzt), holen() = aktueller Wert."""
        g.addWidget(QLabel(text), r, 0)
        cb = QComboBox()
        cb.addItems([t for __, t in optionen])
        cb.activated.connect(lambda i, n=name: self._wahl_gewaehlt(n, i))
        g.addWidget(cb, r, 1)
        self.wahlen[name] = (cb, optionen, holen, setzen)

    def _wahl_gewaehlt(self, name, i):
        if self._laden:
            return
        cb, optionen, __, setzen = self.wahlen[name]
        if 0 <= i < len(optionen):
            setzen(optionen[i][0])

    def _wahlen_fuellen(self):
        for cb, optionen, holen, __ in self.wahlen.values():
            w = holen()
            i = next((n for n, (x, __) in enumerate(optionen) if gleich(x, w)), None)
            if i is None:
                if cb.count() == len(optionen):
                    cb.addItem(f"{w}" if w is not None else optionen[0][1])
                cb.setCurrentIndex(cb.count() - 1 if w is not None else 0)
            else:
                while cb.count() > len(optionen):
                    cb.removeItem(cb.count() - 1)
                cb.setCurrentIndex(i)

    def _regale(self):
        tabs = self._wert("tabs")
        return tabs if isinstance(tabs, list) else []

    def _regal_setzen(self, nr, feld, wert):
        tabs = copy.deepcopy(self._regale())
        if not (0 <= nr < len(tabs)) or not isinstance(tabs[nr], dict):
            return
        if wert is None:
            tabs[nr].pop(feld, None)
        else:
            tabs[nr][feld] = wert
        self._setzen("tabs", tabs)

    def _dynamisch_bauen(self):
        """Abschnitte, deren Inhalt vom Profil abhängt (Theme-Pakete, Bilder, Regale, Ornamente)."""
        if not self.gebaut():
            return
        for name in [n for n in self.wahlen if n.startswith(("theme", "regal", "bild", "brett", "deko"))]:
            del self.wahlen[name]
        ko = self.ko
        themes = kpl.themes(ko)
        regale = self._regale()

        g = self.g_theme
        _leeren(g)
        standard = [(kpl.THEME_EIGEN, _("Custom theme")), (kpl.THEME_SCHLICHT, _("Plain"))] + themes
        self._wahl(g, 0, "theme", _("Default theme"), standard, lambda: self._wert("library_theme"),
                   lambda w: self._setzen("library_theme", w))
        self._wahl(g, 1, "theme_hell", _("Light or dark"), [(k, _(t)) for k, t in kpl.HELLDUNKEL],
                   lambda: self._wert("shelf_theme", "auto"), lambda w: self._setzen("shelf_theme", w, "auto"))
        r = 2
        if regale:
            lab = QLabel(_("Theme per shelf"))
            lab.setProperty("rolle", "abschnitt")
            g.addWidget(lab, r, 0, 1, 2)
            r += 1
            je = [(None, _("Like the default")), ("mine", _("Custom theme")), (kpl.THEME_SCHLICHT, _("Plain"))] + themes
            for n, tab in enumerate(regale):
                self._wahl(g, r, f"regal_theme_{n}", kpl.regal_name(tab), je,
                           lambda n=n: (self._regale()[n] or {}).get("theme"),
                           lambda w, n=n: self._regal_setzen(n, "theme", w))
                r += 1
        g.addWidget(hinweis(_("Theme packs are folders in settings/bookshelf/ornaments with a theme/theme.json; new ones "
                              "come from Bookshelf's theme library. Wallpaper, plank and colours below belong to the "
                              "custom theme; a theme pack lays its own parts over it.") +
                            ("" if themes else " " + _("No theme pack in the profile.")), BREITE), r, 0, 1, 2)

        g = self.g_hintergrund
        _leeren(g)
        bilder = [(b, b) for b in kpl.hintergrundbilder(ko)]
        self._wahl(g, 0, "bild", _("Picture"), [(None, _("None"))] + bilder,
                   lambda: self._wert("wallpaper_default"), lambda w: self._setzen("wallpaper_default", w))
        self._wahl(g, 1, "bild_voll", _("Full screen shelves"), [(None, _("Same as above"))] + bilder,
                   lambda: self._wert("wallpaper_full"), lambda w: self._setzen("wallpaper_full", w))
        self._wahl(g, 2, "bild_abdunkeln", _("Panel shading"), [(k, _(t)) for k, t in kpl.ABDUNKELN],
                   lambda: self._wert("wallpaper_chrome_scrim", 0.85),
                   lambda w: self._setzen("wallpaper_chrome_scrim", w, 0.85))
        for r, (schl, text) in enumerate((("wallpaper_transparent_buttons", _("Transparent buttons")),
                                          ("wallpaper_panel_blur", _("Blur the picture under panels")),
                                          ("wallpaper_invert_night", _("Invert the picture in night mode")),
                                          ("covers_full_panel", _("One panel over the whole covers shelf"))), 3):
            c = QCheckBox(text)
            c.toggled.connect(lambda an, s=schl: None if self._laden else self._setzen(s, bool(an), False))
            g.addWidget(c, r, 0, 1, 2)
            self.felder[schl] = c
        k = QPushButton(_("Add picture …"))
        k.clicked.connect(self.bild_hinzufuegen)
        g.addWidget(k, 7, 0, Qt.AlignLeft)
        g.addWidget(hinweis(_("Pictures are in settings/bookshelf/wallpapers of the profile. \"Add picture\" copies one "
                              "there at once (it still has to get to the e-reader)."), BREITE), 8, 0, 1, 2)

        g = self.g_brett
        _leeren(g)
        self._wahl(g, 0, "brett", _("Plank"), [(None, _("Default (oak, unless you chose a plank colour)")),
                                               ("oak", _("Oak")), (False, _("Colour only"))] + kpl.bretter(ko),
                   lambda: self._wert("theme_plank_pack"), lambda w: self._setzen("theme_plank_pack", w))
        g.addWidget(hinweis(_("The plank colour is under Colours (Plank)."), BREITE), 1, 0, 1, 2)

        g = self.g_deko
        _leeren(g)
        r = 0
        if regale:
            lab = QLabel(_("How often per shelf"))
            lab.setProperty("rolle", "abschnitt")
            g.addWidget(lab, r, 0, 1, 2)
            r += 1
            stufen = [(k, _(t)) for k, t in kpl.HAEUFIGKEIT]
            for n, tab in enumerate(regale):
                self._wahl(g, r, f"deko_{n}", kpl.regal_name(tab), stufen,
                           lambda n=n: (self._regale()[n] or {}).get("ornament_frequency", kpl.HAEUFIGKEIT_VORGABE),
                           lambda w, n=n: self._regal_setzen(n, "ornament_frequency", w))
                r += 1
        lab = QLabel(_("Ornaments (double-click switches on/off)"))
        lab.setProperty("rolle", "abschnitt")
        g.addWidget(lab, r, 0, 1, 2)
        self.deko_baum = _baum(1, 8)
        self.deko_baum.setRootIsDecorated(True)
        self.deko_baum.itemDoubleClicked.connect(lambda *a: self.deko_umschalten())
        self.deko_baum.currentItemChanged.connect(lambda *a: self._merken("deko", self.deko_baum))
        g.addWidget(self.deko_baum, r + 1, 0, 1, 2)
        self._deko = kpl.dekoration(ko)
        g.addWidget(hinweis(_("Ornaments stand in the gaps of spine shelves only. Their files are in "
                              "settings/bookshelf/ornaments (one level of packs).") +
                            ("" if self._deko else " " + _("No ornaments in the profile.")), BREITE), r + 2, 0, 1, 2)

    def _farben_bauen(self, g):
        g.setColumnStretch(1, 0)
        g.setColumnStretch(4, 1)
        g.addWidget(QLabel(_("Day")), 0, 1)
        g.addWidget(QLabel(_("Night")), 0, 2)
        for r, (schl, text) in enumerate(kpl.FARBEN, 1):
            g.addWidget(QLabel(_(text)), r, 0)
            for sp, k in ((1, schl), (2, schl + "_night")):
                feld = QPushButton("")
                feld.setFixedSize(54, 22)
                feld.clicked.connect(lambda *a, k=k: self.farbe_waehlen(k))
                g.addWidget(feld, r, sp)
                self.farb_felder[k] = feld
            x = QToolButton()
            x.setText("✕")
            x.clicked.connect(lambda *a, s=schl: self._farbe_zuruecksetzen(s))
            g.addWidget(x, r, 3)
        g.addWidget(hinweis(_("Click a field to choose a colour; \"-\" = the default. ✕ resets day and night. Colours "
                              "belong to the custom theme."), BREITE), len(kpl.FARBEN) + 1, 0, 1, 5)

    def _farbe_zuruecksetzen(self, schl):
        self.aenderungen_setzen({schl: None, schl + "_night": None})

    def aenderungen_setzen(self, werte):
        for schl, w in werte.items():
            im_profil = (self.datei_werte or {}).get(schl)
            if gleich(w, im_profil) or (w is None and im_profil is None):
                self.aenderungen.pop(schl, None)
            else:
                self.aenderungen[schl] = w
        self._formular_fuellen()
        self._planen(PAUSE_BOOKSHELF, self.ins_bild)

    def _deko_fuellen(self):
        b = self.deko_baum
        offen = {it.data(0, Qt.UserRole) for it in _alle_items(b) if it.isExpanded()}
        b.clear()
        aus = self._wert("ornaments_off") or {}
        pakete_aus = self._wert("ornament_packs_off") or {}

        def zeichen(an):
            return "☑ " if an else "☐ "
        for paket, teile in sorted(self._deko.items()):
            eltern = None
            if paket:
                an = not pakete_aus.get(paket) if isinstance(pakete_aus, dict) else True
                eltern = QTreeWidgetItem([zeichen(an) + paket])
                eltern.setData(0, Qt.UserRole, "paket:" + paket)
                b.addTopLevelItem(eltern)
                eltern.setExpanded(("paket:" + paket) in offen)
            for rel in teile:
                an = not aus.get(rel) if isinstance(aus, dict) else True
                it = QTreeWidgetItem([zeichen(an) + rel.split("/")[-1]])
                it.setData(0, Qt.UserRole, "teil:" + rel)
                if eltern is not None:
                    eltern.addChild(it)
                else:
                    b.addTopLevelItem(it)
        _waehlen(b, self.auswahl.get("deko"))

    def deko_umschalten(self):
        sel = _gewaehlt_id(self.deko_baum)
        if not sel:
            return
        art, name = sel.split(":", 1)
        schl = "ornament_packs_off" if art == "paket" else "ornaments_off"
        menge = dict(self._wert(schl) or {})
        if menge.get(name):
            menge.pop(name)
        else:
            menge[name] = True
        self.auswahl["deko"] = sel
        self._setzen(schl, menge or None)

    def _farben_fuellen(self):
        for k, feld in self.farb_felder.items():
            h = kpl.farbe_hex(self._wert(k))
            if h:
                feld.setText("")
                feld.setStyleSheet(f"QPushButton {{ background: {h}; border: 1px solid #888; }}")
            else:
                feld.setText("-")
                feld.setStyleSheet("")

    def farbe_waehlen(self, schl):
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog
        alt = kpl.farbe_hex(self._wert(schl))
        erg = QColorDialog.getColor(QColor(alt or "#808080"), self.app, _("Colour"))
        if erg.isValid():
            self._setzen(schl, kpl.farbe_wert(erg.name()))

    def bild_hinzufuegen(self):
        import shutil
        from pathlib import Path
        p = dialogs.datei_oeffnen(self.app, _("Wallpaper for Bookshelf"), "",
                                  [(_("Pictures"), " ".join("*" + e for e in sorted(kpl.BILD_ENDUNGEN))),
                                   (_("All files"), "*")])
        if not p:
            return
        ziel = self.ko / "settings" / "bookshelf" / "wallpapers"
        ziel.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(p, ziel / Path(p).name)
        except OSError as e:
            self.app.status.set(str(e))
            return
        kpl._profil_geaendert(self.bereich.profil, "bookshelf")
        self._dynamisch_bauen()
        self._setzen("wallpaper_default", Path(p).name)

    def zuruecksetzen(self):
        self.datei_werte, self.aenderungen = None, {}

    # ------------------------------------------------------------------ Werte
    def _wert(self, schl, vorgabe=None):
        if schl in self.aenderungen:
            w = self.aenderungen[schl]
            return vorgabe if w is None else w
        return (self.datei_werte or {}).get(schl, vorgabe)

    def _kopf_zeigen(self):
        if self.gebaut() and self.info:
            self.kopf.setText(_("Bookshelf {version} in the profile ({datei}).").format(
                version=self.info["version"] or "?", datei=kpl.bookshelf_datei(self.ko).relative_to(self.ko)))

    def neu_laden(self):
        self.info = kpl.erkennen(self.bereich.profil).get(kpl.BOOKSHELF)
        if not self.info:
            return
        self._kopf_zeigen()
        self.datei_werte = kpl.bookshelf_lesen(self.ko)
        self.aenderungen = {}
        self._dynamisch_bauen()
        self._formular_fuellen()

    def _formular_fuellen(self):
        if not self.gebaut():
            return
        self._laden = True
        try:
            for schl, __, __, art, vorgabe, wahl in kpl.BOOKSHELF_WERTE:
                w = self._wert(schl, vorgabe)
                f = self.felder[schl]
                if art == "an":
                    f.setChecked(bool(w))
                elif art == "zahl":
                    f.setText("" if w is None else str(w))
                else:
                    werte = [k for k, __ in wahl]
                    f.setCurrentIndex(werte.index(w) if w in werte else werte.index(vorgabe))
            for schl in ("wallpaper_transparent_buttons", "wallpaper_panel_blur", "wallpaper_invert_night",
                         "covers_full_panel"):
                if schl in self.felder:
                    self.felder[schl].setChecked(bool(self._wert(schl, False)))
            self._wahlen_fuellen()
            self._hero_fuellen()
            self._mod_fuellen()
            self._menue_fuellen()
            self._regale_fuellen()
            if hasattr(self, "deko_baum"):
                self._deko_fuellen()
            self._farben_fuellen()
            self.baum.clear()
            alle = dict(self.datei_werte or {})
            alle.update(dict(self.aenderungen))
            for k in sorted(alle):
                if k in kpl.BOOKSHELF_INTERN or alle[k] is None:
                    continue
                it = QTreeWidgetItem([("● " if k in self.aenderungen else "") + k, kpl.wert_text(alle[k])])
                it.setData(0, Qt.UserRole, k)
                self.baum.addTopLevelItem(it)
            _waehlen(self.baum, self.auswahl.get("alle"))
        finally:
            self._laden = False
        self.stand_zeigen()

    def _wert_geaendert(self, schl):
        if self._laden or self.datei_werte is None:
            return
        __, __, __, art, vorgabe, wahl = next(x for x in kpl.BOOKSHELF_WERTE if x[0] == schl)
        f = self.felder[schl]
        if art == "an":
            w = bool(f.isChecked())
        elif art == "zahl":
            try:
                w = zahl_oder_leer(f.text())
            except ValueError:
                return
        else:
            i = f.currentIndex()
            w = wahl[i][0] if 0 <= i < len(wahl) else vorgabe
        self._setzen(schl, w, vorgabe, fuellen=art != "zahl")

    def _setzen(self, schl, w, vorgabe=None, neu_bauen=False, fuellen=True):
        im_profil = (self.datei_werte or {}).get(schl)
        if gleich(w, im_profil) or (w is not None and gleich(w, vorgabe) and im_profil is None):
            self.aenderungen.pop(schl, None)
        else:
            self.aenderungen[schl] = w
        if neu_bauen:
            self._dynamisch_bauen()
        if fuellen:
            self._formular_fuellen()
        else:
            self.stand_zeigen()
        self._planen(PAUSE_BOOKSHELF, self.ins_bild)

    def schluessel_waehlen(self, schl):
        self.auswahl["alle"] = schl
        _waehlen(self.baum, schl)

    def schluessel_bearbeiten(self):
        schl = _gewaehlt_id(self.baum)
        if not schl:
            return
        alt = self._wert(schl)
        if isinstance(alt, (dict, list)) or alt is None:
            self.app.status.set(_("{schluessel} is a table: change it in Bookshelf itself.").format(schluessel=schl))
            return
        text = dialogs.eingabe(self.app, "Bookshelf", _("New value for {schluessel}:").format(schluessel=schl),
                               kpl.wert_text(alt) if not isinstance(alt, bool) else ("true" if alt else "false"))
        if text is None:
            return
        try:
            w = kpl.wert_aus_text(text, alt)
        except ValueError:
            self.app.status.set(_("\"{text}\" does not fit the value ({art}).").format(text=text, art=type(alt).__name__))
            return
        self._setzen(schl, w)

    def schluessel_loeschen(self):
        schl = _gewaehlt_id(self.baum)
        if schl:
            self._setzen(schl, None)

    def ungespeichert(self):
        return bool(self.aenderungen)

    def reiter_geaendert(self):
        erg = set()
        for schl in self.aenderungen:
            erg |= kpl.bookshelf_reiter(schl)
        return erg

    # ------------------------------------------------------------------ Werkbank
    def in_kopie(self, ko):
        if self.aenderungen:
            kpl.bookshelf_schreiben(ko, self.aenderungen)

    def ins_bild(self):
        """Bookshelf kann nicht neu laden: Werkbank neu starten (Startbildschirm), in_kopie() bringt den Entwurf mit."""
        if self.bereich.unterseite() != self.plugin:
            return
        if self.bereich.modus() != "bibliothek":
            self.bereich.modus_setzen("bibliothek")
        else:
            self.bereich.werkbank_starten(still=True)

    def beim_zeigen(self):
        if self.datei_werte is None:
            self.neu_laden()
        if self.bereich.modus() != "bibliothek":
            self.bereich.modus_setzen("bibliothek")

    def speichern(self):
        if not self.aenderungen:
            return False
        kpl.bookshelf_schreiben(self.ko, self.aenderungen)
        kpl._profil_geaendert(self.bereich.profil, "bookshelf")
        self.app.status.set(_("Bookshelf settings saved in the profile ({n} changed).").format(n=len(self.aenderungen)))
        self.neu_laden()
        return True

    def verwerfen(self):
        if not self.aenderungen or not self.verwerfen_ok():
            return
        self.neu_laden()
        self.ins_bild()
