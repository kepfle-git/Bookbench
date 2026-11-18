# -*- coding: utf-8 -*-
"""
Bookbench - a workshop for your KOReader library: chapter names, blurbs, covers, dictionaries,
KOReader backups and a preview with the desktop KOReader.

Aufbau:
  app.py         Hauptfenster (Menü, Werkzeugleiste, Seitenleiste, Bibliothek, Kapitel, Klappentexte)
  i18n.py        Übersetzungen (_(), ngettext(); Texte aus locale/<code>.po)
  ui/            Einstellungen, Hilfe, Symbole und die Bereiche Cover, Wörterbuch, Gerät, Vorschau
  core/          EPUB lesen und schreiben: Bücher, Inhaltsverzeichnis, Klappentexte, Cover
  dictionary/    Wörterbücher: Datenbank, StarDict, Aufbau aus einem Wiki (wikidict)
  device/        angeschlossenes Gerät: finden, Sicherungen, Wörterbücher kopieren; Modelle
  preview/       Desktop-KOReader als Vorschau
  keller/        Oberflächenbausteine aus dem Keller-Tool (unverändert übernommen)
  locale/        Übersetzungen (.po) und Vorlage (.pot)

Die keller_*.py importieren sich gegenseitig ohne Paketnamen; deshalb kommt keller/ in den Suchpfad.
"""
import os
import sys

_KELLER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keller")
if _KELLER not in sys.path:
    sys.path.insert(0, _KELLER)
