# -*- coding: utf-8 -*-
"""
workbench_sleep.py - Unterseite "Sperrbildschirm" der KOReader-Werkbank (Qt; Tk-Vorlage tk/workbench_sleep.py).
Logik in preview/sleep_screen.py.

KOReaders Optionen unter Bildschirm > Sperrbildschirm (settings.reader.lua: screensaver_*). Wie "Schrift und
Ränder": Entwurf erst nur in der Werkbank, "Ins Profil" behält ihn; KOReader liest die Werte beim Start, also
startet die Werkbank nach einer Änderung neu. Solange die Seite offen ist, zeigt die Werkbank den
Sperrbildschirm (Befehl "sleep 1"); beim Verlassen schließt "sleep 0" ihn wieder.
"""
from pathlib import Path

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QPlainTextEdit, QPushButton, QToolButton, QVBoxLayout, QWidget)

from bookbench.i18n import N_, _
from bookbench.preview import emulator as kv
from bookbench.preview import koreader_settings as kks
from bookbench.preview import plugins as kpl
from bookbench.preview import sleep_screen as kss
from bookbench.ui import dialogs
from bookbench.ui.workbench_base import BREITE, gleich, hinweis, zahl_oder_leer
from bookbench.ui.workbench_reader import PAUSE, _NeustartSeite

MARKE_BILDER = "sperrbildschirm_bilder"           # Profil-Marke: Bilder nach koreader/screensaver kopiert


