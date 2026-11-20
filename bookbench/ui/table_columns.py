# -*- coding: utf-8 -*-
"""
table_columns.py - Spalten der Bibliothekstabelle (ttk.Treeview): Reihenfolge, Ein-/Ausblenden,
Breiten, Sortierpfeil, Kontextmenü am Kopf.

  Spalten(app, tabelle, spalten, aus)   spalten = [(kennung, Text, Standardbreite)] wie app.SPALTEN,
                    aus = Kennungen, die ohne gemerkte Einstellung ausgeblendet sind (seit 1.3)
  anwenden()        Reihenfolge, sichtbare Spalten und Breiten aus den Einstellungen setzen
  kopf_beschriften() Pfeil ▲/▼ an der Sortierspalte
  menue_fuellen(m, spalte)  Einträge fürs Kontextmenü (spalte = Spalte unter der Maus) bzw.
                    Ansicht > Spalten der Bibliothek (spalte None)
  einpassen()       Breiten der sichtbaren Spalten so verteilen, dass sie das Fenster füllen
  zuruecksetzen()   Standard-Reihenfolge, alle Spalten, Standardbreiten (eingepasst)
  sortieren_erlaubt() False direkt nach dem Verschieben einer Spalte (der Klick zählt nicht)

Einstellungen: "spalten" {kennung: breite}, "spalten_reihe" [sichtbare Kennungen in Reihenfolge]
(None = alle außer `aus` in Standard-Reihenfolge), "sortierung" [kennung, umgekehrt].

Warum keine Spalte "stretch" hat: ttk verteilt freien Platz bzw. fehlenden Platz selbst auf
dehnbare Spalten (Titel war die einzige). Dadurch kam eine schmaler gezogene Titelspalte beim
nächsten Start oder Größenwechsel wieder breit zurück. Ohne stretch gelten genau die gezogenen
Breiten; passt die Tabelle nicht ins Fenster, gibt es einen waagrechten Scrollbalken.
"""
import tkinter as tk

import keller_theme as kth
from bookbench.i18n import _

SCHWELLE = 8            # px Mausweg, ab dem ein Klick auf den Kopf zum Verschieben wird
MINDEST = 40            # px Mindestbreite einer Spalte


