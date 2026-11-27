# -*- coding: utf-8 -*-
"""
book_collections.py - Sammlungen (seit 2.4-beta2), Logik ohne Oberfläche: KOReaders Sammlungen lesen und schreiben,
Bookbenchs Hauptkopie in einer Bibliothek auf dem Rechner, Leseordnung einfügen, Abgleich mit dem Reader.

KOReader (frontend/readcollection.lua, settings/collection.lua auf dem Reader):
    return { ["favorites"] = { settings = { order = 1 }, { file = "/mnt/onboard/a.epub", order = 1 }, … }, … }
Jede Sammlung ist eine Liste von Dateien mit absolutem Pfad auf dem Gerät; order gilt, wenn settings.collate fehlt
(manuell sortiert), settings.order ist die Stelle der Sammlung in KOReaders Liste. Einträge, deren Datei es nicht
gibt, verwirft KOReader beim Lesen. Ein Eintrag kann nur eine ganze Datei sein (Geschichten in Anthologien kommen
mit dem Patch in 2.4-beta3).

Sammlung (dict, so auch in library.json unter "sammlungen" und als Basis des Abgleichs):
    name          Name wie in KOReader ("favorites" = KOReaders Favoriten)
    eintraege     [Eintrag] in Lesereihenfolge; Eintrag = {"rel": Pfad relativ zur Wurzel} für ein Buch oder ein
                  Platzhalter {"titel", "autor", "kuerzel"} aus einer eingefügten Leseordnung (Geschichte in einer
                  Anthologie oder nicht gefunden); dazu optional "fremd": absoluter Pfad, der nicht unter der Wurzel
                  liegt (z. B. SD-Karte) - bleibt erhalten, Bookbench zeigt ihn nur
    settings      KOReaders settings-Tabelle (bleibt erhalten; Bookbench nimmt nur collate weg, wenn es die
                  Reihenfolge setzt)

  Ort: ort(ordner) -> ("bibliothek", wurzel) | ("reader", wurzel) | (None, None)
  laden(ordner) -> [Sammlung]; speichern(ordner, sammlungen, sicherung) - schreibt library.json bzw. collection.lua
  von_lua(daten, laufwerk) / nach_lua(sammlungen, laufwerk, alt)   Umwandlung (alt: vorhandene Tabelle)
  leseordnung_lesen(text) -> [Zeile];  zuordnen(zeilen, buecher, wurzel) -> [Eintrag] mit Treffergüte
  vergleichen(rechner, reader, basis) -> [(name, zustand)];  zusammenfuehren(...)   für core/sync
"""
import difflib
import os
import re
import unicodedata
from pathlib import Path


FAVORITEN = "favorites"
DATEI = "collection.lua"


# ------------------------------------------------------------------------------- Ort
def reader_wurzel(ordner):
    from bookbench.core import reading
    return reading._wurzel(ordner) if ordner else None


def ort(ordner):
    """Wo leben die Sammlungen des geöffneten Ordners? Eine Bibliothek auf dem Rechner (library.json) oder der
    E-Reader selbst (collection.lua). Sonst (None, None): ein loser Ordner hat keine Sammlungen."""
    if not ordner:
        return None, None
    from bookbench.core import book_import as bi
    if bi.ist_bibliothek(ordner):
        return "bibliothek", Path(ordner)
    w = reader_wurzel(ordner)
    if w is not None:
        return "reader", Path(w)
    return None, None


def lua_pfad(wurzel):
    from bookbench.device import device as kg
    return Path(wurzel) / kg.ko_ordner(kg.art_von(wurzel)) / "settings" / DATEI


def laufwerk(wurzel):
    from bookbench.device import device as kg
    from bookbench.preview.plugins import LAUFWERK
    return LAUFWERK.get(kg.art_von(wurzel), "/mnt/onboard")


