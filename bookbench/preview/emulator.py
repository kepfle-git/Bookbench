# -*- coding: utf-8 -*-
"""
emulator.py - Vorschau einer Seite vom E-Reader mit dem Desktop-KOReader ("Emulator").
Keine Oberfläche.

Der Desktop-KOReader ist eine optionale Abhängigkeit: Gibt es ihn nicht, fehlt nur
diese Funktion. Unter Windows gibt es kein offizielles KOReader, dort bleibt der
Bereich ganz weg (verfuegbar()).

Die Vorschau läuft in einem eigenen Profil, damit eine normale KOReader-Installation
auf dem Rechner unberührt bleibt:

  <Einstellungsordner>/vorschau/koreader   KO_HOME: Einstellungen, settings/, patches/,
                                           styletweaks/, plugins/ (nur eigene)
  <Einstellungsordner>/vorschau/share      XDG_DATA_HOME: darin fonts/ (Schriften vom Gerät)
  <Einstellungsordner>/vorschau/buecher    Kopie des gerade gezeigten Buchs mit .sdr

KOReader liest KO_HOME vor allem anderen (datastorage.lua) - so funktioniert das mit
AppImage, Paket und Flatpak gleich. Bildschirm: EMULATE_READER_W/H (ffi/SDL3.lua),
EMULATE_READER_DPI (ffi/framebuffer.lua), EMULATE_BW_SCREEN (ffi/framebuffer_SDL3.lua:
schaltet die Farbe ab, für Geräte mit Schwarzweiß-Bildschirm).

  koreader_finden(eigener)     wie KOReader gestartet wird, oder None
  vom_geraet(wurzel, profil)   Profil aus dem angeschlossenen E-Reader neu aufbauen
  aus_sicherung(zip, profil)   Einstellungen aus einer Sicherung übernehmen (Plugins und
                               Schriften bleiben, die stehen in keiner Sicherung)
  profil_stand(profil)         was im Profil liegt
  sdr_finden(buch, ...)        Buchdaten (.sdr) zum Buch: daneben, auf dem Gerät, in der Sicherung
  bildschirm(...)              welches Gerät nachgebildet wird (Einstellung, Profil, angeschlossenes)

Kennung "kobo" bei quelle/plugins_von und in bildschirm() heißt "vom angeschlossenen
Gerät" (Name aus der Zeit, als es nur Kobos gab; bleibt wegen vorhandener Profile).
  starten(...)                 Buch ins Profil kopieren und KOReader starten
  protokoll(profil)            letzte Zeilen von KOReaders Ausgabe, Warnungen gezählt
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from bookbench.device import device as kg
from bookbench.device import models as km
from bookbench.i18n import _

KOREADER = kg.KOREADER                        # .adds/koreader (Kobo; andere Arten: kg.ko_ordner)
FLATPAK_ID = "rocks.koreader.KOReader"
MARKE = "bookbench-vorschau.json"
MARKE_ALT = "kobo-werkstatt-vorschau.json"    # Name bis 0.24
LOG = "koreader.log"

GROESSEN = ("passend", "halb", "voll")
GROESSE_TEXT = {"passend": _("fitted to the screen"), "halb": _("half size"), "voll": _("full size")}

# Plugins, die jeder KOReader mitbringt (frontend/pluginloader.lua, BUILTIN_PLUGINS).
# Nur die anderen kommen ins Profil, sonst gäbe es sie doppelt.
EINGEBAUT = {
    "archiveviewer", "autodim", "autostandby", "autosuspend", "autoturn", "autowarmth", "batterystat",
    "bookshortcuts", "calibre", "cloudstorage", "coverbrowser", "coverimage", "docsettingtweak", "exporter",
    "externalkeyboard", "gestures", "hello", "hotkeys", "httpinspector", "japanese", "keepalive", "kosync",
    "movetoarchive", "newsdownloader", "opds", "perceptionexpander", "profiles", "qrclipboard", "readtimer",
    "SSH", "statistics", "systemstat", "terminal", "texteditor", "timesync", "vocabbuilder", "wallabag",
}
SCHRIFT_ENDUNGEN = {".ttf", ".otf", ".ttc", ".cff", ".woff", ".woff2"}

# Was aus settings.reader.lua heraus muss: Bildschirm-DPI würde EMULATE_READER_DPI schlagen
# (generic/device.lua), Plugin-Pfade und Ordner zeigen aufs Gerät.
RAUS = ("screen_dpi", "extra_plugin_paths", "lastfile", "lastdir", "home_dir")
# Aus einer Sicherung: diese Pfade (relativ zum KOReader-Ordner) gehören ins Profil
SICHERUNG_PFADE = ("settings.reader.lua", "defaults.custom.lua", "settings/", "styletweaks/", "patches/")


def verfuegbar():
    """Kann es auf diesem System überhaupt einen Desktop-KOReader geben?"""
    return not sys.platform.startswith("win")


def profil_ordner(einstellungsdatei):
    """Profil neben der Einstellungsdatei von Bookbench."""
    return Path(einstellungsdatei).parent / "vorschau"


# ================================================================ KOReader finden
def _flatpak_da():
    if not shutil.which("flatpak"):
        return False
    try:
        return subprocess.run(["flatpak", "info", FLATPAK_ID], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def koreader_finden(eigener=""):
    """{"art": "programm"|"appimage"|"flatpak", "pfad": ...} oder None.
    eigener: in den Einstellungen gewählte Datei (z. B. ein AppImage) oder "flatpak" (bzw. die
    Flatpak-Kennung), hat Vorrang - so lässt sich das Flatpak auch nehmen, wenn KOReader
    zusätzlich normal installiert ist."""
    if eigener and eigener.strip().lower() in ("flatpak", FLATPAK_ID.lower()):
        return {"art": "flatpak", "pfad": FLATPAK_ID} if _flatpak_da() else None
    if eigener and Path(eigener).is_file():
        return {"art": "appimage" if eigener.lower().endswith(".appimage") else "programm", "pfad": str(eigener)}
    for name in ("koreader", "KOReader"):
        p = shutil.which(name)
        if p:
            return {"art": "programm", "pfad": p}
    mac = Path("/Applications/KOReader.app/Contents/MacOS/koreader")
    if sys.platform == "darwin" and mac.is_file():
        return {"art": "programm", "pfad": str(mac)}
    kandidaten = []
    for ordner in (Path.home() / "Applications", Path.home() / "Downloads", Path.home() / ".local/bin", Path.home()):
        try:
            kandidaten.extend(ordner.glob("[Kk][Oo][Rr]eader*.AppImage"))
        except OSError:
            pass
    if kandidaten:
        neueste = max(kandidaten, key=lambda p: p.stat().st_mtime)
        return {"art": "appimage", "pfad": str(neueste)}
    if _flatpak_da():
        return {"art": "flatpak", "pfad": FLATPAK_ID}
    return None


# KOReader bis mindestens v2026.07.1 erkennt das Gerät an Dateien (frontend/device.lua, probeDevice,
# nachgesehen 18.11.2026): gibt es eine davon, nimmt auch der Desktop-KOReader den Teil für dieses
# Gerät und stürzt ab (Kobo: getCodeName findet kein Modell). Unter Arch/EndeavourOS legt das Paket
# hwdetect /usr/bin/hwdetect an (beim Nutzer so passiert). Die Flatpak-Fassung sieht die Dateien des
# Systems nicht. Neuere KOReader-Fassungen (master) erkennen das Gerät am Bau, nicht an Dateien.
GERAETE_DATEIEN = (("/proc/usid", "Kindle"), ("/bin/kobo_config.sh", "Kobo"), ("/usr/bin/hwdetect.sh", "Kobo"),
                   ("/usr/bin/hwdetect", "Kobo"), ("/ebrmain", "PocketBook"), ("/usr/bin/xochitl", "reMarkable"),
                   ("/etc/PRSTUX", "Sony PRSTUX"), ("/usr/bin/ntxinfo", "Cervantes"))

# Abhilfe ohne Zutun des Nutzers: ein früher Benutzer-Patch im Profil. reader.lua führt die Patches
# mit "1-" vorn (userpatch.early) bei jedem Start aus, vor require("device"); device.lua prüft die
# Dateien erst dann mit lfs.attributes aus dem gemeinsamen Modul libs/libkoreader-lfs (nachgesehen im
# Quelltext von v2026.07.1). Der Patch lässt lfs.attributes für genau diese Pfade nil liefern, dann
# landet KOReader bei SDL (Desktop). Wird bei jedem Start neu geschrieben, zählt nicht als Patch des
# Nutzers und kommt nie aufs Gerät. Wirkt nicht, wenn Patches abgeschaltet sind (.patches_disabled).
DESKTOP_PATCH = "1-bookbench-desktop.lua"
# Englisch, weil er im Profil auch für englischsprachige Nutzer sichtbar ist
DESKTOP_PATCH_TEXT = """-- Written by Bookbench for its preview and rewritten at every start (do not edit).
-- KOReader recognizes the device by files (frontend/device.lua). If one of them exists on the
-- computer, e.g. /usr/bin/hwdetect on Arch, the desktop KOReader takes itself for an e-reader and
-- crashes. This patch runs before the detection and hides exactly these paths.
local ok, lfs = pcall(require, "libs/libkoreader-lfs")
if not ok or type(lfs) ~= "table" or type(lfs.attributes) ~= "function" then return end
local hidden = {
%s
}
local orig_attributes = lfs.attributes
lfs.attributes = function(path, ...)
    if hidden[path] then return nil end
    return orig_attributes(path, ...)
