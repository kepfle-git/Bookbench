#!/usr/bin/env python3
"""
wikidict - baut aus einem Wiki (MediaWiki, z.B. ein Fandom-Wiki) ein persoenliches
Woerterbuch (StarDict-Format, z.B. fuer KOReader) und gleicht es optional ueber Claudes
Web-Fetch mit einer zweiten Seite ab.

Thema, Wiki, Gegencheck-Seite, Name und Dateiname stehen als Profil in der Datenbank
(--topic, --wiki, --check-site, --name, --stem setzen und merken es). Beim ersten Lauf in einem
neuen Arbeitsordner sind --wiki und --topic noetig. Bookbench verwaltet mehrere
solche Woerterbuecher.

Beispiel:
  wikidict.py --workdir sw --wiki https://starwars.fandom.com --topic "Star Wars Legends" all ~/Buecher

Ablauf (jeder Schritt ist ein eigenes Kommando und merkt sich seinen Stand
in einer SQLite-Datei, man kann also jederzeit abbrechen und weitermachen):

  check      prueft, ob die API des Wikis erreichbar ist
  titles     laedt die Liste aller Artikeltitel + Weiterleitungen
  scan DIR   sucht in deinen EPUBs (lokal!) nach diesen Titeln
  fetch      laedt nur die Artikel, die in deinen Buechern vorkommen
  summarize  laesst Claude aus jedem Artikel einen strukturierten Eintrag bauen
  crosscheck gleicht Eintraege mit der Gegencheck-Seite ab (Claude laedt die Seiten, robots.txt wird beachtet);
             mit --gaps auch Namen aus deinen Buechern, die das Wiki nicht kennt
  build      schreibt die StarDict-Dateien (.ifo/.idx/.dict/.syn)
             (mit den eigenen Eintraegen aus von Bookbench, Tabelle own)
  all DIR    titles bis build nacheinander (ohne crosscheck)

Buchtext verlaesst den Rechner nie: an die KI gehen nur Wiki-Texte und Namen.
"""
import argparse
import hashlib
import html
import json
import os
import re
import sqlite3
import struct
import sys
import time
import zipfile
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path

if __package__ in (None, ""):          # als Skript gestartet (python bookbench/dictionary/wikidict.py)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bookbench.i18n import _  # noqa: E402

DB_NAME = "wikidict.sqlite"
DB_ALT = "wh40kdict.sqlite"         # Name bis Werkstatt 0.13; solche Datenbanken bleiben, wo sie sind
DB_NAMEN = (DB_NAME, DB_ALT)
PROFIL_VERSION = "2"

# Profil des Woerterbuchs; profil_laden() setzt es aus der Datenbank (meta "profil")
STANDARD_PROFIL = {"topic": "", "wiki": "", "check_site": "", "check_name": "",
                   "name": "Wiki Dictionary", "stem": "wiki-dict", "spoilers": "mild"}
# Bis Version 1 galt ohne gespeicherte Angaben das Warhammer-Profil. Alte Datenbanken bekommen
# es beim ersten Oeffnen fest eingetragen (migrieren()), damit sie sich nicht aendern.
ALT_PROFIL = {"topic": "Warhammer 40,000 / Horus Heresy", "wiki": "https://warhammer40k.fandom.com",
              "check_site": "https://wh40k.lexicanum.com/wiki/", "check_name": "Lexicanum",
              "name": "WH40k Dictionary", "stem": "wh40k-dict", "spoilers": "mild"}
PROFIL = dict(STANDARD_PROFIL)


def db_datei(workdir):
    """Datenbank im Arbeitsordner: die alte (wh40kdict.sqlite), wenn nur sie da ist, sonst die neue."""
    workdir = Path(workdir)
    return workdir / DB_ALT if (workdir / DB_ALT).exists() and not (workdir / DB_NAME).exists() \
        else workdir / DB_NAME


def hat_inhalt(db):
    return any(db.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone() for t in ("titles", "entries", "checked"))


def alt_profil_ergaenzen(gespeichert, art, inhalt):
    """Profil einer Datenbank von vor Version 2: fehlende Werte kamen damals aus dem Warhammer-
    Standard. Bei Wiki-Woerterbuechern (oder alten ohne Art, aber mit Inhalt) bleibt das so."""
    if art == "wiki" or (not art and inhalt):
        return {**ALT_PROFIL, **gespeichert}
    if art == "leer":                       # Name und Dateiname kamen auch hier aus dem Standard
        return {"name": ALT_PROFIL["name"], "stem": ALT_PROFIL["stem"], **gespeichert}
    return dict(gespeichert)


def migrieren(db):
    """Einmalig fuer Datenbanken von vor Version 2: Profil fest eintragen, "lexicanum" -> "verified"."""
    if meta_get(db, "profil_version") == PROFIL_VERSION:
        return
    try:
        gespeichert = json.loads(meta_get(db, "profil", "{}") or "{}")
    except ValueError:
        gespeichert = {}
    profil = alt_profil_ergaenzen(gespeichert, meta_get(db, "art"), hat_inhalt(db))
    if profil:
        db.execute("INSERT OR REPLACE INTO meta VALUES('profil', ?)", (json.dumps(profil, ensure_ascii=False),))
    for key, kind, data in db.execute("SELECT key, kind, data FROM checked").fetchall():
        try:
            d = json.loads(data)
        except ValueError:
            continue
        if isinstance(d, dict) and "lexicanum" in d:
            d["verified"] = d.pop("lexicanum")
            db.execute("UPDATE checked SET data=? WHERE key=? AND kind=?",
                       (json.dumps(d, ensure_ascii=False), key, kind))
    meta_set(db, "profil_version", PROFIL_VERSION)


def profil_laden(db, aenderungen=None):
    """Profil aus der Datenbank, mit aenderungen (nur gesetzte Werte) ergaenzt und gespeichert.
    Setzt PROFIL fuer diesen Lauf und gibt es zurueck."""
    global PROFIL
    try:
        gespeichert = json.loads(meta_get(db, "profil", "{}") or "{}")
    except ValueError:
        gespeichert = {}
    neu = {k: v for k, v in (aenderungen or {}).items() if v is not None}
    if "wiki" in neu and neu["wiki"].rstrip("/") != (gespeichert.get("wiki") or "").rstrip("/"):
        db.execute("DELETE FROM meta WHERE k='api_url'")    # andere Seite, andere API
    if neu.get("check_site") is not None and "check_name" not in neu:
        from urllib.parse import urlparse        # Name der zweiten Quelle fuer Texte: ihr Host
        neu["check_name"] = urlparse(neu["check_site"]).netloc or "-"
    if neu:
        gespeichert.update(neu)
        meta_set(db, "profil", json.dumps(gespeichert, ensure_ascii=False))
    PROFIL = {**STANDARD_PROFIL, **gespeichert}
    return PROFIL


def thema():
    return PROFIL.get("topic") or "fiction"


def check_host():
    from urllib.parse import urlparse
    return urlparse(PROFIL.get("check_site") or "").netloc


def wiki_host():
    return (PROFIL.get("wiki") or "").split("//")[-1].rstrip("/") or "wiki"
DEFAULT_MODEL = "claude-haiku-5-5"
# Grobe Preise in $ pro Million Tokens (Haiku 5.5, Stand Nov 2026), nur fuer die Schaetzung.
PRICE = {"batch": (0.05, 0.25), "sync": (0.10, 0.50)}

CATEGORIES = ["Person", "Place", "Faction", "Organisation", "Technology", "Vessel",
              "Species", "Term", "Event", "Publication", "Disambiguation", "Other"]
DROP_SECTIONS = {"sources", "source", "references", "see also", "related articles",
                 "related article", "gallery", "external links", "miniatures",
                 "related videos", "notes", "footnotes"}
STOPWORDS = set("the a an of and or in on at to for by with from as is it he she we you i "
                "this that these those his her its their our my no not".split())


# ---------------------------------------------------------------- Datenbank

