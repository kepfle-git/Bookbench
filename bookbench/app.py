# -*- coding: utf-8 -*-
"""
app.py - Hauptfenster von Bookbench (Gestaltung nach dem
Designleitfaden des Keller-Nietprogramm-Tools, Seitenleiste nach 5a).

  Menüleiste     Datei, Bearbeiten, Ansicht, Hilfe
  Werkzeugleiste links die Aktionen des aktuellen Bereichs, rechts Hilfe
  Seitenleiste   Bibliothek, Kapitel, Klappentexte, Metadaten, Wörterbuch, E-Reader, Vorschau (keller_navigation)
  Statuszeile    kurze Rückmeldungen

Bereiche:
  Bibliothek     Tabelle aller Bücher, Suche und Filter
  Kapitel        Bücherliste links, Inhaltsverzeichnis alt/neu rechts (Namen und Ebenen
                 änderbar), Textanfang darunter
  Klappentexte   Bücherliste links, Klappentext zum Bearbeiten rechts, Nachschlagen per API
  Metadaten      Titel, Autoren, Reihe, Verlag, Sprache, ISBN, Schlagwörter, eigene Calibre-Spalten und
                 rechts daneben das Cover (ui/area_metadata mit ui/area_covers, seit 1.3)
  Wörterbuch     eigenes Wörterbuch (wikidict-Datenbank) lesen, bearbeiten, Lücken füllen
                 (kobo_bereich_woerterbuch)
  E-Reader       angeschlossener Kobo/Kindle/PocketBook, KOReader-Einstellungen sichern, Wörterbücher
                 (ui/area_device, Kennung "kobo")
  Vorschau       Buch im Desktop-KOReader mit den Einstellungen vom Gerät zeigen (kobo_bereich_vorschau);
                 nur Linux/macOS, der Desktop-KOReader ist optional

Die Daten liegen in kobo_daten (Buch), die Logik in tocfix/tocreport/blurbs.
Langsames (Einlesen, Nachschlagen) läuft in einem Hilfsthread; Ergebnisse kommen
über eine Queue zurück, die Oberfläche fasst nur der Hauptthread an
(hintergrund() für einfache Aufgaben: Ergebnistext in die Statuszeile).
"""
import base64
import io
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from types import SimpleNamespace


from bookbench.i18n import N_, _, ngettext  # noqa: E402  (zuerst: legt die Sprache fest)
import keller_icons as kic          # noqa: E402
import keller_navigation as knv     # noqa: E402
import keller_streifen as kst       # noqa: E402
import keller_theme as kth          # noqa: E402
from bookbench.ui import area_device as kbk     # noqa: E402
from bookbench.ui import area_metadata as kbm   # noqa: E402
from bookbench.ui import area_preview as kbv  # noqa: E402
from bookbench.ui import area_dictionary as kbw  # noqa: E402
from bookbench.core import blurbs                       # noqa: E402
from bookbench.core import library as kd             # noqa: E402
from bookbench.ui import settings as kei    # noqa: E402
from bookbench.ui import help as khi            # noqa: E402
from bookbench.ui import list_filter as klf    # noqa: E402
from bookbench.ui import table_columns as ktc  # noqa: E402
from bookbench.ui import icons as ksy          # noqa: E402
from bookbench.ui import updates as kup        # noqa: E402
from bookbench.preview import emulator as kv          # noqa: E402
from bookbench.ui.help import PROGRAMM, VERSION  # noqa: E402

MARK = {
    "hell": {"rot": "#d9534f", "gelb": "#e8a317", "gruen": "#4caf50", "warn": "#d9534f"},
    "dunkel": {"rot": "#d9534f", "gelb": "#e8a317", "gruen": "#4caf50", "warn": "#ff6b61"},
}
COVER_HOEHE = 96                    # px, Cover in den Kopfzeilen von Kapitel und Klappentexte
WARNZEILE = {"hell": "#f6c9c9", "dunkel": "#6b2b2b"}
OHNEZEILE = {"hell": "#fbeec9", "dunkel": "#4f4220"}      # nur Nummer, kein Name: dezenter als Warnung
kst.TEXTE.update(rot=_("changed, not yet applied"), gelb=_("applied, not yet saved"),
                 gruen=_("saved (since opening)"))

# Filter der Bibliothek: nur noch allgemeine; die Filter nach Kapiteln, Klappentexten und Covern
# stehen seit 1.0.5 über den Listen der Bereiche (_kap_filter, _kt_filter, CoverBereich.FILTER)
FILTER = (_("All books"), _("Changed"), _("Unreadable files"), _("No series in the EPUB"))
SPALTEN = (("titel", _("Title"), 300), ("reihe", _("Series"), 200), ("nummer", _("No."), 46), ("autor", _("Author"), 150),
           ("kapitel", _("Chapters"), 150), ("klappentext", _("Blurb"), 100), ("cover", _("Cover"), 90),
           ("verlag", _("Publisher"), 140), ("sprache", _("Language"), 70), ("isbn", "ISBN", 120))
SPALTEN_AUS = ("verlag", "sprache", "isbn")      # seit 1.3: standardmäßig ausgeblendet (Ansicht > Spalten)


def baumlinien(tiefen):
    """Je Zeile die Zeichen vor dem Eintrag: für jede Ebene ab der zweiten "│" (Linie
    läuft weiter), " " (keine) und für die eigene Ebene "├" oder "└" (letzter Eintrag
    unter demselben Eltern-Eintrag). Ebenen werden auf die flachste Ebene bezogen."""
    if not tiefen:
        return []
    basis = min(tiefen)
    t = [x - basis + 1 for x in tiefen]

    def weiter(i, ebene):
        for x in t[i + 1:]:
            if x < ebene:
                return False
            if x == ebene:
                return True
        return False
    erg = []
    for i, d in enumerate(t):
        teile = ["│" if weiter(i, ebene) else " " for ebene in range(2, d)]
        if d >= 2:
            teile.append("├" if weiter(i, d) else "└")
        erg.append(teile)
    return erg


