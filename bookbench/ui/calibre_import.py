# -*- coding: utf-8 -*-
"""
calibre_import.py - Fenster für den einmaligen Import aus einer Calibre-Bibliothek (Qt; Tk-Vorlage
tk/calibre_import.py). Die Logik steht in core/calibre_import.py.

  ImportDialog(app)
      oben: Calibre-Bibliothek (Ordner mit metadata.db, gemerkt als "calibre_bibliothek"), Einlesen
      Reiter "Änderungen": Buch | Feld | Im Buch | Aus Calibre, Haken je Zeile (Klick, Leertaste);
          Auswahl "Alle Abweichungen" / "Nur leere Felder", Haken "Klappentexte (Beschreibung)"
      Reiter "Nicht zugeordnet": Bücher des Ordners ohne passenden Calibre-Eintrag
      eigene Spalten aus Calibre, die noch kein eigenes Feld sind: "Als eigene Felder übernehmen"
      Übernehmen: angehakte Werte wie überall übernommen (gelb), gespeichert wird mit Strg+S

Zuordnung über UUID, ISBN oder Titel + erster Autor (nur eindeutige Treffer).
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QRadioButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from bookbench.core import calibre_import as kci
from bookbench.core import markers as km
from bookbench.i18n import _, ngettext
from bookbench.ui import dialogs


def standard_ordner():
    for name in ("Calibre Library", "Calibre-Bibliothek", "Calibre Bibliothek", "Calibre-Library"):
        p = Path.home() / name
        if (p / "metadata.db").is_file():
            return str(p)
    return ""


def kurz(text, n=120):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


class ImportDialog(QDialog):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.setWindowTitle(_("Import from a Calibre library"))
        self.resize(980, 620)
        self.eintraege, self.spalten, self.zuordnung, self.ohne = [], {}, {}, []
        self.zeilen = []                        # [(item, buch, feld, neu)]

        lay = QVBoxLayout(self)
        oben = QHBoxLayout()
        oben.addWidget(QLabel(_("Calibre library:")))
        self.ordner = QLineEdit(app.e.get("calibre_bibliothek") or standard_ordner())
        oben.addWidget(self.ordner, 1)
        k = QPushButton(_("Browse …"))
        k.clicked.connect(self.waehlen)
        oben.addWidget(k)
        k = QPushButton(_("Read"))
        k.clicked.connect(self.einlesen)
        oben.addWidget(k)
        lay.addLayout(oben)

        wahl = QHBoxLayout()
        self.r_alle = QRadioButton(_("All differences"))
        self.r_leer = QRadioButton(_("Only empty fields"))
        self.r_alle.setChecked(True)
        gruppe = QButtonGroup(self)
        for r in (self.r_alle, self.r_leer):
            gruppe.addButton(r)
            r.toggled.connect(lambda an: an and self.zeigen())
            wahl.addWidget(r)
        wahl.addSpacing(16)
        self.mit_kt = QCheckBox(_("Blurbs (Calibre's description)"))
        self.mit_kt.setChecked(True)
        self.mit_kt.toggled.connect(lambda *a: self.zeigen())
        wahl.addWidget(self.mit_kt)
        wahl.addStretch(1)
        lay.addLayout(wahl)
        self.zusammenfassung = QLabel(_("Choose the folder of your Calibre library (the one with metadata.db) and "
                                        "click Read."))
        self.zusammenfassung.setProperty("rolle", "hinweis")
        self.zusammenfassung.setWordWrap(True)
        lay.addWidget(self.zusammenfassung)

        self.spalten_zeile = QWidget()
        sz = QHBoxLayout(self.spalten_zeile)
        sz.setContentsMargins(0, 0, 0, 0)
        self.spalten_text = QLabel("")
        self.spalten_text.setWordWrap(True)
        sz.addWidget(self.spalten_text, 1)
        k = QPushButton(_("Add as own fields"))
        k.clicked.connect(self.spalten_uebernehmen)
        sz.addWidget(k)
        self.spalten_zeile.hide()
        lay.addWidget(self.spalten_zeile)

        self.reiter = QTabWidget()
        self.tabelle = QTreeWidget()
        self.tabelle.setHeaderLabels(["", _("Book"), _("Field"), _("In the book"), _("From Calibre")])
        self.tabelle.setRootIsDecorated(False)
        self.tabelle.setUniformRowHeights(True)
        self.tabelle.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for i, w in enumerate((34, 240, 120, 250, 250)):
            self.tabelle.setColumnWidth(i, w)
        self.tabelle.keyPressEvent = self._taste
        self.reiter.addTab(self.tabelle, _("Changes"))
        self.ohne_tabelle = QTreeWidget()
        self.ohne_tabelle.setHeaderLabels([_("Book"), _("File")])
        self.ohne_tabelle.setRootIsDecorated(False)
        self.ohne_tabelle.setColumnWidth(0, 420)
        self.reiter.addTab(self.ohne_tabelle, _("Not matched"))
        lay.addWidget(self.reiter, 1)

        unten = QHBoxLayout()
        for text, an in ((_("Tick all"), True), (_("Untick all"), False)):
            k = QPushButton(text)
            k.clicked.connect(lambda __=False, an=an: self.alle(an))
            unten.addWidget(k)
        unten.addStretch(1)
        self.ok = QPushButton(_("Apply ticked"))
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self.uebernehmen)
        unten.addWidget(self.ok)
        k = QPushButton(_("Close"))
        k.clicked.connect(self.close)
        unten.addWidget(k)
        lay.addLayout(unten)
        if self.ordner.text() and kci.finden(self.ordner.text()):
            self.einlesen()

    # ================================================================ Einlesen
    def waehlen(self):
        o = dialogs.ordner(self, _("Calibre library"), self.ordner.text())
        if o:
            self.ordner.setText(o)
            self.einlesen()

    def einlesen(self):
        db = kci.finden(self.ordner.text())
        if not db:
            self.zusammenfassung.setText(_("No metadata.db in this folder. Choose the folder of your Calibre "
                                           "library (Calibre: right-click the library button > Show folder)."))
            return
        try:
            self.eintraege, self.spalten = kci.lesen(db)
        except Exception as fehler:            # beschädigte oder fremde Datenbank
            self.zusammenfassung.setText(_("Could not read the Calibre library: {fehler}").format(fehler=fehler))
            return
        self.app.e["calibre_bibliothek"] = str(db.parent)
        self.zuordnung, self.ohne = kci.zuordnen(self.app.buecher, self.eintraege)
        self.zeigen()

    def _felder(self):
        return km.meta_felder(self.app.e)

    def zeigen(self):
        t = self.tabelle
        t.clear()
        self.zeilen = []
        nach = {b.schluessel: b for b in self.app.buecher}
        nur_leere = self.r_leer.isChecked()
        for schl, (e, __) in sorted(self.zuordnung.items(), key=lambda x: nach[x[0]].titel.casefold()):
            b = nach[schl]
            zeilen = kci.vorschlaege(km.meta_aktuell(b), e, self._felder(), nur_leere)
            if self.mit_kt.isChecked() and e["beschreibung"]:
                jetzt = km.klappentext_aktuell(b).strip()
                if e["beschreibung"].strip() != jetzt and (not nur_leere or not jetzt):
                    zeilen.append(("klappentext", jetzt, e["beschreibung"].strip()))
            for feld, jetzt, neu in zeilen:
                name = _("Blurb") if feld == "klappentext" else km.meta_name(feld, self.app.e)
                it = QTreeWidgetItem(t, ["", b.name, name, kurz(jetzt) or "–", kurz(neu)])
                it.setCheckState(0, Qt.Checked)
                it.setToolTip(4, neu)
                self.zeilen.append((it, b, feld, neu))
        o = self.ohne_tabelle
        o.clear()
        for b in self.ohne:
            QTreeWidgetItem(o, [b.name, b.pfad.name])
        arten = {}
        for __, art in self.zuordnung.values():
            arten[art] = arten.get(art, 0) + 1
        n = len(self.zeilen)
        self.zusammenfassung.setText(_(
            "{n} books in Calibre. Matched: {z} of {buecher} books in the folder (UUID {u}, ISBN {i}, title and "
            "author {t}), not matched: {o}. {aenderungen}").format(
            n=len(self.eintraege), z=len(self.zuordnung), buecher=len([b for b in self.app.buecher if not b.fehler]),
            u=arten.get("uuid", 0), i=arten.get("isbn", 0), t=arten.get("titel", 0), o=len(self.ohne),
            aenderungen=ngettext("{n} change to take over.", "{n} changes to take over.", n).format(n=n)))
        self.reiter.setTabText(1, _("Not matched ({n})").format(n=len(self.ohne)))
        neu = [k for k in self.spalten if k not in self._felder()]
        if neu:
            namen = ", ".join(f"{self.spalten[k].get('name') or k} ({k})" for k in neu)
            self.spalten_text.setText(_("Own columns in Calibre that are not fields yet: {namen}").format(namen=namen))
        self.spalten_zeile.setVisible(bool(neu))
        self.ok.setEnabled(bool(n))

    # ================================================================ Haken
    def _taste(self, ev):
        if ev.key() == Qt.Key_Space:
            for it in self.tabelle.selectedItems():
                it.setCheckState(0, Qt.Unchecked if it.checkState(0) == Qt.Checked else Qt.Checked)
            return
        QTreeWidget.keyPressEvent(self.tabelle, ev)

    def alle(self, an):
        for it, *__ in self.zeilen:
            it.setCheckState(0, Qt.Checked if an else Qt.Unchecked)

    def spalten_uebernehmen(self):
        """Eigene Calibre-Spalten als eigene Felder dazunehmen (Einstellung meta_spalten)."""
        e = self.app.e
        liste = [list(x) for x in e.get("meta_spalten") or []]
        for k, fm in self.spalten.items():
            if k not in {x[0] for x in liste}:
                liste.append([k, fm.get("name") or k])
        e["meta_spalten"] = liste
        self.app.oberflaeche_bauen()                # neue Felder im Formular
        self.zeigen()

    # ================================================================ Übernehmen
    def uebernehmen(self):
        je_buch = {}
        for it, b, feld, neu in self.zeilen:
            if it.checkState(0) == Qt.Checked:
                je_buch.setdefault(b.schluessel, (b, {}))[1][feld] = neu
        m = self.app.metadaten
        for b, felder in je_buch.values():
            kt = felder.pop("klappentext", None)
            if felder:
                werte = km.meta_basis(b)
                werte.update(felder)
                # eigene Spalten, die das Buch noch nicht hat: Definition aus Calibre fürs Speichern mitgeben
                for k in felder:
                    if k.startswith("#") and k in self.spalten:
                        b.meta_defs_import[k] = self.spalten[k]
                m.uebernehmen(b, werte, mit_klappentext=False)
            if kt is not None:
                b.klappentext_entwurf = None
                b.klappentext_neu = kt
                b.klappentext_quelle = "Calibre"
            self.app.buch_geaendert(b)
        if m.seite is not None:
            m.anzeigen()
        self.app.status.set(ngettext("Calibre import: {n} book changed, not yet saved (Ctrl+S).",
                                     "Calibre import: {n} books changed, not yet saved (Ctrl+S).", len(je_buch))
                            .format(n=len(je_buch)))
        self.zeigen()
