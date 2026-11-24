# -*- coding: utf-8 -*-
"""
transfer_window.py - Fenster "Auf den E-Reader" der KOReader-Werkbank (seit 1.4-beta6): zeigt, was im
Vorschau-Profil anders ist als auf dem angeschlossenen E-Reader (preview/transfer.py), mit Haken je
Datei bzw. Einstellung, und schreibt das Gewählte nach einer Sicherung auf den E-Reader.

  ☑/☐       übertragen ja/nein (Doppelklick, Leertaste, "An/aus")
  ⚠          Konflikt: auch auf dem E-Reader seit dem Holen geändert - nicht vorausgewählt
  Nie        gewählte Einstellungen nie mehr anbieten (Einstellung rueckweg_nie)
"""
import tkinter as tk
from tkinter import messagebox, ttk

import keller_theme as kth
from bookbench.preview import transfer as ktr
from bookbench.i18n import _, ngettext

STATUS = {"neu": _("new"), "geaendert": _("changed"), "entfernt": _("removed")}


class TransferFenster(tk.Toplevel):
    def __init__(self, bereich):
        app = bereich.app
        super().__init__(app)
        self.bereich, self.app = bereich, app
        self.title(_("To the e-reader"))
        self.geometry("900x560")
        self.transient(app)
        self.eintraege = []
        self.an = {}                              # iid -> bool
        rahmen = ttk.Frame(self, padding=10)
        rahmen.pack(fill="both", expand=True)
        self.kopf = ttk.Label(rahmen, text="", wraplength=860, justify="left")
        self.kopf.pack(anchor="w", fill="x")
        r = app._listenrahmen(rahmen)
        r.pack(fill="both", expand=True, pady=(8, 0))
        self.baum = ttk.Treeview(r, columns=("status", "profil", "geraet"), selectmode="extended")
        for spalte, text, breite in (("#0", _("Item"), 330), ("status", _("Change"), 170),
                                     ("profil", _("Profile"), 170), ("geraet", _("E-reader"), 170)):
            self.baum.heading(spalte, text=text)
            self.baum.column(spalte, width=breite, stretch=spalte == "#0")
        sb = ttk.Scrollbar(r, orient="vertical", command=self.baum.yview)
        self.baum.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.baum.pack(side="left", fill="both", expand=True)
        self.baum.bind("<Double-Button-1>", lambda e: self.umschalten())
        self.baum.bind("<space>", lambda e: self.umschalten())
        z = ttk.Frame(rahmen)
        z.pack(anchor="w", fill="x", pady=(8, 0))
        for text, befehl in ((_("On/off"), self.umschalten), (_("All"), lambda: self.alle(True)),
                             (_("None"), lambda: self.alle(False)), (_("Suggestion"), self.vorschlag),
                             (_("Never offer"), self.nie)):
            ttk.Button(z, text=text, command=befehl).pack(side="left", padx=(0, 4))
        ttk.Button(z, text=_("Cancel"), command=self.destroy).pack(side="right")
        self.knopf = ttk.Button(z, text=_("Transfer"), command=self.uebertragen)
        self.knopf.pack(side="right", padx=(0, 6))
        self.hinweis = ttk.Label(rahmen, text="", style="Hinweis.TLabel", wraplength=860, justify="left")
        self.hinweis.pack(anchor="w", fill="x", pady=(8, 0))
        self.bind("<Escape>", lambda e: self.destroy())
        self.laden()

    def laden(self):
        b = self.bereich
        self.wurzel = self.app.kobo.wurzel
        self.eintraege = ktr.vergleichen(b.profil, self.wurzel, self.app.e.get("rueckweg_nie") or ())
        self.an = {}
        self.baum.delete(*self.baum.get_children())
        gruppen = {}
        for n, e in enumerate(self.eintraege):
            if e["bereich"] not in gruppen:
                gruppen[e["bereich"]] = self.baum.insert("", "end", iid="g:" + e["bereich"],
                                                         text=ktr.bereich_name(e["bereich"]), open=True)
            iid = f"e:{n}"
            self.an[iid] = e["vorschlag"]
            self.baum.insert(gruppen[e["bereich"]], "end", iid=iid)
        self._zeichnen()
        if not ktr.hat_basis(b.profil):
            basis = _("The profile was taken before 1.4-beta6, so Bookbench does not know what was on the e-reader "
                      "then: profile and e-reader are compared directly. Check every item; only areas Bookbench has "
                      "changed are preselected. Taking the profile again fixes this.")
        else:
            basis = _("Shown is what changed in the profile since it was taken from the e-reader. ⚠ = changed on the "
                      "e-reader too since then - not preselected.")
        if not self.eintraege:
            self.kopf.configure(text=_("Nothing to transfer: the profile matches the e-reader.") + "\n" + basis)
        else:
            self.kopf.configure(text=ngettext("{n} difference between the preview profile and the e-reader.",
                                              "{n} differences between the preview profile and the e-reader.",
                                              len(self.eintraege)).format(n=len(self.eintraege)) + "\n" + basis)
        self.hinweis.configure(text=_("Before writing, the KOReader settings of the e-reader are backed up (E-reader "
                                      "area > backups). KOReader reads the files at its next start - eject the "
                                      "e-reader afterwards. Device-specific settings (screen, Wi-Fi, frontlight, "
                                      "paths) are never offered."))

    def _zeichnen(self):
        n = 0
        for iid, an in self.an.items():
            e = self.eintraege[int(iid[2:])]
            status = STATUS[e["status"]] + ("  ⚠ " + _("conflict") if e["konflikt"] else "")
            self.baum.item(iid, text=("☑ " if an else "☐ ") + e["name"], values=(status, e["profil"], e["geraet"]))
            n += an
        self.knopf.configure(text=_("Transfer ({n})").format(n=n), state="normal" if n else "disabled")

    def _gewaehlt(self):
        erg = []
        for iid in self.baum.selection():
            if iid.startswith("g:"):
                erg += list(self.baum.get_children(iid))
            else:
                erg.append(iid)
        return erg

    def umschalten(self):
        ids = self._gewaehlt()
        if not ids:
            return
        neu = not all(self.an[i] for i in ids)
        for i in ids:
            self.an[i] = neu
        self._zeichnen()

    def alle(self, an):
        for i in self.an:
            self.an[i] = an
        self._zeichnen()

    def vorschlag(self):
        for i in self.an:
            self.an[i] = self.eintraege[int(i[2:])]["vorschlag"]
        self._zeichnen()

    def nie(self):
        namen = [self.eintraege[int(i[2:])]["name"] for i in self._gewaehlt()
                 if self.eintraege[int(i[2:])]["art"] == "schluessel"]
        if not namen:
            self.app.status.set(_("\"Never offer\" works for KOReader settings (keys), not for files."))
            return
        liste = list(self.app.e.get("rueckweg_nie") or [])
        self.app.e["rueckweg_nie"] = sorted(set(liste) | set(namen))
        self.laden()

    def uebertragen(self):
        auswahl = [self.eintraege[int(i[2:])] for i, an in self.an.items() if an]
        if not auswahl:
            return
        wurzel = self.app.kobo.wurzel
        if not wurzel or not wurzel.exists():
            messagebox.showwarning(_("To the e-reader"), _("No e-reader connected."), parent=self)
            return
        konflikte = sum(1 for e in auswahl if e["konflikt"])
        frage = ngettext("Write {n} item to the e-reader?", "Write {n} items to the e-reader?", len(auswahl)).format(
            n=len(auswahl))
        if konflikte:
            frage += "\n\n" + ngettext("{n} of them was changed on the e-reader too; that change is lost.",
                                      "{n} of them were changed on the e-reader too; those changes are lost.",
                                      konflikte).format(n=konflikte)
        if not messagebox.askyesno(_("To the e-reader"), frage, parent=self):
            return
        a, k, profil = self.app, self.app.kobo, self.bereich.profil
        ziel, info = k.sicherungsordner(), dict(k.info or {})
        anzahl = int(a.e.get("kobo_sicherungen_anzahl") or 10)

        def arbeit():
            n, sicherung = ktr.uebertragen(profil, wurzel, auswahl, ziel, info, anzahl)
            text = ngettext("{n} item written to the e-reader.", "{n} items written to the e-reader.", n).format(n=n)
            if sicherung:
                text += " " + _("Backup before: {name}.").format(name=sicherung.name)
            return text + " " + _("Eject the e-reader; KOReader reads the changes at its next start.")

        def nachher():
            k.geschrieben = True
            if getattr(k, "anzeigen", None):
                k.anzeigen()
            self.bereich.anzeigen()
        k.geschrieben = True
        a.hintergrund(_("To the e-reader"), arbeit, nachher=nachher)
        self.destroy()

    def farben(self):
        self.configure(bg=kth.PALETTE["dunkel" if self.app.dark_mode.get() else "hell"]["bg"])
