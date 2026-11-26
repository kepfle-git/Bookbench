# -*- coding: utf-8 -*-
"""
sync.py - Abgleich Bibliothek auf dem Rechner ↔ E-Reader (seit 2.1), ohne Oberfläche.

Ein Vergleich zweier Dateien sagt nur, DASS sie sich unterscheiden, nicht WO geändert wurde. Deshalb merkt
sich Bookbench nach jedem Abgleich je Buch einen Basis-Stand (.bookbench/abgleich.json im Bibliotheksordner):
Größe und Änderungszeit auf beiden Seiten und eine SHA-1 des Inhalts. Beim nächsten Mal wird jede Seite mit
der Basis verglichen:

    Rechner geändert, Reader gleich  → zum Reader      Reader geändert, Rechner gleich → zum Rechner
    beide geändert                   → Konflikt         nur auf einer Seite neu         → hinüber kopieren
    in der Basis, auf einer Seite weg → dort gelöscht: auf der anderen Seite löschen anbieten (nicht angehakt)

Geändert heißt: Größe oder Zeit weichen von der Basis ab UND die Prüfsumme auch. Die Zeit allein reicht nicht:
der Reader hat FAT (2-Sekunden-Raster, Ortszeit - nach der Sommerzeit-Umstellung sehen unter Linux alle Dateien
eine Stunde anders aus). Die Prüfsumme wird nur gerechnet, wenn Größe/Zeit abweichen, damit nicht jedes Mal der
ganze Reader über USB gelesen wird.

Kopiert wird immer an denselben relativen Pfad (Ordnerstruktur gleich auf beiden Seiten); KOReaders .sdr-
Ordner werden nie angefasst. Vor dem Überschreiben oder Löschen kommt die alte Datei in den Sicherungsordner.

  vergleichen(bib, reader, fortschritt)   [Eintrag] (nur was zu tun ist bzw. Konflikte)
  ausfuehren(bib, reader, eintraege, sicherungsordner, anzahl, fortschritt)   (erledigt [rel], fehler [(rel, text)])
  basis_setzen(bib, reader, rels)          Basis für gleiche Dateien anlegen (nach der Erstbefüllung)
  unterschiede(pfad_a, pfad_b)             [Zeile] für Konflikte: Metadaten, Kapitel, Dateien im EPUB
  verknuepft(e, info)                      Bibliotheksordner zu einem Reader (Einstellung bibliotheken)
"""
import hashlib
import json
import os
import shutil
import time
import zipfile
from pathlib import Path

from bookbench.core import book_import as bi
from bookbench.core import library as kd

DATEI = "abgleich.json"
TOLERANZ = 2.0                      # Sekunden (FAT)

# Zustände und vorgeschlagene Aktion (angehakt?)
ZUSTAENDE = {
    "neu_rechner": ("zum_reader", True),
    "neu_reader": ("zum_rechner", True),
    "rechner_geaendert": ("zum_reader", True),
    "reader_geaendert": ("zum_rechner", True),
    "konflikt": ("nichts", False),
    "reader_geloescht": ("loeschen_rechner", False),     # auf dem Reader gelöscht → auf dem Rechner löschen?
    "rechner_geloescht": ("loeschen_reader", False),     # auf dem Rechner gelöscht → auf dem Reader löschen?
}
AKTIONEN = {
    "neu_rechner": ("zum_reader", "nichts"),
    "neu_reader": ("zum_rechner", "nichts"),
    "rechner_geaendert": ("zum_reader", "zum_rechner", "nichts"),
    "reader_geaendert": ("zum_rechner", "zum_reader", "nichts"),
    "konflikt": ("nichts", "zum_reader", "zum_rechner"),
    "reader_geloescht": ("loeschen_rechner", "zum_reader", "nichts"),
    "rechner_geloescht": ("loeschen_reader", "zum_rechner", "nichts"),
}


class Eintrag:
    def __init__(self, rel, zustand, rechner=None, reader=None):
        self.rel = rel
        self.zustand = zustand
        self.aktion, self.an = ZUSTAENDE[zustand]
        self.rechner = rechner          # (Größe, Zeit) oder None
        self.reader = reader


def _stat(p):
    try:
        st = os.stat(p)
        return st.st_size, st.st_mtime
    except OSError:
        return None


