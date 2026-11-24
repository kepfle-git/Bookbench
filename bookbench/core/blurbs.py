# -*- coding: utf-8 -*-
"""
blurbs.py - Klappentexte nachschlagen und ins EPUB schreiben (Teil von Bookbench).

Reihenfolge beim Nachschlagen (die Oberfläche ruft die Schritte einzeln auf):
  free_look_up(titel, autor, isbn, sprache)      Google Books, dann Open Library - kostenlos; für Google Books
                                                 geht ein eigener Schlüssel (GOOGLE_KEY, seit 1.3-beta5)
  profile_for(profile, verlag, reihe, autor)     passendes Quellprofil (erstes aktives, dessen Filter passt)
  look_up(client, args, titel, autor, reihe, profil, sprache)
                                                 Claude ruft die Seiten des Profils ab (Web-Fetch) bzw.
                                                 sucht, und kopiert den Klappentext wörtlich heraus

Ein Quellprofil beschreibt, wo Claude sucht:
  name       Anzeige
  aktiv      False = wird übersprungen
  verlag, reihe, autor
             "gilt für": durch Komma getrennte Teilwörter, Groß-/Kleinschreibung egal. Ein Treffer
             in einem der Felder reicht; alle leer = gilt für alle Bücher.
  thema      wird dem Prompt mitgegeben ("Warhammer 40,000"), darf leer sein
  seiten     URL-Vorlagen, eine je Zeile, in dieser Reihenfolge abgerufen. Platzhalter:
             {title} {base} {author} {series} als Wiki-Seitenname (Leerzeichen -> _),
             {title_q} {author_q} URL-kodiert für Suchseiten. {base} = Titel ohne "Omnibus";
             Vorlagen mit {base} entfallen, wenn der Titel keinen Omnibus-Zusatz hat.
  domains    weitere erlaubte Seiten (eine je Zeile); dazu kommen die Hosts aus den Vorlagen
  abschnitt  wie der Abschnitt mit dem Klappentext dort meist heißt (Hinweis für den Prompt)
  websuche   suchen, wenn keine Vorlage passt - in den erlaubten Seiten, ohne welche im ganzen Netz

Dazu read_opf, book_info, book_extra, with_description: Metadaten (content.opf) lesen und schreiben.
"""
import html
import inspect
import json
import re
import urllib.parse
import urllib.request
from urllib.parse import quote, urlparse

from bookbench.core.toc_report import clean  # noqa: E402
from bookbench.i18n import _

MODEL = "claude-haiku-5-5"
MIN_LAENGE, MAX_LAENGE = 80, 4000          # kürzer/länger: vermutlich kein Klappentext
GOOGLE = "https://www.googleapis.com/books/v1/volumes"
OPENLIBRARY = "https://openlibrary.org"
GOOGLE_KEY = ""                            # eigener Google-Books-API-Schlüssel (Einstellung google_key), "" = ohne
QUELLE_META = "bookbench:blurb-source"        # Herkunft des Klappentexts im content.opf
QUELLE_META_ALT = "kobo-werkstatt:blurb-source"   # Name bis 0.24, wird weiter gelesen

LEXICANUM = "https://wh40k.lexicanum.com/wiki/"
STANDARD_PROFILE = [
    {"id": "lexicanum", "name": "Lexicanum (Warhammer 40,000)", "aktiv": True,
     "verlag": "Black Library, Games Workshop", "reihe": "Warhammer, Horus Heresy, Siege of Terra, Primarchs",
     "autor": "",
     "thema": "Warhammer 40,000 / Horus Heresy",
     "seiten": "\n".join([LEXICANUM + "{base}_(Omnibus)", LEXICANUM + "{base}_(Anthology)"]
                         + [LEXICANUM + "{title}_(%s)" % k for k in ("Novel", "Anthology", "Omnibus", "Novella")]
                         + [LEXICANUM + "{title}", "https://warhammer40k.fandom.com/wiki/{title}"]),
     "domains": "", "abschnitt": 'Lexicanum: "Cover Description"; Fandom: "Official Description", "Description" '
                                 'or "Synopsis"',
     "websuche": True},
    {"id": "web", "name": "Web search", "aktiv": True, "verlag": "", "reihe": "", "autor": "",
     "thema": "", "seiten": "", "domains": "", "abschnitt": "", "websuche": True},
]
LEERES_PROFIL = {"id": "", "name": "", "aktiv": True, "verlag": "", "reihe": "", "autor": "", "thema": "",
                 "seiten": "", "domains": "", "abschnitt": "", "websuche": True}

