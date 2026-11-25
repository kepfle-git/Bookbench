# -*- coding: utf-8 -*-
"""
metadata.py - Metadaten im content.opf lesen und schreiben (Bereich Metadaten), dazu die
Werte aus Calibre (metadata.calibre) und KOReader (custom_metadata.lua) zum Vergleichen.

  FELDER            Kennungen der festen Felder, Werte überall als Text (Autoren mit " & ", Schlagwörter mit ", ");
                    eigene Calibre-Spalten heißen wie in Calibre ("#subtitle") - welche angezeigt werden,
                    stellt der Nutzer ein (Einstellung meta_spalten, seit 1.3-beta2)
  lesen(opf)        {feld: text} aus dem OPF, dazu alle eigenen Spalten, die im Buch stehen
  definitionen(opf) {"#spalte": Felddefinition} der eigenen Spalten im Buch
  schreiben(opf, alt, neu, definitionen)   OPF mit den geänderten Feldern (None bei ungewöhnlichem Aufbau)
  calibre_werte(eintrag), koreader_werte(pfad)   {feld: text}, nur Felder, die dort vorkommen
  unterschiede(werte, andere)   Felder, in denen andere einen Wert hat, der abweicht
  pruefen(werte)    Warnungen (ISBN-Prüfziffer, fehlende Sprache)

Bearbeitet wird textuell wie im Rest von Bookbench (kein XML-Neuschreiben): Was Bookbench nicht
kennt, bleibt Zeichen für Zeichen stehen. Reihe/Nummer schreibt library.opf_mit_reihe.

Formate (nachgesehen im Calibre-Quelltext, ebooks/metadata/opf2.py und opf3.py):
- EPUB2: <dc:creator opf:role="aut" opf:file-as="Abnett, Dan">, ISBN als <dc:identifier opf:scheme="ISBN">,
  eigene Calibre-Spalten je als <meta name="calibre:user_metadata:#spalte" content="{JSON}"/>.
- EPUB3: Rolle und Sortiername über <meta refines="#id" property="role|file-as">, ISBN als urn:isbn:,
  alle eigenen Spalten zusammen als JSON in <meta property="calibre:user_metadata">.
  Das JSON je Spalte ist Calibres Felddefinition mit "#value#"; Mehrfachwerte (z. B. Typ
  "Ampersand separated text") sind Listen, "is_multiple2" sagt, wie sie getrennt angezeigt werden.
"""
import html
import json
import re

from bookbench.core import blurbs
from bookbench.core import toc_report as tocreport
from bookbench.i18n import N_, _

FELDER = ("titel", "autoren", "autor_sort", "reihe", "nummer", "verlag", "sprache", "isbn", "schlagwoerter")
NAMEN = {"titel": N_("Title"), "autoren": N_("Authors"),
         "autor_sort": N_("Author sort"), "reihe": N_("Series"), "nummer": N_("Number"),
         "verlag": N_("Publisher"), "sprache": N_("Language"), "isbn": N_("ISBN"), "schlagwoerter": N_("Tags")}
WICHTIG = ("titel", "autoren", "reihe", "nummer")       # Abweichung hier = ⚠ in der Liste
CALIBRE_PREFIX = "calibre: https://calibre-ebook.com"
UNBEKANNT = {"Unknown", "Unbekannt"}     # schreibt Calibre (in seiner Oberflächensprache) bei fehlendem Titel/Autor

# Calibre speichert Sprachen als ISO 639-2 (eng), EPUBs meist als zwei Buchstaben (en)
SPRACHEN_3 = {"eng": "en", "deu": "de", "ger": "de", "fra": "fr", "fre": "fr", "spa": "es", "ita": "it",
              "nld": "nl", "dut": "nl", "por": "pt", "pol": "pl", "rus": "ru", "swe": "sv", "dan": "da",
              "nor": "no", "nob": "nb", "fin": "fi", "ces": "cs", "cze": "cs", "hun": "hu", "jpn": "ja",
              "zho": "zh", "chi": "zh", "kor": "ko", "tur": "tr", "ell": "el", "gre": "el", "ukr": "uk"}


