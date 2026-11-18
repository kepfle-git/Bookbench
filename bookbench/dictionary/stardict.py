# -*- coding: utf-8 -*-
"""
stardict.py - StarDict-Wörterbücher lesen und schreiben (das Format von KOReader).

  finden(ordner)      die .ifo-Datei im Ordner (oder None)
  lesen(ifo)          StarDict: ifo-Felder, Einträge [(Wort, [(Typ, Bytes)])], Synonyme
  schreiben(...)      .ifo/.idx/.dict/.syn neu schreiben (Reihenfolge wie StarDict sie verlangt)
  als_html(teile)     Inhalt eines Eintrags als HTML (Text wird maskiert)

Unterstützt: .dict und .dict.dz (gzip-kompatibel), .idx und .idx.gz, idxoffsetbits=64,
sametypesequence mit einem oder mehreren Typen und Einträge ohne sametypesequence.
Geschrieben wird immer unkomprimiert mit 32-Bit-Offsets.
"""
import gzip
import html
import struct
from pathlib import Path

TEXTTYPEN = set("mtylgxhkwr")              # klein: Text, mit \0 abgeschlossen
HTMLTYPEN = set("hgx")


def finden(ordner):
    p = Path(ordner)
    if p.suffix == ".ifo" and p.is_file():
        return p
    try:
        ifos = sorted(p.glob("*.ifo"))
    except OSError:
        return None
    return ifos[0] if ifos else None


def sortierschluessel(wort):
    """StarDict: erst ohne Groß/Klein (nur ASCII), dann bytegenau."""
    b = wort.encode("utf-8")
    return b.lower(), b


def _datei(stamm, *endungen):
    for e in endungen:
        p = stamm.with_name(stamm.name + e)
        if p.is_file():
            return p
    return None


def _lesen_bytes(p):
    roh = p.read_bytes()
    return gzip.decompress(roh) if p.suffix in (".dz", ".gz") else roh


class StarDict:
    def __init__(self):
        self.ifo = {}                     # Feldname -> Wert (ohne die erste Zeile)
        self.stamm = ""
        self.eintraege = []               # [(Wort, [(Typ, Bytes)])] in Dateireihenfolge
        self.synonyme = []                # [(Wort, Index in eintraege)]


def _teile(daten, sts):
    """Inhalt eines Eintrags in (Typ, Bytes) zerlegen."""
    erg, i = [], 0
    typen = list(sts) if sts else None
    while i < len(daten):
        if typen is not None:
            if not typen:
                break
            t = typen.pop(0)
            letzter = not typen
        else:
            t = chr(daten[i])
            i += 1
            letzter = False
        if t.islower():
            if letzter:
                ende = len(daten)
                erg.append((t, daten[i:ende]))
                i = ende
            else:
                ende = daten.find(b"\0", i)
                ende = len(daten) if ende < 0 else ende
                erg.append((t, daten[i:ende]))
                i = ende + 1
        else:
            if letzter:
                erg.append((t, daten[i:]))
                i = len(daten)
            else:
                (n,) = struct.unpack(">I", daten[i:i + 4])
                erg.append((t, daten[i + 4:i + 4 + n]))
                i += 4 + n
    return erg


def lesen(ifo_pfad):
    ifo_pfad = Path(ifo_pfad)
    sd = StarDict()
    zeilen = ifo_pfad.read_text(encoding="utf-8", errors="replace").splitlines()
    for z in zeilen[1:]:
        if "=" in z:
            k, v = z.split("=", 1)
            sd.ifo[k.strip()] = v.strip()
    sd.stamm = ifo_pfad.name[:-4]
    stamm = ifo_pfad.with_suffix("")
    idx_p, dict_p = _datei(stamm, ".idx", ".idx.gz"), _datei(stamm, ".dict", ".dict.dz")
    if not idx_p or not dict_p:
        raise FileNotFoundError(f"{ifo_pfad.name}: .idx oder .dict fehlt")
    idx, daten = _lesen_bytes(idx_p), _lesen_bytes(dict_p)
    breit = sd.ifo.get("idxoffsetbits") == "64"
    sts = sd.ifo.get("sametypesequence", "")
    i = 0
    while i < len(idx):
        ende = idx.index(b"\0", i)
        wort = idx[i:ende].decode("utf-8", "replace")
        if breit:
            off, n = struct.unpack(">QI", idx[ende + 1:ende + 13])
            i = ende + 13
        else:
            off, n = struct.unpack(">II", idx[ende + 1:ende + 9])
            i = ende + 9
        sd.eintraege.append((wort, _teile(daten[off:off + n], sts)))
    syn_p = _datei(stamm, ".syn")
    if syn_p:
        syn = syn_p.read_bytes()
        i = 0
        while i < len(syn):
            ende = syn.index(b"\0", i)
            (nr,) = struct.unpack(">I", syn[ende + 1:ende + 5])
            if nr < len(sd.eintraege):
                sd.synonyme.append((syn[i:ende].decode("utf-8", "replace"), nr))
            i = ende + 5
    return sd


