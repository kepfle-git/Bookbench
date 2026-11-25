# -*- coding: utf-8 -*-
"""
area_metadata.py - Bereich Metadaten (Qt; Tk-Vorlage tk/area_metadata.py): Titel, Autoren, Reihe,
Verlag, Sprache, ISBN, Schlagwörter und eigene Calibre-Spalten bearbeiten, darunter der Klappentext
(ui/blurb_panel.py), rechts das Cover (ui/cover_panel.py) - wie in Calibres Metadaten-Dialog.

  Bücherliste links mit Suche und Filter (geändert, weicht von Calibre ab, ohne Cover …)
  Mitte oben das Formular (scrollbar): Feld | Wert, darunter nur bei Abweichung "← Calibre: …" bzw.
      "← KOReader: …" (Klick auf ← übernimmt den Wert ins Feld); darunter der Klappentext, dazwischen ein
      Teiler (gemerkt als listenbreiten["metadaten_formular"]). Darunter Hinweise.
  rechts die Cover-Tafel (Breite gemerkt als listenbreiten["cover"], wie bisher)
  Werkzeugleiste: Übernehmen, Verwerfen (Formular, Klappentext und Cover), Aus Calibre (nur mit
      Calibre-Abgleich), Ergänzen ▾ (alle Bücher: Klappentexte/Cover nachschlagen, Calibre-Import, Lücken)

Stände wie überall: im Formular geändert = rot (buch.meta_entwurf), übernommen = gelb (buch.meta_neu,
Reihe/Nummer über buch.reihe_neu). Die Werte eines Buchs (aktuell, Basis, Abweichungen, Marken) rechnet
core/markers - dieselben Funktionen nehmen Bibliothek und Seitenleiste.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout,
                               QWidget)

from bookbench.core import listing
from bookbench.core import markers as km
from bookbench.core import metadata as kme
from bookbench.i18n import N_, _, ngettext
from bookbench.ui.area import Bereich
from bookbench.ui.blurb_panel import KlappentextTafel
from bookbench.ui.booklist import BuchListe
from bookbench.ui.cover_panel import CoverTafel
from bookbench.ui.panes import Teiler

REIHE = ("reihe", "nummer")


class _Vergleich(QWidget):
    """Zeile "← Calibre: Wert" unter einem Feld; Klick auf den Pfeil übernimmt den Wert."""

    def __init__(self, vorne, klick):
        super().__init__()
        self.vorne = vorne
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 2)
        lay.setSpacing(4)
        self.pfeil = QLabel("←")
        self.pfeil.setProperty("rolle", "verweis")
        self.pfeil.setCursor(Qt.PointingHandCursor)
        self.pfeil.setToolTip(_("Put this value into the field"))
        self.pfeil.mousePressEvent = lambda ev: klick()
        lay.addWidget(self.pfeil, 0, Qt.AlignTop)
        self.wert = QLabel("")
        self.wert.setProperty("rolle", "hinweis")
        self.wert.setWordWrap(True)
        self.wert.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.wert, 1)
        self.hide()

    def setzen(self, wert):
        self.wert.setText(f"{self.vorne}: {wert}")
        self.setVisible(bool(wert))


class MetadatenBereich(Bereich):
    kennung = "metadaten"
    titel = N_("Metadata")
    symbol = "metadaten"

    def __init__(self, app):
        super().__init__(app)
        self.buch = None
        self._laden = False
        self._liste_zustand = {}

    # ================================================================ Aufbau
    def bauen(self):
        teiler = Teiler(self.app, "metadaten", 270)
        self.liste = BuchListe(self.app, self.filter(), self._marken_buch)
        self.liste.gewaehlt.connect(self._buch_gewaehlt)
        teiler.addWidget(self.liste)

        rechts = QWidget()
        rl = QVBoxLayout(rechts)
        rl.setContentsMargins(10, 0, 0, 0)
        self.info = QLabel(_("Choose a book on the left."))
        self.info.setProperty("rolle", "hinweis")
        rl.addWidget(self.info)
        koerper = Teiler(self.app, "cover", 250, fest="rechts", minimum=150)
        mitte = QWidget()
        ml = QVBoxLayout(mitte)
        ml.setContentsMargins(0, 0, 6, 0)
        # Standard: so hoch wie das Formular (mit den "← Calibre"-Zeilen des ersten Buchs), Rest Klappentext
        oben_unten = Teiler(self.app, "metadaten_formular", lambda: self.formular.sizeHint().height() + 8,
                            ausrichtung=Qt.Vertical, minimum=80)
        self.flaeche = QScrollArea()
        self.flaeche.setWidgetResizable(True)
        self.flaeche.setFrameShape(QFrame.NoFrame)
        self.formular = QWidget()
        self.raster = QGridLayout(self.formular)
        self.raster.setContentsMargins(0, 0, 4, 0)
        self.raster.setHorizontalSpacing(8)
        self.raster.setVerticalSpacing(1)
        self.raster.setColumnStretch(1, 1)
        self.flaeche.setWidget(self.formular)
        oben_unten.addWidget(self.flaeche)
        self.klappentext = KlappentextTafel(self.app, self)
        oben_unten.addWidget(self.klappentext)
        ml.addWidget(oben_unten, 1)
        self.hinweis = QLabel("")
        self.hinweis.setProperty("rolle", "hinweis")
        self.hinweis.setWordWrap(True)
        ml.addWidget(self.hinweis)
        koerper.addWidget(mitte)
        self.cover = CoverTafel(self.app, self)
        koerper.addWidget(self.cover)
        koerper.setStretchFactor(0, 1)
        rl.addWidget(koerper, 1)
        teiler.addWidget(rechts)
        teiler.setStretchFactor(1, 1)
        self.seite = teiler
        self.felder_bauen()
        if self._liste_zustand:
            self.liste.wiederherstellen(self._liste_zustand)
        self.liste.fuellen(listing.links_sortiert(self.app.buecher), self.buch)
        if self.buch is None:
            self.anzeigen()
        return teiler

    def felder_bauen(self):
        """Formularzeilen: feste Felder, dann die eigenen Spalten aus den Einstellungen."""
        self.felder_w = {}
        for i, feld in enumerate(km.meta_felder(self.app.e)):
            lab = QLabel(km.meta_name(feld, self.app.e) + ":")
            self.raster.addWidget(lab, 2 * i, 0, Qt.AlignVCenter)
            ein = QLineEdit()
            ein.textEdited.connect(lambda *a: self._getippt())
            ein.returnPressed.connect(self.uebernehmen)
            self.raster.addWidget(ein, 2 * i, 1)
            unter = QWidget()
            ul = QVBoxLayout(unter)
            ul.setContentsMargins(0, 0, 0, 0)
            ul.setSpacing(0)
            vergleich = {}
            for quelle, vorne in (("calibre", "Calibre"), ("koreader", "KOReader")):
                v = _Vergleich(vorne, lambda q=quelle, f=feld: self.von(q, f))
                ul.addWidget(v)
                vergleich[quelle] = v
            self.raster.addWidget(unter, 2 * i + 1, 1)
            self.felder_w[feld] = (lab, ein, vergleich)
        self.raster.setRowStretch(2 * len(self.felder_w), 1)

    def werkzeug(self):
        eintraege = [("uebernehmen", _("Apply"), self.uebernehmen, _("Apply form and blurb for this book (Ctrl+Enter)")),
                     ("rueckgaengig", _("Discard"), self.verwerfen,
                      _("Restore metadata, blurb and cover from the file (also drops a series taken from Calibre)")),
                     None]
        if km_calibre_an(self.app):
            eintraege.append(("oeffnen", _("From Calibre"), self.alle_von_calibre,
                              _("Put every value from metadata.calibre that differs into the form (this book)")))
        menue = [(_("Look up all missing blurbs"), self.app.klappentexte_alle),
                 (_("Look up all missing covers"), lambda: self.app.cover_aktion("alle_ohne")),
                 None,
                 (_("Import from Calibre library …"), self.app.calibre_importieren)]
        if km_calibre_an(self.app):
            menue += [None, (_("Fill gaps from Calibre"), self.luecken_fuellen)]
        eintraege.append(("neu_laden", _("Complete"), None,
                          _("For all books: look up missing blurbs or covers, fill gaps from Calibre"), menue))
        return eintraege

    def marken(self):
        return [m for m in km.zaehlen(self.app.buecher, self._marken_buch) if m[0] != "unlesbar"]

    def _marken_buch(self, b):
        return km.metadaten(b, self.app.e)

    def zustand(self):
        return {"liste": self.liste.zustand()}

    def wiederherstellen(self, z):
        self._liste_zustand = z.get("liste") or {}
        self.liste.wiederherstellen(self._liste_zustand)
        self.liste.fuellen(listing.links_sortiert(self.app.buecher), self.buch)

    def suche_fokus(self):
        self.liste.fokus()

    def beim_zeigen(self):
        if self.buch is None and self.liste.liste.count():
            self.liste.waehlen(self.liste.liste.item(0).data(Qt.UserRole))

    def neu_zeichnen(self):
        if self.seite is None:
            return
        self.liste.fuellen(listing.links_sortiert(self.app.buecher), self.buch)

    def buch_geaendert(self, b):
        self.liste.neu_zeichnen()

    def auswaehlen(self, b):
        self.liste.waehlen(b)

    # ================================================================ Liste
    def filter(self):
        e = self.app.e
        return [("alle", N_("All books"), None),
                ("geaendert", N_("Changed"),
                 lambda b: b.meta_entwurf is not None or b.meta_neu is not None or b.reihe_neu is not None
                 or b.cover_neu is not None or b.klappentext_neu is not None or b.klappentext_entwurf is not None),
                ("ohne", N_("No blurb"), lambda b: bool(km.klappentext_fehlt(b, e))),
                ("kt_calibre", N_("Blurb only in Calibre"), lambda b: not b.fehler
                 and not km.klappentext_aktuell(b).strip()
                 and bool(b.calibre and (b.calibre.get("comments") or "").strip())),
                ("calibre", N_("Differs from Calibre"), lambda b: bool(km.meta_abweichend(b, e))),
                ("sort", N_("No author sort"), lambda b: not b.fehler and not km.meta_aktuell(b).get("autor_sort")),
                ("sprache", N_("No language"), lambda b: not b.fehler and not km.meta_aktuell(b).get("sprache")),
                ("isbn", N_("No ISBN"), lambda b: not b.fehler and not km.meta_aktuell(b).get("isbn")),
                ("koreader", N_("Edited in KOReader"), lambda b: bool(getattr(b, "meta_koreader", None))),
                ("fehlt", N_("No cover"), km.cover_fehlt),
                ("klein", N_("Small cover"), lambda b: km.cover_klein(b, e))]

    # ================================================================ Anzeige
    def _buch_gewaehlt(self, b):
        self.buch = b
        self.anzeigen()

    def definitionen(self, b):
        """Definitionen der eigenen Spalten: aus Calibre, darüber die aus dem Buch."""
        d = kme.calibre_definitionen(b.calibre) if b and b.calibre else {}
        d.update(getattr(b, "meta_defs_import", None) or {})
        d.update(getattr(b, "meta_defs", None) or {})
        felder = km.meta_felder(self.app.e)
        return {k: v for k, v in d.items() if k in felder}

    def anzeigen(self):
        b = self.buch
        self._laden = True
        werte = km.meta_aktuell(b) if b else {}
        for feld, (__, ein, __) in self.felder_w.items():
            ein.setText(werte.get(feld, "") if b else "")
            ein.setEnabled(bool(b and not b.fehler))
        self._laden = False
        self.cover.anzeigen()
        self.klappentext.anzeigen()
        if not b:
            self.info.setText(_("Choose a book on the left."))
            self.hinweis.setText("")
            self._vergleiche({})
            return
        self.info.setText(_("File: {name}").format(name=b.pfad.name))
        self.aktualisieren()

    def _vergleiche(self, werte):
        b = self.buch
        quellen = {"calibre": km.meta_calibre(b, self.app.e) if b else {},
                   "koreader": (getattr(b, "meta_koreader", None) or {}) if b else {}}
        for feld, (__, __, vergleich) in self.felder_w.items():
            for quelle, v in vergleich.items():
                w = quellen[quelle].get(feld, "")
                v.setzen(w if w and not kme.gleich(feld, werte.get(feld, ""), w) else "")

    def _hinweise(self, werte):
        b = self.buch
        zeilen = ["⚠ " + t for __, t in kme.pruefen(werte, self.definitionen(b))]
        if b.fehler:
            zeilen.insert(0, "⚠ " + b.fehler)
        if getattr(b, "meta_koreader", None):
            zeilen.append(_("KOReader has its own book information for this book (edited on the e-reader). KOReader "
                            "shows those values instead of the ones in the file; reset them there (Book information "
                            "> long-press a field) if the file should count."))
        if not b.reihe_datei[0] and b.reihe_quelle and b.reihe_neu is None:
            zeilen.append(_("The series {reihe} only comes from the {quelle} data, not from the file; ← next to "
                            "Series puts it into the form.").format(reihe=b.reihe, quelle=b.reihe_quelle))
        if b.meta_entwurf is not None or b.klappentext_entwurf is not None:
            zeilen.append(_("Changed, not yet applied (Ctrl+Enter)."))
        elif b.meta_neu is not None or b.reihe_neu is not None or b.klappentext_neu is not None:
            zeilen.append(_("Applied, not yet saved (Ctrl+S)."))
        self.hinweis.setText("\n".join(zeilen))

    def formular_werte(self):
        """Werte aus dem Formular; Felder ohne Zeile behalten den bisherigen Stand."""
        b = self.buch
        w = km.meta_aktuell(b) if b else {}
        for f, (__, ein, __) in self.felder_w.items():
            w[f] = kme._norm(ein.text())
        return w

    def aktualisieren(self):
        if self.buch is None or self.seite is None:
            return
        werte = self.formular_werte()
        self._vergleiche(werte)
        self._hinweise(werte)

    # ================================================================ Bearbeiten
    def _getippt(self):
        b = self.buch
        if self._laden or not b or b.fehler:
            return
        werte = self.formular_werte()
        basis = km.meta_basis(b)
        gleich = all(kme._norm(werte.get(f, "")) == kme._norm(basis.get(f, "")) for f in set(werte) | set(basis))
        b.meta_entwurf = None if gleich else werte
        self.app.buch_geaendert(b)
        self.aktualisieren()

    def von(self, quelle, feld):
        """← unter einem Feld: Wert aus Calibre bzw. KOReader ins Formular."""
        b = self.buch
        if not b:
            return
        andere = km.meta_calibre(b, self.app.e) if quelle == "calibre" else (getattr(b, "meta_koreader", None) or {})
        if andere.get(feld) and feld in self.felder_w:
            self.felder_w[feld][1].setText(andere[feld])
            self._getippt()

    def uebernehmen(self, b=None, werte=None, mit_klappentext=True):
        """Formular (oder werte) übernehmen: Reihe/Nummer nach reihe_neu, der Rest nach meta_neu, dazu der
        Klappentext (nicht beim Lückenfüllen: nachgeschlagene Entwürfe soll man erst ansehen)."""
        b = b or self.buch
        if not b or b.fehler:
            self.app.status.set(_("Choose a book in the Metadata area first."))
            return
        if werte is None:
            werte = self.formular_werte() if b is self.buch and self.seite is not None else km.meta_aktuell(b)
        b.meta_entwurf = None
        reihe = (kme._norm(werte.get("reihe", "")), kme.nummer_norm(werte.get("nummer", "")))
        datei = (b.meta.get("reihe", ""), b.meta.get("nummer", ""))
        b.reihe_neu = None if (reihe[0] == kme._norm(datei[0]) and kme.gleich("nummer", reihe[1], datei[1])) \
            else (reihe[0], reihe[1] if reihe[0] else "")
        rest = {f: werte[f] for f in werte if f not in REIHE}
        geaendert = [f for f in rest if kme._norm(rest[f]) != kme._norm(b.meta.get(f, ""))]
        b.meta_neu = rest if geaendert else None
        kt = self.klappentext.uebernehmen(b) if mit_klappentext else False
        self.app.buch_geaendert(b)
        if b is self.buch:
            self.anzeigen()
        self.app.status.set(f"{b.name}: " + (_("applied, not yet saved.")
                                              if b.meta_neu is not None or b.reihe_neu is not None or kt
                                              else _("unchanged.")))

    def verwerfen(self):
        b = self.buch
        if not b:
            return
        b.meta_entwurf = b.meta_neu = b.reihe_neu = None
        b.cover_neu, b.cover_neu_quelle = None, ""
        KlappentextTafel.verwerfen(b)
        self.app.buch_geaendert(b)
        self.anzeigen()
        self.app.status.set(f"{b.name}: " + _("metadata, blurb and cover restored from the file."))

    def _calibre_noetig(self):
        if not km_calibre_an(self.app):
            self.app.status.set(_("The Calibre comparison is switched off (Settings > Books > Calibre)."))
            return False
        return True

    def alle_von_calibre(self):
        if not self._calibre_noetig():
            return
        b = self.buch
        if not b or self.app._bereich() != "metadaten":
            self.app.status.set(_("Choose a book in the Metadata area first."))
            return
        cal = km.meta_calibre(b, self.app.e)
        if not cal:
            self.app.status.set(f"{b.name}: " + _("no Calibre data (metadata.calibre) for this book."))
            return
        felder = kme.unterschiede(self.formular_werte(), cal, list(self.felder_w))
        for f in felder:
            self.felder_w[f][1].setText(cal[f])
        if felder:
            self._getippt()
        self.app.status.set(f"{b.name}: " + (ngettext("{n} value from Calibre in the form, not yet applied.",
                                                      "{n} values from Calibre in the form, not yet applied.",
                                                      len(felder)).format(n=len(felder))
                                              if felder else _("matches Calibre.")))

    def luecken_fuellen(self):
        """Alle Bücher: leere Felder aus Calibre füllen und übernehmen (Formular-Entwürfe bleiben unberührt)."""
        if not self._calibre_noetig():
            return
        e = self.app.e
        felder, buecher = 0, 0
        for b in self.app.buecher:
            if b.fehler or b.meta_entwurf is not None or not b.calibre:
                continue
            cal = km.meta_calibre(b, e)
            werte = km.meta_basis(b)
            leer = [f for f in km.meta_felder(e) if cal.get(f) and not kme._norm(werte.get(f, ""))
                    and (f != "nummer" or not werte.get("reihe") or kme.gleich("reihe", werte["reihe"], cal.get("reihe", "")))]
            if not leer:
                continue
            for f in leer:
                werte[f] = cal[f]
            self.uebernehmen(b, werte, mit_klappentext=False)
            felder += len(leer)
            buecher += 1
        self.anzeigen()
        self.app.status.set(ngettext("{felder} values from Calibre in {n} book, not yet saved (Ctrl+S).",
                                     "{felder} values from Calibre in {n} books, not yet saved (Ctrl+S).", buecher)
                            .format(felder=felder, n=buecher) if buecher else
                            _("Nothing to fill: no book has empty fields that Calibre knows."))


def km_calibre_an(app):
    return bool(app.e.get("calibre_an", True))
