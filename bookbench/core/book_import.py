# -*- coding: utf-8 -*-
"""
book_import.py - Bücher in die Bibliothek holen (seit 2.1), ohne Oberfläche.

Ablauf: dateien_sammeln() → planen() (je Datei ein Eintrag mit Zielpfad nach dem Ordnerschema und einem
gefundenen Duplikat) → der Nutzer prüft in ui/import_window.py Metadaten und Aktion → ausfuehren().

Duplikate werden in dieser Reihenfolge gesucht: Calibre-UUID, ISBN, Titel+Autor (ohne Groß/Klein,
Satzzeichen und führendes "The/Der/Die/Das"). Aktionen je Eintrag:
  neu            in den Ordner nach Schema kopieren
  ueberspringen  nichts tun
  ersetzen       die vorhandene Datei überschreiben, AN IHREM PFAD (KOReaders .sdr hängt am Dateinamen;
                 so bleiben Lesestand und Markierungen erhalten), vorher Sicherung
  beide          als weiteres Buch neben das vorhandene (" (2)" am Namen, falls der Pfad belegt ist)

Die Bibliothek bekommt einen Ordner .bookbench/ mit library.json (Ordnerschema, zugehöriger E-Reader).
Der liegt bewusst IM Bibliotheksordner: zieht der Ordner um oder liegt er in einem Sync-Ordner (Windows
und Linux), kommt beides mit. Reine Daten (JSON), nichts Ausführbares.

  bibliothek_lesen(wurzel) / bibliothek_schreiben(wurzel, daten)
  dateien_sammeln(quellen)            .epub/.kepub aus Dateien und Ordnern
  lesen(pfad)                         Buch nur mit Metadaten (schnell, ohne Inhaltsverzeichnis)
  duplikat(buch, vorhandene)          (Buch, Grund) oder (None, "")
  planen(dateien, vorhandene, wurzel, vorlage)   [Eintrag]
  ausfuehren(eintraege, wurzel, sicherungsordner, anzahl, fortschritt)   (fertig [rel], fehler [(name, text)])
  vom_reader(reader, ziel, fortschritt)          Erstbefüllung: alle Bücher mit gleicher Struktur kopieren
"""
import json
import os
import re
import shutil
import time
import zipfile
from pathlib import Path

from bookbench.core import blurbs
from bookbench.core import folder_scheme as fs
from bookbench.core import library as kd
from bookbench.core import metadata
from bookbench.core import toc_fix as tocfix
from bookbench.core import toc_report as tocreport

ORDNER = ".bookbench"
DATEI = "library.json"
ENDUNGEN = (".epub", ".kepub")
AKTIONEN = ("neu", "ueberspringen", "ersetzen", "beide")


