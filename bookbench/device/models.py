# -*- coding: utf-8 -*-
"""
models.py - Kobo-Modelle: Name und Bildschirm nach der Modellnummer.

Die Modellnummer steht im letzten Feld von .kobo/version, z. B.
  N428xxxxxxxxx,4.9.77,4.46.23852,4.9.77,4.9.77,00000000-0000-0000-0000-000000000390
Benutzt werden nur die letzten drei Ziffern ("390"); ältere Firmware schreibt die Zahl auch
ohne die Nullen davor. Die vier Zeichen vorn an der Seriennummer (N428) sind die Modellnummer
auf dem Typenschild, die ist aber nicht für jedes Gerät eindeutig dokumentiert.

Quellen (nachgesehen 18.11.2026, nicht aus dem Gedächtnis):
  Modellnummern   Calibre, src/calibre/devices/kobo/driver.py (390, 391, 393, 690, 691, 693) und
                  Cadmus/Plato, crates/core/src/device/metadata.rs (alle anderen)
  Auflösung, ppi  Plato, crates/core/src/device.rs; ppi gegengeprüft mit KOReader,
                  frontend/device/kobo/device.lua (display_dpi)
  Farbe           KOReader (hasColorScreen bei monza/spaColour, also Libra/Clara Colour und
                  die baugleichen tolino vision color und shine color)
Tolino-Geräte ab 2024 sind Kobo-Hardware und haben auch einen .kobo-Ordner.
"""
import re

# Nummer: (Name, Breite, Höhe, ppi, Farbe) - Breite/Höhe im Hochformat
MODELLE = {
    "310": ("Kobo Touch (A/B)", 600, 800, 167, False),
    "320": ("Kobo Touch (C)", 600, 800, 167, False),
    "330": ("Kobo Glo", 758, 1024, 212, False),
    "340": ("Kobo Mini", 600, 800, 200, False),
    "350": ("Kobo Aura HD", 1080, 1440, 265, False),
    "360": ("Kobo Aura", 758, 1024, 212, False),
    "370": ("Kobo Aura H2O", 1080, 1440, 265, False),
    "371": ("Kobo Glo HD", 1072, 1448, 300, False),
    "372": ("Kobo Touch 2.0", 600, 800, 167, False),
    "373": ("Kobo Aura ONE", 1404, 1872, 300, False),
    "374": ("Kobo Aura H2O Edition 2", 1080, 1440, 265, False),
    "375": ("Kobo Aura Edition 2", 758, 1024, 212, False),
    "376": ("Kobo Clara HD", 1072, 1448, 300, False),
    "377": ("Kobo Forma", 1440, 1920, 300, False),
    "378": ("Kobo Aura H2O Edition 2 (v2)", 1080, 1440, 265, False),
    "379": ("Kobo Aura Edition 2 (v2)", 758, 1024, 212, False),
    "380": ("Kobo Forma 32 GB", 1440, 1920, 300, False),
    "381": ("Kobo Aura ONE Limited Edition", 1404, 1872, 300, False),
    "382": ("Kobo Nia", 758, 1024, 212, False),
    "383": ("Kobo Sage", 1440, 1920, 300, False),
    "384": ("Kobo Libra H2O", 1264, 1680, 300, False),
    "386": ("Kobo Clara 2E", 1072, 1448, 300, False),
    "387": ("Kobo Elipsa", 1404, 1872, 227, False),
    "388": ("Kobo Libra 2", 1264, 1680, 300, False),
    "389": ("Kobo Elipsa 2E", 1404, 1872, 227, False),
    "390": ("Kobo Libra Colour", 1264, 1680, 300, True),
    "391": ("Kobo Clara BW", 1072, 1448, 300, False),
    "393": ("Kobo Clara Colour", 1072, 1448, 300, True),
    "395": ("Kobo Clara BW", 1072, 1448, 300, False),     # zweite Fassung, gleiche Hardware
    "690": ("tolino vision color", 1264, 1680, 300, True),
    "691": ("tolino shine (5th gen.)", 1072, 1448, 300, False),
    "693": ("tolino shine color", 1072, 1448, 300, True),
}
STANDARD = "390"            # wenn nichts bekannt ist (Gerät des Entwicklers)


def modellnummer(version_text):
    """Letzte drei Ziffern des letzten Felds von .kobo/version, sonst ""."""
    felder = (version_text or "").strip().split(",")
    if len(felder) < 2:
        return ""
    m = re.search(r"(\d{1,3})\s*$", felder[-1])
    return m.group(1).zfill(3) if m else ""


def modell(nummer):
    """dict mit name, w, h, dpi, farbe, nummer - oder None, wenn unbekannt."""
    d = MODELLE.get(nummer or "")
    if not d:
        return None
    name, w, h, dpi, farbe = d
    return {"nummer": nummer, "name": name, "w": w, "h": h, "dpi": dpi, "farbe": farbe}


def auswahl():
    """[(Nummer, Anzeigetext)] für Auswahllisten, nach Name sortiert, ohne doppelte Namen."""
    gesehen, erg = set(), []
    for nr, (name, w, h, dpi, __) in sorted(MODELLE.items(), key=lambda x: x[1][0].casefold()):
        if name not in gesehen:
            gesehen.add(name)
            erg.append((nr, f"{name} ({w} × {h}, {dpi} ppi)"))
    return erg
