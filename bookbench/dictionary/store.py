# -*- coding: utf-8 -*-
"""
store.py - eigene Wörterbücher lesen, bearbeiten, aufbauen. Keine Oberfläche.

Zwei Arten, mit derselben Schnittstelle (Basis):
  Woerterbuch          Datenbank von wikidict.py (wikidict.sqlite, früher wh40kdict.sqlite). Art "wiki" (aus einem
                       Wiki aufgebaut) oder "leer" (nur eigene Einträge, Namen aus Büchern).
                       Eigene/geänderte Einträge in der Tabelle own; sie gewinnen immer.
  StarDictWoerterbuch  ein fertiges StarDict-Wörterbuch (.ifo/.idx/.dict), ohne Datenbank.
                       Änderungen bis zum Erzeugen in bookbench.json (alt: werkstatt.json) im Wörterbuch-Ordner,
                       Erzeugen schreibt die Dateien neu (vorher Sicherung).

  oeffnen(pfad)        passende Art zu einem Ordner/einer Datei
  anlegen(...)         neues Wörterbuch (Datenbank) mit Profil
  ki_eintrag()         Eintrag von Claude: Websuche, aus einer Seite, aus eigenem Wissen
  nachschlageverlauf() Wörter aus KOReaders settings/lookup_history.lua
  html_teile()         Wörterbuch-HTML als (Text, Stile) für die Vorschau
  schritt()            einen Schritt von wikidict.py (titles, scan, fetch, summarize,
                       crosscheck) im eigenen Thread ausführen, Ausgabe und Rückfragen umgeleitet

Einträge sind dicts: strukturiert {category, tagline, sections, aliases} oder
{html, aliases} bzw. {text, aliases} für eingelesene Einträge anderer Wörterbücher.
"""
import html
import json
import os
import re
import shutil
import time
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from bookbench.dictionary import stardict as ksd
from bookbench.dictionary import wikidict as W
from bookbench.i18n import N_, _

KATEGORIEN = W.CATEGORIES
AUSLASSEN = {"Publication"}                       # wie wikidict build --skip-categories
QUELLE_EIGEN = "own entry"
FELDER = ("category", "tagline", "sections", "aliases", "html", "text")
PROFIL_FELDER = ("topic", "name", "stem", "spoilers", "buecher", "wiki", "check_site")
WERKSTATT_JSON = "bookbench.json"
WERKSTATT_JSON_ALT = "werkstatt.json"           # Name bis 0.24; eine vorhandene wird weiter benutzt


def _arbeitsdatei(ordner):
    neu, alt = Path(ordner) / WERKSTATT_JSON, Path(ordner) / WERKSTATT_JSON_ALT
    return alt if not neu.exists() and alt.exists() else neu


def jetzt():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def sauber(data):
    """Nur die Felder, die gespeichert werden."""
    return {k: v for k, v in data.items() if k in FELDER and v is not None}