def open_db(workdir: Path) -> sqlite3.Connection:
    workdir.mkdir(parents=True, exist_ok=True)
    datei = db_datei(workdir)
    neu = not datei.exists()
    db = sqlite3.connect(datei)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS titles(title TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS redirects(src TEXT PRIMARY KEY, dst TEXT);
        CREATE TABLE IF NOT EXISTS mentions(title TEXT, book TEXT, n INTEGER,
                                            PRIMARY KEY(title, book));
        CREATE TABLE IF NOT EXISTS articles(title TEXT PRIMARY KEY, text TEXT);
        CREATE TABLE IF NOT EXISTS entries(title TEXT PRIMARY KEY, data TEXT,
                                           model TEXT, spoilers TEXT);
        CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY, done INTEGER DEFAULT 0,
                                           model TEXT, spoilers TEXT);
        CREATE TABLE IF NOT EXISTS checked(key TEXT, kind TEXT, data TEXT, status TEXT,
                                           PRIMARY KEY(key, kind));
        CREATE TABLE IF NOT EXISTS gaps(name TEXT, book TEXT, n INTEGER, PRIMARY KEY(name, book));
        -- Kobo-Werkstatt: eigene bzw. von Hand geaenderte Eintraege (gewinnen immer; data
        -- {"deleted": true} nimmt einen Eintrag heraus) und Namen, die nicht mehr als fehlend gelten
        CREATE TABLE IF NOT EXISTS own(title TEXT PRIMARY KEY, data TEXT, source TEXT, changed TEXT);
        CREATE TABLE IF NOT EXISTS ignored(name TEXT PRIMARY KEY);
    """)
    try:
        db.execute("ALTER TABLE batches ADD COLUMN kind TEXT DEFAULT 'sum'")
    except sqlite3.OperationalError:
        pass                                # Spalte gibt es schon
    if neu:
        meta_set(db, "profil_version", PROFIL_VERSION)
    else:
        migrieren(db)
    return db


def meta_get(db, k, default=None):
    row = db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return row[0] if row else default


def meta_set(db, k, v):
    db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, v))
    db.commit()


# ---------------------------------------------------------------- Wiki (MediaWiki-API)

class Wiki:
    def __init__(self, db, base, user_agent, delay):
        import requests
        self.db, self.base, self.delay = db, base.rstrip("/"), delay
        self.s = requests.Session()
        self.s.headers["User-Agent"] = user_agent
        self._last = 0.0

    def _get(self, url, params=None):
        for attempt in range(5):
            wait = self._last + self.delay - time.time()
            if wait > 0:
                time.sleep(wait)          # Server schonen: max. 1 Anfrage pro --delay Sekunden
            self._last = time.time()
            r = self.s.get(url, params=params, timeout=60)
            if r.status_code in (429, 502, 503, 504):
                time.sleep(10 * (attempt + 1))
                continue
            return r
        return r

    def api_url(self):
        url = meta_get(self.db, "api_url")
        if url:
            return url
        probe = {"action": "query", "meta": "siteinfo", "format": "json"}
        for path in ("/mediawiki/api.php", "/api.php", "/w/api.php"):
            r = self._get(self.base + path, probe)
            if r.ok and r.text.lstrip().startswith("{"):
                meta_set(self.db, "api_url", self.base + path)
                return self.base + path
            if r.status_code == 403:
                sys.exit(_("403 from {url} - the server blocks the script. Try --user-agent '<browser id>' or try "
                           "again later.").format(url=self.base + path))
        # Letzter Versuch: jede MediaWiki-Seite verlinkt ihre API im <head> (EditURI)
        r = self._get(self.base + "/wiki/Main_Page")
        m = re.search(r'rel="EditURI"[^>]*href="([^"?]+api\.php)', r.text)
        if not m:
            sys.exit(_("Could not find the API (api.php). Try another base URL with --wiki."))
        url = m.group(1)
        if url.startswith("//"):
            url = "https:" + url
        meta_set(self.db, "api_url", url)
        return url

    def query(self, **params):
        """Fuehrt eine query aus und folgt der Fortsetzung (neue und alte MediaWiki-Variante)."""
        params = {"action": "query", "format": "json", "continue": "", **params}
        url = self.api_url()
        while True:
            r = self._get(url, params)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                sys.exit(_("API error: {fehler}").format(fehler=data["error"]))
            yield data
            if "continue" in data:
                params.update(data["continue"])
            elif "query-continue" in data:
                for v in data["query-continue"].values():
                    params.update(v)
            else:
                return


def cmd_check(db, wiki, args):
    url = wiki.api_url()
    info = next(wiki.query(meta="siteinfo", siprop="general|statistics"))["query"]
    print(_("API found: {url}").format(url=url))
    print(f"  {info['general'].get('sitename')} - {info['general'].get('generator')}")
    print("  " + _("Articles: {n}").format(n=info.get("statistics", {}).get("articles")))


def cmd_titles(db, wiki, args):
    n = 0
    for data in wiki.query(list="allpages", apnamespace=0, apfilterredir="nonredirects", aplimit="max"):
        rows = [(p["title"],) for p in data["query"]["allpages"]]
        db.executemany("INSERT OR IGNORE INTO titles VALUES(?)", rows)
        db.commit()
        n += len(rows)
        print("\r  " + _("Titles: {n}").format(n=n), end="", flush=True)
    print()
    # Weiterleitungen in zwei Schritten: erst alle Weiterleitungsseiten auflisten,
    # dann in 50er-Paketen fragen, wohin sie zeigen. (Neuere MediaWikis erlauben
    # das nicht mehr in einer einzigen Abfrage.)
    src = []
    for data in wiki.query(list="allpages", apnamespace=0, apfilterredir="redirects", aplimit="max"):
        src += [p["title"] for p in data["query"]["allpages"]]
        print("\r  " + _("Redirect pages: {n}").format(n=len(src)), end="", flush=True)
    print()
    done = {s for (s,) in db.execute("SELECT src FROM redirects")}
    src = [s for s in src if s not in done]       # bei Abbruch und Neustart nicht alles nochmal
    for i in range(0, len(src), 50):
        rows = []
        for data in wiki.query(titles="|".join(src[i:i + 50]), redirects=1):
            rows += [(r["from"], r["to"].split("#")[0]) for r in data.get("query", {}).get("redirects", [])]
        db.executemany("INSERT OR REPLACE INTO redirects VALUES(?,?)", rows)
        db.commit()
        print("\r  " + _("Redirects resolved: {i}/{n}").format(i=min(i + 50, len(src)), n=len(src)), end="", flush=True)
    print()


# ---------------------------------------------------------------- EPUBs lokal durchsuchen

TOKEN = re.compile(r"[A-Za-z0-9À-ÿ]+(?:['’\-][A-Za-z0-9À-ÿ]+)*")
BLOCK_TAGS = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote", "title"}


def norm(s):
    return " ".join(t.lower().replace("’", "'") for t in TOKEN.findall(s))


def strip_paren(title):
    return re.sub(r"\s*\([^)]*\)\s*$", "", title)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in BLOCK_TAGS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in BLOCK_TAGS:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def read_epub(path):
    """Gibt (Buchtitel, Text) zurueck. Liest nur, schickt nichts irgendwohin."""
    title, parts = path.stem, []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            low = name.lower()
            if low.endswith(".opf"):
                m = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", z.read(name).decode("utf-8", "replace"), re.S)
                if m:
                    title = html.unescape(re.sub(r"\s+", " ", m.group(1)).strip()) or title
            elif low.endswith((".xhtml", ".html", ".htm")):
                p = _Text()
                p.feed(z.read(name).decode("utf-8", "replace"))
                parts.append("".join(p.out))
    return title, "\n".join(parts)


def variants(tok):
    """Wortformen, die auf denselben Titel zeigen sollen: Frodo's -> Frodo, swords -> sword."""
    out = [tok]
    if tok.endswith("'s"):
        out.append(tok[:-2])
    for b in list(out):
        if b.endswith("s") and len(b) > 3:
            out.append(b[:-1])
        if b.endswith("es") and len(b) > 4:
            out.append(b[:-2])
    return out


