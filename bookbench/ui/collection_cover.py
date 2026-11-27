# -*- coding: utf-8 -*-
"""
collection_cover.py - Cover-Tafel rechts im Bereich Sammlungen (seit 2.4-beta6), bedient sich wie die Cover-Tafel
im Bereich Metadaten (ui/cover_panel.py): großes Bild, Klick = so groß wie der Bildschirm, Rechtsklick = Menü, Bild
aufs Feld ziehen, darunter Größe/Format und Knöpfe. Unterschiede: kein Nachschlagen (eine selbst gebaute Sammlung
gibt es nirgends online), dafür „Von einem Buch …“; gespeichert wird sofort wie alles bei den Sammlungen.

  SammlungCover(bereich)    bereich = SammlungenBereich (liefert cover_pfad(), cover_setzen(daten), cover_vom_buch())
    anzeigen(), gross(), aus_datei(), exportieren(), entfernen()
"""
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import QDialog, QGridLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

from bookbench.core import covers as kc
from bookbench.i18n import _
from bookbench.ui import dialogs, theme
from bookbench.ui.cover_panel import info_text

BILDER = (".jpg", ".jpeg", ".png")


class _Flaeche(QWidget):
    def __init__(self, tafel):
        super().__init__()
        self.tafel = tafel
        self.setMinimumSize(120, 170)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(tafel._menue)

    def sizeHint(self):
        return QSize(200, 300)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.tafel.gross()

    def dragEnterEvent(self, ev):
        urls = ev.mimeData().urls()
        if urls and urls[0].toLocalFile().lower().endswith(BILDER) and self.tafel.bereich._sammlung() is not None:
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        urls = ev.mimeData().urls()
        if urls:
            self.tafel.aus_datei(urls[0].toLocalFile())

    def paintEvent(self, ev):
        f = theme.farben()
        m = QPainter(self)
        m.setRenderHint(QPainter.SmoothPixmapTransform)
        m.fillRect(self.rect(), QColor(f["feld"]))
        m.setPen(QColor(f["rahmen"]))
        m.drawRect(self.rect().adjusted(0, 0, -1, -1))
        pm = self.tafel.pixmap
        if pm is None or pm.isNull():
            m.setPen(QColor(f["hinweis"]))
            m.drawText(self.rect().adjusted(8, 8, -8, -8), Qt.AlignCenter | Qt.TextWordWrap,
                       _("No cover. “From file …” or “From a book …” sets one, or drop a picture here."))
            return
        bild = pm.scaled(self.width() - 8, self.height() - 8, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        m.drawPixmap((self.width() - bild.width()) // 2, (self.height() - bild.height()) // 2, bild)


class _Gross(QDialog):
    def __init__(self, eltern, pm, titel):
        super().__init__(eltern)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(titel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        g = QGuiApplication.primaryScreen().availableGeometry()
        if pm.height() > g.height() - 80 or pm.width() > g.width() - 40:
            pm = pm.scaled(g.width() - 40, g.height() - 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        lab = QLabel()
        lab.setPixmap(pm)
        lab.setCursor(Qt.PointingHandCursor)
        lab.mousePressEvent = lambda ev: self.close()
        lay.addWidget(lab)


class SammlungCover(QWidget):
    def __init__(self, bereich):
        super().__init__()
        self.bereich = bereich
        self.app = bereich.app
        self.pixmap = None
        self._gross = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 0, 0, 0)
        self.flaeche = _Flaeche(self)
        lay.addWidget(self.flaeche, 1)
        self.info = QLabel("")
        self.info.setProperty("rolle", "hinweis")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        g = QGridLayout()
        g.setSpacing(4)
        self.k_datei = QPushButton(_("From file …"))
        self.k_datei.clicked.connect(lambda: self.aus_datei())
        self.k_buch = QPushButton(_("From a book …"))
        self.k_buch.setToolTip(_("The cover of a book of this collection"))
        self.k_buch.clicked.connect(lambda: self.bereich.cover_vom_buch())
        self.k_export = QPushButton(_("Export …"))
        self.k_export.clicked.connect(self.exportieren)
        self.k_weg = QPushButton(_("Remove cover"))
        self.k_weg.clicked.connect(self.entfernen)
        for i, k in enumerate((self.k_datei, self.k_buch, self.k_export, self.k_weg)):
            g.addWidget(k, i // 2, i % 2)
        lay.addLayout(g)

    def anzeigen(self):
        s = self.bereich._sammlung()
        pfad = self.bereich.cover_pfad()
        self.pfad = pfad
        self.pixmap = QPixmap(str(pfad)) if pfad else None
        if self.pixmap is not None and self.pixmap.isNull():
            self.pixmap = None
        an = s is not None and self.bereich.ort is not None
        for k in (self.k_datei, self.k_buch):
            k.setEnabled(an)
        for k in (self.k_export, self.k_weg):
            k.setEnabled(an and self.pixmap is not None)
        if pfad:
            try:
                daten = Path(pfad).read_bytes()
                bi_ = kc.bild_info(daten)
                self.info.setText(info_text(tuple(bi_) + (len(daten),)) if bi_ else _("no cover"))
            except OSError:
                self.info.setText("")
        else:
            self.info.setText(_("no cover") if s is not None else "")
        self.flaeche.update()

    def _menue(self, pos):
        m = QMenu(self)
        an = self.bereich._sammlung() is not None and self.bereich.ort is not None
        m.addAction(_("Show large"), self.gross).setEnabled(self.pixmap is not None)
        m.addAction(_("From file …"), lambda: self.aus_datei()).setEnabled(an)
        m.addAction(_("From a book …"), self.bereich.cover_vom_buch).setEnabled(an)
        m.addAction(_("Export …"), self.exportieren).setEnabled(self.pixmap is not None)
        m.addSeparator()
        m.addAction(_("Remove cover"), self.entfernen).setEnabled(self.pixmap is not None)
        self._menue_offen = m
        m.popup(self.flaeche.mapToGlobal(pos))

    def gross(self):
        if self._gross is not None:
            self._gross.close()
            self._gross = None
            return
        if self.pixmap is None:
            return
        s = self.bereich._sammlung()
        self._gross = _Gross(self.app, self.pixmap, s["name"] if s else "")
        self._gross.destroyed.connect(lambda *a: setattr(self, "_gross", None))
        self._gross.show()

    def aus_datei(self, pfad=None):
        if self.bereich._sammlung() is None:
            return
        p = pfad or dialogs.datei_oeffnen(self.app, _("Cover of the collection"), "",
                                          [(_("Images"), "*.jpg *.jpeg *.png")])
        if not p:
            return
        try:
            daten = Path(p).read_bytes()
        except OSError as ex:
            dialogs.fehler(self.app, self.bereich.name(), _("The file could not be read."), str(ex))
            return
        if not kc.bild_info(daten):
            self.app.status.set(_("Not a readable image (JPEG or PNG)."))
            return
        self.bereich.cover_setzen(daten)

    def exportieren(self):
        if not self.pfad:
            return
        s = self.bereich._sammlung()
        ziel = dialogs.datei_speichern(self.app, _("Export cover"), f"{s['name'] if s else 'cover'}{Path(self.pfad).suffix}",
                                       [(_("Images"), "*" + Path(self.pfad).suffix)])
        if ziel:
            try:
                Path(ziel).write_bytes(Path(self.pfad).read_bytes())
                self.app.status.set(_("Cover saved as {datei}.").format(datei=ziel))
            except OSError as ex:
                dialogs.fehler(self.app, self.bereich.name(), _("The cover could not be saved."), str(ex))

    def entfernen(self):
        if self.pixmap is not None:
            self.bereich.cover_setzen(None)
