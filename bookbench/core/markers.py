# -*- coding: utf-8 -*-
"""
markers.py - Marken (kleine Piktogramme je Buch und Bereich statt ⚠, seit 1.3-beta3): Arten, Orte,
Texte und welche Marken ein Buch hat - ohne Oberfläche. Zeichnen: ui/markers.py.

  ORDNUNG, ARTEN   Kennungen in Anzeigereihenfolge; {kennung: (Stufe, (Einzahl, Mehrzahl))}
                   Stufen: fehler (rot), pruefen (orange), fehlt (grau), info (Akzent), offen (gelb)
  ORTE, NAMEN      Orte (Seitenleiste, Bücherlisten, Bibliothek) und Namen für die Einstellungen
  sichtbar(e, ort, kennung), gefiltert(e, ort, marken)   Einstellung marken_aus
  text(kennung, anzahl), sortiert(marken)
  kapitel(b)       Marken eines Buchs im Bereich Kapitel (auch Seitenleiste)
  zaehlen(buecher, marken_fn)   [(kennung, anzahl)] für die Seitenleiste
"""
from bookbench.i18n import N_, _, ngettext

ORDNUNG = ("unlesbar", "kapitel", "vorschlag", "klappentext", "cover", "cover_klein", "calibre", "angaben",
           "woerterbuch", "ereader", "ungespeichert", "verbunden")
# Stufe, (Einzahl, Mehrzahl) für die Seitenleiste
ARTEN = {
    "unlesbar": ("fehler", (N_("{n} book cannot be read"), N_("{n} books cannot be read"))),
    "kapitel": ("pruefen", (N_("{n} book with questionable chapter names"), N_("{n} books with questionable chapter names"))),
    "vorschlag": ("info", (N_("{n} book with chapter suggestions"), N_("{n} books with chapter suggestions"))),
    "klappentext": ("fehlt", (N_("{n} book without blurb"), N_("{n} books without blurb"))),
    "cover": ("fehlt", (N_("{n} book without cover"), N_("{n} books without cover"))),
    "cover_klein": ("pruefen", (N_("{n} small cover"), N_("{n} small covers"))),
    "calibre": ("pruefen", (N_("{n} book differs from Calibre"), N_("{n} books differ from Calibre"))),
    "angaben": ("pruefen", (N_("{n} book with missing or invalid data (language, ISBN)"),
                            N_("{n} books with missing or invalid data (language, ISBN)"))),
    "woerterbuch": ("pruefen", (N_("{n} word looked up without result"), N_("{n} words looked up without result"))),
    "ereader": ("pruefen", (N_("{n} dictionary missing or outdated on the e-reader"),
                            N_("{n} dictionaries missing or outdated on the e-reader"))),
    "ungespeichert": ("offen", (N_("{n} book with unsaved changes"), N_("{n} books with unsaved changes"))),
    "verbunden": ("info", (N_("connected"), N_("connected"))),
}
# Orte, an denen Marken stehen (Einstellungen > Oberfläche > Status-Piktogramme)
ORTE = (("seitenleiste", N_("Sidebar")), ("listen", N_("Book lists")), ("tabelle", N_("Library")))
NUR_SEITENLEISTE = {"woerterbuch", "ereader", "verbunden"}      # gibt es nur in der Seitenleiste
NAMEN = {
    "unlesbar": N_("Book cannot be read"), "kapitel": N_("Questionable chapter names"),
    "vorschlag": N_("Chapter suggestions"), "klappentext": N_("No blurb"), "cover": N_("No cover"),
    "cover_klein": N_("Small cover"), "calibre": N_("Differs from Calibre"),
    "angaben": N_("Language or ISBN missing/invalid"), "woerterbuch": N_("Words without result"),
    "ereader": N_("Dictionaries on the e-reader"), "ungespeichert": N_("Unsaved changes"),
    "verbunden": N_("E-reader connected"),
}


def sichtbar(e, ort, kennung):
    """False, wenn die Marke an diesem Ort abgeschaltet ist (Einstellung marken_aus)."""
    aus = (e or {}).get("marken_aus") or {}
    return kennung not in (aus.get(ort) or [])


def gefiltert(e, ort, marken):
    """[(kennung, text)] ohne die an diesem Ort abgeschalteten Marken."""
    return [m for m in marken if sichtbar(e, ort, m[0])]


def text(kennung, anzahl):
    """Tooltip-Text einer Marke mit Anzahl."""
    ein, mehr = ARTEN[kennung][1]
    return _(ein if anzahl == 1 else mehr).format(n=anzahl)       # Deutsch und Englisch: 1 / sonst


def sortiert(marken):
    return sorted(marken, key=lambda m: ORDNUNG.index(m[0]) if m[0] in ORDNUNG else 99)


def kapitel(b):
    """Marken für Kapitel-Liste und Seitenleiste: unlesbar, fragwürdige Namen, Vorschläge offen."""
    if b.fehler:
        return [("unlesbar", b.fehler)]
    erg = []
    w = b.warnung()
    if w:
        erg.append(("kapitel", w))
    if b.vorschlag and not b.neu and b.entwurf is None:
        erg.append(("vorschlag", ngettext("{n} chapter suggestion", "{n} chapter suggestions",
                                          len(b.vorschlag)).format(n=len(b.vorschlag))))
    return erg


def zaehlen(buecher, marken_fn):
    """[(kennung, anzahl)] über alle Bücher, in Anzeigereihenfolge."""
    erg = {}
    for b in buecher:
        for k, __ in marken_fn(b):
            erg[k] = erg.get(k, 0) + 1
    return sortiert(list(erg.items()))
