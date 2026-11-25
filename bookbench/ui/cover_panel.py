# -*- coding: utf-8 -*-
"""
cover_panel.py - Cover-Tafel rechts im Bereich Metadaten (Qt; Tk-Vorlage tk/area_covers.py).

  CoverTafel(app, bereich)   Fläche mit dem Cover (Klick = groß, Rechtsklick = Menü; Datei und Neu
                             nebeneinander bzw. untereinander bei schmaler Tafel), darunter Angaben und
                             Knöpfe Aus Datei, Nachschlagen, Exportieren, Neues verwerfen
    anzeigen(), einsetzen(b, daten, quelle), aus_datei(), nachschlagen(), alle_ohne(), exportieren(),
    verwerfen(), gross()
  AuswahlDialog(eltern, b, kandidaten, aktuell)   gefundene Cover nebeneinander; .ergebnis
  info_text(info, pfad)

Ein neues Cover ist wie ein übernommener Text: gelb, bis gespeichert wird (Strg+S, mit Sicherung). Es
wird beim Einsetzen ins Format des vorhandenen Covers gebracht (core/covers, dafür braucht es Pillow);
angezeigt wird alles über Qt (JPEG auch ohne Pillow).
"""
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from bookbench.core import covers as kc
from bookbench.core import markers as km
from bookbench.i18n import _, ngettext
from bookbench.ui import cover_view
from bookbench.ui import dialogs
from bookbench.ui import theme

FORMATNAME = {"jpeg": "JPEG", "png": "PNG", "gif": "GIF", "webp": "WebP", "?": "?"}


def groesse_text(n):
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def info_text(info, pfad=""):
    if not info:
        return _("no cover")
    w, h, fmt, n = info
    return "  ·  ".join([f"{w} × {h} px", FORMATNAME.get(fmt, fmt), groesse_text(n)] + ([pfad] if pfad else []))


def pixmap(daten):
    pm = QPixmap()
    return pm if daten and pm.loadFromData(daten) else None