def _sha1(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for stueck in iter(lambda: f.read(1 << 20), b""):
            h.update(stueck)
    return h.hexdigest()


def basis_lesen(bib):
    try:
        d = json.loads((Path(bib) / bi.ORDNER / DATEI).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def basis_schreiben(bib, d):
    p = Path(bib) / bi.ORDNER
    p.mkdir(parents=True, exist_ok=True)
    tmp = p / (DATEI + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p / DATEI)


def _passt(st, b, seite):
    """Größe und Zeit wie in der Basis (Zeit mit FAT-Toleranz)?"""
    return st[0] == b.get("groesse") and abs(st[1] - (b.get(seite) or 0)) < TOLERANZ


def _bibliothek_buecher(bib):
    bib = Path(bib)
    return [p.relative_to(bib).as_posix() for p in bi.dateien_sammeln([bib])]


def vergleichen(bib, reader, fortschritt=None):
    """Was ist zu tun? Gleiche Dateien ohne Basis (oder mit verschobener Zeit) bekommen dabei still eine Basis."""
    bib, reader = Path(bib), Path(reader)
    d = basis_lesen(bib)
    basis = d.setdefault("dateien", {})
    rechner = set(_bibliothek_buecher(bib))
    geraet = set(bi.reader_buecher(reader))
    alle = sorted(rechner | geraet | set(basis), key=str.casefold)
    erg, geaendert = [], False
    summen = {}

    def sha1(q):                                           # je Lauf höchstens einmal je Datei rechnen
        if q not in summen:
            summen[q] = _sha1(q)
        return summen[q]
    for i, rel in enumerate(alle, 1):
        if fortschritt and (i % 20 == 1 or i == len(alle)):
            fortschritt(i, len(alle), rel)
        p = _stat(bib / rel) if rel in rechner else None
        r = _stat(reader / rel) if rel in geraet else None
        b = basis.get(rel)
        if p is None and r is None:
            if b is not None:                              # auf beiden Seiten weg: Basis vergessen
                del basis[rel]
                geaendert = True
            continue
        if p is not None and r is not None:
            if b is None:
                if p[0] == r[0] and sha1(bib / rel) == sha1(reader / rel):
                    basis[rel] = {"groesse": p[0], "rechner": p[1], "reader": r[1], "sha1": sha1(bib / rel)}
                    geaendert = True
                else:
                    erg.append(Eintrag(rel, "konflikt", p, r))
                continue
            cp = not _passt(p, b, "rechner") and sha1(bib / rel) != b.get("sha1")
            cr = not _passt(r, b, "reader") and sha1(reader / rel) != b.get("sha1")
            if not cp and not cr:
                if not _passt(p, b, "rechner") or not _passt(r, b, "reader"):   # nur Zeit verschoben: Basis nachziehen
                    b.update(rechner=p[1], reader=r[1])
                    geaendert = True
                continue
            if cp and cr:
                if p[0] == r[0] and sha1(bib / rel) == sha1(reader / rel):      # beide gleich geändert
                    basis[rel] = {"groesse": p[0], "rechner": p[1], "reader": r[1], "sha1": sha1(bib / rel)}
                    geaendert = True
                else:
                    erg.append(Eintrag(rel, "konflikt", p, r))
            else:
                erg.append(Eintrag(rel, "rechner_geaendert" if cp else "reader_geaendert", p, r))
            continue
        if p is not None:
            erg.append(Eintrag(rel, "reader_geloescht" if b is not None else "neu_rechner", p, None))
        else:
            erg.append(Eintrag(rel, "rechner_geloescht" if b is not None else "neu_reader", None, r))
    if geaendert:
        try:
            basis_schreiben(bib, d)
        except OSError:
            pass
    return erg


def _kopieren(q, z):
    z.parent.mkdir(parents=True, exist_ok=True)
    tmp = z.with_name(z.name + ".tmp")
    shutil.copy2(q, tmp)
    os.replace(tmp, z)


def _sichern_und(p, sicherungsordner, anzahl):
    if p.exists():
        kd.sicherung_anlegen(p, sicherungsordner, anzahl)


def ausfuehren(bib, reader, eintraege, sicherungsordner, anzahl=5, fortschritt=None):
    """Angehakte Aktionen ausführen, Basis je Datei nachziehen. Rückgabe (erledigt [rel], fehler [(rel, text)])."""
    bib, reader = Path(bib), Path(reader)
    d = basis_lesen(bib)
    basis = d.setdefault("dateien", {})
    zu_tun = [e for e in eintraege if e.an and e.aktion != "nichts"]
    erledigt, fehler = [], []
    for i, e in enumerate(zu_tun, 1):
        if fortschritt:
            fortschritt(i, len(zu_tun), e)
        p, r = bib / e.rel, reader / e.rel
        try:
            if e.aktion == "zum_reader":
                _sichern_und(r, sicherungsordner, anzahl)
                _kopieren(p, r)
            elif e.aktion == "zum_rechner":
                _sichern_und(p, sicherungsordner, anzahl)
                _kopieren(r, p)
            elif e.aktion == "loeschen_reader":
                _sichern_und(r, sicherungsordner, anzahl)
                r.unlink(missing_ok=True)
            elif e.aktion == "loeschen_rechner":
                _sichern_und(p, sicherungsordner, anzahl)
                p.unlink(missing_ok=True)
            sp, sr = _stat(p), _stat(r)
            if sp and sr:
                basis[e.rel] = {"groesse": sp[0], "rechner": sp[1], "reader": sr[1], "sha1": _sha1(p)}
            else:
                basis.pop(e.rel, None)
            erledigt.append(e.rel)
        except Exception as ex:
            fehler.append((e.rel, str(ex) or ex.__class__.__name__))
    d["zuletzt"] = time.strftime("%Y-%m-%d %H:%M")
    basis_schreiben(bib, d)
    return erledigt, fehler


def basis_setzen(bib, reader, rels):
    """Basis für Dateien, die auf beiden Seiten gleich sind (z. B. direkt nach der Erstbefüllung)."""
    bib, reader = Path(bib), Path(reader)
    d = basis_lesen(bib)
    basis = d.setdefault("dateien", {})
    for rel in rels:
        sp, sr = _stat(bib / rel), _stat(reader / rel)
        if sp and sr and sp[0] == sr[0]:
            basis[rel] = {"groesse": sp[0], "rechner": sp[1], "reader": sr[1], "sha1": _sha1(bib / rel)}
    basis_schreiben(bib, d)


# ------------------------------------------------------------------------------- Unterschiede (Konflikt)
def unterschiede(a, b):
    """Was unterscheidet zwei Fassungen eines Buchs? [(Art, Text)]; Art: "meta", "kapitel", "datei", "info".
    a = Rechner, b = Reader. Texte englisch-neutral (Feldnamen wie in Buch.meta), die Oberfläche beschriftet."""
    erg = []
    ba, bb = kd.buch_laden(a), kd.buch_laden(b)
    if ba.fehler or bb.fehler:
        return [("info", ba.fehler or bb.fehler)]
    ma, mb = dict(ba.meta or {}), dict(bb.meta or {})
    for k in sorted(set(ma) | set(mb)):
        if (ma.get(k) or "") != (mb.get(k) or ""):
            erg.append(("meta", (k, ma.get(k) or "", mb.get(k) or "")))
    ka = [t for __, t, __, __ in ba.zeilen]
    kb = [t for __, t, __, __ in bb.zeilen]
    if ka != kb:
        if len(ka) != len(kb):
            erg.append(("kapitel", ("anzahl", str(len(ka)), str(len(kb)))))
        for i, (x, y) in enumerate(zip(ka, kb)):
            if x != y:
                erg.append(("kapitel", (str(i + 1), x, y)))
    if (ba.klappentext or "").strip() != (bb.klappentext or "").strip():
        erg.append(("meta", ("klappentext", (ba.klappentext or "")[:80], (bb.klappentext or "")[:80])))
    with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
        ia = {i.filename: i.CRC for i in za.infolist()}
        ib = {i.filename: i.CRC for i in zb.infolist()}
    for n in sorted(set(ia) | set(ib)):
        if n not in ib:
            erg.append(("datei", (n, "nur_rechner")))
        elif n not in ia:
            erg.append(("datei", (n, "nur_reader")))
        elif ia[n] != ib[n]:
            erg.append(("datei", (n, "anders")))
    return erg


# ------------------------------------------------------------------------------- Verknüpfung
def schluessel(info, wurzel=None):
    """Kennung eines Readers: Seriennummer, sonst Art+Modell+Ordnername (Kindle/PocketBook ohne Seriennummer)."""
    i = info or {}
    if i.get("seriennummer"):
        return i["seriennummer"]
    return "|".join([i.get("art", ""), i.get("modell", ""), Path(wurzel).name if wurzel else ""])


def verknuepft(e, info, wurzel=None):
    """Bibliotheksordner, der zum Reader gehört (Einstellung bibliotheken: {Kennung: Ordner}), oder None."""
    pfad = ((e or {}).get("bibliotheken") or {}).get(schluessel(info, wurzel))
    if pfad and bi.ist_bibliothek(pfad):
        return Path(pfad)
    return None


def verknuepfen(e, bib, info, wurzel=None):
    """Bibliothek und Reader verbinden: library.json (reader) und Einstellung bibliotheken. Ein Reader gehört zu
    genau einer Bibliothek; eine andere Verknüpfung desselben Readers wird ersetzt."""
    d = bi.bibliothek_lesen(bib)
    d["reader"] = bi.reader_eintrag(info or {})
    bi.bibliothek_schreiben(bib, d)
    e.setdefault("bibliotheken", {})[schluessel(info, wurzel)] = str(Path(bib))


def trennen(e, info, wurzel=None):
    (e.get("bibliotheken") or {}).pop(schluessel(info, wurzel), None)
