# -*- coding: utf-8 -*-
"""
cleaner.py - Werbe- und Quellenzeilen aus Büchern entfernen (seit 2.1), ohne Oberfläche.

Solche Zeilen ("OceanofPDF.com", "Downloaded from …") stehen meist in einem eigenen <div> oder <p> am Kapitelende.
Wie Calibres Suchen/Ersetzen wird im rohen XHTML gesucht (Groß/Klein egal), damit der Rest der Datei Byte für
Byte bleibt, wie er war. Bookbench geht aber einen Schritt weiter als "Text durch nichts ersetzen": vom Fund aus
nach außen wird das äußerste Element genommen, das danach nichts mehr enthält (nur Leerraum/Satzzeichen, kein
Bild). So verschwindet der leere Container mit, statt als Leerzeile im Buch zu bleiben. Steht der Text mitten in
einem Absatz mit echtem Inhalt, wird nur der Text selbst entfernt.

Muster: eine Zeile je Muster, wörtlich; /…/ = regulärer Ausdruck. Funde im <head> (Titel) bleiben unberührt.
Ein Link, dessen Adresse (href) passt, zählt als Fund, egal wie er beschriftet ist ("Download more books" →
https://oceanofpdf.com): dann ist der ganze Link der Kern; in anderen Attributen (src, class …) zählt nichts.

  muster_kompilieren(zeilen)   [re.Pattern] (ungültige Ausdrücke: ValueError mit der Zeile)
  suchen(pfad, muster)         [Fund] eines Buchs
  entfernen(text, funde)       XHTML ohne die Funde (eine Datei)
  anwenden(pfad, funde, sicherungsordner, anzahl)   schreibt das Buch neu (vorher Sicherung), Anzahl entfernt
"""
import html
import os
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from bookbench.core import library as kd
from bookbench.core import toc_fix as tocfix

STANDARD = ["OceanofPDF.com"]
ENDUNGEN = (".xhtml", ".html", ".htm")
_LEER = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_NIE = {"html", "head", "body"}
_INHALT = re.compile(r"<(img|svg|image|video|audio|object|math)\b", re.I)
KONTEXT = 70


def muster_kompilieren(zeilen):
    erg = []
    for z in zeilen or []:
        z = (z or "").strip()
        if not z:
            continue
        if len(z) > 2 and z.startswith("/") and z.endswith("/"):
            try:
                erg.append(re.compile(z[1:-1], re.I))
            except re.error as e:
                raise ValueError(f"{z}: {e}") from None
        else:
            erg.append(re.compile(re.escape(z), re.I))
    return erg


class Fund:
    """Eine Fundstelle: in Datei `datei` wird text[start:ende] entfernt."""

    def __init__(self, datei, start, ende, treffer, art, kontext):
        self.datei, self.start, self.ende = datei, start, ende
        self.treffer = treffer          # gefundener Text
        self.art = art                  # "text" oder Tag-Name des entfernten Elements ("div", "p", "a" …)
        self.kontext = kontext          # (davor, treffer, danach) sichtbarer Text
        self.an = True                  # in der Liste angehakt


class _Elemente(HTMLParser):
    """Spannen (start, ende, tag) aller Elemente mit Offsets im Text."""

    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self.zeilen = [0]
        for m in re.finditer("\n", text):
            self.zeilen.append(m.end())
        self.text = text
        self.stapel, self.spannen = [], []
        self.feed(text)
        self.close()

    def _pos(self):
        z, s = self.getpos()
        return self.zeilen[z - 1] + s

    def handle_starttag(self, tag, attrs):
        start = self._pos()
        if tag in _LEER:
            return
        self.stapel.append((tag, start))

    def handle_endtag(self, tag):
        pos = self._pos()
        ende = self.text.find(">", pos) + 1
        for i in range(len(self.stapel) - 1, -1, -1):          # unsauberes HTML: bis zum passenden Tag schließen
            if self.stapel[i][0] == tag:
                for t, s in self.stapel[i:]:
                    self.spannen.append((s, ende, t))
                del self.stapel[i:]
                return


def _sichtbar(roh):
    return html.unescape(re.sub(r"<[^>]*>", "", roh))


def _leer_ohne(roh, muster):
    """Bleibt vom sichtbaren Text nach Entfernen aller Muster nichts (außer Leerraum/Satzzeichen)?"""
    if _INHALT.search(roh):
        return False
    t = _sichtbar(roh)
    for m in muster:
        t = m.sub("", t)
    return not re.sub(r"[\W_]+", "", t)


def _in_tag(text, pos):
    return text.rfind("<", 0, pos) > text.rfind(">", 0, pos)


