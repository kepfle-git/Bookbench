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
  metadaten(b, e), bibliothek(b, e)   Marken des Bereichs Metadaten bzw. der Bibliothek (seit 2.0-beta2),
                   dazu klappentext_*, cover_*, meta_* (Stand eines Buchs ohne Oberfläche)
"""
from bookbench.i18n import N_, _, ngettext

ORDNUNG = ("unlesbar", "kapitel", "vorschlag", "klappentext", "cover", "cover_klein", "calibre", "angaben",
           "woerterbuch", "ereader", "konflikt", "abgleich", "ungespeichert", "verbunden")
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
    "konflikt": ("pruefen", (N_("{n} book changed on the computer and on the e-reader"),
                             N_("{n} books changed on the computer and on the e-reader"))),
    "abgleich": ("info", (N_("{n} book to sync between computer and e-reader"),
                          N_("{n} books to sync between computer and e-reader"))),
    "ungespeichert": ("offen", (N_("{n} book with unsaved changes"), N_("{n} books with unsaved changes"))),
    "verbunden": ("info", (N_("connected"), N_("connected"))),
}
# Orte, an denen Marken stehen (Einstellungen > Oberfläche > Status-Piktogramme)
ORTE = (("seitenleiste", N_("Sidebar")), ("listen", N_("Book lists")), ("tabelle", N_("Library")))
NUR_SEITENLEISTE = {"woerterbuch", "ereader", "verbunden", "abgleich", "konflikt"}      # gibt es nur in der Seitenleiste
NAMEN = {
    "unlesbar": N_("Book cannot be read"), "kapitel": N_("Questionable chapter names"),
    "vorschlag": N_("Chapter suggestions"), "klappentext": N_("No blurb"), "cover": N_("No cover"),
    "cover_klein": N_("Small cover"), "calibre": N_("Differs from Calibre"),
    "angaben": N_("Language or ISBN missing/invalid"), "woerterbuch": N_("Words without result"),
    "ereader": N_("Dictionaries on the e-reader"), "ungespeichert": N_("Unsaved changes"),
    "verbunden": N_("E-reader connected"), "abgleich": N_("Books to sync with the e-reader"),
    "konflikt": N_("Changed on both sides (sync)"),
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


# ---------------------------------------------------------------- Metadaten, Klappentext, Cover (ohne Oberfläche)
# Seit 2.0-beta2 hier, damit Bibliothek und Seitenleiste sie ohne den Bereich Metadaten kennen; die
# Bereiche nehmen dieselben Funktionen (Tk-Fassung: area_metadata/area_blurbs/area_covers).

def klappentext_aktuell(b):
    if b.klappentext_entwurf is not None:
        return b.klappentext_entwurf
    return b.klappentext_neu if b.klappentext_neu is not None else b.klappentext


def klappentext_fehlt(b, e):
    """Warntext, wenn das Buch (nach dem aktuellen Stand) keinen Klappentext hat, sonst None."""
    if b.fehler or (klappentext_aktuell(b) or "").strip():
        return None
    if b.calibre and e.get("calibre_an", True) and (b.calibre.get("comments") or "").strip():
        return _("no blurb (Calibre has one: From Calibre)")
    return _("no blurb")


def cover_info(b):
    from bookbench.core import covers as kc
    return kc.bild_info(b.cover_neu) if b.cover_neu is not None else b.cover_info


def cover_hoehe(b):
    """Höhe des Covers in px (das neue, falls es eins gibt), 0 ohne Cover - zum Sortieren."""
    info = cover_info(b)
    return (info[1] or 0) if info else 0


def cover_fehlt(b):
    return not b.fehler and b.cover_neu is None and not b.cover_info


def cover_klein(b, e):
    grenze = int(e.get("cover_klein") or 0)
    info = cover_info(b)
    return bool(grenze and info and info[1] and info[1] < grenze)


def cover_warnung(b, e):
    if b.fehler:
        return None
    if cover_fehlt(b):
        return _("no cover")
    if cover_klein(b, e):
        info = cover_info(b)
        return _("small cover ({w} × {h} px)").format(w=info[0], h=info[1])
    return None


def meta_eigene(e):
    """[(Suchname, Bezeichnung)] der eigenen Felder aus den Einstellungen."""
    erg = []
    for x in e.get("meta_spalten") or []:
        if isinstance(x, (list, tuple)) and x and str(x[0]).startswith("#"):
            erg.append((str(x[0]), str(x[1]) if len(x) > 1 and x[1] else str(x[0])))
    return erg


def meta_felder(e):
    from bookbench.core import metadata as kme
    feste = [f for f in kme.FELDER if f != "datum" or e.get("meta_datum", True)]
    return feste + [s for s, __ in meta_eigene(e)]


def meta_name(feld, e):
    from bookbench.core import metadata as kme
    return _(kme.NAMEN[feld]) if feld in kme.NAMEN else dict(meta_eigene(e)).get(feld, feld)


def meta_basis(b):
    """Übernommener Stand (Datei, darüber meta_neu und reihe_neu)."""
    w = dict(b.meta)
    if b.meta_neu:
        w.update(b.meta_neu)
    if b.reihe_neu is not None:
        w["reihe"], w["nummer"] = b.reihe_neu
    return w


def meta_aktuell(b):
    return dict(b.meta_entwurf) if b.meta_entwurf is not None else meta_basis(b)


def meta_calibre(b, e):
    from bookbench.core import metadata as kme
    return kme.calibre_werte(b.calibre) if b.calibre and e.get("calibre_an", True) else {}


def meta_abweichend(b, e, felder=None):
    from bookbench.core import metadata as kme
    cal = meta_calibre(b, e)
    return kme.unterschiede(meta_aktuell(b), cal, felder or meta_felder(e)) if cal else []


def metadaten(b, e):
    """Marken des Bereichs Metadaten: Klappentext, Cover, Abweichung von Calibre, Angaben."""
    from bookbench.core import metadata as kme
    if b.fehler:
        return [("unlesbar", b.fehler)]
    erg = []
    kt = klappentext_fehlt(b, e)
    if kt:
        erg.append(("klappentext", kt))
    c = cover_warnung(b, e)
    if c:
        erg.append(("cover" if cover_fehlt(b) else "cover_klein", c))
    wichtig = meta_abweichend(b, e, kme.WICHTIG)
    if wichtig:
        erg.append(("calibre", _("differs from Calibre: {felder}").format(
            felder=", ".join(meta_name(f, e) for f in wichtig))))
    w = meta_aktuell(b)
    angaben = []
    if w.get("isbn") and not kme.isbn_ok(w["isbn"]):
        angaben.append(_("ISBN not valid"))
    if not w.get("sprache"):
        angaben.append(_("no language"))
    if angaben:
        erg.append(("angaben", ", ".join(angaben)))
    return erg


def bibliothek(b, e):
    """Marken in der Bibliothek: alles, was die Bereiche melden (Kapitel ohne Vorschläge, Metadaten)."""
    if b.fehler:
        return [("unlesbar", b.fehler)]
    return [m for m in kapitel(b) if m[0] != "vorschlag"] + metadaten(b, e)
