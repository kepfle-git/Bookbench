# -*- coding: utf-8 -*-
"""
toc_fix.py - Kapitelnamen aus dem Buchtext fürs Inhaltsverzeichnis (Teil von Bookbench).

Viele EPUBs haben im Verzeichnis nur "ONE", "Chapter Two" usw., obwohl im Buch darunter ein
Titel steht. analyse_book() findet diese Titel und macht Vorschläge ("One: Blood from
misunderstanding"), mit Gründen für fragwürdige Fälle. Dazu Lesen und Umschreiben von
nav.xhtml/toc.ncx (toc_files, entries_of, rewrite) und write_copy für die neue EPUB-Datei.
Geändert wird nur das Inhaltsverzeichnis, nie Buchtext.

Früher auch ein Kommandozeilen-Skript (bis Werkstatt 0.19 im Repo); die Entscheidungen liegen
weiter in tocfix_entscheidungen.json (kobo_daten.ENTSCHEIDUNGEN).
"""
import html
import posixpath
import re
import zipfile

from bookbench.i18n import _

from bookbench.core.toc_report import GENERIC, clean, resolve_href, text_lines  # noqa: E402

LABEL = re.compile(r"^(prologue|epilogue|interlude|coda|afterword|prolog|epilog)$", re.I)
DATE = re.compile(r"^\d{3}\.?M\d{2}$|^M\d{2}$", re.I)           # "991.M37" - Zeitangabe, kein Titel


def norm(s):
    return re.sub(r"[\s\-\u2010-\u2015]+", " ", s).strip().casefold()


def is_label(title):
    return bool(GENERIC.match(title) or LABEL.match(title))


SMALL = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "with", "from"}


def nice(text):
    """GROSSBUCHSTABEN in normale Titelschreibung: "ROADS OF BONE AND BLOOD" -> "Roads of Bone and Blood".
    Gemischte Schreibung bleibt, wie sie ist."""
    if not text.isupper():
        return text

    def word(i, w):
        core = w.strip(",.:;!?'’")
        if ROMAN.match(core):                     # "BELIAL IV" -> "Belial IV", nicht "Belial Iv"
            return w
        w = w.lower()
        if i and w in SMALL:
            return w
        return "-".join(p[:1].upper() + p[1:] for p in w.split("-"))

    return " ".join(word(i, w) for i, w in enumerate(text.split(" ")))


ROMAN = re.compile(r"^(?=[IVXLC])(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")    # I bis XCIX


def is_subtitle(line, book_title):
    if len(line) > 60 or norm(line) == norm(book_title) or DATE.match(line) or is_label(line):
        return False
    if line[0] in "\u2018\u201c\"'([" or line[-1] in ".!?\u2026\u2019\u201d\"',;:]":
        return False                       # Satzzeichen am Ende/Anfang = Fliesstext, Dialog, [mark: ...]
    if "," in line:
        return False                       # Ortsangabe: "Hull exterior, Rogue trader Malescaythe, The webway"
    if re.search(r"\d\d", line):
        return False                       # Zeitmarken, Codes, Jahreszahlen: "3211 Stop 1545"
    return True


def analyse_book(z, entries, book_title, max_sub):
    """Prueft jeden nummerierten Verzeichniseintrag.
    Rueckgabe: (neue Titel {Schluessel: Titel}, Liste aller Kandidaten mit Begruendung, Hinweis wenn uebersprungen)"""
    from collections import Counter
    names = set(z.namelist())
    items, seen = [], set()
    for href, old in entries:
        key = (href, norm(old))
        if not is_label(old) or key in seen:       # nav.xhtml und toc.ncx enthalten dieselben Eintraege
            continue
        seen.add(key)
        lines = text_lines(z, href, names)[:8]
        start = next((i for i, l in enumerate(lines[:4]) if norm(l) == norm(old)), None)
        subs, rest = [], lines[start + 1:] if start is not None else []
        while rest and len(subs) < max_sub:
            l = rest.pop(0)
            # Titel ueber zwei Zeilen: "THE RADIANT KING," + "IN HIS JOYFUL REPOSE"
            if (l.endswith(",") and l.count(",") == 1 and rest
                    and is_subtitle(l[:-1], book_title) and is_subtitle(rest[0], book_title)):
                l = f"{l} {rest.pop(0)}"
            elif not is_subtitle(l, book_title):
                break
            subs.append(l)
        items.append({"key": key, "old": old, "subs": subs, "lines": lines[:6], "reasons": [],
                      "proposal": f"{nice(old)}: {' / '.join(nice(s) for s in subs)}" if subs else None})

    found = [i for i in items if i["proposal"]]
    # Plausibilitaet: Wenn ein Buch wirklich Kapitelnamen hat, dann bei den meisten Kapiteln.
    # Nur 2 von 40 gefunden heisst: das waren zufaellig kurze Zeilen, keine Titel.
    skipped = None
    if found and len(items) >= 4 and len(found) < 0.5 * len(items):
        kurz = _("only {n} of {m} chapters with a title").format(n=len(found), m=len(items))
        skipped = kurz + " - " + _("probably coincidence")

    # Verdaechtiges fuer --review markieren
    count = Counter(norm(" / ".join(i["subs"])) for i in found)
    for i in found:
        s = " / ".join(i["subs"])
        if count[norm(s)] > 1:
            i["reasons"].append(_("the same name occurs several times in the book"))
        if len(s) < 4:
            i["reasons"].append(_("very short"))
        if len(s) > 45:
            i["reasons"].append(_("very long"))
        if s[:1].islower():
            i["reasons"].append(_("starts with a lowercase letter"))
        if skipped:
            i["reasons"].append(_("book would be skipped otherwise ({grund})").format(grund=kurz))
    if found and not skipped and len(found) < len(items):
        for i in items:
            if not i["proposal"]:
                i["reasons"].append(_("no name found, other chapters in the book have one"))

    new = {} if skipped else {i["key"]: i["proposal"] for i in found}
    return new, items, skipped