# ------------------------------------------------------------------------------- KOReader-Format
def _rel(pfad, lw):
    pfad = str(pfad or "")
    vorne = lw.rstrip("/") + "/"
    return pfad[len(vorne):] if pfad.startswith(vorne) else None


def von_lua(daten, lw):
    """[Sammlung] aus collection.lua (dict); Reihenfolge der Sammlungen nach settings.order."""
    erg = []
    for name, tab in (daten or {}).items():
        if not isinstance(name, str) or not isinstance(tab, (dict, list)):
            continue
        settings = dict(tab.get("settings") or {}) if isinstance(tab, dict) else {}
        posten = list(tab.values()) if isinstance(tab, dict) else list(tab)
        posten = [p for p in posten if isinstance(p, dict) and p.get("file")]
        if not settings.get("collate"):
            posten.sort(key=lambda p: (p.get("order") if isinstance(p.get("order"), (int, float)) else 1e9))
        eintraege = []
        for p in posten:
            r = _rel(p["file"], lw)
            eintraege.append({"rel": r} if r is not None else {"fremd": str(p["file"])})
        erg.append({"name": name, "eintraege": eintraege, "settings": settings})
    erg.sort(key=lambda s: (s["name"] != FAVORITEN, s["settings"].get("order", 1e9), s["name"].casefold()))
    return erg


def nach_lua(s, lw):
    """Tabelle einer Sammlung für collection.lua: settings und die Dateien (Platzhalter fallen weg; order zählt alle
    Einträge mit, damit ein Platzhalter seinen Platz behält, falls ihn später ein Patch füllt)."""
    tab = {"settings": dict(s.get("settings") or {})}
    manuell = not tab["settings"].get("collate")
    n = 0
    for i, e in enumerate(s.get("eintraege") or [], 1):
        datei = (lw.rstrip("/") + "/" + e["rel"]) if e.get("rel") else e.get("fremd")
        if not datei:
            continue
        n += 1
        tab[n] = {"file": datei, "order": i} if manuell else {"file": datei}
    return tab


def lua_lesen(wurzel):
    from bookbench.preview.plugins import einstellungen_lesen
    return von_lua(einstellungen_lesen(lua_pfad(wurzel)), laufwerk(wurzel))


def lua_schreiben(wurzel, sammlungen, geaendert=None, geloescht=(), sicherung=None):
    """Nur die geänderten Sammlungen ersetzen (geaendert = Namen, None = alle), der Rest der Datei bleibt stehen.
    sicherung(pfad) wird vorher mit der alten Datei gerufen."""
    from bookbench.preview.plugins import einstellungen_schreiben
    p = lua_pfad(wurzel)
    if sicherung and p.exists():
        sicherung(p)
    lw = laufwerk(wurzel)
    setzen = {s["name"]: nach_lua(s, lw) for s in sammlungen if geaendert is None or s["name"] in geaendert}
    einstellungen_schreiben(p, setzen, list(geloescht))


# ------------------------------------------------------------------------------- Laden und speichern
def laden(ordner):
    art, w = ort(ordner)
    if art == "bibliothek":
        from bookbench.core import book_import as bi
        return [_sauber(s) for s in bi.bibliothek_lesen(w).get("sammlungen") or [] if isinstance(s, dict)]
    if art == "reader":
        return lua_lesen(w)
    return []


def _sauber(s):
    return {"name": str(s.get("name") or ""), "settings": dict(s.get("settings") or {}),
            "eintraege": [dict(e) for e in s.get("eintraege") or [] if isinstance(e, dict)]}


def speichern(ordner, sammlungen, geaendert=None, geloescht=(), sicherung=None):
    art, w = ort(ordner)
    if art == "bibliothek":
        from bookbench.core import book_import as bi
        d = bi.bibliothek_lesen(w)
        d["sammlungen"] = [_sauber(s) for s in sammlungen]
        bi.bibliothek_schreiben(w, d)
    elif art == "reader":
        lua_schreiben(w, sammlungen, geaendert, geloescht, sicherung)
    else:
        raise OSError("no library or e-reader")


