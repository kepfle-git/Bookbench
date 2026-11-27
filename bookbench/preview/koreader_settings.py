# -*- coding: utf-8 -*-
"""
koreader_settings.py - KOReaders eigene Leseeinstellungen (Schrift, Ränder) und Userpatches im
Vorschau-Profil (seit 1.4-beta4). Nur Logik; Oberfläche in ui/workbench_reader.py.

Nachgesehen im KOReader-Quelltext (master, 24.11.2026):
  frontend/ui/data/creoptions.lua   Optionen des Lesemenüs (prefix "copt"), Vorgaben aus defaults.lua
  frontend/configurable.lua         loadDefaults: G_reader_settings "copt_<name>", sonst default_value;
                                    loadSettings/saveSettings: dieselben Schlüssel in den Buchdaten
  frontend/apps/reader/modules/readerfont.lua   Schrift: Buchdaten "font_face", sonst "cre_font"
  frontend/userpatch.lua, ui/elements/patch_management.lua   Patches

Wichtig: KOReader speichert beim Schließen eines Buchs ALLE copt_*-Werte in dessen Buchdaten (.sdr,
Configurable:saveSettings). Die allgemeinen Werte aus settings.reader.lua gelten deshalb nur für
Bücher, die noch nie offen waren - jedes schon gelesene Buch hat seine eigenen.

Patches (koreader/patches): "<Stufe><Nummer>-<Name>.lua" läuft, alles mit etwas hinter ".lua" (KOReader
selbst hängt ".disabled" an) ist aus. Stufe: 0 früh einmalig, 1 früh, 2 spät, 8 vor dem Beenden,
9 beim Beenden. Die Datei ".patches_disabled" schaltet alle aus.
"""
import re
import shutil
from pathlib import Path

from bookbench.core import lua_data
from bookbench.preview import plugins as kpl
from bookbench.i18n import N_, _

# (Schlüssel, Text, Art, Vorgabe, Auswahl) - Art: "zahl", "wahl", "an" (0/1), "paar" (zwei Zahlen)
SCHRIFT = (
    ("copt_font_size", N_("Font size"), "zahl", 22, None),
    ("copt_font_base_weight", N_("Font weight"), "wahl", 0,
     ((-1, "-1"), (-0.5, "-½"), (0, N_("normal")), (0.5, "+½"), (1, "+1"), (1.5, "+1½"), (3, "+3"))),
    ("copt_line_spacing", N_("Line spacing (%)"), "zahl", 100, None),
    ("copt_word_spacing", N_("Word spacing (%): scaling, reduction"), "paar", [95, 75], None),
    ("copt_word_expansion", N_("Word expansion (%)"), "zahl", 0, None),
    ("copt_font_kerning", N_("Kerning"), "wahl", 3,
     ((0, N_("off")), (1, N_("fast")), (2, N_("good")), (3, N_("best")))),
    ("copt_font_hinting", N_("Hinting"), "wahl", 2, ((0, N_("off")), (1, N_("native")), (2, N_("auto")))),
    ("copt_font_gamma", N_("Contrast (gamma)"), "wahl", 15,
     ((10, "0.8"), (15, "1.0"), (25, "1.4"), (30, "1.6"), (36, "2.0"), (43, "2.5"), (49, "3.0"), (56, "4.0"))),
    ("copt_embedded_fonts", N_("Embedded fonts of the book"), "an", 1, None),
    ("copt_embedded_css", N_("Embedded style of the book"), "an", 1, None),
)
RAENDER = (
    ("copt_h_page_margins", N_("Left and right"), "paar", [10, 10], None),
    ("copt_t_page_margin", N_("Top"), "zahl", 15, None),
    ("copt_b_page_margin", N_("Bottom"), "zahl", 15, None),
    ("copt_sync_t_b_page_margins", N_("Keep top and bottom the same"), "an", 0, None),
)
SCHRIFTART = "cre_font"                  # allgemeine Schrift; im Buch "font_face"
ALLE = SCHRIFT + RAENDER
BUCH_SCHLUESSEL = {k for k, *__ in ALLE} | {"font_face"}
SCHRIFT_ENDUNGEN = {".ttf", ".otf", ".ttc"}


def einstellungen_datei(ko):
    return Path(ko) / "settings.reader.lua"


def lesen(ko):
    return kpl.einstellungen_lesen(einstellungen_datei(ko))


def schreiben(ko, aenderungen):
    """aenderungen {schlüssel: wert}, None = löschen (KOReaders Vorgabe gilt)."""
    setzen = {k: v for k, v in aenderungen.items() if v is not None}
    loeschen = [k for k, v in aenderungen.items() if v is None]
    kpl.einstellungen_schreiben(einstellungen_datei(ko), setzen, loeschen)


