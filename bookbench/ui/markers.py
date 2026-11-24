# -*- coding: utf-8 -*-
"""
markers.py - Marken: kleine Piktogramme statt ⚠ (seit 1.3-beta3), in der Seitenleiste je Bereich mit
Anzahl, in den Bücherlisten je Buch. Weicht bewusst vom Keller-Designleitfaden ab (dort ein ⚠);
keller_navigation und keller_streifen bleiben unverändert, hier stehen nur Unterklassen.

  ARTEN            {kennung: (Stufe, Text für eine Zahl)}; Piktogramme in icons.MARKEN
  farbe(stufe, dunkel, app)   Farbe einer Stufe: fehler rot, pruefen orange, fehlt grau, info Akzent,
                   offen gelb (wie der Punkt für "übernommen, nicht gespeichert")
  bild(kennung, farbe, w)     tk.PhotoImage, eingefärbt und zwischengespeichert
  MarkenStreifen   keller_streifen.StatusStreifen mit Piktogrammen statt ⚠; marken_fn(schlüssel)
                   liefert [(kennung, text)]. Die Breite richtet sich nach dem Buch mit den meisten.
  MarkenNavigation keller_navigation.Navigation; liest seite.nav_marken = [(kennung, anzahl)] und zeichnet
                   rechts je Marke Piktogramm und Zahl; die Leiste wird so breit wie nötig, bis MAX_BREIT -
                   passt eine Zeile dann nicht, stehen die Marken in einer zweiten Zeile (seit 1.3-beta4).
  status_bild(w, stand, kennungen, app)   ein Bild aus Punkt und Piktogrammen (Statusspalte der Bibliothek)
  TabellenStatus   Statusspalte einer ttk.Treeview (Spalte #0 mit diesen Bildern) statt Streifen daneben:
                   ein-/ausblendbar, in der Breite ziehbar, sortierbar (seit 1.3-beta4)
  sichtbar(e, ort, kennung)   Einstellung "marken_aus" {ort: [kennungen]}: je Ort (ORTE) abschaltbar
                   (seit 1.3-beta5). Abgeschaltete Marken fehlen nur in der Anzeige; Filter und Sortieren
                   nach Status zählen sie weiter.
"""
import tkinter as tk
import tkinter.font as tkfont

import keller_navigation as knv
import keller_streifen as kst
import keller_theme as kth
from bookbench.i18n import N_, _
from bookbench.ui import icons as ksy

PRUEFEN = {"hell": "#d9822b", "dunkel": "#f0a548"}
MAX_BREIT = 250          # px; breiter wird die Seitenleiste nicht, dann zweizeilig
ORDNUNG = ("unlesbar", "kapitel", "vorschlag", "klappentext", "cover", "cover_klein", "calibre", "angaben",
           "woerterbuch", "ereader", "ungespeichert", "verbunden")