# ---------------------------------------------------------------- Bausteine
def _attribute(tag):
    return {m.group(1).lower(): html.unescape(m.group(2) if m.group(2) is not None else m.group(3))
            for m in re.finditer(r"""([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""", tag)}


def _elemente(opf, tag):
    """[(start, ende, attribute, text)] aller <dc:tag> (auch leer geschlossen), Text ohne Auszeichnung."""
    erg = []
    for m in re.finditer(r"<dc:%s\b([^>]*?)(/>|>(.*?)</dc:%s\s*>)" % (tag, tag), opf, re.S):
        erg.append((m.start(), m.end(), _attribute(m.group(1)), tocreport.clean(m.group(3) or "")))
    return erg


def _refines(opf, ident):
    """[(start, ende, property, text)] der <meta refines="#ident">."""
    if not ident:
        return []
    erg = []
    for m in re.finditer(r"<meta\b([^>]*?)(/>|>(.*?)</meta\s*>)", opf, re.S):
        a = _attribute(m.group(1))
        if a.get("refines") == "#" + ident:
            erg.append((m.start(), m.end(), a.get("property", ""), tocreport.clean(m.group(3) or "")))
    return erg


def _verfeinert(opf, attrs, eigenschaft):
    for __, __, p, t in _refines(opf, attrs.get("id")):
        if p == eigenschaft:
            return t
    return ""


def epub_version(opf):
    m = re.search(r"<package\b[^>]*\bversion=[\"'](\d)", opf)
    return int(m.group(1)) if m else 2


def _schliessend(opf):
    return re.search(r"</(\w+:)?metadata>", opf)


def _einzug(opf):
    """Leerraum vor den Einträgen in <metadata> (z. B. "\n    "), damit neue Zeilen gleich eingerückt sind."""
    m = re.search(r"<(?:\w+:)?metadata\b[^>]*>(\s*)<", opf)
    return m.group(1) if m and m.group(1) else ""


def _einfuegen(opf, teile, pos=None, einzug=None):
    """Elemente (Liste von Texten) an pos einfügen, sonst als letzte in <metadata>, je mit dem Einzug
    der vorhandenen Einträge. None, wenn es kein </metadata> gibt."""
    if isinstance(teile, str):
        teile = [teile]
    einzug = _einzug(opf) if einzug is None else einzug
    if pos is None:
        m = re.search(r"\s*</(\w+:)?metadata>", opf)
        if not m:
            return None
        pos = m.start()
    return opf[:pos] + "".join(einzug + t for t in teile) + opf[pos:]


def _ausschneiden(opf, bereiche):
    """Bereiche [(start, ende)] entfernen, samt Leerraum davor; gibt (opf, Position des ersten,
    Leerraum vor dem ersten) zurück."""
    erste, einzug = None, None
    for s, e in sorted(bereiche, reverse=True):
        a = s
        while a > 0 and opf[a - 1] in " \t\r\n":
            a -= 1
        einzug = opf[a:s]
        opf = opf[:a] + opf[e:]
        erste = a
    return opf, erste, einzug


def _text(s):
    return html.escape(s, quote=False)


def _attr(s):
    return html.escape(s, quote=True)


def _norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def liste(text, trenner="&"):
    return [t.strip() for t in (text or "").split(trenner) if t.strip()]


def sprache_kurz(code):
    """"eng" → "en", "en-GB" bleibt; zum Vergleichen und beim Übernehmen aus Calibre."""
    c = (code or "").strip()
    return SPRACHEN_3.get(c.lower(), c)


def _autoren_el(opf):
    """dc:creator-Elemente, die Autoren sind (Rolle aut oder keine Rolle)."""
    v3 = epub_version(opf) >= 3
    erg = []
    for el in _elemente(opf, "creator"):
        rolle = el[2].get("opf:role") or el[2].get("role") or (_verfeinert(opf, el[2], "role") if v3 else "")
        if not rolle or rolle.lower() == "aut":
            erg.append(el)
    return erg


