# -*- coding: utf-8 -*-
"""
meta_lookup.py - Metadaten nachschlagen für das Nachschlagefenster (seit 2.3-beta2), ohne Oberfläche.
Google Books und Open Library liefern je Treffer alle Felder, den Klappentext und eine Cover-Adresse.

  SPRACHEN                          [(Kennung, N_(Name))] für die Auswahl; "buch" = wie das Buch
  sprache_fuer(buchsprache, wahl)   (sprache, abweichend) - abweichend: gewählte Sprache ist nicht die des Buchs,
                                    dann wird ohne ISBN gesucht (eine ISBN gehört zu genau einer Ausgabe) und
                                    nur in dieser Sprache (Google: langRestrict, Open Library: language)
  suchen(titel, autor, isbn, sprache, streng, quellen, bericht)   [Treffer]
      Treffer = {"quelle", "link", "werte": {feld: text}, "untertitel", "klappentext", "cover", "vorschau"}
      werte nach den Feldern von core/metadata (titel, autoren, verlag, datum, sprache, isbn, schlagwoerter)
  bild_laden(url)                   Bild (bytes) oder None

Adressen kommen aus core/blurbs (GOOGLE, OPENLIBRARY) und core/covers (OL_COVERS), damit die Tests sie
gemeinsam auf einen nachgebauten Server umbiegen können; der eigene Google-Schlüssel gilt auch hier.
"""
import json
import re
import urllib.parse
import urllib.request

from bookbench.core import blurbs
from bookbench.core import covers
from bookbench.core import metadata as kme
from bookbench.i18n import N_

SPRACHEN = (("buch", N_("Same as the book")), ("en", N_("English")), ("de", N_("German")), ("fr", N_("French")),
            ("es", N_("Spanish")), ("it", N_("Italian")), ("nl", N_("Dutch")), ("pl", N_("Polish")),
            ("pt", N_("Portuguese")), ("ru", N_("Russian")), ("ja", N_("Japanese")))
# Open Library sucht nach MARC-Sprachcodes
MARC = {"en": "eng", "de": "ger", "fr": "fre", "es": "spa", "it": "ita", "nl": "dut", "pl": "pol", "pt": "por",
        "ru": "rus", "ja": "jpn"}
HOECHSTENS = 10
MIT_TEXT = 3                    # bei so vielen Open-Library-Werken wird die Beschreibung extra geholt


def sprache_fuer(buchsprache, wahl):
    """Sprache fürs Nachschlagen: wahl "buch" (oder leer) = die des Buchs. abweichend = True, wenn eine andere
    Sprache gewählt ist als die des Buchs."""
    buch = kme.sprache_kurz(buchsprache or "").lower().split("-")[0]
    if not wahl or wahl == "buch":
        return buch, False
    return wahl, wahl != buch


def _json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Bookbench (metadata lookup)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def bild_laden(url, timeout=15):
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Bookbench (metadata lookup)"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            daten = r.read()
    except Exception:
        return None
    return daten if covers.bild_info(daten) else None


def _titel_passt(gesucht, gefunden):
    if not gesucht:
        return True
    a, b = blurbs._norm(gesucht), blurbs._norm(gefunden)
    return blurbs._titel_passt(gesucht, gefunden) or bool(a and a in b)


def _schlagwoerter(kategorien, hoechstens=6):
    """Google: "Fiction / Science Fiction / Military" -> Fiction, Science Fiction, Military (ohne General)."""
    erg = []
    for k in kategorien or []:
        for t in str(k).split("/"):
            t = t.replace(",", " ").strip()
            if t and t.casefold() != "general" and t.casefold() not in {x.casefold() for x in erg}:
                erg.append(t)
    return ", ".join(erg[:hoechstens])


