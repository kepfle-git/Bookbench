# -*- coding: utf-8 -*-
"""
markdown_view.py - Markdown (wie in GitHub-Releases) in ein tk.Text schreiben, statt den
Quelltext zu zeigen. Für die Änderungen im Update-Fenster (ui/updates.py).

  darstellen(text, md, akzent=None, oeffnen=None)
      schreibt md ab dem Ende in das Text-Widget (das selbst bleibt beschreibbar/gesperrt wie es ist)

Kann: Überschriften (# bis ######), Absätze, harte Zeilenumbrüche wie bei GitHub-Releases,
**fett** / __fett__, *kursiv* / _kursiv_, ***beides***, ~~durchgestrichen~~, `Code`,
Codeblöcke (``` oder ~~~), Aufzählungen (-, *, +) und nummerierte Listen auch verschachtelt
(je 2 Leerzeichen eine Ebene), Aufgabenlisten ([ ] / [x]), Zitate (>), Trennlinien (---),
Links [Text](URL), <URL> und nackte https://-Adressen (anklickbar), \\-Maskierung,
HTML-Kommentare und <br> werden ausgelassen bzw. umgebrochen. Tabellen bleiben als Text.

Alles Unbekannte bleibt als Text stehen - im schlimmsten Fall sieht man Quelltext, wie bisher.
"""
import re
import tkinter as tk
import tkinter.font as tkfont
import webbrowser

GROESSE = 10
H_GROESSE = {1: 15, 2: 13, 3: 12, 4: 11, 5: 10, 6: 10}
EINZUG = 18                     # px je Listenebene

# Inline-Elemente; Reihenfolge = Vorrang (Code vor allem anderen, damit **x** in `…` stehen bleibt)
_INLINE = re.compile(
    r"(?P<esc>\\[\\`*_{}\[\]()#+\-.!~>|])"
    r"|(?P<code>`+)(?P<code_t>.+?)(?P=code)"
    r"|!?\[(?P<link_t>[^\]]*)\]\((?P<link_u>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
    r"|<(?P<auto>https?://[^>\s]+)>"
    r"|(?P<fk>\*\*\*|___)(?P<fk_t>.+?)(?P=fk)"
    r"|(?P<f>\*\*|__)(?P<f_t>.+?)(?P=f)"
    r"|(?P<s>~~)(?P<s_t>.+?)~~"
    r"|(?<![\w*])\*(?P<k_t>[^*\s](?:[^*]*[^*\s])?)\*(?!\*)"
    r"|(?<![\w_])_(?P<k2_t>[^_\s](?:[^_]*[^_\s])?)_(?![\w_])"
    r"|(?P<url>https?://[^\s<>()]+[^\s<>().,;:!?'\"])"
    r"|(?P<br><br\s*/?>)", re.I)

_LISTE = re.compile(r"^(?P<einzug>[ \t]*)(?P<marke>[-*+]|\d{1,9}[.)])[ \t]+(?P<rest>.*)$")
_AUFGABE = re.compile(r"^\[(?P<x>[ xX])\][ \t]+")
_UEBERSCHRIFT = re.compile(r"^(?P<h>#{1,6})[ \t]+(?P<t>.*?)[ \t]*#*[ \t]*$")
_LINIE = re.compile(r"^[ \t]*([-*_])([ \t]*\1){2,}[ \t]*$")
_ZAUN = re.compile(r"^[ \t]*(```|~~~)")


