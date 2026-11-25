# -*- coding: utf-8 -*-
"""
area.py - Grundlage der Bereiche im Hauptfenster (Bibliothek, Kapitel, Metadaten, Wörterbuch,
E-Reader, Vorschau).

Ein Bereich ist ein gewöhnliches Objekt, das so lange lebt wie das Hauptfenster; seine Widgets baut
er mit bauen() - beim Start und bei jedem Neuaufbau der Oberfläche (Sprachwechsel ohne Neustart).
Alles, was einen Neuaufbau überstehen muss (gewähltes Buch, Suchtext, Filter, Teilerbreiten), hält
der Bereich deshalb in eigenen Attributen oder gibt es über zustand()/wiederherstellen() weiter -
nicht nur in den Widgets.

  Bereich           kennung, titel (N_), symbol (ui/icons.HELL), hilfe_thema()
    bauen()         QWidget der Seite (wird bei jedem Neuaufbau neu gerufen)
    werkzeug()      [(symbol, text, fn, tipp) oder None für einen Trenner] - linke Werkzeugleiste
    menue(leiste)   eigenes Menü in die Menüleiste hängen (optional)
    marken()        [(kennung, anzahl)] für die Seitenleiste; zaehler() Text-Zähler als Rückfall
    kinder()        Unterseiten [{"id", "name", "zaehler"}] (Seitenleiste)
    zustand()/wiederherstellen(z)   was über einen Neuaufbau hinaus bleiben soll
    beim_zeigen(), neu_zeichnen(), schliessen_ok(), beenden()
"""

from bookbench.i18n import _


class Bereich:
    kennung = ""
    titel = ""
    symbol = ""

    def __init__(self, app):
        self.app = app
        self.seite = None

    def name(self):
        return _(self.titel)

    def bauen(self):
        raise NotImplementedError

    def werkzeug(self):
        return []

    def menue(self, leiste):
        pass

    def marken(self):
        return []

    def zaehler(self):
        return ""

    def kinder(self):
        return []

    def zustand(self):
        return {}

    def wiederherstellen(self, z):
        pass

    def hilfe_thema(self):
        return self.kennung

    def beim_zeigen(self):
        pass

    def neu_zeichnen(self):
        pass

    def schliessen_ok(self):
        return True

    def beenden(self):
        pass
