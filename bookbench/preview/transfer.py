# -*- coding: utf-8 -*-
"""
transfer.py - Rückweg vom Vorschau-Profil auf den E-Reader (seit 1.4-beta6). Nur Logik; das Fenster
steht in ui/transfer_window.py.

Drei Stände:
  Basis     was beim Holen des Profils auf dem E-Reader stand (<profil>/basis, angelegt von
            emulator.vom_geraet/aus_sicherung; Profile von vor 1.4-beta6 haben keine)
  Profil    <profil>/koreader, mit allem, was Bookbench gespeichert hat
  E-Reader  <wurzel>/<KOReader-Ordner> des angeschlossenen Geräts

Vorgeschlagen wird, was sich im Profil gegenüber der Basis geändert hat. Hat sich dasselbe auch auf
dem E-Reader geändert (dort gegenüber der Basis), ist es ein Konflikt: angezeigt, aber nicht
vorausgewählt. Ohne Basis wird nur Profil gegen E-Reader verglichen, dann ist nichts vorausgewählt
außer Bereichen, die Bookbench als geändert vermerkt hat.

Was verglichen wird (BEREICHE): Bookends (settings/bookends.lua, settings/bookends_presets/),
Bookshelf (settings/bookshelf/), Patches (patches/), Stil-Anpassungen (styletweaks/), Bilder des
Sperrbildschirms (screensaver/, seit 1.4-beta8), KOReaders
Einstellungen (settings.reader.lua) Schlüssel für Schlüssel. Datenbanken (*.sqlite3), Sicherungen
(*.old) und Bookbenchs eigene Patches nie. Bei settings.reader.lua nie die gerätebezogenen Schlüssel
(NIE: Bildschirm-DPI, Pfade, Frontlicht, WLAN, letzte Dateien …) und keine, die Bookbench beim Holen
ohnehin entfernt (emulator.RAUS).

Seit 2.2-beta5 auch der Weg aus dem KOReader-Fenster („In KOReader öffnen“) ins Profil: start_merken,
fenster_vergleichen, fenster_uebernehmen (unten).
"""
import fnmatch
import shutil
from pathlib import Path

from bookbench.core import lua_data
from bookbench.device import device as kg
from bookbench.preview import emulator as kv
from bookbench.preview import koreader_settings as kks
from bookbench.preview import plugins as kpl
from bookbench.i18n import N_, _

BASIS = "basis"
BEREICHE = (("bookends", N_("Bookends"), ("settings/bookends.lua", "settings/bookends_presets/")),
            ("bookshelf", N_("Bookshelf"), ("settings/bookshelf/",)),
            ("patches", N_("Patches"), ("patches/",)),
            ("styletweaks", N_("Style tweaks"), ("styletweaks/",)),
            ("sperrbildschirm", N_("Sleep screen images"), ("screensaver/",)),
            ("lesen", N_("KOReader settings"), ("settings.reader.lua",)))
# Profil-Marke bookbench_geaendert -> Bereich
MARKE_BEREICH = {"bookends": "bookends", "bookshelf": "bookshelf", "patches": "patches", "lesen": "lesen",
                 "sperrbildschirm": "lesen", "sperrbildschirm_bilder": "sperrbildschirm"}
NIE_DATEIEN = ("*.sqlite3", "*.sqlite3-*", "*.old", "*.tmp", "*bookbench-desktop*", "*bookbench-workbench*",
               "*bookbench-probe*")
NIE = ("screen_dpi", "extra_plugin_paths", "lastfile", "lastdir", "home_dir", "last_*", "frontlight*", "fl_*",
       "is_frontlight_on", "*wifi*", "*wlan*", "auto_restore_wifi", "device_*", "dev_*", "quickstart*",
       "*migration*", "battery*", "usbms*", "kobo_*", "kindle_*", "pocketbook_*", "document_metadata_folder",
       "start_with", "fm_rotation_mode", "folder_shortcuts", "collate*", "reverse_collate", "history*",
       "plugins_disabled", "ota_*", "lastfile_*", "time_*", "screensaver_cycle_index")
BASIS_GROESSE = 20 * 1024 * 1024                  # größere Dateien (Bilder …) nicht in die Basis


def nie(schluessel, eigene=()):
    return any(fnmatch.fnmatch(schluessel, m) for m in NIE + tuple(kv.RAUS) + tuple(eigene))


def _nie_datei(rel):
    return any(fnmatch.fnmatch(Path(rel).name, m) for m in NIE_DATEIEN)