class _Schreiber:
    def __init__(self, text, akzent, oeffnen):
        self.t, self.akzent, self.oeffnen = text, akzent, oeffnen
        self.links = 0
        basis = tkfont.nametofont("TkDefaultFont").actual()
        self.familie = basis["family"]
        self.mono = tkfont.nametofont("TkFixedFont").actual()["family"]
        t = text
        for n, g in H_GROESSE.items():
            t.tag_configure(f"md_h{n}", font=(self.familie, g, "bold"), spacing1=6 if n > 1 else 2, spacing3=4)
        t.tag_configure("md_absatz", spacing3=6)
        t.tag_configure("md_codeblock", font=(self.mono, GROESSE - 1), lmargin1=12, lmargin2=12,
                        spacing1=1, spacing3=1)
        t.tag_configure("md_zitat", lmargin1=14, lmargin2=14, foreground="#777777")
        t.tag_configure("md_linie", foreground="#999999", spacing1=4, spacing3=4)
        t.tag_configure("md_link", underline=True, foreground=akzent or "#0a64d6")
        t.tag_bind("md_link", "<Enter>", lambda e: t.configure(cursor="hand2"))
        t.tag_bind("md_link", "<Leave>", lambda e: t.configure(cursor=""))
        self._stile = set()
        self.groesse = GROESSE                  # Überschriften setzen sie kurz höher

    # -------------------------------------------------------------- Inline
    def _stil(self, fett=False, kursiv=False, code=False, durch=False):
        name = f"md_s{self.groesse}" + "".join(k for k, an in (("f", fett), ("k", kursiv), ("c", code),
                                                                ("d", durch)) if an)
        if name not in self._stile:
            self._stile.add(name)
            font = (self.mono if code else self.familie, self.groesse - (1 if code else 0),
                    " ".join(x for x, an in (("bold", fett), ("italic", kursiv)) if an) or "normal")
            self.t.tag_configure(name, font=font, overstrike=durch)
            self.t.tag_raise(name)
        return name

    def _link(self, url):
        self.links += 1
        name = f"md_link{self.links}"
        self.t.tag_bind(name, "<Button-1>", lambda e, u=url: self.oeffnen(u))
        return name

    def inline(self, s, tags=(), fett=False, kursiv=False, durch=False):
        pos = 0
        for m in _INLINE.finditer(s):
            if m.start() > pos:
                self._raus(s[pos:m.start()], tags, fett, kursiv, durch)
            pos = m.end()
            g = m.groupdict()
            if g["esc"]:
                self._raus(g["esc"][1], tags, fett, kursiv, durch)
            elif g["code"]:
                self.t.insert("end", g["code_t"].strip() if g["code_t"].strip() else g["code_t"],
                              tags + (self._stil(fett, kursiv, True, durch),))
            elif g["link_u"] is not None:
                url = g["link_u"]
                extra = ("md_link", self._link(url)) if re.match(r"(https?://|mailto:)", url, re.I) else ()
                self.inline(g["link_t"] or url, tags + extra, fett, kursiv, durch)
            elif g["auto"] or g["url"]:
                url = g["auto"] or g["url"]
                self._raus(url, tags + ("md_link", self._link(url)), fett, kursiv, durch)
            elif g["fk"]:
                self.inline(g["fk_t"], tags, True, True, durch)
            elif g["f"]:
                self.inline(g["f_t"], tags, True, kursiv, durch)
            elif g["s"]:
                self.inline(g["s_t"], tags, fett, kursiv, True)
            elif g["k_t"] is not None or g["k2_t"] is not None:
                self.inline(g["k_t"] if g["k_t"] is not None else g["k2_t"], tags, fett, True, durch)
            elif g["br"]:
                self.t.insert("end", "\n", tags)
        if pos < len(s):
            self._raus(s[pos:], tags, fett, kursiv, durch)

    def _raus(self, s, tags, fett, kursiv, durch):
        if s:
            self.t.insert("end", s, tags + (self._stil(fett, kursiv, False, durch),))

    # -------------------------------------------------------------- Blöcke
    def _liste_tag(self, ebene):
        name = f"md_li{ebene}"
        links = 6 + EINZUG * ebene
        self.t.tag_configure(name, lmargin1=links, lmargin2=links + 14, spacing1=1, spacing3=1)
        return name

    def schreiben(self, md):
        md = re.sub(r"<!--.*?-->", "", md.replace("\r\n", "\n").replace("\r", "\n"), flags=re.S)
        zeilen = md.split("\n")
        i, leer_davor = 0, True
        while i < len(zeilen):
            z = zeilen[i]
            zaun = _ZAUN.match(z)
            if zaun:                                        # Codeblock bis zum schließenden Zaun
                block = []
                i += 1
                while i < len(zeilen) and not zeilen[i].strip().startswith(zaun.group(1)):
                    block.append(zeilen[i])
                    i += 1
                self.t.insert("end", "\n".join(block) + "\n", ("md_codeblock",))
                i += 1
                leer_davor = False
                continue
            if not z.strip():
                if not leer_davor:
                    self.t.insert("end", "\n", ("md_absatz",))
                leer_davor = True
                i += 1
                continue
            leer_davor = False
            h = _UEBERSCHRIFT.match(z)
            li = _LISTE.match(z)
            if h:
                n = len(h.group("h"))
                self.groesse = H_GROESSE[n]
                self.inline(h.group("t"), (f"md_h{n}",), fett=True)
                self.groesse = GROESSE
                self.t.insert("end", "\n", (f"md_h{n}",))
                leer_davor = True                         # Abstand hat die Überschrift schon
            elif _LINIE.match(z) and not li:
                self.t.insert("end", "─" * 40 + "\n", ("md_linie",))
            elif li:
                einzug = li.group("einzug").replace("\t", "    ")
                ebene = min(len(einzug) // 2, 6)
                marke = li.group("marke")
                rest = li.group("rest")
                aufgabe = _AUFGABE.match(rest)
                if aufgabe:
                    zeichen = "☑" if aufgabe.group("x").lower() == "x" else "☐"
                    rest = rest[aufgabe.end():]
                elif marke[0].isdigit():
                    zeichen = marke[:-1] + "."
                else:
                    zeichen = "•◦▪"[ebene % 3]
                tag = self._liste_tag(ebene)
                self.t.insert("end", zeichen + " ", (tag,))
                self.inline(rest, (tag,))
                # eingerückte Folgezeilen gehören zum Punkt
                while (i + 1 < len(zeilen) and zeilen[i + 1].strip() and zeilen[i + 1][:1] in " \t"
                       and not _LISTE.match(zeilen[i + 1])):
                    i += 1
                    self.t.insert("end", "\n", (tag,))
                    self.inline(zeilen[i].strip(), (tag,))
                self.t.insert("end", "\n", (tag,))
            elif z.lstrip().startswith(">"):
                self.inline(re.sub(r"^\s*>+\s?", "", z), ("md_zitat",))
                self.t.insert("end", "\n", ("md_zitat",))
            else:
                self.inline(z.strip())
                self.t.insert("end", "\n")
            i += 1
        # Leerzeilen am Ende weg
        while self.t.get("end-2c", "end-1c") == "\n" and self.t.compare("end-2c", ">", "1.0"):
            self.t.delete("end-2c", "end-1c")


def darstellen(text, md, akzent=None, oeffnen=None):
    """Markdown md am Ende des tk.Text text einfügen (formatiert, Links anklickbar).
    oeffnen(url) für Links, Standard: im Browser (zur Laufzeit nachgeschlagen)."""
    _Schreiber(text, akzent, oeffnen or (lambda u: webbrowser.open(u))).schreiben(md or "")


if __name__ == "__main__":                              # zum Ausprobieren: python -m bookbench.ui.markdown_view
    root = tk.Tk()
    t = tk.Text(root, wrap="word", width=90, height=40, padx=8, pady=6)
    t.pack(fill="both", expand=True)
    darstellen(t, open(__import__("sys").argv[1], encoding="utf-8").read())
    root.mainloop()
