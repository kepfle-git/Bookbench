# -*- coding: utf-8 -*-
"""
plugins.py - Einstellungen der KOReader-Plugins Bookends und Bookshelf im Vorschau-Profil (seit
1.4-beta2). Nur Logik, die Oberfläche steckt in ui/workbench_plugins.py.

Beide Plugins sind Fremd-Plugins (AndyHazz/bookends.koplugin, AndyHazz/bookshelf.koplugin, AGPL);
Bookbench liest und schreibt nur ihre Dateien, nichts aus ihrem Quelltext ist übernommen. Formate
nachgesehen in Bookends 5.31 und Bookshelf 6.6 (24.11.2026); beide ändern sich schnell, deshalb wird
alles Unbekannte beim Schreiben unverändert mitgenommen.

Bookends
  settings/bookends.lua               LuaSettings: enabled, active_preset_filename, pos_*, … (die
                                      sichtbaren Werte stammen aus der aktiven Vorlage: Bookends lädt
                                      sie bei jedem Start neu, "live settings == active preset file")
  settings/bookends_presets/*.lua     Vorlagen: return { name, description, author, defaults = {…},
                                      positions = { tl, tc, tr, bl, bc, br = { lines = {…},
                                      line_style = {…}, line_font_size = {…}, … } },
                                      progress_bars = {…}, text_color, … }
  Im laufenden KOReader übernimmt Bookends eine Vorlage mit Bookends:applyPresetFile(dateiname)
  (preset_manager.lua); die Werkbank ruft das über den Befehl "bookends <datei>" auf.
  Token-Liste: menu/tokens_catalogue.lua des installierten Plugins (zur Laufzeit gelesen).

Bookshelf
  settings/bookshelf/settings.lua     LuaSettings (seit Bookshelf 5.3; vorher settings/bookshelf.lua)
  Kein Neuladen im laufenden KOReader: die Werkbank startet nach einer Änderung neu (~1,2 s).

Entwürfe: Änderungen wirken erst nur in der Werkbank (Wegwerf-Kopie), "Speichern" schreibt sie ins
Vorschau-Profil. Den Weg zurück auf den E-Reader gibt es ab 1.4-beta4.
"""
import re
from pathlib import Path

from bookbench.core import lua_data
from bookbench.i18n import N_, _

BOOKENDS = "bookends"
BOOKSHELF = "bookshelf"
BEKANNT = (BOOKENDS, BOOKSHELF)

POSITIONEN = (("tl", N_("Top left")), ("tc", N_("Top centre")), ("tr", N_("Top right")),
              ("bl", N_("Bottom left")), ("bc", N_("Bottom centre")), ("br", N_("Bottom right")))
POS_KENNUNGEN = tuple(k for k, __ in POSITIONEN)
STILE = (("regular", N_("Regular")), ("bold", N_("Bold")), ("italic", N_("Italic")),
         ("bolditalic", N_("Bold italic")))
# Felder je Zeile (Bookends Config.LINE_FIELDS): Listen bzw. Tabellen mit der Zeilennummer als Schlüssel
ZEILENFELDER = ("line_style", "line_font_size", "line_font_face", "line_v_nudge", "line_h_nudge",
                "line_uppercase", "line_page_filter", "line_bar_type", "line_bar_height", "line_bar_style",
                "line_bar_chapter_ticks", "line_bar_direction", "line_bar_unread_height", "line_bar_colors",
                "line_bar_markers")
# Allgemeine Werte einer Vorlage (defaults), mit Bookends' Vorgaben (main.lua loadSettings, bookends_config.lua)
ALLGEMEIN = (("font_size", N_("Font size"), None), ("font_scale", N_("Font scale (%)"), 100),
             ("margin_top", N_("Margin top"), 10), ("margin_bottom", N_("Margin bottom"), 10),
             ("margin_left", N_("Margin left"), 18), ("margin_right", N_("Margin right"), 18),
             ("overlap_gap", N_("Gap before overlapping (px)"), 50))