def _dateien(ko, muster):
    """{relpfad: Path} der Dateien eines Bereichs unter ko."""
    erg = {}
    ko = Path(ko)
    for m in muster:
        if m.endswith("/"):
            d = ko / m
            for p in d.rglob("*") if d.is_dir() else []:
                rel = p.relative_to(ko).as_posix()
                if p.is_file() and not _nie_datei(rel):
                    erg[rel] = p
        elif (ko / m).is_file():
            erg[m] = ko / m
    return erg


# ================================================================ Basis
def basis_ordner(profil):
    return Path(profil) / BASIS


def basis_anlegen(profil):
    """Stand des Profils direkt nach dem Holen als Basis festhalten (nur die verglichenen Dateien)."""
    profil = Path(profil)
    ko, ziel = kv._ko(profil), basis_ordner(profil)
    kv._leeren(ziel)
    ziel.mkdir(parents=True)
    for __, __, muster in BEREICHE:
        for rel, p in _dateien(ko, muster).items():
            try:
                if p.stat().st_size > BASIS_GROESSE:
                    continue
                (ziel / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, ziel / rel)
            except OSError:
                continue


def hat_basis(profil):
    return basis_ordner(profil).is_dir()


# ================================================================ Vergleich
def _gleich(a, b):
    if a is None or b is None:
        return a is None and b is None
    try:
        return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def _eintraege(pfad):
    """settings.reader.lua: {schlüssel: eintragstext} (wörtlich, wie luasettings sie schreibt)."""
    try:
        return dict(kv.lua_zerlegen(Path(pfad).read_text(encoding="utf-8"))[1])
    except OSError:
        return {}


def _wert(eintrag):
    """Lesbarer Wert eines settings.reader.lua-Eintrags (für die Anzeige)."""
    if eintrag is None:
        return None
    try:
        return lua_data.lesen("return { " + eintrag.split("=", 1)[1].strip().rstrip(",") + " }")[0]
    except (lua_data.LuaFehler, IndexError):
        return eintrag.split("=", 1)[-1].strip().rstrip(",")


def wert_text(w):
    if w is None:
        return "-"
    if isinstance(w, (dict, list)):
        t = lua_data.schreiben(w).replace("\n", " ")
        return t if len(t) <= 60 else t[:57] + "…"
    return kks.wert_text(w)


def vergleichen(profil, wurzel, eigene_nie=()):
    """[{"bereich", "art" (datei|schluessel), "name", "status" (neu|geaendert|entfernt), "konflikt",
    "vorschlag" (vorausgewählt), "profil", "geraet" (Anzeige)}] - alles, was sich übertragen ließe."""
    profil, wurzel = Path(profil), Path(wurzel)
    ko_p = kv._ko(profil)
    ko_g = wurzel / kg.ko_ordner(kg.art_von(wurzel))
    basis = basis_ordner(profil) if hat_basis(profil) else None
    markiert = {MARKE_BEREICH.get(m) for m in kpl.profil_geaendert(profil)}
    erg = []
    for bereich, __, muster in BEREICHE:
        if bereich == "lesen":
            erg += _schluessel_vergleichen(ko_p, ko_g, basis, bereich in markiert, eigene_nie)
            continue
        p_d, g_d = _dateien(ko_p, muster), _dateien(ko_g, muster)
        b_d = _dateien(basis, muster) if basis else {}
        for rel in sorted(set(p_d) | set(g_d)):
            pp, gp, bp = p_d.get(rel), g_d.get(rel), b_d.get(rel)
            if _gleich(pp, gp):
                continue
            if basis is not None:
                im_profil = not _gleich(pp, bp)             # im Profil geändert (gegenüber dem Holen)
                if not im_profil:
                    continue                                # nur auf dem E-Reader geändert: nicht anfassen
                konflikt = not _gleich(gp, bp)
                if bp is None and pp is None:
                    continue
            else:
                konflikt = False
            status = "neu" if gp is None else ("entfernt" if pp is None else "geaendert")
            vorschlag = (not konflikt) if basis is not None else (bereich in markiert)
            erg.append({"bereich": bereich, "art": "datei", "name": rel, "status": status, "konflikt": konflikt,
                        "vorschlag": vorschlag, "profil": _groesse(pp), "geraet": _groesse(gp)})
    return erg


def _groesse(p):
    if p is None:
        return "-"
    try:
        return kg.groesse_text(p.stat().st_size)
    except OSError:
        return "?"


