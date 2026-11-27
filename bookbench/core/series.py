# -*- coding: utf-8 -*-
"""
series.py - Reihen-Übersicht (seit 2.4-beta1), Logik ohne Oberfläche: Bücher nach Reihe gruppieren,
Lücken in der Nummerierung, doppelte Nummern, Bücher ohne Nummer, Lesestand je Reihe.

  Reihe                  name, buecher (nach Nummer, dann Titel), luecken [(von, bis)], doppelt [Nummer],
                         ohne_nummer [Buch], fertig, gelesen_bekannt, naechstes, autoren, spanne
  reihe_nummer(b)        (Reihe, Nummer) wie gerade gültig (übernommen geht vor gespeichert)
  bis(b)                 letzte Nummer eines Sammelbands (Feld nummer_bis) oder ""; enthalten(b) [ganze Nummern]
  baende(b, n)           Namen der enthaltenen Bände aus dem Inhaltsverzeichnis (Vermutung) oder []
  reihen(buecher)        [Reihe] alphabetisch; Bücher ohne Reihe und unlesbare fehlen
  ohne_reihe(buecher)    Bücher ohne Reihe (lesbar), nach Titel
  luecken(nummern)       fehlende ganze Zahlen zwischen 1 und der höchsten Nummer, zusammengefasst
  luecken_text(l)        "3, 5–7"
  FILTER                 (Kennung, Text N_, Prüfung) für die Auswahl über der Liste

Sammelbände (Omnibus 1–3): series_index ist in Calibre und KOReader nur eine Zahl, Bookbench merkt sich die
letzte Nummer im eigenen Feld nummer_bis (core/metadata). Ein Sammelband deckt alle ganzen Nummern seiner
Spanne ab; dass Band 2 außerdem einzeln da ist, gilt nicht als doppelt.

Warum nur ganze Zahlen als Lücken zählen: Zwischenbände wie 0.9 oder 1.5 (Novellen, Kurzgeschichten) sind
Zusätze zu einer Reihe, keine Pflicht. Zwischen 1 und 2 fehlt also nichts, auch wenn es eine 1.5 gibt, die
man nicht hat. Umgekehrt füllt eine 1.5 keine fehlende 1. Eine Reihe, die bei 0 beginnt (Vorgeschichte),
hat deshalb auch keine Lücke bei 0.
"""
from collections import Counter

from bookbench.core import listing
from bookbench.core.bulk_edit import nummer_text
from bookbench.i18n import N_

GRENZE = 999             # höher nummerierte Reihen (Jahreszahlen o. Ä.) bekommen keine Lückenprüfung


def reihe_nummer(b):
    """(Reihe, Nummer), wie sie gerade gilt: übernommen, aber noch nicht gespeichert (reihe_neu) geht vor."""
    neu = getattr(b, "reihe_neu", None)
    return (neu[0] or "", neu[1] or "") if neu is not None else (b.reihe or "", b.nummer or "")


def bis(b):
    """Letzte Nummer eines Sammelbands, wie sie gerade gilt (übernommen geht vor Datei), sonst ""."""
    meta = getattr(b, "meta", None) or {}
    neu = getattr(b, "meta_neu", None) or {}
    t = (neu["nummer_bis"] if "nummer_bis" in neu else meta.get("nummer_bis", "")) or ""
    a, z = _zahl(reihe_nummer(b)[1]), _zahl(t)
    return t if a is not None and z is not None and z > a else ""


