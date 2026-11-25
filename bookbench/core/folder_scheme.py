# -*- coding: utf-8 -*-
"""
folder_scheme.py - Ordnerschema der Bibliothek: Vorlage anwenden und aus vorhandenen Büchern erkennen.

Vorlage: Pfad relativ zur Bibliothek mit "/" und Platzhaltern wie in Calibre, ohne Endung (die bleibt
die der Buchdatei). Teile in eckigen Klammern fallen weg, wenn ein Platzhalter darin leer ist:

    {author_sort}/[{series}/][{series_index:2} - ]{title}

  FELDER                  Platzhalter -> Feld in Buch.meta (bzw. Rechenregel)
  werte(buch)             {platzhalter: text} eines Buchs (core/library.Buch)
  anwenden(vorlage, w)    relativer Pfad ohne Endung ("" = Vorlage ergibt nichts Brauchbares)
  ziel(vorlage, buch, endung)   relativer Pfad mit Endung
  pruefen(vorlage)        Fehlertext oder ""
  erkennen(buecher, wurzel)     (Vorlage, Treffer, Anzahl) - die Vorlage, nach der die meisten Bücher liegen
  sauber(text)            Ordner-/Dateiname, der unter Windows, Linux und auf dem E-Reader (FAT/exFAT) geht

Warum so: Calibre und der E-Reader legen Bücher nach einer Vorlage ab; Bookbench soll neue Bücher so
einsortieren, wie die vorhandenen liegen. Statt den Nutzer die Vorlage tippen zu lassen, setzt
erkennen() die Metadaten jedes Buchs in seinen Pfad ein und schaut, welche Vorlage am häufigsten
herauskommt.
"""
import re
from collections import Counter
from pathlib import Path

FELDER = ("title", "authors", "author", "author_sort", "series", "series_index", "publisher", "language", "isbn")
STANDARD = "{author_sort}/[{series}/][{series_index:2} - ]{title}"
_PLATZ = re.compile(r"\{(\w+)(?::(\d+))?\}")
_VERBOTEN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MAX_TEIL = 120                         # Zeichen je Ordner/Dateiname (Windows-Pfadlänge im Blick)


def sauber(text):
    """Ordner- oder Dateiname: verbotene Zeichen → _, Leerraum zusammengefasst, keine Punkte/Leerzeichen am
    Ende (Windows schneidet sie weg), höchstens MAX_TEIL Zeichen."""
    t = _VERBOTEN.sub("_", str(text or ""))
    t = re.sub(r"\s+", " ", t).strip()
    t = t[:MAX_TEIL].rstrip(" .")
    return t


def sortiername(autoren):
    """Sortiername wie Calibres Vorgabe ("invert"): "Dan Abnett & Nick Kyme" → "Abnett, Dan & Kyme, Nick".
    Für Bücher ohne file-as, damit sie im selben Ordner landen wie die aus Calibre."""
    erg = []
    for a in (x.strip() for x in (autoren or "").split("&")):
        teile = a.split()
        if "," in a or len(teile) < 2:
            erg.append(a)
        else:
            erg.append(teile[-1] + ", " + " ".join(teile[:-1]))
    return " & ".join(x for x in erg if x)


def werte(buch):
    """{platzhalter: text} aus Buch.meta (übernommene Änderungen meta_neu/reihe_neu zuerst)."""
    m = dict(getattr(buch, "meta", None) or {})
    m.update(getattr(buch, "meta_neu", None) or {})
    reihe, nummer = m.get("reihe", "") or getattr(buch, "reihe", ""), m.get("nummer", "") or getattr(buch, "nummer", "")
    if getattr(buch, "reihe_neu", None) is not None:
        reihe, nummer = buch.reihe_neu
    autoren = m.get("autoren", "") or getattr(buch, "autor", "")
    return {
        "title": m.get("titel", "") or getattr(buch, "titel", ""),
        "authors": autoren,
        "author": autoren.split("&")[0].strip(),
        "author_sort": m.get("autor_sort", "") or sortiername(autoren),
        "series": reihe or "",
        "series_index": str(nummer or "") if reihe else "",
        "publisher": m.get("verlag", "") or getattr(buch, "verlag", ""),
        "language": m.get("sprache", "") or getattr(buch, "sprache", ""),
        "isbn": m.get("isbn", "") or getattr(buch, "isbn", ""),
    }