# ------------------------------------------------------------------------------- Bibliotheksordner
def bibliothek_lesen(wurzel):
    """Inhalt von .bookbench/library.json ({} ohne)."""
    try:
        d = json.loads((Path(wurzel) / ORDNER / DATEI).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def bibliothek_schreiben(wurzel, daten):
    p = Path(wurzel) / ORDNER
    p.mkdir(parents=True, exist_ok=True)
    tmp = p / (DATEI + ".tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p / DATEI)


def ist_bibliothek(wurzel):
    return (Path(wurzel) / ORDNER / DATEI).is_file()


def schema(wurzel, standard=fs.STANDARD):
    return bibliothek_lesen(wurzel).get("ordnerschema") or standard


# ------------------------------------------------------------------------------- Einlesen
def _ist_buch(p):
    n = p.name.lower()
    return n.endswith(ENDUNGEN) and not n.startswith("._")         # ._x.epub: macOS-Schattendatei


def dateien_sammeln(quellen):
    """Alle Bücher aus Dateien und (rekursiv) Ordnern, ohne Doppelte, ohne versteckte Ordner und .sdr."""
    erg, gesehen = [], set()
    for q in quellen:
        q = Path(q)
        if q.is_dir():
            kand = []
            for ordner, unter, dateien in os.walk(q):
                unter[:] = sorted(u for u in unter if not u.startswith(".") and not u.endswith(".sdr"))
                kand += [Path(ordner, d) for d in sorted(dateien)]
        else:
            kand = [q]
        for p in kand:
            if p.is_file() and _ist_buch(p):
                r = p.resolve()
                if r not in gesehen:
                    gesehen.add(r)
                    erg.append(p)
    return erg


def lesen(pfad):
    """Buch nur mit den Metadaten (für Prüfliste und Duplikate); Fehler in buch.fehler."""
    b = kd.Buch(pfad)
    try:
        with zipfile.ZipFile(pfad) as z:
            b.opf_pfad, opf = blurbs.read_opf(z)
            b.titel, b.autor, __, __ = blurbs.book_info(opf)
            b.verlag, b.isbn, b.sprache = blurbs.book_extra(opf)
            b.titel = b.titel or b.pfad.stem
            b.reihe, b.nummer = tocreport.reihe_aus_opf(opf)
            if b.nummer.endswith(".0"):
                b.nummer = b.nummer[:-2]
            b.reihe_datei = (b.reihe, b.nummer)
            b.meta = metadata.lesen(opf)
            b.meta_defs = metadata.definitionen(opf)
            b.uuid = kd.opf_uuid(opf)
    except Exception as e:
        b.fehler = str(e) or e.__class__.__name__
    return b


def _norm(s):
    s = (s or "").casefold()
    s = re.sub(r"^(the|a|an|der|die|das|ein|eine)\s+", "", s.strip())
    return re.sub(r"[\W_]+", "", s)


def _autor(b):
    a = (b.meta or {}).get("autoren") or b.autor or ""
    return _norm(a.split("&")[0])


def duplikat(b, vorhandene):
    """(vorhandenes Buch, Grund "uuid"/"isbn"/"titel") oder (None, "")."""
    if b.uuid:
        for v in vorhandene:
            if v.uuid and v.uuid == b.uuid:
                return v, "uuid"
    if b.isbn:
        for v in vorhandene:
            if v.isbn and v.isbn == b.isbn:
                return v, "isbn"
    t, a = _norm(b.titel), _autor(b)
    if t:
        for v in vorhandene:
            if _norm(v.titel) == t and _autor(v) == a:
                return v, "titel"
    return None, ""


class Eintrag:
    """Ein Buch auf dem Weg in die Bibliothek."""

    def __init__(self, quelle, buch):
        self.quelle = Path(quelle)
        self.buch = buch
        self.aenderung = {}          # {feld: text} in der Prüfliste geändert (Felder wie Buch.meta)
        self.ziel = ""               # relativer Pfad nach Schema (für neu/beide)
        self.duplikat = None         # vorhandenes Buch (oder Eintrag derselben Liste: .quelle)
        self.grund = ""              # uuid / isbn / titel / liste
        self.aktion = "neu"
        self.ergebnis = ""           # relativer Pfad nach dem Ausführen

    def werte(self):
        """Metadaten mit den Änderungen aus der Prüfliste (für Schema und Anzeige)."""
        m = dict(self.buch.meta or {})
        m.setdefault("titel", self.buch.titel)
        m.setdefault("autoren", self.buch.autor)
        m.setdefault("reihe", self.buch.reihe)
        m.setdefault("nummer", self.buch.nummer)
        m.update(self.aenderung)
        return m

    def schema_buch(self):
        """Stellvertreter fürs Ordnerschema (folder_scheme.werte liest meta und pfad)."""
        b = kd.Buch(self.quelle)
        b.meta = self.werte()
        return b


def ziel_berechnen(e, vorlage):
    e.ziel = fs.ziel(vorlage, e.schema_buch(), fs.endung(e.quelle))
    return e.ziel


def planen(dateien, vorhandene, wurzel, vorlage):
    """Je Datei ein Eintrag; Duplikate gegen die Bibliothek und innerhalb der Liste (zweites Vorkommen
    = überspringen). Unlesbare Dateien: aktion "ueberspringen", buch.fehler gesetzt."""
    eintraege = []
    wurzel = Path(wurzel).resolve()
    for d in dateien:
        b = lesen(d)
        e = Eintrag(d, b)
        if b.fehler:
            e.aktion = "ueberspringen"
            eintraege.append(e)
            continue
        try:                                          # liegt schon in der Bibliothek: nichts zu tun
            Path(d).resolve().relative_to(wurzel)
            e.duplikat = next((v for v in vorhandene if Path(v.pfad).resolve() == Path(d).resolve()), None)
            e.grund, e.aktion = "selbst", "ueberspringen"
        except ValueError:
            v, grund = duplikat(b, vorhandene)
            if v is None:
                w, grund = duplikat(b, [x.buch for x in eintraege if not x.buch.fehler])
                if w is not None:
                    v, grund = w, "liste"
            if v is not None:
                e.duplikat, e.grund, e.aktion = v, grund, "ueberspringen"
        ziel_berechnen(e, vorlage)
        eintraege.append(e)
    return eintraege


# ------------------------------------------------------------------------------- Ausführen
def _schreiben(quelle, ziel, e):
    """Quelle nach ziel kopieren; mit Änderungen aus der Prüfliste wird das OPF dabei neu geschrieben."""
    ziel.parent.mkdir(parents=True, exist_ok=True)
    tmp = ziel.with_name(ziel.name + ".tmp")
    alt = e.buch.meta or {}
    reihe_alt = (alt.get("reihe", e.buch.reihe), alt.get("nummer", e.buch.nummer))
    neu = {k: v for k, v in e.aenderung.items() if k not in ("reihe", "nummer") and v != alt.get(k, "")}
    reihe = (e.aenderung.get("reihe", reihe_alt[0]), e.aenderung.get("nummer", reihe_alt[1]))
    if neu or reihe != reihe_alt:
        with zipfile.ZipFile(quelle) as z:
            opf_pfad, opf = blurbs.read_opf(z)
        neu_opf = metadata.schreiben(opf, alt, neu, {}) if neu else opf
        if neu_opf is not None and reihe != reihe_alt:
            neu_opf = kd.opf_mit_reihe(neu_opf, *reihe)
        if neu_opf is None:
            raise ValueError("the metadata file has an unusual format")
        tocfix.write_copy(Path(quelle), tmp, {opf_pfad: neu_opf})
    else:
        shutil.copy2(quelle, tmp)
    os.replace(tmp, ziel)


def ausfuehren(eintraege, wurzel, sicherungsordner, anzahl=5, fortschritt=None):
    """Führt die Aktionen aus. Rückgabe (fertig: [relativer Pfad], fehler: [(Dateiname, Text)])."""
    wurzel = Path(wurzel)
    fertig, fehler, belegt = [], [], set()
    zu_tun = [e for e in eintraege if e.aktion in ("neu", "beide", "ersetzen") and not e.buch.fehler]
    for i, e in enumerate(zu_tun, 1):
        if fortschritt:
            fortschritt(i, len(zu_tun), e)
        try:
            if e.aktion == "ersetzen":
                if e.duplikat is None or e.grund in ("liste", "selbst"):
                    raise ValueError("nothing to replace")
                ziel = Path(e.duplikat.pfad)
                if ziel.exists():
                    kd.sicherung_anlegen(ziel, sicherungsordner, anzahl)
            else:
                rel = fs.frei(wurzel, e.ziel or fs.ziel(fs.STANDARD, e.schema_buch()), belegt)
                belegt.add(rel)
                ziel = wurzel / rel
            _schreiben(e.quelle, ziel, e)
            try:
                e.ergebnis = ziel.relative_to(wurzel).as_posix()
            except ValueError:
                e.ergebnis = str(ziel)
            fertig.append(e.ergebnis)
        except Exception as ex:
            fehler.append((e.quelle.name, str(ex) or ex.__class__.__name__))
    return fertig, fehler


# ------------------------------------------------------------------------------- Erstbefüllung
_AUSLASSEN = {".kobo", ".adds", ".kobo-images", "koreader", "system", "applications", ".Trashes", ".Spotlight-V100",
              "$RECYCLE.BIN", "System Volume Information", ".bookbench"}


def reader_buecher(reader):
    """Bücher auf dem E-Reader (relativ, "/"), ohne Systemordner, KOReader-Ordner und .sdr."""
    reader = Path(reader)
    erg = []
    for ordner, unter, dateien in os.walk(reader):
        if Path(ordner) == reader:
            unter[:] = [u for u in unter if u not in _AUSLASSEN]
        unter[:] = sorted(u for u in unter if not u.startswith(".") and not u.endswith(".sdr"))
        for d in sorted(dateien):
            p = Path(ordner, d)
            if _ist_buch(p) and not d.endswith((".orig", ".tmp")):
                erg.append(p.relative_to(reader).as_posix())
    return erg


def vom_reader(reader, ziel, fortschritt=None, abbrechen=None):
    """Kopiert alle Bücher vom Reader mit gleicher Ordnerstruktur nach ziel (die .sdr bleiben auf dem
    Reader). Vorhandene gleiche Dateien (Größe+Zeit) werden übersprungen, so geht ein abgebrochener Lauf
    einfach weiter. Rückgabe (kopiert, übersprungen, fehler [(rel, text)])."""
    reader, ziel = Path(reader), Path(ziel)
    liste = reader_buecher(reader)
    kopiert = uebersprungen = 0
    fehler = []
    for i, rel in enumerate(liste, 1):
        if abbrechen and abbrechen():
            break
        if fortschritt:
            fortschritt(i, len(liste), rel)
        q, z = reader / rel, ziel / rel
        try:
            sq = q.stat()
            if z.exists():
                sz = z.stat()
                if sz.st_size == sq.st_size and abs(sz.st_mtime - sq.st_mtime) < 2:   # FAT: 2 s Raster
                    uebersprungen += 1
                    continue
            z.parent.mkdir(parents=True, exist_ok=True)
            tmp = z.with_name(z.name + ".tmp")
            shutil.copy2(q, tmp)
            os.replace(tmp, z)
            kopiert += 1
        except OSError as ex:
            fehler.append((rel, str(ex)))
    return kopiert, uebersprungen, fehler


def reader_eintrag(info):
    """Was library.json über den zugehörigen Reader festhält (aus device.geraet_info)."""
    return {"art": info.get("art", ""), "modell": info.get("modell", ""), "seriennummer": info.get("seriennummer", ""),
            "verknuepft": time.strftime("%Y-%m-%d")}
