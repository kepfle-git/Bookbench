# -*- coding: utf-8 -*-
"""
threads.py - Arbeit im Hilfsthread, Ergebnis im Hauptthread.

Qt-Widgets darf (wie Tk-Widgets) nur der Hauptthread anfassen. Statt der Queue des Tk-Programms
(app._q, alle 100 ms abgeholt) nimmt Qt das selbst in die Hand: Ein Signal, das ein Hilfsthread
auslöst, landet über eine "queued connection" in der Ereignisschleife des Threads, dem das
empfangende Objekt gehört - hier dem Hauptthread. Kein Abfragen, keine Verzögerung.

  einrichten()          einmal im Hauptthread, nach dem Anlegen der QApplication
  im_hauptthread(fn)    fn() läuft bald im Hauptthread (aus jedem Thread aufrufbar)
  starten(fn)           fn() in einem neuen Hilfsthread (daemon: hält das Beenden nicht auf)
"""
import threading

from PySide6.QtCore import QObject, Signal


class _Bote(QObject):
    aufruf = Signal(object)


_bote = None


def einrichten():
    global _bote
    if _bote is None:
        _bote = _Bote()
        _bote.aufruf.connect(lambda fn: fn())


def im_hauptthread(fn):
    _bote.aufruf.emit(fn)


def starten(fn):
    t = threading.Thread(target=fn, daemon=True)
    t.start()
    return t