# Stufe, (Einzahl, Mehrzahl) für die Seitenleiste
ARTEN = {
    "unlesbar": ("fehler", (N_("{n} book cannot be read"), N_("{n} books cannot be read"))),
    "kapitel": ("pruefen", (N_("{n} book with questionable chapter names"), N_("{n} books with questionable chapter names"))),
    "vorschlag": ("info", (N_("{n} book with chapter suggestions"), N_("{n} books with chapter suggestions"))),
    "klappentext": ("fehlt", (N_("{n} book without blurb"), N_("{n} books without blurb"))),
    "cover": ("fehlt", (N_("{n} book without cover"), N_("{n} books without cover"))),
    "cover_klein": ("pruefen", (N_("{n} small cover"), N_("{n} small covers"))),
    "calibre": ("pruefen", (N_("{n} book differs from Calibre"), N_("{n} books differ from Calibre"))),
    "angaben": ("pruefen", (N_("{n} book with missing or invalid data (language, ISBN)"),
                            N_("{n} books with missing or invalid data (language, ISBN)"))),
    "woerterbuch": ("pruefen", (N_("{n} word looked up without result"), N_("{n} words looked up without result"))),
    "ereader": ("pruefen", (N_("{n} dictionary missing or outdated on the e-reader"),
                            N_("{n} dictionaries missing or outdated on the e-reader"))),
    "ungespeichert": ("offen", (N_("{n} book with unsaved changes"), N_("{n} books with unsaved changes"))),
    "verbunden": ("info", (N_("connected"), N_("connected"))),
}
# Orte, an denen Marken stehen (Einstellungen > Oberfläche > Status-Piktogramme)
ORTE = (("seitenleiste", N_("Sidebar")), ("listen", N_("Book lists")), ("tabelle", N_("Library")))
NUR_SEITENLEISTE = {"woerterbuch", "ereader", "verbunden"}      # gibt es nur in der Seitenleiste
NAMEN = {
    "unlesbar": N_("Book cannot be read"), "kapitel": N_("Questionable chapter names"),
    "vorschlag": N_("Chapter suggestions"), "klappentext": N_("No blurb"), "cover": N_("No cover"),
    "cover_klein": N_("Small cover"), "calibre": N_("Differs from Calibre"),
    "angaben": N_("Language or ISBN missing/invalid"), "woerterbuch": N_("Words without result"),
    "ereader": N_("Dictionaries on the e-reader"), "ungespeichert": N_("Unsaved changes"),
    "verbunden": N_("E-reader connected"),
}
_BILDER = {}


def sichtbar(e, ort, kennung):
    """False, wenn die Marke an diesem Ort abgeschaltet ist (Einstellung marken_aus)."""
    aus = (e or {}).get("marken_aus") or {}
    return kennung not in (aus.get(ort) or [])


def gefiltert(e, ort, marken):
    """[(kennung, text)] ohne die an diesem Ort abgeschalteten Marken."""
    return [m for m in marken if sichtbar(e, ort, m[0])]


def farbe(stufe, dunkel, app=None):
    modus = "dunkel" if dunkel else "hell"
    p = kth.PALETTE[modus]
    if stufe == "fehler":
        return knv.WARN[modus]
    if stufe == "pruefen":
        return PRUEFEN[modus]
    if stufe == "offen":
        return app._mark_farben()["gelb"] if app else "#e8a317"
    if stufe == "info":
        return p["akzent"]
    return p["hinweis"]


def bild(kennung, f, w):
    """Piktogramm in Farbe f; w: ein Widget des Fensters (Bilder gehören zu einem Tk-Interpreter -
    nach einem Neustart der Oberfläche, z. B. beim Sprachwechsel, gibt es neue)."""
    schl = (kennung, f, id(w.tk))
    if schl not in _BILDER:
        _BILDER[schl] = tk.PhotoImage(master=w, data=knv._gefaerbt(ksy.MARKEN[kennung], f))
    return _BILDER[schl]


def status_bild(w, stand, kennungen, app):
    """Bild für die Statusspalte: Punkt für den Stand (oder Lücke), daneben die Piktogramme."""
    dunkel = app.dark_mode.get()
    schl = ("status", stand, tuple(kennungen), dunkel, id(w.tk))
    if schl in _BILDER:
        return _BILDER[schl]
    breite = 16 + 16 * len(kennungen)
    img = tk.PhotoImage(master=w, width=breite, height=16)
    if stand:
        punkt = bild("punkt", app._mark_farben()[stand], w)
        img.tk.call(img, "copy", punkt, "-to", 1, 1)
    for i, k in enumerate(kennungen):
        if k in ksy.MARKEN:
            img.tk.call(img, "copy", bild(k, farbe(ARTEN[k][0], dunkel, app), w), "-to", 17 + 16 * i, 1)
    _BILDER[schl] = img
    return img


def text(kennung, anzahl):
    """Tooltip-Text einer Marke mit Anzahl."""
    ein, mehr = ARTEN[kennung][1]
    return _(ein if anzahl == 1 else mehr).format(n=anzahl)       # Deutsch und Englisch: 1 / sonst


def sortiert(marken):
    return sorted(marken, key=lambda m: ORDNUNG.index(m[0]) if m[0] in ORDNUNG else 99)