KUERZEN = (("center", N_("Shorten the centre first")), ("sides", N_("Shorten the sides first")))


# ================================================================ Erkennung
def ko_ordner(profil):
    return Path(profil) / "koreader"


def erkennen(profil):
    """Unterstützte Plugins im Profil: {name: {"ordner", "version"}} (nur Bookends und Bookshelf)."""
    erg = {}
    plugins = ko_ordner(profil) / "plugins"
    for name in BEKANNT:
        p = plugins / f"{name}.koplugin"
        if (p / "main.lua").is_file():
            erg[name] = {"ordner": p, "version": plugin_version(p)}
    return erg


def plugin_version(ordner):
    try:
        text = (Path(ordner) / "_meta.lua").read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r'\bversion\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else ""


def _profil_geaendert(profil, teil):
    """Merkt im Profil, dass Bookbench dort etwas geändert hat (Warnung vor "Vom E-Reader")."""
    from bookbench.preview import emulator as kv
    alt = kv._marke_lesen(profil).get("bookbench_geaendert") or []
    if teil not in alt:
        kv._marke_schreiben(profil, {"bookbench_geaendert": sorted(set(alt) | {teil})})


def profil_geaendert(profil):
    from bookbench.preview import emulator as kv
    return list(kv._marke_lesen(profil).get("bookbench_geaendert") or [])


# ================================================================ LuaSettings
def einstellungen_lesen(pfad):
    """LuaSettings-Datei als dict ({} wenn sie fehlt oder kaputt ist)."""
    try:
        w = lua_data.datei_lesen(pfad)
    except (OSError, lua_data.LuaFehler):
        return {}
    return w if isinstance(w, dict) else {}


def einstellungen_schreiben(pfad, setzen=None, loeschen=()):
    """Einzelne Schlüssel einer LuaSettings-Datei setzen/löschen, der Rest bleibt wörtlich stehen
    (emulator.einstellungen_anpassen kann nur einfache Werte, hier gehen auch Tabellen)."""
    from bookbench.preview import emulator as kv
    pfad = Path(pfad)
    try:
        text = pfad.read_text(encoding="utf-8")
    except OSError:
        text = "-- we can read Lua syntax here!\nreturn {\n}\n"
    kopf, eintraege, fuss = kv.lua_zerlegen(text)
    setzen = setzen or {}
    neu = {k: t for k, t in eintraege if k not in setzen and k not in loeschen}
    for k, w in setzen.items():
        if w is None:
            neu.pop(k, None)
        else:
            neu[k] = f'    [{lua_data.zeichenkette(k)}] = {lua_data.schreiben(w, 1)},\n'
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(kopf + "".join(neu[k] for k in sorted(neu)) + (fuss or "}\n"), encoding="utf-8")


# ================================================================ Bookends
def vorlagen_ordner(ko):
    return Path(ko) / "settings" / "bookends_presets"


def bookends_datei(ko):
    return Path(ko) / "settings" / "bookends.lua"


def vorlagen(ko):
    """[{"datei", "name", "fehler"}] aller Vorlagen, nach Namen sortiert."""
    erg = []
    ordner = vorlagen_ordner(ko)
    for p in sorted(ordner.glob("*.lua")) if ordner.is_dir() else []:
        try:
            d = lua_data.datei_lesen(p)
            erg.append({"datei": p.name, "name": (d.get("name") if isinstance(d, dict) else None) or p.stem,
                        "fehler": "" if isinstance(d, dict) else _("not a table")})
        except (OSError, lua_data.LuaFehler) as e:
            erg.append({"datei": p.name, "name": p.stem, "fehler": str(e)})
    return sorted(erg, key=lambda v: v["name"].lower())