SYSTEM = """You look up the OFFICIAL publisher blurb (back-cover text) of a book{thema}.
You get the book's title, author, series and language{kandidaten_kurz}.
{schritte}
Copy the blurb VERBATIM. Do not summarise, shorten, translate or add anything. Keep the paragraph breaks.
If a page only has a plot summary written by wiki editors or readers (not the publisher blurb), that does NOT count.
Reader reviews do not count either. Make sure the page is about THIS book (title and author).
{sprache}
Return ONE JSON object and nothing else:
{{"blurb": "paragraph one\\n\\nparagraph two", "source": "<URL you took it from>"}}
or, if you found no publisher blurb: {{"none": true}}"""


# ---------------------------------------------------------------- Metadaten
def read_opf(z):
    container = z.read("META-INF/container.xml").decode("utf-8", "replace")
    opf_path = re.search(r'full-path="([^"]+)"', container).group(1)
    return opf_path, z.read(opf_path).decode("utf-8-sig", "replace")


def _dc(opf, tag):
    m = re.search(r"<dc:%s\b[^>]*>(.*?)</dc:%s>" % (tag, tag), opf, re.S)
    return clean(m.group(1)) if m else ""


def book_info(opf):
    series = ""
    m = re.search(r"""<meta\b[^>]*name=["']calibre:series["'][^>]*content=["']([^"']*)""", opf) or \
        re.search(r"""<meta\b[^>]*content=["']([^"']*)["'][^>]*name=["']calibre:series["']""", opf)
    if m:
        series = clean(m.group(1))
    desc = re.search(r"<dc:description\b[^>]*>(.*?)</dc:description>", opf, re.S)
    return _dc(opf, "title"), _dc(opf, "creator"), series, clean(desc.group(1)) if desc else ""


def isbn_aus(opf):
    """ISBN aus dc:identifier (scheme ISBN, urn:isbn: oder einfach 10/13 Ziffern), sonst ""."""
    for attrs, wert in re.findall(r"<dc:identifier\b([^>]*)>(.*?)</dc:identifier>", opf, re.S):
        w = clean(wert)
        if re.search(r"""scheme=["']isbn["']""", attrs, re.I) or w.lower().startswith(("urn:isbn:", "isbn:")) \
                or re.fullmatch(r"(97[89])?[\d-]{9,13}[\dXx]", w):
            ziffern = re.sub(r"[^\dXx]", "", w.split(":")[-1]).upper()
            if len(ziffern) in (10, 13):
                return ziffern
    return ""


def book_extra(opf):
    """(Verlag, ISBN, Sprache) aus dem content.opf; Sprache als zweibuchstabiger Code ("en", "de")."""
    sprache = _dc(opf, "language").lower().replace("_", "-").split("-")[0]
    return _dc(opf, "publisher"), isbn_aus(opf), sprache if len(sprache) in (2, 3) else ""


def source_aus(opf):
    m = re.search(r"""<meta\b[^>]*name=["'](?:%s|%s)["'][^>]*>""" % (re.escape(QUELLE_META), re.escape(QUELLE_META_ALT)), opf)
    c = re.search(r"""content=["']([^"']*)["']""", m.group(0)) if m else None
    return html.unescape(c.group(1)) if c else ""


def with_description(opf, blurb, source=None):
    """Klappentext als <dc:description> eintragen, im selben Format wie Calibre (HTML, maskiert).
    source: Herkunft als eigenes <meta> (None = nicht anfassen, "" = entfernen)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", blurb) if p.strip()]
    inner = html.escape("".join(f"<p>{html.escape(p)}</p>" for p in paras), quote=False)
    tag = f"<dc:description>{inner}</dc:description>"
    if re.search(r"<dc:description\b[^>]*/>|<dc:description\b[^>]*>.*?</dc:description>", opf, re.S):
        opf = re.sub(r"<dc:description\b[^>]*/>|<dc:description\b[^>]*>.*?</dc:description>",
                     lambda m: tag, opf, count=1, flags=re.S)
    else:
        if "xmlns:dc" not in opf:                      # Namensraum fehlt: am <metadata>-Tag ergänzen
            m = re.search(r"<((\w+:)?metadata)\b", opf)
            if not m:
                return None
            opf = opf[:m.end()] + ' xmlns:dc="http://purl.org/dc/elements/1.1/"' + opf[m.end():]
        m = re.search(r"</(\w+:)?metadata>", opf)
        if not m:
            return None
        opf = opf[:m.start()] + tag + "\n" + opf[m.start():]
    return opf if source is None else with_source(opf, source)


def with_source(opf, source):
    opf = re.sub(r"""\s*<meta\b[^>]*name=["'](?:%s|%s)["'][^>]*/?>""" % (re.escape(QUELLE_META), re.escape(QUELLE_META_ALT)),
                 "", opf)
    if not source:
        return opf
    m = re.search(r"</(\w+:)?metadata>", opf)
    if not m:
        return opf
    neu = f'<meta name="{QUELLE_META}" content="{html.escape(source, quote=True)}"/>\n'
    return opf[:m.start()] + neu + opf[m.start():]