class SperrSeite(_NeustartSeite):
    plugin = "sperrbildschirm"
    titel = N_("Sleep screen")
    ansicht = None                                # geht auf der Leseseite und auf dem Startbildschirm

    def __init__(self, bereich):
        super().__init__(bereich)
        self.datei_werte = None
        self.aenderungen = {}
        self._laden = False
        self._hinweis = None                      # eigener Hinweistext (Meldung von KOReader) oder None

    def inhalt_bauen(self):
        self.felder, self.werte_w = {}, {}
        self.kopf.setText(_("KOReader's sleep screen (Screen > Sleep screen in KOReader's menu). While this page is "
                            "open, the workbench shows the sleep screen; after a change it restarts (about a second)."))
        i = self._abschnitt("vorschau", _("Preview"))
        lay = QVBoxLayout(i)
        lay.setContentsMargins(0, 0, 0, 0)
        z = QHBoxLayout()
        for text, fn in ((_("Show again"), self.zeigen), (_("Back to the page"), self.schliessen)):
            k = QPushButton(text)
            k.clicked.connect(lambda *a, fn=fn: fn())
            z.addWidget(k)
        z.addStretch(1)
        lay.addLayout(z)
        self.vorschau_text = hinweis("", BREITE)
        lay.addWidget(self.vorschau_text)

        i = self._abschnitt("bild", _("Wallpaper"))
        g = self._raster(i, kss.BILD)
        g.addWidget(hinweis(_("Paths are the ones on the e-reader. \"Choose …\" takes a file or folder on the connected "
                              "e-reader; anything else is copied into the profile (folder screensaver) and goes to the "
                              "e-reader with \"To the e-reader …\"."), BREITE), 99, 0, 1, 3)
        i = self._abschnitt("ausnahmen", _("Ignore the book cover"), offen=False)
        self._raster(i, kss.AUSNAHMEN)
        i = self._abschnitt("meldung", _("Message"))
        ml = QVBoxLayout(i)
        ml.setContentsMargins(0, 0, 0, 0)
        w = QWidget()
        self._raster(w, kss.MELDUNG)
        ml.addWidget(w)
        # Bookbench-Patch: Bild neben die Meldung (seit 2.2)
        self.patch_rahmen = QWidget()
        pl = QVBoxLayout(self.patch_rahmen)
        pl.setContentsMargins(0, 8, 0, 0)
        kopf = QHBoxLayout()
        t = QLabel(_("Picture next to the message"))
        t.setProperty("rolle", "abschnitt")
        kopf.addWidget(t)
        self.patch_stand = hinweis("")
        kopf.addWidget(self.patch_stand)
        kopf.addStretch(1)
        self.patch_knopf = QPushButton("")
        self.patch_knopf.clicked.connect(self.patch_einspielen)
        kopf.addWidget(self.patch_knopf)
        pl.addLayout(kopf)
        w = QWidget()
        self._raster(w, kss.PATCH_WERTE)
        pl.addWidget(w)
        pl.addWidget(hinweis(_("Needs Bookbench's patch {name} (in the profile and on the e-reader). Without it, "
                               "KOReader lays the message over the picture.").format(name=kss.PATCH.removesuffix(".lua")),
                             BREITE))
        ml.addWidget(self.patch_rahmen)
        i = self._abschnitt("aufwachen", _("After waking up"), offen=False)
        g = self._raster(i, kss.AUFWACHEN)
        g.addWidget(hinweis(_("The gesture is set in KOReader under Taps and gestures (Device: Exit sleep screen)."),
                            BREITE), 99, 0, 1, 3)
        if self.datei_werte is not None:
            self._fuellen()

    # ------------------------------------------------------------------ Aufbau
    def _raster(self, eltern, liste):
        g = QGridLayout(eltern)
        g.setContentsMargins(0, 0, 0, 0)
        g.setColumnStretch(1, 1)
        for r, (schl, text, art, vorgabe, wahl) in enumerate(liste):
            if art in ("an", "an_falsch"):
                c = QCheckBox(_(text))
                c.toggled.connect(lambda *a, s=schl: self._geaendert(s))
                g.addWidget(c, r, 0, 1, 3)
                self.werte_w[schl], self.felder[schl] = c, [c]
                continue
            lab = QLabel(_(text))
            lab.setWordWrap(True)
            lab.setMaximumWidth(150)
            g.addWidget(lab, r, 0, Qt.AlignTop)
            if art == "wahl":
                cb = QComboBox()
                cb.addItems([_(t) for __, t in wahl])
                cb.activated.connect(lambda *a, s=schl: self._geaendert(s))
                g.addWidget(cb, r, 1, 1, 2, Qt.AlignLeft)
                self.werte_w[schl], self.felder[schl] = cb, [lab, cb]
            elif art == "zahl":
                e = QLineEdit()
                e.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,3}"), e))
                e.setFixedWidth(52)
                e.textEdited.connect(lambda *a, s=schl: self._geaendert(s))
                g.addWidget(e, r, 1, Qt.AlignLeft)
                h = hinweis(_("empty = {wert}").format(wert=vorgabe) if vorgabe is not None else _("empty = no limit"))
                g.addWidget(h, r, 2)
                self.werte_w[schl], self.felder[schl] = e, [lab, e, h]
            elif art in ("datei", "ordner"):
                f = QWidget()
                fl = QVBoxLayout(f)
                fl.setContentsMargins(0, 0, 0, 0)
                e = QLineEdit()
                e.editingFinished.connect(lambda s=schl: self._geaendert(s))
                fl.addWidget(e)
                k = QHBoxLayout()
                b1 = QPushButton(_("Choose …"))
                b1.clicked.connect(lambda *a, s=schl, ar=art: self.waehlen(s, ar))
                b2 = QPushButton(_("Clear"))
                b2.clicked.connect(lambda *a, s=schl: (self.werte_w[s].clear(), self._geaendert(s)))
                k.addWidget(b1)
                k.addWidget(b2)
                k.addStretch(1)
                fl.addLayout(k)
                g.addWidget(f, r, 1, 1, 2)
                self.werte_w[schl], self.felder[schl] = e, [lab, e, b1, b2]
            elif art == "text":
                f = QWidget()
                fl = QVBoxLayout(f)
                fl.setContentsMargins(0, 0, 0, 0)
                t = QPlainTextEdit()
                t.setFixedHeight(64)
                t.textChanged.connect(lambda s=schl: self._geaendert(s))
                fl.addWidget(t)
                mb = QToolButton()
                mb.setText(_("Insert"))
                mb.setPopupMode(QToolButton.InstantPopup)
                menue = QMenu(mb)
                for p, bed in kss.PLATZHALTER:
                    menue.addAction(f"{p}   {_(bed)}", lambda p=p, s=schl: self._einfuegen(s, p))
                mb.setMenu(menue)
                fl.addWidget(mb, 0, Qt.AlignLeft)
                if schl == "screensaver_message":
                    fl.addWidget(hinweis(_("empty = \"{text}\"").format(text=_("Sleeping"))))
                g.addWidget(f, r, 1, 1, 2)
                self.werte_w[schl], self.felder[schl] = t, [lab, t, mb]
        return g

    def _einfuegen(self, schl, platzhalter):
        t = self.werte_w[schl]
        t.insertPlainText(platzhalter)
        t.setFocus()

    # ------------------------------------------------------------------ Werte
    def geladen(self):
        return self.datei_werte is not None

    def zuruecksetzen(self):
        self.datei_werte, self.aenderungen = None, {}

    def _werte(self):
        w = dict(self.datei_werte or {})
        for k, v in self.aenderungen.items():
            if v is None:
                w.pop(k, None)
            else:
                w[k] = v
        return w

    def neu_laden(self):
        self.datei_werte = kks.lesen(self.ko)
        self.aenderungen = {}
        self._fuellen()

    def _fuellen(self):
        if not self.gebaut():
            return
        self._laden = True
        werte = self._werte()
        try:
            for schl, __, art, vorgabe, wahl in kss.ALLE:
                w = werte.get(schl)
                f = self.werte_w[schl]
                if art == "an":
                    f.setChecked(bool(w if w is not None else vorgabe))
                elif art == "an_falsch":
                    f.setChecked(w is not False)
                elif art == "wahl":
                    w = vorgabe if w is None else w
                    f.setCurrentIndex(max(0, next((n for n, (k, __) in enumerate(wahl) if gleich(k, w)), 0)))
                elif art == "text":
                    f.setPlainText(w if isinstance(w, str) else "")
                else:
                    f.setText("" if w is None else str(w))
        finally:
            self._laden = False
        self._ausgrauen()
        self._hinweis_zeigen()
        self.stand_zeigen()

    def _ausgrauen(self):
        """Felder ausblenden, die bei der aktuellen Wahl nichts bewirken (KOReaders Menü graut sie aus)."""
        w = self._werte()
        typ = kss.wert(w, "screensaver_type")
        bild = typ in ("cover", "document_cover", "random_image")
        meldung = bool(kss.wert(w, "screensaver_show_message"))
        geste = kss.wert(w, "screensaver_delay") == "gesture"
        aktiv = {
            "screensaver_document_cover": typ == "document_cover",
            "screensaver_dir": typ == "random_image",
            "screensaver_cycle_images_alphabetically": typ == "random_image",
            "screensaver_img_background": bild, "screensaver_stretch_images": bild,
            "screensaver_stretch_limit_percentage": bild and bool(kss.wert(w, "screensaver_stretch_images")),
            "screensaver_images_crop_to_fit": bild, "screensaver_rotate_auto_for_best_fit": bild,
            "screensaver_exclude_on_hold_books": typ == "cover", "screensaver_exclude_finished_books": typ == "cover",
            "screensaver_hide_cover_in_filemanager": typ == "cover",
            "screensaver_message": meldung, "screensaver_message_container": meldung,
            "screensaver_message_vertical_position": meldung, "screensaver_message_alpha": meldung,
            "screensaver_msg_background": meldung and typ == "disable",
            "screensaver_show_exit_message": geste,
            "screensaver_exit_message": geste and kss.wert(w, "screensaver_show_exit_message"),
        }
        aktiv["bookbench_screensaver_center"] = bool(kss.wert(w, "bookbench_screensaver_avoid_message"))
        for schl, widgets in self.felder.items():         # was zur Wahl nicht passt, verschwindet (2.0.1)
            an = bool(aktiv.get(schl, True))
            for wd in widgets:
                wd.setVisible(an)
        self._patch_zeigen(bild and meldung)
        if "ausnahmen" in self.abschnitte:                 # Buchcover auslassen gibt es nur beim Buchcover
            knopf, inhalt = self.abschnitte["ausnahmen"]
            knopf.setVisible(typ == "cover")
            inhalt.setVisible(typ == "cover" and knopf.isChecked())

    def _patch_zeigen(self, passt):
        """Teil „Bild neben der Meldung“: nur bei Bild + Meldung; ohne Patch im Profil ausgegraut."""
        if not self.gebaut():
            return
        self.patch_rahmen.setVisible(passt)
        stand = kks.mitgebracht_stand(self.ko, kss.PATCH)
        self.patch_stand.setText({"fehlt": _("patch not in the profile"), "aus": _("patch switched off (page Patches)"),
                                  "aktuell": _("patch in the profile"),
                                  "anders": _("patch in the profile, another version")}[stand])
        knopf = {"fehlt": _("Add patch"), "anders": _("Update patch")}.get(stand)
        self.patch_knopf.setVisible(bool(knopf))
        self.patch_knopf.setText(knopf or "")
        an = stand in ("aktuell", "anders")
        tipp = "" if an else _("Needs the patch in the profile.")
        for schl, __, __, __, __ in kss.PATCH_WERTE:
            for wd in self.felder[schl]:
                wd.setEnabled(an)
                wd.setToolTip(tipp)

    def patch_einspielen(self):
        kks.mitgebracht_einspielen(self.ko, kss.PATCH)
        kpl._profil_geaendert(self.bereich.profil, "patches")
        self.app.status.set(_("Patch {name} added to the profile.").format(name=kss.PATCH))
        seite = self.bereich.plugin_seiten.get("patches")
        if seite is not None:
            seite.liste_neu()
        self._ausgrauen()
        self.ins_bild()

    def _geaendert(self, schl):
        if self._laden or self.datei_werte is None:
            return
        __, __, art, vorgabe, wahl = kss.eintrag(schl)
        f = self.werte_w[schl]
        try:
            if art == "an":
                w = bool(f.isChecked())
            elif art == "an_falsch":
                w = None if f.isChecked() else False
            elif art == "wahl":
                i = f.currentIndex()
                w = wahl[i][0] if 0 <= i < len(wahl) else vorgabe
            elif art == "zahl":
                w = zahl_oder_leer(f.text())
                if w is not None:
                    w = max(0, min(100, int(w)))
            elif art == "text":
                text = f.toPlainText()
                w = text if text.strip() else None
            else:
                w = f.text().strip() or None
        except ValueError:
            return
        im_profil = (self.datei_werte or {}).get(schl)
        if gleich(w, im_profil) or (w is None and im_profil is None):
            self.aenderungen.pop(schl, None)
        else:
            self.aenderungen[schl] = w
        if schl == "screensaver_stretch_images" and w is True:     # wie KOReader: Strecken und Zuschneiden
            self._nebenbei("screensaver_images_crop_to_fit", False)   # schließen einander aus
        elif schl == "screensaver_images_crop_to_fit" and w is True:
            self._nebenbei("screensaver_stretch_images", False)
        self._ausgrauen()
        self._hinweis = None
        self._hinweis_zeigen()
        self.stand_zeigen()
        self._planen(PAUSE if art in ("text", "zahl", "datei", "ordner") else 300, self.ins_bild)

    def _nebenbei(self, schl, w):
        im_profil = (self.datei_werte or {}).get(schl)
        if gleich(w, im_profil) or (not w and im_profil is None):
            self.aenderungen.pop(schl, None)
        else:
            self.aenderungen[schl] = w
        self._laden = True
        self.werte_w[schl].setChecked(bool(w))
        self._laden = False

    def ungespeichert(self):
        return bool(self.aenderungen)

    # ------------------------------------------------------------------ Pfade
    def _art(self):
        return (kv.profil_stand(self.bereich.profil)["geraet"] or {}).get("art") or None

    def _wurzel(self):
        k = getattr(self.app, "kobo", None)
        w = getattr(k, "wurzel", None)
        return w if w and Path(w).exists() else None

    def waehlen(self, schl, art):
        wurzel = self._wurzel()
        start = str(wurzel) if wurzel else str(Path.home())
        if art == "ordner":
            pfad = dialogs.ordner(self.app, _("Image folder"), start)
        else:
            pfad = dialogs.datei_oeffnen(self.app, _("Image or book"), start,
                                         [(_("Images"), " ".join("*" + e for e in sorted(kss.BILD_ENDUNGEN))),
                                          (_("All files"), "*")])
        if not pfad:
            return
        geraet = kss.geraetepfad(pfad, self._art(), wurzel) or kss.profilpfad(pfad, self.ko, self._art())
        if geraet is None:
            try:
                geraet = kss.ins_profil(pfad, self.ko, self._art())
            except (OSError, ValueError):
                dialogs.fehler(self.app, self.name(), _("There are no images in the folder.") if art == "ordner"
                               else _("The file could not be copied."))
                return
            kpl._profil_geaendert(self.bereich.profil, MARKE_BILDER)
            self.app.status.set(_("Copied into the profile (folder screensaver): {name}").format(name=Path(pfad).name))
        self.werte_w[schl].setText(geraet)
        self._geaendert(schl)

    # ------------------------------------------------------------------ Werkbank
    def _hinweis_zeigen(self, text=None):
        if text is not None:
            self._hinweis = text
        if not self.gebaut():
            return
        if self._hinweis is not None:
            self.vorschau_text.setText(self._hinweis)
            return
        self.vorschau_text.setText(_(kss.was_fehlt(self._werte(), self._art(), self.ko, self._wurzel()))
                                   if self.datei_werte is not None else "")

    def in_kopie(self, ko):
        if self.datei_werte is None and not self.aenderungen:
            return
        if self.aenderungen:
            kks.schreiben(ko, self.aenderungen)
        werte = kks.lesen(ko)
        uebersetzt = {}
        for schl in kss.PFADE:
            lp = kss.lokal(werte.get(schl), self._art(), ko, self._wurzel())
            if lp is not None:
                uebersetzt[schl] = str(lp)
        if uebersetzt:
            kks.schreiben(ko, uebersetzt)

    def ins_bild(self):
        if self.bereich.unterseite() == self.plugin:
            self.bereich.werkbank_starten(still=True)

    def _wb(self):
        wb = self.bereich.werkbank
        return wb if wb and wb.laeuft() and (wb.bereit or wb.haengt) else None

    def nach_start(self):
        if self.bereich.unterseite() == self.plugin and self._wb():
            self._wb().schlafen(True)              # der Bereich holt danach das Bild

    def beim_zeigen(self):
        if not self.geladen():
            self.neu_laden()
        self._hinweis = None
        self._hinweis_zeigen()
        self.zeigen(starten=True)

    def beim_verlassen(self):
        wb = self._wb()
        if wb:
            wb.schlafen(False)
            wb.bild()
            self.bereich._takt_planen()

    def zeigen(self, starten=False):
        wb = self._wb()
        if wb:
            wb.schlafen(True)
            wb.bild()
            self.bereich._takt_planen()
        elif starten or not (self.bereich.werkbank and self.bereich.werkbank.laeuft()):
            self.bereich.werkbank_starten(still=True)

    def schliessen(self):
        self.beim_verlassen()

    def befehl_erledigt(self, e):
        if e["befehl"] != "sleep 1":
            return
        if e["text"] == "ok nothing":
            self._hinweis_zeigen(_("KOReader shows no sleep screen with these settings: the screen stays as it is and "
                                   "there is no message."))
        elif not e["ok"]:
            self._hinweis_zeigen(_("KOReader reports: {text}").format(text=e["text"]))
        else:
            self._hinweis = None
            self._hinweis_zeigen()

    def speichern(self):
        if not self.aenderungen:
            return False
        kks.schreiben(self.ko, self.aenderungen)
        kpl._profil_geaendert(self.bereich.profil, self.plugin)
        self.app.status.set(_("Sleep screen saved in the profile ({n} changed).").format(n=len(self.aenderungen)))
        self.neu_laden()
        return True

    def verwerfen(self):
        if not self.aenderungen or not self.verwerfen_ok():
            return
        self.neu_laden()
        self.ins_bild()