class MarkenStreifen(kst.StatusStreifen):
    """Statusstreifen mit Piktogrammen: Punkt für den Stand, daneben je Marke ein Piktogramm."""
    SCHRITT = 16

    def __init__(self, app, liste, eltern, status_fn, marken_fn, name_fn=None, alle_fn=None, bei_breite=None):
        """alle_fn() = alle Schlüssel (nicht nur die sichtbaren Zeilen): die Breite richtet sich danach und
        springt beim Blättern nicht; bei_breite() wird nach einer Änderung der Breite aufgerufen."""
        super().__init__(app, liste, eltern, status_fn, name_fn)
        self._marken_fn = marken_fn
        self.alle_fn = alle_fn
        self.bei_breite = bei_breite

    def marken_fn(self, schluessel):
        return gefiltert(self.app.e, "listen", self._marken_fn(schluessel))

    def einpacken(self):
        """Vor der Liste einpacken (rechts, links vom Scrollbalken): so bekommt der Streifen seine Breite
        zuerst, auch wenn die Tabelle breiter ist als das Fenster (keller_streifen packt danach)."""
        if not self.canvas.winfo_ismapped():
            self.canvas.pack(side="right", fill="y", before=self.liste)

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
        dunkel = self.app.dark_mode.get()
        mf = self.app._mark_farben()
        zeilen = list(self._zeilen())
        alle = {k: sortiert(self.marken_fn(k)) for k, __, __, __ in zeilen}
        schluessel = self.alle_fn() if self.alle_fn else list(alle)
        meiste = max((len(alle[k]) if k in alle else len(self.marken_fn(k)) for k in schluessel), default=0)
        breite = max(kst.BREITE, 16 + self.SCHRITT * meiste)
        if int(c.cget("width")) != breite:
            c.configure(width=breite)
            if self.bei_breite:
                c.after_idle(self.bei_breite)
        for schluessel, y, h, gewaehlt in zeilen:
            y0 = y + versatz
            if gewaehlt:
                c.create_rectangle(0, y0, breite, y0 + h, fill=auswahl, outline="")
            stand, __ = self.status_fn(schluessel)
            mitte = y0 + h / 2
            if stand:
                c.create_oval(3, mitte - 4, 11, mitte + 4, fill=mf[stand], outline="")
            for i, (kennung, __) in enumerate(alle[schluessel]):
                if kennung in ksy.MARKEN:
                    c.create_image(16 + i * self.SCHRITT + 7, mitte, image=bild(kennung, farbe(ARTEN[kennung][0], dunkel, self.app), c))

    def _hover(self, e):
        k = self._zeile_bei(e.y)
        if k is None:
            return
        stand, __ = self.status_fn(k)
        teile = [kst.TEXTE[stand]] if stand else []
        teile += [t for __, t in sortiert(self.marken_fn(k)) if t]
        if teile:
            self.app.status.set(f"{self.name_fn(k)}: " + " - ".join(teile))


