# -*- coding: utf-8 -*-
"""
toc_report.py - Inhaltsverzeichnis und Metadaten aus EPUB/KEPUB lesen (Teil von Bookbench).

  read_toc(pfad)       Einträge (Tiefe, Titel, Ziel) aus nav.xhtml bzw. toc.ncx
  parse_nav/parse_ncx  dasselbe aus dem Text einer Datei
  text_lines           die ersten Zeilen Buchtext an einem Ziel
  reihe_aus_opf        Reihe und Nummer (Calibre- oder EPUB3-Schreibweise)
  clean, resolve_href  Hilfen

Früher auch ein Kommandozeilen-Skript für Berichte (bis Werkstatt 0.19 im Repo).
"""
import html
import posixpath
import re
import zipfile

NUMWORDS = ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
            "sixteen seventeen eighteen nineteen twenty thirty forty fifty").split()
GENERIC = re.compile(
    r"^(chapter|kapitel|part|teil|book|buch)?\s*[:.\-]?\s*"
    r"(\d+|[ivxlcdm]+|(" + "|".join(NUMWORDS) + r")([\s-](" + "|".join(NUMWORDS) + r"))?)\s*[:.]?$", re.I)


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def read_toc(path):
    """Gibt (Buchtitel, [(Tiefe, Titel), ...]) zurueck. Bevorzugt nav.xhtml (EPUB3), sonst toc.ncx."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        container = z.read("META-INF/container.xml").decode("utf-8", "replace")
        opf_path = re.search(r'full-path="([^"]+)"', container).group(1)
        opf = z.read(opf_path).decode("utf-8", "replace")
        base = posixpath.dirname(opf_path)
        m = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", opf, re.S)
        title = clean(m.group(1)) if m else path.stem

        def href_of(pattern):
            for item in re.findall(r"<item\b[^>]*>", opf):
                if re.search(pattern, item):
                    h = re.search(r'href="([^"]+)"', item)
                    if h:
                        p = posixpath.normpath(posixpath.join(base, html.unescape(h.group(1))))
                        if p in names:
                            return p
            return None

        def resolve(toc, tocfile):
            d = posixpath.dirname(tocfile)
            return [(dep, t, resolve_href(d, h)) for dep, t, h in toc]

        nav = href_of(r'properties="[^"]*\bnav\b')
        if nav:
            toc = parse_nav(z.read(nav).decode("utf-8", "replace"))
            if toc:
                return title, resolve(toc, nav)
        ncx = href_of(r'media-type="application/x-dtbncx\+xml"')
        if ncx:
            return title, resolve(parse_ncx(z.read(ncx).decode("utf-8", "replace")), ncx)
    return title, []


def resolve_href(base_dir, href):
    """Relativen Link aus dem Inhaltsverzeichnis in einen Pfad im ZIP umwandeln (inkl. %20 usw.)."""
    from urllib.parse import unquote
    if not href:
        return ""
    file, __, frag = href.partition("#")
    path = posixpath.normpath(posixpath.join(base_dir, unquote(file))) if file else ""
    return path + ("#" + frag if frag else "")


def text_lines(z, href, names):
    """Textzeilen ab der Stelle, auf die ein Verzeichniseintrag zeigt (ohne <head>)."""
    file, __, frag = href.partition("#")
    if file not in names:
        return []
    src = z.read(file).decode("utf-8", "replace")
    src = re.sub(r"<head\b.*?</head>", "", src, flags=re.S | re.I)   # <title> im Kopf ist kein Buchtext
    if frag:
        m = re.search(r"""id=["']%s["']""" % re.escape(frag), src)
        if m:
            src = src[src.rfind("<", 0, m.start()):]
    src = re.sub(r"<(script|style)\b.*?</\1>", "", src, flags=re.S | re.I)
    src = re.sub(r"<(br|/p|/div|/h\d|/li|/tr)\b[^>]*>", "\n", src, flags=re.I)
    return [l for l in (clean(x) for x in src.split("\n")) if l]


def parse_nav(src):
    m = re.search(r'<nav\b[^>]*epub:type="toc"[^>]*>(.*?)</nav>', src, re.S) or \
        re.search(r"<nav\b[^>]*>(.*?)</nav>", src, re.S)
    if not m:
        return []
    out, depth = [], 0
    for tok in re.finditer(r"<(/?)(ol|ul)\b[^>]*>|<a\b([^>]*)>(.*?)</a>|<span\b[^>]*>(.*?)</span>", m.group(1), re.S):
        if tok.group(2):
            depth += -1 if tok.group(1) else 1
        else:
            text = clean(tok.group(4) or tok.group(5) or "")
            h = re.search(r"""href=["']([^"']*)["']""", tok.group(3) or "")
            if text:
                out.append((max(depth, 1), text, html.unescape(h.group(1)) if h else ""))
    return out


def parse_ncx(src):
    out, depth, need_href = [], 0, False
    for tok in re.finditer(r"""<(/?)navPoint\b[^>]*>|<text>(.*?)</text>|<content\b[^>]*src=["']([^"']*)["']""",
                           src, re.S):
        if tok.group(2) is not None:
            if depth > 0:
                out.append((depth, clean(tok.group(2)), ""))
                need_href = True
        elif tok.group(3) is not None:
            if need_href:
                d, t, __ = out[-1]
                out[-1] = (d, t, html.unescape(tok.group(3)))
                need_href = False
        else:
            depth += -1 if tok.group(1) else 1
            need_href = False
    return out


def reihe_aus_opf(opf):
    """(Reihe, Nummer) aus dem Text einer content.opf: Calibre-Stil oder EPUB3-Stil."""
    def meta(name):                                   # Calibre-Stil: <meta name="calibre:series" content="...">
        for tag in re.findall(r"<meta\b[^>]*>", opf):
            if re.search(r"""name=["']%s["']""" % re.escape(name), tag):
                c = re.search(r"""content=["']([^"']*)["']""", tag)
                if c:
                    return clean(c.group(1))
        return ""

    series, idx = meta("calibre:series"), meta("calibre:series_index")
    if not series:                                    # EPUB3-Stil: belongs-to-collection
        for attrs, text in re.findall(r"<meta\b([^>]*?)(?<!/)>(.*?)</meta>", opf, re.S):
            if re.search(r"""property=["']belongs-to-collection["']""", attrs):
                series = clean(text)
                i = re.search(r"""\bid=["']([^"']+)["']""", attrs)
                if i:
                    for a2, t2 in re.findall(r"<meta\b([^>]*?)(?<!/)>(.*?)</meta>", opf, re.S):
                        if (re.search(r"""refines=["']#%s["']""" % re.escape(i.group(1)), a2)
                                and re.search(r"""property=["']group-position["']""", a2)):
                            idx = clean(t2)
                break
    return series, idx
