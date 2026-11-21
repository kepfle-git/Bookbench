# -*- coding: utf-8 -*-
"""
area_blurbs.py - Klappentext von Bookbench: seit 1.3-beta3 kein eigener Bereich mehr, sondern eine Tafel
unter dem Formular im Bereich Metadaten (wie Calibres "Kommentare" im Metadaten-Dialog).

  KlappentextTafel(app, eltern, metadaten)
      Kopfzeile "Klappentext" mit kleinen Knöpfen Nachschlagen / Aus Calibre, darunter das Textfeld und
      die Quelle. Buch und Liste gehören dem Bereich Metadaten.
  aktueller_text(b), fehlt(b)   Entwurf vor Übernommenem vor Datei; Warntext ohne Klappentext

Stände wie überall: getippt = buch.klappentext_entwurf (rot), übernommen = klappentext_neu (gelb).
Das Nachschlagen im Hintergrund (Zwischenspeicher, Quellprofile, Claude) bleibt in app.py.
"""
import tkinter as tk
from tkinter import ttk

import keller_theme as kth
from bookbench.core import blurbs
from bookbench.core import library as kd
from bookbench.i18n import _


class KlappentextTafel:
    def __init__(self, app, eltern, metadaten):
        self.app = app
        self.metadaten = metadaten
        self._laden = False
        kopf = ttk.Frame(eltern)
        kopf.pack(fill="x", pady=(0, 3))
        ttk.Label(kopf, text=_("Blurb"), style="Ueberschrift.TLabel").pack(side="left")
        self.knoepfe = ttk.Frame(kopf)
        self.knoepfe.pack(side="right")
        self.knoepfe_bauen()
        r = app._listenrahmen(eltern)
        r.pack(fill="both", expand=True)
        self.text = tk.Text(r, wrap="word", borderwidth=0, highlightthickness=0, padx=8, pady=6,
                            font=kth.schrift(11), undo=True, height=4)
        sb = ttk.Scrollbar(r, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.quelle = ttk.Label(eltern, text="", style="Hinweis.TLabel")
        self.quelle.pack(anchor="w", pady=(3, 0))
        self.text.bind("<<Modified>>", lambda e: self._getippt())
        self.text.bind("<Control-Return>", lambda e: (app.uebernehmen(), "break")[1])
        app.kt_text, app.kt_quelle = self.text, self.quelle          # Zugang wie vor 1.3-beta3 (Tests)

    def knoepfe_bauen(self):
        """Kleine Knöpfe rechts in der Kopfzeile (Aus Calibre nur mit Calibre-Abgleich)."""
        for w in self.knoepfe.winfo_children():
            w.destroy()
        knoepfe = [(_("Look up"), self.app.klappentext_nachschlagen)]
        if self.app.e.get("calibre_an", True):
            knoepfe.append((_("From Calibre"), self.aus_calibre))
        for text, befehl in knoepfe:
            ttk.Button(self.knoepfe, text=text, command=befehl, style="Klein.TButton").pack(side="left", padx=(4, 0))

    # ================================================================ Werte
    @staticmethod
    def aktueller_text(b):
        if b.klappentext_entwurf is not None:
            return b.klappentext_entwurf
        return b.klappentext_neu if b.klappentext_neu is not None else b.klappentext

    def fehlt(self, b):
        """Warntext, wenn das Buch (nach dem aktuellen Stand) keinen Klappentext hat."""
        if b.fehler or self.aktueller_text(b).strip():
            return None
        if b.calibre and self.app.e.get("calibre_an", True) and (b.calibre.get("comments") or "").strip():
            return _("no blurb (Calibre has one: From Calibre)")
        return _("no blurb")

    @staticmethod
    def quelle_text(b):
        q = b.klappentext_quelle
        name = blurbs.source_name(q)
        return q if name == q else f"{name} ({q})"

    # ================================================================ Anzeige und Bearbeiten
    def anzeigen(self):
        b = self.metadaten.buch
        self._laden = True
        self.text.delete("1.0", "end")
        if b:
            self.text.insert("1.0", self.aktueller_text(b))
            self.quelle.configure(text=_("Source: {quelle}").format(quelle=self.quelle_text(b)) if b.klappentext_quelle
                                  else ("" if b.klappentext else _("No blurb in the file.")))
            self.text.configure(state="normal" if not b.fehler else "disabled")
        else:
            self.quelle.configure(text="")
        self.text.edit_modified(False)
        self.text.edit_reset()
        self._laden = False

    def _getippt(self):
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        b = self.metadaten.buch
        if self._laden or not b:
            return
        text = self.text.get("1.0", "end-1c").strip()
        vorher = b.klappentext_neu if b.klappentext_neu is not None else b.klappentext
        b.klappentext_entwurf = None if text == vorher.strip() else text
        self.app._geaendert(b)
        self.metadaten._aktualisieren()

    def uebernehmen(self, b):
        """Klappentext des Buchs übernehmen (Text aus dem Feld, wenn es das angezeigte Buch ist)."""
        if b is self.metadaten.buch:
            text = self.text.get("1.0", "end-1c").strip()
        else:
            text = self.aktueller_text(b).strip()
        b.klappentext_entwurf = None
        b.klappentext_neu = None if text == b.klappentext.strip() else text
        return b.klappentext_neu is not None

    def verwerfen(self, b):
        b.klappentext_entwurf = b.klappentext_neu = None
        b.klappentext_quelle = b.klappentext_quelle_datei

    def aus_calibre(self):
        if self.app._calibre_aus():
            return
        b = self.metadaten.buch
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
        self.app._geaendert(b)
        self.metadaten._aktualisieren()
        self.app.status.set(f"{b.name}: " + _("description from Calibre, not yet applied."))
