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
  Platzhalter       Bereich, der noch in der Tk-Fassung steckt (2.0-Betas): sagt, mit welcher Beta er kommt
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from bookbench.i18n import N_, _, ngettext


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


class Platzhalter(Bereich):
    """Noch nicht umgezogener Bereich: zeigt, ab welcher Beta er in der neuen Oberfläche steckt."""

    def __init__(self, app, kennung, titel, symbol, kommt_in):
        super().__init__(app)
        self.kennung, self.titel, self.symbol, self.kommt_in = kennung, titel, symbol, kommt_in

    def bauen(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)
        titel = QLabel(self.name())
        titel.setProperty("rolle", "ueberschrift")
        titel.setAlignment(Qt.AlignCenter)
        lay.addWidget(titel)
        text = QLabel(_("This area moves to the new interface in {version}. Until then, use Bookbench 1.4 "
                        "for it.").format(version=self.kommt_in))
        text.setProperty("rolle", "hinweis")
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignCenter)
        text.setFixedWidth(520)
        lay.addWidget(text, 0, Qt.AlignCenter)
        self.zusatz = QLabel("")
        self.zusatz.setAlignment(Qt.AlignCenter)
        self.zusatz.setWordWrap(True)
        self.zusatz.setFixedWidth(520)
        self.zusatz.setProperty("rolle", "hinweis")
        lay.addWidget(self.zusatz, 0, Qt.AlignCenter)
        self.seite = w
        self.neu_zeichnen()
        return w

    def neu_zeichnen(self):
        if self.kennung == "bibliothek" and self.seite is not None:
            n = len(self.app.buecher)
            self.zusatz.setText(ngettext("{n} book read from {ordner}.", "{n} books read from {ordner}.", n)
                                .format(n=n, ordner=self.app.ordner)
                                if self.app.ordner else "")


# Bereiche der Tk-Fassung und die Beta, in der sie umziehen (Plan 2.0)
BEREICHE = (("bibliothek", N_("Library"), "bibliothek", "2.0-beta2"),
            ("kapitel", N_("Chapters"), "kapitel", "2.0-beta2"),
            ("metadaten", N_("Metadata"), "metadaten", "2.0-beta3"),
            ("woerterbuch", N_("Dictionary"), "woerterbuch", "2.0-beta4"),
            ("kobo", N_("E-reader"), "kobo", "2.0-beta5"),
            ("vorschau", N_("Preview"), "vorschau", "2.0-beta6"))