class _Flaeche(QWidget):
    """Zeichnet das Cover der Datei und ggf. das neue, eingepasst in die Fläche."""

    def __init__(self, tafel):
        super().__init__()
        self.tafel = tafel
        self.setMinimumSize(140, 200)
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(tafel._menue)

    def sizeHint(self):
        return QSize(220, 320)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.tafel.gross()

    def paintEvent(self, ev):
        f = theme.farben()
        m = QPainter(self)
        m.setRenderHint(QPainter.SmoothPixmapTransform)
        m.fillRect(self.rect(), QColor(f["feld"]))
        m.setPen(QColor(f["rahmen"]))
        m.drawRect(self.rect().adjusted(0, 0, -1, -1))
        bilder = self.tafel.bilder()
        w, h = self.width(), self.height()
        if not bilder:
            if self.tafel.bereich.buch is not None:
                m.setPen(QColor(f["hinweis"]))
                m.drawText(self.rect().adjusted(12, 12, -12, -12), Qt.AlignCenter | Qt.TextWordWrap,
                           _("No cover. \"From file\" or \"Look up\" adds one."))
            return
        n = len(bilder)
        rand, unterschrift = 12, 22 if n > 1 else 0
        senkrecht = n > 1 and h > w * 1.6                 # schmale Tafel: Datei und Neu untereinander
        breite = w - 2 * rand if senkrecht else (w - rand * (n + 1)) // n
        hoehe = (h - rand * (n + 1)) // n - unterschrift if senkrecht else h - 2 * rand - unterschrift
        for i, (titel, pm) in enumerate(bilder):
            x = rand if senkrecht else rand + i * (breite + rand)
            y = rand + i * (hoehe + unterschrift + rand) if senkrecht else rand
            if n > 1:
                m.setPen(QColor(f["fg"]))
                fett = m.font()
                fett.setBold(True)
                m.setFont(fett)
                m.drawText(QRect(x, y, breite, unterschrift), Qt.AlignHCenter | Qt.AlignTop, titel)
            if pm is None:
                m.setPen(QColor(f["hinweis"]))
                m.drawText(QRect(x, y + unterschrift, breite, hoehe), Qt.AlignCenter | Qt.TextWordWrap, "?")
                continue
            skaliert = pm.size().scaled(QSize(breite, hoehe), Qt.KeepAspectRatio)
            faktor = min(skaliert.width() / max(1, pm.width()), 2.0)            # höchstens doppelt vergrößern
            ziel = QSize(round(pm.width() * faktor), round(pm.height() * faktor))
            m.drawPixmap(QRect(x + (breite - ziel.width()) // 2, y + unterschrift, ziel.width(), ziel.height()), pm)
        m.end()


class CoverTafel(QWidget):
    def __init__(self, app, bereich):
        super().__init__()
        self.app, self.bereich = app, bereich
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 0, 0, 0)
        self.flaeche = _Flaeche(self)
        lay.addWidget(self.flaeche, 1)
        self.zeile_datei = QLabel("")
        self.zeile_neu = QLabel("")
        self.hinweis = QLabel("")
        for lab, rolle in ((self.zeile_datei, "hinweis"), (self.zeile_neu, None), (self.hinweis, "hinweis")):
            lab.setWordWrap(True)
            if rolle:
                lab.setProperty("rolle", rolle)
            lay.addWidget(lab)
        g = QGridLayout()
        g.setContentsMargins(0, 6, 0, 0)
        g.setSpacing(4)
        self.knoepfe = {}
        for i, (k, text, fn) in enumerate((("datei", _("From file …"), self.aus_datei),
                                           ("nachschlagen", _("Look up"), self.nachschlagen),
                                           ("export", _("Export …"), self.exportieren),
                                           ("verwerfen", _("Discard new"), self.verwerfen))):
            knopf = QPushButton(text)
            knopf.clicked.connect(fn)
            g.addWidget(knopf, i // 2, i % 2)
            self.knoepfe[k] = knopf
        lay.addLayout(g)
        self._cache = {}

    @property
    def buch(self):
        return self.bereich.buch

    # ================================================================ Anzeige
    def datei_bytes(self, b):
        try:
            schl = (str(b.pfad), b.pfad.stat().st_mtime)
        except OSError:
            return None
        if schl not in self._cache:
            from bookbench.core import library as kd
            self._cache = {schl: kd.cover_lesen(b.pfad)}
        return self._cache[schl]

    def aktuelle_bytes(self, b):
        return b.cover_neu if b.cover_neu is not None else self.datei_bytes(b)

    def bilder(self):
        b = self.buch
        if b is None:
            return []
        erg = []
        if b.cover_info:
            erg.append((_("In the file"), pixmap(self.datei_bytes(b))))
        if b.cover_neu is not None:
            erg.append((_("New"), pixmap(b.cover_neu)))
        return erg

    def anzeigen(self):
        b = self.buch
        cover_view.gross_schliessen(ausser=b)
        if not b:
            for lab in (self.zeile_datei, self.zeile_neu, self.hinweis):
                lab.setText("")
        else:
            self.zeile_datei.setText(_("In the file: {info}").format(info=info_text(b.cover_info, b.cover_datei)))
            if b.cover_neu is not None:
                i = kc.bild_info(b.cover_neu)
                self.zeile_neu.setText(_("New: {info} - from {quelle}; applied, not yet saved (Ctrl+S).").format(
                    info=info_text((i[0], i[1], i[2], len(b.cover_neu)) if i else None), quelle=b.cover_neu_quelle))
            else:
                self.zeile_neu.setText("")
            self.hinweis.setText(_("⚠ Smaller than {n} px in height (limit in Settings > Covers).").format(
                n=self.app.e.get("cover_klein")) if km.cover_klein(b, self.app.e) else "")
        self.knoepfe["verwerfen"].setEnabled(bool(b and b.cover_neu is not None))
        for k in ("datei", "nachschlagen", "export"):
            self.knoepfe[k].setEnabled(bool(b and not b.fehler))
        self.flaeche.update()

    def _menue(self, pos):
        b = self.buch
        m = QMenu(self)
        m.addAction(_("Show large"), self.gross)
        m.addAction(_("From file …"), self.aus_datei)
        m.addAction(_("Look up"), self.nachschlagen)
        m.addAction(_("Export …"), self.exportieren)
        m.addSeparator()
        m.addAction(_("Discard new cover"), self.verwerfen).setEnabled(bool(b and b.cover_neu is not None))
        self._menue_offen = m
        m.popup(self.flaeche.mapToGlobal(pos))

    # ================================================================ Aktionen
    def _buch_noetig(self):
        if self.app._bereich() != "metadaten" or not self.buch:
            self.app.status.set(_("Choose a book in the Metadata area first."))
            return None
        return self.buch

    def einsetzen(self, b, daten, quelle):
        """Neues Bild vorbereiten (Format des vorhandenen Covers, ggf. verkleinert) und übernehmen.
        True, wenn es geklappt hat; Fehler stehen in der Statuszeile."""
        info = kc.bild_info(daten)
        if not info:
            self.app.status.set(f"{b.name}: " + _("not a readable image (JPEG, PNG, GIF or WebP)."))
            return False
        ziel = b.cover_info[2] if b.cover_info and b.cover_info[2] != "?" else (
            info[2] if info[2] in ("jpeg", "png") else "jpeg")
        try:
            neu = kc.vorbereiten(daten, ziel, int(self.app.e.get("cover_max_hoehe") or 0),
                                 int(self.app.e.get("cover_qualitaet") or 90))
        except RuntimeError:
            self.app.status.set(f"{b.name}: " + _("the image would have to be converted to {fmt}; that needs Pillow "
                                                  "(pip install pillow).").format(fmt=FORMATNAME[ziel]))
            return False
        except Exception as e:
            self.app.status.set(f"{b.name}: " + _("image could not be read ({fehler}).").format(fehler=e))
            return False
        b.cover_neu, b.cover_neu_quelle = neu, quelle
        self.app.buch_geaendert(b)
        if b is self.buch:
            self.anzeigen()
            self.bereich.aktualisieren()
        return True

    def aus_datei(self, pfad=None):
        b = self._buch_noetig()
        if not b:
            return
        p = pfad or dialogs.datei_oeffnen(self, _("Choose the new cover"), "",
                                          [(_("Images"), "*.jpg *.jpeg *.png *.gif *.webp")])
        if not p:
            return
        try:
            daten = Path(p).read_bytes()
        except OSError as e:
            self.app.status.set(str(e))
            return
        if self.einsetzen(b, daten, Path(p).name):
            self.app.status.set(f"{b.name}: " + _("new cover applied, not yet saved (Ctrl+S)."))

    def _quellen(self):
        kc.MIN_HOEHE = int(self.app.e.get("cover_min_hoehe") or 300)
        return [q for q in ("openlibrary", "google") if self.app.e.get(f"cover_{q}", True)]

    def nachschlagen(self):
        b = self._buch_noetig()
        if not b:
            return
        if not self._quellen():
            self.app.status.set(_("All cover sources are switched off (Settings > Covers)."))
            return
        if self.app._arbeit:
            self.app.status.set(_("Still running: {arbeit}.").format(arbeit=self.app._arbeit))
            return
        ergebnis = {}
        quellen, anzahl = self._quellen(), int(self.app.e.get("cover_anzahl") or 8)

        def arbeit():
            ergebnis["k"] = kc.nachschlagen(b.titel, b.autor, b.isbn, quellen, anzahl)
            return ngettext("{n} cover found.", "{n} covers found.", len(ergebnis["k"])).format(n=len(ergebnis["k"]))

        def nachher():
            k = ergebnis.get("k")
            if not k:
                self.app.status.set(f"{b.name}: " + _("no cover found."))
                return
            d = AuswahlDialog(self.app, b, k, self.datei_bytes(b) if b.cover_info else None)
            self.auswahl_offen = d                        # für Tests
            wahl = d.ausfuehren()
            if wahl and self.einsetzen(b, wahl["daten"], wahl["url"]):
                self.app.status.set(f"{b.name}: " + _("cover from {quelle} applied, not yet saved (Ctrl+S).")
                                    .format(quelle=wahl["quelle"]))
        self.app.status.set(f"{b.name}: " + _("looking for covers …"))
        self.app.hintergrund(_("Looking up covers"), arbeit, nachher=nachher)

    def alle_ohne(self, fragen=True):
        offen = [b for b in self.app.buecher if km.cover_fehlt(b)]
        if not offen:
            self.app.status.set(_("All books have a cover."))
            return
        if not self._quellen():
            self.app.status.set(_("All cover sources are switched off (Settings > Covers)."))
            return
        if self.app._arbeit:
            self.app.status.set(_("Still running: {arbeit}.").format(arbeit=self.app._arbeit))
            return
        if fragen and not dialogs.frage(self.app, _("All without cover"), ngettext(
                "{n} book has no cover. For it the largest cover found is taken; check it afterwards and "
                "save with Ctrl+S.\n\nStart?",
                "{n} books have no cover. For each the largest cover found is taken; check them afterwards and "
                "save with Ctrl+S.\n\nStart?", len(offen)).format(n=len(offen))):
            return
        gefunden, quellen = {}, self._quellen()
        from bookbench.ui import threads

        def arbeit():
            for i, b in enumerate(offen, 1):
                text = _("Looking up covers ({i}/{n}): {name} …").format(i=i, n=len(offen), name=b.name)
                threads.im_hauptthread(lambda t=text: self.app.status.set(t))
                try:
                    k = kc.nachschlagen(b.titel, b.autor, b.isbn, quellen, hoechstens=3)
                except Exception:
                    k = []
                if k:
                    gefunden[b.schluessel] = k[0]
            return ngettext("Covers: {n} of {gesamt} book found.", "Covers: {n} of {gesamt} books found.",
                            len(offen)).format(n=len(gefunden), gesamt=len(offen))

        def nachher():
            for schl, k in gefunden.items():
                b = self.app.nach_schluessel.get(schl)
                if b:
                    self.einsetzen(b, k["daten"], k["url"])
        self.app.hintergrund(_("Looking up covers"), arbeit, nachher=nachher)

    def verwerfen(self):
        b = self._buch_noetig()
        if not b or b.cover_neu is None:
            return
        b.cover_neu, b.cover_neu_quelle = None, ""
        self.app.buch_geaendert(b)
        self.anzeigen()
        self.bereich.aktualisieren()
        self.app.status.set(f"{b.name}: " + _("new cover discarded."))

    def exportieren(self, pfad=None):
        b = self._buch_noetig()
        if not b:
            return
        daten = self.aktuelle_bytes(b)
        info = kc.bild_info(daten) if daten else None
        if not info:
            self.app.status.set(f"{b.name}: " + _("no cover to export."))
            return
        endung = kc.ENDUNG[info[2]]
        name = "".join(z for z in b.titel if z not in '\\/:*?"<>|').strip() or "cover"
        p = pfad or dialogs.datei_speichern(self, _("Export cover"), str(Path.home() / f"{name}.{endung}"),
                                            [(FORMATNAME[info[2]], f"*.{endung}")])
        if not p:
            return
        try:
            Path(p).write_bytes(daten)
        except OSError as e:
            self.app.status.set(str(e))
            return
        self.app.status.set(_("Cover saved: {datei}").format(datei=p))

    def gross(self):
        b = self.buch
        if b is None:
            return
        if not self.aktuelle_bytes(b):
            self.app.status.set(f"{b.name}: " + _("no cover."))
            return
        cover_view.gross(self.app, b)


class _Kachel(QFrame):
    def __init__(self, dialog, k, titel, waehlbar):
        super().__init__()
        self.dialog, self.k, self.waehlbar = dialog, k, waehlbar
        self.setFrameShape(QFrame.Box)
        self.setLineWidth(3)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        bild = QLabel()
        pm = pixmap(k["daten"])
        if pm is not None:
            bild.setPixmap(pm.scaled(220, AuswahlDialog.HOEHE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                           if pm.height() > AuswahlDialog.HOEHE or pm.width() > 220 else pm)
        else:
            bild.setText("?")
        bild.setAlignment(Qt.AlignCenter)
        lay.addWidget(bild)
        info = kc.bild_info(k["daten"])
        unter = QLabel(titel + (f"\n{info[0]} × {info[1]} px, {groesse_text(len(k['daten']))}" if info else ""))
        unter.setAlignment(Qt.AlignCenter)
        if not waehlbar:
            unter.setProperty("rolle", "hinweis")
        lay.addWidget(unter)
        if waehlbar:
            self.setCursor(Qt.PointingHandCursor)
        self.markieren(False)

    def markieren(self, an):
        f = theme.farben()
        self.setStyleSheet(f"_Kachel, QFrame {{ border: 3px solid {f['akzent'] if an else f['feld']}; }}"
                           "QLabel { border: none; }")

    def mousePressEvent(self, ev):
        if self.waehlbar:
            self.dialog.waehlen(self.k)

    def mouseDoubleClickEvent(self, ev):
        if self.waehlbar:
            self.dialog.waehlen(self.k)
            self.dialog.ok()


class AuswahlDialog(QDialog):
    """Gefundene Cover nebeneinander; Klick wählt, Doppelklick oder OK übernimmt."""
    HOEHE = 260

    def __init__(self, eltern, b, kandidaten, aktuell=None):
        super().__init__(eltern)
        self.ergebnis, self.gewaehlt = None, None
        self.setWindowTitle(_("Choose a cover: {name}").format(name=b.name))
        lay = QVBoxLayout(self)
        flaeche = QScrollArea()
        flaeche.setWidgetResizable(True)
        flaeche.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        innen = QWidget()
        reihe = QHBoxLayout(innen)
        reihe.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.kacheln = []
        if aktuell:
            reihe.addWidget(_Kachel(self, {"daten": aktuell, "quelle": ""}, _("In the file"), False))
        for k in kandidaten:
            kachel = _Kachel(self, k, k["quelle"], True)
            reihe.addWidget(kachel)
            self.kacheln.append(kachel)
        flaeche.setWidget(innen)
        lay.addWidget(flaeche, 1)
        hinweis = QLabel(_("Click a cover to choose it, double-click takes it at once."))
        hinweis.setProperty("rolle", "hinweis")
        lay.addWidget(hinweis)
        unten = QHBoxLayout()
        unten.addStretch(1)
        self.ok_knopf = QPushButton("OK")
        self.ok_knopf.setEnabled(False)
        self.ok_knopf.setDefault(True)
        self.ok_knopf.clicked.connect(self.ok)
        unten.addWidget(self.ok_knopf)
        ab = QPushButton(_("Cancel"))
        ab.clicked.connect(self.reject)
        unten.addWidget(ab)
        lay.addLayout(unten)
        breite = min(max(560, 250 * (len(kandidaten) + (1 if aktuell else 0)) + 40), 1400)
        self.resize(breite, self.HOEHE + 170)

    def waehlen(self, k):
        self.gewaehlt = k
        for kachel in self.kacheln:
            kachel.markieren(kachel.k is k)
        self.ok_knopf.setEnabled(True)

    def ok(self):
        if self.gewaehlt is not None:
            self.ergebnis = self.gewaehlt
            self.accept()

    def ausfuehren(self):
        self.exec()
        return self.ergebnis