# Attribute koennen in "..." oder '...' stehen; Gruppen: 2 = Link, 4 = Text (nav) bzw. 2 = Text, 4 = Link (ncx)
NAV_A = re.compile(r"""(<a\b[^>]*?href=["'])([^"']*)(["'][^>]*>)(.*?)(</a>)""", re.S)
NCX_PT = re.compile(r"""(<navLabel>\s*<text>)([^<]*)(</text>\s*</navLabel>\s*<content\b[^>]*?src=["'])([^"']*)""", re.S)


def toc_files(z):
    container = z.read("META-INF/container.xml").decode("utf-8", "replace")
    opf_path = re.search(r'full-path="([^"]+)"', container).group(1)
    opf = z.read(opf_path).decode("utf-8", "replace")
    base = posixpath.dirname(opf_path)
    title = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", opf, re.S)
    out = []
    for item in re.findall(r"<item\b[^>]*>", opf):
        h = re.search(r'href="([^"]+)"', item)
        if not h:
            continue
        path = resolve_href(base, html.unescape(h.group(1)))
        if re.search(r'properties="[^"]*\bnav\b', item):
            out.append(("nav", path))
        elif "application/x-dtbncx+xml" in item:
            out.append(("ncx", path))
    return (clean(title.group(1)) if title else ""), out


def entries_of(kind, src, tocdir):
    if kind == "nav":
        return [(resolve_href(tocdir, html.unescape(m.group(2))), clean(m.group(4))) for m in NAV_A.finditer(src)]
    return [(resolve_href(tocdir, html.unescape(m.group(4))), clean(m.group(2))) for m in NCX_PT.finditer(src)]


def rewrite(kind, src, tocdir, new):
    count = 0

    def sub(m):
        nonlocal count
        if kind == "nav":
            key = (resolve_href(tocdir, html.unescape(m.group(2))), norm(clean(m.group(4))))
            if key in new:
                count += 1
                return m.group(1) + m.group(2) + m.group(3) + html.escape(new[key], quote=False) + m.group(5)
        else:
            key = (resolve_href(tocdir, html.unescape(m.group(4))), norm(clean(m.group(2))))
            if key in new:
                count += 1
                return m.group(1) + html.escape(new[key], quote=False) + m.group(3) + m.group(4)
        return m.group(0)

    return (NAV_A if kind == "nav" else NCX_PT).sub(sub, src), count


def write_copy(src_path, dst_path, changed):
    """Kopie des EPUB mit geänderten Dateien. changed: Pfad -> str (UTF-8) oder bytes;
    Pfade, die es noch nicht gibt, kommen am Ende dazu (z. B. ein neues Titelbild)."""
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src_path) as zin, zipfile.ZipFile(dst_path, "w") as zout:
        infos = zin.infolist()
        infos.sort(key=lambda i: i.filename != "mimetype")      # EPUB-Regel: mimetype zuerst, unkomprimiert
        vorhanden = set()
        for info in infos:
            vorhanden.add(info.filename)
            data = changed[info.filename] if info.filename in changed else zin.read(info.filename)
            if isinstance(data, str):
                data = data.encode("utf-8")
            ctype = zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
            zout.writestr(info, data, compress_type=ctype)
        for name, data in changed.items():
            if name not in vorhanden:
                zout.writestr(name, data.encode("utf-8") if isinstance(data, str) else data,
                              compress_type=zipfile.ZIP_DEFLATED)