def build_keymap(db):
    """Schluessel (kleingeschrieben) -> Liste von Artikeltiteln."""
    titles = {t for (t,) in db.execute("SELECT title FROM titles")}
    keymap, paren = {}, defaultdict(list)
    for t in titles:
        base = strip_paren(t)
        if base != t:                       # "Rand (Character)" -> auch unter "Rand" findbar
            paren[norm(base)].append(t)
    for k, ts in paren.items():
        if len(ts) <= 4:
            keymap[k] = sorted(ts)
    for src, dst in db.execute("SELECT src, dst FROM redirects"):
        if dst in titles:
            keymap[norm(src)] = [dst]
    for t in titles:                        # direkter Titel gewinnt immer
        keymap[norm(t)] = [t]
    # Vor- und Nachnamen: In den Romanen steht meist nur "Frodo" oder "Baggins", nicht "Frodo Baggins".
    # Nur wenn der Name eindeutig zu einem Titel gehoert und kein normales englisches Wort ist.
    from wordfreq import zipf_frequency
    tok_titles = defaultdict(set)
    for t in titles:
        toks = strip_paren(t).split()
        if len(toks) >= 2:
            for tok in (toks[0], toks[-1]):
                if len(tok) >= 4 and tok[0].isupper() and not re.fullmatch(r"[IVXLC]+", tok):
                    tok_titles[norm(tok)].add(t)
    for k, ts in tok_titles.items():
        if len(ts) == 1 and k not in keymap and " " not in k and zipf_frequency(k, "en") < 3.0:
            keymap[k] = list(ts)
    for k in list(keymap):
        toks = k.split()
        if not k or len(toks) > 6 or (len(toks) == 1 and (len(k) < 3 or k.isdigit() or k in STOPWORDS)):
            del keymap[k]
    return keymap


def is_sentence_start(text, start):
    j = start - 1
    while j >= 0 and text[j] in " \t":
        j -= 1
    return j < 0 or text[j] in ".!?:\n\"'“”‘’"


def scan_text(text, keymap, first_len):
    counts, cap_mid, lower, cands = Counter(), Counter(), Counter(), Counter()
    ms = list(TOKEN.finditer(text))
    toks = [m.group().lower().replace("’", "'") for m in ms]
    n, i = len(toks), 0

    def capword(k):
        return ms[k].group()[0].isupper() and toks[k] not in STOPWORDS

    while i < n:
        t = toks[i]
        maxlen = max(first_len.get(t, 0), 1)
        hit = None
        for ln in range(min(maxlen, n - i), 0, -1):     # laengster Treffer zuerst
            head = toks[i:i + ln - 1]
            for v in variants(toks[i + ln - 1]):
                key = " ".join(head + [v])
                if key in keymap:
                    hit = (key, ln)
                    break
            if hit:
                break
        if not hit:
            # Unbekannter, grossgeschriebener Name mitten im Satz -> Kandidat fuer die Luecken-Suche.
            # Folgen wie "Minas Tirith" werden zusammengefasst (max. 3 Woerter).
            if capword(i) and not is_sentence_start(text, ms[i].start()):
                k = i + 1
                while (k < n and k - i < 3 and capword(k) and toks[k] not in keymap
                       and text[ms[k - 1].end():ms[k].start()].strip() == ""):
                    k += 1
                name = " ".join(m.group() for m in ms[i:k])
                name = re.sub(r"['’]s$", "", name)
                cands[name] += 1
                i = k
            else:
                i += 1
            continue
        key, ln = hit
        counts[key] += 1
        if ln == 1:
            # Fuer Einzelwoerter merken wir uns die Schreibweise mitten im Satz:
            # "the Shire" (gross) ist ein Eigenname, "an angel" (klein) nicht.
            start = ms[i].start()
            if text[start].isupper():
                if not is_sentence_start(text, start):
                    cap_mid[key] += 1
            else:
                lower[key] += 1
        i += ln
    return counts, cap_mid, lower, cands


def cmd_scan(db, wiki, args):
    from wordfreq import zipf_frequency
    keymap = build_keymap(db)
    if not keymap and meta_get(db, "art") != "leer":    # leeres Woerterbuch: nur Namen sammeln
        sys.exit(_("No titles in the database - run 'titles' first."))
    first_len = {}
    for k in keymap:
        toks = k.split()
        first_len[toks[0]] = max(first_len.get(toks[0], 0), len(toks))
    # KEPUBs sind EPUBs mit zusaetzlichen Kobo-<span>s; heissen meist .kepub.epub, manchmal nur .kepub
    root = Path(args.books).expanduser()
    files = sorted({f for pat in ("*.epub", "*.kepub") for f in root.rglob(pat)})
    if not files:
        sys.exit(_("No .epub/.kepub files found under {ordner}.").format(ordner=args.books))
    books = {}
    for f in files:
        try:
            title, text = read_epub(f)
        except Exception as e:
            print("  " + _("skipped ({fehler}): {name}").format(fehler=e, name=f.name))
            continue
        if title in books:                  # dasselbe Buch als EPUB und KEPUB -> die vollstaendigere Datei nehmen
            old_f, old_text = books[title]
            if len(old_text) >= len(text):
                print("  " + _("duplicate, skipped: {name}").format(name=f.name))
                continue
            print("  " + _("duplicate, skipped: {name}").format(name=old_f.name))
        books[title] = (f, text)
    per_book, cap_mid, lower, cand_book = {}, Counter(), Counter(), {}
    for title, (f, text) in books.items():
        c, cm, lo, ca = scan_text(text, keymap, first_len)
        per_book.setdefault(title, Counter()).update(c)
        cand_book.setdefault(title, Counter()).update(ca)
        cap_mid.update(cm)
        lower.update(lo)
        print(f"  {title}: " + _("{n} terms").format(n=len(c)))

    wd = Path(args.workdir)
    include = {norm(l) for l in _lines(wd / "include.txt")}
    exclude = {norm(l) for l in _lines(wd / "exclude.txt")}

    def keep(key):
        if key in exclude:
            return False
        if key in include or " " in key:
            return True
        if zipf_frequency(key, "en") < args.zipf:      # kein normales englisches Wort -> behalten
            return True
        return cap_mid[key] >= 3 and cap_mid[key] >= 4 * lower[key]

    db.execute("DELETE FROM mentions")
    kept = set()
    for book, counts in per_book.items():
        agg = Counter()
        for key, cnt in counts.items():
            if keep(key):
                for title in keymap[key]:
                    agg[title] += cnt
        kept.update(agg)
        db.executemany("INSERT OR REPLACE INTO mentions VALUES(?,?,?)",
                       [(t, book, c) for t, c in agg.items()])
    db.commit()
    print(_("{buecher} books, {artikel} wiki articles occur in them.").format(buecher=len(per_book), artikel=len(kept)))

    # Luecken: haeufige Namen, fuer die das Wiki keinen Artikel hat (fuer 'crosscheck --gaps').
    total = Counter()
    for ca in cand_book.values():
        total.update(ca)

    def gap_ok(name):
        if total[name] < args.min_gap or norm(name) in keymap or norm(name) in exclude:
            return False
        return any(len(t) >= 3 and not re.fullmatch(r"[IVXLC]+", t) and zipf_frequency(t.lower(), "en") < 3.0
                   for t in name.split())

    gaps = [g for g, __ in total.most_common() if gap_ok(g)][:args.gap_limit]
    gapset = set(gaps)
    db.execute("DELETE FROM gaps")
    for book, ca in cand_book.items():
        db.executemany("INSERT OR REPLACE INTO gaps VALUES(?,?,?)",
                       [(g, book, c) for g, c in ca.items() if g in gapset])
    db.commit()
    print(_("{n} frequent names without a wiki article found (candidates for 'crosscheck --gaps').").format(n=len(gaps)))


def _lines(path):
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


# ---------------------------------------------------------------- Artikel laden + saeubern

