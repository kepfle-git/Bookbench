# -*- coding: utf-8 -*-
"""
keller_navigation.py - Seitenleiste links statt Reiterköpfen (Designleitfaden 5a).

Gleich in Client (ticketclient) und Serververwaltung (ticketserver/gui);
bei Änderungen beide Kopien ersetzen.

  NaviNotebook   ttk.Notebook ohne sichtbare Reiterköpfe. Meldet jede
                 Änderung (add, hide, tab(text=…), select) mit dem
                 virtuellen Ereignis <<NaviGeaendert>>.
  Navigation     tk.Frame links im Fenster: liest die Bereiche aus dem
                 Haupt-Notebook (Reihenfolge, versteckte Reiter, Text) und
                 deren Unterseiten aus seite.nb (ebenfalls NaviNotebook).

Text eines Reiters "Name (Zähler)" wird zu Name und Zähler rechts, z. B.
"Prüfungen (1 ⚠)". Eingeklappt bleiben nur die Symbole; ein Punkt am
Symbol zeigt, dass etwas ansteht (⚠ rot, reine Zahl in Akzentfarbe;
"2/3" oder "1 heute" sind nur Information und bekommen keinen Punkt).

Angaben an der Seite (Attribute des Widgets im Haupt-Notebook):
  nav_symbol    Name des Symbols (Schlüssel in symbole[modus])
  nav_unten     True: unten in der Leiste, abgesetzt (Verwaltung)
  nb            Notebook mit Unterseiten -> Unterbaum

Bedienung: Klick auf einen Bereich zeigt ihn (zuletzt gewählte Unterseite)
und klappt seinen Unterbaum auf; ▸/▾ klappt nur auf oder zu. ☰ oben
oder Strg+B klappt die Leiste ein und aus (tastenkuerzel()). Strg+1 … 9
wählen die Bereiche in Leistenreihenfolge.
"""
import base64
import re
import struct
import tkinter as tk
import zlib
from tkinter import ttk

try:                                    # Serververwaltung: Paket ticketserver.gui
    from . import keller_theme as kth
except ImportError:                     # Client: Module liegen nebeneinander
    import keller_theme as kth

BREIT = 196             # px ausgeklappt
SCHMAL = 44             # px eingeklappt
ZEILE_H = 32            # Bereich
UNTER_H = 26            # Unterseite
BALKEN = 3              # Markierung links am gewählten Eintrag
WARN = {"hell": "#d9534f", "dunkel": "#ff6b61"}

