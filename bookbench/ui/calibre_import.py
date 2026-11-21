# -*- coding: utf-8 -*-
"""
calibre_import.py (ui) - Fenster für den einmaligen Import aus einer Calibre-Bibliothek (seit 1.3-beta4).
Die Logik steht in core/calibre_import.py.

  ImportDialog(app)
      oben: Calibre-Bibliothek (Ordner mit metadata.db, gemerkt als "calibre_bibliothek"), Einlesen
      Reiter "Änderungen": Tabelle Buch | Feld | Im Buch | Aus Calibre, Haken je Zeile (Klick, Leertaste);
          Auswahl "Alle Abweichungen" / "Nur leere Felder", Haken "Klappentexte (Beschreibung)"
      Reiter "Nicht zugeordnet": Bücher des Ordners ohne passenden Calibre-Eintrag
      eigene Spalten aus Calibre, die noch kein eigenes Feld sind: "Als eigene Felder übernehmen"
      Übernehmen: angehakte Werte wie überall übernommen (gelb), gespeichert wird mit Strg+S

Zuordnung über UUID, ISBN oder Titel + erster Autor (nur eindeutige Treffer).
"""
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from bookbench.core import calibre_import as kci
from bookbench.i18n import _, ngettext

AN, AUS = "☑", "☐"


def standard_ordner():
    for name in ("Calibre Library", "Calibre-Bibliothek", "Calibre Bibliothek", "Calibre-Library"):
        p = Path.home() / name
        if (p / "metadata.db").is_file():
            return str(p)
    return ""


class ImportDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title(_("Import from a Calibre library"))
        self.transient(app)
        self.geometry("980x620")
        self.eintraege, self.spalten, self.zuordnung, self.ohne = [], {}, {}, []
        self.zeilen = {}                       # iid -> (buch, feld, neu)
        self.haken = {}                        # iid -> bool

        oben = ttk.Frame(self, padding=(10, 10, 10, 4))
        oben.pack(fill="x")
        ttk.Label(oben, text=_("Calibre library:")).pack(side="left")
        self.ordner = tk.StringVar(value=app.e.get("calibre_bibliothek") or standard_ordner())
        ttk.Entry(oben, textvariable=self.ordner, width=50).pack(side="left", padx=4, fill="x", expand=True)
        ttk.Button(oben, text=_("Browse …"), command=self.waehlen).pack(side="left", padx=(0, 4))
        ttk.Button(oben, text=_("Read"), command=self.einlesen).pack(side="left")

        wahl = ttk.Frame(self, padding=(10, 0, 10, 4))
        wahl.pack(fill="x")
        self.modus = tk.StringVar(value="alle")
        ttk.Radiobutton(wahl, text=_("All differences"), value="alle", variable=self.modus,
                        command=self.zeigen).pack(side="left")
        ttk.Radiobutton(wahl, text=_("Only empty fields"), value="leer", variable=self.modus,
                        command=self.zeigen).pack(side="left", padx=(10, 0))
        self.mit_kt = tk.BooleanVar(value=True)
        ttk.Checkbutton(wahl, text=_("Blurbs (Calibre's description)"), variable=self.mit_kt,
                        command=self.zeigen).pack(side="left", padx=(16, 0))
        self.zusammenfassung = ttk.Label(self, text=_("Choose the folder of your Calibre library (the one with "
                                                       "metadata.db) and click Read."),
                                         style="Hinweis.TLabel", padding=(10, 0, 10, 4), justify="left")
        self.zusammenfassung.pack(fill="x")
        self.zusammenfassung.bind("<Configure>", lambda e: self.zusammenfassung.configure(wraplength=e.width - 20))

        self.spalten_zeile = ttk.Frame(self, padding=(10, 0, 10, 4))
        ttk.Button(self.spalten_zeile, text=_("Add as own fields"), command=self.spalten_uebernehmen).pack(
            side="right", padx=(8, 0))
        self.spalten_text = ttk.Label(self.spalten_zeile, text="", justify="left")
        self.spalten_text.pack(side="left", fill="x", expand=True)
        self.spalten_text.bind("<Configure>", lambda e: self.spalten_text.configure(wraplength=e.width - 4))

        unten = ttk.Frame(self, padding=10)
        unten.pack(side="bottom", fill="x")
        ttk.Button(unten, text=_("Close"), command=self.destroy).pack(side="right")
        self.ok = ttk.Button(unten, text=_("Apply ticked"), command=self.uebernehmen, state="disabled")
        self.ok.pack(side="right", padx=(0, 6))
        ttk.Button(unten, text=_("Tick all"), command=lambda: self.alle(True)).pack(side="left")
        ttk.Button(unten, text=_("Untick all"), command=lambda: self.alle(False)).pack(side="left", padx=(6, 0))

        nb = self.nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10)
        s1 = ttk.Frame(nb)
        nb.add(s1, text=_("Changes"))
        self.tabelle = self._tabelle(s1, (("buch", _("Book"), 240), ("feld", _("Field"), 120),
                                          ("jetzt", _("In the book"), 250), ("neu", _("From Calibre"), 250)))
        self.tabelle.configure(show="tree headings")
        self.tabelle.column("#0", width=34, stretch=False, anchor="center")
        self.tabelle.bind("<Button-1>", self._klick, add="+")
        self.tabelle.bind("<space>", lambda e: self._umschalten(self.tabelle.selection()))
        s2 = ttk.Frame(nb)
        nb.add(s2, text=_("Not matched"))
        self.ohne_tabelle = self._tabelle(s2, (("buch", _("Book"), 420), ("datei", _("File"), 420)))
        self.bind("<Escape>", lambda e: self.destroy())
        if self.ordner.get() and kci.finden(self.ordner.get()):
            self.after(50, self.einlesen)

    def _tabelle(self, eltern, spalten):
        r = self.app._listenrahmen(eltern)
        r.pack(fill="both", expand=True, pady=(4, 0))
        t = ttk.Treeview(r, columns=[c for c, __, __ in spalten], show="headings", selectmode="extended")
        for c, text, w in spalten:
            t.heading(c, text=text, anchor="w")
            t.column(c, width=w, stretch=True)
        sb = ttk.Scrollbar(r, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        return t

    # ================================================================ Einlesen
    def waehlen(self):
        o = filedialog.askdirectory(parent=self, title=_("Calibre library"), initialdir=self.ordner.get() or None)
        if o:
            self.ordner.set(o)
            self.einlesen()

    def einlesen(self):
        db = kci.finden(self.ordner.get())
        if not db:
            self.zusammenfassung.configure(text=_("No metadata.db in this folder. Choose the folder of your Calibre "
                                                  "library (Calibre: right-click the library button > Show folder)."))
            return
        try:
            self.eintraege, self.spalten = kci.lesen(db)
        except Exception as fehler:            # beschädigte oder fremde Datenbank
            self.zusammenfassung.configure(text=_("Could not read the Calibre library: {fehler}").format(fehler=fehler))
            return
        self.app.e["calibre_bibliothek"] = str(db.parent)
        self.zuordnung, self.ohne = kci.zuordnen(self.app.buecher, self.eintraege)
        self.zeigen()

    def _felder(self):
        return self.app.metadaten.felder()

    def zeigen(self):
        t = self.tabelle
        t.delete(*t.get_children())
        self.zeilen, self.haken = {}, {}
        nach = {b.schluessel: b for b in self.app.buecher}
        nur_leere = self.modus.get() == "leer"
        n = 0
        for schl, (e, __) in sorted(self.zuordnung.items(), key=lambda x: nach[x[0]].titel.casefold()):
            b = nach[schl]
            werte = self.app.metadaten.aktuell(b)
            zeilen = kci.vorschlaege(werte, e, self._felder(), nur_leere)
            if self.mit_kt.get() and e["beschreibung"]:
                jetzt = self.app.metadaten.klappentext.aktueller_text(b).strip()
                if e["beschreibung"].strip() != jetzt and (not nur_leere or not jetzt):
                    zeilen.append(("klappentext", jetzt, e["beschreibung"].strip()))
            for feld, jetzt, neu in zeilen:
                n += 1
                iid = f"z{n}"
                self.zeilen[iid] = (b, feld, neu)
                self.haken[iid] = True
                name = _("Blurb") if feld == "klappentext" else self.app.metadaten.name(feld)
                t.insert("", "end", iid=iid, text=AN,
                         values=(b.name, name, kurz(jetzt) or "–", kurz(neu)))
        o = self.ohne_tabelle
        o.delete(*o.get_children())
        for b in self.ohne:
            o.insert("", "end", values=(b.name, b.pfad.name))
        arten = {}
        for __, art in self.zuordnung.values():
            arten[art] = arten.get(art, 0) + 1
        self.zusammenfassung.configure(text=_(
            "{n} books in Calibre. Matched: {z} of {buecher} books in the folder (UUID {u}, ISBN {i}, title and "
            "author {t}), not matched: {o}. {aenderungen}").format(
            n=len(self.eintraege), z=len(self.zuordnung), buecher=len([b for b in self.app.buecher if not b.fehler]),
            u=arten.get("uuid", 0), i=arten.get("isbn", 0), t=arten.get("titel", 0), o=len(self.ohne),
            aenderungen=ngettext("{n} change to take over.", "{n} changes to take over.", n).format(n=n)))
        self.nb.tab(1, text=_("Not matched ({n})").format(n=len(self.ohne)))
        neu = [k for k in self.spalten if k not in self._felder()]
        if neu:
            namen = ", ".join(f"{self.spalten[k].get('name') or k} ({k})" for k in neu)
            self.spalten_text.configure(text=_("Own columns in Calibre that are not fields yet: {namen}").format(namen=namen))
            self.spalten_zeile.pack(fill="x", after=self.zusammenfassung)
        else:
            self.spalten_zeile.pack_forget()
        self.ok.configure(state="normal" if n else "disabled")

    # ================================================================ Haken
    def _klick(self, e):
        if self.tabelle.identify_column(e.x) == "#0":
            iid = self.tabelle.identify_row(e.y)
            if iid:
                self._umschalten((iid,))
                return "break"

    def _umschalten(self, iids):
        for iid in iids:
            if iid in self.haken:
                self.haken[iid] = not self.haken[iid]
                self.tabelle.item(iid, text=AN if self.haken[iid] else AUS)

    def alle(self, an):
        for iid in self.haken:
            self.haken[iid] = an
            self.tabelle.item(iid, text=AN if an else AUS)

    def spalten_uebernehmen(self):
        """Eigene Calibre-Spalten als eigene Felder dazunehmen (Einstellung meta_spalten)."""
        e = self.app.e
        liste = [list(x) for x in e.get("meta_spalten") or []]
        for k, fm in self.spalten.items():
            if k not in {x[0] for x in liste}:
                liste.append([k, fm.get("name") or k])
        e["meta_spalten"] = liste
        self.app.metadaten.felder_bauen()
        self.app.metadaten.anzeigen()
        self.zeigen()

    # ================================================================ Übernehmen
    def uebernehmen(self):
        je_buch = {}
        for iid, (b, feld, neu) in self.zeilen.items():
            if self.haken.get(iid):
                je_buch.setdefault(b.schluessel, (b, {}))[1][feld] = neu
        m = self.app.metadaten
        for b, felder in je_buch.values():
            kt = felder.pop("klappentext", None)
            if felder:
                werte = m.basis(b)
                werte.update(felder)
                # eigene Spalten, die das Buch noch nicht hat: Definition aus Calibre fürs Speichern mitgeben
                for k in felder:
                    if k.startswith("#") and k in self.spalten:
                        b.meta_defs_import[k] = self.spalten[k]
                m.uebernehmen(b, werte, mit_klappentext=False)
            if kt is not None:
                b.klappentext_entwurf = None
                b.klappentext_neu = kt
                b.klappentext_quelle = "Calibre"
            self.app._geaendert(b)
        m.anzeigen()
        self.app.status.set(ngettext("Calibre import: {n} book changed, not yet saved (Ctrl+S).",
                                     "Calibre import: {n} books changed, not yet saved (Ctrl+S).", len(je_buch))
                            .format(n=len(je_buch)))
        self.zeigen()


def kurz(text, n=120):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"