def _haupttitel(opf):
    """(Haupttitel-Element, Untertitel-Text aus EPUB3 title-type)."""
    haupt, unter = None, ""
    for el in _elemente(opf, "title"):
        art = _verfeinert(opf, el[2], "title-type")
        if art == "subtitle":
            unter = unter or el[3]
        elif haupt is None:
            haupt = el
    return haupt, unter


# ---------------------------------------------------------------- eigene Calibre-Spalten
def _spalten_epub2(opf):
    """{spalte: (start, ende, definition)} aus <meta name="calibre:user_metadata:#…">."""
    erg = {}
    for m in re.finditer(r"<meta\b[^>]*>", opf):
        a = _attribute(m.group(0))
        name = a.get("name", "")
        if name.startswith("calibre:user_metadata:") and "content" in a:
            try:
                erg[name.split(":", 2)[2]] = (m.start(), m.end(), json.loads(a["content"]))
            except ValueError:
                pass
    return erg


def _spalten_epub3(opf):
    """(start, ende, {spalte: definition}) aus <meta property="calibre:user_metadata">, sonst None."""
    for m in re.finditer(r"<meta\b([^>]*?)(?<!/)>(.*?)</meta\s*>", opf, re.S):
        if _attribute(m.group(1)).get("property", "").lower() == "calibre:user_metadata":
            try:
                daten = json.loads(html.unescape(m.group(2)))
            except ValueError:
                continue
            if isinstance(daten, dict):
                return m.start(), m.end(), daten
    return None


def _trenner(fm):
    """Trennzeichen eines Mehrfachfelds für die Anzeige ("&" oder ","), None bei Einzelwerten."""
    im = fm.get("is_multiple2") or (fm.get("is_multiple") if isinstance(fm.get("is_multiple"), dict) else None)
    if im:
        return (im.get("ui_to_list") or ",").strip() or ","
    if isinstance(fm.get("#value#"), list) or fm.get("is_multiple"):
        return "&" if (fm.get("display") or {}).get("is_names") else ","
    return None


def spalten_text(fm):
    """Wert einer Calibre-Felddefinition als Text (Listen mit " & " bzw. ", ", Ja/Nein, Datum ohne Uhrzeit)."""
    if not isinstance(fm, dict):
        return ""
    w = fm.get("#value#")
    if isinstance(w, list):
        t = _trenner(fm) or ","
        return (" & " if t == "&" else ", ").join(str(x) for x in w if str(x).strip())
    if w is None:
        return ""
    if isinstance(w, bool) or fm.get("datatype") == "bool":
        return _("yes") if w else _("no")
    if isinstance(w, float) and w == int(w):
        return str(int(w))
    if fm.get("datatype") == "datetime":
        return str(w)[:10]
    if isinstance(w, dict) and "__value__" in w:                # Calibres JSON für Datumswerte
        return str(w["__value__"])[:10]
    return str(w)


def _spalten_wert(fm, text):
    """Text aus dem Formular in den Wert für Calibres JSON; ValueError bei Unsinn in Zahlenfeldern."""
    t = _trenner(fm)
    if t:
        return liste(text, t)
    if not text:
        return None
    art = fm.get("datatype")
    if art in ("int", "rating"):
        return int(float(text.replace(",", ".")))
    if art == "float":
        return float(text.replace(",", "."))
    if art == "bool":
        if text.casefold() in {"yes", "ja", "true", "1", "y", "j", _("yes").casefold()}:
            return True
        if text.casefold() in {"no", "nein", "false", "0", "n", _("no").casefold()}:
            return False
        raise ValueError(text)
    return text