def clean_wikitext(src, limit):
    """Wikitext -> lesbarer Text. Infobox-Felder bleiben als 'Feld: Wert' erhalten."""
    import mwparserfromhell
    src = re.sub(r"<ref[^>]*?/>|<ref.*?</ref>|<gallery.*?</gallery>|<!--.*?-->", "", src, flags=re.S | re.I)
    code = mwparserfromhell.parse(src)
    info = []
    for t in code.filter_templates(recursive=False):
        named = [p for p in t.params if p.showkey]
        if len(named) >= 4:
            for p in named:
                v = re.sub(r"\s+", " ", p.value.strip_code()).strip()
                if v and len(v) < 200 and not re.search(r"\.(jpg|png|gif)$", v, re.I):
                    info.append(f"{str(p.name).strip()}: {v}")
    out = []
    for sec in code.get_sections(levels=[2], include_lead=True):
        heads = sec.filter_headings()
        if heads and str(heads[0].title).strip().lower() in DROP_SECTIONS:
            continue
        for link in sec.filter_wikilinks():
            if re.match(r"\s*(file|image|category|datei|bild)\s*:", str(link.title), re.I):
                try:
                    sec.remove(link)
                except ValueError:
                    pass
        out.append(sec.strip_code(normalize=True, collapse=True))
    body = re.sub(r"\n{3,}", "\n\n", "\n\n".join(out)).strip()
    text = ("Infobox:\n" + "\n".join(info) + "\n\n" if info else "") + body
    return text[:limit]


def cmd_fetch(db, wiki, args):
    want = [t for (t,) in db.execute(
        "SELECT DISTINCT title FROM mentions WHERE title NOT IN (SELECT title FROM articles)")]
    print(_("{n} articles to load").format(n=len(want)))
    for i in range(0, len(want), 20):
        chunk, got = want[i:i + 20], {}
        for data in wiki.query(prop="revisions", rvprop="content", rvslots="main", titles="|".join(chunk)):
            for page in data.get("query", {}).get("pages", {}).values():
                revs = page.get("revisions")
                if revs:
                    rev = revs[0]
                    raw = rev.get("slots", {}).get("main", {}).get("*") or rev.get("*") or ""
                    got[page["title"]] = raw
        for t in chunk:                      # nicht gefundene als leer merken, damit sie nicht ewig neu versucht werden
            try:
                text = clean_wikitext(got.get(t, ""), args.max_chars)
            except Exception as e:
                print("\n  " + _("Problem with '{titel}': {fehler}").format(titel=t, fehler=e))
                text = ""
            db.execute("INSERT OR REPLACE INTO articles VALUES(?,?)", (t, text))
        db.commit()
        print(f"\r  {min(i + 20, len(want))}/{len(want)}", end="", flush=True)
    print()


# ---------------------------------------------------------------- KI-Zusammenfassung

SPOILER_RULES = {
    "strict": "Do NOT describe plot events at all. Only say what/who this is, affiliation, role and "
              "general background that a reader would know when the subject is first introduced.",
    "mild": "Background and important events are welcome, but do NOT reveal: deaths, final fates, "
            "who betrays whom, secret identities, or how a specific novel ends. Exception: facts that are the "
            "basic public premise of the setting or series (what any blurb or introduction tells a new "
            "reader) are fine. When in doubt, leave it out.",
    "full": "No spoiler restrictions.",
}


def system_prompt(spoilers, words):
    return f"""You write entries for a personal {thema()} reader's dictionary.
You get one wiki article. Use ONLY information from that article; never add your own knowledge.

Return ONE JSON object and nothing else:
{{"category": one of {json.dumps(CATEGORIES)},
 "tagline": "one sentence, max 25 words: who or what this is",
 "sections": [{{"h": "heading", "t": "1-3 sentences"}}],
 "aliases": ["other names or titles used for this subject in the article"]}}

Headings to choose from, by category (use only those the article supports, in this order):
- Person: "Origin & background", "Significance", "Relationships", "Key events"
- Place: "Description", "Significance", "Key events"
- Faction / Organisation / Species: "Overview", "Role", "Notable members", "Key events"
- Technology / Vessel: "What it is", "Who uses it", "Notes"
- Term: "Meaning", "Context"
- Event: "What happened", "Who was involved", "Consequences"
- Disambiguation: one section per option, heading = the option's name, text = one line saying what it is
- Publication: real-world books, games, miniatures, authors (tagline only)

Length: about {words} words in total. Short article -> short entry; do not pad.
Write plain prose, in-universe, present tense where natural. No markdown, no source references.
If the page has no usable content, return {{"skip": true}}.

Spoiler policy: {SPOILER_RULES[spoilers]}"""


def cid(title):
    return hashlib.sha1(title.encode()).hexdigest()[:40]


def parse_reply(message):
    # Bei Tool-Nutzung gibt es mehrere Textbloecke; das JSON steht im letzten brauchbaren.
    texts = [b.text for b in message.content if getattr(b, "type", "") == "text"]
    data = None
    for text in reversed(texts):
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                data = json.loads(m.group())
                break
            except json.JSONDecodeError:
                continue
    if not isinstance(data, dict):
        return None
    if data.get("skip"):
        return {"skip": True}
    if data.get("category") not in CATEGORIES or not data.get("tagline"):
        return None
    data["sections"] = [s for s in data.get("sections", []) if isinstance(s, dict) and s.get("h") and s.get("t")]
    data["aliases"] = [a for a in data.get("aliases", []) if isinstance(a, str) and 1 < len(a) < 80]
    return data


def make_client():
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit(_("ANTHROPIC_API_KEY is not set (export ANTHROPIC_API_KEY=sk-ant-...)."))
    return anthropic.Anthropic()


def save_entry(db, title, data, args):
    db.execute("INSERT OR REPLACE INTO entries VALUES(?,?,?,?)",
               (title, json.dumps(data, ensure_ascii=False), args.model, args.spoilers))


def job_keys(db, kind):
    """custom_id -> Schluessel (Artikeltitel bzw. Name) fuer die drei Auftragsarten."""
    if kind == "check":
        return {cid("c:" + t): t for (t,) in db.execute("SELECT title FROM entries")}
    if kind == "gap":
        return {cid("g:" + n): n for (n,) in db.execute("SELECT DISTINCT name FROM gaps")}
    return {cid(t): t for (t,) in db.execute("SELECT title FROM articles")}


def handle_result(db, kind, key, message, args, errors):
    data = parse_reply(message)
    errors.update(fetch_errors(message))
    if not data:
        return False
    if kind == "sum":
        save_entry(db, key, data, args)
    else:
        if data.get("skip"):
            status = "skip"
        elif kind == "check":
            status = "ok" if data.get("verified", data.get("lexicanum")) else "not_found"   # lexicanum: Version 1
        else:
            status = "ok"
        db.execute("INSERT OR REPLACE INTO checked VALUES(?,?,?,?)",
                   (key, kind, json.dumps(data, ensure_ascii=False), status))
    return True


def collect_batch(db, client, batch_id, kind, args):
    by_cid = job_keys(db, kind)
    ok = bad = 0
    errors = Counter()
    for r in client.messages.batches.results(batch_id):
        key = by_cid.get(r.custom_id)
        if key and r.result.type == "succeeded" and handle_result(db, kind, key, r.result.message, args, errors):
            ok += 1
        else:
            bad += 1
    db.execute("UPDATE batches SET done=1 WHERE id=?", (batch_id,))
    db.commit()
    print("  " + _("Batch {id}: {ok} done, {bad} failed (retried in the next run)").format(id=batch_id, ok=ok, bad=bad))
    report_fetch_errors(errors)


def fetch_errors(message):
    """Fehlercodes des Web-Fetch-Tools (z.B. url_not_allowed, wenn robots.txt den Abruf verbietet)."""
    out = []
    for b in message.content:
        if getattr(b, "type", "") != "web_fetch_tool_result":
            continue
        c = getattr(b, "content", None)
        ctype = getattr(c, "type", None) or (c.get("type") if isinstance(c, dict) else "")
        if ctype and "error" in ctype:
            out.append(getattr(c, "error_code", None) or (c.get("error_code") if isinstance(c, dict) else "?"))
    return out


