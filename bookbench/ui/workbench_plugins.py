# -*- coding: utf-8 -*-
"""
workbench_plugins.py - Unterseiten Bookends und Bookshelf der KOReader-Werkbank (seit 1.4-beta2).
Nur Oberfläche; Dateiformate und Logik in preview/plugins.py, KOReader-Steuerung in
preview/workbench.py. Die Seiten stehen in der linken Spalte des Bereichs Vorschau (Unterseiten in
der Seitenleiste), das Bild von KOReader bleibt rechts daneben.

Ablauf (für beide gleich): Änderungen sind erst ein Entwurf und wirken nur in der Werkbank
(Wegwerf-Kopie des Profils). "Ins Profil speichern" schreibt sie ins Vorschau-Profil, "Verwerfen" liest
das Profil neu. Bei jedem Neustart der Werkbank schreibt in_kopie() die Entwürfe in die neue Kopie.

  Bookends    jede Änderung nach kurzer Pause sofort im Bild (Befehl "bookends <datei>", < 0,2 s)
  Bookshelf   Änderung -> Neustart der Werkbank auf dem Startbildschirm (~1,2 s; Bookshelf kann seine
              Einstellungen im laufenden KOReader nicht neu laden)
"""
import copy
import re
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

import keller_theme as kth
from bookbench.ui import panes as kpn
from bookbench.preview import plugins as kpl
from bookbench.i18n import N_, _

PAUSE_BOOKENDS = 350                              # ms nach der letzten Eingabe, dann ins Bild
PAUSE_BOOKSHELF = 900                             # ms, dann Neustart (länger: kostet ~1,2 s)
BREITE = 360                                      # Umbruchbreite der Hinweise


