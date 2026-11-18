# -*- coding: utf-8 -*-
"""
area_dictionary.py - Bereich "Wörterbuch" von Bookbench: eigene Wörterbücher
lesen, bearbeiten, ergänzen, aufbauen und erzeugen. Die Logik steckt in kobo_woerterbuch.

  oben     Wörterbuch wählen (mehrere; Neu, Öffnen, Eigenschaften), Anzeigen, Suche
  links    Liste mit Statusstreifen
  rechts   Formular (Name, Kategorie, Kurzbeschreibung, andere Namen, Abschnitte; bei
           eingelesenen Einträgen das HTML bzw. den Text) und die Vorschau darunter
  Aufbau   (Ansicht, nur Wörterbücher mit Datenbank) die Schritte von wikidict.py mit
           Stand, Optionen und Ausgabe

Arten: Datenbank aus einem Wiki, Datenbank leer (nur eigene Einträge), StarDict-Ordner
(ohne Datenbank, z. B. ein fremdes Wörterbuch oder eine Kopie unterwegs).

Stand im Streifen: rot = im Formular geändert, nicht übernommen; gelb = übernommen, noch
nicht erzeugt; grün = erzeugt seit dem Öffnen. ⚠ = in KOReader nachgeschlagen, aber ohne
Eintrag (Fehlende) bzw. ungeprüfter Eintrag aus Claudes eigenem Wissen.
"""
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import keller_streifen as kst
import keller_theme as kth
from bookbench.device import device as kg
from bookbench.dictionary import store as kwb
from bookbench.dictionary import wikidict as W
from bookbench.i18n import _, ngettext

# Texte auf Modulebene: übersetzt beim Import (die Sprache wechselt nur mit einem Neustart)
ANSICHTEN = (_("Entries"), _("Missing terms"), _("Ignored and removed"), _("Steps"))
NEU = "＋ " + _("new entry")
STANDARD_ABSCHNITT = "Notes"
ART_TEXT = {"wiki": _("from a wiki"), "leer": _("own entries"), "stardict": _("StarDict folder")}
SPOILER = (("strict", _("none")), ("mild", _("background only")), ("full", _("all")))


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