def source_name(source):
    """Kurzer Name für Spalten: Host einer URL ohne www., sonst der Text selbst."""
    if source.startswith(("http://", "https://")):
        host = urlparse(source).netloc.lower()
        return {"www.googleapis.com": "Google Books", "books.google.com": "Google Books",
                "openlibrary.org": "Open Library"}.get(host, host[4:] if host.startswith("www.") else host)
    return source


# ---------------------------------------------------------------- Vergleichen
def _norm(s):
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s.casefold())
    return " ".join(re.findall(r"\w+", s))


def _titel_passt(gesucht, gefunden):
    a, b = _norm(gesucht), _norm(gefunden)
    if not a or not b:
        return False
    return a == b or a.startswith(b + " ") or b.startswith(a + " ")


def _autor_passt(gesucht, gefundene):
    if not gesucht:
        return True
    nach = set(_norm(gesucht).split()) - {"and", "und"}
    return any(nach & set(_norm(g).split()) for g in gefundene)


def _text(beschreibung):
    """Beschreibung aus einer API (oft HTML) -> Text mit Absätzen."""
    t = re.sub(r"(?i)<br\s*/?>", "\n", beschreibung or "")
    t = re.sub(r"(?i)</p\s*>|</div\s*>", "\n\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n\s*", "\n\n", t).strip()
    t = re.sub(r"\s*\(\[source\]\[\d+\]\)\s*$|\s*-{3,}.*$", "", t, flags=re.S)   # Open-Library-Anhänge
    return t


def _brauchbar(t):
    return t if MIN_LAENGE <= len(t) <= MAX_LAENGE else ""


# ---------------------------------------------------------------- kostenlose Quellen
def _json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Bookbench (blurb lookup)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def google_parameter(p):
    """Anfrage-Parameter für Google Books, mit eigenem Schlüssel, wenn einer eingetragen ist."""
    return {**p, "key": GOOGLE_KEY.strip()} if GOOGLE_KEY.strip() else p


def fehler_text(e):
    """Lesbarer Grund für einen Fehler einer kostenlosen Quelle (HTTP 429/403 erklärt)."""
    code = getattr(e, "code", None)
    if code == 429:
        return (_("daily quota of your Google key used up (429)") if GOOGLE_KEY.strip() else
                _("daily quota used up (429) - shared by everyone without an own key"))
    if code in (400, 403) and GOOGLE_KEY.strip():
        return _("key rejected ({code}) - check it in Settings > Books > Blurbs").format(code=code)
    return str(e)


def google_books(titel, autor, isbn="", sprache="", basis=None, bericht=None):
    """bericht (dict, optional): "gefunden" = True, wenn das Buch da ist, aber ohne brauchbaren Text."""
    basis = basis or GOOGLE
    anfragen = []
    if isbn:
        anfragen.append(f"isbn:{isbn}")
    q = f'intitle:"{titel}"' + (f' inauthor:"{autor.split(",")[0]}"' if autor else "")
    anfragen.append(q)
    for a in anfragen:
        daten = _json(f"{basis}?" + urllib.parse.urlencode(google_parameter(
            {"q": a, "maxResults": 10, "printType": "books"})))
        treffer = []
        for nr, item in enumerate(daten.get("items") or []):
            v = item.get("volumeInfo") or {}
            if not (_titel_passt(titel, v.get("title", "")) and _autor_passt(autor, v.get("authors") or [])):
                continue                                # auch bei der ISBN: Begleitbücher u. Ä. aussortieren
            if bericht is not None:
                bericht["gefunden"] = True
            t = _brauchbar(_text(v.get("description", "")))
            if t:
                treffer.append((v.get("language") != sprache if sprache else False, nr, t,
                                v.get("canonicalVolumeLink") or v.get("infoLink") or
                                f"https://books.google.com/books?id={item.get('id', '')}"))
        if treffer:
            treffer.sort(key=lambda x: x[:2])          # passende Sprache zuerst, sonst wie Google sortiert
            return {"blurb": treffer[0][2], "source": treffer[0][3]}
    return None


