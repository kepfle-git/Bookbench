# -*- coding: utf-8 -*-
"""
reading.py - Lesestand aus KOReader, nur lesend (seit 2.3-beta3): Status, Fortschritt, Bewertung aus den
Buchdaten (<Buch>.sdr/metadata.<endung>.lua) und Lesezeit/gelesene Seiten aus der Lesestatistik
(<KOReader-Ordner>/settings/statistics.sqlite3). Bookbench schreibt nichts davon zurück.

  laden(ordner, buecher)        ({str(pfad): Eintrag}, Herkunft) für die geöffneten Bücher:
                                 - Ordner auf einem E-Reader: frisch aus den .sdr und der Statistik
                                 - Bibliothek auf dem Rechner (library.json): der beim letzten Anstecken gemerkte
                                   Stand (Herkunft = {"stand", "reader"})
                                 - sonst die .sdr neben den Büchern, falls es welche gibt (ohne Statistik)
  vom_reader(wurzel)            {rel: Eintrag} aller Bücher auf dem Reader
  merken(bib, eintraege, reader)   in library.json ablegen ("lesestand"), {rel: Eintrag} der Bücher dort
  aus_sidecar(buchpfad)         Eintrag aus den Buchdaten oder None (Buch nie in KOReader geöffnet)
  statistik(db)                 Statistik je Buch: {"md5": {...}, "titel": {...}} (leer ohne Datei)
  partial_md5(pfad)             KOReaders Prüfsumme (util.partialMD5), mit der die Statistik Bücher erkennt
  beschreibung(e), status_text(e), zeit_text(sek)   Anzeige

Eintrag (dict, alle Schlüssel optional): status ("reading", "complete", "abandoned"; KOReader zeigt „abandoned“
als „Pausiert/On hold“), prozent (0-100), bewertung (1-5), fertig ("JJJJ-MM-TT", summary.modified bei complete),
zuletzt (Unix-Zeit: last_open der Statistik, sonst Änderungszeit der Buchdaten), zeit (Sekunden), seiten_gelesen,
seiten, markierungen. Ein leeres dict = Buch ungelesen (keine Buchdaten); None = nichts bekannt (keine Quelle).

KOReader-Quelltext: frontend/docsettings.lua (summary, percent_finished, partial_md5_checksum), frontend/util.lua
(partialMD5), plugins/statistics.koplugin/main.lua (Tabellen book und page_stat_data).
"""
import hashlib
import re
import sqlite3
import time
from pathlib import Path

from bookbench.i18n import _, ngettext

STATUS_FOLGE = {"": 0, "reading": 1, "abandoned": 2, "complete": 3}      # Sortierung der Spalte


# ---------------------------------------------------------------- Buchdaten (.sdr)
def sidecar(buchpfad):
    p = Path(buchpfad)
    stamm, __, endung = p.name.rpartition(".")
    return p.parent / f"{stamm}.sdr" / f"metadata.{endung}.lua"


def _markierungen(d):
    a = d.get("annotations")
    if isinstance(a, (list, dict)):
        return len(a)
    h = d.get("highlight")                            # bis KOReader 2024.04: {Seite = {…}}
    if isinstance(h, dict):
        return sum(len(v) if isinstance(v, (list, dict)) else 1 for v in h.values())
    if isinstance(h, list):
        return sum(len(v) if isinstance(v, (list, dict)) else 1 for v in h)
    return 0


def aus_sidecar(buchpfad):
    datei = sidecar(buchpfad)
    try:
        if not datei.is_file():
            return None
        from bookbench.core import lua_data
        d = lua_data.datei_lesen(datei)
        mtime = int(datei.stat().st_mtime)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    s = d.get("summary") if isinstance(d.get("summary"), dict) else {}
    e = {"status": str(s.get("status") or "reading"), "zuletzt": mtime}
    pf = d.get("percent_finished")
    if isinstance(pf, (int, float)):
        e["prozent"] = max(0, min(100, int(round(pf * 100))))
    if isinstance(s.get("rating"), (int, float)) and s["rating"]:
        e["bewertung"] = int(s["rating"])
    if e["status"] == "complete" and s.get("modified"):
        e["fertig"] = str(s["modified"])[:10]
    stats = d.get("stats") if isinstance(d.get("stats"), dict) else {}
    seiten = d.get("doc_pages") or stats.get("pages")
    if isinstance(seiten, (int, float)) and seiten:
        e["seiten"] = int(seiten)
    n = _markierungen(d)
    if n:
        e["markierungen"] = n
    if d.get("partial_md5_checksum"):
        e["md5"] = str(d["partial_md5_checksum"])
    return e