def spalten_fehler(fm, text):
    """Warnung, wenn text nicht zum Typ der Spalte passt, sonst None."""
    try:
        _spalten_wert(fm or {}, text)
    except ValueError:
        return {"int": _("a whole number"), "rating": _("a whole number"), "float": _("a number"),
                "bool": _("yes or no")}.get((fm or {}).get("datatype"), _("a valid value"))
    return None


def standard_definition(spalte):
    """Felddefinition für eine Textspalte, wenn weder Buch noch Calibre eine liefern. Calibre übernimmt
    beim Hinzufügen nur Spalten, die es in der Bibliothek mit gleichem Typ gibt (datatype)."""
    return {"datatype": "text", "is_multiple": None, "is_multiple2": {}, "is_custom": True, "is_editable": True,
            "is_category": True, "is_csp": False, "kind": "field", "key": spalte, "label": spalte.lstrip("#"),
            "name": spalte.lstrip("#").capitalize(), "search_terms": [spalte], "display": {}, "column": "value",
            "table": "", "colnum": 0, "rec_index": 0, "category_sort": "value", "link_column": "value",
            "#value#": None, "#extra#": None}


def _fuer_datei(fm):
    """Definition so, wie Calibre sie in die Datei schreibt (encode_is_multiple)."""
    fm = dict(fm)
    im = fm.get("is_multiple2") or (fm.get("is_multiple") if isinstance(fm.get("is_multiple"), dict) else None)
    if im:
        fm["is_multiple2"] = im
        fm["is_multiple"] = "," if fm.get("datatype") == "composite" else "|"
    else:
        fm["is_multiple"], fm["is_multiple2"] = None, {}
    return fm


def _mit_prefix(opf):
    """EPUB3: calibre-Präfix am <package> sicherstellen (wie Calibres ensure_prefix)."""
    m = re.search(r"<package\b[^>]*>", opf)
    if not m:
        return opf
    tag = m.group(0)
    p = re.search(r"""\bprefix=(["'])(.*?)\1""", tag, re.S)
    if p:
        if re.search(r"(^|\s)calibre:", p.group(2)):
            return opf
        neu = tag[:p.start(2)] + (p.group(2).rstrip() + " " + CALIBRE_PREFIX).strip() + tag[p.end(2):]
    else:
        neu = tag[:-1].rstrip("/") + f' prefix="{CALIBRE_PREFIX}"' + ("/>" if tag.endswith("/>") else ">")
    return opf[:m.start()] + neu + opf[m.end():]


def mit_spalte(opf, spalte, text, definition=None):
    """Eigene Calibre-Spalte setzen (leer = Wert leeren). definition: Felddefinition aus Calibre,
    falls die Datei die Spalte noch nicht hat."""
    if epub_version(opf) >= 3:
        vorhanden = _spalten_epub3(opf)
        alle = dict(vorhanden[2]) if vorhanden else {}
        fm = alle.get(spalte) or (dict(definition) if definition else None)
        if fm is None:
            if not text:
                return opf
            fm = standard_definition(spalte)
        fm = _fuer_datei(fm)
        fm["#value#"] = _spalten_wert(fm, text)
        alle[spalte] = fm
        tag = ('<meta property="calibre:user_metadata">'
               + _text(json.dumps(alle, ensure_ascii=False, indent=2, sort_keys=True)) + "</meta>")
        neu = opf[:vorhanden[0]] + tag + opf[vorhanden[1]:] if vorhanden else _einfuegen(opf, tag)
        return _mit_prefix(neu) if neu is not None else None
    vorhanden = _spalten_epub2(opf).get(spalte)
    fm = vorhanden[2] if vorhanden else (dict(definition) if definition else None)
    if fm is None:
        if not text:
            return opf
        fm = standard_definition(spalte)
    fm = _fuer_datei(fm)
    fm["#value#"] = _spalten_wert(fm, text)
    tag = (f'<meta name="calibre:user_metadata:{_attr(spalte)}" '
           f'content="{_attr(json.dumps(fm, ensure_ascii=False))}"/>')
    if vorhanden:
        return opf[:vorhanden[0]] + tag + opf[vorhanden[1]:]
    return _einfuegen(opf, tag)