class WoerterbuchBereich:
    def __init__(self, app):
        self.app = app
        self.wb = None                           # kwb.Woerterbuch / StarDictWoerterbuch oder None
        self.verlauf, self.verlauf_herkunft = [], ""
        self.fehlend = {}                        # Name -> Eintrag aus wb.fehlende()
        self.entwuerfe = {}                      # Listenschlüssel -> (Titel, data, Quelle)
        self.erzeugt = set()                     # in dieser Sitzung erzeugte eigene Einträge
        self.aktuell = None                      # Listenschlüssel im Formular
        self._laden_laeuft = False               # Formular wird programmseitig gefüllt
        self._modus = None                       # None (Formular), "html" oder "text"
        self._abbruch = threading.Event()
        self._migrieren()
        s = self.seite = app._seite(_("Dictionary"), "woerterbuch")

        # -- Kopf: welches Wörterbuch ---------------------------------------------
        kopf = ttk.Frame(s)
        kopf.pack(fill="x", pady=(0, 6))
        ttk.Label(kopf, text=_("Dictionary:")).pack(side="left")
        self.wahl_var = tk.StringVar()
        self.wahl = ttk.Combobox(kopf, textvariable=self.wahl_var, state="readonly", width=36)
        self.wahl.pack(side="left", padx=(4, 8))
        self.wahl.bind("<<ComboboxSelected>>", lambda e: self._gewaehlt())
        for text, befehl in ((_("New …"), self.anlegen), (_("Open …"), self.oeffnen_dialog),
                             (_("Properties …"), self.eigenschaften), (_("Remove from list"), self.aus_liste)):
            ttk.Button(kopf, text=text, command=befehl, width=-1).pack(side="left", padx=2)

        # -- ohne Wörterbuch ---------------------------------------------------------
        self.leer = ttk.Frame(s)
        ttk.Label(self.leer, text=_("No dictionary open."), style="Ueberschrift.TLabel").pack(anchor="w")
        self.leer_text = ttk.Label(self.leer, style="Hinweis.TLabel", wraplength=700, justify="left", text=(
            _("New …: create a dictionary, from a wiki (e.g. a Fandom wiki) or empty for your own entries.\nOpen "
              "…: the working folder of wikidict.py (with wikidict.sqlite) or a folder with a StarDict dictionary "
              "(.ifo), e.g. a copy or one from the e-reader.")))
        self.leer_text.pack(anchor="w", pady=(4, 8))

        # -- mit Wörterbuch ------------------------------------------------------------
        self.voll = ttk.Frame(s)
        oben = ttk.Frame(self.voll)
        oben.pack(fill="x", pady=(0, 6))
        ttk.Label(oben, text=_("Show:")).pack(side="left")
        self.ansicht = tk.StringVar(value=ANSICHTEN[0])
        self.ansicht_cb = ttk.Combobox(oben, textvariable=self.ansicht, values=ANSICHTEN, state="readonly", width=22)
        self.ansicht_cb.pack(side="left", padx=(4, 12))
        self.ansicht_cb.bind("<<ComboboxSelected>>", lambda e: self.liste_fuellen())
        ttk.Label(oben, text=_("Search:")).pack(side="left")
        self.suche = tk.StringVar()
        self.suchfeld = ttk.Entry(oben, textvariable=self.suche, width=28)
        self.suchfeld.pack(side="left", padx=4)
        self.suche.trace_add("write", lambda *a: self.liste_fuellen())
        self.db_label = ttk.Label(oben, text="", style="Hinweis.TLabel")
        self.db_label.pack(side="right")

        self.arbeit = ttk.Frame(self.voll)       # Liste + Formular
        self._liste_bauen(self.arbeit)
        self._formular_bauen(self.arbeit)
        self.aufbau = ttk.Frame(self.voll)       # Schritte von wikidict
        self._aufbau_bauen(self.aufbau)

        for v in self.v.values():
            v.trace_add("write", lambda *a: self._getippt())
        for t in (self.abschnitte, self.roh_text):
            t.bind("<<Modified>>", lambda e, t=t: self._text_getippt(t))
        for w in (self.abschnitte, self.roh_text, self.name_feld):
            w.bind("<Control-Return>", lambda e: (self.uebernehmen(), "break")[1])
        self.wahl_fuellen()
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
    def _liste_bauen(self, eltern):
        links = ttk.Frame(eltern)
        links.pack(side="left", fill="y")
        r = self.app._listenrahmen(links)
        r.pack(fill="both", expand=True)
        self.liste = tk.Listbox(r, width=30, borderwidth=0, highlightthickness=0, exportselection=False,
                                activestyle="none")
        sb = ttk.Scrollbar(r, orient="vertical", command=self.liste.yview)
        sb.pack(side="right", fill="y")
        self.liste.pack(side="left", fill="both", expand=True)
        self.streifen = kst.StatusStreifen(self.app, self.liste, r, self._status)
        self.liste.configure(yscrollcommand=lambda *a: (sb.set(*a), self.streifen.zeichnen()))
        if self.app.status_liste.get():
            self.streifen.einpacken()
        self.app._streifen.append(self.streifen)
        self.liste.bind("<<ListboxSelect>>", lambda e: self.anzeigen())
        self.anzahl = ttk.Label(links, text="", style="Hinweis.TLabel", wraplength=230, justify="left")
        self.anzahl.pack(anchor="w", pady=(4, 0))

    def _formular_bauen(self, eltern):
        rechts = ttk.Frame(eltern)
        rechts.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.kopf = ttk.Label(rechts, text=_("Choose an entry on the left."), style="Ueberschrift.TLabel")
        self.kopf.pack(anchor="w")
        self.info = ttk.Label(rechts, text="", style="Hinweis.TLabel", wraplength=700, justify="left")
        self.info.pack(anchor="w", pady=(2, 6))
        teiler = ttk.PanedWindow(rechts, orient="vertical")
        teiler.pack(fill="both", expand=True)

        form = ttk.Frame(teiler)
        form.columnconfigure(1, weight=1)
        self.v = {k: tk.StringVar() for k in ("name", "kategorie", "tagline", "aliase")}
        ttk.Label(form, text="Name:").grid(row=0, column=0, sticky="w", pady=2)
        self.name_feld = ttk.Entry(form, textvariable=self.v["name"])
        self.name_feld.grid(row=0, column=1, sticky="ew", pady=2)
        self.kat_label = ttk.Label(form, text=_("Category:"))
        self.kat_label.grid(row=0, column=2, sticky="w", padx=(12, 4))
        self.kat_feld = ttk.Combobox(form, textvariable=self.v["kategorie"], values=kwb.KATEGORIEN,
                                     state="readonly", width=14)
        self.kat_feld.grid(row=0, column=3, sticky="w")
        self.tag_label = ttk.Label(form, text=_("Short description:"))
        self.tag_label.grid(row=1, column=0, sticky="w", pady=2)
        self.tag_feld = ttk.Entry(form, textvariable=self.v["tagline"])
        self.tag_feld.grid(row=1, column=1, columnspan=3, sticky="ew", pady=2)
        ttk.Label(form, text=_("Other names:")).grid(row=2, column=0, sticky="w", pady=2)
        ttk.Entry(form, textvariable=self.v["aliase"]).grid(row=2, column=1, columnspan=3, sticky="ew", pady=2)
        self.text_label = ttk.Label(form, text=_("Sections:"))
        self.text_label.grid(row=3, column=0, sticky="nw", pady=2)
        form.rowconfigure(3, weight=1)
        self.text_rahmen = {}
        for name in ("abschnitte", "roh_text"):
            tr = self.app._listenrahmen(form)
            t = tk.Text(tr, height=7, wrap="word", borderwidth=0, highlightthickness=0, padx=6, pady=4,
                        font=kth.schrift(10) if name == "abschnitte" else kth.schrift(10, mono=True), undo=True)
            tsb = ttk.Scrollbar(tr, orient="vertical", command=t.yview)
            t.configure(yscrollcommand=tsb.set)
            tsb.pack(side="right", fill="y")
            t.pack(side="left", fill="both", expand=True)
            setattr(self, name, t)
            self.text_rahmen[name] = tr
        self.text_rahmen["abschnitte"].grid(row=3, column=1, columnspan=3, sticky="nsew", pady=2)
        self.form_hinweis = ttk.Label(form, style="Hinweis.TLabel",
                                      text=_("Line with # = heading, the text below it. Separate other names with "
                                             "commas."))
        self.form_hinweis.grid(row=4, column=1, columnspan=3, sticky="w")
        teiler.add(form, weight=3)

        unten = ttk.Frame(teiler, padding=(0, 6, 0, 0))
        ttk.Label(unten, text=_("This is how it looks in the dictionary:")).pack(anchor="w")
        vr = self.app._listenrahmen(unten)
        vr.pack(fill="both", expand=True)
        self.vorschau = tk.Text(vr, height=7, wrap="word", borderwidth=0, highlightthickness=0, padx=8, pady=6,
                                font=kth.schrift(10), state="disabled", cursor="arrow")
        vsb = ttk.Scrollbar(vr, orient="vertical", command=self.vorschau.yview)
        self.vorschau.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.vorschau.pack(side="left", fill="both", expand=True)
        self.vorschau.tag_configure("kursiv", font=kth.schrift(10) + ("italic",))
        self.vorschau.tag_configure("fett", font=kth.schrift(10, fett=True))
        self.vorschau.tag_configure("klein", font=kth.schrift(8))
        teiler.add(unten, weight=2)

    def _formular_modus(self, modus):
        """Formular für strukturierte Einträge oder Rohinhalt (HTML/Text) eingelesener Wörterbücher."""
        if modus == self._modus:
            return
        self._modus = modus
        strukturiert = modus is None
        for w in (self.kat_label, self.kat_feld, self.tag_label, self.tag_feld):
            (w.grid if strukturiert else w.grid_remove)()
        self.text_rahmen["abschnitte" if strukturiert else "roh_text"].grid(row=3, column=1, columnspan=3,
                                                                          sticky="nsew", pady=2)
        self.text_rahmen["roh_text" if strukturiert else "abschnitte"].grid_remove()
        self.text_label.configure(text=_("Sections:") if strukturiert else "HTML:" if modus == "html" else "Text:")
        self.form_hinweis.configure(text=_("Line with # = heading, the text below it. Separate other names with "
                                           "commas.")
                                    if strukturiert else _("Entry from an imported dictionary: content as stored "
                                                           "(HTML or text)."))

    def _aufbau_bauen(self, eltern):
        self.aufbau_titel = ttk.Label(eltern, text="", style="Ueberschrift.TLabel")
        self.aufbau_titel.pack(anchor="w")
        self.aufbau_info = ttk.Label(eltern, text="", style="Hinweis.TLabel", wraplength=900, justify="left")
        self.aufbau_info.pack(anchor="w", pady=(2, 8))
        tab = ttk.Frame(eltern)
        tab.pack(fill="x")
        tab.columnconfigure(2, weight=1)
        self.ao = {"scan_ordner": tk.StringVar(), "sofort": tk.BooleanVar(value=False),
                   "worte": tk.IntVar(value=150), "luecken": tk.BooleanVar(value=True),
                   "websuche": tk.BooleanVar(value=False), "nur_luecken": tk.BooleanVar(value=False)}
        self.schritt_zeilen = {}

        def zeile(r, befehl, titel, erklaerung, optionen=None):
            ttk.Label(tab, text=titel, font=kth.schrift(10, fett=True)).grid(row=r, column=0, sticky="nw", pady=(6, 0))
            stand = ttk.Label(tab, text="", style="Hinweis.TLabel", width=30)
            stand.grid(row=r, column=1, sticky="nw", padx=10, pady=(7, 0))
            mitte = ttk.Frame(tab)
            mitte.grid(row=r, column=2, sticky="ew", pady=(4, 0))
            ttk.Label(mitte, text=erklaerung, style="Hinweis.TLabel", wraplength=400, justify="left").pack(anchor="w")
            if optionen:
                optionen(mitte)
            knopf = ttk.Button(tab, text=_("Start"), command=lambda: self.schritt_starten(befehl))
            knopf.grid(row=r, column=3, sticky="ne", pady=(4, 0))
            self.schritt_zeilen[befehl] = (stand, knopf, [w for w in tab.grid_slaves(row=r)])

        def opt_scan(f):
            z = ttk.Frame(f)
            z.pack(anchor="w", fill="x")
            ttk.Entry(z, textvariable=self.ao["scan_ordner"], width=34).pack(side="left")
            ttk.Button(z, text=_("Choose …"), command=self._scan_ordner_waehlen, width=-1).pack(side="left", padx=4)

        def opt_sum(f):
            z = ttk.Frame(f)
            z.pack(anchor="w")
            ttk.Checkbutton(z, text=_("immediately instead of batch (twice the price)"),
                            variable=self.ao["sofort"]).pack(side="left")
            ttk.Label(z, text=_("  Length about")).pack(side="left")
            ttk.Spinbox(z, from_=60, to=400, increment=10, textvariable=self.ao["worte"], width=5).pack(side="left",
                                                                                                    padx=4)
            ttk.Label(z, text=_("words")).pack(side="left")

        def opt_check(f):
            z = ttk.Frame(f)
            z.pack(anchor="w")
            ttk.Checkbutton(z, text=_("Fill gaps"), variable=self.ao["luecken"]).pack(side="left")
            ttk.Checkbutton(z, text=_("gaps only"), variable=self.ao["nur_luecken"]).pack(side="left", padx=8)
            ttk.Checkbutton(z, text=_("Web search (1 cent per search)"),
                            variable=self.ao["websuche"]).pack(side="left")

        zeile(0, "titles", _("1. Load titles"), _("All article titles of the wiki (once, a few minutes)."))
        zeile(1, "scan", _("2. Search books"), _("Look for the titles in the books; the book text stays on the "
                                                    "computer. Names without an article become gaps."), opt_scan)
        zeile(2, "fetch", _("3. Load articles"), _("Only the articles that occur in the books."))
        zeile(3, "summarize", _("4. Summarize"), _("Claude writes the entries; cost estimated beforehand."), opt_sum)
        zeile(4, "crosscheck", _("5. Cross-check"), _("Compare with the second site, fill gaps."), opt_check)
        zeile(5, "build", _("6. Build"), _("Write the dictionary files."))
        unten = ttk.Frame(eltern)
        unten.pack(fill="both", expand=True, pady=(10, 0))
        z = ttk.Frame(unten)
        z.pack(fill="x")
        ttk.Label(z, text=_("Output:")).pack(side="left")
        self.abbruch_knopf = ttk.Button(z, text=_("Cancel"), command=self._abbrechen, state="disabled")
        self.abbruch_knopf.pack(side="right")
        lr = self.app._listenrahmen(unten)
        lr.pack(fill="both", expand=True, pady=(4, 0))
        self.log = tk.Text(lr, height=8, wrap="none", borderwidth=0, highlightthickness=0, padx=6, pady=4,
                           font=kth.schrift(9, mono=True), state="disabled")
        lsb = ttk.Scrollbar(lr, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=lsb.set)
        lsb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

    # ================================================================ Werkzeugleiste
    def werkzeug(self, eltern):
        a = self.app
        a._wz_knopf(eltern, "uebernehmen", _("Apply"), self.uebernehmen,
                    _("Apply the entry (Ctrl+Enter); it goes into the dictionary with Build"))
        a._wz_knopf(eltern, "rueckgaengig", _("Discard"), self.verwerfen, _("Discard the changes in the form"))
        ttk.Separator(eltern, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
        a._wz_knopf(eltern, "neu", _("New"), self.neu, _("Add a new term by hand"))
        ki = a._wz_knopf(eltern, "suchen", _("Claude ▾"), lambda: None,
                         _("Entry from Claude: search the web, from a page, from own knowledge"))
        ki.bind("<ButtonRelease-1>", lambda e: (a._tipp_weg(), self._ki_menue(ki)))
        a._wz_knopf(eltern, "zeile_minus", _("Remove"), self.entfernen,
                    _("Ignore a missing term or take an entry out of the dictionary (undo under Ignored and removed)"))
        ttk.Separator(eltern, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
        a._wz_knopf(eltern, "woerterbuch", _("Build"), self.erzeugen,
                    _("Rewrite the dictionary files; then copy them to the e-reader in the E-reader area"))

    def _ki_menue(self, knopf):
        m = tk.Menu(self.app, tearoff=False)
        m.add_command(label=_("Search the web (about 2-4 cents)"), command=lambda: self.ki("suche"))
        m.add_command(label=_("Summarize from a page …"), command=lambda: self.ki("link"))
        m.add_command(label=_("From own knowledge (unverified)"), command=lambda: self.ki("wissen"))
        m.tk_popup(knopf.winfo_rootx(), knopf.winfo_rooty() + knopf.winfo_height())

    # ================================================================ Wörterbücher verwalten
    def _liste_der_woerterbuecher(self):
        return [p for p in self.app.e.get("woerterbuecher", []) if p]

    def _anzeigename(self, pfad):
        info = kwb.kurzinfo(pfad)
        if not info:
            return _("(not found)") + f" - {pfad}"
        return f"{info[0]} ({ART_TEXT.get(info[1], info[1])}) - {pfad}"

    def wahl_fuellen(self):
        liste = self._liste_der_woerterbuecher()
        self._wahl_pfade = {self._anzeigename(p): p for p in liste}
        self.wahl.configure(values=list(self._wahl_pfade))
        aktiv = str(self.wb.pfad) if self.wb else ""
        for text, p in self._wahl_pfade.items():
            if p == aktiv:
                self.wahl_var.set(text)
                break
        else:
            self.wahl_var.set("")

    def _gewaehlt(self):
        p = self._wahl_pfade.get(self.wahl_var.get())
        if p and (not self.wb or str(self.wb.pfad) != p):
            if self._offen_ok():
                self.oeffnen(p)
            else:
                self.wahl_fuellen()

    def _offen_ok(self):
        n = len(self.entwuerfe)
        return not n or messagebox.askyesno(_("Dictionary"), ngettext(
            "{n} entry is changed in the form but not applied. Discard?",
            "{n} entries are changed in the form but not applied. Discard?", n).format(n=n), parent=self.app)

    def oeffnen_dialog(self):
        if not self._offen_ok():
            return
        o = filedialog.askdirectory(parent=self.app, title=_("Open dictionary (folder, it is also searched below)"),
                                    initialdir=self.app.e.get("woerterbuch_aktiv") or str(Path.home()))
        if not o:
            return
        gefunden = kwb.finden(o)
        if not gefunden:
            self.app.status.set(_("There is no dictionary in {ordner} or below (no .ifo file, no wikidict.sqlite).")
                                .format(ordner=o))
        elif len(gefunden) == 1:
            self.oeffnen(gefunden[0])
        else:
            AuswahlDialog(self, Path(o), gefunden)

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
            self.leer.pack_forget()
            self.voll.pack(fill="both", expand=True)
            self.db_label.configure(text=str(getattr(self.wb, "datei", self.wb.ifo_pfad if
                                                     self.wb.art == "stardict" else self.wb.pfad)))
            hat_aufbau = self.wb.art in ("wiki", "leer")
            self.ansicht_cb.configure(values=ANSICHTEN if hat_aufbau else ANSICHTEN[:3])
            if not hat_aufbau and self.ansicht.get() == ANSICHTEN[3]:
                self.ansicht.set(ANSICHTEN[0])
            if hat_aufbau:
                self.ao["scan_ordner"].set(W.meta_get(self.wb.db, "scan_dir", "") or self.app.ordner or "")
            self.verlauf_laden()
            if not still:
                self.app.status.set(ngettext("Dictionary {name}: {n} entry.", "Dictionary {name}: {n} entries.",
                                             len(self.wb.eintraege)).format(name=self.wb.titel(), n=len(self.wb.eintraege)))
        else:
            self.voll.pack_forget()
            self.leer.pack(fill="both", expand=True, anchor="nw")
        self.wahl_fuellen()
        self.liste_fuellen()

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
            WoerterbuchDialog(self, neu=True)

    def eigenschaften(self):
        if self.wb:
            WoerterbuchDialog(self, neu=False)

    def verlauf_laden(self):
        k = self.app.kobo if hasattr(self.app, "kobo") else None
        text, self.verlauf_herkunft = kg.verlauf_lesen(k.wurzel if k else None,
                                                       Path(self.app.e["sicherungsordner"]) / "KOReader")
        self.verlauf = kwb.nachschlageverlauf(text)

    def _bibliothek(self):
        return {b.titel: (b.reihe, b.autor) for b in getattr(self.app, "buecher", [])}

    # ================================================================ Liste
    def _schluessel(self):
        sel = self.liste.curselection()
        return self.liste.get(sel[0]) if sel else None

    def liste_fuellen(self, waehlen=None):
        self.fehlend = {f["name"]: f for f in self.wb.fehlende(self.verlauf, self._bibliothek())} if self.wb else {}
        if self.wb and self.ansicht.get() == ANSICHTEN[3]:
            self.arbeit.pack_forget()
            self.aufbau.pack(fill="both", expand=True)
            self.aufbau_zeigen()
            self.zaehler()
            return
        self.aufbau.pack_forget()
        self.arbeit.pack(fill="both", expand=True)
        alt = waehlen or self._schluessel()
        self.liste.delete(0, "end")
        if not self.wb:
            self.zaehler()
            return
        ansicht, such = self.ansicht.get(), self.suche.get().strip().casefold()
        if ansicht == ANSICHTEN[0]:
            namen = self.wb.suchen(such)
            if NEU in self.entwuerfe:
                namen = [NEU] + namen
            self.anzahl.configure(text=ngettext("{n} of {gesamt} entry", "{n} of {gesamt} entries", len(self.wb.eintraege))
                                  .format(n=len(namen), gesamt=len(self.wb.eintraege)))
        elif ansicht == ANSICHTEN[1]:
            namen = [n for n in self.fehlend if such in n.casefold()]
            herkunft = _("Lookup history {herkunft}").format(herkunft=self.verlauf_herkunft) if self.verlauf_herkunft \
                else _("no lookup history (connect the e-reader or back up the KOReader settings)")
            self.anzahl.configure(text=ngettext("{n} missing term", "{n} missing terms", len(namen)).format(n=len(namen))
                                  + "\n" + herkunft)
        else:
            namen = [n for n in self.wb.ignorierte() + self.wb.geloescht() if such in n.casefold()]
            self.anzahl.configure(text=_("{n} ignored or removed").format(n=len(namen)))
        for n in namen:
            self.liste.insert("end", n)
        if alt in namen:
            i = namen.index(alt)
            self.liste.selection_set(i)
            self.liste.see(i)
        self.anzeigen()
        self.zaehler()

    def _status(self, schluessel):
        if not self.wb:
            return None, None
        warn = None
        if self.ansicht.get() == ANSICHTEN[1]:
            f = self.fehlend.get(schluessel)
            warn = f["grund"] if f and f["nachgeschlagen"] else None
        elif "unverified" in (self.wb.quellen.get(schluessel) or ""):
            warn = _("unverified entry from Claude's own knowledge")
        if schluessel in self.entwuerfe:
            return "rot", warn
        if schluessel in self.erzeugt and not self.wb.stand(schluessel):
            return "gruen", warn
        return self.wb.stand(schluessel), warn

    def zaehler(self):
        n = sum(1 for f in self.fehlend.values() if f["nachgeschlagen"]) if self.wb else 0
        self.app.nb.tab(self.seite, text=_("Dictionary ({n} ⚠)").format(n=n) if n else _("Dictionary"))

    # ================================================================ Formular
    def anzeigen(self):
        k = self.aktuell = self._schluessel()
        self._laden_laeuft = True
        try:
            for v in self.v.values():
                v.set("")
            for t in (self.abschnitte, self.roh_text):
                t.delete("1.0", "end")
            self.name_feld.configure(state="normal")
            if not self.wb or not k:
                self._formular_modus(None)
                self.kopf.configure(text=_("Choose an entry on the left.") if self.wb else "")
                self.info.configure(text="")
                self._vorschau_setzen("")
                return
            titel, data, quelle = self._stand_von(k)
            self._formular_modus(_roh(data))
            self.kopf.configure(text=titel or _("New entry"))
            self.info.configure(text=self._info(k, titel, quelle))
            self.v["name"].set(titel)
            if data:
                self.v["aliase"].set(", ".join(data.get("aliases", [])))
                if self._modus:
                    self.roh_text.insert("1.0", data.get(self._modus) or "")
                else:
                    self.v["kategorie"].set(data.get("category", ""))
                    self.v["tagline"].set(data.get("tagline", ""))
                    self.abschnitte.insert("1.0", abschnitte_text(data.get("sections", [])))
            neu = k == NEU or self.ansicht.get() == ANSICHTEN[1] or (k in self.entwuerfe and titel != k)
            self.name_feld.configure(state="normal" if neu else "readonly")
        finally:
            for t in (self.abschnitte, self.roh_text):
                t.edit_modified(False)
            self._laden_laeuft = False
        self._vorschau_aktualisieren()
        self.streifen.zeichnen()

    def _basis(self, k):
        """(Titel, data, Quelle) in der Datenbank bzw. Datei, ohne Entwurf."""
        if k == NEU or self.ansicht.get() == ANSICHTEN[1]:
            return ("" if k == NEU else k), None, kwb.QUELLE_EIGEN
        return k, self.wb.eintraege.get(k) or self.wb.basis.get(k), self.wb.quellen.get(k, "")

    def _stand_von(self, k):
        if k in self.entwuerfe:
            return self.entwuerfe[k]
        return self._basis(k)

    def _info(self, k, titel, quelle):
        teile = []
        if self.ansicht.get() == ANSICHTEN[1] and k in self.fehlend:
            teile.append(self.fehlend[k]["grund"])
        elif self.ansicht.get() == ANSICHTEN[2]:
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
        aliase = [a.strip() for a in self.v["aliase"].get().split(",") if a.strip()]
        if self._modus:
            return self.v["name"].get().strip(), {self._modus: self.roh_text.get("1.0", "end-1c"), "aliases": aliase}
        return self.v["name"].get().strip(), {
            "category": self.v["kategorie"].get() or "Other",
            "tagline": self.v["tagline"].get().strip(),
            "sections": abschnitte_lesen(self.abschnitte.get("1.0", "end-1c")),
            "aliases": aliase}

    def _text_getippt(self, t):
        if t.edit_modified():
            t.edit_modified(False)
            self._getippt()

    def _getippt(self):
        if self._laden_laeuft or not self.wb or not self.aktuell:
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
        self.streifen.zeichnen()

    def _vorschau_aktualisieren(self):
        if not self.wb or not self.aktuell:
            return self._vorschau_setzen("")
        k = self.aktuell
        if k in self.entwuerfe:
            titel, data, quelle = self.entwuerfe[k]
            leer = not (data.get("tagline") or data.get("html") or data.get("text"))
            html = "" if leer else self.wb.vorschau(titel or "?", data, quelle)
        else:
            titel, data, quelle = self._stand_von(k)
            html = self.wb.vorschau(titel) if titel in self.wb.eintraege else \
                (self.wb.vorschau(titel, data, quelle) if data else "")
        self._vorschau_setzen(html, titel)

    def _vorschau_setzen(self, html, titel=""):
        v = self.vorschau
        v.configure(state="normal")
        v.delete("1.0", "end")
        if html:
            v.insert("end", titel + "\n", ("fett",))
            for text, stile in kwb.html_teile(html):
                v.insert("end", text, stile)
        v.configure(state="disabled")

    # ================================================================ Aktionen
    def _bereit(self):
        if not self.wb:
            self.app.status.set(_("No dictionary open (New … or Open …)."))
            return False
        if self.app._arbeit:
            self.app.status.set(_("Still running: {arbeit}.").format(arbeit=self.app._arbeit))
            return False
        return True

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
        if ersetzt and not messagebox.askyesno(
                _("Apply"), _("\"{titel}\" is already in the dictionary. Replace it with this entry?").format(titel=titel),
                parent=self.app):
            return
        self.wb.eigen_speichern(titel, data, quelle)
        self.entwuerfe.pop(k, None)
        self.erzeugt.discard(titel)
        if k != titel and k != NEU and self.ansicht.get() == ANSICHTEN[1] and not self.wb.bekannt(k):
            self.wb.ignorieren(k)       # z. B. "Sindermann" -> "Kyril Sindermann" ohne Alias: nicht mehr fehlend
        naechster = self._naechster(k) if self.ansicht.get() == ANSICHTEN[1] else titel
        if k == NEU:
            self.ansicht.set(ANSICHTEN[0])
        self.liste_fuellen(waehlen=naechster)
        self.app.status.set(f"{titel}: " + _("applied. It goes into the dictionary with Build."))

    def _naechster(self, k):
        namen = list(self.liste.get(0, "end"))
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
        self.ansicht.set(ANSICHTEN[0])
        self.suche.set("")
        self.entwuerfe[NEU] = ("", {"category": "Person", "tagline": "", "sections": [], "aliases": []},
                               kwb.QUELLE_EIGEN)
        self.liste_fuellen(waehlen=NEU)
        self.name_feld.focus_set()

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
        k, ansicht = self.aktuell, self.ansicht.get()
        naechster = self._naechster(k)
        self.entwuerfe.pop(k, None)
        if ansicht == ANSICHTEN[1]:
            self.wb.ignorieren(k)
            self.app.status.set(f"{k}: " + _("ignored (get it back under Ignored and removed)."))
        elif ansicht == ANSICHTEN[0]:
            self.wb.loeschen(k)
            self.app.status.set(f"{k}: " + _("taken out of the dictionary (get it back under Ignored and removed)."))
        else:
            self.wiederherstellen()
            return
        self.liste_fuellen(waehlen=naechster)

    def wiederherstellen(self):
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
        if not self._bereit() or not self.aktuell or self.ansicht.get() == ANSICHTEN[3]:
            self.app.status.set(_("First choose a term or enter a name with New."))
            return
        k = self.aktuell
        name = self.v["name"].get().strip() or (k if k != NEU else "")
        if not name:
            self.app.status.set(_("Enter a name first."))
            return
        url = None
        if art == "link":
            url = simpledialog.askstring(_("From a page"), _("Address of a page about \"{name}\":").format(name=name),
                                         parent=self.app)
            if not url:
                return
            url = url.strip()
        client = self.app._api_client()
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
            if self.aktuell == k:
                self.anzeigen()
            self.streifen.zeichnen()
        self.app.hintergrund(_("Asking Claude"), arbeit, nachher=nachher)

    def erzeugen(self):
        if not self._bereit():
            return
        if self.aktuell in self.entwuerfe:
            if not messagebox.askyesno(_("Build"), _("The entry in the form is not applied yet and will not be in "
                                                     "the dictionary. Build anyway?"), parent=self.app):
                return
        e = self.app.e
        stardict = self.wb.art == "stardict"
        ziel = self.wb.ausgabe()
        if not ziel:
            ziel = filedialog.askdirectory(parent=self.app, title=_("Folder for the dictionary (copied to the e-reader)"),
                                           initialdir=str(self.wb.pfad.parent))
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
            self.wb.laden()
            self.erzeugt |= eigene
            if not e.get("woerterbuch_quelle"):
                e["woerterbuch_quelle"] = ziel          # damit der Bereich E-Reader es gleich findet
            self.liste_fuellen()
            if hasattr(self.app, "kobo"):
                self.app.kobo._quellen = (None, 0.0, [])
        self.app.hintergrund(_("Building dictionary"), arbeit, nachher=nachher)

    def aus_stardict_uebernehmen(self):
        """Änderungen, die unterwegs an einer StarDict-Kopie gemacht wurden, in die Datenbank holen."""
        if not self._bereit() or self.wb.art == "stardict":
            self.app.status.set(_("Only for dictionaries with a database: the changes are collected there."))
            return
        o = filedialog.askdirectory(parent=self.app, title=_("StarDict folder with changes from Bookbench"))
        if not o:
            return
        n = self.wb.aus_stardict_uebernehmen(o)
        self.liste_fuellen()
        self.app.status.set(ngettext("{n} change taken from {ordner}.", "{n} changes taken from {ordner}.", n)
                            .format(n=n, ordner=o) if n else
                            _("{ordner} has no changes from Bookbench (bookbench.json).").format(ordner=o))

    # ================================================================ Aufbau (wikidict-Schritte)
    def aufbau_zeigen(self):
        wb = self.wb
        if not wb or wb.art == "stardict":
            return
        p = wb.profil()
        st = wb.stand_aufbau()
        wiki = wb.art == "wiki"
        self.aufbau_titel.configure(text=f"{wb.titel()} - {ART_TEXT[wb.art]}")
        self.aufbau_info.configure(text="  ·  ".join(x for x in (
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
                (w.grid if sichtbar else w.grid_remove)()
            stand.configure(text=texte.get(befehl, ""))
            aus = laeuft or (befehl == "crosscheck" and not p.get("check_site"))
            knopf.configure(state="disabled" if aus else "normal")

    def _scan_ordner_waehlen(self):
        o = filedialog.askdirectory(parent=self.app, title=_("Books folder to search"),
                                    initialdir=self.ao["scan_ordner"].get() or self.app.ordner or str(Path.home()))
        if o:
            self.ao["scan_ordner"].set(o)

    def _log(self, text, ersetzen=False):
        lg = self.log
        lg.configure(state="normal")
        if ersetzen and lg.index("end-1c") != "1.0":
            lg.delete("end-2l linestart", "end-1c")
            if lg.index("end-1c") != "1.0":
                lg.insert("end", "\n")
        elif lg.index("end-1c") != "1.0":
            lg.insert("end", "\n")
        lg.insert("end", text)
        lg.see("end")
        lg.configure(state="disabled")

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
            ordner = self.ao["scan_ordner"].get().strip()
            if not ordner or not Path(ordner).is_dir():
                self.app.status.set(_("Choose the books folder first."))
                return
            W.meta_set(wb.db, "scan_dir", ordner)
            argumente = [ordner]
        elif befehl in ("summarize", "crosscheck"):
            if self.app._api_client() is None:
                return
            if e.get("api_key"):
                os.environ["ANTHROPIC_API_KEY"] = e["api_key"]
            argumente = ["--model", e["modell"], "--spoilers", p.get("spoilers") or "mild"]
            if befehl == "summarize":
                argumente += ["--words", str(self.ao["worte"].get())] + (["--sync"] if self.ao["sofort"].get() else [])
            else:
                if self.ao["nur_luecken"].get():
                    argumente.append("--gaps-only")
                elif self.ao["luecken"].get():
                    argumente.append("--gaps")
                if self.ao["websuche"].get():
                    argumente.append("--search")
        self._abbruch.clear()
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.abbruch_knopf.configure(state="normal")
        q, arbeitsordner = self.app._q, str(wb.pfad)

        def schreiben(text, ersetzen=False):
            q.put(("rueckruf", lambda: self._log(text, ersetzen)))

        def fragen(text):
            antwort, fertig = {}, threading.Event()

            def frage():
                antwort["ja"] = messagebox.askyesno(kwb.SCHRITTE[befehl][0], text, parent=self.app)
                fertig.set()
            q.put(("rueckruf", frage))
            while not fertig.wait(0.2):
                if self._abbruch.is_set():
                    return False
            return antwort.get("ja", False)

        def arbeit():
            return kwb.schritt(arbeitsordner, befehl, argumente, schreiben, fragen, self._abbruch.is_set)

        def nachher():
            self.abbruch_knopf.configure(state="disabled")
            self.wb.laden()
            self.liste_fuellen()
        self.app.hintergrund(kwb.SCHRITTE[befehl][0], arbeit, nachher=nachher)
        self.aufbau_zeigen()

    # ================================================================ Sonstiges
    def beim_zeigen(self):
        """Bereich wird sichtbar: Nachschlageverlauf auffrischen (Gerät evtl. neu angesteckt)."""
        if self.wb:
            self.verlauf_laden()
            self.liste_fuellen()

    def farben(self):
        p = kth.PALETTE["dunkel" if self.app.dark_mode.get() else "hell"]
        for t in (self.abschnitte, self.roh_text, self.vorschau, self.log):
            t.configure(bg=p["feld"], fg=p["feld_fg"], insertbackground=p["feld_fg"])

    def offen(self):
        return len(self.entwuerfe)


# ================================================================ Dialog: mehrere gefunden
class AuswahlDialog(tk.Toplevel):
    """Mehrere Wörterbücher im gewählten Ordner: markierte in die Liste, das erste öffnen."""
    def __init__(self, bereich, basis, pfade):
        super().__init__(bereich.app)
        self.bereich, self.pfade = bereich, pfade
        self.title(_("Dictionaries found"))
        self.transient(bereich.app)
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=_("There are {n} dictionaries in {ordner}. The selected ones go into the list, the first "
                            "one is opened.").format(n=len(pfade), ordner=basis), wraplength=560, justify="left").pack(anchor="w")
        r = bereich.app._listenrahmen(f)
        r.pack(fill="both", expand=True, pady=8)
        self.liste = tk.Listbox(r, selectmode="extended", height=min(12, len(pfade)), width=80, borderwidth=0,
                                highlightthickness=0, activestyle="none")
        self.liste.pack(fill="both", expand=True)
        for p in pfade:
            info = kwb.kurzinfo(p) or (p.name, "?")
            try:
                rel = p.relative_to(basis)
            except ValueError:
                rel = p
            self.liste.insert("end", f"{info[0]} ({ART_TEXT.get(info[1], info[1])}) - {rel}")
        self.liste.selection_set(0)
        self.liste.bind("<Double-1>", lambda e: self.ok())
        z = ttk.Frame(f)
        z.pack(fill="x")
        ttk.Button(z, text=_("Cancel"), command=self.destroy).pack(side="right")
        ttk.Button(z, text=_("Open"), command=self.ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.destroy())

    def ok(self):
        gewaehlt = [self.pfade[i] for i in self.liste.curselection()]
        if not gewaehlt:
            return
        liste = self.bereich.app.e.setdefault("woerterbuecher", [])
        for p in gewaehlt[1:]:
            if str(p) not in liste:
                liste.append(str(p))
        self.destroy()
        self.bereich.oeffnen(gewaehlt[0])


# ================================================================ Dialog: neu / Eigenschaften
class WoerterbuchDialog(tk.Toplevel):
    def __init__(self, bereich, neu):
        app = bereich.app
        super().__init__(app)
        self.bereich, self.app, self.neu = bereich, app, neu
        wb = None if neu else bereich.wb
        p = wb.profil() if wb else {}
        self.art = tk.StringVar(value=wb.art if wb else "wiki")
        self.title(_("New dictionary") if neu else _("Properties: {name}").format(name=wb.titel()))
        self.transient(app)
        self.resizable(True, False)
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        self.v = {k: tk.StringVar(value=str(p.get(k) or "")) for k in ("name", "stem", "topic", "wiki", "check_site")}
        self.v["buecher"] = tk.StringVar(value=", ".join(p.get("buecher") or []))
        self.v["spoilers"] = tk.StringVar(value=p.get("spoilers") or "mild")
        self.v["ordner"] = tk.StringVar(value="")
        r = 0
        if neu:
            ttk.Label(f, text=_("Type:")).grid(row=r, column=0, sticky="nw", pady=2)
            z = ttk.Frame(f)
            z.grid(row=r, column=1, columnspan=2, sticky="w")
            ttk.Radiobutton(z, text=_("build from a wiki (MediaWiki, e.g. a Fandom wiki)"), value="wiki",
                            variable=self.art, command=self._art).pack(anchor="w")
            ttk.Radiobutton(z, text=_("empty, own entries only (collect names from books, Claude, by hand)"),
                            value="leer", variable=self.art, command=self._art).pack(anchor="w")
            r += 1
            self._feld(f, r, "ordner", _("Working folder:"), _("Bookbench creates the database here (new, empty "
                                                           "folder)."), knopf=self._ordner)
            r += 2
        else:
            ttk.Label(f, text=f"{ART_TEXT[wb.art]}: {wb.pfad}", style="Hinweis.TLabel").grid(
                row=r, column=0, columnspan=3, sticky="w", pady=(0, 6))
            r += 1
        self._feld(f, r, "name", _("Name in KOReader:"), _("Shown in KOReader's dictionary list."))
        r += 2
        if neu or wb.art != "stardict":
            self._feld(f, r, "stem", _("File name:"), _("Name of the dictionary files (without extension), e.g. "
                                                     "sw-legends."))
            r += 2
        self._feld(f, r, "topic", _("Topic:"), _("For Claude: what it is about, e.g. \"Star Wars Legends\" or \"Brandon "
                                              "Sanderson's Cosmere\". English is most precise."))
        r += 2
        self.wiki_zeilen = []
        if neu or wb.art == "wiki":
            self.wiki_zeilen += self._feld(f, r, "wiki", "Wiki:", _(
                "Base address of a MediaWiki, e.g. https://starwars.fandom.com or https://coppermind.net"))
            r += 2
            self.wiki_zeilen += self._feld(f, r, "check_site", _("Cross-check:"), _(
                "Optional: page prefix of a second source where Claude checks the entries, e.g. "
                "https://example.org/wiki/ (empty = no cross-check)"))
            r += 2
        self._feld(f, r, "buecher", _("Books:"), _("Parts of title, series or author, separated by commas. Only "
                                                   "words looked up in these books count as missing (in addition "
                                                   "to the searched books). Empty = all."))
        r += 2
        ttk.Label(f, text=_("Spoilers (Claude):")).grid(row=r, column=0, sticky="w", pady=2)
        z = ttk.Frame(f)
        z.grid(row=r, column=1, sticky="w")
        for wert, text in SPOILER:
            ttk.Radiobutton(z, text=text, value=wert, variable=self.v["spoilers"]).pack(side="left", padx=(0, 10))
        r += 1
        if wb is not None and wb.art in ("wiki", "leer"):
            ttk.Button(f, text=_("Take changes from a StarDict folder …"),
                       command=lambda: (self.destroy(), bereich.aus_stardict_uebernehmen())).grid(
                row=r, column=1, sticky="w", pady=(10, 0))
            r += 1
        unten = ttk.Frame(self, padding=(14, 0, 14, 12))
        unten.pack(fill="x")
        ttk.Button(unten, text=_("Cancel"), command=self.destroy).pack(side="right")
        ttk.Button(unten, text=_("Create") if neu else _("OK"), command=self.ok).pack(side="right", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())
        self._art()
        self.update_idletasks()                  # sonst ist reqheight noch der Anfangswert (200)
        self.geometry(f"{max(780, self.winfo_reqwidth())}x{self.winfo_reqheight()}")

    def _feld(self, f, r, schluessel, text, hinweis, knopf=None):
        lab = ttk.Label(f, text=text)
        lab.grid(row=r, column=0, sticky="w", pady=(4, 0))
        e = ttk.Entry(f, textvariable=self.v[schluessel])
        e.grid(row=r, column=1, sticky="ew", pady=(4, 0))
        teile = [lab, e]
        if knopf:
            k = ttk.Button(f, text=_("Choose …"), command=knopf)
            k.grid(row=r, column=2, padx=4, pady=(4, 0))
            teile.append(k)
        h = ttk.Label(f, text=hinweis, style="Hinweis.TLabel", wraplength=600, justify="left")
        h.grid(row=r + 1, column=1, columnspan=2, sticky="w")
        teile.append(h)
        return teile

    def _art(self):
        for w in self.wiki_zeilen:
            (w.grid if self.art.get() == "wiki" else w.grid_remove)()

    def _ordner(self):
        o = filedialog.askdirectory(parent=self, title=_("Working folder for the new dictionary"))
        if o:
            self.v["ordner"].set(o)
            if not self.v["stem"].get():
                self.v["stem"].set(Path(o).name.lower().replace(" ", "-"))

    def ok(self):
        werte = {k: v.get().strip() for k, v in self.v.items()}
        profil = {"name": werte["name"], "topic": werte["topic"], "spoilers": werte["spoilers"],
                  "buecher": [b.strip() for b in werte["buecher"].split(",") if b.strip()]}
        if werte["stem"]:
            profil["stem"] = werte["stem"]
        if self.art.get() == "wiki":
            profil["wiki"] = werte["wiki"].rstrip("/")
            profil["check_site"] = werte["check_site"]
        if self.neu:
            if not werte["ordner"]:
                messagebox.showerror(_("New dictionary"), _("Please choose a working folder."), parent=self)
                return
            if not werte["name"] or not werte["topic"] or (self.art.get() == "wiki" and not werte["wiki"]):
                messagebox.showerror(_("New dictionary"), _("Name, topic and wiki are required.") if self.art.get() == "wiki"
                                     else _("Name and topic are required."), parent=self)
                return
            try:
                wb = kwb.anlegen(werte["ordner"], self.art.get(), profil)
            except Exception as e:
                messagebox.showerror(_("New dictionary"), str(e), parent=self)
                return
            wb.schliessen()
            self.destroy()
            self.bereich.oeffnen(werte["ordner"])
            if self.art.get() == "wiki" or self.art.get() == "leer":
                self.bereich.ansicht.set(ANSICHTEN[3])
                self.bereich.liste_fuellen()
            return
        wb = self.bereich.wb
        if wb.art == "stardict":
            profil.pop("stem", None)
        wb.profil_setzen(profil)
        self.destroy()
        self.bereich.wahl_fuellen()
        self.bereich.liste_fuellen()
        self.app.status.set(_("Properties saved; name and file name apply at the next build.") if wb.art != "stardict"
                            else _("Properties saved."))
