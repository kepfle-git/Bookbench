# -*- coding: utf-8 -*-
"""
toc_mark.py - KOReaders Lua-Dateien lesen (Teil von Bookbench).

  LuaReader / read_lua(pfad)   Tabellen aus settings.reader.lua, metadata.*.lua usw. als Python-Werte
  sidecar_for(buch)            Pfad der Buchdaten (.sdr) neben einem Buch

Früher auch ein Kommandozeilen-Skript, das markierte Kapitelnamen übernahm (bis Werkstatt 0.19
im Repo).
"""
import re

# ---------------------------------------------------------------- KOReaders Lua-Dateien lesen

class LuaReader:
    """Liest das Lua-Tabellenformat, in dem KOReader metadata.epub.lua speichert."""

    def __init__(self, src):
        self.s, self.i = src, 0

    def ws(self):
        while self.i < len(self.s):
            if self.s.startswith("--", self.i):
                j = self.s.find("\n", self.i)
                self.i = len(self.s) if j < 0 else j + 1
            elif self.s[self.i].isspace():
                self.i += 1
            else:
                break

    def value(self):
        self.ws()
        c = self.s[self.i]
        if c == "{":
            return self.table()
        if c in "\"'":
            return self.string()
        for word, val in (("true", True), ("false", False), ("nil", None)):
            if self.s.startswith(word, self.i):
                self.i += len(word)
                return val
        m = re.compile(r"-?(0x[0-9a-fA-F]+|\d+\.?\d*(e[-+]?\d+)?|\.\d+)").match(self.s, self.i)
        if not m:
            raise ValueError(f"Unerwartetes Zeichen bei {self.i}: {self.s[self.i:self.i + 20]!r}")
        self.i = m.end()
        t = m.group()
        return int(t, 16) if "0x" in t else (float(t) if any(x in t for x in ".e") else int(t))

    def string(self):
        # Lua schreibt Umlaute teils als Byte-Escapes ("\195\182" = ö) -> erst Bytes sammeln
        q = self.s[self.i]
        self.i += 1
        out = bytearray()
        while True:
            c = self.s[self.i]
            if c == q:
                self.i += 1
                return out.decode("utf-8", "replace")
            if c == "\\":
                n = self.s[self.i + 1]
                if n.isdigit():
                    m = re.compile(r"\d{1,3}").match(self.s, self.i + 1)
                    out.append(int(m.group()) & 0xFF)
                    self.i = m.end()
                    continue
                out += {"n": "\n", "t": "\t", "r": "\r", "\n": "\n"}.get(n, n).encode("utf-8")
                self.i += 2
                continue
            out += c.encode("utf-8")
            self.i += 1

    def table(self):
        self.i += 1
        arr, dic = [], {}
        while True:
            self.ws()
            if self.s[self.i] == "}":
                self.i += 1
                break
            if self.s[self.i] == "[":
                self.i += 1
                key = self.value()
                self.ws()
                self.i += 1                              # ]
                self.ws()
                self.i += 1                              # =
                dic[key] = self.value()
            else:
                m = re.compile(r"([A-Za-z_]\w*)\s*=").match(self.s, self.i)
                if m:
                    self.i = m.end()
                    dic[m.group(1)] = self.value()
                else:
                    arr.append(self.value())
            self.ws()
            if self.i < len(self.s) and self.s[self.i] in ",;":
                self.i += 1
        if arr and not dic:
            return arr
        for n, v in enumerate(arr, 1):
            dic[n] = v
        return dic


def read_lua(path):
    src = path.read_text(encoding="utf-8", errors="replace")
    src = src[src.index("return") + 6:] if "return" in src else src
    return LuaReader(src).value()


def sidecar_for(book):
    # KOReader: "Buch.kepub.epub" -> "Buch.kepub.sdr/metadata.epub.lua"
    stem, __, ext = book.name.rpartition(".")
    return book.parent / f"{stem}.sdr" / f"metadata.{ext}.lua"


# ---------------------------------------------------------------- Markierung -> Verzeichniseintrag
