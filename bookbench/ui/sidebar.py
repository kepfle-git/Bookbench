# -*- coding: utf-8 -*-
"""
sidebar.py - Seitenleiste links (Designleitfaden 5a des Keller-Tools, nachgebaut in Qt).

Ein einziges Widget, das alles selbst zeichnet (wie keller_navigation, nur ohne ein Widget je Zeile):
oben ☰ zum Ein-/Ausklappen, darunter je Bereich Symbol, Name und rechts die Marken (Piktogramm und
Anzahl, ui/markers). Passen die Marken nicht in die Zeile, kommen sie in eine zweite Zeile unter den
Namen; die Leiste wird so breit wie nötig, höchstens MAX_BREIT. Eingeklappt bleiben nur die Symbole,
ein Punkt zeigt die schwerste Marke. Bereiche mit Unterseiten (Vorschau) zeigen diese darunter, wenn
der Bereich gewählt oder aufgeklappt ist (Pfeil ▸/▾).

  setzen(bereiche)    [{"id", "name", "symbol", "marken": [(kennung, anzahl)], "zaehler": "",
                        "kinder": [{"id", "name", "zaehler"}]}] - nach jeder Änderung neu übergeben
  waehlen(id, kind)   zeigt die Auswahl (ohne Signal)
  gewaehlt            Signal(id, kind) bei Klick oder Strg+1 … 9
  umschalten()        ein-/ausklappen; zustand_geaendert(schlüssel, wert) zum Merken in den Einstellungen
"""
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QToolTip, QWidget

from bookbench.core.markers import sortiert, text as marken_text
from bookbench.i18n import _
from bookbench.ui import markers as mk
from bookbench.ui import theme

GRUND = 196          # px ausgeklappt ohne Marken
SCHMAL = 44          # px eingeklappt
MAX_BREIT = 250      # breiter wird die Leiste nicht, dann zweizeilig
ZEILE_H = 32         # Bereich
UNTER_H = 26         # Unterseite
ZWEITE_H = 18        # zusätzliche Höhe der zweiten Zeile (Marken)
BALKEN = 3           # Markierung links am gewählten Eintrag