def vorlage_lesen(ko, datei):
    d = lua_data.datei_lesen(vorlagen_ordner(ko) / datei)
    if not isinstance(d, dict):
        raise lua_data.LuaFehler(_("not a table"))
    return d


def vorlage_schreiben(ko, datei, daten):
    """Schreibt eine Vorlage so, wie Bookends selbst es tut (Kopfzeile + return { … })."""
    ordner = vorlagen_ordner(ko)
    ordner.mkdir(parents=True, exist_ok=True)
    name = daten.get("name") or Path(datei).stem
    text = f"-- Bookends preset: {name}\nreturn {lua_data.schreiben(daten)}\n"
    tmp = ordner / (datei + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(ordner / datei)


def dateiname(ko, name, ausser=None):
    """Freier Dateiname für eine neue Vorlage (wie Bookends' sanitizePresetFilename: Kleinbuchstaben,
    Unterstriche, .lua)."""
    stamm = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "preset"
    vorhanden = {p.name for p in vorlagen_ordner(ko).glob("*.lua")} - {ausser}
    datei, n = f"{stamm}.lua", 2
    while datei in vorhanden:
        datei, n = f"{stamm}_{n}.lua", n + 1
    return datei


def bookends_stand(ko):
    """{"an": bool, "aktiv": Dateiname der aktiven Vorlage oder None}."""
    e = einstellungen_lesen(bookends_datei(ko))
    return {"an": bool(e.get("enabled", False)), "aktiv": e.get("active_preset_filename")}


def bookends_setzen(ko, an=None, aktiv=None):
    setzen = {}
    if an is not None:
        setzen["enabled"] = bool(an)
    if aktiv is not None:
        setzen["active_preset_filename"] = aktiv
        setzen["manual_active_preset_filename"] = aktiv
    if setzen:
        einstellungen_schreiben(bookends_datei(ko), setzen)


def leere_vorlage(name):
    return {"name": name, "positions": {k: {"lines": []} for k in POS_KENNUNGEN}}


def zeilen(daten, pos):
    p = (daten.get("positions") or {}).get(pos) or {}
    z = p.get("lines") or []
    if isinstance(z, dict):                       # Lücken (sollte nicht vorkommen): nach Nummer ordnen
        z = [z[k] for k in sorted(k for k in z if isinstance(k, int))]
    return [str(x) for x in z]


def zeilenwert(daten, pos, feld, nr):
    """Wert eines Zeilenfelds (nr ab 1) oder None."""
    w = ((daten.get("positions") or {}).get(pos) or {}).get(feld)
    if isinstance(w, list):
        return w[nr - 1] if 0 < nr <= len(w) else None
    if isinstance(w, dict):
        return w.get(nr)
    return None


def _feld_als_dict(w):
    if isinstance(w, list):
        return {i + 1: x for i, x in enumerate(w)}
    if isinstance(w, dict):
        return {k: v for k, v in w.items() if isinstance(k, int)}
    return {}


def zeilenwert_setzen(daten, pos, feld, nr, wert):
    p = daten.setdefault("positions", {}).setdefault(pos, {"lines": []})
    d = _feld_als_dict(p.get(feld))
    if wert is None:
        d.pop(nr, None)
    else:
        d[nr] = wert
    p[feld] = d if d else None
    if p[feld] is None:
        del p[feld]


def zeilen_setzen(daten, pos, neue):
    """Neue Zeilen einer Position. Die Felder je Zeile (Stil, Größe, …) wandern mit ihrer Zeile:
    erst gleiche Stelle mit gleichem Text, dann gleicher Text an anderer Stelle (eingefügte/gelöschte
    Zeilen), bei gleicher Zeilenzahl zuletzt die gleiche Stelle (Zeile wurde bearbeitet). Neue Zeilen
    bekommen keine Felder."""
    p = daten.setdefault("positions", {}).setdefault(pos, {"lines": []})
    alte = zeilen(daten, pos)
    neue = list(neue)
    zuordnung = {}
    frei = set(range(1, len(alte) + 1))
    for i, z in enumerate(neue, 1):
        if i in frei and alte[i - 1] == z:
            zuordnung[i] = i
            frei.discard(i)
    for i, z in enumerate(neue, 1):
        if i not in zuordnung:
            j = next((j for j in sorted(frei) if alte[j - 1] == z), None)
            if j is not None:
                zuordnung[i] = j
                frei.discard(j)
    if len(alte) == len(neue):
        for i in range(1, len(neue) + 1):
            if i not in zuordnung and i in frei:
                zuordnung[i] = i
                frei.discard(i)
    for feld in ZEILENFELDER:
        if feld not in p:
            continue
        alt = _feld_als_dict(p[feld])
        neu = {i: alt[j] for i, j in zuordnung.items() if j in alt}
        if neu:
            p[feld] = neu
        else:
            del p[feld]
    p["lines"] = neue


def allgemein(daten, schluessel):
    return (daten.get("defaults") or {}).get(schluessel)


def allgemein_setzen(daten, schluessel, wert):
    d = daten.setdefault("defaults", {})
    if wert is None:
        d.pop(schluessel, None)
    else:
        d[schluessel] = wert
    if not d:
        del daten["defaults"]


def tokens(plugin_ordner):
    """[(Gruppe, Token, Beschreibung)] aus menu/tokens_catalogue.lua des installierten Bookends
    (englische Texte, wie im Plugin). Fehlt die Datei: []."""
    try:
        text = (Path(plugin_ordner) / "menu" / "tokens_catalogue.lua").read_text(encoding="utf-8")
    except OSError:
        return []
    gruppen = dict(re.findall(r'\{\s*key\s*=\s*"([^"]+)"\s*,\s*label\s*=\s*_\("((?:[^"\\]|\\.)*)"\)', text))
    erg = []
    for m in re.finditer(r'\{\s*description\s*=\s*_\("((?:[^"\\]|\\.)*)"\)\s*,\s*token\s*=\s*"((?:[^"\\]|\\.)*)"'
                         r'\s*,\s*chip\s*=\s*"([^"]+)"', text):
        beschreibung, token, chip = (lua_data.lesen('"' + m.group(1) + '"'), lua_data.lesen('"' + m.group(2) + '"'),
                                     m.group(3))
        erg.append((gruppen.get(chip, chip), token, beschreibung))
    return erg


# ================================================================ Bookshelf
def bookshelf_datei(ko):
    """settings/bookshelf/settings.lua (ab Bookshelf 5.3), sonst die alte settings/bookshelf.lua."""
    neu = Path(ko) / "settings" / "bookshelf" / "settings.lua"
    alt = Path(ko) / "settings" / "bookshelf.lua"
    return alt if alt.is_file() and not neu.is_file() else neu


# Gepflegte Auswahl (Schlüssel, Gruppe, Text, Art, Vorgabe, Auswahl). Art: "an" (an/aus), "zahl"
# (leer = Vorgabe), "wahl". Vorgaben aus Bookshelf 6.6 (Store.read/isTrue/nilOrTrue); fehlt ein
# Schlüssel in der Datei, gilt die Vorgabe. Alles andere steht unter "Alle Schlüssel".
BOOKSHELF_GRUPPEN = (("anordnung", N_("Layout")), ("schrift", N_("Font sizes (%)")),
                     ("cover", N_("Covers and spines")), ("anzeige", N_("Display")))
BOOKSHELF_WERTE = (
    ("bookshelf_columns", "anordnung", N_("Columns (empty = automatic)"), "zahl", None, None),
    ("bookshelf_rows", "anordnung", N_("Rows (empty = automatic)"), "zahl", None, None),
    ("footer_bar", "anordnung", N_("Footer bar"), "wahl", "show",
     (("show", N_("Show")), ("hide", N_("Hide")), ("invisible", N_("Invisible buttons")))),
    ("start_menu_position", "anordnung", N_("Start menu button"), "wahl", "left",
     (("left", N_("Left")), ("right", N_("Right")), ("off", N_("Off")))),
    ("chip_flex_widths", "anordnung", N_("Shelf buttons as wide as their text"), "an", False, None),
    ("chip_uppercase_labels", "anordnung", N_("Shelf buttons in capitals"), "an", True, None),
    ("font_scale", "schrift", N_("General"), "zahl", 100, None),
    ("start_menu_font_scale", "schrift", N_("Start menu"), "zahl", 100, None),
    ("cover_badge_font_scale", "schrift", N_("Badges on covers"), "zahl", 100, None),
    ("spine_font_scale", "schrift", N_("Spines"), "zahl", 100, None),
    ("stack_label_font_scale", "schrift", N_("Stack labels"), "zahl", 100, None),
    ("hero_module_font_scale", "schrift", N_("Modules in the hero card"), "zahl", 100, None),
    ("expanded_shelf_font_scale", "schrift", N_("Full screen shelves"), "zahl", 100, None),
    ("cover_no_shadow", "cover", N_("Covers without shadow"), "an", False, None),
    ("cover_square_corners", "cover", N_("Square cover corners"), "an", False, None),
    ("true_cover_aspect", "cover", N_("Covers in their real proportions"), "an", False, None),
    ("spine_no_shadows", "cover", N_("Spines without shadows"), "an", False, None),
    ("spine_show_author", "cover", N_("Author on spines"), "an", True, None),
    ("hide_single_book_stacks", "cover", N_("No stack for a single book"), "an", False, None),
    ("open_cover_effect", "cover", N_("Effect when opening a book"), "an", True, None),
    ("color_panel_dithering", "anzeige", N_("Dithering on colour screens"), "an", True, None),
    ("shelf_full_refresh", "anzeige", N_("Full refresh when turning shelf pages"), "an", False, None),
)
# Schlüssel, die Bookshelf selbst laufend schreibt (Stand, Zwischenspeicher, Updater): nicht anbieten
BOOKSHELF_INTERN = {"migrated", "active_chip", "active_cursor", "active_page", "drill_path", "orn_resume",
                    "home_expanded", "last_run_version", "dev_branch", "last_install_source", "check_updates",
                    "top_panel_rows_taken", "pubdate_reader_version"}


def bookshelf_lesen(ko):
    return einstellungen_lesen(bookshelf_datei(ko))


def bookshelf_schreiben(ko, aenderungen):
    """aenderungen: {schlüssel: wert}, None = Schlüssel löschen (Vorgabe gilt)."""
    setzen = {k: v for k, v in aenderungen.items() if v is not None}
    loeschen = [k for k, v in aenderungen.items() if v is None]
    einstellungen_schreiben(bookshelf_datei(ko), setzen, loeschen)


def wert_text(w):
    """Kurzer Text für einen Wert in der Liste aller Schlüssel."""
    if isinstance(w, bool):
        return _("on") if w else _("off")
    if isinstance(w, (int, float, str)):
        return str(w)
    if isinstance(w, list):
        return _("list with {n} entries").format(n=len(w))
    if isinstance(w, dict):
        return _("table with {n} entries").format(n=len(w))
    return ""


def wert_aus_text(text, alt):
    """Eingabe in den Typ des alten Werts wandeln (Zahl bleibt Zahl usw.). ValueError bei Unsinn."""
    text = text.strip()
    if isinstance(alt, bool):
        if text.lower() in ("true", "1", "on", "an", "ja", "yes", _("on").lower()):
            return True
        if text.lower() in ("false", "0", "off", "aus", "nein", "no", _("off").lower()):
            return False
        raise ValueError(text)
    if isinstance(alt, int):
        return int(text)
    if isinstance(alt, float):
        return float(text.replace(",", "."))
    return text
