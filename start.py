# -*- coding: utf-8 -*-
"""Bookbench starten: python start.py [Bücherordner]

Seit 2.0 braucht Bookbench Qt (PySide6). Fehlt es - etwa nach einem Update aus 1.x heraus, das nur die
Programmdateien tauscht -, meldet sich start.py mit einem kleinen Tk-Fenster (Tk war bis 1.4 nötig, ist
also da) und bietet an, PySide6 mit pip in die laufende Python-Umgebung zu holen. Ohne Tk kommt die
Meldung auf die Konsole."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PAKET = "PySide6-Essentials"        # QtCore, QtGui, QtWidgets - mehr braucht Bookbench nicht


def _qt_da():
    try:
        import PySide6.QtWidgets  # noqa: F401
        return True
    except ImportError:
        return False


def _texte():
    try:
        from bookbench.i18n import _
    except Exception:                          # noqa: BLE001 - nur für die Meldung
        def _(t):
            return t
    titel = _("Bookbench needs Qt")
    text = _("Since version 2.0 Bookbench uses Qt (the Python package PySide6), which is missing in this Python "
             "environment:\n{python}\n\nBest on Arch/EndeavourOS: sudo pacman -S pyside6 (then the KDE style and "
             "file dialog are used too), then start Bookbench again.\n\nOr install it now with pip into this "
             "environment ({paket}, about 100 MB)?").format(python=sys.executable, paket=PAKET)
    return titel, text, _("Installing {paket} …").format(paket=PAKET), _("Installation failed:")


def _pip():
    befehl = [sys.executable, "-m", "pip", "install", "--upgrade", PAKET]
    r = subprocess.run(befehl, capture_output=True, text=True)
    if r.returncode != 0 and "externally-managed-environment" in (r.stderr or ""):
        r = subprocess.run(befehl + ["--user", "--break-system-packages"], capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or r.stdout or "")[-1500:]


def qt_fehlt():
    """PySide6 nachinstallieren anbieten; True, wenn es danach da ist."""
    titel, text, laeuft, fehler = _texte()
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError:
        print(f"{titel}\n\n{text}\n\n  {sys.executable} -m pip install {PAKET}", file=sys.stderr)
        return False
    wurzel = tk.Tk()
    wurzel.withdraw()
    if not messagebox.askyesno(titel, text, parent=wurzel):
        wurzel.destroy()
        return False
    hinweis = tk.Toplevel(wurzel)
    hinweis.title(titel)
    tk.Label(hinweis, text=laeuft, padx=24, pady=18).pack()
    hinweis.update()
    ok, ausgabe = _pip()
    hinweis.destroy()
    if not ok:
        messagebox.showerror(titel, f"{fehler}\n\n{ausgabe}", parent=wurzel)
    wurzel.destroy()
    return ok and _qt_da()


if __name__ == "__main__":
    if not _qt_da():
        if not qt_fehlt():
            sys.exit(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)      # frisch starten, mit Qt
    from bookbench.app import main
    main()