def open_library(titel, autor, isbn="", sprache="", basis=None, bericht=None):
    basis = basis or OPENLIBRARY
    werke = []
    if isbn:
        try:
            ed = _json(f"{basis}/isbn/{isbn}.json")
            werke += [w["key"] for w in ed.get("works") or [] if w.get("key")]
            if bericht is not None:
                bericht["gefunden"] = True
            if ed.get("description"):
                t = _brauchbar(_text(ed["description"] if isinstance(ed["description"], str)
                                     else ed["description"].get("value", "")))
                if t:
                    return {"blurb": t, "source": f"{basis}{ed.get('key', '')}"}
        except Exception:                               # 404: ISBN unbekannt
            pass
    if not werke:
        p = {"title": titel, "fields": "key,title,author_name,language", "limit": 5}
        if autor:
            p["author"] = autor.split(",")[0]
        daten = _json(f"{basis}/search.json?" + urllib.parse.urlencode(p))
        for d in daten.get("docs") or []:
            if _titel_passt(titel, d.get("title", "")) and _autor_passt(autor, d.get("author_name") or []):
                werke.append(d["key"])
    if werke and bericht is not None:
        bericht["gefunden"] = True
    for key in werke[:3]:
        w = _json(f"{basis}{key}.json")
        d = w.get("description")
        t = _brauchbar(_text(d if isinstance(d, str) else (d or {}).get("value", "")))
        if t:
            return {"blurb": t, "source": f"{basis}{key}"}
    return None


# Ergebnis je Quelle (bericht in free_look_up): Kennung -> Bedeutung
TREFFER, KEIN_TEXT, NICHT_GEFUNDEN, FEHLER = "treffer", "kein_text", "nicht_gefunden", "fehler"


def free_look_up(titel, autor, isbn="", sprache="", quellen=None, bericht=None):
    """Erst Google Books, dann Open Library. Netzfehler einer Quelle -> nächste Quelle.
    Gibt (Treffer oder None, [Fehlertexte]) zurück. bericht (Liste, optional) bekommt je gefragter Quelle
    (Name, Kennung, Fehlertext): TREFFER, KEIN_TEXT (Buch da, aber ohne Klappentext), NICHT_GEFUNDEN, FEHLER."""
    fehler = []
    for name, f in quellen or (("Google Books", google_books), ("Open Library", open_library)):
        info = {}
        try:
            if "bericht" in inspect.signature(f).parameters:
                r = f(titel, autor, isbn, sprache, bericht=info)
            else:                                       # Quelle ohne bericht-Parameter (Tests, eigene)
                r = f(titel, autor, isbn, sprache)
        except Exception as e:
            fehler.append(f"{name}: {fehler_text(e)}")
            if bericht is not None:
                bericht.append((name, FEHLER, fehler_text(e)))
            continue
        if bericht is not None:
            bericht.append((name, TREFFER if r else KEIN_TEXT if info.get("gefunden") else NICHT_GEFUNDEN, ""))
        if r:
            return r, fehler
    return None, fehler


# ---------------------------------------------------------------- Profile
def _teile(s):
    return [t.strip().casefold() for t in (s or "").split(",") if t.strip()]


def profile_matches(p, verlag, reihe, autor):
    """Leere Filter: passt immer. Sonst reicht ein Treffer in einem der ausgefüllten Felder."""
    gefuellt = False
    for feld, wert in (("verlag", verlag), ("reihe", reihe), ("autor", autor)):
        teile = _teile(p.get(feld))
        gefuellt = gefuellt or bool(teile)
        if any(t in (wert or "").casefold() for t in teile):
            return True
    return not gefuellt


def profile_for(profile, verlag, reihe, autor):
    """Erstes aktive Profil, dessen Filter passt, oder None."""
    for p in profile or []:
        if p.get("aktiv", True) and profile_matches(p, verlag, reihe, autor):
            return {**LEERES_PROFIL, **p}
    return None


def profile_id(p):
    """Kennung für den Zwischenspeicher: ändert sich, wenn sich Seiten/Suche ändern."""
    return p.get("id") or re.sub(r"\W+", "-", p.get("name", "").casefold()).strip("-") or "profil"


def _slug(s):
    return quote(s.replace(" ", "_"), safe="_()',-:")