# ================================================================ gemeinsame Teile
class Basis:
    art = ""

    def __init__(self):
        self.eintraege, self.quellen, self.buecher = {}, {}, {}
        self.basis = {}                           # ohne eigene Änderungen (für "Original")
        self.eigen = {}                           # Titel -> (data, Quelle, geändert)
        self.synonyme = set()                     # {(Wort, Stichwort)}
        self._index = {}

    # -- Profil (Thema, Name, Spoiler, Bücherfilter …) ------------------------------
    def profil(self):
        raise NotImplementedError

    def titel(self):
        return self.profil().get("name") or self.pfad.name

    # -- Suche -------------------------------------------------------------------------
    def _index_bauen(self):
        self._index = defaultdict(set)
        for t in self.eintraege:
            self._index[t.casefold()].add(t)
        for w, t in self.synonyme:
            self._index[w.casefold()].add(t)

    def suchen(self, text):
        t = text.strip().casefold()
        if not t:
            return sorted(self.eintraege, key=str.casefold)
        exakt = self._index.get(t, set())
        teil = {s for w, ss in self._index.items() if t in w for s in ss}
        return sorted(exakt, key=str.casefold) + sorted(teil - exakt, key=str.casefold)

    def bekannt(self, wort):
        return wort.casefold() in self._index

    def synonyme_von(self, titel):
        return sorted(w for w, t in self.synonyme if t == titel)

    def ist_eigen(self, titel):
        return titel in self.eigen

    def geloescht(self):
        return sorted(t for t, (d, __, __) in self.eigen.items() if d.get("deleted"))

    # -- Fehlende Begriffe ----------------------------------------------------------
    def eigene_buecher(self):
        """Bücher, aus denen die Begriffe dieses Wörterbuchs stammen (für den Verlauf-Filter)."""
        return set()

    def buch_passt(self, titel, bibliothek=None):
        """Gehört ein nachgeschlagenes Wort aus diesem Buch zu diesem Wörterbuch? Muster aus dem
        Profil (Teile von Titel, Reihe oder Autor) und die Bücher aus wikidict scan; ohne
        beides passt jedes Buch."""
        muster = [m.casefold() for m in self.profil().get("buecher") or [] if m.strip()]
        eigene = self.eigene_buecher()
        if not muster and not eigene:
            return True
        if titel in eigene:
            return True
        reihe, autor = (bibliothek or {}).get(titel, ("", ""))
        text = f"{titel}\n{reihe}\n{autor}".casefold()
        return any(m in text for m in muster)

    def _luecken(self):
        """[{name, grund, n, buecher}] aus wikidict scan (nur Datenbank)."""
        return []

    def fehlende(self, verlauf=(), bibliothek=None):
        ignoriert = {n.casefold() for n in self.ignorierte()}
        geloescht = {t.casefold() for t in self.geloescht()}
        erg = {}
        for e in self._luecken():
            k = e["name"].casefold()
            if not (self.bekannt(e["name"]) or k in ignoriert or k in geloescht):
                erg[k] = dict(e, nachgeschlagen=0)
        zaehler, buecher_von = Counter(), defaultdict(Counter)
        for wort, buch, __ in verlauf:
            w = _wort(wort)
            if not w or self.bekannt(w) or w.casefold() in ignoriert or not _eigenname(w):
                continue
            if not self.buch_passt(buch, bibliothek):
                continue
            zaehler[w] += 1
            if buch:
                buecher_von[w][buch] += 1
        for w, n in zaehler.items():
            e = erg.setdefault(w.casefold(), {"name": w, "grund": "", "n": 0,
                                              "buecher": list(buecher_von[w].items()), "nachgeschlagen": 0})
            e["nachgeschlagen"] += n
            text = _("looked up on the e-reader ({n}×)").format(n=n)
            e["grund"] = f"{text}; {e['grund']}" if e["grund"] else text
        return sorted(erg.values(), key=lambda e: (-e["nachgeschlagen"], -e["n"], e["name"].casefold()))

    def vorschau(self, titel, data=None, quelle=None):
        """HTML des Eintrags, wie es im Wörterbuch steht; data/quelle: ungespeicherte Fassung."""
        if data is None:
            data = self.eintraege.get(titel)
            quelle = self.quellen.get(titel, QUELLE_EIGEN)
        if not data:
            return ""
        if data.get("text") is not None:
            return html.escape(data["text"]).replace("\n", "<br/>")
        return W.render(titel, data, self.buecher.get(titel, []), quelle or QUELLE_EIGEN)


