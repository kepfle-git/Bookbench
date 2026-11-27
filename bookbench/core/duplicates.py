# -*- coding: utf-8 -*-
"""
duplicates.py - Duplikate in der geöffneten Bibliothek finden (seit 2.4-beta5), Logik ohne Oberfläche.

Zwei Bücher gelten als dasselbe Buch, wenn eines davon zutrifft (wie beim Hinzufügen, core/book_import.duplikat):
  uuid    gleiche Calibre-UUID
  isbn    gleiche ISBN
  titel   gleicher Titel und gleicher erster Autor (ohne Artikel, Satzzeichen, Groß/klein)
  datei   gleicher Inhalt (gleiche Größe und SHA-1) - echte Kopien, auch unter anderem Namen
Zusammenhängende Paare bilden eine Gruppe (A = B über die ISBN, B = C über den Titel → eine Gruppe A, B, C).

  gruppen(buecher, pruefsummen=True, fortschritt=None)   [Gruppe] nach Titel
  Gruppe.buecher, Gruppe.gruende {"uuid", "isbn", "titel", "datei"}, Gruppe.titel
  info(b)               {"groesse", "zeit", "format"} einer Datei
  loeschen(buecher, sicherungsordner, anzahl)   (gelöscht [Buch], fehler [(Buch, Text)]); vorher Sicherung
"""
import hashlib
import os
from pathlib import Path

from bookbench.core import book_import as bi
from bookbench.core import library as kd

GRUENDE = ("uuid", "isbn", "titel", "datei")


class Gruppe:
    def __init__(self, buecher, gruende):
        self.buecher = sorted(buecher, key=lambda b: str(b.pfad).casefold())
        self.gruende = set(gruende)
        self.titel = next((b.titel for b in self.buecher if b.titel), self.buecher[0].name)


def info(b):
    try:
        st = os.stat(b.pfad)
        groesse, zeit = st.st_size, st.st_mtime
    except OSError:
        groesse, zeit = 0, 0
    name = Path(b.pfad).name.lower()
    fmt = "KEPUB" if name.endswith((".kepub.epub", ".kepub")) else Path(name).suffix.lstrip(".").upper()
    return {"groesse": groesse, "zeit": zeit, "format": fmt}


def _sha1(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for stueck in iter(lambda: f.read(1 << 20), b""):
            h.update(stueck)
    return h.hexdigest()


def gruppen(buecher, pruefsummen=True, fortschritt=None):
    """Gruppen gleicher Bücher (mindestens zwei); unlesbare Dateien nur über die Prüfsumme."""
    buecher = list(buecher)
    eltern = list(range(len(buecher)))
    gruende = {}

    def wurzel(i):
        while eltern[i] != i:
            eltern[i] = eltern[eltern[i]]
            i = eltern[i]
        return i

    def verbinden(i, j, grund):
        a, b = wurzel(i), wurzel(j)
        if a != b:
            eltern[b] = a
        gruende.setdefault(wurzel(i), set()).add(grund)

    def nach(schluessel_fn, grund):
        gesehen = {}
        for i, b in enumerate(buecher):
            k = schluessel_fn(b)
            if not k:
                continue
            if k in gesehen:
                verbinden(gesehen[k], i, grund)
            else:
                gesehen[k] = i

    lesbar = lambda fn: (lambda b: None if b.fehler else fn(b))          # noqa: E731
    nach(lesbar(lambda b: getattr(b, "uuid", "") or None), "uuid")
    nach(lesbar(lambda b: (getattr(b, "isbn", "") or "").replace("-", "") or None), "isbn")
    nach(lesbar(lambda b: (bi._norm(b.titel), bi._autor(b)) if bi._norm(b.titel) else None), "titel")
    if pruefsummen:                                   # nur Dateien gleicher Größe lesen
        groessen = {}
        for i, b in enumerate(buecher):
            groessen.setdefault(info(b)["groesse"], []).append(i)
        kandidaten = [ii for g, ii in groessen.items() if g and len(ii) > 1]
        n = sum(len(ii) for ii in kandidaten)
        k = 0
        for ii in kandidaten:
            summen = {}
            for i in ii:
                k += 1
                if fortschritt:
                    fortschritt(k, n)
                try:
                    s = _sha1(buecher[i].pfad)
                except OSError:
                    continue
                if s in summen:
                    verbinden(summen[s], i, "datei")
                else:
                    summen[s] = i
    sammeln = {}
    for i in range(len(buecher)):
        sammeln.setdefault(wurzel(i), []).append(i)
    erg = []
    for w, ii in sammeln.items():
        if len(ii) > 1:
            g = set()
            for i in ii:
                g |= gruende.get(i, set())
            g |= gruende.get(w, set())
            erg.append(Gruppe([buecher[i] for i in ii], g))
    return sorted(erg, key=lambda g: g.titel.casefold())


def loeschen(buecher, sicherungsordner, anzahl=5):
    """Dateien löschen (vorher Sicherung). KOReaders .sdr daneben bleibt (Lesestand, Markierungen)."""
    weg, fehler = [], []
    for b in buecher:
        try:
            kd.sicherung_anlegen(b.pfad, sicherungsordner, anzahl)
            Path(b.pfad).unlink()
            weg.append(b)
        except OSError as ex:
            fehler.append((b, str(ex)))
    return weg, fehler