def _schluessel_vergleichen(ko_p, ko_g, basis, markiert, eigene_nie):
    p_e = _eintraege(ko_p / "settings.reader.lua")
    g_e = _eintraege(ko_g / "settings.reader.lua")
    b_e = _eintraege(basis / "settings.reader.lua") if basis else None
    erg = []
    for k in sorted(set(p_e) | set(g_e)):
        if nie(k, eigene_nie):
            continue
        pv, gv = p_e.get(k), g_e.get(k)
        if pv == gv or _wert(pv) == _wert(gv):
            continue
        if b_e is not None:
            bv = b_e.get(k)
            if pv == bv or _wert(pv) == _wert(bv):
                continue                                    # im Profil unverändert
            konflikt = not (gv == bv or _wert(gv) == _wert(bv))
        else:
            if pv is None:
                continue                                    # ohne Basis keine Löschungen vorschlagen
            konflikt = False
        status = "neu" if gv is None else ("entfernt" if pv is None else "geaendert")
        vorschlag = (not konflikt) if b_e is not None else markiert
        erg.append({"bereich": "lesen", "art": "schluessel", "name": k, "status": status, "konflikt": konflikt,
                    "vorschlag": vorschlag, "profil": wert_text(_wert(pv)), "geraet": wert_text(_wert(gv))})
    return erg


# ================================================================ Übertragen
SICHERUNG_TEILE = ("einstellungen", "settings", "anpassungen")


def uebertragen(profil, wurzel, auswahl, sicherungsordner=None, info=None, anzahl=10):
    """Gewählte Einträge (aus vergleichen()) auf den E-Reader schreiben, vorher sichern (wenn ein
    Sicherungsordner angegeben ist). Danach steht der übertragene Stand auch in der Basis.
    Gibt (Anzahl, Pfad der Sicherung oder None) zurück."""
    profil, wurzel = Path(profil), Path(wurzel)
    ko_p = kv._ko(profil)
    ko_g = wurzel / kg.ko_ordner(kg.art_von(wurzel))
    sicherung = None
    if sicherungsordner and auswahl:
        vorhanden = [t for t in SICHERUNG_TEILE if t in kg.teile_ermitteln(wurzel)]
        if vorhanden:
            sicherung = kg.sichern(wurzel, sicherungsordner, vorhanden, info, anzahl + 1, anlass="vor_rueckweg")
    basis = basis_ordner(profil)
    n = 0
    schluessel = [e for e in auswahl if e["art"] == "schluessel"]
    for e in auswahl:
        if e["art"] != "datei":
            continue
        quelle, ziel = ko_p / e["name"], ko_g / e["name"]
        if e["status"] == "entfernt":
            if ziel.exists():
                ziel.unlink()
            if (basis / e["name"]).exists():
                (basis / e["name"]).unlink()
        else:
            ziel.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(quelle, ziel)
            if basis.is_dir():
                (basis / e["name"]).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(quelle, basis / e["name"])
        n += 1
    if schluessel:
        n += _schluessel_schreiben(ko_p / "settings.reader.lua", ko_g / "settings.reader.lua", schluessel)
        if basis.is_dir():
            _schluessel_schreiben(ko_p / "settings.reader.lua", basis / "settings.reader.lua", schluessel)
    _marke_pruefen(profil, wurzel)
    return n, sicherung


def _schluessel_schreiben(quelle, ziel, eintraege):
    """Einträge wörtlich aus der Profil-Datei in die Ziel-Datei übernehmen (bzw. dort löschen); der Rest
    der Ziel-Datei bleibt, wie er ist."""
    p_e = _eintraege(quelle)
    try:
        text = Path(ziel).read_text(encoding="utf-8")
    except OSError:
        text = "-- we can read Lua syntax here!\nreturn {\n}\n"
    kopf, liste, fuss = kv.lua_zerlegen(text)
    neu = dict(liste)
    n = 0
    for e in eintraege:
        k = e["name"]
        if e["status"] == "entfernt" or k not in p_e:
            if neu.pop(k, None) is not None:
                n += 1
        else:
            neu[k] = p_e[k]
            n += 1
    Path(ziel).parent.mkdir(parents=True, exist_ok=True)
    Path(ziel).write_text(kopf + "".join(neu[k] for k in sorted(neu)) + (fuss or "}\n"), encoding="utf-8")
    return n


