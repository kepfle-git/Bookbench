# -*- coding: utf-8 -*-
"""
dialogs.py - Meldungen, Fragen und Dateiauswahl in je einer Zeile (Ersatz für tkinter.messagebox und
filedialog). Die Dateidialoge sind die des Systems: unter KDE über das xdg-desktop-portal der
KDE-Dialog, unter Windows der Explorer-Dialog.

  info / warnung / fehler(eltern, titel, text, details=None)
  frage(eltern, titel, text, standard=True)      -> True/False (Ja/Nein)
  frage3(eltern, titel, text)                    -> True (Ja) / False (Nein) / None (Abbrechen)
  speichern_frage(eltern, titel, text)           -> "speichern" / "verwerfen" / None
  ordner(eltern, titel, start="")                -> Pfad oder ""
  datei_oeffnen(eltern, titel, start="", typen=None)   -> Pfad oder ""
  datei_speichern(eltern, titel, start="", typen=None) -> Pfad oder ""
  eingabe(eltern, titel, text, vorgabe="")       -> Text oder None

typen wie bei tkinter: [("JSON", "*.json"), (_("Images"), "*.jpg *.png")]; "Alle Dateien" hängt Qt
nicht von selbst an, deshalb hier.
"""
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from bookbench.i18n import _


def _meldung(art, eltern, titel, text, details=None, knoepfe=QMessageBox.Ok, standard=None):
    m = QMessageBox(art, titel, text, knoepfe, eltern)
    if details:
        m.setDetailedText(details)
    if standard is not None:
        m.setDefaultButton(standard)
    return m.exec()


def info(eltern, titel, text, details=None):
    _meldung(QMessageBox.Information, eltern, titel, text, details)


def warnung(eltern, titel, text, details=None):
    _meldung(QMessageBox.Warning, eltern, titel, text, details)


def fehler(eltern, titel, text, details=None):
    _meldung(QMessageBox.Critical, eltern, titel, text, details)


def frage(eltern, titel, text, standard=True):
    r = _meldung(QMessageBox.Question, eltern, titel, text, knoepfe=QMessageBox.Yes | QMessageBox.No,
                 standard=QMessageBox.Yes if standard else QMessageBox.No)
    return r == QMessageBox.Yes


def frage3(eltern, titel, text):
    r = _meldung(QMessageBox.Question, eltern, titel, text,
                 knoepfe=QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, standard=QMessageBox.Yes)
    return {QMessageBox.Yes: True, QMessageBox.No: False}.get(r)


def speichern_frage(eltern, titel, text):
    r = _meldung(QMessageBox.Warning, eltern, titel, text,
                 knoepfe=QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, standard=QMessageBox.Save)
    return {QMessageBox.Save: "speichern", QMessageBox.Discard: "verwerfen"}.get(r)


def _filter(typen):
    teile = [f"{name} ({muster})" for name, muster in typen or []]
    return ";;".join(teile + [_("All files") + " (*)"])


def ordner(eltern, titel, start=""):
    return QFileDialog.getExistingDirectory(eltern, titel, start or str(Path.home())) or ""


def datei_oeffnen(eltern, titel, start="", typen=None):
    p, __ = QFileDialog.getOpenFileName(eltern, titel, start or str(Path.home()), _filter(typen))
    return p or ""


def datei_speichern(eltern, titel, start="", typen=None):
    p, __ = QFileDialog.getSaveFileName(eltern, titel, start or str(Path.home()), _filter(typen))
    return p or ""


def eingabe(eltern, titel, text, vorgabe=""):
    t, ok = QInputDialog.getText(eltern, titel, text, text=vorgabe)
    return t if ok else None
