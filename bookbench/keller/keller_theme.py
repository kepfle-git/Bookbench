# -*- coding: utf-8 -*-
"""
keller_theme.py - Hell-/Dunkel-Darstellung fuer die Keller-GUI.

  * hell / dunkel : beide mit dem ttk-Theme "clam" (das einzige, das sich
             vollstaendig umfaerben laesst). Gleiches Theme in beiden Modi
             heisst gleiche Abstaende und Raender - beim Umschalten aendern
             sich nur die Farben, nichts verrutscht.
  * Titelleiste unter Windows 10/11 ueber DwmSetWindowAttribute (Attribut 20,
    aeltere Builds 19); unter Linux/Pi bestimmt das der Fenstermanager.
  * system : richtet sich nach der Systemeinstellung (Windows-Registry,
             macOS "AppleInterfaceStyle", GNOME/GTK unter Linux/Pi)

Widgets, die ihre Farben selbst verwalten (z. B. der schwarze Punkte-Plot),
setzen das Attribut `_feste_farben = True` und werden uebersprungen.
"""
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

PALETTE = {
    "hell": {
        "bg": "#f0f0f0", "fg": "#000000", "feld": "#ffffff", "feld_fg": "#000000",
        "sel": "#0078d7", "sel_fg": "#ffffff", "rahmen": "#b4b4b4",
        "kopf": "#e6e6e6", "hinweis": "#666666", "akzent": "#0078d7",
        "deaktiviert": "#8a8a8a", "knopf": "#e1e1e1", "knopf_aktiv": "#e5f1fb",
        "tabellenkopf": "#dddddd",
    },
    "dunkel": {
        "bg": "#2b2d30", "fg": "#dfe1e5", "feld": "#1e1f22", "feld_fg": "#dfe1e5",
        "sel": "#2f5a8f", "sel_fg": "#ffffff", "rahmen": "#43454a",
        "kopf": "#3c3f41", "hinweis": "#9aa0a6", "akzent": "#4a88c7",
        "deaktiviert": "#6f737a", "knopf": "#3c3f41", "knopf_aktiv": "#4a4d52",
        "tabellenkopf": "#3c3f41",
    },
}

import copy as _copy
import re as _re

PALETTE_STANDARD = _copy.deepcopy(PALETTE)

# Anzeigenamen fuer den Einstellungsdialog (Reihenfolge = Anzeige)
PALETTE_NAMEN = [
    ("bg", "Fensterhintergrund"), ("fg", "Schrift"),
    ("feld", "Listen und Eingabefelder"), ("feld_fg", "Schrift in Listen/Feldern"),
    ("sel", "Auswahl"), ("sel_fg", "Schrift in der Auswahl"),
    ("kopf", "Menüleiste und Tabellenköpfe"), ("knopf", "Schaltflächen"),
    ("knopf_aktiv", "Schaltfläche unter der Maus"), ("rahmen", "Rahmen und Linien"),
    ("akzent", "Akzent (Häkchen, Fokus)"), ("hinweis", "Hinweistexte"),
    ("deaktiviert", "Deaktivierte Einträge"), ("tabellenkopf", "Abschnittszeilen (Parameter)"),
]

FARBE_OK = _re.compile(r"^#[0-9a-fA-F]{6}$")


def palette_setzen(ueberschreibungen):
    """ueberschreibungen = {"hell": {"ui.bg": "#rrggbb", ...}, "dunkel": {...}}
    Nur Schluessel mit Praefix "ui." betreffen die Palette."""
    for modus in ("hell", "dunkel"):
        PALETTE[modus] = dict(PALETTE_STANDARD[modus])
        for k, v in (ueberschreibungen.get(modus) or {}).items():
            if k.startswith("ui.") and k[3:] in PALETTE[modus] and FARBE_OK.match(str(v)):
                PALETTE[modus][k[3:]] = v


def system_dunkel():
    """True, wenn das Betriebssystem auf dunkle Darstellung eingestellt ist.
    Faellt bei jedem Fehler auf False (hell) zurueck."""
    try:
        if sys.platform.startswith("win"):
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            wert, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return wert == 0
        if sys.platform == "darwin":
            r = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                               capture_output=True, text=True, timeout=2)
            return "dark" in r.stdout.lower()
        if ":dark" in os.environ.get("GTK_THEME", "").lower():
            return True
        for schluessel in ("color-scheme", "gtk-theme"):
            r = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", schluessel],
                               capture_output=True, text=True, timeout=2)
            if "dark" in r.stdout.lower():
                return True
    except Exception:
        pass
    return False