# ---------------------------------------------------------------- Google Books
def _google_treffer(item):
    v = item.get("volumeInfo") or {}
    ids = {i.get("type"): i.get("identifier", "") for i in v.get("industryIdentifiers") or []}
    links = v.get("imageLinks") or {}
    vorschau = links.get("thumbnail") or links.get("smallThumbnail") or ""
    gross = next((links[k] for k in ("extraLarge", "large", "medium") if links.get(k)), "")
    if not gross and vorschau:                          # zoom=0 liefert die größte Fassung, wenn es eine gibt
        gross = vorschau.replace("zoom=1", "zoom=0").replace("&edge=curl", "")
    return {
        "quelle": "Google Books",
        "link": v.get("canonicalVolumeLink") or v.get("infoLink") or
        f"https://books.google.com/books?id={item.get('id', '')}",
        "werte": {"titel": v.get("title", ""), "autoren": " & ".join(v.get("authors") or []),
                  "verlag": v.get("publisher", ""), "datum": kme.datum_norm(v.get("publishedDate", "")),
                  "sprache": v.get("language", ""), "isbn": ids.get("ISBN_13") or ids.get("ISBN_10") or "",
                  "schlagwoerter": _schlagwoerter(v.get("categories"))},
        "untertitel": v.get("subtitle", ""),
        "klappentext": blurbs._text(v.get("description", "")),
        "cover": covers._https(gross), "vorschau": covers._https(vorschau),
    }


def google(titel, autor, isbn="", sprache="", streng=False):
    anfragen = [f"isbn:{isbn}"] if isbn else []
    if titel:
        anfragen.append(f'intitle:"{titel}"' + (f' inauthor:"{autor.split(",")[0].split("&")[0].strip()}"'
                                                 if autor else ""))
    for a in anfragen:
        p = {"q": a, "maxResults": HOECHSTENS, "printType": "books"}
        if streng and sprache:
            p["langRestrict"] = sprache
        daten = _json(f"{blurbs.GOOGLE}?" + urllib.parse.urlencode(blurbs.google_parameter(p)))
        erg = []
        for item in daten.get("items") or []:
            t = _google_treffer(item)
            if not a.startswith("isbn:"):              # bei der ISBN zählt die Ausgabe, nicht der Wortlaut
                if not (_titel_passt(titel, t["werte"]["titel"])
                        and blurbs._autor_passt(autor, (item.get("volumeInfo") or {}).get("authors") or [])):
                    continue
            erg.append(t)
        if erg:
            if sprache and not streng:                  # Buchsprache zuerst, sonst wie Google sortiert
                erg.sort(key=lambda t: t["werte"]["sprache"] != sprache)
            return erg
    return []


# ---------------------------------------------------------------- Open Library
def _ol_datum(text):
    """Open Library: "April 25, 2006", "2006", "25 Apr 2006" -> 2006-04-25 bzw. 2006."""
    import datetime
    t = (text or "").strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%B %Y", "%b %Y"):
        try:
            d = datetime.datetime.strptime(t, fmt)
            return d.strftime("%Y-%m-%d" if "%d" in fmt else "%Y-%m")
        except ValueError:
            pass
    n = kme.datum_norm(t)
    if kme.datum_ok(n):
        return n
    m = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", t)
    return m.group(1) if m else ""


def _beschreibung(d):
    return blurbs._text(d if isinstance(d, str) else (d or {}).get("value", ""))


def _ol_isbn(isbn):
    """Ausgabe zur ISBN über die Books-API (mit Autorennamen, Verlag, Cover)."""
    daten = _json(f"{blurbs.OPENLIBRARY}/api/books?" + urllib.parse.urlencode(
        {"bibkeys": f"ISBN:{isbn}", "format": "json", "jscmd": "data"}))
    e = daten.get(f"ISBN:{isbn}")
    if not e:
        return []
    ids = e.get("identifiers") or {}
    cover = e.get("cover") or {}
    t = {"quelle": "Open Library", "link": e.get("url") or f"{blurbs.OPENLIBRARY}{e.get('key', '')}",
         "werte": {"titel": e.get("title", ""), "autoren": " & ".join(a.get("name", "") for a in e.get("authors") or []),
                   "verlag": ((e.get("publishers") or [{}])[0]).get("name", ""), "datum": _ol_datum(e.get("publish_date", "")),
                   "sprache": "", "isbn": ((ids.get("isbn_13") or ids.get("isbn_10") or [isbn])[0]),
                   "schlagwoerter": ", ".join(s.get("name", "").replace(",", " ") for s in (e.get("subjects") or [])[:6])},
         "untertitel": e.get("subtitle", ""), "klappentext": "",
         "cover": cover.get("large", ""), "vorschau": cover.get("medium") or cover.get("small", "")}
    try:                                                # Beschreibung steht bei der Ausgabe oder beim Werk
        ed = _json(f"{blurbs.OPENLIBRARY}/isbn/{isbn}.json")
        t["klappentext"] = _beschreibung(ed.get("description"))
        sprachen = [x.get("key", "").rsplit("/", 1)[-1] for x in ed.get("languages") or []]
        t["werte"]["sprache"] = kme.sprache_kurz(sprachen[0]) if sprachen else ""
        if not t["klappentext"]:
            for w in (ed.get("works") or [])[:1]:
                t["klappentext"] = _beschreibung(_json(f"{blurbs.OPENLIBRARY}{w['key']}.json").get("description"))
    except Exception:
        pass
    return [t]