class TabellenStatus:
    """Statusspalte einer ttk.Treeview: Spalte #0 (die einzige, die Bilder zeigen kann) mit Punkt und
    Piktogrammen je Zeile. Ersetzt den Streifen neben der Tabelle; Sichtbarkeit und Breite verwalten
    die Spalten der Tabelle (table_columns.Spalten), hier nur Bilder und Hover-Text."""

    def __init__(self, app, tabelle, status_fn, marken_fn, name_fn):
        self.app, self.t = app, tabelle
        self.liste = tabelle                       # wie bei den Streifen (Tests, app._streifen)
        self.status_fn, self._marken_fn, self.name_fn = status_fn, marken_fn, name_fn
        self._stand = {}
        tabelle.bind("<Motion>", self._hover, add="+")

    def marken_fn(self, iid):
        return gefiltert(self.app.e, "tabelle", self._marken_fn(iid))

    def marken(self, iid):
        return [k for k, __ in sortiert(self.marken_fn(iid)) if k in ksy.MARKEN]

    def breite_noetig(self):
        """Breite für das Buch mit den meisten Piktogrammen (mindestens Platz für den Punkt)."""
        meiste = max((len(self.marken(i)) for i in self.t.get_children()), default=0)
        return 26 + 16 * meiste

    def zeichnen(self):
        try:
            for iid in self.t.get_children():
                stand, __ = self.status_fn(iid)
                kennungen = self.marken(iid)
                schl = (stand, tuple(kennungen), self.app.dark_mode.get())
                if self._stand.get(iid) != schl:
                    self._stand[iid] = schl
                    self.t.item(iid, image=status_bild(self.t, stand, kennungen, self.app))
            sp = getattr(self.app, "tabellen_spalten", None)
            if sp is not None:
                sp.status_breite()                 # mehr oder weniger Piktogramme: Breite nachziehen
        except tk.TclError:
            pass

    def vergessen(self):
        """Nach dem Leeren der Tabelle: Bilder beim nächsten Zeichnen neu setzen."""
        self._stand = {}

    # wie ein Streifen behandelt (app._streifen), ohne eigenes Widget
    def einpacken(self):
        pass

    def auspacken(self):
        pass

    def _hover(self, e):
        if self.t.identify_column(e.x) != "#0":
            return
        iid = self.t.identify_row(e.y)
        if not iid:
            return
        stand, __ = self.status_fn(iid)
        teile = [kst.TEXTE[stand]] if stand else []
        teile += [t for __, t in sortiert(self.marken_fn(iid)) if t]
        if teile:
            self.app.status.set(f"{self.name_fn(iid)}: " + " - ".join(teile))


