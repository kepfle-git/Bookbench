# -*- coding: utf-8 -*-
"""
updates.py - nach neuen Versionen suchen und sie einspielen (Oberfläche zu core/updater.py).

  faellig(e, jetzt)    ist die automatische Suche dran? (Einstellung update_pruefen)
  Updates              hängt an der App: automatisch() beim Start, pruefen() aus dem Menü Hilfe
  UpdateDialog         neue Version: Änderungen, Installieren, Seite, Überspringen, Später

Gesucht wird im Hilfsthread (nicht über app.hintergrund, damit eine laufende Arbeit nicht
blockiert); Ergebnisse kommen über app._q in den Hauptthread. Installieren: herunterladen
(Fortschritt im Dialog), prüfen, dann fragt app.schliessen_ok() nach offenen Änderungen.
Windows: Installer still starten und beenden; Linux: programm/ tauschen und neu starten.
"""
import threading
import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

from bookbench.core import updater as ku
from bookbench.i18n import _
from bookbench.ui.help import PROGRAMM, VERSION

ABSTAND = {"start": timedelta(0), "taeglich": timedelta(days=1), "woechentlich": timedelta(days=7)}


def faellig(e, jetzt=None):
    art = e.get("update_pruefen", "taeglich")
    if art not in ABSTAND:
        return False
    try:
        zuletzt = datetime.fromisoformat(e.get("update_zuletzt") or "")
    except ValueError:
        return True
    return (jetzt or datetime.now()) - zuletzt >= ABSTAND[art]


class Updates:
    def __init__(self, app):
        self.app = app
        self.laeuft = False
        self.dialog = None
        self.release = None                     # zuletzt gefundene neuere Version

    def _einstellungen(self, e=None):
        e = e or self.app.e
        return ku.REPO, bool(e.get("update_vorab"))

    def automatisch(self):
        """Beim Start: suchen, wenn die Einstellung es will; nur bei einer neuen, nicht
        übersprungenen Version meldet sich ein Dialog, Fehler stehen still in der Statuszeile.
        Nur bei installierten Kopien: ein Quelltext-Ordner (git-Klon, Tests) lässt sich nicht
        aus dem Programm heraus erneuern, dort sucht man von Hand (Menü Hilfe)."""
        if ku.installationsart() in ("windows", "linux") and faellig(self.app.e):
            self.pruefen(von_hand=False)

    def pruefen(self, von_hand=True, einstellungen=None):
        """einstellungen: andere Werte als app.e (Knopf im Einstellungsdialog vor OK)."""
        if self.laeuft:
            return
        self.laeuft = True
        if von_hand:
            self.app.status.set(_("Checking for updates …"))
        repo, vorab = self._einstellungen(einstellungen)

        def lauf():
            try:
                ergebnis, fehler = ku.release_holen(repo, vorab), None
            except ku.UpdateFehler as e:
                ergebnis, fehler = None, str(e)
            except Exception as e:                       # Meldung statt stillem Abbruch
                ergebnis, fehler = None, _("Update check failed ({fehler}).").format(fehler=e)
            self.app._q.put(("rueckruf", lambda: self._geprueft(ergebnis, fehler, von_hand)))
        threading.Thread(target=lauf, daemon=True).start()

    def _geprueft(self, release, fehler, von_hand):
        self.laeuft = False
        e = self.app.e
        if fehler:
            self.app.status.set(fehler)
            if von_hand:
                messagebox.showwarning(_("Updates"), fehler, parent=self.app)
            return
        e["update_zuletzt"] = datetime.now().isoformat(timespec="seconds")
        if not ku.neuer(release["version"], VERSION):
            self.release = None
            text = _("{programm} {version} is up to date.").format(programm=PROGRAMM, version=VERSION)
            self.app.status.set(text)
            if von_hand:
                messagebox.showinfo(_("Updates"), text, parent=self.app)
            return
        self.release = release
        self.app.status.set(_("New version {version} available (installed: {alt}).").format(
            version=release["version"], alt=VERSION))
        if not von_hand and e.get("update_ausgelassen") == release["version"]:
            return
        self.zeigen()

    def zeigen(self):
        if self.dialog and self.dialog.winfo_exists():
            self.dialog.lift()
            return
        if self.release:
            self.dialog = UpdateDialog(self.app, self.release)


