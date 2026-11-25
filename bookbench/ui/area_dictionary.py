# -*- coding: utf-8 -*-
"""
area_dictionary.py - Bereich Wörterbuch (Qt; Tk-Vorlage tk/area_dictionary.py): eigene Wörterbücher lesen,
bearbeiten, ergänzen, aufbauen und erzeugen. Die Logik steckt in dictionary/store.py (kwb) und
dictionary/wikidict.py (W).

  oben     Wörterbuch wählen (mehrere; Neu, Öffnen, Eigenschaften, Aus der Liste), Anzeigen, Suche
  links    Liste mit Statusstreifen (Punkt für den Stand, Piktogramm bei Fehlenden/ungeprüften Einträgen)
  rechts   Formular (Name, Kategorie, Kurzbeschreibung, andere Namen, Abschnitte; bei eingelesenen
           Einträgen das HTML bzw. den Text), darunter die Vorschau (Teiler gemerkt)
  Schritte (Anzeige, nur Wörterbücher mit Datenbank) die Schritte von wikidict.py mit Stand, Optionen
           und Ausgabe

Arten: Datenbank aus einem Wiki, Datenbank leer (nur eigene Einträge), StarDict-Ordner (ohne Datenbank).
Stand: rot = im Formular geändert, nicht übernommen; gelb = übernommen, noch nicht erzeugt; grün =
erzeugt seit dem Öffnen. Der ganze Zustand (offenes Wörterbuch, Entwürfe, Ansicht, Suche, Optionen, Ausgabe)
hängt am Bereich, nicht an den Widgets: er übersteht den Neuaufbau beim Sprachwechsel.
"""
import os
import sqlite3
import threading
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit,
                               QPushButton, QRadioButton, QSpinBox, QStackedWidget, QStyle,
                               QStyledItemDelegate, QTextBrowser, QToolTip, QVBoxLayout, QWidget, QButtonGroup)

from bookbench.device import device as kg
from bookbench.dictionary import store as kwb
from bookbench.dictionary import wikidict as W
from bookbench.i18n import N_, _, ngettext
from bookbench.ui import dialogs, threads
from bookbench.ui import markers as mk
from bookbench.ui import theme
from bookbench.ui.area import Bereich
from bookbench.ui.panes import Teiler

EINTRAEGE, FEHLENDE, IGNORIERT, SCHRITTE = range(4)
ANSICHTEN = (N_("Entries"), N_("Missing terms"), N_("Ignored and removed"), N_("Steps"))
NEU = "\x00neu"                                  # Listenschlüssel für einen neuen Eintrag
STANDARD_ABSCHNITT = "Notes"
ART_TEXT = {"wiki": N_("from a wiki"), "leer": N_("own entries"), "stardict": N_("StarDict folder")}
SPOILER = (("strict", N_("none")), ("mild", N_("background only")), ("full", N_("all")))
SCHRITT_ZEILEN = (
    ("titles", N_("1. Load titles"), N_("All article titles of the wiki (once, a few minutes).")),
    ("scan", N_("2. Search books"), N_("Look for the titles in the books; the book text stays on the computer. "
                                       "Names without an article become gaps.")),
    ("fetch", N_("3. Load articles"), N_("Only the articles that occur in the books.")),
    ("summarize", N_("4. Summarize"), N_("Claude writes the entries; cost estimated beforehand.")),
    ("crosscheck", N_("5. Cross-check"), N_("Compare with the second site, fill gaps.")),
    ("build", N_("6. Build"), N_("Write the dictionary files.")))
FORM_HINWEIS = N_("Line with # = heading, the text below it. Separate other names with commas.")


def abschnitte_text(sections):
    """Abschnitte fürs Textfeld: Zeile "# Überschrift", darunter der Text, Leerzeile dazwischen."""
    return "\n\n".join(f"# {s.get('h', '')}\n{s.get('t', '')}" for s in sections)


def abschnitte_lesen(text):
    erg, h, zeilen = [], None, []

    def fertig():
        t = " ".join(z.strip() for z in zeilen if z.strip())
        if t:
            erg.append({"h": (h or STANDARD_ABSCHNITT).strip() or STANDARD_ABSCHNITT, "t": t})
    for z in text.splitlines():
        if z.lstrip().startswith("#"):
            fertig()
            h, zeilen = z.lstrip().lstrip("#").strip(), []
        else:
            zeilen.append(z)
    fertig()
    return erg


def _roh(data):
    """"html" / "text" bei eingelesenen Einträgen, sonst None (Formular)."""
    if data is None:
        return None
    return "html" if data.get("html") is not None else "text" if data.get("text") is not None else None


def _gleich(a, b):
    def norm(d):
        return (d.get("category") or "Other", (d.get("tagline") or "").strip(),
                [(s.get("h"), s.get("t")) for s in d.get("sections", [])], list(d.get("aliases", [])),
                d.get("html"), d.get("text"))
    return norm(a) == norm(b)


def vorschau_html(titel, html):
    """Vorschau wie im Tk-Programm: Titel fett, darunter der Eintrag nur mit kursiv/fett/klein."""
    if not html:
        return ""
    from html import escape
    teile = [f"<b>{escape(titel)}</b><br>"]
    for text, stile in kwb.html_teile(html):
        t = escape(text).replace("\n", "<br>")
        if "kursiv" in stile:
            t = f"<i>{t}</i>"
        if "fett" in stile:
            t = f"<b>{t}</b>"
        if "klein" in stile:
            t = f"<small>{t}</small>"
        teile.append(t)
    return "".join(teile)


# ================================================================ Liste mit Streifen
class _Streifen(QStyledItemDelegate):
    def __init__(self, bereich, liste):
        super().__init__(liste)
        self.bereich = bereich

    def paint(self, m, opt, index):
        k = index.data(Qt.UserRole)
        stand, warn = self.bereich.status(k)
        an = bool(self.bereich.app.e.get("status_liste", True))
        rechts = 36 if an else 0
        style = opt.widget.style()
        voll = type(opt)(opt)
        self.initStyleOption(voll, index)
        voll.text = ""
        style.drawControl(QStyle.CE_ItemViewItem, voll, m, opt.widget)
        o = type(opt)(opt)
        self.initStyleOption(o, index)
        o.rect = QRect(opt.rect.x(), opt.rect.y(), opt.rect.width() - rechts, opt.rect.height())
        o.backgroundBrush = QColor(Qt.transparent)
        o.state &= ~QStyle.State_HasFocus
        style.drawControl(QStyle.CE_ItemViewItem, o, m, opt.widget)
        if not an:
            return
        x = opt.rect.right() - rechts + 2
        y = opt.rect.y() + (opt.rect.height() - 14) // 2
        if stand:
            m.drawPixmap(x, y, mk.bild("punkt", theme.MARK[theme.modus()][stand]))
        if warn:
            m.drawPixmap(x + 16, y, mk.bild("woerterbuch"))

    def sizeHint(self, opt, index):
        s = super().sizeHint(opt, index)
        return QSize(s.width(), max(s.height(), 20))


class _Liste(QListWidget):
    def __init__(self, bereich):
        super().__init__()
        self.bereich = bereich
        self.setMouseTracking(True)

    def viewportEvent(self, ev):
        if ev.type() == ev.Type.ToolTip:
            it = self.itemAt(ev.pos())
            if it:
                stand, warn = self.bereich.status(it.data(Qt.UserRole))
                text = "\n".join(x for x in (it.text(), warn or "") if x)
                QToolTip.showText(ev.globalPos(), text, self)
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(ev)


