# -*- coding: utf-8 -*-
"""
workbench_sleep.py - Unterseite "Sperrbildschirm" der KOReader-Werkbank (seit 1.4-beta8). Logik in
preview/sleep_screen.py.

KOReaders Optionen unter Bildschirm > Sperrbildschirm (settings.reader.lua: screensaver_*). Wie "Schrift und
Ränder": Entwurf erst nur in der Werkbank, "Ins Profil" behält ihn; KOReader liest die Werte beim Start,
also startet die Werkbank nach einer Änderung neu. Solange die Seite offen ist, zeigt die Werkbank den
Sperrbildschirm (Befehl "sleep 1" an den Werkbank-Patch: Screensaver:setup()+show() ohne Ruhezustand);
beim Verlassen schließt "sleep 0" ihn wieder.
"""
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import keller_theme as kth
from bookbench.preview import emulator as kv
from bookbench.preview import koreader_settings as kks
from bookbench.preview import plugins as kpl
from bookbench.preview import sleep_screen as kss
from bookbench.ui.workbench_plugins import BREITE, _gleich, _zahl_oder_leer
from bookbench.ui.workbench_reader import PAUSE, _NeustartSeite
from bookbench.i18n import _

MARKE_BILDER = "sperrbildschirm_bilder"           # Profil-Marke: Bilder nach koreader/screensaver kopiert


