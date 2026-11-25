# -*- coding: utf-8 -*-
"""
device.py - E-Reader mit KOReader am Rechner (Kobo, Kindle, PocketBook): finden,
KOReader-Einstellungen sichern und zurückspielen, Wörterbücher kopieren, auswerfen.
Keine Oberfläche.

  ARTEN                        Gerätearten: Name, KOReader-Ordner, Schriftordner
  geraeteart(pfad)             "kobo" / "kindle" / "pocketbook" oder None
  geraete_finden(zusaetzlich)  Wurzeln angeschlossener E-Reader
  geraet_info(wurzel)          Art, Modell (models), Seriennummer, Firmware, KOReader-Version, Platz
  TEILE, teile(art)            was eine Sicherung enthalten kann (Pfade je Geräteart)
  teile_ermitteln(wurzel)      je Teil die Dateien (relativ zur Wurzel) und Größe
  sichern(...)                 ZIP mit den gewählten Teilen und einem Inhaltsverzeichnis
  sicherungen(ordner)          vorhandene Sicherungen, neueste zuerst
  zurueckspielen(...)          gewählte Teile aus einer Sicherung aufs Gerät (auch auf eine andere Art)
  woerterbuecher(quelle, wurzel)  Stand je Wörterbuch (Quelle gegen Gerät)
  woerterbuch_kopieren(...)    ein Wörterbuch in <KOReader-Ordner>/data/dict/<Name>/
  auswerfen(wurzel)            Laufwerk abmelden (udisksctl bzw. Explorer); unter Linux bei
                               "busy" zweimal nach kurzer Pause noch einmal
  blockierer(wurzel)           Linux: Programme mit Dateien/Ordnern auf dem Gerät (aus /proc)
  verlauf_lesen(...)           KOReaders Nachschlageverlauf (Gerät oder neueste Sicherung)

Pfade in den Sicherungen sind relativ zur Wurzel des Geräts und mit "/" getrennt,
damit eine Sicherung von Windows auch unter Linux zurückgespielt werden kann.

Wo KOReader liegt (nachgesehen 18.11.2026 im KOReader-Quelltext, nicht geraten): der
Datenordner ist der Installationsordner (datastorage.lua, ohne KO_HOME). Installiert ist er
auf dem Kobo unter .adds/koreader (platform/kobo), auf dem Kindle unter koreader in der
Wurzel des USB-Laufwerks = /mnt/us (platform/kindle), auf dem PocketBook unter
/mnt/ext1/applications/koreader (platform/pocketbook/koreader.app, Laufwerk = /mnt/ext1).
Zusätzliche Schriften: Kobo /mnt/onboard/fonts, Kindle /mnt/us/fonts (EXT_FONT_DIR in den
Startskripten); PocketBook nutzt die Systemschriften (hasSystemFonts), eigene liegen dort
unter system/fonts (nicht im KOReader-Quelltext belegt, ungeprüft).
Neuere Kindles und Android-Geräte melden sich nur per MTP: kein Laufwerk, also nicht hier.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

from bookbench.device import models as km
from bookbench.i18n import N_, _

# Art: Name, KOReader-Ordner und Schriftordner relativ zur Wurzel (Quellen oben)
ARTEN = {
    "kobo": {"name": "Kobo", "koreader": ".adds/koreader", "schriften": ("fonts",)},
    "kindle": {"name": "Kindle", "koreader": "koreader", "schriften": ("fonts",)},
    "pocketbook": {"name": "PocketBook", "koreader": "applications/koreader", "schriften": ("system/fonts",)},
}
STANDARD_ART = "kobo"             # alte Sicherungen und Profile ohne Angabe
KOREADER = ARTEN["kobo"]["koreader"]
DICT = KOREADER + "/data/dict"
INHALT = "bookbench.json"                 # Inhaltsverzeichnis in jeder Sicherung
INHALT_ALT = "kobo-werkstatt.json"        # Name bis 0.24 (Kobo-Werkstatt)


def inhalt_lesen(z):
    """Inhaltsverzeichnis aus einer offenen Sicherung (neuer oder alter Name); KeyError, wenn keins da ist."""
    for name in (INHALT, INHALT_ALT):
        try:
            return json.loads(z.read(name).decode("utf-8"))
        except KeyError:
            continue
    raise KeyError(INHALT)
PRAEFIX = "KOReader_"


def ko_ordner(art):
    """KOReader-Ordner der Geräteart relativ zur Wurzel ("/" getrennt)."""
    return ARTEN.get(art or STANDARD_ART, ARTEN[STANDARD_ART])["koreader"]


def art_name(art):
    return ARTEN.get(art or STANDARD_ART, ARTEN[STANDARD_ART])["name"]


# (Schlüssel, Name, Beschreibung, Pfade relativ zur Wurzel, standardmäßig gewählt)
# "{ko}" steht für den KOReader-Ordner der Geräteart, "*.sdr" für alle Buchdaten-Ordner
# neben den Büchern. Teile in NUR_BEI gibt es nur bei dieser Geräteart.
TEILE = (
    ("einstellungen", N_("Settings"), "settings.reader.lua, defaults.custom.lua",
     ("{ko}/settings.reader.lua", "{ko}/defaults.custom.lua"), True),
    ("settings", N_("Statistics and plugin data"),
     N_("Folder settings: statistics, history, Bookends, Silverfish …"),
     ("{ko}/settings",), True),
    ("buchdaten", N_("Book data"), N_("Folders .sdr: reading position, highlights, notes"),
     ("*.sdr", "{ko}/docsettings", "{ko}/hashdocsettings"), True),
    ("anpassungen", N_("Style tweaks and patches"), N_("Folders styletweaks and patches"),
     ("{ko}/styletweaks", "{ko}/patches"), True),
    ("kobo", N_("Kobo settings"), N_("Kobo eReader.conf (only on a Kobo)"),
     (".kobo/Kobo/Kobo eReader.conf",), False),
)
NUR_BEI = {"kobo": "kobo"}
TEIL_NAME = {k: n for k, n, *__ in TEILE}       # N_()-Texte: bei der Anzeige _() drum


def teile(art=STANDARD_ART):
    """TEILE für eine Geräteart: {ko} aufgelöst, Teile anderer Arten weggelassen."""
    ko = ko_ordner(art)
    return tuple((k, n, b, tuple(p.replace("{ko}", ko) for p in pfade), std)
                 for k, n, b, pfade, std in TEILE if NUR_BEI.get(k, art) == art)


# Beim Durchsuchen nach .sdr-Ordnern in der Wurzel auslassen (dazu der KOReader-Ordner)
_NICHT_DURCHSUCHEN = {".kobo", ".kobo-images", ".adds", "System Volume Information", "$RECYCLE.BIN"}
_NICHT_DURCHSUCHEN_ART = {"kindle": {"system", "koreader"}, "pocketbook": {"system", "applications"}}


# ================================================================ Finden
def _laufwerke():
    """Mögliche Einhängepunkte von Wechseldatenträgern."""
    if sys.platform == "win32":
        try:
            import ctypes
            maske = ctypes.windll.kernel32.GetLogicalDrives()
            typ = ctypes.windll.kernel32.GetDriveTypeW
        except (AttributeError, OSError):
            return [Path(f"{b}:\\") for b in "DEFGHIJKLMNOPQRSTUVWXYZ"]
        erg = []
        for i in range(26):
            if maske >> i & 1:
                p = f"{chr(65 + i)}:\\"
                if typ(p) in (2, 3):                    # Wechseldatenträger, Festplatte (manche Kobos)
                    erg.append(Path(p))
        return erg
    erg = []
    benutzer = os.environ.get("USER") or ""
    for basis in (Path("/run/media") / benutzer, Path("/media") / benutzer, Path("/media"), Path("/mnt")):
        try:
            erg.extend(p for p in basis.iterdir() if p.is_dir())
        except OSError:
            pass
    return erg


def geraeteart(pfad):
    """Welche Art E-Reader hat hier seine Wurzel? "kobo", "kindle", "pocketbook" oder None.
    Kobo: Ordner .kobo (auch tolino ab 2024). PocketBook: applications/koreader oder
    applications + system/config (KOReader liest dort extensions.cfg). Kindle: documents +
    system (calibre: EBOOK_DIR_MAIN = documents, dazu system/thumbnails usw.)."""
    p = Path(pfad)
    try:
        if (p / ".kobo").is_dir():
            return "kobo"
        if (p / "applications" / "koreader").is_dir() or \
                ((p / "applications").is_dir() and (p / "system" / "config").is_dir()):
            return "pocketbook"
        if (p / "documents").is_dir() and (p / "system").is_dir():
            return "kindle"
    except OSError:
        pass
    return None


def ist_geraet(pfad):
    return geraeteart(pfad) is not None


def art_von(wurzel):
    """Geräteart der Wurzel, ohne Erkennung die Standardart (Kobo)."""
    return (geraeteart(wurzel) if wurzel else None) or STANDARD_ART


def ist_laufwerk(pfad):
    """Wurzel eines Datenträgers (Laufwerksbuchstabe bzw. Einhängepunkt). Ein echter E-Reader
    ist das immer; eine Kopie davon auf der Festplatte (mit .kobo-Ordner usw.) nie."""
    try:
        return os.path.ismount(pfad)
    except OSError:
        return False


def geraete_finden(zusaetzlich=()):
    """Wurzeln aller angeschlossenen E-Reader. zusaetzlich: Ordner, deren Wurzel auch
    geprüft wird (z. B. der geöffnete Bücherordner) - dann klappt es auch ohne
    Standard-Einhängepunkt. Ordner, die keine Laufwerkswurzel sind (Sicherungskopien),
    zählen nicht."""
    gefunden = []
    for p in list(_laufwerke()) + [Path(z) for z in zusaetzlich if z]:
        for kandidat in [p] + list(p.parents):
            if ist_geraet(kandidat) and ist_laufwerk(kandidat):
                if kandidat not in gefunden:
                    gefunden.append(kandidat)
                break
    return gefunden


def _lesen(pfad):
    try:
        return Path(pfad).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def geraet_info(wurzel):
    """Angaben zum Gerät als dict; fehlende Werte sind leer. Modell, Seriennummer und
    Firmware gibt es nur beim Kobo (.kobo/version), Kindle und PocketBook legen dafür
    nichts Lesbares aufs Laufwerk."""
    w = Path(wurzel)
    art = art_von(w)
    info = {"wurzel": str(w), "art": art, "artname": art_name(art), "seriennummer": "", "firmware": "",
            "modell": art_name(art), "modellnummer": "", "koreader": "", "frei": None, "gesamt": None}
    if art == "kobo":
        version = _lesen(w / ".kobo" / "version")
        felder = version.split(",")
        if len(felder) >= 3:
            info["seriennummer"], info["firmware"] = felder[0], felder[2]
            info["modellnummer"] = nr = km.modellnummer(version)
            m = km.modell(nr)
            # Unbekannt: Typenschild-Nummer vorn an der Seriennummer (N428) zeigen, die findet man im Netz
            info["modell"] = m["name"] if m else f"Kobo ({felder[0][:4] or nr or '?'})"
    ko = w / ko_ordner(art)
    if ko.is_dir():
        rev = _lesen(ko / "git-rev")
        info["koreader"] = rev.split("-")[0] if rev else _("installed")
    try:
        du = shutil.disk_usage(w)
        info["frei"], info["gesamt"] = du.free, du.total
    except OSError:
        pass
    return info


def groesse_text(n):
    if n is None:
        return "?"
    for einheit in ("B", "KB", "MB", "GB"):
        if n < 1024 or einheit == "GB":
            return f"{n:.0f} {einheit}" if einheit == "B" else f"{n:.1f} {einheit}"
        n /= 1024


# ================================================================ Sichern
def _dateien_unter(wurzel, rel):
    """Alle Dateien unter wurzel/rel (Datei oder Ordner), als relative Pfade mit "/"."""
    p = Path(wurzel) / rel
    if p.is_file():
        return [rel]
    if not p.is_dir():
        return []
    erg = []
    for ordner, __, dateien in os.walk(p):
        for d in dateien:
            erg.append(Path(ordner, d).relative_to(wurzel).as_posix())
    return erg


def _sdr_ordner(wurzel, art=None):
    """Alle .sdr-Ordner unter der Wurzel (relativ, "/" getrennt), ohne Systemordner und
    den KOReader-Ordner. Auf dem Kindle liegen dort auch die Kindle-eigenen Dateien
    (.azw3f usw.) - die kommen mit, schaden beim Zurückspielen nicht."""
    art = art or art_von(wurzel)
    auslassen = _NICHT_DURCHSUCHEN | _NICHT_DURCHSUCHEN_ART.get(art, set())
    erg = []
    for ordner, unter, __ in os.walk(wurzel):
        if Path(ordner) == Path(wurzel):
            unter[:] = [u for u in unter if u not in auslassen]
        for u in list(unter):
            if u.endswith(".sdr"):
                erg.append(Path(ordner, u).relative_to(wurzel).as_posix())
                unter.remove(u)
    return erg


def teile_ermitteln(wurzel):
    """{schlüssel: [relative Pfade]} für alle Teile, die es auf dem Gerät gibt."""
    erg = {}
    art = art_von(wurzel)
    for k, __, __, pfade, __ in teile(art):
        dateien = []
        for rel in pfade:
            if rel == "*.sdr":
                for s in _sdr_ordner(wurzel, art):
                    dateien.extend(_dateien_unter(wurzel, s))
            else:
                dateien.extend(_dateien_unter(wurzel, rel))
        if dateien:
            erg[k] = sorted(set(dateien))
    return erg


def summe(wurzel, dateien):
    n = 0
    for rel in dateien:
        try:
            n += (Path(wurzel) / rel).stat().st_size
        except OSError:
            pass
    return n


def _teil_von(rel, art=STANDARD_ART):
    """Zu welchem Teil gehört ein Pfad in einer Sicherung von dieser Geräteart?"""
    ko = ko_ordner(art) + "/"
    for k, __, __, pfade, __ in teile(art):
        for p in pfade:
            if p == "*.sdr":
                if any(s.endswith(".sdr") for s in rel.split("/")[:-1]) and not rel.startswith(ko) \
                        and not rel.startswith(".adds/"):
                    return k
            elif rel == p or rel.startswith(p + "/"):
                return k
    return None


def art_aus_namen(namen):
    """Geräteart einer Sicherung ohne Angabe im Inhaltsverzeichnis, an den Pfaden erkannt.
    Längster KOReader-Ordner zuerst (applications/koreader vor koreader)."""
    for art in sorted(ARTEN, key=lambda a: -len(ko_ordner(a))):
        ko = ko_ordner(art) + "/"
        if any(n.startswith(ko) for n in namen):
            return art
    return STANDARD_ART


def sicherung_art(inhalt, namen=()):
    """Geräteart einer Sicherung: Inhaltsverzeichnis (seit 0.26), sonst an den Pfaden."""
    art = ((inhalt or {}).get("geraet") or {}).get("art")
    return art if art in ARTEN else art_aus_namen(namen)


def sichern(wurzel, ziel_ordner, teile, info=None, anzahl=10, anlass=""):
    """Legt <ziel_ordner>/KOReader_JJJJMMTT_HHMMSS.zip an und gibt den Pfad zurück.
    teile: Schlüssel aus TEILE. Hält die neuesten `anzahl` Sicherungen."""
    ziel_ordner = Path(ziel_ordner)
    ziel_ordner.mkdir(parents=True, exist_ok=True)
    vorhanden = teile_ermitteln(wurzel)
    art = art_von(wurzel)
    stempel = datetime.now()
    ziel = ziel_ordner / f"{PRAEFIX}{stempel:%Y%m%d_%H%M%S}.zip"
    i = 1
    while ziel.exists():                                    # zwei Sicherungen in derselben Sekunde
        ziel = ziel_ordner / f"{PRAEFIX}{stempel:%Y%m%d_%H%M%S}_{i}.zip"
        i += 1
    inhalt = {"programm": "Bookbench", "datum": stempel.isoformat(timespec="seconds"),
              "anlass": anlass, "geraet": dict({k: (info or {}).get(k, "") for k in
                                                ("modell", "modellnummer", "seriennummer", "firmware",
                                                 "koreader")}, art=art),
              "teile": {}}
    tmp = ziel.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for k in teile:
            dateien = vorhanden.get(k, [])
            for rel in dateien:
                z.write(Path(wurzel) / rel, rel)
            inhalt["teile"][k] = {"dateien": len(dateien), "bytes": summe(wurzel, dateien)}
        z.writestr(INHALT, json.dumps(inhalt, ensure_ascii=False, indent=1))
    os.replace(tmp, ziel)
    _aufraeumen(ziel_ordner, anzahl)
    return ziel


def _aufraeumen(ordner, anzahl):
    alle = sicherungen(ordner)
    for s in alle[max(1, anzahl):]:
        try:
            Path(s["pfad"]).unlink()
        except OSError:
            pass


def sicherung_lesen(pfad):
    """Inhaltsverzeichnis einer Sicherung; fehlt es, wird es aus den Dateien ermittelt."""
    with zipfile.ZipFile(pfad) as z:
        namen = z.namelist()
        try:
            inhalt = inhalt_lesen(z)
        except (KeyError, ValueError):
            inhalt = {"teile": {}}
            art = art_aus_namen(namen)
            for zi in z.infolist():
                k = _teil_von(zi.filename, art)
                if k:
                    t = inhalt["teile"].setdefault(k, {"dateien": 0, "bytes": 0})
                    t["dateien"] += 1
                    t["bytes"] += zi.file_size
    inhalt["pfad"] = str(pfad)
    inhalt["art"] = sicherung_art(inhalt, namen)
    if not inhalt.get("datum"):
        m = re.search(r"(\d{8})_(\d{6})", Path(pfad).name)
        inhalt["datum"] = (datetime.strptime("".join(m.groups()), "%Y%m%d%H%M%S").isoformat()
                           if m else datetime.fromtimestamp(Path(pfad).stat().st_mtime).isoformat())
    return inhalt


def sicherungen(ordner):
    """Alle Sicherungen im Ordner, neueste zuerst; unlesbare werden ausgelassen."""
    erg = []
    try:
        dateien = list(Path(ordner).glob(PRAEFIX + "*.zip"))
    except OSError:
        return erg
    for p in dateien:
        try:
            erg.append(sicherung_lesen(p))
        except (OSError, zipfile.BadZipFile):
            pass
    return sorted(erg, key=lambda s: (s["datum"], s["pfad"]), reverse=True)


def zurueckspielen(pfad, wurzel, gewaehlt):
    """Schreibt die Dateien der gewählten Teile aus der Sicherung aufs Gerät.
    Vorhandene Dateien werden überschrieben, andere bleiben unberührt. Stammt die Sicherung
    von einer anderen Geräteart, landet der KOReader-Ordner am Ort der Zielart; Teile, die
    es dort nicht gibt (Kobo eReader.conf), bleiben weg. Gibt die Anzahl geschriebener
    Dateien zurück."""
    wurzel = Path(wurzel).resolve()
    ziel_art = art_von(wurzel)
    n = 0
    with zipfile.ZipFile(pfad) as z:
        try:
            inhalt = inhalt_lesen(z)
        except (KeyError, ValueError):
            inhalt = {}
        quell_art = sicherung_art(inhalt, z.namelist())
        q_ko, z_ko = ko_ordner(quell_art) + "/", ko_ordner(ziel_art) + "/"
        erlaubt = {k for k, *__ in teile(ziel_art)}
        for zi in z.infolist():
            if zi.is_dir() or zi.filename in (INHALT, INHALT_ALT):
                continue
            k = _teil_von(zi.filename, quell_art)
            if k not in gewaehlt or k not in erlaubt:
                continue
            rel = zi.filename
            if rel.startswith(q_ko):
                rel = z_ko + rel[len(q_ko):]
            ziel = (wurzel / rel).resolve()
            if wurzel not in ziel.parents:                  # keine Pfade außerhalb des Geräts
                continue
            ziel.parent.mkdir(parents=True, exist_ok=True)
            tmp = ziel.with_name(ziel.name + ".tmp")
            with z.open(zi) as quelle, open(tmp, "wb") as f:
                shutil.copyfileobj(quelle, f)
            os.replace(tmp, ziel)
            zeit = time.mktime(zi.date_time + (0, 0, -1))
            os.utime(ziel, (zeit, zeit))
            n += 1
    return n


VERLAUF_REL = "settings/lookup_history.lua"          # im KOReader-Ordner
VERLAUF = KOREADER + "/" + VERLAUF_REL
NICHT_KOPIEREN = {"bookbench.json", "werkstatt.json"}   # Arbeitsdatei im Wörterbuch-Ordner (neu, bis 0.24)


def verlauf_lesen(wurzel=None, sicherungsordner=None):
    """KOReaders Nachschlageverlauf als Text: vom angeschlossenen Gerät, sonst aus der neuesten
    Sicherung, die ihn enthält. Gibt (Text, Herkunft) zurück, ("", "") wenn es keinen gibt."""
    if wurzel:
        art = art_von(wurzel)
        p = Path(wurzel) / ko_ordner(art) / VERLAUF_REL
        if p.is_file():
            return (p.read_text(encoding="utf-8", errors="replace"),
                    _("from the {geraet}").format(geraet=art_name(art)))
    if sicherungsordner:
        for s in sicherungen(sicherungsordner):
            name = ko_ordner(s.get("art")) + "/" + VERLAUF_REL
            try:
                with zipfile.ZipFile(s["pfad"]) as z:
                    if name in z.namelist():
                        datum = s.get("datum", "")[:16].replace("T", " ")
                        return (z.read(name).decode("utf-8", "replace"),
                                _("from the backup of {datum}").format(datum=datum))
            except (OSError, zipfile.BadZipFile):
                continue
    return "", ""


# ================================================================ Wörterbücher
def _ist_woerterbuch(ordner):
    try:
        return any(p.suffix == ".ifo" for p in Path(ordner).iterdir())
    except OSError:
        return False


SUCHTIEFE = 8                     # Ordnerebenen unter der Quelle
SUCHGRENZE = 5000                 # höchstens so viele Ordner ansehen
# Versteckte Ordner werden durchsucht (Wörterbücher liegen auf dem Kobo und in Kopien davon
# unter .adds/koreader/data/dict), nur bekannte große ohne Wörterbücher nicht.
_NICHT_SUCHEN = {"__pycache__", "node_modules", "venv", ".venv", "site-packages", "$RECYCLE.BIN",
                 "System Volume Information", "AppData", "Windows", "Program Files", "Program Files (x86)",
                 ".git", ".cache", ".local", ".config", ".mozilla", ".npm", ".cargo", ".rustup", ".Trash",
                 ".Trash-1000", ".kobo", ".kobo-images", "cache", "fonts", "plugins", "frontend"}


def woerterbuch_quellen(quelle):
    """Wörterbuch-Ordner (mit .ifo-Datei) in der Quelle und darunter, bis SUCHTIEFE Ebenen
    und höchstens SUCHGRENZE Ordner; Ordner aus _NICHT_SUCHEN werden ausgelassen, in einen
    gefundenen Wörterbuch-Ordner wird nicht weiter hineingeschaut. Gleichnamige Ordner:
    der mit der neuesten .ifo gilt (auf dem Gerät landet jeder unter seinem Namen)."""
    if not quelle or not Path(quelle).is_dir():
        return []
    q = Path(quelle)
    gefunden, gesehen = {}, 0
    stufe = [q]
    for __ in range(SUCHTIEFE + 1):
        naechste = []
        for ordner in stufe:
            gesehen += 1
            if gesehen > SUCHGRENZE:
                break
            try:
                eintraege = list(os.scandir(ordner))
            except OSError:
                continue
            ifo = [e for e in eintraege if e.name.endswith(".ifo") and e.is_file()]
            if ifo:
                zeit = max(e.stat().st_mtime for e in ifo)
                alt = gefunden.get(ordner.name)
                if alt is None or zeit > alt[1]:
                    gefunden[ordner.name] = (Path(ordner), zeit)
                continue
            naechste += [Path(e.path) for e in eintraege if e.is_dir(follow_symlinks=False)
                         and e.name not in _NICHT_SUCHEN]
        stufe = sorted(naechste, key=lambda p: str(p).casefold())
        if not stufe or gesehen > SUCHGRENZE:
            break
    return sorted((p for p, __ in gefunden.values()), key=lambda p: p.name.casefold())


def _gleich(a, b):
    """Gleiche Größe und (FAT: auf 2 s genau) gleiche Änderungszeit."""
    try:
        sa, sb = a.stat(), b.stat()
    except OSError:
        return False
    return sa.st_size == sb.st_size and abs(sa.st_mtime - sb.st_mtime) <= 2


def woerterbuch_stand(quelle_ordner, ziel_ordner):
    """"aktuell", "veraltet" oder "fehlt"."""
    if not ziel_ordner.is_dir():
        return "fehlt"
    dateien = [p for p in quelle_ordner.iterdir() if p.is_file() and p.name not in NICHT_KOPIEREN]
    if all(_gleich(p, ziel_ordner / p.name) for p in dateien):
        return "aktuell"
    return "veraltet"


def dict_ordner(wurzel):
    """Wörterbuch-Ordner von KOReader auf dem Gerät."""
    return Path(wurzel) / ko_ordner(art_von(wurzel)) / "data" / "dict"


def woerterbuecher(quelle, wurzel, quellen=None):
    """[(name, stand, quellordner)] - stand (Kennungen, Anzeige in der Oberfläche):
    aktuell / veraltet / fehlt (in der Quelle, nicht auf dem Gerät) / "nur auf dem Kobo"
    (nur auf dem Gerät, quellordner dann None) / "kein Kobo" (kein Gerät angeschlossen).
    quellen: Ergebnis von woerterbuch_quellen, falls schon ermittelt."""
    erg, namen = [], set()
    ziel = dict_ordner(wurzel) if wurzel else None
    for q in woerterbuch_quellen(quelle) if quellen is None else quellen:
        namen.add(q.name)
        erg.append((q.name, woerterbuch_stand(q, ziel / q.name) if ziel else "kein Kobo", q))
    if ziel and ziel.is_dir():
        for p in sorted(ziel.iterdir(), key=lambda p: p.name.casefold()):
            if p.is_dir() and p.name not in namen and _ist_woerterbuch(p):
                erg.append((p.name, "nur auf dem Kobo", None))
    return erg


def woerterbuch_kopieren(quelle_ordner, wurzel):
    """Kopiert den Wörterbuch-Ordner nach <KOReader-Ordner>/data/dict/<Name>/. Dateien im
    Ziel, die es in der Quelle nicht (mehr) gibt, werden entfernt (z. B. eine alte .dict
    neben einer neuen .dict.dz). Gibt die Anzahl kopierter Dateien zurück."""
    q = Path(quelle_ordner)
    ziel = dict_ordner(wurzel) / q.name
    ziel.mkdir(parents=True, exist_ok=True)
    dateien = [p for p in q.iterdir() if p.is_file() and p.name not in NICHT_KOPIEREN]
    namen = {p.name for p in dateien}
    for p in ziel.iterdir():
        if p.is_file() and p.name not in namen:
            p.unlink()
    n = 0
    for p in dateien:
        z = ziel / p.name
        if _gleich(p, z):
            continue
        tmp = z.with_name(z.name + ".tmp")
        shutil.copy2(p, tmp)
        os.replace(tmp, z)
        n += 1
    return n


# ================================================================ Auswerfen
def _ausfuehren(befehl):
    kw = {"capture_output": True, "text": True, "timeout": 30}
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000                    # CREATE_NO_WINDOW
    return subprocess.run(befehl, **kw)


# Bekannte Programme, die den Einhängepunkt halten (Name aus /proc/<pid>/comm, ohne Groß/klein)
BLOCKIERER_NAMEN = {
    "dolphin": N_("Dolphin (file manager)"), "nautilus": N_("Files/Nautilus (file manager)"),
    "nemo": N_("Nemo (file manager)"), "thunar": N_("Thunar (file manager)"),
    "pcmanfm": N_("PCManFM (file manager)"), "pcmanfm-qt": N_("PCManFM (file manager)"),
    "caja": N_("Caja (file manager)"), "konsole": N_("Konsole (terminal)"),
    "baloo_file": N_("Baloo (KDE file search)"), "baloo_file_extractor": N_("Baloo (KDE file search)"),
    "calibre": N_("Calibre"), "calibre-parallel": N_("Calibre"), "koreader": N_("Desktop KOReader"),
    "luajit": N_("Desktop KOReader"), "reader.lua": N_("Desktop KOReader"),
}
SHELLS = {"bash", "zsh", "fish", "sh", "dash", "ksh", "tcsh", "nu"}


# Programme, in die ein Terminal eingebettet ist (Elternprozess einer Shell): Name, Abhilfe
TERMINAL_WIRTE = {
    "dolphin": N_("Terminal panel in a Dolphin window (F4) - open another folder in Dolphin or close the window"),
    "kate": N_("Terminal panel in Kate - change its folder or close Kate"),
    "kwrite": N_("Terminal panel in KWrite - change its folder or close KWrite"),
    "code": N_("Terminal in VS Code - change its folder or close the terminal"),
    "code-oss": N_("Terminal in VS Code - change its folder or close the terminal"),
    "codium": N_("Terminal in VSCodium - change its folder or close the terminal"),
    "yakuake": N_("Terminal in Yakuake (drop-down terminal) - change its folder or close the tab"),
}
TERMINAL_FENSTER = {"konsole", "kitty", "alacritty", "foot", "wezterm-gui", "gnome-terminal-", "gnome-terminal-server",
                    "xfce4-terminal", "tilix", "terminator", "xterm", "urxvt", "st", "ghostty", "ptyxis", "kgx"}


def _eltern(pid, proc="/proc", tiefe=5):
    """Programmnamen (comm) der Elternprozesse von pid, nächster zuerst."""
    erg = []
    for __ in range(tiefe):
        try:
            with open(os.path.join(proc, str(pid), "status"), encoding="utf-8", errors="replace") as f:
                ppid = next((int(z.split()[1]) for z in f if z.startswith("PPid:")), 0)
            if ppid <= 1:
                break
            with open(os.path.join(proc, str(ppid), "comm"), encoding="utf-8", errors="replace") as f:
                erg.append(f.read().strip())
        except (OSError, ValueError, IndexError):
            break
        pid = ppid
    return erg


def _blockierer_name(comm, eltern=()):
    """Anzeigename; bei Shells nach dem Programm, in dem das Terminal steckt (eltern = comm der
    Elternprozesse, nächster zuerst), denn ein eingebettetes Terminal sieht man oft gar nicht."""
    c = comm.lower()
    if c in BLOCKIERER_NAMEN:
        return _(BLOCKIERER_NAMEN[c])
    if c.startswith("kioworker") or c.startswith("kio_") or c in ("file.so", "kiod6", "kiod5"):
        return _("KDE file access ({name}, usually belongs to Dolphin)").format(name=comm)
    if c in SHELLS:
        for e in (x.lower() for x in eltern):
            if e in SHELLS or e in ("sudo", "su", "tmux: server", "screen"):
                continue
            if e in TERMINAL_WIRTE:
                return _(TERMINAL_WIRTE[e])
            if e in TERMINAL_FENSTER:
                return _("Terminal window ({programm}) with {name} in a folder on the e-reader - "
                         "cd elsewhere or close it").format(programm=e, name=comm)
            break
        return _("Terminal ({name} with a folder on the e-reader)").format(name=comm)
    return comm


def blockierer(wurzel, proc="/proc"):
    """Linux: [(pid, Name zum Anzeigen, Programmname)] der Prozesse, die etwas unter wurzel offen
    haben (Arbeitsordner, offene Dateien, eingeblendete Dateien). Nur eigene Prozesse lassen sich
    lesen; fremde fehlen dann. Leer unter Windows oder ohne /proc."""
    wurzel = os.path.realpath(str(wurzel))
    praefix = wurzel.rstrip("/") + "/"
    eigen = os.getpid()

    def drunter(ziel):
        return ziel == wurzel or ziel.startswith(praefix)

    erg = []
    try:
        pids = [int(e) for e in os.listdir(proc) if e.isdigit()]
    except OSError:
        return erg
    for pid in pids:
        basis = os.path.join(proc, str(pid))
        treffer = False
        for link in ("cwd", "root"):
            try:
                if drunter(os.readlink(os.path.join(basis, link))):
                    treffer = True
            except OSError:
                pass
        if not treffer:
            try:
                for fd in os.listdir(os.path.join(basis, "fd")):
                    try:
                        if drunter(os.readlink(os.path.join(basis, "fd", fd))):
                            treffer = True
                            break
                    except OSError:
                        pass
            except OSError:
                pass
        if not treffer:
            try:
                with open(os.path.join(basis, "maps"), encoding="utf-8", errors="replace") as f:
                    treffer = any(drunter(z.split(None, 5)[5].strip()) for z in f if len(z.split(None, 5)) == 6)
            except OSError:
                pass
        if not treffer:
            continue
        try:
            with open(os.path.join(basis, "comm"), encoding="utf-8", errors="replace") as f:
                comm = f.read().strip()
        except OSError:
            comm = "?"
        name = _("Bookbench itself") if pid == eigen else _blockierer_name(
            comm, _eltern(pid, proc) if comm.lower() in SHELLS else ())
        erg.append((pid, name, comm))
    return sorted(erg)


def auswerfen(wurzel):
    """Meldet das Gerät ab. Gibt (ok, meldung) zurück."""
    wurzel = Path(wurzel)
    try:
        if sys.platform == "win32":
            laufwerk = wurzel.drive or str(wurzel)[:2]
            skript = ("(New-Object -ComObject Shell.Application).Namespace(17)"
                      f".ParseName('{laufwerk}').InvokeVerb('Eject')")
            _ausfuehren(["powershell", "-NoProfile", "-NonInteractive", "-Command", skript])
            for __ in range(20):                             # Explorer meldet nichts zurück
                if not wurzel.exists():
                    return True, _("ejected")
                time.sleep(0.5)
            return False, _("Windows did not release the drive (files still open?)")
        if shutil.which("udisksctl") is None:
            return False, _("udisksctl not found")
        r = _ausfuehren(["findmnt", "-n", "-o", "SOURCE", "--target", str(wurzel)])
        geraet = r.stdout.strip()
        if r.returncode or not geraet.startswith("/dev/"):
            return False, _("device for the mount point not found")
        for versuch in range(3):
            r = _ausfuehren(["udisksctl", "unmount", "-b", geraet])
            meldung = (r.stderr or r.stdout).strip()
            # "target is busy" verschwindet oft von selbst (Vorschaubilder, Dateisuche noch dran)
            if not r.returncode or "busy" not in meldung.lower() or versuch == 2:
                break
            time.sleep(1.5)
        if r.returncode:
            return False, meldung or _("unmounting failed")
        _ausfuehren(["udisksctl", "power-off", "-b", geraet])  # nicht überall erlaubt - dann reicht das Aushängen
        return True, _("ejected")
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