def report_fetch_errors(errors):
    if errors:
        print("  " + _("Fetch errors:"), ", ".join(f"{k} x{v}" for k, v in errors.most_common()))
        if errors.get("url_not_allowed"):
            print("  -> " + _("url_not_allowed means: {seite} does not allow this fetch (robots.txt).")
                  .format(seite=PROFIL["check_name"]))
        if errors.get("url_not_accessible"):
            print("  -> " + _("url_not_accessible usually means: there is no page under this name (normal for wrong "
                              "candidates)."))


def wait_for_batches(db, client, args):
    while True:
        open_ids = db.execute("SELECT id, COALESCE(kind, 'sum') FROM batches WHERE done=0").fetchall()
        if not open_ids:
            return
        for bid, kind in open_ids:
            b = client.messages.batches.retrieve(bid)
            if b.processing_status == "ended":
                collect_batch(db, client, bid, kind, args)
            else:
                c = b.request_counts
                print("  " + _("Batch {id}: {laeuft} in progress, {fertig} done ... (Ctrl+C is fine, 'summarize' "
                               "continues here later)").format(id=bid, laeuft=c.processing, fertig=c.succeeded))
        if db.execute("SELECT 1 FROM batches WHERE done=0").fetchone():
            time.sleep(args.poll)


def cmd_summarize(db, wiki, args):
    client = make_client()
    wait_for_batches(db, client, args)          # erst offene Batches von frueher einsammeln
    if args.redo:
        db.execute("DELETE FROM entries")
        db.commit()
    rows = db.execute("""SELECT a.title, a.text FROM articles a
                         JOIN (SELECT title, SUM(n) n FROM mentions GROUP BY title) m ON m.title=a.title
                         WHERE length(a.text) > 40 AND a.title NOT IN (SELECT title FROM entries)
                         ORDER BY m.n DESC""").fetchall()
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        print(_("Nothing to do - all articles already have an entry."))
        return
    system = system_prompt(args.spoilers, args.words)
    mode = "sync" if args.sync else "batch"
    tin = sum(len(t) for __, t in rows) / 4 + len(rows) * len(system) / 4
    tout = len(rows) * (args.words * 2 + 300)
    cost = tin / 1e6 * PRICE[mode][0] + tout / 1e6 * PRICE[mode][1]
    print(_("{n} articles, model {modell}, mode {modus}. Roughly ${kosten} (assuming Haiku 5.5 prices).").format(
        n=len(rows), modell=args.model, modus=mode, kosten=f"{cost:.2f}"))
    if not args.yes and input(_("Start? [y/N] ")).strip().lower() not in ("j", "y", "ja", "yes"):
        return

    def params(title, text):
        return {"model": args.model, "max_tokens": 8000, "system": system,
                "messages": [{"role": "user", "content": f"Article title: {title}\n\n{text}"}]}

    if args.sync:
        for i, (title, text) in enumerate(rows, 1):
            data = parse_reply(client.messages.create(**params(title, text)))
            if data:
                save_entry(db, title, data, args)
                db.commit()
            print(f"  [{i}/{len(rows)}] {title}: " + ("ok" if data else _("no usable answer")))
        return
    # Batch-API: halber Preis, dafuer asynchron (meist unter einer Stunde).
    for i in range(0, len(rows), 2000):
        reqs = [{"custom_id": cid(t), "params": params(t, x)} for t, x in rows[i:i + 2000]]
        b = client.messages.batches.create(requests=reqs)
        db.execute("INSERT INTO batches(id, model, spoilers, kind) VALUES(?,?,?,?)",
                   (b.id, args.model, args.spoilers, "sum"))
        db.commit()
        print("  " + _("Batch {id} sent ({n} articles)").format(id=b.id, n=len(reqs)))
    wait_for_batches(db, client, args)


# ---------------------------------------------------------------- Gegencheck (zweite Seite)


def pruef_url(title):
    from urllib.parse import quote
    return PROFIL["check_site"] + quote(title.replace(" ", "_"), safe="_()',-:")


def pruef_kandidaten(title, aliases=(), redirect_srcs=(), limit=6, plural=True):
    """Moegliche Seitennamen auf der Gegencheck-Seite: zwei Wikis benennen manches anders
    ("Immaterium" vs. "Warp", Kurz- vs. voller Name). Claude darf nur Adressen abrufen, die
    im Auftrag stehen, also geben wir ihm eine Auswahl mit."""
    names = [title, strip_paren(title)]
    if plural:                               # "Jedi Knights" <-> "Jedi Knight", aber nicht "Gandalfs"
        for n in (title, strip_paren(title)):
            names.append(n[:-1] if n.endswith("s") else n + "s")
    names += [a for a in aliases if 2 < len(a) < 60][:3]
    names += sorted(redirect_srcs, key=len)[:4]
    out, seen = [], set()
    for n in names:
        n = n.strip()
        key = n[:1].upper() + n[1:]          # MediaWiki: erster Buchstabe egal
        if n and key not in seen:
            seen.add(key)
            out.append(pruef_url(key))
    return out[:limit]


def check_prompt(spoilers, words):
    n = PROFIL["check_name"]
    return system_prompt(spoilers, words) + f"""

TASK VARIANT - CROSS-CHECK:
You get a DRAFT entry (written from another wiki) and a list of candidate {n} URLs, best guess first.
Fetch them with the web_fetch tool, in order, and stop at the first page that is about the same subject
(a page that does not exist just means: try the next one). {n} is the more reliable source.
- Correct anything the {n} page contradicts and add important facts the draft is missing.
  "Use ONLY information from the article" now means: the draft plus the {n} page.
- If the page is a disambiguation page, you may fetch one link from it that clearly matches the draft.
- Add "verified": true and "changes": [up to 3 short notes on what you changed; empty list if nothing].
- If none of the candidates works or they are about something else: return the draft unchanged
  with "verified": false.
Return only the JSON object."""


def gap_prompt(spoilers, words):
    n, t = PROFIL["check_name"], thema()
    return system_prompt(spoilers, words) + f"""

TASK VARIANT - NEW ENTRY:
You get a name that appears in {t} novels and candidate {n} URLs.
Fetch them with the web_fetch tool, in order, until one exists.
- If it is an article about this name (redirects are fine), write the entry from that page and add
  "title": "<the {n} article title>".
- If it is a disambiguation page, fetch the one option that clearly fits a novel character, place or term;
  if none clearly dominates, write a Disambiguation entry.
- If no candidate exists and you have a web_search tool, search once for the name ({n} only)
  and fetch the result that best fits a {t} novel character, place or term.
- If nothing fits, return {{"skip": true}}.
Return only the JSON object."""