# ================================================================ Datenbank (wikidict)
class Woerterbuch(Basis):
    def __init__(self, pfad):
        super().__init__()
        p = Path(pfad).expanduser()
        if p.is_dir():
            p = W.db_datei(p)
        if not p.is_file():
            raise FileNotFoundError(_("{pfad} not found").format(pfad=p))
        self.pfad = p.parent
        self.datei = p
        self.db = W.open_db(p.parent)           # legt own/ignored an, falls es sie nicht gibt
        self.laden()

    @property
    def art(self):
        a = W.meta_get(self.db, "art")
        if a:
            return a
        return "wiki" if self.db.execute("SELECT 1 FROM titles LIMIT 1").fetchone() or \
            self.db.execute("SELECT 1 FROM entries LIMIT 1").fetchone() else "leer"

    def schliessen(self):
        self.db.close()

    def profil(self):
        return W.profil_laden(self.db)

    def profil_setzen(self, werte):
        W.profil_laden(self.db, {k: v for k, v in werte.items() if k in PROFIL_FELDER})
        self.laden()

    def laden(self):
        W.profil_laden(self.db)                  # setzt W.PROFIL (Quellenangaben, Dateiname)
        host = W.wiki_host()
        self.eintraege, self.quellen, self.buecher, extra, redirs = W.collect(self.db, host, AUSLASSEN)
        self.basis = W.collect(self.db, host, AUSLASSEN, include_own=False)[0]
        self.eigen = {t: (json.loads(d), q, g) for t, d, q, g in
                      self.db.execute("SELECT title, data, source, changed FROM own")}
        self.synonyme = W.synonyms(self.eintraege, redirs, extra)
        self._index_bauen()

    def erzeugt_am(self):
        return W.meta_get(self.db, "built_at", "")

    def ausgabe(self):
        return W.meta_get(self.db, "built_out", "")

    def stand(self, titel):
        e = self.eigen.get(titel)
        return "gelb" if e and (e[2] or "") > self.erzeugt_am() else None

    def ignorierte(self):
        return sorted((n for (n,) in self.db.execute("SELECT name FROM ignored")), key=str.casefold)

    def eigene_buecher(self):
        return {b for (b,) in self.db.execute("SELECT DISTINCT book FROM mentions UNION SELECT DISTINCT book FROM gaps")}

    def _luecken(self):
        status = {k: st for k, st in self.db.execute("SELECT key, status FROM checked WHERE kind='gap'")}
        luecken = defaultdict(list)
        for name, buch, n in self.db.execute("SELECT name, book, n FROM gaps ORDER BY n DESC"):
            luecken[name].append((buch, n))
        pruef = W.PROFIL.get("check_name") or "-"
        erg = []
        for name, buecher in luecken.items():
            st = status.get(name)
            if self.art == "leer":
                grund = _("frequent name in the books")
            else:
                grund = (_("not in the wiki, nothing found on {seite}") if st in ("not_found", "skip") else
                         _("not in the wiki, not yet searched on {seite}") if st is None else
                         _("not in the wiki, {seite} entry skipped")).format(seite=pruef)
            erg.append({"name": name, "grund": grund, "n": sum(n for __, n in buecher), "buecher": buecher})
        return erg

    def stand_aufbau(self):
        """Zahlen für die Schritte: Titel, Bücher, Artikel, Einträge, geprüft, Lücken."""
        q = lambda s: self.db.execute(s).fetchone()[0]   # noqa: E731
        return {"titel": q("SELECT COUNT(*) FROM titles"), "weiterleitungen": q("SELECT COUNT(*) FROM redirects"),
                "buecher": q("SELECT COUNT(DISTINCT book) FROM mentions"),
                "begriffe": q("SELECT COUNT(DISTINCT title) FROM mentions"),
                "artikel": q("SELECT COUNT(*) FROM articles"), "eintraege": q("SELECT COUNT(*) FROM entries"),
                "geprueft": q("SELECT COUNT(*) FROM checked WHERE kind='check'"),
                "geprueft_ok": q("SELECT COUNT(*) FROM checked WHERE kind='check' AND status='ok'"),
                "luecken": q("SELECT COUNT(DISTINCT name) FROM gaps"),
                "luecken_ok": q("SELECT COUNT(*) FROM checked WHERE kind='gap' AND status='ok'"),
                "batches": q("SELECT COUNT(*) FROM batches WHERE done=0"),
                "erzeugt": self.erzeugt_am()}

    # -- Schreiben -----------------------------------------------------------------
    def eigen_speichern(self, titel, data, quelle=QUELLE_EIGEN):
        self.db.execute("INSERT OR REPLACE INTO own VALUES(?,?,?,?)",
                        (titel, json.dumps(sauber(data), ensure_ascii=False), quelle, jetzt()))
        self.db.execute("DELETE FROM ignored WHERE name=?", (titel,))
        self.db.commit()
        self.laden()

    def original(self, titel):
        self.db.execute("DELETE FROM own WHERE title=?", (titel,))
        self.db.commit()
        self.laden()

    def loeschen(self, titel):
        self.db.execute("INSERT OR REPLACE INTO own VALUES(?,?,?,?)",
                        (titel, json.dumps({"deleted": True}), "", jetzt()))
        self.db.commit()
        self.laden()

    def ignorieren(self, name):
        self.db.execute("INSERT OR IGNORE INTO ignored VALUES(?)", (name,))
        self.db.commit()

    def nicht_ignorieren(self, name):
        self.db.execute("DELETE FROM ignored WHERE name=?", (name,))
        self.db.commit()

    def erzeugen(self, ordner, sicherung=None):
        W.profil_laden(self.db)
        n = W.build_to(self.db, ordner, W.PROFIL["name"], W.wiki_host(), AUSLASSEN)
        self.laden()
        return n

    def aus_stardict_uebernehmen(self, ordner):
        """Änderungen, die in Bookbench direkt an einem StarDict-Ordner gemacht wurden (z. B. an
        einer Kopie unterwegs), als eigene Einträge übernehmen. Gibt die Anzahl zurück."""
        j = _json_laden(_arbeitsdatei(ordner))
        n = 0
        for teil in ("geschrieben", "eigene"):
            for titel, (data, quelle, __) in j.get(teil, {}).items():
                if data.get("deleted"):
                    self.db.execute("INSERT OR REPLACE INTO own VALUES(?,?,?,?)",
                                    (titel, json.dumps({"deleted": True}), "", jetzt()))
                else:
                    self.db.execute("INSERT OR REPLACE INTO own VALUES(?,?,?,?)",
                                    (titel, json.dumps(sauber(data), ensure_ascii=False), quelle, jetzt()))
                n += 1
        self.db.commit()
        self.laden()
        return n