class Seitenleiste(QWidget):
    gewaehlt = Signal(str, str)
    zustand_geaendert = Signal(str, object)

    def __init__(self, ausgeklappt=True, offen=()):
        super().__init__()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.ausgeklappt = ausgeklappt
        self.offen = set(offen)            # aufgeklappte Bereiche (Kennungen)
        self.bereiche = []
        self.aktuell, self.kind = None, None
        self._zeilen = []                  # [(QRect, art, daten)] nach dem Layout
        self._hover = None
        self.breite = GRUND
        self._schriften()

    def _schriften(self):
        self.schrift = QFont(self.font())
        self.fett = QFont(self.schrift)
        self.fett.setBold(True)
        self.klein = QFont(self.schrift)
        self.klein.setPointSizeF(max(6.0, self.schrift.pointSizeF() - 1))
        self.knopf = QFont(self.schrift)
        self.knopf.setPointSizeF(self.schrift.pointSizeF() + 2)

    # -- Daten ----------------------------------------------------------------------------
    def setzen(self, bereiche):
        self.bereiche = [dict(b, marken=sortiert([(k, n) for k, n in b.get("marken") or [] if n]))
                         for b in bereiche]
        self._layout()

    def waehlen(self, kennung, kind=None):
        self.aktuell, self.kind = kennung, kind
        b = self._bereich(kennung)
        if b and b.get("kinder"):
            self.offen.add(kennung)
        self._layout()

    def _bereich(self, kennung):
        return next((b for b in self.bereiche if b["id"] == kennung), None)

    def umschalten(self):
        self.ausgeklappt = not self.ausgeklappt
        self.zustand_geaendert.emit("ausgeklappt", self.ausgeklappt)
        QToolTip.hideText()
        self._layout()

    def auf_zu(self, kennung):
        self.offen.symmetric_difference_update({kennung})
        self.zustand_geaendert.emit("offen", sorted(self.offen))
        self._layout()

    def nummer(self, i):
        """Strg+1 … 9: i-ter Bereich."""
        if 0 <= i < len(self.bereiche):
            self._klick_bereich(self.bereiche[i]["id"])

    def _klick_bereich(self, kennung, kind=None):
        b = self._bereich(kennung)
        if b and b.get("kinder"):
            self.offen.add(kennung)
            self.zustand_geaendert.emit("offen", sorted(self.offen))
        self.gewaehlt.emit(kennung, kind or "")

    # -- Maße -----------------------------------------------------------------------------
    def _markenbreite(self, marken):
        fm = QFontMetrics(self.klein)
        return sum(14 + 2 + (fm.horizontalAdvance(str(n)) if k != "verbunden" else 0) + 7 for k, n in marken)

    def _offen(self, b):
        return bool(b.get("kinder")) and self.ausgeklappt and (b["id"] in self.offen or b["id"] == self.aktuell)

    def _layout(self):
        fm_fett = QFontMetrics(self.fett)
        noetig, zwei = GRUND, set()
        for b in self.bereiche:
            if not b["marken"]:
                continue
            name = SCHMAL + fm_fett.horizontalAdvance(b["name"]) + 18 + (16 if b.get("kinder") else 0)
            mb = self._markenbreite(b["marken"])
            if name + mb <= MAX_BREIT:
                noetig = max(noetig, name + mb)
            else:
                zwei.add(b["id"])
                noetig = max(noetig, min(max(name, SCHMAL - 2 + mb + 10), MAX_BREIT))
        self.breite = noetig if self.ausgeklappt else SCHMAL
        self._zweizeilig = zwei if self.ausgeklappt else set()
        self._zeilen = [(QRect(0, 0, self.breite, ZEILE_H), "knopf", None)]
        y = ZEILE_H
        for b in self.bereiche:
            h = ZEILE_H + (ZWEITE_H if b["id"] in self._zweizeilig else 0)
            self._zeilen.append((QRect(0, y, self.breite, h), "bereich", b))
            y += h
            if self._offen(b):
                for k in b["kinder"]:
                    self._zeilen.append((QRect(0, y, self.breite, UNTER_H), "kind", (b, k)))
                    y += UNTER_H
        self._hoehe = y
        self.setFixedWidth(self.breite + 1)
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        return QSize(self.breite + 1, getattr(self, "_hoehe", 200))

    def minimumSizeHint(self):
        return QSize(self.breite + 1, 100)

    # -- Zeichnen -------------------------------------------------------------------------
    def paintEvent(self, ev):
        p = theme.farben()
        m = QPainter(self)
        m.setRenderHint(QPainter.Antialiasing)
        m.fillRect(self.rect(), QColor(p["kopf"]))
        m.fillRect(QRect(self.width() - 1, 0, 1, self.height()), QColor(p["rahmen"]))
        for r, art, d in self._zeilen:
            if art == "knopf":
                self._hintergrund(m, r, False, d)
                m.setFont(self.knopf)
                m.setPen(QColor(p["fg"]))
                m.drawText(QRect(0, r.y(), SCHMAL, r.height()), Qt.AlignCenter, "☰")
            elif art == "bereich":
                self._zeile_bereich(m, r, d, p)
            else:
                self._zeile_kind(m, r, *d, p=p)
        m.end()

    def _hintergrund(self, m, r, markiert, d):
        p = theme.farben()
        if markiert:
            m.fillRect(r, QColor(p["feld"]))
            m.fillRect(QRect(r.x(), r.y(), BALKEN, r.height()), QColor(p["akzent"]))
        elif self._hover is not None and self._hover == (r.y(), id(d)):
            m.fillRect(r, QColor(p["knopf_aktiv"]))

    def _zeile_bereich(self, m, r, b, p):
        gewaehlt = b["id"] == self.aktuell
        offen = self._offen(b)
        self._hintergrund(m, r, gewaehlt and not (offen and self.kind), b)
        oben = QRect(r.x(), r.y(), r.width(), ZEILE_H)
        pm = theme.seitenleiste(b["symbol"], gewaehlt)
        if gewaehlt and not pm.isNull():
            pm = theme.eingefaerbt(pm, p["akzent"])       # im Akzent des Designs, nicht fest blau
        if not pm.isNull():
            m.drawPixmap(QPoint(SCHMAL // 2 - pm.width() // 2, oben.center().y() - pm.height() // 2 + 1), pm)
        marken = b["marken"]
        if not self.ausgeklappt:
            schwer = mk.schwerste([k for k, __ in marken])
            farbe = mk.farbe(schwer) if schwer else (theme.WARN[theme.modus()] if "⚠" in (b.get("zaehler") or "")
                                                     else None)
            if farbe:
                m.setPen(QColor(p["kopf"]))
                m.setBrush(QColor(farbe))
                m.drawEllipse(QRect(SCHMAL // 2 + 6, r.y() + 5, 7, 7))
            return
        m.setFont(self.fett if gewaehlt else self.schrift)
        m.setPen(QColor(p["akzent"] if gewaehlt else p["fg"]))
        m.drawText(QRect(SCHMAL - 2, oben.y(), r.width() - SCHMAL, ZEILE_H), Qt.AlignVCenter | Qt.AlignLeft, b["name"])
        rechts = r.width() - 10
        if b.get("kinder"):
            m.setFont(self.schrift)
            m.setPen(QColor(p["hinweis"]))
            m.drawText(QRect(rechts - 12, oben.y(), 12, ZEILE_H), Qt.AlignCenter, "▾" if offen else "▸")
            rechts -= 16
        m.setFont(self.klein)
        fm = QFontMetrics(self.klein)
        if marken and b["id"] in self._zweizeilig:
            x, y = SCHMAL - 2, r.y() + ZEILE_H - 4
            for k, n in marken:
                f = mk.farbe_von(k)
                m.drawPixmap(x, y, mk.bild(k, f))
                x += 16
                if k != "verbunden":
                    m.setPen(QColor(f))
                    m.drawText(QRect(x, y, 40, 16), Qt.AlignVCenter | Qt.AlignLeft, str(n))
                    x += fm.horizontalAdvance(str(n)) + 7
        elif marken:
            x = rechts
            for k, n in reversed(marken):
                f = mk.farbe_von(k)
                if k != "verbunden":
                    w = fm.horizontalAdvance(str(n))
                    m.setPen(QColor(f))
                    m.drawText(QRect(x - w, oben.y(), w, ZEILE_H), Qt.AlignVCenter | Qt.AlignRight, str(n))
                    x -= w + 2
                m.drawPixmap(x - 14, oben.center().y() - 7, mk.bild(k, f))
                x -= 14 + 7
        elif b.get("zaehler"):
            m.setPen(QColor(theme.WARN[theme.modus()] if "⚠" in b["zaehler"] else p["hinweis"]))
            m.drawText(QRect(0, oben.y(), rechts, ZEILE_H), Qt.AlignVCenter | Qt.AlignRight, b["zaehler"])

    def _zeile_kind(self, m, r, b, k, p):
        gewaehlt = b["id"] == self.aktuell and k["id"] == self.kind
        self._hintergrund(m, r, gewaehlt, k)
        m.setFont(self.schrift)
        m.setPen(QColor(p["akzent"] if gewaehlt else p["fg"]))
        m.drawText(QRect(SCHMAL + 10, r.y(), r.width() - SCHMAL - 20, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   k["name"])
        if k.get("zaehler"):
            m.setFont(self.klein)
            m.setPen(QColor(theme.WARN[theme.modus()] if "⚠" in k["zaehler"] else p["hinweis"]))
            m.drawText(QRect(0, r.y(), r.width() - 10, r.height()), Qt.AlignVCenter | Qt.AlignRight, k["zaehler"])

    # -- Maus -----------------------------------------------------------------------------
    def _treffer(self, pos):
        for r, art, d in self._zeilen:
            if r.contains(pos):
                return r, art, d
        return None

    def mouseMoveEvent(self, ev):
        t = self._treffer(ev.position().toPoint())
        neu = (t[0].y(), id(t[2])) if t else None
        if neu != self._hover:
            self._hover = neu
            self.update()
        self.setCursor(Qt.PointingHandCursor if t else Qt.ArrowCursor)

    def leaveEvent(self, ev):
        self._hover = None
        self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        pos = ev.position().toPoint()
        t = self._treffer(pos)
        if not t:
            return
        r, art, d = t
        if art == "knopf":
            self.umschalten()
        elif art == "bereich":
            if d.get("kinder") and self.ausgeklappt and pos.x() >= r.width() - 26 and pos.y() < r.y() + ZEILE_H:
                self.auf_zu(d["id"])               # Pfeil: nur auf-/zuklappen
            else:
                self._klick_bereich(d["id"])
        else:
            self._klick_bereich(d[0]["id"], d[1]["id"])

    def tipp(self, pos):
        """Text des Tooltips an einer Stelle (auch für Tests)."""
        t = self._treffer(pos)
        if not t:
            return ""
        r, art, d = t
        if art == "knopf":
            return _("Collapse the sidebar (Ctrl+B)") if self.ausgeklappt else _("Expand the sidebar (Ctrl+B)")
        if art == "kind":
            return ""
        if d["marken"]:
            return d["name"] + ": " + ", ".join(marken_text(k, n) for k, n in d["marken"])
        if not self.ausgeklappt:
            return d["name"] + (f" ({d['zaehler']})" if d.get("zaehler") else "")
        return ""

    def event(self, ev):
        if ev.type() == ev.Type.ToolTip:
            text = self.tipp(ev.pos())
            if text:
                QToolTip.showText(ev.globalPos(), text, self)
            else:
                QToolTip.hideText()
                ev.ignore()
            return True
        return super().event(ev)

    def changeEvent(self, ev):
        if ev.type() in (ev.Type.FontChange, ev.Type.PaletteChange, ev.Type.StyleChange):
            self._schriften()
            self._layout()
        super().changeEvent(ev)