# ---------------------------------------------------------------- Lesestatistik
def partial_md5(pfad):
    """Wie KOReaders util.partialMD5: je 1024 Bytes an den Stellen 0 (lshift(1024, -2) ist in LuaJIT 0),
    1024, 4096, 16384, … bis 1024 << 20, solange die Datei reicht."""
    m = hashlib.md5()
    try:
        with open(pfad, "rb") as f:
            for i in range(-1, 11):
                f.seek(0 if i < 0 else 1024 << (2 * i))
                stueck = f.read(1024)
                if not stueck:
                    break
                m.update(stueck)
    except OSError:
        return ""
    return m.hexdigest()


def _norm(s):
    return re.sub(r"[^\w]+", " ", str(s or "").casefold()).strip()


def statistik(db):
    """{"md5": {md5: werte}, "titel": {(titel, erster Autor): werte}} aus statistics.sqlite3, nur lesend."""
    erg = {"md5": {}, "titel": {}}
    if not db or not Path(db).is_file():
        return erg
    try:
        con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro&immutable=1", uri=True)
    except sqlite3.Error:
        return erg
    try:
        spalten = {r[1] for r in con.execute("PRAGMA table_info(book)")}
        if not spalten:
            return erg
        wahl = [s for s in ("id", "title", "authors", "md5", "last_open", "pages", "total_read_time",
                            "total_read_pages", "highlights") if s in spalten]
        summe = {}
        try:                                          # genauer als die Zähler in book (die erst beim Schließen stimmen)
            for r in con.execute("SELECT id_book, SUM(duration), COUNT(DISTINCT page) FROM page_stat_data "
                                 "GROUP BY id_book"):
                summe[r[0]] = (r[1] or 0, r[2] or 0)
        except sqlite3.Error:
            pass
        for r in con.execute(f"SELECT {', '.join(wahl)} FROM book"):
            z = dict(zip(wahl, r))
            zeit, seiten = summe.get(z.get("id"), (z.get("total_read_time") or 0, z.get("total_read_pages") or 0))
            w = {k: v for k, v in (("zeit", int(zeit or 0)), ("seiten_gelesen", int(seiten or 0)),
                                   ("zuletzt", int(z.get("last_open") or 0)), ("seiten", int(z.get("pages") or 0)))
                 if v}
            if z.get("md5"):
                erg["md5"][str(z["md5"])] = w
            autor = (str(z.get("authors") or "").split("\n") or [""])[0]
            erg["titel"][(_norm(z.get("title")), _norm(autor))] = w
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return erg


def _mit_statistik(e, buchpfad, stat, titel="", autor=""):
    """Statistik zum Buch dazunehmen (über die Prüfsumme der Buchdaten, sonst berechnet, sonst Titel+Autor)."""
    if not stat["md5"] and not stat["titel"]:
        return e
    md5 = (e or {}).get("md5") or (partial_md5(buchpfad) if e is not None else "")
    w = stat["md5"].get(md5) if md5 else None
    if w is None and titel:
        erster = re.split(r"\s*&\s*|,", autor or "")[0]
        w = stat["titel"].get((_norm(titel), _norm(erster)))
    if not w:
        return e
    e = dict(e or {})
    for k, v in w.items():
        if k == "zuletzt":
            e[k] = max(v, e.get(k, 0)) if e.get("status") else v
        elif k == "seiten":
            e.setdefault(k, v)
        else:
            e[k] = v
    if "status" not in e and (e.get("zeit") or e.get("seiten_gelesen")):
        e["status"] = "reading"                       # Buchdaten gelöscht, Statistik kennt das Buch noch
    return e


# ---------------------------------------------------------------- Quellen
def _wurzel(ordner):
    """E-Reader, auf dem der Ordner liegt (Wurzel), oder None."""
    from bookbench.device import device as kg
    p = Path(ordner)
    for kandidat in [p] + list(p.parents)[:6]:
        if kg.ist_geraet(kandidat):
            return kandidat
    return None


def _db(wurzel):
    from bookbench.device import device as kg
    return Path(wurzel) / kg.ko_ordner(kg.art_von(wurzel)) / "settings" / "statistics.sqlite3"


def _eintrag(pfad, stat, titel="", autor=""):
    e = aus_sidecar(pfad)
    e = _mit_statistik(e, pfad, stat, titel, autor)
    if e is not None:
        e.pop("md5", None)
    return e if e is not None else {}


