# -*- coding: utf-8 -*-
"""
area_device.py - Bereich E-Reader (Kennung "kobo"; Qt, Tk-Vorlage tk/area_device.py): angeschlossenen
E-Reader (Kobo, Kindle, PocketBook) anzeigen, KOReader-Einstellungen sichern und zurückspielen, Wörterbücher
kopieren, auswerfen. Die Logik steckt in device/device.py, hier nur die Oberfläche.

  Kopf          Modell (bei mehreren Geräten eine Auswahl), Laufwerk, Firmware, KOReader-Version, frei
  Sicherungen   Tabelle der Sicherungen links, Teile (Haken mit Stand auf dem Gerät) rechts, scrollbar
  Wörterbücher  Quelle auf dem Rechner, Stand je Wörterbuch auf dem Gerät (veraltet/fehlt hinterlegt);
                Doppelklick öffnet das Wörterbuch im Bereich Wörterbuch

Das Gerät wird regelmäßig gesucht (Einstellung kobo_suche_sekunden, Hilfsthread), damit Anstecken und
Abziehen ohne Knopfdruck erkannt werden; beim Anstecken öffnet Bookbench die Bücher vom Gerät (Einstellung
kobo_oeffnen). Langsames (Sichern, Zurückspielen, Kopieren, Auswerfen) läuft über app.hintergrund().
Der Zustand (Gerät, Angaben, Teile, gewählte Sicherung und Wörterbücher) hängt am Bereich, nicht an den
Widgets: er übersteht den Neuaufbau beim Sprachwechsel.
"""
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QScrollArea, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from bookbench.device import device as kg
from bookbench.device import models as kmo
from bookbench.i18n import N_, _, ngettext
from bookbench.ui import dialogs, theme, threads
from bookbench.ui.area import Bereich
from bookbench.ui.device_sync import AbgleichTeil
from bookbench.ui.panes import Teiler

KURZ = {"einstellungen": N_("Settings"), "settings": N_("Statistics/plugins"), "buchdaten": N_("Book data"),
        "anpassungen": N_("Tweaks"), "kobo": N_("Kobo settings")}
# Kennungen aus device.woerterbuecher (Namen aus der Zeit, als es nur Kobos gab)
STAND_TEXT = {"aktuell": N_("up to date"), "veraltet": N_("outdated on the e-reader"),
              "fehlt": N_("missing on the e-reader"), "nur auf dem Kobo": N_("only on the e-reader"), "kein Kobo": "-"}
# Anlass einer Sicherung (steht in der ZIP); "vor dem Zurückspielen" schrieben Versionen bis 0.16
ANLASS = {"vor_zurueckspielen": N_("before restoring"), "vor dem Zurückspielen": N_("before restoring"),
          "vor_rueckweg": N_("before writing from the preview")}


