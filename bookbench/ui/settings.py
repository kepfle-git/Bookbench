# -*- coding: utf-8 -*-
"""
settings.py - Einstellungsdialog (Qt). Laden, Speichern und Standardwerte: core/settings.py.

  EinstellungsDialog(app, seite)   Baum links (Gruppen mit Unterseiten), Seite rechts (scrollbar),
                                   unter jedem Feld ein Hinweis; OK übernimmt alles auf einmal
  ProfilDialog(eltern, profil)     ein Quellprofil für Klappentexte bearbeiten (.ergebnis)

Neue Einstellung: Schlüssel in core/settings.STANDARD, bei einfachem Wert in EINFACH, Eingabe auf der
passenden Seite (_seite_<kennung>, Bausteine aus ui/forms.py), Hilfethema einst_<seite>.
"""
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea,
                               QSpinBox, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from bookbench import i18n as ks
from bookbench.core import blurbs
from bookbench.core import markers as kmk
from bookbench.core.settings import MODELLE, STANDARD, klappentext_profile, ordner_zeigen, pfad
from bookbench.device import models as km
from bookbench.i18n import N_, _, ngettext
from bookbench.ui import dialogs
from bookbench.ui import markers as mk
from bookbench.ui import threads
from bookbench.ui.forms import EINZUG, Formular, Werte, label


# Seiten bis 2.0 -> heutige Seite (Aufrufe, Hilfeverweise)
ALT = {"klappentexte_claude": "online", "calibre": "metadaten"}