def anlegen(ordner, art, profil):
    """Neues Wörterbuch (Datenbank) im Ordner; art "wiki" oder "leer"."""
    ordner = Path(ordner)
    if any((ordner / n).exists() for n in W.DB_NAMEN):
        raise FileExistsError(_("There is already a dictionary in {ordner}.").format(ordner=ordner))
    db = W.open_db(ordner)
    W.meta_set(db, "art", art)
    W.profil_laden(db, {k: v for k, v in profil.items() if k in PROFIL_FELDER})
    db.close()
    return Woerterbuch(ordner)


# ================================================================ StarDict ohne Datenbank
_STRUKTUR = re.compile(r"^<div><i>([^<]*)</i></div><p>(.*?)</p>((?:<p><b>.*?\.</b> .*?</p>)*)"
                       r"(<p><small>.*</small></p>)?$", re.S)
_ABSCHNITT = re.compile(r"<p><b>(.*?)\.</b> (.*?)</p>", re.S)


def struktur_lesen(h):
    """Eintrag im Aufbau von wikidict (Kategorie, Kurzbeschreibung, Abschnitte, Fußzeile) zurück in
    Felder zerlegen; (data, Quelle) oder (None, None), wenn der Aufbau ein anderer ist."""
    m = _STRUKTUR.match(h.strip())
    if not m or html.unescape(m.group(1)) not in KATEGORIEN or "<" in m.group(2):
        return None, None
    roh = _ABSCHNITT.findall(m.group(3))
    if any("<" in a or "<" in b for a, b in roh):     # weiteres HTML darin: als HTML bearbeiten
        return None, None
    abschnitte = [{"h": html.unescape(a), "t": html.unescape(b)} for a, b in roh]
    fuss = m.group(4) or ""
    q = re.search(r"Source: (.*?)(?:<br/>|</small>)", fuss)
    data = {"category": html.unescape(m.group(1)), "tagline": html.unescape(m.group(2)), "sections": abschnitte,
            "aliases": []}
    if fuss:
        data["_fuss"] = fuss
    return data, html.unescape(q.group(1)) if q else ""