# ---------------------------------------------------------------- Lesen
def definitionen(opf):
    """{"#spalte": Felddefinition} aller eigenen Calibre-Spalten im Buch (EPUB3-Block vor EPUB2-Einträgen)."""
    erg = {k: v[2] for k, v in _spalten_epub2(opf).items() if isinstance(v[2], dict)}
    v3 = _spalten_epub3(opf) if epub_version(opf) >= 3 else None
    if v3:
        erg.update({k: v for k, v in v3[2].items() if isinstance(v, dict)})
    return erg


def lesen(opf):
    """Alle Felder als Text, dazu alle eigenen Calibre-Spalten des Buchs ("#spalte")."""
    haupt, __ = _haupttitel(opf)
    autoren = _autoren_el(opf)
    v3 = epub_version(opf) >= 3
    sorten = []
    for el in autoren:
        s = el[2].get("opf:file-as") or el[2].get("file-as") or (_verfeinert(opf, el[2], "file-as") if v3 else "")
        sorten.append(s)
    belegt = [s for s in sorten if s]
    if belegt and len(set(belegt)) == 1 and len(autoren) > 1 and len(belegt) == len(autoren):
        autor_sort = belegt[0]                     # Calibre schreibt den ganzen Sortiernamen an jeden Autor
    else:
        autor_sort = " & ".join(belegt)
    reihe, nummer = tocreport.reihe_aus_opf(opf)
    if nummer.endswith(".0"):
        nummer = nummer[:-2]
    sprache = _elemente(opf, "language")
    w = {
        "titel": haupt[3] if haupt else "",
        "autoren": " & ".join(el[3] for el in autoren if el[3]),
        "autor_sort": autor_sort,
        "reihe": reihe, "nummer": nummer,
        "verlag": (_elemente(opf, "publisher") or [(0, 0, {}, "")])[0][3],
        "sprache": sprache[0][3] if sprache else "",
        "isbn": blurbs.isbn_aus(opf),
        "schlagwoerter": ", ".join(el[3] for el in _elemente(opf, "subject") if el[3]),
    }
    for k, fm in definitionen(opf).items():
        if k.startswith("#"):
            w[k] = spalten_text(fm)
    return w


def epub3_untertitel(opf):
    """Untertitel nach EPUB 3 (zweiter dc:title mit title-type subtitle), sonst ""."""
    return _haupttitel(opf)[1]


# ---------------------------------------------------------------- Schreiben
def _mit_titel(opf, titel):
    haupt, __ = _haupttitel(opf)
    if haupt:
        s, e, a, __ = haupt
        alt = opf[s:e]
        kopf = re.match(r"<dc:title\b[^>]*?(?=/?>)", alt).group(0)
        return opf[:s] + f"{kopf}>{_text(titel)}</dc:title>" + opf[e:]
    return _einfuegen(opf, f"<dc:title>{_text(titel)}</dc:title>")