def _gleich(a, b):
    """Gleichheit ohne Pythons True == 1 und False == 0 (Bookshelf unterscheidet false und 0)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def _zahl_oder_leer(text):
    text = text.strip().replace(",", ".")
    if not text:
        return None
    w = float(text)
    return int(w) if w.is_integer() else w


class _Seite:
    """Gemeinsames: Rahmen mit Scrollbalken, Kopf, Stand-Zeile, Entwurf."""
    plugin = ""                                   # Kennung der Unterseite (auch für werkbank_abschnitte)
    titel = ""                                    # Name in Seitenleiste und Meldungen

    def __init__(self, bereich, eltern):
        self.bereich = bereich
        self.app = bereich.app
        self.rahmen = ttk.Frame(eltern)
        self.roll = kpn.RollFlaeche(self.rahmen)
        self.roll.pack(fill="both", expand=True)
        self.innen = ttk.Frame(self.roll.innen, padding=(0, 0, 10, 8))
        self.innen.pack(fill="both", expand=True)
        self.kopf = ttk.Label(self.innen, text="", style="Hinweis.TLabel", wraplength=BREITE, justify="left")
        self.kopf.pack(anchor="w", fill="x")
        self.stand = ttk.Label(self.innen, text="", wraplength=BREITE, justify="left")
        self.stand.pack(anchor="w", fill="x", pady=(2, 8))
        self.info = None                         # kpl.erkennen()[plugin]
        self._job = None
        self.abschnitte = {}                     # Kennung -> (BooleanVar, Rahmen, zeigen)

    def _abschnitt(self, kennung, titel, offen=True):
        """Aufklappbarer Abschnitt (wie "Profil, Gerät und Ausgabe" in der Ansicht, seit 1.4-beta3); offen/zu
        steht je Plugin und Abschnitt in der Einstellung werkbank_abschnitte. Gibt den Inhaltsrahmen zurück."""
        zustand = self.app.e.setdefault("werkbank_abschnitte", {})
        schl = f"{self.plugin}.{kennung}"
        var = tk.BooleanVar(value=bool(zustand.get(schl, offen)))
        knopf = ttk.Checkbutton(self.innen, variable=var, style="Toolbutton")
        knopf.pack(anchor="w", pady=(6, 0))
        rahmen = ttk.Frame(self.innen, padding=(8, 2, 0, 4))

        def zeigen():
            an = var.get()
            self.app.e.setdefault("werkbank_abschnitte", {})[schl] = an
            knopf.configure(text=("▾ " if an else "▸ ") + titel)
            if an:
                rahmen.pack(after=knopf, anchor="w", fill="x")
            else:
                rahmen.pack_forget()
        knopf.configure(command=zeigen)
        zeigen()
        self.abschnitte[kennung] = (var, rahmen, zeigen)
        return rahmen

    def aufklappen(self, kennung, an=True):
        var, __, zeigen = self.abschnitte[kennung]
        var.set(an)
        zeigen()

    @property
    def ko(self):
        return kpl.ko_ordner(self.bereich.profil)

    def farben(self):
        self.roll.farbe(kth.PALETTE["dunkel" if self.app.dark_mode.get() else "hell"]["bg"])

    def _planen(self, ms, fn):
        if self._job:
            self.app.after_cancel(self._job)
        self._job = self.app.after(ms, self._ausfuehren, fn)

    def _ausfuehren(self, fn):
        self._job = None
        fn()

    def ungespeichert(self):
        return False

    def zuruecksetzen(self):
        """Neues Profil: Entwurf und geladenen Stand vergessen (beim nächsten Zeigen neu lesen)."""

    def fragen_ob_verwerfen(self):
        """Vor dem Neuladen (Profil vom E-Reader usw.): True = weitermachen."""
        if not self.ungespeichert():
            return True
        a = messagebox.askyesnocancel(
            self.titel,
            _("The {plugin} settings have unsaved changes. Save them in the profile first?").format(
                plugin=self.titel), parent=self.app)
        if a is None:
            return False
        if a:
            self.speichern()
        return True

    def stand_zeigen(self):
        if self.ungespeichert():
            self.stand.configure(text=_("● Unsaved changes - so far only in the picture. \"Save to profile\" keeps "
                                        "them."), foreground=self.app._mark_farben()["rot"])
        else:
            self.stand.configure(text=_("Same as in the profile. \"To the e-reader …\" in the toolbar writes it to "
                                        "the e-reader."), foreground="")


# Bookshelfs Standard-Einträge im Startmenü (bookshelf_start_menu_model.lua DEFAULTS, Aktionen ohne Module);
# zum Wiederherstellen. Die Beschriftung wird in Bookbenchs Sprache gespeichert, wie Bookshelf es auch tut.
STARTMENUE_STANDARD = (
    {"type": "action", "label": N_("Reading calendar"), "icon": "\uf073", "action": {"stats_calendar_view": True}},
    {"type": "action", "label": N_("Bookmark browser"), "icon": "\uf02e", "action": {"bookmark_browser": True}},
    {"type": "action", "label": N_("Screenshot"), "icon": "\ue7ff", "action": {"screenshot": True}},
    {"type": "action", "label": N_("Frontlight"), "icon": "\ueca7",
     "menu_path": [{"id": "setting"}, {"id": "frontlight"}]},
    {"type": "action", "label": N_("Full screen refresh"), "icon": "\uf0e7", "action": {"full_refresh": True}},
    {"type": "action", "label": N_("Battery statistics"), "icon": "\ue790", "action": {"battery_statistics": True}},
    {"type": "action", "label": N_("Wi-Fi connection"), "icon": "\uea5e",
     "menu_path": [{"id": "setting"}, {"id": "network"}, {"id": "network_wifi"}], "menu_toggle": True},
    {"type": "action", "label": N_("Night mode"), "icon": "\uea5e",
     "menu_path": [{"id": "setting"}, {"id": "night_mode"}], "menu_toggle": True},
    {"type": "action", "label": N_("Close book"), "icon": "\ue905", "menu_path": [{"id": "filemanager"}],
     "scope": "reader"},
    {"type": "action", "label": N_("Sleep"), "icon": "\ueb24", "action": {"suspend": True}},
)


class _Wahl:
    """Klappliste mit festen Werten [(wert, Text)] (Text übersetzt); wert() / setzen(wert)."""

    def __init__(self, eltern, optionen, befehl, breite=14):
        self.var = tk.StringVar()
        self.box = ttk.Combobox(eltern, textvariable=self.var, state="readonly", width=breite)
        self.box.bind("<<ComboboxSelected>>", lambda e: befehl())
        self.optionen(optionen)

    def optionen(self, optionen):
        self._optionen = list(optionen)
        self.box.configure(values=[_(t) for __, t in self._optionen])

    def wert(self):
        return next((w for w, t in self._optionen if _(t) == self.var.get()),
                    self._optionen[0][0] if self._optionen else None)

    def setzen(self, wert, aktiv=None):
        t = next((t for w, t in self._optionen if w == wert), self._optionen[0][1] if self._optionen else "")
        self.var.set(_(t) if wert is not None or self._optionen else "")
        if aktiv is not None:
            self.aktiv(aktiv)

    def aktiv(self, an):
        self.box.configure(state="readonly" if an else "disabled")


class _SymbolText:
    """Textfelder mit Nerd-Font-Symbolen als Bild (Bookends-Zeilen, Bookshelf-Hero-Zeilen)."""

    # Nerd-Font-Symbole (privater Unicode-Bereich) zeigt Tk mit keiner normalen Schrift. Sie stehen
    # deshalb als kleines Bild im Textfeld (mit KOReaders symbols.ttf gezeichnet); beim Auslesen wird
    # das Bild wieder zum Zeichen. Ohne Pillow oder ohne Schrift bleiben es Zeichen (meist Kästchen).
    def _schrift(self):
        if not hasattr(self, "_symbolschrift"):
            self._symbolschrift = kpl.symbolschrift(self.bereich.profil, self.bereich.befund)
        return self._symbolschrift

    def glyph_bild(self, ch, groesse=15, farbe=None):
        """PhotoImage für ein Symbol (gecacht) oder None."""
        farbe = farbe or kth.PALETTE["dunkel" if self.app.dark_mode.get() else "hell"]["feld_fg"]
        schl = (ch, groesse, farbe)
        if not hasattr(self, "_glyphen"):
            self._glyphen, self._bild_zeichen = {}, {}
        if schl in self._glyphen:
            return self._glyphen[schl]
        bild = None
        pfad = self._schrift()
        if pfad:
            try:
                from PIL import Image, ImageDraw, ImageFont, ImageTk
                f = ImageFont.truetype(str(pfad), groesse)
                links, oben, rechts, unten = f.getbbox(ch)
                w, h = max(1, rechts - links), groesse + 2
                im = Image.new("RGBA", (w + 2, h), (0, 0, 0, 0))
                ImageDraw.Draw(im).text((1 - links, (h - (unten - oben)) // 2 - oben), ch, font=f, fill=farbe)
                bild = ImageTk.PhotoImage(im, master=self.app)
                self._bild_zeichen[str(bild)] = ch
            except (ImportError, OSError, ValueError):
                bild = None
        self._glyphen[schl] = bild
        return bild

    def _text_einsetzen(self, t, index, text):
        """Text einfügen; Symbole als Bild (siehe oben). Über eine Marke mit rechter Schwerkraft, sonst
        kehrt sich bei einem festen Index wie "1.0" die Reihenfolge der Stücke um."""
        t.mark_set("bb_einfuegen", index)
        t.mark_gravity("bb_einfuegen", "right")
        index = "bb_einfuegen"
        stueck = ""
        for ch in text:
            bild = self.glyph_bild(ch) if kpl.ist_symbol(ch) else None
            if bild is None:
                stueck += ch
                continue
            if stueck:
                t.insert(index, stueck)
                stueck = ""
            t.image_create(index, image=bild, padx=0)
        if stueck:
            t.insert(index, stueck)

    def _text_lesen(self, t):
        """Inhalt eines Textfelds mit den Symbol-Bildern als Zeichen."""
        teile = []
        for art, wert, index in t.dump("1.0", "end-1c", text=True, image=True):
            if art == "text":
                teile.append(wert)
            elif art == "image":
                teile.append(getattr(self, "_bild_zeichen", {}).get(str(t.image_cget(index, "image")), ""))
        return "".join(teile)


# ====================================================================== Bookends
class BookendsSeite(_SymbolText, _Seite):
    plugin = kpl.BOOKENDS
    titel = "Bookends"

    def __init__(self, bereich, eltern):
        super().__init__(bereich, eltern)
        self.datei = None                         # Dateiname der gezeigten Vorlage
        self.daten = None                         # Entwurf (dict)
        self.gespeichert = None                   # Stand im Profil (dict) bzw. None bei neuer Vorlage
        self.stand_profil = {"an": False, "aktiv": None}
        self.aktiv_neu = None                     # im Entwurf zur aktiven Vorlage gemacht
        self._namen = {}                          # Anzeigename -> Datei
        self._zeile = None                        # (pos, nr) für Stil/Größe
        self._fokus = None                        # zuletzt benutztes Textfeld (Token einfügen)
        self._laden_laeuft = False
        self._glyphen = {}                        # Zeichen -> PhotoImage (Symbole in den Textfeldern)
        self._bild_zeichen = {}                   # Name des PhotoImage -> Zeichen
        self._symbolfenster = None

        # -- Vorlage -------------------------------------------------------------------
        i = self._abschnitt("vorlage", _("Preset"))
        self.an_var = tk.BooleanVar()
        ttk.Checkbutton(i, text=_("Bookends switched on"), variable=self.an_var,
                        command=self._geaendert).pack(anchor="w")
        self.wahl_var = tk.StringVar()
        self.wahl = ttk.Combobox(i, textvariable=self.wahl_var, state="readonly")
        self.wahl.pack(anchor="w", fill="x", pady=(4, 0))
        self.wahl.bind("<<ComboboxSelected>>", lambda e: self._wahl_gewechselt())
        z = ttk.Frame(i)
        z.pack(anchor="w", fill="x", pady=(4, 0))
        for text, befehl in ((_("New"), self.neu), (_("Duplicate"), self.duplizieren), (_("Delete"), self.loeschen)):
            ttk.Button(z, text=text, command=befehl, style="Klein.TButton").pack(side="left", padx=(0, 4))
        self.aktiv_text = ttk.Label(i, text="", style="Hinweis.TLabel", wraplength=BREITE, justify="left")
        self.aktiv_text.pack(anchor="w", fill="x", pady=(4, 0))
        self.aktiv_knopf = ttk.Button(i, text=_("Make active"), command=self.aktiv_machen, style="Klein.TButton")
        self.aktiv_knopf.pack(anchor="w", pady=(2, 0))
        g = ttk.Frame(i)
        g.pack(anchor="w", fill="x", pady=(6, 0))
        g.columnconfigure(1, weight=1)
        self.name_var, self.beschr_var = tk.StringVar(), tk.StringVar()
        for r, (text, var) in enumerate(((_("Name"), self.name_var), (_("Description"), self.beschr_var))):
            ttk.Label(g, text=text).grid(row=r, column=0, sticky="w", padx=(0, 6), pady=1)
            e = ttk.Entry(g, textvariable=var)
            e.grid(row=r, column=1, sticky="we", pady=1)
            var.trace_add("write", lambda *a: self._kopf_geaendert())

        # -- Zeilen ----------------------------------------------------------------------
        i = self._abschnitt("zeilen", _("Lines"))
        k = ttk.Frame(i)
        k.pack(anchor="w", fill="x")
        self.token_knopf = ttk.Menubutton(k, text=_("Insert token"), style="Klein.TButton")
        self.token_knopf.pack(side="left")
        self.token_menue = tk.Menu(self.token_knopf, tearoff=False)
        self.token_knopf.configure(menu=self.token_menue)
        self.symbol_knopf = ttk.Button(k, text=_("Special characters …"), style="Klein.TButton",
                                       command=self.symbole_zeigen)
        self.symbol_knopf.pack(side="left", padx=(4, 0))
        ttk.Label(i, text=_("One line per row; tokens like %title or %page_num are filled in by Bookends. Extra "
                            "margin moves the whole position away from the edge (px)."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").pack(anchor="w", fill="x")
        self.texte, self.rand_var = {}, {}
        for pos, name in kpl.POSITIONEN:
            kz = ttk.Frame(i)
            kz.pack(anchor="w", fill="x", pady=(4, 0))
            ttk.Label(kz, text=_(name)).pack(side="left")
            felder = (("v_offset", "↕"),) + ((("h_offset", "↔"),) if kpl.mit_seitenrand(pos) else ())
            for feld, zeichen in reversed(felder):
                v = self.rand_var[(pos, feld)] = tk.StringVar()
                sp = ttk.Spinbox(kz, from_=0, to=999, width=4, textvariable=v,
                                 command=lambda p=pos: self._rand_geaendert(p))
                sp.pack(side="right")
                sp.bind("<KeyRelease>", lambda e, p=pos: self._rand_geaendert(p))
                ttk.Label(kz, text=zeichen).pack(side="right", padx=(6, 2))
            ttk.Label(kz, text=_("extra margin"), style="Hinweis.TLabel").pack(side="right")
            r = self.app._listenrahmen(i)
            r.pack(fill="x")
            t = tk.Text(r, height=2, width=20, wrap="none", undo=True, borderwidth=0, highlightthickness=0,
                        font=kth.schrift(10))
            t.pack(fill="x", padx=2, pady=1)
            t.bind("<<Modified>>", lambda e, p=pos: self._text_geaendert(p))
            for ev in ("<KeyRelease>", "<ButtonRelease-1>", "<FocusIn>"):
                t.bind(ev, lambda e, p=pos: self._zeile_gewaehlt(p), add="+")
            self.texte[pos] = t

        # -- gewählte Zeile -----------------------------------------------------------------
        i = self._abschnitt("zeile", _("Selected line"))
        self.zeile_kopf = ttk.Label(i, text=_("Click into a line above."))
        self.zeile_kopf.pack(anchor="w")
        zr = ttk.Frame(i)
        zr.pack(anchor="w", fill="x", pady=(2, 0))
        ttk.Label(zr, text=_("Style")).pack(side="left")
        self.stil_var = tk.StringVar()
        self.stil = ttk.Combobox(zr, textvariable=self.stil_var, state="disabled", width=11,
                                 values=[_(t) for __, t in kpl.STILE])
        self.stil.pack(side="left", padx=(4, 10))
        self.stil.bind("<<ComboboxSelected>>", lambda e: self._zeilenwerte_uebernehmen())
        ttk.Label(zr, text=_("Size")).pack(side="left")
        self.groesse_var = tk.StringVar()
        self.groesse = ttk.Spinbox(zr, from_=4, to=80, width=5, textvariable=self.groesse_var, state="disabled",
                                   command=self._zeilenwerte_uebernehmen)
        self.groesse.pack(side="left", padx=(4, 10))
        self.groesse.bind("<KeyRelease>", lambda e: self._zeilenwerte_uebernehmen())
        # zweite Reihe: Großbuchstaben und Seitenfilter (in einer Reihe passte es englisch nicht)
        sr = ttk.Frame(i)
        sr.pack(anchor="w", fill="x", pady=(4, 0))
        self.gross_var = tk.BooleanVar()
        self.gross = ttk.Checkbutton(sr, text=_("Capitals"), variable=self.gross_var, state="disabled",
                                     command=self._zeilenwerte_uebernehmen)
        self.gross.pack(side="left", padx=(0, 10))
        ttk.Label(sr, text=_("Show on")).pack(side="left")
        self.seiten = _Wahl(sr, kpl.SEITEN, self._zeilenwerte_uebernehmen, breite=12)
        self.seiten.box.pack(side="left", padx=(4, 0))
        vr = ttk.Frame(i)
        vr.pack(anchor="w", fill="x", pady=(4, 0))
        ttk.Label(vr, text=_("Offset")).pack(side="left")
        self.versatz_var, self.versatz = {}, {}
        for feld, text in (("line_h_nudge", _("← →")), ("line_v_nudge", _("↑ ↓"))):
            ttk.Label(vr, text=text).pack(side="left", padx=(6, 2))
            v = self.versatz_var[feld] = tk.StringVar()
            sp = self.versatz[feld] = ttk.Spinbox(vr, from_=-999, to=999, width=4, textvariable=v, state="disabled",
                                                  command=self._zeilenwerte_uebernehmen)
            sp.pack(side="left")
            sp.bind("<KeyRelease>", lambda e: self._zeilenwerte_uebernehmen())
        ttk.Button(vr, text=_("Back to 0"), style="Klein.TButton", width=-1,
                   command=self._versatz_zurueck).pack(side="left", padx=(6, 0))
        # Balken in der Zeile (Token %bar)
        self.zbalken_rahmen = ttk.Frame(i)
        self.zbalken_rahmen.pack(anchor="w", fill="x", pady=(6, 0))
        self.zbalken_kopf = ttk.Label(self.zbalken_rahmen, text="")
        self.zbalken_kopf.grid(row=0, column=0, columnspan=4, sticky="w")
        self.zbalken_knopf = ttk.Button(self.zbalken_rahmen, text="", style="Klein.TButton",
                                        command=self._zeilenbalken_umschalten)
        self.zbalken_knopf.grid(row=4, column=0, columnspan=4, sticky="w", pady=(2, 0))
        self.zb = {"art": _Wahl(self.zbalken_rahmen, kpl.BALKEN_ARTEN, self._zeilenbalken_uebernehmen, 10),
                   "striche": _Wahl(self.zbalken_rahmen, kpl.BALKEN_STRICHE, self._zeilenbalken_uebernehmen, 18),
                   "stil": _Wahl(self.zbalken_rahmen, kpl.BALKEN_STILE, self._zeilenbalken_uebernehmen, 12),
                   "richtung": _Wahl(self.zbalken_rahmen, kpl.RICHTUNGEN[:2], self._zeilenbalken_uebernehmen, 14)}
        self.zb["art"].box.grid(row=1, column=0, columnspan=2, sticky="w", pady=1)
        self.zb["striche"].box.grid(row=1, column=2, columnspan=3, sticky="w", padx=(6, 0), pady=1)
        self.zb["stil"].box.grid(row=2, column=0, columnspan=2, sticky="w", pady=1)
        self.zb["richtung"].box.grid(row=2, column=2, columnspan=3, sticky="w", padx=(6, 0), pady=1)
        dz = ttk.Frame(self.zbalken_rahmen)
        dz.grid(row=3, column=0, columnspan=5, sticky="w", pady=1)
        self.zb_dicke_var, self.zb_dicke = {}, {}
        for feld, text in (("dicke", _("Thickness")), ("ungelesen", _("unread"))):
            ttk.Label(dz, text=text).pack(side="left", padx=(0 if feld == "dicke" else 8, 4))
            v = self.zb_dicke_var[feld] = tk.StringVar()
            sp = self.zb_dicke[feld] = ttk.Spinbox(dz, from_=1, to=200, width=5, textvariable=v,
                                                   command=self._zeilenbalken_uebernehmen)
            sp.pack(side="left")
            sp.bind("<KeyRelease>", lambda e: self._zeilenbalken_uebernehmen())
        ttk.Label(dz, text="px", style="Hinweis.TLabel").pack(side="left", padx=(4, 0))
        ttk.Label(i, text=_("Empty size = the general font size. Offset in pixels: negative = left or up. Empty "
                            "thickness = as high as the text; empty unread = like read. Font per line, colours "
                            "and markers of a bar and conditions in the text stay as they are."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").pack(anchor="w", fill="x", pady=(4, 0))

        # -- Fortschrittsbalken über die ganze Breite -------------------------------------
        i = self._abschnitt("balken", _("Progress bars"), offen=False)
        bk = ttk.Frame(i)
        bk.pack(anchor="w", fill="x")
        self.balken_nr = tk.IntVar(value=1)
        self.balken_wahl = ttk.Combobox(bk, state="readonly", width=22)
        self.balken_wahl.pack(side="left")
        self.balken_wahl.bind("<<ComboboxSelected>>", lambda e: self._balken_gewaehlt())
        self.balken_an = tk.BooleanVar()
        ttk.Checkbutton(bk, text=_("Switched on"), variable=self.balken_an,
                        command=self._balken_uebernehmen).pack(side="left", padx=(8, 0))
        bg = self.balken_gitter = ttk.Frame(i)
        bg.pack(anchor="w", fill="x", pady=(4, 0))
        self.bb = {"type": _Wahl(bg, kpl.BALKEN_ARTEN, self._balken_uebernehmen, 10),
                   "chapter_ticks": _Wahl(bg, kpl.BALKEN_STRICHE, self._balken_uebernehmen, 18),
                   "style": _Wahl(bg, kpl.BALKEN_STILE, self._balken_uebernehmen, 12),
                   "direction": _Wahl(bg, kpl.RICHTUNGEN, self._balken_uebernehmen, 14),
                   "v_anchor": _Wahl(bg, kpl.ANKER, self._balken_anker, 10)}
        for r, (links, rechts) in enumerate((("type", "chapter_ticks"), ("style", "direction"))):
            self.bb[links].box.grid(row=r, column=0, columnspan=2, sticky="w", pady=1)
            self.bb[rechts].box.grid(row=r, column=2, columnspan=2, sticky="w", padx=(6, 0), pady=1)
        ttk.Label(bg, text=_("Edge")).grid(row=2, column=0, sticky="w", pady=1)
        self.bb["v_anchor"].box.grid(row=2, column=1, sticky="w", padx=(4, 0), pady=1)
        self.bb_zahl_var, self.bb_zahl_text = {}, {}
        zahlen = ttk.Frame(i)
        zahlen.pack(anchor="w", fill="x", pady=(2, 0))
        for r, felder in enumerate(((("height", _("Thickness")), ("unread_height", _("unread"))),
                                    (("margin_v", _("Distance from the edge")),),
                                    (("margin_left", _("Margin left")), ("margin_right", _("right"))))):
            for c, (feld, text) in enumerate(felder):
                lb = self.bb_zahl_text[feld] = ttk.Label(zahlen, text=text)
                lb.grid(row=r, column=c * 2, sticky="w", padx=(0 if c == 0 else 10, 4), pady=1)
                v = self.bb_zahl_var[feld] = tk.StringVar()
                sp = ttk.Spinbox(zahlen, from_=-999 if feld == "margin_v" else 0, to=999, width=5, textvariable=v,
                                 command=self._balken_uebernehmen)
                sp.grid(row=r, column=c * 2 + 1, sticky="w", pady=1)
                sp.bind("<KeyRelease>", lambda e: self._balken_uebernehmen())
        self.balken_text = ttk.Label(i, text="", style="Hinweis.TLabel", wraplength=BREITE, justify="left")
        self.balken_text.pack(anchor="w", fill="x", pady=(4, 0))

        # -- allgemein -------------------------------------------------------------------
        i = self._abschnitt("allgemein", _("General"), offen=False)
        ga = ttk.Frame(i)
        ga.pack(anchor="w", fill="x")
        self.allg_var = {}
        for r, (schl, text, vorgabe) in enumerate(kpl.ALLGEMEIN):
            ttk.Label(ga, text=_(text)).grid(row=r, column=0, sticky="w", padx=(0, 6), pady=1)
            v = self.allg_var[schl] = tk.StringVar()
            sp = ttk.Spinbox(ga, from_=0, to=400, width=6, textvariable=v, command=self._allgemein_geaendert)
            sp.grid(row=r, column=1, sticky="w", pady=1)
            sp.bind("<KeyRelease>", lambda e: self._allgemein_geaendert())
            ttk.Label(ga, text=_("empty = {wert}").format(wert=vorgabe if vorgabe is not None else
                                                          _("size of KOReader's status bar")),
                      style="Hinweis.TLabel").grid(row=r, column=2, sticky="w", padx=(6, 0))
        self.kuerzen_var = tk.StringVar(value="center")
        for wert, text in kpl.KUERZEN:
            ttk.Radiobutton(i, text=_(text), value=wert, variable=self.kuerzen_var,
                            command=self._allgemein_geaendert).pack(anchor="w")

    def zuruecksetzen(self):
        self.datei = self.daten = self.gespeichert = None
        self.aktiv_neu = None

    def farben(self):
        super().farben()
        if self.daten is not None:                 # Symbole in den Textfeldern in der neuen Schriftfarbe
            self._formular_fuellen()

    # ------------------------------------------------------------------ Laden
    def neu_laden(self, datei=None):
        """Vorlagen und Stand aus dem Profil lesen; datei: diese zeigen (sonst die bisherige/aktive)."""
        self.info = kpl.erkennen(self.bereich.profil).get(kpl.BOOKENDS)
        if not self.info:
            return
        self.kopf.configure(text=_("Bookends {version} in the profile. Changes show in the picture at once.").format(
            version=self.info["version"] or "?"))
        self.stand_profil = kpl.bookends_stand(self.ko)
        self.aktiv_neu = None
        self.an_var.set(self.stand_profil["an"])
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

    def _wahl_werte(self):
        werte = list(self._namen)
        if self.datei and self.datei not in self._namen.values():          # neue, noch nicht gespeicherte
            werte.append(self._anzeige(self.datei))
        self.wahl.configure(values=werte)

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
        self._formular_fuellen()

    def _formular_fuellen(self):
        self._laden_laeuft = True
        try:
            self._wahl_werte()
            self.wahl_var.set(self._anzeige(self.datei) if self.datei else "")
            d = self.daten or {}
            self.name_var.set(d.get("name") or "")
            self.beschr_var.set(d.get("description") or "")
            for pos, t in self.texte.items():
                t.configure(state="normal")
                t.delete("1.0", "end")
                z = kpl.zeilen(d, pos)
                self._text_einsetzen(t, "1.0", "\n".join(z))
                t.configure(height=max(2, min(6, len(z) + 1)))
                t.edit_modified(False)
                t.edit_reset()
                if self.daten is None:
                    t.configure(state="disabled")
            for schl, v in self.allg_var.items():
                w = kpl.allgemein(d, schl)
                v.set("" if w is None else str(w))
            for (pos, feld), v in self.rand_var.items():
                w = kpl.positionswert(d, pos, feld)
                v.set("" if not w else str(w))
            self.kuerzen_var.set(kpl.allgemein(d, "truncation_priority") or "center")
            self._zeile = None
            self._zeile_zeigen()
            self._balken_zeigen()
        finally:
            self._laden_laeuft = False
        self._aktiv_zeigen()
        self.stand_zeigen()

    def _aktiv_zeigen(self):
        aktiv = self.aktiv_neu or self.stand_profil["aktiv"]
        if not self.datei:
            text = _("No preset in the profile. \"New\" makes one.")
        elif self.datei == aktiv:
            text = _("This is the active preset (Bookends uses it on the e-reader).")
        else:
            text = _("Not active: on the e-reader Bookends uses \"{name}\". The picture shows this one.").format(
                name=self._anzeige(aktiv) if aktiv else "?")
        self.aktiv_text.configure(text=text)
        self.aktiv_knopf.configure(state="normal" if self.datei and self.datei != aktiv else "disabled")

    def _tokens_fuellen(self):
        m = self.token_menue
        m.delete(0, "end")
        gruppen = {}
        for gruppe, token, beschreibung in kpl.tokens(self.info["ordner"]) if self.info else []:
            if gruppe.lower() == "all":
                continue
            if gruppe not in gruppen:
                gruppen[gruppe] = tk.Menu(m, tearoff=False)
                m.add_cascade(label=gruppe, menu=gruppen[gruppe])
            gruppen[gruppe].add_command(label=f"{token}  -  {beschreibung}", command=lambda t=token: self._einfuegen(t))
        self.token_knopf.configure(state="normal" if gruppen else "disabled")

    # ------------------------------------------------------------------ Bearbeiten
    def ungespeichert(self):
        if self.daten is None:
            return False
        if self.gespeichert is None or self.daten != self.gespeichert:
            return True
        return self.an_var.get() != self.stand_profil["an"] or bool(self.aktiv_neu)

    def _einfuegen(self, token):
        t = self._fokus or self.texte["tc"]
        if self.daten is None:
            return
        self._text_einsetzen(t, "insert", token)
        t.focus_set()

    def symbole_zeigen(self):
        """Fenster mit den Sonderzeichen aus Bookends' Katalog; Klick fügt ins zuletzt benutzte Feld ein."""
        if self._symbolfenster is not None and self._symbolfenster.winfo_exists():
            self._symbolfenster.lift()
            return
        gruppen = kpl.symbole(self.info["ordner"]) if self.info else []
        if not gruppen:
            self.app.status.set(_("This Bookends version has no list of special characters."))
            return
        self._symbolfenster = SymbolFenster(self, gruppen)

    def _text_geaendert(self, pos):
        t = self.texte[pos]
        if not t.edit_modified():
            return
        t.edit_modified(False)
        if self._laden_laeuft or self.daten is None:
            return
        z = self._text_lesen(t).split("\n")
        while z and not z[-1].strip():
            z.pop()
        if z != kpl.zeilen(self.daten, pos):
            kpl.zeilen_setzen(self.daten, pos, z)
            t.configure(height=max(2, min(6, len(z) + 1)))
            self._zeile_gewaehlt(pos)
            self._zeilenbalken_zeigen()                # %bar von Hand eingetippt oder gelöscht
            self._geaendert()

    def _zeile_gewaehlt(self, pos):
        t = self.texte[pos]
        self._fokus = t
        nr = int(t.index("insert").split(".")[0])
        neu = (pos, nr) if self.daten is not None and nr <= len(kpl.zeilen(self.daten, pos)) else None
        if neu != self._zeile:
            self._zeile = neu
            self._zeile_zeigen()

    def _zeile_zeigen(self):
        self._laden_laeuft = True
        try:
            if not self._zeile:
                self.zeile_kopf.configure(text=_("Click into a line above."))
                for w in (self.stil, self.groesse, self.gross, *self.versatz.values()):
                    w.configure(state="disabled")
                self.stil_var.set("")
                self.groesse_var.set("")
                self.gross_var.set(False)
                for v in self.versatz_var.values():
                    v.set("")
                self.seiten.setzen(None, aktiv=False)
                self._zeilenbalken_zeigen()
                return
            pos, nr = self._zeile
            name = dict(kpl.POSITIONEN)[pos]
            self.zeile_kopf.configure(text=_("{position}, line {nr}").format(position=_(name), nr=nr))
            self.stil.configure(state="readonly")
            self.groesse.configure(state="normal")
            self.gross.configure(state="normal")
            for feld, v in self.versatz_var.items():
                self.versatz[feld].configure(state="normal")
                v.set(str(kpl.zeilenwert(self.daten, pos, feld, nr) or 0))
            stil = kpl.zeilenwert(self.daten, pos, "line_style", nr) or "regular"
            self.stil_var.set(_(dict(kpl.STILE).get(stil, kpl.STILE[0][1])))
            g = kpl.zeilenwert(self.daten, pos, "line_font_size", nr)
            self.groesse_var.set("" if g is None else str(g))
            self.gross_var.set(bool(kpl.zeilenwert(self.daten, pos, "line_uppercase", nr)))
            self.seiten.setzen(kpl.zeilenwert(self.daten, pos, "line_page_filter", nr), aktiv=True)
            self._zeilenbalken_zeigen()
        finally:
            self._laden_laeuft = False

    def _zeilentext(self):
        if not self._zeile or self.daten is None:
            return ""
        pos, nr = self._zeile
        z = kpl.zeilen(self.daten, pos)
        return z[nr - 1] if nr <= len(z) else ""

    def _zeilenbalken_zeigen(self):
        """Balken-Felder der gewählten Zeile; nur bedienbar, wenn die Zeile %bar enthält."""
        alt, self._laden_laeuft = self._laden_laeuft, True
        try:
            mit = kpl.hat_balken(self._zeilentext())
            self.zbalken_kopf.configure(text=_("Bar in this line") if mit else
                                        _("No bar in this line (token %bar)."))
            self.zbalken_knopf.configure(text=_("Remove bar") if mit else _("Insert bar"),
                                         state="normal" if self._zeile else "disabled")
            werte = kpl.zeilenbalken(self.daten, *self._zeile) if mit else {}
            for k, w in self.zb.items():
                w.setzen(werte.get(k), aktiv=mit)
            if mit:
                self.zb["striche"].aktiv(werte["art"] == "book" and werte["stil"] != "pacman")
                self.zb["richtung"].aktiv(werte["stil"] not in ("radial", "radial_hollow"))
            for k, v in self.zb_dicke_var.items():
                w = werte.get(k)
                if k == "ungelesen" and w is None:
                    w = werte.get("dicke")
                v.set("" if w is None else str(w))
                self.zb_dicke[k].configure(state="normal" if mit else "disabled")
        finally:
            self._laden_laeuft = alt

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
        tw = self.texte[pos]
        self._laden_laeuft = True
        try:
            tw.delete(f"{nr}.0", f"{nr}.end")
            self._text_einsetzen(tw, f"{nr}.0", t)
            tw.edit_modified(False)
        finally:
            self._laden_laeuft = False
        self._zeilenbalken_zeigen()
        self._geaendert()

    def _zeilenbalken_uebernehmen(self):
        if self._laden_laeuft or not self._zeile or self.daten is None or not kpl.hat_balken(self._zeilentext()):
            return
        werte = {k: w.wert() for k, w in self.zb.items()}
        try:
            for k, v in self.zb_dicke_var.items():
                g = _zahl_oder_leer(v.get())
                werte[k] = None if g is None else int(g)
        except ValueError:
            return
        kpl.zeilenbalken_setzen(self.daten, *self._zeile, werte)
        self.zb["striche"].aktiv(werte["art"] == "book" and werte["stil"] != "pacman")
        self.zb["richtung"].aktiv(werte["stil"] not in ("radial", "radial_hollow"))
        self._geaendert()

    # ------------------------------------------------------------------ Balken über die ganze Breite
    def _balken_zeigen(self):
        alt, self._laden_laeuft = self._laden_laeuft, True
        try:
            d = self.daten or {}
            namen = []
            for n in range(1, kpl.BALKEN_ANZAHL + 1):
                b = kpl.balken(d, n)
                namen.append(_("Bar {nr}").format(nr=n) + (" ✓ " + _(dict(kpl.ANKER)[b.get("v_anchor", "bottom")])
                                                           if b.get("enabled") else ""))
            self.balken_wahl.configure(values=namen)
            nr = self.balken_nr.get()
            self.balken_wahl.current(nr - 1)
            b = kpl.balken(d, nr)
            an = bool(b.get("enabled")) and self.daten is not None
            self.balken_an.set(bool(b.get("enabled")))
            rund = b.get("style") in ("radial", "radial_hollow")
            for feld, w in self.bb.items():
                if feld == "direction":
                    w.optionen([o for o in kpl.RICHTUNGEN if o[0] in kpl.balken_richtungen(b)])
                    w.setzen(kpl.balken_richtung(b), aktiv=an and not rund)
                else:
                    w.setzen(b.get(feld), aktiv=an)
            self.bb["chapter_ticks"].aktiv(an and b.get("type") == "book" and b.get("style") != "pacman")
            relativ = b.get("band_offset") is not None and not kpl.balken_senkrecht(b)
            senkrecht = kpl.balken_senkrecht(b)
            self.bb_zahl_text["height"].configure(text=_("Diameter") if rund else _("Thickness"))
            self.bb_zahl_text["margin_v"].configure(text=_("Distance from the line text") if relativ else
                                                    _("Distance from the edge"))
            self.bb_zahl_text["margin_left"].configure(text=_("Margin top") if senkrecht else _("Margin left"))
            self.bb_zahl_text["margin_right"].configure(text=_("bottom") if senkrecht else _("right"))
            for feld, v in self.bb_zahl_var.items():
                if feld == "margin_v" and relativ:
                    w = b.get("band_offset")
                elif feld == "unread_height":
                    w = b.get("unread_height", b.get("height"))
                else:
                    w = b.get(feld)
                v.set("" if w is None else str(w))
            self.balken_text.configure(text=_("Up to {n} bars across the page. Colours, markers and \"Position "
                                              "relative to line text\" stay as they are; switch those on the "
                                              "e-reader.").format(n=kpl.BALKEN_ANZAHL))
            for kind in self.balken_gitter.winfo_children():
                if isinstance(kind, ttk.Label):
                    kind.configure(state="normal" if an else "disabled")
        finally:
            self._laden_laeuft = alt

    def _balken_gewaehlt(self):
        self.balken_nr.set(self.balken_wahl.current() + 1)
        self._balken_zeigen()

    def _balken_uebernehmen(self):
        if self._laden_laeuft or self.daten is None:
            return
        nr = self.balken_nr.get()
        b = kpl.balken(self.daten, nr)
        werte = {"enabled": True if self.balken_an.get() else False}
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
            for feld, v in self.bb_zahl_var.items():
                g = _zahl_oder_leer(v.get())
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
        if self._laden_laeuft or self.daten is None:
            return
        kpl.balken_anker_setzen(self.daten, self.balken_nr.get(), self.bb["v_anchor"].wert())
        self._balken_zeigen()
        self._geaendert()

    def _zeilenwerte_uebernehmen(self):
        if self._laden_laeuft or not self._zeile or self.daten is None:
            return
        pos, nr = self._zeile
        stil = next((k for k, t in kpl.STILE if _(t) == self.stil_var.get()), "regular")
        kpl.zeilenwert_setzen(self.daten, pos, "line_style", nr, None if stil == "regular" else stil)
        try:
            g = _zahl_oder_leer(self.groesse_var.get())
        except ValueError:
            return
        kpl.zeilenwert_setzen(self.daten, pos, "line_font_size", nr, g)
        kpl.zeilenwert_setzen(self.daten, pos, "line_uppercase", nr, True if self.gross_var.get() else None)
        for feld, v in self.versatz_var.items():
            try:
                w = int(float(v.get().strip().replace(",", ".") or 0))
            except ValueError:
                return
            kpl.zeilenwert_setzen(self.daten, pos, feld, nr, w or None)    # 0 = kein Eintrag, wie Bookends
        kpl.zeilenwert_setzen(self.daten, pos, "line_page_filter", nr, self.seiten.wert())
        self._geaendert()

    def _versatz_zurueck(self):
        for v in self.versatz_var.values():
            v.set("0")
        self._zeilenwerte_uebernehmen()

    def _rand_geaendert(self, pos):
        if self._laden_laeuft or self.daten is None:
            return
        for (p, feld), v in self.rand_var.items():
            if p != pos:
                continue
            try:
                w = _zahl_oder_leer(v.get())
            except ValueError:
                return
            kpl.positionswert_setzen(self.daten, pos, feld, int(w) if w else None)
        self._geaendert()

    def _allgemein_geaendert(self):
        if self._laden_laeuft or self.daten is None:
            return
        for schl, v in self.allg_var.items():
            try:
                kpl.allgemein_setzen(self.daten, schl, _zahl_oder_leer(v.get()))
            except ValueError:
                return
        k = self.kuerzen_var.get()
        kpl.allgemein_setzen(self.daten, "truncation_priority", None if k == "center" and
                             kpl.allgemein(self.gespeichert or {}, "truncation_priority") is None else k)
        self._geaendert()

    def _kopf_geaendert(self):
        if self._laden_laeuft or self.daten is None:
            return
        for schl, var in (("name", self.name_var), ("description", self.beschr_var)):
            w = var.get().strip()
            if w:
                self.daten[schl] = w
            else:
                self.daten.pop(schl, None)
        self._geaendert(bild=False)

    def _geaendert(self, bild=True):
        if self._laden_laeuft:
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
        kpl.bookends_setzen(ko, an=self.an_var.get(), aktiv=self.datei)

    def ins_bild(self):
        """Entwurf in die laufende Werkbank: Vorlage schreiben, übernehmen lassen, neues Bild."""
        wb = self.bereich.werkbank
        if self.daten is None or not self.datei:
            return
        if self.bereich.modus_var.get() != "lesen":
            if self.bereich.unterseite() == self.plugin:  # nur von der eigenen Seite aus die Ansicht wechseln
                self.bereich.modus_setzen("lesen")        # startet neu, in_kopie() bringt den Entwurf mit
            return
        if not (wb and wb.laeuft() and wb.bereit):
            return                                        # beim nächsten Start über in_kopie()
        kpl.vorlage_schreiben(wb.ko, self.datei, self.daten)
        wb.bookends_an(self.an_var.get())
        wb.bookends(self.datei)
        wb.bild()
        self.bereich._takt_planen()

    def nach_start(self):
        """Werkbank ist bereit: nichts zu tun, in_kopie() hat den Entwurf schon hineingeschrieben."""

    def beim_zeigen(self):
        if self.daten is None:
            self.neu_laden()
        if self.bereich.modus_var.get() != "lesen":
            self.bereich.modus_setzen("lesen")

    # ------------------------------------------------------------------ Vorlagen
    def _wahl_gewechselt(self):
        datei = self._namen.get(self.wahl_var.get())
        if datei == self.datei:
            return
        if not self._verwerfen_erlaubt():
            self.wahl_var.set(self._anzeige(self.datei))
            return
        self.aktiv_neu = None
        self.an_var.set(self.stand_profil["an"])
        self._vorlage_zeigen(datei)
        self.ins_bild()

    def _verwerfen_erlaubt(self):
        if not self.ungespeichert():
            return True
        a = messagebox.askyesnocancel(_("Bookends"), _("The preset \"{name}\" has unsaved changes. Save them in the "
                                                       "profile?").format(name=self._anzeige(self.datei)),
                                      parent=self.app)
        if a is None:
            return False
        if a:
            self.speichern()
        return True

    def neu(self, vorlage=None):
        if not self.info or not self._verwerfen_erlaubt():
            return
        name = simpledialog.askstring(_("New preset"), _("Name of the new preset:"), parent=self.app,
                                      initialvalue=(vorlage or {}).get("name", "") and
                                      _("{name} (copy)").format(name=vorlage["name"]))
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
        if not messagebox.askyesno(_("Bookends"), _("Delete the preset \"{name}\" from the profile?").format(
                name=self._anzeige(self.datei)), parent=self.app):
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
        kpl.bookends_setzen(self.ko, an=self.an_var.get(), aktiv=self.aktiv_neu)
        kpl._profil_geaendert(self.bereich.profil, "bookends")
        self.app.status.set(_("Bookends preset \"{name}\" saved in the profile.").format(name=self._anzeige(self.datei)))
        self.neu_laden(self.datei)
        return True

    def verwerfen(self):
        if self.ungespeichert() and not messagebox.askyesno(
                _("Bookends"), _("Discard the unsaved changes?"), parent=self.app):
            return
        datei = self.datei if self.gespeichert is not None else None
        self.datei = self.daten = None
        self.neu_laden(datei)
        self.ins_bild()