class SperrSeite(_NeustartSeite):
    plugin = "sperrbildschirm"
    titel = _("Sleep screen")
    ansicht = None                                # geht auf der Leseseite und auf dem Startbildschirm

    def __init__(self, bereich, eltern):
        super().__init__(bereich, eltern)
        self.datei_werte = None
        self.aenderungen = {}
        self._laden_laeuft = False
        self.var = {}
        self.felder = {}                          # Schlüssel -> Widgets (zum Ausgrauen)
        self.texte = {}                           # Schlüssel -> tk.Text
        self.kopf.configure(text=_("KOReader's sleep screen (Screen > Sleep screen in KOReader's menu). While this "
                                   "page is open, the workbench shows the sleep screen; after a change it restarts "
                                   "(about a second)."))

        i = self._abschnitt("vorschau", _("Preview"))
        z = ttk.Frame(i)
        z.pack(anchor="w")
        ttk.Button(z, text=_("Show again"), style="Klein.TButton",
                   command=self.zeigen).pack(side="left", padx=(0, 4))
        ttk.Button(z, text=_("Back to the page"), style="Klein.TButton",
                   command=self.schliessen).pack(side="left")
        self.vorschau_text = ttk.Label(i, text="", wraplength=BREITE, justify="left", style="Hinweis.TLabel")
        self.vorschau_text.pack(anchor="w", fill="x", pady=(4, 0))

        i = self._abschnitt("bild", _("Wallpaper"))
        i.columnconfigure(1, weight=1)
        self._zeilen(i, kss.BILD)
        ttk.Label(i, text=_("Paths are the ones on the e-reader. \"Choose …\" takes a file or folder on the connected "
                            "e-reader; anything else is copied into the profile (folder screensaver) and goes to the "
                            "e-reader with \"To the e-reader …\"."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").grid(row=99, column=0, columnspan=3,
                                                                                 sticky="we", pady=(4, 0))

        i = self._abschnitt("ausnahmen", _("Ignore the book cover"), offen=False)
        self._zeilen(i, kss.AUSNAHMEN)

        i = self._abschnitt("meldung", _("Message"))
        i.columnconfigure(1, weight=1)
        self._zeilen(i, kss.MELDUNG)

        i = self._abschnitt("aufwachen", _("After waking up"), offen=False)
        i.columnconfigure(1, weight=1)
        self._zeilen(i, kss.AUFWACHEN)
        ttk.Label(i, text=_("The gesture is set in KOReader under Taps and gestures (Device: Exit sleep screen)."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").grid(row=99, column=0, columnspan=3,
                                                                                 sticky="we", pady=(4, 0))

    # ------------------------------------------------------------------ Aufbau
    def _zeilen(self, eltern, liste):
        for r, (schl, text, art, vorgabe, wahl) in enumerate(liste):
            if art in ("an", "an_falsch"):
                v = self.var[schl] = tk.BooleanVar()
                w = ttk.Checkbutton(eltern, text=_(text), variable=v, command=lambda s=schl: self._geaendert(s))
                w.grid(row=r, column=0, columnspan=3, sticky="w", pady=1)
                self.felder[schl] = [w]
                continue
            lab = ttk.Label(eltern, text=_(text), wraplength=150, justify="left")
            lab.grid(row=r, column=0, sticky="nw", padx=(0, 6), pady=1)
            if art == "wahl":
                v = self.var[schl] = tk.StringVar()
                cb = ttk.Combobox(eltern, textvariable=v, state="readonly", width=24,
                                  values=[_(t) for __, t in wahl])
                cb.grid(row=r, column=1, columnspan=2, sticky="w", pady=1)
                cb.bind("<<ComboboxSelected>>", lambda e, s=schl: self._geaendert(s))
                self.felder[schl] = [lab, cb]
            elif art == "zahl":
                v = self.var[schl] = tk.StringVar()
                sp = ttk.Spinbox(eltern, from_=0, to=100, increment=5, width=5, textvariable=v,
                                 command=lambda s=schl: self._geaendert(s))
                sp.grid(row=r, column=1, sticky="w", pady=1)
                sp.bind("<KeyRelease>", lambda e, s=schl: self._geaendert(s))
                hinweis = ttk.Label(eltern, text=_("empty = {wert}").format(wert=vorgabe) if vorgabe is not None
                                    else _("empty = no limit"), style="Hinweis.TLabel")
                hinweis.grid(row=r, column=2, sticky="w", padx=(2, 0))
                self.felder[schl] = [lab, sp, hinweis]
            elif art in ("datei", "ordner"):
                v = self.var[schl] = tk.StringVar()
                f = ttk.Frame(eltern)
                f.grid(row=r, column=1, columnspan=2, sticky="we", pady=1)
                ent = ttk.Entry(f, textvariable=v, width=26)
                ent.pack(side="top", fill="x")
                ent.bind("<Return>", lambda e, s=schl: self._geaendert(s))
                ent.bind("<FocusOut>", lambda e, s=schl: self._geaendert(s))
                k = ttk.Frame(f)
                k.pack(side="top", anchor="w", pady=(2, 0))
                b1 = ttk.Button(k, text=_("Choose …"), style="Klein.TButton",
                                command=lambda s=schl, a=art: self.waehlen(s, a))
                b1.pack(side="left", padx=(0, 4))
                b2 = ttk.Button(k, text=_("Clear"), style="Klein.TButton",
                                command=lambda s=schl: (self.var[s].set(""), self._geaendert(s)))
                b2.pack(side="left")
                self.felder[schl] = [lab, ent, b1, b2]
            elif art == "text":
                f = ttk.Frame(eltern)
                f.grid(row=r, column=1, columnspan=2, sticky="we", pady=1)
                t = tk.Text(f, height=3, width=28, wrap="word", font=("TkDefaultFont",), borderwidth=1,
                            relief="solid", highlightthickness=0, undo=True)
                t.pack(side="top", fill="x")
                t.bind("<KeyRelease>", lambda e, s=schl: self._geaendert(s))
                self.texte[schl] = t
                k = ttk.Frame(f)
                k.pack(side="top", anchor="w", pady=(2, 0))
                mb = ttk.Menubutton(k, text=_("Insert ▾"), style="Klein.TButton")
                menue = tk.Menu(mb, tearoff=False)
                for p, bed in kss.PLATZHALTER:
                    menue.add_command(label=f"{p}   {_(bed)}", command=lambda p=p, s=schl: self._einfuegen(s, p))
                mb.configure(menu=menue)
                mb.pack(side="left")
                leer = _("empty = \"{text}\"").format(text=_("Sleeping")) if schl == "screensaver_message" else ""
                if leer:
                    ttk.Label(f, text=leer, style="Hinweis.TLabel").pack(side="top", anchor="w")
                self.felder[schl] = [lab, t, mb]
        self.farben()

    def farben(self):
        super().farben()
        f = kth.PALETTE["dunkel" if self.app.dark_mode.get() else "hell"]
        for t in getattr(self, "texte", {}).values():
            t.configure(bg=f["feld"], fg=f["feld_fg"], insertbackground=f["feld_fg"])

    def _einfuegen(self, schl, platzhalter):
        t = self.texte[schl]
        t.insert("insert", platzhalter)
        t.focus_set()
        self._geaendert(schl)

    # ------------------------------------------------------------------ Werte
    def geladen(self):
        return self.datei_werte is not None

    def zuruecksetzen(self):
        self.datei_werte, self.aenderungen = None, {}

    def _werte(self):
        w = dict(self.datei_werte or {})
        for k, v in self.aenderungen.items():
            if v is None:
                w.pop(k, None)
            else:
                w[k] = v
        return w

    def neu_laden(self):
        self.datei_werte = kks.lesen(self.ko)
        self.aenderungen = {}
        self._fuellen()

    def _fuellen(self):
        self._laden_laeuft = True
        werte = self._werte()
        try:
            for schl, __, art, vorgabe, wahl in kss.ALLE:
                w = werte.get(schl)
                if art == "an":
                    self.var[schl].set(bool(w if w is not None else vorgabe))
                elif art == "an_falsch":
                    self.var[schl].set(w is not False)
                elif art == "wahl":
                    w = vorgabe if w is None else w
                    self.var[schl].set(next((_(t) for k, t in wahl if _gleich(k, w)), str(w)))
                elif art == "text":
                    t = self.texte[schl]
                    t.delete("1.0", "end")
                    t.insert("1.0", w if isinstance(w, str) else "")
                    t.edit_reset()
                else:
                    self.var[schl].set("" if w is None else str(w))
        finally:
            self._laden_laeuft = False
        self._ausgrauen()
        self._hinweis_zeigen()
        self.stand_zeigen()

    def _ausgrauen(self):
        """Felder ausgrauen, die bei der aktuellen Wahl nichts bewirken (wie KOReaders Menü)."""
        w = self._werte()
        typ = kss.wert(w, "screensaver_type")
        bild = typ in ("cover", "document_cover", "random_image")
        meldung = bool(kss.wert(w, "screensaver_show_message"))
        geste = kss.wert(w, "screensaver_delay") == "gesture"
        aktiv = {
            "screensaver_document_cover": typ == "document_cover",
            "screensaver_dir": typ == "random_image",
            "screensaver_cycle_images_alphabetically": typ == "random_image",
            "screensaver_img_background": bild, "screensaver_stretch_images": bild,
            "screensaver_stretch_limit_percentage": bild and bool(kss.wert(w, "screensaver_stretch_images")),
            "screensaver_images_crop_to_fit": bild, "screensaver_rotate_auto_for_best_fit": bild,
            "screensaver_exclude_on_hold_books": typ == "cover", "screensaver_exclude_finished_books": typ == "cover",
            "screensaver_hide_cover_in_filemanager": typ == "cover",
            "screensaver_message": meldung, "screensaver_message_container": meldung,
            "screensaver_message_vertical_position": meldung, "screensaver_message_alpha": meldung,
            "screensaver_msg_background": meldung and typ == "disable",
            "screensaver_show_exit_message": geste,
            "screensaver_exit_message": geste and kss.wert(w, "screensaver_show_exit_message"),
        }
        for schl, widgets in self.felder.items():
            an = aktiv.get(schl, True)
            for wd in widgets:
                if isinstance(wd, ttk.Label):         # ausgegraute Labels bekommen im Keller-Theme einen Kasten
                    continue
                if isinstance(wd, tk.Text):
                    wd.configure(state="normal" if an else "disabled")
                elif isinstance(wd, ttk.Combobox):
                    wd.state(["!disabled", "readonly"] if an else ["disabled"])
                else:
                    try:
                        wd.state(["!disabled"] if an else ["disabled"])
                    except tk.TclError:
                        pass

    def _geaendert(self, schl):
        if self._laden_laeuft or self.datei_werte is None:
            return
        __, __, art, vorgabe, wahl = kss.eintrag(schl)
        try:
            if art == "an":
                w = bool(self.var[schl].get())
            elif art == "an_falsch":
                w = None if self.var[schl].get() else False
            elif art == "wahl":
                w = next((k for k, t in wahl if _(t) == self.var[schl].get()), vorgabe)
            elif art == "zahl":
                w = _zahl_oder_leer(self.var[schl].get())
                if w is not None:
                    w = max(0, min(100, int(w)))
            elif art == "text":
                text = self.texte[schl].get("1.0", "end-1c")
                w = text if text.strip() else None
            else:
                w = self.var[schl].get().strip() or None
        except ValueError:
            return
        im_profil = (self.datei_werte or {}).get(schl)
        if _gleich(w, im_profil) or (w is None and im_profil is None):
            self.aenderungen.pop(schl, None)
        else:
            self.aenderungen[schl] = w
        if schl == "screensaver_stretch_images" and w is True:     # wie KOReader: Strecken und Zuschneiden
            self._nebenbei("screensaver_images_crop_to_fit", False)   # schließen einander aus
        elif schl == "screensaver_images_crop_to_fit" and w is True:
            self._nebenbei("screensaver_stretch_images", False)
        self._ausgrauen()
        self._hinweis_zeigen()
        self.stand_zeigen()
        self._planen(PAUSE if art in ("text", "zahl", "datei", "ordner") else 300, self.ins_bild)

    def _nebenbei(self, schl, w):
        im_profil = (self.datei_werte or {}).get(schl)
        if _gleich(w, im_profil) or (not w and im_profil is None):
            self.aenderungen.pop(schl, None)
        else:
            self.aenderungen[schl] = w
        self._laden_laeuft = True
        self.var[schl].set(bool(w))
        self._laden_laeuft = False

    def ungespeichert(self):
        return bool(self.aenderungen)

    # ------------------------------------------------------------------ Pfade
    def _art(self):
        return (kv.profil_stand(self.bereich.profil)["geraet"] or {}).get("art") or None

    def _wurzel(self):
        k = getattr(self.app, "kobo", None)
        w = getattr(k, "wurzel", None)
        return w if w and Path(w).exists() else None

    def waehlen(self, schl, art):
        wurzel = self._wurzel()
        start = str(wurzel) if wurzel else str(Path.home())
        if art == "ordner":
            pfad = filedialog.askdirectory(parent=self.app, title=_("Image folder"), initialdir=start)
        else:
            pfad = filedialog.askopenfilename(parent=self.app, title=_("Image or book"), initialdir=start,
                                              filetypes=[(_("Images"), " ".join("*" + e for e in sorted(kss.BILD_ENDUNGEN))),
                                                         (_("All files"), "*")])
        if not pfad:
            return
        geraet = kss.geraetepfad(pfad, self._art(), wurzel) or kss.profilpfad(pfad, self.ko, self._art())
        if geraet is None:
            try:
                geraet = kss.ins_profil(pfad, self.ko, self._art())
            except (OSError, ValueError):
                messagebox.showerror(self.titel, _("There are no images in the folder.") if art == "ordner"
                                     else _("The file could not be copied."), parent=self.app)
                return
            kpl._profil_geaendert(self.bereich.profil, MARKE_BILDER)
            self.app.status.set(_("Copied into the profile (folder screensaver): {name}").format(name=Path(pfad).name))
        self.var[schl].set(geraet)
        self._geaendert(schl)

    # ------------------------------------------------------------------ Werkbank
    def _hinweis_zeigen(self, text=None):
        if text is None:
            text = _(kss.was_fehlt(self._werte(), self._art(), self.ko, self._wurzel())) \
                if self.datei_werte is not None else ""
        self.vorschau_text.configure(text=text)

    def ins_bild(self):
        if self.bereich.unterseite() == self.plugin:
            self.bereich.werkbank_starten(still=True)

    def in_kopie(self, ko):
        if self.datei_werte is None and not self.aenderungen:
            return
        if self.aenderungen:
            kks.schreiben(ko, self.aenderungen)
        werte = kks.lesen(ko)
        uebersetzt = {}
        for schl in kss.PFADE:
            lp = kss.lokal(werte.get(schl), self._art(), ko, self._wurzel())
            if lp is not None:
                uebersetzt[schl] = str(lp)
        if uebersetzt:
            kks.schreiben(ko, uebersetzt)

    def _wb(self):
        wb = self.bereich.werkbank
        return wb if wb and wb.laeuft() and (wb.bereit or wb.haengt) else None

    def nach_start(self):
        if self.bereich.unterseite() == self.plugin and self._wb():
            self._wb().schlafen(True)              # der Bereich holt danach das Bild

    def beim_zeigen(self):
        if not self.geladen():
            self.neu_laden()
        self._hinweis_zeigen()
        self.zeigen(starten=True)

    def beim_verlassen(self):
        wb = self._wb()
        if wb:
            wb.schlafen(False)
            wb.bild()
            self.bereich._takt_planen()

    def zeigen(self, starten=False):
        wb = self._wb()
        if wb:
            wb.schlafen(True)
            wb.bild()
            self.bereich._takt_planen()
        elif starten or not (self.bereich.werkbank and self.bereich.werkbank.laeuft()):
            self.bereich.werkbank_starten(still=True)

    def schliessen(self):
        self.beim_verlassen()

    def befehl_erledigt(self, e):
        if e["befehl"] != "sleep 1":
            return
        if e["text"] == "ok nothing":
            self._hinweis_zeigen(_("KOReader shows no sleep screen with these settings: the screen stays as it is "
                                   "and there is no message."))
        elif not e["ok"]:
            self._hinweis_zeigen(_("KOReader reports: {text}").format(text=e["text"]))
        else:
            self._hinweis_zeigen()

    def speichern(self):
        if not self.aenderungen:
            return False
        kks.schreiben(self.ko, self.aenderungen)
        kpl._profil_geaendert(self.bereich.profil, self.plugin)
        self.app.status.set(_("Sleep screen saved in the profile ({n} changed).").format(n=len(self.aenderungen)))
        self.neu_laden()
        return True

    def verwerfen(self):
        if not self.aenderungen:
            return
        if not messagebox.askyesno(self.titel, _("Discard the unsaved changes?"), parent=self.app):
            return
        self.neu_laden()
        self.ins_bild()
