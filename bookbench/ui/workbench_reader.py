# -*- coding: utf-8 -*-
"""
workbench_reader.py - Unterseiten "Schrift und Ränder" und "Patches" der KOReader-Werkbank (seit
1.4-beta4). Wie die Plugin-Seiten (ui/workbench_plugins.py): Entwurf erst nur in der Werkbank,
"Ins Profil speichern" behält ihn. Beide brauchen einen Neustart der Werkbank (KOReader liest die
Werte bzw. führt die Patches beim Start aus, ~1,2 s). Logik in preview/koreader_settings.py.

  LesenSeite   allgemeine Schrift und Ränder (settings.reader.lua: cre_font, copt_*); Buchwerte des
               gezeigten Buchs anzeigen und in der Werkbank auf Wunsch übergehen
  PatchSeite   Userpatches an/aus (wie KOReaders Patchverwaltung), ansehen, hinzufügen, löschen;
               ⚠ bei Patches, die in der Werkbank fehlgeschlagen sind
"""
import re
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import keller_theme as kth
from bookbench.preview import emulator as kv
from bookbench.preview import koreader_settings as kks
from bookbench.preview import plugins as kpl
from bookbench.ui.workbench_plugins import BREITE, _gleich, _Seite, _zahl_oder_leer
from bookbench.i18n import _

PAUSE = 900                                       # ms nach der letzten Änderung, dann Neustart


class _NeustartSeite(_Seite):
    """Gemeinsam: Änderung -> nach einer Pause Werkbank neu starten (in der passenden Ansicht)."""
    ansicht = "lesen"

    def ins_bild(self):
        b = self.bereich
        if b.unterseite() != self.plugin:
            return
        if b.modus_var.get() != self.ansicht:
            b.modus_setzen(self.ansicht)
        else:
            b.werkbank_starten(still=True)

    def nach_start(self):
        pass

    def beim_zeigen(self):
        if not self.geladen():
            self.neu_laden()
        if self.ansicht and self.bereich.modus_var.get() != self.ansicht:
            self.bereich.modus_setzen(self.ansicht)

    def geladen(self):
        return True


