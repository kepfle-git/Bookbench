# -*- coding: utf-8 -*-
"""
area_preview.py - Bereich Vorschau, die KOReader-Werkbank (Qt; Tk-Vorlage tk/area_preview.py): KOReader läuft
unsichtbar im Hintergrund (preview/workbench.py) und zeigt die Seite bzw. den Startbildschirm so, wie sie
auf dem E-Reader aussehen (Schrift, Ränder, Bookends, Bookshelf). Logik in preview/emulator.py und
preview/workbench.py, hier nur die Oberfläche.

  Kopf      gefundener KOReader, sonst ein Hinweis zur Installation
  links     Unterseiten (in der Seitenleiste unter Vorschau): Ansicht (Leseseite/Startbildschirm, Buch,
            Blättern, aufklappbar Profil, Gerät, Fenstergröße, KOReaders Ausgabe), Schrift und Ränder,
            Sperrbildschirm, Patches, je Plugin im Profil eine Seite (Bookends, Bookshelf). Ohne Profil
            gibt es nur die Ansicht.
  rechts    das Bild von KOReader, eingepasst: Klick links/rechts blättert, auf dem Startbildschirm tippt
            er; Strg+Klick tippt, Rechtsklick drückt lange, Ziehen wischt, Mausrad blättert bzw. wischt

"In KOReader öffnen" startet den vollen KOReader im Fenster (auf einer eigenen Kopie). Nur unter Linux und
macOS gebaut (emulator.verfuegbar()). Qt liest PNG selbst, Pillow ist dafür nicht nötig.
Zustand (Unterseite, Buch, andere Datei, letztes Bild, Werkbank) am Bereich; übersteht den Sprachwechsel.
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QRadioButton, QScrollArea, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from bookbench.core import listing
from bookbench.core import settings as kei
from bookbench.device import device as kg
from bookbench.i18n import N_, _, ngettext
from bookbench.preview import emulator as kv
from bookbench.preview import plugins as kpl
from bookbench.preview import transfer as ktr
from bookbench.preview import workbench as kwb
from bookbench.ui import dialogs, theme
from bookbench.ui.area import Bereich
from bookbench.ui.panes import Teiler
from bookbench.ui.workbench_base import hinweis

ABSTAND = 1000                                   # ms, Nachschauen, ob KOReader (Fenster) noch läuft
TAKT = 50                                        # ms, Ereignisse der Werkbank abholen
BLINDTEXT = "blindtext"                          # Kennung in der Buchauswahl
WISCHEN_AB = 24                                  # so viele Pixel gezogen gilt als Wischen statt Klick
HILFE = {"bookends": "vorschau_bookends", "bookshelf": "vorschau_bookshelf", "lesen": "vorschau_lesen",
         "patches": "vorschau_patches", "sperrbildschirm": "vorschau_sperrbildschirm"}


def installieren_text():
    return (_("The preview needs the desktop KOReader. It is only needed for this, everything else works without "
              "it. Install it (one of these):") + "\n"
            "  •  Arch/EndeavourOS: yay -S koreader-bin\n"
            "  •  Flatpak: flatpak install flathub rocks.koreader.KOReader\n"
            "  •  " + _("AppImage from github.com/koreader/koreader/releases into ~/Applications or ~/Downloads, "
                       "or \"Choose KOReader …\" below") + "\n" +
            _("Then \"Find KOReader\" in the Preview menu."))


def _datum(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return iso or "?"


class _Bild(QWidget):
    """Fläche mit dem Bild von KOReader, eingepasst und mittig; leitet Maus und Tasten an den Bereich."""

    def __init__(self, bereich):
        super().__init__()
        self.bereich = bereich
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(200, 200)
        self._druck = None

    def geometrie(self):
        """(x0, y0, Faktor, Bildbreite, Bildhöhe) des gezeichneten Bilds oder None."""
        pm = self.bereich.pixmap
        if pm is None or pm.isNull():
            return None
        w, h = self.width(), self.height()
        f = min(w / pm.width(), h / pm.height(), 1.0)
        return (w - pm.width() * f) / 2, (h - pm.height() * f) / 2, f, pm.width(), pm.height()

    def paintEvent(self, ev):
        m = QPainter(self)
        m.setRenderHint(QPainter.SmoothPixmapTransform)
        f = theme.farben()
        geo = self.geometrie()
        if geo is None:
            m.setPen(Qt.GlobalColor.gray)
            m.drawText(self.rect().adjusted(20, 20, -20, -20), Qt.AlignCenter | Qt.TextWordWrap,
                       _("The picture from KOReader appears here."))
            return
        x0, y0, fa, iw, ih = geo
        m.drawPixmap(QRectF(x0, y0, iw * fa, ih * fa), self.bereich.pixmap, QRectF(0, 0, iw, ih))
        if self.bereich.wartet_bild:                  # neues Bild unterwegs: altes als veraltet kennzeichnen
            r = QRectF(self.width() / 2 - 110, self.height() / 2 - 18, 220, 36)
            m.fillRect(r, QColor(f["kopf"]))
            m.setPen(QColor(f["rahmen"]))
            m.drawRect(r)
            m.setPen(QColor(f["fg"]))
            m.drawText(r, Qt.AlignCenter, _("KOReader is loading …"))

    def bildpunkt(self, pos):
        """Punkt auf der Fläche -> Pixel auf KOReaders Bildschirm (None außerhalb des Bilds)."""
        geo = self.geometrie()
        if not geo:
            return None
        x0, y0, f, iw, ih = geo
        bx, by = (pos.x() - x0) / f, (pos.y() - y0) / f
        if not (0 <= bx < iw and 0 <= by < ih):
            return None
        return int(bx), int(by)

    def mousePressEvent(self, ev):
        self.setFocus()
        if ev.button() == Qt.RightButton:
            self.bereich.tippen(ev.position(), halten=True)
        elif ev.button() == Qt.LeftButton:
            if ev.modifiers() & Qt.ControlModifier:
                self._druck = None
                self.bereich.tippen(ev.position())
            else:
                self._druck = QPointF(ev.position())

    def mouseReleaseEvent(self, ev):
        start, self._druck = self._druck, None
        if start is None or ev.button() != Qt.LeftButton:
            return
        dx, dy = ev.position().x() - start.x(), ev.position().y() - start.y()
        if max(abs(dx), abs(dy)) < WISCHEN_AB:
            self.bereich.klick(ev.position(), self.width())
            return
        if abs(dx) > abs(dy):
            richtung = "east" if dx > 0 else "west"
        else:
            richtung = "south" if dy > 0 else "north"
        f = (self.geometrie() or (0, 0, 1))[2]
        self.bereich.wischen(start, richtung, max(abs(dx), abs(dy)) / f)

    def wheelEvent(self, ev):
        self.bereich.rad(ev.position(), ev.angleDelta().y() or ev.angleDelta().x(),
                         bool(ev.modifiers() & Qt.ShiftModifier) or not ev.angleDelta().y())
        ev.accept()

    def keyPressEvent(self, ev):
        r = {Qt.Key_Left: -1, Qt.Key_PageUp: -1, Qt.Key_Right: 1, Qt.Key_PageDown: 1, Qt.Key_Space: 1}.get(ev.key())
        if r:
            self.bereich.blaettern(r)
        else:
            super().keyPressEvent(ev)


class VorschauBereich(Bereich):
    kennung = "vorschau"
    titel = N_("Preview")
    symbol = "vorschau"

    def __init__(self, app):
        super().__init__(app)
        self.profil = kv.profil_ordner(kei.pfad())
        self.befund = None
        self.prozess = None                      # voller KOReader im Fenster
        self.werkbank = None                     # KOReader im Hintergrund (kwb.Werkbank)
        self.andere_datei = None                 # Buch außerhalb der Bibliothek
        self.buch_name = None                    # gewählter Eintrag der Buchauswahl
        self._namen = {}                         # Anzeigename -> Pfad (BLINDTEXT: Blindtext-Buch)
        self.pixmap = None                       # zuletzt gezeigtes Bild
        self.wartet_bild = False
        self._startzeit = 0.0
        self._werk_text = ""
        self._rad_zuletzt = 0.0
        self._protokoll_ordner = None
        self._rueckweg = None
        self.unterseite_name = app.e.get("werkbank_unterseite") or "ansicht"
        self._sichtbar = set()
        self.takt = QTimer()
        self.takt.setSingleShot(True)
        self.takt.timeout.connect(self._takt_schritt)
        self.beobachter = QTimer()
        self.beobachter.setSingleShot(True)
        self.beobachter.timeout.connect(self._beobachten)
        from bookbench.ui import workbench_plugins as kwp
        from bookbench.ui import workbench_reader as kwr
        from bookbench.ui import workbench_sleep as kws
        self.plugin_seiten = {"lesen": kwr.LesenSeite(self), "sperrbildschirm": kws.SperrSeite(self),
                              "patches": kwr.PatchSeite(self), kpl.BOOKENDS: kwp.BookendsSeite(self),
                              kpl.BOOKSHELF: kwp.BookshelfSeite(self)}
        self.koreader_suchen(still=True)
        self._sichtbar_berechnen()

    # ================================================================ Aufbau
    def bauen(self):
        s = QWidget()
        lay = QVBoxLayout(s)
        lay.setContentsMargins(0, 0, 0, 0)
        t = QLabel(_("KOReader workbench"))
        t.setProperty("rolle", "ueberschrift")
        lay.addWidget(t)
        self.zeile = hinweis("")
        lay.addWidget(self.zeile)
        self.fehlt = QWidget()
        fl = QVBoxLayout(self.fehlt)
        fl.setContentsMargins(0, 4, 0, 6)
        fl.addWidget(QLabel(installieren_text()))
        k = QPushButton(_("Choose KOReader …"))
        k.clicked.connect(self.koreader_waehlen)
        fl.addWidget(k, 0, Qt.AlignLeft)
        lay.addWidget(self.fehlt)

        teiler = Teiler(self.app, "vorschau", 400)
        self.links = QStackedWidget()
        self.links.addWidget(self._ansicht_bauen())
        for name, seite in self.plugin_seiten.items():
            self.links.addWidget(seite.bauen())
        teiler.addWidget(self.links)
        self.bild = _Bild(self)
        teiler.addWidget(self.bild)
        teiler.setStretchFactor(1, 1)
        lay.addWidget(teiler, 1)
        self.seite = s
        self._werk_meldung(self._werk_text)
        self.liste_fuellen(starten=False)
        self.anzeigen()
        self._unterseite_zeigen(self.unterseite_name, beim_bauen=True)
        return s

    def _ansicht_bauen(self):
        flaeche = QScrollArea()
        flaeche.setWidgetResizable(True)
        flaeche.setFrameShape(QFrame.NoFrame)
        flaeche.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        innen = QWidget()
        lay = QVBoxLayout(innen)
        lay.setContentsMargins(0, 0, 12, 8)
        lay.setSpacing(3)

        def ueberschrift(text, oben=0):
            if oben:
                lay.addSpacing(oben)
            lab = QLabel(text)
            lab.setProperty("rolle", "abschnitt")
            lab.setWordWrap(True)
            lay.addWidget(lab)

        e = self.app.e
        ueberschrift(_("View"))
        self.modus_gruppe = QButtonGroup(innen)
        self.modus_knopf = {}
        for wert, text in (("lesen", _("Reading page")), ("bibliothek", _("Start screen (library, Bookshelf)"))):
            r = self.modus_knopf[wert] = QRadioButton(text)
            r.setChecked((e.get("werkbank_modus") or "lesen") == wert)
            r.toggled.connect(lambda an, w=wert: an and self._modus_gewechselt(w))
            self.modus_gruppe.addButton(r)
            lay.addWidget(r)
        self.start_gruppe = QButtonGroup(innen)
        self.startbuecher_knopf = {}
        for wert, text in (("beispiel", _("with sample books")), ("bibliothek", _("with the opened library"))):
            r = self.startbuecher_knopf[wert] = QRadioButton(text)
            r.setChecked((e.get("werkbank_startbuecher") or "beispiel") == wert)
            r.setContentsMargins(20, 0, 0, 0)
            r.setStyleSheet("QRadioButton { margin-left: 20px; }")
            r.toggled.connect(lambda an, w=wert: an and self._startbuecher_gewechselt(w))
            self.start_gruppe.addButton(r)
            lay.addWidget(r)

        ueberschrift(_("Book"), 10)
        self.buch_wahl = QComboBox()
        self.buch_wahl.activated.connect(lambda *a: self._buch_aus_liste())
        lay.addWidget(self.buch_wahl)
        k = QPushButton(_("Other file …"))
        k.clicked.connect(self.datei_waehlen)
        lay.addWidget(k, 0, Qt.AlignLeft)
        self.buch_text = hinweis("")
        lay.addWidget(self.buch_text)

        z = QHBoxLayout()
        for text, fn in (("◀", lambda: self.blaettern(-1)), ("▶", lambda: self.blaettern(1))):
            k = QPushButton(text)
            k.setFixedWidth(36)
            k.clicked.connect(fn)
            z.addWidget(k)
        z.addSpacing(8)
        for text, fn in ((_("Restart"), lambda: self.werkbank_starten()), (_("New picture"), self.neues_bild)):
            k = QPushButton(text)
            k.clicked.connect(fn)
            z.addWidget(k)
        z.addStretch(1)
        lay.addSpacing(8)
        lay.addLayout(z)
        self.werk_label = hinweis("")
        lay.addWidget(self.werk_label)

        self.details_knopf = QToolButton()
        self.details_knopf.setText(_("Profile, device and output"))
        self.details_knopf.setCheckable(True)
        self.details_knopf.setAutoRaise(True)
        self.details_knopf.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.details_knopf.setChecked(bool(e.get("werkbank_details")))
        lay.addSpacing(6)
        lay.addWidget(self.details_knopf)
        self.details = QWidget()
        dl = QVBoxLayout(self.details)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(3)

        def d_ueberschrift(text, oben=0):
            if oben:
                dl.addSpacing(oben)
            lab = QLabel(text)
            lab.setProperty("rolle", "abschnitt")
            lab.setWordWrap(True)
            dl.addWidget(lab)
        d_ueberschrift(_("Profile (settings, plugins, fonts from the e-reader)"))
        self.profil_text = QLabel("")
        self.profil_text.setWordWrap(True)
        dl.addWidget(self.profil_text)
        self.profil_hinweis = hinweis("")
        self.profil_hinweis.setTextInteractionFlags(Qt.TextSelectableByMouse)
        dl.addWidget(self.profil_hinweis)
        d_ueberschrift(_("Device"), 8)
        self.geraet_text = hinweis("")
        dl.addWidget(self.geraet_text)
        dl.addWidget(hinweis(_("Window for \"Open in KOReader\":")))
        self.groesse_gruppe = QButtonGroup(self.details)
        self.groesse_knopf = {}
        for name in kv.GROESSEN:
            r = self.groesse_knopf[name] = QRadioButton(name)
            r.setChecked((e.get("vorschau_groesse") or "passend") == name)
            r.toggled.connect(lambda an, n=name: an and self.app.e.__setitem__("vorschau_groesse", n))
            self.groesse_gruppe.addButton(r)
            dl.addWidget(r)
        d_ueberschrift(_("KOReader output"), 8)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log.setMinimumHeight(160)
        dl.addWidget(self.log)
        lay.addWidget(self.details)

        def details(an):
            self.app.e["werkbank_details"] = bool(an)
            self.details_knopf.setArrowType(Qt.DownArrow if an else Qt.RightArrow)
            self.details.setVisible(bool(an))
        self.details_knopf.toggled.connect(details)
        details(self.details_knopf.isChecked())
        lay.addStretch(1)
        flaeche.setWidget(innen)
        return flaeche

    # ================================================================ Unterseiten
    def _sichtbar_berechnen(self):
        sichtbar = set(kpl.erkennen(self.profil))
        if kv.profil_stand(self.profil)["vorhanden"]:
            sichtbar |= {"lesen", "sperrbildschirm", "patches"}
        self._sichtbar = sichtbar & set(self.plugin_seiten)
        if self.unterseite_name not in self._sichtbar | {"ansicht"}:
            self.unterseite_name = "ansicht"

    def plugins_pruefen(self):
        """Unterseiten nach den Plugins im Profil zeigen/verstecken."""
        vorher = set(self._sichtbar)
        self._sichtbar_berechnen()
        if self.seite is not None and self.links.currentIndex() != self._index(self.unterseite_name):
            self._unterseite_zeigen(self.unterseite_name)
        if vorher != self._sichtbar:
            self.kinder_geaendert()

    def _index(self, name):
        return 0 if name == "ansicht" else 1 + list(self.plugin_seiten).index(name)

    def kinder(self):
        if not self._sichtbar:
            return []
        erg = [{"id": "ansicht", "name": _("View"), "zaehler": ""}]
        for name, seite in self.plugin_seiten.items():
            if name in self._sichtbar:
                erg.append({"id": name, "name": seite.name(), "zaehler": "●" if seite.ungespeichert() else ""})
        return erg

    def kinder_geaendert(self):
        if hasattr(self.app, "leiste"):
            self.app._zaehler()
            if self.app._aktuell == self.kennung:
                self.app.leiste.waehlen(self.kennung, self.unterseite_name if self._sichtbar else None)

    def aktuelles_kind(self):
        return self.unterseite_name if self._sichtbar else None

    def kind_waehlen(self, kind):
        """Seitenleiste: Unterseite gewählt (None/"" = Ansicht)."""
        self.unterseite_waehlen(kind or "ansicht")

    def unterseite(self):
        return self.unterseite_name

    def plugin_seite(self):
        return self.plugin_seiten.get(self.unterseite_name)

    def unterseite_waehlen(self, name):
        if name not in self._sichtbar:
            name = "ansicht"
        if name == self.unterseite_name and self.seite is not None and self.links.currentIndex() == self._index(name):
            return
        self._unterseite_zeigen(name)

    def _unterseite_zeigen(self, name, beim_bauen=False):
        vorher = self.plugin_seiten.get(self.unterseite_name)
        self.unterseite_name = name
        self.app.e["werkbank_unterseite"] = name
        if self.seite is not None:
            self.links.setCurrentIndex(self._index(name))
        if vorher is not None and vorher is not self.plugin_seiten.get(name) and not beim_bauen:
            vorher.beim_verlassen()
        if self.app._aktuell == self.kennung and not beim_bauen:
            self.app._wz_bereich_bauen()
            seite = self.plugin_seite()
            if seite:
                seite.beim_zeigen()
            self.app.leiste.waehlen(self.kennung, name if self._sichtbar else None)

    def hilfe_thema(self):
        return HILFE.get(self.unterseite_name, "vorschau")

    def ungespeichert(self):
        """Namen der Unterseiten mit ungespeichertem Entwurf."""
        return [s.name() for s in self.plugin_seiten.values() if s.ungespeichert()]

    def entwuerfe_fragen(self):
        """Vor dem Neuaufbau des Profils: ungespeicherte Entwürfe speichern/verwerfen (False = abbrechen)."""
        return all(s.fragen_ob_verwerfen() for s in self.plugin_seiten.values())

    def _entwuerfe_in_kopie(self, ko):
        for s in self.plugin_seiten.values():
            s.in_kopie(ko)

    def modus(self):
        return self.app.e.get("werkbank_modus") or "lesen"

    def modus_setzen(self, modus):
        """Ansicht umschalten (Leseseite/Startbildschirm) und die Werkbank neu starten."""
        if self.seite is not None and modus in self.modus_knopf:
            self.modus_knopf[modus].blockSignals(True)
            self.modus_knopf[modus].setChecked(True)
            self.modus_knopf[modus].blockSignals(False)
        self._modus_gewechselt(modus)

    # ================================================================ Werkzeugleiste, Menü
    def werkzeug(self):
        eintraege = [("starten", _("Open in KOReader"), self.starten,
                      _("Open the full desktop KOReader in a window (reading page or start screen, as chosen), with "
                        "the settings from the e-reader and the drafts - for trying out menus. Works on its own "
                        "copy.")), None]
        seite = self.plugin_seite()
        rueckweg = ("sichern", _("To the e-reader …"), self.auf_den_reader,
                    _("Write what is changed in the preview profile to the connected e-reader (with a backup before) "
                      "- you choose what"))
        if seite:
            return eintraege + [("uebernehmen", _("Save to profile"), seite.speichern,
                                 _("Keep the changes in the preview profile (until now they only show in the picture)")),
                                ("rueckgaengig", _("Discard"), seite.verwerfen, _("Back to what is in the profile")),
                                None, rueckweg]
        return eintraege + [("uebernehmen", _("From the e-reader"), self.vom_kobo,
                             _("Rebuild the profile from the connected e-reader: settings, Bookends, patches, plugins, "
                               "fonts")),
                            ("zurueckschreiben", _("From backup"), self.aus_sicherung,
                             _("Settings from the backup selected in the E-reader area (otherwise the newest); plugins "
                               "and fonts stay")),
                            rueckweg]

    def menue(self, leiste):
        m = leiste.addMenu(_("Preview"))
        for eintrag in ((_("Open in KOReader"), self.starten),
                        (_("Changes from the KOReader window …"), self.fenster_aenderungen),
                        (_("Restart the workbench"), self.werkbank_starten),
                        None, (_("Take profile from the e-reader"), self.vom_kobo),
                        (_("Take profile from a backup"), self.aus_sicherung), (_("Other file …"), self.datei_waehlen),
                        None, (_("Find KOReader"), self.koreader_suchen_menue),
                        (_("Choose KOReader …"), self.koreader_waehlen), (_("Open profile folder"), self.profil_oeffnen)):
            if eintrag is None:
                m.addSeparator()
            else:
                m.addAction(eintrag[0], lambda fn=eintrag[1]: self._aus_menue(fn))

    def _aus_menue(self, fn):
        if self.app._aktuell != self.kennung:
            self.app.bereich_zeigen(self.kennung)
        fn()

    def auf_den_reader(self):
        """Rückweg Profil -> E-Reader: Fenster mit den Unterschieden."""
        a = self.app
        if a._arbeit:
            a.status.set(_("Still running: {arbeit}.").format(arbeit=a._arbeit))
            return
        if not a.kobo.wurzel or not a.kobo.wurzel.exists():
            a.status.set(_("No e-reader connected."))
            return
        if not kv.profil_stand(self.profil)["vorhanden"]:
            a.status.set(_("The profile is empty: first \"From the e-reader\" or \"From backup\"."))
            return
        if not self.entwuerfe_fragen():
            return
        from bookbench.ui import transfer_window as ktw
        if self._rueckweg is not None:
            self._rueckweg.close()
        self._rueckweg = ktw.TransferFenster(self)
        self._rueckweg.show()

    # -- Änderungen aus dem KOReader-Fenster ins Profil (seit 2.2-beta5; Logik preview/transfer.fenster_*)
    def fenster_arbeit(self):
        return kwb.arbeitsordner(self.profil, kwb.FENSTER)

    def fenster_aenderungen(self, still=False):
        """Fenster mit den Änderungen aus „In KOReader öffnen“; still: nur öffnen, wenn es welche gibt."""
        a = self.app
        if self.laeuft():
            a.status.set(_("KOReader is still open. Close its window first."))
            return
        if not ktr.hat_fensterstand(self.fenster_arbeit()):
            if not still:
                a.status.set(_("KOReader has not been opened from Bookbench yet (\"Open in KOReader\")."))
            return
        if still and not ktr.fenster_vergleichen(self.profil, self.fenster_arbeit(), a.e.get("rueckweg_nie") or ()):
            return
        from bookbench.ui import transfer_window as ktw
        if self._rueckweg is not None:
            self._rueckweg.close()
        self._rueckweg = ktw.TransferFenster(self, "fenster")
        self._rueckweg.show()

    def fenster_uebernehmen(self, auswahl):
        if not self.entwuerfe_fragen():
            return
        n = ktr.fenster_uebernehmen(self.profil, self.fenster_arbeit(), auswahl)
        self.app.status.set(ngettext("{n} change from the KOReader window taken into the profile.",
                                     "{n} changes from the KOReader window taken into the profile.", n).format(n=n))
        self._profil_neu()

    def koreader_suchen_menue(self):
        self.koreader_suchen()
        self.anzeigen()

    # ================================================================ Anzeige
    def koreader_suchen(self, still=False):
        self.befund = kv.koreader_finden(self.app.e.get("koreader_pfad") or "")
        if not still:
            self.app.status.set(f"KOReader: {kv.beschreibung(self.befund)}")

    def beim_zeigen(self):
        if not self.befund:
            self.koreader_suchen(still=True)
        self.liste_fuellen(starten=False)
        self.anzeigen()
        seite = self.plugin_seite()
        if seite:
            seite.beim_zeigen()                         # startet ggf. in der passenden Ansicht neu
        if not (self.werkbank and self.werkbank.laeuft()):
            self.werkbank_starten(still=True)

    def auswaehlen(self, b):
        """Bibliothek: Öffnen in der Vorschau."""
        self.buch_waehlen(b, starten=True)

    def liste_fuellen(self, starten=False):
        """Buchauswahl: Blindtext, die Bücher der Bibliothek (wie in Kapitel sortiert), andere Datei."""
        a = self.app
        self._namen = {_("Sample text (Lorem ipsum)"): BLINDTEXT}
        self._namen.update({listing.anzeigename(b): b.pfad for b in listing.links_sortiert(a.buecher)})
        if self.andere_datei:
            self._namen[_("[File] {name}").format(name=self.andere_datei.name)] = self.andere_datei
        if self.buch_name not in self._namen:
            # nach dem Sprachwechsel heißt der Blindtext anders: über den Pfad wiederfinden
            pfad = getattr(self, "_buch_pfad", None)
            self.buch_name = next((n for n, p in self._namen.items() if p == pfad), next(iter(self._namen)))
        if self.seite is not None:
            self.buch_wahl.blockSignals(True)
            self.buch_wahl.clear()
            self.buch_wahl.addItems(list(self._namen))
            self.buch_wahl.setCurrentIndex(list(self._namen).index(self.buch_name))
            self.buch_wahl.blockSignals(False)
        self._buch_gewaehlt(neu_starten=starten)

    def _buch_aus_liste(self):
        self.buch_name = self.buch_wahl.currentText()
        self._buch_gewaehlt(neu_starten=True)

    def buch_waehlen(self, b, starten=True):
        """Buch wählen (Bibliothek: Öffnen in der Vorschau) und die Werkbank damit neu starten."""
        self.buch_name = listing.anzeigename(b)
        self._buch_pfad = b.pfad
        if self.modus() != "lesen":
            self.app.e["werkbank_modus"] = "lesen"
            if self.seite is not None:
                self.modus_knopf["lesen"].blockSignals(True)
                self.modus_knopf["lesen"].setChecked(True)
                self.modus_knopf["lesen"].blockSignals(False)
        self.liste_fuellen(starten=starten)

    def _gewaehltes_buch(self):
        """Pfad des gewählten Buchs; None beim Blindtext."""
        p = self._namen.get(self.buch_name)
        self._buch_pfad = p
        return None if p == BLINDTEXT else p

    def anzeigen(self):
        self.plugins_pruefen()
        if self.seite is None:
            return
        da = self.befund is not None
        self.zeile.setText(f"KOReader: {kv.beschreibung(self.befund)}" if da else _("Desktop KOReader not found."))
        self.fehlt.setVisible(not da)
        st = kv.profil_stand(self.profil)
        if not st["vorhanden"]:
            self.profil_text.setText(_("Still empty."))
            self.profil_hinweis.setText(_("Connect the e-reader and \"From the e-reader\". \"From backup\" works too, "
                                          "but then plugins (Bookends) and fonts are missing."))
        else:
            if st["quelle"] == "kobo":
                g = st["geraet"]
                wer = ", ".join(x for x in (g.get("modell"), g.get("koreader") and f"KOReader {g['koreader']}") if x)
                kopf = _("Taken from the e-reader on {datum}").format(datum=_datum(st["datum"])) + (f" ({wer})" if wer else "")
            else:
                kopf = _("Taken from backup {name} on {datum}").format(name=st["sicherung"], datum=_datum(st["datum"]))
            teile = [_("Plugins: {liste}").format(liste=", ".join(st["plugins"]) or _("none")),
                     _("Fonts: {n}").format(n=st["schriften"]), _("Patches: {n}").format(n=st["patches"]),
                     _("Style tweaks: {n}").format(n=st["styletweaks"]),
                     _("Bookends presets: {n}").format(n=st["bookends_vorlagen"])]
            self.profil_text.setText(kopf + "\n" + "  ·  ".join(teile))
            hinweise = []
            if not st["plugins_von"]:
                hinweise.append(_("⚠ Plugins and fonts are missing: take \"From the e-reader\" once, otherwise Bookends "
                                  "is missing."))
            elif "bookends" not in st["plugins"]:
                hinweise.append(_("Bookends is not in the profile (not installed on the e-reader?)."))
            hinweise.append(_("Folder: {ordner}").format(ordner=self.profil))
            self.profil_hinweis.setText("\n".join(hinweise))
        bs = self.bildschirm(st)
        hoehe = self.app.screen().size().height() if self.app.screen() else 1080
        for name, k in self.groesse_knopf.items():
            w, h, dpi = kv.groesse(name, hoehe, bs)
            k.setText(f"{_(kv.GROESSE_TEXT[name])} ({w} × {h}, {dpi} dpi)")
        woher = {"eigen": _("own size from the settings"), "einstellung": _("chosen in the settings"),
                 "profil": _("device of the profile"), "kobo": _("connected e-reader"),
                 "standard": _("⚠ device unknown, standard size - choose it in Settings > Preview")}[bs["quelle"]]
        self.geraet_text.setText(_(
            "{name}: {w} × {h} pixels, {dpi} dpi, {farbe} ({woher}). The workbench always renders at full size and "
            "fits the picture into the area.").format(
            name=bs["name"], w=bs["w"], h=bs["h"], dpi=bs["dpi"], woher=woher,
            farbe=_("colour") if bs["farbe"] else _("black and white")))
        self.protokoll_zeigen()

    def _buch_gewaehlt(self, neu_starten=False):
        p = self._gewaehltes_buch()
        if self.seite is not None:
            hat_bib = bool(self.app.buecher and self.app.ordner)
            self.startbuecher_knopf["bibliothek"].setEnabled(hat_bib)
            if self.modus() == "bibliothek":
                text = _("\"{name}\" counts as the book read last (Bookshelf shows it at the top). ").format(
                    name=self.buch_name) if p else ""
                if self._startbuecher():
                    text += _("The start screen shows the opened library, with the reading progress from the book "
                              "data and the most recently read books first. Click into the picture to tap there (e.g. "
                              "Bookshelf's shelf buttons), right-click for a long press.")
                else:
                    text += _("The start screen shows eight sample books with covers. Click into the picture to tap "
                              "there (e.g. Bookshelf's shelf buttons), right-click for a long press.")
            elif not p:
                text = _("Sample text with chapters, title, author and series - enough for Bookends.")
            elif p.with_name(p.stem + ".sdr").is_dir():
                text = _("Book data (.sdr) is next to the book: font size, margins etc. as on the e-reader.")
            else:
                text = _("No book data next to the book. The connected e-reader and the newest backup are searched "
                         "for the same file name, otherwise the general settings apply.")
            self.buch_text.setText(text)
        if neu_starten:
            self.werkbank_starten()

    def _startbuecher_gewechselt(self, wert):
        self.app.e["werkbank_startbuecher"] = wert
        self.plugin_seiten[kpl.BOOKSHELF].startbuecher_zeigen()
        if self.modus() == "bibliothek":
            self._buch_gewaehlt(neu_starten=True)

    def startbuecher_setzen(self, wert):
        """Startbildschirm mit Beispielbüchern oder der Bibliothek (auch von der Seite Bookshelf aus)."""
        if self.seite is not None and wert in self.startbuecher_knopf:
            self.startbuecher_knopf[wert].blockSignals(True)
            self.startbuecher_knopf[wert].setChecked(True)
            self.startbuecher_knopf[wert].blockSignals(False)
        self._startbuecher_gewechselt(wert)

    def _startbuecher(self):
        """Bücher der geöffneten Bibliothek für den Startbildschirm, oder None (Beispielbücher)."""
        a = self.app
        if (a.e.get("werkbank_startbuecher") or "beispiel") != "bibliothek" or not a.buecher or not a.ordner:
            return None
        return Path(a.ordner), [b.pfad for b in a.buecher]

    def _modus_gewechselt(self, modus):
        self.app.e["werkbank_modus"] = modus
        self._buch_gewaehlt(neu_starten=True)

    def protokoll_zeigen(self):
        ordner = self._protokoll_ordner or (self.werkbank.arbeit if self.werkbank else self.profil)
        text, n, __ = kv.protokoll(ordner)
        if self.seite is not None:
            self.log.setPlainText(text)
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        return n

    def neu_zeichnen(self):
        if self.seite is not None:
            self.bild.update()
            for seite in self.plugin_seiten.values():
                seite.stand_zeigen()

    # ================================================================ Werkbank
    def _groesse_voll(self):
        bs = self.bildschirm()
        return bs["w"], bs["h"], bs["dpi"], not bs["farbe"]

    def werkbank_starten(self, still=False):
        """KOReader im Hintergrund (neu) starten: Ansicht und Buch aus der Auswahl, volle Gerätegröße."""
        a = self.app
        if not self.befund:
            self.koreader_suchen(still=True)
        if not self.befund:
            self._werk_meldung(_("Desktop KOReader not found."))
            return
        if not kv.profil_stand(self.profil)["vorhanden"]:
            self._werk_meldung(_("The profile is empty: first \"From the e-reader\" or \"From backup\"."))
            return
        if self.werkbank is None or self.werkbank.befund != self.befund:
            if self.werkbank:
                self.werkbank.beenden()
            self.werkbank = kwb.Werkbank(self.befund, self.profil)
        modus = self.modus()
        buch = self._gewaehltes_buch() if modus == "lesen" else None
        w, h, dpi, sw = self._groesse_voll()
        sdr = None
        if buch:
            kobo = a.kobo.wurzel if a.kobo.wurzel and a.kobo.wurzel.exists() else None
            sdr = kv.sdr_finden(buch, kobo, self._sicherung())
        bib = self._startbuecher() if modus == "bibliothek" else None
        zuerst = self._gewaehltes_buch() if modus == "bibliothek" else None   # als zuletzt gelesen
        try:
            self.werkbank.starten(modus, buch, w, h, dpi, sw, sdr, bibliothek=bib[0] if bib else None,
                                  buecher=bib[1] if bib else None, zuerst=zuerst, anpassen=self._entwuerfe_in_kopie)
        except (RuntimeError, OSError) as e:
            self._werk_meldung(str(e))
            if not still:
                a.status.set(str(e))
            return
        self._startzeit = time.monotonic()
        self.wartet_bild = True
        self.neu_zeichnen()                          # altes Bild mit "lädt"-Hinweis
        self._werk_meldung(_("KOReader is starting in the background …"))
        self._takt_planen()

    def _werk_meldung(self, text):
        self._werk_text = text
        if self.seite is not None:
            self.werk_label.setText(text)

    def _takt_planen(self):
        if not self.takt.isActive():
            self.takt.start(TAKT)

    def _spaeter(self, ms, fn):
        QTimer.singleShot(ms, fn)

    def _takt_schritt(self):
        wb = self.werkbank
        if wb is None:
            return
        for e in wb.ereignisse():
            if e["art"] == "bereit":
                for seite in self.plugin_seiten.values():
                    seite.nach_start()
                wb.bild()
                if wb.modus == "bibliothek":           # Cover liest KOReader im Hintergrund nach und nach aus
                    for ms in (1500, 4000, 8000, 15000):
                        self._spaeter(ms, lambda w=wb: w is self.werkbank and w.laeuft() and w.bild())
            elif e["art"] == "haengt":
                wb.bild()                                   # zeigen, was KOReader zeigt
                self.wartet_bild = False
                self._werk_meldung(_("KOReader did not open the book. On top: {fenster}. The picture shows KOReader's "
                                     "screen; click into it to tap there (e.g. a button of a dialog).").format(
                    fenster=e["text"] or "?"))
            elif e["art"] == "bild":
                erstes = self.wartet_bild
                self.wartet_bild = False                    # vor dem Zeichnen: kein "lädt"-Hinweis mehr
                self._bild_laden(e["pfad"])
                wb.alte_bilder_weg(behalten=e["pfad"])
                if wb.haengt:
                    pass
                elif erstes:
                    self._werk_meldung(_("Running in the background. Started in {s:.1f} s.").format(
                        s=time.monotonic() - self._startzeit))
                else:
                    self._werk_meldung(_("Running in the background. Last picture in {s:.2f} s.").format(s=e["dauer"]))
            elif e["art"] == "erledigt" and e["befehl"].startswith("sleep"):
                seite = self.plugin_seiten.get("sperrbildschirm")
                if seite:
                    seite.befehl_erledigt(e)
            elif e["art"] == "erledigt" and not e["ok"]:
                self._werk_meldung(_("KOReader reports: {text}").format(text=e["text"]))
            elif e["art"] == "fehler":
                self._werk_meldung(_("KOReader reports: {text}").format(text=e["text"]))
            elif e["art"] == "ende":
                n = self.protokoll_zeigen()
                text = _("KOReader in the background has stopped") + (
                    " " + _("(exit code {code})").format(code=e["code"]) if e["code"] else "") + "."
                if n:
                    text += " " + _("{n} warnings/errors in the output.").format(n=n)
                if wb.prozess is None and not e["code"]:
                    text = _("Stopped.")
                self._werk_meldung(text)
                return
        if wb.laeuft() or not wb._q.empty():
            self._takt_planen()

    def neues_bild(self):
        """Bild neu holen, ohne etwas zu tun (z. B. wenn KOReader im Hintergrund Cover nachgeladen hat)."""
        wb = self.werkbank
        if wb and wb.laeuft() and (wb.bereit or wb.haengt):
            wb.bild()
            self._takt_planen()

    def blaettern(self, richtung):
        wb = self.werkbank
        if not (wb and wb.laeuft() and wb.bereit):
            return
        wb.blaettern(richtung)
        wb.bild()
        self._takt_planen()

    def rad(self, pos, delta, waagerecht):
        """Mausrad: auf der Leseseite blättern, auf dem Startbildschirm wischen (nach unten drehen = Finger
        nach oben), mit Umschalt waagerecht. Höchstens ein Schritt je 250 ms, sonst stauen sich Befehle."""
        jetzt = time.monotonic()
        if jetzt - self._rad_zuletzt < 0.25 or not delta:
            return
        self._rad_zuletzt = jetzt
        vor = delta < 0
        wb = self.werkbank
        if wb and wb.modus != "bibliothek" and not wb.haengt:
            self.blaettern(1 if vor else -1)
        elif waagerecht:
            self.wischen(pos, "west" if vor else "east")
        else:
            self.wischen(pos, "north" if vor else "south")

    def wischen(self, pos, richtung, weite=300):
        wb = self.werkbank
        punkt = self.bild.bildpunkt(pos)
        if not (wb and wb.laeuft() and (wb.bereit or wb.haengt)) or punkt is None:
            return
        wb.wischen(*punkt, richtung, weite)
        wb.bild()
        for ms in (400, 1500):
            self._spaeter(ms, lambda: wb.laeuft() and wb.bild())
        self._takt_planen()

    def klick(self, pos, breite):
        """Leseseite wie auf dem E-Reader: linkes Drittel zurück, sonst weiter. Startbildschirm (und wenn
        KOReader vor dem Buch hängt): an dieser Stelle tippen."""
        wb = self.werkbank
        if wb and (wb.modus == "bibliothek" or wb.haengt):
            self.tippen(pos)
            return
        self.blaettern(-1 if pos.x() < breite / 3 else +1)

    def tippen(self, pos, halten=False):
        """Tippen bzw. lange drücken an dieser Stelle in KOReader, danach neue Bilder."""
        wb = self.werkbank
        punkt = self.bild.bildpunkt(pos)
        if not (wb and wb.laeuft() and (wb.bereit or wb.haengt)) or punkt is None:
            return
        wb.tippen(*punkt, halten=halten)
        wb.bild()
        for ms in (400, 1500):
            self._spaeter(ms, lambda: wb.laeuft() and wb.bild())
        self._takt_planen()

    def _bild_laden(self, pfad):
        pm = QPixmap(str(pfad))
        if pm.isNull():
            return
        self.pixmap = pm
        self.neu_zeichnen()

    def beenden(self):
        """Beim Schließen von Bookbench: KOReader im Hintergrund beenden."""
        self.takt.stop()
        if self.werkbank:
            self.werkbank.beenden()

    def schliessen_ok(self):
        offen = self.ungespeichert()
        if not offen:
            return True
        return dialogs.frage(self.app, _("Quit"), _("The workbench has unsaved changes ({liste}) that are not in the "
                                                    "profile. Quit anyway?").format(liste=", ".join(offen)),
                             standard=False)

    def bildschirm(self, st=None):
        """Nachgebildetes Gerät nach Einstellung, Profil und angeschlossenem Gerät (emulator.bildschirm)."""
        st = st or kv.profil_stand(self.profil)
        k = self.app.kobo
        info = k.info if getattr(k, "wurzel", None) and k.wurzel.exists() else None
        return kv.bildschirm(self.app.e.get("vorschau_geraet") or "auto", self.app.e.get("vorschau_eigen"),
                             st.get("geraet"), info)

    # ================================================================ Aktionen
    def _sicherung(self):
        """Im Bereich E-Reader gewählte Sicherung, sonst die neueste."""
        k = self.app.kobo
        if k.sicherung_gewaehlt and k.sicherung_gewaehlt in k._sicherungen:
            return Path(k.sicherung_gewaehlt)
        alle = kg.sicherungen(k.sicherungsordner())
        return Path(alle[0]["pfad"]) if alle else None

    def vom_kobo(self):
        k = self.app.kobo
        if self.app._arbeit:
            self.app.status.set(_("Still running: {arbeit}.").format(arbeit=self.app._arbeit))
            return
        if not k.wurzel or not k.wurzel.exists():
            self.app.status.set(_("No e-reader connected."))
            return
        if not self._profil_ersetzen_ok():
            return
        wurzel, info, profil = k.wurzel, dict(k.info), self.profil

        def arbeit():
            st = kv.vom_geraet(wurzel, profil, info)
            return _("Profile taken from the e-reader: {plugins} plugins, {schriften} fonts, {vorlagen} Bookends "
                     "presets.").format(plugins=len(st["plugins"]), schriften=st["schriften"],
                                        vorlagen=st["bookends_vorlagen"])
        self.app.hintergrund(_("Taking profile"), arbeit, nachher=self._profil_neu)

    def _profil_ersetzen_ok(self):
        """Vor "Vom E-Reader"/"Aus Sicherung": Entwürfe und im Profil gespeicherte Änderungen gehen verloren."""
        if not self.entwuerfe_fragen():
            return False
        geaendert = kpl.profil_geaendert(self.profil)
        if geaendert and not dialogs.frage(self.app, self.name(), _(
                "Bookbench has changed {liste} in the profile, and these changes are not on the e-reader yet. Taking "
                "the profile again replaces them. Continue?").format(
                liste=", ".join(self.plugin_seiten[n].name() if n in self.plugin_seiten else n for n in geaendert))):
            return False
        return True

    def _profil_neu(self):
        for seite in self.plugin_seiten.values():   # Entwürfe gehören zum alten Profil
            seite.zuruecksetzen()
        self.anzeigen()
        seite = self.plugin_seite()
        if seite is not None:
            seite.neu_laden()
        self.werkbank_starten(still=True)

    def aus_sicherung(self):
        if self.app._arbeit:
            self.app.status.set(_("Still running: {arbeit}.").format(arbeit=self.app._arbeit))
            return
        zip_pfad = self._sicherung()
        if not zip_pfad:
            self.app.status.set(_("No backup available (E-reader area: Back up)."))
            return
        if not self._profil_ersetzen_ok():
            return
        profil = self.profil

        def arbeit():
            st = kv.aus_sicherung(zip_pfad, profil)
            text = _("Settings taken from {name}.").format(name=zip_pfad.name)
            if not st["plugins_von"]:
                text += " " + _("Plugins and fonts are still missing (take them from the e-reader once).")
            return text
        self.app.hintergrund(_("Taking profile"), arbeit, nachher=self._profil_neu)

    def datei_waehlen(self):
        p = dialogs.datei_oeffnen(self.app, _("Book for the preview"), "",
                                  [("E-Books", "*.epub *.kepub *.kepub.epub *.pdf *.fb2 *.mobi"),
                                   (_("All files"), "*")])
        if not p:
            return
        self.andere_datei = Path(p)
        self.buch_name = _("[File] {name}").format(name=self.andere_datei.name)
        self._buch_pfad = self.andere_datei
        if self.modus() != "lesen":
            self.modus_setzen("lesen")
            self.liste_fuellen(starten=False)
        else:
            self.liste_fuellen(starten=True)

    def koreader_waehlen(self):
        p = dialogs.datei_oeffnen(self.app, _("Choose the KOReader program or AppImage"), str(Path.home()))
        if not p:
            return
        self.app.e["koreader_pfad"] = p
        self.koreader_suchen()
        self.anzeigen()
        self.werkbank_starten(still=True)

    def profil_oeffnen(self):
        self.profil.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(self.profil)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            self.app.status.set(_("The folder could not be opened: {fehler}").format(fehler=e))

    def laeuft(self):
        return self.prozess is not None and self.prozess.poll() is None

    def starten(self):
        a = self.app
        if a._arbeit:
            a.status.set(_("Still running: {arbeit}.").format(arbeit=a._arbeit))
            return
        if self.laeuft():
            a.status.set(_("KOReader is already running. Close its window, then start again."))
            return
        if not self.befund:
            self.koreader_suchen(still=True)
            if not self.befund:
                a.status.set(_("Desktop KOReader not found (see the note at the top of the area)."))
                self.anzeigen()
                return
        if not kv.profil_stand(self.profil)["vorhanden"]:
            a.status.set(_("The profile is empty: first \"From the e-reader\" or \"From backup\"."))
            return
        # auf einer eigenen Wegwerf-Kopie (vorschau/fenster) wie die Werkbank: gleiche Ansicht, kepub-Kopie,
        # Entwürfe; das Profil bleibt unberührt
        modus = self.modus()
        buch = self._gewaehltes_buch()
        bs = self.bildschirm()
        hoehe = a.screen().size().height() if a.screen() else 1080
        w, h, dpi = kv.groesse(a.e.get("vorschau_groesse") or "passend", hoehe, bs)
        sw = not bs["farbe"]
        sdr = None
        if buch and modus == "lesen":
            kobo = a.kobo.wurzel if a.kobo.wurzel and a.kobo.wurzel.exists() else None
            sdr = kv.sdr_finden(buch, kobo, self._sicherung())
        bib = self._startbuecher() if modus == "bibliothek" else None
        fenster = kwb.Werkbank(self.befund, self.profil, ordner=kwb.FENSTER, fenster=True)
        try:
            self.prozess = fenster.starten(modus, buch if modus == "lesen" else None, w, h, dpi, sw, sdr,
                                           bibliothek=bib[0] if bib else None, buecher=bib[1] if bib else None,
                                           zuerst=buch if modus == "bibliothek" else None,
                                           anpassen=self._entwuerfe_in_kopie)
        except (RuntimeError, OSError) as e:
            a.status.set(str(e))
            return
        self._protokoll_ordner = fenster.arbeit
        if modus == "bibliothek":
            text = _("KOReader started with the start screen ({w} × {h}, {dpi} dpi).").format(w=w, h=h, dpi=dpi)
        else:
            if not sdr:
                woher = _("without book data, general settings")
            elif sdr[0] == "zip":
                woher = _("book data from the backup")
            elif sdr[1].parent == Path(buch).parent:
                woher = _("book data next to the book")
            else:
                woher = _("book data from the e-reader")
            name = Path(buch).name if buch else kwb.BLINDTEXT
            text = _("KOReader started: {name} ({w} × {h}, {dpi} dpi, {woher}).").format(name=name, w=w, h=h, dpi=dpi,
                                                                                       woher=woher)
        a.status.set(text)
        self.protokoll_zeigen()
        self.beobachter.start(ABSTAND)

    def _beobachten(self):
        if self.prozess is None:
            return
        code = self.prozess.poll()
        if code is None:
            self.protokoll_zeigen()
            self.beobachter.start(ABSTAND)
            return
        self.prozess = None
        n = self.protokoll_zeigen()
        text = _("KOReader closed") + (" " + _("(exit code {code})").format(code=code) if code else "")
        if n:
            text += ", " + _("{n} warnings/errors in the output (Preview > Profile, device and output)").format(n=n)
        self.app.status.set(text + ".")
        grund = kv.absturz_grund(self._protokoll_ordner or self.profil, self.befund) if code else None
        if not grund:
            self.fenster_aenderungen(still=True)         # Menü-Änderungen anbieten (2.2-beta5)
        if grund:                                       # Desktop-KOReader hält den Rechner für einen E-Reader
            dialogs.warnung(self.app, self.name(), grund)
