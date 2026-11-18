# -*- coding: utf-8 -*-
"""
keller_streifen.py - Statusstreifen rechts neben einer Liste (Programmliste,
BASIC-Dateiliste, Dateiliste). Je Zeile ein Punkt für den Bearbeitungsstand
(rot/gelb/grün) und ein Warnzeichen; die Auswahlfarbe der Liste läuft über den
Streifen durch, damit die markierte Zeile durchgehend hinterlegt ist.

Funktioniert mit tk.Listbox und ttk.Treeview. status_fn(schluessel) liefert
(stand, warntext); stand ist "rot", "gelb", "gruen" oder None. Der Schlüssel ist
bei der Listbox der Eintragstext, beim Treeview die Item-ID.
"""
import tkinter as tk
from tkinter import ttk

import keller_theme as kth

BREITE = 24
TEXTE = {"rot": "im Editor geändert, noch nicht übernommen bzw. zurückgeschrieben",
         "gelb": "übernommen, noch nicht auf die Diskette gespeichert",
         "gruen": "geändert und gespeichert (seit dem Öffnen)"}


class StatusStreifen:
    def __init__(self, app, liste, eltern, status_fn, name_fn=None):
        self.app = app
        self.liste = liste
        self.status_fn = status_fn
        self.name_fn = name_fn or (lambda k: k)
        self.ist_baum = isinstance(liste, ttk.Treeview)
        c = self.canvas = tk.Canvas(eltern, width=BREITE, highlightthickness=0, borderwidth=0)
        c._feste_farben = True                         # Farben setzt zeichnen()
        c.bind("<Configure>", lambda e: self.zeichnen())
        c.bind("<Motion>", self._hover)
        c.bind("<Button-1>", self._klick)
        for ereignis, schritt in (("<Button-4>", -1), ("<Button-5>", 1)):
            c.bind(ereignis, lambda e, s=schritt: self.liste.yview_scroll(s, "units"))
        c.bind("<MouseWheel>", lambda e: self.liste.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        auswahl = "<<TreeviewSelect>>" if self.ist_baum else "<<ListboxSelect>>"
        liste.bind(auswahl, lambda e: self.zeichnen(), add="+")

    # -- Platz in der Anordnung ----------------------------------------------
    def einpacken(self):
        if not self.canvas.winfo_ismapped():
            self.canvas.pack(side="left", fill="y", after=self.liste)

    def umschalten(self):
        if self.app.status_liste.get():
            self.einpacken()
        else:
            self.canvas.pack_forget()
        self.zeichnen()

    # -- Zeilen der Liste ------------------------------------------------------
    def _zeilen(self):
        """(schlüssel, y oben, höhe, ausgewählt) aller sichtbaren Zeilen."""
        l = self.liste
        if self.ist_baum:
            gewaehlt = set(l.selection())
            for iid in l.get_children():
                box = l.bbox(iid)
                if box:
                    yield iid, box[1], box[3], iid in gewaehlt
        else:
            gewaehlt = set(l.curselection())
            for i in range(l.size()):
                box = l.bbox(i)
                if box:
                    # Listbox: bbox umfasst nur den Text - Zeilenhöhe aus dem Abstand
                    # Der Auswahlbalken der Listbox beginnt um den Rahmen der
                    # Auswahl (selectborderwidth) über dem Text
                    rand = int(l.cget("selectborderwidth") or 0)
                    naechste = l.bbox(i + 1) if i + 1 < l.size() else None
                    hoehe = (naechste[1] - box[1]) if naechste else box[3] + 2 * rand
                    yield l.get(i), box[1] - rand, hoehe, i in gewaehlt

    def _farben(self):
        p = kth.PALETTE["dunkel" if self.app.dark_mode.get() else "hell"]
        if self.ist_baum:
            hinter = ttk.Style().lookup("Treeview", "fieldbackground") or p["feld"]
            for zustand, farbe in ttk.Style().map("Treeview", "background") or []:
                if "selected" in str(zustand):
                    return hinter, farbe
            return hinter, p["auswahl"]
        return self.liste.cget("bg"), self.liste.cget("selectbackground")

    def zeichnen(self):
        c = self.canvas
        c.delete("all")
        try:
            hinter, auswahl = self._farben()
            c.configure(bg=hinter)
            versatz = self.liste.winfo_rooty() - c.winfo_rooty()
        except tk.TclError:
            return
        if not self.app.status_liste.get():
            return
        mf = self.app._mark_farben()
        schrift = kth.schrift(10, fett=True)
        for schluessel, y, h, gewaehlt in self._zeilen():
            y0 = y + versatz
            if gewaehlt:
                c.create_rectangle(0, y0, BREITE, y0 + h, fill=auswahl, outline="")
            stand, warn = self.status_fn(schluessel)
            mitte = y0 + h / 2
            if stand:
                c.create_oval(3, mitte - 4, 11, mitte + 4, fill=mf[stand], outline="")
            if warn:
                c.create_text(18, mitte, text="⚠", fill=mf["warn"], font=schrift)

    # -- Maus ------------------------------------------------------------------
    def _zeile_bei(self, y):
        versatz = self.liste.winfo_rooty() - self.canvas.winfo_rooty()
        for schluessel, oben, h, _ in self._zeilen():
            if oben + versatz <= y < oben + versatz + h:
                return schluessel
        return None

    def _hover(self, e):
        k = self._zeile_bei(e.y)
        if k is None:
            return
        stand, warn = self.status_fn(k)
        teile = [TEXTE[stand]] if stand else []
        if warn:
            teile.append(warn)
        if teile:
            self.app.status.set(f"{self.name_fn(k)}: " + " - ".join(teile))

    def _klick(self, e):
        """Klick auf den Streifen wählt die Zeile aus, wie ein Klick in die Liste."""
        k = self._zeile_bei(e.y)
        if k is None:
            return
        l = self.liste
        if self.ist_baum:
            l.selection_set(k)
        else:
            i = list(l.get(0, tk.END)).index(k)
            l.selection_clear(0, tk.END)
            l.selection_set(i)
            l.event_generate("<<ListboxSelect>>")