def _mit_autoren(opf, autoren, sortiert):
    """Autoren-Elemente ersetzen (andere Rollen wie Herausgeber bleiben)."""
    v3 = epub_version(opf) >= 3
    alte = _autoren_el(opf)
    bereiche = [(s, e) for s, e, __, __ in alte]
    ids = set()
    for __, __, a, __ in alte:
        if a.get("id"):
            ids.add(a["id"])
            bereiche += [(s, e) for s, e, __, __ in _refines(opf, a["id"])]
    namen = liste(autoren)
    sorten = liste(sortiert)
    if len(sorten) != len(namen):
        sorten = [sortiert.strip()] + [""] * (len(namen) - 1) if namen else []
    opf, pos, einzug = _ausschneiden(opf, bereiche)
    teile = []
    if v3:
        belegt = set(re.findall(r"""\bid=["']([^"']+)["']""", opf)) - ids
        n = 0
        for name, sort in zip(namen, sorten):
            n += 1
            while f"bbautor{n}" in belegt:
                n += 1
            i = f"bbautor{n}"
            teile.append(f'<dc:creator id="{i}">{_text(name)}</dc:creator>')
            teile.append(f'<meta refines="#{i}" property="role" scheme="marc:relators">aut</meta>')
            if sort:
                teile.append(f'<meta refines="#{i}" property="file-as">{_text(sort)}</meta>')
    else:
        if namen and "xmlns:opf" not in opf:
            m = re.search(r"<((\w+:)?metadata)\b", opf)
            if not m:
                return None
            opf = opf[:m.end()] + ' xmlns:opf="http://www.idpf.org/2007/opf"' + opf[m.end():]
            pos = pos + len(' xmlns:opf="http://www.idpf.org/2007/opf"') if pos is not None and pos > m.end() else pos
        for name, sort in zip(namen, sorten):
            fa = f' opf:file-as="{_attr(sort)}"' if sort else ""
            teile.append(f'<dc:creator opf:role="aut"{fa}>{_text(name)}</dc:creator>')
    if not teile:
        return opf
    return _einfuegen(opf, teile, pos, einzug if pos is not None else None)


def _mit_einfach(opf, tag, wert):
    """Ein einfaches dc-Element (publisher, language) ersetzen, anlegen oder (leer) entfernen."""
    alte = _elemente(opf, tag)
    if not wert:
        return _ausschneiden(opf, [alte[0][:2]])[0] if alte else opf
    if alte:
        s, e = alte[0][:2]
        kopf = re.match(r"<dc:%s\b[^>]*?(?=/?>)" % tag, opf[s:e]).group(0)
        return opf[:s] + f"{kopf}>{_text(wert)}</dc:{tag}>" + opf[e:]
    return _einfuegen(opf, f"<dc:{tag}>{_text(wert)}</dc:{tag}>")


def _mit_schlagwoertern(opf, text):
    alte = _elemente(opf, "subject")
    opf, pos, einzug = _ausschneiden(opf, [(s, e) for s, e, __, __ in alte])
    neu = [f"<dc:subject>{_text(t)}</dc:subject>" for t in liste(text, ",")]
    if not neu:
        return opf
    return _einfuegen(opf, neu, pos, einzug if pos is not None else None)


def _isbn_element(opf):
    """(start, ende, attribute, wert) des ISBN-Identifiers - erkannt wie in blurbs.isbn_aus."""
    for s, e, a, w in _elemente(opf, "identifier"):
        schema = (a.get("opf:scheme") or a.get("scheme") or "").lower()
        if schema == "isbn" or w.lower().startswith(("urn:isbn:", "isbn:")) \
                or re.fullmatch(r"(97[89])?[\d-]{9,13}[\dXx]", w):
            if len(re.sub(r"[^\dXx]", "", w.split(":")[-1])) in (10, 13):
                return s, e, a, w
    return None


def _mit_isbn(opf, isbn):
    isbn = re.sub(r"[^\dXx]", "", isbn or "").upper()
    alt = _isbn_element(opf)
    if alt:
        s, e, a, w = alt
        eindeutig = re.search(r"""unique-identifier=["']([^"']+)""", opf)
        if not isbn:
            if eindeutig and a.get("id") == eindeutig.group(1):
                return opf                       # Pflicht-Kennung des Buchs bleibt stehen
            return _ausschneiden(opf, [(s, e)])[0]
        kopf = re.match(r"<dc:identifier\b[^>]*?(?=/?>)", opf[s:e]).group(0)
        wert = ("urn:isbn:" if w.lower().startswith("urn:isbn:") else "isbn:" if w.lower().startswith("isbn:")
                else "") + isbn
        return opf[:s] + f"{kopf}>{_text(wert)}</dc:identifier>" + opf[e:]
    if not isbn:
        return opf
    if epub_version(opf) >= 3:
        return _einfuegen(opf, f"<dc:identifier>urn:isbn:{isbn}</dc:identifier>")
    if "xmlns:opf" not in opf:
        m = re.search(r"<((\w+:)?metadata)\b", opf)
        if not m:
            return None
        opf = opf[:m.end()] + ' xmlns:opf="http://www.idpf.org/2007/opf"' + opf[m.end():]
    return _einfuegen(opf, f'<dc:identifier opf:scheme="ISBN">{isbn}</dc:identifier>')


