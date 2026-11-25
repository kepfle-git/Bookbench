# -*- coding: utf-8 -*-
"""
lua_data.py - Lua-Datentabellen lesen und schreiben (seit 1.4-beta2), für Dateien, die nur eine
Tabelle zurückgeben: Bookends-Vorlagen, LuaSettings-Dateien (settings/bookends.lua,
settings/bookshelf/settings.lua). Kein Lua-Interpreter: nur Literale (Zeichenketten, Zahlen,
true/false/nil, Tabellen), Kommentare werden übersprungen. Ausdrücke oder Funktionsaufrufe ergeben
einen LuaFehler.

Abbildung:
  Tabelle mit den Schlüsseln 1..n (lückenlos)  -> list
  andere Tabelle                               -> dict (Reihenfolge wie in der Datei)
  leere Tabelle                                -> dict (schreibt sich wieder als {})
  nil                                          -> None

  lesen(text)                   Wert nach "return" (bzw. der ganze Text, wenn kein return davor steht)
  schreiben(wert, einzug=0)     Lua-Literal, mehrzeilig wie KOReaders Dateien (4 Leerzeichen)
"""
import math
import re

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ZAHL = re.compile(r"0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_SCHLUESSELWOERTER = {"and", "break", "do", "else", "elseif", "end", "false", "for", "function", "goto", "if",
                      "in", "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while"}
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v",
            "\\": "\\", '"': '"', "'": "'", "\n": "\n"}


class LuaFehler(ValueError):
    pass


