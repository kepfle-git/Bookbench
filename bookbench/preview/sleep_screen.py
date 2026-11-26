# -*- coding: utf-8 -*-
"""
sleep_screen.py - KOReaders Sperrbildschirm (Screensaver) im Vorschau-Profil (seit 1.4-beta8). Nur Logik;
Oberfläche in ui/workbench_sleep.py.

Nachgesehen im KOReader-Quelltext (master und v2025.10, 25.11.2026):
  frontend/ui/screensaver.lua               Vorgaben (oben im Modul), setup()/show()/close()/cleanup()
  frontend/ui/elements/screensaver_menu.lua Menü "Sleep screen", Werte der Auswahlen
  frontend/ui/widget/screensaverlockwidget.lua   screensaver_show_exit_message (nur false wird gespeichert)
  frontend/apps/filemanager/filemanagerbookinfo.lua  expandString: Platzhalter der Meldung

Seit KOReader 2025.10 steht die Meldung in einem Banner oder Kasten mit Höhe in Prozent und Deckkraft
(screensaver_message_container/_vertical_position/_alpha); vorher gab es nur screensaver_message_position
(oben/Mitte/unten). Die Platzhalter kommen seit 2025.10 aus bookinfo:expandString (mit %C Kapitel und
%P Kapitel-Prozent); Patches für ältere Fassungen (Screensaver.expandSpecial) laufen dort ins Leere.

Pfade (Bild, Ordner) gelten auf dem E-Reader (/mnt/onboard/… auf dem Kobo). Für die Werkbank übersetzt
lokal() sie: in den KOReader-Ordner der Kopie oder auf den angeschlossenen E-Reader. Bilder von anderswo
kopiert Bookbench in den Profil-Ordner screensaver/ (kommt mit "Zum E-Reader …" aufs Gerät).
"""
import shutil
from pathlib import Path

from bookbench.device import device as kg
from bookbench.i18n import N_

# (Schlüssel, Text, Art, Vorgabe, Auswahl) - Art: "wahl", "an", "zahl", "text", "datei", "ordner",
# "an_falsch" (Haken = Schlüssel fehlt, ohne Haken = false; so speichert KOReader screensaver_show_exit_message)
ARTEN_BILD = (("cover", N_("Cover of the book")), ("document_cover", N_("Chosen image or book cover")),
              ("random_image", N_("Random image from a folder")), ("readingprogress", N_("Reading progress")),
              ("bookstatus", N_("Book status")), ("disable", N_("Leave the screen as it is")))
FUELLUNG = (("black", N_("black")), ("white", N_("white")), ("none", N_("none")))

