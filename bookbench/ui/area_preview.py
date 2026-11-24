# -*- coding: utf-8 -*-
"""
area_preview.py - Bereich "Vorschau" von Bookbench, seit 1.4 die KOReader-Werkbank: KOReader läuft
unsichtbar im Hintergrund (preview/workbench.py) und zeigt die Seite bzw. den Startbildschirm so, wie
sie auf dem E-Reader aussehen (Schrift, Ränder, Bookends, Bookshelf). Die Logik steckt in
preview/emulator.py und preview/workbench.py, hier nur die Oberfläche.

  Kopf      gefundener KOReader, sonst ein Hinweis zur Installation
  links     Ansicht (Leseseite/Startbildschirm), Buch (Blindtext, eins der Bibliothek, andere Datei),
            Blättern, Stand des Profils, Gerät, KOReaders Ausgabe
  rechts    das Bild von KOReader, auf die Fläche eingepasst; Klick links/rechts blättert

"In KOReader öffnen" startet wie bis 1.3 den vollen KOReader im Fenster (zum Ausprobieren von Menüs).
Nur unter Linux und macOS gebaut (emulator.verfuegbar()).

Seit 1.4-beta2 hat die linke Spalte Unterseiten (in der Seitenleiste unter Vorschau): Ansicht (das
Obige), seit 1.4-beta4 Schrift und Ränder sowie Patches (ui/workbench_reader.py, sobald es ein Profil
gibt) und je erkanntem Plugin im Profil eine Einstellungsseite (ui/workbench_plugins.py: Bookends,
Bookshelf). Das Bild rechts bleibt dabei stehen. Ohne Profil gibt es keine Unterseiten.
"""
import subprocess
import sys
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import keller_theme as kth
from bookbench.ui import panes as kpn
from bookbench.ui import settings as kei
from bookbench.device import device as kg
from bookbench.preview import emulator as kv
from bookbench.preview import workbench as kwb
from bookbench.preview import plugins as kpl
from bookbench.ui import workbench_plugins as kwp
from bookbench.ui import workbench_reader as kwr
from bookbench.ui import transfer_window as ktw
from bookbench.i18n import _

