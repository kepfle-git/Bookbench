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


# ---- Seitenfilter und Balken in einer Zeile (seit 1.4-beta7; Bookends bookends_line_editor.lua)
SEITEN = ((None, N_("All pages")), ("odd", N_("Odd pages only")), ("even", N_("Even pages only")))
BALKEN_ARTEN = (("chapter", N_("Chapter")), ("book", N_("Book")))
BALKEN_STRICHE = (("off", N_("No chapter ticks")), ("level1", N_("Ticks: top level")),
                  ("level2", N_("Ticks: top 2 levels")), ("all", N_("Ticks: all levels")))
BALKEN_STILE = (("bordered", N_("Bordered")), ("solid", N_("Solid")), ("rounded", N_("Rounded")),
                ("metro", N_("Metro")), ("wavy", N_("Wave")), ("radial", N_("Radial")),
                ("radial_hollow", N_("Radial hollow")), ("pacman", N_("Pacman")))
RICHTUNGEN = (("ltr", N_("Left to right")), ("rtl", N_("Right to left")), ("ttb", N_("Top to bottom")),
              ("btt", N_("Bottom to top")))
ALTE_BALKENARTEN = {"book_ticks": "level1", "book_ticks2": "level2", "book_ticks_all": "all"}


def hat_balken(zeile):
    return "%bar" in (zeile or "")


def zeilenbalken(daten, pos, nr):
    """Balken einer Zeile als {art, striche, stil, richtung, dicke, ungelesen} mit Bookends' Vorgaben
    (Kapitel, ohne Striche, umrandet, links nach rechts, Dicke None = wie die Schrift). Alte Arten
    ("book_ticks" …) werden wie in Bookends gelesen."""
    art = zeilenwert(daten, pos, "line_bar_type", nr) or "chapter"
    striche = zeilenwert(daten, pos, "line_bar_chapter_ticks", nr) or "off"
    if art in ALTE_BALKENARTEN:
        art, striche = "book", ALTE_BALKENARTEN[art]
    if art != "book":
        art, striche = "chapter", "off"
    return {"art": art, "striche": striche,
            "stil": zeilenwert(daten, pos, "line_bar_style", nr) or "bordered",
            "richtung": zeilenwert(daten, pos, "line_bar_direction", nr) or "ltr",
            "dicke": zeilenwert(daten, pos, "line_bar_height", nr),
            "ungelesen": zeilenwert(daten, pos, "line_bar_unread_height", nr)}


def zeilenbalken_setzen(daten, pos, nr, werte):
    """Gegenstück zu zeilenbalken(); Vorgaben werden nicht gespeichert (wie Bookends)."""
    art = werte.get("art") or "chapter"
    striche = werte.get("striche") or "off"
    dicke, ungelesen = werte.get("dicke"), werte.get("ungelesen")
    for feld, wert in (("line_bar_type", None if art == "chapter" else art),
                       ("line_bar_chapter_ticks", None if art == "chapter" or striche == "off" else striche),
                       ("line_bar_style", None if werte.get("stil") in (None, "bordered") else werte["stil"]),
                       ("line_bar_direction", None if werte.get("richtung") in (None, "ltr") else werte["richtung"]),
                       ("line_bar_height", dicke),
                       ("line_bar_unread_height", None if ungelesen is None or ungelesen == dicke else ungelesen)):
        zeilenwert_setzen(daten, pos, feld, nr, wert)


# ---- Fortschrittsbalken über die ganze Breite (seit 1.4-beta7; Bookends menu/progress_bar_menu.lua)
BALKEN_ANZAHL = 8                                 # Config.MAX_BARS
BALKEN_VORGABE = {"enabled": False, "type": "book", "style": "solid", "height": 20, "v_anchor": "bottom",
                  "margin_v": 0, "margin_left": 0, "margin_right": 0, "chapter_ticks": "off"}
ANKER = (("top", N_("Top")), ("bottom", N_("Bottom")), ("left", N_("Left")), ("right", N_("Right")))


def balken_liste(daten):
    b = daten.get("progress_bars") or []
    if isinstance(b, dict):
        b = [b[k] for k in sorted(k for k in b if isinstance(k, int))]
    return [x if isinstance(x, dict) else {} for x in b]