# ------------------------------------------------------------------------------- Bearbeiten
def finden(sammlungen, name):
    return next((s for s in sammlungen if s["name"] == name), None)


def neu(sammlungen, name, eintraege=()):
    """Neue Sammlung (manuell sortiert) hinten anhängen; settings.order nach der bisher letzten."""
    letzte = max([s["settings"].get("order", 0) for s in sammlungen if isinstance(s["settings"].get("order"), (int, float))]
                 or [0])
    s = {"name": name, "settings": {"order": int(letzte) + 1}, "eintraege": [dict(e) for e in eintraege]}
    sammlungen.append(s)
    return s


def manuell(s):
    """Bookbench setzt die Reihenfolge: KOReader soll sie so zeigen (collate weg = manuell)."""
    s["settings"].pop("collate", None)


def rels(s):
    return [e["rel"] for e in s["eintraege"] if e.get("rel")]


def hinzufuegen(s, rel_liste):
    """Bücher hinten anhängen (schon enthaltene nicht doppelt). Anzahl neuer."""
    da = set(rels(s))
    n = 0
    for r in rel_liste:
        if r not in da:
            s["eintraege"].append({"rel": r})
            da.add(r)
            n += 1
    return n


def name_frei(sammlungen, wunsch):
    namen = {s["name"].casefold() for s in sammlungen}
    if wunsch.casefold() not in namen:
        return wunsch
    i = 2
    while f"{wunsch} ({i})".casefold() in namen:
        i += 1
    return f"{wunsch} ({i})"


# ------------------------------------------------------------------------------- Leseordnung einfügen
_ZEILE = re.compile(r"^\s*(?:(\d+(?:[.,]\d+)?)\s*[.):\-–]?\s+)?(.+?)\s*$")
_KUERZEL = re.compile(r"\s*\(([^()]{1,12})\)\s*$")
_VON = re.compile(r"\s+(?:by|von)\s+(.+)$", re.I)


def leseordnung_lesen(text):
    """Zeilen wie „2. The Wolf of Ash and Fire (EoT) by Graham McNeill“ (Seiten wie heresyomnibus.com) →
    [{"nr", "titel", "kuerzel", "autor"}]. Tabulatoren gelten als Trenner zwischen Titel und Autor. Zeilen ohne
    Buchstaben, Überschriften wie „Reading Order“ oder „Legend: …“ fallen weg."""
    erg = []
    for roh in (text or "").splitlines():
        z = roh.replace(" ", " ").strip()
        if not z or not re.search(r"[^\W\d_]", z) or re.match(r"(?i)(legend|legende|reading order|leseordnung)\b", z):
            continue
        mv = re.match(r"(?i)^(?:by|von)\s+(.+)$", z)
        if mv and erg and not erg[-1]["autor"]:        # Autor in einer eigenen Zeile (kopiert aus einer Webseite)
            erg[-1]["autor"] = mv.group(1).strip()
            continue
        if _KUERZEL.fullmatch(" " + z) and erg and not erg[-1]["kuerzel"]:     # „(EoT)“ allein in einer Zeile
            erg[-1]["kuerzel"] = _KUERZEL.fullmatch(" " + z).group(1)
            continue
        m = _ZEILE.match(z)
        nr, rest = m.group(1), m.group(2)
        autor = ""
        if "\t" in rest:
            rest, autor = (t.strip() for t in rest.split("\t", 1))
            autor = re.sub(r"(?i)^(by|von)\s+", "", autor)
        else:
            mv = _VON.search(rest)
            if mv:
                autor, rest = mv.group(1).strip(), rest[:mv.start()].strip()
        kuerzel = ""
        mk = _KUERZEL.search(rest)
        if mk and len(mk.group(1).split()) == 1:
            kuerzel, rest = mk.group(1), rest[:mk.start()].strip()
        if rest:
            erg.append({"nr": (nr or "").replace(",", "."), "titel": rest, "kuerzel": kuerzel, "autor": autor})
    return erg