def vom_reader(wurzel, buecher_rel=None):
    from bookbench.core import book_import as bi
    stat = statistik(_db(wurzel))
    erg = {}
    for rel in (buecher_rel if buecher_rel is not None else bi.reader_buecher(wurzel)):
        erg[rel] = _eintrag(Path(wurzel) / rel, stat)
    return erg


def merken(bib, eintraege, reader=""):
    from bookbench.core import book_import as bi
    daten = bi.bibliothek_lesen(bib)
    daten["lesestand"] = {"stand": time.strftime("%Y-%m-%d %H:%M"), "reader": reader, "buecher": eintraege}
    bi.bibliothek_schreiben(bib, daten)
    return daten["lesestand"]


def laden(ordner, buecher):
    """({str(pfad): Eintrag}, Herkunft); Herkunft None = frisch gelesen, sonst {"stand", "reader"}."""
    from bookbench.core import book_import as bi
    wurzel = _wurzel(ordner)
    if wurzel is not None:
        stat = statistik(_db(wurzel))
        return {str(b.pfad): _eintrag(b.pfad, stat, b.titel, b.autor) for b in buecher if not b.fehler}, None
    if bi.ist_bibliothek(ordner):
        ls = bi.bibliothek_lesen(ordner).get("lesestand") or {}
        if ls.get("buecher"):
            erg = {}
            for b in buecher:
                try:
                    rel = Path(b.pfad).relative_to(ordner).as_posix()
                except ValueError:
                    continue
                if rel in ls["buecher"]:
                    erg[str(b.pfad)] = ls["buecher"][rel]
                elif not b.fehler:
                    erg[str(b.pfad)] = {}             # beim Anstecken nicht auf dem Reader: nichts gelesen
            return erg, {"stand": ls.get("stand", ""), "reader": ls.get("reader", "")}
    erg = {}
    for b in buecher:
        e = aus_sidecar(b.pfad)
        if e is not None:
            e.pop("md5", None)
            erg[str(b.pfad)] = e
    if erg:                                           # Kopie eines Readers: die übrigen sind ungelesen
        for b in buecher:
            if not b.fehler:
                erg.setdefault(str(b.pfad), {})
    return erg, None


# ---------------------------------------------------------------- Anzeige
def zeit_text(sek):
    sek = int(sek or 0)
    if sek <= 0:
        return ""
    h, m = divmod(sek // 60, 60)
    if h:
        return _("{h} h {m} min").format(h=h, m=m)
    return _("{m} min").format(m=max(1, m))


def datum_text(t):
    return time.strftime("%Y-%m-%d", time.localtime(t)) if t else ""


def status_text(e):
    """Text der Spalte Gelesen: leer (unbekannt), ungelesen, 53 %, gelesen, pausiert."""
    if e is None:
        return ""
    st = e.get("status", "")
    if not st:
        return _("unread")
    if st == "complete":
        return _("finished")
    if st == "abandoned":
        return _("on hold") + (f" ({e['prozent']} %)" if e.get("prozent") is not None else "")
    if st == "reading":
        return f"{e['prozent']} %" if e.get("prozent") is not None else _("started")
    return st


def beschreibung(e):
    """Eine Zeile für Statuszeile und Metadaten: Status, Fortschritt, zuletzt, Lesezeit, Bewertung, Markierungen."""
    if e is None:
        return ""
    teile = [status_text(e)]
    if e.get("status") == "complete" and e.get("fertig"):
        teile[0] = _("finished on {datum}").format(datum=e["fertig"])
    if e.get("zuletzt") and e.get("status"):
        teile.append(_("last read {datum}").format(datum=datum_text(e["zuletzt"])))
    if e.get("zeit"):
        teile.append(_("reading time {zeit}").format(zeit=zeit_text(e["zeit"])))
    if e.get("seiten_gelesen"):
        teile.append(ngettext("{n} page read", "{n} pages read", e["seiten_gelesen"]).format(n=e["seiten_gelesen"])
                     + (f" / {e['seiten']}" if e.get("seiten") else ""))
    if e.get("bewertung"):
        teile.append("★" * int(e["bewertung"]))
    if e.get("markierungen"):
        teile.append(ngettext("{n} highlight", "{n} highlights", e["markierungen"]).format(n=e["markierungen"]))
    return ", ".join(t for t in teile if t)


def sortierwert(e):
    if e is None:
        return (-1, 0)
    return (STATUS_FOLGE.get(e.get("status", ""), 1), e.get("prozent") or 0)