def _marke_pruefen(profil, wurzel):
    """Bereiche ohne offene Unterschiede (auch keine Konflikte) aus der Profil-Marke bookbench_geaendert nehmen."""
    offen = {e["bereich"] for e in vergleichen(profil, wurzel)}      # auch Konflikte: noch nicht auf dem Gerät
    alt = kpl.profil_geaendert(profil)
    neu = [m for m in alt if MARKE_BEREICH.get(m) in offen]
    if neu != alt:
        kv._marke_schreiben(profil, {"bookbench_geaendert": neu})


def bereich_name(bereich):
    return _(dict((k, n) for k, n, __ in BEREICHE).get(bereich, bereich))


# ================================================================ Aus dem KOReader-Fenster ins Profil (seit 2.2-beta5)
# „In KOReader öffnen“ läuft auf der Wegwerf-Kopie vorschau/fenster/koreader. Nach dem Einrichten (Entwürfe drin,
# Bookbenchs eigene Anpassungen gemacht), aber vor dem Start merkt start_merken() die Dateien der BEREICHE in
# vorschau/fenster/start. Nach dem Schließen zeigt fenster_vergleichen(), was KOReader seitdem geändert hat: das sind
# die Änderungen aus den Menüs. Einstellungsdateien (LuaSettings) Schlüssel für Schlüssel, ohne die Schlüssel, die
# KOReader bzw. die Plugins im Betrieb selbst schreiben.
FENSTER_START = "start"
SCHLUESSEL_DATEIEN = {"settings.reader.lua": "lesen", "settings/bookends.lua": "bookends",
                      "settings/bookshelf/settings.lua": "bookshelf"}
FENSTER_NIE = {"settings.reader.lua": ("quickstart_shown_version", "font_size_*_cache", "cre_font_*_cache",
                                       "font_info_*", "deprecation_*", "sdl_window", "terminal_*",
                                       "httpinspector_*", "emulator_*", "window_*"),
               # bookends.lua hält die aktive Vorlage live gespiegelt (pos_*, progress_bar_*, defaults): die
               # Änderung steht in der Vorlagendatei, die angeboten wird
               "settings/bookends.lua": ("*migrat*", "*_done", "*promoted*", "last_*", "bookends_version",
                                         "dev_branch", "*_seeded", "schema_version", "pos_*", "progress_bar_*",
                                         "font_face", "font_size", "font_bold", "font_scale", "margin_*",
                                         "overlap_gap", "truncation_priority", "text_color", "symbol_color",
                                         "background_color*"),
               "settings/bookshelf/settings.lua": tuple(kpl.BOOKSHELF_INTERN) + ("*_seeded", "*migrated*",
                                                                                  "*cache*", "last_*")}
# Dateien, die Bookshelf im Betrieb selbst anlegt (Zustand, Zwischenspeicher): nie aus dem Fenster anbieten
FENSTER_NIE_DATEIEN = ("start_trip", "bytecode_off", "*.dat", "*.cache", "*cache*", "*.zst", "*.json.tmp")
MARKE_VON_BEREICH = {"bookends": "bookends", "bookshelf": "bookshelf", "patches": "patches", "lesen": "lesen",
                     "sperrbildschirm": "sperrbildschirm_bilder"}


def _alle_muster():
    return [m for __, __, muster in BEREICHE for m in muster]


def start_merken(arbeit):
    """Stand der Kopie vor dem Start des Fensters merken (nur die Dateien der BEREICHE)."""
    arbeit = Path(arbeit)
    ziel = arbeit / FENSTER_START
    if ziel.exists():
        shutil.rmtree(ziel)
    for rel, p in _dateien(arbeit / "koreader", _alle_muster()).items():
        if _groesse_ok(p):
            (ziel / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, ziel / rel)
    ziel.mkdir(parents=True, exist_ok=True)


def _groesse_ok(p):
    try:
        return p.stat().st_size <= BASIS_GROESSE
    except OSError:
        return False


def hat_fensterstand(arbeit):
    return (Path(arbeit) / FENSTER_START).is_dir() and (Path(arbeit) / "koreader").is_dir()


