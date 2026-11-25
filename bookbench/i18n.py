# -*- coding: utf-8 -*-
"""
i18n.py - Übersetzungen von Bookbench (gettext-Stil).

Die Texte im Code sind Englisch; andere Sprachen kommen aus locale/<code>.po (dieselben
Dateien, die Poedit & Co. bearbeiten). Gelesen wird die .po direkt, eine .mo braucht es nicht.

  _(text)                   übersetzter Text (oder der englische, wenn es keine Übersetzung gibt)
  ngettext(ein, mehr, n)    Ein- oder Mehrzahl, übersetzt
  N_(text)                  markiert nur (für Listen, die erst später durch _() gehen)
  aktiv()                   Code der eingestellten Sprache ("en", "de")
  einstellen(code)          "auto", "en" oder "de"; gilt für alles, was danach _() aufruft

Die Sprache wird beim ersten Import festgelegt, also bevor andere Module ihre Konstanten
bauen: Umgebungsvariable BOOKBENCH_SPRACHE (für Tests; alt: KOBO_WERKSTATT_SPRACHE), sonst Schlüssel "sprache" in
der Einstellungsdatei, sonst "auto" (Systemsprache; Deutsch, wenn sie deutsch ist, sonst
Englisch). Ein Wechsel im laufenden Programm wirkt deshalb erst nach einem Neustart
vollständig; Bookbench startet sich dafür selbst neu (App.sprache_wechseln).
"""
import json
import locale
import os
import re
import sys
from pathlib import Path

ORDNER = Path(__file__).resolve().parent / "locale"
SPRACHEN = {"en": "English", "de": "Deutsch"}      # Name jeweils in der eigenen Sprache
UMGEBUNG = "BOOKBENCH_SPRACHE"
UMGEBUNG_ALT = "KOBO_WERKSTATT_SPRACHE"             # Name bis 0.24

_aktiv = "en"
_tabelle = {}                                       # msgid -> msgstr bzw. (msgid, plural) -> [formen]


# ================================================================ .po lesen
def _zeichenkette(roh):
    """Inhalt einer "…"-Zeile aus einer .po-Datei, mit C-Escapes."""
    roh = roh.strip()
    if not (roh.startswith('"') and roh.endswith('"')):
        raise ValueError(roh)
    s = roh[1:-1]
    return re.sub(r'\\(["\\ntr])', lambda m: {"n": "\n", "t": "\t", "r": "\r"}.get(m.group(1), m.group(1)), s)


def po_lesen(pfad):
    """Liste von Einträgen {msgid, msgid_plural, msgstr (str oder Liste), fuzzy, kommentare, orte}."""
    eintraege, e, feld = [], None, None

    def neu():
        return {"msgid": None, "msgid_plural": None, "msgstr": None, "fuzzy": False, "kommentare": [],
                "orte": [], "obsolet": False}

    def fertig():
        if e is not None and e["msgid"] is not None:
            eintraege.append(e)

    for zeile in Path(pfad).read_text(encoding="utf-8").splitlines():
        z = zeile.strip()
        if not z:
            fertig()
            e, feld = None, None
            continue
        if e is None:
            e = neu()
        if z.startswith("#~"):
            e["obsolet"] = True
            continue
        if z.startswith("#,"):
            e["fuzzy"] = e["fuzzy"] or "fuzzy" in z
            continue
        if z.startswith("#:"):
            e["orte"] += z[2:].split()
            continue
        if z.startswith("#"):
            e["kommentare"].append(zeile)
            continue
        m = re.match(r"(msgid_plural|msgid|msgstr\[(\d+)\]|msgstr|msgctxt)\s+(.*)", z)
        if m:
            schluessel, nr, rest = m.group(1), m.group(2), m.group(3)
            if nr is not None:
                if not isinstance(e["msgstr"], list):
                    e["msgstr"] = []
                e["msgstr"].append(_zeichenkette(rest))
                feld = ("msgstr", int(nr))
            else:
                e[schluessel] = _zeichenkette(rest)
                feld = (schluessel, None)
            continue
        if z.startswith('"') and feld:                # Fortsetzungszeile
            s, nr = feld
            if nr is None:
                e[s] += _zeichenkette(z)
            else:
                e["msgstr"][nr] += _zeichenkette(z)
    fertig()
    return [x for x in eintraege if not x["obsolet"]]


