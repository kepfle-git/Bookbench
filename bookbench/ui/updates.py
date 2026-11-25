# -*- coding: utf-8 -*-
"""
updates.py - nach neuen Versionen suchen und sie einspielen (Oberfläche zu core/updater.py).

  faellig(e, jetzt)    ist die automatische Suche dran? (Einstellung update_pruefen)
  Updates              hängt an der App: automatisch() beim Start, pruefen() aus dem Menü Hilfe
  UpdateDialog         neue Version: Änderungen (Markdown), Installieren, Seite, Überspringen, Später

Gesucht und geladen wird im Hilfsthread (nicht über app.hintergrund, damit eine laufende Arbeit nicht
blockiert); Ergebnisse kommen über threads.im_hauptthread zurück. Installieren: herunterladen
(Fortschritt im Dialog), prüfen, dann fragt app.schliessen_ok() nach offenen Änderungen.
Windows: Installer still starten und beenden; Linux: programm/ tauschen und neu starten.
"""
import webbrowser
from datetime import datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextBrowser,
                               QVBoxLayout)

from bookbench.core import updater as ku
from bookbench.i18n import _
from bookbench.ui import dialogs
from bookbench.ui import theme
from bookbench.ui import threads
from bookbench.version import PROGRAMM, VERSION

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
        vorab = bool((einstellungen or self.app.e).get("update_vorab"))

        def lauf():
            try:
                ergebnis, fehler = ku.release_holen(ku.REPO, vorab), None
            except ku.UpdateFehler as e:
                ergebnis, fehler = None, str(e)
            except Exception as e:                       # Meldung statt stillem Abbruch
                ergebnis, fehler = None, _("Update check failed ({fehler}).").format(fehler=e)
            threads.im_hauptthread(lambda: self._geprueft(ergebnis, fehler, von_hand))
        threads.starten(lauf)

    def _geprueft(self, release, fehler, von_hand):
        self.laeuft = False
        e = self.app.e
        if fehler:
            self.app.status.set(fehler)
            if von_hand:
                dialogs.warnung(self.app, _("Updates"), fehler)
            return
        e["update_zuletzt"] = datetime.now().isoformat(timespec="seconds")
        if not ku.neuer(release["version"], VERSION):
            self.release = None
            text = _("{programm} {version} is up to date.").format(programm=PROGRAMM, version=VERSION)
            self.app.status.set(text)
            if von_hand:
                dialogs.info(self.app, _("Updates"), text)
            return
        self.release = release
        self.app.status.set(_("New version {version} available (installed: {alt}).").format(
            version=release["version"], alt=VERSION))
        if not von_hand and e.get("update_ausgelassen") == release["version"]:
            return
        self.zeigen()

    def zeigen(self):
        if self.dialog is not None and self.dialog.isVisible():
            self.dialog.raise_()
            return
        if self.release:
            self.dialog = UpdateDialog(self.app, self.release)
            self.dialog.show()