def _nr(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 1e9


class App(tk.Tk):
    def __init__(self, ordner=None, bereich=None, buch=None, geometrie=None):
        super().__init__()
        self._start_bereich, self._start_buch = bereich, buch
        self._popen = subprocess.Popen           # Tests ersetzen das, um den Neustart abzufangen
        self.e = kei.laden()
        zuletzt = self.e.get("bereich_zuletzt")      # wird beim ersten Bereichswechsel überschrieben
        self.darstellung = tk.StringVar(value=self.e["darstellung"])
        self.dark_mode = tk.BooleanVar(value=kth.ist_dunkel(self.e["darstellung"]))
        self.tooltips_an = tk.BooleanVar(value=self.e["tooltips"])
        self.status_liste = tk.BooleanVar(value=self.e["status_liste"])
        self.status = tk.StringVar(value=_("Open a folder (Ctrl+O)."))
        self.buecher = []                    # [kd.Buch]
        self.nach_schluessel = {}
        self.ordner = None
        self.calibre_wurzel, self.calibre_eintraege = None, []
        self.entscheidungen = kd.json_laden(kd.ENTSCHEIDUNGEN)
        self.cache = kd.json_laden(kd.KLAPPENTEXT_CACHE)
        self._q = queue.Queue()
        self.updates = kup.Updates(self)     # Suche nach neuen Versionen (ui/updates.py)
        self._arbeit = None                  # Name der laufenden Hintergrundarbeit
        self._tipp_job = self._tipp = None
        self._ikonen = {}
        self._hilfe = None
        self._bearbeiter = None              # Eingabefeld beim Bearbeiten einer Zelle
        self._kt_laden = False               # Klappentext-Feld wird gerade programmseitig gefüllt
        self.cover_an = tk.BooleanVar(value=self.e["cover"])
        self._cover, self._cover_hinweis = {}, False
        self._linien_font, self._linien_teil = None, {}

        self.title(f"{PROGRAMM} {VERSION}")
        self.geometry(geometrie or self.e["fenster"])
        self.minsize(860, 520)
        try:                                  # Programmsymbol (tools/make_app_icon.py), sonst das der Seitenleiste
            self._programmsymbol = tk.PhotoImage(file=str(Path(__file__).resolve().parent / "ui" / "bookbench.png"))
        except tk.TclError:
            self._programmsymbol = tk.PhotoImage(data=ksy.HELL["bibliothek_aktiv"])
        self.iconphoto(True, self._programmsymbol)
        self._menue()
        self._werkzeugleiste()
        self.statuszeile = ttk.Label(self, textvariable=self.status, anchor="w", padding=(6, 2))
        self.statuszeile.pack(side="bottom", fill="x")
        self._hinweisleiste_bauen()
        self.nb = knv.NaviNotebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(4, 0))
        self.navi = knv.Navigation(self, self.nb, {"hell": ksy.HELL, "dunkel": ksy.DUNKEL},
                                   dunkel=self.dark_mode.get(), ausgeklappt=self.e["navi_ausgeklappt"],
                                   offen=self.e["navi_offen"],
                                   merken=lambda k, w: self.e.__setitem__("navi_" + k, w))
        self.navi.pack(side="left", fill="y", before=self._wz_rahmen)
        self.statuszeile.pack(side="bottom", fill="x", before=self.navi)
        self.navi.tastenkuerzel(self)
        self._bibliothek_bauen()
        self._kapitel_bauen()
        self._klappentext_bauen()
        self.OHNEZEILE = OHNEZEILE
        self.metadaten = kbm.MetadatenBereich(self)      # legt auch self.cover an (Cover-Tafel darin)
        self.woerterbuch = kbw.WoerterbuchBereich(self)
        self.kobo = kbk.KoboBereich(self)
        # Vorschau nur, wo es einen Desktop-KOReader geben kann (nicht unter Windows)
        self.vorschau = kbv.VorschauBereich(self) if kv.verfuegbar() else None
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._bereich_gewechselt())
        self._theme_anwenden()
        self._bereich_gewechselt()
        self.protocol("WM_DELETE_WINDOW", self.beenden)
        for k, f in (("<Control-o>", self.ordner_oeffnen), ("<F5>", self.neu_einlesen), ("<Control-s>", self.speichern),
                     ("<Control-Return>", self.uebernehmen), ("<F1>", self.hilfe),
                     ("<Control-f>", self._suche_fokus)):
            self.bind_all(k, lambda e, f=f: (f(), "break")[1])
        self.after(100, self._abholen)
        start = ordner or (self.e.get("ordner") if self.e.get("start_ordner", True) else None)
        if start and Path(start).is_dir():
            self.after(50, lambda: self.laden(start))
        if not bereich and self.e.get("start_bereich") == "zuletzt":
            bereich = zuletzt
        if bereich:
            self.after(60, lambda: self.bereich_zeigen(bereich))
        self.after(4000, self.updates.automatisch)     # nach dem Start, damit das Fenster schon steht

    # ================================================================ Rahmen
    def _menue(self):
        leiste = tk.Menu(self)
        m = tk.Menu(leiste, tearoff=False)
        m.add_command(label=_("Open folder …"), accelerator=_("Ctrl+O"), command=self.ordner_oeffnen)
        self._zuletzt = tk.Menu(m, tearoff=False, postcommand=self._zuletzt_fuellen)
        m.add_cascade(label=_("Recently opened"), menu=self._zuletzt)
        m.add_command(label=_("Reload"), accelerator="F5", command=self.neu_einlesen)
        m.add_command(label=_("Close library"), command=self.bibliothek_schliessen)
        m.add_separator()
        m.add_command(label=_("Save"), accelerator=_("Ctrl+S"), command=self.speichern)
        m.add_separator()
        m.add_command(label=_("Settings …"), command=lambda: kei.EinstellungsDialog(self))
        m.add_separator()
        m.add_command(label=_("Quit"), command=self.beenden)
        leiste.add_cascade(label=_("File"), menu=m, underline=0)
        b = tk.Menu(leiste, tearoff=False)
        b.add_command(label=_("Apply"), accelerator=_("Ctrl+Enter"), command=self.uebernehmen)
        b.add_command(label=_("Apply all chapter suggestions"), command=self.alle_uebernehmen)
        b.add_separator()
        b.add_command(label=_("Chapters: restore suggestions"), command=self.kapitel_vorschlaege)
        b.add_command(label=_("Chapters: restore original"), command=self.kapitel_original)
        b.add_command(label=_("Chapters: level up"), accelerator=_("Shift+Tab"), command=lambda: self.ebene(-1))
        b.add_command(label=_("Chapters: level down"), accelerator="Tab", command=lambda: self.ebene(1))
        b.add_separator()
        b.add_command(label=_("Look up blurb"), command=self.klappentext_nachschlagen)
        b.add_command(label=_("Look up all missing blurbs"), command=self.klappentexte_alle)
        b.add_separator()
        b.add_command(label=_("Cover from file …"), command=lambda: self._cover_aktion("aus_datei"))
        b.add_command(label=_("Look up cover"), command=lambda: self._cover_aktion("nachschlagen"))
        b.add_command(label=_("Look up all missing covers"), command=lambda: self.cover.alle_ohne())
        b.add_command(label=_("Show cover large"), command=lambda: self._cover_aktion("gross"))
        b.add_separator()
        b.add_command(label=_("Take series and blurbs from Calibre"), command=self.calibre_uebernehmen)
        b.add_command(label=_("Metadata from Calibre (this book)"),
                      command=lambda: self._metadaten_aktion("alle_von_calibre"))
        b.add_command(label=_("Fill metadata gaps from Calibre"), command=lambda: self.metadaten.luecken_fuellen())
        leiste.add_cascade(label=_("Edit"), menu=b, underline=0)
        k = tk.Menu(leiste, tearoff=False)
        k.add_command(label=_("Find e-reader"), command=lambda: self.kobo.suchen(still=False))
        k.add_command(label=_("Open books on the e-reader"), command=lambda: self.kobo.buecher_oeffnen())
        k.add_separator()
        k.add_command(label=_("Back up KOReader settings"), command=lambda: self.kobo.sichern())
        k.add_command(label=_("Restore backup …"), command=lambda: self.kobo.zurueckspielen())
        k.add_command(label=_("Copy dictionary"), command=lambda: self.kobo.woerterbuch_kopieren())
        k.add_separator()
        k.add_command(label=_("Eject"), command=lambda: self.kobo.auswerfen())
        w = tk.Menu(leiste, tearoff=False)
        w.add_command(label=_("New dictionary …"), command=lambda: self._woerterbuch(lambda b: b.anlegen()))
        w.add_command(label=_("Open dictionary …"), command=lambda: self._woerterbuch(lambda b: b.oeffnen_dialog()))
        w.add_command(label=_("Properties …"), command=lambda: self._woerterbuch(lambda b: b.eigenschaften()))
        w.add_command(label=_("Take changes from a StarDict folder …"),
                      command=lambda: self._woerterbuch(lambda b: b.aus_stardict_uebernehmen()))
        w.add_separator()
        w.add_command(label=_("New entry"), command=lambda: self._woerterbuch(lambda b: b.neu()))
        w.add_command(label=_("Apply"), accelerator=_("Ctrl+Enter"),
                      command=lambda: self._woerterbuch(lambda b: b.uebernehmen()))
        w.add_command(label=_("Discard"), command=lambda: self._woerterbuch(lambda b: b.verwerfen()))
        w.add_command(label=_("Discard own version (original)"),
                      command=lambda: self._woerterbuch(lambda b: b.original()))
        w.add_separator()
        w.add_command(label=_("Claude: search the web"), command=lambda: self._woerterbuch(lambda b: b.ki("suche")))
        w.add_command(label=_("Claude: summarize from a page …"),
                      command=lambda: self._woerterbuch(lambda b: b.ki("link")))
        w.add_command(label=_("Claude: from own knowledge (unverified)"),
                      command=lambda: self._woerterbuch(lambda b: b.ki("wissen")))
        w.add_separator()
        w.add_command(label=_("Ignore / remove"), command=lambda: self._woerterbuch(lambda b: b.entfernen()))
        w.add_command(label=_("Bring back"), command=lambda: self._woerterbuch(lambda b: b.wiederherstellen()))
        w.add_separator()
        w.add_command(label=_("Build dictionary"), command=lambda: self._woerterbuch(lambda b: b.erzeugen()))
        w.add_command(label=_("Steps (from the wiki)"),
                      command=lambda: self._woerterbuch(lambda b: (b.ansicht.set(kbw.ANSICHTEN[3]), b.liste_fuellen())))
        leiste.add_cascade(label=_("Dictionary"), menu=w, underline=0)
        leiste.add_cascade(label=_("E-reader"), menu=k, underline=0)
        if kv.verfuegbar():
            v = tk.Menu(leiste, tearoff=False)
            # die Befehle gehören dem Bereich, der hier noch nicht gebaut ist
            for text, f in ((N_("Start"), "starten"), (None, None),
                            (N_("Take profile from the e-reader"), "vom_kobo"),
                            (N_("Take profile from a backup"), "aus_sicherung"), (N_("Other file …"), "datei_waehlen"),
                            (None, None), (N_("Find KOReader"), "koreader_suchen_menue"),
                            (N_("Choose KOReader …"), "koreader_waehlen"), (N_("Open profile folder"), "profil_oeffnen")):
                if text is None:
                    v.add_separator()
                else:
                    v.add_command(label=_(text), command=lambda f=f: self._vorschau(f))
            leiste.add_cascade(label=_("Preview"), menu=v, underline=0)
        a = tk.Menu(leiste, tearoff=False)
        for wert, text in (("hell", _("Light")), ("dunkel", _("Dark")), ("system", _("Like the system"))):
            a.add_radiobutton(label=text, value=wert, variable=self.darstellung, command=self._darstellung)
        a.add_separator()
        a.add_command(label=_("Sidebar on/off"), accelerator=_("Ctrl+B"), command=lambda: self.navi.umschalten())
        a.add_checkbutton(label=_("Status in the lists"), variable=self.status_liste, command=self._streifen_umschalten)
        sp = tk.Menu(a, tearoff=False)
        sp.configure(postcommand=lambda: self.tabellen_spalten.menue_fuellen(sp))
        a.add_cascade(label=_("Library columns"), menu=sp)
        a.add_checkbutton(label="Cover", variable=self.cover_an, command=self._cover_umschalten)
        a.add_checkbutton(label="Tooltips", variable=self.tooltips_an,
                          command=lambda: self.e.__setitem__("tooltips", self.tooltips_an.get()))
        leiste.add_cascade(label=_("View"), menu=a, underline=0)
        h = tk.Menu(leiste, tearoff=False)
        h.add_command(label=_("Help"), accelerator="F1", command=self.hilfe)
        h.add_command(label=_("Check for updates …"), command=lambda: self.updates.pruefen(von_hand=True))
        h.add_separator()
        h.add_command(label=_("About"), command=lambda: messagebox.showinfo(
            _("About"), f"{PROGRAMM} {VERSION}\n\n" + _("Chapter names, blurbs and settings for KOReader "
                                                           "on the e-reader."), parent=self))
        leiste.add_cascade(label=_("Help"), menu=h, underline=0)
        self.config(menu=leiste)

    def _woerterbuch(self, aktion):
        """Menübefehl des Wörterbuchs: Bereich zeigen, dann ausführen."""
        if self._bereich() != "woerterbuch":
            self.nb.select(self.woerterbuch.seite)
            self.update_idletasks()
        aktion(self.woerterbuch)

    def _vorschau(self, name):
        """Menübefehl der Vorschau: Bereich zeigen, dann ausführen."""
        if self._bereich() != "vorschau":
            self.nb.select(self.vorschau.seite)
            self.update_idletasks()
        getattr(self.vorschau, name)()

    def _zuletzt_fuellen(self):
        self._zuletzt.delete(0, "end")
        for o in self.e.get("letzte_ordner", [])[:8]:
            self._zuletzt.add_command(label=o, command=lambda o=o: self.laden(o))
        if not self.e.get("letzte_ordner"):
            self._zuletzt.add_command(label=_("(empty)"), state="disabled")

    def _werkzeugleiste(self):
        wz = self._wz_rahmen = ttk.Frame(self, padding=(4, 3))
        wz.pack(side="top", fill="x")
        # Designleitfaden 2.: links die Aktionen des Bereichs, rechts die globalen Knöpfe - Öffnen, Neu
        # einlesen und Speichern gelten für alle Bereiche und stehen deshalb rechts, vor Hilfe (seit 1.0.4)
        self._wz_bereich, self._wz_rechts = ttk.Frame(wz), ttk.Frame(wz)
        self._wz_bereich.pack(side="left")
        self._wz_rechts.pack(side="right")
        self._wz = []
        ttk.Separator(self._wz_rechts, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
        self._wz_knopf(self._wz_rechts, "oeffnen", _("Open"), self.ordner_oeffnen, _("Open books folder (Ctrl+O)"))
        self._wz_knopf(self._wz_rechts, "neu_laden", _("Reload"), self.neu_einlesen, _("Reload folder (F5)"))
        self._wz_knopf(self._wz_rechts, "speichern", _("Save"), self.speichern,
                       _("Write applied changes to the files, with backup (Ctrl+S)"))
        ttk.Separator(self._wz_rechts, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
        self._wz_knopf(self._wz_rechts, "hilfe", _("Help"), self.hilfe, _("Help for the current area (F1)"))

    def _hinweisleiste_bauen(self):
        """Leiste unter der Werkzeugleiste, nur sichtbar, wenn der geöffnete Ordner nicht mehr da ist
        (ordner_pruefen); Farbe wie Warnzeilen, gesetzt in _theme_anwenden."""
        h = self.hinweisleiste = tk.Frame(self, padx=8, pady=4)
        h._feste_farben = True
        self.hinweis_text = tk.Label(h, text="", anchor="w", justify="left")
        self.hinweis_text._feste_farben = True
        ttk.Button(h, text=_("Close library"), command=self.bibliothek_schliessen).pack(side="right")
        self.hinweis_text.pack(side="left", fill="x", expand=True)
        # Umbruch an der wirklichen Breite (neben dem Knopf), auch beim Ändern der Fenstergröße
        self.hinweis_text.bind("<Configure>", lambda e: self.hinweis_text.configure(wraplength=max(200, e.width - 8)))
        self._ordner_weg = False

    def ordner_pruefen(self):
        """Ist der geöffnete Ordner noch da? Sonst Hinweisleiste (Bibliothek bleibt sichtbar, Speichern
        verweigert _nicht_erreichbar). Aufgerufen bei jeder Gerätesuche (area_device)."""
        weg = bool(self.ordner) and not self._arbeit and not Path(self.ordner).is_dir()
        if weg == self._ordner_weg:
            return
        self._ordner_weg = weg
        if weg:
            self.hinweis_text.configure(text="⚠ " + _(
                "The folder {ordner} is no longer reachable (e-reader unplugged?). The library stays visible, "
                "but saving only works again once the folder is back.").format(ordner=self.ordner))
            self.hinweisleiste.pack(side="top", fill="x", after=self._wz_rahmen, padx=8, pady=(4, 0))
        else:
            self.hinweisleiste.pack_forget()
            if self.ordner:
                self.status.set(_("The folder {ordner} is reachable again.").format(ordner=self.ordner))

    def bibliothek_schliessen(self, still=False):
        """Geöffneten Ordner schließen (ungespeicherte Änderungen nach Rückfrage verwerfen)."""
        if self._arbeit or not self.ordner:
            return
        if not still and not self._aenderungen_verwerfen_ok():
            return
        self._bearbeiter_weg(speichern=False)
        self.ordner = None
        self.buecher, self.nach_schluessel = [], {}
        self.calibre_wurzel, self.calibre_eintraege = None, []
        self._ordner_weg = True                      # damit ordner_pruefen die Leiste wegnimmt
        self.ordner_pruefen()
        self._alles_neu_zeichnen()
        if not still:
            self.status.set(_("Library closed."))

    def _wz_knopf(self, eltern, symbol, text, befehl, tipp):
        k = tk.Label(eltern, text=text, compound="left", padx=4, pady=3, borderwidth=0, cursor="hand2")
        k._feste_farben = True
        k.pack(side="left", padx=1)
        k.bind("<Enter>", lambda e: (k.configure(bg=self._farben["knopf_aktiv"]), self._tipp_planen(k, tipp)))
        k.bind("<Leave>", lambda e: (k.configure(bg=self._farben["bg"]), self._tipp_weg()))
        k.bind("<ButtonRelease-1>", lambda e: (self._tipp_weg(), befehl()))
        self._wz.append((k, symbol))
        if hasattr(self, "_farben"):
            self._knopf_faerben(k, symbol)
        return k

    def _knopf_faerben(self, k, symbol):
        symbole = dict(kic.DUNKEL, **ksy.WZ_DUNKEL) if self.dark_mode.get() else dict(kic.HELL, **ksy.WZ_HELL)
        if symbol in symbole:
            schl = (symbol, self.dark_mode.get())
            if schl not in self._ikonen:
                self._ikonen[schl] = tk.PhotoImage(data=symbole[symbol])
            k.configure(image=self._ikonen[schl])
        k.configure(bg=self._farben["bg"], fg=self._farben["fg"])

    def _wz_bereich_bauen(self, name):
        for w in self._wz_bereich.winfo_children():
            self._wz = [(k, s) for k, s in self._wz if k is not w]
            w.destroy()
        if name == "bibliothek":
            if self.e.get("calibre_an", True):
                self._wz_knopf(self._wz_bereich, "uebernehmen", _("From Calibre"), self.calibre_uebernehmen,
                               _("Take series, number and blurb from metadata.calibre where the EPUB lacks them"))
        elif name == "kapitel":
            self._wz_knopf(self._wz_bereich, "uebernehmen", _("Apply"), self.uebernehmen,
                           _("Apply the New column for this book (Ctrl+Enter)"))
            self._wz_knopf(self._wz_bereich, "pruefen", _("Apply all"), self.alle_uebernehmen,
                           _("Apply the suggestions of all books without questionable entries"))
            ttk.Separator(self._wz_bereich, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
            self._wz_knopf(self._wz_bereich, "ausruecken", _("Up"), lambda: self.ebene(-1),
                           _("Move the selected entries with their sub-entries one level up (Shift+Tab)"))
            self._wz_knopf(self._wz_bereich, "einruecken", _("Down"), lambda: self.ebene(1),
                           _("Move the selected entries with their sub-entries one level down (Tab)"))
            ttk.Separator(self._wz_bereich, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
            self._wz_knopf(self._wz_bereich, "rueckgaengig", _("Suggestions"), self.kapitel_vorschlaege,
                           _("Reset the book to the suggestions"))
            self._wz_knopf(self._wz_bereich, "zurueckschreiben", _("Original"), self.kapitel_original,
                           _("Reset the book to the unchanged table of contents"))
        elif name == "metadaten":
            self.metadaten.werkzeug(self._wz_bereich)
        elif name == "kobo":
            self.kobo.werkzeug(self._wz_bereich)
        elif name == "vorschau":
            self.vorschau.werkzeug(self._wz_bereich)
        elif name == "woerterbuch":
            self.woerterbuch.werkzeug(self._wz_bereich)
        else:
            self._wz_knopf(self._wz_bereich, "suchen", _("Look up"), self.klappentext_nachschlagen,
                           _("Look up the blurb of this book: free sources first, then Claude (about 1-2 cents)"))
            self._wz_knopf(self._wz_bereich, "neu_laden", _("Look up all"), self.klappentexte_alle,
                           _("Look up all books without a blurb, in the background"))
            ttk.Separator(self._wz_bereich, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
            self._wz_knopf(self._wz_bereich, "uebernehmen", _("Apply"), self.uebernehmen,
                           _("Apply the text (Ctrl+Enter)"))
            self._wz_knopf(self._wz_bereich, "rueckgaengig", _("Discard"), self.klappentext_verwerfen,
                           _("Restore the text from the file"))
            if self.e.get("calibre_an", True):
                ttk.Separator(self._wz_bereich, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
                self._wz_knopf(self._wz_bereich, "oeffnen", _("From Calibre"), self.klappentext_aus_calibre,
                               _("Put the description from metadata.calibre into the text field"))

    # -- Tooltips als Einblendung (kein eigenes Fenster) -------------------------
    def _tipp_planen(self, widget, text):
        self._tipp_weg()
        if self.tooltips_an.get():
            self._tipp_job = self.after(int(self.e.get("tooltip_verzoegerung", 600)),
                                        lambda: self._tipp_zeigen(widget, text))

    def _tipp_zeigen(self, widget, text):
        p = kth.PALETTE["dunkel" if self.dark_mode.get() else "hell"]
        t = self._tipp = tk.Label(self, text=text, bg=p["kopf"], fg=p["fg"], padx=6, pady=3,
                                  relief="solid", borderwidth=1, font=kth.schrift(9))
        t._feste_farben = True
        x = widget.winfo_rootx() - self.winfo_rootx()
        t.place(x=min(x, max(0, self.winfo_width() - t.winfo_reqwidth() - 8)),
                y=widget.winfo_rooty() - self.winfo_rooty() + widget.winfo_height() + 4)

    def _tipp_weg(self):
        if self._tipp_job:
            self.after_cancel(self._tipp_job)
            self._tipp_job = None
        if self._tipp is not None:
            self._tipp.destroy()
            self._tipp = None

    # -- Bausteine ---------------------------------------------------------------
    def _seite(self, titel, symbol):
        s = ttk.Frame(self.nb, padding=(10, 8, 4, 6))
        s.nav_symbol = symbol
        self.nb.add(s, text=titel)
        return s

    def _listenrahmen(self, eltern):
        r = tk.Frame(eltern, highlightthickness=1, borderwidth=0)
        self._rahmen_liste.append(r)
        return r

    def _buchliste(self, eltern, auswahl, status_fn=None, streifen=True, filter=None, geaendert=None, kopf=None):
        """Schmale Bücherliste mit Scrollbalken in einem Rahmen, mit Statusstreifen
        (streifen=False: ohne, z. B. in der Vorschau). Darüber die Such-/Filterzeile
        (list_filter.ListenFilter, als lb.filter): filter = [(kennung, Text, Prüfung)],
        geaendert() füllt die Liste neu, kopf = Label "Bücher:" darüber."""
        lf = klf.ListenFilter(eltern, filter or [("alle", "All books", None)], geaendert or (lambda: None), kopf)
        r = self._listenrahmen(eltern)
        r.pack(fill="both", expand=True)
        lb = tk.Listbox(r, width=32, borderwidth=0, highlightthickness=0, exportselection=False,
                        activestyle="none")
        sb = ttk.Scrollbar(r, orient="vertical", command=lb.yview)
        sb.pack(side="right", fill="y")
        lb.pack(side="left", fill="both", expand=True)
        lb.bind("<<ListboxSelect>>", lambda e: auswahl())
        lb.filter = lf
        if not streifen:
            lb.configure(yscrollcommand=sb.set)
            return lb
        st = kst.StatusStreifen(self, lb, r, status_fn or self._status_von_name)
        lb.configure(yscrollcommand=lambda *a: (sb.set(*a), st.zeichnen()))
        if self.status_liste.get():
            st.einpacken()
        self._auswahl_mitzeichnen(lb, st)
        self._streifen.append(st)
        return lb

    @staticmethod
    def _auswahl_mitzeichnen(lb, st):
        """Der Streifen zeichnet die Auswahlmarkierung selbst und erfährt nur über
        <<ListboxSelect>> davon - das kommt bei einer Auswahl aus dem Programm heraus
        (selection_set beim Bereichswechsel usw.) nicht, dann blieb die alte Markierung
        im Streifen stehen. Hier für genau diese Liste umgeleitet (keller_streifen bleibt)."""
        def nachher(echt):
            def neu(*a):
                erg = echt(*a)
                try:
                    st.canvas.after_idle(st.zeichnen)
                except tk.TclError:
                    pass
                return erg
            return neu
        for name in ("selection_set", "selection_clear", "select_set", "select_clear", "delete", "insert"):
            setattr(lb, name, nachher(getattr(lb, name)))
        # Auf einer verdeckten Seite hat die Liste noch keine Zeilenmaße (bbox None): beim Sichtbarwerden
        # neu zeichnen, sonst fehlt die Markierung im Streifen bis zum nächsten Klick
        for w in (lb, st.canvas):
            w.bind("<Map>", lambda e: st.canvas.after_idle(st.zeichnen), add="+")

    def _status_von_name(self, name):
        b = self._listen_buch.get(name)
        return (b.stand(), b.warnung()) if b else (None, None)

    def _status_klappentext(self, name):
        """Klappentext-Liste: Kapitelwarnungen gehören nicht hierher - nur unlesbare
        Dateien und fehlender Klappentext."""
        b = self._listen_buch.get(name)
        return (b.stand(), b.fehler or self._kt_fehlt(b)) if b else (None, None)

    def _kt_fehlt(self, b):
        """Warntext, wenn das Buch (nach dem aktuellen Stand) keinen Klappentext hat."""
        if self._kt_aktueller_text(b).strip():
            return None
        if b.calibre and (b.calibre.get("comments") or "").strip():
            return _("no blurb (Calibre has one: From Calibre)")
        return _("no blurb")

    def _status_von_iid(self, iid):
        b = self.nach_schluessel.get(iid)
        return (b.stand(), b.warnung()) if b else (None, None)

    # ================================================================ Bibliothek
    def _bibliothek_bauen(self):
        self._rahmen_liste, self._streifen, self._listen_buch = [], [], {}
        s = self.seite_bibliothek = self._seite(_("Library"), "bibliothek")
        oben = ttk.Frame(s)
        oben.pack(fill="x", pady=(0, 6))
        ttk.Label(oben, text=_("Search:")).pack(side="left")
        self.suche = tk.StringVar()
        self.suchfeld = ttk.Entry(oben, textvariable=self.suche, width=30)
        self.suchfeld.pack(side="left", padx=(4, 14))
        self.suche.trace_add("write", lambda *a: self._tabelle_fuellen())
        ttk.Label(oben, text=_("Filter:")).pack(side="left")
        self.filter = tk.StringVar(value=FILTER[0])
        cb = ttk.Combobox(oben, textvariable=self.filter, values=FILTER, state="readonly", width=22)
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self._tabelle_fuellen())
        self.ordner_label = ttk.Label(oben, text="", style="Hinweis.TLabel")
        self.ordner_label.pack(side="right")
        r = self._listenrahmen(s)
        r.pack(fill="both", expand=True)
        t = self.tabelle = ttk.Treeview(r, columns=[c for c, __, __ in SPALTEN], show="headings", selectmode="browse")
        for c, text, w in SPALTEN:
            t.heading(c, text=text, command=lambda c=c: self._sortieren(c))
            t.column(c, anchor="e" if c == "nummer" else "w")
        sb = ttk.Scrollbar(r, orient="vertical", command=t.yview)
        sb.pack(side="right", fill="y")
        # waagrecht nur, wenn die Spalten breiter sind als das Fenster (keine Spalte dehnt sich)
        xsb = self.tabelle_xsb = ttk.Scrollbar(r, orient="horizontal", command=t.xview)

        def waagrecht(lo, hi):
            xsb.set(lo, hi)
            if float(lo) <= 0 and float(hi) >= 1:
                xsb.pack_forget()
            elif not xsb.winfo_ismapped():
                xsb.pack(side="bottom", fill="x", before=t)
        t.configure(xscrollcommand=waagrecht)
        t.pack(side="left", fill="both", expand=True)
        self.tabellen_streifen = kst.StatusStreifen(self, t, r, self._status_von_iid,
                                                    lambda iid: self.nach_schluessel[iid].name)
        t.configure(yscrollcommand=lambda *a: (sb.set(*a), self.tabellen_streifen.zeichnen()))
        if self.status_liste.get():
            self.tabellen_streifen.einpacken()
        self._streifen.append(self.tabellen_streifen)
        self.tabellen_spalten = ktc.Spalten(self, t, SPALTEN, aus=SPALTEN_AUS)
        self.tabellen_spalten.anwenden()
        t.bind("<Double-1>", lambda e: self._buch_oeffnen() if t.identify_region(e.x, e.y) == "cell" else None)
        t.bind("<Return>", lambda e: self._buch_oeffnen())
        t.bind("<<TreeviewSelect>>", lambda e: self._tabelle_auswahl(), add="+")

    def _filter_passt(self, b):
        f, such = self.filter.get(), self.suche.get().strip().casefold()
        if such and such not in " ".join((b.titel, b.reihe, b.autor)).casefold():
            return False
        if f == FILTER[1]:
            return b.stand() is not None
        if f == FILTER[2]:
            return bool(b.fehler)
        if f == FILTER[3]:
            return not b.reihe_datei[0] and b.reihe_neu is None
        return True

    def _sortieren(self, spalte, umgekehrt=None):
        """Klick auf den Kopf: nach der Spalte sortieren, nochmal = umgekehrt (umgekehrt=True/False:
        fest, aus dem Kontextmenü). Kein Sortieren direkt nach dem Verschieben einer Spalte."""
        if umgekehrt is None and not self.tabellen_spalten.sortieren_erlaubt():
            return
        alt, rueck = self.e.get("sortierung", ["reihe", False])
        if umgekehrt is None:
            umgekehrt = not rueck if alt == spalte else False
        self.e["sortierung"] = [spalte, umgekehrt]
        self.tabellen_spalten.kopf_beschriften()
        self._tabelle_fuellen()

    def _sortiert(self, buecher):
        spalte, rueck = self.e.get("sortierung", ["reihe", False])
        if spalte == "reihe":
            schl = lambda b: (b.reihe.casefold() or "￿", _nr(b.nummer), b.titel.casefold())
        elif spalte == "nummer":
            schl = lambda b: (_nr(b.nummer), b.titel.casefold())
        elif spalte == "cover":
            schl = lambda b: (self.cover.hoehe(b), b.titel.casefold())       # nach Pixelhöhe, nicht als Text
        else:
            schl = lambda b: (str(self._zelle(b, spalte)).casefold(), b.titel.casefold())
        return sorted(buecher, key=schl, reverse=rueck)

    def _zelle(self, b, spalte):
        if spalte == "kapitel":
            return b.fehler or b.kapitel_zustand()
        if spalte == "klappentext":
            if b.klappentext_neu is not None or b.klappentext_entwurf is not None:
                return _("changed")
            if b.klappentext:
                return blurbs.source_name(b.klappentext_quelle_datei) or _("yes")
            return _("in Calibre") if b.calibre and b.calibre.get("comments") else "-"
        if spalte == "cover":
            if b.cover_neu is not None:
                return _("changed")
            return f"{b.cover_info[0]} × {b.cover_info[1]}" if b.cover_info else "-"
        return getattr(b, spalte)

    def _tabelle_fuellen(self):
        t = self.tabelle
        gewaehlt = t.selection()
        t.delete(*t.get_children())
        sichtbar = [b for b in self._sortiert(self.buecher) if self._filter_passt(b)]
        for b in sichtbar:
            t.insert("", "end", iid=b.schluessel, values=[self._zelle(b, c) for c, __, __ in SPALTEN],
                     tags=("warn",) if b.fehler else ())
        if gewaehlt and t.exists(gewaehlt[0]):
            t.selection_set(gewaehlt[0])
            t.see(gewaehlt[0])
        self.tabellen_streifen.zeichnen()
        if self.buecher:
            self.ordner_label.configure(text=ngettext("{n} of {gesamt} book", "{n} of {gesamt} books", len(self.buecher))
                                        .format(n=len(sichtbar), gesamt=len(self.buecher)) + f"  ·  {self.ordner}")

    def _tabelle_auswahl(self):
        sel = self.tabelle.selection()
        if sel:
            b = self.nach_schluessel[sel[0]]
            zusatz = [b.fehler] if b.fehler else []
            if b.reihe_neu is not None:
                zusatz.append(_("series applied, not yet saved"))
            elif b.reihe_quelle == "Calibre":
                zusatz.append(_("Series from metadata.calibre, not in the EPUB - \"From Calibre\" applies it"))
            elif b.reihe_quelle:
                zusatz.append(_("Series from the {quelle} data, not in the EPUB").format(quelle=b.reihe_quelle))
            self.status.set(" - ".join([b.pfad.name] + zusatz))

    def _buch_oeffnen(self):
        sel = self.tabelle.selection()
        if sel:
            self._auswaehlen(self.kap_liste, self.nach_schluessel[sel[0]])
            self.nb.select(self.seite_kapitel)

    def _suche_fokus(self):
        if self._bereich() == "woerterbuch" and self.woerterbuch.wb:
            self.woerterbuch.suchfeld.focus_set()
            self.woerterbuch.suchfeld.select_range(0, "end")
            return
        bereich = self._bereich()
        liste = {"kapitel": self.kap_liste, "klappentexte": self.kt_liste,
                 "metadaten": getattr(getattr(self, "metadaten", None), "liste", None),
                 "vorschau": getattr(getattr(self, "vorschau", None), "liste", None)}.get(bereich)
        if liste is not None and getattr(liste, "filter", None):
            liste.filter.fokus()
            return
        self.nb.select(self.seite_bibliothek)
        self.suchfeld.focus_set()
        self.suchfeld.select_range(0, "end")

    # ================================================================ Kapitel
    def _kapitel_bauen(self):
        s = self.seite_kapitel = self._seite(_("Chapters"), "kapitel")
        links = ttk.Frame(s)
        links.pack(side="left", fill="y")
        kopf = ttk.Label(links, text=_("Books:"))
        kopf.pack(anchor="w")
        self.kap_liste = self._buchliste(links, self._kapitel_anzeigen, filter=self._kap_filter(),
                                         geaendert=lambda: self._liste_neu(self.kap_liste), kopf=kopf)
        rechts = ttk.Frame(s)
        rechts.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.kap_cover, self.kap_kopf, self.kap_info = self._kopfzeile(rechts)
        teiler = ttk.PanedWindow(rechts, orient="vertical")
        teiler.pack(fill="both", expand=True)
        r = self._listenrahmen(teiler)
        t = self.kap_tabelle = ttk.Treeview(r, columns=("alt", "neu", "hinweis"), show="headings",
                                            selectmode="extended")
        for c, text, w in (("alt", _("Entry"), 200), ("neu", _("New"), 260), ("hinweis", _("Note"), 160)):
            t.heading(c, text=text)
            t.column(c, width=w, minwidth=60, stretch=True)
        sb = ttk.Scrollbar(r, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        teiler.add(r, weight=4)
        unten = ttk.Frame(teiler, padding=(0, 6, 0, 0))
        ttk.Label(unten, text=_("In the book at this point:")).pack(anchor="w")
        tr = self._listenrahmen(unten)
        tr.pack(fill="both", expand=True)
        self.kap_text = tk.Text(tr, height=6, wrap="word", borderwidth=0, highlightthickness=0, padx=6, pady=4,
                                font=kth.schrift(10), state="disabled")
        tsb = ttk.Scrollbar(tr, orient="vertical", command=self.kap_text.yview)
        self.kap_text.configure(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self.kap_text.pack(side="left", fill="both", expand=True)
        teiler.add(unten, weight=1)
        t.bind("<<TreeviewSelect>>", lambda e: self._kapitel_zeile())
        t.bind("<Double-1>", self._zelle_bearbeiten)
        t.bind("<F2>", self._zelle_bearbeiten)
        t.bind("<Delete>", lambda e: self._zeile_original())
        for taste, richtung in (("<Tab>", 1), ("<Alt-Right>", 1), ("<Shift-Tab>", -1), ("<ISO_Left_Tab>", -1),
                                ("<Alt-Left>", -1)):
            try:
                t.bind(taste, lambda e, r=richtung: (self.ebene(r), "break")[1])
            except tk.TclError:                         # ISO_Left_Tab gibt es unter Windows nicht
                pass
        self._kap_buch = None

    def _kopfzeile(self, eltern):
        """Cover links, Titel und Angaben daneben. Gibt (cover, titel, info) zurück."""
        z = ttk.Frame(eltern)
        z.pack(fill="x", pady=(0, 6))
        cover = tk.Label(z, borderwidth=0, highlightthickness=0, cursor="hand2")
        cover.bind("<Button-1>", lambda e: self.cover.gross(getattr(cover, "buch", None)))
        texte = ttk.Frame(z)
        texte.pack(side="left", fill="x", anchor="n")
        kopf = ttk.Label(texte, text=_("Choose a book on the left."), style="Ueberschrift.TLabel")
        kopf.pack(anchor="w")
        info = ttk.Label(texte, text="", style="Hinweis.TLabel")
        info.pack(anchor="w", pady=(2, 0))
        cover.texte = texte
        return cover, kopf, info

    def _cover_zeigen(self, label, b):
        label.buch = b
        bild = self._cover_bild(b) if b and self.cover_an.get() else None
        if bild is None:
            label.configure(image="")
            label.pack_forget()
            return
        label.configure(image=bild)
        label.pack(side="left", padx=(0, 10), before=label.texte)

    def _cover_bild(self, b, hoehe=None):
        """PhotoImage des Titelbilds in der Höhe `hoehe` (zwischengespeichert) oder None.
        JPEG braucht Pillow; ohne Pillow gehen nur PNG und GIF."""
        hoehe = hoehe or int(self.e.get("cover_kopf_hoehe") or COVER_HOEHE)
        try:
            stempel = b.pfad.stat().st_mtime
        except OSError:
            return None
        schl = (str(b.pfad), stempel, hoehe, id(b.cover_neu) if b.cover_neu is not None else None)
        if schl in self._cover:
            return self._cover[schl]
        daten = b.cover_neu if b.cover_neu is not None else kd.cover_lesen(b.pfad)
        bild = None
        if daten:
            try:
                from PIL import Image, ImageTk
                im = Image.open(io.BytesIO(daten))
                im.load()
                breite = max(1, round(im.width * hoehe / im.height))
                bild = ImageTk.PhotoImage(im.convert("RGB").resize((breite, hoehe), Image.LANCZOS), master=self)
            except ImportError:
                try:
                    roh = tk.PhotoImage(data=base64.b64encode(daten).decode(), master=self)
                    faktor = max(1, -(-roh.height() // hoehe))
                    bild = roh.subsample(faktor) if faktor > 1 else roh
                except tk.TclError:                         # JPEG ohne Pillow
                    if not self._cover_hinweis:
                        self._cover_hinweis = True
                        self.status.set(_("JPEG covers need Pillow (pip install pillow)."))
            except Exception:                                # kaputtes Bild
                bild = None
        self._cover[schl] = bild
        return bild

    def _cover_umschalten(self):
        self.e["cover"] = self.cover_an.get()
        self._cover_zeigen(self.kap_cover, self._kap_buch)
        self._cover_zeigen(self.kt_cover, self._kt_buch)

    def _linien(self, teile):
        """Zeichen aus baumlinien() als Text; jede Ebene gleich breit (Proportionalschrift:
        aufgefüllt mit Leerzeichen, schmalen und Haar-Leerzeichen, gemessen in der Schrift
        der Tabelle)."""
        if self._linien_font is None:
            name = ttk.Style().lookup("Treeview", "font") or "TkDefaultFont"
            try:
                self._linien_font = tkfont.nametofont(name)
            except tk.TclError:
                self._linien_font = tkfont.Font(font=name)
            self._linien_teil = {}
        f = self._linien_font
        if not self._linien_teil:
            ziel = f.measure("├─ ")
            for zeichen, text in (("├", "├─"), ("└", "└─"), ("│", "│"), (" ", "")):
                for fueller in (" ", "\u2009", "\u200a"):
                    while f.measure(text + fueller) <= ziel:
                        text += fueller
                self._linien_teil[zeichen] = text
        return "".join(self._linien_teil[z] for z in teile)

    # ================================================================ Listen und Filter
    def _kap_filter(self):
        return [("alle", N_("All books"), None),
                ("vorschlaege", N_("With suggestions"), lambda b: bool(b.vorschlag)),
                ("fragwuerdig", N_("Questionable names"), lambda b: bool(b.warnung())),
                ("ohne_namen", N_("Some without names"), lambda b: b.einzelne_ohne_namen()),
                ("geaendert", N_("Changed chapters"), lambda b: bool(
                    b.neu or b.entwurf is not None or b.tiefen_neu is not None or b.tiefen_entwurf is not None))]

    def _kt_filter(self):
        return [("alle", N_("All books"), None),
                ("ohne", N_("No blurb"), lambda b: bool(self._kt_fehlt(b))),
                ("calibre", N_("Only in Calibre"), lambda b: not self._kt_aktueller_text(b).strip()
                 and bool(b.calibre and (b.calibre.get("comments") or "").strip())),
                ("geaendert", N_("Changed blurb"), lambda b: b.klappentext_neu is not None
                 or b.klappentext_entwurf is not None)]

    def _links_sortiert(self):
        """Bücher wie in den Listen links: nach Reihe, Nummer, Titel - wie im Bookshelf."""
        return sorted(self.buecher, key=lambda b: (b.reihe.casefold() or "\uffff", _nr(b.nummer),
                                                   b.titel.casefold()))

    def _liste_fuellen(self, liste, sortiert, vorher, anzeige):
        """Füllt eine schmale Bücherliste nach ihrem Filter und wählt wieder das bisherige
        Buch (oder das nächste passende, list_filter.nachfolger); anzeige() zeigt es rechts."""
        lf = liste.filter
        sichtbar = [b for b in sortiert if lf.passt(b)]
        liste.delete(0, "end")
        for b in sichtbar:
            liste.insert("end", self._anzeigename(b))
        lf.anzahl(len(sichtbar), len(sortiert))
        ziel = klf.nachfolger(sortiert, vorher, lf.passt) if vorher else None
        if ziel:
            self._auswaehlen(liste, ziel)
        elif vorher and sichtbar:
            # das bisherige ist weggefiltert und es gibt nichts darunter/darüber - erstes nehmen
            self._auswaehlen(liste, sichtbar[0])
        else:
            anzeige()

    def _liste_neu(self, liste):
        """Suche oder Filter einer Liste geändert."""
        anzeige = self._kapitel_anzeigen if liste is self.kap_liste else self._klappentext_anzeigen
        if liste is self.kap_liste:
            self._bearbeiter_weg(speichern=True)
        self._liste_fuellen(liste, self._links_sortiert(), self._aktuelles_buch(liste), anzeige)
        for s in self._streifen:
            s.zeichnen()

    def _aktuelles_buch(self, liste):
        sel = liste.curselection()
        return self._listen_buch.get(liste.get(sel[0])) if sel else None

    @staticmethod
    def _anzeigename(b):
        return getattr(b, "titel_anzeige", None) or b.name

    def _auswaehlen(self, liste, buch):
        """Buch in der Liste wählen und rechts zeigen. Ist es weggefiltert (z. B. Doppelklick in
        der Bibliothek), werden Suche und Filter dieser Liste zurückgesetzt."""
        namen = list(liste.get(0, "end"))
        lf = getattr(liste, "filter", None)
        if self._anzeigename(buch) not in namen and lf and lf.aktiv() and buch in self.buecher:
            lf.zuruecksetzen()
            namen = list(liste.get(0, "end"))
        if self._anzeigename(buch) in namen:
            i = namen.index(self._anzeigename(buch))
            liste.selection_clear(0, "end")
            liste.selection_set(i)
            liste.see(i)
            # direkt aufrufen: <<ListboxSelect>> kommt bei verdeckten Seiten nicht an
            (self._kapitel_anzeigen if liste is self.kap_liste else self._klappentext_anzeigen)()
            for s in self._streifen:
                s.zeichnen()

    def _kapitel_anzeigen(self):
        self._bearbeiter_weg(speichern=True)
        b = self._kap_buch = self._aktuelles_buch(self.kap_liste)
        t = self.kap_tabelle
        t.delete(*t.get_children())
        self._text_setzen(self.kap_text, [])
        if not b:
            self._cover_zeigen(self.kap_cover, None)
            return
        self.kap_kopf.configure(text=b.name)
        self._cover_zeigen(self.kap_cover, b)
        teile = [x for x in (b.autor, f"{b.reihe} {b.nummer}".strip()) if x] + [b.pfad.name]
        if b.uebersprungen:
            teile.append(_("No suggestions: {grund}").format(grund=b.uebersprungen))
        if b.fehler:
            teile.append(b.fehler)
        self.kap_info.configure(text="  ·  ".join(teile))
        aktuell = b.aktuelle_titel()
        tiefen = b.aktuelle_tiefen()
        linien = baumlinien(tiefen)
        for i, (tiefe, titel, href, k) in enumerate(b.zeilen):
            neu = aktuell.get(k, "")
            kand = b.kandidaten.get(k)
            hinweis = "; ".join(kand["reasons"]) if kand and kand["reasons"] and k not in b.neu else ""
            tags = []
            if hinweis:
                tags.append("warn")
            elif kand and (not neu or neu == titel):
                hinweis = _("number only, no name found")     # zählt in "ok (n ohne Namen)"
                tags.append("ohne")
            if tiefen[i] != tiefe:
                hinweis = "; ".join(x for x in (_("Level {alt} → {neu}").format(alt=tiefe, neu=tiefen[i]), hinweis)
                                    if x)
            t.insert("", "end", iid=str(i), values=(self._linien(linien[i]) + titel, neu if neu != titel else "", hinweis),
                     tags=tags)
        self.status.set(f"{b.name}: " + ngettext("{n} entry", "{n} entries", len(b.zeilen)).format(n=len(b.zeilen))
                        + ", " + ngettext("{n} suggestion.", "{n} suggestions.", len(b.vorschlag)).format(n=len(b.vorschlag)))

    def _kapitel_zeile(self):
        b, sel = self._kap_buch, self.kap_tabelle.selection()
        if not (b and sel):
            return
        tiefe, titel, href, k = b.zeilen[int(sel[0])]
        self._text_setzen(self.kap_text, kd.textanfang(b, href))
        hinweis = self.kap_tabelle.set(sel[0], "hinweis")
        if hinweis:
            self.status.set(f"{titel}: {hinweis}")

    def _text_setzen(self, w, zeilen):
        w.configure(state="normal")
        w.delete("1.0", "end")
        w.insert("end", "\n".join(zeilen))
        w.configure(state="disabled")

    # -- Zellen bearbeiten -------------------------------------------------------
    def _zelle_bearbeiten(self, ev=None):
        b, t = self._kap_buch, self.kap_tabelle
        if not b:
            return "break"
        iid = t.identify_row(ev.y) if ev is not None and hasattr(ev, "y") and ev.type == tk.EventType.ButtonPress \
            else (t.selection() or [None])[0]
        if iid is None:
            return "break"
        self._bearbeiter_weg(speichern=True)
        t.selection_set(iid)
        t.see(iid)
        self.update_idletasks()
        box = t.bbox(iid, "neu")
        if not box:
            return "break"
        tiefe, titel, href, k = b.zeilen[int(iid)]
        wert = tk.StringVar(value=t.set(iid, "neu") or titel)
        f = self._bearbeiter = ttk.Entry(t, textvariable=wert)
        f.place(x=box[0], y=box[1], width=box[2], height=box[3])
        f.focus_set()
        f.select_range(0, "end")
        f._ziel = (iid, wert)
        f.bind("<Return>", lambda e: (self._bearbeiter_weg(speichern=True), "break")[1])
        f.bind("<KP_Enter>", lambda e: (self._bearbeiter_weg(speichern=True), "break")[1])
        f.bind("<Escape>", lambda e: (self._bearbeiter_weg(speichern=False), "break")[1])
        f.bind("<FocusOut>", lambda e: self._bearbeiter_weg(speichern=True))
        return "break"

    def _bearbeiter_weg(self, speichern):
        f = self._bearbeiter
        if f is None:
            return
        self._bearbeiter = None
        iid, wert = f._ziel
        f.destroy()
        if speichern:
            self._zeile_setzen(int(iid), wert.get().strip())
        self.kap_tabelle.focus_set()

    def _zeile_setzen(self, index, text):
        b = self._kap_buch
        tiefe, titel, href, k = b.zeilen[index]
        aktuell = b.aktuelle_titel()
        alt = aktuell.get(k, titel)
        neu = text or titel
        if neu == alt:
            return
        if b.entwurf is None:
            b.entwurf = dict(aktuell)
        if neu == titel:
            b.entwurf.pop(k, None)
        else:
            b.entwurf[k] = neu
        self.kap_tabelle.set(str(index), "neu", neu if neu != titel else "")
        self._geaendert(b)
        self.status.set(f"{titel}: " + _("changed, not yet applied (Ctrl+Enter)."))

    def _zeile_original(self):
        for iid in self.kap_tabelle.selection() if self._kap_buch else ():
            self._zeile_setzen(int(iid), "")

    def ebene(self, richtung):
        """Markierte Einträge samt Untereinträgen eine Ebene tiefer (+1) oder höher (-1)."""
        b, t = self._kap_buch, self.kap_tabelle
        if self._bereich() != "kapitel" or not b:
            return
        self._bearbeiter_weg(speichern=True)
        sel = [int(i) for i in t.selection()]
        if not sel:
            self.status.set(_("Select entries in the table, then Tab (down) or Shift+Tab (up)."))
            return
        if b.ebenen_sperre:
            self.status.set(f"{b.name}: " + _("levels cannot be changed - {grund}.").format(grund=b.ebenen_sperre))
            return
        try:
            neu = kd.ebenen_verschieben(b.aktuelle_tiefen(), sel, richtung)
        except ValueError as e:
            self.status.set((_("Cannot move down: {grund}.") if richtung > 0 else _("Cannot move up: {grund}."))
                            .format(grund=e))
            return
        basis = b.tiefen_neu if b.tiefen_neu is not None else b.original_tiefen()
        b.tiefen_entwurf = None if neu == basis else neu
        oben = t.yview()[0]
        self._geaendert(b)
        self._kapitel_anzeigen()
        t.yview_moveto(oben)
        t.selection_set([str(i) for i in sel])
        t.focus(str(sel[0]))
        self.status.set((ngettext("{n} entry moved down (with sub-entries), not yet applied (Ctrl+Enter).",
                                  "{n} entries moved down (with sub-entries), not yet applied (Ctrl+Enter).", len(sel))
                         if richtung > 0 else
                         ngettext("{n} entry moved up (with sub-entries), not yet applied (Ctrl+Enter).",
                                  "{n} entries moved up (with sub-entries), not yet applied (Ctrl+Enter).", len(sel)))
                        .format(n=len(sel)))

    # -- Kapitel: Aktionen -------------------------------------------------------
    def _kapitel_uebernehmen(self, b):
        original = {z[3]: z[1] for z in b.zeilen}
        b.neu = {k: v for k, v in b.aktuelle_titel().items() if v != original.get(k)}
        b.entwurf = None
        if b.tiefen_entwurf is not None:
            b.tiefen_neu = None if b.tiefen_entwurf == b.original_tiefen() else b.tiefen_entwurf
            b.tiefen_entwurf = None
        for kand in b.kandidaten.values():              # entschieden = nicht mehr fragwürdig
            kand["reasons"] = []
        kd.entscheidungen_merken(b, self.entscheidungen)

    def uebernehmen(self):
        bereich = self._bereich()
        if bereich == "woerterbuch":
            return self.woerterbuch.uebernehmen()
        if bereich == "klappentexte":
            return self._klappentext_uebernehmen()
        if bereich == "metadaten":
            return self.metadaten.uebernehmen()
        if bereich != "kapitel" or not self._kap_buch:
            self.status.set(_("Apply: choose a book in the Chapters or Blurbs area."))
            return
        self._bearbeiter_weg(speichern=True)
        b = self._kap_buch
        self._kapitel_uebernehmen(b)
        kd.json_speichern(kd.ENTSCHEIDUNGEN, self.entscheidungen)
        self._geaendert(b, neu_zeichnen=True)
        self.status.set(f"{b.name}: " + ngettext("{n} chapter name applied, not yet saved.",
                                                  "{n} chapter names applied, not yet saved.", len(b.neu)).format(n=len(b.neu)))

    def alle_uebernehmen(self):
        self._bearbeiter_weg(speichern=True)
        n = 0
        for b in self.buecher:
            if b.vorschlag and b.entwurf is None and b.tiefen_entwurf is None and not b.warnung() and not b.neu:
                self._kapitel_uebernehmen(b)
                n += 1
        kd.json_speichern(kd.ENTSCHEIDUNGEN, self.entscheidungen)
        self._alles_neu_zeichnen()
        offen = sum(1 for b in self.buecher if b.warnung())
        self.status.set(ngettext("Suggestions of {n} book applied.", "Suggestions of {n} books applied.", n).format(n=n) +
                        (" " + ngettext("Please check {n} book with questionable entries one by one.",
                                        "Please check {n} books with questionable entries one by one.", offen)
                         .format(n=offen) if offen else ""))

    def kapitel_vorschlaege(self):
        b = self._kap_buch
        if b:
            b.entwurf, b.neu = None, {}
            b.tiefen_entwurf = b.tiefen_neu = None
            self._geaendert(b, neu_zeichnen=True)
            self.status.set(f"{b.name}: " + _("reset to the suggestions."))

    def kapitel_original(self):
        b = self._kap_buch
        if b:
            b.entwurf = {}
            b.tiefen_entwurf = b.original_tiefen() if b.aktuelle_tiefen() != b.original_tiefen() else None
            self._geaendert(b, neu_zeichnen=True)
            self.status.set(f"{b.name}: " + _("original restored, not yet applied."))

    # ================================================================ Klappentexte
    def _klappentext_bauen(self):
        s = self.seite_klappentext = self._seite(_("Blurbs"), "klappentext")
        links = ttk.Frame(s)
        links.pack(side="left", fill="y")
        kopf = ttk.Label(links, text=_("Books:"))
        kopf.pack(anchor="w")
        self.kt_liste = self._buchliste(links, self._klappentext_anzeigen, self._status_klappentext,
                                        filter=self._kt_filter(), geaendert=lambda: self._liste_neu(self.kt_liste),
                                        kopf=kopf)
        rechts = ttk.Frame(s)
        rechts.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.kt_cover, self.kt_kopf, self.kt_info = self._kopfzeile(rechts)
        r = self._listenrahmen(rechts)
        r.pack(fill="both", expand=True)
        self.kt_text = tk.Text(r, wrap="word", borderwidth=0, highlightthickness=0, padx=8, pady=6,
                               font=kth.schrift(11), undo=True)
        sb = ttk.Scrollbar(r, orient="vertical", command=self.kt_text.yview)
        self.kt_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.kt_text.pack(side="left", fill="both", expand=True)
        self.kt_quelle = ttk.Label(rechts, text="", style="Hinweis.TLabel")
        self.kt_quelle.pack(anchor="w", pady=(4, 0))
        self.kt_text.bind("<<Modified>>", lambda e: self._klappentext_getippt())
        self.kt_text.bind("<Control-Return>", lambda e: (self.uebernehmen(), "break")[1])
        self._kt_buch = None

    def _kt_aktueller_text(self, b):
        if b.klappentext_entwurf is not None:
            return b.klappentext_entwurf
        return b.klappentext_neu if b.klappentext_neu is not None else b.klappentext

    def _klappentext_anzeigen(self):
        b = self._kt_buch = self._aktuelles_buch(self.kt_liste)
        self._kt_laden = True
        self.kt_text.delete("1.0", "end")
        if b:
            self.kt_kopf.configure(text=b.name)
            self._cover_zeigen(self.kt_cover, b)
            info = [x for x in (b.autor, f"{b.reihe} {b.nummer}".strip()) if x]
            self.kt_info.configure(text="  ·  ".join(info + [b.pfad.name]))
            self.kt_text.insert("1.0", self._kt_aktueller_text(b))
            self.kt_quelle.configure(text=_("Source: {quelle}").format(quelle=self._kt_quelle_text(b)) if b.klappentext_quelle else
                                     ("" if b.klappentext else _("No blurb in the file.")))
        else:
            self._cover_zeigen(self.kt_cover, None)
        self.kt_text.edit_modified(False)
        self.kt_text.edit_reset()
        self._kt_laden = False

    def _klappentext_getippt(self):
        if not self.kt_text.edit_modified():
            return
        self.kt_text.edit_modified(False)
        b = self._kt_buch
        if self._kt_laden or not b:
            return
        text = self.kt_text.get("1.0", "end-1c").strip()
        vorher = b.klappentext_neu if b.klappentext_neu is not None else b.klappentext
        b.klappentext_entwurf = None if text == vorher.strip() else text
        self._geaendert(b)

    def _klappentext_uebernehmen(self):
        b = self._kt_buch
        if not b:
            return
        text = self.kt_text.get("1.0", "end-1c").strip()
        b.klappentext_entwurf = None
        b.klappentext_neu = None if text == b.klappentext.strip() else text
        self._geaendert(b)
        self.status.set(f"{b.name}: " + (_("blurb applied, not yet saved.") if b.klappentext_neu is not None
                                          else _("unchanged.")))

    def klappentext_verwerfen(self):
        b = self._kt_buch
        if b:
            b.klappentext_entwurf = b.klappentext_neu = None
            b.klappentext_quelle = b.klappentext_quelle_datei
            self._klappentext_anzeigen()
            self._geaendert(b)
            self.status.set(f"{b.name}: " + _("blurb restored from the file."))

    # -- Nachschlagen (Hintergrund) ------------------------------------------------
    def _api_client(self, stumm=False):
        try:
            import anthropic
        except ImportError:
            if not stumm:
                messagebox.showerror(_("Look up"), _("The anthropic package is missing.\n\npip install anthropic"),
                                     parent=self)
            return None
        key = self.e.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            if not stumm:
                messagebox.showerror(_("Look up"), _("No API key. Settings > Blurbs."), parent=self)
            return None
        return anthropic.Anthropic(api_key=key)

    def _kt_quelle_text(self, b):
        q = b.klappentext_quelle
        name = blurbs.source_name(q)
        return q if name == q else f"{name} ({q})"

    def klappentext_nachschlagen(self):
        b = self._kt_buch if self._bereich() == "klappentexte" else None
        if not b:
            self.status.set(_("Look up: choose a book in the Blurbs area."))
            return
        self._nachschlagen_starten([b], einzeln=True)

    def klappentexte_alle(self):
        # Bücher, für die Calibre eine Beschreibung hat, nicht nachschlagen (_("From Calibre"))
        offen = [b for b in self.buecher if not self._kt_aktueller_text(b).strip() and not b.fehler
                 and not (b.calibre and b.calibre.get("comments"))]
        if not offen:
            self.status.set(_("All books have a blurb."))
            return
        self._nachschlagen_starten(offen)

    # Zwischenspeicher (blurbs_cache.json), Schlüssel "Titel|Autor":
    #   {"blurb": …, "source": …}            gefunden
    #   {"none": true, "versucht": [...]}    nichts gefunden; "frei" bzw. "claude:<Profilkennung>"
    #   null                                 bis 0.20: im Lexicanum nichts gefunden
    def _kt_versucht(self, schl):
        if schl not in self.cache:
            return set()
        eintrag = self.cache[schl]
        if eintrag is None:                 # gilt für das Lexicanum-Profil, wie es auch eingestellt ist
            return {"claude:lexicanum"}
        return set(eintrag.get("versucht") or [])

    @staticmethod
    def _kt_profil_kennung(p):
        """Ändern sich Seiten, Suche oder Hinweise eines Profils, wird neu nachgeschlagen."""
        import hashlib
        inhalt = "|".join(str(p.get(k, "")) for k in ("seiten", "domains", "abschnitt", "thema", "websuche"))
        return f"{blurbs.profile_id(p)}-{hashlib.sha1(inhalt.encode('utf-8')).hexdigest()[:8]}"

    def _kt_plan(self, buecher):
        """[(Buch, Schritte, schon versucht)] mit Schritten "frei" und/oder ("claude", Profil) - ohne die schon versuchten."""
        profile = kei.klappentext_profile(self.e)
        plan = []
        for b in buecher:
            schl = f"{b.titel}|{b.autor}"
            if (self.cache.get(schl) or {}).get("blurb"):
                plan.append((b, [], set()))
                continue
            versucht, schritte = self._kt_versucht(schl), []
            if self.e.get("kostenlos", True) and "frei" not in versucht:
                schritte.append("frei")
            p = blurbs.profile_for(profile, b.verlag, b.reihe, b.autor)
            if p and not {"claude:" + self._kt_profil_kennung(p), "claude:" + blurbs.profile_id(p)} & versucht:
                schritte.append(("claude", p))
            plan.append((b, schritte, versucht))
        return plan

    def _nachschlagen_starten(self, buecher, einzeln=False):
        if self._arbeit:
            self.status.set(_("Still running: {arbeit}.").format(arbeit=self._arbeit))
            return
        plan = self._kt_plan(buecher)
        mit_claude = sum(1 for __, sch, __ in plan if any(isinstance(x, tuple) for x in sch))
        mit_frei = sum(1 for __, sch, __ in plan if "frei" in sch)
        client, ohne_schluessel = None, False
        if mit_claude:
            # Ohne Schlüssel nur meckern, wenn es sonst gar nichts zu tun gibt
            client = self._api_client(stumm=bool(mit_frei))
            if client is None:
                if not mit_frei:
                    return
                plan = [(b, [x for x in sch if x == "frei"], v) for b, sch, v in plan]
                mit_claude, ohne_schluessel = 0, True
        if not einzeln and mit_claude and not messagebox.askyesno(
                _("Look up all"),
                ngettext("{n} book without a blurb.", "{n} books without a blurb.", len(plan)).format(n=len(plan))
                + "\n" + (_("The free sources are asked first; Claude only for what they do not have.") + "\n"
                          if mit_frei else "")
                + ngettext("At most {n} book goes to Claude: up to about {kosten} $.",
                           "At most {n} books go to Claude: up to about {kosten} $.", mit_claude)
                .format(n=mit_claude, kosten=f"{mit_claude * float(self.e.get('kt_kosten', 0.015)):.2f}")
                + "\n\n" + _("Start?"),
                parent=self):
            return
        args = SimpleNamespace(model=self.e["modell"])
        blurbs.MIN_LAENGE = int(self.e.get("kt_min", 80))
        blurbs.MAX_LAENGE = int(self.e.get("kt_max", 4000))
        self._arbeit = _("Looking up blurbs")

        def arbeit():
            gefunden = 0
            for i, (b, schritte, versucht) in enumerate(plan, 1):
                schl = f"{b.titel}|{b.autor}"
                treffer = None
                for schritt in schritte:
                    self._q.put(("status", _("Looking up ({i}/{n}): {name} …").format(i=i, n=len(plan), name=b.name)))
                    if schritt == "frei":
                        treffer, fehler = blurbs.free_look_up(b.titel, b.autor, b.isbn, b.sprache)
                        if fehler:                      # Netzfehler: nicht als versucht merken
                            self._q.put(("status", f"{b.name}: " + "; ".join(fehler)))
                        elif not treffer:
                            versucht.add("frei")
                    else:
                        try:
                            treffer = blurbs.look_up(client, args, b.titel, b.autor, b.reihe, schritt[1], b.sprache)
                        except Exception as e:
                            self._q.put(("status", f"{b.name}: " + _("API error ({fehler})").format(fehler=e)))
                            continue
                        if not treffer:
                            versucht.add("claude:" + self._kt_profil_kennung(schritt[1]))
                    if treffer:
                        break
                if treffer:
                    gefunden += 1
                    self._q.put(("cache", (schl, treffer)))
                elif schritte:
                    self._q.put(("cache", (schl, {"none": True, "versucht": sorted(versucht)})))
                self._q.put(("klappentext", b.schluessel))
            text = ngettext("Look-up finished ({n} book).", "Look-up finished ({n} books).", len(plan)) \
                .format(n=len(plan))
            if len(plan) > 1:
                text += " " + ngettext("{n} blurb found.", "{n} blurbs found.", gefunden).format(n=gefunden)
            if ohne_schluessel:
                text += " " + _("Claude was not asked (no API key).")
            self._q.put(("fertig", text))
        threading.Thread(target=arbeit, daemon=True).start()

    def _klappentext_ergebnis(self, schluessel):
        b = self.nach_schluessel.get(schluessel)
        if not b:
            return
        treffer = self.cache.get(f"{b.titel}|{b.autor}") or {}
        if treffer.get("blurb"):
            b.klappentext_entwurf = treffer["blurb"]
            b.klappentext_quelle = treffer.get("source", "")
            self.status.set(f"{b.name}: " + _("blurb found ({quelle}), not yet applied.")
                            .format(quelle=blurbs.source_name(b.klappentext_quelle) or "?"))
        else:
            self.status.set(f"{b.name}: " + _("no blurb found."))
        self._geaendert(b)
        if b is self._kt_buch:
            self._klappentext_anzeigen()

    # ================================================================ Calibre
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

    def klappentext_aus_calibre(self):
        if self._calibre_aus():
            return
        b = self._kt_buch if self._bereich() == "klappentexte" else None
        if not b:
            return
        text = kd.html_zu_text((b.calibre or {}).get("comments") or "")
        if not text:
            self.status.set(f"{b.name}: " + _("Calibre has no description."))
            return
        b.klappentext_entwurf = text
        b.klappentext_quelle = "Calibre"
        self._klappentext_anzeigen()
        self._geaendert(b)
        self.status.set(f"{b.name}: " + _("description from Calibre, not yet applied."))

    # ================================================================ Laden und Speichern
    def ordner_oeffnen(self):
        if not self._aenderungen_verwerfen_ok():
            return
        o = filedialog.askdirectory(parent=self, title=_("Open books folder"),
                                    initialdir=self.e.get("ordner") or str(Path.home()))
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
                    self._q.put(("status", _("Reading books … {i}/{n}").format(i=i, n=len(dateien))))
                ergebnis.append(kd.buch_laden(f, einst[0], einst[1], einst[2]))
            wurzel, eintraege = kd.calibre_finden(ordner) if calibre else (None, [])
            kd.calibre_zuordnen(ergebnis, wurzel, eintraege)
            self._q.put(("geladen", (ergebnis, wurzel, eintraege)))
        threading.Thread(target=arbeit, daemon=True).start()

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
        if self._start_buch:
            self._buch_wieder_waehlen(self._start_buch)
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
        self._bearbeiter_weg(speichern=True)
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
            messagebox.showwarning(_("Save"), grund, parent=self)
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
        if ok:
            self.kobo.vermerken(self.ordner)
        if fehler:
            messagebox.showerror(_("Save"), _("Not saved:") + "\n\n" + "\n".join(fehler), parent=self)
        self.status.set(ngettext("{n} book saved, backups in {ordner}.", "{n} books saved, backups in {ordner}.", ok)
                        .format(n=ok, ordner=self.e["sicherungsordner"]) +
                        (" " + _("{n} with changes not yet applied.").format(n=rot) if rot else ""))

    def _aenderungen_verwerfen_ok(self):
        offen = sum(1 for b in self.buecher if b.stand() in ("rot", "gelb"))
        return not offen or messagebox.askyesno(
            _("Changes"), ngettext("{n} book has unsaved changes. Discard them?",
                                   "{n} books have unsaved changes. Discard them?", offen).format(n=offen), parent=self)

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
            self._q.put(("rueckruf", fertig))
        threading.Thread(target=lauf, daemon=True).start()

    def _abholen(self):
        try:
            while True:
                art, daten = self._q.get_nowait()
                if art == "status":
                    self.status.set(daten)
                elif art == "geladen":
                    self._geladen(daten)
                elif art == "cache":
                    self.cache[daten[0]] = daten[1]
                    kd.json_speichern(kd.KLAPPENTEXT_CACHE, self.cache)
                elif art == "klappentext":
                    self._klappentext_ergebnis(daten)
                elif art == "fertig":
                    self._arbeit = None
                    self.status.set(daten)
                elif art == "rueckruf":
                    daten()
        except queue.Empty:
            pass
        self.after(100, self._abholen)

    # ================================================================ Anzeige
    def _geaendert(self, b, neu_zeichnen=False):
        """Ein Buch hat sich geändert: Listen, Streifen, Zähler, Titel nachziehen."""
        if self.tabelle.exists(b.schluessel):
            self.tabelle.item(b.schluessel, values=[self._zelle(b, c) for c, __, __ in SPALTEN])
        if neu_zeichnen and b is self._kap_buch:
            sel = self.kap_tabelle.selection()
            self._kapitel_anzeigen()
            if sel and self.kap_tabelle.exists(sel[0]):
                self.kap_tabelle.selection_set(sel[0])
                self.kap_tabelle.see(sel[0])
        for s in self._streifen:
            s.zeichnen()
        self._zaehler()

    def _alles_neu_zeichnen(self):
        alt = {liste: self._aktuelles_buch(liste) for liste in (self.kap_liste, self.kt_liste)}
        self._listen_buch = {self._anzeigename(b): b for b in self.buecher}
        sortiert = self._links_sortiert()
        for liste, anzeige in ((self.kap_liste, self._kapitel_anzeigen), (self.kt_liste, self._klappentext_anzeigen)):
            vorher = alt[liste]
            alt_b = self.nach_schluessel.get(vorher.schluessel) if vorher else None
            self._liste_fuellen(liste, sortiert, alt_b, anzeige)
        self.metadaten.liste_fuellen(sortiert)
        self._tabelle_fuellen()
        if getattr(self, "vorschau", None) and self._bereich() == "vorschau":
            self.vorschau.liste_fuellen()
        for s in self._streifen:
            s.zeichnen()
        self._zaehler()

    def _zaehler(self):
        n = len(self.buecher)
        warn = sum(1 for b in self.buecher if b.warnung())
        ohne = sum(1 for b in self.buecher if not self._kt_aktueller_text(b).strip())
        self.nb.tab(self.seite_bibliothek, text=_("Library ({n})").format(n=n) if n else _("Library"))
        self.nb.tab(self.seite_kapitel, text=_("Chapters ({n} ⚠)").format(n=warn) if warn else _("Chapters"))
        # wie Kapitel: Zahl mit ⚠ (die Listen zeigen das ⚠ im Streifen, ohne farbige Zeilen)
        self.nb.tab(self.seite_klappentext, text=_("Blurbs ({n} ⚠)").format(n=ohne) if ohne and n else _("Blurbs"))
        meta = self.metadaten.warnungen() if self.buecher else 0
        self.nb.tab(self.metadaten.seite, text=_("Metadata ({n} ⚠)").format(n=meta) if meta else _("Metadata"))
        offen = any(b.stand() in ("rot", "gelb") for b in self.buecher)
        self.title(f"{PROGRAMM} {VERSION}" + (" *" if offen else ""))

    def _bereich(self):
        try:
            w = self.nb.nametowidget(self.nb.select())
        except (KeyError, tk.TclError):
            return "bibliothek"
        seiten = {self.seite_kapitel: "kapitel", self.seite_klappentext: "klappentexte",
                  self.kobo.seite: "kobo", self.woerterbuch.seite: "woerterbuch"}
        if getattr(self, "metadaten", None):
            seiten[self.metadaten.seite] = "metadaten"
        if getattr(self, "vorschau", None):
            seiten[self.vorschau.seite] = "vorschau"
        return seiten.get(w, "bibliothek")

    def _bereich_gewechselt(self):
        self._bearbeiter_weg(speichern=True)
        name = self._bereich()
        self.e["bereich_zuletzt"] = name
        self._wz_bereich_bauen(name)
        if name == "kapitel" and not self.kap_liste.curselection() and self.kap_liste.size():
            self.kap_liste.selection_set(0)
            self._kapitel_anzeigen()
        if name == "klappentexte" and not self.kt_liste.curselection() and self.kt_liste.size():
            self.kt_liste.selection_set(0)
            self._klappentext_anzeigen()
        if name == "metadaten":
            self.metadaten.beim_zeigen()
        if name == "kobo":
            self.kobo.anzeigen()
        if name == "woerterbuch":
            self.woerterbuch.beim_zeigen()
        if name == "vorschau":
            self.vorschau.beim_zeigen()
        self.after_idle(lambda: [s.zeichnen() for s in self._streifen])

    def _mark_farben(self):                       # für keller_streifen
        return MARK["dunkel" if self.dark_mode.get() else "hell"]

    def _streifen_umschalten(self):
        self.e["status_liste"] = self.status_liste.get()
        for s in self._streifen:
            s.umschalten()

    def _darstellung(self):
        self.e["darstellung"] = self.darstellung.get()         # sonst setzt der Einstellungsdialog zurück
        self.dark_mode.set(kth.ist_dunkel(self.darstellung.get()))
        self._theme_anwenden()

    def _theme_anwenden(self):
        dunkel = self.dark_mode.get()
        p = kth.anwenden(self, dunkel)
        self._farben = p
        for k, symbol in self._wz:
            self._knopf_faerben(k, symbol)
        for r in self._rahmen_liste:
            r.configure(highlightbackground=p["rahmen"], highlightcolor=p["rahmen"], bg=p["feld"])
        modus = "dunkel" if dunkel else "hell"
        self._linien_font = None                    # Schrift der Tabelle kann sich mit dem Thema ändern
        for t in (self.tabelle, self.kap_tabelle):
            t.tag_configure("warn", background=WARNZEILE[modus])
            t.tag_configure("ohne", background=OHNEZEILE[modus])
        self.navi.farben(dunkel)
        if hasattr(self, "kobo"):
            self.kobo.farben(modus, WARNZEILE)
        self.hinweisleiste.configure(bg=WARNZEILE[modus])
        self.hinweis_text.configure(bg=WARNZEILE[modus], fg=p["fg"])
        if hasattr(self, "woerterbuch"):
            self.woerterbuch.farben()
        if hasattr(self, "cover"):
            self.cover.farben()
        if getattr(self, "vorschau", None):
            self.vorschau.farben()
        if self._hilfe is not None and self._hilfe.winfo_exists():
            self._hilfe.farben()
        for s in self._streifen:
            s.zeichnen()

    # ================================================================ Sonstiges
    def einstellungen_geaendert(self):
        self.darstellung.set(self.e["darstellung"])
        self.tooltips_an.set(self.e["tooltips"])
        if self.status_liste.get() != self.e["status_liste"]:
            self.status_liste.set(self.e["status_liste"])
            self._streifen_umschalten()
        self.cover_an.set(self.e["cover"])
        self._cover_umschalten()                         # auch für eine neue Höhe
        calibre_hinweis = self._calibre_umschalten()
        self.metadaten.felder_bauen()
        self.metadaten.anzeigen()
        self._wz_bereich_bauen(self._bereich())
        if self.navi.ausgeklappt != bool(self.e.get("navi_ausgeklappt", True)):
            self.navi.umschalten()
        self._darstellung()
        if self.vorschau:
            self.vorschau.koreader_suchen(still=True)
            self.vorschau.anzeigen()
        kei.speichern(self._e_zum_speichern())
        self.status.set(_("Settings saved. Chapter settings apply after reloading (F5).")
                        + (" " + calibre_hinweis if calibre_hinweis else ""))

    def _calibre_umschalten(self):
        """Calibre-Abgleich aus: Calibre-Daten sofort vergessen; an: wirkt nach dem Neu-Einlesen (Rückgabe:
        Hinweis dazu oder None)."""
        an = bool(self.e.get("calibre_an", True))
        if not an and self.calibre_eintraege:
            self.calibre_wurzel, self.calibre_eintraege = None, []
            for b in self.buecher:
                b.calibre = None
                if b.reihe_quelle == "Calibre":
                    b.reihe, b.nummer, b.reihe_quelle = b.reihe_datei[0], b.reihe_datei[1], ""
            self._alles_neu_zeichnen()
        elif an and self.ordner and not self.calibre_eintraege and kd.calibre_finden(self.ordner)[1]:
            return _("Calibre comparison on: reload (F5) to read metadata.calibre.")
        return None

    def _e_zum_speichern(self):
        self.e.update(darstellung=self.darstellung.get(), tooltips=self.tooltips_an.get(),
                      status_liste=self.status_liste.get())
        return self.e

    def hilfe_zeigen(self, kennung):
        """Hilfe mit einem bestimmten Thema öffnen (z. B. aus den Einstellungen)."""
        if self._hilfe is not None and self._hilfe.winfo_exists():
            self._hilfe.zeige(kennung)
        else:
            self._hilfe = khi.HilfeFenster(self, kennung)

    def hilfe(self):
        thema = khi.thema(self._bereich())
        if self._hilfe is not None and self._hilfe.winfo_exists():
            self._hilfe.zeige(thema)
        else:
            self._hilfe = khi.HilfeFenster(self, thema)

    def _cover_aktion(self, name):
        """Menü: in den Bereich Metadaten (mit dem Cover) wechseln, mit dem gewählten Buch, und ausführen."""
        if self._bereich() != "metadaten":
            b = self._gewaehltes_buch() if self._bereich() in ("klappentexte", "kapitel") else None
            self.nb.select(self.metadaten.seite)
            self.update_idletasks()
            if b:
                self.metadaten.auswaehlen(b)
        getattr(self.cover, name)()

    def _metadaten_aktion(self, name):
        """Menü: in den Bereich Metadaten wechseln (mit dem gewählten Buch) und ausführen."""
        if self._bereich() != "metadaten":
            b = self._gewaehltes_buch()
            self.nb.select(self.metadaten.seite)
            self.update_idletasks()
            if b:
                self.metadaten.auswaehlen(b)
        getattr(self.metadaten, name)()

    def bereich_zeigen(self, name):
        seiten = {"bibliothek": self.seite_bibliothek, "kapitel": self.seite_kapitel,
                  "klappentexte": self.seite_klappentext, "cover": self.metadaten.seite, "kobo": self.kobo.seite,
                  "metadaten": self.metadaten.seite,
                  "woerterbuch": self.woerterbuch.seite}
        if self.vorschau:
            seiten["vorschau"] = self.vorschau.seite
        if name in seiten:
            self.nb.select(seiten[name])

    def _buch_wieder_waehlen(self, pfad):
        b = next((b for b in self.buecher if str(b.pfad) == str(pfad)), None)
        if not b:
            return
        if self.tabelle.exists(b.schluessel):
            self.tabelle.selection_set(b.schluessel)
            self.tabelle.see(b.schluessel)
        self._auswaehlen(self.kap_liste, b)
        self._auswaehlen(self.kt_liste, b)
        self.metadaten.auswaehlen(b)

    def _gewaehltes_buch(self):
        bereich = self._bereich()
        if bereich == "kapitel":
            return self._kap_buch
        if bereich == "klappentexte":
            return self._kt_buch
        if bereich == "metadaten":
            return self.metadaten.buch
        sel = self.tabelle.selection()
        return self.nach_schluessel.get(sel[0]) if sel else None

    def sprache_wechseln(self, alt):
        """Neue Sprache: Bookbench startet neu, mit Ordner, Bereich, Buch und Fenster. Viele Texte
        (Ansichten, Spalten, Filter) werden beim Import übersetzt, ein Neuaufbau im laufenden
        Programm würde sie in der alten Sprache lassen."""
        self._bearbeiter_weg(speichern=True)
        offen = sum(1 for b in self.buecher if b.stand() in ("rot", "gelb"))
        n = self.woerterbuch.offen()
        fragen = []
        if offen:
            fragen.append(ngettext("{n} book has unsaved changes.", "{n} books have unsaved changes.", offen).format(n=offen))
        if n:
            fragen.append(ngettext("{n} dictionary entry is changed in the form but not applied.",
                                   "{n} dictionary entries are changed in the form but not applied.", n).format(n=n))
        if fragen and not messagebox.askyesno(
                _("Language"), "\n".join(fragen) + "\n\n" + _("Restart now and lose them? (No: the language "
                                                               "changes at the next start.)"), parent=self):
            self.status.set(_("The new language applies at the next start."))
            return
        self.neu_starten()

    def neu_starten(self):
        """Bookbench neu starten (Sprachwechsel, Update), mit Ordner, Bereich, Buch und Fenster.
        Fragt nichts mehr; offene Änderungen vorher klären (schliessen_ok)."""
        b = self._gewaehltes_buch()
        start = Path(__file__).resolve().parent.parent / "start.py"
        befehl = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(start)]
        if self.ordner:
            befehl.append(self.ordner)
        befehl += ["--bereich", self._bereich(), "--geometrie", self.geometry()]
        if b:
            befehl += ["--buch", str(b.pfad)]
        self._einstellungen_sichern()
        self._popen(befehl)
        self.destroy()

    def _einstellungen_sichern(self):
        self.e["fenster"] = self.geometry().split("+")[0]
        self.e["spalten"] = self.tabellen_spalten.breiten()
        try:
            kei.speichern(self._e_zum_speichern())
        except OSError:
            pass

    def schliessen_ok(self):
        """Darf Bookbench jetzt zugehen? Fragt nach ungespeicherten Büchern, nicht übernommenen
        Wörterbuch-Einträgen und ans Auswerfen des E-Readers (Beenden, Update)."""
        self._bearbeiter_weg(speichern=True)
        offen = sum(1 for b in self.buecher if b.stand() in ("rot", "gelb"))
        if offen and not messagebox.askyesno(
                _("Quit"), ngettext("{n} book has unsaved changes. Quit anyway?",
                                    "{n} books have unsaved changes. Quit anyway?", offen).format(n=offen), parent=self):
            return False
        n = self.woerterbuch.offen()
        if n and not messagebox.askyesno(
                _("Quit"), ngettext("{n} dictionary entry is changed in the form but not applied. Quit anyway?",
                                    "{n} dictionary entries are changed in the form but not applied. Quit anyway?", n)
                .format(n=n), parent=self):
            return False
        return self.kobo.beenden_ok()

    def beenden(self):
        if not self.schliessen_ok():
            return
        self._einstellungen_sichern()
        self.destroy()


def main():
    import argparse
    ap = argparse.ArgumentParser(description=f"{PROGRAMM} {VERSION}")
    ap.add_argument("ordner", nargs="?", help=_("books folder to open"))
    ap.add_argument("--bereich", help=argparse.SUPPRESS)        # für den Neustart beim Sprachwechsel
    ap.add_argument("--buch", help=argparse.SUPPRESS)
    ap.add_argument("--geometrie", help=argparse.SUPPRESS)
    a = ap.parse_args()
    App(a.ordner, a.bereich, a.buch, a.geometrie).mainloop()


if __name__ == "__main__":
    main()