def _datum(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return iso or "?"


def _kurz(k):
    return _(KURZ[k]) if k in KURZ else k


class EReaderBereich(AbgleichTeil, Bereich):
    kennung = "kobo"
    titel = N_("E-reader")
    symbol = "kobo"

    def __init__(self, app):
        super().__init__(app)
        self.wurzeln, self.wurzel, self.info = [], None, {}
        self.vorhanden, self.groessen = {}, {}   # Teil -> Dateien bzw. Bytes auf dem Gerät
        self.geschrieben = False                 # in dieser Sitzung etwas aufs Gerät geschrieben
        self._suche_laeuft = False
        self._sicherungen = {}                   # Pfad -> Inhaltsverzeichnis
        self._dicts = []
        self._quellen = (None, 0.0, [])          # (Quelle, Zeitpunkt, Wörterbuch-Ordner) - Suche kann dauern
        self._neu_angesteckt = None              # Wurzel, für die noch über das Öffnen entschieden wird
        self.sicherung_gewaehlt = None           # Pfad der gewählten Sicherung
        self.dicts_gewaehlt = set()
        self.abgleich_init()                     # Bücher: Rechner ↔ E-Reader (ui/device_sync.py, seit 2.1)
        self.takt = QTimer()
        self.takt.setSingleShot(True)
        self.takt.timeout.connect(self._regelmaessig)
        self.takt.start(200)

    # ================================================================ Aufbau der Seite
    def bauen(self):
        s = QWidget()
        lay = QVBoxLayout(s)
        lay.setContentsMargins(0, 0, 0, 0)
        kopf = QHBoxLayout()
        self.titel_label = QLabel("")
        self.titel_label.setProperty("rolle", "ueberschrift")
        kopf.addWidget(self.titel_label)
        self.wahl = QComboBox()
        self.wahl.setMinimumWidth(260)
        self.wahl.activated.connect(lambda *a: self._gewaehlt(Path(self.wahl.currentData())))
        kopf.addWidget(self.wahl)
        kopf.addStretch(1)
        lay.addLayout(kopf)
        self.zeile = QLabel("")
        self.zeile.setProperty("rolle", "hinweis")
        self.zeile.setWordWrap(True)
        self.zeile.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.zeile)
        lay.addSpacing(8)

        aussen = Teiler(self.app, "ereader_abgleich", 250, fest="links", ausrichtung=Qt.Vertical, minimum=150)
        aussen.addWidget(self.abgleich_bauen())
        oben_unten = Teiler(self.app, "ereader_woerterbuecher", 190, fest="rechts", ausrichtung=Qt.Vertical,
                            minimum=110)
        # -- Sicherungen
        oben = QWidget()
        ol = QVBoxLayout(oben)
        ol.setContentsMargins(0, 0, 0, 6)
        t = QLabel(_("Backups of the KOReader settings"))
        t.setProperty("rolle", "abschnitt")
        ol.addWidget(t)
        self.ordner_label = QLabel("")
        self.ordner_label.setProperty("rolle", "hinweis")
        ol.addWidget(self.ordner_label)
        mitte = QHBoxLayout()
        self.baum = QTreeWidget()
        self.baum.setRootIsDecorated(False)
        self.baum.setUniformRowHeights(True)
        self.baum.setSelectionMode(QAbstractItemView.SingleSelection)
        self.baum.setHeaderLabels([_("Date"), _("Device"), _("Reason"), _("Contents"), _("Size")])
        k = self.baum.header()
        k.setStretchLastSection(False)
        for i, modus in enumerate((QHeaderView.ResizeToContents, QHeaderView.ResizeToContents,
                                   QHeaderView.ResizeToContents, QHeaderView.Stretch, QHeaderView.ResizeToContents)):
            k.setSectionResizeMode(i, modus)
        self.baum.currentItemChanged.connect(lambda *a: self._sicherung_gewaehlt())
        self.baum.itemDoubleClicked.connect(lambda *a: self.zurueckspielen())
        mitte.addWidget(self.baum, 1)
        roll = QScrollArea()
        roll.setWidgetResizable(True)
        roll.setFrameShape(QFrame.NoFrame)
        roll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        teile = QWidget()
        tl = QVBoxLayout(teile)
        tl.setContentsMargins(14, 0, 4, 0)
        tl.addWidget(QLabel(_("Parts (for backing up and restoring)")))
        self.teil_knopf, self.teil_info = {}, {}
        gewaehlt = set(self.app.e.get("kobo_teile") or [])
        for k, name, beschreibung, __, __ in kg.TEILE:
            c = QCheckBox(_(name))
            c.setChecked(k in gewaehlt)
            c.toggled.connect(lambda *a: self._teile_merken())
            tl.addWidget(c)
            for text in (_(beschreibung), ""):
                h = QLabel(text)
                h.setProperty("rolle", "hinweis")
                h.setWordWrap(True)
                h.setContentsMargins(22, 0, 0, 0)
                tl.addWidget(h)
            self.teil_knopf[k], self.teil_info[k] = c, h
            tl.addSpacing(4)
        tl.addStretch(1)
        roll.setWidget(teile)
        roll.setFixedWidth(min(400, teile.sizeHint().width() + 24))
        mitte.addWidget(roll)
        ol.addLayout(mitte, 1)
        oben_unten.addWidget(oben)

        # -- Wörterbücher
        unten = QWidget()
        ul = QVBoxLayout(unten)
        ul.setContentsMargins(0, 6, 0, 0)
        t = QLabel(_("Dictionaries: computer → e-reader"))
        t.setProperty("rolle", "abschnitt")
        ul.addWidget(t)
        q = QHBoxLayout()
        self.quelle_label = QLabel("")
        self.quelle_label.setProperty("rolle", "hinweis")
        self.quelle_label.setWordWrap(True)
        q.addWidget(self.quelle_label, 1)
        k = QPushButton(_("Choose source …"))
        k.clicked.connect(self.quelle_waehlen)
        q.addWidget(k)
        ul.addLayout(q)
        self.dict_baum = QTreeWidget()
        self.dict_baum.setRootIsDecorated(False)
        self.dict_baum.setUniformRowHeights(True)
        self.dict_baum.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.dict_baum.setHeaderLabels([_("Dictionary"), _("On the e-reader"), _("Folder in the source")])
        k = self.dict_baum.header()
        k.setSectionResizeMode(0, QHeaderView.Stretch)
        k.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        k.setSectionResizeMode(2, QHeaderView.Stretch)
        self.dict_baum.itemSelectionChanged.connect(self._dicts_merken)
        self.dict_baum.itemDoubleClicked.connect(lambda it, *a: self.woerterbuch_oeffnen(it.text(0)))
        ul.addWidget(self.dict_baum, 1)
        oben_unten.addWidget(unten)
        aussen.addWidget(oben_unten)
        lay.addWidget(aussen, 1)
        self.seite = s
        self.anzeigen()
        self._teile_zeigen()
        return s

    # ================================================================ Werkzeugleiste, Menü, Seitenleiste
    def werkzeug(self):
        return [("oeffnen", _("Books"), self.buecher_oeffnen,
                 _("Open the books on the e-reader in Library, Chapters and Metadata")),
                ("abgleichen", _("Sync"), self.abgleichen,
                 _("Copy the checked books between the library on this computer and the e-reader")),
                None,
                ("sichern", _("Back up"), self.sichern,
                 _("Back up the chosen parts of the KOReader settings into a ZIP file")),
                ("zurueckschreiben", _("Restore"), self.zurueckspielen,
                 _("Write the chosen parts from the selected backup to the e-reader (double-click)")),
                None,
                ("woerterbuch", _("Dictionary"), self.woerterbuch_kopieren,
                 _("Selected dictionaries (otherwise all that are not up to date) to data/dict in the KOReader "
                   "folder")),
                None,
                ("auswerfen", _("Eject"), self.auswerfen, _("Unmount the e-reader; then the cable can come off"))]

    def menue(self, leiste):
        m = leiste.addMenu(_("E-reader"))
        for eintrag in ((_("Find e-reader"), lambda: self.suchen(still=False)),
                         (_("Open books on the e-reader"), self.buecher_oeffnen), None,
                         (_("Compare books with the library"), lambda: self.abgleich_vergleichen()),
                         (_("Sync books"), self.abgleichen),
                         (_("Link library …"), self.abgleich_verknuepfen), None,
                         (_("Back up KOReader settings"), self.sichern),
                         (_("Restore backup …"), self.zurueckspielen),
                         (_("Copy dictionary"), self.woerterbuch_kopieren), None,
                         (_("Eject"), self.auswerfen)):
            if eintrag is None:
                m.addSeparator()
            else:
                m.addAction(eintrag[0], lambda fn=eintrag[1]: self._aus_menue(fn))

    def _aus_menue(self, fn):
        if self.app._aktuell != self.kennung:
            self.app.bereich_zeigen(self.kennung)
        fn()

    def marken(self):
        offen = sum(1 for __, st, __ in self._dicts if st in ("veraltet", "fehlt")) if self.wurzel else 0
        return self.abgleich_marken() + [m for m in (("ereader", offen), ("verbunden", 1 if self.wurzel else 0)) if m[1]]

    def beim_zeigen(self):
        if self.seite is not None:
            self.anzeigen()

    def beenden(self):
        self.takt.stop()

    # ================================================================ Suchen
    def _regelmaessig(self):
        self.suchen(still=True)
        self.app.ordner_pruefen()
        if self._neu_angesteckt and not self.app._arbeit:
            self._angesteckt(self._neu_angesteckt)
        self.takt.start(max(1, int(self.app.e.get("kobo_suche_sekunden") or 3)) * 1000)

    def suchen(self, still=True):
        if self._suche_laeuft:
            return
        self._suche_laeuft = True
        zusaetzlich = [self.app.ordner] if self.app.ordner else []

        def arbeit():
            try:
                gefunden = kg.geraete_finden(zusaetzlich)
            except Exception:                              # nie den Takt abreißen lassen
                gefunden = []
            threads.im_hauptthread(lambda: self._gefunden(gefunden, still))
        threads.starten(arbeit)

    def _gefunden(self, gefunden, still):
        self._suche_laeuft = False
        if gefunden == self.wurzeln and self.wurzel in gefunden + [None]:
            if not still:
                self.app.status.set(f"{self.info.get('artname') or 'Kobo'}: {self.wurzel}" if self.wurzel
                                    else _("No e-reader found."))
            if not still and self.wurzel:
                self._gewaehlt(self.wurzel)                # Angaben auffrischen
            return
        vorher = self.wurzel
        self.wurzeln = gefunden
        self.wurzel = vorher if vorher in gefunden else (gefunden[0] if gefunden else None)
        if self.wurzel is None:
            self.info, self.vorhanden, self.groessen = {}, {}, {}
            self._neu_angesteckt = None
            self.abgleich_reader_neu()
            self.anzeigen()
            if vorher:
                self.app.status.set(_("E-reader no longer connected."))
            self.app.ordner_pruefen()
            return
        self._gewaehlt(self.wurzel)
        if self.wurzel != vorher:
            self.app.status.set(_("{modell} connected: {ordner}").format(modell=self.info.get("modell", "?"),
                                                                         ordner=self.wurzel))
            self.app.ordner_pruefen()
            self._neu_angesteckt = self.wurzel        # beim Start oder während Arbeit: nächste Suche
            if not self.app._arbeit:
                self._angesteckt(self.wurzel)

    def _auf_geraet(self, wurzel=None):
        """Liegt der geöffnete Bücherordner auf dem Gerät?"""
        a, w = self.app, wurzel or self.wurzel
        try:
            return bool(a.ordner and w and Path(a.ordner).resolve().is_relative_to(Path(w).resolve()))
        except (OSError, ValueError):
            return False

    def _angesteckt(self, wurzel):
        """Neu angesteckt: Bücher vom Gerät öffnen, je nach Einstellung kobo_oeffnen."""
        self._neu_angesteckt = None
        a = self.app
        if wurzel != self.wurzel or not wurzel.exists() or self._auf_geraet(wurzel):
            return                                     # weg, oder seine Bücher sind schon offen
        art = a.e.get("kobo_oeffnen", "auto")
        if art == "nie":
            return
        if self.ab_bib is not None:                    # verknüpfte Bibliothek auf dem Rechner statt der Reader-Bücher
            if a.ordner and Path(a.ordner).resolve() == self.ab_bib.resolve():
                return
            if a.ordner or art == "fragen":
                text = _("{modell} connected. Open its library on this computer?").format(
                    modell=self.info.get("modell") or str(wurzel)) + "\n\n" + str(self.ab_bib)
                if a.ordner:
                    text += "\n\n" + _("Currently open: {ordner}").format(ordner=a.ordner)
                if not dialogs.frage(a, self.name(), text):
                    return
            if a._aenderungen_verwerfen_ok():
                a.laden(str(self.ab_bib))
            return
        if a.ordner or art == "fragen":
            name = self.info.get("modell") or self.info.get("artname") or str(wurzel)
            text = _("{modell} connected. Open the books on the e-reader?").format(modell=name)
            if a.ordner:
                text += "\n\n" + _("Currently open: {ordner}").format(ordner=a.ordner)
            if not dialogs.frage(a, self.name(), text):
                return
        if a._aenderungen_verwerfen_ok():
            a.laden(wurzel)

    def _gewaehlt(self, wurzel):
        self.wurzel = wurzel
        self.info = kg.geraet_info(wurzel)
        self.abgleich_reader_neu()
        self.anzeigen()

        def arbeit():
            try:
                vorhanden = kg.teile_ermitteln(wurzel)
            except OSError:
                vorhanden = {}
            groessen = {k: kg.summe(wurzel, v) for k, v in vorhanden.items()}
            threads.im_hauptthread(lambda: self._teile(wurzel, vorhanden, groessen))
        threads.starten(arbeit)

    def _teile(self, wurzel, vorhanden, groessen):
        if wurzel != self.wurzel:
            return
        self.vorhanden, self.groessen = vorhanden, groessen
        self._teile_zeigen()

    def _teile_zeigen(self):
        if self.seite is None:
            return
        art = self.info.get("art") or kg.STANDARD_ART
        for k, lab in self.teil_info.items():
            if not self.wurzel:
                lab.setText("")
                self.teil_knopf[k].setEnabled(True)
                continue
            moeglich = kg.NUR_BEI.get(k, art) == art
            self.teil_knopf[k].setEnabled(moeglich)
            if not moeglich:
                lab.setText(_("not on a {geraet}").format(geraet=kg.art_name(art)))
            elif k in self.vorhanden:
                n = len(self.vorhanden[k])
                lab.setText(ngettext("on the e-reader: {n} file, {groesse}", "on the e-reader: {n} files, {groesse}", n)
                            .format(n=n, groesse=kg.groesse_text(self.groessen.get(k, 0))))
            else:
                lab.setText(_("not on the e-reader"))

    # ================================================================ Anzeige
    def sicherungsordner(self):
        return Path(self.app.e["sicherungsordner"]) / "KOReader"

    def anzeigen(self):
        if self.seite is None:
            self._dicts_lesen()
            return
        i = self.info
        if self.wurzel:
            self.titel_label.setText(i.get("modell") or i.get("artname") or "?")
            teile = [str(self.wurzel)]
            if i.get("art", "kobo") != "kobo":
                teile.append(_("KOReader folder {ordner}").format(ordner=kg.ko_ordner(i["art"])))
            if i.get("modellnummer") and not kmo.modell(i["modellnummer"]):
                teile.append(_("model number {nr} unknown").format(nr=i["modellnummer"]))
            if i.get("firmware"):
                teile.append(f"Firmware {i['firmware']}")
            teile.append(f"KOReader {i['koreader']}" if i.get("koreader") else _("KOReader not installed"))
            if i.get("frei") is not None:
                teile.append(_("{frei} of {gesamt} free").format(frei=kg.groesse_text(i["frei"]),
                                                               gesamt=kg.groesse_text(i["gesamt"])))
            self.zeile.setText("  ·  ".join(teile))
        else:
            self.titel_label.setText(_("No e-reader connected."))
            self.zeile.setText(_("Connect the Kobo, Kindle or PocketBook by USB and confirm the connection on the "
                                 "device (KOReader: USB mass storage). It is detected automatically."))
        self.wahl.blockSignals(True)
        self.wahl.clear()
        for w in self.wurzeln:
            self.wahl.addItem(str(w), str(w))
        self.wahl.setCurrentIndex(self.wahl.findData(str(self.wurzel)) if self.wurzel else -1)
        self.wahl.blockSignals(False)
        self.wahl.setVisible(len(self.wurzeln) > 1)
        self.ordner_label.setText(_("Folder: {ordner}").format(ordner=self.sicherungsordner()))
        self.abgleich_zeigen()
        self._teile_zeigen()
        self._sicherungen_fuellen()
        self._woerterbuecher_fuellen()

    def _sicherungen_fuellen(self):
        b = self.baum
        b.blockSignals(True)
        b.clear()
        self._sicherungen = {}
        for s in kg.sicherungen(self.sicherungsordner()):
            pfad = s["pfad"]
            self._sicherungen[pfad] = s
            inhalt = ", ".join(_kurz(k) for k in s.get("teile", {}))
            try:
                groesse = kg.groesse_text(Path(pfad).stat().st_size)
            except OSError:
                groesse = "?"
            anlass = s.get("anlass") or ""
            geraet = (s.get("geraet") or {}).get("modell") or kg.art_name(s.get("art"))
            it = QTreeWidgetItem([_datum(s.get("datum")), geraet, _(ANLASS[anlass]) if anlass in ANLASS else anlass,
                                  inhalt, groesse])
            it.setData(0, Qt.UserRole, pfad)
            it.setTextAlignment(4, Qt.AlignRight | Qt.AlignVCenter)
            b.addTopLevelItem(it)
            if pfad == self.sicherung_gewaehlt:
                b.setCurrentItem(it)
        b.blockSignals(False)

    def _woerterbuch_quelle(self):
        return self.app.e.get("woerterbuch_quelle") or ""

    def _dicts_lesen(self):
        quelle = self._woerterbuch_quelle()
        self._dicts = kg.woerterbuecher(quelle, self.wurzel, self._woerterbuch_ordner(quelle))

    def _woerterbuecher_fuellen(self):
        self._dicts_lesen()
        if self.seite is not None:
            quelle = self._woerterbuch_quelle()
            self.quelle_label.setText(_("Source on this computer: {quelle}").format(quelle=quelle) if quelle else
                                      _("Source on this computer: not chosen yet (folder with the dictionary, e.g. "
                                        "My-Dictionary, or a folder with several)"))
            d = self.dict_baum
            d.blockSignals(True)
            d.clear()
            warn = QColor(theme.WARNZEILE[theme.modus()])
            for name, stand, ordner in self._dicts:
                try:
                    rel = str(Path(ordner).relative_to(quelle)) if ordner else ""
                except ValueError:
                    rel = str(ordner)
                it = QTreeWidgetItem([name, _(STAND_TEXT[stand]) if stand in STAND_TEXT else stand,
                                      "" if rel == "." else rel])
                if stand in ("veraltet", "fehlt"):
                    for c in range(3):
                        it.setBackground(c, warn)
                d.addTopLevelItem(it)
                it.setSelected(name in self.dicts_gewaehlt)
            d.blockSignals(False)
        if hasattr(self.app, "leiste"):
            self.app._zaehler()

    def _woerterbuch_ordner(self, quelle, neu=False):
        """Wörterbuch-Ordner der Quelle; die Suche läuft höchstens alle 10 s neu."""
        q, zeit, ordner = self._quellen
        if neu or q != quelle or time.time() - zeit > 10:
            ordner = kg.woerterbuch_quellen(quelle)
            self._quellen = (quelle, time.time(), ordner)
        return ordner

    def neu_zeichnen(self):
        if self.seite is not None:
            self._woerterbuecher_fuellen()

    def _dicts_merken(self):
        self.dicts_gewaehlt = {it.text(0) for it in self.dict_baum.selectedItems()}

    def _sicherung_gewaehlt(self):
        it = self.baum.currentItem()
        self.sicherung_gewaehlt = it.data(0, Qt.UserRole) if it else None
        s = self._sicherungen.get(self.sicherung_gewaehlt)
        if not s:
            return
        g = s.get("geraet") or {}
        teile = [f"{_kurz(k)} ({t.get('dateien', 0)})" for k, t in s.get("teile", {}).items()]
        text = _("Backup of {datum}:").format(datum=_datum(s.get("datum"))) + " " + ", ".join(teile)
        if g.get("seriennummer"):
            text += f"  ·  {g.get('modell', 'Kobo')} {g['seriennummer']}"
            if self.info.get("seriennummer") and g["seriennummer"] != self.info["seriennummer"]:
                text += " - " + _("a different device than the connected one")
        elif s.get("art") and s["art"] != "kobo":
            text += f"  ·  {g.get('modell') or kg.art_name(s['art'])}"
        if g.get("koreader"):
            text += f", KOReader {g['koreader']}"
        self.app.status.set(text)

    def _teile_merken(self):
        self.app.e["kobo_teile"] = self._gewaehlte_teile()

    def _gewaehlte_teile(self):
        if self.seite is None:
            return list(self.app.e.get("kobo_teile") or [])
        return [k for k, c in self.teil_knopf.items() if c.isChecked()]

    # ================================================================ Aktionen
    def _bereit(self):
        if self.app._arbeit:
            self.app.status.set(_("Still running: {arbeit}.").format(arbeit=self.app._arbeit))
            return False
        if not self.wurzel or not self.wurzel.exists():
            self.app.status.set(_("No e-reader connected."))
            return False
        return True

    def buecher_oeffnen(self):
        if self._bereit() and self.app._aenderungen_verwerfen_ok():
            self.app.laden(self.wurzel)
            self.app.bereich_zeigen("bibliothek")

    def sichern(self):
        if not self._bereit():
            return
        teile = [k for k in self._gewaehlte_teile() if k in self.vorhanden]
        if not teile:
            self.app.status.set(_("None of the chosen parts exist on the e-reader - nothing to back up."))
            return
        wurzel, info, ziel = self.wurzel, dict(self.info), self.sicherungsordner()
        anzahl = int(self.app.e["kobo_sicherungen_anzahl"])

        def arbeit():
            p = kg.sichern(wurzel, ziel, teile, info, anzahl)
            return _("Backed up: {name} ({groesse}).").format(name=p.name, groesse=kg.groesse_text(p.stat().st_size))
        self.app.hintergrund(_("Back up"), arbeit, nachher=self.anzeigen)

    def zurueckspielen(self):
        if not self._bereit():
            return
        s = self._sicherungen.get(self.sicherung_gewaehlt)
        if not s:
            self.app.status.set(_("Select a backup in the list."))
            return
        ziel_art = self.info.get("art") or kg.STANDARD_ART
        quell_art = s.get("art") or kg.STANDARD_ART
        teile = [k for k in self._gewaehlte_teile() if k in s.get("teile", {})
                 and kg.NUR_BEI.get(k, ziel_art) == ziel_art]
        if not teile:
            self.app.status.set(_("The selected backup contains none of the chosen parts."))
            return
        g = s.get("geraet") or {}
        anderes = (g.get("seriennummer") and self.info.get("seriennummer")
                   and g["seriennummer"] != self.info["seriennummer"])
        hinweis = ""
        if quell_art != ziel_art:
            hinweis = "\n\n" + _("The backup comes from a {quelle}, the connected device is a {ziel}. The KOReader "
                                 "folder is written to {ordner}. Folders stored in the settings (home folder, "
                                 "last book) still point to the {quelle}; KOReader asks for them again if "
                                 "needed.").format(quelle=kg.art_name(quell_art), ziel=kg.art_name(ziel_art),
                                                   ordner=kg.ko_ordner(ziel_art))
        elif anderes:
            hinweis = "\n\n" + _("The backup comes from a different device.")
        if not dialogs.frage(
                self.app, _("Restore"),
                _("Write from the backup of {datum} to the e-reader:").format(datum=_datum(s.get("datum"))) + "\n\n"
                + "\n".join(f"- {_(kg.TEIL_NAME[k])}" for k in teile) + hinweis
                + "\n\n" + _("Files with the same name on the e-reader are overwritten, others stay. "
                             "The current state is backed up first.")):
            return
        wurzel, info, ziel, pfad = self.wurzel, dict(self.info), self.sicherungsordner(), s["pfad"]
        anzahl = int(self.app.e["kobo_sicherungen_anzahl"])
        vorhanden = [k for k in teile if k in self.vorhanden]

        def arbeit():
            if vorhanden:
                # +1: die gerade angelegte Sicherung darf die zurückgespielte nicht verdrängen
                kg.sichern(wurzel, ziel, vorhanden, info, anzahl + 1, anlass="vor_zurueckspielen")
            n = kg.zurueckspielen(pfad, wurzel, teile)
            return ngettext("{n} file restored. KOReader reads it at the next start (after ejecting).",
                            "{n} files restored. KOReader reads them at the next start (after ejecting).", n).format(n=n)
        self.geschrieben = True
        self.app.hintergrund(_("Restore"), arbeit, nachher=lambda: self._gewaehlt(self.wurzel))

    def quelle_waehlen(self):
        o = dialogs.ordner(self.app, _("Choose the dictionary folder"), self._woerterbuch_quelle() or str(Path.home()))
        if not o:
            return
        self.app.e["woerterbuch_quelle"] = o
        self._woerterbuecher_fuellen()
        if not self._woerterbuch_ordner(o):
            self.app.status.set(_("There is no dictionary in this folder (no .ifo file, not even up to {n} levels "
                                  "deeper).").format(n=kg.SUCHTIEFE))
        else:
            self.app.status.set(ngettext("{n} dictionary found.", "{n} dictionaries found.", len(self._dicts))
                                .format(n=len(self._dicts)))

    def woerterbuch_oeffnen(self, name):
        """Wörterbuch (Doppelklick) im Bereich Wörterbuch öffnen: das eingetragene, das in diesen Ordner
        erzeugt (built_out), sonst den Ordner aus der Quelle selbst; gibt es das Wörterbuch nur auf dem
        Gerät, nach Rückfrage die Kopie dort."""
        eintrag = next(((n, st, q) for n, st, q in self._dicts if n == name), None)
        wb = getattr(self.app, "woerterbuch", None)
        if not eintrag or wb is None:
            return
        n, stand, quelle = eintrag
        if quelle is None:
            if not (self.wurzel and self.wurzel.exists()):
                return
            pfad = kg.dict_ordner(self.wurzel) / n
            if not dialogs.frage(self.app, self.name(), _("The dictionary {name} is only on the e-reader. Open the "
                                                          "copy there? Changes are then saved on the e-reader.")
                                 .format(name=n)):
                return
        else:
            pfad = wb.eingetragen_fuer(quelle) or quelle
        if wb.wb and Path(wb.wb.pfad) == Path(pfad):
            self.app.bereich_zeigen("woerterbuch")
            return
        if not wb._offen_ok():
            return
        wb.oeffnen(str(pfad))
        self.app.bereich_zeigen("woerterbuch")

    def woerterbuch_kopieren(self):
        if not self._bereit():
            return
        quellen = {q.name: q for q in self._woerterbuch_ordner(self._woerterbuch_quelle(), neu=True)}
        if not quellen:
            self.app.status.set(_("Choose the source first (folder with the dictionary)."))
            return
        sel = [n for n in self.dicts_gewaehlt if n in quellen]
        if not sel:
            sel = [n for n, st, __ in self._dicts if n in quellen and st != "aktuell"]
        if not sel:
            self.app.status.set(_("All dictionaries on the e-reader are up to date."))
            return
        wurzel = self.wurzel
        ziele = [quellen[n] for n in sorted(sel)]

        def arbeit():
            n = sum(kg.woerterbuch_kopieren(q, wurzel) for q in ziele)
            return (ngettext("Dictionary copied: {namen} ({n} file).", "Dictionary copied: {namen} ({n} files).", n)
                    .format(namen=", ".join(q.name for q in ziele), n=n) + " " +
                    _("In KOReader it appears under the dictionary settings after a restart."))
        self.geschrieben = True
        self.app.hintergrund(_("Copying dictionary"), arbeit, nachher=self._woerterbuecher_fuellen)

    def auswerfen(self, nochmal=False):
        """Gerät abmelden. Liegt die Bibliothek darauf: vorher speichern oder verwerfen (Abbrechen bricht
        ab), nach dem Auswerfen wird sie geschlossen. Scheitert es, nennt ein Fenster die Programme, die
        etwas auf dem Gerät offen haben, mit "Wiederholen"."""
        if not self._bereit():
            return
        a = self.app
        auf_geraet = self._auf_geraet()
        if auf_geraet and not nochmal:
            a.kapitel._bearbeitung_beenden()
            gelb = sum(1 for b in a.buecher if b.stand() == "gelb")
            rot = sum(1 for b in a.buecher if b.stand() == "rot")
            if gelb or rot:
                text = ngettext("{n} book on the e-reader has unsaved changes.",
                                "{n} books on the e-reader have unsaved changes.", gelb + rot).format(n=gelb + rot)
                text += "\n\n" + _("Yes: save applied changes, then eject.\nNo: discard the changes and eject.\n"
                                   "Cancel: do not eject.")
                if rot:
                    text += "\n\n" + ngettext("{n} book has changes that are not applied yet; they are lost either way.",
                                              "{n} books have changes that are not applied yet; they are lost either "
                                              "way.", rot).format(n=rot)
                antwort = dialogs.frage3(a, _("Eject"), text)
                if antwort is None:
                    return
                if antwort and gelb:
                    a.speichern()
                    if any(b.stand() == "gelb" for b in a.buecher):
                        a.status.set(_("Not ejected: saving failed for some books."))
                        return
        wurzel = self.wurzel
        self._auswurf = {"ok": False, "meldung": "", "blockierer": []}

        def arbeit():
            ok, meldung = kg.auswerfen(wurzel)
            self._auswurf.update(ok=ok, meldung=meldung)
            if not ok:
                if sys.platform != "win32":
                    self._auswurf["blockierer"] = kg.blockierer(wurzel)
                return _("Ejecting failed: {meldung}").format(meldung=meldung)
            self.geschrieben = False
            return _("E-reader ejected, the cable can come off.")

        def nachher():
            if self._auswurf["ok"]:
                if auf_geraet:
                    a.bibliothek_schliessen(still=True)
                    a.status.set(_("E-reader ejected, the cable can come off.") + " " +
                                 _("The library from the e-reader was closed."))
                self.suchen(still=True)
            else:
                self._auswurf_fehlgeschlagen()
        a.hintergrund(_("Eject"), arbeit, nachher=nachher)

    def _blockierer_text(self, blockierer):
        zeilen = "\n".join(f"- {name} (PID {pid})" for pid, name, __ in blockierer)
        return "\n\n" + _("These programs have files or folders on the e-reader open:") + "\n" + zeilen

    def _auswurf_fehlgeschlagen(self):
        f = self._auswurf
        text = _("Ejecting failed: {meldung}").format(meldung=f["meldung"])
        if f["blockierer"]:
            text += self._blockierer_text(f["blockierer"])
            text += "\n\n" + _("Close them, or in a file manager change to another folder (also close its tabs "
                               "and terminal panel), then try again.")
        elif sys.platform != "win32":
            text += "\n\n" + _("No program with open files on the e-reader was found (programs of other users "
                               "cannot be seen). Close file managers showing the e-reader and try again.")
        else:
            text += "\n\n" + _("Close Explorer windows and programs using the drive, then try again.")
        if dialogs.nochmal(self.app, _("Eject"), text):
            self.auswerfen(nochmal=True)

    def vermerken(self, pfad):
        """Die Oberfläche hat etwas unter pfad gespeichert - liegt das auf dem Gerät?"""
        try:
            if self.wurzel and Path(pfad).resolve().is_relative_to(Path(self.wurzel).resolve()):
                self.geschrieben = True
        except (OSError, ValueError):
            pass
        self.abgleich_nach_speichern(pfad)

    def schliessen_ok(self):
        """Erinnerung ans Auswerfen beim Beenden. False: nicht beenden."""
        if not (self.app.e.get("auswerfen_erinnern", True) and self.geschrieben
                and self.wurzel and self.wurzel.exists()):
            return True
        antwort = dialogs.frage3(self.app, self.name(), _("Data was written to the e-reader. Eject before unplugging, "
                                                          "otherwise data may be missing.\n\nEject now?"))
        if antwort is None:
            return False
        if antwort:
            ok, meldung = kg.auswerfen(self.wurzel)
            if not ok:
                blockierer = kg.blockierer(self.wurzel) if sys.platform != "win32" else []
                dialogs.warnung(self.app, self.name(), _("Ejecting failed: {meldung}").format(meldung=meldung)
                                + (self._blockierer_text(blockierer) if blockierer else "")
                                + "\n\n" + _("Eject in the file manager."))
            else:
                self.geschrieben = False
        return True
