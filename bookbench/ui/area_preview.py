# -*- coding: utf-8 -*-
"""
area_preview.py - Bereich "Vorschau" von Bookbench: ein Buch im
Desktop-KOReader so zeigen, wie es auf dem E-Reader aussieht (Schrift, Ränder, Kopf- und
Fußzeilen von Bookends). Die Logik steckt in kobo_vorschau, hier nur die Oberfläche.

  Kopf      gefundener KOReader, sonst ein Hinweis zur Installation
  links     Bücher der geöffneten Bibliothek (oder eine andere Datei)
  rechts    Stand des Profils, Bildschirmgröße, Buchdaten, KOReaders Ausgabe

Nur unter Linux und macOS gebaut (kobo_vorschau.verfuegbar()). KOReader läuft als
eigener Prozess weiter, Bookbench schaut nur einmal je Sekunde nach, ob er noch läuft.
"""
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import keller_theme as kth
from bookbench.ui import settings as kei
from bookbench.device import device as kg
from bookbench.preview import emulator as kv
from bookbench.i18n import _

ABSTAND = 1000                                   # ms, Nachschauen, ob KOReader noch läuft
INSTALLIEREN = (_("The preview needs the desktop KOReader. It is only needed for this, everything else works "
                  "without it. Install it (one of these):") + "\n"
                "  •  Arch/EndeavourOS: yay -S koreader-bin\n"
                "  •  Flatpak: flatpak install flathub rocks.koreader.KOReader\n"
                "  •  " + _("AppImage from github.com/koreader/koreader/releases into ~/Applications or ~/Downloads, "
                           "or \"Choose KOReader …\" below") + "\n" +
                _("Then \"Find KOReader\" in the Preview menu."))


