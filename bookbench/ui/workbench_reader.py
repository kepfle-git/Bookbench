# -*- coding: utf-8 -*-
"""
workbench_reader.py - Unterseiten "Schrift und Ränder" und "Patches" der KOReader-Werkbank (Qt; Tk-Vorlage
tk/workbench_reader.py). Wie die Plugin-Seiten: Entwurf erst nur in der Werkbank, "Ins Profil speichern"
behält ihn. Beide brauchen einen Neustart der Werkbank (KOReader liest die Werte bzw. führt die Patches beim
Start aus, ~1,2 s). Logik in preview/koreader_settings.py.

  LesenSeite   allgemeine Schrift und Ränder (settings.reader.lua: cre_font, copt_*); Buchwerte des gezeigten
               Buchs anzeigen und in der Werkbank auf Wunsch übergehen
  PatchSeite   Userpatches an/aus (wie KOReaders Patchverwaltung), ansehen, hinzufügen, löschen; Patches, die
               in der Werkbank fehlgeschlagen sind, mit Warnzeichen
Entwürfe und geladener Stand hängen an der Seite (nicht an den Widgets): sie überstehen den Sprachwechsel.
"""
import re
import shutil
from pathlib import Path

from PySide6.QtCore import QRegularExpression, Qt, QTimer
from PySide6.QtGui import QFontDatabase, QRegularExpressionValidator
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from bookbench.i18n import N_, _
from bookbench.preview import emulator as kv
from bookbench.preview import koreader_settings as kks
from bookbench.preview import plugins as kpl
from bookbench.ui import dialogs
from bookbench.ui.workbench_base import BREITE, Seite, gleich, hinweis, zahl_oder_leer

PAUSE = 900                                       # ms nach der letzten Änderung, dann Neustart
ZAHL = QRegularExpression(r"\d{0,3}([.,]\d{0,2})?")


class _NeustartSeite(Seite):
    """Gemeinsam: Änderung -> nach einer Pause Werkbank neu starten (in der passenden Ansicht)."""
    ansicht = "lesen"

    def ins_bild(self):
        b = self.bereich
        if b.unterseite() != self.plugin:
            return
        if b.modus() != self.ansicht:
            b.modus_setzen(self.ansicht)
        else:
            b.werkbank_starten(still=True)

    def beim_zeigen(self):
        if not self.geladen():
            self.neu_laden()
        if self.ansicht and self.bereich.modus() != self.ansicht:
            self.bereich.modus_setzen(self.ansicht)

    def geladen(self):
        return True