def cmd_crosscheck(db, wiki, args):
    if not check_host():
        sys.exit(_("No cross-check set (profile check_site is empty, set it with --check-site)."))
    client = make_client()
    wait_for_batches(db, client, args)
    if args.redo:
        db.execute("DELETE FROM checked")
        db.commit()
    if args.retry_not_found:
        db.execute("DELETE FROM checked WHERE status IN ('not_found', 'skip')")
        db.commit()
    skip_cats = {c.strip() for c in args.skip_categories.split(",") if c.strip()}
    jobs = []
    redirs = defaultdict(list)
    for src, dst in db.execute("SELECT src, dst FROM redirects"):
        redirs[dst].append(src)

    def urls(cands):
        return f"Candidate {PROFIL['check_name']} URLs:\n" + "\n".join(cands)

    if not args.gaps_only:
        rows = db.execute("""SELECT e.title, e.data FROM entries e
                             JOIN (SELECT title, SUM(n) n FROM mentions GROUP BY title) m ON m.title=e.title
                             WHERE e.title NOT IN (SELECT key FROM checked WHERE kind='check')
                             ORDER BY m.n DESC""").fetchall()
        for title, raw in rows:
            data = json.loads(raw)
            if not data.get("skip") and data.get("category") not in skip_cats:
                draft = {k: data[k] for k in ("category", "tagline", "sections", "aliases") if k in data}
                cands = pruef_kandidaten(title, data.get("aliases", []), redirs.get(title, []),
                                       plural=data.get("category") != "Person")
                jobs.append(("check", title, urls(cands) + "\n\nDRAFT:\n" + json.dumps(draft, ensure_ascii=False)))
    gap_jobs = []
    if args.gaps or args.gaps_only:
        rows = db.execute("""SELECT name FROM gaps WHERE name NOT IN (SELECT key FROM checked WHERE kind='gap')
                             GROUP BY name ORDER BY SUM(n) DESC""").fetchall()
        gap_jobs = [("gap", n, f"Name: {n}\n" + urls(pruef_kandidaten(n, limit=3, plural=False))) for (n,) in rows]
    if args.limit:                          # beim Probelauf beide Sorten mischen
        half = args.limit // 2 if gap_jobs and jobs else args.limit
        jobs = jobs[:args.limit - min(half, len(gap_jobs))] + gap_jobs[:half]
    else:
        jobs += gap_jobs
    if not jobs:
        print(_("Nothing to do."))
        return

    prompts = {"check": check_prompt(args.spoilers, args.words), "gap": gap_prompt(args.spoilers, args.words)}
    tool = {"type": args.fetch_tool, "name": "web_fetch", "max_uses": 4,
            "allowed_domains": [check_host()], "max_content_tokens": args.fetch_tokens}

    search = {"type": "web_search_20250305", "name": "web_search", "max_uses": 1,
              "allowed_domains": [check_host()]}

    def params(kind, content):
        tools = [tool, search] if kind == "gap" and args.search else [tool]
        return {"model": args.model, "max_tokens": 8000, "system": prompts[kind], "tools": tools,
                "messages": [{"role": "user", "content": content}]}

    # Standard: eins nach dem anderen mit Pause. Ein Batch wuerde hunderte Abrufe gleichzeitig
    # an die Gegencheck-Seite schicken - das bremst mit too_many_requests, und hoeflich ist es auch nicht.
    mode = "batch" if args.batch else "sync"
    n_gap = sum(1 for j in jobs if j[0] == "gap")
    tin = len(jobs) * (args.fetch_tokens + len(prompts["check"]) / 2 + 600) + (n_gap * 3000 if args.search else 0)
    tout = len(jobs) * (args.words * 2 + 400)
    cost = tin / 1e6 * PRICE[mode][0] + tout / 1e6 * PRICE[mode][1]
    if args.search:
        cost += n_gap * 0.01                 # Websuche: 10 $ pro 1000 Suchen (nur wenn sie gebraucht wird)
    hours = len(jobs) * (12 + args.pause) / 3600
    print(_("Cross-check {n} entries, fill {luecken} gaps, mode {modus}. Roughly ${kosten}").format(
        n=len(jobs) - n_gap, luecken=n_gap, modus=mode, kosten=f"{cost:.2f}")
        + (", " + _("takes roughly {stunden} h.").format(stunden=f"{hours:.1f}") if mode == "sync" else "."))
    if not args.yes and input(_("Start? [y/N] ")).strip().lower() not in ("j", "y", "ja", "yes"):
        return

    if mode == "sync":
        import anthropic
        errors = Counter()
        faillog = Path(args.workdir) / "failed.jsonl"
        for i, (kind, key, content) in enumerate(jobs, 1):
            for attempt in range(4):
                try:
                    p = params(kind, content)
                    msg = client.messages.create(**p)
                    # pause_turn: Claude hat die Tool-Schleife unterbrochen und will weitermachen
                    for __ in range(2):
                        if getattr(msg, "stop_reason", None) != "pause_turn":
                            break
                        p["messages"] = p["messages"][:1] + [{"role": "assistant", "content": msg.content}]
                        msg = client.messages.create(**p)
                except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as e:
                    print("  " + _("API error ({fehler}), waiting {s} s ...").format(fehler=type(e).__name__, s=args.backoff))
                    time.sleep(args.backoff)
                    continue
                errs = fetch_errors(msg)
                if "too_many_requests" in errs and attempt < 3:
                    # Gegencheck-Seite bremst: laenger warten und denselben Eintrag nochmal versuchen
                    print(f"  [{i}/{len(jobs)}] {key}: " + _("{seite} is throttling, waiting {s} s ...").format(
                        seite=PROFIL["check_name"], s=args.backoff))
                    time.sleep(args.backoff)
                    continue
                break
            else:
                print(f"  [{i}/{len(jobs)}] {kind} {key}: " + _("given up, will be retried in the next run"))
                continue
            ok = handle_result(db, kind, key, msg, args, errors)
            db.commit()
            st = db.execute("SELECT status FROM checked WHERE key=? AND kind=?", (key, kind)).fetchone()
            why = ""
            if not ok:
                stop = getattr(msg, "stop_reason", "?")
                texts = [b.text for b in msg.content if getattr(b, "type", "") == "text"]
                why = f" [stop_reason={stop}]"
                with open(faillog, "a", encoding="utf-8") as fl:
                    fl.write(json.dumps({"kind": kind, "key": key, "stop_reason": stop,
                                         "text": (texts[-1] if texts else "")[:3000]}, ensure_ascii=False) + "\n")
            print(f"  [{i}/{len(jobs)}] {kind} {key}: " + (st[0] if ok and st else _("no usable answer")) + why
                  + (f" ({', '.join(map(str, errs))})" if errs else ""), flush=True)
            time.sleep(args.pause)
        report_fetch_errors(errors)
        return
    print(_("Note: in batch mode many fetches run at the same time; {seite} will reject many of them.").format(
        seite=PROFIL["check_name"]))
    for i in range(0, len(jobs), 1000):
        chunk = jobs[i:i + 1000]
        for kind in ("check", "gap"):
            reqs = [{"custom_id": cid(("c:" if k == "check" else "g:") + key), "params": params(k, content)}
                    for k, key, content in chunk if k == kind]
            if not reqs:
                continue
            b = client.messages.batches.create(requests=reqs)
            db.execute("INSERT INTO batches(id, model, spoilers, kind) VALUES(?,?,?,?)",
                       (b.id, args.model, args.spoilers, kind))
            db.commit()
            print("  " + _("Batch {id} sent ({n} x {art})").format(id=b.id, n=len(reqs), art=kind))
    wait_for_batches(db, client, args)


# ---------------------------------------------------------------- StarDict schreiben

def render(title, data, books, source):
    e = html.escape
    if data.get("html") is not None:               # Eintrag als fertiges HTML (eingelesen oder von Hand)
        return data["html"]
    parts = [f"<div><i>{e(data.get('category', 'Other'))}</i></div>", f"<p>{e(data.get('tagline', ''))}</p>"]
    for s in data.get("sections", []):
        parts.append(f"<p><b>{e(s['h'])}.</b> {e(s['t'])}</p>")
    small = []
    if books:
        shown = ", ".join(f"{e(b)} ({n})" for b, n in books[:6])
        more = f" +{len(books) - 6} more" if len(books) > 6 else ""
        small.append(f"In your library: {shown}{more}")
    small.append(f"Source: {e(source)}")
    parts.append("<p><small>" + "<br/>".join(small) + "</small></p>")
    return "".join(parts)


def sort_key(word):
    b = word.encode("utf-8")
    return (b.lower(), b)       # StarDict verlangt: erst ohne Gross/Klein (nur ASCII), dann bytegenau