class _Leser:
    def __init__(self, text):
        self.t = text
        self.i = 0

    def fehler(self, was):
        zeile = self.t.count("\n", 0, self.i) + 1
        raise LuaFehler(f"{was} (Zeile {zeile})")

    def leer(self):
        """Leerraum und Kommentare überspringen."""
        t = self.t
        while self.i < len(t):
            c = t[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif t.startswith("--", self.i):
                lang = re.match(r"--\[(=*)\[", t[self.i:])
                if lang:
                    ende = t.find("]" + lang.group(1) + "]", self.i + lang.end())
                    if ende < 0:
                        self.fehler("unterminated comment")
                    self.i = ende + len(lang.group(1)) + 2
                else:
                    nl = t.find("\n", self.i)
                    self.i = len(t) if nl < 0 else nl + 1
            else:
                break

    def wert(self):
        self.leer()
        t, i = self.t, self.i
        if i >= len(t):
            self.fehler("value expected")
        c = t[i]
        if c == "{":
            return self.tabelle()
        if c in "\"'":
            return self.zeichenkette(c)
        if c == "[" and re.match(r"\[=*\[", t[i:]):
            return self.lange_zeichenkette()
        if c == "-" or c.isdigit() or (c == "." and i + 1 < len(t) and t[i + 1].isdigit()):
            return self.zahl()
        m = _NAME.match(t, i)
        if m:
            wort = m.group()
            self.i = m.end()
            if wort == "true":
                return True
            if wort == "false":
                return False
            if wort == "nil":
                return None
            if wort in ("math",) and t.startswith(".huge", self.i):        # math.huge (selten, aber möglich)
                self.i += 5
                return math.inf
            self.fehler(f"kein Datenwert: {wort}")
        self.fehler(f"unerwartetes Zeichen {c!r}")

    def zahl(self):
        t = self.t
        minus = False
        while t[self.i] == "-":
            minus = not minus
            self.i += 1
            self.leer()
        m = _ZAHL.match(t, self.i)
        if not m:
            self.fehler("number expected")
        self.i = m.end()
        s = m.group()
        if s[:2] in ("0x", "0X"):
            n = int(s, 16)
        elif any(ch in s for ch in ".eE"):
            n = float(s)
        else:
            n = int(s)
        return -n if minus else n

    def zeichenkette(self, q):
        """Lua-Zeichenketten sind Bytes: normale Zeichen als UTF-8, \\ddd und \\xXX als einzelne Bytes."""
        t = self.t
        self.i += 1
        b = bytearray()
        while True:
            if self.i >= len(t):
                self.fehler("unterminated string")
            c = t[self.i]
            if c == q:
                self.i += 1
                break
            if c == "\n":
                self.fehler("line break in string")
            if c != "\\":
                b += c.encode("utf-8")
                self.i += 1
                continue
            self.i += 1
            e = t[self.i] if self.i < len(t) else ""
            if e in _ESCAPES:
                b += _ESCAPES[e].encode("utf-8")
                self.i += 1
            elif e == "x":
                b.append(int(t[self.i + 1:self.i + 3], 16))
                self.i += 3
            elif e.isdigit():
                m = re.match(r"\d{1,3}", t[self.i:])
                b.append(int(m.group()) & 0xFF)
                self.i += m.end()
            elif e == "z":
                self.i += 1
                while self.i < len(t) and t[self.i] in " \t\r\n":
                    self.i += 1
            elif e == "u":
                m = re.match(r"u\{([0-9a-fA-F]+)\}", t[self.i:])
                if not m:
                    self.fehler("invalid \\u escape")
                b += chr(int(m.group(1), 16)).encode("utf-8")
                self.i += m.end()
            else:
                self.fehler(f"unbekanntes Escape \\{e}")
        return b.decode("utf-8", errors="replace")

    def lange_zeichenkette(self):
        t = self.t
        m = re.match(r"\[(=*)\[", t[self.i:])
        anfang = self.i + m.end()
        ende = t.find("]" + m.group(1) + "]", anfang)
        if ende < 0:
            self.fehler("unterminated long string")
        self.i = ende + len(m.group(1)) + 2
        s = t[anfang:ende]
        return s[1:] if s.startswith("\n") else s

    def tabelle(self):
        t = self.t
        self.i += 1
        paare = []
        n = 0
        while True:
            self.leer()
            if self.i >= len(t):
                self.fehler("unterminated table")
            if t[self.i] == "}":
                self.i += 1
                break
            if t[self.i] == "[" and not re.match(r"\[=*\[", t[self.i:]):
                self.i += 1
                k = self.wert()
                self.leer()
                if not t.startswith("]", self.i):
                    self.fehler("] expected")
                self.i += 1
                self.gleich()
                v = self.wert()
            else:
                m = _NAME.match(t, self.i)
                rest = t[m.end():] if m else ""
                if m and m.group() not in _SCHLUESSELWOERTER and re.match(r"\s*=(?!=)", rest):
                    k = m.group()
                    self.i = m.end()
                    self.gleich()
                    v = self.wert()
                else:
                    n += 1
                    k, v = n, self.wert()
            if v is not None:
                paare.append((k, v))
            self.leer()
            if self.i < len(t) and t[self.i] in ",;":
                self.i += 1
        if paare and all(isinstance(k, int) and not isinstance(k, bool) for k, __ in paare):
            schluessel = sorted(k for k, __ in paare)
            if schluessel == list(range(1, len(paare) + 1)):
                d = dict(paare)
                return [d[i] for i in schluessel]
        return dict(paare)

    def gleich(self):
        self.leer()
        if not self.t.startswith("=", self.i):
            self.fehler("= expected")
        self.i += 1


def lesen(text):
    """Den Wert einer Lua-Datendatei ("return { … }") lesen."""
    le = _Leser(text)
    le.leer()
    if text.startswith("return", le.i) and not _NAME.match(text, le.i + 6):
        le.i += 6
    w = le.wert()
    le.leer()
    if le.i < len(text):
        le.fehler("unexpected text after the value")
    return w


def datei_lesen(pfad):
    with open(pfad, encoding="utf-8") as f:
        return lesen(f.read())


def zeichenkette(s):
    """Lua-Zeichenkette in doppelten Anführungszeichen (UTF-8 bleibt lesbar)."""
    aus = []
    for ch in s:
        if ch in ('"', "\\"):
            aus.append("\\" + ch)
        elif ch == "\n":
            aus.append("\\n")
        elif ch == "\r":
            aus.append("\\r")
        elif ch == "\t":
            aus.append("\\t")
        elif ord(ch) < 32 or ord(ch) == 127:
            aus.append(f"\\{ord(ch):03d}")
        else:
            aus.append(ch)
    return '"' + "".join(aus) + '"'


def _schluessel(k):
    if isinstance(k, str) and _NAME.fullmatch(k) and k not in _SCHLUESSELWOERTER:
        return k
    if isinstance(k, bool):
        return "[" + ("true" if k else "false") + "]"
    if isinstance(k, (int, float)):
        return f"[{_zahl(k)}]"
    return "[" + zeichenkette(str(k)) + "]"


def _zahl(n):
    if isinstance(n, float):
        if math.isinf(n):
            return "math.huge" if n > 0 else "-math.huge"
        if n.is_integer() and abs(n) < 1e15:
            return repr(n)                          # "14.0" bleibt eine Kommazahl (Lua 5.3 unterscheidet)
        return repr(n)
    return str(n)


def _einfach(w):
    return w is None or isinstance(w, (bool, int, float, str)) or (isinstance(w, (list, tuple, dict)) and not w)


def schreiben(w, einzug=0):
    """Wert als Lua-Literal. Kurze Tabellen aus einfachen Werten bleiben einzeilig."""
    if w is None:
        return "nil"
    if isinstance(w, bool):
        return "true" if w else "false"
    if isinstance(w, (int, float)):
        return _zahl(w)
    if isinstance(w, str):
        return zeichenkette(w)
    if isinstance(w, (list, tuple)):
        if not w:
            return "{}"
        teile = [schreiben(x, einzug + 1) for x in w]
        if all(_einfach(x) for x in w) and sum(len(x) for x in teile) < 70:
            return "{ " + ", ".join(teile) + " }"
        innen = " " * (4 * (einzug + 1))
        return "{\n" + "".join(f"{innen}{x},\n" for x in teile) + " " * (4 * einzug) + "}"
    if isinstance(w, dict):
        if not w:
            return "{}"
        teile = [f"{_schluessel(k)} = {schreiben(v, einzug + 1)}" for k, v in w.items() if v is not None]
        if all(_einfach(v) for v in w.values()) and sum(len(x) for x in teile) < 70 and len(teile) <= 4:
            return "{ " + ", ".join(teile) + " }"
        innen = " " * (4 * (einzug + 1))
        return "{\n" + "".join(f"{innen}{x},\n" for x in teile) + " " * (4 * einzug) + "}"
    raise TypeError(f"nicht als Lua darstellbar: {type(w).__name__}")