# ====================================================================== Schrift und Ränder
class LesenSeite(_NeustartSeite):
    plugin = "lesen"
    titel = N_("Font and margins")

    def __init__(self, bereich):
        super().__init__(bereich)
        self.datei_werte = None                   # settings.reader.lua im Profil
        self.aenderungen = {}
        self.buchwerte = None                     # Schrift-/Randwerte des gezeigten Buchs (None = kein Buch)
        self._laden = False
        self.schriften = []

    def inhalt_bauen(self):
        self.kopf.setText(_("KOReader's general reading settings, as \"Set as default\" in KOReader's menu stores "
                            "them. They show in the picture after a restart of the workbench (about a second)."))
        self.felder = {}
        i = self._abschnitt("schrift", _("Font"))
        g = QGridLayout(i)
        g.setColumnStretch(2, 1)
        g.addWidget(QLabel(_("Font")), 0, 0)
        self.schrift = QComboBox()
        self.schrift.setEditable(True)
        self.schrift.setMinimumContentsLength(18)
        self.schrift.activated.connect(lambda *a: self._schrift_geaendert())
        self.schrift.lineEdit().editingFinished.connect(self._schrift_geaendert)
        g.addWidget(self.schrift, 0, 1, 1, 2, Qt.AlignLeft)
        self._zeilen(g, kks.SCHRIFT, 1)

        i = self._abschnitt("raender", _("Margins"))
        g = QGridLayout(i)
        g.setColumnStretch(2, 1)
        self._zeilen(g, kks.RAENDER, 0)
        g.addWidget(hinweis(_("In KOReader's units (pixels at the device's density). Bookends' own margins are on the "
                              "Bookends page."), BREITE), len(kks.RAENDER), 0, 1, 3)

        i = self._abschnitt("buch", _("Values of the book shown"))
        lay = QVBoxLayout(i)
        lay.setContentsMargins(0, 0, 0, 0)
        self.buch_text = QLabel("")
        self.buch_text.setWordWrap(True)
        lay.addWidget(self.buch_text)
        self.buch_aus = QCheckBox(_("Ignore the book's own values in the workbench"))
        self.buch_aus.setChecked(bool(self.app.e.get("werkbank_buchwerte_aus")))
        self.buch_aus.toggled.connect(self._buch_aus_geaendert)
        lay.addWidget(self.buch_aus)
        lay.addWidget(hinweis(_("KOReader stores font and margins in the book data (.sdr) of every book it has opened "
                                "once; there they win over the general values. The general values therefore only "
                                "apply to books never opened before. Ignoring them here only affects the workbench "
                                "(the copy), never the book."), BREITE))
        if self.datei_werte is not None:
            self._fuellen()

    def _zeilen(self, g, liste, start):
        for r, (schl, text, art, vorgabe, wahl) in enumerate(liste, start):
            if art == "an":
                c = QCheckBox(_(text))
                c.toggled.connect(lambda *a, s=schl: self._geaendert(s))
                g.addWidget(c, r, 0, 1, 3)
                self.felder[schl] = c
                continue
            lab = QLabel(_(text))
            lab.setWordWrap(True)
            lab.setMaximumWidth(150)
            g.addWidget(lab, r, 0)
            if art == "wahl":
                cb = QComboBox()
                cb.addItems([_(t) for __, t in wahl])
                cb.activated.connect(lambda *a, s=schl: self._geaendert(s))
                g.addWidget(cb, r, 1, Qt.AlignLeft)
                self.felder[schl] = cb
                continue
            f = QWidget()
            fl = QHBoxLayout(f)
            fl.setContentsMargins(0, 0, 0, 0)
            felder = []
            for __ in range(2 if art == "paar" else 1):
                e = QLineEdit()
                e.setValidator(QRegularExpressionValidator(ZAHL, e))
                e.setFixedWidth(52)
                e.textEdited.connect(lambda *a, s=schl: self._geaendert(s))
                fl.addWidget(e)
                felder.append(e)
            g.addWidget(f, r, 1, Qt.AlignLeft)
            g.addWidget(hinweis(_("empty = {wert}").format(wert=kks.wert_text(vorgabe))), r, 2)
            self.felder[schl] = felder

    # ------------------------------------------------------------------ Werte
    def geladen(self):
        return self.datei_werte is not None

    def zuruecksetzen(self):
        self.datei_werte, self.aenderungen = None, {}

    def _wert(self, schl, vorgabe=None):
        if schl in self.aenderungen:
            w = self.aenderungen[schl]
            return vorgabe if w is None else w
        return (self.datei_werte or {}).get(schl, vorgabe)

    def neu_laden(self):
        self.datei_werte = kks.lesen(self.ko)
        self.aenderungen = {}
        self.schriften = kks.schriftfamilien(kks.schriftordner(self.bereich.profil, self.bereich.befund))
        self._fuellen()

    def _fuellen(self):
        if not self.gebaut():
            return
        self._laden = True
        try:
            self.schrift.clear()
            self.schrift.addItems(self.schriften)
            self.schrift.setCurrentText(self._wert(kks.SCHRIFTART) or "")
            for schl, __, art, vorgabe, wahl in kks.ALLE:
                w = self._wert(schl)
                f = self.felder[schl]
                if art == "an":
                    f.setChecked(bool(w if w is not None else vorgabe))
                elif art == "wahl":
                    w = vorgabe if w is None else w
                    i = next((n for n, (k, __) in enumerate(wahl) if gleich(k, w)), -1)
                    if i < 0:
                        f.setEditable(True)
                        f.setCurrentText(str(w))
                    else:
                        f.setCurrentIndex(i)
                elif art == "paar":
                    werte = w if isinstance(w, list) and len(w) == 2 else ["", ""]
                    for x, y in zip(f, werte):
                        x.setText(str(y))
                else:
                    f[0].setText("" if w is None else str(w))
        finally:
            self._laden = False
        self._buch_zeigen()
        self.stand_zeigen()

    def _schrift_geaendert(self):
        if self._laden or self.datei_werte is None:
            return
        name = self.schrift.currentText().strip()
        self._setzen(kks.SCHRIFTART, name or None)

    def _geaendert(self, schl):
        if self._laden or self.datei_werte is None:
            return
        __, __, art, vorgabe, wahl = next(x for x in kks.ALLE if x[0] == schl)
        f = self.felder[schl]
        try:
            if art == "an":
                w = 1 if f.isChecked() else 0
            elif art == "wahl":
                i = f.currentIndex()
                w = wahl[i][0] if 0 <= i < len(wahl) else vorgabe
            elif art == "paar":
                teile = [zahl_oder_leer(x.text()) for x in f]
                w = None if all(t is None for t in teile) else [t if t is not None else d
                                                                for t, d in zip(teile, vorgabe)]
            else:
                w = zahl_oder_leer(f[0].text())
        except ValueError:
            return
        self._setzen(schl, w, vorgabe)

    def _setzen(self, schl, w, vorgabe=None):
        im_profil = (self.datei_werte or {}).get(schl)
        if gleich(w, im_profil) or (w is not None and gleich(w, vorgabe) and im_profil is None):
            self.aenderungen.pop(schl, None)
        else:
            self.aenderungen[schl] = w
        self.stand_zeigen()
        self._planen(PAUSE, self.ins_bild)

    def ungespeichert(self):
        return bool(self.aenderungen)

    # ------------------------------------------------------------------ Buchwerte
    def _buch_aus_geaendert(self, an):
        self.app.e["werkbank_buchwerte_aus"] = bool(an)
        self._planen(100, self.ins_bild)

    def _buch_zeigen(self):
        if not self.gebaut():
            return
        if self.bereich.modus() != "lesen":
            text = _("The start screen shows no book.")
        elif self.buchwerte is None:
            text = _("Sample text: it has no book data, so the general values apply.")
        elif not self.buchwerte:
            text = _("The book has no values of its own: the general values apply.")
        else:
            liste = ", ".join(f"{k.removeprefix('copt_')} = {kks.wert_text(w)}" for k, w in sorted(self.buchwerte.items()))
            text = _("The book has its own values ({n}): {liste}.").format(n=len(self.buchwerte), liste=liste)
            text += " " + (_("The workbench ignores them now.") if self.app.e.get("werkbank_buchwerte_aus") else
                           _("They win over the general values - changes above do not show for this book."))
        self.buch_text.setText(text)

    # ------------------------------------------------------------------ Werkbank
    def in_kopie(self, ko):
        if self.aenderungen:
            kks.schreiben(ko, self.aenderungen)
        b = self.bereich
        buch = b._gewaehltes_buch() if b.modus() == "lesen" else None
        if buch:
            from bookbench.preview import workbench as kwb
            sdr = Path(ko).parent / "buecher" / kv._sdr_name(kwb.kopiename(buch))
            self.buchwerte = kks.buchwerte(sdr)
            if self.app.e.get("werkbank_buchwerte_aus"):
                kks.buchwerte_entfernen(sdr)
        else:
            self.buchwerte = None

    def nach_start(self):
        self._buch_zeigen()

    def speichern(self):
        if not self.aenderungen:
            return False
        kks.schreiben(self.ko, self.aenderungen)
        kpl._profil_geaendert(self.bereich.profil, self.plugin)
        self.app.status.set(_("Font and margins saved in the profile ({n} changed).").format(n=len(self.aenderungen)))
        self.neu_laden()
        return True

    def verwerfen(self):
        if not self.aenderungen or not self.verwerfen_ok():
            return
        self.neu_laden()
        self.ins_bild()