def candidates(profil, titel, autor="", reihe=""):
    base = re.sub(r"\s*[-:]\s*the omnibus$|\s+the omnibus$|\s+omnibus$", "", titel, flags=re.I)
    werte = {"title": _slug(titel), "base": _slug(base), "author": _slug(autor.split(",")[0]),
             "series": _slug(reihe), "title_q": quote(titel), "author_q": quote(autor.split(",")[0])}
    out = []
    for v in (profil.get("seiten") or "").splitlines():
        v = v.strip()
        if not v or ("{base}" in v and base == titel) or ("{series" in v and not reihe):
            continue
        try:
            out.append(v.format(**werte))
        except (KeyError, IndexError, ValueError):     # unbekannter Platzhalter: Vorlage auslassen
            continue
    return list(dict.fromkeys(out))[:9]


def domains(profil):
    hosts = [urlparse(v.strip().split("{")[0]).netloc for v in (profil.get("seiten") or "").splitlines()
             if v.strip().startswith(("http://", "https://"))]
    for d in (profil.get("domains") or "").replace(",", "\n").splitlines():
        d = d.strip()
        if d:
            hosts.append(urlparse(d).netloc if "//" in d else d.split("/")[0])
    return list(dict.fromkeys(h.lower() for h in hosts if h))


def system_prompt(profil, sprache, kandidaten):
    hosts = domains(profil)
    schritte = []
    if kandidaten:
        schritte.append("Fetch the candidate URLs in order with web_fetch until you find the page about THIS book.")
    if profil.get("abschnitt"):
        schritte.append(f"On these sites the blurb is usually in this section: {profil['abschnitt']}.")
    if profil.get("websuche"):
        if hosts:
            schritte.append(("If no candidate works, search" if kandidaten else "Search") +
                            " once and fetch the best result.")
        else:
            schritte.append(("If no candidate works, search the web" if kandidaten else "Search the web") +
                            " (at most twice) and fetch the best results. Prefer the publisher's own page, then "
                            "big bookshops (product description), then wikis that quote the back cover.")
    return SYSTEM.format(
        thema=f" ({profil['thema']})" if profil.get("thema") else "",
        kandidaten_kurz=", plus candidate URLs" if kandidaten else "",
        schritte="\n".join(schritte),
        sprache=(f"The book is in the language with code '{sprache}'. Take the blurb of the edition in that "
                 "language if there is one; otherwise none.") if sprache and sprache != "en" else
                "Take the blurb of the English edition.")


# ---------------------------------------------------------------- Claude
def parse(message):
    texts = [b.text for b in message.content if getattr(b, "type", "") == "text"]
    for t in reversed(texts):
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group())
            except ValueError:
                continue
    return None


def look_up(client, args, title, author, series, profil=None, sprache=""):
    profil = {**LEERES_PROFIL, **(profil or STANDARD_PROFILE[0])}
    kandidaten = candidates(profil, title, author, series)
    hosts = domains(profil)
    if not kandidaten and not profil.get("websuche"):
        return None                                     # Profil ohne Seiten und ohne Suche: nichts zu tun
    fetch = {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 5, "max_content_tokens": 15000}
    if hosts:
        fetch["allowed_domains"] = hosts
    tools = [fetch]
    if profil.get("websuche"):
        suche = {"type": "web_search_20250305", "name": "web_search", "max_uses": 1 if hosts else 2}
        if hosts:
            suche["allowed_domains"] = hosts
        tools.append(suche)
    user = (f"Title: {title}\nAuthor: {author or 'unknown'}\nSeries: {series or 'unknown'}\n"
            f"Language: {sprache or 'unknown'}\n")
    if kandidaten:
        user += "\nCandidate URLs:\n" + "\n".join(kandidaten)
    p = {"model": args.model, "max_tokens": 8000, "system": system_prompt(profil, sprache, kandidaten),
         "tools": tools, "messages": [{"role": "user", "content": user}]}
    msg = client.messages.create(**p)
    for __ in range(2):                                 # pause_turn: Claude will weitermachen
        if getattr(msg, "stop_reason", None) != "pause_turn":
            break
        p["messages"] = p["messages"][:1] + [{"role": "assistant", "content": msg.content}]
        msg = client.messages.create(**p)
    data = parse(msg) or {}
    blurb = (data.get("blurb") or "").strip()
    if not blurb or data.get("none") or not _brauchbar(blurb):
        return None
    return {"blurb": blurb, "source": data.get("source", "")}
