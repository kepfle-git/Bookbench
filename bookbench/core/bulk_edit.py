# -*- coding: utf-8 -*-
"""
bulk_edit.py - Massenbearbeitung der Metadaten (seit 2.3-beta1), Logik ohne Oberfläche.
Die Oberfläche (ui/area_metadata.py, ui/bulk_edit.py) baut damit je Buch alte und neue Werte und
übernimmt sie nach der Vorschau wie ein Formular (gelb, gespeichert wird mit Strg+S samt Sicherung).

  gemeinsam(werte_liste, feld)              gemeinsamer Wert aller Bücher oder None (verschieden)
  anwenden(alt, text, modus, trenner)       neuer Wert: modus "ersetzen", "dazu" oder "weg" (nur Mehrfachfelder)
  nummern(anzahl, start, schritt)           ["1", "2", …] (Kommazahlen ohne ".0")
  ersetzen(text, suche, ersatz, regex, gross)   (neu, Zahl der Treffer); re.error bei falschem Muster
  muster_fehler(suche, regex)               Fehlertext eines regulären Ausdrucks oder ""
  aenderungen(plan, felder)                 [(buch, [(feld, alt, neu)])] nur, wo sich etwas ändert
"""
import re

from bookbench.core import metadata as kme

MODI = ("ersetzen", "dazu", "weg")


def gemeinsam(werte_liste, feld):
    """Wert, den alle Bücher in feld haben (verglichen wie im Formular, mit kme.gleich), sonst None."""
    erster = None
    for i, w in enumerate(werte_liste):
        wert = kme._norm(w.get(feld, ""))
        if i == 0:
            erster = wert
        elif not (wert == erster or (wert and erster and kme.gleich(feld, wert, erster))):
            return None
    return erster


def _teile(text, trenner):
    return [t.strip() for t in kme.liste(text or "", trenner) if t.strip()]


def _verbinden(teile, trenner):
    return (" & " if trenner == "&" else ", ").join(teile)


def anwenden(alt, text, modus="ersetzen", trenner=None):
    """Neuer Wert eines Felds. Ersetzen nimmt text; bei Mehrfachfeldern (trenner "&" oder ",") hängt
    "dazu" die Teile aus text an (ohne Doppelte, Groß/klein egal), "weg" entfernt sie."""
    if modus == "ersetzen" or not trenner:
        return kme._norm(text)
    alt_t, neu_t = _teile(alt, trenner), _teile(text, trenner)
    if modus == "dazu":
        erg, gesehen = [], set()
        for t in alt_t + neu_t:
            if t.casefold() not in gesehen:
                gesehen.add(t.casefold())
                erg.append(t)
        return _verbinden(erg, trenner)
    weg = {t.casefold() for t in neu_t}
    return _verbinden([t for t in alt_t if t.casefold() not in weg], trenner)


def nummer_text(x):
    t = f"{x:.2f}".rstrip("0").rstrip(".")
    return "0" if t in ("", "-0") else t


def nummern(anzahl, start=1.0, schritt=1.0):
    return [nummer_text(start + i * schritt) for i in range(anzahl)]


def muster_fehler(suche, regex):
    if not regex or not suche:
        return ""
    try:
        re.compile(suche)
    except re.error as e:
        return str(e)
    return ""


def ersetzen(text, suche, ersatz, regex=False, gross=False):
    """(neuer Text, Zahl der Ersetzungen). Ohne regex wird suche wörtlich genommen und ersatz auch
    (kein \\1); mit regex gelten Gruppen wie \\1 im Ersatz."""
    if not suche:
        return text, 0
    flags = 0 if gross else re.IGNORECASE
    if regex:
        return re.subn(suche, ersatz, text or "", flags=flags)
    return re.subn(re.escape(suche), lambda m: ersatz, text or "", flags=flags)


def aenderungen(plan, felder=None):
    """plan: [(buch, alt, neu)] mit {feld: text}. Gibt [(buch, [(feld, alt, neu)])] für die Bücher zurück, bei
    denen sich etwas ändert (verglichen wie beim Übernehmen: Leerraum zählt nicht)."""
    erg = []
    for b, alt, neu in plan:
        zeilen = []
        for f in (felder or [f for f in neu]):
            a, n = kme._norm(alt.get(f, "")), kme._norm(neu.get(f, ""))
            if a != n:
                zeilen.append((f, a, n))
        if zeilen:
            erg.append((b, zeilen))
    return erg