def balken(daten, nr):
    """Werte von Balken nr (ab 1), fehlende mit Bookends' Vorgaben aufgefüllt (Kopie)."""
    liste = balken_liste(daten)
    roh = liste[nr - 1] if 0 < nr <= len(liste) else {}
    return {**BALKEN_VORGABE, **roh}


def balken_aendern(daten, nr, **werte):
    """Felder von Balken nr setzen (None = Feld entfernen). Fehlende Balken davor legt Bookends beim
    Laden selbst mit den Vorgaben an; hier werden sie ebenso aufgefüllt, damit die Liste lückenlos bleibt."""
    liste = balken_liste(daten)
    while len(liste) < nr:
        liste.append(dict(BALKEN_VORGABE))
    b = liste[nr - 1]
    for feld, wert in werte.items():
        if wert is None:
            b.pop(feld, None)
        else:
            b[feld] = wert
    daten["progress_bars"] = liste


def balken_senkrecht(b):
    return b.get("v_anchor") in ("left", "right")


def balken_richtungen(b):
    """Füllrichtungen, die Bookends für diesen Balken anbietet (Metro/Welle nur entlang der Achse,
    rund: keine)."""
    stil = b.get("style") or "solid"
    if stil in ("radial", "radial_hollow"):
        return ()
    if stil in ("metro", "wavy"):
        return ("ttb", "btt") if balken_senkrecht(b) else ("ltr", "rtl")
    return ("ltr", "rtl", "ttb", "btt")


def balken_richtung(b):
    return b.get("direction") or ("ttb" if balken_senkrecht(b) else "ltr")


def balken_anker_setzen(daten, nr, anker):
    """Anker wechseln wie in Bookends: Abstand zum Zeilentext gilt nicht mehr, Richtung passend zur Achse."""
    b = balken(daten, nr)
    senkrecht = anker in ("left", "right")
    richtung = b.get("direction") or ("ttb" if balken_senkrecht(b) else "ltr")
    neu_richtung = b.get("direction")
    if senkrecht and richtung not in ("ttb", "btt"):
        neu_richtung = "btt"
    elif not senkrecht and richtung in ("ttb", "btt"):
        neu_richtung = None
    balken_aendern(daten, nr, v_anchor=anker, band_offset=None, direction=neu_richtung)


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


# ================================================================ Bookends: Sonderzeichen (seit 1.4-beta3)
def ist_symbol(ch):
    """Zeichen aus dem privaten Bereich (Nerd-Font-Symbole), das eine normale Schrift nicht zeigt."""
    o = ord(ch)
    return 0xE000 <= o <= 0xF8FF or 0xF0000 <= o <= 0x10FFFD


def symbole(plugin_ordner):
    """[(Gruppe, [(Zeichen, Beschreibung, Einfügetext)])] aus menu/icons_catalogue.lua des installierten
    Bookends (CURATED_BY_CHIP). Einfügetext ist meist das Zeichen selbst, bei "dynamischen" Symbolen
    ein Token (%batt_icon …). Ohne Datei: []."""
    try:
        text = (Path(plugin_ordner) / "menu" / "icons_catalogue.lua").read_text(encoding="utf-8")
    except OSError:
        return []
    gruppen = dict(re.findall(r'\{\s*key\s*=\s*"([^"]+)"\s*,\s*label\s*=\s*_\("((?:[^"\\]|\\.)*)"\)', text))
    erg, aktuell, liste = [], None, None
    drin = False
    for zeile in text.splitlines():
        if re.match(r"\s*M\.CURATED_BY_CHIP\s*=\s*\{", zeile):
            drin = True
            continue
        if not drin:
            continue
        if re.match(r"^\}", zeile):
            break
        m = re.match(r"^\s{4}([A-Za-z_]+)\s*=\s*\{\s*$", zeile)
        if m:
            aktuell, liste = m.group(1), []
            erg.append((gruppen.get(aktuell, aktuell), liste))
            continue
        if liste is None:
            continue
        m = re.match(r'\s*\{\s*code\s*=\s*0x([0-9A-Fa-f]+)\s*(?:,\s*label\s*=\s*_\("((?:[^"\\]|\\.)*)"\))?'
                     r'\s*(?:,\s*insert_value\s*=\s*"((?:[^"\\]|\\.)*)")?\s*\},?\s*(?:--\s*(.*))?$', zeile)
        if m:
            ch = chr(int(m.group(1), 16))
            name = (lua_data.lesen('"' + m.group(2) + '"') if m.group(2) else (m.group(4) or "").strip()) or f"U+{ord(ch):04X}"
            liste.append((ch, name, lua_data.lesen('"' + m.group(3) + '"') if m.group(3) else ch))
            continue
        m = re.match(r'\s*\{\s*glyph\s*=\s*"((?:[^"\\]|\\.)*)"\s*,\s*label\s*=\s*_\("((?:[^"\\]|\\.)*)"\)', zeile)
        if m:
            ch = lua_data.lesen('"' + m.group(1) + '"')
            liste.append((ch, lua_data.lesen('"' + m.group(2) + '"'), ch))
    return [(g, l) for g, l in erg if l]