def ist_dunkel(modus):
    """'hell' / 'dunkel' / 'system' -> bool"""
    if modus == "system":
        return system_dunkel()
    return modus == "dunkel"


def _ttk_einfaerben(style, p):
    style.configure(".", background=p["bg"], foreground=p["fg"],
                    fieldbackground=p["feld"], bordercolor=p["rahmen"],
                    lightcolor=p["bg"], darkcolor=p["bg"], troughcolor=p["feld"],
                    selectbackground=p["sel"], selectforeground=p["sel_fg"],
                    insertcolor=p["fg"], focuscolor=p["akzent"])
    style.map(".", foreground=[("disabled", p["deaktiviert"])])
    style.configure("TButton", background=p["knopf"], padding=(8, 3))
    style.map("TButton", background=[("pressed", p["sel"]), ("active", p["knopf_aktiv"])])
    style.configure("TEntry", fieldbackground=p["feld"], foreground=p["feld_fg"])
    style.configure("TCombobox", fieldbackground=p["feld"], foreground=p["feld_fg"],
                    arrowcolor=p["fg"])
    # clam färbt reine Auswahlfelder (state="readonly") sonst grau mit der
    # Schrift aus dem Modus - im Dunkelmodus hellgrau auf hellgrau
    style.map("TCombobox", fieldbackground=[("readonly", p["feld"])],
              foreground=[("disabled", p["deaktiviert"]), ("readonly", p["feld_fg"])],
              selectbackground=[("readonly", p["feld"])], selectforeground=[("readonly", p["feld_fg"])],
              background=[("active", p["knopf_aktiv"]), ("readonly", p["knopf"])])
    style.configure("TSpinbox", fieldbackground=p["feld"], foreground=p["feld_fg"],
                    arrowcolor=p["fg"])
    style.configure("TNotebook", background=p["bg"], bordercolor=p["rahmen"])
    style.configure("TNotebook.Tab", background=p["knopf"], foreground=p["fg"], padding=(10, 3))
    # gleicher Innenabstand fuer aktiven und inaktive Reiter - clam gibt dem
    # aktiven sonst einen kleineren, und beim Wechsel rutschen die anderen
    style.map("TNotebook.Tab", background=[("selected", p["bg"]), ("active", p["knopf_aktiv"])],
              padding=[("selected", (10, 3))], expand=[("selected", (0, 0, 0, 0))])
    style.configure("Treeview", background=p["feld"], fieldbackground=p["feld"],
                    foreground=p["feld_fg"], bordercolor=p["rahmen"])
    style.map("Treeview", background=[("selected", p["sel"])],
              foreground=[("selected", p["sel_fg"])])
    style.configure("Treeview.Heading", background=p["kopf"], foreground=p["fg"],
                    bordercolor=p["rahmen"])
    style.map("Treeview.Heading", background=[("active", p["knopf_aktiv"])])
    for w in ("TCheckbutton", "TRadiobutton"):
        style.configure(w, background=p["bg"], foreground=p["fg"],
                        indicatorbackground=p["feld"], indicatorforeground=p["fg"])
        style.map(w, background=[("active", p["bg"])],
                  indicatorbackground=[("selected", p["akzent"]), ("pressed", p["knopf_aktiv"])])
    style.configure("TScrollbar", background=p["knopf"], troughcolor=p["feld"],
                    arrowcolor=p["fg"], bordercolor=p["rahmen"])
    style.map("TScrollbar", background=[("active", p["knopf_aktiv"])])
    style.configure("TSeparator", background=p["rahmen"])
    style.configure("TLabelframe", background=p["bg"], bordercolor=p["rahmen"])
    style.configure("TLabelframe.Label", background=p["bg"], foreground=p["fg"])