def _datum(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return iso or "?"


class VorschauBereich:
    def __init__(self, app):
        self.app = app
        self.profil = kv.profil_ordner(kei.pfad())
        self.befund = None
        self.prozess = None
        self.andere_datei = None                 # Buch außerhalb der Bibliothek
        self._namen = {}                         # Anzeigename -> Pfad
        s = self.seite = app._seite(_("Preview"), "vorschau")

        # -- Kopf -------------------------------------------------------------
        ttk.Label(s, text=_("KOReader preview"), font=kth.schrift(12, fett=True)).pack(anchor="w")
        self.zeile = ttk.Label(s, text="", style="Hinweis.TLabel")
        self.zeile.pack(anchor="w", pady=(2, 4))
        self.fehlt = ttk.Frame(s)
        ttk.Label(self.fehlt, text=INSTALLIEREN, wraplength=900, justify="left").pack(anchor="w")
        ttk.Button(self.fehlt, text=_("Choose KOReader …"), command=self.koreader_waehlen).pack(anchor="w", pady=(6, 0))

        # -- Mitte --------------------------------------------------------------
        self.mitte = ttk.Frame(s)
        self.mitte.pack(fill="both", expand=True, pady=(8, 0))
        links = ttk.Frame(self.mitte)
        links.pack(side="left", fill="both")
        ttk.Label(links, text=_("Book"), style="Ueberschrift.TLabel").pack(anchor="w")
        # ohne Statusstreifen (der Stand gehört zu Kapitel), Suche ohne Filterauswahl
        self.liste = app._buchliste(links, self._buch_gewaehlt, streifen=False, geaendert=lambda: self.liste_fuellen())
        self.liste.bind("<Double-1>", lambda e: self.starten())

        rechts = ttk.Frame(self.mitte, padding=(16, 0, 0, 0))
        rechts.pack(side="left", fill="both", expand=True)
        ttk.Label(rechts, text=_("Profile (settings, plugins, fonts from the e-reader)"),
                  style="Ueberschrift.TLabel").pack(anchor="w")
        self.profil_text = ttk.Label(rechts, text="", wraplength=620, justify="left")
        self.profil_text.pack(anchor="w", pady=(0, 2))
        self.profil_hinweis = ttk.Label(rechts, text="", style="Hinweis.TLabel", wraplength=620, justify="left")
        self.profil_hinweis.pack(anchor="w", pady=(0, 10))

        ttk.Label(rechts, text=_("Screen"), style="Ueberschrift.TLabel").pack(anchor="w")
        self.groesse_var = tk.StringVar(value=app.e.get("vorschau_groesse") or "passend")
        self.groesse_knopf = {}
        for name in kv.GROESSEN:
            k = self.groesse_knopf[name] = ttk.Radiobutton(rechts, value=name, variable=self.groesse_var,
                                                            command=self._groesse_merken)
            k.pack(anchor="w")
        self.geraet_text = ttk.Label(rechts, text="", style="Hinweis.TLabel", wraplength=620, justify="left")
        self.geraet_text.pack(anchor="w", pady=(0, 10))

        self.buch_text = ttk.Label(rechts, text="", style="Hinweis.TLabel", wraplength=620, justify="left")
        self.buch_text.pack(anchor="w", pady=(0, 8))

        ttk.Label(rechts, text=_("KOReader output"), style="Ueberschrift.TLabel").pack(anchor="w")
        r = app._listenrahmen(rechts)
        r.pack(fill="both", expand=True)
        self.log = tk.Text(r, height=8, wrap="none", borderwidth=0, highlightthickness=0, font=kth.schrift(9))
        sb = ttk.Scrollbar(r, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set, state="disabled")
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        self.koreader_suchen(still=True)
        self.anzeigen()

    # ================================================================ Werkzeugleiste, Menü
    def werkzeug(self, eltern):
        a = self.app
        a._wz_knopf(eltern, "starten", _("Start"), self.starten,
                    _("Open the selected book in the desktop KOReader, with the settings from the e-reader "
                      "(double-click)"))
        ttk.Separator(eltern, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
        a._wz_knopf(eltern, "uebernehmen", _("From the e-reader"), self.vom_kobo,
                    _("Rebuild the profile from the connected e-reader: settings, Bookends, patches, plugins, fonts"))
        a._wz_knopf(eltern, "zurueckschreiben", _("From backup"), self.aus_sicherung,
                    _("Settings from the backup selected in the E-reader area (otherwise the newest); plugins and "
                      "fonts stay"))
        ttk.Separator(eltern, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
        a._wz_knopf(eltern, "oeffnen", _("Other file"), self.datei_waehlen,
                    _("Show a book that is not in the opened library"))

    def koreader_suchen_menue(self):
        self.koreader_suchen()
        self.anzeigen()

    # ================================================================ Anzeige
    def koreader_suchen(self, still=False):
        self.befund = kv.koreader_finden(self.app.e.get("koreader_pfad") or "")
        if not still:
            self.app.status.set(f"KOReader: {kv.beschreibung(self.befund)}")

    def beim_zeigen(self):
        if not self.befund:
            self.koreader_suchen(still=True)
        self.liste_fuellen()
        self.anzeigen()

    def liste_fuellen(self):
        a = self.app
        alt = self._gewaehlter_name()
        if alt is None:                                     # sonst das Buch, das in Kapitel gerade offen ist
            b = a._aktuelles_buch(a.kap_liste)
            alt = a._anzeigename(b) if b else None
        # gleiche Reihenfolge wie in Kapitel und Klappentexte (nach Reihe, Nummer, Titel), eigene Suche
        lf = self.liste.filter
        self._namen = {a._anzeigename(b): b.pfad for b in a._links_sortiert() if lf.passt(b)}
        if self.andere_datei:
            self._namen[f"[Datei] {self.andere_datei.name}"] = self.andere_datei
        self.liste.delete(0, "end")
        for n in self._namen:
            self.liste.insert("end", n)
        namen = list(self._namen)
        if alt in self._namen:
            i = namen.index(alt)
            self.liste.selection_set(i)
            self.liste.see(i)
        self._buch_gewaehlt()

    def _gewaehlter_name(self):
        sel = self.liste.curselection()
        return self.liste.get(sel[0]) if sel else None

    def _gewaehltes_buch(self):
        n = self._gewaehlter_name()
        return self._namen.get(n) if n else None

    def anzeigen(self):
        da = self.befund is not None
        self.zeile.configure(text=f"KOReader: {kv.beschreibung(self.befund)}" if da else
                             _("Desktop KOReader not found."))
        if da:
            self.fehlt.pack_forget()
        else:
            self.fehlt.pack(anchor="w", fill="x", before=self.mitte, pady=(0, 6))
        st = kv.profil_stand(self.profil)
        if not st["vorhanden"]:
            self.profil_text.configure(text=_("Still empty."))
            self.profil_hinweis.configure(text=_("Connect the e-reader and \"From the e-reader\". \"From backup\" works too, "
                                                 "but then plugins (Bookends) and fonts are missing."))
        else:
            if st["quelle"] == "kobo":
                g = st["geraet"]
                wer = ", ".join(x for x in (g.get("modell"), g.get("koreader") and f"KOReader {g['koreader']}") if x)
                kopf = _("Taken from the e-reader on {datum}").format(datum=_datum(st["datum"])) + (f" ({wer})" if wer else "")
            else:
                kopf = _("Taken from backup {name} on {datum}").format(name=st["sicherung"], datum=_datum(st["datum"]))
            teile = [_("Plugins: {liste}").format(liste=", ".join(st["plugins"]) or _("none")),
                     _("Fonts: {n}").format(n=st["schriften"]), _("Patches: {n}").format(n=st["patches"]),
                     _("Style tweaks: {n}").format(n=st["styletweaks"]),
                     _("Bookends presets: {n}").format(n=st["bookends_vorlagen"])]
            self.profil_text.configure(text=kopf + "\n" + "  ·  ".join(teile))
            hinweise = []
            if not st["plugins_von"]:
                hinweise.append(_("⚠ Plugins and fonts are missing: take \"From the e-reader\" once, otherwise Bookends "
                                  "is missing."))
            elif "bookends" not in st["plugins"]:
                hinweise.append(_("Bookends is not in the profile (not installed on the e-reader?)."))
            hinweise.append(_("Folder: {ordner}").format(ordner=self.profil))
            self.profil_hinweis.configure(text="\n".join(hinweise))
        bs = self.bildschirm(st)
        hoehe = self.app.winfo_screenheight()
        for name, k in self.groesse_knopf.items():
            w, h, dpi = kv.groesse(name, hoehe, bs)
            k.configure(text=f"{kv.GROESSE_TEXT[name]} ({w} × {h}, {dpi} dpi)")
        woher = {"eigen": _("own size from the settings"), "einstellung": _("chosen in the settings"),
                 "profil": _("device of the profile"), "kobo": _("connected e-reader"),
                 "standard": _("⚠ device unknown, standard size - choose it in Settings > Preview")}[bs["quelle"]]
        self.geraet_text.configure(text=_(
            "{name}: {w} × {h} pixels, {dpi} dpi, {farbe} ({woher}). Such a tall window rarely fits the screen; "
            "smaller with a matching DPI the page looks the same, only coarser.").format(
            name=bs["name"], w=bs["w"], h=bs["h"], dpi=bs["dpi"], woher=woher,
            farbe=_("colour") if bs["farbe"] else _("black and white")))
        self.protokoll_zeigen()

    def _buch_gewaehlt(self):
        p = self._gewaehltes_buch()
        if not p:
            self.buch_text.configure(text=_("Select a book on the left (open a library with Ctrl+O)."))
            return
        if p.with_name(p.stem + ".sdr").is_dir():
            text = _("Book data (.sdr) is next to the book: font size, margins etc. as on the e-reader.")
        else:
            text = _("No book data next to the book. At start the connected e-reader and the newest backup are searched "
                     "for the same file name, otherwise the general settings apply.")
        self.buch_text.configure(text=f"{p.name}\n{text}")

    def protokoll_zeigen(self):
        text, n, __ = kv.protokoll(self.profil)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("1.0", text)
        self.log.see("end")
        self.log.configure(state="disabled")
        return n

    def farben(self):
        p = kth.PALETTE["dunkel" if self.app.dark_mode.get() else "hell"]
        self.log.configure(bg=p["feld"], fg=p["feld_fg"], insertbackground=p["feld_fg"])

    def bildschirm(self, st=None):
        """Nachgebildetes Gerät nach Einstellung, Profil und angeschlossenem Gerät (emulator.bildschirm)."""
        st = st or kv.profil_stand(self.profil)
        k = self.app.kobo
        info = k.info if getattr(k, "wurzel", None) and k.wurzel.exists() else None
        return kv.bildschirm(self.app.e.get("vorschau_geraet") or "auto", self.app.e.get("vorschau_eigen"),
                             st.get("geraet"), info)

    def _groesse_merken(self):
        self.app.e["vorschau_groesse"] = self.groesse_var.get()

    # ================================================================ Aktionen
    def _sicherung(self):
        """Im Bereich E-Reader markierte Sicherung, sonst die neueste."""
        k = self.app.kobo
        sel = k.baum.selection()
        if sel and sel[0] in k._sicherungen:
            return Path(sel[0])
        alle = kg.sicherungen(k.sicherungsordner())
        return Path(alle[0]["pfad"]) if alle else None

    def vom_kobo(self):
        k = self.app.kobo
        if self.app._arbeit:
            self.app.status.set(_("Still running: {arbeit}.").format(arbeit=self.app._arbeit))
            return
        if not k.wurzel or not k.wurzel.exists():
            self.app.status.set(_("No e-reader connected."))
            return
        wurzel, info, profil = k.wurzel, dict(k.info), self.profil

        def arbeit():
            st = kv.vom_geraet(wurzel, profil, info)
            return _("Profile taken from the e-reader: {plugins} plugins, {schriften} fonts, {vorlagen} Bookends presets.").format(
                plugins=len(st["plugins"]), schriften=st["schriften"], vorlagen=st["bookends_vorlagen"])
        self.app.hintergrund(_("Taking profile"), arbeit, nachher=self.anzeigen)

    def aus_sicherung(self):
        if self.app._arbeit:
            self.app.status.set(_("Still running: {arbeit}.").format(arbeit=self.app._arbeit))
            return
        zip_pfad = self._sicherung()
        if not zip_pfad:
            self.app.status.set(_("No backup available (E-reader area: Back up)."))
            return
        profil = self.profil

        def arbeit():
            st = kv.aus_sicherung(zip_pfad, profil)
            text = _("Settings taken from {name}.").format(name=zip_pfad.name)
            if not st["plugins_von"]:
                text += " " + _("Plugins and fonts are still missing (take them from the e-reader once).")
            return text
        self.app.hintergrund(_("Taking profile"), arbeit, nachher=self.anzeigen)

    def datei_waehlen(self):
        p = filedialog.askopenfilename(parent=self.app, title=_("Book for the preview"),
                                       filetypes=[("E-Books", "*.epub *.kepub *.kepub.epub *.pdf *.fb2 *.mobi"),
                                                  (_("All files"), "*")])
        if not p:
            return
        self.andere_datei = Path(p)
        self.liste_fuellen()
        name = f"[Datei] {self.andere_datei.name}"
        namen = list(self._namen)
        self.liste.selection_clear(0, "end")
        self.liste.selection_set(namen.index(name))
        self.liste.see(namen.index(name))
        self._buch_gewaehlt()

    def koreader_waehlen(self):
        p = filedialog.askopenfilename(parent=self.app, title=_("Choose the KOReader program or AppImage"),
                                       initialdir=str(Path.home()))
        if not p:
            return
        self.app.e["koreader_pfad"] = p
        self.koreader_suchen()
        self.anzeigen()

    def profil_oeffnen(self):
        self.profil.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(self.profil)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            self.app.status.set(_("The folder could not be opened: {fehler}").format(fehler=e))

    def laeuft(self):
        return self.prozess is not None and self.prozess.poll() is None

    def starten(self):
        a = self.app
        if a._arbeit:
            a.status.set(_("Still running: {arbeit}.").format(arbeit=a._arbeit))
            return
        if self.laeuft():
            a.status.set(_("KOReader is already running. Close its window, then start again."))
            return
        if not self.befund:
            self.koreader_suchen(still=True)
            if not self.befund:
                a.status.set(_("Desktop KOReader not found (see the note at the top of the area)."))
                self.anzeigen()
                return
        buch = self._gewaehltes_buch()
        if not buch:
            a.status.set(_("Select a book on the left first."))
            return
        if not kv.profil_stand(self.profil)["vorhanden"]:
            a.status.set(_("The profile is empty: first \"From the e-reader\" or \"From backup\"."))
            return
        bs = self.bildschirm()
        w, h, dpi = kv.groesse(self.groesse_var.get(), a.winfo_screenheight(), bs)
        sw = not bs["farbe"]
        befund, profil = self.befund, self.profil
        kobo = a.kobo.wurzel if a.kobo.wurzel and a.kobo.wurzel.exists() else None
        sicherung = self._sicherung()
        ergebnis = {}

        def arbeit():
            sdr = kv.sdr_finden(buch, kobo, sicherung)
            ergebnis["prozess"] = kv.starten(befund, profil, buch, w, h, dpi, sdr, sw)
            if not sdr:
                woher = _("without book data, general settings")
            elif sdr[0] == "zip":
                woher = _("book data from the backup")
            elif sdr[1].parent == buch.parent:
                woher = _("book data next to the book")
            else:
                woher = _("book data from the e-reader")
            return _("KOReader started: {name} ({w} × {h}, {dpi} dpi, {woher}).").format(name=buch.name, w=w, h=h, dpi=dpi,
                                                                                       woher=woher)

        def nachher():
            self.prozess = ergebnis.get("prozess")
            if self.prozess:
                self.protokoll_zeigen()                 # neue, noch leere Ausgabe statt der vom letzten Lauf
                a.after(ABSTAND, self._beobachten)
        a.hintergrund(_("Starting preview"), arbeit, nachher=nachher)

    def _beobachten(self):
        if self.prozess is None:
            return
        code = self.prozess.poll()
        if code is None:
            self.protokoll_zeigen()
            self.app.after(ABSTAND, self._beobachten)
            return
        self.prozess = None
        n = self.protokoll_zeigen()
        text = _("KOReader closed") + (" " + _("(exit code {code})").format(code=code) if code else "")
        if n:
            text += ", " + _("{n} warnings/errors in the output (at the bottom of the Preview area)").format(n=n)
        self.app.status.set(text + ".")
        grund = kv.absturz_grund(self.profil, self.befund) if code else None
        if grund:                                       # Desktop-KOReader hält den Rechner für einen E-Reader
            messagebox.showwarning(_("Preview"), grund, parent=self.app)