def symbolschrift(profil, befund=None):
    """Pfad der Nerd-Font-Symbolschrift (nerdfonts/symbols.ttf), mit der KOReader diese Zeichen zeichnet:
    im Profil (Schriften vom E-Reader), sonst neben dem Desktop-KOReader. None, wenn keine da ist."""
    kandidaten = []
    fonts = Path(profil) / "share" / "fonts"
    if fonts.is_dir():
        kandidaten += sorted(fonts.rglob("nerdfonts/symbols.ttf"))
    if befund and befund.get("art") in ("programm", "appimage") and befund.get("pfad"):
        p = Path(befund["pfad"]).resolve()
        kandidaten += [p.parent / "fonts" / "nerdfonts" / "symbols.ttf",
                       p.parent.parent / "lib" / "koreader" / "fonts" / "nerdfonts" / "symbols.ttf"]
    kandidaten += [Path(p) / "fonts" / "nerdfonts" / "symbols.ttf" for p in
                   ("/usr/lib/koreader", "/opt/koreader", "/usr/share/koreader", "/usr/local/lib/koreader")]
    return next((p for p in kandidaten if p.is_file()), None)


# Zusätzlicher Rand je Position (Bookends position_menu: v_offset alle, h_offset nur Ecken, 0…999 px)
def mit_seitenrand(pos):
    return pos in ("tl", "tr", "bl", "br")


def positionswert(daten, pos, feld):
    return ((daten.get("positions") or {}).get(pos) or {}).get(feld)


def positionswert_setzen(daten, pos, feld, wert):
    p = daten.setdefault("positions", {}).setdefault(pos, {"lines": []})
    if wert in (None, 0):
        p.pop(feld, None)
    else:
        p[feld] = wert


# ================================================================ Bookshelf: Theme und Dekoration (seit 1.4-beta3)
# Nachgesehen in Bookshelf 6.6 (lib/bookshelf_theme_pack.lua, _wallpaper.lua, _ornaments.lua, _color.lua).
# Ein Theme ist eine Schicht über dem eigenen Aussehen ("Eigenes Theme"): library_theme bzw. tab.theme
# wählt es, Hintergrund/Brett/Farben unten bearbeiten das eigene Theme.
THEME_EIGEN = None                                  # library_theme fehlt = eigenes Theme
THEME_SCHLICHT = "plain"
HELLDUNKEL = (("auto", N_("Automatic (like KOReader)")), ("light", N_("Light")), ("dark", N_("Dark")))
ABDUNKELN = ((0, N_("Transparent")), (0.35, N_("Low")), (0.6, N_("Moderate")), (0.85, N_("Heavy")), (1, N_("Solid")))
HAEUFIGKEIT = ((0, N_("None")), (0.5, N_("Rarely")), (1, N_("Often")), (2, N_("Always")))
HAEUFIGKEIT_VORGABE = 1
FARBEN = (("ink_color", N_("Text")), ("progress_fill", N_("Progress bar")), ("progress_track", N_("Progress track")),
          ("bookmark_color", N_("Bookmark")), ("complete_bookmark_color", N_("Finished bookmark")),
          ("favorite_star_color", N_("Favourite star")), ("favorite_heart_color", N_("Favourite heart")),
          ("rating_star_color", N_("Rating stars")), ("badge_fg", N_("Badge text")),
          ("badge_bg", N_("Badge background")), ("chrome_bg", N_("Menu bar")), ("module_bg", N_("Module card")),
          ("module_border", N_("Module border")), ("panel_color", N_("Panel")), ("panel_ink", N_("Panel text")),
          ("border_color", N_("Cover border")), ("selection_color", N_("Selection")),
          ("card_shadow_color", N_("Cover shadow")), ("spine_plank_color", N_("Plank")),
          ("folder_overlay_bg", N_("Folder label")), ("folder_overlay_fg", N_("Folder text")),
          ("chip_selected_bg", N_("Selected shelf")), ("chip_selected_fg", N_("Selected shelf text")),
          ("wallpaper_bg", N_("Page")))
