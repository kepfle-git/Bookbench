# -*- coding: utf-8 -*-
"""
settings.py - Einstellungen von Bookbench: Laden, Speichern, Dialog.

Gespeichert als JSON: Windows %APPDATA%\\Bookbench\\einstellungen.json,
sonst ~/.config/bookbench/einstellungen.json (i18n.einstellungsordner). Neue Schlüssel bekommen einen
Standardwert, alte Dateien funktionieren weiter.

  EinstellungsDialog   Baum links (Bereiche), Seite rechts, unter jedem Feld ein Hinweis
"""
import copy
import json
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from bookbench.core import blurbs
import keller_theme as kth
from bookbench.device import models as km
from bookbench import i18n as ks
from bookbench.i18n import N_, _, ngettext

STANDARD = {
    "darstellung": "system", "tooltips": True, "status_liste": True, "cover": True, "fenster": "1200x760",
    "navi_ausgeklappt": True, "navi_offen": [],
    "ordner": "", "letzte_ordner": [],
    "sicherungsordner": str(Path.home() / "Bookbench Backups"), "sicherungen_anzahl": 5,
    "max_sub": 1, "caps": False,
    "api_key": "", "modell": "claude-haiku-5-5", "websuche": True,   # websuche: alt, steckt jetzt im Profil
    "kostenlos": True, "klappentext_profile": None,                  # None: mitgelieferte Profile
    "cover_max_hoehe": 0, "cover_qualitaet": 90, "cover_klein": 800, "cover_openlibrary": True, "cover_google": True,
    "spalten": {}, "spalten_reihe": None, "sortierung": ["reihe", False],   # Bibliothek (ui/table_columns.py)
    "kobo_sicherungen_anzahl": 10, "kobo_teile": ["einstellungen", "settings", "buchdaten", "anpassungen"],
    "woerterbuch_quelle": "", "auswerfen_erinnern": True, "kobo_oeffnen": "auto",
    "woerterbuecher": [], "woerterbuch_aktiv": "",
    "koreader_pfad": "", "vorschau_groesse": "passend", "sprache": "auto",
    "vorschau_geraet": "auto", "vorschau_eigen": [1264, 1680, 300, False],   # eigen: Breite, Höhe, ppi, Farbe
    "start_ordner": True, "start_bereich": "bibliothek", "bereich_zuletzt": "bibliothek",
    "tooltip_verzoegerung": 600, "cover_kopf_hoehe": 96, "kt_min": 80, "kt_max": 4000, "kt_kosten": 0.015,
    "cover_min_hoehe": 300, "cover_anzahl": 8, "kobo_suche_sekunden": 3,
    # Updates (ui/updates.py): pruefen aus/start/taeglich/woechentlich, zuletzt/ausgelassen ohne Seite
    "update_pruefen": "taeglich", "update_vorab": False,     # Repo fest in core/updater.py (REPO)
    "update_zuletzt": "", "update_ausgelassen": "",
}


def klappentext_profile(e):
    """Quellprofile für Klappentexte. Ohne gespeicherte die mitgelieferten; die alte Einstellung
    "websuche" (bis 0.20 global für das Lexicanum) geht dabei ins Lexicanum-Profil."""
    if isinstance(e.get("klappentext_profile"), list):
        return copy.deepcopy(e["klappentext_profile"])
    profile = copy.deepcopy(blurbs.STANDARD_PROFILE)
    for p in profile:
        if p["id"] == "lexicanum":
            p["websuche"] = bool(e.get("websuche", True))
        if p["id"] == "web":
            p["name"] = _("Web search")
    return profile


def pfad():
    return str(ks.einstellungsordner() / "einstellungen.json")


# Auswahl für das Modell (Klappentexte und Wörterbuch über Claude); "Liste laden" holt die aktuelle
# Liste von der API. Stand 18.11.2026, laut Anthropic die neuesten Modelle.
MODELLE = ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-2")


def laden():
    e = json.loads(json.dumps(STANDARD))                # tiefe Kopie
    try:
        with open(pfad(), encoding="utf-8") as f:
            e.update(json.load(f))
    except (OSError, ValueError):
        pass
    for alt in ("update_repo", "update_token"):          # bis 1.0.3 (Repo war privat); Token nicht liegen lassen
        e.pop(alt, None)
    return e