ABSTAND = 1000                                   # ms, Nachschauen, ob KOReader (Fenster) noch läuft
TAKT = 50                                        # ms, Ereignisse der Werkbank abholen
BLINDTEXT = "blindtext"                          # Kennung in der Buchauswahl
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
        self.prozess = None                      # voller KOReader im Fenster
        self.werkbank = None                     # KOReader im Hintergrund (kwb.Werkbank)
        self.andere_datei = None                 # Buch außerhalb der Bibliothek
        self._namen = {}                         # Anzeigename -> Pfad (BLINDTEXT: Blindtext-Buch)
        self._bild_pfad = None                   # zuletzt gezeigtes Bild
        self._bild_roh = None                    # PIL-Bild bzw. Pfad, zum Neu-Einpassen
        self._foto = None
        self._takt = None
        self._wartet_bild = False
        self._startzeit = 0.0
        s = self.seite = app._seite(_("Preview"), "vorschau")

        # -- Kopf -------------------------------------------------------------
        ttk.Label(s, text=_("KOReader workbench"), font=kth.schrift(12, fett=True)).pack(anchor="w")
        self.zeile = ttk.Label(s, text="", style="Hinweis.TLabel")
        self.zeile.pack(anchor="w", pady=(2, 4))
        self.fehlt = ttk.Frame(s)
        ttk.Label(self.fehlt, text=INSTALLIEREN, wraplength=900, justify="left").pack(anchor="w")
        ttk.Button(self.fehlt, text=_("Choose KOReader …"), command=self.koreader_waehlen).pack(anchor="w", pady=(6, 0))

        # -- Mitte --------------------------------------------------------------
        self.mitte = ttk.Frame(s)
        self.mitte.pack(fill="both", expand=True, pady=(8, 0))
        links_teil, rechts_teil = kpn.teilen(app, self.mitte, "vorschau", 400)
        # Unterseiten der linken Spalte (seit 1.4-beta2): Reiter unsichtbar, gewählt wird in der Seitenleiste
        self.unter = ttk.Notebook(links_teil, style="Navi.TNotebook")
        self.unter.pack(fill="both", expand=True)
        self.ansicht = ttk.Frame(self.unter)
        self.unter.add(self.ansicht, text=_("View"))
        self.ansicht_roll = kpn.RollFlaeche(self.ansicht)             # seit 1.4-beta6: aufgeklappt zu hoch
        self.ansicht_roll.pack(fill="both", expand=True)
        links = ttk.Frame(self.ansicht_roll.innen, padding=(0, 0, 12, 8))
        links.pack(fill="both", expand=True)
        self.plugin_seiten = {}

        ttk.Label(links, text=_("View"), style="Ueberschrift.TLabel").pack(anchor="w")
        self.modus_var = tk.StringVar(value=app.e.get("werkbank_modus") or "lesen")
        for wert, text in (("lesen", _("Reading page")), ("bibliothek", _("Start screen (library, Bookshelf)"))):
            ttk.Radiobutton(links, text=text, value=wert, variable=self.modus_var,
                            command=self._modus_gewechselt).pack(anchor="w")
        # Startbildschirm mit Beispielbüchern oder der geöffneten Bibliothek (seit 1.4-beta5)
        sb = ttk.Frame(links)
        sb.pack(anchor="w", padx=(20, 0))
        self.startbuecher_var = tk.StringVar(value=app.e.get("werkbank_startbuecher") or "beispiel")
        self.startbuecher_knopf = {}
        for wert, text in (("beispiel", _("with sample books")), ("bibliothek", _("with the opened library"))):
            k = self.startbuecher_knopf[wert] = ttk.Radiobutton(sb, text=text, value=wert,
                                                               variable=self.startbuecher_var,
                                                               command=self._startbuecher_gewechselt)
            k.pack(anchor="w")

        ttk.Label(links, text=_("Book"), style="Ueberschrift.TLabel").pack(anchor="w", pady=(10, 0))
        self.buch_var = tk.StringVar()
        self.buch_wahl = ttk.Combobox(links, textvariable=self.buch_var, state="readonly", width=34)
        self.buch_wahl.pack(anchor="w", fill="x")
        self.buch_wahl.bind("<<ComboboxSelected>>", lambda e: self._buch_gewaehlt(neu_starten=True))
        ttk.Button(links, text=_("Other file …"), style="Klein.TButton", command=self.datei_waehlen).pack(
            anchor="w", pady=(2, 0))                    # bis 1.4-beta5 in der Werkzeugleiste
        self.buch_text = ttk.Label(links, text="", style="Hinweis.TLabel", wraplength=320, justify="left")
        self.buch_text.pack(anchor="w", pady=(2, 0), fill="x")

        z = ttk.Frame(links)
        z.pack(anchor="w", pady=(10, 0))
        self.zurueck_knopf = ttk.Button(z, text="◀", width=3, command=lambda: self.blaettern(-1))
        self.zurueck_knopf.pack(side="left")
        self.weiter_knopf = ttk.Button(z, text="▶", width=3, command=lambda: self.blaettern(+1))
        self.weiter_knopf.pack(side="left", padx=(4, 0))
        ttk.Button(z, text=_("Restart"), command=self.werkbank_starten).pack(side="left", padx=(10, 0))
        ttk.Button(z, text=_("New picture"), command=self.neues_bild).pack(side="left", padx=(4, 0))
        self.werk_text = ttk.Label(links, text="", style="Hinweis.TLabel", wraplength=320, justify="left")
        self.werk_text.pack(anchor="w", pady=(4, 6), fill="x")

        # Profil, Gerät, Fenstergröße und Ausgabe: aufklappbar, damit die Spalte auf kleine Bildschirme passt
        self.details_var = tk.BooleanVar(value=bool(app.e.get("werkbank_details")))
        self.details_knopf = ttk.Checkbutton(links, text=_("Profile, device and output"), variable=self.details_var,
                                             command=self._details_zeigen, style="Toolbutton")
        self.details_knopf.pack(anchor="w", pady=(0, 6))
        details = self.details = ttk.Frame(links)
        links = details

        ttk.Label(links, text=_("Profile (settings, plugins, fonts from the e-reader)"),
                  style="Ueberschrift.TLabel", wraplength=320).pack(anchor="w")
        self.profil_text = ttk.Label(links, text="", wraplength=320, justify="left")
        self.profil_text.pack(anchor="w", pady=(0, 2))
        self.profil_hinweis = ttk.Label(links, text="", style="Hinweis.TLabel", wraplength=320, justify="left")
        self.profil_hinweis.pack(anchor="w", pady=(0, 10))

        ttk.Label(links, text=_("Device"), style="Ueberschrift.TLabel").pack(anchor="w")
        self.geraet_text = ttk.Label(links, text="", style="Hinweis.TLabel", wraplength=320, justify="left")
        self.geraet_text.pack(anchor="w", pady=(0, 4))
        ttk.Label(links, text=_("Window for \"Open in KOReader\":"), style="Hinweis.TLabel").pack(anchor="w")
        self.groesse_var = tk.StringVar(value=app.e.get("vorschau_groesse") or "passend")
        self.groesse_knopf = {}
        for name in kv.GROESSEN:
            k = self.groesse_knopf[name] = ttk.Radiobutton(links, value=name, variable=self.groesse_var,
                                                            command=self._groesse_merken)
            k.pack(anchor="w")

        ttk.Label(links, text=_("KOReader output"), style="Ueberschrift.TLabel").pack(anchor="w", pady=(10, 0))
        r = app._listenrahmen(links)
        r.pack(fill="x")
        self.log = tk.Text(r, height=10, width=10, wrap="none", borderwidth=0, highlightthickness=0,
                           font=kth.schrift(9))
        sb = ttk.Scrollbar(r, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set, state="disabled")
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        # -- Bild -----------------------------------------------------------------
        self.flaeche = tk.Canvas(rechts_teil, highlightthickness=0, borderwidth=0, cursor="hand2", takefocus=1)
        self.flaeche.pack(fill="both", expand=True)
        self.flaeche.bind("<Configure>", lambda e: self._bild_zeichnen())
        self.flaeche.bind("<Button-1>", self._klick)
        self.flaeche.bind("<Control-Button-1>", lambda e: self._tippen(e))
        self.flaeche.bind("<Button-3>", lambda e: self._tippen(e, halten=True))
        for taste, r in (("<Left>", -1), ("<Prior>", -1), ("<Right>", 1), ("<Next>", 1), ("<space>", 1)):
            self.flaeche.bind(taste, lambda e, r=r: self.blaettern(r))
        self._details_zeigen()

        # Unterseiten: KOReaders Schrift/Ränder und Patches (seit 1.4-beta4, sobald es ein Profil gibt),
        # dann je erkanntem Plugin eine Seite (seit 1.4-beta2)
        self.plugin_seiten = {"lesen": kwr.LesenSeite(self, self.unter), "patches": kwr.PatchSeite(self, self.unter),
                              kpl.BOOKENDS: kwp.BookendsSeite(self, self.unter),
                              kpl.BOOKSHELF: kwp.BookshelfSeite(self, self.unter)}
        for name, seite in self.plugin_seiten.items():
            self.unter.add(seite.rahmen, text=seite.titel, state="hidden")
        self.unter.bind("<<NotebookTabChanged>>", lambda e: self._unterseite_gewechselt())
        self._sichtbar = set()

        self.koreader_suchen(still=True)
        self.anzeigen()

    # ================================================================ Unterseiten (seit 1.4-beta2)
    def plugins_pruefen(self):
        """Unterseiten nach den Plugins im Profil zeigen/verstecken. Ohne Plugin keine Unterseiten in
        der Seitenleiste (seite.nb fehlt dann)."""
        sichtbar = set(kpl.erkennen(self.profil))
        if kv.profil_stand(self.profil)["vorhanden"]:
            sichtbar |= {"lesen", "patches"}
        neu = sichtbar != self._sichtbar
        self._sichtbar = sichtbar
        for name, seite in self.plugin_seiten.items():
            self.unter.tab(seite.rahmen, state="normal" if name in sichtbar else "hidden")
        if self.unterseite() not in sichtbar | {"ansicht"}:
            self.unter.select(self.ansicht)
        if sichtbar:
            self.seite.nb = self.unter
        else:
            self.seite.nb = None
            self.unter.select(self.ansicht)
        if neu:
            nav = getattr(self.app, "navi", None)
            if nav:
                nav.aktualisieren()

    def unterseite(self):
        """Kennung der gezeigten Unterseite: "ansicht", "bookends" oder "bookshelf"."""
        try:
            w = self.unter.nametowidget(self.unter.select())
        except (KeyError, tk.TclError):
            return "ansicht"
        return next((n for n, s in self.plugin_seiten.items() if s.rahmen is w), "ansicht")

    def plugin_seite(self):
        return self.plugin_seiten.get(self.unterseite())

    def unterseite_waehlen(self, name):
        seite = self.plugin_seiten.get(name)
        self.unter.select(seite.rahmen if seite and name in self._sichtbar else self.ansicht)

    def _unterseite_gewechselt(self):
        name = self.unterseite()
        self.app.e["werkbank_unterseite"] = name
        if self.app._bereich() == "vorschau":
            self.app._wz_bereich_bauen("vorschau")
            seite = self.plugin_seite()
            if seite:
                seite.beim_zeigen()

    def hilfe_thema(self):
        return {"bookends": "vorschau_bookends", "bookshelf": "vorschau_bookshelf", "lesen": "vorschau_lesen",
                "patches": "vorschau_patches"}.get(self.unterseite(), "vorschau")

    def ungespeichert(self):
        """Namen der Plugin-Seiten mit ungespeichertem Entwurf."""
        return [s.titel for s in self.plugin_seiten.values() if s.ungespeichert()]

    def entwuerfe_fragen(self):
        """Vor dem Neuaufbau des Profils: ungespeicherte Entwürfe speichern/verwerfen (False = abbrechen)."""
        return all(s.fragen_ob_verwerfen() for s in self.plugin_seiten.values())

    def _entwuerfe_in_kopie(self, ko):
        for s in self.plugin_seiten.values():
            s.in_kopie(ko)

    def modus_setzen(self, modus):
        """Ansicht umschalten (Leseseite/Startbildschirm) und die Werkbank neu starten."""
        self.modus_var.set(modus)
        self._modus_gewechselt()

    # ================================================================ Werkzeugleiste, Menü
    def werkzeug(self, eltern):
        a = self.app
        seite = self.plugin_seite()
        a._wz_knopf(eltern, "starten", _("Open in KOReader"), self.starten,
                    _("Open the full desktop KOReader in a window (reading page or start screen, as chosen), with the "
                      "settings from the e-reader and the drafts - for trying out menus. Works on its own copy."))
        ttk.Separator(eltern, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
        if seite:
            a._wz_knopf(eltern, "uebernehmen", _("Save to profile"), seite.speichern,
                        _("Keep the changes in the preview profile (until now they only show in the picture)"))
            a._wz_knopf(eltern, "rueckgaengig", _("Discard"), seite.verwerfen,
                        _("Back to what is in the profile"))
            ttk.Separator(eltern, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
            self._wz_rueckweg(eltern)
            return                                      # Profil holen usw. auf der Unterseite Ansicht
        a._wz_knopf(eltern, "uebernehmen", _("From the e-reader"), self.vom_kobo,
                    _("Rebuild the profile from the connected e-reader: settings, Bookends, patches, plugins, fonts"))
        a._wz_knopf(eltern, "zurueckschreiben", _("From backup"), self.aus_sicherung,
                    _("Settings from the backup selected in the E-reader area (otherwise the newest); plugins and "
                      "fonts stay"))
        self._wz_rueckweg(eltern)

    def _wz_rueckweg(self, eltern):
        self.app._wz_knopf(eltern, "sichern", _("To the e-reader …"), self.auf_den_reader,
                           _("Write what is changed in the preview profile to the connected e-reader (with a backup "
                             "before) - you choose what"))

    def auf_den_reader(self):
        """Rückweg Profil -> E-Reader (seit 1.4-beta6): Fenster mit den Unterschieden."""
        a = self.app
        if a._arbeit:
            a.status.set(_("Still running: {arbeit}.").format(arbeit=a._arbeit))
            return
        if not a.kobo.wurzel or not a.kobo.wurzel.exists():
            a.status.set(_("No e-reader connected."))
            return
        if not kv.profil_stand(self.profil)["vorhanden"]:
            a.status.set(_("The profile is empty: first \"From the e-reader\" or \"From backup\"."))
            return
        if not self.entwuerfe_fragen():
            return
        if getattr(self, "_rueckweg", None) is not None and self._rueckweg.winfo_exists():
            self._rueckweg.destroy()
        self._rueckweg = ktw.TransferFenster(self)

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
        seite = self.plugin_seite()
        if seite:
            seite.beim_zeigen()                         # startet ggf. in der passenden Ansicht neu
        if not (self.werkbank and self.werkbank.laeuft()):
            self.werkbank_starten(still=True)

    def liste_fuellen(self):
        """Buchauswahl: Blindtext, die Bücher der Bibliothek (wie in Kapitel sortiert), andere Datei."""
        a = self.app
        alt = self.buch_var.get()
        self._namen = {_("Sample text (Lorem ipsum)"): BLINDTEXT}
        self._namen.update({a._anzeigename(b): b.pfad for b in a._links_sortiert()})
        if self.andere_datei:
            self._namen[_("[File] {name}").format(name=self.andere_datei.name)] = self.andere_datei
        self.buch_wahl.configure(values=list(self._namen))
        if alt not in self._namen:
            self.buch_var.set(next(iter(self._namen)))
        self._buch_gewaehlt()

    def buch_waehlen(self, b, starten=True):
        """Buch wählen (Bibliothek: Öffnen in der Vorschau) und die Werkbank damit neu starten."""
        self.liste_fuellen()
        name = self.app._anzeigename(b)
        if name in self._namen:
            self.buch_var.set(name)
        if self.modus_var.get() != "lesen":
            self.modus_var.set("lesen")
            self.app.e["werkbank_modus"] = "lesen"
        self._buch_gewaehlt(neu_starten=starten)

    def _gewaehlter_name(self):
        return self.buch_var.get() or None

    def _gewaehltes_buch(self):
        """Pfad des gewählten Buchs; None beim Blindtext."""
        p = self._namen.get(self.buch_var.get())
        return None if p == BLINDTEXT else p

    def anzeigen(self):
        self.plugins_pruefen()
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
            "{name}: {w} × {h} pixels, {dpi} dpi, {farbe} ({woher}). The workbench always renders at full size "
            "and fits the picture into the area.").format(
            name=bs["name"], w=bs["w"], h=bs["h"], dpi=bs["dpi"], woher=woher,
            farbe=_("colour") if bs["farbe"] else _("black and white")))
        self.protokoll_zeigen()

    def _buch_gewaehlt(self, neu_starten=False):
        p = self._gewaehltes_buch()
        hat_bib = bool(self.app.buecher and getattr(self.app, "ordner", None))
        self.startbuecher_knopf["bibliothek"].configure(state="normal" if hat_bib else "disabled")
        if self.modus_var.get() == "bibliothek":
            if p:
                text = _("\"{name}\" counts as the book read last (Bookshelf shows it at the top). ").format(
                    name=self.buch_var.get())
            else:
                text = ""
            if self._startbuecher():
                text += _("The start screen shows the opened library, with the reading progress from the book data and "
                          "the most recently read books first. Click into the picture to tap there (e.g. Bookshelf's "
                          "shelf buttons), right-click for a long press.")
            else:
                text += _("The start screen shows eight sample books with covers. Click into the picture to tap there "
                          "(e.g. Bookshelf's shelf buttons), right-click for a long press.")
        elif not p:
            text = _("Sample text with chapters, title, author and series - enough for Bookends.")
        elif p.with_name(p.stem + ".sdr").is_dir():
            text = _("Book data (.sdr) is next to the book: font size, margins etc. as on the e-reader.")
        else:
            text = _("No book data next to the book. The connected e-reader and the newest backup are searched "
                     "for the same file name, otherwise the general settings apply.")
        self.buch_text.configure(text=text)
        if neu_starten:
            self.werkbank_starten()

    def _details_zeigen(self):
        an = self.details_var.get()
        self.app.e["werkbank_details"] = an
        self.details_knopf.configure(text=("▾ " if an else "▸ ") + _("Profile, device and output"))
        if an:
            self.details.pack(fill="both", expand=True)
        else:
            self.details.pack_forget()

    def _startbuecher_gewechselt(self):
        self.app.e["werkbank_startbuecher"] = self.startbuecher_var.get()
        if self.modus_var.get() == "bibliothek":
            self._buch_gewaehlt(neu_starten=True)

    def _startbuecher(self):
        """Bücher der geöffneten Bibliothek für den Startbildschirm, oder None (Beispielbücher)."""
        a = self.app
        if self.startbuecher_var.get() != "bibliothek" or not a.buecher or not getattr(a, "ordner", None):
            return None
        return Path(a.ordner), [b.pfad for b in a.buecher]

    def _modus_gewechselt(self):
        self.app.e["werkbank_modus"] = self.modus_var.get()
        self._buch_gewaehlt(neu_starten=True)

    def protokoll_zeigen(self):
        ordner = getattr(self, "_protokoll_ordner", None) or (self.werkbank.arbeit if self.werkbank else self.profil)
        text, n, __ = kv.protokoll(ordner)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("1.0", text)
        self.log.see("end")
        self.log.configure(state="disabled")
        return n

    def farben(self):
        self.ansicht_roll.farbe(kth.PALETTE["dunkel" if self.app.dark_mode.get() else "hell"]["bg"])
        for seite in self.plugin_seiten.values():
            seite.farben()
            seite.stand_zeigen()
        p = kth.PALETTE["dunkel" if self.app.dark_mode.get() else "hell"]
        self.log.configure(bg=p["feld"], fg=p["feld_fg"], insertbackground=p["feld_fg"])
        self.flaeche.configure(bg=p["bg"])
        self._bild_zeichnen()

    # ================================================================ Werkbank
    def _groesse_voll(self):
        bs = self.bildschirm()
        return bs["w"], bs["h"], bs["dpi"], not bs["farbe"]

    def werkbank_starten(self, still=False):
        """KOReader im Hintergrund (neu) starten: Ansicht und Buch aus der Auswahl, volle Gerätegröße."""
        a = self.app
        if not self.befund:
            self.koreader_suchen(still=True)
        if not self.befund:
            self._werk_meldung(_("Desktop KOReader not found."))
            return
        if not kv.profil_stand(self.profil)["vorhanden"]:
            self._werk_meldung(_("The profile is empty: first \"From the e-reader\" or \"From backup\"."))
            return
        if self.werkbank is None or self.werkbank.befund != self.befund:
            if self.werkbank:
                self.werkbank.beenden()
            self.werkbank = kwb.Werkbank(self.befund, self.profil)
        modus = self.modus_var.get()
        buch = self._gewaehltes_buch() if modus == "lesen" else None
        w, h, dpi, sw = self._groesse_voll()
        sdr = None
        if buch:
            kobo = a.kobo.wurzel if a.kobo.wurzel and a.kobo.wurzel.exists() else None
            sdr = kv.sdr_finden(buch, kobo, self._sicherung())
        bib = self._startbuecher() if modus == "bibliothek" else None
        zuerst = self._gewaehltes_buch() if modus == "bibliothek" else None   # als zuletzt gelesen (1.4-beta6)
        try:
            self.werkbank.starten(modus, buch, w, h, dpi, sw, sdr, bibliothek=bib[0] if bib else None,
                                  buecher=bib[1] if bib else None, zuerst=zuerst, anpassen=self._entwuerfe_in_kopie)
        except (RuntimeError, OSError) as e:
            self._werk_meldung(str(e))
            if not still:
                a.status.set(str(e))
            return
        self._startzeit = time.monotonic()
        self._wartet_bild = True
        self._bild_zeichnen()                          # altes Bild mit "lädt"-Hinweis
        self._werk_meldung(_("KOReader is starting in the background …"))
        self._takt_planen()

    def _werk_meldung(self, text):
        self.werk_text.configure(text=text)

    def _takt_planen(self):
        if self._takt is None:
            self._takt = self.app.after(TAKT, self._takt_schritt)

    def _takt_schritt(self):
        self._takt = None
        wb = self.werkbank
        if wb is None:
            return
        for e in wb.ereignisse():
            if e["art"] == "bereit":
                for seite in self.plugin_seiten.values():
                    seite.nach_start()
                wb.bild()
                if wb.modus == "bibliothek":           # Cover liest KOReader im Hintergrund nach und nach aus
                    for ms in (1500, 4000, 8000, 15000):
                        self.app.after(ms, lambda w=wb: w is self.werkbank and w.laeuft() and w.bild())
            elif e["art"] == "haengt":
                wb.bild()                                   # zeigen, was KOReader zeigt
                self._wartet_bild = False
                self._werk_meldung(_("KOReader did not open the book. On top: {fenster}. The picture shows KOReader's "
                                     "screen; click into it to tap there (e.g. a button of a dialog).").format(
                    fenster=e["text"] or "?"))
            elif e["art"] == "bild":
                erstes = self._wartet_bild
                self._wartet_bild = False                   # vor dem Zeichnen: kein "lädt"-Hinweis mehr
                self._bild_laden(e["pfad"])
                wb.alte_bilder_weg(behalten=e["pfad"])
                if wb.haengt:
                    pass
                elif erstes:
                    self._werk_meldung(_("Running in the background. Started in {s:.1f} s.").format(
                        s=time.monotonic() - self._startzeit))
                else:
                    self._werk_meldung(_("Running in the background. Last picture in {s:.2f} s.").format(s=e["dauer"]))
            elif e["art"] == "erledigt" and not e["ok"]:
                self._werk_meldung(_("KOReader reports: {text}").format(text=e["text"]))
            elif e["art"] == "fehler":
                self._werk_meldung(_("KOReader reports: {text}").format(text=e["text"]))
            elif e["art"] == "ende":
                n = self.protokoll_zeigen()
                text = _("KOReader in the background has stopped") + (
                    " " + _("(exit code {code})").format(code=e["code"]) if e["code"] else "") + "."
                if n:
                    text += " " + _("{n} warnings/errors in the output.").format(n=n)
                if wb.prozess is None and not e["code"]:
                    text = _("Stopped.")
                self._werk_meldung(text)
                return
        if wb.laeuft() or not wb._q.empty():
            self._takt_planen()

    def neues_bild(self):
        """Bild neu holen, ohne etwas zu tun (z. B. wenn KOReader im Hintergrund Cover nachgeladen hat)."""
        wb = self.werkbank
        if wb and wb.laeuft() and (wb.bereit or wb.haengt):
            wb.bild()
            self._takt_planen()

    def blaettern(self, richtung):
        wb = self.werkbank
        if not (wb and wb.laeuft() and wb.bereit):
            return
        wb.blaettern(richtung)
        wb.bild()
        self._takt_planen()

    def _klick(self, e):
        """Leseseite wie auf dem E-Reader: linkes Drittel zurück, sonst weiter. Startbildschirm (und wenn
        KOReader vor dem Buch hängt): an dieser Stelle tippen (seit 1.4-beta5)."""
        self.flaeche.focus_set()
        wb = self.werkbank
        if wb and (wb.modus == "bibliothek" or wb.haengt):
            self._tippen(e)
            return
        self.blaettern(-1 if e.x < self.flaeche.winfo_width() / 3 else +1)

    def _bildpunkt(self, x, y):
        """Klick auf der Fläche -> Pixel auf KOReaders Bildschirm (None außerhalb des Bilds)."""
        geo = getattr(self, "_bild_geo", None)
        if not geo:
            return None
        x0, y0, f, iw, ih = geo
        bx, by = (x - x0) / f, (y - y0) / f
        if not (0 <= bx < iw and 0 <= by < ih):
            return None
        return int(bx), int(by)

    def _tippen(self, e, halten=False):
        """Tippen (Strg+Klick, auf dem Startbildschirm jeder Klick) bzw. lange drücken (Rechtsklick) an
        dieser Stelle in KOReader, danach neue Bilder (KOReader zeichnet manches erst etwas später)."""
        self.flaeche.focus_set()
        wb = self.werkbank
        punkt = self._bildpunkt(e.x, e.y)
        if not (wb and wb.laeuft() and (wb.bereit or wb.haengt)) or punkt is None:
            return
        wb.tippen(*punkt, halten=halten)
        wb.bild()
        for ms in (400, 1500):
            self.app.after(ms, lambda: wb.laeuft() and wb.bild())
        self._takt_planen()

    def _bild_laden(self, pfad):
        try:
            from PIL import Image
            with Image.open(pfad) as im:
                self._bild_roh = im.convert("RGB")
        except ImportError:
            self._bild_roh = str(pfad)              # ohne Pillow: tk.PhotoImage mit ganzzahliger Verkleinerung
        except OSError:
            return
        self._bild_pfad = Path(pfad)
        self._bild_zeichnen()

    def _bild_zeichnen(self):
        c = self.flaeche
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 20 or h < 20:
            return
        if self._bild_roh is None:
            c.create_text(w // 2, h // 2, text=_("The picture from KOReader appears here."),
                          fill=kth.PALETTE["dunkel" if self.app.dark_mode.get() else "hell"]["fg"], width=w - 40)
            return
        if isinstance(self._bild_roh, str):
            foto = tk.PhotoImage(file=self._bild_roh, master=c)
            teiler = max(1, -(-foto.height() // h), -(-foto.width() // w))
            self._foto = foto.subsample(teiler) if teiler > 1 else foto
            self._teiler = teiler
        else:
            from PIL import Image, ImageTk
            iw, ih = self._bild_roh.size
            f = min(w / iw, h / ih, 1.0)
            self._foto = ImageTk.PhotoImage(self._bild_roh.resize((max(1, int(iw * f)), max(1, int(ih * f))),
                                                                  Image.LANCZOS), master=c)
        c.create_image(w // 2, h // 2, image=self._foto, anchor="center")
        fw, fh = self._foto.width(), self._foto.height()
        ohne_pil = isinstance(self._bild_roh, str)
        voll_w = fw * self._teiler if ohne_pil else self._bild_roh.size[0]
        voll_h = fh * self._teiler if ohne_pil else self._bild_roh.size[1]
        f = fw / voll_w if voll_w else 1
        self._bild_geo = ((w - fw) / 2, (h - fh) / 2, f, voll_w, voll_h)
        if self._wartet_bild:                          # neues Bild unterwegs: altes als veraltet kennzeichnen
            p = kth.PALETTE["dunkel" if self.app.dark_mode.get() else "hell"]
            c.create_rectangle(w // 2 - 110, h // 2 - 18, w // 2 + 110, h // 2 + 18, fill=p["kopf"], outline=p["rahmen"])
            c.create_text(w // 2, h // 2, text=_("KOReader is loading …"), fill=p["fg"])

    def beenden(self):
        """Beim Schließen von Bookbench: KOReader im Hintergrund beenden."""
        if self.werkbank:
            self.werkbank.beenden()

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
        if not self._profil_ersetzen_ok():
            return
        wurzel, info, profil = k.wurzel, dict(k.info), self.profil

        def arbeit():
            st = kv.vom_geraet(wurzel, profil, info)
            return _("Profile taken from the e-reader: {plugins} plugins, {schriften} fonts, {vorlagen} Bookends presets.").format(
                plugins=len(st["plugins"]), schriften=st["schriften"], vorlagen=st["bookends_vorlagen"])
        self.app.hintergrund(_("Taking profile"), arbeit, nachher=self._profil_neu)

    def _profil_ersetzen_ok(self):
        """Vor "Vom E-Reader"/"Aus Sicherung": Entwürfe und im Profil gespeicherte Änderungen gehen verloren."""
        if not self.entwuerfe_fragen():
            return False
        geaendert = kpl.profil_geaendert(self.profil)
        if geaendert and not messagebox.askyesno(_("Preview"), _(
                "Bookbench has changed {liste} in the profile, and these changes are not on the e-reader yet. Taking "
                "the profile again replaces them. Continue?").format(
                liste=", ".join(self.plugin_seiten[n].titel if n in self.plugin_seiten else n for n in geaendert)),
                parent=self.app):
            return False
        return True

    def _profil_neu(self):
        for seite in self.plugin_seiten.values():   # Entwürfe gehören zum alten Profil
            seite.zuruecksetzen()
        self.anzeigen()
        for name, seite in self.plugin_seiten.items():
            if name in self._sichtbar and (self.unterseite() == name):
                seite.neu_laden()
        self.werkbank_starten(still=True)

    def aus_sicherung(self):
        if self.app._arbeit:
            self.app.status.set(_("Still running: {arbeit}.").format(arbeit=self.app._arbeit))
            return
        zip_pfad = self._sicherung()
        if not zip_pfad:
            self.app.status.set(_("No backup available (E-reader area: Back up)."))
            return
        if not self._profil_ersetzen_ok():
            return
        profil = self.profil

        def arbeit():
            st = kv.aus_sicherung(zip_pfad, profil)
            text = _("Settings taken from {name}.").format(name=zip_pfad.name)
            if not st["plugins_von"]:
                text += " " + _("Plugins and fonts are still missing (take them from the e-reader once).")
            return text
        self.app.hintergrund(_("Taking profile"), arbeit, nachher=self._profil_neu)

    def datei_waehlen(self):
        p = filedialog.askopenfilename(parent=self.app, title=_("Book for the preview"),
                                       filetypes=[("E-Books", "*.epub *.kepub *.kepub.epub *.pdf *.fb2 *.mobi"),
                                                  (_("All files"), "*")])
        if not p:
            return
        self.andere_datei = Path(p)
        self.liste_fuellen()
        self.buch_var.set(_("[File] {name}").format(name=self.andere_datei.name))
        if self.modus_var.get() != "lesen":
            self.modus_var.set("lesen")
            self._modus_gewechselt()
        else:
            self._buch_gewaehlt(neu_starten=True)

    def koreader_waehlen(self):
        p = filedialog.askopenfilename(parent=self.app, title=_("Choose the KOReader program or AppImage"),
                                       initialdir=str(Path.home()))
        if not p:
            return
        self.app.e["koreader_pfad"] = p
        self.koreader_suchen()
        self.anzeigen()
        self.werkbank_starten(still=True)

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
        if not kv.profil_stand(self.profil)["vorhanden"]:
            a.status.set(_("The profile is empty: first \"From the e-reader\" or \"From backup\"."))
            return
        # seit 1.4-beta6 auf einer eigenen Wegwerf-Kopie (vorschau/fenster) wie die Werkbank: gleiche Ansicht
        # (Leseseite oder Startbildschirm mit Bibliothek), kepub-Kopie, Entwürfe; das Profil bleibt unberührt
        modus = self.modus_var.get()
        buch = self._gewaehltes_buch()
        bs = self.bildschirm()
        w, h, dpi = kv.groesse(self.groesse_var.get(), a.winfo_screenheight(), bs)
        sw = not bs["farbe"]
        sdr = None
        if buch and modus == "lesen":
            kobo = a.kobo.wurzel if a.kobo.wurzel and a.kobo.wurzel.exists() else None
            sdr = kv.sdr_finden(buch, kobo, self._sicherung())
        bib = self._startbuecher() if modus == "bibliothek" else None
        fenster = kwb.Werkbank(self.befund, self.profil, ordner=kwb.FENSTER, fenster=True)
        try:
            self.prozess = fenster.starten(modus, buch if modus == "lesen" else None, w, h, dpi, sw, sdr,
                                           bibliothek=bib[0] if bib else None, buecher=bib[1] if bib else None,
                                           zuerst=buch if modus == "bibliothek" else None,
                                           anpassen=self._entwuerfe_in_kopie)
        except (RuntimeError, OSError) as e:
            a.status.set(str(e))
            return
        self._protokoll_ordner = fenster.arbeit
        if modus == "bibliothek":
            text = _("KOReader started with the start screen ({w} × {h}, {dpi} dpi).").format(w=w, h=h, dpi=dpi)
        else:
            if not sdr:
                woher = _("without book data, general settings")
            elif sdr[0] == "zip":
                woher = _("book data from the backup")
            elif sdr[1].parent == Path(buch).parent:
                woher = _("book data next to the book")
            else:
                woher = _("book data from the e-reader")
            name = Path(buch).name if buch else kwb.BLINDTEXT
            text = _("KOReader started: {name} ({w} × {h}, {dpi} dpi, {woher}).").format(name=name, w=w, h=h, dpi=dpi,
                                                                                       woher=woher)
        a.status.set(text)
        self.protokoll_zeigen()
        a.after(ABSTAND, self._beobachten)

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
            text += ", " + _("{n} warnings/errors in the output (Preview > Profile, device and output)").format(n=n)
        self.app.status.set(text + ".")
        grund = kv.absturz_grund(getattr(self, "_protokoll_ordner", None) or self.profil, self.befund) if code else None
        if grund:                                       # Desktop-KOReader hält den Rechner für einen E-Reader
            messagebox.showwarning(_("Preview"), grund, parent=self.app)