def tabelle_aus(eintraege):
    t = {}
    for e in eintraege:
        if not e["msgid"] or e["fuzzy"]:
            continue                                  # Kopf und unsichere Übersetzungen auslassen
        if e["msgid_plural"] is not None:
            formen = e["msgstr"] if isinstance(e["msgstr"], list) else []
            if formen and all(formen):
                t[(e["msgid"], e["msgid_plural"])] = formen
        elif e["msgstr"]:
            t[e["msgid"]] = e["msgstr"]
    return t


# ================================================================ Sprache wählen
def system_sprache():
    """Code der Systemsprache, soweit wir sie anbieten, sonst "en"."""
    kandidaten = [os.environ.get(v, "") for v in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")]
    if sys.platform.startswith("win"):
        try:
            import ctypes
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            kandidaten.insert(0, locale.windows_locale.get(lcid, ""))
        except Exception:
            pass
    try:
        kandidaten.append(locale.getlocale()[0] or "")
    except ValueError:
        pass
    for k in kandidaten:
        for teil in k.split(":"):
            code = teil.split("_")[0].split(".")[0].lower()
            if code in SPRACHEN:
                return code
            if code and code not in ("c", "posix"):
                return "en"                           # bewusst eine andere Sprache: Englisch
    return "en"


def einstellen(code):
    global _aktiv, _tabelle
    code = (code or "auto").lower()
    if code == "auto" or code not in SPRACHEN:
        code = system_sprache()
    _aktiv = code
    datei = ORDNER / f"{code}.po"
    _tabelle = tabelle_aus(po_lesen(datei)) if code != "en" and datei.exists() else {}
    return code


def aktiv():
    return _aktiv


def einstellungsordner():
    """Ordner für Einstellungen und Daten: Windows %APPDATA%\\Bookbench, sonst ~/.config/bookbench.
    Bis 0.24 hieß das Programm Kobo-Werkstatt; dessen Ordner wird beim ersten Mal kopiert (nicht
    verschoben - so bleibt eine ältere Fassung lauffähig)."""
    if sys.platform.startswith("win"):
        basis = Path(os.environ.get("APPDATA") or Path.home())
        neu, alt = basis / "Bookbench", basis / "Kobo-Werkstatt"
    else:
        basis = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        neu, alt = basis / "bookbench", basis / "kobo-werkstatt"
    if not neu.exists() and alt.is_dir():
        try:
            import shutil
            shutil.copytree(alt, neu)
        except OSError:
            pass
    return neu


def _einstellungsdatei():
    """Wie ui.settings.pfad(), ohne es zu importieren (das bräuchte tkinter)."""
    return einstellungsordner() / "einstellungen.json"


def gewuenscht():
    """Eingestellte Sprache ("auto", "en", "de"), ohne sie zu aktivieren."""
    for name in (UMGEBUNG, UMGEBUNG_ALT):
        if os.environ.get(name):
            return os.environ[name]
    try:
        return json.loads(_einstellungsdatei().read_text(encoding="utf-8")).get("sprache") or "auto"
    except (OSError, ValueError, AttributeError):
        return "auto"


# ================================================================ Übersetzen
def _(text):
    return _tabelle.get(text) or text


def ngettext(ein, mehr, n):
    formen = _tabelle.get((ein, mehr))
    if formen:
        return formen[0 if n == 1 else min(1, len(formen) - 1)]    # de/en: zwei Formen
    return ein if n == 1 else mehr


def N_(text):
    return text


def spaet(text, **werte):
    """Text, der erst bei der Anzeige übersetzt wird (die Sprache wechselt ohne Neustart): für Gründe und
    Hinweise, die beim Einlesen entstehen und lange am Buch hängen. Anzeigen mit text(); Werte dürfen
    selbst spaet(...) sein."""
    return (text, werte)


def text(t):
    """spaet(...) in der aktuellen Sprache; gewöhnliche Texte bleiben, wie sie sind."""
    if isinstance(t, tuple) and len(t) == 2 and isinstance(t[1], dict):
        return _(t[0]).format(**{k: text(v) for k, v in t[1].items()})
    return t


einstellen(gewuenscht())