def _json_laden(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class StarDictWoerterbuch(Basis):
    art = "stardict"

    def __init__(self, pfad):
        super().__init__()
        ifo = ksd.finden(pfad)
        if not ifo:
            raise FileNotFoundError(f"{pfad}: keine .ifo-Datei")
        self.ifo_pfad = ifo
        self.pfad = ifo.parent
        self.json_pfad = _arbeitsdatei(self.pfad)
        self.laden()

    def schliessen(self):
        pass

    def _json_speichern(self):
        tmp = self.json_pfad.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.j, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.json_pfad)

    def profil(self):
        p = dict(self.j.get("profil", {}))
        p.setdefault("name", self.sd.ifo.get("bookname", self.pfad.name))
        p["stem"] = self.sd.stamm
        p.setdefault("topic", "")
        p.setdefault("spoilers", "mild")
        return p

    def profil_setzen(self, werte):
        p = self.j.setdefault("profil", {})
        p.update({k: v for k, v in werte.items() if k in ("topic", "name", "spoilers", "buecher")})
        self._json_speichern()

    def laden(self):
        self.j = _json_laden(self.json_pfad)        # kann ein anderer Thread (Erzeugen) geändert haben
        self.sd = ksd.lesen(self.ifo_pfad)
        self.basis, self.quellen, self._roh, self._typ = {}, {}, {}, {}
        namen = Counter(w for w, __ in self.sd.eintraege)
        nummer = Counter()
        schluessel = []
        for wort, teile in self.sd.eintraege:
            k = wort
            if namen[wort] > 1:                     # gleiches Stichwort mehrfach: unterscheidbar machen
                nummer[wort] += 1
                k = f"{wort} [{nummer[wort]}]"
            schluessel.append(k)
            h = ksd.als_html(teile)
            data, quelle = struktur_lesen(h) if not ksd.nur_text(teile) else (None, None)
            if data is None:
                data = {"text": "".join(b.decode("utf-8", "replace") for __, b in teile)} if ksd.nur_text(teile) \
                    else {"html": h}
                data["aliases"] = []
            if k != wort:
                data["_wort"] = wort
            self.basis[k] = data
            self.quellen[k] = quelle or ""
            self._roh[k] = teile
        for w, nr in self.sd.synonyme:
            if nr < len(schluessel):
                self.basis[schluessel[nr]]["aliases"].append(w)
        self.eigen = {t: tuple(v) for t, v in self.j.get("eigene", {}).items()}
        self.eintraege = dict(self.basis)
        for t, (data, quelle, __) in self.eigen.items():
            if data.get("deleted"):
                self.eintraege.pop(t, None)
            else:
                alt = self.basis.get(t, {})
                d = dict(data)
                for k in ("_fuss", "_wort"):
                    if k in alt and k not in d:
                        d[k] = alt[k]
                self.eintraege[t] = d
                self.quellen[t] = quelle
        self.synonyme = {(a, t) for t, d in self.eintraege.items() for a in d.get("aliases", [])}
        self._index_bauen()

    def erzeugt_am(self):
        return self.j.get("erzeugt", "")

    def ausgabe(self):
        return str(self.pfad)

    def stand(self, titel):
        return "gelb" if titel in self.eigen else None

    def ignorierte(self):
        return sorted(self.j.get("ignoriert", []), key=str.casefold)

    # -- Schreiben (Änderungen bis zum Erzeugen in werkstatt.json) --------------------
    def eigen_speichern(self, titel, data, quelle=QUELLE_EIGEN):
        self.j.setdefault("eigene", {})[titel] = [sauber(data), quelle, jetzt()]
        self.j["ignoriert"] = [n for n in self.j.get("ignoriert", []) if n != titel]
        self._json_speichern()
        self.laden()

    def original(self, titel):
        self.j.get("eigene", {}).pop(titel, None)
        self._json_speichern()
        self.laden()

    def loeschen(self, titel):
        self.j.setdefault("eigene", {})[titel] = [{"deleted": True}, "", jetzt()]
        self._json_speichern()
        self.laden()

    def ignorieren(self, name):
        ig = self.j.setdefault("ignoriert", [])
        if name not in ig:
            ig.append(name)
        self._json_speichern()

    def nicht_ignorieren(self, name):
        self.j["ignoriert"] = [n for n in self.j.get("ignoriert", []) if n != name]
        self._json_speichern()

    def _inhalt(self, k, data):
        """Bytes eines Eintrags; unveränderte Einträge Byte für Byte wie vorher."""
        if k in self.basis and k not in self.eigen:
            teile = self._roh[k]
            if len(teile) == 1 and teile[0][0] in "hm":
                return teile[0][0], teile[0][1]
            return "h", ksd.als_html(teile).encode("utf-8")
        if data.get("text") is not None:
            return "m", data["text"].encode("utf-8")
        return "h", self._render(k, data, self.quellen.get(k)).encode("utf-8")

    def _render(self, k, data, quelle):
        h = W.render(data.get("_wort", k), data, [], quelle or QUELLE_EIGEN)
        if data.get("_fuss") and data.get("html") is None:       # Fußzeile (Bücher, Quelle) wie vorher
            q = html.escape(quelle or QUELLE_EIGEN)
            fuss = re.sub(r"Source: .*?(<br/>|</small>)", lambda m: f"Source: {q}{m.group(1)}", data["_fuss"], 1)
            h = re.sub(r"<p><small>.*</small></p>$", lambda m: fuss, h, flags=re.S)
        return h

    def vorschau(self, titel, data=None, quelle=None):
        if data is None:
            data = self.eintraege.get(titel)
            if not data:
                return ""
            if titel in self.basis and titel not in self.eigen:
                return ksd.als_html(self._roh[titel])
            quelle = self.quellen.get(titel)
        if data.get("text") is not None:
            return html.escape(data["text"]).replace("\n", "<br/>")
        alt = self.basis.get(titel, {})
        d = dict(data, **{k: alt[k] for k in ("_fuss", "_wort") if k in alt and k not in data})
        return self._render(titel, d, quelle)

    def erzeugen(self, ordner=None, sicherung=None):
        """Schreibt die StarDict-Dateien neu (vorher Kopie nach sicherung/<Stamm>_JJJJMMTT_HHMMSS)."""
        if sicherung:
            ziel = Path(sicherung) / f"{self.sd.stamm}_{time.strftime('%Y%m%d_%H%M%S')}"
            ziel.mkdir(parents=True, exist_ok=True)
            for p in self.pfad.glob(self.sd.stamm + ".*"):
                shutil.copy2(p, ziel / p.name)
            alte = sorted(Path(sicherung).glob(f"{self.sd.stamm}_????????_??????"))
            for a in alte[:-5]:
                shutil.rmtree(a, ignore_errors=True)
        inhalte = {k: self._inhalt(k, d) for k, d in self.eintraege.items()}
        typ = "m" if inhalte and all(t == "m" for t, __ in inhalte.values()) else "h"
        eintr = []
        for k, (t, b) in inhalte.items():
            if typ == "h" and t == "m":
                b = html.escape(b.decode("utf-8")).replace("\n", "<br/>").encode("utf-8")
            eintr.append((self.eintraege[k].get("_wort", k), b))
        syn = [(a, self.eintraege[t].get("_wort", t)) for a, t in self.synonyme]
        ifo = dict(self.sd.ifo)
        ifo["bookname"] = self.profil().get("name") or ifo.get("bookname", self.pfad.name)
        n = ksd.schreiben(self.pfad, self.sd.stamm, ifo, eintr, syn, typ)
        geschrieben = self.j.setdefault("geschrieben", {})
        geschrieben.update(self.j.get("eigene", {}))
        self.j["eigene"] = {}
        self.j["erzeugt"] = jetzt()
        self._json_speichern()
        self.laden()
        return n