def als_html(teile):
    """HTML-Fassung eines Eintrags (Text maskiert, Zeilenumbrüche als <br/>); Bilder u. ä. fehlen."""
    aus = []
    for t, b in teile:
        s = b.decode("utf-8", "replace")
        if t in HTMLTYPEN:
            aus.append(s)
        elif t in TEXTTYPEN:
            aus.append(html.escape(s).replace("\n", "<br/>"))
    return "".join(aus)


def nur_text(teile):
    """True, wenn der Eintrag reiner Text (m) ist."""
    return all(t == "m" for t, _ in teile)


def schreiben(ordner, stamm, ifo, eintraege, synonyme, typ="h"):
    """eintraege: [(Wort, Bytes)] (jeder Inhalt vom Typ `typ`), synonyme: [(Wort, Wort des
    Eintrags)]. Sortiert nach StarDict-Regeln, schreibt .ifo/.idx/.dict/.syn und entfernt
    alte .dict.dz/.idx.gz gleichen Namens. Gibt (Einträge, Synonyme) zurück."""
    ordner = Path(ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    reihe = sorted(range(len(eintraege)), key=lambda i: sortierschluessel(eintraege[i][0]))
    neu_index, idx, off = {}, bytearray(), 0
    basis = ordner / stamm
    tmp = {e: basis.with_name(basis.name + e + ".tmp") for e in (".dict", ".idx", ".syn", ".ifo")}
    with open(tmp[".dict"], "wb") as f:
        for neu, alt in enumerate(reihe):
            wort, inhalt = eintraege[alt]
            f.write(inhalt)
            idx += wort.encode("utf-8") + b"\0" + struct.pack(">II", off, len(inhalt))
            off += len(inhalt)
            neu_index.setdefault(wort, neu)
    tmp[".idx"].write_bytes(idx)
    paare = sorted({(w, neu_index[z]) for w, z in synonyme if z in neu_index and w and w != z},
                   key=lambda p: (sortierschluessel(p[0]), p[1]))
    with open(tmp[".syn"], "wb") as f:
        for w, nr in paare:
            f.write(w.encode("utf-8") + b"\0" + struct.pack(">I", nr))
    felder = {k: v for k, v in ifo.items() if k not in ("idxoffsetbits", "dicttype")}
    felder.update(wordcount=str(len(eintraege)), idxfilesize=str(len(idx)), sametypesequence=typ)
    if paare:
        felder["synwordcount"] = str(len(paare))
    else:
        felder.pop("synwordcount", None)
    felder.setdefault("version", "2.4.2")
    reihenfolge = ["version", "bookname", "wordcount", "synwordcount", "idxfilesize", "sametypesequence"]
    zeilen = ["StarDict's dict ifo file"] + [f"{k}={felder[k]}" for k in reihenfolge if k in felder] + \
             [f"{k}={v}" for k, v in felder.items() if k not in reihenfolge]
    tmp[".ifo"].write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    for e, t in tmp.items():
        if e == ".syn" and not paare:
            t.unlink()
            basis.with_name(basis.name + ".syn").unlink(missing_ok=True)
            continue
        t.replace(basis.with_name(basis.name + e))
    for alt in (".dict.dz", ".idx.gz"):
        basis.with_name(basis.name + alt).unlink(missing_ok=True)
    return len(eintraege), len(paare)
