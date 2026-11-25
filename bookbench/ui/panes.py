# -*- coding: utf-8 -*-
"""
panes.py - Teiler mit gemerkter Breite (Qt-Gegenstück zu tk/panes.teilen).

  Teiler(app, name, standard, fest="links", ausrichtung=Qt.Horizontal)
      QSplitter mit zwei Seiten; die Breite der festen Seite steht in der Einstellung
      "listenbreiten" {name: px} und gilt nach jedem Neuaufbau wieder. Doppelklick auf den Griff =
      Standardbreite. fest="rechts": die rechte Seite hat die gemerkte Breite (Cover-Tafel).
      standard darf eine Funktion sein (z. B. Höhe des Formulars im Bereich Metadaten).
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QSplitter, QSplitterHandle


class _Griff(QSplitterHandle):
    def mouseDoubleClickEvent(self, ev):
        self.splitter().standard()


class Teiler(QSplitter):
    def __init__(self, app, name, standard, fest="links", ausrichtung=Qt.Horizontal, minimum=140):
        super().__init__(ausrichtung)
        self.app, self.name, self.std, self.fest, self.minimum = app, name, standard, fest, minimum
        self.setChildrenCollapsible(False)
        self.splitterMoved.connect(lambda *a: self._merken())
        self._gesetzt = False

    def createHandle(self):
        return _Griff(self.orientation(), self)

    def standardbreite(self):
        return self.std() if callable(self.std) else self.std

    def gemerkt(self):
        try:
            return int((self.app.e.get("listenbreiten") or {}).get(self.name) or 0) or self.standardbreite()
        except (TypeError, ValueError):
            return self.standardbreite()

    def _gesamt(self):
        return self.width() if self.orientation() == Qt.Horizontal else self.height()

    def _anwenden(self):
        gesamt = self._gesamt()
        if gesamt < self.minimum + 200 or self.count() < 2:
            return False
        w = max(self.minimum, min(self.gemerkt(), gesamt - 200))
        self.setSizes([w, gesamt - w] if self.fest == "links" else [gesamt - w, w])
        return True

    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._gesetzt:
            QTimer.singleShot(0, lambda: setattr(self, "_gesetzt", self._anwenden()))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if not self._gesetzt:
            self._gesetzt = self._anwenden()
        else:                                         # feste Seite behält ihre Breite
            self._anwenden()

    def _merken(self):
        groessen = self.sizes()
        if len(groessen) < 2:
            return
        self.app.e.setdefault("listenbreiten", {})[self.name] = groessen[0] if self.fest == "links" else groessen[1]

    def standard(self):
        (self.app.e.get("listenbreiten") or {}).pop(self.name, None)
        self._anwenden()