def schriftfamilien(ordner_liste):
    """Familiennamen der Schriften in den Ordnern (so, wie KOReader sie in cre_font schreibt), sortiert.
    Braucht Pillow; ohne Pillow die Dateinamen ohne Endung und Schnitt."""
    namen = set()
    try:
        from PIL import ImageFont
    except ImportError:
        ImageFont = None
    for ordner in ordner_liste:
        ordner = Path(ordner)
        if not ordner.is_dir():
            continue
        for p in ordner.rglob("*"):
            if p.suffix.lower() not in SCHRIFT_ENDUNGEN or "nerdfonts" in p.parts:
                continue
            name = None
            if ImageFont:
                try:
                    name = ImageFont.truetype(str(p), 10).getname()[0]
                except (OSError, ValueError):
                    name = None
            if not name:
                name = re.split(r"[-_](Regular|Bold|Italic|Medium|Light|Book|Roman)", p.stem, flags=re.I)[0]
            namen.add(name)
    return sorted(namen, key=str.lower)


def schriftordner(profil, befund=None):
    """Ordner, aus denen der Desktop-KOReader der Werkbank Schriften nimmt: die des Profils (vom
    E-Reader) und KOReaders eigene neben dem Programm."""
    erg = [Path(profil) / "share" / "fonts"]
    if befund and befund.get("art") in ("programm", "appimage") and befund.get("pfad"):
        p = Path(befund["pfad"]).resolve()
        erg += [p.parent / "fonts", p.parent.parent / "lib" / "koreader" / "fonts"]
    erg += [Path(p) / "fonts" for p in ("/usr/lib/koreader", "/opt/koreader")]
    return [p for p in erg if p.is_dir()]


# ================================================================ Buchdaten
def buchwerte(sdr_ordner):
    """{schlüssel: wert} der Schrift-/Randwerte in den Buchdaten (metadata.*.lua) eines .sdr-Ordners."""
    erg = {}
    for p in sorted(Path(sdr_ordner).glob("metadata.*.lua")) if Path(sdr_ordner).is_dir() else []:
        if p.name.endswith(".old"):
            continue
        werte = kpl.einstellungen_lesen(p)
        erg.update({k: v for k, v in werte.items() if k in BUCH_SCHLUESSEL})
    return erg


def buchwerte_entfernen(sdr_ordner):
    """Schrift-/Randwerte aus den Buchdaten entfernen (nur in der Wegwerf-Kopie der Werkbank!)."""
    for p in sorted(Path(sdr_ordner).glob("metadata.*.lua")) if Path(sdr_ordner).is_dir() else []:
        kpl.einstellungen_schreiben(p, loeschen=sorted(BUCH_SCHLUESSEL))


def wert_text(w):
    if isinstance(w, list):
        return " / ".join(str(x) for x in w)
    return str(w)


# ================================================================ Patches
STUFEN = (("0", N_("Early, once after an update")), ("1", N_("Early")), ("2", N_("Late (after the start)")),
          ("8", N_("Before quitting")), ("9", N_("When quitting")))
ALLE_AUS = ".patches_disabled"
EIGENE = ("1-bookbench-desktop.lua", "2-bookbench-workbench.lua")      # schreibt Bookbench selbst


# Patches, die Bookbench mitbringt (bookbench/patches, im Release auch als eigene Anhänge; seit 1.4-beta7)
MITGEBRACHT_ORDNER = Path(__file__).resolve().parent.parent / "patches"
MITGEBRACHT = {
    "2-bookbench-subtitle.lua": N_("Subtitle and calibre's custom columns from the EPUB: Bookshelf gets the token "
                                   "%subtitle (also for the top panel), and %calibre{name} in Bookshelf and "
                                   "Bookends finds columns stored in the book, without calibre's metadata.calibre."),
    "2-bookbench-screensaver.lua": N_("Sleep screen with a picture and a message: the picture moves into the free "
                                      "space next to the message instead of lying under it (switch and options on "
                                      "the page Sleep screen)."),
    "2-bookbench-collections.lua": N_("Collections with series, number, blurb and cover (a series is one entry like a "
                                      "folder, “About this collection”), and stories inside anthologies as entries of "
                                      "a collection, opened right inside the anthology with a reading position of "
                                      "their own (area Collections). Replaces 2-bookbench-stories.lua.")
}


# mitgebrachte Patches, die einen älteren unter anderem Namen ersetzen
ERSETZT = {"2-bookbench-collections.lua": ("2-bookbench-stories.lua",)}


