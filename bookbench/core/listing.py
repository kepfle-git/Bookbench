# -*- coding: utf-8 -*-
"""
listing.py - Bücher für Listen und Tabellen aufbereiten (ohne Oberfläche, seit 2.0-beta2 aus der
Tk-Fassung gelöst: app.py, list_filter.py).

  nr(text)                 Reihennummer als Zahl zum Sortieren (1.5, "" = ganz hinten)
  anzeigename(b)           Name in den Listen (gleiche Titel mit Dateinamen unterschieden)
  links_sortiert(buecher)  wie die schmalen Listen links: Reihe, Nummer, Titel (wie im Bookshelf)
  such_passt(b, such)      Suchtext (casefold) in Titel, Reihe oder Autor
  nachfolger(sortiert, vorher, passt)   welches Buch nach dem Filtern gewählt sein soll
  SPALTEN, SPALTEN_AUS     Spalten der Bibliothek (Kennung, Text N_, Standardbreite) und standardmäßig aus
  FILTER                   Filter der Bibliothek (Kennung, Text N_, Prüfung)
  zelle(b, spalte)         Text einer Zelle der Bibliothek
  sortiert(buecher, spalte, umgekehrt, e)   Reihenfolge der Bibliothek
  kapitel_filter()         Filter der Kapitel-Liste
"""
from bookbench.core import blurbs
from bookbench.core import markers as km
from bookbench.i18n import N_, _


def nr(s):
    try:
        return float(str(s).replace(",", "."))
    except (TypeError, ValueError):
        return 1e9


def anzeigename(b):
    return getattr(b, "titel_anzeige", None) or b.name


def links_sortiert(buecher):
    return sorted(buecher, key=lambda b: (b.reihe.casefold() or "￿", nr(b.nummer), b.titel.casefold()))


def such_passt(b, such):
    return not such or such in " ".join((b.titel or "", b.reihe or "", b.autor or "")).casefold()


def nachfolger(sortiert, vorher, passt):
    """Buch, das nach dem Filtern gewählt sein soll: das bisherige, wenn es noch passt, sonst
    das nächste passende darunter, sonst das nächste darüber."""
    if vorher is None:
        return None
    if passt(vorher):
        return vorher
    schl = [b.schluessel for b in sortiert]
    if vorher.schluessel not in schl:
        return None
    i = schl.index(vorher.schluessel)
    for b in sortiert[i + 1:]:
        if passt(b):
            return b
    for b in reversed(sortiert[:i]):
        if passt(b):
            return b
    return None


# ---------------------------------------------------------------- Bibliothek
SPALTEN = (("titel", N_("Title"), 300), ("reihe", N_("Series"), 200), ("nummer", N_("No."), 46),
           ("autor", N_("Author"), 150), ("kapitel", N_("Chapters"), 150), ("klappentext", N_("Blurb"), 100),
           ("cover", N_("Cover"), 90), ("verlag", N_("Publisher"), 140), ("sprache", N_("Language"), 70),
           ("isbn", "ISBN", 120), ("datum", N_("Published"), 90),
           ("gelesen", N_("Read status"), 90), ("zuletzt", N_("Last read"), 90), ("lesezeit", N_("Reading time"), 90))
# seit 1.3: standardmäßig ausgeblendet (datum seit 2.3-beta1, Lesestand seit 2.3-beta3: gelesen sichtbar)
SPALTEN_AUS = ("verlag", "sprache", "isbn", "datum", "zuletzt", "lesezeit")
FILTER = (("alle", N_("All books"), None),
          ("geaendert", N_("Changed"), lambda b: b.stand() is not None),
          ("unlesbar", N_("Unreadable files"), lambda b: bool(b.fehler)),
          ("ohne_reihe", N_("No series in the EPUB"), lambda b: not b.reihe_datei[0] and b.reihe_neu is None),
          # Lesestand aus KOReader (seit 2.3-beta3); ohne bekannten Stand (lesen None) passt keiner
          ("ungelesen", N_("Unread"), lambda b: getattr(b, "lesen", None) is not None and not b.lesen.get("status")),
          ("lese", N_("Currently reading"), lambda b: (getattr(b, "lesen", None) or {}).get("status") == "reading"),
          ("gelesen", N_("Finished"), lambda b: (getattr(b, "lesen", None) or {}).get("status") == "complete"),
          ("pausiert", N_("On hold"), lambda b: (getattr(b, "lesen", None) or {}).get("status") == "abandoned"))


def zelle(b, spalte):
    if spalte == "kapitel":
        return b.fehler or b.kapitel_zustand()
    if spalte == "klappentext":
        if b.klappentext_neu is not None or b.klappentext_entwurf is not None:
            return _("changed")
        if b.klappentext:
            return blurbs.source_name(b.klappentext_quelle_datei) or _("yes")
        return _("in Calibre") if b.calibre and b.calibre.get("comments") else "-"
    if spalte == "cover":
        if b.cover_neu is not None:
            return _("changed")
        return f"{b.cover_info[0]} × {b.cover_info[1]}" if b.cover_info else "-"
    if spalte == "datum":
        return km.meta_aktuell(b).get("datum", "") if not b.fehler else ""
    if spalte in ("gelesen", "zuletzt", "lesezeit"):
        from bookbench.core import reading
        e = getattr(b, "lesen", None)
        if spalte == "gelesen":
            return reading.status_text(e)
        if spalte == "zuletzt":
            return reading.datum_text((e or {}).get("zuletzt")) if (e or {}).get("status") else ""
        return reading.zeit_text((e or {}).get("zeit"))
    return getattr(b, spalte, "") or ""


def sortiert(buecher, spalte, umgekehrt, e):
    if spalte == "reihe":
        schl = lambda b: (b.reihe.casefold() or "￿", nr(b.nummer), b.titel.casefold())    # noqa: E731
    elif spalte == "nummer":
        schl = lambda b: (nr(b.nummer), b.titel.casefold())                                     # noqa: E731
    elif spalte == "cover":
        schl = lambda b: (km.cover_hoehe(b), b.titel.casefold())                               # noqa: E731
    elif spalte in ("gelesen", "zuletzt", "lesezeit"):
        from bookbench.core import reading

        def schl(b):
            e = getattr(b, "lesen", None) or {}
            wert = {"gelesen": reading.sortierwert(getattr(b, "lesen", None)),
                    "zuletzt": e.get("zuletzt", 0) if e.get("status") else 0, "lesezeit": e.get("zeit", 0)}[spalte]
            return (wert, b.titel.casefold())
    elif spalte == "status":
        # unlesbar zuerst, dann nach Zahl der Marken, dann Ungespeichertes
        schl = lambda b: (not b.fehler, -len(km.bibliothek(b, e)), b.stand() is None, b.titel.casefold())  # noqa: E731
    else:
        schl = lambda b: (str(zelle(b, spalte)).casefold(), b.titel.casefold())                # noqa: E731
    return sorted(buecher, key=schl, reverse=umgekehrt)


# ---------------------------------------------------------------- Kapitel
def kapitel_filter():
    return [("alle", N_("All books"), None),
            ("vorschlaege", N_("With suggestions"), lambda b: bool(b.vorschlag)),
            ("fragwuerdig", N_("Questionable names"), lambda b: bool(b.warnung())),
            ("ohne_namen", N_("Some without names"), lambda b: b.einzelne_ohne_namen()),
            ("geaendert", N_("Changed chapters"), lambda b: bool(
                b.neu or b.entwurf is not None or b.tiefen_neu is not None or b.tiefen_entwurf is not None))]