end
""" % "\n".join(f'    ["{pfad}"] = true,' for pfad, __ in GERAETE_DATEIEN)


def desktop_patch_schreiben(profil):
    """Legt den Patch gegen die Geräteerkennung ins Profil (vor jedem Start)."""
    ordner = _ko(profil) / "patches"
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / DESKTOP_PATCH).write_text(DESKTOP_PATCH_TEXT, encoding="utf-8")


def geraete_datei(wurzel="/"):
    """(Pfad, Gerät) der ersten Datei, an der KOReader ein E-Reader-Gerät erkennt, oder None."""
    for pfad, geraet in GERAETE_DATEIEN:
        if (Path(wurzel) / pfad.lstrip("/")).exists():
            return pfad, geraet
    return None


def absturz_grund(profil, befund, wurzel="/"):
    """Hielt sich der Desktop-KOReader für einen E-Reader? Erklärung oder None. Erkannt an der
    Ausgabe (frontend/device/<gerät>/device.lua) und einer der Dateien oben."""
    if not befund or befund.get("art") == "flatpak":
        return None
    text, __, __ = protokoll(profil, zeilen=200)
    if not re.search(r"frontend/device/(kobo|kindle|pocketbook|remarkable|sony-prstux|cervantes)/device\.lua", text):
        return None
    gefunden = geraete_datei(wurzel)
    if not gefunden:
        return None
    pfad, geraet = gefunden
    zusatz = _(" (on Arch/EndeavourOS it comes from the package hwdetect)") if pfad == "/usr/bin/hwdetect" else ""
    gesperrt = (_ko(profil) / "patches" / ".patches_disabled").is_file()
    return _("The desktop KOReader takes this computer for a {geraet} because the file {pfad} exists{zusatz}. "
             "Up to at least version 2026.07 KOReader recognizes the device by such files and then crashes "
             "on the computer; KOReader alone (without Bookbench) does the same. Bookbench normally hides "
             "these files from KOReader with a start patch ({patch}); {grund}\n\n").format(
        geraet=geraet, pfad=pfad, zusatz=zusatz, patch=DESKTOP_PATCH,
        grund=_("here patches are switched off in KOReader (file .patches_disabled in the profile).") if gesperrt
        else _("that did not help here, perhaps a KOReader version that checks differently.")) + _(
        "Way out: KOReader as Flatpak (rocks.koreader.KOReader) does not see the files of the system. "
        "Install it (flatpak install flathub rocks.koreader.KOReader) and enter flatpak under Settings > "
        "Device > Preview > Desktop KOReader, or remove the file if nothing else needs it.")


def beschreibung(befund):
    if not befund:
        return _("not found")
    return {"flatpak": f"Flatpak {FLATPAK_ID}", "appimage": f"AppImage {befund['pfad']}"}.get(
        befund["art"], befund["pfad"])


# ================================================================ settings.reader.lua
_EINTRAG = re.compile(r'^    \["((?:[^"\\]|\\.)*)"\] = ', re.M)


def lua_zerlegen(text):
    """settings.reader.lua so, wie KOReader sie schreibt (luasettings: ein Eintrag je
    Schlüssel, vier Leerzeichen eingerückt, "}" am Zeilenanfang als Ende).
    Gibt (kopf, [(schlüssel, eintragstext)], fuss) zurück; Inhalte bleiben unverändert."""
    m = re.search(r"return\s*\{[ \t]*\n?", text)
    ende = text.rfind("}")
    if not m or ende < m.end():
        return text, [], ""
    kopf, rumpf, fuss = text[:m.end()], text[m.end():ende], text[ende:]
    if not kopf.endswith("\n"):
        kopf += "\n"
    treffer = list(_EINTRAG.finditer(rumpf))
    eintraege = []
    for i, t in enumerate(treffer):
        stop = treffer[i + 1].start() if i + 1 < len(treffer) else len(rumpf)
        stueck = rumpf[t.start():stop].rstrip() + "\n"
        eintraege.append((t.group(1), stueck))
    return kopf, eintraege, fuss


def lua_wert(w):
    if isinstance(w, bool):
        return "true" if w else "false"
    if isinstance(w, (int, float)):
        return repr(w)
    return '"' + str(w).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def einstellungen_anpassen(pfad, raus=RAUS, setzen=None):
    """Entfernt Schlüssel aus settings.reader.lua und setzt andere. Fehlt die Datei, wird
    eine angelegt. Gibt die entfernten Schlüssel zurück."""
    pfad = Path(pfad)
    try:
        text = pfad.read_text(encoding="utf-8")
    except OSError:
        text = "-- we can read Lua syntax here!\nreturn {\n}\n"
    kopf, eintraege, fuss = lua_zerlegen(text)
    setzen = setzen or {}
    entfernt = [k for k, __ in eintraege if k in raus or k in setzen]
    neu = {k: t for k, t in eintraege if k not in raus and k not in setzen}
    for k, w in setzen.items():
        neu[k] = f'    ["{k}"] = {lua_wert(w)},\n'
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(kopf + "".join(neu[k] for k in sorted(neu)) + (fuss or "}\n"), encoding="utf-8")
    return [k for k in entfernt if k in raus]


# ================================================================ Profil
def _ko(profil):
    return Path(profil) / "koreader"


def _schriften(profil):
    return Path(profil) / "share" / "fonts"


def _leeren(p):
    if p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()


def _marke_schreiben(profil, daten):
    alt = _marke_lesen(profil)
    alt.update(daten)
    Path(profil).mkdir(parents=True, exist_ok=True)
    (Path(profil) / MARKE).write_text(json.dumps(alt, ensure_ascii=False, indent=1), encoding="utf-8")


def _marke_lesen(profil):
    for name in (MARKE, MARKE_ALT):
        try:
            return json.loads((Path(profil) / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


def _bereinigen(profil):
    """Einstellungen fürs Profil zurechtrücken. Buchdaten immer neben dem Buch, weil
    die Vorschau das Buch samt .sdr in buecher/ kopiert."""
    return einstellungen_anpassen(_ko(profil) / "settings.reader.lua",
                                  setzen={"home_dir": str(Path(profil) / "buecher"),
                                          "document_metadata_folder": "doc"})


def eigene_plugins(plugin_ordner):
    try:
        return sorted(p for p in Path(plugin_ordner).iterdir()
                      if p.is_dir() and p.name.endswith(".koplugin") and p.name[:-9] not in EINGEBAUT)
    except OSError:
        return []


def vom_geraet(wurzel, profil, info=None):
    """Baut das Profil aus dem angeschlossenen E-Reader neu auf. Gibt profil_stand() zurück."""
    wurzel, profil = Path(wurzel), Path(profil)
    art = kg.art_von(wurzel)
    quelle = wurzel / kg.ko_ordner(art)
    if not quelle.is_dir():
        raise RuntimeError(_("KOReader is not installed on the {geraet} ({ordner} is missing).").format(
            geraet=kg.art_name(art), ordner=kg.ko_ordner(art)))
    ko = _ko(profil)
    _leeren(ko)
    _leeren(_schriften(profil))
    ko.mkdir(parents=True)
    for name in ("settings.reader.lua", "defaults.custom.lua"):
        if (quelle / name).is_file():
            shutil.copy2(quelle / name, ko / name)
    for name in ("settings", "styletweaks", "patches"):
        if (quelle / name).is_dir():
            shutil.copytree(quelle / name, ko / name)
    for p in eigene_plugins(quelle / "plugins"):
        shutil.copytree(p, ko / "plugins" / p.name)
    # Schriften: KOReaders eigener Ordner und die Schriftordner des Geräts (kg.ARTEN, z. B. /fonts
    # im Hauptverzeichnis = EXT_FONT_DIR auf Kobo und Kindle). Die mitgelieferten stehen dann
    # doppelt da - schadet nicht, die Datei ist dieselbe.
    ziel = _schriften(profil)
    ziel.mkdir(parents=True, exist_ok=True)
    ordner_liste = [(quelle / "fonts", "koreader")] + [(wurzel / rel, "geraet" if i == 0 else f"geraet{i + 1}")
                                                       for i, rel in enumerate(kg.ARTEN[art]["schriften"])]
    for ordner, unter in ordner_liste:
        if ordner.is_dir():
            shutil.copytree(ordner, ziel / unter, dirs_exist_ok=True)
    entfernt = _bereinigen(profil)
    g = info or {}
    _marke_schreiben(profil, {"quelle": "kobo", "datum": datetime.now().isoformat(timespec="seconds"),
                              "geraet": dict({k: g.get(k, "") for k in ("modell", "modellnummer", "seriennummer",
                                                                         "koreader")}, art=art),
                              "sicherung": "", "entfernt": entfernt, "plugins_von": "kobo",
                              "bookbench_geaendert": []})
    return profil_stand(profil)


def aus_sicherung(zip_pfad, profil):
    """Übernimmt Einstellungen, settings/, styletweaks/ und patches/ aus einer Sicherung.
    Plugins und Schriften bleiben, wie sie sind (stehen in keiner Sicherung)."""
    profil = Path(profil)
    ko = _ko(profil)
    with zipfile.ZipFile(zip_pfad) as z:
        namen = [n for n in z.namelist() if not n.endswith("/")]
        try:                                            # Gerät laut Inhaltsverzeichnis der Sicherung
            geraet = kg.inhalt_lesen(z).get("geraet") or {}
        except (KeyError, ValueError):
            geraet = {}
        art = kg.sicherung_art({"geraet": geraet}, namen)
        geraet = dict(geraet, art=art)
        praefix = kg.ko_ordner(art) + "/"
        passend = [n for n in namen if n.startswith(praefix) and any(
            n[len(praefix):] == p or (p.endswith("/") and n[len(praefix):].startswith(p)) for p in SICHERUNG_PFADE)]
        if not passend:
            raise RuntimeError(_("The backup contains no KOReader settings."))
        # nur ersetzen, was die Sicherung auch mitbringt
        for name in ("settings", "styletweaks", "patches"):
            if any(n.startswith(f"{praefix}{name}/") for n in passend):
                _leeren(ko / name)
        ko_basis = ko.resolve()
        for n in passend:
            ziel = (ko / n[len(praefix):]).resolve()
            if not ziel.is_relative_to(ko_basis):          # keine Pfade außerhalb
                continue
            ziel.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as q, open(ziel, "wb") as f:
                shutil.copyfileobj(q, f)
    entfernt = _bereinigen(profil)
    _marke_schreiben(profil, {"quelle": "sicherung", "datum": datetime.now().isoformat(timespec="seconds"),
                              "sicherung": Path(zip_pfad).name, "entfernt": entfernt, "geraet": geraet,
                              "bookbench_geaendert": []})
    return profil_stand(profil)


def _zaehlen(ordner, endungen=None, muster="*"):
    try:
        return sum(1 for p in Path(ordner).rglob(muster)
                   if p.is_file() and (endungen is None or p.suffix.lower() in endungen))
    except OSError:
        return 0


def profil_stand(profil):
    profil = Path(profil)
    ko = _ko(profil)
    m = _marke_lesen(profil)
    return {
        "vorhanden": (ko / "settings.reader.lua").is_file(),
        "quelle": m.get("quelle", ""), "datum": m.get("datum", ""), "geraet": m.get("geraet") or {},
        "sicherung": m.get("sicherung", ""), "plugins_von": m.get("plugins_von", ""),
        "plugins": [p.name[:-9] for p in eigene_plugins(ko / "plugins")],
        "schriften": _zaehlen(_schriften(profil), SCHRIFT_ENDUNGEN),
        "patches": _zaehlen(ko / "patches", {".lua"}) - (ko / "patches" / DESKTOP_PATCH).is_file(),
        "styletweaks": _zaehlen(ko / "styletweaks", {".css"}),
        "bookends_vorlagen": _zaehlen(ko / "settings" / "bookends_presets", {".lua"}),
        "bookends_aktiv": (ko / "settings" / "bookends.lua").is_file(),
        "entfernt": m.get("entfernt") or [],
    }


# ================================================================ Buchdaten
# Buchdaten in einer Sicherung liegen neben den Büchern, nicht in einem KOReader-Ordner
_KO_PRAEFIXE = tuple({".adds/"} | {kg.ko_ordner(a) + "/" for a in kg.ARTEN})


def _sdr_name(buch):
    return Path(buch).stem + ".sdr"


def sdr_finden(buch, kobo_wurzel=None, sicherung=None):
    """Wo liegen KOReaders Buchdaten (Schriftgröße, Ränder, Position) zum Buch?
    Reihenfolge: neben dem Buch, auf dem angeschlossenen Gerät (gleicher Dateiname),
    in der Sicherung. Gibt ("ordner", Pfad) / ("zip", zip, Präfix) / None zurück."""
    buch = Path(buch)
    daneben = buch.with_name(_sdr_name(buch))
    if daneben.is_dir():
        return ("ordner", daneben)
    name = _sdr_name(buch)
    if kobo_wurzel and Path(kobo_wurzel).is_dir():
        for rel in kg._sdr_ordner(kobo_wurzel):
            if rel.rsplit("/", 1)[-1] == name:
                return ("ordner", Path(kobo_wurzel) / rel)
    if sicherung:
        try:
            with zipfile.ZipFile(sicherung) as z:
                for n in z.namelist():
                    teile = n.split("/")
                    if len(teile) >= 2 and teile[-2] == name and not n.startswith(_KO_PRAEFIXE):
                        return ("zip", str(sicherung), "/".join(teile[:-1]) + "/")
        except (OSError, zipfile.BadZipFile):
            pass
    return None


def _sdr_kopieren(sdr, ziel):
    if not sdr:
        return
    if sdr[0] == "ordner":
        shutil.copytree(sdr[1], ziel, dirs_exist_ok=True)
        return
    __, zip_pfad, praefix = sdr
    ziel.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_pfad) as z:
        for n in z.namelist():
            if n.startswith(praefix) and not n.endswith("/") and "/" not in n[len(praefix):]:
                with z.open(n) as q, open(ziel / n[len(praefix):], "wb") as f:
                    shutil.copyfileobj(q, f)


# ================================================================ Starten
def bildschirm(einstellung="auto", eigen=None, profil_geraet=None, kobo_info=None):
    """Welcher Bildschirm nachgebildet wird: dict mit name, w, h, dpi, farbe, quelle.
    einstellung: "auto", eine Modellnummer ("390") oder "eigen" (dann eigen = (w, h, dpi, farbe)).
    Automatisch: das Gerät, von dem das Profil stammt, sonst das angeschlossene, sonst
    STANDARD - quelle sagt dann "standard", die Oberfläche weist darauf hin."""
    if einstellung == "eigen" and eigen:
        w, h, dpi, farbe = eigen
        return {"name": _("Own size"), "w": int(w), "h": int(h), "dpi": int(dpi), "farbe": bool(farbe),
                "quelle": "eigen"}
    m = km.modell(einstellung) if einstellung not in ("auto", "eigen") else None
    if m:
        return dict(m, quelle="einstellung")
    for quelle, g in (("profil", profil_geraet), ("kobo", kobo_info)):
        m = km.modell((g or {}).get("modellnummer"))
        if m:
            return dict(m, quelle=quelle)
    return dict(km.modell(km.STANDARD), quelle="standard")


def groesse(name, bildschirm_hoehe=1080, bs=None):
    """(Breite, Höhe, DPI) des Fensters. bs: bildschirm(); ohne: Standardgerät.
    "passend": so hoch, wie der Bildschirm erlaubt; KOReader skaliert nach DPI, das
    Seitenbild bleibt also gleich, nur gröber."""
    bs = bs or km.modell(km.STANDARD)
    bw, bh, bdpi = bs["w"], bs["h"], bs["dpi"]
    if name == "voll":
        return bw, bh, bdpi
    if name == "halb":
        return bw // 2, bh // 2, bdpi // 2
    h = max(min(600, bh), min(bh, int(bildschirm_hoehe) - 160))
    return round(h * bw / bh), h, round(bdpi * h / bh)


def umgebung(profil, w, h, dpi, sw=False):
    v = {"KO_HOME": str(_ko(profil)), "XDG_DATA_HOME": str(Path(profil) / "share"),
         "EMULATE_READER_W": str(w), "EMULATE_READER_H": str(h), "EMULATE_READER_DPI": str(dpi)}
    if sw:
        v["EMULATE_BW_SCREEN"] = "1"
    return v


def befehl(befund, profil, variablen, buch):
    if befund["art"] == "flatpak":
        return (["flatpak", "run", f"--filesystem={profil}"] + [f"--env={k}={v}" for k, v in variablen.items()]
                + [FLATPAK_ID, str(buch)])
    return [befund["pfad"], str(buch)]


def buch_bereitstellen(profil, buch, sdr=None):
    """Kopiert das Buch (und seine .sdr) nach <profil>/buecher. Die Vorschau arbeitet so nie
    auf dem Original: KOReader schreibt beim Lesen in die .sdr."""
    ziel = Path(profil) / "buecher"
    _leeren(ziel)
    ziel.mkdir(parents=True)
    kopie = ziel / Path(buch).name
    shutil.copy2(buch, kopie)
    _sdr_kopieren(sdr, ziel / _sdr_name(buch))
    return kopie


def starten(befund, profil, buch, w, h, dpi, sdr=None, sw=False):
    """Startet KOReader mit dem Buch im Profil. Gibt den Prozess zurück."""
    if not befund:
        raise RuntimeError(_("Desktop KOReader not found."))
    profil = Path(profil)
    if not (_ko(profil) / "settings.reader.lua").is_file():
        raise RuntimeError(_("The profile is empty: take it from the e-reader or from a backup first."))
    _bereinigen(profil)                      # KOReader könnte beim letzten Lauf etwas zurückgeschrieben haben
    desktop_patch_schreiben(profil)          # Geräteerkennung: Rechner nicht für einen E-Reader halten
    kopie = buch_bereitstellen(profil, buch, sdr)
    variablen = umgebung(profil, w, h, dpi, sw)
    env = dict(os.environ, **variablen)
    if befund["art"] == "appimage":
        p = Path(befund["pfad"])
        if not os.access(p, os.X_OK):
            p.chmod(p.stat().st_mode | stat.S_IXUSR)
    log = open(profil / LOG, "w", encoding="utf-8", errors="replace")
    try:
        return subprocess.Popen(befehl(befund, profil, variablen, kopie), env=env, cwd=profil, stdout=log,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        raise RuntimeError(_("KOReader could not be started: {fehler}").format(fehler=e))
    finally:
        log.close()                          # der Prozess hat seine eigene Kopie des Dateigriffs


_WARNUNG = re.compile(r"\b(ERROR|WARN)\b")


def protokoll(profil, zeilen=40):
    """(letzte Zeilen, Anzahl Warnungen/Fehler, Zeilen mit Warnungen) aus KOReaders Ausgabe."""
    try:
        text = (Path(profil) / LOG).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", 0, []
    alle = text.splitlines()
    warn = [z for z in alle if _WARNUNG.search(z)]
    return "\n".join(alle[-zeilen:]), len(warn), warn[-10:]
