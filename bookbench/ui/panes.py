# -*- coding: utf-8 -*-
"""
panes.py - Bücherlisten in der Breite verstellbar und mit Tooltip für zu lange Namen (seit 1.3-beta4).

  teilen(app, eltern, name, standard)   (links, rechts): waagrechter ttk.Panedwindow in eltern; die
                    gezogene Breite der linken Seite steht in der Einstellung "listenbreiten" {name: px}.
                    Doppelklick auf den Teiler = Standardbreite. fest="rechts": die rechte Seite hat
                    die gemerkte Breite (Cover-Tafel im Bereich Metadaten).
  ListenTipp(listbox, text_fn)   zeigt den ganzen Eintrag unter der Maus, wenn er abgeschnitten ist
                    (text_fn(index) liefert den Text, Standard: der Listeneintrag selbst)
  RollFlaeche(eltern)   Rahmen mit senkrechtem Scrollbalken (nur bei Bedarf) und Mausrad; Inhalt in
                    .innen packen (seit 1.4-beta2, Plugin-Seiten der Werkbank)
"""
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import keller_theme as kth


def teilen(app, eltern, name, standard, fest="links", minimum=140):
    """fest="rechts": die rechte Seite hat die gemerkte Breite (z. B. die Cover-Tafel, seit 1.3-beta5),
    die linke bekommt den Rest; die feste Seite wird nie schmaler als minimum."""
    p = ttk.Panedwindow(eltern, orient="horizontal")
    p.pack(fill="both", expand=True)
    links = ttk.Frame(p)
    rechts = ttk.Frame(p)
    p.add(links, weight=0 if fest == "links" else 1)
    p.add(rechts, weight=1 if fest == "links" else 0)
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
            if breite < 300 + minimum:
                return
            w = max(minimum, min(gemerkt(), breite - 300))
            p.sashpos(0, w if fest == "links" else breite - w)
            p._gesetzt = True
        except tk.TclError:
            pass

    def merken(e=None):
        try:
            pos = int(p.sashpos(0))
            app.e.setdefault("listenbreiten", {})[name] = pos if fest == "links" else p.winfo_width() - pos
        except tk.TclError:
            pass

    def zurueck(e=None):
        (app.e.get("listenbreiten") or {}).pop(name, None)
        p._gesetzt = False
        setzen()

    p.bind("<Configure>", setzen, add="+")
    p.bind("<ButtonRelease-1>", merken, add="+")
    p.bind("<Double-Button-1>", zurueck, add="+")
    links.teiler = rechts.teiler = p
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


class RollFlaeche(ttk.Frame):
    """Senkrecht scrollbarer Rahmen: Inhalt in self.innen. Das Mausrad scrollt, solange die Maus
    darüber ist; der Scrollbalken erscheint nur, wenn der Inhalt nicht passt."""

    def __init__(self, eltern, **k):
        super().__init__(eltern, **k)
        self.flaeche = tk.Canvas(self, highlightthickness=0, borderwidth=0, height=1, width=1)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.flaeche.yview)
        self.flaeche.configure(yscrollcommand=self._scroll)
        self.flaeche.pack(side="left", fill="both", expand=True)
        self.innen = ttk.Frame(self.flaeche)
        self._fenster = self.flaeche.create_window(0, 0, window=self.innen, anchor="nw")
        self.innen.bind("<Configure>", lambda e: self._groesse())
        self.flaeche.bind("<Configure>", lambda e: self._groesse())
        for w in (self.flaeche, self.innen):
            w.bind("<Enter>", lambda e: self._rad(True), add="+")
            w.bind("<Leave>", lambda e: self._rad(False), add="+")

    def farbe(self, bg):
        self.flaeche.configure(bg=bg)

    def _groesse(self):
        f = self.flaeche
        f.itemconfigure(self._fenster, width=f.winfo_width())
        f.configure(scrollregion=(0, 0, f.winfo_width(), self.innen.winfo_reqheight()))

    def _scroll(self, a, b):
        self.sb.set(a, b)
        if float(a) <= 0.0 and float(b) >= 1.0:
            self.sb.pack_forget()
        elif not self.sb.winfo_ismapped():
            self.sb.pack(side="right", fill="y", before=self.flaeche)

    def nach_oben(self):
        self.flaeche.yview_moveto(0)

    def _rad(self, an):
        f = self.flaeche
        if not an:
            try:
                w = f.winfo_containing(*f.winfo_pointerxy())
            except (tk.TclError, KeyError):
                w = None
            if w is not None and str(w).startswith(str(f)):
                return
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                f.unbind_all(ev)
            return

        def rollen(schritte):
            if self.sb.winfo_ismapped():
                f.yview_scroll(schritte, "units")
        f.bind_all("<MouseWheel>", lambda e: rollen(-1 if e.delta > 0 else 1))
        f.bind_all("<Button-4>", lambda e: rollen(-1))
        f.bind_all("<Button-5>", lambda e: rollen(1))
