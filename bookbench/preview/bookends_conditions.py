# -*- coding: utf-8 -*-
"""
bookends_conditions.py - Bedingungen in Bookends-Zeilen (seit 2.2-beta3). Keine Oberfläche.

Bookends kennt in jeder Zeile Blöcke [if:ausdruck]dann[else]sonst[/if] (bookends_tokens.lua: processConditionals),
beliebig verschachtelt. Ausdruck: Teile wie batt<20, wifi=on, not series, title="A Book", chap_title_1!=@title,
calibre{mood}="cosy", verknüpft mit and/or/not und Klammern. Vergleiche: = != < > <= >=; ein Teil ohne Vergleich
ist wahr, wenn der Wert nicht leer ist.

  felder(plugin_ordner)      [(feld, vergleich, beispielwert, beschreibung)] aus menu/tokens_catalogue.lua
                             (M.CONDITIONALS, Gruppe "ifelse") des installierten Bookends
  beispiele(plugin_ordner)   [(beschreibung, ausdruck)] (Gruppe "templates": fertige Zeilen mit Bedingungen)
  bloecke(text)              Blöcke einer Zeile als Baum (Block), None bei unpaarigen Tags
  zerlegen(ausdruck)         {"verknuepfung": "and"|"or", "teile": [{nicht, feld, vergleich, wert}]} oder None,
                             wenn der Ausdruck Klammern hat oder and und or mischt (dann nur als Text bearbeitbar)
  bauen(zerlegt)             Gegenstück zu zerlegen()
  block_text(ausdruck, dann, sonst)   fertiger Block
  ersetzen(text, block, neu)          Block im Text ersetzen
  aufloesen(text, block)              Block entfernen, nur der Dann-Teil bleibt
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from bookbench.core import lua_data

VERGLEICHE = ("=", "!=", "<", ">", "<=", ">=")
_TAG = re.compile(r"\[if:([^\]]*)\]|\[else\]|\[/if\]")
_TEIL = re.compile(r'^\s*(?P<nicht>not\s+)?(?P<feld>[A-Za-z_][\w]*(?:\{[^}]*\})?)'
                   r'(?:\s*(?P<vergleich><=|>=|!=|=|<|>)\s*(?P<wert>"[^"]*"|[^\s()]+))?\s*$')


@dataclass
class Block:
    anfang: int                   # Index von "[if:"
    ende: int                     # Index hinter "[/if]"
    ausdruck: str
    dann: tuple                   # (anfang, ende) im Text
    sonst: tuple = None           # (anfang, ende) oder None
    kinder: list = field(default_factory=list)

    def dann_text(self, text):
        return text[self.dann[0]:self.dann[1]]

    def sonst_text(self, text):
        return text[self.sonst[0]:self.sonst[1]] if self.sonst else None


def _katalog(plugin_ordner):
    try:
        text = (Path(plugin_ordner) / "menu" / "tokens_catalogue.lua").read_text(encoding="utf-8")
    except OSError:
        return []
    erg = []
    for m in re.finditer(r'\{\s*description\s*=\s*_\("((?:[^"\\]|\\.)*)"\)\s*,\s*expression\s*=\s*"((?:[^"\\]|\\.)*)"'
                         r'\s*,\s*chip\s*=\s*"([^"]+)"', text):
        erg.append((lua_data.lesen('"' + m.group(1) + '"'), lua_data.lesen('"' + m.group(2) + '"'), m.group(3)))
    return erg


def felder(plugin_ordner):
    erg, gesehen = [], set()
    for beschreibung, ausdruck, chip in _katalog(plugin_ordner):
        if chip != "ifelse":
            continue
        m = re.match(r"\[if:([^\]]*)\]", ausdruck)
        z = zerlegen(m.group(1)) if m else None
        if not z or len(z["teile"]) != 1:
            continue
        t = z["teile"][0]
        if t["feld"] in gesehen:
            continue
        gesehen.add(t["feld"])
        erg.append((t["feld"], t["vergleich"], t["wert"], beschreibung))
    return erg


def beispiele(plugin_ordner):
    return [(b, a) for b, a, chip in _katalog(plugin_ordner) if chip == "templates"]


def bloecke(text):
    """Oberste Blöcke (mit kinder) oder None, wenn die Tags nicht paarig sind."""
    wurzel, stapel = [], []
    for m in _TAG.finditer(text or ""):
        tag = m.group(0)
        if tag.startswith("[if:"):
            b = Block(m.start(), -1, m.group(1), (m.end(), -1))
            (stapel[-1][0].kinder if stapel else wurzel).append(b)
            stapel.append([b, None])              # [Block, Index von [else]]
        elif tag == "[else]":
            if not stapel or stapel[-1][1] is not None:
                return None
            stapel[-1][1] = (m.start(), m.end())
        else:
            if not stapel:
                return None
            b, sonst = stapel.pop()
            if sonst:
                b.dann = (b.dann[0], sonst[0])
                b.sonst = (sonst[1], m.start())
            else:
                b.dann = (b.dann[0], m.start())
            b.ende = m.end()
    return None if stapel else wurzel


def alle(bloecke_liste):
    """Alle Blöcke in Textreihenfolge mit Tiefe: [(block, tiefe)]."""
    erg = []

    def gehen(liste, tiefe):
        for b in liste:
            erg.append((b, tiefe))
            gehen(b.kinder, tiefe + 1)
    gehen(bloecke_liste or [], 0)
    return erg


def block_an(text, pos):
    """Innerster Block, in dem die Schreibmarke pos steht, oder None."""
    treffer = None
    for b, __ in alle(bloecke(text) or []):
        if b.anfang <= pos <= b.ende:
            treffer = b
    return treffer


def _teile_trennen(ausdruck):
    """Ausdruck an and/or (außerhalb von Anführungszeichen) trennen: (teile, verknüpfungen) oder None bei Klammern."""
    teile, verkn, rest, i = [], [], "", 0
    s = ausdruck
    while i < len(s):
        c = s[i]
        if c == '"':
            j = s.find('"', i + 1)
            j = len(s) - 1 if j < 0 else j
            rest += s[i:j + 1]
            i = j + 1
            continue
        if c in "()":
            return None
        m = re.match(r"\s+(and|or)\s+", s[i:])
        if m:
            teile.append(rest)
            verkn.append(m.group(1))
            rest = ""
            i += m.end()
            continue
        rest += c
        i += 1
    teile.append(rest)
    return teile, verkn


def zerlegen(ausdruck):
    getrennt = _teile_trennen(ausdruck or "")
    if getrennt is None:
        return None
    teile, verkn = getrennt
    if len(set(verkn)) > 1:
        return None
    erg = []
    for t in teile:
        m = _TEIL.match(t)
        if not m:
            return None
        wert = m.group("wert")
        erg.append({"nicht": bool(m.group("nicht")), "feld": m.group("feld"),
                    "vergleich": m.group("vergleich"), "wert": wert})
    return {"verknuepfung": verkn[0] if verkn else "and", "teile": erg}


def wert_text(wert):
    """Wert für den Ausdruck: mit Leerzeichen in Anführungszeichen (wie title="A Book")."""
    if wert is None:
        return None
    wert = str(wert)
    if wert.startswith('"') and wert.endswith('"') and len(wert) >= 2:
        return wert
    return f'"{wert}"' if re.search(r'[\s()\]]', wert) else wert


def bauen(zerlegt):
    stuecke = []
    for t in zerlegt["teile"]:
        s = ("not " if t.get("nicht") else "") + t["feld"].strip()
        if t.get("vergleich") and t.get("wert") not in (None, ""):
            s += t["vergleich"] + wert_text(t["wert"])
        stuecke.append(s)
    return f" {zerlegt.get('verknuepfung') or 'and'} ".join(stuecke)


def block_text(ausdruck, dann, sonst=None):
    return f"[if:{ausdruck}]{dann}" + (f"[else]{sonst}" if sonst is not None else "") + "[/if]"


def ersetzen(text, block, neu):
    return text[:block.anfang] + neu + text[block.ende:]


def aufloesen(text, block):
    return text[:block.anfang] + block.dann_text(text) + text[block.ende:]


def lesbar(ausdruck, feldnamen=None):
    """Kurzer lesbarer Text: Beschreibung des Felds statt des Kürzels, wo bekannt (feldnamen {feld: text})."""
    z = zerlegen(ausdruck)
    if not z or not feldnamen:
        return ausdruck
    stuecke = []
    for t in z["teile"]:
        name = feldnamen.get(t["feld"], t["feld"])
        s = ("not " if t["nicht"] else "") + name
        if t["vergleich"]:
            s += f" {t['vergleich']} {t['wert']}"
        stuecke.append(s)
    return f" {z['verknuepfung']} ".join(stuecke)