def kurzinfo(pfad):
    """(Name, Art) eines Wörterbuchs, ohne es ganz zu laden (für Auswahllisten); None, wenn es
    nicht (mehr) da ist."""
    import sqlite3
    p = Path(pfad).expanduser()
    datei = p if p.suffix == ".sqlite" else W.db_datei(p)
    try:
        if datei.is_file():
            db = sqlite3.connect(f"file:{datei}?mode=ro", uri=True)
            try:
                meta = dict(db.execute("SELECT k, v FROM meta WHERE k IN ('profil', 'art', 'profil_version')")
                            .fetchall())
                inhalt = W.hat_inhalt(db)
                art = meta.get("art") or ("wiki" if inhalt else "leer")
            finally:
                db.close()
            profil = json.loads(meta.get("profil") or "{}")
            if meta.get("profil_version") != W.PROFIL_VERSION:     # noch nicht umgestellt (nur lesend)
                profil = W.alt_profil_ergaenzen(profil, meta.get("art"), inhalt)
            name = profil.get("name") or W.STANDARD_PROFIL["name"]
            return name, art
        ifo = ksd.finden(p)
        if ifo:
            for z in ifo.read_text(encoding="utf-8", errors="replace").splitlines():
                if z.startswith("bookname="):
                    return z.split("=", 1)[1].strip(), "stardict"
            return p.name, "stardict"
    except (OSError, ValueError, sqlite3.Error):
        pass
    return None


def ist_woerterbuch(pfad):
    p = Path(pfad).expanduser()
    return (p.suffix == ".sqlite" and p.is_file()) or (p.is_dir() and W.db_datei(p).is_file()) \
        or ksd.finden(p) is not None


def finden(pfad):
    """Wörterbücher im Ordner und darunter: der Ordner selbst, wenn er eins ist, sonst alle
    StarDict-Ordner (auch unter .adds, z. B. in einer Kobo-Kopie) und Arbeitsordner mit
    wikidict.sqlite (oder wh40kdict.sqlite). Suche wie im Bereich E-Reader (begrenzte Tiefe und Ordnerzahl)."""
    from bookbench.device import device as kg
    p = Path(pfad).expanduser()
    if ist_woerterbuch(p):
        return [p]
    erg, stufe, gesehen = [], [p], 0
    for __ in range(kg.SUCHTIEFE + 1):
        naechste = []
        for ordner in stufe:
            gesehen += 1
            if gesehen > kg.SUCHGRENZE:
                break
            try:
                eintraege = list(os.scandir(ordner))
            except OSError:
                continue
            if any(e.name in W.DB_NAMEN for e in eintraege) or \
                    any(e.name.endswith(".ifo") and e.is_file() for e in eintraege):
                erg.append(Path(ordner))
                continue
            naechste += [Path(e.path) for e in eintraege if e.is_dir(follow_symlinks=False)
                         and e.name not in kg._NICHT_SUCHEN]
        stufe = sorted(naechste, key=lambda x: str(x).casefold())
        if not stufe or gesehen > kg.SUCHGRENZE:
            break
    return erg


def oeffnen(pfad):
    """Wörterbuch zu einem Pfad: Arbeitsordner/.sqlite -> Datenbank, Ordner/.ifo -> StarDict."""
    p = Path(pfad).expanduser()
    if p.suffix == ".sqlite" or (p.is_dir() and W.db_datei(p).is_file()):
        return Woerterbuch(p)
    if ksd.finden(p):
        return StarDictWoerterbuch(p)
    raise FileNotFoundError(f"{p}: " + _("neither wikidict.sqlite nor a StarDict dictionary (.ifo)"))


# ================================================================ Hilfen
_SATZZEICHEN = re.compile(r"^[\W_]+|[\W_]+$")


def _wort(text):
    """Nachgeschlagenes Wort säubern: Satzzeichen außen, englisches Genitiv-s."""
    w = _SATZZEICHEN.sub("", (text or "").strip())
    w = re.sub(r"['’]s$", "", w)
    return w if 1 < len(w) < 80 else ""


def _eigenname(w):
    """Nur Wörter, die nach Eigenname aussehen: groß geschrieben oder selten.
    Alltagswörter schlägt man im normalen Wörterbuch nach."""
    if w[:1].isupper():
        return True
    try:
        from wordfreq import zipf_frequency
    except ImportError:
        return False
    return zipf_frequency(w.lower(), "en") < 2.0