class UpdateDialog(tk.Toplevel):
    def __init__(self, app, release):
        super().__init__(app)
        self.app, self.r = app, release
        self.art, self.angaben = ku.installation()
        self.download = ku.datei_fuer(release, self.art)
        self._abbrechen = False
        self.title(_("Update available"))
        self.transient(app)
        self.geometry("760x500")                # breit genug für die vier Knöpfe auf Deutsch
        self.minsize(600, 340)
        rahmen = ttk.Frame(self, padding=12)
        rahmen.pack(fill="both", expand=True)
        ttk.Label(rahmen, text=_("{programm} {version} is available").format(programm=PROGRAMM, version=release["version"]),
                  style="Ueberschrift.TLabel").pack(anchor="w")
        zeile = _("Installed: {alt}").format(alt=VERSION)
        if release.get("datum"):
            zeile += "  ·  " + _("published {datum}").format(datum=release["datum"])
        if release.get("vorab"):
            zeile += "  ·  " + _("pre-release")
        ttk.Label(rahmen, text=zeile, style="Hinweis.TLabel").pack(anchor="w", pady=(2, 8))

        unten = ttk.Frame(rahmen)
        unten.pack(side="bottom", fill="x", pady=(10, 0))
        self.hinweis = ttk.Label(rahmen, text=self._hinweistext(), style="Hinweis.TLabel", wraplength=720,
                                 justify="left")
        self.hinweis.pack(side="bottom", anchor="w", fill="x", pady=(8, 0))
        self.balken = ttk.Progressbar(rahmen, mode="determinate", maximum=100)

        ttk.Label(rahmen, text=_("Changes")).pack(anchor="w")
        tf = ttk.Frame(rahmen)
        tf.pack(fill="both", expand=True)
        self.text = tk.Text(tf, wrap="word", height=10, relief="flat", borderwidth=1, padx=8, pady=6)
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.insert("1.0", release.get("text") or _("(no description)"))
        self.text.configure(state="disabled")

        self.k_installieren = ttk.Button(unten, text=_("Install now"), command=self.installieren)
        if self.download:
            self.k_installieren.pack(side="left")
        self.k_seite = ttk.Button(unten, text=_("Release page"), command=self.seite)
        if release.get("seite"):
            self.k_seite.pack(side="left", padx=(6 if self.download else 0, 0))
        self.k_spaeter = ttk.Button(unten, text=_("Later"), command=self.schliessen)
        self.k_spaeter.pack(side="right")
        self.k_auslassen = ttk.Button(unten, text=_("Skip this version"), command=self.auslassen)
        self.k_auslassen.pack(side="right", padx=6)
        self.protocol("WM_DELETE_WINDOW", self.schliessen)

    def _hinweistext(self):
        if self.art == "windows":
            return (_("Install now downloads the setup ({name}), closes Bookbench, installs the new version "
                      "over the old one and starts it again. Settings stay.").format(name=self.download[0])
                    if self.download else
                    _("This release has no Windows setup; download it from the release page."))
        if self.art == "linux":
            return _("Install now downloads the new version, replaces the program folder ({ordner}) and "
                     "restarts Bookbench. Settings and the Python environment stay.").format(ordner=ku.PROGRAMM)
        return _("This copy runs from the source code ({ordner}), not from an installation, so it is not "
                 "replaced. Update it yourself, e.g. with git pull, or install the release (install.sh / "
                 "setup).").format(ordner=ku.PROGRAMM)

    def seite(self):
        webbrowser.open(self.r["seite"])

    def auslassen(self):
        self.app.e["update_ausgelassen"] = self.r["version"]
        self.app.status.set(_("Version {version} is skipped; Help > Check for updates still shows it.").format(
            version=self.r["version"]))
        self.destroy()

    def schliessen(self):
        self._abbrechen = True
        self.destroy()

    # -- Installieren -------------------------------------------------------------------------
    def installieren(self):
        name, url, accept = self.download
        ziel = ku.download_ordner() / name
        for k in (self.k_installieren, self.k_auslassen, self.k_seite):
            k.state(["disabled"])
        self.k_spaeter.configure(text=_("Cancel"))
        self.balken.pack(side="bottom", fill="x", before=self.hinweis)
        self.hinweis.configure(text=_("Downloading {name} …").format(name=name))
        self._abbrechen = False

        def fortschritt(geladen, gesamt):
            self.app._q.put(("rueckruf", lambda: self._fortschritt(geladen, gesamt)))

        def lauf():
            try:
                summen = ku.summen_holen(self.r)
                vorhanden = False                 # schon geladen (früher abgebrochen)? Fertige Dateien sind
                if ziel.is_file():                # immer vollständig: geladen wird erst in eine .teil-Datei
                    try:
                        ku.pruefen(ziel, name, summen)
                        vorhanden = True
                    except ku.UpdateFehler:
                        ziel.unlink()
                if not vorhanden:
                    ku.herunterladen(url, ziel, accept, fortschritt, lambda: self._abbrechen)
                    ku.pruefen(ziel, name, summen)
                fehler = None
            except ku.UpdateFehler as e:
                fehler = str(e)
            except Exception as e:
                fehler = _("Download failed ({fehler}).").format(fehler=e)
            self.app._q.put(("rueckruf", lambda: self._geladen(ziel, fehler)))
        threading.Thread(target=lauf, daemon=True).start()

    def _fortschritt(self, geladen, gesamt):
        if not self.winfo_exists():
            return
        if gesamt:
            self.balken.configure(mode="determinate", value=geladen * 100 / gesamt)
        else:
            self.balken.configure(mode="indeterminate")
            self.balken.step(5)
        self.hinweis.configure(text=_("Downloading … {mb:.1f} MB").format(mb=geladen / 1e6))

    def _geladen(self, ziel, fehler):
        if fehler:
            self.app.status.set(fehler)
            if self.winfo_exists():
                self.balken.pack_forget()
                self.hinweis.configure(text=fehler)
                for k in (self.k_installieren, self.k_auslassen, self.k_seite):
                    k.state(["!disabled"])
                self.k_spaeter.configure(text=_("Later"))
            return
        if self.winfo_exists():
            self.balken.configure(mode="determinate", value=100)
            self.hinweis.configure(text=_("Downloaded. Waiting for Bookbench to close …"))
        if not self.app.schliessen_ok():
            self.app.status.set(_("Update downloaded; Help > Check for updates > Install now installs it without "
                                  "downloading again."))
            if self.winfo_exists():
                self.destroy()
            return
        if self.art == "windows":
            self.app._einstellungen_sichern()
            self.app._popen(ku.windows_befehl(ziel))
            self.app.destroy()
            return
        try:
            ku.linux_einspielen(ziel, erwartet=self.r["version"])
        except ku.UpdateFehler as e:
            messagebox.showerror(_("Updates"), str(e), parent=self.app)
            self.app.status.set(str(e))
            if self.winfo_exists():
                self.destroy()
            return
        self.app.neu_starten()
