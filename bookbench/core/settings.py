# -*- coding: utf-8 -*-
"""
settings.py - Einstellungen von Bookbench laden und speichern (ohne Oberfläche).

Gespeichert als JSON: Windows %APPDATA%\\Bookbench\\einstellungen.json,
sonst ~/.config/bookbench/einstellungen.json (i18n.einstellungsordner). Neue Schlüssel bekommen einen
Standardwert, alte Dateien funktionieren weiter. Der Dialog steht in ui/settings.py.

  STANDARD            alle Schlüssel mit Standardwert (der Typ bestimmt das Eingabefeld im Dialog)
  laden(), speichern(e)
  klappentext_profile(e)   Quellprofile (gespeicherte oder die mitgelieferten)
  ordner_zeigen(ordner)    Ordner im Dateimanager öffnen
"""
import copy
import json
import os
import sys
from pathlib import Path

from bookbench.core import blurbs
from bookbench import i18n as ks
from bookbench.i18n import _

STANDARD = {
    "darstellung": "system", "tooltips": True, "status_liste": True, "cover": True, "fenster": "1200x760",
    "navi_ausgeklappt": True, "navi_offen": [],
    "ordner": "", "letzte_ordner": [],
    "sicherungsordner": str(Path.home() / "Bookbench Backups"), "sicherungen_anzahl": 5,
    "max_sub": 1, "caps": False,
    "api_key": "", "modell": "claude-haiku-5-5", "websuche": True,   # websuche: alt, steckt jetzt im Profil
    "kostenlos": True, "klappentext_profile": None,                  # None: mitgelieferte Profile
    "google_key": "",                                                # eigener Google-Books-Schlüssel (1.3-beta5)
    "cover_max_hoehe": 0, "cover_qualitaet": 90, "cover_klein": 800, "cover_openlibrary": True, "cover_google": True,
    "spalten": {}, "spalten_reihe": None, "sortierung": ["reihe", False],   # Bibliothek (ui/table_columns.py)
    "kobo_sicherungen_anzahl": 10, "kobo_teile": ["einstellungen", "settings", "buchdaten", "anpassungen"],
    "woerterbuch_quelle": "", "auswerfen_erinnern": True, "kobo_oeffnen": "auto",
    "woerterbuecher": [], "woerterbuch_aktiv": "",
    "koreader_pfad": "", "vorschau_groesse": "passend", "sprache": "auto",
    "vorschau_geraet": "auto", "vorschau_eigen": [1264, 1680, 300, False],   # eigen: Breite, Höhe, ppi, Farbe
    "werkbank_modus": "lesen", "werkbank_details": False,           # Vorschau als Werkbank (seit 1.4)
    "start_ordner": True, "start_bereich": "bibliothek", "bereich_zuletzt": "bibliothek",
    "tooltip_verzoegerung": 600, "cover_kopf_hoehe": 96, "kt_min": 80, "kt_max": 4000, "kt_kosten": 0.015,
    "cover_min_hoehe": 300, "cover_anzahl": 8, "kobo_suche_sekunden": 3,
    # Bereich Metadaten (seit 1.3): eigene Felder [[Suchname in Calibre, Bezeichnung]], Calibre-Abgleich
    "meta_spalten": [], "calibre_an": True, "calibre_bibliothek": "",
    # seit 1.3-beta5: abgeschaltete Status-Piktogramme je Ort (ui/markers.ORTE), Ziel des Doppelklicks
    "marken_aus": {}, "buch_oeffnen": "kapitel",
    # Updates (ui/updates.py): pruefen aus/start/taeglich/woechentlich, zuletzt/ausgelassen ohne Seite
    "update_pruefen": "taeglich", "update_vorab": False,     # Repo fest in core/updater.py (REPO)
    "update_zuletzt": "", "update_ausgelassen": "",
    # seit 2.1: Zwischenspeicher fürs Einlesen (core/scan_cache.py), Vorgabe-Ordnerschema für neue Bibliotheken
    "einlese_cache": True, "ordnerschema": "{author_sort}/[{series}/][{series_index:2} - ]{title}",
    "import_quelle": "",
}


def klappentext_profile(e):
    """Quellprofile für Klappentexte. Ohne gespeicherte die mitgelieferten; die alte Einstellung
    "websuche" (bis 0.20 global für das Lexicanum) geht dabei ins Lexicanum-Profil."""
    if isinstance(e.get("klappentext_profile"), list):
        return copy.deepcopy(e["klappentext_profile"])
    profile = copy.deepcopy(blurbs.STANDARD_PROFILE)
    for p in profile:
        if p["id"] == "lexicanum":
            p["websuche"] = bool(e.get("websuche", True))
        if p["id"] == "web":
            p["name"] = _("Web search")
    return profile


def pfad():
    return str(ks.einstellungsordner() / "einstellungen.json")


# Auswahl für das Modell (Klappentexte und Wörterbuch über Claude); "Liste laden" holt die aktuelle
# Liste von der API. Stand 18.11.2026, laut Anthropic die neuesten Modelle.
MODELLE = ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-2")


def laden():
    e = json.loads(json.dumps(STANDARD))                # tiefe Kopie
    try:
        with open(pfad(), encoding="utf-8") as f:
            e.update(json.load(f))
    except (OSError, ValueError):
        pass
    for alt in ("update_repo", "update_token"):          # bis 1.0.3 (Repo war privat); Token nicht liegen lassen
        e.pop(alt, None)
    alte_einstellungen(e)
    return e


def alte_einstellungen(e):
    """Einstellungen älterer Versionen umziehen: Untertitel aus 1.3-beta1 wird ein eigenes Feld."""
    if "meta_untertitel" in e or "meta_untertitel_spalte" in e:
        an, spalte = e.pop("meta_untertitel", False), e.pop("meta_untertitel_spalte", "") or "#subtitle"
        if an and not e.get("meta_spalten"):
            e["meta_spalten"] = [[spalte, _("Subtitle")]]


def speichern(e):
    p = pfad()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(e, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


def ordner_zeigen(ordner):
    """Ordner im Dateimanager öffnen (Explorer, Finder, xdg-open)."""
    import subprocess
    ordner = str(ordner)
    try:
        if sys.platform.startswith("win"):
            os.startfile(ordner)                       # noqa: S606 - nur ein Ordner
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", ordner],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except (OSError, AttributeError):
        pass