def schreiben(opf, alt, neu, definitionen=None):
    """OPF mit den Feldern aus neu, die sich gegenüber alt geändert haben (Reihe/Nummer nicht -
    die schreibt library.opf_mit_reihe). Eigene Spalten ("#…") mit der Definition aus dem Buch, sonst
    aus definitionen (metadata.calibre), sonst als Textspalte. None, wenn das OPF einen ungewöhnlichen
    Aufbau hat; ValueError, wenn ein Wert nicht zum Typ seiner Spalte passt."""
    definitionen = definitionen or {}

    def anders(f):
        return f in neu and _norm(neu[f]) != _norm(alt.get(f, ""))
    if anders("titel"):
        opf = _mit_titel(opf, _norm(neu["titel"]))
    if opf is not None and (anders("autoren") or anders("autor_sort")):
        opf = _mit_autoren(opf, neu.get("autoren", alt.get("autoren", "")), neu.get("autor_sort", alt.get("autor_sort", "")))
    for f, tag in (("verlag", "publisher"), ("sprache", "language")):
        if opf is not None and anders(f):
            opf = _mit_einfach(opf, tag, _norm(neu[f]))
    if opf is not None and anders("isbn"):
        opf = _mit_isbn(opf, neu["isbn"])
    if opf is not None and anders("schlagwoerter"):
        opf = _mit_schlagwoertern(opf, neu["schlagwoerter"])
    for k in sorted(f for f in neu if f.startswith("#")):
        if opf is not None and anders(k):
            opf = mit_spalte(opf, k, _norm(neu[k]), definitionen.get(k))
    return opf


# ---------------------------------------------------------------- Calibre, KOReader
def calibre_definitionen(eintrag):
    """{"#spalte": Felddefinition ohne Wert} aus einem Eintrag von metadata.calibre."""
    erg = {}
    for k, fm in ((eintrag or {}).get("user_metadata") or {}).items():
        if isinstance(fm, dict):
            fm = dict(fm)
            fm.pop("#value#", None)
            fm.pop("#extra#", None)
            erg[k] = fm
    return erg


def calibre_werte(eintrag):
    """{feld: text} aus einem Eintrag von metadata.calibre (nur, was dort steht), eigene Spalten als "#…"."""
    from bookbench.core.library import nummer_text
    e = eintrag or {}
    if not e:
        return {}
    w = {"titel": e.get("title") or "", "autoren": " & ".join(e.get("authors") or []),
         "autor_sort": e.get("author_sort") or "", "reihe": e.get("series") or "",
         "nummer": nummer_text(e.get("series_index")) if e.get("series") else "",
         "verlag": e.get("publisher") or "",
         "sprache": sprache_kurz((e.get("languages") or [""])[0]),
         "isbn": re.sub(r"[^\dXx]", "", ((e.get("identifiers") or {}).get("isbn") or "")).upper(),
         "schlagwoerter": ", ".join(e.get("tags") or [])}
    for k, fm in (e.get("user_metadata") or {}).items():
        if k.startswith("#") and isinstance(fm, dict):
            w[k] = spalten_text(fm)
    for f in ("titel", "autoren"):              # Calibres Platzhalter für fehlende Angaben
        if w[f] in UNBEKANNT:
            w[f] = ""
    return w