def enthalten(b):
    """Ganze Nummern, die ein Sammelband enthält (Omnibus 1–3: [1, 2, 3]); einzelnes Buch: []."""
    a, z = _zahl(reihe_nummer(b)[1]), _zahl(bis(b))
    if a is None or z is None or z - a > 50:
        return []
    return list(range(int(-(-a // 1)), int(z) + 1))


def baende(b, n):
    """Namen der n Bände im Sammelband, vermutet aus dem Inhaltsverzeichnis: Einträge der obersten Ebene, unter
    denen weitere Einträge stehen (ein Roman hat Kapitel, „Über den Autor“ nicht). Nur wenn es mindestens n
    solche gibt, sonst [] - lieber keine Namen als falsche."""
    zeilen = getattr(b, "zeilen", None) or []
    if not zeilen:
        return []
    neu = getattr(b, "neu", None) or {}
    oben = min(z[0] for z in zeilen)
    namen = []
    for i, (tiefe, titel, __, schl) in enumerate(zeilen):
        if tiefe == oben and i + 1 < len(zeilen) and zeilen[i + 1][0] > oben:
            namen.append(neu.get(schl) or titel)
    return namen[:n] if len(namen) >= n else []


def _zahl(nummer):
    z = listing.nr(nummer)
    return None if z >= 1e9 else z


def luecken(nummern):
    """[(von, bis)] der fehlenden ganzen Zahlen 1 … höchste Nummer; nummern als Zahlen (None = ohne) oder
    (von, bis) für Sammelbände, die alle ganzen Zahlen dazwischen abdecken."""
    ganze, zahlen = set(), []
    for x in nummern:
        if isinstance(x, tuple):
            a, z = x
            zahlen.append(z)
            ganze.update(range(int(-(-a // 1)), int(z) + 1))
        elif x is not None and x >= 0:
            zahlen.append(x)
            if x == int(x):
                ganze.add(int(x))
    if not zahlen or max(zahlen) > GRENZE:
        return []
    erg, von = [], None
    for n in range(1, int(max(zahlen)) + 1):
        if n not in ganze:
            von = n if von is None else von
        elif von is not None:
            erg.append((von, n - 1))
            von = None
    if von is not None:
        erg.append((von, int(max(zahlen))))
    return erg


def luecken_text(l):
    return ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in l)


def _status(b):
    e = getattr(b, "lesen", None)
    return None if e is None else e.get("status", "")


class Reihe:
    def __init__(self, name, buecher):
        self.name = name
        self.buecher = sorted(buecher, key=lambda b: (listing.nr(reihe_nummer(b)[1]), b.titel.casefold()))
        zahlen = [_zahl(reihe_nummer(b)[1]) for b in self.buecher]
        enden = [_zahl(bis(b)) for b in self.buecher]
        self.luecken = luecken([(a, e) if e is not None else a for a, e in zip(zahlen, enden)])
        zaehl = Counter(z for z, e in zip(zahlen, enden) if z is not None and e is None)    # Sammelbände nicht
        self.doppelt = [nummer_text(z) for z in sorted(zaehl) if zaehl[z] > 1]
        self.ohne_nummer = [b for b, z in zip(self.buecher, zahlen) if z is None]
        nummeriert = [z for z in zahlen if z is not None]
        self.hoechste = max(nummeriert + [e for e in enden if e is not None]) if nummeriert else None
        if nummeriert:
            a, z = nummer_text(min(nummeriert)), nummer_text(self.hoechste)
            self.spanne = a if a == z else f"{a}–{z}"
        else:
            self.spanne = ""
        autoren = Counter(a.strip() for b in self.buecher for a in (b.autor or "").split("&") if a.strip())
        self.autoren = [a for a, __ in autoren.most_common()]
        st = [_status(b) for b in self.buecher]
        self.gelesen_bekannt = any(s is not None for s in st)
        self.fertig = sum(1 for s in st if s == "complete")
        self.angefangen = any(s in ("reading", "complete", "abandoned") for s in st)
        self.naechstes = self._naechstes() if self.gelesen_bekannt else None

    def _naechstes(self):
        """Buch, das gerade gelesen wird (das mit der kleinsten Nummer), sonst das erste ungelesene
        (pausierte zählen nicht als „als Nächstes“)."""
        lese = [b for b in self.buecher if _status(b) == "reading"]
        if lese:
            return lese[0]
        return next((b for b in self.buecher if _status(b) == ""), None)

    @property
    def probleme(self):
        return bool(self.luecken or self.doppelt or self.ohne_nummer)

    def fehlend(self):
        return sum(b - a + 1 for a, b in self.luecken)


def _schluessel(name):
    return " ".join(name.split()).casefold()


def reihen(buecher):
    """Reihen der lesbaren Bücher; gleiche Namen mit anderer Groß-/Kleinschreibung oder Leerzeichen gehören
    zusammen (angezeigt wird die häufigste Schreibweise)."""
    gruppen, namen = {}, {}
    for b in buecher:
        reihe = reihe_nummer(b)[0]
        if b.fehler or not reihe.strip():
            continue
        k = _schluessel(reihe)
        gruppen.setdefault(k, []).append(b)
        namen.setdefault(k, Counter())[" ".join(reihe.split())] += 1
    erg = [Reihe(namen[k].most_common(1)[0][0], bs) for k, bs in gruppen.items()]
    return sorted(erg, key=lambda r: r.name.casefold())


def ohne_reihe(buecher):
    return sorted((b for b in buecher if not b.fehler and not reihe_nummer(b)[0].strip()),
                  key=lambda b: b.titel.casefold())


FILTER = (("alle", N_("All series"), None),
          ("luecken", N_("With gaps"), lambda r: bool(r.luecken)),
          ("pruefen", N_("Numbers to check (duplicates, missing)"), lambda r: bool(r.doppelt or r.ohne_nummer)),
          ("angefangen", N_("Started, not finished"), lambda r: r.angefangen and r.fertig < len(r.buecher)),
          ("ungelesen", N_("Not started"), lambda r: r.gelesen_bekannt and not r.angefangen),
          ("fertig", N_("Finished"), lambda r: r.gelesen_bekannt and r.fertig == len(r.buecher)),
          ("ohne_reihe", N_("Books without series"), None))


def passt(r, such):
    """Suchtext (casefold) im Namen der Reihe, in Titeln oder Autoren ihrer Bücher."""
    return not such or such in r.name.casefold() or any(listing.such_passt(b, such) for b in r.buecher)