class MarkenNavigation(knv.Navigation):
    """Seitenleiste mit Marken: rechts in der Zeile je Marke Piktogramm und Anzahl, alle, nicht nur eine.
    Eingeklappt zeigt der Punkt die schwerste Stufe. Ohne nav_marken wie keller_navigation (Zähler-Text)."""
    GRUND = knv.BREIT
    SCHWERE = ("fehler", "pruefen", "offen", "fehlt", "info")

    def _mass(self, schrift, text):
        """Breite eines Texts in px (kth.schrift liefert nur eine Schriftangabe)."""
        return tkfont.Font(root=self, font=schrift).measure(text)

    def _marken(self, b):
        e = getattr(self.master, "e", None)
        return sortiert([(k, n) for k, n in getattr(b["widget"], "nav_marken", None) or []
                         if n and k in ARTEN and sichtbar(e, "seitenleiste", k)])

    def _markenbreite(self, marken):
        return sum(14 + 2 + self._mass(self.schrift_klein, str(n) if k != "verbunden" else "") + 7 for k, n in marken)

    def _platz(self, b, marken):
        """(einzeilig_breite, zweizeilig_breite) eines Bereichs mit Marken."""
        name = knv.SCHMAL + self._mass(self.schrift_fett, b["name"]) + 18 + (16 if b["kinder"] else 0)
        mb = self._markenbreite(marken)
        return name + mb, max(name, knv.SCHMAL - 2 + mb + 10)

    def zeichnen(self):
        # Breite nach dem Bereich mit dem meisten Platzbedarf (Name + Marken), höchstens MAX_BREIT;
        # Bereiche, deren Marken dann nicht in die Zeile passen, bekommen eine zweite Zeile.
        # keller_navigation liest BREIT bei jedem Zeichnen aus dem Modul, deshalb dort gesetzt.
        self._zweizeilig = set()
        try:
            noetig = self.GRUND
            for b in self.bereiche():
                marken = self._marken(b)
                if marken:
                    eins, zwei = self._platz(b, marken)
                    if eins <= MAX_BREIT:
                        noetig = max(noetig, eins)
                    else:
                        self._zweizeilig.add(b["id"])
                        noetig = max(noetig, min(zwei, MAX_BREIT))
            knv.BREIT = noetig
        except (AttributeError, tk.TclError):
            pass
        super().zeichnen()

    def _bereich(self, b, tid, kid, seite, eltern=None):
        marken = self._marken(b)
        if not marken:
            if any(n for __, n in getattr(b["widget"], "nav_marken", None) or []):
                # Marken da, aber alle ausgeblendet: nicht auf den Reitertext-Zähler ("n ⚠") zurückfallen
                b = dict(b, zaehler="")
            return super()._bereich(b, tid, kid, seite, eltern)
        b = dict(b, zaehler="")                       # Zähler-Text nicht doppelt zeigen
        super()._bereich(b, tid, kid, seite, eltern)
        z = next((zz for zz, art, d in reversed(self._eintraege) if art == "bereich" and d is b), None)
        if z is None:
            return
        dunkel = self.modus == "dunkel"
        tipp = b["name"] + ": " + ", ".join(text(k, n) for k, n in marken)
        neu = []
        zweizeilig = self.ausgeklappt and b["id"] in getattr(self, "_zweizeilig", set())
        if zweizeilig:
            # Zeile höher machen; Symbol, Name und Pfeil in die obere Hälfte, Marken darunter von links
            z.configure(height=knv.ZEILE_H + 18)
            for w in z.place_slaves():
                info = w.place_info()
                if info.get("rely") in ("0.5", 0.5):
                    w.place_configure(rely=0, y=knv.ZEILE_H // 2)
            x = knv.SCHMAL - 2
            for k, n in marken:
                f = farbe(ARTEN[k][0], dunkel)
                sym = self._label(z, image=bild(k, f, z))
                sym.place(x=x, y=knv.ZEILE_H + 4, anchor="w")
                x += 14 + 2
                neu.append(sym)
                if k != "verbunden":
                    zl = self._label(z, text=str(n), fg=f, font=self.schrift_klein)
                    zl.place(x=x, y=knv.ZEILE_H + 4, anchor="w")
                    x += self._mass(self.schrift_klein, str(n)) + 7
                    neu.append(zl)
        elif self.ausgeklappt:
            x = knv.BREIT - 10 - (16 if b["kinder"] else 0)
            for k, n in reversed(marken):
                f = farbe(ARTEN[k][0], dunkel)
                if k != "verbunden":
                    zl = self._label(z, text=str(n), fg=f, font=self.schrift_klein)
                    zl.place(x=x, rely=0.5, anchor="e")
                    x -= self._mass(self.schrift_klein, str(n)) + 2
                    neu.append(zl)
                sym = self._label(z, image=bild(k, f, z))
                sym.place(x=x, rely=0.5, anchor="e")
                x -= 14 + 7
                neu.append(sym)
        else:
            schwer = min((ARTEN[k][0] for k, __ in marken), key=self.SCHWERE.index)
            pk = tk.Canvas(z, width=8, height=8, bg=z._bg, highlightthickness=0, borderwidth=0)
            pk._feste_farben = True
            f = farbe(schwer, dunkel)
            pk.create_oval(0, 0, 7, 7, fill=f, outline=z._bg)
            pk.place(x=knv.SCHMAL // 2 + 6, y=5)
            neu.append(pk)
        # Hover und Klick wie die übrigen Teile der Zeile
        for w in neu:
            w.configure(cursor="hand2")
            w.bind("<ButtonRelease-1>", lambda e, i=b["id"]: self.waehlen(i))
            w.bind("<Enter>", lambda e: (z.event_generate("<Enter>"), self._tipp_zeigen(z, tipp)))
            w.bind("<Leave>", lambda e: (z.event_generate("<Leave>"), self._tipp_weg()))
        z.marken = neu
        z.bind("<Enter>", lambda e: self._tipp_zeigen(z, tipp), add="+")
        z.bind("<Leave>", lambda e: self._tipp_weg(), add="+")
        # beim Hervorheben (keller_navigation färbt nur seine Teile) die Marken mitfärben
        for w in neu:
            z.bind("<Enter>", lambda e, w=w: self._mitfaerben(z, w), add="+")
            z.bind("<Leave>", lambda e, w=w: self._mitfaerben(z, w), add="+")

    def _mitfaerben(self, z, w):
        try:
            w.configure(bg=z.cget("bg"))
        except tk.TclError:
            pass