class Spalten:
    def __init__(self, app, tabelle, spalten, aus=()):
        self.app, self.t = app, tabelle
        self.spalten = list(spalten)
        self.kennungen = [c for c, __, __ in self.spalten]
        self.grund = [c for c in self.kennungen if c not in aus]     # sichtbar ohne Einstellung
        self.text = {c: t for c, t, __ in self.spalten}
        self.standard = {c: w for c, __, w in self.spalten}
        self._ziehen = None                     # {"spalte", "x0", "aktiv"} beim Ziehen am Kopf
        self._kein_sortieren = False
        self._eingepasst = bool(app.e.get("spalten"))
        self.marke = tk.Frame(tabelle, width=3)           # Einfügestelle beim Ziehen
        self.marke._feste_farben = True                     # Farbe setzt _ziehen_bewegt (Akzent)
        t = tabelle
        t.bind("<ButtonPress-1>", self._druecken, add="+")
        t.bind("<B1-Motion>", self._ziehen_bewegt, add="+")
        t.bind("<ButtonRelease-1>", self._loslassen, add="+")
        t.bind("<Button-3>", self._kontextmenue, add="+")
        t.bind("<Configure>", self._erste_groesse, add="+")

    # ================================================================ Zustand
    def sichtbar(self):
        reihe = self.app.e.get("spalten_reihe")
        if not reihe:
            return list(self.grund)
        erg = [c for c in reihe if c in self.kennungen]
        return erg or list(self.grund)

    def _setzen(self, reihe):
        self.app.e["spalten_reihe"] = None if reihe == self.grund else list(reihe)
        self.t.configure(displaycolumns=reihe)
        self.app.tabellen_streifen.zeichnen()

    def anwenden(self):
        breiten = self.app.e.get("spalten") or {}
        for c in self.kennungen:
            try:
                w = max(MINDEST, int(breiten.get(c, self.standard[c])))
            except (TypeError, ValueError):
                w = self.standard[c]
            self.t.column(c, width=w, minwidth=MINDEST, stretch=False)
        self.t.configure(displaycolumns=self.sichtbar())
        self.kopf_beschriften()

    def breiten(self):
        return {c: self.t.column(c, "width") for c in self.kennungen}

    def kopf_beschriften(self):
        spalte, rueck = self.app.e.get("sortierung") or ["reihe", False]
        for c in self.kennungen:
            pfeil = (" ▼" if rueck else " ▲") if c == spalte else ""
            self.t.heading(c, text=self.text[c] + pfeil)

    # ================================================================ Aktionen
    def umschalten(self, spalte):
        reihe = self.sichtbar()
        if spalte in reihe:
            if len(reihe) == 1:
                return                                   # die letzte bleibt
            reihe.remove(spalte)
        else:
            # an ihrer Standardstelle wieder einfügen: hinter der letzten sichtbaren, die davor steht
            vorher = self.kennungen[:self.kennungen.index(spalte)]
            pos = max((reihe.index(c) + 1 for c in vorher if c in reihe), default=0)
            reihe.insert(pos, spalte)
        self._setzen(reihe)

    def verschieben(self, spalte, ziel):
        """Spalte an Position ziel (0 … Anzahl sichtbarer) der sichtbaren Spalten setzen."""
        reihe = self.sichtbar()
        if spalte not in reihe:
            return
        i = reihe.index(spalte)
        reihe.pop(i)
        if ziel > i:
            ziel -= 1
        reihe.insert(max(0, min(ziel, len(reihe))), spalte)
        self._setzen(reihe)

    def einpassen(self):
        """Sichtbare Spalten im Verhältnis ihrer jetzigen Breiten auf die Fensterbreite bringen."""
        platz = self.t.winfo_width() - 4
        reihe = self.sichtbar()
        jetzt = [self.t.column(c, "width") for c in reihe]
        summe = sum(jetzt)
        if platz < MINDEST * len(reihe) or not summe:
            return
        neu = [max(MINDEST, int(w * platz / summe)) for w in jetzt]
        neu[0] += platz - sum(neu)                       # Rundungsrest in die erste Spalte
        for c, w in zip(reihe, neu):
            self.t.column(c, width=max(MINDEST, w))

    def zuruecksetzen(self):
        self.app.e["spalten"] = {}
        self.app.e["spalten_reihe"] = None
        for c in self.kennungen:
            self.t.column(c, width=self.standard[c])
        self.t.configure(displaycolumns=self.grund)
        self.einpassen()
        self.app.tabellen_streifen.zeichnen()

    def sortieren_erlaubt(self):
        return not self._kein_sortieren

    def _erste_groesse(self, e):
        """Ohne gemerkte Breiten beim ersten Anzeigen einmal einpassen."""
        if not self._eingepasst and e.width > 100:
            self._eingepasst = True
            self.einpassen()

    # ================================================================ Menü
    def menue_fuellen(self, m, spalte=None):
        m.delete(0, "end")
        reihe = self.sichtbar()
        if spalte:
            i = reihe.index(spalte)
            name = self.text[spalte]
            m.add_command(label=_("Sort ascending"), command=lambda: self.app._sortieren(spalte, False))
            m.add_command(label=_("Sort descending"), command=lambda: self.app._sortieren(spalte, True))
            m.add_separator()
            m.add_command(label=_("Move \"{name}\" left").format(name=name), state="normal" if i > 0 else "disabled",
                          command=lambda: self.verschieben(spalte, i - 1))
            m.add_command(label=_("Move \"{name}\" right").format(name=name),
                          state="normal" if i < len(reihe) - 1 else "disabled",
                          command=lambda: self.verschieben(spalte, i + 2))
            m.add_command(label=_("Hide \"{name}\"").format(name=name), state="normal" if len(reihe) > 1 else "disabled",
                          command=lambda: self.umschalten(spalte))
            m.add_separator()
        self._vars = []
        for c in self.kennungen:
            v = tk.BooleanVar(value=c in reihe)
            self._vars.append(v)
            einzig = c in reihe and len(reihe) == 1
            m.add_checkbutton(label=self.text[c], variable=v, state="disabled" if einzig else "normal",
                              command=lambda c=c: self.umschalten(c))
        m.add_separator()
        m.add_command(label=_("Fit columns to the window"), command=self.einpassen)
        m.add_command(label=_("Reset columns"), command=self.zuruecksetzen)

    def _kontextmenue(self, e):
        if self.t.identify_region(e.x, e.y) not in ("heading", "separator"):
            return
        spalte = self._spalte_bei(e.x)
        m = tk.Menu(self.t, tearoff=False)
        self.menue_fuellen(m, spalte)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()
        return "break"

    # ================================================================ Ziehen am Kopf
    def _spalte_bei(self, x):
        """Kennung der sichtbaren Spalte unter x (None außerhalb)."""
        c = self.t.identify_column(x)
        reihe = self.sichtbar()
        try:
            i = int(c.lstrip("#")) - 1
        except ValueError:
            return None
        return reihe[i] if 0 <= i < len(reihe) else None

    def _grenzen(self):
        """x-Positionen (im Widget) der linken Kanten aller sichtbaren Spalten und der rechten
        Kante der letzten, mit dem waagrechten Scrollen verrechnet."""
        reihe = self.sichtbar()
        breiten = [self.t.column(c, "width") for c in reihe]
        versatz = self.t.xview()[0] * sum(breiten)
        erg, x = [], -versatz
        for w in breiten:
            erg.append(x)
            x += w
        return erg + [x]

    def _ziel_bei(self, x):
        """Einfügeposition (0 … n) für die Maus bei x: die nächste Spaltengrenze."""
        grenzen = self._grenzen()
        return min(range(len(grenzen)), key=lambda i: abs(grenzen[i] - x))

    def _druecken(self, e):
        self._ziehen = None
        if self.t.identify_region(e.x, e.y) == "heading":
            spalte = self._spalte_bei(e.x)
            if spalte:
                self._ziehen = {"spalte": spalte, "x0": e.x, "aktiv": False}

    def _ziehen_bewegt(self, e):
        z = self._ziehen
        if not z:
            return
        if not z["aktiv"] and abs(e.x - z["x0"]) < SCHWELLE:
            return
        if not z["aktiv"]:
            z["aktiv"] = True
            self.t.configure(cursor="sb_h_double_arrow")
            modus = "dunkel" if self.app.dark_mode.get() else "hell"
            self.marke.configure(background=kth.PALETTE[modus]["akzent"])
        grenzen = self._grenzen()
        x = grenzen[self._ziel_bei(e.x)]
        self.marke.place(x=max(0, min(int(x) - 1, self.t.winfo_width() - 3)), y=0, relheight=1)
        self.marke.lift()

    def _loslassen(self, e):
        z, self._ziehen = self._ziehen, None
        if not z or not z["aktiv"]:
            return
        self.marke.place_forget()
        self.t.configure(cursor="")
        # ttk ruft den Befehl des Kopfes (Sortieren) per "after 0" auf, wenn auf demselben Kopf
        # losgelassen wird - dieses eine Mal nicht
        self._kein_sortieren = True
        self.t.after(150, lambda: setattr(self, "_kein_sortieren", False))
        self.verschieben(z["spalte"], self._ziel_bei(e.x))