# ================================================================ Bereich
class WoerterbuchBereich(Bereich):
    kennung = "woerterbuch"
    titel = N_("Dictionary")
    symbol = "woerterbuch"

    def __init__(self, app):
        super().__init__(app)
        self.wb = None                           # kwb.Woerterbuch / StarDictWoerterbuch oder None
        self.verlauf, self.verlauf_herkunft = [], ""
        self.fehlend = {}                        # Name -> Eintrag aus wb.fehlende()
        self.entwuerfe = {}                      # Listenschlüssel -> (Titel, data, Quelle)
        self.erzeugt = set()                     # in dieser Sitzung erzeugte eigene Einträge
        self.aktuell = None                      # Listenschlüssel im Formular
        self.ansicht = EINTRAEGE
        self.such = ""
        self.ao = {"scan_ordner": "", "sofort": False, "worte": 150, "luecken": True, "websuche": False,
                   "nur_luecken": False}
        self.log_zeilen = []
        self.schritt_laeuft = False
        self._abbruch = threading.Event()
        self._laden = False
        self._modus = None
        self.liste = None
        self._migrieren()
        self.oeffnen(app.e.get("woerterbuch_aktiv") or "", still=True)

    def _migrieren(self):
        """Einstellungen von 0.10 (ein Wörterbuch) in die Liste übernehmen."""
        e = self.app.e
        alt = e.pop("woerterbuch_db", "") if "woerterbuch_db" in e else ""
        liste = e.setdefault("woerterbuecher", [])
        if alt and alt not in liste:
            liste.append(alt)
        if alt and not e.get("woerterbuch_aktiv"):
            e["woerterbuch_aktiv"] = alt

    # ================================================================ Aufbau der Seite
    def bauen(self):
        s = QWidget()
        lay = QVBoxLayout(s)
        lay.setContentsMargins(0, 0, 0, 0)
        kopf = QHBoxLayout()
        kopf.addWidget(QLabel(_("Dictionary:")))
        self.wahl = QComboBox()
        self.wahl.setMinimumWidth(320)
        self.wahl.activated.connect(lambda *a: self._gewaehlt())
        kopf.addWidget(self.wahl, 1)
        for text, fn in ((_("New …"), self.anlegen), (_("Open …"), self.oeffnen_dialog),
                         (_("Properties …"), self.eigenschaften), (_("Remove from list"), self.aus_liste)):
            k = QPushButton(text)
            k.clicked.connect(lambda *a, fn=fn: fn())
            kopf.addWidget(k)
        lay.addLayout(kopf)

        self.stapel = QStackedWidget()
        # -- ohne Wörterbuch
        leer = QWidget()
        ll = QVBoxLayout(leer)
        ll.setContentsMargins(0, 8, 0, 0)
        t = QLabel(_("No dictionary open."))
        t.setProperty("rolle", "ueberschrift")
        ll.addWidget(t)
        h = QLabel(_("New …: create a dictionary, from a wiki (e.g. a Fandom wiki) or empty for your own entries.\n"
                     "Open …: the working folder of wikidict.py (with wikidict.sqlite) or a folder with a StarDict "
                     "dictionary (.ifo), e.g. a copy or one from the e-reader."))
        h.setProperty("rolle", "hinweis")
        h.setWordWrap(True)
        ll.addWidget(h)
        ll.addStretch(1)
        self.stapel.addWidget(leer)

        # -- mit Wörterbuch
        voll = QWidget()
        vl = QVBoxLayout(voll)
        vl.setContentsMargins(0, 6, 0, 0)
        oben = QHBoxLayout()
        oben.addWidget(QLabel(_("Show:")))
        self.ansicht_cb = QComboBox()
        self.ansicht_cb.currentIndexChanged.connect(self._ansicht_gewaehlt)
        oben.addWidget(self.ansicht_cb)
        oben.addSpacing(12)
        self.suchfeld = QLineEdit(self.such)
        self.suchfeld.setPlaceholderText(_("Search:").rstrip(":") + " …")
        self.suchfeld.setClearButtonEnabled(True)
        self.suchfeld.setMaximumWidth(260)
        self.suchfeld.textChanged.connect(self._suche)
        oben.addWidget(self.suchfeld)
        oben.addStretch(1)
        self.db_label = QLabel("")
        self.db_label.setProperty("rolle", "hinweis")
        oben.addWidget(self.db_label)
        vl.addLayout(oben)
        self.innen = QStackedWidget()
        self.innen.addWidget(self._arbeit_bauen())
        self.innen.addWidget(self._schritte_bauen())
        vl.addWidget(self.innen, 1)
        self.stapel.addWidget(voll)
        lay.addWidget(self.stapel, 1)
        self.seite = s
        self._modus = "?"
        self._zeigen()
        return s

    def _arbeit_bauen(self):
        teiler = Teiler(self.app, "woerterbuch", 270)
        links = QWidget()
        ll = QVBoxLayout(links)
        ll.setContentsMargins(0, 0, 0, 0)
        self.liste = _Liste(self)
        self.liste.setSelectionMode(QAbstractItemView.SingleSelection)
        self.liste.setUniformItemSizes(True)
        self.liste.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.liste.setItemDelegate(_Streifen(self, self.liste))
        self.liste.currentItemChanged.connect(lambda *a: self._auswahl())
        ll.addWidget(self.liste, 1)
        self.anzahl = QLabel("")
        self.anzahl.setProperty("rolle", "hinweis")
        self.anzahl.setWordWrap(True)
        ll.addWidget(self.anzahl)
        teiler.addWidget(links)

        rechts = QWidget()
        rl = QVBoxLayout(rechts)
        rl.setContentsMargins(10, 0, 0, 0)
        self.kopf = QLabel("")
        self.kopf.setProperty("rolle", "ueberschrift")
        rl.addWidget(self.kopf)
        self.info = QLabel("")
        self.info.setProperty("rolle", "hinweis")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rl.addWidget(self.info)
        ou = Teiler(self.app, "woerterbuch_formular", 300, ausrichtung=Qt.Vertical, minimum=120)
        form = QWidget()
        g = QGridLayout(form)
        g.setContentsMargins(0, 4, 0, 4)
        g.setColumnStretch(1, 1)
        g.addWidget(QLabel(_("Name:")), 0, 0)
        self.name_feld = QLineEdit()
        g.addWidget(self.name_feld, 0, 1)
        self.kat_label = QLabel(_("Category:"))
        g.addWidget(self.kat_label, 0, 2)
        self.kat_feld = QComboBox()
        self.kat_feld.addItems(list(kwb.KATEGORIEN))
        g.addWidget(self.kat_feld, 0, 3)
        self.tag_label = QLabel(_("Short description:"))
        g.addWidget(self.tag_label, 1, 0)
        self.tag_feld = QLineEdit()
        g.addWidget(self.tag_feld, 1, 1, 1, 3)
        g.addWidget(QLabel(_("Other names:")), 2, 0)
        self.aliase_feld = QLineEdit()
        g.addWidget(self.aliase_feld, 2, 1, 1, 3)
        self.text_label = QLabel(_("Sections:"))
        g.addWidget(self.text_label, 3, 0, Qt.AlignTop)
        self.abschnitte = QPlainTextEdit()
        self.roh_text = QPlainTextEdit()
        self.roh_text.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        g.addWidget(self.abschnitte, 3, 1, 1, 3)
        g.addWidget(self.roh_text, 3, 1, 1, 3)
        g.setRowStretch(3, 1)
        self.form_hinweis = QLabel(_(FORM_HINWEIS))
        self.form_hinweis.setProperty("rolle", "hinweis")
        g.addWidget(self.form_hinweis, 4, 1, 1, 3)
        ou.addWidget(form)
        unten = QWidget()
        ul = QVBoxLayout(unten)
        ul.setContentsMargins(0, 6, 0, 0)
        ul.addWidget(QLabel(_("This is how it looks in the dictionary:")))
        self.vorschau = QTextBrowser()
        self.vorschau.setOpenLinks(False)
        ul.addWidget(self.vorschau, 1)
        ou.addWidget(unten)
        rl.addWidget(ou, 1)
        teiler.addWidget(rechts)
        teiler.setStretchFactor(1, 1)
        for f in (self.name_feld, self.tag_feld, self.aliase_feld):
            f.textEdited.connect(lambda *a: self._getippt())
        self.kat_feld.activated.connect(lambda *a: self._getippt())
        for t in (self.abschnitte, self.roh_text):
            t.textChanged.connect(self._getippt)
        return teiler

    def _formular_modus(self, modus):
        """Formular für strukturierte Einträge oder Rohinhalt (HTML/Text) eingelesener Wörterbücher."""
        if modus == self._modus:
            return
        self._modus = modus
        strukturiert = modus is None
        for w in (self.kat_label, self.kat_feld, self.tag_label, self.tag_feld):
            w.setVisible(strukturiert)
        self.abschnitte.setVisible(strukturiert)
        self.roh_text.setVisible(not strukturiert)
        self.text_label.setText(_("Sections:") if strukturiert else "HTML:" if modus == "html" else "Text:")
        self.form_hinweis.setText(_(FORM_HINWEIS) if strukturiert else
                                  _("Entry from an imported dictionary: content as stored (HTML or text)."))

    def _schritte_bauen(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.aufbau_titel = QLabel("")
        self.aufbau_titel.setProperty("rolle", "ueberschrift")
        lay.addWidget(self.aufbau_titel)
        self.aufbau_info = QLabel("")
        self.aufbau_info.setProperty("rolle", "hinweis")
        self.aufbau_info.setWordWrap(True)
        lay.addWidget(self.aufbau_info)
        g = QGridLayout()
        g.setColumnStretch(2, 1)
        g.setVerticalSpacing(8)
        self.schritt_zeilen = {}
        optionen = {"scan": self._opt_scan, "summarize": self._opt_sum, "crosscheck": self._opt_check}
        for r, (befehl, titel, erklaerung) in enumerate(SCHRITT_ZEILEN):
            t = QLabel(_(titel))
            t.setProperty("rolle", "abschnitt")
            g.addWidget(t, r, 0, Qt.AlignTop)
            stand = QLabel("")
            stand.setProperty("rolle", "hinweis")
            stand.setMinimumWidth(220)
            g.addWidget(stand, r, 1, Qt.AlignTop)
            mitte = QWidget()
            ml = QVBoxLayout(mitte)
            ml.setContentsMargins(0, 0, 0, 0)
            e = QLabel(_(erklaerung))
            e.setProperty("rolle", "hinweis")
            e.setWordWrap(True)
            ml.addWidget(e)
            if befehl in optionen:
                optionen[befehl](ml)
            g.addWidget(mitte, r, 2)
            knopf = QPushButton(_("Start"))
            knopf.clicked.connect(lambda *a, b=befehl: self.schritt_starten(b))
            g.addWidget(knopf, r, 3, Qt.AlignTop)
            self.schritt_zeilen[befehl] = (stand, knopf, [t, stand, mitte, knopf])
        lay.addLayout(g)
        z = QHBoxLayout()
        z.addWidget(QLabel(_("Output:")))
        z.addStretch(1)
        self.abbruch_knopf = QPushButton(_("Cancel"))
        self.abbruch_knopf.clicked.connect(self._abbrechen)
        self.abbruch_knopf.setEnabled(self.schritt_laeuft)
        z.addWidget(self.abbruch_knopf)
        lay.addSpacing(10)
        lay.addLayout(z)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.log.setPlainText("\n".join(self.log_zeilen))
        lay.addWidget(self.log, 1)
        return w

    def _haken(self, schl, text):
        c = QCheckBox(text)
        c.setChecked(bool(self.ao[schl]))
        c.toggled.connect(lambda an: self.ao.__setitem__(schl, an))
        return c

    def _opt_scan(self, lay):
        z = QHBoxLayout()
        self.scan_feld = QLineEdit(self.ao["scan_ordner"])
        self.scan_feld.textChanged.connect(lambda t: self.ao.__setitem__("scan_ordner", t))
        z.addWidget(self.scan_feld, 1)
        k = QPushButton(_("Choose …"))
        k.clicked.connect(self._scan_ordner_waehlen)
        z.addWidget(k)
        lay.addLayout(z)

    def _opt_sum(self, lay):
        z = QHBoxLayout()
        z.addWidget(self._haken("sofort", _("immediately instead of batch (twice the price)")))
        z.addSpacing(10)
        z.addWidget(QLabel(_("Length about")))
        sp = QSpinBox()
        sp.setRange(60, 400)
        sp.setSingleStep(10)
        sp.setValue(int(self.ao["worte"]))
        sp.valueChanged.connect(lambda v: self.ao.__setitem__("worte", v))
        z.addWidget(sp)
        z.addWidget(QLabel(_("words")))
        z.addStretch(1)
        lay.addLayout(z)

    def _opt_check(self, lay):
        z = QHBoxLayout()
        z.addWidget(self._haken("luecken", _("Fill gaps")))
        z.addWidget(self._haken("nur_luecken", _("gaps only")))
        z.addWidget(self._haken("websuche", _("Web search (1 cent per search)")))
        z.addStretch(1)
        lay.addLayout(z)

    # ================================================================ Werkzeugleiste, Seitenleiste
    def werkzeug(self):
        return [("uebernehmen", _("Apply"), self.uebernehmen,
                 _("Apply the entry (Ctrl+Enter); it goes into the dictionary with Build")),
                ("rueckgaengig", _("Discard"), self.verwerfen, _("Discard the changes in the form")),
                None,
                ("neu", _("New"), self.neu, _("Add a new term by hand")),
                ("suchen", _("Claude"), None, _("Entry from Claude: search the web, from a page, from own knowledge"),
                 [(_("Search the web (about 2-4 cents)"), lambda: self.ki("suche")),
                  (_("Summarize from a page …"), lambda: self.ki("link")),
                  (_("From own knowledge (unverified)"), lambda: self.ki("wissen"))]),
                ("zeile_minus", _("Remove"), self.entfernen,
                 _("Ignore a missing term or take an entry out of the dictionary (undo under Ignored and removed)")),
                None,
                ("woerterbuch", _("Build"), self.erzeugen,
                 _("Rewrite the dictionary files; then copy them to the e-reader in the E-reader area"))]

    def menue(self, leiste):
        m = leiste.addMenu(_("Dictionary"))

        def befehl(text, fn, taste=None):
            act = m.addAction(text, lambda: self._aus_menue(fn))
            if taste:
                act.setShortcut(taste)
                act.setShortcutContext(Qt.WidgetShortcut)      # Strg+Enter gehört dem Fenster
        befehl(_("New dictionary …"), self.anlegen)
        befehl(_("Open dictionary …"), self.oeffnen_dialog)
        befehl(_("Properties …"), self.eigenschaften)
        befehl(_("Take changes from a StarDict folder …"), self.aus_stardict_uebernehmen)
        m.addSeparator()
        befehl(_("New entry"), self.neu)
        befehl(_("Apply"), self.uebernehmen, "Ctrl+Return")
        befehl(_("Discard"), self.verwerfen)
        befehl(_("Discard own version (original)"), self.original)
        m.addSeparator()
        befehl(_("Claude: search the web"), lambda: self.ki("suche"))
        befehl(_("Claude: summarize from a page …"), lambda: self.ki("link"))
        befehl(_("Claude: from own knowledge (unverified)"), lambda: self.ki("wissen"))
        m.addSeparator()
        befehl(_("Ignore / remove"), self.entfernen)
        befehl(_("Bring back"), self.zurueckholen)
        m.addSeparator()
        befehl(_("Build dictionary"), self.erzeugen)
        befehl(_("Steps (from the wiki)"), self.schritte_zeigen)

    def _aus_menue(self, fn):
        """Menübefehl: Bereich zeigen, dann ausführen."""
        if self.app._aktuell != self.kennung:
            self.app.bereich_zeigen(self.kennung)
        fn()

    def schritte_zeigen(self):
        if self.wb and self.wb.art in ("wiki", "leer"):
            self._ansicht_setzen(SCHRITTE)
            self.liste_fuellen()

    def marken(self):
        n = sum(1 for f in self.fehlend.values() if f["nachgeschlagen"]) if self.wb else 0
        return [("woerterbuch", n)] if n else []

    def beim_zeigen(self):
        """Bereich wird sichtbar: Nachschlageverlauf auffrischen (Gerät evtl. neu angesteckt)."""
        if self.wb:
            self.verlauf_laden()
            self.liste_fuellen()

    def neu_zeichnen(self):
        if self.liste is not None:
            self.liste.viewport().update()

    def offen(self):
        return len(self.entwuerfe)

    def schliessen_ok(self):
        return self._offen_ok()

    def suche_fokus(self):
        if self.wb and self.seite is not None:
            self.suchfeld.setFocus()
            self.suchfeld.selectAll()

    # ================================================================ Wörterbücher verwalten
    def _liste_der_woerterbuecher(self):
        return [p for p in self.app.e.get("woerterbuecher", []) if p]

    def _anzeigename(self, pfad):
        info = kwb.kurzinfo(pfad)
        if not info:
            return _("(not found)") + f" - {pfad}"
        return f"{info[0]} ({_(ART_TEXT.get(info[1], info[1]))}) - {pfad}"

    def wahl_fuellen(self):
        if self.seite is None:
            return
        self.wahl.blockSignals(True)
        self.wahl.clear()
        aktiv = str(self.wb.pfad) if self.wb else ""
        for p in self._liste_der_woerterbuecher():
            self.wahl.addItem(self._anzeigename(p), p)
        self.wahl.setCurrentIndex(self.wahl.findData(aktiv) if aktiv else -1)
        self.wahl.blockSignals(False)

    def eingetragen_fuer(self, ordner):
        """Eingetragenes Wörterbuch (Arbeitsordner mit Datenbank), das zuletzt in ordner erzeugt wurde
        (meta built_out), sonst None - für den Doppelklick im Bereich E-Reader."""
        try:
            ziel = Path(ordner).resolve()
        except OSError:
            return None
        for p in self._liste_der_woerterbuecher():
            q = Path(p).expanduser()
            db_datei = q if q.suffix == ".sqlite" else W.db_datei(q)
            if not db_datei.is_file():
                continue
            try:
                db = sqlite3.connect(f"file:{db_datei}?mode=ro", uri=True)
                try:
                    aus = W.meta_get(db, "built_out", "")
                finally:
                    db.close()
                if aus and Path(aus).resolve() == ziel:
                    return p
            except (sqlite3.Error, OSError):
                continue
        return None

    def _gewaehlt(self):
        p = self.wahl.currentData()
        if p and (not self.wb or str(self.wb.pfad) != p):
            if self._offen_ok():
                self.oeffnen(p)
            else:
                self.wahl_fuellen()

    def _offen_ok(self):
        n = len(self.entwuerfe)
        return not n or dialogs.frage(self.app, _("Dictionary"), ngettext(
            "{n} entry is changed in the form but not applied. Discard?",
            "{n} entries are changed in the form but not applied. Discard?", n).format(n=n), standard=False)

    def oeffnen_dialog(self):
        if not self._offen_ok():
            return
        o = dialogs.ordner(self.app, _("Open dictionary (folder, it is also searched below)"),
                           self.app.e.get("woerterbuch_aktiv") or str(Path.home()))
        if not o:
            return
        gefunden = kwb.finden(o)
        if not gefunden:
            self.app.status.set(_("There is no dictionary in {ordner} or below (no .ifo file, no wikidict.sqlite).")
                                .format(ordner=o))
        elif len(gefunden) == 1:
            self.oeffnen(gefunden[0])
        else:
            self.auswahl_offen = AuswahlDialog(self, Path(o), gefunden)
            self.auswahl_offen.open()

    def oeffnen(self, pfad, still=False):
        if self.wb:
            self.wb.schliessen()
        self.wb, self.entwuerfe, self.aktuell = None, {}, None
        if pfad:
            try:
                self.wb = kwb.oeffnen(pfad)
            except Exception as e:                     # fehlende Datei, kaputte Datenbank
                if not still:
                    self.app.status.set(_("Dictionary not opened: {fehler}").format(fehler=e))
        e = self.app.e
        if self.wb:
            p = str(self.wb.pfad)
            if p not in e.setdefault("woerterbuecher", []):
                e["woerterbuecher"].append(p)
            e["woerterbuch_aktiv"] = p
            if self.wb.art in ("wiki", "leer"):
                self.ao["scan_ordner"] = W.meta_get(self.wb.db, "scan_dir", "") or self.app.ordner or ""
            elif self.ansicht == SCHRITTE:
                self.ansicht = EINTRAEGE
            self.verlauf_laden()
            if not still:
                self.app.status.set(ngettext("Dictionary {name}: {n} entry.", "Dictionary {name}: {n} entries.",
                                             len(self.wb.eintraege)).format(name=self.wb.titel(), n=len(self.wb.eintraege)))
        self.fehlend_berechnen()
        if self.seite is not None:
            self._zeigen()
        if hasattr(self.app, "leiste"):
            self.app._zaehler()

    def _zeigen(self):
        """Widgets nach dem Zustand: Auswahl, Seite, Ansichten, Liste."""
        self.wahl_fuellen()
        self.stapel.setCurrentIndex(1 if self.wb else 0)
        if not self.wb:
            return
        self.db_label.setText(str(getattr(self.wb, "datei", self.wb.ifo_pfad if self.wb.art == "stardict"
                                          else self.wb.pfad)))
        hat_aufbau = self.wb.art in ("wiki", "leer")
        self.ansicht_cb.blockSignals(True)
        self.ansicht_cb.clear()
        for t in ANSICHTEN if hat_aufbau else ANSICHTEN[:3]:
            self.ansicht_cb.addItem(_(t))
        self.ansicht_cb.setCurrentIndex(self.ansicht)
        self.ansicht_cb.blockSignals(False)
        if hasattr(self, "scan_feld"):
            self.scan_feld.setText(self.ao["scan_ordner"])
        self.liste_fuellen(waehlen=self.aktuell)

    def aus_liste(self):
        if not self.wb:
            return
        p = str(self.wb.pfad)
        e = self.app.e
        e["woerterbuecher"] = [x for x in e.get("woerterbuecher", []) if x != p]
        e["woerterbuch_aktiv"] = e["woerterbuecher"][0] if e["woerterbuecher"] else ""
        self.oeffnen(e["woerterbuch_aktiv"], still=True)
        self.app.status.set(_("{pfad} removed from the list (the files stay).").format(pfad=p))

    def anlegen(self):
        if self._offen_ok():
            self.dialog_offen = WoerterbuchDialog(self, neu=True)
            self.dialog_offen.open()

    def eigenschaften(self):
        if self.wb:
            self.dialog_offen = WoerterbuchDialog(self, neu=False)
            self.dialog_offen.open()

    def verlauf_laden(self):
        k = getattr(self.app, "kobo", None)
        text, self.verlauf_herkunft = kg.verlauf_lesen(getattr(k, "wurzel", None) if k else None,
                                                       Path(self.app.e["sicherungsordner"]) / "KOReader")
        self.verlauf = kwb.nachschlageverlauf(text)

    def _bibliothek(self):
        return {b.titel: (b.reihe, b.autor) for b in getattr(self.app, "buecher", [])}

    def fehlend_berechnen(self):
        self.fehlend = {f["name"]: f for f in self.wb.fehlende(self.verlauf, self._bibliothek())} if self.wb else {}

    # ================================================================ Liste
    def _ansicht_gewaehlt(self, i):
        if i >= 0:
            self.ansicht = i
            self.liste_fuellen()

    def _suche(self, t):
        self.such = t
        self.liste_fuellen()

    def namen(self):
        """Schlüssel der Liste in der aktuellen Ansicht."""
        if self.liste is None:
            return []
        return [self.liste.item(i).data(Qt.UserRole) for i in range(self.liste.count())]

    def liste_fuellen(self, waehlen=None):
        self.fehlend_berechnen()
        if self.app and hasattr(self.app, "leiste"):
            self.app._zaehler()
        if self.seite is None or not self.wb:
            return
        if self.ansicht == SCHRITTE:
            self.innen.setCurrentIndex(1)
            self.aufbau_zeigen()
            return
        self.innen.setCurrentIndex(0)
        alt = waehlen if waehlen is not None else self.aktuell
        such = self.such.strip().casefold()
        if self.ansicht == EINTRAEGE:
            namen = self.wb.suchen(such)
            if NEU in self.entwuerfe:
                namen = [NEU] + namen
            self.anzahl.setText(ngettext("{n} of {gesamt} entry", "{n} of {gesamt} entries", len(self.wb.eintraege))
                                .format(n=len(namen), gesamt=len(self.wb.eintraege)))
        elif self.ansicht == FEHLENDE:
            namen = [n for n in self.fehlend if such in n.casefold()]
            herkunft = _("Lookup history {herkunft}").format(herkunft=self.verlauf_herkunft) if self.verlauf_herkunft \
                else _("no lookup history (connect the e-reader or back up the KOReader settings)")
            self.anzahl.setText(ngettext("{n} missing term", "{n} missing terms", len(namen)).format(n=len(namen))
                                + "\n" + herkunft)
        else:
            namen = [n for n in self.wb.ignorierte() + self.wb.geloescht() if such in n.casefold()]
            self.anzahl.setText(_("{n} ignored or removed").format(n=len(namen)))
        self.liste.blockSignals(True)
        self.liste.clear()
        for n in namen:
            it = QListWidgetItem("＋ " + _("new entry") if n == NEU else n)
            it.setData(Qt.UserRole, n)
            self.liste.addItem(it)
        if alt in namen:
            self.liste.setCurrentRow(namen.index(alt))
            self.liste.scrollToItem(self.liste.currentItem())
        self.liste.blockSignals(False)
        self._auswahl()

    def status(self, k):
        if not self.wb or k is None:
            return None, None
        warn = None
        if self.ansicht == FEHLENDE:
            f = self.fehlend.get(k)
            warn = f["grund"] if f and f["nachgeschlagen"] else None
        elif "unverified" in (self.wb.quellen.get(k) or ""):
            warn = _("unverified entry from Claude's own knowledge")
        if k in self.entwuerfe:
            return "rot", warn
        if k in self.erzeugt and not self.wb.stand(k):
            return "gruen", warn
        return self.wb.stand(k), warn

    # ================================================================ Formular
    def _auswahl(self):
        it = self.liste.currentItem() if self.liste is not None else None
        self.aktuell = it.data(Qt.UserRole) if it else None
        self.anzeigen()

    def anzeigen(self):
        k = self.aktuell
        self._laden = True
        try:
            for f in (self.name_feld, self.tag_feld, self.aliase_feld):
                f.clear()
            for t in (self.abschnitte, self.roh_text):
                t.clear()
            self.name_feld.setReadOnly(False)
            if not self.wb or not k:
                self._formular_modus(None)
                self.kopf.setText(_("Choose an entry on the left.") if self.wb else "")
                self.info.setText("")
                self.vorschau.clear()
                return
            titel, data, quelle = self._stand_von(k)
            self._formular_modus(_roh(data))
            self.kopf.setText(titel or _("New entry"))
            self.info.setText(self._info(k, titel, quelle))
            self.name_feld.setText(titel)
            if data:
                self.aliase_feld.setText(", ".join(data.get("aliases", [])))
                if self._modus:
                    self.roh_text.setPlainText(data.get(self._modus) or "")
                else:
                    i = self.kat_feld.findText(data.get("category", ""))
                    self.kat_feld.setCurrentIndex(max(0, i))
                    self.tag_feld.setText(data.get("tagline", ""))
                    self.abschnitte.setPlainText(abschnitte_text(data.get("sections", [])))
            neu = k == NEU or self.ansicht == FEHLENDE or (k in self.entwuerfe and titel != k)
            self.name_feld.setReadOnly(not neu)
        finally:
            self._laden = False
        self._vorschau_aktualisieren()
        self.neu_zeichnen()

    def _basis(self, k):
        """(Titel, data, Quelle) in der Datenbank bzw. Datei, ohne Entwurf."""
        if k == NEU or self.ansicht == FEHLENDE:
            return ("" if k == NEU else k), None, kwb.QUELLE_EIGEN
        return k, self.wb.eintraege.get(k) or self.wb.basis.get(k), self.wb.quellen.get(k, "")

    def _stand_von(self, k):
        if k in self.entwuerfe:
            return self.entwuerfe[k]
        return self._basis(k)

    def _info(self, k, titel, quelle):
        teile = []
        if self.ansicht == FEHLENDE and k in self.fehlend:
            teile.append(self.fehlend[k]["grund"])
        elif self.ansicht == IGNORIERT:
            teile.append(_("removed from the dictionary") if k in self.wb.geloescht() else _("ignored"))
        if quelle:
            teile.append(_("Source: {quelle}").format(quelle=quelle))
        if self.wb.ist_eigen(titel) and titel in self.wb.basis:
            teile.append(_("own version (original exists)"))
        buecher = self.wb.buecher.get(titel) or (self.fehlend.get(k) or {}).get("buecher") or []
        if buecher:
            teile.append(_("occurs in: ") + ", ".join(f"{b} ({n})" for b, n in buecher[:5]))
        syn = self.wb.synonyme_von(titel)
        if syn:
            teile.append(_("can also be found under: ") + ", ".join(syn[:12]) + (" …" if len(syn) > 12 else ""))
        return "  ·  ".join(teile)

    def _formular(self):
        aliase = [a.strip() for a in self.aliase_feld.text().split(",") if a.strip()]
        if self._modus:
            return self.name_feld.text().strip(), {self._modus: self.roh_text.toPlainText(), "aliases": aliase}
        return self.name_feld.text().strip(), {
            "category": self.kat_feld.currentText() or "Other",
            "tagline": self.tag_feld.text().strip(),
            "sections": abschnitte_lesen(self.abschnitte.toPlainText()),
            "aliases": aliase}

    def _getippt(self):
        if self._laden or not self.wb or not self.aktuell:
            return
        k = self.aktuell
        titel, data = self._formular()
        b_titel, b_data, b_quelle = self._basis(k)
        if b_data is not None and titel == b_titel and _gleich(data, b_data):
            self.entwuerfe.pop(k, None)
        else:
            if k in self.entwuerfe:
                quelle = self.entwuerfe[k][2]
            elif b_data is not None and b_quelle and b_quelle != kwb.QUELLE_EIGEN and not b_quelle.endswith("edited"):
                quelle = f"{b_quelle}, edited"
            else:
                quelle = b_quelle or kwb.QUELLE_EIGEN
            self.entwuerfe[k] = (titel, data, quelle)
        self._vorschau_aktualisieren()
        self.neu_zeichnen()

    def _vorschau_aktualisieren(self):
        if not self.wb or not self.aktuell:
            self.vorschau.clear()
            return
        k = self.aktuell
        if k in self.entwuerfe:
            titel, data, quelle = self.entwuerfe[k]
            leer = not (data.get("tagline") or data.get("html") or data.get("text"))
            html = "" if leer else self.wb.vorschau(titel or "?", data, quelle)
        else:
            titel, data, quelle = self._stand_von(k)
            html = self.wb.vorschau(titel) if titel in self.wb.eintraege else \
                (self.wb.vorschau(titel, data, quelle) if data else "")
        self.vorschau.setHtml(vorschau_html(titel, html))

    # ================================================================ Aktionen
    def _bereit(self):
        if not self.wb:
            self.app.status.set(_("No dictionary open (New … or Open …)."))
            return False
        if self.app._arbeit:
            self.app.status.set(_("Still running: {arbeit}.").format(arbeit=self.app._arbeit))
            return False
        return True

    def _client(self):
        from bookbench.core import blurb_lookup as kbl
        client, fehler = kbl.api_client(self.app.e)
        if client is None:
            dialogs.fehler(self.app, _("Claude"), fehler)
        return client

    def uebernehmen(self):
        if not self._bereit():
            return
        k = self.aktuell
        if not k or k not in self.entwuerfe:
            self.app.status.set(_("Nothing to apply."))
            return
        titel, data, quelle = self.entwuerfe[k]
        if not titel or not (data.get("tagline") or data.get("html") or data.get("text")):
            self.app.status.set(_("Name and short description (or content) are required."))
            return
        ersetzt = titel in self.wb.eintraege and titel != k
        if ersetzt and not dialogs.frage(
                self.app, _("Apply"),
                _("\"{titel}\" is already in the dictionary. Replace it with this entry?").format(titel=titel)):
            return
        self.wb.eigen_speichern(titel, data, quelle)
        self.entwuerfe.pop(k, None)
        self.erzeugt.discard(titel)
        if k != titel and k != NEU and self.ansicht == FEHLENDE and not self.wb.bekannt(k):
            self.wb.ignorieren(k)       # z. B. "Sindermann" -> "Kyril Sindermann" ohne Alias: nicht mehr fehlend
        naechster = self._naechster(k) if self.ansicht == FEHLENDE else titel
        if k == NEU:
            self._ansicht_setzen(EINTRAEGE)
        self.liste_fuellen(waehlen=naechster)
        self.app.status.set(f"{titel}: " + _("applied. It goes into the dictionary with Build."))

    def _ansicht_setzen(self, i):
        self.ansicht = i
        if self.seite is not None:
            self.ansicht_cb.blockSignals(True)
            self.ansicht_cb.setCurrentIndex(i)
            self.ansicht_cb.blockSignals(False)

    def _naechster(self, k):
        namen = self.namen()
        if k in namen and namen.index(k) + 1 < len(namen):
            return namen[namen.index(k) + 1]
        return None

    def verwerfen(self):
        k = self.aktuell
        if k in self.entwuerfe:
            self.entwuerfe.pop(k)
            if k == NEU:
                self.liste_fuellen()
            else:
                self.anzeigen()
            self.app.status.set(_("Changes discarded."))

    def neu(self):
        if not self._bereit():
            return
        self._ansicht_setzen(EINTRAEGE)
        self.such = ""
        if self.seite is not None:
            self.suchfeld.blockSignals(True)
            self.suchfeld.clear()
            self.suchfeld.blockSignals(False)
        self.entwuerfe[NEU] = ("", {"category": "Person", "tagline": "", "sections": [], "aliases": []},
                               kwb.QUELLE_EIGEN)
        self.liste_fuellen(waehlen=NEU)
        if self.seite is not None:
            self.name_feld.setFocus()

    def original(self):
        k = self.aktuell
        if self._bereit() and k and self.wb.ist_eigen(k):
            self.entwuerfe.pop(k, None)
            self.wb.original(k)
            self.liste_fuellen(waehlen=k)
            self.app.status.set(f"{k}: " + (_("own version discarded, the original applies again.")
                                            if k in self.wb.eintraege else _("own version discarded.")))

    def entfernen(self):
        if not self._bereit() or not self.aktuell or self.aktuell == NEU:
            return
        k = self.aktuell
        naechster = self._naechster(k)
        self.entwuerfe.pop(k, None)
        if self.ansicht == FEHLENDE:
            self.wb.ignorieren(k)
            self.app.status.set(f"{k}: " + _("ignored (get it back under Ignored and removed)."))
        elif self.ansicht == EINTRAEGE:
            self.wb.loeschen(k)
            self.app.status.set(f"{k}: " + _("taken out of the dictionary (get it back under Ignored and removed)."))
        else:
            self.zurueckholen()
            return
        self.liste_fuellen(waehlen=naechster)

    def zurueckholen(self):
        k = self.aktuell
        if not self._bereit() or not k:
            return
        if k in self.wb.geloescht():
            self.wb.original(k)
        else:
            self.wb.nicht_ignorieren(k)
        self.liste_fuellen(waehlen=self._naechster(k))
        self.app.status.set(f"{k}: " + _("restored."))

    def ki(self, art):
        if not self._bereit() or not self.aktuell or self.ansicht == SCHRITTE:
            self.app.status.set(_("First choose a term or enter a name with New."))
            return
        k = self.aktuell
        name = self.name_feld.text().strip() or (k if k != NEU else "")
        if not name:
            self.app.status.set(_("Enter a name first."))
            return
        url = None
        if art == "link":
            url = dialogs.eingabe(self.app, _("From a page"), _("Address of a page about \"{name}\":").format(name=name))
            if not url or not url.strip():
                return
            url = url.strip()
        client = self._client()
        if client is None:
            return
        buecher = self.wb.buecher.get(name) or (self.fehlend.get(k) or {}).get("buecher") or []
        e, profil = self.app.e, self.wb.profil()
        ergebnis = {}

        def arbeit():
            data, quelle, meldung = kwb.ki_eintrag(client, e["modell"], name, art, url, buecher,
                                                   profil.get("spoilers") or "mild", thema=profil.get("topic"))
            ergebnis.update(data=data, quelle=quelle)
            if data is None:
                return f"{name}: {meldung}." + (" " + _("With \"From a page\" you can give an address.")
                                               if art == "suche" else "")
            return f"{name}: " + _("draft from Claude, please check and apply (Ctrl+Enter).")

        def nachher():
            data = ergebnis.get("data")
            if data is None:
                return
            titel = data.pop("title", name)
            self.entwuerfe[k] = (titel, {f: data.get(f) for f in ("category", "tagline", "sections", "aliases")},
                                 ergebnis["quelle"])
            if self.aktuell == k and self.seite is not None:
                self.anzeigen()
            self.neu_zeichnen()
        self.app.hintergrund(_("Asking Claude"), arbeit, nachher=nachher)

    def erzeugen(self):
        if not self._bereit():
            return
        if self.aktuell in self.entwuerfe:
            if not dialogs.frage(self.app, _("Build"), _("The entry in the form is not applied yet and will not be in "
                                                         "the dictionary. Build anyway?")):
                return
        e = self.app.e
        stardict = self.wb.art == "stardict"
        ziel = self.wb.ausgabe()
        if not ziel:
            ziel = dialogs.ordner(self.app, _("Folder for the dictionary (copied to the e-reader)"),
                                  str(self.wb.pfad.parent))
            if not ziel:
                return
        pfad = str(getattr(self.wb, "datei", self.wb.pfad))
        sicherung = Path(e["sicherungsordner"]) / "Wörterbücher"
        eigene = set(self.wb.eigen)

        def arbeit():
            wb = kwb.oeffnen(pfad)                     # eigene Verbindung: sqlite3 nur im eigenen Thread
            try:
                n, nsyn = wb.erzeugen(ziel, sicherung=sicherung)
            finally:
                wb.schliessen()
            if not n:
                raise RuntimeError(_("There are no entries."))
            return (_("Dictionary built: {n} entries, {nsyn} synonyms in {ziel}").format(n=n, nsyn=nsyn, ziel=ziel)
                    + (" " + _("(backed up before in {sicherung})").format(sicherung=sicherung) if stardict else "")
                    + ". " + _("Copy it to the e-reader in the E-reader area."))

        def nachher():
            if not self.wb:
                return
            self.wb.laden()
            self.erzeugt |= eigene
            if not e.get("woerterbuch_quelle"):
                e["woerterbuch_quelle"] = ziel          # damit der Bereich E-Reader es gleich findet
            self.liste_fuellen()
            kobo = getattr(self.app, "kobo", None)
            if kobo is not None and hasattr(kobo, "_quellen"):
                kobo._quellen = (None, 0.0, [])
        self.app.hintergrund(_("Building dictionary"), arbeit, nachher=nachher)

    def aus_stardict_uebernehmen(self):
        """Änderungen, die unterwegs an einer StarDict-Kopie gemacht wurden, in die Datenbank holen."""
        if not self._bereit() or self.wb.art == "stardict":
            self.app.status.set(_("Only for dictionaries with a database: the changes are collected there."))
            return
        o = dialogs.ordner(self.app, _("StarDict folder with changes from Bookbench"))
        if not o:
            return
        n = self.wb.aus_stardict_uebernehmen(o)
        self.liste_fuellen()
        self.app.status.set(ngettext("{n} change taken from {ordner}.", "{n} changes taken from {ordner}.", n)
                            .format(n=n, ordner=o) if n else
                            _("{ordner} has no changes from Bookbench (bookbench.json).").format(ordner=o))

    # ================================================================ Schritte (wikidict)
    def aufbau_zeigen(self):
        wb = self.wb
        if not wb or wb.art == "stardict" or self.seite is None:
            return
        p = wb.profil()
        st = wb.stand_aufbau()
        wiki = wb.art == "wiki"
        self.aufbau_titel.setText(f"{wb.titel()} - {_(ART_TEXT[wb.art])}")
        self.aufbau_info.setText("  ·  ".join(x for x in (
            _("Topic: {thema}").format(thema=p.get("topic")) if p.get("topic") else "",
            f"Wiki: {p.get('wiki')}" if wiki else "",
            _("Cross-check: {seite}").format(seite=p.get("check_site") or _("none")) if wiki else "",
            _("last built: {wann}").format(wann=st["erzeugt"] or _("never"))) if x))
        texte = {
            "titles": _("{titel} titles, {weiter} redirects").format(titel=st["titel"], weiter=st["weiterleitungen"]),
            "scan": _("{buecher} books, {begriffe} terms, {luecken} gaps").format(
                buecher=st["buecher"], begriffe=st["begriffe"], luecken=st["luecken"]),
            "fetch": _("{artikel} of {begriffe} articles").format(artikel=st["artikel"], begriffe=st["begriffe"]),
            "summarize": _("{n} entries").format(n=st["eintraege"]) + (
                ", " + _("{n} batch open").format(n=st["batches"]) if st["batches"] else ""),
            "crosscheck": _("{n} checked ({ok} ok), {luecken} gaps filled").format(
                n=st["geprueft"], ok=st["geprueft_ok"], luecken=st["luecken_ok"]),
            "build": _("{n} entries in the dictionary").format(n=len(wb.eintraege)),
        }
        laeuft = bool(self.app._arbeit)
        for befehl, (stand, knopf, widgets) in self.schritt_zeilen.items():
            sichtbar = wiki or befehl in ("scan", "build")
            for w in widgets:
                w.setVisible(sichtbar)
            stand.setText(texte.get(befehl, ""))
            knopf.setEnabled(not (laeuft or (befehl == "crosscheck" and not p.get("check_site"))))
        self.abbruch_knopf.setEnabled(self.schritt_laeuft)

    def _scan_ordner_waehlen(self):
        o = dialogs.ordner(self.app, _("Books folder to search"),
                           self.ao["scan_ordner"] or self.app.ordner or str(Path.home()))
        if o:
            self.ao["scan_ordner"] = o
            self.scan_feld.setText(o)

    def _log(self, text, ersetzen=False):
        if ersetzen and self.log_zeilen:
            self.log_zeilen[-1] = text
        else:
            self.log_zeilen.append(text)
        if self.seite is not None:
            self.log.setPlainText("\n".join(self.log_zeilen))
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _abbrechen(self):
        self._abbruch.set()
        self.app.status.set(_("Cancelling at the next intermediate step …"))

    def schritt_starten(self, befehl):
        if not self._bereit():
            return
        if befehl == "build":
            return self.erzeugen()
        wb, e = self.wb, self.app.e
        p = wb.profil()
        argumente = []
        if befehl == "scan":
            ordner = self.ao["scan_ordner"].strip()
            if not ordner or not Path(ordner).is_dir():
                self.app.status.set(_("Choose the books folder first."))
                return
            W.meta_set(wb.db, "scan_dir", ordner)
            argumente = [ordner]
        elif befehl in ("summarize", "crosscheck"):
            if self._client() is None:
                return
            if e.get("api_key"):
                os.environ["ANTHROPIC_API_KEY"] = e["api_key"]
            argumente = ["--model", e["modell"], "--spoilers", p.get("spoilers") or "mild"]
            if befehl == "summarize":
                argumente += ["--words", str(self.ao["worte"])] + (["--sync"] if self.ao["sofort"] else [])
            else:
                if self.ao["nur_luecken"]:
                    argumente.append("--gaps-only")
                elif self.ao["luecken"]:
                    argumente.append("--gaps")
                if self.ao["websuche"]:
                    argumente.append("--search")
        self._abbruch.clear()
        self.log_zeilen = []
        if self.seite is not None:
            self.log.clear()
        self.schritt_laeuft = True
        arbeitsordner = str(wb.pfad)
        name = _(kwb.SCHRITTE[befehl][0])

        def schreiben(text, ersetzen=False):
            threads.im_hauptthread(lambda: self._log(text, ersetzen))

        def fragen(text):
            antwort, fertig = {}, threading.Event()

            def frage():
                antwort["ja"] = dialogs.frage(self.app, name, text)
                fertig.set()
            threads.im_hauptthread(frage)
            while not fertig.wait(0.2):
                if self._abbruch.is_set():
                    return False
            return antwort.get("ja", False)

        def arbeit():
            return kwb.schritt(arbeitsordner, befehl, argumente, schreiben, fragen, self._abbruch.is_set)

        def nachher():
            self.schritt_laeuft = False
            if self.wb:
                self.wb.laden()
            self.liste_fuellen()
        self.app.hintergrund(name, arbeit, nachher=nachher)
        self.aufbau_zeigen()


# ================================================================ Dialog: mehrere gefunden
class AuswahlDialog(QDialog):
    """Mehrere Wörterbücher im gewählten Ordner: markierte in die Liste, das erste öffnen."""

    def __init__(self, bereich, basis, pfade):
        super().__init__(bereich.app)
        self.bereich, self.pfade = bereich, pfade
        self.setWindowTitle(_("Dictionaries found"))
        lay = QVBoxLayout(self)
        t = QLabel(_("There are {n} dictionaries in {ordner}. The selected ones go into the list, the first one is "
                     "opened.").format(n=len(pfade), ordner=basis))
        t.setWordWrap(True)
        lay.addWidget(t)
        self.liste = QListWidget()
        self.liste.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for p in pfade:
            info = kwb.kurzinfo(p) or (p.name, "?")
            try:
                rel = p.relative_to(basis)
            except ValueError:
                rel = p
            self.liste.addItem(f"{info[0]} ({_(ART_TEXT.get(info[1], info[1]))}) - {rel}")
        self.liste.setCurrentRow(0)
        self.liste.itemDoubleClicked.connect(lambda *a: self.ok())
        lay.addWidget(self.liste, 1)
        z = QHBoxLayout()
        z.addStretch(1)
        k = QPushButton(_("Open"))
        k.setDefault(True)
        k.clicked.connect(self.ok)
        z.addWidget(k)
        a = QPushButton(_("Cancel"))
        a.clicked.connect(self.reject)
        z.addWidget(a)
        lay.addLayout(z)
        self.resize(640, 360)

    def ok(self):
        gewaehlt = [self.pfade[self.liste.row(it)] for it in self.liste.selectedItems()]
        gewaehlt.sort(key=self.pfade.index)
        if not gewaehlt:
            return
        liste = self.bereich.app.e.setdefault("woerterbuecher", [])
        for p in gewaehlt[1:]:
            if str(p) not in liste:
                liste.append(str(p))
        self.accept()
        self.bereich.oeffnen(gewaehlt[0])


# ================================================================ Dialog: neu / Eigenschaften
class WoerterbuchDialog(QDialog):
    def __init__(self, bereich, neu):
        app = bereich.app
        super().__init__(app)
        self.bereich, self.app, self.neu = bereich, app, neu
        wb = None if neu else bereich.wb
        p = wb.profil() if wb else {}
        self.setWindowTitle(_("New dictionary") if neu else _("Properties: {name}").format(name=wb.titel()))
        self.setMinimumWidth(760)
        lay = QVBoxLayout(self)
        g = QGridLayout()
        g.setColumnStretch(1, 1)
        g.setVerticalSpacing(2)
        lay.addLayout(g)
        self.f = {}
        self.wiki_zeilen = []
        self.art = wb.art if wb else "wiki"
        self._r = 0
        if neu:
            g.addWidget(QLabel(_("Type:")), self._r, 0, Qt.AlignTop)
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            self.arten = QButtonGroup(self)
            for wert, text in (("wiki", _("build from a wiki (MediaWiki, e.g. a Fandom wiki)")),
                               ("leer", _("empty, own entries only (collect names from books, Claude, by hand)"))):
                r = QRadioButton(text)
                r.setChecked(wert == self.art)
                r.toggled.connect(lambda an, w=wert: an and self._art(w))
                self.arten.addButton(r)
                bl.addWidget(r)
            g.addWidget(box, self._r, 1, 1, 2)
            self._r += 1
            self._feld(g, "ordner", _("Working folder:"), _("Bookbench creates the database here (new, empty folder)."),
                       "", knopf=self._ordner)
        else:
            h = QLabel(f"{_(ART_TEXT[wb.art])}: {wb.pfad}")
            h.setProperty("rolle", "hinweis")
            g.addWidget(h, self._r, 0, 1, 3)
            self._r += 1
        self._feld(g, "name", _("Name in KOReader:"), _("Shown in KOReader's dictionary list."), p.get("name"))
        if neu or wb.art != "stardict":
            self._feld(g, "stem", _("File name:"), _("Name of the dictionary files (without extension), e.g. "
                                                    "sw-legends."), p.get("stem"))
        self._feld(g, "topic", _("Topic:"), _("For Claude: what it is about, e.g. \"Star Wars Legends\" or \"Brandon "
                                             "Sanderson's Cosmere\". English is most precise."), p.get("topic"))
        if neu or wb.art == "wiki":
            self.wiki_zeilen += self._feld(g, "wiki", "Wiki:", _(
                "Base address of a MediaWiki, e.g. https://starwars.fandom.com or https://coppermind.net"), p.get("wiki"))
            self.wiki_zeilen += self._feld(g, "check_site", _("Cross-check:"), _(
                "Optional: page prefix of a second source where Claude checks the entries, e.g. "
                "https://example.org/wiki/ (empty = no cross-check)"), p.get("check_site"))
        self._feld(g, "buecher", _("Books:"), _("Parts of title, series or author, separated by commas. Only words "
                                                "looked up in these books count as missing (in addition to the "
                                                "searched books). Empty = all."), ", ".join(p.get("buecher") or []))
        g.addWidget(QLabel(_("Spoilers (Claude):")), self._r, 0)
        box = QWidget()
        bl = QHBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        self.spoiler = QButtonGroup(self)
        for wert, text in SPOILER:
            r = QRadioButton(_(text))
            r.setProperty("wert", wert)
            r.setChecked(wert == (p.get("spoilers") or "mild"))
            self.spoiler.addButton(r)
            bl.addWidget(r)
        bl.addStretch(1)
        g.addWidget(box, self._r, 1, 1, 2)
        self._r += 1
        if wb is not None and wb.art in ("wiki", "leer"):
            k = QPushButton(_("Take changes from a StarDict folder …"))
            k.clicked.connect(lambda: (self.reject(), bereich.aus_stardict_uebernehmen()))
            g.addWidget(k, self._r, 1, Qt.AlignLeft)
            self._r += 1
        z = QHBoxLayout()
        z.addStretch(1)
        ok = QPushButton(_("Create") if neu else _("OK"))
        ok.setDefault(True)
        ok.clicked.connect(self.ok)
        z.addWidget(ok)
        ab = QPushButton(_("Cancel"))
        ab.clicked.connect(self.reject)
        z.addWidget(ab)
        lay.addSpacing(10)
        lay.addLayout(z)
        self._art(self.art)

    def _feld(self, g, schl, text, hinweis, wert, knopf=None):
        lab = QLabel(text)
        g.addWidget(lab, self._r, 0)
        ein = QLineEdit(str(wert or ""))
        g.addWidget(ein, self._r, 1)
        self.f[schl] = ein
        teile = [lab, ein]
        if knopf:
            k = QPushButton(_("Choose …"))
            k.clicked.connect(knopf)
            g.addWidget(k, self._r, 2)
            teile.append(k)
        h = QLabel(hinweis)
        h.setProperty("rolle", "hinweis")
        h.setWordWrap(True)
        g.addWidget(h, self._r + 1, 1, 1, 2)
        teile.append(h)
        self._r += 2
        return teile

    def _art(self, art):
        self.art = art
        for w in self.wiki_zeilen:
            w.setVisible(art == "wiki")
        self.adjustSize()

    def _ordner(self):
        o = dialogs.ordner(self, _("Working folder for the new dictionary"))
        if o:
            self.f["ordner"].setText(o)
            if not self.f["stem"].text():
                self.f["stem"].setText(Path(o).name.lower().replace(" ", "-"))

    def werte(self):
        w = {k: f.text().strip() for k, f in self.f.items()}
        b = self.spoiler.checkedButton()
        w["spoilers"] = b.property("wert") if b else "mild"
        return w

    def ok(self):
        werte = self.werte()
        profil = {"name": werte["name"], "topic": werte["topic"], "spoilers": werte["spoilers"],
                  "buecher": [b.strip() for b in werte["buecher"].split(",") if b.strip()]}
        if werte.get("stem"):
            profil["stem"] = werte["stem"]
        if self.art == "wiki":
            profil["wiki"] = werte.get("wiki", "").rstrip("/")
            profil["check_site"] = werte.get("check_site", "")
        if self.neu:
            if not werte["ordner"]:
                dialogs.fehler(self, _("New dictionary"), _("Please choose a working folder."))
                return
            if not werte["name"] or not werte["topic"] or (self.art == "wiki" and not werte.get("wiki")):
                dialogs.fehler(self, _("New dictionary"), _("Name, topic and wiki are required.") if self.art == "wiki"
                               else _("Name and topic are required."))
                return
            try:
                wb = kwb.anlegen(werte["ordner"], self.art, profil)
            except Exception as e:
                dialogs.fehler(self, _("New dictionary"), str(e))
                return
            wb.schliessen()
            self.accept()
            self.bereich.ansicht = SCHRITTE
            self.bereich.oeffnen(werte["ordner"])
            return
        wb = self.bereich.wb
        if wb.art == "stardict":
            profil.pop("stem", None)
        wb.profil_setzen(profil)
        self.accept()
        self.bereich.wahl_fuellen()
        self.bereich.liste_fuellen()
        self.app.status.set(_("Properties saved; name and file name apply at the next build.") if wb.art != "stardict"
                            else _("Properties saved."))
