# -*- coding: utf-8 -*-
"""
blurb_panel.py - Klappentext-Tafel im Bereich Metadaten (Qt; Tk-Vorlage tk/area_blurbs.py).

  KlappentextTafel(app, bereich)   Kopf "Klappentext" mit kleinen Knöpfen Nachschlagen / Aus Calibre,
                                   Textfeld, darunter die Quelle (und das letzte Nachschlage-Ergebnis)
    anzeigen(), uebernehmen(b), verwerfen(b), aus_calibre(), text()

Getippt = buch.klappentext_entwurf (rot), übernommen = klappentext_neu (gelb). Das Nachschlagen selbst
steht in core/blurb_lookup.py, gestartet wird es von der App (klappentext_nachschlagen).
"""
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from bookbench.core import blurbs
from bookbench.core import library as kd
from bookbench.core import markers as km
from bookbench.i18n import _


def quelle_text(b):
    q = b.klappentext_quelle
    name = blurbs.source_name(q)
    return q if name == q else f"{name} ({q})"


class KlappentextTafel(QWidget):
    def __init__(self, app, bereich):
        super().__init__()
        self.app, self.bereich = app, bereich
        self._laden = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        kopf = QHBoxLayout()
        titel = QLabel(_("Blurb"))
        titel.setProperty("rolle", "ueberschrift")
        kopf.addWidget(titel)
        kopf.addStretch(1)
        self.knoepfe = []
        knoepfe = [(_("Look up"), lambda: self.app.klappentext_nachschlagen())]
        if self.app.e.get("calibre_an", True):
            knoepfe.append((_("From Calibre"), self.aus_calibre))
        for text, fn in knoepfe:
            k = QPushButton(text)
            k.clicked.connect(fn)
            kopf.addWidget(k)
            self.knoepfe.append(k)
        lay.addLayout(kopf)
        self.feld = QPlainTextEdit()
        self.feld.setTabChangesFocus(True)
        f = self.feld.font()
        f.setPointSizeF(f.pointSizeF() + 1)
        self.feld.setFont(f)
        self.feld.textChanged.connect(self._getippt)
        lay.addWidget(self.feld, 1)
        self.quelle = QLabel("")
        self.quelle.setProperty("rolle", "hinweis")
        self.quelle.setWordWrap(True)
        lay.addWidget(self.quelle)

    def text(self):
        return self.feld.toPlainText().strip()

    def anzeigen(self):
        b = self.bereich.buch
        self._laden = True
        self.feld.setPlainText(km.klappentext_aktuell(b) if b else "")
        self.feld.setReadOnly(not b or bool(b.fehler))
        if b:
            text = _("Source: {quelle}").format(quelle=quelle_text(b)) if b.klappentext_quelle \
                else ("" if b.klappentext else _("No blurb in the file."))
            if getattr(b, "kt_nachschlag", "") and not km.klappentext_aktuell(b).strip():
                text += ("\n" if text else "") + _("Last look-up: {ergebnis}").format(ergebnis=b.kt_nachschlag)
            self.quelle.setText(text)
        else:
            self.quelle.setText("")
        self._laden = False

    def _getippt(self):
        b = self.bereich.buch
        if self._laden or not b:
            return
        text = self.text()
        vorher = b.klappentext_neu if b.klappentext_neu is not None else b.klappentext
        neu = None if text == vorher.strip() else text
        if neu != b.klappentext_entwurf:
            b.klappentext_entwurf = neu
            self.app.buch_geaendert(b)
            self.bereich.aktualisieren()

    def uebernehmen(self, b):
        """Klappentext übernehmen (Text aus dem Feld, wenn es das angezeigte Buch ist)."""
        text = self.text() if b is self.bereich.buch else km.klappentext_aktuell(b).strip()
        b.klappentext_entwurf = None
        b.klappentext_neu = None if text == b.klappentext.strip() else text
        return b.klappentext_neu is not None

    @staticmethod
    def verwerfen(b):
        b.klappentext_entwurf = b.klappentext_neu = None
        b.klappentext_quelle = b.klappentext_quelle_datei

    def aus_calibre(self):
        if self.app._calibre_aus():
            return
        b = self.bereich.buch
        if not b:
            self.app.status.set(_("Choose a book in the Metadata area first."))
            return
        text = kd.html_zu_text((b.calibre or {}).get("comments") or "")
        if not text:
            self.app.status.set(f"{b.name}: " + _("Calibre has no description."))
            return
        b.klappentext_entwurf = text
        b.klappentext_quelle = "Calibre"
        self.anzeigen()
        self.app.buch_geaendert(b)
        self.bereich.aktualisieren()
        self.app.status.set(f"{b.name}: " + _("description from Calibre, not yet applied."))