class SymbolFenster(tk.Toplevel):
    """Sonderzeichen aus Bookends' Katalog (menu/icons_catalogue.lua), nach Gruppen. Bleibt offen;
    jeder Klick fügt an der Schreibmarke des zuletzt benutzten Zeilenfelds ein."""
    SPALTEN = 10

    def __init__(self, seite, gruppen):
        super().__init__(seite.app)
        self.seite = seite
        self.gruppen = gruppen
        self.title(_("Special characters"))
        self.transient(seite.app)
        self.geometry("460x420")
        oben = ttk.Frame(self, padding=8)
        oben.pack(fill="x")
        ttk.Label(oben, text=_("Group")).pack(side="left")
        self.gruppe_var = tk.StringVar(value=gruppen[0][0])
        cb = ttk.Combobox(oben, textvariable=self.gruppe_var, state="readonly", width=18,
                          values=[g for g, __ in gruppen])
        cb.pack(side="left", padx=(6, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self.fuellen())
        self.roll = kpn.RollFlaeche(self)
        self.roll.pack(fill="both", expand=True, padx=8)
        self.roll.farbe(kth.PALETTE["dunkel" if seite.app.dark_mode.get() else "hell"]["bg"])
        self.text = ttk.Label(self, text="", style="Hinweis.TLabel", padding=8)
        self.text.pack(fill="x")
        if not seite._schrift():
            self.text.configure(text=_("KOReader's symbol font (nerdfonts/symbols.ttf) was not found: symbols show as "
                                       "names. Take the profile from the e-reader to get its fonts."))
        self.knoepfe = []
        self.fuellen()

    def fuellen(self):
        for k in self.knoepfe:
            k.destroy()
        self.knoepfe = []
        liste = dict(self.gruppen).get(self.gruppe_var.get(), [])
        p = kth.PALETTE["dunkel" if self.seite.app.dark_mode.get() else "hell"]
        for n, (ch, name, einfuegen) in enumerate(liste):
            bild = self.seite.glyph_bild(ch, 22, p["fg"]) if kpl.ist_symbol(ch) else None
            if bild is not None:
                k = tk.Label(self.roll.innen, image=bild, width=34, height=34, cursor="hand2", bg=p["feld"])
            else:
                text = ch if not kpl.ist_symbol(ch) else name[:6]
                k = tk.Label(self.roll.innen, text=text, width=3, height=1, font=kth.schrift(14), cursor="hand2",
                             bg=p["feld"], fg=p["fg"])
            k._feste_farben = True
            k.grid(row=n // self.SPALTEN, column=n % self.SPALTEN, padx=1, pady=1, sticky="nsew")
            hinweis = name + (f"  ({einfuegen})" if einfuegen != ch else "")
            k.bind("<Enter>", lambda e, h=hinweis: self.text.configure(text=h))
            k.bind("<Button-1>", lambda e, w=einfuegen: self.seite._einfuegen(w))
            self.knoepfe.append(k)
        self.roll.nach_oben()


# ====================================================================== Bookshelf
class BookshelfSeite(_SymbolText, _Seite):
    plugin = kpl.BOOKSHELF
    titel = "Bookshelf"

    def __init__(self, bereich, eltern):
        super().__init__(bereich, eltern)
        self.datei_werte = None                   # settings.lua im Profil (dict), None = nicht geladen
        self.aenderungen = {}                     # Entwurf: Schlüssel -> Wert (None = löschen)
        self._laden_laeuft = False
        self.var = {}
        self.wahlen = {}                          # Name -> (StringVar, [(wert, text)], holen(), setzen(wert))
        self.farb_felder = {}                     # Schlüssel -> Label (Farbfeld)
        ttk.Label(self.innen, text=_("Bookshelf has no way to reload its settings while running: after a change the "
                                     "workbench restarts on the start screen (about a second)."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").pack(anchor="w", fill="x")
        # dieselbe Einstellung wie unter Ansicht (seit 1.4-beta6): hier, weil sie vor allem Bookshelf betrifft
        sb = ttk.Frame(self.innen)
        sb.pack(anchor="w", fill="x", pady=(6, 0))
        ttk.Label(sb, text=_("Start screen shows:")).pack(anchor="w")
        for wert, text in (("beispiel", _("sample books")), ("bibliothek", _("the opened library"))):
            ttk.Radiobutton(sb, text=text, value=wert, variable=bereich.startbuecher_var,
                            command=bereich._startbuecher_gewechselt).pack(anchor="w", padx=(12, 0))

        # -- Theme, Hintergrund, Brett, Dekoration, Farben (seit 1.4-beta3; Inhalt hängt vom Profil ab) ----
        self.f_theme = self._abschnitt("theme", _("Themes"))
        self.f_hintergrund = self._abschnitt("hintergrund", _("Wallpaper"), offen=False)
        self.f_brett = self._abschnitt("brett", _("Plank"), offen=False)
        self.f_deko = self._abschnitt("deko", _("Decoration (ornaments)"), offen=False)
        self.f_farben = self._abschnitt("farben", _("Colours"), offen=False)
        self._hero_bauen(self._abschnitt("hero", _("Top panel"), offen=False))
        self._module_bauen(self._abschnitt("module", _("Modules in the top panel"), offen=False))
        self._menue_bauen(self._abschnitt("startmenue", _("Start menu"), offen=False))
        self._regale_bauen(self._abschnitt("regale", _("Shelves"), offen=False))

        # -- feste Auswahl ------------------------------------------------------------------
        for gruppe, gtext in kpl.BOOKSHELF_GRUPPEN:
            f = self._abschnitt(gruppe, _(gtext), offen=(gruppe == "anordnung"))
            f.columnconfigure(1, weight=1)
            r = 0
            for schl, g, text, art, vorgabe, wahl in kpl.BOOKSHELF_WERTE:
                if g != gruppe:
                    continue
                if art == "an":
                    v = self.var[schl] = tk.BooleanVar()
                    ttk.Checkbutton(f, text=_(text), variable=v,
                                    command=lambda s=schl: self._wert_geaendert(s)).grid(row=r, column=0, columnspan=2,
                                                                                         sticky="w", pady=1)
                elif art == "zahl":
                    ttk.Label(f, text=_(text)).grid(row=r, column=0, sticky="w", padx=(0, 6), pady=1)
                    v = self.var[schl] = tk.StringVar()
                    sp = ttk.Spinbox(f, from_=0, to=400, width=6, textvariable=v,
                                     command=lambda s=schl: self._wert_geaendert(s))
                    sp.grid(row=r, column=1, sticky="w", pady=1)
                    sp.bind("<KeyRelease>", lambda e, s=schl: self._wert_geaendert(s))
                else:
                    ttk.Label(f, text=_(text)).grid(row=r, column=0, sticky="w", padx=(0, 6), pady=1)
                    v = self.var[schl] = tk.StringVar()
                    cb = ttk.Combobox(f, textvariable=v, state="readonly", width=16, values=[_(t) for __, t in wahl])
                    cb.grid(row=r, column=1, sticky="w", pady=1)
                    cb.bind("<<ComboboxSelected>>", lambda e, s=schl: self._wert_geaendert(s))
                r += 1

        # -- alle Schlüssel ---------------------------------------------------------------
        i = self._abschnitt("alle", _("All keys in the file"), offen=False)
        ttk.Label(i, text=_("For everything not listed above. Double-click a simple value to change it; tables "
                            "(shelves, modules) only in the sections above or in Bookshelf itself. \"Default\" removes "
                            "the key, then Bookshelf's default applies."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").pack(anchor="w", fill="x")
        r = self.app._listenrahmen(i)
        r.pack(fill="x", pady=(4, 0))
        self.baum = ttk.Treeview(r, columns=("wert",), height=10, selectmode="browse")
        self.baum.heading("#0", text=_("Key"))
        self.baum.heading("wert", text=_("Value"))
        self.baum.column("#0", width=180, stretch=True)
        self.baum.column("wert", width=140, stretch=True)
        sb = ttk.Scrollbar(r, orient="vertical", command=self.baum.yview)
        self.baum.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.baum.pack(side="left", fill="x", expand=True)
        self.baum.bind("<Double-Button-1>", lambda e: self.schluessel_bearbeiten())
        z = ttk.Frame(i)
        z.pack(anchor="w", pady=(4, 0))
        ttk.Button(z, text=_("Change …"), style="Klein.TButton",
                   command=self.schluessel_bearbeiten).pack(side="left", padx=(0, 4))
        ttk.Button(z, text=_("Default"), style="Klein.TButton", command=self.schluessel_loeschen).pack(side="left")

    # ------------------------------------------------------------------ Oberer Bereich (Hero-Karte, seit 1.4-beta7)
    def _hero_bauen(self, i):
        z = ttk.Frame(i)
        z.pack(anchor="w", fill="x")
        ttk.Label(z, text=_("Shows")).pack(side="left")
        self.hero_modus = _Wahl(z, kpl.HERO_MODUS, self._hero_modus_geaendert, breite=26)
        self.hero_modus.box.pack(side="left", padx=(4, 0))
        ttk.Label(i, text=_("Lines of the hero card (the current book):"), style="Hinweis.TLabel").pack(
            anchor="w", pady=(8, 0))
        z = ttk.Frame(i)
        z.pack(anchor="w", fill="x", pady=(2, 0))
        self.hero_kennung = "metadata"
        self.hero_wahl = ttk.Combobox(z, state="readonly", width=24)
        self.hero_wahl.pack(side="left")
        self.hero_wahl.bind("<<ComboboxSelected>>", lambda e: self._hero_gewaehlt())
        self.hero_an = tk.BooleanVar()
        ttk.Checkbutton(z, text=_("Shown"), variable=self.hero_an,
                        command=self._hero_uebernehmen).pack(side="left", padx=(8, 0))
        self.hero_text = tk.Text(i, height=2, wrap="word", undo=True, borderwidth=1, relief="solid",
                                 font=("", 10), highlightthickness=0)
        self.hero_text.pack(anchor="w", fill="x", pady=(4, 0))
        self.hero_text.bind("<<Modified>>", self._hero_text_geaendert)
        z = ttk.Frame(i)
        z.pack(anchor="w", fill="x", pady=(2, 0))
        self.hero_token = ttk.Menubutton(z, text=_("Insert token"), style="Klein.TButton")
        self.hero_token.pack(side="left")
        self.hero_token_menue = tk.Menu(self.hero_token, tearoff=False)
        self.hero_token["menu"] = self.hero_token_menue
        self.hero_untertitel = ttk.Button(z, text=_("Subtitle"), style="Klein.TButton",
                                          command=self._hero_untertitel)
        self.hero_untertitel.pack(side="left", padx=(4, 0))
        ttk.Button(z, text=_("Default"), style="Klein.TButton",
                   command=self._hero_zuruecksetzen).pack(side="left", padx=(4, 0))
        g = self.hero_gitter = ttk.Frame(i)
        g.pack(anchor="w", fill="x", pady=(4, 0))
        ttk.Label(g, text=_("Size")).grid(row=0, column=0, sticky="w")
        self.hero_groesse = tk.StringVar()
        sp = self.hero_groesse_feld = ttk.Spinbox(g, from_=6, to=72, width=4, textvariable=self.hero_groesse,
                                                  command=self._hero_uebernehmen)
        sp.grid(row=0, column=1, sticky="w", padx=(4, 10))
        sp.bind("<KeyRelease>", lambda e: self._hero_uebernehmen())
        self.hero_ausrichtung = _Wahl(g, kpl.HERO_AUSRICHTUNG, self._hero_uebernehmen, breite=8)
        self.hero_ausrichtung.box.grid(row=0, column=2, sticky="w")
        self.hero_fett, self.hero_gross = tk.BooleanVar(), tk.BooleanVar()
        self.hero_fett_knopf = ttk.Checkbutton(g, text=_("Bold"), variable=self.hero_fett,
                                               command=self._hero_uebernehmen)
        self.hero_fett_knopf.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self.hero_gross_knopf = ttk.Checkbutton(g, text=_("Capitals"), variable=self.hero_gross,
                                                command=self._hero_uebernehmen)
        self.hero_gross_knopf.grid(row=1, column=2, sticky="w", pady=(2, 0))
        # nur für die Tag-Zeile
        self.hero_tags_rahmen = ttk.Frame(i)
        self.hero_tags_var = {}
        for n, (feld, text) in enumerate(kpl.HERO_TAGS):
            v = self.hero_tags_var[feld] = tk.BooleanVar()
            ttk.Checkbutton(self.hero_tags_rahmen, text=_(text), variable=v,
                            command=self._hero_uebernehmen).grid(row=n // 3, column=n % 3, sticky="w", padx=(0, 8))
        ttk.Label(self.hero_tags_rahmen, text=_("Rows at most")).grid(row=2, column=0, sticky="w", pady=(2, 0))
        self.hero_zeilen = tk.StringVar()
        sp = ttk.Spinbox(self.hero_tags_rahmen, from_=1, to=5, width=3, textvariable=self.hero_zeilen,
                         command=self._hero_uebernehmen)
        sp.grid(row=2, column=1, sticky="w", pady=(2, 0))
        sp.bind("<KeyRelease>", lambda e: self._hero_uebernehmen())
        self.hero_hinweis = ttk.Label(i, text="", style="Hinweis.TLabel", wraplength=BREITE, justify="left")
        self.hero_hinweis.pack(anchor="w", fill="x", pady=(4, 0))

    def _hero_werte(self):
        """Einstellungen mit Entwurf, für hero_zeile()."""
        return {"hero_regions": self._wert("hero_regions")}

    def _hero_fuellen(self):
        if not hasattr(self, "hero_wahl"):
            return
        alt, self._laden_laeuft = self._laden_laeuft, True
        try:
            w = self._hero_werte()
            self.hero_modus.setzen(self._wert("hero_area_mode", "currently_reading"))
            namen = []
            for k, t in kpl.HERO_ZEILEN:
                namen.append(_(t) + ("" if kpl.hero_zeile(w, k).get("disabled") else "  ✓"))
            self.hero_wahl.configure(values=namen)
            kennung = self.hero_kennung
            self.hero_wahl.current([k for k, __ in kpl.HERO_ZEILEN].index(kennung))
            z = kpl.hero_zeile(w, kennung)
            self.hero_an.set(not z.get("disabled"))
            mit_text = kennung not in kpl.HERO_OHNE_VORLAGE
            self.hero_text.configure(state="normal")
            self.hero_text.delete("1.0", "end")
            if mit_text:
                self._text_einsetzen(self.hero_text, "1.0", z.get("template") or "")
            self.hero_text.edit_modified(False)
            self.hero_text.configure(state="normal" if mit_text else "disabled")
            for knopf in (self.hero_token, self.hero_untertitel):
                knopf.configure(state="normal" if mit_text else "disabled")
            self.hero_groesse.set(str(z.get("font_size", "")))
            self.hero_ausrichtung.setzen(z.get("alignment", "left"))
            self.hero_fett.set(bool(z.get("bold")))
            self.hero_gross.set(bool(z.get("uppercase")))
            self.hero_fett_knopf.configure(state="normal" if mit_text else "disabled")
            self.hero_gross_knopf.configure(state="normal" if mit_text and kennung != "description" else "disabled")
            if kennung == "tags":
                self.hero_tags_rahmen.pack(anchor="w", fill="x", pady=(4, 0), after=self.hero_gitter)
                for feld, v in self.hero_tags_var.items():
                    v.set(z.get(feld, True) is not False)
                self.hero_zeilen.set(str(z.get("max_rows", 2)))
            else:
                self.hero_tags_rahmen.pack_forget()
            hinweis = {
                "rating": _("Stars to tap; only on/off, size and alignment."),
                "tags": _("Buttons for author, series, collections, genres and folder, each can be hidden."),
                "metadata": _("An extra line between author and description; Bookshelf puts the series here by "
                              "default. \"Subtitle\" puts the book's subtitle here (needs the Bookbench patch "
                              "2-bookbench-subtitle, page Patches)."),
            }.get(kennung, _("Tokens like in Bookshelf's line editor, [if:token]…[/if] shows a part only if the "
                             "token has a value. Empty = the line is left out."))
            if mit_text and "%subtitle" in self._hero_text_lesen() and not self._untertitel_patch():
                hinweis += "\n" + _("⚠ %subtitle needs the patch 2-bookbench-subtitle in the profile (page Patches).")
            self.hero_hinweis.configure(text=hinweis)
            self._hero_token_menue_fuellen()
        finally:
            self._laden_laeuft = alt

    def _untertitel_patch(self):
        d = Path(self.ko) / "patches"
        return (d / "2-bookbench-subtitle.lua").is_file()

    def _hero_token_menue_fuellen(self):
        m = self.hero_token_menue
        m.delete(0, "end")
        gruppen = {}
        tokens = list(kpl.bookshelf_tokens(self.info["ordner"])) if getattr(self, "info", None) else []
        tokens.append(("Bookbench", "%subtitle", _("Subtitle from the EPUB (needs the Bookbench patch)")))
        for gruppe, token, text in tokens:
            if gruppe not in gruppen:
                gruppen[gruppe] = tk.Menu(m, tearoff=False)
                m.add_cascade(label=gruppe, menu=gruppen[gruppe])
            gruppen[gruppe].add_command(label=f"{token}  –  {text}", command=lambda t=token: self._hero_einfuegen(t))

    def _hero_einfuegen(self, token):
        if str(self.hero_text.cget("state")) == "disabled":
            return
        self._text_einsetzen(self.hero_text, "insert", token)
        self.hero_text.focus_set()

    def _hero_untertitel(self):
        """Untertitel in die Zeile setzen (Metadata: ersetzt die Reihe; sonst ans Ende)."""
        if self.hero_kennung == "metadata":
            text = kpl.HERO_UNTERTITEL
        else:
            text = (self._hero_text_lesen() + " " + kpl.HERO_UNTERTITEL).strip()
        self.hero_text.delete("1.0", "end")
        self._text_einsetzen(self.hero_text, "1.0", text)

    def _hero_text_lesen(self):
        return self._text_lesen(self.hero_text).strip("\n")

    def _hero_text_geaendert(self, e=None):
        if not self.hero_text.edit_modified():
            return
        self.hero_text.edit_modified(False)
        self._hero_uebernehmen()

    def _hero_gewaehlt(self):
        self.hero_kennung = kpl.HERO_ZEILEN[self.hero_wahl.current()][0]
        self._hero_fuellen()

    def _hero_uebernehmen(self):
        if self._laden_laeuft or self.datei_werte is None:
            return
        k = self.hero_kennung
        felder = {"disabled": None if self.hero_an.get() else True}
        try:
            g = _zahl_oder_leer(self.hero_groesse.get())
        except ValueError:
            return
        felder["font_size"] = None if g is None else int(g)
        felder["alignment"] = self.hero_ausrichtung.wert()
        if k not in kpl.HERO_OHNE_VORLAGE:
            felder["template"] = self._hero_text_lesen()
            felder["bold"] = bool(self.hero_fett.get())
            if k != "description":
                felder["uppercase"] = bool(self.hero_gross.get())
        if k == "tags":
            for feld, v in self.hero_tags_var.items():
                felder[feld] = bool(v.get())
            try:
                n = _zahl_oder_leer(self.hero_zeilen.get())
            except ValueError:
                return
            felder["max_rows"] = None if n is None else max(1, min(5, int(n)))
        neu = kpl.hero_aendern(self._hero_werte(), k, **felder)
        self._hero_setzen(neu)

    def _hero_setzen(self, neu):
        """hero_regions als Ganzes in den Entwurf (ohne das Formular neu zu bauen, damit das Textfeld
        beim Tippen den Cursor behält)."""
        im_profil = (self.datei_werte or {}).get("hero_regions")
        if _gleich(neu, im_profil):
            self.aenderungen.pop("hero_regions", None)
        else:
            self.aenderungen["hero_regions"] = neu
        self._hero_fuellen_ausser_text()
        self.stand_zeigen()
        self._planen(PAUSE_BOOKSHELF, self.ins_bild)

    def _hero_fuellen_ausser_text(self):
        w = self._hero_werte()
        self.hero_wahl.configure(values=[_(t) + ("" if kpl.hero_zeile(w, k).get("disabled") else "  ✓")
                                         for k, t in kpl.HERO_ZEILEN])
        self.hero_wahl.current([k for k, __ in kpl.HERO_ZEILEN].index(self.hero_kennung))

    def _hero_zuruecksetzen(self):
        if self.datei_werte is None:
            return
        neu = kpl.hero_zuruecksetzen(self._hero_werte(), self.hero_kennung)
        im_profil = (self.datei_werte or {}).get("hero_regions")
        if _gleich(neu, im_profil):
            self.aenderungen.pop("hero_regions", None)
        else:
            self.aenderungen["hero_regions"] = neu
        self._formular_fuellen()
        self._planen(PAUSE_BOOKSHELF, self.ins_bild)

    def _hero_modus_geaendert(self):
        if self._laden_laeuft or self.datei_werte is None:
            return
        self._setzen("hero_area_mode", self.hero_modus.wert(), "currently_reading")

    # ------------------------------------------------------------------ Listen: Module, Startmenü, Regale (1.4-beta7)
    def _liste(self, i, hoehe=8, spalte=None):
        r = self.app._listenrahmen(i)
        r.pack(fill="x", pady=(2, 0))
        baum = ttk.Treeview(r, columns=("b",) if spalte else (), show="tree", height=hoehe, selectmode="browse")
        if spalte:
            baum.column("#0", width=200, stretch=True)
            baum.column("b", width=spalte, stretch=False)
        sb = ttk.Scrollbar(r, orient="vertical", command=baum.yview)
        baum.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        baum.pack(side="left", fill="x", expand=True)
        return baum

    def _knoepfe(self, i, knoepfe, spalten=3):
        z = ttk.Frame(i)
        z.pack(anchor="w", fill="x", pady=(4, 0))
        erg = {}
        for n, (text, befehl) in enumerate(knoepfe):
            if befehl is None:                    # Menüknopf
                w = ttk.Menubutton(z, text=text, style="Klein.TButton")
                w.menue = tk.Menu(w, tearoff=False)     # w["menu"] liefert nur den Namen
                w["menu"] = w.menue
            else:
                w = ttk.Button(z, text=text, style="Klein.TButton", command=befehl)
            w.grid(row=n // spalten, column=n % spalten, sticky="we", padx=(0, 4), pady=(0, 2))
            erg[text] = w
        return erg

    def _gewaehlt_id(self, baum):
        sel = baum.selection()
        return sel[0] if sel else None

    def _liste_setzen(self, schl, neu, zaehler=None, waehlen=None):
        if zaehler is not None:
            self.aenderungen[zaehler[0]] = zaehler[1]
        self._setzen(schl, neu)
        if schl == "tabs":
            self._dynamisch_bauen()
            self._formular_fuellen()
        for baum in (self.mod_baum, self.menue_baum, self.regal_baum):
            if waehlen and baum.exists(waehlen):
                baum.selection_set(waehlen)
                baum.see(waehlen)

    # -- Module im oberen Bereich
    def _module_bauen(self, i):
        self.mod_hinweis = ttk.Label(i, text="", style="Hinweis.TLabel", wraplength=BREITE, justify="left")
        self.mod_hinweis.pack(anchor="w", fill="x")
        self.mod_baum = self._liste(i, 6, spalte=120)
        self.mod_baum.bind("<<TreeviewSelect>>", lambda e: self._mod_position_zeigen())
        k = self._knoepfe(i, ((_("Add"), None), (_("Up"), lambda: self._mod_schieben(-1)),
                              (_("Down"), lambda: self._mod_schieben(1)), (_("Remove"), self._mod_entfernen)), 3)
        self.mod_neu = k[_("Add")]
        pz = ttk.Frame(i)
        pz.pack(anchor="w", fill="x", pady=(4, 0))
        self.mod_auto = tk.BooleanVar()
        self.mod_auto_knopf = ttk.Checkbutton(pz, text=_("Place automatically"), variable=self.mod_auto,
                                              command=self._mod_position_uebernehmen)
        self.mod_auto_knopf.grid(row=0, column=0, columnspan=10, sticky="w")
        self.mod_pos, self.mod_pos_felder = {}, []
        for n, (feld, text) in enumerate(zip(kpl.POSITION, (_("Page"), _("Column"), _("Row"), _("Width"),
                                                             _("Height")))):
            ttk.Label(pz, text=text).grid(row=1 + n // 3, column=(n % 3) * 2, sticky="w", padx=(0 if n % 3 == 0 else 8, 2))
            v = self.mod_pos[feld] = tk.StringVar()
            sp = ttk.Spinbox(pz, from_=1, to=12, width=3, textvariable=v, command=self._mod_position_uebernehmen)
            sp.grid(row=1 + n // 3, column=(n % 3) * 2 + 1, sticky="w", pady=1)
            sp.bind("<KeyRelease>", lambda e: self._mod_position_uebernehmen())
            self.mod_pos_felder.append(sp)
        ttk.Label(i, text=_("Positions in grid cells. The top panel has 1 or 2 rows and 2 to 8 columns, depending on "
                            "the screen; Bookshelf moves a module that does not fit or overlaps another. Modules "
                            "that need a choice (action, shelf, ornament) are added in Bookshelf."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").pack(anchor="w", fill="x", pady=(4, 0))

    def _modulnamen(self):
        if not hasattr(self, "_mod_namen") and getattr(self, "info", None):
            self._mod_namen = kpl.micromodule(self.info["ordner"])
        return getattr(self, "_mod_namen", [])

    def _mod_liste(self):
        w = self._wert(kpl.MODULE_SCHLUESSEL[0])
        return w if isinstance(w, list) else None

    def _mod_fuellen(self):
        liste = self._mod_liste()
        b = self.mod_baum
        sel = self._gewaehlt_id(b)
        b.delete(*b.get_children())
        titel = {m["key"]: _(m["titel"]) for m in self._modulnamen()}
        for e in liste or []:
            if not isinstance(e, dict) or not e.get("id"):
                continue
            at = e.get("at")
            pos = (_("page {seite}: {spalte}/{reihe}, {w}×{h}").format(
                seite=at.get("page"), spalte=at.get("col"), reihe=at.get("row"), w=at.get("w"), h=at.get("h"))
                   if isinstance(at, dict) else _("automatic"))
            b.insert("", "end", iid=e["id"], text=titel.get(e.get("module"), e.get("module", "?")), values=(pos,))
        if sel and b.exists(sel):
            b.selection_set(sel)
        da = liste is not None
        self.mod_hinweis.configure(text="" if da else _("Bookshelf has not set up the modules yet: open the top "
                                                         "panel's modules once on the e-reader."))
        self.mod_neu.configure(state="normal" if da else "disabled")
        m = self.mod_neu.menue
        m.delete(0, "end")
        for mod in self._modulnamen():
            if mod["key"] in kpl.MODULE_MIT_EINRICHTUNG:
                continue
            m.add_command(label=f"{_(mod['titel'])}  –  {_(mod['text'])}" if mod["text"] else _(mod["titel"]),
                          command=lambda k=mod["key"]: self._mod_hinzufuegen(k))
        self._mod_position_zeigen()

    def _mod_position_zeigen(self):
        alt, self._laden_laeuft = self._laden_laeuft, True
        try:
            kennung = self._gewaehlt_id(self.mod_baum)
            l, n = kpl.eintrag_suchen(self._mod_liste() or [], kennung)
            e = l[n] if l is not None else None
            at = e.get("at") if e else None
            self.mod_auto.set(e is not None and not isinstance(at, dict))
            self.mod_auto_knopf.configure(state="normal" if e else "disabled")
            for feld, sp in zip(kpl.POSITION, self.mod_pos_felder):
                self.mod_pos[feld].set(str(at.get(feld, "")) if isinstance(at, dict) else "")
                sp.configure(state="normal" if isinstance(at, dict) else "disabled")
        finally:
            self._laden_laeuft = alt

    def _mod_position_uebernehmen(self):
        if self._laden_laeuft:
            return
        kennung = self._gewaehlt_id(self.mod_baum)
        liste = self._mod_liste()
        if not kennung or liste is None:
            return
        if self.mod_auto.get():
            neu = kpl.aendern(liste, kennung, at=None)
        else:
            l, n = kpl.eintrag_suchen(liste, kennung)
            alt = l[n].get("at") if isinstance(l[n].get("at"), dict) else {"page": 1, "col": 1, "row": 1, "w": 2, "h": 1}
            at = {}
            for feld in kpl.POSITION:
                try:
                    w = int(self.mod_pos[feld].get())
                except ValueError:
                    w = alt.get(feld, 1)
                at[feld] = max(1, min(12, w))
            neu = kpl.aendern(liste, kennung, at=at)
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
        kennung, liste = self._gewaehlt_id(self.mod_baum), self._mod_liste()
        if kennung and liste is not None:
            self._liste_setzen(kpl.MODULE_SCHLUESSEL[0], kpl.verschieben(liste, kennung, schritt), waehlen=kennung)

    def _mod_entfernen(self):
        kennung, liste = self._gewaehlt_id(self.mod_baum), self._mod_liste()
        if kennung and liste is not None:
            self._liste_setzen(kpl.MODULE_SCHLUESSEL[0], kpl.entfernen(liste, kennung))

    # -- Startmenü
    def _menue_bauen(self, i):
        self.menue_hinweis = ttk.Label(i, text="", style="Hinweis.TLabel", wraplength=BREITE, justify="left")
        self.menue_hinweis.pack(anchor="w", fill="x")
        self.menue_baum = self._liste(i, 9)
        self.menue_baum.bind("<Double-Button-1>", lambda e: self._menue_umbenennen())
        k = self._knoepfe(i, ((_("Add"), None), (_("Up"), lambda: self._menue_schieben(-1)),
                              (_("Down"), lambda: self._menue_schieben(1)), (_("Folder"), None),
                              (_("Rename …"), self._menue_umbenennen), (_("Remove"), self._menue_entfernen)), 3)
        self.menue_neu, self.menue_ordner = k[_("Add")], k[_("Folder")]
        ttk.Label(i, text=_("A folder holds entries, one level deep as in Bookshelf. New entries are Bookshelf's "
                            "standard ones; other actions and icons are set in Bookshelf's start menu editor."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").pack(anchor="w", fill="x", pady=(4, 0))

    def _menue_liste(self):
        w = self._wert(kpl.STARTMENUE_SCHLUESSEL[0])
        return w if isinstance(w, list) else None

    def _menue_text(self, e, titel):
        art = e.get("type")
        if art == "divider":
            return "──────────"
        if art == "module":
            return "▣ " + titel.get(e.get("module"), e.get("module", "?"))
        text = str(e.get("label") or "?")
        return text                               # Ordner erkennt man am Aufklapp-Zeichen des Baums

    def _menue_fuellen(self):
        liste = self._menue_liste()
        b = self.menue_baum
        sel = self._gewaehlt_id(b)
        b.delete(*b.get_children())
        titel = {m["key"]: _(m["titel"]) for m in self._modulnamen()}
        ordner = []
        for e in liste or []:
            if not isinstance(e, dict) or not e.get("id"):
                continue
            b.insert("", "end", iid=e["id"], text=self._menue_text(e, titel), open=True)
            if e.get("type") == "folder":
                ordner.append(e)
                for c in e.get("children") or []:
                    if isinstance(c, dict) and c.get("id"):
                        b.insert(e["id"], "end", iid=c["id"], text=self._menue_text(c, titel))
        if sel and b.exists(sel):
            b.selection_set(sel)
        da = liste is not None
        self.menue_hinweis.configure(text="" if da else _("Bookshelf has not set up its start menu yet: open it "
                                                           "once on the e-reader."))
        for knopf in (self.menue_neu, self.menue_ordner):
            knopf.configure(state="normal" if da else "disabled")
        m = self.menue_neu.menue
        m.delete(0, "end")
        m.add_command(label=_("Folder …"), command=self._menue_neuer_ordner)
        m.add_command(label=_("Divider"), command=lambda: self._menue_neu({"type": "divider"}))
        mm = tk.Menu(m, tearoff=False)
        for mod in self._modulnamen():
            if mod["nur_oben"]:
                continue
            mm.add_command(label=_(mod["titel"]), command=lambda k=mod["key"]: self._menue_neu(
                {"type": "module", "module": k}))
        m.add_cascade(label=_("Module"), menu=mm)
        sm = tk.Menu(m, tearoff=False)
        for vorlage in STARTMENUE_STANDARD:
            sm.add_command(label=_(vorlage["label"]), command=lambda v=vorlage: self._menue_neu(
                {**copy.deepcopy(v), "label": _(v["label"])}))
        m.add_cascade(label=_("Standard entry"), menu=sm)
        om = self.menue_ordner.menue
        om.delete(0, "end")
        for o in ordner:
            om.add_command(label=_("Into \"{name}\"").format(name=o.get("label", "?")),
                           command=lambda k=o["id"]: self._menue_in_ordner(k))
        om.add_command(label=_("Out of the folder"), command=lambda: self._menue_in_ordner(None))

    def _menue_neu(self, eintrag):
        liste = self._menue_liste()
        if liste is None:
            return
        werte = dict(self.datei_werte or {})
        werte.update({k: v for k, v in self.aenderungen.items() if v is not None})
        kennung, zaehler = kpl.neue_id(werte, kpl.STARTMENUE_SCHLUESSEL[1], kpl.STARTMENUE_SCHLUESSEL[2])
        neu = copy.deepcopy(liste)
        e = {"id": kennung, **eintrag}
        sel = self._gewaehlt_id(self.menue_baum)
        l, n = kpl.eintrag_suchen(neu, sel) if sel else (None, None)
        if l is not None and (l is neu or e["type"] not in ("folder", "divider")):
            l.insert(n + 1, e)                    # hinter dem gewählten Eintrag, in seiner Ebene
        else:
            neu.append(e)
        self._liste_setzen(kpl.STARTMENUE_SCHLUESSEL[0], neu, (kpl.STARTMENUE_SCHLUESSEL[1], zaehler), waehlen=kennung)

    def _menue_neuer_ordner(self):
        name = simpledialog.askstring(_("Start menu"), _("Name of the folder:"), parent=self.app)
        if name and name.strip():
            self._menue_neu({"type": "folder", "label": name.strip(), "children": []})

    def _menue_umbenennen(self):
        kennung, liste = self._gewaehlt_id(self.menue_baum), self._menue_liste()
        if not kennung or liste is None:
            return
        l, n = kpl.eintrag_suchen(liste, kennung)
        if l is None or l[n].get("type") not in ("action", "folder"):
            self.app.status.set(_("Only entries and folders have a name."))
            return
        name = simpledialog.askstring(_("Start menu"), _("New name:"), initialvalue=l[n].get("label", ""),
                                      parent=self.app)
        if name and name.strip():
            self._liste_setzen(kpl.STARTMENUE_SCHLUESSEL[0], kpl.aendern(liste, kennung, label=name.strip()),
                               waehlen=kennung)

    def _menue_schieben(self, schritt):
        kennung, liste = self._gewaehlt_id(self.menue_baum), self._menue_liste()
        if kennung and liste is not None:
            self._liste_setzen(kpl.STARTMENUE_SCHLUESSEL[0], kpl.verschieben(liste, kennung, schritt), waehlen=kennung)

    def _menue_in_ordner(self, ordner):
        kennung, liste = self._gewaehlt_id(self.menue_baum), self._menue_liste()
        if kennung and liste is not None:
            neu = kpl.in_ordner(liste, kennung, ordner)
            if neu == liste:
                self.app.status.set(_("Folders and dividers stay at the top level."))
                return
            self._liste_setzen(kpl.STARTMENUE_SCHLUESSEL[0], neu, waehlen=kennung)

    def _menue_entfernen(self):
        kennung, liste = self._gewaehlt_id(self.menue_baum), self._menue_liste()
        if not kennung or liste is None:
            return
        l, n = kpl.eintrag_suchen(liste, kennung)
        if l is not None and l[n].get("type") == "folder" and l[n].get("children") and not messagebox.askyesno(
                _("Start menu"), _("Remove the folder with its {n} entries?").format(n=len(l[n]["children"])),
                parent=self.app):
            return
        self._liste_setzen(kpl.STARTMENUE_SCHLUESSEL[0], kpl.entfernen(liste, kennung))

    # -- Regale
    def _regale_bauen(self, i):
        self.regal_hinweis = ttk.Label(i, text="", style="Hinweis.TLabel", wraplength=BREITE, justify="left")
        self.regal_hinweis.pack(anchor="w", fill="x")
        self.regal_baum = self._liste(i, 8, spalte=90)
        self.regal_baum.bind("<Double-Button-1>", lambda e: self._regal_umschalten())
        self.regal_baum.bind("<<TreeviewSelect>>", lambda e: self._regal_ansicht_zeigen())
        k = self._knoepfe(i, ((_("On/off"), self._regal_umschalten), (_("Up"), lambda: self._regal_schieben(-1)),
                              (_("Down"), lambda: self._regal_schieben(1)), (_("Rename …"), self._regal_umbenennen),
                              (_("Add"), None), (_("Remove"), self._regal_entfernen)), 3)
        self.regal_neu = k[_("Add")]
        self.regal_knoepfe = list(k.values())
        z = ttk.Frame(i)
        z.pack(anchor="w", fill="x", pady=(4, 0))
        ttk.Label(z, text=_("Shown as")).pack(side="left")
        self.regal_ansicht = _Wahl(z, kpl.ANSICHTEN, self._regal_ansicht_uebernehmen, breite=14)
        self.regal_ansicht.box.pack(side="left", padx=(4, 0))
        ttk.Label(i, text=_("☑ shown as a button above the shelf, ☐ hidden. Sorting, filters and new shelves from "
                            "collections or folders are set in Bookshelf; removed standard shelves can be added "
                            "again here."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").pack(anchor="w", fill="x", pady=(4, 0))

    def _regale_fuellen(self):
        liste = self._wert("tabs")
        liste = liste if isinstance(liste, list) else None
        b = self.regal_baum
        sel = self._gewaehlt_id(b)
        b.delete(*b.get_children())
        ansichten = dict(kpl.ANSICHTEN)
        for e in liste or []:
            if not isinstance(e, dict) or not e.get("id"):
                continue
            text = ("☐ " if e.get("enabled") is False else "☑ ") + str(e.get("label") or e["id"])
            b.insert("", "end", iid=e["id"], text=text, values=(_(ansichten.get(e.get("view_mode"),
                                                                                 ansichten[None])),))
        if sel and b.exists(sel):
            b.selection_set(sel)
        da = liste is not None
        self.regal_hinweis.configure(text="" if da else _("Bookshelf still uses its standard shelves; change them "
                                                           "once on the e-reader, then they can be edited here."))
        for knopf in self.regal_knoepfe:
            knopf.configure(state="normal" if da else "disabled")
        m = self.regal_neu.menue
        m.delete(0, "end")
        vorhanden = {e.get("id") for e in liste or [] if isinstance(e, dict)}
        fehlend = [r for r in kpl.REGALE_EINGEBAUT if r["id"] not in vorhanden]
        for r in fehlend:
            m.add_command(label=_(r["label"]), command=lambda r=r: self._regal_hinzufuegen(r))
        if not fehlend:
            m.add_command(label=_("All standard shelves are there."), state="disabled")
        self._regal_ansicht_zeigen()

    def _regal_liste(self):
        w = self._wert("tabs")
        return w if isinstance(w, list) else None

    def _regal_ansicht_zeigen(self):
        alt, self._laden_laeuft = self._laden_laeuft, True
        try:
            kennung, liste = self._gewaehlt_id(self.regal_baum), self._regal_liste()
            l, n = kpl.eintrag_suchen(liste or [], kennung)
            self.regal_ansicht.setzen(l[n].get("view_mode") if l is not None else None, aktiv=l is not None)
        finally:
            self._laden_laeuft = alt

    def _regal_ansicht_uebernehmen(self):
        kennung, liste = self._gewaehlt_id(self.regal_baum), self._regal_liste()
        if self._laden_laeuft or not kennung or liste is None:
            return
        self._liste_setzen("tabs", kpl.aendern(liste, kennung, view_mode=self.regal_ansicht.wert()), waehlen=kennung)

    def _regal_umschalten(self):
        kennung, liste = self._gewaehlt_id(self.regal_baum), self._regal_liste()
        if not kennung or liste is None:
            return
        l, n = kpl.eintrag_suchen(liste, kennung)
        an = l[n].get("enabled") is not False
        if an and sum(1 for e in liste if isinstance(e, dict) and e.get("enabled") is not False) <= 1:
            self.app.status.set(_("At least one shelf stays shown."))
            return
        self._liste_setzen("tabs", kpl.aendern(liste, kennung, enabled=not an), waehlen=kennung)

    def _regal_schieben(self, schritt):
        kennung, liste = self._gewaehlt_id(self.regal_baum), self._regal_liste()
        if kennung and liste is not None:
            self._liste_setzen("tabs", kpl.verschieben(liste, kennung, schritt), waehlen=kennung)

    def _regal_umbenennen(self):
        kennung, liste = self._gewaehlt_id(self.regal_baum), self._regal_liste()
        if not kennung or liste is None:
            return
        l, n = kpl.eintrag_suchen(liste, kennung)
        name = simpledialog.askstring(_("Shelves"), _("New name:"), initialvalue=l[n].get("label", ""), parent=self.app)
        if name and name.strip():
            self._liste_setzen("tabs", kpl.aendern(liste, kennung, label=name.strip()), waehlen=kennung)

    def _regal_hinzufuegen(self, vorlage):
        liste = self._regal_liste()
        if liste is None:
            return
        neu = copy.deepcopy(liste) + [{**copy.deepcopy(vorlage), "label": _(vorlage["label"]), "enabled": True}]
        self._liste_setzen("tabs", neu, waehlen=vorlage["id"])

    def _regal_entfernen(self):
        kennung, liste = self._gewaehlt_id(self.regal_baum), self._regal_liste()
        if not kennung or liste is None:
            return
        if len([e for e in liste if isinstance(e, dict)]) <= 1:
            self.app.status.set(_("At least one shelf stays shown."))
            return
        if not messagebox.askyesno(_("Shelves"), _("Remove the shelf? Standard shelves can be added again; "
                                                   "your own (collections, folders) only in Bookshelf."),
                                   parent=self.app):
            return
        self._liste_setzen("tabs", kpl.entfernen(liste, kennung))

    # ------------------------------------------------------------------ Theme und Dekoration
    def _wahl(self, eltern, zeile, name, text, optionen, holen, setzen, breite=24):
        """Auswahlliste mit Werten: optionen [(wert, text)], holen() liefert den aktuellen Wert."""
        ttk.Label(eltern, text=text).grid(row=zeile, column=0, sticky="w", padx=(0, 6), pady=1)
        v = tk.StringVar()
        cb = ttk.Combobox(eltern, textvariable=v, state="readonly", width=breite, values=[t for __, t in optionen])
        cb.grid(row=zeile, column=1, sticky="we", pady=1)
        cb.bind("<<ComboboxSelected>>", lambda e: self._wahl_gewaehlt(name))
        self.wahlen[name] = (v, optionen, holen, setzen)

    def _wahl_gewaehlt(self, name):
        if self._laden_laeuft:
            return
        v, optionen, __, setzen = self.wahlen[name]
        wert = next((w for w, t in optionen if t == v.get()), None)
        setzen(wert)

    def _wahlen_fuellen(self):
        for v, optionen, holen, __ in self.wahlen.values():
            w = holen()
            text = next((t for x, t in optionen if _gleich(x, w)), None)
            v.set(text if text is not None else (f"{w}" if w is not None else optionen[0][1]))

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

    def _leeren(self, f):
        for w in f.winfo_children():
            w.destroy()

    def _dynamisch_bauen(self):
        """Abschnitte, deren Inhalt vom Profil abhängt (Theme-Pakete, Bilder, Regale, Ornamente)."""
        for name in [n for n in self.wahlen if n.startswith(("theme", "regal", "bild", "brett", "deko"))]:
            del self.wahlen[name]
        ko = self.ko
        themes = kpl.themes(ko)
        regale = self._regale()

        f = self.f_theme
        self._leeren(f)
        f.columnconfigure(1, weight=1)
        standard = [(kpl.THEME_EIGEN, _("Custom theme")), (kpl.THEME_SCHLICHT, _("Plain"))] + themes
        self._wahl(f, 0, "theme", _("Default theme"), standard, lambda: self._wert("library_theme"),
                   lambda w: self._setzen("library_theme", w))
        self._wahl(f, 1, "theme_hell", _("Light or dark"), [(k, _(t)) for k, t in kpl.HELLDUNKEL],
                   lambda: self._wert("shelf_theme", "auto"), lambda w: self._setzen("shelf_theme", w, "auto"))
        r = 2
        if regale:
            ttk.Label(f, text=_("Theme per shelf"), style="Ueberschrift.TLabel").grid(row=r, column=0, columnspan=2,
                                                                                     sticky="w", pady=(6, 0))
            r += 1
            je = [(None, _("Like the default")), ("mine", _("Custom theme")), (kpl.THEME_SCHLICHT, _("Plain"))] + themes
            for n, tab in enumerate(regale):
                self._wahl(f, r, f"regal_theme_{n}", kpl.regal_name(tab), je,
                           lambda n=n: (self._regale()[n] or {}).get("theme"),
                           lambda w, n=n: self._regal_setzen(n, "theme", w))
                r += 1
        ttk.Label(f, text=_("Theme packs are folders in settings/bookshelf/ornaments with a theme/theme.json; new ones "
                            "come from Bookshelf's theme library. Wallpaper, plank and colours below belong to the "
                            "custom theme; a theme pack lays its own parts over it.") +
                  ("" if themes else " " + _("No theme pack in the profile.")),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").grid(row=r, column=0, columnspan=2,
                                                                                 sticky="we", pady=(4, 0))

        f = self.f_hintergrund
        self._leeren(f)
        f.columnconfigure(1, weight=1)
        bilder = [(b, b) for b in kpl.hintergrundbilder(ko)]
        self._wahl(f, 0, "bild", _("Picture"), [(None, _("None"))] + bilder,
                   lambda: self._wert("wallpaper_default"), lambda w: self._setzen("wallpaper_default", w))
        self._wahl(f, 1, "bild_voll", _("Full screen shelves"), [(None, _("Same as above"))] + bilder,
                   lambda: self._wert("wallpaper_full"), lambda w: self._setzen("wallpaper_full", w))
        self._wahl(f, 2, "bild_abdunkeln", _("Panel shading"), [(k, _(t)) for k, t in kpl.ABDUNKELN],
                   lambda: self._wert("wallpaper_chrome_scrim", 0.85),
                   lambda w: self._setzen("wallpaper_chrome_scrim", w, 0.85))
        for r, (schl, text) in enumerate((("wallpaper_transparent_buttons", _("Transparent buttons")),
                                          ("wallpaper_panel_blur", _("Blur the picture under panels")),
                                          ("wallpaper_invert_night", _("Invert the picture in night mode")),
                                          ("covers_full_panel", _("One panel over the whole covers shelf"))), 3):
            v = self.var[schl] = tk.BooleanVar()
            ttk.Checkbutton(f, text=text, variable=v,
                            command=lambda s=schl: self._setzen(s, bool(self.var[s].get()), False)).grid(
                row=r, column=0, columnspan=2, sticky="w", pady=1)
        z = ttk.Frame(f)
        z.grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(z, text=_("Add picture …"), style="Klein.TButton", command=self.bild_hinzufuegen).pack(side="left")
        ttk.Label(f, text=_("Pictures are in settings/bookshelf/wallpapers of the profile. \"Add picture\" copies one "
                            "there at once (it still has to get to the e-reader)."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").grid(row=8, column=0, columnspan=2,
                                                                                 sticky="we", pady=(2, 0))

        f = self.f_brett
        self._leeren(f)
        f.columnconfigure(1, weight=1)
        self._wahl(f, 0, "brett", _("Plank"), [(None, _("Default (oak, unless you chose a plank colour)")),
                                               ("oak", _("Oak")), (False, _("Colour only"))] + kpl.bretter(ko),
                   lambda: self._wert("theme_plank_pack"), lambda w: self._setzen("theme_plank_pack", w))
        ttk.Label(f, text=_("The plank colour is under Colours (Plank)."), style="Hinweis.TLabel",
                  wraplength=BREITE, justify="left").grid(row=1, column=0, columnspan=2, sticky="we", pady=(2, 0))

        f = self.f_deko
        self._leeren(f)
        f.columnconfigure(1, weight=1)
        r = 0
        if regale:
            ttk.Label(f, text=_("How often per shelf"), style="Ueberschrift.TLabel").grid(row=r, column=0, columnspan=2,
                                                                                         sticky="w")
            r += 1
            stufen = [(k, _(t)) for k, t in kpl.HAEUFIGKEIT]
            for n, tab in enumerate(regale):
                self._wahl(f, r, f"deko_{n}", kpl.regal_name(tab), stufen,
                           lambda n=n: (self._regale()[n] or {}).get("ornament_frequency", kpl.HAEUFIGKEIT_VORGABE),
                           lambda w, n=n: self._regal_setzen(n, "ornament_frequency", w), breite=12)
                r += 1
        ttk.Label(f, text=_("Ornaments (double-click switches on/off)"), style="Ueberschrift.TLabel").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))
        rr = self.app._listenrahmen(f)
        rr.grid(row=r + 1, column=0, columnspan=2, sticky="we")
        self.deko_baum = ttk.Treeview(rr, show="tree", height=8, selectmode="browse")
        sb = ttk.Scrollbar(rr, orient="vertical", command=self.deko_baum.yview)
        self.deko_baum.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.deko_baum.pack(side="left", fill="x", expand=True)
        self.deko_baum.bind("<Double-Button-1>", lambda e: self.deko_umschalten())
        self.deko_baum.bind("<space>", lambda e: self.deko_umschalten())
        self._deko = kpl.dekoration(ko)
        ttk.Label(f, text=_("Ornaments stand in the gaps of spine shelves only. Their files are in "
                            "settings/bookshelf/ornaments (one level of packs).") +
                  ("" if self._deko else " " + _("No ornaments in the profile.")),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").grid(row=r + 2, column=0, columnspan=2,
                                                                                 sticky="we", pady=(2, 0))

        f = self.f_farben
        if not self.farb_felder:
            ttk.Label(f, text=_("Day")).grid(row=0, column=1, padx=4)
            ttk.Label(f, text=_("Night")).grid(row=0, column=2, padx=4)
            for r, (schl, text) in enumerate(kpl.FARBEN, 1):
                ttk.Label(f, text=_(text)).grid(row=r, column=0, sticky="w", padx=(0, 6), pady=1)
                for sp, k in ((1, schl), (2, schl + "_night")):
                    feld = tk.Label(f, width=6, relief="solid", borderwidth=1, cursor="hand2")
                    feld._feste_farben = True
                    feld.grid(row=r, column=sp, padx=4, pady=1)
                    feld.bind("<Button-1>", lambda e, k=k: self.farbe_waehlen(k))
                    self.farb_felder[k] = feld
                ttk.Button(f, text="✕", width=2, style="Klein.TButton",
                           command=lambda s=schl: (self._setzen(s, None), self._setzen(s + "_night", None))).grid(
                    row=r, column=3, padx=(4, 0), pady=1)
            ttk.Label(f, text=_("Click a field to choose a colour; \"-\" = the default. ✕ resets day and night. Colours "
                                "belong to the custom theme."),
                      style="Hinweis.TLabel", wraplength=BREITE, justify="left").grid(row=len(kpl.FARBEN) + 1,
                                                                                     column=0, columnspan=4,
                                                                                     sticky="we", pady=(4, 0))

    def _deko_fuellen(self):
        b = self.deko_baum
        offen = {i for i in b.get_children() if b.item(i, "open")}
        b.delete(*b.get_children())
        aus = self._wert("ornaments_off") or {}
        pakete_aus = self._wert("ornament_packs_off") or {}

        def zeichen(an):
            return "☑ " if an else "☐ "
        for paket, teile in sorted(self._deko.items()):
            eltern = ""
            if paket:
                an = not pakete_aus.get(paket) if isinstance(pakete_aus, dict) else True
                eltern = b.insert("", "end", iid="paket:" + paket, text=zeichen(an) + paket,
                                  open=("paket:" + paket) in offen)
            for rel in teile:
                an = not aus.get(rel) if isinstance(aus, dict) else True
                b.insert(eltern, "end", iid="teil:" + rel, text=zeichen(an) + rel.split("/")[-1])

    def deko_umschalten(self):
        sel = self.deko_baum.selection()
        if not sel:
            return
        art, name = sel[0].split(":", 1)
        schl = "ornament_packs_off" if art == "paket" else "ornaments_off"
        menge = dict(self._wert(schl) or {})
        if menge.get(name):
            menge.pop(name)
        else:
            menge[name] = True
        self._setzen(schl, menge or None)
        if self.deko_baum.exists(sel[0]):
            self.deko_baum.selection_set(sel[0])

    def _farben_fuellen(self):
        p = kth.PALETTE["dunkel" if self.app.dark_mode.get() else "hell"]
        for k, feld in self.farb_felder.items():
            h = kpl.farbe_hex(self._wert(k))
            if h:
                feld.configure(bg=h, text="", fg=p["fg"])
            else:
                feld.configure(bg=p["feld"], fg=p["hinweis"], text="-")

    def farbe_waehlen(self, schl):
        from tkinter import colorchooser
        alt = kpl.farbe_hex(self._wert(schl))
        erg = colorchooser.askcolor(color=alt or "#808080", parent=self.app, title=_("Colour"))
        if erg and erg[1]:
            self._setzen(schl, kpl.farbe_wert(erg[1]))

    def bild_hinzufuegen(self):
        from tkinter import filedialog
        import shutil
        p = filedialog.askopenfilename(parent=self.app, title=_("Wallpaper for Bookshelf"),
                                       filetypes=[(_("Pictures"), " ".join("*" + e for e in sorted(kpl.BILD_ENDUNGEN))),
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

    def farben(self):
        super().farben()
        if self.farb_felder and self.datei_werte is not None:
            self._farben_fuellen()

    # ------------------------------------------------------------------ Werte
    def _wert(self, schl, vorgabe=None):
        if schl in self.aenderungen:
            w = self.aenderungen[schl]
            return vorgabe if w is None else w
        return (self.datei_werte or {}).get(schl, vorgabe)

    def neu_laden(self):
        self.info = kpl.erkennen(self.bereich.profil).get(kpl.BOOKSHELF)
        if not self.info:
            return
        self.kopf.configure(text=_("Bookshelf {version} in the profile ({datei}).").format(
            version=self.info["version"] or "?", datei=kpl.bookshelf_datei(self.ko).relative_to(self.ko)))
        self.datei_werte = kpl.bookshelf_lesen(self.ko)
        self.aenderungen = {}
        self._dynamisch_bauen()
        self._formular_fuellen()

    def _formular_fuellen(self):
        self._laden_laeuft = True
        try:
            for schl, __, __, art, vorgabe, wahl in kpl.BOOKSHELF_WERTE:
                w = self._wert(schl, vorgabe)
                if art == "an":
                    self.var[schl].set(bool(w))
                elif art == "zahl":
                    self.var[schl].set("" if w is None else str(w))
                else:
                    self.var[schl].set(_(dict(wahl).get(w, dict(wahl)[vorgabe])))
            for schl in ("wallpaper_transparent_buttons", "wallpaper_panel_blur", "wallpaper_invert_night",
                         "covers_full_panel"):
                if schl in self.var:
                    self.var[schl].set(bool(self._wert(schl, False)))
            self._wahlen_fuellen()
            self._hero_fuellen()
            self._mod_fuellen()
            self._menue_fuellen()
            self._regale_fuellen()
            if hasattr(self, "deko_baum"):
                self._deko_fuellen()
            self._farben_fuellen()
            self.baum.delete(*self.baum.get_children())
            alle = dict(self.datei_werte or {})
            alle.update({k: v for k, v in self.aenderungen.items()})
            for k in sorted(alle):
                if k in kpl.BOOKSHELF_INTERN or alle[k] is None:
                    continue
                self.baum.insert("", "end", iid=k, text=("● " if k in self.aenderungen else "") + k,
                                 values=(kpl.wert_text(alle[k]),))
        finally:
            self._laden_laeuft = False
        self.stand_zeigen()

    def _wert_geaendert(self, schl):
        if self._laden_laeuft or self.datei_werte is None:
            return
        __, __, __, art, vorgabe, wahl = next(x for x in kpl.BOOKSHELF_WERTE if x[0] == schl)
        v = self.var[schl].get()
        if art == "an":
            w = bool(v)
        elif art == "zahl":
            try:
                w = _zahl_oder_leer(v)
            except ValueError:
                return
        else:
            w = next((k for k, t in wahl if _(t) == v), vorgabe)
        self._setzen(schl, w, vorgabe)

    def _setzen(self, schl, w, vorgabe=None):
        im_profil = (self.datei_werte or {}).get(schl)
        if _gleich(w, im_profil) or (w is not None and _gleich(w, vorgabe) and im_profil is None):
            self.aenderungen.pop(schl, None)
        else:
            self.aenderungen[schl] = w
        self._formular_fuellen()
        self._planen(PAUSE_BOOKSHELF, self.ins_bild)

    def schluessel_bearbeiten(self):
        sel = self.baum.selection()
        if not sel:
            return
        schl = sel[0]
        alt = self._wert(schl)
        if isinstance(alt, (dict, list)) or alt is None:
            self.app.status.set(_("{schluessel} is a table: change it in Bookshelf itself.").format(schluessel=schl))
            return
        text = simpledialog.askstring(_("Bookshelf"), _("New value for {schluessel}:").format(schluessel=schl),
                                      initialvalue=kpl.wert_text(alt) if not isinstance(alt, bool) else
                                      ("true" if alt else "false"), parent=self.app)
        if text is None:
            return
        try:
            w = kpl.wert_aus_text(text, alt)
        except ValueError:
            self.app.status.set(_("\"{text}\" does not fit the value ({art}).").format(text=text,
                                                                                         art=type(alt).__name__))
            return
        self._setzen(schl, w)

    def schluessel_loeschen(self):
        sel = self.baum.selection()
        if sel:
            self._setzen(sel[0], None)

    def ungespeichert(self):
        return bool(self.aenderungen)

    # ------------------------------------------------------------------ Werkbank
    def in_kopie(self, ko):
        if self.aenderungen:
            kpl.bookshelf_schreiben(ko, self.aenderungen)

    def ins_bild(self):
        """Bookshelf kann nicht neu laden: Werkbank neu starten (Startbildschirm), in_kopie() bringt den Entwurf mit."""
        if self.bereich.unterseite() != self.plugin:
            return
        if self.bereich.modus_var.get() != "bibliothek":
            self.bereich.modus_setzen("bibliothek")
        else:
            self.bereich.werkbank_starten(still=True)

    def nach_start(self):
        pass

    def beim_zeigen(self):
        if self.datei_werte is None:
            self.neu_laden()
        if self.bereich.modus_var.get() != "bibliothek":
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
        if not self.aenderungen:
            return
        if not messagebox.askyesno(_("Bookshelf"), _("Discard the unsaved changes?"), parent=self.app):
            return
        self.neu_laden()
        self.ins_bild()