def koreader_werte(pfad):
    """{feld: text} aus KOReaders custom_metadata.lua (in KOReader bearbeitete Buchinfos; KOReader zeigt
    diese statt der Werte aus der Datei). Leer, wenn es keine gibt."""
    try:
        from pathlib import Path
        from bookbench.core import toc_mark as tocmark
        datei = tocmark.sidecar_for(Path(pfad)).parent / "custom_metadata.lua"
        if not datei.exists():
            return {}
        props = tocmark.read_lua(datei).get("custom_props") or {}
    except Exception:
        return {}
    w = {}
    if props.get("title"):
        w["titel"] = str(props["title"]).strip()
    if props.get("authors"):
        w["autoren"] = " & ".join(liste(str(props["authors"]), "\n"))
    if props.get("series"):
        reihe, nummer = str(props["series"]).strip(), props.get("series_index")
        m = re.match(r"^(.*?)\s*#\s*(\d+(?:\.\d+)?)$", reihe)
        if m:
            reihe, nummer = m.group(1), nummer or m.group(2)
        w["reihe"] = reihe
        if nummer not in (None, ""):
            from bookbench.core.library import nummer_text
            w["nummer"] = nummer_text(nummer)
    if props.get("language"):
        w["sprache"] = str(props["language"]).strip()
    if props.get("keywords"):
        w["schlagwoerter"] = ", ".join(liste(str(props["keywords"]), "\n"))
    return w


def gleich(feld, a, b):
    a, b = _norm(a), _norm(b)
    if feld == "schlagwoerter":
        return {x.casefold() for x in liste(a, ",")} == {x.casefold() for x in liste(b, ",")}
    if feld == "sprache":
        return sprache_kurz(a).lower().split("-")[0] == sprache_kurz(b).lower().split("-")[0]
    if feld == "isbn":
        return re.sub(r"[^\dXx]", "", a).upper() == re.sub(r"[^\dXx]", "", b).upper()
    if feld == "nummer":
        try:
            return float((a or "0").replace(",", ".")) == float((b or "0").replace(",", "."))
        except ValueError:
            return a == b
    if feld == "autoren":
        return liste(a) == liste(b)
    return a == b


def nummer_norm(text):
    """Reihennummer wie Calibre: Komma wird Punkt (1,5 → 1.5)."""
    return _norm(text).replace(",", ".")


def unterschiede(werte, andere, felder=FELDER):
    """Felder, in denen andere einen Wert hat, der von werte abweicht."""
    return [f for f in felder if _norm(andere.get(f, "")) and not gleich(f, werte.get(f, ""), andere[f])]


def isbn_ok(isbn):
    z = re.sub(r"[^\dXx]", "", isbn or "").upper()
    if len(z) == 10 and re.fullmatch(r"\d{9}[\dX]", z):
        return sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(z)) % 11 == 0
    if len(z) == 13 and z.isdigit():
        return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(z)) % 10 == 0
    return False


def pruefen(werte, definitionen=None):
    """[(feld, Warnung)] für die Anzeige unter dem Formular; definitionen: Typen der eigenen Spalten."""
    erg = []
    if _norm(werte.get("isbn")) and not isbn_ok(werte["isbn"]):
        erg.append(("isbn", _("The ISBN is not valid (check digit or length).")))
    if not _norm(werte.get("sprache")):
        erg.append(("sprache", _("No language (KOReader needs it for hyphenation).")))
    if not _norm(werte.get("titel")):
        erg.append(("titel", _("No title.")))
    if _norm(werte.get("nummer")) and not _norm(werte.get("reihe")):
        erg.append(("nummer", _("Number without series.")))
    elif _norm(werte.get("nummer")):
        try:
            float(nummer_norm(werte["nummer"]))
        except ValueError:
            erg.append(("nummer", _("The number must be a number (e.g. 3, 1.5 or 0.9).")))
    for k, fm in (definitionen or {}).items():
        art = spalten_fehler(fm, _norm(werte.get(k, ""))) if k in werte else None
        if art:
            erg.append((k, _("{feld} must be {art}.").format(feld=fm.get("name") or k, art=art)))
    return erg