def _feldtext(w, name, breite):
    t = str(w.get(name, "") or "").strip()
    if name == "series_index" and t:
        if t.endswith(".0"):
            t = t[:-2]
        if breite and t.replace(".", "", 1).isdigit():   # wie Calibres {series_index:0>2s}: 3 → 03, 1.5 bleibt
            t = t.zfill(int(breite))
    return sauber(t).replace("/", "_")


def _ersetzen(stueck, w):
    """Platzhalter in einem Stück Vorlage einsetzen; None, wenn einer davon leer ist."""
    leer = False

    def ein(m):
        nonlocal leer
        t = _feldtext(w, m.group(1), m.group(2))
        if not t:
            leer = True
        return t
    erg = _PLATZ.sub(ein, stueck)
    return None if leer else erg


def _teile(vorlage):
    """Vorlage in [(text, optional)] zerlegen."""
    teile, pos = [], 0
    for m in re.finditer(r"\[([^\[\]]*)\]", vorlage):
        if m.start() > pos:
            teile.append((vorlage[pos:m.start()], False))
        teile.append((m.group(1), True))
        pos = m.end()
    if pos < len(vorlage):
        teile.append((vorlage[pos:], False))
    return teile


def pruefen(vorlage):
    """Fehlertext (englisch, Aufrufer übersetzt nicht) oder "" - für die Einstellungen."""
    v = (vorlage or "").strip()
    if not v:
        return "empty"
    if v.count("[") != v.count("]") or re.search(r"\[[^\]]*\[", v):
        return "brackets"
    for m in _PLATZ.finditer(v):
        if m.group(1) not in FELDER:
            return "unknown:" + m.group(1)
    letzter = v.replace("[", "").replace("]", "").split("/")[-1]
    if not _PLATZ.search(letzter):
        return "no-field-in-name"
    return ""


def anwenden(vorlage, w):
    """Relativer Pfad (mit "/") ohne Endung; "" wenn der Dateiname leer bliebe."""
    stuecke = []
    for text, optional in _teile(vorlage or ""):
        t = _ersetzen(text, w)
        if t is None:
            if optional:
                continue
            t = _PLATZ.sub(lambda m: _feldtext(w, m.group(1), m.group(2)), text)
        stuecke.append(t)
    teile = [sauber(t) for t in "".join(stuecke).split("/")]
    teile = [t for t in teile if t]
    if not teile:
        return ""
    return "/".join(teile)


def endung(pfad):
    """.kepub.epub bleibt ganz erhalten, sonst die letzte Endung."""
    n = Path(pfad).name.lower()
    for e in (".kepub.epub", ".kepub", ".epub"):
        if n.endswith(e):
            return Path(pfad).name[-len(e):]
    return Path(pfad).suffix


def ziel(vorlage, buch, end=None):
    rel = anwenden(vorlage, werte(buch))
    if not rel:
        rel = sauber(Path(buch.pfad).stem) or "book"
    return rel + (end if end is not None else endung(buch.pfad))


def frei(wurzel, rel, belegt=()):
    """rel, oder rel mit " (2)", " (3)" … vor der Endung, falls die Datei schon da ist (oder belegt)."""
    wurzel = Path(wurzel)
    end = endung(rel)
    stamm = rel[:-len(end)] if end else rel
    kand, i = rel, 1
    while (wurzel / kand).exists() or kand in belegt:
        i += 1
        kand = f"{stamm} ({i}){end}"
    return kand