# ====================================================================== Schrift und Ränder
class LesenSeite(_NeustartSeite):
    plugin = "lesen"
    titel = _("Font and margins")

    def __init__(self, bereich, eltern):
        super().__init__(bereich, eltern)
        self.datei_werte = None                   # settings.reader.lua im Profil
        self.aenderungen = {}
        self.buchwerte = None                     # Schrift-/Randwerte des gezeigten Buchs (None = kein Buch)
        self._laden_laeuft = False
        self.var = {}
        self.kopf.configure(text=_("KOReader's general reading settings, as \"Set as default\" in KOReader's "
                                   "menu stores them. They show in the picture after a restart of the workbench "
                                   "(about a second)."))

        i = self._abschnitt("schrift", _("Font"))
        i.columnconfigure(2, weight=1)
        ttk.Label(i, text=_("Font")).grid(row=0, column=0, sticky="w", padx=(0, 6), pady=1)
        self.schrift_var = tk.StringVar()
        self.schrift = ttk.Combobox(i, textvariable=self.schrift_var, width=18)
        self.schrift.grid(row=0, column=1, columnspan=2, sticky="w", pady=1)
        self.schrift.bind("<<ComboboxSelected>>", lambda e: self._schrift_geaendert())
        self.schrift.bind("<Return>", lambda e: self._schrift_geaendert())
        self.schrift.bind("<FocusOut>", lambda e: self._schrift_geaendert())
        self._zeilen(i, kks.SCHRIFT, 1)

        i = self._abschnitt("raender", _("Margins"))
        i.columnconfigure(2, weight=1)
        self._zeilen(i, kks.RAENDER, 0)
        ttk.Label(i, text=_("In KOReader's units (pixels at the device's density). Bookends' own margins are on "
                            "the Bookends page."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").grid(row=len(kks.RAENDER), column=0,
                                                                                 columnspan=3, sticky="we",
                                                                                 pady=(4, 0))

        i = self._abschnitt("buch", _("Values of the book shown"))
        self.buch_text = ttk.Label(i, text="", wraplength=BREITE, justify="left")
        self.buch_text.pack(anchor="w", fill="x")
        self.buch_aus_var = tk.BooleanVar(value=bool(self.app.e.get("werkbank_buchwerte_aus")))
        ttk.Checkbutton(i, text=_("Ignore the book's own values in the workbench"), variable=self.buch_aus_var,
                        command=self._buch_aus_geaendert).pack(anchor="w", pady=(4, 0))
        ttk.Label(i, text=_("KOReader stores font and margins in the book data (.sdr) of every book it has opened "
                            "once; there they win over the general values. The general values therefore only apply "
                            "to books never opened before. Ignoring them here only affects the workbench (the copy), "
                            "never the book."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").pack(anchor="w", fill="x", pady=(4, 0))

    def _zeilen(self, eltern, liste, start):
        for r, (schl, text, art, vorgabe, wahl) in enumerate(liste, start):
            if art == "an":
                v = self.var[schl] = tk.BooleanVar()
                ttk.Checkbutton(eltern, text=_(text), variable=v,
                                command=lambda s=schl: self._geaendert(s)).grid(row=r, column=0, columnspan=3,
                                                                               sticky="w", pady=1)
                continue
            ttk.Label(eltern, text=_(text), wraplength=150, justify="left").grid(row=r, column=0, sticky="w",
                                                                              padx=(0, 6), pady=1)
            if art == "wahl":
                v = self.var[schl] = tk.StringVar()
                cb = ttk.Combobox(eltern, textvariable=v, state="readonly", width=10,
                                  values=[_(t) for __, t in wahl])
                cb.grid(row=r, column=1, sticky="w", pady=1)
                cb.bind("<<ComboboxSelected>>", lambda e, s=schl: self._geaendert(s))
                continue
            f = ttk.Frame(eltern)
            f.grid(row=r, column=1, sticky="w", pady=1)
            teile = 2 if art == "paar" else 1
            v = self.var[schl] = [tk.StringVar() for __ in range(teile)]
            for x in v:
                sp = ttk.Spinbox(f, from_=0, to=500, increment=1, width=4, textvariable=x,
                                 command=lambda s=schl: self._geaendert(s))
                sp.pack(side="left", padx=(0, 4))
                sp.bind("<KeyRelease>", lambda e, s=schl: self._geaendert(s))
            ttk.Label(eltern, text=_("empty = {wert}").format(wert=kks.wert_text(vorgabe)),
                      style="Hinweis.TLabel").grid(row=r, column=2, sticky="w", padx=(2, 0))

    # ------------------------------------------------------------------ Werte
    def geladen(self):
        return self.datei_werte is not None

    def zuruecksetzen(self):
        self.datei_werte, self.aenderungen = None, {}

    def _wert(self, schl, vorgabe=None):
        if schl in self.aenderungen:
            w = self.aenderungen[schl]
            return vorgabe if w is None else w
        return (self.datei_werte or {}).get(schl, vorgabe)

    def neu_laden(self):
        self.datei_werte = kks.lesen(self.ko)
        self.aenderungen = {}
        self.schrift.configure(values=kks.schriftfamilien(kks.schriftordner(self.bereich.profil, self.bereich.befund)))
        self._fuellen()

    def _fuellen(self):
        self._laden_laeuft = True
        try:
            self.schrift_var.set(self._wert(kks.SCHRIFTART) or "")
            for schl, __, art, vorgabe, wahl in kks.ALLE:
                w = self._wert(schl)
                v = self.var[schl]
                if art == "an":
                    v.set(bool(w if w is not None else vorgabe))
                elif art == "wahl":
                    w = vorgabe if w is None else w
                    v.set(next((_(t) for k, t in wahl if _gleich(k, w)), str(w)))
                elif art == "paar":
                    werte = w if isinstance(w, list) and len(w) == 2 else ["", ""]
                    for x, y in zip(v, werte):
                        x.set(str(y))
                else:
                    v[0].set("" if w is None else str(w))
        finally:
            self._laden_laeuft = False
        self._buch_zeigen()
        self.stand_zeigen()

    def _schrift_geaendert(self):
        if self._laden_laeuft or self.datei_werte is None:
            return
        name = self.schrift_var.get().strip()
        self._setzen(kks.SCHRIFTART, name or None)

    def _geaendert(self, schl):
        if self._laden_laeuft or self.datei_werte is None:
            return
        __, __, art, vorgabe, wahl = next(x for x in kks.ALLE if x[0] == schl)
        v = self.var[schl]
        try:
            if art == "an":
                w = 1 if v.get() else 0
            elif art == "wahl":
                w = next((k for k, t in wahl if _(t) == v.get()), vorgabe)
            elif art == "paar":
                teile = [_zahl_oder_leer(x.get()) for x in v]
                w = None if all(t is None for t in teile) else [t if t is not None else d
                                                                for t, d in zip(teile, vorgabe)]
            else:
                w = _zahl_oder_leer(v[0].get())
        except ValueError:
            return
        self._setzen(schl, w, vorgabe)

    def _setzen(self, schl, w, vorgabe=None):
        im_profil = (self.datei_werte or {}).get(schl)
        if _gleich(w, im_profil) or (w is not None and _gleich(w, vorgabe) and im_profil is None):
            self.aenderungen.pop(schl, None)
        else:
            self.aenderungen[schl] = w
        self.stand_zeigen()
        self._planen(PAUSE, self.ins_bild)

    def ungespeichert(self):
        return bool(self.aenderungen)

    # ------------------------------------------------------------------ Buchwerte
    def _buch_aus_geaendert(self):
        self.app.e["werkbank_buchwerte_aus"] = bool(self.buch_aus_var.get())
        self._planen(100, self.ins_bild)

    def _buch_zeigen(self):
        if self.bereich.modus_var.get() != "lesen":
            text = _("The start screen shows no book.")
        elif self.buchwerte is None:
            text = _("Sample text: it has no book data, so the general values apply.")
        elif not self.buchwerte:
            text = _("The book has no values of its own: the general values apply.")
        else:
            liste = ", ".join(f"{k.removeprefix('copt_')} = {kks.wert_text(w)}" for k, w in sorted(self.buchwerte.items()))
            text = _("The book has its own values ({n}): {liste}.").format(n=len(self.buchwerte), liste=liste)
            text += " " + (_("The workbench ignores them now.") if self.buch_aus_var.get() else
                           _("They win over the general values - changes above do not show for this book."))
        self.buch_text.configure(text=text)

    # ------------------------------------------------------------------ Werkbank
    def in_kopie(self, ko):
        if self.aenderungen:
            kks.schreiben(ko, self.aenderungen)
        b = self.bereich
        buch = b._gewaehltes_buch() if b.modus_var.get() == "lesen" else None
        if buch:
            from bookbench.preview import workbench as kwb
            sdr = Path(ko).parent / "buecher" / kv._sdr_name(kwb.kopiename(buch))
            self.buchwerte = kks.buchwerte(sdr)
            if self.buch_aus_var.get():
                kks.buchwerte_entfernen(sdr)
        else:
            self.buchwerte = None

    def nach_start(self):
        self._buch_zeigen()

    def speichern(self):
        if not self.aenderungen:
            return False
        kks.schreiben(self.ko, self.aenderungen)
        kpl._profil_geaendert(self.bereich.profil, self.plugin)
        self.app.status.set(_("Font and margins saved in the profile ({n} changed).").format(n=len(self.aenderungen)))
        self.neu_laden()
        return True

    def verwerfen(self):
        if not self.aenderungen:
            return
        if not messagebox.askyesno(self.titel, _("Discard the unsaved changes?"), parent=self.app):
            return
        self.neu_laden()
        self.ins_bild()


# ====================================================================== Patches
class PatchSeite(_NeustartSeite):
    plugin = "patches"
    titel = _("Patches")
    ansicht = None                                # Patches betreffen beide Ansichten

    def __init__(self, bereich, eltern):
        super().__init__(bereich, eltern)
        self.liste = None                         # kks.patches() des Profils
        self.schalter = {}                        # Entwurf: Name -> an
        self.alle_neu = None                      # Entwurf: alle aus (True/False) oder None = wie im Profil
        self.fehler = {}                          # Name -> Meldung aus der Werkbank
        self._laden_laeuft = False
        self.kopf.configure(text=_("User patches (koreader/patches) as in KOReader's patch management. They run "
                                   "when KOReader starts, so the workbench restarts after a change."))
        i = self._abschnitt("liste", _("Patches"))
        self.alle_var = tk.BooleanVar()
        ttk.Checkbutton(i, text=_("Switch off all patches (like KOReader's switch)"), variable=self.alle_var,
                        command=self._alle_geaendert).pack(anchor="w")
        r = self.app._listenrahmen(i)
        r.pack(fill="x", pady=(4, 0))
        self.baum = ttk.Treeview(r, show="tree", height=12, selectmode="browse")
        sb = ttk.Scrollbar(r, orient="vertical", command=self.baum.yview)
        self.baum.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.baum.pack(side="left", fill="x", expand=True)
        self.baum.bind("<Double-Button-1>", lambda e: self.umschalten())
        self.baum.bind("<space>", lambda e: self.umschalten())
        self.baum.bind("<<TreeviewSelect>>", lambda e: self._auswahl_zeigen())
        z = ttk.Frame(i)
        z.pack(anchor="w", pady=(4, 0))
        for n, (text, befehl) in enumerate(((_("On/off"), self.umschalten), (_("Show …"), self.anzeigen),
                                            (_("Add …"), self.hinzufuegen), (_("Delete"), self.loeschen))):
            ttk.Button(z, text=text, command=befehl, style="Klein.TButton").grid(row=n // 2, column=n % 2,
                                                                                 padx=(0, 4), pady=(0, 2), sticky="we")
        self.detail = ttk.Label(i, text="", wraplength=BREITE, justify="left")
        self.detail.pack(anchor="w", fill="x", pady=(4, 0))
        ttk.Label(i, text=_("☑ on, ☐ off, ⚠ failed in the workbench (message below when selected). Some patches "
                            "need the e-reader and never run on the computer. Adding and deleting change the profile "
                            "at once; switching on/off is a draft until \"Save to profile\"."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").pack(anchor="w", fill="x", pady=(4, 0))
        # Patches, die Bookbench mitbringt
        i = self._abschnitt("bookbench", _("Patches from Bookbench"))
        self.mit_rahmen = ttk.Frame(i)
        self.mit_rahmen.pack(anchor="w", fill="x")
        ttk.Label(i, text=_("They are also attached to every Bookbench release on GitHub, for copying into "
                            "koreader/patches by hand. To bring them onto the e-reader from here: add, then "
                            "\"To the e-reader …\"."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").pack(anchor="w", fill="x", pady=(4, 0))

    def _mitgebracht_zeigen(self):
        for w in self.mit_rahmen.winfo_children():
            w.destroy()
        stand_text = {"fehlt": _("not in the profile"), "aktuell": _("in the profile"),
                      "anders": _("in the profile, another version")}
        knopf_text = {"fehlt": _("Add"), "aktuell": None, "anders": _("Update")}
        for n, m in enumerate(kks.mitgebracht(self.ko)):
            z = ttk.Frame(self.mit_rahmen)
            z.pack(anchor="w", fill="x", pady=(0 if n == 0 else 8, 0))
            kopf = ttk.Frame(z)
            kopf.pack(anchor="w", fill="x")
            ttk.Label(kopf, text=m["name"].removesuffix(".lua"), style="Ueberschrift.TLabel").pack(side="left")
            ttk.Label(kopf, text="  " + stand_text[m["stand"]], style="Hinweis.TLabel").pack(side="left")
            if knopf_text[m["stand"]]:
                ttk.Button(kopf, text=knopf_text[m["stand"]], style="Klein.TButton",
                           command=lambda m=m: self._mitgebracht_hinzufuegen(m)).pack(side="right")
            ttk.Label(z, text=_(m["beschreibung"]), wraplength=BREITE, justify="left").pack(anchor="w", fill="x")

    def _mitgebracht_hinzufuegen(self, m):
        ziel = kks.patch_ordner(self.ko)
        ziel.mkdir(parents=True, exist_ok=True)
        aus = ziel / (m["name"] + ".disabled")
        if aus.is_file():                         # ausgeschaltete alte Fassung: ersetzen, Schalter bleibt
            shutil.copy2(m["quelle"], aus)
        else:
            shutil.copy2(m["quelle"], ziel / m["name"])
        kpl._profil_geaendert(self.bereich.profil, self.plugin)
        self.app.status.set(_("Patch {name} added to the profile.").format(name=m["name"]))
        self.liste = kks.patches(self.ko)
        self._fuellen()
        self._planen(100, self.ins_bild)

    def geladen(self):
        return self.liste is not None

    def zuruecksetzen(self):
        self.liste, self.schalter, self.alle_neu = None, {}, None

    def neu_laden(self):
        self.liste = kks.patches(self.ko)
        self.schalter, self.alle_neu = {}, None
        self._fehler_lesen()
        self._fuellen()

    def _an(self, p):
        return self.schalter.get(p["name"], p["an"])

    def _alle_aus(self):
        return kks.alle_aus(self.ko) if self.alle_neu is None else self.alle_neu

    def _fehler_lesen(self):
        wb = self.bereich.werkbank
        log = (wb.arbeit / kv.LOG) if wb else None
        try:
            self.fehler = kks.patch_fehler(log.read_text(encoding="utf-8", errors="replace")) if log else {}
        except OSError:
            self.fehler = {}

    def _fuellen(self):
        b = self.baum
        sel = b.selection()
        b.delete(*b.get_children())
        self._laden_laeuft = True
        self.alle_var.set(self._alle_aus())
        self._laden_laeuft = False
        stufen = dict(kks.STUFEN)
        for p in self.liste or []:
            eltern = "stufe:" + p["stufe"]
            if not b.exists(eltern):
                b.insert("", "end", iid=eltern, text=_(stufen.get(p["stufe"], p["stufe"])), open=True)
            zeichen = "☑ " if self._an(p) else "☐ "
            text = zeichen + p["name"].removesuffix(".lua") + ("  ⚠" if p["name"] in self.fehler else "") + (
                "  ●" if p["name"] in self.schalter else "")
            b.insert(eltern, "end", iid="patch:" + p["name"], text=text)
        if not self.liste:
            b.insert("", "end", iid="leer", text=_("No patches in the profile."))
        if sel and b.exists(sel[0]):
            b.selection_set(sel[0])
        self._auswahl_zeigen()
        self._mitgebracht_zeigen()
        self.stand_zeigen()

    def _gewaehlt(self):
        sel = self.baum.selection()
        if not sel or not sel[0].startswith("patch:"):
            return None
        name = sel[0][6:]
        return next((p for p in self.liste or [] if p["name"] == name), None)

    def _auswahl_zeigen(self):
        p = self._gewaehlt()
        if not p:
            self.detail.configure(text="")
            return
        text = p["datei"]
        if p["name"] in self.fehler:
            text += "\n" + _("⚠ Failed in the workbench: {meldung}").format(meldung=self.fehler[p["name"]])
        self.detail.configure(text=text)

    def umschalten(self):
        p = self._gewaehlt()
        if not p:
            return
        neu = not self._an(p)
        if neu == p["an"]:
            self.schalter.pop(p["name"], None)
        else:
            self.schalter[p["name"]] = neu
        self._fuellen()
        self._planen(PAUSE, self.ins_bild)

    def _alle_geaendert(self):
        if self._laden_laeuft:
            return
        neu = bool(self.alle_var.get())
        self.alle_neu = None if neu == kks.alle_aus(self.ko) else neu
        self._fuellen()
        self._planen(PAUSE, self.ins_bild)

    def ungespeichert(self):
        return bool(self.schalter) or self.alle_neu is not None

    # ------------------------------------------------------------------ Dateien (wirken sofort im Profil)
    def anzeigen(self):
        p = self._gewaehlt()
        if not p:
            return
        f = tk.Toplevel(self.app)
        f.title(p["name"])
        f.geometry("760x560")
        f.transient(self.app)
        farben = kth.PALETTE["dunkel" if self.app.dark_mode.get() else "hell"]
        t = tk.Text(f, wrap="none", font=("Monospace", 10), bg=farben["feld"], fg=farben["feld_fg"],
                    borderwidth=0, highlightthickness=0)
        sb = ttk.Scrollbar(f, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(fill="both", expand=True)
        t.insert("1.0", kks.patch_text(self.ko, p["datei"]))
        t.configure(state="disabled")
        f.bind("<Escape>", lambda e: f.destroy())
        self._fenster = f

    def hinzufuegen(self):
        pfad = filedialog.askopenfilename(parent=self.app, title=_("Add a patch"),
                                          filetypes=[(_("Lua patches"), "*.lua"), (_("All files"), "*")])
        if not pfad:
            return
        pfad = Path(pfad)
        try:
            text = pfad.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self.app.status.set(str(e))
            return
        warnung = kks.lua_pruefen(text)
        if warnung and not messagebox.askyesno(self.titel, warnung + "\n" + _("Add it anyway?"), parent=self.app):
            return
        name = pfad.name if pfad.name.endswith(".lua") else pfad.name + ".lua"
        if not re.match(r"^\d+-", name):
            name = "2-" + name                        # ohne Stufe würde KOReader ihn nie ausführen
        ziel = kks.patch_ordner(self.ko)
        ziel.mkdir(parents=True, exist_ok=True)
        if (ziel / name).exists() and not messagebox.askyesno(
                self.titel, _("{name} is already in the profile. Replace it?").format(name=name), parent=self.app):
            return
        shutil.copy2(pfad, ziel / name)
        kpl._profil_geaendert(self.bereich.profil, self.plugin)
        self.app.status.set(_("Patch {name} added to the profile.").format(name=name))
        self.liste = kks.patches(self.ko)
        self._fuellen()
        self._planen(100, self.ins_bild)

    def loeschen(self):
        p = self._gewaehlt()
        if not p:
            return
        if not messagebox.askyesno(self.titel, _("Delete the patch {name} from the profile?").format(name=p["name"]),
                                   parent=self.app):
            return
        try:
            (kks.patch_ordner(self.ko) / p["datei"]).unlink()
        except OSError as e:
            self.app.status.set(str(e))
            return
        self.schalter.pop(p["name"], None)
        kpl._profil_geaendert(self.bereich.profil, self.plugin)
        self.liste = kks.patches(self.ko)
        self._fuellen()
        self._planen(100, self.ins_bild)

    # ------------------------------------------------------------------ Werkbank
    def ins_bild(self):
        if self.bereich.unterseite() == self.plugin:
            self.bereich.werkbank_starten(still=True)

    def in_kopie(self, ko):
        """Zustand in der Wegwerf-Kopie herstellen. workbench.arbeitsprofil hat ".patches_disabled" schon in
        einzeln ausgeschaltete Patches verwandelt; hier gilt der Entwurf."""
        if self.liste is None:
            return
        alle_aus = self._alle_aus()
        soll = {p["name"]: (self._an(p) and not alle_aus) for p in self.liste}
        kks.patches_anwenden(ko, soll)

    def nach_start(self):
        if self.liste is not None:
            self._fehler_lesen()
            self.app.after(1500, self._nachlesen)     # späte Patches laufen erst nach "ready"
            self._fuellen()

    def _nachlesen(self):
        if self.liste is not None:
            self._fehler_lesen()
            self._fuellen()

    def speichern(self):
        if not self.ungespeichert():
            return False
        kks.patches_anwenden(self.ko, self.schalter, self.alle_neu)
        kpl._profil_geaendert(self.bereich.profil, self.plugin)
        self.app.status.set(_("Patches saved in the profile."))
        self.neu_laden()
        return True

    def verwerfen(self):
        if not self.ungespeichert():
            return
        if not messagebox.askyesno(self.titel, _("Discard the unsaved changes?"), parent=self.app):
            return
        self.neu_laden()
        self.ins_bild()