def nachschlageverlauf(text):
    """[(Wort, Buchtitel, Zeit)] aus KOReaders lookup_history.lua (angehängte Aufrufe
    LookupHistoryEntry{...}, jeder Eintrag eine Tabelle mit book_title, time, word)."""
    erg = []
    for tab in re.finditer(r"\{[^{}]*\[\"word\"\][^{}]*\}", text or ""):
        felder = {}
        for m in re.finditer(r'\["(\w+)"\]\s*=\s*(?:"((?:[^"\\]|\\.)*)"|(-?\d+))', tab.group(0), re.S):
            felder[m.group(1)] = _lua_text(m.group(2)) if m.group(2) is not None else int(m.group(3))
        if felder.get("word"):
            erg.append((felder["word"], felder.get("book_title", ""), felder.get("time", 0)))
    return erg


def _lua_text(s):
    """Lua-Zeichenkette (%q-Schreibweise) zurückverwandeln; Bytes > 127 stehen roh drin."""
    roh = bytearray()
    b = s.encode("utf-8")
    i = 0
    while i < len(b):
        c = b[i]
        if c == 0x5C and i + 1 < len(b):
            n = b[i + 1]
            if 0x30 <= n <= 0x39:
                j = i + 1
                while j < len(b) and j < i + 4 and 0x30 <= b[j] <= 0x39:
                    j += 1
                roh.append(int(b[i + 1:j]) & 0xFF)
                i = j
                continue
            roh += {ord("n"): b"\n", 0x0A: b"\n", ord("t"): b"\t", ord("r"): b"\r"}.get(n, bytes([n]))
            i += 2
            continue
        roh.append(c)
        i += 1
    return roh.decode("utf-8", "replace")


class _Teile(HTMLParser):
    STIL = {"i": "kursiv", "em": "kursiv", "b": "fett", "strong": "fett", "small": "klein"}

    def __init__(self):
        super().__init__()
        self.teile, self.stile = [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.STIL:
            self.stile.append(self.STIL[tag])
        elif tag == "br":
            self.teile.append(("\n", tuple(self.stile)))

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.teile.append(("\n", tuple(self.stile)))

    def handle_endtag(self, tag):
        if tag in self.STIL and self.STIL[tag] in self.stile:
            self.stile.remove(self.STIL[tag])
        elif tag in ("p", "div", "li"):
            self.teile.append(("\n\n" if tag == "p" else "\n", ()))

    def handle_data(self, data):
        self.teile.append((data, tuple(self.stile)))


def html_teile(html_text):
    p = _Teile()
    p.feed(html_text)
    p.close()
    return p.teile


# ================================================================ KI
def _arten(thema):
    t = thema or "the books the reader is reading"
    return {
        "suche": ("Claude (web search)", f"""

TASK VARIANT - WEB SEARCH:
Ignore the instruction about one wiki article. You get a name from {t}; no wiki article was found for it.
Use web_search (up to 3 searches; wikis, publisher pages, Reddit and forums are all fine) and web_fetch to
read the most relevant pages. Write the entry ONLY from what these pages say. Add "title": the usual full
name of the subject, and "sources": [the URLs you used]. If nothing clearly about this subject turns up,
return {{"skip": true}}.
Return only the JSON object."""),
        "link": ("Claude (from given page)", """

TASK VARIANT - GIVEN PAGE:
Ignore the instruction about one wiki article. You get a name and the URL of a page about it (any
website). Fetch the URL with web_fetch and write the entry from that page only. Add "title": the usual
full name of the subject, and "sources": [the URL]. If the page is not about this subject or cannot be
fetched, return {"skip": true}.
Return only the JSON object."""),
        "wissen": ("Claude (own knowledge, unverified)", f"""

TASK VARIANT - OWN KNOWLEDGE:
Ignore the instruction about one wiki article; no source is available. Write the entry from your own
knowledge of {t}. Only state what you are confident about and leave out anything you are unsure of;
a short entry is better than a wrong one. Add "title": the usual full name.
If you do not recognise the name as part of {t}, return {{"skip": true}}.
Return only the JSON object."""),
    }


ARTEN = ("suche", "link", "wissen")


def ki_eintrag(client, modell, name, art, url=None, buecher=(), spoiler="mild", worte=150, thema=None):
    """Fragt Claude nach einem Eintrag. Gibt (data, Quelle, Meldung) zurück; data ist None,
    wenn nichts Brauchbares kam. data["title"] ist der vorgeschlagene Name; der nachgeschlagene
    steht dann in den Aliasen."""
    if art not in ARTEN:
        raise ValueError(art)
    if art == "link" and not (url and urlparse(url).scheme in ("http", "https") and urlparse(url).netloc):
        return None, "", _("not a valid address (http:// or https://)")
    alt = W.PROFIL
    W.PROFIL = dict(alt, topic=thema or alt.get("topic") or "the books the reader is reading")
    try:
        quelle, zusatz = _arten(W.PROFIL["topic"])[art]
        system = W.system_prompt(spoiler, worte) + zusatz
    finally:
        W.PROFIL = alt
    user = f"Name: {name}"
    if buecher:
        user += "\nAppears in these books: " + ", ".join(b for b, __ in list(buecher)[:6])
    tools = []
    if art == "suche":
        tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3},
                 {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 4, "max_content_tokens": 12000}]
    elif art == "link":
        user += f"\nURL: {url}"
        tools = [{"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 2, "max_content_tokens": 15000,
                  "allowed_domains": [urlparse(url).netloc]}]
    p = {"model": modell, "max_tokens": 8000, "system": system, "messages": [{"role": "user", "content": user}]}
    if tools:
        p["tools"] = tools
    msg = client.messages.create(**p)
    for __ in range(3):                                   # pause_turn: Claude will weitermachen
        if getattr(msg, "stop_reason", None) != "pause_turn":
            break
        p["messages"] = p["messages"][:1] + [{"role": "assistant", "content": msg.content}]
        msg = client.messages.create(**p)
    data = W.parse_reply(msg)
    fehler = W.fetch_errors(msg)
    zusatz = f" ({', '.join(map(str, fehler))})" if fehler else ""
    if data is None:
        return None, "", _("no usable answer") + zusatz
    if data.get("skip"):
        return None, "", (_("nothing suitable found") if art != "wissen" else _("Claude does not know the term")) + zusatz
    titel = (data.get("title") or name).strip() or name
    data["title"] = titel
    if titel.casefold() != name.casefold() and name not in data["aliases"]:
        data["aliases"].append(name)
    quellen = [q for q in data.get("sources", []) if isinstance(q, str)][:3] if art != "wissen" else []
    if art == "link" and not quellen:
        quellen = [url]
    return data, quelle + (": " + ", ".join(quellen) if quellen else ""), ""