def openlibrary(titel, autor, isbn="", sprache="", streng=False):
    if isbn:
        erg = _ol_isbn(isbn)
        if erg:
            return erg
    if not titel:
        return []
    p = {"title": titel, "limit": 6,
         "fields": "key,title,subtitle,author_name,publisher,first_publish_year,language,subject,cover_i"}
    if autor:
        p["author"] = autor.split(",")[0].split("&")[0].strip()
    if streng and sprache in MARC:
        p["language"] = MARC[sprache]
    erg = []
    for d in _json(f"{blurbs.OPENLIBRARY}/search.json?" + urllib.parse.urlencode(p)).get("docs") or []:
        if not (_titel_passt(titel, d.get("title", "")) and blurbs._autor_passt(autor, d.get("author_name") or [])):
            continue
        sprachen = d.get("language") or []
        if streng and sprache:
            sp = sprache
        else:
            sp = kme.sprache_kurz(sprachen[0]) if len(sprachen) == 1 else ""
        cover = f"{covers.OL_COVERS}/b/id/{d['cover_i']}" if d.get("cover_i") else ""
        erg.append({"quelle": "Open Library", "link": f"{blurbs.OPENLIBRARY}{d.get('key', '')}", "key": d.get("key", ""),
                    "werte": {"titel": d.get("title", ""), "autoren": " & ".join(d.get("author_name") or []),
                              "verlag": (d.get("publisher") or [""])[0],
                              "datum": str(d.get("first_publish_year") or ""), "sprache": sp, "isbn": "",
                              "schlagwoerter": ", ".join(s.replace(",", " ") for s in (d.get("subject") or [])[:6])},
                    "untertitel": d.get("subtitle", ""), "klappentext": "",
                    "cover": cover + "-L.jpg?default=false" if cover else "",
                    "vorschau": cover + "-M.jpg?default=false" if cover else ""})
    for t in erg[:MIT_TEXT]:                            # Beschreibung steht beim Werk: eine Anfrage je Treffer
        try:
            t["klappentext"] = _beschreibung(_json(f"{blurbs.OPENLIBRARY}{t['key']}.json").get("description"))
        except Exception:
            pass
    return erg


QUELLEN = (("Google Books", google), ("Open Library", openlibrary))


def suchen(titel, autor="", isbn="", sprache="", streng=False, quellen=None, bericht=None):
    """Alle Treffer beider Quellen (Google zuerst). streng: nur in dieser Sprache und ohne ISBN suchen.
    bericht (Liste, optional) bekommt je Quelle (Name, Zahl der Treffer, Fehlertext)."""
    if streng:
        isbn = ""
    isbn = re.sub(r"[^\dXx]", "", isbn or "").upper()
    erg = []
    for name, f in quellen or QUELLEN:
        try:
            t = f(titel, autor, isbn, sprache, streng)
        except Exception as e:
            if bericht is not None:
                bericht.append((name, 0, blurbs.fehler_text(e)))
            continue
        if bericht is not None:
            bericht.append((name, len(t), ""))
        erg += t
    return erg