_TEILEN = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def einfaerben(daten, farbe):
    """PNG (base64, 8 Bit RGBA, wie navi_symbole_erzeugen sie schreibt) in
    einer Farbe "#rrggbb" neu einfärben, Deckkraft (Kantenglättung) bleibt.
    So folgen die aktiven Symbole dem Akzent des Farbdesigns, ohne dass für
    jedes Design eigene Bilder nötig sind. Andere PNG-Arten: unverändert."""
    roh = base64.b64decode(daten)
    breite, hoehe, tiefe, art, _, _, zeilensprung = struct.unpack(">IIBBBBB", roh[16:29])
    if (tiefe, art, zeilensprung) != (8, 6, 0):
        return daten
    idat, pos = b"", 8
    while pos < len(roh):
        laenge, typ = struct.unpack(">I4s", roh[pos:pos + 8])
        if typ == b"IDAT":
            idat += roh[pos + 8:pos + 8 + laenge]
        pos += 12 + laenge
    gefiltert = zlib.decompress(idat)
    bpp, zl = 4, breite * 4
    vorher = bytearray(zl)
    r, g, b = int(farbe[1:3], 16), int(farbe[3:5], 16), int(farbe[5:7], 16)
    neu = bytearray()
    for y in range(hoehe):
        filt = gefiltert[y * (zl + 1)]
        zeile = bytearray(gefiltert[y * (zl + 1) + 1:(y + 1) * (zl + 1)])
        for i in range(zl):                     # Filter rückgängig machen (PNG-Spez. Kap. 9)
            a = zeile[i - bpp] if i >= bpp else 0
            o = vorher[i]
            c = vorher[i - bpp] if i >= bpp else 0
            if filt == 1:
                zeile[i] = (zeile[i] + a) & 255
            elif filt == 2:
                zeile[i] = (zeile[i] + o) & 255
            elif filt == 3:
                zeile[i] = (zeile[i] + (a + o) // 2) & 255
            elif filt == 4:
                zeile[i] = (zeile[i] + _paeth(a, o, c)) & 255
        vorher = zeile
        aus = bytearray(zeile)
        aus[0::4], aus[1::4], aus[2::4] = bytes([r]) * breite, bytes([g]) * breite, bytes([b]) * breite
        neu += b"\0" + aus                      # Filter 0, Alpha (jedes 4. Byte) bleibt

    def block(typ, inhalt):
        return struct.pack(">I", len(inhalt)) + typ + inhalt + struct.pack(">I", zlib.crc32(typ + inhalt))
    png = (roh[:8] + block(b"IHDR", roh[16:29]) + block(b"IDAT", zlib.compress(bytes(neu), 9))
           + block(b"IEND", b""))
    return base64.b64encode(png).decode()


_FARBIG = {}


def _gefaerbt(daten, farbe):
    """einfaerben() mit Zwischenspeicher (Designwechsel hin und her)."""
    if not (isinstance(farbe, str) and len(farbe) == 7 and farbe.startswith("#")):
        return daten
    schl = (daten, farbe)
    if schl not in _FARBIG:
        try:
            _FARBIG[schl] = einfaerben(daten, farbe)
        except Exception:               # lieber blau als gar kein Symbol
            _FARBIG[schl] = daten
    return _FARBIG[schl]


def teilen(text):
    """"Prüfungen (1 ⚠)" -> ("Prüfungen", "1 ⚠"); ohne Klammer Zähler ""."""
    m = _TEILEN.match(text or "")
    return (m.group(1), m.group(2)) if m else (text or "", "")


def punkt_farbe(zaehler, p, modus):
    """Farbe des Punkts am eingeklappten Symbol oder None."""
    if "⚠" in zaehler:
        return WARN[modus]
    if zaehler.strip().isdigit():
        return p["akzent"]
    return None


def stil_einrichten(root):
    """Notebook-Stil ohne Reiterköpfe; nach jedem theme_use nötig (Layouts
    gelten je Theme), deshalb aus Navigation.farben aufgerufen."""
    s = ttk.Style(root)
    s.layout("Navi.TNotebook.Tab", [])
    s.configure("Navi.TNotebook", borderwidth=0, tabmargins=0, padding=0)


class NaviNotebook(ttk.Notebook):
    def __init__(self, *a, **k):
        k.setdefault("style", "Navi.TNotebook")
        super().__init__(*a, **k)
        stil_einrichten(self)

    def _melden(self):
        try:
            self.event_generate("<<NaviGeaendert>>", when="tail")
        except tk.TclError:
            pass

    def add(self, *a, **k):
        super().add(*a, **k)
        self._melden()

    def insert(self, *a, **k):
        super().insert(*a, **k)
        self._melden()

    def hide(self, *a, **k):
        super().hide(*a, **k)
        self._melden()

    def forget(self, *a, **k):
        super().forget(*a, **k)
        self._melden()

    def tab(self, tab_id, option=None, **k):
        erg = super().tab(tab_id, option, **k)
        if k:
            self._melden()
        return erg


class Navigation(tk.Frame):
    def __init__(self, eltern, notebook, symbole, dunkel=False, ausgeklappt=True, offen=(), merken=None):
        """symbole: {"hell": {name: base64}, "dunkel": {...}} mit name und
        name + "_aktiv". merken(schluessel, wert): Zustand sichern
        ("ausgeklappt" bool, "offen" Liste der aufgeklappten Bereichsnamen)."""
        super().__init__(eltern, highlightthickness=0, borderwidth=0)
        self._feste_farben = True
        self.nb = notebook
        self.symbole = symbole
        self.dunkel = dunkel
        self.ausgeklappt = ausgeklappt
        self.offen = set(offen)
        self.merken = merken or (lambda k, w: None)
        self._bilder = {}
        self._job = None
        self._tipp = None
        self._eintraege = []                # [(frame, art, daten)] für Tests und Hover
        self.innen = tk.Frame(self, borderwidth=0, highlightthickness=0)
        self.innen._feste_farben = True
        self.innen.pack(side="left", fill="both", expand=True)
        self.linie = tk.Frame(self, width=1, borderwidth=0, highlightthickness=0)
        self.linie._feste_farben = True
        self.linie.pack(side="right", fill="y")
        self._hoehe = 0
        self.bind("<Configure>", self._groesse)
        self.bind_all("<<NaviGeaendert>>", lambda e: self.aktualisieren(), add="+")
        self.bind_all("<<NotebookTabChanged>>", lambda e: self.aktualisieren(), add="+")
        self.farben(dunkel)

    # -- Struktur -------------------------------------------------------------------
    def bereiche(self):
        """Sichtbare Bereiche: [{id, widget, name, zaehler, symbol, unten, kinder}],
        kinder: [{id, nb, name, zaehler}]."""
        erg = []
        for tid in self.nb.tabs():
            if self.nb.tab(tid, "state") == "hidden":
                continue
            w = self.nb.nametowidget(tid)
            name, zaehler = teilen(self.nb.tab(tid, "text"))
            kinder = []
            sub = getattr(w, "nb", None)
            if isinstance(sub, ttk.Notebook):
                for kid in sub.tabs():
                    if sub.tab(kid, "state") != "hidden":
                        kn, kz = teilen(sub.tab(kid, "text"))
                        kinder.append({"id": kid, "nb": sub, "name": kn, "zaehler": kz})
            erg.append({"id": tid, "widget": w, "name": name, "zaehler": zaehler,
                        "symbol": getattr(w, "nav_symbol", None), "unten": getattr(w, "nav_unten", False),
                        "kinder": kinder})
        return erg

    def _gewaehlt(self):
        """(id des Bereichs, id der Unterseite oder None)."""
        try:
            tid = self.nb.select()
        except tk.TclError:
            return None, None
        if not tid:
            return None, None
        sub = getattr(self.nb.nametowidget(tid), "nb", None)
        kid = None
        if isinstance(sub, ttk.Notebook):
            try:
                kid = sub.select() or None
            except tk.TclError:
                pass
        return tid, kid

    # -- Bedienung ------------------------------------------------------------------
    def waehlen(self, tid, kid=None):
        b = next((b for b in self.bereiche() if b["id"] == tid), None)
        if b is None:
            return
        if b["kinder"]:
            self.offen.add(b["name"])
            self.merken("offen", sorted(self.offen))
        if kid is not None:
            b["widget"].nb.select(kid)
        self.nb.select(tid)
        self.aktualisieren()

    def nummer(self, i):
        """Strg+1 … 9: i-ter Bereich in Leistenreihenfolge (oben, dann unten)."""
        reihe = [b for b in self.bereiche() if not b["unten"]] + [b for b in self.bereiche() if b["unten"]]
        if 0 <= i < len(reihe):
            self.waehlen(reihe[i]["id"])

    def auf_zu(self, name):
        self.offen.symmetric_difference_update({name})
        self.merken("offen", sorted(self.offen))
        self.aktualisieren()

    def umschalten(self):
        self.ausgeklappt = not self.ausgeklappt
        self.merken("ausgeklappt", self.ausgeklappt)
        self._tipp_weg()
        self.aktualisieren()            # nicht sofort: der Klick kommt aus einem Widget, das dabei verschwindet

    def tastenkuerzel(self, root):
        root.bind_all("<Control-b>", lambda e: self.umschalten())
        for i in range(9):
            root.bind_all(f"<Control-Key-{i + 1}>", lambda e, i=i: self.nummer(i))

    # -- Zeichnen -------------------------------------------------------------------
    def farben(self, dunkel):
        self.dunkel = dunkel
        stil_einrichten(self)
        self.p = dict(kth.PALETTE["dunkel" if dunkel else "hell"])
        self.modus = "dunkel" if dunkel else "hell"
        self._bilder = {}
        for name, daten in self.symbole[self.modus].items():
            if name.endswith("_aktiv"):         # im Akzent des Designs, nicht fest blau
                daten = _gefaerbt(daten, self.p["akzent"])
            self._bilder[name] = tk.PhotoImage(data=daten)
        self.schrift = kth.schrift(10)
        self.schrift_fett = kth.schrift(10, fett=True)
        self.schrift_klein = kth.schrift(9)
        self.zeichnen()

    def aktualisieren(self):
        """Neu zeichnen, gesammelt (viele Änderungen hintereinander = einmal)."""
        if self._job is None:
            try:
                self._job = self.after_idle(self.zeichnen)
            except tk.TclError:
                pass

    def _groesse(self, e):
        if e.height != self._hoehe:
            self._hoehe = e.height
            self.aktualisieren()

    def _offen(self, b, tid):
        return bool(b["kinder"]) and self.ausgeklappt and (b["name"] in self.offen or b["id"] == tid)

    def _noetig(self, alle, tid):
        """Höhe, die alle Einträge brauchen (für die Entscheidung, ob der
        untere Block unten stehen kann)."""
        h = ZEILE_H + 12
        for b in alle:
            h += ZEILE_H + (len(b["kinder"]) * UNTER_H if self._offen(b, tid) else 0)
        return h

    def zeichnen(self):
        self._job = None
        if not self.winfo_exists():
            return
        p = self.p
        for w in self.innen.winfo_children():
            w.destroy()
        self._eintraege = []
        self.configure(bg=p["kopf"], width=BREIT if self.ausgeklappt else SCHMAL)
        self.innen.configure(bg=p["kopf"], width=BREIT if self.ausgeklappt else SCHMAL)
        self.linie.configure(bg=p["rahmen"])
        self.pack_propagate(False)
        self.innen.pack_propagate(True)

        kopf = self._zeile(self.innen, ZEILE_H, None)
        knopf = tk.Label(kopf, text="☰", font=kth.schrift(12), bg=p["kopf"], fg=p["fg"], cursor="hand2")
        knopf._feste_farben = True
        knopf.place(x=SCHMAL // 2, rely=0.5, anchor="center")
        self._hover(kopf, [knopf], lambda: self.umschalten(),
                    "Leiste einklappen (Strg+B)" if self.ausgeklappt else "Leiste ausklappen (Strg+B)")
        kopf.pack(side="top", fill="x")

        tid, kid = self._gewaehlt()
        alle = self.bereiche()
        unten = [b for b in alle if b["unten"]]
        for b in [b for b in alle if not b["unten"]]:
            self._bereich(b, tid, kid, "top")
        if unten:
            # unten abgesetzt; reicht die Höhe nicht, rückt der Block direkt
            # unter die anderen, damit nichts überdeckt wird
            rahmen = tk.Frame(self.innen, bg=p["kopf"], highlightthickness=0, borderwidth=0)
            rahmen._feste_farben = True
            if self._noetig(alle, tid) <= self.winfo_height():
                rahmen.pack(side="bottom", fill="x", pady=(0, 6))
            else:
                rahmen.pack(side="top", fill="x", pady=(6, 0))
            trenner = tk.Frame(rahmen, height=1, bg=p["rahmen"])
            trenner._feste_farben = True
            trenner.pack(side="top", fill="x", padx=8, pady=(0, 4))
            for b in unten:
                self._bereich(b, tid, kid, "top", eltern=rahmen)

    def _zeile(self, eltern, hoehe, aktiv):
        p = self.p
        z = tk.Frame(eltern, height=hoehe, bg=p["feld"] if aktiv else p["kopf"],
                     highlightthickness=0, borderwidth=0)
        z._feste_farben = True
        z.pack_propagate(False)
        z._bg = z.cget("bg")
        if aktiv:
            balken = tk.Frame(z, width=BALKEN, bg=p["akzent"])
            balken._feste_farben = True
            balken.place(x=0, y=0, relheight=1)
        return z

    def _label(self, z, **k):
        k.setdefault("fg", self.p["fg"])
        l = tk.Label(z, bg=z._bg, borderwidth=0, **k)
        l._feste_farben = True
        return l

    def _bereich(self, b, tid, kid, seite, eltern=None):
        p = self.p
        eltern = eltern or self.innen
        gewaehlt = b["id"] == tid
        mit_kindern = bool(b["kinder"]) and self.ausgeklappt
        offen = self._offen(b, tid)
        # Bereich selbst hervorgehoben, wenn er gewählt ist und keine Unterseite
        # sichtbar ist, die das übernimmt
        markiert = gewaehlt and not offen
        z = self._zeile(eltern, ZEILE_H, markiert)
        z.pack(side=seite, fill="x")
        teile = []
        bild = self._bilder.get(f"{b['symbol']}_aktiv" if gewaehlt else b["symbol"])
        if bild is not None:
            sym = self._label(z, image=bild)
            sym.place(x=SCHMAL // 2, rely=0.5, anchor="center")
            teile.append(sym)
        zaehler = b["zaehler"]
        if self.ausgeklappt:
            text = self._label(z, text=b["name"], font=self.schrift_fett if gewaehlt else self.schrift,
                               fg=p["akzent"] if gewaehlt else p["fg"], anchor="w")
            text.place(x=SCHMAL - 2, rely=0.5, anchor="w")
            teile.append(text)
            rechts = BREIT - 10
            if mit_kindern:
                pfeil = self._label(z, text="▾" if offen else "▸", fg=p["hinweis"], font=self.schrift, cursor="hand2")
                pfeil.place(x=rechts, rely=0.5, anchor="e")
                pfeil.bind("<ButtonRelease-1>", lambda e, n=b["name"]: (self.auf_zu(n), "break")[1])
                rechts -= 16
            if zaehler:
                farbe = WARN[self.modus] if "⚠" in zaehler else p["hinweis"]
                zl = self._label(z, text=zaehler, fg=farbe, font=self.schrift_klein)
                zl.place(x=rechts, rely=0.5, anchor="e")
                teile.append(zl)
        else:
            farbe = punkt_farbe(zaehler, p, self.modus)
            if farbe:
                pk = tk.Canvas(z, width=8, height=8, bg=z._bg, highlightthickness=0, borderwidth=0)
                pk._feste_farben = True
                pk.create_oval(0, 0, 7, 7, fill=farbe, outline=z._bg)
                pk.place(x=SCHMAL // 2 + 6, y=5)
                teile.append(pk)
        tipp = b["name"] + (f" ({zaehler})" if zaehler else "")
        self._hover(z, teile, lambda: self.waehlen(b["id"]), None if self.ausgeklappt else tipp)
        self._eintraege.append((z, "bereich", b))
        if offen:
            for k in b["kinder"]:
                self._kind(eltern, b, k, gewaehlt and k["id"] == kid, seite)

    def _kind(self, eltern, b, k, gewaehlt, seite):
        p = self.p
        z = self._zeile(eltern, UNTER_H, gewaehlt)
        z.pack(side=seite, fill="x")
        text = self._label(z, text=k["name"], font=self.schrift, fg=p["akzent"] if gewaehlt else p["fg"], anchor="w")
        text.place(x=SCHMAL + 10, rely=0.5, anchor="w")
        teile = [text]
        if k["zaehler"]:
            farbe = WARN[self.modus] if "⚠" in k["zaehler"] else p["hinweis"]
            zl = self._label(z, text=k["zaehler"], fg=farbe, font=self.schrift_klein)
            zl.place(x=BREIT - 10, rely=0.5, anchor="e")
            teile.append(zl)
        self._hover(z, teile, lambda: self.waehlen(b["id"], k["id"]), None)
        self._eintraege.append((z, "kind", (b, k)))

    def _hover(self, z, teile, befehl, tipp):
        p = self.p
        alle = [z] + teile

        def rein(_e):
            if z._bg == p["kopf"]:
                for w in alle:
                    try:
                        w.configure(bg=p["knopf_aktiv"])
                    except tk.TclError:
                        pass
            if tipp:
                self._tipp_zeigen(z, tipp)

        def raus(_e):
            if z._bg == p["kopf"]:
                for w in alle:
                    try:
                        w.configure(bg=p["kopf"])
                    except tk.TclError:
                        pass
            self._tipp_weg()

        for w in alle:
            w.bind("<Enter>", rein)
            w.bind("<Leave>", raus)
            w.bind("<ButtonRelease-1>", lambda e: befehl())
            if w is not z:
                w.configure(cursor="hand2")
        z.configure(cursor="hand2")

    # -- Einblendung neben der eingeklappten Leiste (wie die Tooltips) -------------------
    def _tipp_zeigen(self, z, text):
        self._tipp_weg()
        top = self.winfo_toplevel()
        t = self._tipp = tk.Label(top, text=text, bg=self.p["kopf"], fg=self.p["fg"], padx=6, pady=3,
                                  relief="solid", borderwidth=1, font=self.schrift_klein)
        t._feste_farben = True
        t.place(x=z.winfo_rootx() - top.winfo_rootx() + z.winfo_width() + 4,
                y=z.winfo_rooty() - top.winfo_rooty() + (z.winfo_height() - 22) // 2)
        t.lift()

    def _tipp_weg(self):
        if self._tipp is not None:
            try:
                self._tipp.destroy()
            except tk.TclError:
                pass
            self._tipp = None