# ---------------------------------------------------------------------------------------------- Erkennen
def _verallgemeinern(rel, w):
    """Pfad eines Buchs (ohne Endung) → Vorlage, in der die Metadaten durch Platzhalter ersetzt sind.
    Längere Werte zuerst, damit "Horus Rising" nicht als Teil von "The Horus Heresy" ersetzt wird."""
    werte_liste = []
    for name in ("title", "series", "author_sort", "authors", "author", "publisher"):
        t = _feldtext(w, name, None)
        if len(t) >= 2:
            werte_liste.append((t, "{" + name + "}"))
    nr = _feldtext(w, "series_index", None)
    teile = []
    for teil in rel.split("/"):
        for t, platz in sorted(werte_liste, key=lambda x: -len(x[0])):
            if t in teil:
                teil = teil.replace(t, "\x00" + platz + "\x01")
        if nr:                                    # Nummer nur als ganzes Wort, ggf. mit führenden Nullen
            def nummer(m):
                ziffern = m.group(0)
                breite = len(ziffern.split(".")[0])
                return "{series_index:%d}" % breite if ziffern.startswith("0") else "{series_index}"
            stuecke = re.split(r"(\x00[^\x01]*\x01)", teil)
            soll = nr.lstrip("0") or "0"
            for i, s in enumerate(stuecke):
                if not s.startswith("\x00"):
                    stuecke[i] = re.sub(r"(?<![\d.])0*" + re.escape(soll) + r"(?![\d])",
                                        nummer, s, count=1)
            teil = "".join(stuecke)
        teile.append(teil.replace("\x00", "").replace("\x01", ""))
    return "/".join(teile)


def _kandidaten(vorlagen):
    """Aus den häufigsten Einzel-Vorlagen weitere bilden: Teile mit Reihe/Nummer optional machen."""
    kand = set()
    erweitert = []
    for v in vorlagen:                 # ohne eigenen Sortiernamen sind author_sort und authors gleich
        erweitert += [v, v.replace("{author_sort}", "{authors}"), v.replace("{author_sort}", "{author}")]
    for v in erweitert:
        kand.add(v)
        teile = v.split("/")
        neu = []
        for t in teile[:-1]:
            neu.append("[" + t + "/]" if "{series" in t and "{title}" not in t else t + "/")
        name = teile[-1]
        m = re.match(r"^(.*?\{series_index(?::\d+)?\}[^{]*)(\{.*)$", name)
        if m and "{title}" not in m.group(1):
            name = "[" + m.group(1) + "]" + m.group(2)
        m = re.match(r"^(.*\{title\})(.*\{series.*)$", name)
        if m:
            name = m.group(1) + "[" + m.group(2) + "]"
        kand.add("".join(neu) + name)
    return kand


def erkennen(buecher, wurzel):
    """(Vorlage, Treffer, Anzahl): die Vorlage, nach der die meisten lesbaren Bücher unter wurzel
    liegen. Ohne Bücher oder ohne Treffer: (STANDARD, 0, Anzahl)."""
    wurzel = Path(wurzel)
    paare = []
    for b in buecher:
        if getattr(b, "fehler", ""):
            continue
        try:
            rel = Path(b.pfad).relative_to(wurzel).as_posix()
        except ValueError:
            continue
        end = endung(rel)
        paare.append((rel[:-len(end)] if end else rel, werte(b)))
    if not paare:
        return STANDARD, 0, 0
    zaehler = Counter(_verallgemeinern(rel, w) for rel, w in paare)
    oft = [v for v, __ in zaehler.most_common(8) if _PLATZ.search(v.split("/")[-1])]
    def rang(v, n):
        # mehr Treffer zuerst; bei Gleichstand {authors} vor {author} vor {author_sort} (passt ohne Sortiernamen
        # gleich gut), dann die kürzere Vorlage (weniger Klammern = einfacher zu lesen)
        autor = v.count("{author}") + 2 * v.count("{author_sort}")
        return (-n, autor, len(v), v)
    beste, treffer = STANDARD, -1
    for v in sorted(_kandidaten(oft)) + [STANDARD]:
        if pruefen(v):
            continue
        n = sum(1 for rel, w in paare if anwenden(v, w) == rel)
        if treffer < 0 or rang(v, n) < rang(beste, treffer):
            beste, treffer = v, n
    return (beste, treffer, len(paare)) if treffer > 0 else (STANDARD, 0, len(paare))