BILD = (
    ("screensaver_type", N_("Wallpaper"), "wahl", "disable", ARTEN_BILD),
    ("screensaver_document_cover", N_("Image or book"), "datei", None, None),
    ("screensaver_dir", N_("Image folder"), "ordner", None, None),
    ("screensaver_cycle_images_alphabetically", N_("Images in order instead of random"), "an", False, None),
    ("screensaver_img_background", N_("Border fill"), "wahl", "black", FUELLUNG),
    ("screensaver_stretch_images", N_("Stretch to fit the screen"), "an", False, None),
    ("screensaver_stretch_limit_percentage", N_("Stretch only up to (%)"), "zahl", None, None),
    ("screensaver_images_crop_to_fit", N_("Crop to fit the screen"), "an", False, None),
    ("screensaver_rotate_auto_for_best_fit", N_("Rotate for best fit"), "an", False, None),
)
AUSNAHMEN = (
    ("screensaver_exclude_on_hold_books", N_("No cover for books on hold"), "an", False, None),
    ("screensaver_exclude_finished_books", N_("No cover for finished books"), "an", False, None),
    ("screensaver_hide_cover_in_filemanager", N_("No cover when locked in the file browser"), "an", False, None),
)
MELDUNG = (
    ("screensaver_show_message", N_("Show a message"), "an", False, None),
    ("screensaver_message", N_("Message"), "text", None, None),
    ("screensaver_message_container", N_("Shape"), "wahl", "box",
     (("box", N_("box")), ("banner", N_("banner")))),
    ("screensaver_message_vertical_position", N_("Height (%; 0 bottom, 50 middle, 100 top)"), "zahl", 50, None),
    ("screensaver_message_alpha", N_("Opacity (%)"), "zahl", 100, None),
    ("screensaver_msg_background", N_("Background (only with \"leave the screen\")"), "wahl", "none", FUELLUNG),
)
AUFWACHEN = (
    ("screensaver_delay", N_("Keep the sleep screen after waking"), "wahl", "disable",
     (("disable", N_("no")), ("1", N_("1 second")), ("3", N_("3 seconds")), ("5", N_("5 seconds")),
      ("tap", N_("until a tap")), ("gesture", N_("until the 'Exit sleep screen' gesture")))),
    ("screensaver_show_exit_message", N_("Show the 'Exit sleep screen' message"), "an_falsch", True, None),
    ("screensaver_exit_message", N_("'Exit sleep screen' message"), "text", None, None),
    ("screensaver_hide_fallback_msg", N_("No message when rebooting or powering off"), "an", False, None),
)
# Bookbench-Patch 2-bookbench-screensaver (seit 2.2): Bild neben die Meldung statt darunter
PATCH = "2-bookbench-screensaver.lua"
PATCH_WERTE = (
    ("bookbench_screensaver_avoid_message", N_("Keep the picture clear of the message"), "an_falsch", True, None),
    ("bookbench_screensaver_center", N_("Keep the picture in the middle (smaller)"), "an", False, None),
)
ALLE = BILD + AUSNAHMEN + MELDUNG + AUFWACHEN + PATCH_WERTE
PFADE = ("screensaver_document_cover", "screensaver_dir")
STANDARD_MELDUNG = "Sleeping"                      # KOReaders default_screensaver_message (englisch)

# Platzhalter der Meldung (bookinfo:expandString, KOReader 2025.10+); Text = Bedeutung
PLATZHALTER = (("%T", N_("title")), ("%A", N_("author(s)")), ("%a", N_("first author")), ("%S", N_("series")),
               ("%c", N_("current page")), ("%t", N_("total pages")), ("%p", N_("percent read")),
               ("%C", N_("chapter title")), ("%P", N_("chapter percent")), ("%l", N_("pages left in chapter")),
               ("%h", N_("time left in chapter")), ("%H", N_("time left in book")), ("%b", N_("battery level")),
               ("%B", N_("battery symbol")), ("%D", N_("date")), ("%m", N_("time")), ("%f", N_("file name")))

BILD_ENDUNGEN = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".tif", ".tiff"}
ORDNER = "screensaver"                             # Bilder im Profil (koreader/screensaver)
# Laufwerk des E-Readers, wie KOReader es dort sieht (platform/*/koreader.sh)
LAUFWERK = {"kobo": "/mnt/onboard", "kindle": "/mnt/us", "pocketbook": "/mnt/ext1"}


def eintrag(schl):
    return next(x for x in ALLE if x[0] == schl)


def laufwerk(art):
    return LAUFWERK.get(art or kg.STANDARD_ART, LAUFWERK[kg.STANDARD_ART])


def lokal(pfad, art, ko_kopie, wurzel=None):
    """Pfad auf dem E-Reader -> Pfad auf diesem Rechner (für die Werkbank) oder None, wenn nicht erreichbar.
    Im KOReader-Ordner des Geräts: in der Kopie (ko_kopie); sonst auf dem angeschlossenen E-Reader (wurzel)."""
    if not pfad or not isinstance(pfad, str):
        return None
    lw = laufwerk(art).rstrip("/") + "/"
    if pfad.startswith(lw):
        rel = pfad[len(lw):]
        ko = kg.ko_ordner(art).strip("/") + "/"
        if rel.startswith(ko):
            p = Path(ko_kopie) / rel[len(ko):]
            if p.exists():
                return p
        if wurzel and Path(wurzel).is_dir():
            p = Path(wurzel) / rel
            return p if p.exists() else None
        return None
    p = Path(pfad)
    return p if p.is_absolute() and p.exists() else None