def speichern(e):
    p = pfad()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(e, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


class EinstellungsDialog(tk.Toplevel):
    """Baum links (Gruppen mit Unterseiten), Seite rechts (scrollbar), unter jedem Feld ein Hinweis.
    Seiten mit Unterseiten haben eigenen Inhalt; reine Gruppen zeigen eine Übersicht ihrer Seiten."""
    # (Kennung, Elternseite, Titel, Kurzbeschreibung für die Übersicht)
    SEITEN = (
        ("allgemein", "", N_("General"), N_("Language, look, start, updates")),
        ("darstellung", "allgemein", N_("Language and theme"), N_("Language of the interface, light or dark")),
        ("oberflaeche", "allgemein", N_("Interface"), N_("Status strip, tooltips, covers in the headers, sidebar")),
        ("start", "allgemein", N_("Startup"), N_("What opens when the program starts")),
        ("updates", "allgemein", N_("Updates"), N_("Checking for new versions")),
        ("speichern", "", N_("Saving and backups"), N_("Backup folder and how many backups are kept")),
        ("buecher", "", N_("Books"), N_("Chapters, blurbs and covers")),
        ("kapitel", "buecher", N_("Chapters"), N_("How chapter names are taken from the book text")),
        ("klappentexte", "buecher", N_("Blurbs"), N_("Order of the sources, free sources, checks")),
        ("klappentexte_profile", "klappentexte", N_("Source profiles"),
         N_("Where Claude looks, per publisher, series or author")),
        ("klappentexte_claude", "klappentexte", N_("Claude API"), N_("Key, model, cost estimate")),
        ("cover", "buecher", N_("Covers"), N_("Inserting and marking covers")),
        ("cover_nachschlagen", "cover", N_("Looking up covers"), N_("Sources and which images count")),
        ("geraet", "", N_("Device"), N_("E-reader and preview")),
        ("kobo", "geraet", N_("E-reader"), N_("Detection, backups, dictionaries, ejecting")),
        ("vorschau", "geraet", N_("Preview"), N_("Desktop KOReader and the device shown")),
        ("erweitert", "", N_("Advanced"), N_("Files of the program, cache, export, reset")),
    )
    UEBERSICHT = {"allgemein", "buecher", "geraet"}          # nur Übersicht, keine eigenen Einstellungen
    # Einstellungen mit einfachem Wert; die Variable richtet sich nach dem Typ in STANDARD
    EINFACH = ("darstellung", "tooltips", "status_liste", "cover", "cover_kopf_hoehe", "tooltip_verzoegerung",
               "navi_ausgeklappt", "start_ordner", "start_bereich", "sicherungsordner", "sicherungen_anzahl",
               "max_sub", "caps", "api_key", "modell", "kt_kosten", "kostenlos", "kt_min", "kt_max",
               "cover_max_hoehe", "cover_qualitaet", "cover_klein", "cover_openlibrary", "cover_google",
               "cover_min_hoehe", "cover_anzahl", "kobo_sicherungen_anzahl", "woerterbuch_quelle",
               "auswerfen_erinnern", "kobo_suche_sekunden", "kobo_oeffnen", "koreader_pfad", "update_pruefen", "update_vorab")

    def __init__(self, app, seite=None):
        super().__init__(app)
        self.app = app
        e = app.e
        self.title(_("Settings"))
        self.transient(app)
        self.geometry("860x600")
        self.minsize(680, 420)
        self.v = {}
        for k in self.EINFACH:
            wert = e.get(k, STANDARD[k])
            typ = type(STANDARD[k])
            var = tk.BooleanVar if typ is bool else tk.IntVar if typ is int else \
                tk.DoubleVar if typ is float else tk.StringVar
            self.v[k] = var(value=wert)
        self.profile = klappentext_profile(e)
        self.sprache = tk.StringVar(value=self._sprachname(e.get("sprache") or "auto"))
        unten = ttk.Frame(self, padding=8)
        unten.pack(side="bottom", fill="x")
        ttk.Button(unten, text=_("Help"), command=self.hilfe).pack(side="left")
        ttk.Button(unten, text=_("Cancel"), command=self.destroy).pack(side="right")
        ttk.Button(unten, text="OK", command=self.ok).pack(side="right", padx=6)
        links = ttk.Frame(self, padding=(8, 8, 0, 0))
        links.pack(side="left", fill="y")
        self.rahmen = tk.Frame(links, highlightthickness=1, borderwidth=0)
        self.rahmen.pack(fill="both", expand=True)
        self.baum = ttk.Treeview(self.rahmen, show="tree", selectmode="browse", height=18)
        self.baum.column("#0", width=200)
        self.baum.pack(fill="both", expand=True)
        self.p = kth.PALETTE["dunkel" if app.dark_mode.get() else "hell"]
        self.seiten, self.leinwaende = {}, {}
        self.inhalt = ttk.Frame(self, padding=(0, 6, 0, 0))
        self.inhalt.pack(side="left", fill="both", expand=True)
        for name, eltern, titel, __ in self.SEITEN:
            if name == "vorschau" and sys.platform.startswith("win"):
                continue                               # keine Vorschau unter Windows
            self.baum.insert(eltern, "end", iid=name, text=_(titel), open=True)
            innen = self._seitenrahmen(name)
            if name in self.UEBERSICHT:
                self._uebersicht(name, innen)
            else:
                getattr(self, "_seite_" + name)(innen)
        self.baum.bind("<<TreeviewSelect>>", lambda ev: self._zeigen())
        self.rahmen.configure(highlightbackground=self.p["rahmen"], highlightcolor=self.p["rahmen"])
        start = (seite or "darstellung").lower()
        self.baum.selection_set(start if self.baum.exists(start) else "darstellung")
        self.baum.see(self.baum.selection()[0])
        self.bind("<Escape>", lambda ev: self.destroy())
        self.bind("<Return>", lambda ev: self.ok() if not isinstance(ev.widget, tk.Text) else None)
        self.bind("<F1>", lambda ev: self.hilfe())
        for ereignis in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind(ereignis, self._rad)             # Toplevel steht in den bindtags aller Kinder

    # -- Rahmen: scrollbare Seiten ---------------------------------------------------
    def _seitenrahmen(self, name):
        aussen = ttk.Frame(self.inhalt)
        lw = tk.Canvas(aussen, highlightthickness=0, borderwidth=0, bg=self.p["bg"])
        sb = ttk.Scrollbar(aussen, orient="vertical", command=lw.yview)
        lw.configure(yscrollcommand=sb.set)
        innen = ttk.Frame(lw, padding=(16, 4, 12, 8))
        fenster = lw.create_window(0, 0, window=innen, anchor="nw")

        def anpassen(ev=None):
            lw.configure(scrollregion=(0, 0, innen.winfo_reqwidth(), innen.winfo_reqheight()))
            lw.itemconfigure(fenster, width=lw.winfo_width())
            if innen.winfo_reqheight() > lw.winfo_height() > 1:
                sb.pack(side="right", fill="y")
            else:
                sb.pack_forget()
                lw.yview_moveto(0)
        innen.bind("<Configure>", anpassen)
        lw.bind("<Configure>", anpassen)
        lw.pack(side="left", fill="both", expand=True)
        self.seiten[name] = aussen
        self.leinwaende[name] = lw
        return innen

    def _rad(self, ev):
        """Mausrad/Touchpad scrollt die gezeigte Seite, wenn sie länger ist als das Fenster."""
        try:
            if ev.widget.winfo_toplevel() is not self:
                return
        except (AttributeError, tk.TclError, KeyError):
            return
        sel = self.baum.selection()
        lw = self.leinwaende.get(sel[0]) if sel else None
        if lw is None or str(ev.widget).startswith(str(self.baum)):
            return
        if lw.bbox("all") and lw.bbox("all")[3] <= lw.winfo_height():
            return
        schritt = -1 if getattr(ev, "num", 0) == 4 or getattr(ev, "delta", 0) > 0 else 1
        lw.yview_scroll(schritt * 2, "units")

    def _uebersicht(self, name, s):
        titel = next(_(t) for k, __, t, __ in self.SEITEN if k == name)
        ttk.Label(s, text=titel, style="Ueberschrift.TLabel").pack(anchor="w", pady=(0, 10))
        for k, eltern, t, beschreibung in self.SEITEN:
            if eltern != name or (k == "vorschau" and sys.platform.startswith("win")):
                continue
            knopf = ttk.Label(s, text=_(t), style="Verweis.TLabel", cursor="hand2")
            knopf.pack(anchor="w")
            knopf.bind("<Button-1>", lambda ev, k=k: self.gehe_zu(k))
            self._hinweis(s, _(beschreibung))
        ttk.Style(self).configure("Verweis.TLabel", foreground=self.p["akzent"], font=kth.schrift(10, fett=True))

    def gehe_zu(self, name):
        if self.baum.exists(name):
            self.baum.selection_set(name)
            self.baum.see(name)

    def hilfe(self):
        sel = self.baum.selection()
        self.app.hilfe_zeigen("einst_" + (sel[0] if sel else "darstellung"))

    # -- Bausteine ---------------------------------------------------------------
    def _ueberschrift(self, eltern, text, oben=0):
        ttk.Label(eltern, text=text, style="Ueberschrift.TLabel").pack(anchor="w", pady=(oben, 6))

    def _abschnitt(self, eltern, text):
        ttk.Label(eltern, text=text, font=kth.schrift(10, fett=True)).pack(anchor="w", pady=(6, 2))

    def _hinweis(self, eltern, text):
        ttk.Label(eltern, text=text, style="Hinweis.TLabel", wraplength=540, justify="left").pack(
            anchor="w", pady=(0, 10), padx=(22, 0))

    def _schalter(self, eltern, var, text, hinweis):
        ttk.Checkbutton(eltern, text=text, variable=self.v[var]).pack(anchor="w")
        self._hinweis(eltern, hinweis)

    def _feld(self, eltern, var, text, hinweis, breite=40, zeigen=None, knopf=None):
        ttk.Label(eltern, text=text).pack(anchor="w")
        z = ttk.Frame(eltern)
        z.pack(anchor="w", fill="x", padx=(22, 0))
        f = ttk.Entry(z, textvariable=self.v[var], width=breite, show=zeigen or "")
        f.pack(side="left")
        if knopf:
            ttk.Button(z, text=knopf[0], command=knopf[1]).pack(side="left", padx=6)
        self._hinweis(eltern, hinweis)
        return f

    def _zahl(self, eltern, var, text, hinweis, von, bis, schritt=1, format=None):
        z = ttk.Frame(eltern)
        z.pack(anchor="w")
        ttk.Label(z, text=text).pack(side="left")
        sp = ttk.Spinbox(z, from_=von, to=bis, increment=schritt, textvariable=self.v[var], width=7)
        if format:
            sp.configure(format=format)
        sp.pack(side="left", padx=8)
        self._hinweis(eltern, hinweis)

    def _auswahl(self, eltern, var, werte, hinweis=None):
        for wert, text in werte:
            ttk.Radiobutton(eltern, text=text, value=wert, variable=self.v[var]).pack(anchor="w")
        if hinweis:
            self._hinweis(eltern, hinweis)

    # -- Sprache ------------------------------------------------------------------
    @staticmethod
    def _sprachen():
        """[(Code, Anzeigename)]; die Sprachen stehen in ihrer eigenen Sprache da."""
        return [("auto", _("Automatic (system language)"))] + list(ks.SPRACHEN.items())

    def _sprachname(self, code):
        return dict(self._sprachen()).get(code, self._sprachen()[0][1])

    def _sprachcode(self):
        return next((c for c, n in self._sprachen() if n == self.sprache.get()), "auto")

    # -- Allgemein -------------------------------------------------------------------
    def _seite_darstellung(self, s):
        self._ueberschrift(s, _("Language and theme"))
        self._abschnitt(s, _("Language"))
        z = ttk.Frame(s)
        z.pack(anchor="w", pady=(0, 2), padx=(22, 0))
        self.sprachwahl = ttk.Combobox(z, textvariable=self.sprache, state="readonly", width=32,
                                       values=[n for c, n in self._sprachen()])
        self.sprachwahl.pack(side="left")
        self._hinweis(s, _("Automatic: German if the system language is German, otherwise English. Changing it "
                           "restarts the program; folder, area, selected book and window stay as they are."))
        self._abschnitt(s, _("Theme"))
        self._auswahl(s, "darstellung", (("hell", _("Light")), ("dunkel", _("Dark")), ("system", _("Like the system"))),
                      _("Like the system: follows the light/dark setting of Windows or KDE/GNOME, checked at start."))

    def _seite_oberflaeche(self, s):
        self._ueberschrift(s, _("Interface"))
        self._abschnitt(s, _("Lists"))
        self._schalter(s, "status_liste", _("Status strip next to the lists"),
                       _("Coloured dots (changed, applied, saved) and ⚠ to the right of the book lists."))
        self._abschnitt(s, _("Tooltips"))
        self._schalter(s, "tooltips", _("Show tooltips"), _("Explanations when the mouse stays over a button."))
        self._zahl(s, "tooltip_verzoegerung", _("Delay (ms):"),
                   _("How long the mouse has to stay still before the explanation appears."), 0, 3000, 100)
        self._abschnitt(s, _("Covers in the headers"))
        self._schalter(s, "cover", _("Show covers in Chapters and Blurbs"),
                       _("Small cover next to the book title; a click shows it large. JPEG images need Pillow "
                         "(pip install pillow)."))
        self._zahl(s, "cover_kopf_hoehe", _("Height (px):"), _("Default 96."), 40, 300, 8)
        self._abschnitt(s, _("Sidebar"))
        self._schalter(s, "navi_ausgeklappt", _("Sidebar expanded"),
                       _("With names and counters; collapsed only the symbols. Ctrl+B switches at any time."))

    def _seite_start(self, s):
        self._ueberschrift(s, _("Startup"))
        self._schalter(s, "start_ordner", _("Open the last folder"),
                       _("The books folder that was open when the program was last closed, if it still exists "
                         "(e.g. the e-reader is connected). Otherwise the program starts empty."))
        self._abschnitt(s, _("Area at start"))
        self._auswahl(s, "start_bereich", (("bibliothek", _("Library")), ("zuletzt", _("The last area used"))))

    def _seite_updates(self, s):
        from bookbench.core import updater as ku
        self._ueberschrift(s, _("Updates"))
        art = ku.installationsart()
        self._abschnitt(s, _("This copy"))
        text = {"windows": _("Installed with the Windows setup: updates are installed by the setup."),
                "linux": _("Installed with install.sh: updates replace the program folder {ordner}.").format(
                    ordner=ku.PROGRAMM),
                }.get(art, _("Runs from the source code ({ordner}), e.g. a git clone: updates are only shown, "
                             "not installed, and there is no automatic check.").format(ordner=ku.PROGRAMM))
        self._hinweis(s, text)
        z = ttk.Frame(s)
        z.pack(anchor="w", padx=(22, 0), pady=(0, 10))
        ttk.Button(z, text=_("Check now"), command=self._update_jetzt).pack(side="left")
        zuletzt = (self.app.e.get("update_zuletzt") or "").replace("T", " ")[:16]
        ttk.Label(z, text=_("Last check: {wann}").format(wann=zuletzt or _("never")),
                  style="Hinweis.TLabel").pack(side="left", padx=10)
        self._abschnitt(s, _("Automatic check"))
        self._auswahl(s, "update_pruefen", (("aus", _("Off")), ("start", _("At every start")),
                                            ("taeglich", _("At start, at most once a day")),
                                            ("woechentlich", _("At start, at most once a week"))),
                      _("Looks a few seconds after the start whether GitHub has a newer release. Only a new "
                        "version shows a window; errors (no network) only appear in the status line."))
        ausgelassen = self.app.e.get("update_ausgelassen")
        if ausgelassen:
            z = ttk.Frame(s)
            z.pack(anchor="w", padx=(22, 0), pady=(0, 10))
            lab = ttk.Label(z, text=_("Skipped version: {version}").format(version=ausgelassen))
            lab.pack(side="left")

            def wieder():
                self.app.e["update_ausgelassen"] = ""
                lab.configure(text=_("Skipped version: none"))
            ttk.Button(z, text=_("Show again"), command=wieder).pack(side="left", padx=8)
        self._schalter(s, "update_vorab", _("Include pre-releases"),
                       _("Also offers releases marked as pre-release on GitHub (test versions)."))
        self._hinweis(s, _("The releases come from github.com/{repo}.").format(repo=ku.REPO))

    def _update_jetzt(self):
        e = dict(self.app.e)
        for k in ("update_vorab",):
            try:
                e[k] = self.v[k].get()
            except tk.TclError:
                pass
        self.app.updates.pruefen(von_hand=True, einstellungen=e)

    # -- Speichern ---------------------------------------------------------------------
    def _seite_speichern(self, s):
        self._ueberschrift(s, _("Saving and backups"))
        self._feld(s, "sicherungsordner", _("Backup folder"),
                   _("Before each save the book is copied here (name with date and time). Do not put it on the e-reader, "
                     "or KOReader shows the backups as books. The KOReader backups of the E-reader area go into its "
                     "subfolder KOReader, dictionaries into Wörterbücher."), 46,
                   knopf=(_("Choose …"), self._ordner_waehlen))
        self._zahl(s, "sicherungen_anzahl", _("Backups per book:"),
                   _("The newest ones are kept, older ones are deleted when saving."), 1, 50)

    # -- Bücher --------------------------------------------------------------------------
    def _seite_kapitel(self, s):
        self._ueberschrift(s, _("Chapters"))
        self._zahl(s, "max_sub", _("Subtitle lines per chapter:"),
                   _("1: only the first line below the number. Some books have three; with 3 all of them are "
                     "joined with \" / \". Applies after reloading (F5)."), 1, 5)
        self._schalter(s, "caps", _("Write entries in capitals normally"),
                       _("THE SHIRE becomes The Shire, A LONG-EXPECTED PARTY becomes A Long-Expected Party. "
                         "Applies after reloading (F5)."))

    def _seite_klappentexte(self, s):
        self._ueberschrift(s, _("Blurbs"))
        self._hinweis(s, _("Order when looking up: the EPUB itself, Calibre (From Calibre), the free sources, "
                           "then Claude with the matching source profile."))
        self._abschnitt(s, _("Free sources"))
        self._schalter(s, "kostenlos", _("Ask Google Books and Open Library first"),
                       _("No key, no cost. Claude is only asked if they have nothing. Switched off, every look-up "
                         "goes to Claude."))
        self._abschnitt(s, _("Checks"))
        self._zahl(s, "kt_min", _("Shortest blurb (characters):"),
                   _("Shorter texts from a source are not taken (often only a teaser line)."), 0, 2000, 10)
        self._zahl(s, "kt_max", _("Longest blurb (characters):"),
                   _("Longer texts are not taken (usually a plot summary or a whole article)."), 200, 20000, 100)

    def _seite_klappentexte_profile(self, s):
        self._ueberschrift(s, _("Source profiles"))
        self._hinweis(s, _("A profile says where Claude looks for a blurb. The first active profile that fits the "
                           "book is used; order with Up/Down. Double-click edits."))
        z = ttk.Frame(s)
        z.pack(anchor="w", fill="x", padx=(22, 0))
        r = tk.Frame(z, highlightthickness=1, borderwidth=0)
        r.pack(side="left", fill="x", expand=True)
        r.configure(highlightbackground=self.p["rahmen"], highlightcolor=self.p["rahmen"])
        self.profil_liste = ttk.Treeview(r, columns=("name", "gilt"), show="headings", selectmode="browse", height=7)
        self.profil_liste.heading("name", text=_("Profile"))
        self.profil_liste.heading("gilt", text=_("Applies to"))
        self.profil_liste.column("name", width=200, stretch=True)
        self.profil_liste.column("gilt", width=200, stretch=True)
        self.profil_liste.pack(fill="x")
        self.profil_liste.bind("<Double-1>", lambda ev: self._profil_bearbeiten())
        k = ttk.Frame(z)
        k.pack(side="left", anchor="n", padx=(6, 0))
        for text, fn in ((_("New …"), self._profil_neu), (_("Edit …"), self._profil_bearbeiten),
                         (_("Delete"), self._profil_loeschen), (_("Up"), lambda: self._profil_schieben(-1)),
                         (_("Down"), lambda: self._profil_schieben(1)), (_("Defaults"), self._profile_standard)):
            ttk.Button(k, text=text, command=fn, width=14).pack(fill="x", pady=(0, 2))
        self._hinweis(s, _("Defaults puts the included profiles (Lexicanum, web search) back; your own profiles "
                           "are removed."))
        self._profile_zeigen()

    def _seite_klappentexte_claude(self, s):
        self._ueberschrift(s, _("Claude API"))
        self._feld(s, "api_key", _("API key"), _("From console.anthropic.com. Empty: environment variable "
                                                    "ANTHROPIC_API_KEY. Stored in plain text in the settings file."),
                   46, zeigen="•")
        ttk.Label(s, text=_("Model")).pack(anchor="w")
        z = ttk.Frame(s)
        z.pack(anchor="w", fill="x", padx=(22, 0))
        werte = list(MODELLE)
        if self.v["modell"].get() and self.v["modell"].get() not in werte:
            werte.insert(0, self.v["modell"].get())
        self.modell_wahl = ttk.Combobox(z, textvariable=self.v["modell"], values=werte, width=30)
        self.modell_wahl.pack(side="left")
        ttk.Button(z, text=_("Load list"), command=self._modelle_laden).pack(side="left", padx=6)
        self.modell_hinweis = ttk.Label(s, text=_("Haiku is enough for looking things up and is the cheapest. "
                                                  "Load list asks Anthropic with the API key which models there "
                                                  "are; typing a name also works."),
                                        style="Hinweis.TLabel", wraplength=520, justify="left")
        self.modell_hinweis.pack(anchor="w", padx=(22, 0), pady=(2, 10))
        self._zahl(s, "kt_kosten", _("Estimated cost per book ($):"),
                   _("Only for the question before \"Look up all\"; the real cost depends on page length and "
                     "searches."), 0, 1, 0.005, "%.3f")

    def _modelle_laden(self):
        """Modelle über die API abfragen (models.list), im Hilfsthread."""
        schluessel = self.v["api_key"].get().strip() or os.environ.get("ANTHROPIC_API_KEY", "")
        if not schluessel:
            self.modell_hinweis.configure(text=_("Enter the API key first."))
            return
        self.modell_hinweis.configure(text=_("Asking Anthropic …"))

        def lauf():
            try:
                import anthropic
                namen = [m.id for m in anthropic.Anthropic(api_key=schluessel).models.list(limit=100)]
                fehler = None if namen else _("Anthropic returned no models.")
            except ImportError:
                namen, fehler = [], _("The package anthropic is missing (pip install anthropic).")
            except Exception as e:                     # Netz, falscher Schlüssel
                namen, fehler = [], _("Could not load the models ({fehler}).").format(fehler=e)
            self.app._q.put(("rueckruf", lambda: self._modelle_geladen(namen, fehler)))
        threading.Thread(target=lauf, daemon=True).start()

    def _modelle_geladen(self, namen, fehler):
        try:
            if fehler:
                self.modell_hinweis.configure(text=fehler)
                return
            self.modell_wahl.configure(values=namen)
            self.modell_hinweis.configure(text=ngettext("{n} model loaded; the list is newest first.",
                                                        "{n} models loaded; the list is newest first.",
                                                        len(namen)).format(n=len(namen)))
        except tk.TclError:                            # Dialog schon zu
            pass

    def _profile_standard(self):
        self.profile = klappentext_profile({"websuche": True})
        self._profile_zeigen(0)

    # -- Quellprofile --------------------------------------------------------------
    def _gilt_text(self, p):
        teile = [x for x in (p.get("verlag"), p.get("reihe"), p.get("autor")) if (x or "").strip()]
        text = " / ".join(teile) if teile else _("all books")
        return text if p.get("aktiv", True) else _("(off) {text}").format(text=text)

    def _profile_zeigen(self, auswahl=None):
        t = self.profil_liste
        t.delete(*t.get_children())
        for i, p in enumerate(self.profile):
            t.insert("", "end", iid=str(i), values=(p.get("name") or "?", self._gilt_text(p)))
        if auswahl is not None and 0 <= auswahl < len(self.profile):
            t.selection_set(str(auswahl))
            t.see(str(auswahl))

    def _profil_index(self):
        sel = self.profil_liste.selection()
        return int(sel[0]) if sel else None

    def _profil_neu(self):
        p = ProfilDialog(self, dict(blurbs.LEERES_PROFIL, name=_("New profile"))).ergebnis
        if p:
            self.profile.insert(0, p)                # vorne: sonst greift das allgemeine Profil zuerst
            self._profile_zeigen(0)

    def _profil_bearbeiten(self):
        i = self._profil_index()
        if i is None:
            return
        p = ProfilDialog(self, self.profile[i]).ergebnis
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

    def _seite_cover(self, s):
        self._ueberschrift(s, _("Covers"))
        self._abschnitt(s, _("Inserting a new cover"))
        self._zahl(s, "cover_max_hoehe", _("Shrink to at most this height (px):"),
                   _("0: never shrink. Your e-reader shows at most its screen height (e.g. 1680 px); larger "
                     "images only make the file bigger. Images are never enlarged."), 0, 6000, 10)
        self._zahl(s, "cover_qualitaet", _("JPEG quality:"),
                   _("Only when an image is converted or shrunk; otherwise it is taken unchanged. The new cover "
                     "keeps the format of the old one (JPEG stays JPEG)."), 50, 100)
        self._abschnitt(s, _("Marking"))
        self._zahl(s, "cover_klein", _("Mark covers below this height (px):"),
                   _("Shown with ⚠ in the Covers area and in the filter \"Small cover\". 0: never."), 0, 6000, 10)

    def _seite_cover_nachschlagen(self, s):
        self._ueberschrift(s, _("Looking up covers"))
        self._abschnitt(s, _("Sources"))
        self._schalter(s, "cover_openlibrary", _("Open Library"), _("Free, no key. Often large scans of the "
                                                                    "cover, sometimes of another edition."))
        self._schalter(s, "cover_google", _("Google Books"), _("Free, no key. Usually smaller images."))
        self._abschnitt(s, _("Which images count"))
        self._zahl(s, "cover_min_hoehe", _("Smallest height (px):"),
                   _("Smaller images are left out (preview thumbnails)."), 50, 2000, 10)
        self._zahl(s, "cover_anzahl", _("At most this many to choose from:"),
                   _("Each image is downloaded, so more takes longer."), 1, 30)

    # -- Gerät -------------------------------------------------------------------------
    def _seite_kobo(self, s):
        self._ueberschrift(s, _("E-reader"))
        self._abschnitt(s, _("Detection"))
        self._zahl(s, "kobo_suche_sekunden", _("Look for the e-reader every (seconds):"),
                   _("While Bookbench is open it checks this often whether an e-reader is connected or "
                     "unplugged."), 1, 60)
        ttk.Label(s, text=_("When an e-reader is connected:")).pack(anchor="w", pady=(6, 0))
        self._auswahl(s, "kobo_oeffnen", (
            ("auto", _("Open its books (ask if another folder is open)")),
            ("fragen", _("Always ask whether to open its books")),
            ("nie", _("Do nothing (open with Books in the E-reader area)"))))
        self._abschnitt(s, _("Backups"))
        self._zahl(s, "kobo_sicherungen_anzahl", _("Backups of the KOReader settings:"),
                   _("This many stay in the KOReader subfolder of the backup folder; older ones are deleted. This "
                     "includes the backup made before each restore."), 1, 100)
        self._abschnitt(s, _("Dictionaries"))
        self._feld(s, "woerterbuch_quelle", _("Dictionaries (folder on the computer)"),
                   _("A dictionary folder (with an .ifo file, e.g. My-Dictionary) or a folder with several of them."),
                   46, knopf=(_("Choose …"), lambda: self._ordner_waehlen("woerterbuch_quelle")))
        self._abschnitt(s, _("Ejecting"))
        self._schalter(s, "auswerfen_erinnern", _("Remind me to eject when quitting"),
                       _("Only if something was written to the e-reader in this session."))

    def _seite_vorschau(self, s):
        self._ueberschrift(s, _("Preview"))
        self._feld(s, "koreader_pfad", _("Desktop KOReader (optional)"),
                   _("Empty: searched for (koreader in PATH, AppImage in ~/Applications or ~/Downloads, "
                     "Flatpak). Only fill in if it is somewhere else. flatpak: always the Flatpak "
                     "rocks.koreader.KOReader, even if KOReader is also installed normally."),
                   46, knopf=(_("Choose …"), self._koreader_waehlen))
        ttk.Label(s, text=_("Device shown")).pack(anchor="w")
        self._geraete = [("auto", _("Automatic (device of the profile, otherwise the connected e-reader)"))] \
            + km.auswahl() + [("eigen", _("Own size"))]
        aktuell = self.app.e.get("vorschau_geraet") or "auto"
        if aktuell not in dict(self._geraete):           # z. B. 395: steht unter 391 in der Liste
            m = km.modell(aktuell)
            aktuell = next((nr for nr, __ in self._geraete if m and km.modell(nr) and
                            km.modell(nr)["name"] == m["name"]), "auto")
        self.geraet_var = tk.StringVar(value=dict(self._geraete)[aktuell])
        z = ttk.Frame(s)
        z.pack(anchor="w", padx=(22, 0))
        self.geraet_wahl = ttk.Combobox(z, textvariable=self.geraet_var, state="readonly", width=52,
                                        values=[t for __, t in self._geraete], height=16)
        self.geraet_wahl.pack(side="left")
        self.geraet_wahl.bind("<<ComboboxSelected>>", lambda ev: self._eigen_zeigen())
        self._hinweis(s, _("Size and pixel density of the window, and colour or black and white. Tolino devices "
                           "from 2024 on are Kobo hardware and are listed too."))
        w, h, dpi, farbe = (list(self.app.e.get("vorschau_eigen") or STANDARD["vorschau_eigen"]) + [False])[:4]
        self.eigen = {"w": tk.IntVar(value=w), "h": tk.IntVar(value=h), "dpi": tk.IntVar(value=dpi),
                      "farbe": tk.BooleanVar(value=farbe)}
        self.eigen_rahmen = ttk.Frame(s)
        z = ttk.Frame(self.eigen_rahmen)
        z.pack(anchor="w", padx=(22, 0))
        for k, text, von, bis in (("w", _("Width:"), 200, 4000), ("h", _("Height:"), 200, 4000),
                                  ("dpi", _("ppi:"), 100, 600)):
            ttk.Label(z, text=text).pack(side="left")
            ttk.Spinbox(z, from_=von, to=bis, textvariable=self.eigen[k], width=6).pack(side="left", padx=(4, 12))
        ttk.Checkbutton(self.eigen_rahmen, text=_("Colour screen"), variable=self.eigen["farbe"]).pack(
            anchor="w", padx=(22, 0), pady=(4, 0))
        self._hinweis(self.eigen_rahmen, _("Pixels in portrait format. For other e-readers with KOReader: see the "
                                           "maker's data sheet."))
        self._eigen_zeigen()

    def _geraet_code(self):
        return next((nr for nr, t in getattr(self, "_geraete", []) if t == self.geraet_var.get()), "auto")

    def _eigen_zeigen(self):
        if self._geraet_code() == "eigen":
            self.eigen_rahmen.pack(anchor="w", fill="x")
        else:
            self.eigen_rahmen.pack_forget()

    # -- Erweitert -----------------------------------------------------------------------
    def _seite_erweitert(self, s):
        self._ueberschrift(s, _("Advanced"))
        self._abschnitt(s, _("Files of the program"))
        from bookbench.core import library as kd
        g = ttk.Frame(s)
        g.pack(anchor="w", fill="x", padx=(22, 0))
        for zeile, (text, datei) in enumerate(((_("Settings"), Path(pfad())),
                                               (_("Chapter decisions"), Path(kd.ENTSCHEIDUNGEN)),
                                               (_("Blurb cache"), Path(kd.KLAPPENTEXT_CACHE)))):
            ttk.Label(g, text=text + ":").grid(row=zeile, column=0, sticky="nw", pady=1)
            ttk.Label(g, text=str(datei), style="Hinweis.TLabel", wraplength=320, justify="left").grid(
                row=zeile, column=1, sticky="w", padx=(8, 0), pady=1)
        z = ttk.Frame(s)
        z.pack(anchor="w", padx=(22, 0), pady=(4, 0))
        ttk.Button(z, text=_("Open settings folder"), command=lambda: ordner_zeigen(Path(pfad()).parent)).pack(side="left")
        self._hinweis(s, _("The chapter decisions remember which names were applied, so they are suggested again "
                           "for other copies of the same book. The cache holds looked-up blurbs and what was "
                           "already tried, so looking up again costs nothing."))
        self._abschnitt(s, _("Blurb cache"))
        z = ttk.Frame(s)
        z.pack(anchor="w", padx=(22, 0))
        self.cache_text = ttk.Label(z, text="")
        self.cache_text.pack(side="left")
        ttk.Button(z, text=_("Empty …"), command=self._cache_leeren).pack(side="left", padx=8)
        self._cache_zeigen()
        self._hinweis(s, _("Afterwards everything is looked up again (and Claude costs again)."))
        self._abschnitt(s, _("Export and import"))
        z = ttk.Frame(s)
        z.pack(anchor="w", padx=(22, 0))
        ttk.Button(z, text=_("Export settings …"), command=self._exportieren).pack(side="left")
        ttk.Button(z, text=_("Import settings …"), command=self._importieren).pack(side="left", padx=6)
        self._hinweis(s, _("A JSON file, e.g. to take the settings to another computer. It contains the API key. "
                           "Importing replaces the current settings; the language applies at the next start."))
        self._abschnitt(s, _("Reset"))
        ttk.Button(s, text=_("Reset all settings …"), command=self._zuruecksetzen).pack(anchor="w", padx=(22, 0))
        self._hinweis(s, _("Everything back to the defaults. Kept: opened folders, the list of dictionaries, window "
                           "size, language and the API key."))

    def _cache_zeigen(self):
        n = len(getattr(self.app, "cache", {}) or {})
        self.cache_text.configure(text=ngettext("{n} entry", "{n} entries", n).format(n=n))

    def _cache_leeren(self):
        from bookbench.core import library as kd
        if not messagebox.askyesno(_("Blurb cache"), _("Empty the blurb cache?"), parent=self):
            return
        self.app.cache = {}
        kd.json_speichern(kd.KLAPPENTEXT_CACHE, {})
        self._cache_zeigen()

    def _exportieren(self):
        p = filedialog.asksaveasfilename(parent=self, title=_("Export settings"), defaultextension=".json",
                                         initialfile="bookbench-settings.json",
                                         filetypes=[("JSON", "*.json")])
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self.app._e_zum_speichern(), f, indent=2, ensure_ascii=False)
        except OSError as e:
            messagebox.showerror(_("Export settings"), str(e), parent=self)
            return
        self.app.status.set(_("Settings exported: {datei}").format(datei=p))

    def _importieren(self):
        p = filedialog.askopenfilename(parent=self, title=_("Import settings"), filetypes=[("JSON", "*.json")])
        if not p:
            return
        try:
            with open(p, encoding="utf-8") as f:
                daten = json.load(f)
            if not isinstance(daten, dict):
                raise ValueError(_("not a settings file"))
        except (OSError, ValueError) as e:
            messagebox.showerror(_("Import settings"), str(e), parent=self)
            return
        self.app.e.update({k: v for k, v in daten.items() if k in STANDARD})
        self.app.einstellungen_geaendert()
        self.destroy()
        self.app.status.set(_("Settings imported from {datei}.").format(datei=p))

    BEHALTEN = ("ordner", "letzte_ordner", "woerterbuecher", "woerterbuch_aktiv", "fenster", "api_key", "sprache")

    def _zuruecksetzen(self):
        if not messagebox.askyesno(_("Reset"), _("Reset all settings to the defaults?"), parent=self):
            return
        alt = {k: self.app.e.get(k) for k in self.BEHALTEN}
        self.app.e.clear()
        self.app.e.update(json.loads(json.dumps(STANDARD)), **alt)
        self.app.einstellungen_geaendert()
        self.destroy()
        self.app.status.set(_("All settings reset to the defaults."))

    # -- Ablauf ------------------------------------------------------------------
    def _zeigen(self):
        sel = self.baum.selection()
        for name, s in self.seiten.items():
            if sel and name == sel[0]:
                s.pack(fill="both", expand=True)
            else:
                s.pack_forget()

    def _ordner_waehlen(self, var="sicherungsordner"):
        o = filedialog.askdirectory(parent=self, initialdir=self.v[var].get() or str(Path.home()))
        if o:
            self.v[var].set(o)

    def _koreader_waehlen(self):
        p = filedialog.askopenfilename(parent=self, title=_("Choose the KOReader program or AppImage"),
                                       initialdir=str(Path.home()))
        if p:
            self.v["koreader_pfad"].set(p)

    def ok(self):
        for k, var in self.v.items():
            try:
                self.app.e[k] = var.get()
            except tk.TclError:                       # z. B. Buchstaben im Zahlenfeld
                pass
        self.app.e["klappentext_profile"] = self.profile
        if hasattr(self, "geraet_var"):
            self.app.e["vorschau_geraet"] = self._geraet_code()
            try:
                self.app.e["vorschau_eigen"] = [int(self.eigen["w"].get()), int(self.eigen["h"].get()),
                                                int(self.eigen["dpi"].get()), bool(self.eigen["farbe"].get())]
            except (tk.TclError, ValueError):            # Unsinn im Zahlenfeld: alten Wert behalten
                pass
        alt, neu = self.app.e.get("sprache") or "auto", self._sprachcode()
        self.app.e["sprache"] = neu
        self.app.einstellungen_geaendert()
        self.destroy()
        if neu != alt:
            self.app.sprache_wechseln(alt)


