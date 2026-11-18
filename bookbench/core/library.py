# -*- coding: utf-8 -*-
"""
library.py - Datenschicht von Bookbench (ohne Oberfläche).

  Buch            ein EPUB/KEPUB: Metadaten, Inhaltsverzeichnis, Kapitelvorschläge
                  (aus tocfix), Klappentext; dazu die Änderungen in zwei Stufen:
                  entwurf  = in der Tabelle geändert, noch nicht übernommen (rot)
                  neu      = übernommen, noch nicht gespeichert (gelb)
  buecher_finden  alle .epub/.kepub unter einem Ordner (ohne den Sicherungsordner)
  buch_laden      liest ein Buch; Entscheidungen aus tocfix_entscheidungen.json gelten
  speichern       schreibt die übernommenen Änderungen, vorher Sicherung
  cover_lesen     Titelbild als Bytes (EPUB3, EPUB2, Dateiname, guide)
  ebenen_verschieben / ebenen_umbauen
                  Ebenen im Inhaltsverzeichnis ändern (Eintrag samt Untereinträgen)
                  und nav.xhtml/toc.ncx mit der neuen Verschachtelung schreiben

Die Logik selbst steckt in tocreport.py, tocfix.py und blurbs.py; früher waren das auch
Kommandozeilenwerkzeuge (bis 0.19), daher teilen sie sich mit der Oberfläche die
Entscheidungsdatei und den Klappentext-Zwischenspeicher.
"""
import html
import json
import os
import posixpath
import re
import shutil
import time
import zipfile
from pathlib import Path

from bookbench.core import blurbs
from bookbench.core import covers as kc
from bookbench.core import toc_fix as tocfix
from bookbench.core import toc_report as tocreport
from bookbench import i18n as ks
from bookbench.i18n import _, ngettext

ORDNER = Path(__file__).resolve().parents[2]       # Programmordner; dort lagen die Datendateien bis 0.23


def _datendatei(name):
    """Datei im Einstellungsordner. Bis 0.23 lagen sie neben dem Programm; das geht nicht mehr, sobald
    ein Installer oder Updater den Programmordner ersetzt. Eine alte Datei wird beim ersten Mal kopiert."""
    neu = ks.einstellungsordner() / name
    alt = ORDNER / name
    if not neu.exists() and alt.is_file():
        try:
            neu.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(alt, neu)
        except OSError:
            return alt
    return neu


ENTSCHEIDUNGEN = _datendatei("tocfix_entscheidungen.json")     # Name aus der Zeit von tocfix.py als Skript
KLAPPENTEXT_CACHE = _datendatei("blurbs_cache.json")            # Name aus der Zeit von blurbs.py als Skript


# ---------------------------------------------------------------- Dateien
def buecher_finden(ordner, ausnehmen=()):
    wurzel = Path(ordner)
    aus = [Path(a).resolve() for a in ausnehmen if a]
    gefunden = set()
    for muster in ("*.epub", "*.kepub"):
        for f in wurzel.rglob(muster):
            r = f.resolve()
            if any(a == r or a in r.parents for a in aus):
                continue
            if f.name.endswith((".orig", ".tmp")):
                continue
            gefunden.add(f)
    return sorted(gefunden, key=lambda p: str(p).casefold())