class EinstellungsDialog(QDialog):
    """Baum links (Gruppen mit Unterseiten), Seite rechts (scrollbar), unter jedem Feld ein Hinweis.
    Seiten mit Unterseiten haben eigenen Inhalt; reine Gruppen zeigen eine Übersicht ihrer Seiten."""
    # (Kennung, Elternseite, Titel, Kurzbeschreibung für die Übersicht)
    SEITEN = (
        ("allgemein", "", N_("General"), N_("Language, look, start, updates")),
        ("darstellung", "allgemein", N_("Language and theme"), N_("Language of the interface, light or dark")),
        ("oberflaeche", "allgemein", N_("Interface"), N_("Status strip, tooltips, covers in the headers, sidebar")),
        ("marken", "oberflaeche", N_("Status symbols"), N_("Which symbols are shown where")),
        ("start", "allgemein", N_("Startup"), N_("What opens when the program starts")),
        ("updates", "allgemein", N_("Updates"), N_("Checking for new versions")),
        ("speichern", "", N_("Saving and backups"), N_("Backup folder, backups of books and of the KOReader settings")),
        ("buecher", "", N_("Books"), N_("Library and import, chapters, blurbs, covers and metadata")),
        ("bibliothek", "buecher", N_("Library and import"), N_("Folder scheme for new books, reading cache")),
        ("kapitel", "buecher", N_("Chapters"), N_("How chapter names are taken from the book text")),
        ("klappentexte", "buecher", N_("Blurbs"), N_("Order of the sources, free sources, checks")),
        ("klappentexte_profile", "klappentexte", N_("Source profiles"),
         N_("Where Claude looks, per publisher, series or author")),
        ("cover", "buecher", N_("Covers"), N_("Inserting and marking covers")),
        ("cover_nachschlagen", "cover", N_("Looking up covers"), N_("Sources and which images count")),
        ("metadaten", "buecher", N_("Metadata and Calibre"), N_("Own fields from Calibre columns, comparing with Calibre")),
        ("geraet", "", N_("Device"), N_("E-reader and preview")),
        ("kobo", "geraet", N_("E-reader"), N_("Detection, copying dictionaries, ejecting")),
        ("vorschau", "geraet", N_("Preview"), N_("Desktop KOReader and the device shown")),
        ("online", "", N_("Online services"), N_("Google Books key, Claude API: key, model, cost estimate")),
        ("erweitert", "", N_("Advanced"), N_("Files of the program, cache, export, reset")),
    )
    UEBERSICHT = {"allgemein", "buecher", "geraet"}          # nur Übersicht, keine eigenen Einstellungen
    # Einstellungen mit einfachem Wert; der Typ richtet sich nach STANDARD
    EINFACH = ("darstellung", "tooltips", "status_liste", "cover", "cover_kopf_hoehe", "tooltip_verzoegerung",
               "navi_ausgeklappt", "start_ordner", "start_bereich", "sicherungsordner", "sicherungen_anzahl",
               "max_sub", "caps", "api_key", "modell", "kt_kosten", "kostenlos", "google_key", "kt_min", "kt_max",
               "cover_max_hoehe", "cover_qualitaet", "cover_klein", "cover_openlibrary", "cover_google",
               "cover_min_hoehe", "cover_anzahl", "kobo_sicherungen_anzahl", "woerterbuch_quelle",
               "auswerfen_erinnern", "kobo_suche_sekunden", "kobo_oeffnen", "koreader_pfad", "update_pruefen",
               "update_vorab", "calibre_an", "buch_oeffnen", "ordnerschema", "einlese_cache")
    BEHALTEN = ("ordner", "letzte_ordner", "woerterbuecher", "woerterbuch_aktiv", "fenster", "api_key", "google_key",
                "sprache")

    def __init__(self, app, seite=None):
        super().__init__(app)
        self.app = app
        self.setWindowTitle(_("Settings"))
        self.resize(900, 620)
        self.setMinimumSize(700, 440)
        self.werte = Werte()
        self.bib_schema = None                             # Feld Ordnerschema der geöffneten Bibliothek (2.1)
        self.profile = klappentext_profile(app.e)
        self.meta_spalten = [list(x) for x in app.e.get("meta_spalten") or [] if isinstance(x, (list, tuple)) and x]
        aus = app.e.get("marken_aus") or {}
        self.marken = {}                                   # (ort, kennung) -> QCheckBox
        self._marken_aus = aus

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        mitte = QHBoxLayout()
        lay.addLayout(mitte, 1)
        self.baum = QTreeWidget()
        self.baum.setHeaderHidden(True)
        self.baum.setFixedWidth(240)
        mitte.addWidget(self.baum)
        self.stapel = QStackedWidget()
        mitte.addWidget(self.stapel, 1)
        unten = QHBoxLayout()
        k = QPushButton(_("Help"))
        k.clicked.connect(self.hilfe)
        unten.addWidget(k)
        unten.addStretch(1)
        self.ok_knopf = QPushButton("OK")
        self.ok_knopf.setDefault(True)
        self.ok_knopf.clicked.connect(self.ok)
        unten.addWidget(self.ok_knopf)
        k = QPushButton(_("Cancel"))
        k.clicked.connect(self.reject)
        unten.addWidget(k)
        lay.addLayout(unten)

        self.eintraege, self.seiten = {}, {}
        for name, eltern, titel, __ in self.SEITEN:
            if name == "vorschau" and sys.platform.startswith("win"):
                continue                               # keine Vorschau unter Windows
            it = QTreeWidgetItem(self.eintraege.get(eltern) or self.baum, [_(titel)])
            it.setData(0, Qt.UserRole, name)
            self.eintraege[name] = it
            f = Formular(self.werte)
            if name in self.UEBERSICHT:
                self._uebersicht(name, f)
            else:
                getattr(self, "_seite_" + name)(f)
            f.dehnen()
            rahmen = QScrollArea()
            rahmen.setWidget(f)
            rahmen.setWidgetResizable(True)
            rahmen.setFrameShape(QFrame.NoFrame)
            self.stapel.addWidget(rahmen)
            self.seiten[name] = rahmen
        self.baum.expandAll()
        self.baum.currentItemChanged.connect(lambda it, __: self._zeigen(it))
        start = ALT.get((seite or "darstellung").lower(), (seite or "darstellung").lower())
        self.gehe_zu(start if start in self.eintraege else "darstellung")
        QShortcut(QKeySequence("F1"), self, activated=self.hilfe)

    def _w(self, schl):
        return self.app.e.get(schl, STANDARD.get(schl))

    def _zeigen(self, it):
        if it is not None:
            self.stapel.setCurrentWidget(self.seiten[it.data(0, Qt.UserRole)])

    def seite(self):
        it = self.baum.currentItem()
        return it.data(0, Qt.UserRole) if it else "darstellung"

    def gehe_zu(self, name):
        if name in self.eintraege:
            self.baum.setCurrentItem(self.eintraege[name])

    def hilfe(self):
        self.app.hilfe_zeigen("einst_" + self.seite())

    def _uebersicht(self, name, f):
        titel = next(_(t) for k, __, t, __ in self.SEITEN if k == name)
        f.ueberschrift(titel)
        for k, eltern, t, beschreibung in self.SEITEN:
            if eltern != name or (k == "vorschau" and sys.platform.startswith("win")):
                continue
            verweis = label(_(t), "verweis")
            verweis.setCursor(Qt.PointingHandCursor)
            verweis.mousePressEvent = lambda ev, k=k: self.gehe_zu(k)
            f.lay.addWidget(verweis)
            f.hinweis(_(beschreibung))

    @staticmethod
    def _liste(spalten, hoehe=7):
        t = QTreeWidget()
        t.setColumnCount(len(spalten))
        t.setHeaderLabels(spalten)
        t.setRootIsDecorated(False)
        t.setUniformRowHeights(True)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setFixedHeight(28 + hoehe * 22)
        return t

    def _knopfspalte(self, knoepfe):
        spalte = QVBoxLayout()
        spalte.setSpacing(2)
        for text, fn in knoepfe:
            k = QPushButton(text)
            k.setMinimumWidth(130)
            k.clicked.connect(fn)
            spalte.addWidget(k)
        spalte.addStretch(1)
        return spalte

    # -- Sprache ------------------------------------------------------------------
    @staticmethod
    def _sprachen():
        """[(Code, Anzeigename)]; die Sprachen stehen in ihrer eigenen Sprache da."""
        return [("auto", _("Automatic (system language)"))] + list(ks.SPRACHEN.items())

    # -- Allgemein -------------------------------------------------------------------
    def _seite_darstellung(self, f):
        f.ueberschrift(_("Language and theme"))
        f.abschnitt(_("Language"))
        self.sprachwahl = QComboBox()
        for code, name in self._sprachen():
            self.sprachwahl.addItem(name, code)
        i = self.sprachwahl.findData(self.app.e.get("sprache") or "auto")
        self.sprachwahl.setCurrentIndex(max(0, i))
        z = f.zeile()
        z.addWidget(self.sprachwahl)
        z.addStretch(1)
        f.hinweis(_("Automatic: German if the system language is German, otherwise English. The change applies "
                    "at once; folder, area, selected book and unsaved changes stay as they are."))
        f.abschnitt(_("Theme"))
        f.auswahl("darstellung", (("hell", _("Light")), ("dunkel", _("Dark")), ("system", _("Like the system"))),
                  _("Like the system: the style and colours of your desktop (on KDE with the system's PySide6: "
                    "Breeze), checked at start. Light and dark use the colours of the Keller design guide."),
                  wert=self._w("darstellung"))

    def _seite_oberflaeche(self, f):
        f.ueberschrift(_("Interface"))
        f.abschnitt(_("Lists"))
        f.schalter("status_liste", _("Status strip next to the lists"),
                   _("Coloured dots (changed, applied, saved) and ⚠ to the right of the book lists."),
                   self._w("status_liste"))
        f.abschnitt(_("Tooltips"))
        an = f.schalter("tooltips", _("Show tooltips"), _("Explanations when the mouse stays over a button."),
                        self._w("tooltips"))
        f.unter(an).zahl("tooltip_verzoegerung", _("Delay (ms):"),
               _("How long the mouse has to stay still before the explanation appears."),
               self._w("tooltip_verzoegerung"), 0, 3000, 100)
        f.abschnitt(_("Covers in the headers"))
        an = f.schalter("cover", _("Show cover in Chapters"),
                        _("Small cover next to the book title; a click shows it large."), self._w("cover"))
        f.unter(an).zahl("cover_kopf_hoehe", _("Height (px):"), _("Default 96."), self._w("cover_kopf_hoehe"), 40, 300, 8)
        f.abschnitt(_("Library"))
        f.text(_("Double-click on a book opens it in:"))
        f.auswahl("buch_oeffnen", [(k, _(t)) for k, t in self.app.oeffnen_ziele()],
                  _("Right-click on a book offers all of them. KOReader: selects the book in the Preview and "
                    "starts the desktop KOReader with it."), wert=self._w("buch_oeffnen"))
        f.abschnitt(_("Sidebar"))
        f.schalter("navi_ausgeklappt", _("Sidebar expanded"),
                   _("With names and counters; collapsed only the symbols. Ctrl+B switches at any time."),
                   self.app.leiste.ausgeklappt)

    def _seite_marken(self, f):
        f.ueberschrift(_("Status symbols"))
        f.hinweis(_("The small symbols next to the books and in the sidebar (no cover, no blurb, questionable "
                    "chapter names …). Switched off, a symbol is only hidden: filters and sorting by status "
                    "still count it."))
        g = QGridLayout()
        g.setContentsMargins(EINZUG, 0, 0, 6)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(1)
        for spalte, (__, titel) in enumerate(kmk.ORTE):
            lab = label(_(titel), "abschnitt", umbruch=True)
            lab.setAlignment(Qt.AlignCenter | Qt.AlignBottom)
            lab.setMaximumWidth(100)
            g.addWidget(lab, 0, spalte, Qt.AlignBottom | Qt.AlignHCenter)
        n = len(kmk.ORTE)
        for zeile, k in enumerate(kmk.ORDNUNG, 1):
            for spalte, (ort, __) in enumerate(kmk.ORTE):
                if ort != "seitenleiste" and k in kmk.NUR_SEITENLEISTE:
                    continue
                cb = QCheckBox()
                cb.setChecked(k not in (self._marken_aus.get(ort) or []))
                self.marken[(ort, k)] = cb
                g.addWidget(cb, zeile, spalte, Qt.AlignCenter)
            bild = QLabel()
            bild.setPixmap(mk.bild(k))
            g.addWidget(bild, zeile, n)
            g.addWidget(label(_(kmk.NAMEN[k])), zeile, n + 1)
        g.setColumnStretch(n + 2, 1)
        f.lay.addLayout(g)
        z = f.zeile()
        f.knopf(_("All on"), lambda: self._marken_alle(True), z)
        f.knopf(_("All off"), lambda: self._marken_alle(False), z)
        z.addStretch(1)
        f.hinweis(_("Book lists: the narrow lists in Chapters and Metadata. Library: the Status column of the "
                    "library. The coloured dot for changed, applied and saved stays; the whole strip can be "
                    "switched off under Interface."))

    def _marken_alle(self, an):
        for cb in self.marken.values():
            cb.setChecked(an)

    def _seite_start(self, f):
        f.ueberschrift(_("Startup"))
        f.schalter("start_ordner", _("Open the last folder"),
                   _("The books folder that was open when the program was last closed, if it still exists "
                     "(e.g. the e-reader is connected). Otherwise the program starts empty."), self._w("start_ordner"))
        f.abschnitt(_("Area at start"))
        f.auswahl("start_bereich", (("bibliothek", _("Library")), ("zuletzt", _("The last area used"))),
                  wert=self._w("start_bereich"))

    def _seite_updates(self, f):
        from bookbench.core import updater as ku
        f.ueberschrift(_("Updates"))
        art = ku.installationsart()
        f.abschnitt(_("This copy"))
        f.hinweis({"windows": _("Installed with the Windows setup: updates are installed by the setup."),
                   "linux": _("Installed with install.sh: updates replace the program folder {ordner}.").format(
                       ordner=ku.PROGRAMM),
                   }.get(art, _("Runs from the source code ({ordner}), e.g. a git clone: updates are only shown, "
                                "not installed, and there is no automatic check.").format(ordner=ku.PROGRAMM)))
        z = f.zeile()
        f.knopf(_("Check now"), self._update_jetzt, z)
        zuletzt = (self.app.e.get("update_zuletzt") or "").replace("T", " ")[:16]
        z.addWidget(label(_("Last check: {wann}").format(wann=zuletzt or _("never")), "hinweis"))
        z.addStretch(1)
        f.lay.addSpacing(8)
        f.abschnitt(_("Automatic check"))
        f.auswahl("update_pruefen", (("aus", _("Off")), ("start", _("At every start")),
                                     ("taeglich", _("At start, at most once a day")),
                                     ("woechentlich", _("At start, at most once a week"))),
                  _("Looks a few seconds after the start whether GitHub has a newer release. Only a new "
                    "version shows a window; errors (no network) only appear in the status line."),
                  wert=self._w("update_pruefen"))
        ausgelassen = self.app.e.get("update_ausgelassen")
        if ausgelassen:
            u = f.unter(bedingung=lambda: bool(self.app.e.get("update_ausgelassen")))
            z = u.zeile()
            z.addWidget(label(_("Skipped version: {version}").format(version=ausgelassen)))

            def wieder():
                self.app.e["update_ausgelassen"] = ""
                u.pruefen()
            u.knopf(_("Show again"), wieder, z)
            z.addStretch(1)
            u.lay.addSpacing(8)
        f.schalter("update_vorab", _("Include pre-releases"),
                   _("Also offers releases marked as pre-release on GitHub (test versions)."), self._w("update_vorab"))
        f.hinweis(_("The releases come from github.com/{repo}.").format(repo=ku.REPO))

    def _update_jetzt(self):
        e = dict(self.app.e)
        e["update_vorab"] = self.werte.lesen("update_vorab", e.get("update_vorab"))
        self.app.updates.pruefen(von_hand=True, einstellungen=e)

    # -- Speichern ---------------------------------------------------------------------
    def _seite_speichern(self, f):
        f.ueberschrift(_("Saving and backups"))
        self.sicherung_feld = f.feld(
            "sicherungsordner", _("Backup folder"),
            _("Before each save the book is copied here (name with date and time). Do not put it on the e-reader, "
              "or KOReader shows the backups as books. The KOReader backups of the E-reader area go into its "
              "subfolder KOReader, dictionaries into Wörterbücher."), self._w("sicherungsordner"), 46,
            knopf=(_("Choose …"), lambda: self._ordner_waehlen("sicherungsordner")))
        f.zahl("sicherungen_anzahl", _("Backups per book:"),
               _("The newest ones are kept, older ones are deleted when saving."), self._w("sicherungen_anzahl"), 1, 50)
        f.zahl("kobo_sicherungen_anzahl", _("Backups of the KOReader settings:"),
               _("Backups made in the E-reader area. This many stay in the KOReader subfolder of the backup "
                 "folder; older ones are deleted. This includes the backup made before each restore."),
               self._w("kobo_sicherungen_anzahl"), 1, 100)

    # -- Bücher --------------------------------------------------------------------------
    # -- Bibliothek und Import (seit 2.1) ------------------------------------------------
    def _bibliothek_auf_rechner(self):
        from bookbench.device import device as kg
        o = self.app.ordner
        return bool(o) and not kg.ist_geraet(o)

    def _seite_bibliothek(self, f):
        from bookbench.core import folder_scheme as fs
        from bookbench.ui import import_window as kiw
        f.ueberschrift(_("Library and import"))
        f.abschnitt(_("Folder scheme"))
        f.text(_("Where Add books puts new books, relative to the library folder. Placeholders: {title}, {authors}, "
                 "{author} (first author), {author_sort}, {series}, {series_index}, {publisher}, {language}, "
                 "{isbn}. {series_index:2} fills up with zeros (3 → 03). A part in [square brackets] is left out "
                 "when a placeholder in it is empty, e.g. [{series}/] for books without a series. The file "
                 "extension stays that of the book."))
        self.bib_schema = None
        if self._bibliothek_auf_rechner():
            vorlage, herkunft = kiw.schema_fuer(self.app)
            self.bib_schema = f.feld("bib_schema", _("This library ({ordner}):").format(ordner=self.app.ordner),
                                     None, vorlage, 34, knopf=(_("Detect from the books"), self._schema_erkennen))
            self._bib_herkunft = herkunft
            self.bib_beispiel = f.hinweis("")
            self.bib_schema.textChanged.connect(self._schema_beispiel)
            self._schema_beispiel()
            f.hinweis(_("Saved in the library folder (.bookbench/library.json), so it travels with the folder, "
                        "e.g. in a synced folder used on Windows and Linux. Books already in the library are never "
                        "moved or renamed: KOReader keeps reading positions and highlights next to the file name."))
        else:
            f.hinweis(_("Open a library on this computer to set its own scheme. A library opened directly on the "
                        "e-reader uses the scheme detected from its books."))
        f.feld("ordnerschema", _("Default for new libraries:"),
               _("Used when a library has no scheme of its own and none can be detected from its books."),
               self._w("ordnerschema"), 34,
               knopf=(_("Reset to Calibre-like default"), lambda: self.werte.setzen("ordnerschema", fs.STANDARD)))
        f.abschnitt(_("Reading cache"))
        f.schalter("einlese_cache", _("Remember read books (faster opening)"),
                   _("Bookbench remembers what it read from each book and only reads changed files again. "
                     "Stored in the settings folder, per library. Switch off if something looks out of date."),
                   self._w("einlese_cache"))
        z = f.zeile()
        f.knopf(_("Empty reading cache"), self._einlese_cache_leeren, z)
        z.addStretch(1)

    def _schema_erkennen(self):
        from bookbench.core import folder_scheme as fs
        v, n, gesamt = fs.erkennen(self.app.buecher, self.app.ordner)
        if n:
            self._bib_herkunft = _("detected: {n} of {gesamt} books are stored like this").format(n=n, gesamt=gesamt)
            self.bib_schema.setText(v)
        else:
            self._bib_herkunft = _("No common scheme found in the books of this library.")
        self._schema_beispiel()

    def _schema_beispiel(self):
        from bookbench.core import folder_scheme as fs
        v = self.bib_schema.text().strip()
        fehler = fs.pruefen(v)
        if fehler:
            texte = {"empty": _("The scheme is empty."), "brackets": _("Square brackets do not match."),
                     "no-field-in-name": _("The file name (after the last /) needs at least one placeholder.")}
            t = texte.get(fehler) or _("Unknown placeholder: {name}").format(name=fehler.split(":", 1)[-1])
            self.bib_beispiel.setText("⚠ " + t)
            return
        self.bib_beispiel.setText(self._bib_herkunft + self._beispiel_text(v))

    def _beispiel_text(self, v):
        from bookbench.core import folder_scheme as fs
        b = next((x for x in self.app.buecher if not x.fehler and x.reihe), None) or \
            next((x for x in self.app.buecher if not x.fehler), None)
        return "\n" + _("Example: {pfad}").format(pfad=fs.ziel(v, b)) if b is not None else ""

    def _einlese_cache_leeren(self):
        from bookbench.core import scan_cache
        scan_cache.leeren()
        self.app.status.set(_("Reading cache emptied; the next opening reads all books again."))

    def _seite_kapitel(self, f):
        f.ueberschrift(_("Chapters"))
        f.zahl("max_sub", _("Subtitle lines per chapter:"),
               _("1: only the first line below the number. Some books have three; with 3 all of them are "
                 "joined with \" / \". Applies after reloading (F5)."), self._w("max_sub"), 1, 5)
        f.schalter("caps", _("Write entries in capitals normally"),
                   _("THE SHIRE becomes The Shire, A LONG-EXPECTED PARTY becomes A Long-Expected Party. "
                     "Applies after reloading (F5)."), self._w("caps"))

    def _seite_klappentexte(self, f):
        f.ueberschrift(_("Blurbs"))
        f.hinweis(_("Order when looking up: the EPUB itself, Calibre (From Calibre), the free sources, "
                    "then Claude with the matching source profile."), einzug=0)
        f.abschnitt(_("Free sources"))
        f.schalter("kostenlos", _("Ask Google Books and Open Library first"),
                   _("No cost. Claude is only asked if they have nothing. Switched off, every look-up "
                     "goes to Claude."), self._w("kostenlos"))
        f.hinweis(_("An own Google Books key (Online services) avoids the shared daily quota."))
        f.abschnitt(_("Checks"))
        f.zahl("kt_min", _("Shortest blurb (characters):"),
               _("Shorter texts from a source are not taken (often only a teaser line)."), self._w("kt_min"), 0, 2000, 10)
        f.zahl("kt_max", _("Longest blurb (characters):"),
               _("Longer texts are not taken (usually a plot summary or a whole article)."),
               self._w("kt_max"), 200, 20000, 100)

    def _seite_klappentexte_profile(self, f):
        f.ueberschrift(_("Source profiles"))
        f.hinweis(_("A profile says where Claude looks for a blurb. The first active profile that fits the "
                    "book is used; order with Up/Down. Double-click edits."), einzug=0)
        z = f.zeile()
        self.profil_liste = self._liste([_("Profile"), _("Applies to")])
        self.profil_liste.itemDoubleClicked.connect(lambda *a: self._profil_bearbeiten())
        z.addWidget(self.profil_liste, 1)
        z.addLayout(self._knopfspalte(((_("New …"), self._profil_neu), (_("Edit …"), self._profil_bearbeiten),
                                       (_("Delete"), self._profil_loeschen), (_("Up"), lambda: self._profil_schieben(-1)),
                                       (_("Down"), lambda: self._profil_schieben(1)),
                                       (_("Defaults"), self._profile_standard))))
        f.hinweis(_("Defaults puts the included profiles (Lexicanum, web search) back; your own profiles "
                    "are removed."))
        self._profile_zeigen()

    def _seite_online(self, f):
        f.ueberschrift(_("Online services"))
        f.hinweis(_("Keys for the services Bookbench asks on the internet. Both are stored in plain text in the "
                    "settings file (also when exporting it). What is sent where: Help > Costs and privacy."),
                  einzug=0)
        f.abschnitt("Google Books")
        f.feld("google_key", _("Own Google Books API key (optional)"),
               _("For looking up blurbs and covers. Without a key, Google Books often answers \"quota exceeded\": "
                 "everyone without a key shares one daily quota. With your own key (free, Google Cloud Console: "
                 "enable the Books API, then create an API key) you get your own quota."),
               self._w("google_key"), 46, verdeckt=True)
        f.abschnitt(_("Claude API"))
        schl = f.feld("api_key", _("API key"),
                      _("From console.anthropic.com; for blurbs from source profiles and for dictionary entries. "
                        "Empty: environment variable ANTHROPIC_API_KEY."), self._w("api_key"), 46, verdeckt=True)
        u = f.unter(bedingung=lambda: bool(schl.text().strip() or os.environ.get("ANTHROPIC_API_KEY")))
        schl.textChanged.connect(lambda *a: u.pruefen())
        f = u                                              # Modell und Kosten erst mit Schlüssel
        f.text(_("Model"))
        z = f.zeile()
        self.modell_wahl = QComboBox()
        self.modell_wahl.setEditable(True)
        self.modell_wahl.setMinimumWidth(260)
        werte = list(MODELLE)
        if self._w("modell") and self._w("modell") not in werte:
            werte.insert(0, self._w("modell"))
        self.modell_wahl.addItems(werte)
        self.modell_wahl.setCurrentText(self._w("modell") or MODELLE[0])
        self.werte.eintragen("modell", lambda: self.modell_wahl.currentText().strip(), self.modell_wahl.setCurrentText)
        z.addWidget(self.modell_wahl)
        f.knopf(_("Load list"), self._modelle_laden, z)
        z.addStretch(1)
        self.modell_hinweis = f.hinweis(_("Haiku is enough for looking things up and is the cheapest. Load list "
                                          "asks Anthropic with the API key which models there are; typing a name "
                                          "also works."))
        f.zahl("kt_kosten", _("Estimated cost per book ($):"),
               _("Only for the question before \"Look up all\"; the real cost depends on page length and "
                 "searches."), self._w("kt_kosten"), 0, 1, 0.005, nachkomma=3)

    def _modelle_laden(self):
        """Modelle über die API abfragen (models.list), im Hilfsthread."""
        schluessel = self.werte.lesen("api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        if not schluessel:
            self.modell_hinweis.setText(_("Enter the API key first."))
            return
        self.modell_hinweis.setText(_("Asking Anthropic …"))
        offen = [True]
        self.destroyed.connect(lambda: offen.__setitem__(0, False))

        def lauf():
            try:
                import anthropic
                namen = [m.id for m in anthropic.Anthropic(api_key=schluessel).models.list(limit=100)]
                fehler = None if namen else _("Anthropic returned no models.")
            except ImportError:
                namen, fehler = [], _("The package anthropic is missing (pip install anthropic).")
            except Exception as e:                     # Netz, falscher Schlüssel
                namen, fehler = [], _("Could not load the models ({fehler}).").format(fehler=e)
            threads.im_hauptthread(lambda: self._modelle_geladen(namen, fehler) if offen[0] else None)
        threads.starten(lauf)

    def _modelle_geladen(self, namen, fehler):
        if fehler:
            self.modell_hinweis.setText(fehler)
            return
        aktuell = self.modell_wahl.currentText()
        self.modell_wahl.clear()
        self.modell_wahl.addItems(namen)
        self.modell_wahl.setCurrentText(aktuell)
        self.modell_hinweis.setText(ngettext("{n} model loaded; the list is newest first.",
                                             "{n} models loaded; the list is newest first.",
                                             len(namen)).format(n=len(namen)))

    # -- Quellprofile --------------------------------------------------------------
    def _profile_standard(self):
        self.profile = klappentext_profile({"websuche": True})
        self._profile_zeigen(0)

    def _gilt_text(self, p):
        teile = [x for x in (p.get("verlag"), p.get("reihe"), p.get("autor")) if (x or "").strip()]
        text = " / ".join(teile) if teile else _("all books")
        return text if p.get("aktiv", True) else _("(off) {text}").format(text=text)

    def _profile_zeigen(self, auswahl=None):
        t = self.profil_liste
        t.clear()
        for p in self.profile:
            QTreeWidgetItem(t, [p.get("name") or "?", self._gilt_text(p)])
        t.resizeColumnToContents(0)
        if auswahl is not None and 0 <= auswahl < len(self.profile):
            t.setCurrentItem(t.topLevelItem(auswahl))

    def _profil_index(self):
        it = self.profil_liste.currentItem()
        return self.profil_liste.indexOfTopLevelItem(it) if it else None

    def _profil_neu(self):
        p = ProfilDialog(self, dict(blurbs.LEERES_PROFIL, name=_("New profile"))).ausfuehren()
        if p:
            self.profile.insert(0, p)                # vorne: sonst greift das allgemeine Profil zuerst
            self._profile_zeigen(0)

    def _profil_bearbeiten(self):
        i = self._profil_index()
        if i is None:
            return
        p = ProfilDialog(self, self.profile[i]).ausfuehren()
        if p:
            self.profile[i] = p
            self._profile_zeigen(i)

    def _profil_loeschen(self):
        i = self._profil_index()
        if i is None:
            return
        del self.profile[i]
        self._profile_zeigen(min(i, len(self.profile) - 1))

    def _profil_schieben(self, d):
        i = self._profil_index()
        if i is None or not 0 <= i + d < len(self.profile):
            return
        self.profile[i], self.profile[i + d] = self.profile[i + d], self.profile[i]
        self._profile_zeigen(i + d)

    def _seite_cover(self, f):
        f.ueberschrift(_("Covers"))
        f.abschnitt(_("Inserting a new cover"))
        f.zahl("cover_max_hoehe", _("Shrink to at most this height (px):"),
               _("0: never shrink. Your e-reader shows at most its screen height (e.g. 1680 px); larger "
                 "images only make the file bigger. Images are never enlarged."), self._w("cover_max_hoehe"), 0, 6000, 10)
        f.zahl("cover_qualitaet", _("JPEG quality:"),
               _("Only when an image is converted or shrunk; otherwise it is taken unchanged. The new cover "
                 "keeps the format of the old one (JPEG stays JPEG)."), self._w("cover_qualitaet"), 50, 100)
        f.abschnitt(_("Marking"))
        f.zahl("cover_klein", _("Mark covers below this height (px):"),
               _("Shown with ⚠ in the Metadata area and in the filter \"Small cover\". 0: never."),
               self._w("cover_klein"), 0, 6000, 10)

    def _seite_cover_nachschlagen(self, f):
        f.ueberschrift(_("Looking up covers"))
        f.abschnitt(_("Sources"))
        f.schalter("cover_openlibrary", _("Open Library"), _("Free, no key. Often large scans of the "
                                                             "cover, sometimes of another edition."),
                   self._w("cover_openlibrary"))
        f.schalter("cover_google", _("Google Books"), _("Free. Usually smaller images. Uses your own Google Books key "
                                                        "if there is one (Online services)."), self._w("cover_google"))
        f.abschnitt(_("Which images count"))
        f.zahl("cover_min_hoehe", _("Smallest height (px):"),
               _("Smaller images are left out (preview thumbnails)."), self._w("cover_min_hoehe"), 50, 2000, 10)
        f.zahl("cover_anzahl", _("At most this many to choose from:"),
               _("Each image is downloaded, so more takes longer."), self._w("cover_anzahl"), 1, 30)

    def _seite_metadaten(self, f):
        f.ueberschrift(_("Metadata and Calibre"))
        f.abschnitt("Calibre")
        f.schalter("calibre_an", _("Compare with Calibre"),
                   _("Reads Calibre's metadata.calibre (on the e-reader or in the opened folder) and shows its "
                     "values: in the Metadata area for comparing, in Blurbs and the Library for taking over "
                     "series and blurbs. Switch it off if you do not use Calibre (any more); the Calibre buttons "
                     "then disappear. Switching on applies after reloading (F5)."), self._w("calibre_an"))
        f.abschnitt(_("Own fields"))
        f.hinweis(_("Extra fields in the Metadata area, one per Calibre column (Calibre: Preferences > Add your "
                    "own columns). Bookbench reads and writes them the way Calibre stores them in the book."))
        z = f.zeile()
        self.spalten_liste = self._liste([_("Lookup name"), _("Label")], 6)
        self.spalten_liste.currentItemChanged.connect(lambda *a: self._spalte_gewaehlt())
        z.addWidget(self.spalten_liste, 1)
        z.addLayout(self._knopfspalte(((_("Delete"), self._spalte_loeschen), (_("Up"), lambda: self._spalte_schieben(-1)),
                                       (_("Down"), lambda: self._spalte_schieben(1)),
                                       (_("From Calibre"), self._spalten_aus_calibre))))
        f.lay.addSpacing(6)
        z = f.zeile()
        z.addWidget(label(_("Lookup name:")))
        self.spalte_feld = QLineEdit("#")
        self.spalte_feld.setFixedWidth(110)
        z.addWidget(self.spalte_feld)
        z.addSpacing(8)
        z.addWidget(label(_("Label:")))
        self.spalte_name = QLineEdit()
        self.spalte_name.setFixedWidth(150)
        z.addWidget(self.spalte_name)
        f.knopf(_("Add / change"), self._spalte_setzen, z)
        z.addStretch(1)
        f.hinweis(_("Lookup name as in Calibre, with #, e.g. #subtitle; the label is what Bookbench shows. "
                    "From Calibre adds all own columns found in the metadata.calibre of the open folder. "
                    "Columns with several values (ampersand or comma separated) are shown joined with "
                    "\" & \" or \", \"."))
        self._spalten_zeigen()

    def _spalten_zeigen(self, waehlen=None):
        t = self.spalten_liste
        t.blockSignals(True)
        t.clear()
        for spalte, name in self.meta_spalten:
            QTreeWidgetItem(t, [spalte, name])
        t.blockSignals(False)
        if waehlen is not None and 0 <= waehlen < t.topLevelItemCount():
            t.setCurrentItem(t.topLevelItem(waehlen))

    def _spalte_index(self):
        it = self.spalten_liste.currentItem()
        return self.spalten_liste.indexOfTopLevelItem(it) if it else None

    def _spalte_gewaehlt(self):
        i = self._spalte_index()
        if i is not None:
            self.spalte_feld.setText(self.meta_spalten[i][0])
            self.spalte_name.setText(self.meta_spalten[i][1])

    def _spalte_setzen(self):
        spalte = self.spalte_feld.text().strip()
        if spalte and not spalte.startswith("#"):
            spalte = "#" + spalte
        if len(spalte) < 2:
            return
        name = self.spalte_name.text().strip() or spalte
        vorhanden = [i for i, (sp, __) in enumerate(self.meta_spalten) if sp == spalte]
        if vorhanden:
            self.meta_spalten[vorhanden[0]] = [spalte, name]
            i = vorhanden[0]
        else:
            self.meta_spalten.append([spalte, name])
            i = len(self.meta_spalten) - 1
        self._spalten_zeigen(i)

    def _spalte_loeschen(self):
        i = self._spalte_index()
        if i is not None:
            del self.meta_spalten[i]
            self._spalten_zeigen()

    def _spalte_schieben(self, richtung):
        i = self._spalte_index()
        if i is None or not 0 <= i + richtung < len(self.meta_spalten):
            return
        sp = self.meta_spalten
        sp[i], sp[i + richtung] = sp[i + richtung], sp[i]
        self._spalten_zeigen(i + richtung)

    def _spalten_aus_calibre(self):
        """Alle eigenen Spalten aus metadata.calibre des geöffneten Ordners dazunehmen (Bezeichnung aus Calibre)."""
        gefunden = {}
        for eintrag in getattr(self.app, "calibre_eintraege", None) or []:
            for k, fm in (eintrag.get("user_metadata") or {}).items():
                if k.startswith("#") and isinstance(fm, dict) and k not in gefunden:
                    gefunden[k] = fm.get("name") or k
        neu = [[k, n] for k, n in sorted(gefunden.items()) if k not in {sp for sp, __ in self.meta_spalten}]
        self.meta_spalten += neu
        self._spalten_zeigen()
        self.spalten_meldung = ngettext("{n} column added.", "{n} columns added.", len(neu)).format(n=len(neu)) \
            if gefunden else _("No own columns found (open a folder with metadata.calibre first).")
        dialogs.info(self, _("Settings"), self.spalten_meldung)

    # -- Gerät -------------------------------------------------------------------------
    def _seite_kobo(self, f):
        f.ueberschrift(_("E-reader"))
        f.abschnitt(_("Detection"))
        f.zahl("kobo_suche_sekunden", _("Look for the e-reader every (seconds):"),
               _("While Bookbench is open it checks this often whether an e-reader is connected or "
                 "unplugged."), self._w("kobo_suche_sekunden"), 1, 60)
        f.lay.addSpacing(4)
        f.text(_("When an e-reader is connected:"))
        f.auswahl("kobo_oeffnen", (
            ("auto", _("Open its books (ask if another folder is open)")),
            ("fragen", _("Always ask whether to open its books")),
            ("nie", _("Do nothing (open with Books in the E-reader area)"))), wert=self._w("kobo_oeffnen"))
        f.abschnitt(_("Copying dictionaries"))
        f.feld("woerterbuch_quelle", _("Copy dictionaries from (folder on the computer)"),
               _("Where Copy dictionary in the E-reader area takes them from: a dictionary folder (with an .ifo "
                 "file, e.g. My-Dictionary) or a folder with several of them. Also set by Choose source there."),
               self._w("woerterbuch_quelle"), 46, knopf=(_("Choose …"), lambda: self._ordner_waehlen("woerterbuch_quelle")))
        f.abschnitt(_("Ejecting"))
        f.schalter("auswerfen_erinnern", _("Remind me to eject when quitting"),
                   _("Only if something was written to the e-reader in this session."), self._w("auswerfen_erinnern"))

    def _seite_vorschau(self, f):
        f.ueberschrift(_("Preview"))
        f.feld("koreader_pfad", _("Desktop KOReader (optional)"),
               _("Empty: searched for (koreader in PATH, AppImage in ~/Applications or ~/Downloads, "
                 "Flatpak). Only fill in if it is somewhere else. flatpak: always the Flatpak "
                 "rocks.koreader.KOReader, even if KOReader is also installed normally."),
               self._w("koreader_pfad"), 46, knopf=(_("Choose …"), self._koreader_waehlen))
        f.text(_("Device shown"))
        self._geraete = [("auto", _("Automatic (device of the profile, otherwise the connected e-reader)"))] \
            + km.auswahl() + [("eigen", _("Own size"))]
        aktuell = self.app.e.get("vorschau_geraet") or "auto"
        if aktuell not in dict(self._geraete):           # z. B. 395: steht unter 391 in der Liste
            m = km.modell(aktuell)
            aktuell = next((nr for nr, __ in self._geraete if m and km.modell(nr) and
                            km.modell(nr)["name"] == m["name"]), "auto")
        self.geraet_wahl = QComboBox()
        self.geraet_wahl.setMaxVisibleItems(16)
        for nr, text in self._geraete:
            self.geraet_wahl.addItem(text, nr)
        self.geraet_wahl.setCurrentIndex(max(0, self.geraet_wahl.findData(aktuell)))
        self.geraet_wahl.currentIndexChanged.connect(lambda *a: self._eigen_zeigen())
        f.widget(self.geraet_wahl)
        f.hinweis(_("Size and pixel density of the window, and colour or black and white. Tolino devices "
                    "from 2024 on are Kobo hardware and are listed too."))
        w, h, dpi, farbe = (list(self.app.e.get("vorschau_eigen") or STANDARD["vorschau_eigen"]) + [False])[:4]
        self.eigen_rahmen = QWidget()
        el = QVBoxLayout(self.eigen_rahmen)
        el.setContentsMargins(EINZUG, 0, 0, 0)
        z = QHBoxLayout()
        self.eigen = {}
        for k, text, von, bis, wert in (("w", _("Width:"), 200, 4000, w), ("h", _("Height:"), 200, 4000, h),
                                        ("dpi", _("ppi:"), 100, 600, dpi)):
            z.addWidget(label(text))
            sp = QSpinBox()
            sp.setRange(von, bis)
            sp.setValue(int(wert))
            self.eigen[k] = sp
            z.addWidget(sp)
            z.addSpacing(10)
        z.addStretch(1)
        el.addLayout(z)
        self.eigen["farbe"] = QCheckBox(_("Colour screen"))
        self.eigen["farbe"].setChecked(bool(farbe))
        el.addWidget(self.eigen["farbe"])
        hinweis = label(_("Pixels in portrait format. For other e-readers with KOReader: see the maker's data sheet."),
                        "hinweis", umbruch=True)
        el.addWidget(hinweis)
        f.lay.addWidget(self.eigen_rahmen)
        self._eigen_zeigen()

    def _eigen_zeigen(self):
        self.eigen_rahmen.setVisible(self.geraet_wahl.currentData() == "eigen")

    # -- Erweitert -----------------------------------------------------------------------
    def _seite_erweitert(self, f):
        from bookbench.core import library as kd
        f.ueberschrift(_("Advanced"))
        f.abschnitt(_("Files of the program"))
        g = QGridLayout()
        g.setContentsMargins(EINZUG, 0, 0, 0)
        for zeile, (text, datei) in enumerate(((_("Settings"), Path(pfad())),
                                               (_("Chapter decisions"), Path(kd.ENTSCHEIDUNGEN)),
                                               (_("Blurb cache"), Path(kd.KLAPPENTEXT_CACHE)))):
            g.addWidget(label(text + ":"), zeile, 0, Qt.AlignTop)
            g.addWidget(label(str(datei), "hinweis", umbruch=True), zeile, 1)
        g.setColumnStretch(1, 1)
        f.lay.addLayout(g)
        z = f.zeile()
        f.knopf(_("Open settings folder"), lambda: ordner_zeigen(Path(pfad()).parent), z)
        z.addStretch(1)
        f.hinweis(_("The chapter decisions remember which names were applied, so they are suggested again "
                    "for other copies of the same book. The cache holds looked-up blurbs and what was "
                    "already tried, so looking up again costs nothing."))
        f.abschnitt(_("Blurb cache"))
        z = f.zeile()
        self.cache_text = label("")
        z.addWidget(self.cache_text)
        f.knopf(_("Empty …"), self._cache_leeren, z)
        z.addStretch(1)
        self._cache_zeigen()
        f.hinweis(_("Afterwards everything is looked up again (and Claude costs again)."))
        f.abschnitt(_("Export and import"))
        z = f.zeile()
        f.knopf(_("Export settings …"), self._exportieren, z)
        f.knopf(_("Import settings …"), self._importieren, z)
        z.addStretch(1)
        f.hinweis(_("A JSON file, e.g. to take the settings to another computer. It contains the API keys. "
                    "Importing replaces the current settings, the language included."))
        f.abschnitt(_("Reset"))
        f.knopf(_("Reset all settings …"), self._zuruecksetzen)
        f.hinweis(_("Everything back to the defaults. Kept: opened folders, the list of dictionaries, window "
                    "size, language and the API keys."))

    def _cache_zeigen(self):
        n = len(getattr(self.app, "cache", {}) or {})
        self.cache_text.setText(ngettext("{n} entry", "{n} entries", n).format(n=n))

    def _cache_leeren(self):
        from bookbench.core import library as kd
        if not dialogs.frage(self, _("Blurb cache"), _("Empty the blurb cache?"), standard=False):
            return
        self.app.cache = {}
        kd.json_speichern(kd.KLAPPENTEXT_CACHE, {})
        self._cache_zeigen()

    def _exportieren(self):
        p = dialogs.datei_speichern(self, _("Export settings"), str(Path.home() / "bookbench-settings.json"),
                                    [("JSON", "*.json")])
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(self.app.e, fh, indent=2, ensure_ascii=False)
        except OSError as e:
            dialogs.fehler(self, _("Export settings"), str(e))
            return
        self.app.status.set(_("Settings exported: {datei}").format(datei=p))

    def _importieren(self):
        p = dialogs.datei_oeffnen(self, _("Import settings"), "", [("JSON", "*.json")])
        if not p:
            return
        try:
            with open(p, encoding="utf-8") as fh:
                daten = json.load(fh)
            if not isinstance(daten, dict):
                raise ValueError(_("not a settings file"))
        except (OSError, ValueError) as e:
            dialogs.fehler(self, _("Import settings"), str(e))
            return
        alt = self.app.e.get("sprache") or "auto"
        self.app.e.update({k: v for k, v in daten.items() if k in STANDARD})
        self.reject()
        self.app.einstellungen_geaendert(sprache_alt=alt)
        self.app.status.set(_("Settings imported from {datei}.").format(datei=p))

    def _zuruecksetzen(self):
        if not dialogs.frage(self, _("Reset"), _("Reset all settings to the defaults?"), standard=False):
            return
        alt = {k: self.app.e.get(k) for k in self.BEHALTEN}
        self.app.e.clear()
        self.app.e.update(json.loads(json.dumps(STANDARD)), **alt)
        self.reject()
        self.app.einstellungen_geaendert()
        self.app.status.set(_("All settings reset to the defaults."))

    # -- Ablauf ------------------------------------------------------------------
    def _ordner_waehlen(self, schl):
        o = dialogs.ordner(self, "", self.werte.lesen(schl, "") or str(Path.home()))
        if o:
            self.werte.setzen(schl, o)

    def _koreader_waehlen(self):
        p = dialogs.datei_oeffnen(self, _("Choose the KOReader program or AppImage"), str(Path.home()))
        if p:
            self.werte.setzen("koreader_pfad", p)

    def ok(self):
        e = self.app.e
        for k in self.EINFACH:
            if k not in self.werte:
                continue
            wert, typ = self.werte.lesen(k), type(STANDARD[k])
            try:
                e[k] = typ(wert) if typ in (bool, int, float, str) else wert
            except (TypeError, ValueError):            # Unsinn im Feld: alten Wert behalten
                pass
        from bookbench.core import folder_scheme as fs
        if fs.pruefen(e.get("ordnerschema", "")):          # unbrauchbare Vorgabe: Standard
            e["ordnerschema"] = fs.STANDARD
        e["klappentext_profile"] = self.profile
        e["meta_spalten"] = [list(x) for x in self.meta_spalten]
        e["marken_aus"] = {ort: [k for k in kmk.ORDNUNG if (ort, k) in self.marken and not self.marken[(ort, k)].isChecked()]
                           for ort, __ in kmk.ORTE}
        if hasattr(self, "geraet_wahl"):
            e["vorschau_geraet"] = self.geraet_wahl.currentData() or "auto"
            e["vorschau_eigen"] = [self.eigen["w"].value(), self.eigen["h"].value(), self.eigen["dpi"].value(),
                                   self.eigen["farbe"].isChecked()]
        if self.bib_schema is not None:                    # Ordnerschema der geöffneten Bibliothek (library.json)
            from bookbench.core import book_import as bi
            from bookbench.core import folder_scheme as fs
            v = self.bib_schema.text().strip()
            d = bi.bibliothek_lesen(self.app.ordner)
            if fs.pruefen(v):
                dialogs.warnung(self, _("Folder scheme"), _("The folder scheme of this library is not valid and "
                                                            "was not saved: {vorlage}").format(vorlage=v))
            elif v != d.get("ordnerschema"):
                d["ordnerschema"] = v
                try:
                    bi.bibliothek_schreiben(self.app.ordner, d)
                except OSError as fehler:
                    dialogs.warnung(self, _("Folder scheme"), str(fehler))
        alt = e.get("sprache") or "auto"
        e["sprache"] = self.sprachwahl.currentData() or "auto"
        self.accept()
        self.app.einstellungen_geaendert(sprache_alt=alt)


class ProfilDialog(QDialog):
    """Ein Quellprofil bearbeiten. ausfuehren(): das geänderte Profil oder None (abgebrochen)."""

    def __init__(self, eltern, profil):
        super().__init__(eltern)
        self.ergebnis = None
        self.profil = dict(blurbs.LEERES_PROFIL, **profil)
        self.setWindowTitle(_("Source profile"))
        self.resize(640, 640)
        lay = QVBoxLayout(self)
        f = Formular(rand=(16, 10, 12, 0), hinweis_breite=560)
        lay.addWidget(f, 1)
        z = f.zeile(0)
        z.addWidget(label(_("Name:")))
        self.name_feld = QLineEdit(self.profil["name"])
        self.name_feld.setMinimumWidth(260)
        z.addWidget(self.name_feld)
        self.aktiv = QCheckBox(_("Active"))
        self.aktiv.setChecked(bool(self.profil["aktiv"]))
        z.addSpacing(8)
        z.addWidget(self.aktiv)
        z.addStretch(1)
        f.ueberschrift(_("Applies to"), oben=10)
        self.felder = {}
        g = QGridLayout()
        g.setContentsMargins(EINZUG, 0, 0, 0)
        for zeile, (k, text) in enumerate((("verlag", _("Publisher:")), ("reihe", _("Series:")), ("autor", _("Author:")))):
            g.addWidget(label(text), zeile, 0)
            self.felder[k] = QLineEdit(self.profil[k] or "")
            g.addWidget(self.felder[k], zeile, 1)
        f.lay.addLayout(g)
        f.hinweis(_("Parts of names, separated by commas. One match is enough. All empty: every book."))
        f.ueberschrift(_("Where Claude looks"), oben=4)
        f.text(_("Pages to fetch (one address per line, in this order):"))
        self.seiten = QPlainTextEdit(self.profil["seiten"] or "")
        self.seiten.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.seiten.setFixedHeight(90)
        f.widget(self.seiten)
        f.hinweis(_("Placeholders: {title}, {author}, {series} as a wiki page name, {title_q} and {author_q} "
                    "for search addresses, {base} = title without \"Omnibus\". Empty: search only."))
        g = QGridLayout()
        g.setContentsMargins(EINZUG, 0, 0, 0)
        for zeile, (k, text) in enumerate((("domains", _("Further allowed sites:")),
                                           ("abschnitt", _("Section with the blurb:")), ("thema", _("Topic:")))):
            g.addWidget(label(text), zeile, 0)
            self.felder[k] = QLineEdit(self.profil[k] or "")
            g.addWidget(self.felder[k], zeile, 1)
        f.lay.addLayout(g)
        f.hinweis(_("Further sites separated by commas, e.g. tor.com; the sites of the addresses above are "
                    "always allowed. Section and topic are optional hints for Claude, e.g. \"Official "
                    "Description\" or \"Star Wars\"."))
        self.websuche = QCheckBox(_("Web search if no page fits"))
        self.websuche.setChecked(bool(self.profil["websuche"]))
        f.lay.addWidget(self.websuche)
        f.hinweis(_("Only in the allowed sites; without any, on the whole web."))
        f.dehnen()
        unten = QHBoxLayout()
        unten.addStretch(1)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.ok)
        unten.addWidget(ok)
        ab = QPushButton(_("Cancel"))
        ab.clicked.connect(self.reject)
        unten.addWidget(ab)
        lay.addLayout(unten)
        self.name_feld.setFocus()

    def ausfuehren(self):
        self.exec()
        return self.ergebnis

    def ok(self):
        p = dict(self.profil)
        p["name"] = self.name_feld.text().strip() or _("Profile")
        p["aktiv"] = self.aktiv.isChecked()
        p["websuche"] = self.websuche.isChecked()
        for k, feld in self.felder.items():
            p[k] = feld.text().strip()
        p["seiten"] = "\n".join(z.strip() for z in self.seiten.toPlainText().splitlines() if z.strip())
        if not p.get("id"):
            p["id"] = blurbs.profile_id({"name": p["name"]})
        self.ergebnis = p
        self.accept()