BILD_ENDUNGEN = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
DEKO_ENDUNGEN = {".png", ".svg"}


def deko_ordner(ko):
    """Ordner der Dekoration (Ornamente, Theme-Pakete): settings/bookshelf/ornaments (ab 5.3),
    früher icons/bookshelf.ornaments (wird von Bookshelf weiter gelesen)."""
    return [p for p in (Path(ko) / "settings" / "bookshelf" / "ornaments", Path(ko) / "icons" / "bookshelf.ornaments")
            if p.is_dir()]


def _json(pfad):
    import json
    try:
        w = json.loads(Path(pfad).read_text(encoding="utf-8"))
        return w if isinstance(w, dict) else {}
    except (OSError, ValueError):
        return {}


def themes(ko):
    """[(Wert für library_theme/tab.theme, Name)] der Theme-Pakete (Ordner mit theme/theme.json)."""
    erg = {}
    for ordner in deko_ordner(ko):
        for p in sorted(ordner.iterdir()):
            m = p / "theme" / "theme.json"
            if p.is_dir() and m.is_file() and p.name not in erg:
                erg[p.name] = _json(m).get("name") or p.name
    return sorted(erg.items(), key=lambda x: x[1].lower())


def hintergrundbilder(ko):
    """Dateinamen in settings/bookshelf/wallpapers (Wert für wallpaper_default/wallpaper_full)."""
    d = Path(ko) / "settings" / "bookshelf" / "wallpapers"
    return sorted((p.name for p in d.iterdir() if p.is_file() and p.suffix.lower() in BILD_ENDUNGEN),
                  key=str.lower) if d.is_dir() else []


def bretter(ko):
    """[(Wert für theme_plank_pack, Name)] der Bretter aus Paketen (<paket>/theme/plank[.<name>].middle.png)."""
    erg = []
    for ordner in deko_ordner(ko):
        for p in sorted(ordner.iterdir()):
            t = p / "theme"
            if not t.is_dir():
                continue
            for f in sorted(t.iterdir()):
                m = re.fullmatch(r"plank(?:\.(.+))?\.middle\.png", f.name, re.I)
                if m:
                    wert = f"{p.name}/theme/plank" + (f".{m.group(1)}" if m.group(1) else "")
                    erg.append((wert, f"{p.name}: {m.group(1) or _('plank')}"))
    return erg


def dekoration(ko):
    """{Paket oder "": [relpfad]} aller Ornamente (lose Dateien und eine Ebene Pakete; ohne theme/)."""
    erg = {}
    for ordner in deko_ordner(ko):
        for p in sorted(ordner.iterdir()):
            if p.is_file() and p.suffix.lower() in DEKO_ENDUNGEN:
                erg.setdefault("", []).append(p.name)
            elif p.is_dir():
                teile = [f"{p.name}/{f.name}" for f in sorted(p.iterdir())
                         if f.is_file() and f.suffix.lower() in DEKO_ENDUNGEN]
                if teile:
                    erg.setdefault(p.name, []).extend(teile)
    return erg


def regal_name(tab):
    if not isinstance(tab, dict):
        return "?"
    return str(tab.get("label") or tab.get("name") or tab.get("id") or "?")


def farbe_hex(w):
    """Bookshelf-Farbe ({hex=} / {grey=} / Zahl) als #RRGGBB, sonst None."""
    if isinstance(w, dict):
        if isinstance(w.get("hex"), str) and re.fullmatch(r"#?[0-9A-Fa-f]{6}", w["hex"]):
            return "#" + w["hex"].lstrip("#").upper()
        w = w.get("grey")
    if isinstance(w, (int, float)) and not isinstance(w, bool):
        g = max(0, min(255, int(w)))
        return f"#{g:02X}{g:02X}{g:02X}"
    return None


def farbe_wert(hexwert):
    """#RRGGBB -> Bookshelfs Speicherform: {grey=N} bei Grau (r=g=b), sonst {hex="#RRGGBB"}."""
    h = hexwert.lstrip("#").upper()
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return {"grey": r} if r == g == b else {"hex": "#" + h}