def mitgebracht(ko):
    """[{"name", "beschreibung", "stand"}] der mitgebrachten Patches; stand = "fehlt", "aktuell" oder "anders"
    (im Profil, aber nicht diese Fassung)."""
    erg = []
    for name, text in MITGEBRACHT.items():
        quelle = MITGEBRACHT_ORDNER / name
        if not quelle.is_file():
            continue
        d = patch_ordner(ko)
        da = next((d / n for n in (name, name + ".disabled") if (d / n).is_file()), None)
        if da is None:
            stand = "fehlt"
        else:
            stand = "aktuell" if da.read_bytes() == quelle.read_bytes() else "anders"
        erg.append({"name": name, "beschreibung": text, "stand": stand, "quelle": quelle})
    return erg


def mitgebracht_einspielen(ko, name):
    """Mitgebrachten Patch ins Profil kopieren (neu oder neuere Fassung). Eine ausgeschaltete alte Fassung
    (.disabled) wird ersetzt und bleibt aus."""
    quelle = MITGEBRACHT_ORDNER / name
    ziel = patch_ordner(ko)
    ziel.mkdir(parents=True, exist_ok=True)
    aus = ziel / (name + ".disabled")
    shutil.copy2(quelle, aus if aus.is_file() else ziel / name)
    for alt in ERSETZT.get(name, ()):                       # Vorgänger unter anderem Namen weg
        for p in (ziel / alt, ziel / (alt + ".disabled")):
            p.unlink(missing_ok=True)


def mitgebracht_stand(ko, name):
    """"fehlt", "aus" (nur .disabled), "aktuell" oder "anders" für einen mitgebrachten Patch."""
    m = next((m for m in mitgebracht(ko) if m["name"] == name), None)
    if m is None or m["stand"] == "fehlt":
        return "fehlt"
    if not (patch_ordner(ko) / name).is_file():
        return "aus"
    return m["stand"]


def patch_ordner(ko):
    return Path(ko) / "patches"


def patch_name(datei):
    """Name ohne Anhängsel: "2-x.lua.disabled" -> "2-x.lua"."""
    i = datei.find(".lua")
    return datei[:i + 4] if i >= 0 else datei


def patches(ko):
    """[{"datei", "name", "an", "stufe"}] wie KOReaders Patchverwaltung (nur "<Ziffern>-…" mit .lua),
    ohne Bookbenchs eigene, nach Stufe und natürlicher Reihenfolge."""
    d = patch_ordner(ko)
    erg = []
    for p in d.iterdir() if d.is_dir() else []:
        if not p.is_file() or ".lua" not in p.name:
            continue
        m = re.match(r"^(\d)\d*-", p.name)
        name = patch_name(p.name)
        if not m or name in EIGENE or "bookbench-probe" in name:
            continue
        erg.append({"datei": p.name, "name": name, "an": p.name.endswith(".lua"), "stufe": m.group(1)})

    def natuerlich(s):
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]
    return sorted(erg, key=lambda x: (x["stufe"], natuerlich(x["name"])))


def alle_aus(ko):
    return (patch_ordner(ko) / ALLE_AUS).is_file()


def patches_anwenden(ko, schalter, alle=None):
    """schalter {name: an}: umbenennen wie KOReader (an = "name.lua", aus = "name.lua.disabled").
    alle: True/False = .patches_disabled anlegen/entfernen, None = lassen."""
    d = patch_ordner(ko)
    for p in patches(ko):
        if p["name"] in schalter and schalter[p["name"]] != p["an"]:
            ziel = p["name"] if schalter[p["name"]] else p["name"] + ".disabled"
            (d / p["datei"]).rename(d / ziel)
    if alle is not None:
        marke = d / ALLE_AUS
        if alle:
            d.mkdir(parents=True, exist_ok=True)
            marke.touch()
        elif marke.exists():
            marke.unlink()


def patch_text(ko, datei):
    try:
        return (patch_ordner(ko) / datei).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return str(e)


def patch_fehler(log_text):
    """{patchname: Fehlermeldung} aus KOReaders Ausgabe ("Applying patch: …", dann "Patching failed: …")."""
    erg, zuletzt = {}, None
    for zeile in log_text.splitlines():
        m = re.search(r"Applying patch:\s*(\S+)", zeile)
        if m:
            zuletzt = patch_name(Path(m.group(1)).name)
            continue
        m = re.search(r"Patching failed:\s*(.*)", zeile)
        if m and zuletzt:
            erg[zuletzt] = m.group(1).strip()
    return erg


def lua_pruefen(text):
    """Grobe Plausibilität einer hinzugefügten Datei: Lua-Text, kein Binärzeug. Gibt eine Warnung oder ""."""
    if "\0" in text:
        return _("The file is not a text file.")
    try:
        lua_data.lesen(text)
        return _("The file only contains data, no patch code.")
    except lua_data.LuaFehler:
        return ""