def collect(db, host, skip_cats, include_own=True):
    """Alle Eintraege, wie sie ins Woerterbuch kommen: Wiki-Zusammenfassungen (gegengecheckte
    Fassung bevorzugt), gefuellte Luecken, dann die eigenen Eintraege (Tabelle own).
    Gibt (entries, sources, books, extra_syns, redirs) zurueck."""
    books = defaultdict(list)
    for title, book, n in db.execute("SELECT title, book, n FROM mentions ORDER BY n DESC"):
        books[title].append((book, n))
    redirs = defaultdict(list)
    for src, dst in db.execute("SELECT src, dst FROM redirects"):
        redirs[dst].append(src)
    checked = {(k, kind): (json.loads(d), st)
               for k, kind, d, st in db.execute("SELECT key, kind, data, status FROM checked")}

    entries, sources, extra_syns = {}, {}, []
    for title, raw in db.execute("SELECT title, data FROM entries"):
        data, src = json.loads(raw), host
        chk = checked.get((title, "check"))
        if chk and chk[1] == "ok":                 # gegengecheckte Fassung bevorzugen
            data, src = chk[0], f"{host}, checked against {PROFIL['check_name']}"
        if data.get("skip") or data.get("category") in skip_cats or title not in books:
            continue
        entries[title], sources[title] = data, src

    # Luecken, die ueber die Gegencheck-Seite gefuellt wurden
    gap_books = defaultdict(list)
    for name, book, n in db.execute("SELECT name, book, n FROM gaps ORDER BY n DESC"):
        gap_books[name].append((book, n))
    for (name, kind), (data, st) in checked.items():
        if kind != "gap" or st != "ok" or data.get("category") in skip_cats or name not in gap_books:
            continue
        head = (data.get("title") or name).strip()
        if head in entries:                        # Kurzname -> gibt es schon unter dem vollen Namen
            extra_syns.append((name, head))
            continue
        entries[head], sources[head] = data, PROFIL["check_name"]
        books[head] = gap_books[name]
        if name != head:
            extra_syns.append((name, head))

    # Eigene Eintraege gewinnen immer
    for title, raw, source in db.execute("SELECT title, data, source FROM own") if include_own else ():
        data = json.loads(raw)
        if data.get("deleted"):
            entries.pop(title, None)
            extra_syns = [(w, h) for w, h in extra_syns if h != title]
            continue
        entries[title], sources[title] = data, source or "own entry"
        if not books.get(title):
            books[title] = gap_books.get(title, [])
    return entries, sources, books, extra_syns, redirs


def synonyms(entries, redirs, extra_syns):
    """{(Wort, Stichwort)}: Weiterleitungen, Aliase, Name ohne Klammerzusatz, Plural bei
    Sachen, eindeutige Vor-/Nachnamen bei Personen."""
    try:
        from wordfreq import zipf_frequency
    except ImportError:                            # ohne wordfreq: nur die Eindeutigkeit zaehlt
        def zipf_frequency(word, lang):
            return 0.0
    # Wie viele Personen teilen sich einen Vor-/Nachnamen? ("Gandalf" eindeutig, "Captain" nicht)
    name_use = Counter()
    for title, data in entries.items():
        if data.get("category") == "Person":
            for tok in set(strip_paren(title).split()):
                name_use[tok.lower()] += 1
    syns = set()
    for title, data in entries.items():
        cand = set(redirs.get(title, [])) | set(data.get("aliases", []))
        base = strip_paren(title)
        cand.add(base)
        if data.get("category") in ("Technology", "Species", "Vessel", "Faction", "Organisation") \
                and not base.lower().endswith("s"):
            cand.add(base + "s")
        if data.get("category") == "Person":
            toks = base.split()
            if len(toks) > 1:
                for tok in (toks[0], toks[-1]):
                    if len(tok) >= 4 and name_use[tok.lower()] <= 3 and zipf_frequency(tok.lower(), "en") < 4.0 \
                            and not re.fullmatch(r"[IVXLC]+", tok):
                        cand.add(tok)
        for c in cand:
            c = c.strip()
            if c and c != title and len(c.encode()) < 250:
                syns.add((c, title))
    for word, head in extra_syns:
        if word != head and head in entries and len(word.encode()) < 250:
            syns.add((word, head))
    return syns


