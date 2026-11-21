# -*- coding: utf-8 -*-
"""
panes.py - Bücherlisten in der Breite verstellbar und mit Tooltip für zu lange Namen (seit 1.3-beta4).

  teilen(app, eltern, name, standard)   (links, rechts): waagrechter ttk.Panedwindow in eltern; die
                    gezogene Breite der linken Seite steht in der Einstellung "listenbreiten" {name: px}.
                    Doppelklick auf den Teiler = Standardbreite.
  ListenTipp(listbox, text_fn)   zeigt den ganzen Eintrag unter der Maus, wenn er abgeschnitten ist
                    (text_fn(index) liefert den Text, Standard: der Listeneintrag selbst)
"""
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import keller_theme as kth


def teilen(app, eltern, name, standard):
    p = ttk.Panedwindow(eltern, orient="horizontal")
    p.pack(fill="both", expand=True)
    links = ttk.Frame(p)
    rechts = ttk.Frame(p)
    p.add(links, weight=0)
    p.add(rechts, weight=1)
    p._gesetzt = False

    def gemerkt():
        try:
            return int((app.e.get("listenbreiten") or {}).get(name) or 0) or standard
        except (TypeError, ValueError):
            return standard

    def setzen(e=None):
        if p._gesetzt:
            return
        try:
            breite = p.winfo_width()
            if breite < 300:
                return
            p.sashpos(0, max(140, min(gemerkt(), breite - 300)))
            p._gesetzt = True
        except tk.TclError:
            pass

    def merken(e=None):
        try:
            app.e.setdefault("listenbreiten", {})[name] = int(p.sashpos(0))
        except tk.TclError:
            pass

    def zurueck(e=None):
        (app.e.get("listenbreiten") or {}).pop(name, None)
        p._gesetzt = False
        setzen()

    p.bind("<Configure>", setzen, add="+")
    p.bind("<ButtonRelease-1>", merken, add="+")
    p.bind("<Double-Button-1>", zurueck, add="+")
    links.teiler = p
    return links, rechts


class ListenTipp:
    """Tooltip für Listbox-Einträge, die nicht in die Breite passen."""

    def __init__(self, liste, text_fn=None):
        self.lb = liste
        self.text_fn = text_fn or (lambda i: liste.get(i))
        self._tipp = None
        self._index = None
        liste.bind("<Motion>", self._bewegt, add="+")
        liste.bind("<Leave>", lambda e: self.weg(), add="+")
        liste.bind("<MouseWheel>", lambda e: self.weg(), add="+")
        liste.bind("<Button-4>", lambda e: self.weg(), add="+")
        liste.bind("<Button-5>", lambda e: self.weg(), add="+")

    def _bewegt(self, e):
        lb = self.lb
        if not lb.size():
            return self.weg()
        i = lb.nearest(e.y)
        box = lb.bbox(i)
        if not box or not box[1] <= e.y <= box[1] + box[3]:
            return self.weg()
        if i == self._index and self._tipp is not None:
            return
        text = lb.get(i)
        schrift = tkfont.Font(root=lb, font=lb.cget("font"))
        if schrift.measure(text) + 6 <= lb.winfo_width():
            return self.weg()
        self.zeigen(i, box)

    def zeigen(self, i, box):
        self.weg()
        self._index = i
        lb = self.lb
        top = lb.winfo_toplevel()
        modus = "dunkel" if getattr(top, "dark_mode", None) and top.dark_mode.get() else "hell"
        p = kth.PALETTE[modus]
        t = self._tipp = tk.Label(top, text=self.text_fn(i), bg=p["kopf"], fg=p["fg"], padx=6, pady=2,
                                  relief="solid", borderwidth=1, font=lb.cget("font"), justify="left")
        t._feste_farben = True
        # unter die Zeile, nicht über die Maus (sonst verlässt sie die Liste und der Tipp verschwindet)
        x = lb.winfo_rootx() - top.winfo_rootx() + box[0] + 8
        y = lb.winfo_rooty() - top.winfo_rooty() + box[1] + box[3] + 2
        t.place(x=x, y=y)
        t.lift()

    def weg(self):
        self._index = None
        if self._tipp is not None:
            try:
                self._tipp.destroy()
            except tk.TclError:
                pass
            self._tipp = None