# ================================================================ Schritte von wikidict
class Abgebrochen(BaseException):               # BaseException: kein "except Exception" im Skript faengt es
    pass


SCHRITTE = {                                       # Befehl -> (Name, braucht API, sperrt Arbeitsordner)
    "titles": (N_("Load titles"), False, False),
    "scan": (N_("Search books"), False, False),
    "fetch": (N_("Load articles"), False, False),
    "summarize": (N_("Summarize"), True, True),
    "crosscheck": (N_("Cross-check"), True, True),
}


def schritt(arbeitsordner, befehl, argumente, schreiben, fragen, abbrechen):
    """Führt `wikidict.py <befehl> <argumente>` im aufrufenden Thread aus. schreiben(text, ersetzen)
    bekommt die Ausgabe zeilenweise (ersetzen=True: Fortschrittszeile mit \\r, ersetzt die letzte), fragen(text) beantwortet Rückfragen (True = ja), abbrechen() -> True
    bricht beim nächsten Ausgabeschritt ab. Gibt eine Schlussmeldung zurück."""
    args = W.parser().parse_args(["--workdir", str(arbeitsordner), befehl] + list(argumente))
    puffer = []

    def drucken(*a, sep=" ", end="\n", **_):
        if abbrechen():
            raise Abgebrochen()
        text = sep.join(str(x) for x in a) + end
        puffer.append(text)
        ersetzen = text.startswith("\r")
        for z in text.strip("\r").rstrip("\n").split("\n"):
            schreiben(z, ersetzen)
            ersetzen = False

    def eingabe(prompt=""):
        if abbrechen():
            raise Abgebrochen()
        letzte = "".join(puffer[-6:]).strip()
        return "j" if fragen(f"{letzte}\n\n{prompt.strip()}") else "n"
    db = W.open_db(Path(arbeitsordner))
    W.print, W.input = drucken, eingabe
    try:
        W.profil_laden(db)
        if SCHRITTE.get(befehl, ("", False, False))[2]:
            W.lock_or_exit(Path(arbeitsordner))
        wiki = W.wiki_oeffnen(db, args) if befehl in ("titles", "fetch", "check") else None
        getattr(W, f"cmd_{befehl}")(db, wiki, args)
        return f"{_(SCHRITTE.get(befehl, (befehl,))[0])}: " + _("done.")
    except Abgebrochen:
        return f"{_(SCHRITTE.get(befehl, (befehl,))[0])}: " + _("cancelled. What was done so far is saved, "
                                                             "the next run continues from there.")
    except SystemExit as e:
        return f"{SCHRITTE.get(befehl, (befehl,))[0]}: {e.code}" if e.code not in (None, 0) else \
            f"{SCHRITTE.get(befehl, (befehl,))[0]}: " + _("done.")
    finally:
        for name in ("print", "input"):
            W.__dict__.pop(name, None)
        lock = W.__dict__.get("_LOCK")
        if lock is not None:
            lock.close()
            W._LOCK = None
        db.close()
