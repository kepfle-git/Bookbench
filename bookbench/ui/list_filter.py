# -*- coding: utf-8 -*-
"""
list_filter.py - Such- und Filterzeile über den schmalen Bücherlisten (Kapitel, Klappentexte,
Cover, Vorschau).

  ListenFilter(eltern, filter, geaendert, kopf)
      Zeile "Suchen: [Feld] ✕", darunter (bei mehr als einem Filter) die Filterauswahl.
      filter = [(kennung, N_("Text"), prüfung)], der erste ist "alle" (prüfung None).
      geaendert() wird nach jeder Änderung von Suche oder Filter aufgerufen, kopf ist das
      Label "Bücher:" darüber - es zeigt bei aktivem Filter "Bücher: 3 von 12".
  passt(b)        Buch passt zu Suche (Titel, Reihe, Autor) und Filter
  zuruecksetzen() Suche leeren, Filter auf "alle" (ruft geaendert() einmal)
  nachfolger(...) welches Buch nach dem Filtern gewählt sein soll

Die Filter selbst stehen bei den Bereichen (app.py, area_covers.py), weil sie deren Logik
brauchen (Warnungen, fehlendes Cover usw.).
"""
import tkinter as tk
from tkinter import ttk

from bookbench.i18n import _


def such_passt(b, such):
    """Suchtext (schon casefold) in Titel, Reihe oder Autor - wie die Suche der Bibliothek."""
    return not such or such in " ".join((b.titel or "", b.reihe or "", b.autor or "")).casefold()


def nachfolger(sortiert, vorher, passt):
    """Buch, das nach dem Filtern gewählt sein soll: das bisherige, wenn es noch passt, sonst
    das nächste passende darunter, sonst das nächste darüber. Übernehmen allein füllt die
    Liste nicht neu (das Buch bleibt stehen, solange man daran arbeitet); erst ein Wechsel von
    Suche/Filter oder Neu einlesen/Alle übernehmen lässt es herausfallen."""
    if vorher is None:
        return None
    if passt(vorher):
        return vorher
    schl = [b.schluessel for b in sortiert]
    if vorher.schluessel not in schl:
        return None
    i = schl.index(vorher.schluessel)
    for b in sortiert[i + 1:]:
        if passt(b):
            return b
    for b in reversed(sortiert[:i]):
        if passt(b):
            return b
    return None


class ListenFilter:
    def __init__(self, eltern, filter, geaendert, kopf=None):
        self.filter = list(filter)
        self.geaendert = geaendert
        self.kopf = kopf
        self._kopf_text = kopf.cget("text") if kopf is not None else ""
        self._still = False
        self.such = tk.StringVar()
        self.wahl = tk.StringVar(value=_(self.filter[0][1]))

        r = self.rahmen = ttk.Frame(eltern)
        r.pack(fill="x", pady=(0, 4))
        zeile = ttk.Frame(r)
        zeile.pack(fill="x")
        ttk.Label(zeile, text=_("Search:")).pack(side="left")
        self.feld = ttk.Entry(zeile, textvariable=self.such, width=8)
        self.feld.pack(side="left", fill="x", expand=True, padx=(4, 2))
        # schmaler Knopf in Höhe des Suchfelds (TButton hat 8/3 px Innenabstand); erbt sonst alles
        ttk.Style(eltern).configure("Leeren.TButton", padding=(3, 0))
        self.leeren = ttk.Button(zeile, text="✕", width=2, style="Leeren.TButton", command=self.zuruecksetzen,
                                 state="disabled")
        self.leeren.pack(side="left", fill="y")
        self.feld.bind("<Escape>", lambda e: (self.such.set(""), "break")[1])
        self.such.trace_add("write", lambda *a: self._melden())
        self.auswahl = None
        if len(self.filter) > 1:
            self.auswahl = ttk.Combobox(r, textvariable=self.wahl, state="readonly", width=8,
                                        values=[_(text) for __, text, __ in self.filter])
            self.auswahl.pack(fill="x", pady=(4, 0))
            self.auswahl.bind("<<ComboboxSelected>>", lambda e: self._melden())

    # ---------------------------------------------------------------- Zustand
    def kennung(self):
        texte = [_(text) for __, text, __ in self.filter]
        w = self.wahl.get()
        return self.filter[texte.index(w)][0] if w in texte else self.filter[0][0]

    def setzen(self, kennung=None, such=None):
        """Filter (Kennung) und/oder Suchtext setzen, geaendert() einmal."""
        self._still = True
        try:
            if kennung is not None:
                self.wahl.set(next(_(t) for k, t, __ in self.filter if k == kennung))
            if such is not None:
                self.such.set(such)
        finally:
            self._still = False
        self._melden()

    def aktiv(self):
        return bool(self.such.get().strip()) or self.kennung() != self.filter[0][0]

    def passt(self, b):
        if not such_passt(b, self.such.get().strip().casefold()):
            return False
        pruefung = next(p for k, __, p in self.filter if k == self.kennung())
        return pruefung is None or bool(pruefung(b))

    def zuruecksetzen(self):
        if self.aktiv():
            self.setzen(self.filter[0][0], "")

    def anzahl(self, n, gesamt):
        """Kopfzeile "Bücher:" bzw. "Bücher: 3 von 12" bei aktivem Filter."""
        if self.kopf is None:
            return
        if self.aktiv():
            self.kopf.configure(text=_("Books: {n} of {gesamt}").format(n=n, gesamt=gesamt))
        else:
            self.kopf.configure(text=self._kopf_text)

    def fokus(self):
        self.feld.focus_set()
        self.feld.select_range(0, "end")

    def _melden(self):
        if self._still:
            return
        self.leeren.configure(state="normal" if self.aktiv() else "disabled")
        self.geaendert()