def geraetepfad(lokaler_pfad, art, wurzel=None):
    """Pfad einer Datei/eines Ordners auf dem angeschlossenen E-Reader -> Pfad, wie KOReader ihn dort sieht.
    None, wenn er nicht auf dem E-Reader liegt."""
    if not wurzel:
        return None
    try:
        rel = Path(lokaler_pfad).resolve().relative_to(Path(wurzel).resolve())
    except ValueError:
        return None
    return laufwerk(art).rstrip("/") + "/" + rel.as_posix()


def profilpfad(lokaler_pfad, ko, art):
    """Pfad im KOReader-Ordner des Profils -> Pfad auf dem E-Reader; None, wenn er nicht dort liegt."""
    try:
        rel = Path(lokaler_pfad).resolve().relative_to(Path(ko).resolve())
    except ValueError:
        return None
    return laufwerk(art).rstrip("/") + "/" + kg.ko_ordner(art).strip("/") + "/" + rel.as_posix()


def ins_profil(quelle, ko, art):
    """Bild oder Ordner von anderswo in den Profil-Ordner screensaver/ kopieren (Ordner: nur die Bilder darin,
    nicht aus Unterordnern). Gibt den Pfad auf dem E-Reader zurück."""
    quelle = Path(quelle)
    ziel = Path(ko) / ORDNER
    if quelle.is_dir():
        ziel = ziel / quelle.name
        ziel.mkdir(parents=True, exist_ok=True)
        n = 0
        for p in sorted(quelle.iterdir()):
            if p.is_file() and p.suffix.lower() in BILD_ENDUNGEN and not p.name.startswith("._"):
                shutil.copy2(p, ziel / p.name)
                n += 1
        if not n:
            raise ValueError("no images")
    else:
        ziel.mkdir(parents=True, exist_ok=True)
        ziel = ziel / quelle.name
        shutil.copy2(quelle, ziel)
    return profilpfad(ziel, ko, art)


def bilder_im_ordner(ordner):
    ordner = Path(ordner)
    return sorted(p for p in ordner.iterdir() if p.is_file() and p.suffix.lower() in BILD_ENDUNGEN) \
        if ordner.is_dir() else []


def wert(werte, schl):
    """Wirksamer Wert eines Schlüssels (Vorgabe, wenn er fehlt)."""
    __, __, art, vorgabe, __ = eintrag(schl)
    if art == "an_falsch":
        return werte.get(schl) is not False
    return werte.get(schl, vorgabe)


def was_fehlt(werte, art, ko, wurzel=None):
    """Hinweis, warum die Werkbank das gewählte Bild nicht zeigen kann (oder "")."""
    typ = wert(werte, "screensaver_type")
    if typ == "document_cover":
        p = werte.get("screensaver_document_cover")
        if not p:
            return N_("No image chosen: KOReader shows a random image from the image folder instead, otherwise its logo.")
        if lokal(p, art, ko, wurzel) is None:
            return N_("The image is on the e-reader, which is not connected: the workbench cannot show it.")
    if typ == "readingprogress" and not (Path(ko) / "settings" / "statistics.sqlite3").is_file():
        return N_("The profile has no reading statistics (settings/statistics.sqlite3): the workbench can only show "
                  "the message. The e-reader uses its own statistics.")
    if typ == "random_image":
        p = werte.get("screensaver_dir")
        if not p:
            return N_("No folder chosen: KOReader shows its logo instead.")
        lp = lokal(p, art, ko, wurzel)
        if lp is None:
            return N_("The folder is on the e-reader, which is not connected: the workbench cannot show it.")
        if not bilder_im_ordner(lp):
            return N_("There are no images in the folder: KOReader shows its logo instead.")
    return ""