def write_dict(out, name, host, entries, sources, books, syns):
    """Schreibt <out>/<stem>.ifo/.idx/.dict/.syn (stem aus dem Profil).
    Gibt (Eintraege, Synonyme) zurueck."""
    heads = sorted(entries, key=sort_key)
    index = {t: i for i, t in enumerate(heads)}
    out = Path(out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    stem = out / PROFIL["stem"]
    for alt in out.glob("*.dict.dz"):              # alte gepackte Fassung wuerde neben der neuen liegen
        if alt.name == f"{PROFIL['stem']}.dict.dz":
            alt.unlink()
    idx, offset = bytearray(), 0
    with open(f"{stem}.dict", "wb") as fdict:
        for title in heads:
            body = render(title, entries[title], books.get(title, []), sources[title]).encode("utf-8")
            fdict.write(body)
            idx += title.encode("utf-8") + b"\0" + struct.pack(">II", offset, len(body))
            offset += len(body)
    Path(f"{stem}.idx").write_bytes(idx)
    pairs = sorted(((w, index[h]) for w, h in syns), key=lambda s: (sort_key(s[0]), s[1]))
    with open(f"{stem}.syn", "wb") as fsyn:
        for word, i in pairs:
            fsyn.write(word.encode("utf-8") + b"\0" + struct.pack(">I", i))
    Path(f"{stem}.ifo").write_text(
        "StarDict's dict ifo file\nversion=2.4.2\n"
        f"bookname={name}\nwordcount={len(heads)}\nsynwordcount={len(pairs)}\n"
        f"idxfilesize={len(idx)}\nsametypesequence=h\n"
        f"description=AI summaries of {host} articles (CC BY-SA where applicable)"
        + (f", partly checked against {check_host()}" if check_host() else "")
        + ", plus own entries. Built for personal use.\n",
        encoding="utf-8")
    return len(heads), len(pairs)


def build_to(db, out, name, host, skip_cats):
    """Sammeln und schreiben; merkt sich Zeitpunkt und Ausgabeordner (meta built_at/built_out).
    Gibt (Eintraege, Synonyme) zurueck, (0, 0) wenn es nichts gibt."""
    entries, sources, books, extra_syns, redirs = collect(db, host, skip_cats)
    if not entries:
        return 0, 0
    n, nsyn = write_dict(out, name, host, entries, sources, books, synonyms(entries, redirs, extra_syns))
    meta_set(db, "built_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    meta_set(db, "built_out", str(Path(out).expanduser().resolve()))
    db.commit()
    return n, nsyn


def cmd_build(db, wiki, args):
    skip_cats = {c.strip() for c in args.skip_categories.split(",") if c.strip()}
    out = args.out or meta_get(db, "built_out") or PROFIL["stem"]
    n, nsyn = build_to(db, out, PROFIL["name"], wiki_host(), skip_cats)
    if not n:
        sys.exit(_("No entries yet - run 'summarize' first."))
    print(_("{n} entries, {nsyn} synonyms -> {ordner}/").format(n=n, nsyn=nsyn, ordner=Path(out).expanduser()))
    print(_("Copy the whole folder to data/dict/ in the KOReader folder on the e-reader (Kobo: .adds/koreader/data/dict/)."))


# ---------------------------------------------------------------- Kleinkram

def print_entry(label, data):
    print(f"--- {label}  [{data.get('category')}]\n{data.get('tagline')}")
    for s in data.get("sections", []):
        print(f"\n{s['h']}: {s['t']}")
    if data.get("aliases"):
        print("\nAliases:", ", ".join(data["aliases"]))
    if data.get("changes"):
        print("\n" + _("Changed by the cross-check ({seite}):").format(seite=PROFIL["check_name"]) + "\n  - "
              + "\n  - ".join(data["changes"]))
    print()


def cmd_show(db, wiki, args):
    found = False
    row = db.execute("SELECT title, data FROM entries WHERE title LIKE ?", (args.word,)).fetchone()
    if not row:
        dst = db.execute("SELECT dst FROM redirects WHERE src LIKE ?", (args.word,)).fetchone()
        row = dst and db.execute("SELECT title, data FROM entries WHERE title=?", dst).fetchone()
    if row:
        found = True
        print_entry(f"{row[0]} (Wiki)", json.loads(row[1]))
        chk = db.execute("SELECT data, status FROM checked WHERE key=? AND kind='check'", (row[0],)).fetchone()
        if chk:
            if chk[1] == "ok":
                print_entry(f"{row[0]} " + _("(after the cross-check)"), json.loads(chk[0]))
            else:
                print(_("Cross-check: {seite}").format(seite=chk[1]) + "\n")
    for key, data, status in db.execute("SELECT key, data, status FROM checked WHERE kind='gap' AND key LIKE ?",
                                        (args.word,)):
        found = True
        if status == "ok":
            print_entry(f"{key} " + _("(gap, from {seite})").format(seite=PROFIL["check_name"]), json.loads(data))
        else:
            print(f"{key}: " + _("gap, not found on {seite} ({status})").format(seite=PROFIL["check_name"], status=status))
    if not found:
        sys.exit(_("No entry found."))


def cmd_stats(db, wiki, args):
    q = lambda sql: db.execute(sql).fetchone()[0]
    for label, sql in ((_("Titles:"), "SELECT COUNT(*) FROM titles"),
                       (_("Redirects:"), "SELECT COUNT(*) FROM redirects"),
                       (_("Books:"), "SELECT COUNT(DISTINCT book) FROM mentions"),
                       (_("Terms in books:"), "SELECT COUNT(DISTINCT title) FROM mentions"),
                       (_("Articles loaded:"), "SELECT COUNT(*) FROM articles"),
                       (_("Entries done:"), "SELECT COUNT(*) FROM entries"),
                       (_("Gap candidates:"), "SELECT COUNT(DISTINCT name) FROM gaps")):
        print(f"{label:<22}{q(sql)}")
    for kind, label in (("check", _("Cross-check")), ("gap", _("Gaps"))):
        rows = db.execute("SELECT status, COUNT(*) FROM checked WHERE kind=? GROUP BY status", (kind,)).fetchall()
        if rows:
            print(f"{label}: " + ", ".join(f"{s} {n}" for s, n in rows))
    print(f"{_('Open batches:'):<22}{q('SELECT COUNT(*) FROM batches WHERE done=0')}")


def cmd_all(db, wiki, args):
    if not db.execute("SELECT 1 FROM titles LIMIT 1").fetchone():
        cmd_titles(db, wiki, args)
    cmd_scan(db, wiki, args)
    cmd_fetch(db, wiki, args)
    cmd_summarize(db, wiki, args)
    cmd_build(db, wiki, args)


_LOCK = None


def lock_or_exit(workdir):
    """Verhindert, dass zwei Laeufe gleichzeitig dieselbe Liste abarbeiten (doppelte Kosten)."""
    global _LOCK
    _LOCK = open(workdir / "run.lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(_LOCK.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_LOCK, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(_("A summarize/crosscheck is already running with this working folder. Check with: pgrep -af "
                   "wikidict"))


def parser():
    """Kommandozeilen-Parser; Bookbench ruft die Schritte mit denselben Standardwerten auf."""
    ap = argparse.ArgumentParser(description=_(
        "Builds a personal dictionary (StarDict, e.g. for KOReader) from a MediaWiki and optionally cross-checks it "
        "with a second site using Claude. Wiki, topic, cross-check site, name and file name are remembered as a "
        "profile in the database; on the first run in a new working folder --wiki and --topic are needed.")
        + "\n\n" + _("Example:") + "\n  wikidict.py --workdir sw --wiki https://starwars.fandom.com "
        "--topic \"Star Wars Legends\" all ~/Books", formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workdir", default="wikidict_data", help=_("folder for the database and intermediate data"))
    ap.add_argument("--wiki", help=_("base URL of the wiki, e.g. https://starwars.fandom.com (remembered in the "
                                     "profile)"))
    ap.add_argument("--topic", help=_("topic for Claude, e.g. 'Star Wars Legends' (remembered)"))
    ap.add_argument("--check-site", help=_("page prefix for the cross-check, e.g. https://example.org/wiki/ ('' = "
                                           "no cross-check; remembered)"))
    ap.add_argument("--stem", help=_("file name of the dictionary files (remembered)"))
    ap.add_argument("--delay", type=float, default=1.0, help=_("seconds of pause between wiki requests"))
    ap.add_argument("--user-agent", default="wikidict/1.0 (personal reading dictionary; python-requests)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_scan(p):
        p.add_argument("books", help=_("folder with EPUBs (searched recursively)"))
        p.add_argument("--zipf", type=float, default=4.0,
                       help=_("from this word frequency on a single word counts as 'normal English' and must "
                              "appear capitalized in the book (lower = stricter)"))
        p.add_argument("--min-gap", type=int, default=5,
                       help=_("how often an unknown name must occur to become a gap candidate"))
        p.add_argument("--gap-limit", type=int, default=1500, help=_("at most this many gap candidates"))

    def add_fetch(p):
        p.add_argument("--max-chars", type=int, default=14000, help=_("cut articles after this many characters"))

    def add_sum(p):
        p.add_argument("--model", default=DEFAULT_MODEL)
        p.add_argument("--spoilers", choices=list(SPOILER_RULES), default="mild")
        p.add_argument("--words", type=int, default=150, help=_("approximate length of an entry"))
        p.add_argument("--limit", type=int, help=_("only the N most mentioned articles (for trying it out)"))
        p.add_argument("--sync", action="store_true", help=_("immediately instead of batch (more expensive, good "
                                                             "for --limit 20)"))
        p.add_argument("--redo", action="store_true", help=_("discard existing entries and create them again"))
        p.add_argument("--poll", type=int, default=60)
        p.add_argument("--yes", action="store_true", help=_("do not ask"))

    def add_build(p):
        p.add_argument("--out", help=_("output folder (default: the one of the last build, otherwise the file name)"))
        p.add_argument("--name", help=_("name in KOReader (remembered in the profile)"))
        p.add_argument("--skip-categories", default="Publication",
                       help=_("categories that should not go into the dictionary (comma-separated)"))

    sub.add_parser("check")
    sub.add_parser("titles")
    add_scan(sub.add_parser("scan"))
    add_fetch(sub.add_parser("fetch"))
    add_sum(sub.add_parser("summarize"))
    p = sub.add_parser("crosscheck", help=_("cross-check entries with the cross-check site using Claude's web fetch"))
    add_sum(p)
    p.add_argument("--gaps", action="store_true", help=_("also fill gaps from the cross-check site"))
    p.add_argument("--gaps-only", action="store_true", help=_("only fill gaps"))
    p.add_argument("--batch", action="store_true",
                   help=_("use the batch API instead of one by one (cheaper, but the cross-check site then "
                          "usually throttles a lot)"))
    p.add_argument("--pause", type=float, default=3, help=_("seconds of pause between two entries"))
    p.add_argument("--backoff", type=int, default=60, help=_("seconds to wait when the cross-check site throttles"))
    p.add_argument("--search", action="store_true",
                   help=_("if needed, search gaps with a web search on the cross-check site (1 cent per search)"))
    p.add_argument("--retry-not-found", action="store_true",
                   help=_("try again entries that were not found last time"))
    p.add_argument("--skip-categories", default="Publication,Disambiguation")
    p.add_argument("--fetch-tool", default="web_fetch_20250910", help=_("version of the web fetch tool"))
    p.add_argument("--fetch-tokens", type=int, default=12000, help=_("at most this many tokens per fetched page"))
    add_build(sub.add_parser("build"))
    sub.add_parser("stats")
    sub.add_parser("show").add_argument("word")
    p = sub.add_parser("all")
    for f in (add_scan, add_fetch, add_sum, add_build):
        f(p)

    return ap


def wiki_oeffnen(db, args):
    if not PROFIL.get("wiki"):
        sys.exit(_("No wiki set - give it with --wiki <address> (and --topic) on the first run."))
    return Wiki(db, PROFIL["wiki"], args.user_agent, args.delay)


def main():
    args = parser().parse_args()
    db = open_db(Path(args.workdir))
    if args.cmd in ("summarize", "crosscheck", "all"):
        lock_or_exit(Path(args.workdir))
    # Nur diese Schritte reden mit dem Wiki (und brauchen requests)
    profil_laden(db, {"wiki": args.wiki, "topic": args.topic, "check_site": args.check_site, "stem": args.stem,
                      "name": getattr(args, "name", None)})
    wiki = wiki_oeffnen(db, args) if args.cmd in ("check", "titles", "fetch", "all") else None
    globals()[f"cmd_{args.cmd}"](db, wiki, args)


if __name__ == "__main__":
    main()