def fenster_vergleichen(profil, arbeit, eigene_nie=()):
    """Änderungen im KOReader-Fenster: [{"bereich", "art", "datei", "name", "status", "konflikt", "vorschlag",
    "profil", "geraet"}] wie vergleichen(); "geraet" ist hier der Wert im Fenster, status bezieht sich aufs Fenster
    (neu = im Fenster angelegt). Konflikt: auch im Profil seit dem Start geändert (z. B. inzwischen gespeichert)."""
    arbeit = Path(arbeit)
    if not hat_fensterstand(arbeit):
        return []
    ko_k, start, ko_p = arbeit / "koreader", arbeit / FENSTER_START, kv._ko(profil)
    erg = []
    for bereich, __, muster in BEREICHE:
        k_d, s_d, p_d = _dateien(ko_k, muster), _dateien(start, muster), _dateien(ko_p, muster)
        for rel in sorted(set(k_d) | set(s_d)):
            kp, sp, pp = k_d.get(rel), s_d.get(rel), p_d.get(rel)
            if rel in SCHLUESSEL_DATEIEN:
                erg += _fenster_schluessel(rel, SCHLUESSEL_DATEIEN[rel], kp, sp, pp, eigene_nie)
                continue
            if any(fnmatch.fnmatch(Path(rel).name, m) for m in FENSTER_NIE_DATEIEN):
                continue
            if _gleich(kp, sp) or (kp is not None and not _groesse_ok(kp)) or _lua_gleich(rel, kp, sp):
                continue
            konflikt = not _gleich(pp, sp)
            status = "neu" if sp is None else ("entfernt" if kp is None else "geaendert")
            erg.append({"bereich": bereich, "art": "datei", "datei": rel, "name": rel, "status": status,
                        "konflikt": konflikt, "vorschlag": not konflikt, "profil": _groesse(pp), "geraet": _groesse(kp)})
    return erg


def _lua_gleich(rel, a, b):
    """Lua-Daten (Vorlagen, Plugin-Einstellungen; keine Patches) inhaltlich gleich, nur anders geschrieben?"""
    if a is None or b is None or not rel.endswith(".lua") or rel.startswith("patches/"):
        return False
    try:
        return lua_data.datei_lesen(a) == lua_data.datei_lesen(b)
    except (OSError, lua_data.LuaFehler):
        return False


def _fenster_schluessel(rel, bereich, kp, sp, pp, eigene_nie):
    k_e = _eintraege(kp) if kp else {}
    s_e = _eintraege(sp) if sp else {}
    p_e = _eintraege(pp) if pp else {}
    extra = FENSTER_NIE.get(rel, ()) + tuple(eigene_nie)          # „Nie anbieten“ gilt für alle Einstellungsdateien
    erg = []
    for k in sorted(set(k_e) | set(s_e)):
        if (rel == "settings.reader.lua" and nie(k, extra)) or any(fnmatch.fnmatch(k, m) for m in extra):
            continue
        kv_, sv = k_e.get(k), s_e.get(k)
        if kv_ == sv or _wert(kv_) == _wert(sv):
            continue
        pv = p_e.get(k)
        konflikt = not (pv == sv or _wert(pv) == _wert(sv))
        status = "neu" if sv is None else ("entfernt" if kv_ is None else "geaendert")
        name = k if rel == "settings.reader.lua" else f"{rel.rsplit('/', 1)[-1]}: {k}"
        erg.append({"bereich": bereich, "art": "schluessel", "datei": rel, "schluessel": k, "name": name,
                    "status": status, "konflikt": konflikt, "vorschlag": not konflikt,
                    "profil": wert_text(_wert(pv)), "geraet": wert_text(_wert(kv_))})
    return erg


def fenster_uebernehmen(profil, arbeit, auswahl):
    """Gewählte Änderungen aus dem Fenster ins Profil schreiben (und in den Startstand, damit sie nicht wieder
    angeboten werden); Profil-Marke für den Rückweg setzen. Gibt die Anzahl zurück."""
    arbeit = Path(arbeit)
    ko_k, start, ko_p = arbeit / "koreader", arbeit / FENSTER_START, kv._ko(profil)
    n = 0
    for e in auswahl:
        if e["art"] != "datei":
            continue
        for ziel in (ko_p / e["datei"], start / e["datei"]):
            if e["status"] == "entfernt":
                if ziel.exists():
                    ziel.unlink()
            else:
                ziel.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ko_k / e["datei"], ziel)
        n += 1
    nach_datei = {}
    for e in auswahl:
        if e["art"] == "schluessel":
            nach_datei.setdefault(e["datei"], []).append({"name": e["schluessel"], "status": e["status"]})
    for rel, eintraege in nach_datei.items():
        n += _schluessel_schreiben(ko_k / rel, ko_p / rel, eintraege)
        _schluessel_schreiben(ko_k / rel, start / rel, eintraege)
    for bereich in {e["bereich"] for e in auswahl}:
        if bereich in MARKE_VON_BEREICH:
            kpl._profil_geaendert(profil, MARKE_VON_BEREICH[bereich])
    return n