def _funde_text(datei, text, muster):
    body = re.search(r"<body\b[^>]*>", text, re.I)
    ab = body.end() if body else 0
    treffer, links = [], []
    for m in muster:
        for t in m.finditer(text, ab):
            if t.end() <= t.start():
                continue
            if not _in_tag(text, t.start()):
                treffer.append((t.start(), t.end()))
            else:                                         # Treffer in einem Tag: zählt nur im href eines Links
                tag_start = text.rfind("<", 0, t.start())
                tag = text[tag_start:text.find(">", tag_start) + 1]
                if re.match(r"<a\b", tag, re.I) and _im_href(tag, t.start() - tag_start):
                    links.append(tag_start)
    if not treffer and not links:
        return []
    spannen = _Elemente(text).spannen
    kerne = [(s, e, "text") for s, e in treffer]
    for ls in set(links):                                 # ganzer Link, egal wie er beschriftet ist
        a = next((x for x in spannen if x[0] == ls and x[2] == "a"), None)
        if a:
            kerne.append((a[0], a[1], "a"))
    funde = []
    for s, e, art in sorted(set(kerne)):
        um = sorted((x for x in spannen if x[0] <= s and e <= x[1] and (x[0], x[1]) != (s, e) and x[2] not in _NIE),
                    key=lambda x: x[1] - x[0])          # innen nach außen
        start, ende = s, e
        for xs, xe, tag in um:                           # Container leer, wenn der Kern (und alle Muster) weg sind?
            if _leer_ohne(text[xs:s] + text[e:xe], muster):
                start, ende, art = xs, xe, tag
            else:
                break
        mitten = (start, ende) == (s, e)                  # nur Kern (Text oder Link) mitten in einem Absatz
        if mitten and text[s - 1:s] == " " and text[e:e + 1] in (" ", "\n"):
            ende = e + 1                                # "mit  mitten" vermeiden
        if not mitten:                                  # Einrückung davor und Zeilenende danach mitnehmen
            zs = text.rfind("\n", 0, start) + 1
            if not text[zs:start].strip():
                ze = text.find("\n", ende)
                if ze >= 0 and not text[ende:ze].strip():
                    start, ende = zs, ze + 1
        sichtbar_vor = _sichtbar(text[max(ab, s - 600):s])
        sichtbar_nach = _sichtbar(text[e:e + 600])
        gezeigt = " ".join(_sichtbar(text[s:e]).split())
        if (s, e, "a") in kerne and not any(m.search(gezeigt) for m in muster):
            href = re.search(r'href\s*=\s*["\']([^"\']*)', text[s:e], re.I)
            gezeigt = (gezeigt + " " if gezeigt else "") + "→ " + (href.group(1) if href else "")
        kontext = (" ".join(sichtbar_vor.split())[-KONTEXT:], gezeigt, " ".join(sichtbar_nach.split())[:KONTEXT])
        funde.append(Fund(datei, start, ende, text[s:e], art, kontext))
    return _zusammenfassen(funde)


def _im_href(tag, pos):
    """Liegt Position pos (im Tag-Text) im Wert des href-Attributs?"""
    for m in re.finditer(r'\bhref\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', tag, re.I):
        if m.start(1) <= pos < m.end(1):
            return True
    return False


def _zusammenfassen(funde):
    """Überlappende Spannen: die äußere behalten (z. B. zwei Treffer im selben <div>)."""
    erg = []
    for f in sorted(funde, key=lambda f: (f.start, -f.ende)):
        if erg and f.start < erg[-1].ende:
            if f.ende > erg[-1].ende:
                erg[-1].ende = f.ende
            continue
        erg.append(f)
    return erg


def _dateien(z):
    return [i.filename for i in z.infolist() if i.filename.lower().endswith(ENDUNGEN)]


def _lesen(z, name):
    roh = z.read(name)
    try:
        return roh.decode("utf-8")
    except UnicodeDecodeError:
        return roh.decode("cp1252", errors="replace")


def suchen(pfad, muster):
    """Alle Fundstellen eines Buchs (nach Datei und Position sortiert)."""
    if not muster:
        return []
    funde = []
    with zipfile.ZipFile(pfad) as z:
        for name in _dateien(z):
            funde += _funde_text(name, _lesen(z, name), muster)
    return funde


def entfernen(text, funde):
    for f in sorted(funde, key=lambda f: -f.start):
        text = text[:f.start] + text[f.ende:]
    return text


def anwenden(pfad, funde, sicherungsordner, anzahl=5):
    """Entfernt die angehakten Funde aus dem Buch (Sicherung vorher). Rückgabe: Anzahl entfernter Stellen."""
    pfad = Path(pfad)
    je_datei = {}
    for f in funde:
        if f.an:
            je_datei.setdefault(f.datei, []).append(f)
    if not je_datei:
        return 0
    geaendert = {}
    with zipfile.ZipFile(pfad) as z:
        for name, fs in je_datei.items():
            geaendert[name] = entfernen(_lesen(z, name), fs)
    kd.sicherung_anlegen(pfad, sicherungsordner, anzahl)
    tmp = pfad.with_name(pfad.name + ".tmp")
    tocfix.write_copy(pfad, tmp, geaendert)
    os.replace(tmp, pfad)
    return sum(len(v) for v in je_datei.values())