# ====================================================================== Patches
class PatchSeite(_NeustartSeite):
    plugin = "patches"
    titel = N_("Patches")
    ansicht = None                                # Patches betreffen beide Ansichten

    def __init__(self, bereich):
        super().__init__(bereich)
        self.liste = None                         # kks.patches() des Profils
        self.schalter = {}                        # Entwurf: Name -> an
        self.alle_neu = None                      # Entwurf: alle aus (True/False) oder None = wie im Profil
        self.fehler = {}                          # Name -> Meldung aus der Werkbank
        self.gewaehlt_name = None
        self._laden = False
        self._fenster = None

    def inhalt_bauen(self):
        self.kopf.setText(_("User patches (koreader/patches) as in KOReader's patch management. They run when "
                            "KOReader starts, so the workbench restarts after a change."))
        i = self._abschnitt("liste", _("Patches"))
        lay = QVBoxLayout(i)
        lay.setContentsMargins(0, 0, 0, 0)
        self.alle = QCheckBox(_("Switch off all patches (like KOReader's switch)"))
        self.alle.toggled.connect(self._alle_geaendert)
        lay.addWidget(self.alle)
        self.baum = QTreeWidget()
        self.baum.setHeaderHidden(True)
        self.baum.setMinimumHeight(220)
        self.baum.itemDoubleClicked.connect(lambda *a: self.umschalten())
        self.baum.currentItemChanged.connect(lambda *a: self._auswahl_zeigen())
        self.baum.keyPressEvent = self._taste
        lay.addWidget(self.baum)
        g = QGridLayout()
        for n, (text, fn) in enumerate(((_("On/off"), self.umschalten), (_("Show …"), self.zeigen),
                                        (_("Add …"), self.hinzufuegen), (_("Delete"), self.loeschen))):
            k = QPushButton(text)
            k.clicked.connect(lambda *a, fn=fn: fn())
            g.addWidget(k, n // 2, n % 2)
        lay.addLayout(g)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.detail)
        lay.addWidget(hinweis(_("☑ on, ☐ off, ⚠ failed in the workbench (message below when selected). Some patches "
                                "need the e-reader and never run on the computer. Adding and deleting change the "
                                "profile at once; switching on/off is a draft until \"Save to profile\"."), BREITE))
        i = self._abschnitt("bookbench", _("Patches from Bookbench"))
        lay = QVBoxLayout(i)
        lay.setContentsMargins(0, 0, 0, 0)
        self.mit_rahmen = QVBoxLayout()
        lay.addLayout(self.mit_rahmen)
        lay.addWidget(hinweis(_("They are also attached to every Bookbench release on GitHub, for copying into "
                                "koreader/patches by hand. To bring them onto the e-reader from here: add, then "
                                "\"To the e-reader …\"."), BREITE))
        if self.liste is not None:
            self._fuellen()

    def _taste(self, ev):
        if ev.key() == Qt.Key_Space:
            self.umschalten()
        else:
            QTreeWidget.keyPressEvent(self.baum, ev)

    def _mitgebracht_zeigen(self):
        while self.mit_rahmen.count():
            w = self.mit_rahmen.takeAt(0).widget()
            if w:
                w.deleteLater()
        stand_text = {"fehlt": _("not in the profile"), "aktuell": _("in the profile"),
                      "anders": _("in the profile, another version")}
        knopf_text = {"fehlt": _("Add"), "aktuell": None, "anders": _("Update")}
        for m in kks.mitgebracht(self.ko):
            z = QWidget()
            zl = QVBoxLayout(z)
            zl.setContentsMargins(0, 4, 0, 4)
            kopf = QHBoxLayout()
            t = QLabel(m["name"].removesuffix(".lua"))
            t.setProperty("rolle", "abschnitt")
            kopf.addWidget(t)
            kopf.addWidget(hinweis(stand_text[m["stand"]]))
            kopf.addStretch(1)
            if knopf_text[m["stand"]]:
                k = QPushButton(knopf_text[m["stand"]])
                k.clicked.connect(lambda *a, m=m: self._mitgebracht_hinzufuegen(m))
                kopf.addWidget(k)
            zl.addLayout(kopf)
            b = QLabel(_(m["beschreibung"]))
            b.setWordWrap(True)
            zl.addWidget(b)
            self.mit_rahmen.addWidget(z)

    def _mitgebracht_hinzufuegen(self, m):
        kks.mitgebracht_einspielen(self.ko, m["name"])     # ausgeschaltete alte Fassung: ersetzen, Schalter bleibt
        kpl._profil_geaendert(self.bereich.profil, self.plugin)
        self.app.status.set(_("Patch {name} added to the profile.").format(name=m["name"]))
        self.liste_neu()
        self._planen(100, self.ins_bild)

    def liste_neu(self):
        """Liste neu lesen (z. B. nachdem eine andere Seite einen Patch hinzugefügt hat); Entwurf bleibt."""
        if self.liste is None:
            return
        self.liste = kks.patches(self.ko)
        self._fuellen()

    def geladen(self):
        return self.liste is not None

    def zuruecksetzen(self):
        self.liste, self.schalter, self.alle_neu = None, {}, None

    def neu_laden(self):
        self.liste = kks.patches(self.ko)
        self.schalter, self.alle_neu = {}, None
        self._fehler_lesen()
        self._fuellen()

    def _an(self, p):
        return self.schalter.get(p["name"], p["an"])

    def _alle_aus(self):
        return kks.alle_aus(self.ko) if self.alle_neu is None else self.alle_neu

    def _fehler_lesen(self):
        wb = self.bereich.werkbank
        log = (wb.arbeit / kv.LOG) if wb else None
        try:
            self.fehler = kks.patch_fehler(log.read_text(encoding="utf-8", errors="replace")) if log else {}
        except OSError:
            self.fehler = {}

    def _fuellen(self):
        if not self.gebaut():
            return
        b = self.baum
        b.blockSignals(True)
        b.clear()
        self._laden = True
        self.alle.setChecked(bool(self._alle_aus()))
        self._laden = False
        stufen = dict(kks.STUFEN)
        gruppen = {}
        aktuell = None
        for p in self.liste or []:
            if p["stufe"] not in gruppen:
                g = QTreeWidgetItem([_(stufen.get(p["stufe"], p["stufe"]))])
                b.addTopLevelItem(g)
                g.setExpanded(True)
                gruppen[p["stufe"]] = g
            zeichen = "☑ " if self._an(p) else "☐ "
            text = zeichen + p["name"].removesuffix(".lua") + ("  ⚠" if p["name"] in self.fehler else "") + (
                "  ●" if p["name"] in self.schalter else "")
            it = QTreeWidgetItem([text])
            it.setData(0, Qt.UserRole, p["name"])
            gruppen[p["stufe"]].addChild(it)
            if p["name"] == self.gewaehlt_name:
                aktuell = it
        if not self.liste:
            b.addTopLevelItem(QTreeWidgetItem([_("No patches in the profile.")]))
        if aktuell is not None:
            b.setCurrentItem(aktuell)
        b.blockSignals(False)
        self._auswahl_zeigen()
        self._mitgebracht_zeigen()
        self.stand_zeigen()

    def _gewaehlt(self):
        return next((p for p in self.liste or [] if p["name"] == self.gewaehlt_name), None)

    def _auswahl_zeigen(self):
        it = self.baum.currentItem()
        name = it.data(0, Qt.UserRole) if it else None
        if name:
            self.gewaehlt_name = name
        p = self._gewaehlt() if name else None
        if not p:
            self.detail.setText("")
            return
        text = p["datei"]
        if p["name"] in self.fehler:
            text += "\n" + _("⚠ Failed in the workbench: {meldung}").format(meldung=self.fehler[p["name"]])
        self.detail.setText(text)

    def waehlen(self, name):
        """Patch in der Liste wählen (Tests, Menü)."""
        self.gewaehlt_name = name
        self._fuellen()

    def umschalten(self):
        p = self._gewaehlt()
        if not p:
            return
        neu = not self._an(p)
        if neu == p["an"]:
            self.schalter.pop(p["name"], None)
        else:
            self.schalter[p["name"]] = neu
        self._fuellen()
        self._planen(PAUSE, self.ins_bild)

    def _alle_geaendert(self, an):
        if self._laden:
            return
        neu = bool(an)
        self.alle_neu = None if neu == kks.alle_aus(self.ko) else neu
        self._fuellen()
        self._planen(PAUSE, self.ins_bild)

    def ungespeichert(self):
        return bool(self.schalter) or self.alle_neu is not None

    # ------------------------------------------------------------------ Dateien (wirken sofort im Profil)
    def zeigen(self):
        p = self._gewaehlt()
        if not p:
            return
        f = QDialog(self.app)
        f.setWindowTitle(p["name"])
        f.resize(760, 560)
        lay = QVBoxLayout(f)
        t = QPlainTextEdit(kks.patch_text(self.ko, p["datei"]))
        t.setReadOnly(True)
        t.setLineWrapMode(QPlainTextEdit.NoWrap)
        t.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        lay.addWidget(t)
        f.show()
        self._fenster = f

    def hinzufuegen(self):
        pfad = dialogs.datei_oeffnen(self.app, _("Add a patch"), "", [(_("Lua patches"), "*.lua"),
                                                                      (_("All files"), "*")])
        if not pfad:
            return
        pfad = Path(pfad)
        try:
            text = pfad.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self.app.status.set(str(e))
            return
        warnung = kks.lua_pruefen(text)
        if warnung and not dialogs.frage(self.app, self.name(), warnung + "\n" + _("Add it anyway?")):
            return
        name = pfad.name if pfad.name.endswith(".lua") else pfad.name + ".lua"
        if not re.match(r"^\d+-", name):
            name = "2-" + name                        # ohne Stufe würde KOReader ihn nie ausführen
        ziel = kks.patch_ordner(self.ko)
        ziel.mkdir(parents=True, exist_ok=True)
        if (ziel / name).exists() and not dialogs.frage(
                self.app, self.name(), _("{name} is already in the profile. Replace it?").format(name=name)):
            return
        shutil.copy2(pfad, ziel / name)
        kpl._profil_geaendert(self.bereich.profil, self.plugin)
        self.app.status.set(_("Patch {name} added to the profile.").format(name=name))
        self.liste = kks.patches(self.ko)
        self._fuellen()
        self._planen(100, self.ins_bild)

    def loeschen(self):
        p = self._gewaehlt()
        if not p:
            return
        if not dialogs.frage(self.app, self.name(), _("Delete the patch {name} from the profile?").format(name=p["name"])):
            return
        try:
            (kks.patch_ordner(self.ko) / p["datei"]).unlink()
        except OSError as e:
            self.app.status.set(str(e))
            return
        self.schalter.pop(p["name"], None)
        self.gewaehlt_name = None
        kpl._profil_geaendert(self.bereich.profil, self.plugin)
        self.liste = kks.patches(self.ko)
        self._fuellen()
        self._planen(100, self.ins_bild)

    # ------------------------------------------------------------------ Werkbank
    def ins_bild(self):
        if self.bereich.unterseite() == self.plugin:
            self.bereich.werkbank_starten(still=True)

    def in_kopie(self, ko):
        """Zustand in der Wegwerf-Kopie herstellen. workbench.arbeitsprofil hat ".patches_disabled" schon in
        einzeln ausgeschaltete Patches verwandelt; hier gilt der Entwurf."""
        if self.liste is None:
            return
        alle_aus = self._alle_aus()
        soll = {p["name"]: (self._an(p) and not alle_aus) for p in self.liste}
        kks.patches_anwenden(ko, soll)

    def nach_start(self):
        if self.liste is not None:
            self._fehler_lesen()
            QTimer.singleShot(1500, self._nachlesen)  # späte Patches laufen erst nach "ready"
            self._fuellen()

    def _nachlesen(self):
        if self.liste is not None:
            self._fehler_lesen()
            self._fuellen()

    def speichern(self):
        if not self.ungespeichert():
            return False
        kks.patches_anwenden(self.ko, self.schalter, self.alle_neu)
        kpl._profil_geaendert(self.bereich.profil, self.plugin)
        self.app.status.set(_("Patches saved in the profile."))
        self.neu_laden()
        return True

    def verwerfen(self):
        if not self.ungespeichert() or not self.verwerfen_ok():
            return
        self.neu_laden()
        self.ins_bild()