def _tk_einfaerben(w, p):
    """Klassische Tk-Widgets rekursiv umfaerben."""
    if getattr(w, "_feste_farben", False):
        return
    k = w.winfo_class()
    try:
        if k in ("Tk", "Toplevel", "Frame"):
            w.configure(background=p["bg"])
        elif k == "Label":
            w.configure(background=p["bg"], foreground=p["fg"])
        elif k == "Listbox":
            w.configure(background=p["feld"], foreground=p["feld_fg"],
                        selectbackground=p["sel"], selectforeground=p["sel_fg"],
                        highlightbackground=p["rahmen"], highlightcolor=p["akzent"],
                        disabledforeground=p["deaktiviert"])
        elif k == "Text":
            w.configure(background=p["feld"], foreground=p["feld_fg"],
                        insertbackground=p["fg"], selectbackground=p["sel"],
                        selectforeground=p["sel_fg"], highlightbackground=p["rahmen"])
        elif k == "Canvas":
            w.configure(background=p["bg"], highlightbackground=p["rahmen"])
        elif k == "Menu":
            w.configure(background=p["kopf"], foreground=p["fg"],
                        activebackground=p["sel"], activeforeground=p["sel_fg"],
                        selectcolor=p["fg"], disabledforeground=p["deaktiviert"])
    except tk.TclError:
        pass
    for kind in w.winfo_children():
        _tk_einfaerben(kind, p)


def schrift(groesse=10, fett=False, mono=False):
    """Schriftangabe mit der ECHTEN Familie hinter TkDefaultFont bzw.
    TkFixedFont. (Ein Tupel wie ("TkFixedFont", 9) funktioniert nicht:
    Tk sucht dann eine Familie namens "TkFixedFont", findet keine und
    nimmt die Proportionalschrift.)"""
    import tkinter.font as tkfont
    name = "TkFixedFont" if mono else "TkDefaultFont"
    try:
        familie = tkfont.nametofont(name).actual("family")
    except tk.TclError:
        familie = "Courier" if mono else "Helvetica"
    return (familie, groesse, "bold" if fett else "normal")


def titelleiste(fenster, dunkel):
    """Windows 10/11: Titelleiste des Fensters hell/dunkel schalten."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        fenster.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(fenster.winfo_id())
        wert = ctypes.c_int(1 if dunkel else 0)
        for attribut in (20, 19):          # DWMWA_USE_IMMERSIVE_DARK_MODE (neu / alt)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribut, ctypes.byref(wert), ctypes.sizeof(wert)) == 0:
                break
        # Rahmen neu zeichnen lassen, ohne Position/Groesse zu aendern
        # (SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED)
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)
    except Exception:
        pass


def anwenden(root, dunkel):
    """Darstellung auf das ganze Fenster anwenden. Gibt die Palette zurueck."""
    style = ttk.Style(root)
    p = PALETTE["dunkel" if dunkel else "hell"]
    if style.theme_use() != "clam":
        style.theme_use("clam")
    _ttk_einfaerben(style, p)
    root._theme_dunkel = dunkel
    titelleiste(root, dunkel)
    if not getattr(root, "_theme_map_gebunden", False):
        # spaeter geoeffnete Dialoge bekommen beim Erscheinen dieselbe Titelleiste
        root.bind_class("Toplevel", "<Map>",
                        lambda ev: titelleiste(ev.widget, getattr(root, "_theme_dunkel", False))
                        if ev.widget.winfo_class() == "Toplevel" else None, add="+")
        root._theme_map_gebunden = True
    # eigene Stile (in beiden Modi)
    style.configure("Hinweis.TLabel", foreground=p["hinweis"])
    style.configure("Platzhalter.TEntry", foreground=p["hinweis"])
    style.configure("Ueberschrift.TLabel", font=("", 10, "bold"))

    # Voreinstellungen fuer spaeter erzeugte Widgets (Dialoge, Menues)
    for muster, wert in (("*Toplevel.background", p["bg"]), ("*Menu.background", p["kopf"]),
                         ("*Menu.foreground", p["fg"]), ("*Menu.activeBackground", p["sel"]),
                         ("*Menu.activeForeground", p["sel_fg"]),
                         ("*Listbox.background", p["feld"]), ("*Listbox.foreground", p["feld_fg"]),
                         ("*Text.background", p["feld"]), ("*Text.foreground", p["feld_fg"]),
                         ("*Label.background", p["bg"]), ("*Label.foreground", p["fg"])):
        root.option_add(muster, wert, "interactive")
    _tk_einfaerben(root, p)
    return p