class UpdateDialog(QDialog):
    def __init__(self, app, release):
        super().__init__(app)
        self.app, self.r = app, release
        self.art, self.angaben = ku.installation()
        self.download = ku.datei_fuer(release, self.art)
        self._abbrechen = False
        self.setWindowTitle(_("Update available"))
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(760, 500)
        self.setMinimumSize(600, 340)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        kopf = QLabel(_("{programm} {version} is available").format(programm=PROGRAMM, version=release["version"]))
        kopf.setProperty("rolle", "ueberschrift")
        lay.addWidget(kopf)
        zeile = _("Installed: {alt}").format(alt=VERSION)
        if release.get("datum"):
            zeile += "  ·  " + _("published {datum}").format(datum=release["datum"])
        if release.get("vorab"):
            zeile += "  ·  " + _("pre-release")
        z = QLabel(zeile)
        z.setProperty("rolle", "hinweis")
        lay.addWidget(z)
        lay.addSpacing(6)
        lay.addWidget(QLabel(_("Changes")))
        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(True)            # GitHub-Releasetext ist Markdown, Links im Browser
        self.text.document().setDefaultStyleSheet(f"a {{ color: {theme.farben()['akzent']}; }}")
        self.text.setMarkdown(release.get("text") or _("(no description)"))
        lay.addWidget(self.text, 1)
        self.balken = QProgressBar()
        self.balken.setRange(0, 100)
        self.balken.hide()
        lay.addWidget(self.balken)
        self.hinweis = QLabel(self._hinweistext())
        self.hinweis.setProperty("rolle", "hinweis")
        self.hinweis.setWordWrap(True)
        lay.addWidget(self.hinweis)
        unten = QHBoxLayout()
        self.k_installieren = QPushButton(_("Install now"))
        self.k_installieren.clicked.connect(self.installieren)
        self.k_installieren.setVisible(bool(self.download))
        unten.addWidget(self.k_installieren)
        self.k_seite = QPushButton(_("Release page"))
        self.k_seite.clicked.connect(self.seite)
        self.k_seite.setVisible(bool(release.get("seite")))
        unten.addWidget(self.k_seite)
        unten.addStretch(1)
        self.k_auslassen = QPushButton(_("Skip this version"))
        self.k_auslassen.clicked.connect(self.auslassen)
        unten.addWidget(self.k_auslassen)
        self.k_spaeter = QPushButton(_("Later"))
        self.k_spaeter.clicked.connect(self.close)
        unten.addWidget(self.k_spaeter)
        lay.addLayout(unten)

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
        self.close()

    def closeEvent(self, ev):
        self._abbrechen = True
        super().closeEvent(ev)

    # -- Installieren -------------------------------------------------------------------------
    def installieren(self):
        name, url, accept = self.download
        ziel = ku.download_ordner() / name
        for k in (self.k_installieren, self.k_auslassen, self.k_seite):
            k.setEnabled(False)
        self.k_spaeter.setText(_("Cancel"))
        self.balken.show()
        self.hinweis.setText(_("Downloading {name} …").format(name=name))
        self._abbrechen = False
        offen = [True]
        self.destroyed.connect(lambda: offen.__setitem__(0, False))

        def im_dialog(fn):
            threads.im_hauptthread(lambda: fn() if offen[0] else None)

        def fortschritt(geladen, gesamt):
            im_dialog(lambda: self._fortschritt(geladen, gesamt))

        def lauf():
            try:
                summen = ku.summen_holen(self.r)
                vorhanden = False                 # schon geladen (früher abgebrochen)? Fertige Dateien sind
                if ziel.is_file():                # immer vollständig: geladen wird erst in eine .teil-Datei
                    try:
                        vorhanden = ku.vorhandene_datei_ok(ziel, name, summen, self.r["version"])
                    except ku.UpdateFehler:
                        vorhanden = False
                    if not vorhanden:
                        ziel.unlink(missing_ok=True)
                if not vorhanden:
                    ku.herunterladen(url, ziel, accept, fortschritt, lambda: self._abbrechen)
                    ku.pruefen(ziel, name, summen)
                fehler = None
            except ku.UpdateFehler as e:
                fehler = str(e)
            except Exception as e:
                fehler = _("Download failed ({fehler}).").format(fehler=e)
            threads.im_hauptthread(lambda: self._geladen(ziel, fehler, offen[0]))
        threads.starten(lauf)

    def _fortschritt(self, geladen, gesamt):
        if gesamt:
            self.balken.setRange(0, 100)
            self.balken.setValue(int(geladen * 100 / gesamt))
        else:
            self.balken.setRange(0, 0)                     # unbestimmt: Qt zeigt einen laufenden Balken
        self.hinweis.setText(_("Downloading … {mb:.1f} MB").format(mb=geladen / 1e6))

    def _geladen(self, ziel, fehler, offen):
        if fehler:
            self.app.status.set(fehler)
            if offen:
                self.balken.hide()
                self.hinweis.setText(fehler)
                for k in (self.k_installieren, self.k_auslassen, self.k_seite):
                    k.setEnabled(True)
                self.k_spaeter.setText(_("Later"))
            return
        if offen:
            self.balken.setRange(0, 100)
            self.balken.setValue(100)
            self.hinweis.setText(_("Downloaded. Waiting for Bookbench to close …"))
        if not self.app.schliessen_ok():
            self.app.status.set(_("Update downloaded; Help > Check for updates > Install now installs it without "
                                  "downloading again."))
            if offen:
                self.close()
            return
        if self.art == "windows":
            self.app._einstellungen_sichern()
            self.app._popen(ku.windows_befehl(ziel))
            self.app._ohne_rueckfrage = True
            self.app.close()
            return
        try:
            ku.linux_einspielen(ziel, erwartet=self.r["version"])
        except ku.UpdateFehler as e:
            ziel.unlink(missing_ok=True)                 # falsche/kaputte Datei nicht beim nächsten Versuch wieder nehmen
            dialogs.fehler(self.app, _("Updates"), str(e))
            self.app.status.set(str(e))
            if offen:
                self.close()
            return
        self.app.neu_starten()