def ordner_zeigen(ordner):
    """Ordner im Dateimanager öffnen (Explorer, Finder, xdg-open)."""
    import subprocess
    ordner = str(ordner)
    try:
        if sys.platform.startswith("win"):
            os.startfile(ordner)                       # noqa: S606 - nur ein Ordner
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", ordner],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except (OSError, AttributeError):
        pass


class ProfilDialog(tk.Toplevel):
    """Ein Quellprofil bearbeiten. ergebnis: das geänderte Profil oder None (abgebrochen)."""

    def __init__(self, eltern, profil):
        super().__init__(eltern)
        self.ergebnis = None
        self.profil = dict(blurbs.LEERES_PROFIL, **profil)
        self.title(_("Source profile"))
        self.transient(eltern)
        self.geometry("620x630")
        self.minsize(560, 630)
        unten = ttk.Frame(self, padding=8)
        unten.pack(side="bottom", fill="x")
        ttk.Button(unten, text=_("Cancel"), command=self.destroy).pack(side="right")
        ttk.Button(unten, text="OK", command=self.ok).pack(side="right", padx=6)
        s = ttk.Frame(self, padding=(16, 10, 12, 0))
        s.pack(fill="both", expand=True)
        self.v = {k: (tk.BooleanVar if k in ("aktiv", "websuche") else tk.StringVar)(value=self.profil[k])
                  for k in ("name", "aktiv", "verlag", "reihe", "autor", "thema", "domains", "abschnitt", "websuche")}
        z = ttk.Frame(s)
        z.pack(anchor="w", fill="x")
        ttk.Label(z, text=_("Name:")).pack(side="left")
        self.name_feld = ttk.Entry(z, textvariable=self.v["name"], width=34)
        self.name_feld.pack(side="left", padx=8)
        ttk.Checkbutton(z, text=_("Active"), variable=self.v["aktiv"]).pack(side="left", padx=8)
        ttk.Label(s, text=_("Applies to"), style="Ueberschrift.TLabel").pack(anchor="w", pady=(12, 2))
        g = ttk.Frame(s)
        g.pack(anchor="w", fill="x", padx=(22, 0))
        for zeile, (k, text) in enumerate((("verlag", _("Publisher:")), ("reihe", _("Series:")),
                                           ("autor", _("Author:")))):
            ttk.Label(g, text=text).grid(row=zeile, column=0, sticky="w", pady=1)
            ttk.Entry(g, textvariable=self.v[k], width=46).grid(row=zeile, column=1, sticky="w", padx=8, pady=1)
        self._hinweis(s, _("Parts of names, separated by commas. One match is enough. All empty: every book."))
        ttk.Label(s, text=_("Where Claude looks"), style="Ueberschrift.TLabel").pack(anchor="w", pady=(6, 2))
        ttk.Label(s, text=_("Pages to fetch (one address per line, in this order):")).pack(anchor="w")
        r = tk.Frame(s, highlightthickness=1, borderwidth=0)
        r.pack(anchor="w", fill="x", padx=(22, 0))
        farbe = kth.PALETTE["dunkel" if eltern.app.dark_mode.get() else "hell"]
        r.configure(highlightbackground=farbe["rahmen"], highlightcolor=farbe["rahmen"])
        self.seiten = tk.Text(r, height=4, wrap="none", borderwidth=0, highlightthickness=0, padx=4, pady=2,
                              font=kth.schrift(9), bg=farbe["feld"], fg=farbe["feld_fg"],
                              insertbackground=farbe["feld_fg"])
        self.seiten.pack(fill="x")
        self.seiten.insert("1.0", self.profil["seiten"])
        self._hinweis(s, _("Placeholders: {title}, {author}, {series} as a wiki page name, {title_q} and {author_q} "
                           "for search addresses, {base} = title without \"Omnibus\". Empty: search only."))
        g = ttk.Frame(s)
        g.pack(anchor="w", fill="x", padx=(22, 0))
        for zeile, (k, text) in enumerate((("domains", _("Further allowed sites:")),
                                           ("abschnitt", _("Section with the blurb:")), ("thema", _("Topic:")))):
            ttk.Label(g, text=text).grid(row=zeile, column=0, sticky="w", pady=1)
            ttk.Entry(g, textvariable=self.v[k], width=34).grid(row=zeile, column=1, sticky="w", padx=8, pady=1)
        self._hinweis(s, _("Further sites separated by commas, e.g. tor.com; the sites of the addresses above are "
                           "always allowed. Section and topic are optional hints for Claude, e.g. \"Official "
                           "Description\" or \"Star Wars\"."))
        ttk.Checkbutton(s, text=_("Web search if no page fits"), variable=self.v["websuche"]).pack(anchor="w")
        self._hinweis(s, _("Only in the allowed sites; without any, on the whole web."))
        self.bind("<Escape>", lambda ev: self.destroy())
        self.name_feld.focus_set()
        self.grab_set()
        self.wait_window()

    def _hinweis(self, eltern, text):
        ttk.Label(eltern, text=text, style="Hinweis.TLabel", wraplength=520, justify="left").pack(
            anchor="w", pady=(0, 6), padx=(22, 0))

    def ok(self):
        p = dict(self.profil)
        for k, var in self.v.items():
            p[k] = var.get().strip() if isinstance(var.get(), str) else var.get()
        p["seiten"] = "\n".join(z.strip() for z in self.seiten.get("1.0", "end").splitlines() if z.strip())
        if not p["name"]:
            p["name"] = _("Profile")
        if not p.get("id"):
            p["id"] = blurbs.profile_id({"name": p["name"]})
        self.ergebnis = p
        self.destroy()