def json_laden(pfad):
    try:
        return json.loads(Path(pfad).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def json_speichern(pfad, daten):
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_name(pfad.name + ".tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(pfad)


# ---------------------------------------------------------------- Text
def html_zu_text(h):
    """Beschreibung (HTML wie bei Calibre) -> lesbarer Text mit Absätzen."""
    if not h:
        return ""
    if "<" not in h:
        return html.unescape(h).strip()
    t = re.sub(r"(?i)<br\s*/?>", "\n", h)
    t = re.sub(r"(?i)</p\s*>|</div\s*>", "\n\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n\s*", "\n\n", t).strip()


def opf_beschreibung(opf):
    m = re.search(r"<dc:description\b[^>]*>(.*?)</dc:description>", opf, re.S)
    return html_zu_text(html.unescape(m.group(1))) if m else ""


def opf_meta(opf, name):
    for tag in re.findall(r"<meta\b[^>]*>", opf):
        if re.search(r"""name=["']%s["']""" % re.escape(name), tag):
            c = re.search(r"""content=["']([^"']*)["']""", tag)
            if c:
                return tocreport.clean(c.group(1))
    return ""


# ---------------------------------------------------------------- Buch
class Buch:
    def __init__(self, pfad):
        self.pfad = Path(pfad)
        self.titel = self.pfad.stem
        self.autor = self.reihe = self.nummer = ""
        self.verlag = self.isbn = self.sprache = ""     # zum Nachschlagen der Klappentexte
        self.reihe_quelle = ""           # "KOReader"/"Calibre", wenn die Reihe nicht im EPUB steht
        self.reihe_datei = ("", "")      # (Reihe, Nummer) so, wie sie im EPUB steht
        self.reihe_neu = None            # (Reihe, Nummer) übernommen, noch nicht gespeichert
        self.calibre = None              # passender Eintrag aus metadata.calibre
        self.uuid = ""                   # Calibre-UUID aus dem EPUB (zum Zuordnen)
        self.klappentext = ""            # aus der Datei
        self.klappentext_neu = None      # übernommen, noch nicht gespeichert
        self.klappentext_entwurf = None  # im Textfeld geändert, noch nicht übernommen
        self.klappentext_quelle = ""     # Herkunft des angezeigten Texts (URL oder Name)
        self.klappentext_quelle_datei = ""   # Herkunft laut EPUB (von der Werkstatt eingetragen)
        self.cover_datei = ""            # Pfad des Titelbilds im ZIP ("" = keins)
        self.cover_info = None           # (Breite, Höhe, Format, Bytes) des Titelbilds in der Datei
        self.cover_neu = None            # neues Bild (Bytes, schon im Zielformat), noch nicht gespeichert
        self.cover_neu_quelle = ""       # woher das neue Bild kommt (Datei, URL)
        self.opf_pfad = ""
        self.quellen = {}                # Pfad im ZIP -> (art, text) der Inhaltsverzeichnisse
        self.zeilen = []                 # [(tiefe, titel, href, schlüssel)] zur Anzeige
        self.kandidaten = {}             # schlüssel -> Kandidat aus tocfix.analyse_book
        self.uebersprungen = None
        self.vorschlag = {}              # schlüssel -> neuer Titel (Vorschläge + Entscheidungen)
        self.neu = {}                    # schlüssel -> Titel, übernommen
        self.entwurf = None              # schlüssel -> Titel, in der Tabelle geändert (None = keiner)
        self.tiefen_neu = None           # [Ebene je Zeile], übernommen, noch nicht gespeichert
        self.tiefen_entwurf = None       # [Ebene je Zeile], verschoben, noch nicht übernommen
        self.ebenen_sperre = ""          # Grund, warum sich die Ebenen nicht ändern lassen
        self.gespeichert = False         # seit dem Öffnen gespeichert
        self.fehler = ""

    # Bezeichnung für Listen
    @property
    def name(self):
        return self.titel or self.pfad.name

    @property
    def schluessel(self):
        return str(self.pfad)

    # -- Zustand ---------------------------------------------------------------
    def stand(self):
        """Statusstreifen: rot / gelb / gruen / None."""
        if self.entwurf is not None or self.klappentext_entwurf is not None or self.tiefen_entwurf is not None:
            return "rot"
        if self.neu or self.klappentext_neu is not None or self.reihe_neu is not None or self.tiefen_neu is not None \
                or self.cover_neu is not None:
            return "gelb"
        return "gruen" if self.gespeichert else None

    def warnung(self):
        offen = [k for k in self.kandidaten.values() if k["reasons"] and k["schluessel"] not in self.neu]
        if self.fehler:
            return self.fehler
        if offen:
            return ngettext("{n} questionable chapter name", "{n} questionable chapter names", len(offen)).format(n=len(offen))
        return None

    def _ohne_namen(self):
        """(Anzahl Einträge ohne Namen, ob das noch "ok" ist) - wenige davon sind normal."""
        ohne = len(self.kandidaten)
        kapitel = sum(1 for z in self.zeilen if z[0] == max(z[0] for z in self.zeilen))
        return ohne, ohne <= max(2, kapitel // 4)

    def einzelne_ohne_namen(self):
        """Filter "Kapitel: einzelne ohne Namen": keine Vorschläge, aber ein paar Einträge nur mit Nummer."""
        if not self.zeilen or self.uebersprungen or self.vorschlag or not self.kandidaten:
            return False
        return self._ohne_namen()[1]

    def kapitel_zustand(self):
        if not self.zeilen:
            return _("no table of contents")
        if self.uebersprungen:
            return _("no names found")
        n = len(self.vorschlag)
        if n:
            return ngettext("{n} suggestion", "{n} suggestions", n).format(n=n)
        # Einträge, die nur eine Nummer sind ("Eighteen", "Prologue") - wenige davon sind normal
        if not self.kandidaten:
            return "ok"
        ohne, normal = self._ohne_namen()
        return _("ok ({n} without names)").format(n=ohne) if normal else _("without names")

    def original_tiefen(self):
        return [z[0] for z in self.zeilen]

    def aktuelle_tiefen(self):
        """Ebene je Zeile, wie sie angezeigt werden soll (Entwurf vor Übernommenem vor Datei)."""
        if self.tiefen_entwurf is not None:
            return list(self.tiefen_entwurf)
        if self.tiefen_neu is not None:
            return list(self.tiefen_neu)
        return self.original_tiefen()

    def aktuelle_titel(self):
        """schlüssel -> Titel, wie er angezeigt werden soll (Entwurf vor Übernommenem vor Vorschlag)."""
        d = dict(self.vorschlag)
        d.update(self.neu)
        if self.entwurf is not None:
            d = dict(self.entwurf)
        return d


def opf_uuid(opf):
    """Calibre-UUID aus dc:identifier (opf:scheme="uuid" bzw. id="uuid_id"), sonst ""."""
    for attrs, wert in re.findall(r"<dc:identifier\b([^>]*)>(.*?)</dc:identifier>", opf, re.S):
        if re.search(r"""(scheme=["'](calibre:)?uuid["']|id=["']uuid_id["'])""", attrs, re.I):
            return tocreport.clean(wert).replace("urn:uuid:", "")
    return ""


# ---------------------------------------------------------------- Calibre (metadata.calibre)
def calibre_finden(ordner):
    """metadata.calibre im Ordner oder einem darüber (Calibre legt sie ins Hauptverzeichnis
    des Kobo). Rückgabe (Ordner der Datei, Liste der Einträge) oder (None, [])."""
    o = Path(ordner).resolve()
    for kandidat in [o] + list(o.parents):
        for name in ("metadata.calibre", ".metadata.calibre"):
            f = kandidat / name
            if f.is_file():
                try:
                    daten = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(daten, list):
                    return kandidat, daten
    return None, []


def _norm_titel(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").casefold()).strip()


def calibre_zuordnen(buecher, wurzel, eintraege):
    """Ordnet jedem Buch seinen Calibre-Eintrag zu: über den Pfad (lpath), den Dateinamen
    (auch bei Kopien in anderen Ordnern), die UUID oder Titel + Autor."""
    nach_pfad, nach_name, nach_uuid, nach_titel = {}, {}, {}, {}
    for e in eintraege:
        lp = (e.get("lpath") or "").replace("\\", "/")
        nach_pfad[lp.casefold()] = e
        nach_name.setdefault(lp.rsplit("/", 1)[-1].casefold(), []).append(e)
        if e.get("uuid"):
            nach_uuid[e["uuid"]] = e
        autor = (e.get("authors") or [""])[0]
        nach_titel.setdefault((_norm_titel(e.get("title")), _norm_titel(autor)), []).append(e)
    for b in buecher:
        e = None
        if wurzel is not None:
            try:
                e = nach_pfad.get(b.pfad.resolve().relative_to(wurzel).as_posix().casefold())
            except ValueError:
                pass
        if e is None and len(nach_name.get(b.pfad.name.casefold(), [])) == 1:
            e = nach_name[b.pfad.name.casefold()][0]
        if e is None and getattr(b, "uuid", ""):
            e = nach_uuid.get(b.uuid)
        if e is None:
            treffer = nach_titel.get((_norm_titel(b.titel), _norm_titel(b.autor)), [])
            e = treffer[0] if len(treffer) == 1 else None
        b.calibre = e
        if e and not b.reihe and e.get("series"):           # Anzeige, solange nicht übernommen
            b.reihe, b.nummer = e["series"], nummer_text(e.get("series_index"))
            b.reihe_quelle = "Calibre"


def nummer_text(n):
    if n in (None, ""):
        return ""
    try:
        f = float(n)
    except (TypeError, ValueError):
        return str(n)
    return str(int(f)) if f == int(f) else f"{f:g}"


def calibre_vorschlag(b):
    """Was aus Calibre übernommen werden kann: (Reihe/Nummer oder None, Klappentext oder None).
    Nur, wo im EPUB nichts steht - vorhandene Angaben werden nie überschrieben."""
    e = b.calibre
    if not e:
        return None, None
    reihe = None
    if e.get("series") and not b.reihe_datei[0] and b.reihe_neu is None:
        reihe = (e["series"], nummer_text(e.get("series_index")))
    text = None
    vorhanden = b.klappentext_neu if b.klappentext_neu is not None else b.klappentext
    if e.get("comments") and not vorhanden.strip() and b.klappentext_entwurf is None:
        text = html_zu_text(e["comments"])
    return reihe, text or None


def opf_mit_reihe(opf, reihe, nummer):
    """Reihe im Calibre-Stil eintragen (so liest KOReader sie); alte Calibre-Reihenangaben ersetzen."""
    opf = re.sub(r"""\s*<meta\b[^>]*name=["']calibre:series(_index)?["'][^>]*/?>""", "", opf)
    neu = f'<meta name="calibre:series" content="{html.escape(reihe)}"/>'
    if nummer:
        neu += f'<meta name="calibre:series_index" content="{html.escape(nummer)}"/>'
    m = re.search(r"</(\w+:)?metadata>", opf)
    return opf[:m.start()] + neu + "\n" + opf[m.start():] if m else None


def koreader_reihe(pfad):
    """Reihe aus KOReaders eigenen Buchdaten (in KOReader bearbeitete Metadaten):
    <Buch>.sdr/custom_metadata.lua, Tabelle custom_props. Liegt nur vor, wenn der
    Ordner mit den .sdr-Ordnern geöffnet wird (z. B. direkt der Kobo)."""
    try:
        from bookbench.core import toc_mark as tocmark
        datei = tocmark.sidecar_for(Path(pfad)).parent / "custom_metadata.lua"
        if not datei.exists():
            return "", ""
        props = tocmark.read_lua(datei).get("custom_props") or {}
    except Exception:
        return "", ""
    reihe = str(props.get("series") or "").strip()
    nummer = props.get("series_index")
    m = re.match(r"^(.*?)\s*#\s*(\d+(?:\.\d+)?)$", reihe)      # "Horus Heresy #3"
    if m:
        reihe, nummer = m.group(1), nummer or m.group(2)
    return reihe, "" if nummer in (None, "") else str(nummer)


_ATTR = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def _attribute(tag):
    return {m.group(1).lower(): html.unescape(m.group(2) if m.group(2) is not None else m.group(3))
            for m in _ATTR.finditer(tag)}


def cover_pfad(opf, opf_pfad):
    """Pfad des Titelbilds im EPUB oder None. Reihenfolge: EPUB3 properties="cover-image",
    EPUB2 <meta name="cover">, ein Bild mit "cover" in id/Dateiname, <guide type="cover">
    (Seite mit dem Bild, Pfad zur Seite; das Bild sucht cover_lesen darin)."""
    basis = posixpath.dirname(opf_pfad)

    def voll(href):
        return posixpath.normpath(posixpath.join(basis, href.split("#")[0]))
    items = [_attribute(m.group(0)) for m in re.finditer(r"<(?:\w+:)?item\b[^>]*>", opf)]
    bilder = [i for i in items if i.get("media-type", "").startswith("image/") and i.get("href")]
    for i in bilder:
        if "cover-image" in i.get("properties", "").split():
            return voll(i["href"])
    for m in re.finditer(r"<(?:\w+:)?meta\b[^>]*>", opf):
        a = _attribute(m.group(0))
        if a.get("name") == "cover" and a.get("content"):
            for i in bilder:
                if i.get("id") == a["content"]:
                    return voll(i["href"])
    for i in bilder:
        if "cover" in i.get("id", "").lower() or "cover" in posixpath.basename(i["href"]).lower():
            return voll(i["href"])
    for m in re.finditer(r"<(?:\w+:)?reference\b[^>]*>", opf):
        a = _attribute(m.group(0))
        if a.get("type", "").lower() in ("cover", "title-page") and a.get("href"):
            return voll(a["href"])
    return None


def cover_bild_pfad(z, opf, opf_pfad):
    """Pfad der Bilddatei des Titelbilds im ZIP oder None. Zeigt cover_pfad auf eine
    Titelseite, ist es das erste Bild darin."""
    p = cover_pfad(opf, opf_pfad)
    if not p:
        return None
    namen = set(z.namelist())
    if p.lower().endswith((".xhtml", ".html", ".htm")) and p in namen:   # Titelseite: erstes Bild darin
        seite = z.read(p).decode("utf-8", "replace")
        m = re.search(r"""<(?:img|image)\b[^>]*?(?:src|xlink:href|href)\s*=\s*["']([^"']+)""", seite)
        if not m:
            return None
        p = posixpath.normpath(posixpath.join(posixpath.dirname(p), html.unescape(m.group(1))))
    return p if p in namen else None


def cover_laden(pfad):
    """(Pfad im ZIP, Bytes) des Titelbilds oder (None, None) - auch bei kaputten Dateien."""
    try:
        with zipfile.ZipFile(pfad) as z:
            opf_pfad, opf = blurbs.read_opf(z)
            p = cover_bild_pfad(z, opf, opf_pfad)
            return (p, z.read(p)) if p else (None, None)
    except (OSError, KeyError, zipfile.BadZipFile, AttributeError):
        return None, None


def cover_lesen(pfad):
    """Bytes des Titelbilds oder None (auch bei kaputten Dateien)."""
    return cover_laden(pfad)[1]


COVER_NEU_ID = "cover-bookbench"


def opf_mit_cover(opf, opf_pfad, fmt):
    """Für ein Buch ohne Cover: Manifest-Eintrag (EPUB3 mit properties="cover-image") und
    <meta name="cover"> (EPUB2, liest auch KOReader) ergänzen. Gibt (opf, Pfad im ZIP) zurück,
    oder (None, None), wenn das OPF ungewöhnlich aufgebaut ist."""
    href = f"{COVER_NEU_ID}.{kc.ENDUNG[fmt]}"
    epub3 = re.search(r"""<(?:\w+:)?package\b[^>]*\bversion=["']3""", opf) is not None
    item = (f'<item id="{COVER_NEU_ID}" href="{href}" media-type="{kc.MEDIENTYP[fmt]}"'
            + (' properties="cover-image"' if epub3 else "") + "/>")
    m = re.search(r"</(\w+:)?manifest>", opf)
    if not m:
        return None, None
    opf = opf[:m.start()] + item + "\n" + opf[m.start():]
    if not re.search(r"""<(?:\w+:)?meta\b[^>]*name=["']cover["']""", opf):
        m = re.search(r"</(\w+:)?metadata>", opf)
        if not m:
            return None, None
        opf = opf[:m.start()] + f'<meta name="cover" content="{COVER_NEU_ID}"/>\n' + opf[m.start():]
    return opf, posixpath.normpath(posixpath.join(posixpath.dirname(opf_pfad), href))


# ---------------------------------------------------------------- Ebenen
def ebenen_fehler(tiefen):
    """None, wenn die Folge als Verschachtelung möglich ist, sonst der Grund."""
    for i, d in enumerate(tiefen):
        if d < 1:
            return _("cannot go higher than the top level")
        if i == 0 and d != 1:
            return _("the first entry must be on the top level")
        if i and d > tiefen[i - 1] + 1:
            return _("an entry can be at most one level deeper than the one above")
    return None


def ebenen_verschieben(tiefen, indizes, richtung):
    """Gewählte Zeilen samt ihren Untereinträgen eine Ebene tiefer (+1) oder höher (-1).
    Gibt die neue Liste zurück; ValueError mit Begründung, wenn das nicht geht."""
    bewegen = set()
    for i in sorted(indizes):
        bewegen.add(i)
        for j in range(i + 1, len(tiefen)):
            if tiefen[j] <= tiefen[i]:
                break
            bewegen.add(j)
    neu = [d + richtung if i in bewegen else d for i, d in enumerate(tiefen)]
    fehler = ebenen_fehler(neu)
    if fehler:
        raise ValueError(fehler)
    return neu


def _nav_toc_bereich(src):
    """(Anfang, Ende) der äußeren <ol> im Inhaltsverzeichnis-<nav> von nav.xhtml oder None."""
    m = re.search(r"""<nav\b[^>]*epub:type\s*=\s*["'][^"']*\btoc\b[^"']*["'][^>]*>""", src) \
        or re.search(r"<nav\b[^>]*>", src)
    if not m:
        return None
    ende_nav = src.find("</nav>", m.end())
    o = re.compile(r"<ol\b[^>]*>").search(src, m.end(), ende_nav)
    zu = src.rfind("</ol>", m.end(), ende_nav)
    if not o or zu < 0:
        return None
    return o.start(), zu + len("</ol>")


_NCX_PUNKT = re.compile(r"<navPoint\b[^>]*>.*?<content\b[^>]*?(?:/>|>\s*</content>)", re.S)


def _ncx_bereich(src):
    m = re.search(r"<navMap\b[^>]*>", src)
    if not m:
        return None
    zu = src.find("</navMap>", m.end())
    return (m.end(), zu) if zu > 0 else None


def toc_eintraege(art, src):
    """Anzahl der Einträge, die ebenen_umbauen umstellen würde (None: Aufbau unbekannt)."""
    if art == "nav":
        b = _nav_toc_bereich(src)
        return len(tocfix.NAV_A.findall(src[b[0]:b[1]])) if b else None
    b = _ncx_bereich(src)
    return len(_NCX_PUNKT.findall(src[b[0]:b[1]])) if b else None


def ebenen_umbauen(art, src, tiefen):
    """Baut die Verschachtelung von nav.xhtml (<ol>/<li>) bzw. toc.ncx (<navPoint>) neu auf.
    Die Einträge selbst (<a …>…</a> bzw. navPoint mit id, playOrder, navLabel, content)
    bleiben Zeichen für Zeichen erhalten, ebenso ihre Reihenfolge; nur die Ebene ändert
    sich. Attribute an <li>/<ol> innerhalb des Verzeichnisses gehen dabei verloren."""
    if ebenen_fehler(tiefen):
        raise ValueError(ebenen_fehler(tiefen))
    if art == "nav":
        b = _nav_toc_bereich(src)
        if not b:
            raise ValueError(_("table of contents not found in nav.xhtml"))
        anker = [m.group(0) for m in tocfix.NAV_A.finditer(src, b[0], b[1])]
        if len(anker) != len(tiefen):
            raise ValueError(_("{datei} has {n} entries instead of {soll}").format(datei="nav.xhtml", n=len(anker),
                                                                                  soll=len(tiefen)))
        aus, ebene = "", 0
        for d, a in zip(tiefen, anker):
            einzug = "\n" + "  " * d
            if d > ebene:
                aus += "<ol>" + einzug + "<li>"
            else:
                aus += "</li>"
                for e in range(ebene, d, -1):
                    aus += "\n" + "  " * e + "</ol></li>"
                aus += einzug + "<li>"
            aus += a
            ebene = d
        aus += "</li>"
        for e in range(ebene, 1, -1):
            aus += "\n" + "  " * e + "</ol></li>"
        aus += "\n</ol>"
        return src[:b[0]] + aus + src[b[1]:]
    b = _ncx_bereich(src)
    if not b:
        raise ValueError(_("navMap not found in toc.ncx"))
    innen = src[b[0]:b[1]]
    punkte = list(_NCX_PUNKT.finditer(innen))
    if len(punkte) != len(tiefen):
        raise ValueError(_("{datei} has {n} entries instead of {soll}").format(datei="toc.ncx", n=len(punkte),
                                                                              soll=len(tiefen)))
    aus, ebene = innen[:punkte[0].start()] if punkte else innen, 0
    for d, m in zip(tiefen, punkte):
        if d <= ebene:
            aus += "</navPoint>" * (ebene - d + 1)
        aus += "\n" + "  " * d + m.group(0)
        ebene = d
    aus += "</navPoint>" * ebene + "\n"
    neu = src[:b[0]] + aus + src[b[1]:]
    return re.sub(r"""(<meta\b[^>]*name=["']dtb:depth["'][^>]*content=["'])\d+""",
                  lambda m: m.group(1) + str(max(tiefen, default=1)), neu)


def _schluessel(href, titel):
    return (href, tocfix.norm(titel))


def buch_laden(pfad, max_sub=1, caps=False, entscheidungen=None):
    """Liest ein Buch komplett. Fehler landen in buch.fehler statt als Ausnahme."""
    b = Buch(pfad)
    try:
        with zipfile.ZipFile(pfad) as z:
            b.opf_pfad, opf = blurbs.read_opf(z)
            b.titel, b.autor, __, __ = blurbs.book_info(opf)
            b.verlag, b.isbn, b.sprache = blurbs.book_extra(opf)
            b.titel = b.titel or b.pfad.stem
            b.reihe, b.nummer = tocreport.reihe_aus_opf(opf)
            b.reihe_datei = (b.reihe, b.nummer)
            b.uuid = opf_uuid(opf)
            if not b.reihe:                               # nur in KOReader eingetragen?
                b.reihe, b.nummer = koreader_reihe(b.pfad)
                b.reihe_quelle = "KOReader" if b.reihe else ""
            if b.nummer.endswith(".0"):
                b.nummer = b.nummer[:-2]
            b.klappentext = opf_beschreibung(opf)
            b.klappentext_quelle = b.klappentext_quelle_datei = blurbs.source_aus(opf) if b.klappentext else ""
            cp = cover_bild_pfad(z, opf, b.opf_pfad)
            if cp:
                daten = z.read(cp)
                info = kc.bild_info(daten)
                b.cover_datei = cp
                b.cover_info = (info[0], info[1], info[2], len(daten)) if info else (0, 0, "?", len(daten))
            __, tocs = tocfix.toc_files(z)
            namen = set(z.namelist())
            eintraege = []
            for art, p in tocs:
                if p in namen:
                    b.quellen[p] = (art, z.read(p).decode("utf-8-sig", "replace"))
                    eintraege += tocfix.entries_of(art, b.quellen[p][1], posixpath.dirname(p))
            neu, items, b.uebersprungen = tocfix.analyse_book(z, eintraege, b.titel, max_sub)
        __, toc = tocreport.read_toc(pfad)
        b.zeilen = [(t, titel, href, _schluessel(href, titel)) for t, titel, href in toc]
        for p, (art, src) in b.quellen.items():          # lassen sich die Ebenen umbauen?
            n = toc_eintraege(art, src)
            if n != len(b.zeilen):
                b.ebenen_sperre = (_("{datei} has an unusual structure").format(datei=posixpath.basename(p))
                                   if n is None else
                                   _("{datei} has {n} entries instead of {soll}").format(
                                       datei=posixpath.basename(p), n=n, soll=len(b.zeilen)))
                break
        for i in items:
            i["schluessel"] = i["key"]
            i["dkey"] = f"{b.titel or b.pfad.name}|{i['key'][0]}|{i['old']}"
            b.kandidaten[i["key"]] = i
        b.vorschlag = dict(neu)
        for i in items:                                   # gespeicherte Entscheidungen
            if entscheidungen and i["dkey"] in entscheidungen:
                t = entscheidungen[i["dkey"]]
                if t:
                    b.vorschlag[i["key"]] = t
                else:
                    b.vorschlag.pop(i["key"], None)
                i["reasons"] = []                         # entschieden = nicht mehr fragwürdig
        if caps:
            for __, titel, __, k in b.zeilen:
                if k not in b.vorschlag and titel.isupper() and len(titel) > 3 and tocfix.nice(titel) != titel:
                    b.vorschlag[k] = tocfix.nice(titel)
    except Exception as e:                                # kaputte Datei: anzeigen statt abbrechen
        b.fehler = _("not readable ({fehler})").format(fehler=e)
    return b


def textanfang(buch, href, zeilen=6):
    """Erste Zeilen Buchtext an einer Verzeichnisstelle (für die Anzeige unter der Tabelle)."""
    try:
        with zipfile.ZipFile(buch.pfad) as z:
            return tocreport.text_lines(z, href, set(z.namelist()))[:zeilen]
    except Exception:
        return []


# ---------------------------------------------------------------- Entscheidungen
def entscheidungen_merken(buch, entscheidungen):
    """Nach dem Übernehmen: für jeden nummerierten Eintrag festhalten, was gilt
    (Titel oder None = Original)."""
    for k, i in buch.kandidaten.items():
        t = buch.neu.get(k)                   # nach dem Übernehmen ist buch.neu der vollständige Stand
        entscheidungen[i["dkey"]] = t if t and t != i["old"] else None


# ---------------------------------------------------------------- Speichern
def sicherung_anlegen(pfad, ordner, anzahl):
    """<Ordner>/<Name>_JJJJMMTT_HHMMSS<Endung>; nur die neuesten `anzahl` je Datei bleiben.
    Endung bleibt erhalten, aber der Ordner sollte nicht auf dem Kobo liegen
    (sonst zeigt KOReader die Sicherungen als Bücher)."""
    ordner = Path(ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    name = pfad.name
    stamm, endung = (name[:-len(".kepub.epub")], ".kepub.epub") if name.endswith(".kepub.epub") \
        else (pfad.stem, pfad.suffix)
    ziel = ordner / f"{stamm}_{time.strftime('%Y%m%d_%H%M%S')}{endung}"
    shutil.copy2(pfad, ziel)
    alte = sorted(ordner.glob(f"{glob_escape(stamm)}_????????_??????{endung}"))
    for a in alte[:-anzahl] if anzahl > 0 else []:
        try:
            a.unlink()
        except OSError:
            pass
    return ziel


def glob_escape(s):
    return re.sub(r"([*?\[])", r"[\1]", s)


def speichern(buch, sicherungsordner, anzahl=5):
    """Übernommene Änderungen (buch.neu, buch.klappentext_neu) ins EPUB schreiben."""
    geaendert = {}
    if buch.neu or buch.tiefen_neu is not None:
        if buch.tiefen_neu is not None and buch.ebenen_sperre:
            raise ValueError(_("levels cannot be changed: {grund}").format(grund=buch.ebenen_sperre))
        for p, (art, src) in buch.quellen.items():
            aus, n = tocfix.rewrite(art, src, posixpath.dirname(p), buch.neu) if buch.neu else (src, 0)
            if buch.tiefen_neu is not None and buch.tiefen_neu != buch.original_tiefen():
                aus = ebenen_umbauen(art, aus, buch.tiefen_neu)
            if aus != src:
                geaendert[p] = aus
    neue_dateien = {}
    if buch.cover_neu is not None:
        with zipfile.ZipFile(buch.pfad) as z:
            opf_pfad, opf = blurbs.read_opf(z)
            ziel = cover_bild_pfad(z, opf, opf_pfad)
        info = kc.bild_info(buch.cover_neu)
        if not info:
            raise ValueError(_("the new cover is not a readable image"))
        if ziel:
            alt = buch.cover_info[2] if buch.cover_info else None
            if alt and alt != "?" and alt != info[2]:
                raise ValueError(_("the new cover has the wrong format ({neu} instead of {alt})")
                                 .format(neu=info[2], alt=alt))
            neue_dateien[ziel] = buch.cover_neu
        else:
            neu_opf, ziel = opf_mit_cover(opf, opf_pfad, info[2])
            if neu_opf is None:
                raise ValueError(_("the metadata file has an unusual format"))
            geaendert[opf_pfad] = neu_opf
            neue_dateien[ziel] = buch.cover_neu
    if buch.klappentext_neu is not None or buch.reihe_neu is not None:
        with zipfile.ZipFile(buch.pfad) as z:
            opf_pfad, opf = blurbs.read_opf(z)
        neu_opf = geaendert.get(opf_pfad, opf)
        if buch.klappentext_neu is not None:
            neu_opf = blurbs.with_description(neu_opf, buch.klappentext_neu, buch.klappentext_quelle) \
                if buch.klappentext_neu.strip() else blurbs.with_source(
                    re.sub(r"<dc:description\b[^>]*/>|<dc:description\b[^>]*>.*?</dc:description>\s*", "", neu_opf,
                           flags=re.S), "")
        if neu_opf is not None and buch.reihe_neu is not None:
            neu_opf = opf_mit_reihe(neu_opf, *buch.reihe_neu)
        if neu_opf is None:
            raise ValueError(_("the metadata file has an unusual format"))
        geaendert[opf_pfad] = neu_opf
    geaendert.update(neue_dateien)
    if not geaendert:
        return None
    sicherung = sicherung_anlegen(buch.pfad, sicherungsordner, anzahl)
    tmp = buch.pfad.with_name(buch.pfad.name + ".tmp")
    tocfix.write_copy(buch.pfad, tmp, geaendert)
    os.replace(tmp, buch.pfad)
    return sicherung