def _norm(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().casefold()
    t = re.sub(r"[’'`]", "", t)
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return re.sub(r"^(the|a|an|der|die|das)\s+", "", t)


def _titel_varianten(titel):
    """„Eisenhorn: Xenos“ passt auch auf „Xenos“ (Reihe vor dem Doppelpunkt)."""
    v = {_norm(titel)}
    if ":" in titel:
        v.add(_norm(titel.split(":", 1)[1]))
    return {x for x in v if x}


def _treffer(zeile, buecher):
    """(Buch, Güte 0..1) des besten Treffers oder (None, 0)."""
    gesucht = _titel_varianten(zeile["titel"])
    autor = _norm(zeile.get("autor", ""))
    best, guete = None, 0.0
    for b in buecher:
        if getattr(b, "fehler", None):
            continue
        kand = _titel_varianten(b.titel or "")
        g = max((1.0 if a == k else difflib.SequenceMatcher(None, a, k).ratio()) for a in gesucht for k in kand) \
            if kand else 0.0
        if autor and g >= 0.8:
            ba = _norm(b.autor or "")
            if ba and (autor in ba or ba in autor):
                g += 0.05
            elif ba:
                g -= 0.1
        if g > guete:
            best, guete = b, g
    return (best, guete) if guete >= 0.86 else (None, guete)


def zuordnen(zeilen, buecher, wurzel):
    """[(Eintrag, Zeile, Buch oder None)]: gefundene Bücher als {"rel"}, sonst Platzhalter {"titel", "autor",
    "kuerzel"} (mit Kürzel: Geschichte in einer Anthologie, kommt mit dem Patch in beta3)."""
    wurzel = Path(wurzel)
    erg = []
    for z in zeilen:
        b, __ = _treffer(z, buecher)
        if b is not None:
            try:
                erg.append(({"rel": Path(b.pfad).resolve().relative_to(wurzel.resolve()).as_posix()}, z, b))
                continue
            except ValueError:
                pass
        erg.append(({"titel": z["titel"], "autor": z.get("autor", ""), "kuerzel": z.get("kuerzel", "")}, z, None))
    return erg


# ------------------------------------------------------------------------------- Abgleich
def _da(e, vorhanden):
    if e.get("fremd"):
        return True
    return bool(e.get("rel")) and (vorhanden is None or e["rel"] in vorhanden)


def dateien(s, vorhanden=None):
    """Was KOReader von einer Sammlung sieht (zum Vergleichen): Dateien in Reihenfolge; Platzhalter und Bücher, die
    nicht auf dem Reader liegen (vorhanden = Menge der rel dort), fallen weg - KOReader verwirft solche Einträge
    beim Lesen, sie dürfen deshalb nicht als „auf dem Reader gelöscht“ gelten."""
    if s is None:
        return None
    return [e.get("rel") or e.get("fremd") for e in s["eintraege"] if _da(e, vorhanden)]


def vergleichen(rechner, reader, basis, vorhanden=None):
    """[(name, zustand)] wie core/sync.ZUSTAENDE; basis {name: [Dateien]} vom letzten Abgleich. Gleiche Sammlungen
    ohne Basis bekommen still eine (Rückgabe 2: geänderte Basis oder None)."""
    a = {s["name"]: dateien(s, vorhanden) for s in rechner}
    b = {s["name"]: dateien(s, vorhanden) for s in reader}
    basis = dict(basis or {})
    erg, geaendert = [], False
    for name in sorted(set(a) | set(b) | set(basis), key=lambda n: (n != FAVORITEN, n.casefold())):
        x, y, z = a.get(name), b.get(name), basis.get(name)
        if x is None and y is None:
            if z is not None:
                del basis[name]
                geaendert = True
            continue
        if x is not None and y is not None:
            if x == y:
                if z != x:
                    basis[name] = x
                    geaendert = True
                continue
            if z is None:
                erg.append((name, "konflikt"))
            elif x != z and y != z:
                erg.append((name, "konflikt"))
            else:
                erg.append((name, "rechner_geaendert" if x != z else "reader_geaendert"))
            continue
        if x is not None:
            erg.append((name, "reader_geloescht" if z is not None else "neu_rechner"))
        else:
            erg.append((name, "rechner_geloescht" if z is not None else "neu_reader"))
    return erg, (basis if geaendert else None)


def uebernehmen_vom_reader(alt, reader_s, vorhanden=None):
    """Sammlung auf dem Rechner nach der Fassung vom Reader: Dateien und Reihenfolge vom Reader; Platzhalter und
    Bücher, die (noch) nicht auf dem Reader liegen, bleiben hinter dem Eintrag, hinter dem sie vorher standen."""
    if alt is None:
        return _sauber(reader_s)
    nach = {}
    vorher = None
    for e in alt["eintraege"]:
        if _da(e, vorhanden):
            vorher = e.get("rel") or e.get("fremd")
        else:
            nach.setdefault(vorher, []).append(e)
    neu_e = list(nach.get(None, []))
    for e in reader_s["eintraege"]:
        neu_e.append(dict(e))
        neu_e += nach.get(e.get("rel") or e.get("fremd"), [])
    return {"name": alt["name"], "settings": dict(reader_s.get("settings") or alt["settings"]), "eintraege": neu_e}


def unterschiede(a, b, vorhanden=None):
    """[(Art, [Dateinamen])] für die Anzeige: was hat die eine Fassung, was die andere nicht, Reihenfolge anders?
    a = Rechner. Art: "rechner", "reader", "reihenfolge"."""
    x, y = dateien(a, vorhanden) or [], dateien(b, vorhanden) or []
    erg = []
    nur_a = [p for p in x if p not in y]
    nur_b = [p for p in y if p not in x]
    if nur_a:
        erg.append(("rechner", [os.path.basename(p) for p in nur_a]))
    if nur_b:
        erg.append(("reader", [os.path.basename(p) for p in nur_b]))
    if not nur_a and not nur_b and x != y:
        erg.append(("reihenfolge", []))
    return erg


# ------------------------------------------------------------------------------- Abgleich ausführen (core/sync)
def abgleich_vergleichen(bib, reader, basis, vorhanden):
    """Für core/sync.vergleichen: ([(name, zustand)], neue Basis oder None). Kaputte collection.lua = nichts tun."""
    try:
        return vergleichen(laden(bib), lua_lesen(reader), basis, vorhanden)
    except Exception:
        return [], None


def abgleich_ausfuehren(bib, reader, name, aktion, vorhanden, sicherung=None):
    """Eine Sammlung abgleichen; Rückgabe der neue Basis-Eintrag (Dateiliste) oder None (weg)."""
    rechner, geraet = laden(bib), lua_lesen(reader)
    a, b = finden(rechner, name), finden(geraet, name)
    if aktion == "zum_reader" and a is not None:
        lua_schreiben(reader, [a], [name], (), sicherung)
        return dateien(a, vorhanden)
    if aktion == "zum_rechner" and b is not None:
        neu_s = uebernehmen_vom_reader(a, b, vorhanden)
        rechner = [neu_s if s is a else s for s in rechner] if a is not None else rechner + [neu_s]
        speichern(bib, rechner)
        return dateien(b, vorhanden)
    if aktion == "loeschen_reader":
        lua_schreiben(reader, [], [], [name], sicherung)
        return None
    if aktion == "loeschen_rechner":
        speichern(bib, [s for s in rechner if s["name"] != name])
        return None
    return dateien(a, vorhanden) if a is not None else dateien(b, vorhanden)
