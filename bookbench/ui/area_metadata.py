# -*- coding: utf-8 -*-
"""
area_metadata.py - Bereich "Metadaten" von Bookbench: Titel, Autoren, Reihe, Verlag, Sprache,
ISBN, Schlagwörter (und auf Wunsch der Untertitel aus einer eigenen Calibre-Spalte) im OPF bearbeiten.
Die Logik steckt in core/metadata (Lesen/Schreiben, Vergleich); gespeichert wird über library.speichern.

  Bücherliste links mit Suche und Filter (geändert, weicht von Calibre ab, ohne Sortiername …)
  rechts ein Formular: Feld | Wert im Buch | Calibre ← | KOReader ←
      die Spalten Calibre/KOReader erscheinen nur, wenn es dort Werte gibt; ← übernimmt ins Feld
  Werkzeugleiste: Übernehmen, Verwerfen, Aus Calibre (dieses Buch), Lücken aus Calibre (alle Bücher)

Stände wie überall: im Formular geändert = rot (buch.meta_entwurf), übernommen = gelb (buch.meta_neu,
Reihe/Nummer über buch.reihe_neu wie beim Übernehmen aus Calibre in der Bibliothek).
Die Oberfläche ist absichtlich dünn (Plan 2.0: Umstieg auf Qt).
"""
import tkinter as tk
from tkinter import ttk

from bookbench.core import metadata as km
from bookbench.i18n import N_, _, ngettext
from bookbench.ui import list_filter as klf

REIHE = ("reihe", "nummer")
BREITE = {"nummer": 8, "sprache": 10, "isbn": 20}


class MetadatenBereich:
    def __init__(self, app):
        self.app = app
        self.buch = None
        self._laden = False                       # Formular wird gerade programmseitig gefüllt
        s = self.seite = app._seite(_("Metadata"), "metadaten")
        links = ttk.Frame(s)
        links.pack(side="left", fill="y")
        kopf = ttk.Label(links, text=_("Books:"))
        kopf.pack(anchor="w")
        self.liste = app._buchliste(links, self.anzeigen, self._status, filter=self.filter(),
                                    geaendert=lambda: self.liste_fuellen(), kopf=kopf)
        rechts = ttk.Frame(s)
        rechts.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.cover, self.kopf, self.info = app._kopfzeile(rechts)
        f = self.formular = ttk.Frame(rechts)
        f.pack(fill="x", anchor="n")
        f.columnconfigure(1, weight=1)
        self.kopfzeilen = {}
        for spalte, text in ((1, _("In the book")), (2, "Calibre"), (4, "KOReader")):
            lab = ttk.Label(f, text=text, style="Hinweis.TLabel")
            lab.grid(row=0, column=spalte, columnspan=2 if spalte > 1 else 1, sticky="w", padx=(0, 6), pady=(0, 4))
            self.kopfzeilen[spalte] = lab
        self.var, self.zeilen = {}, {}
        for i, feld in enumerate(km.FELDER, 1):
            lab = ttk.Label(f, text=_(km.NAMEN[feld]) + ":")
            lab.grid(row=i, column=0, sticky="w", padx=(0, 8), pady=2)
            v = self.var[feld] = tk.StringVar()
            ein = ttk.Entry(f, textvariable=v, width=BREITE.get(feld, 44))
            ein.grid(row=i, column=1, sticky="w" if feld in BREITE else "we", pady=2)
            ein.bind("<Return>", lambda e: (self.uebernehmen(), "break")[1])
            v.trace_add("write", lambda *a: self._getippt())
            cal = ttk.Label(f, text="", wraplength=240, justify="left")
            cal.grid(row=i, column=2, sticky="w", padx=(12, 2))
            cal_k = self._pfeil(f, lambda feld=feld: self.von("calibre", feld))
            cal_k.grid(row=i, column=3, sticky="w")
            ko = ttk.Label(f, text="", wraplength=200, justify="left")
            ko.grid(row=i, column=4, sticky="w", padx=(12, 2))
            ko_k = self._pfeil(f, lambda feld=feld: self.von("koreader", feld))
            ko_k.grid(row=i, column=5, sticky="w")
            self.zeilen[feld] = (lab, ein, cal, cal_k, ko, ko_k)
        self.hinweis = ttk.Label(rechts, text="", style="Hinweis.TLabel", wraplength=900, justify="left")
        self.hinweis.pack(anchor="w", pady=(10, 0), fill="x")
        self.hinweis.bind("<Configure>", lambda e: self.hinweis.configure(wraplength=max(300, e.width - 8)))

    def _pfeil(self, eltern, befehl):
        """Klickbares ← (Label statt Knopf: ein ttk-Knopf macht die Zeile höher als die übrigen)."""
        k = ttk.Label(eltern, text="←", cursor="hand2", style="Ueberschrift.TLabel", padding=(4, 0))
        k.bind("<Button-1>", lambda e: befehl())
        return k

    # ================================================================ Werkzeugleiste
    def werkzeug(self, eltern):
        a = self.app
        a._wz_knopf(eltern, "uebernehmen", _("Apply"), self.uebernehmen, _("Apply the form for this book (Ctrl+Enter)"))
        a._wz_knopf(eltern, "rueckgaengig", _("Discard"), self.verwerfen,
                    _("Restore the values from the file (also drops a series taken from Calibre)"))
        ttk.Separator(eltern, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
        a._wz_knopf(eltern, "oeffnen", _("From Calibre"), self.alle_von_calibre,
                    _("Put every value from metadata.calibre that differs into the form (this book)"))
        a._wz_knopf(eltern, "pruefen", _("Fill gaps from Calibre"), self.luecken_fuellen,
                    _("All books: take values from metadata.calibre only where the book has none"))

    # ================================================================ Werte
    def felder(self):
        """Angezeigte Felder (Untertitel nur, wenn eingeschaltet)."""
        an = self.app.e.get("meta_untertitel") and self.app.e.get("meta_untertitel_spalte")
        return [f for f in km.FELDER if f != "untertitel" or an]

    @staticmethod
    def basis(b):
        """Übernommener Stand (Datei, darüber meta_neu und reihe_neu)."""
        w = dict(b.meta)
        if b.meta_neu:
            w.update(b.meta_neu)
        if b.reihe_neu is not None:
            w["reihe"], w["nummer"] = b.reihe_neu
        return w

    def aktuell(self, b):
        return dict(b.meta_entwurf) if b.meta_entwurf is not None else self.basis(b)

    def calibre(self, b):
        return km.calibre_werte(b.calibre) if b.calibre else {}

    def abweichend(self, b, felder=None):
        cal = self.calibre(b)
        return km.unterschiede(self.aktuell(b), cal, felder or self.felder()) if cal else []

    def _warnung(self, b):
        if b.fehler:
            return b.fehler
        if b.meta.get("isbn") and not km.isbn_ok(self.aktuell(b).get("isbn", "")):
            return _("ISBN not valid")
        wichtig = self.abweichend(b, km.WICHTIG)
        if wichtig:
            return _("differs from Calibre: {felder}").format(felder=", ".join(_(km.NAMEN[f]) for f in wichtig))
        return None

    def warnungen(self):
        return sum(1 for b in self.app.buecher if self._warnung(b))

    # ================================================================ Liste
    def filter(self):
        return [("alle", N_("All books"), None),
                ("geaendert", N_("Changed metadata"),
                 lambda b: b.meta_entwurf is not None or b.meta_neu is not None or b.reihe_neu is not None),
                ("calibre", N_("Differs from Calibre"), lambda b: bool(self.abweichend(b))),
                ("sort", N_("No author sort"), lambda b: not b.fehler and not self.aktuell(b).get("autor_sort")),
                ("sprache", N_("No language"), lambda b: not b.fehler and not self.aktuell(b).get("sprache")),
                ("isbn", N_("No ISBN"), lambda b: not b.fehler and not self.aktuell(b).get("isbn")),
                ("koreader", N_("Edited in KOReader"), lambda b: bool(getattr(b, "meta_koreader", None)))]

    def liste_fuellen(self, sortiert=None):
        a = self.app
        if sortiert is None:
            sortiert = a._links_sortiert()
        vorher = a.nach_schluessel.get(self.buch.schluessel) if self.buch else None
        lf = self.liste.filter
        sichtbar = [b for b in sortiert if lf.passt(b)]
        self.liste.delete(0, "end")
        for b in sichtbar:
            self.liste.insert("end", a._anzeigename(b))
        lf.anzahl(len(sichtbar), len(sortiert))
        neu = klf.nachfolger(sortiert, vorher, lf.passt) or (sichtbar[0] if vorher and sichtbar else None)
        if neu:
            self.auswaehlen(neu)
        else:
            self.anzeigen()

    def auswaehlen(self, b):
        namen = list(self.liste.get(0, "end"))
        name = self.app._anzeigename(b)
        if name not in namen and self.liste.filter.aktiv() and b in self.app.buecher:
            self.liste.filter.zuruecksetzen()
            namen = list(self.liste.get(0, "end"))
        if name in namen:
            i = namen.index(name)
            self.liste.selection_clear(0, "end")
            self.liste.selection_set(i)
            self.liste.see(i)
            self.anzeigen()

    def _status(self, name):
        b = self.app._listen_buch.get(name)
        return (b.stand(), self._warnung(b)) if b else (None, None)

    def beim_zeigen(self):
        if not self.liste.curselection() and self.liste.size():
            self.liste.selection_set(0)
        self.anzeigen()

    # ================================================================ Anzeige
    def anzeigen(self):
        self.buch = b = self.app._aktuelles_buch(self.liste)
        self._laden = True
        felder = self.felder()
        cal = self.calibre(b) if b else {}
        ko = (getattr(b, "meta_koreader", None) or {}) if b else {}
        werte = self.aktuell(b) if b else {}
        for feld, (lab, ein, c, ck, k, kk) in self.zeilen.items():
            sichtbar = feld in felder
            for w in (lab, ein, c, ck, k, kk):
                if sichtbar:
                    w.grid()
                else:
                    w.grid_remove()
            self.var[feld].set(werte.get(feld, "") if b else "")
            ein.configure(state="normal" if b and not b.fehler else "disabled")
            self._vergleich(c, ck, feld, cal, werte, bool(cal) and sichtbar)
            self._vergleich(k, kk, feld, ko, werte, bool(ko) and sichtbar)
        for spalte, da in ((2, bool(cal)), (4, bool(ko))):
            (self.kopfzeilen[spalte].grid if da else self.kopfzeilen[spalte].grid_remove)()
        self._laden = False
        if not b:
            self.kopf.configure(text=_("Choose a book on the left."))
            self.info.configure(text="")
            self.app._cover_zeigen(self.cover, None)
            self.hinweis.configure(text="")
            return
        self.kopf.configure(text=b.name)
        self.info.configure(text=b.pfad.name)
        self.app._cover_zeigen(self.cover, b)
        self._hinweise()

    def _vergleich(self, lab, knopf, feld, andere, werte, da):
        """Wert aus Calibre/KOReader neben dem Feld; ← nur, wenn er abweicht."""
        if not da:
            lab.grid_remove()
            knopf.grid_remove()
            return
        lab.grid()
        w = andere.get(feld, "")
        abw = bool(w) and not km.gleich(feld, werte.get(feld, ""), w)
        lab.configure(text=w or "–", style="TLabel" if abw else "Hinweis.TLabel")
        if abw:
            knopf.grid()
        else:
            knopf.grid_remove()

    def _hinweise(self):
        b = self.buch
        werte = self.formular_werte()
        zeilen = ["⚠ " + t for __, t in km.pruefen(werte)]
        if b.fehler:
            zeilen.insert(0, "⚠ " + b.fehler)
        if getattr(b, "meta_koreader", None):
            zeilen.append(_("KOReader has its own book information for this book (edited on the e-reader). KOReader "
                            "shows those values instead of the ones in the file; reset them there (Book information "
                            "> long-press a field) if the file should count."))
        if not b.reihe_datei[0] and b.reihe_quelle and b.reihe_neu is None:
            zeilen.append(_("The series {reihe} only comes from the {quelle} data, not from the file; ← next to "
                            "Series puts it into the form.").format(reihe=b.reihe, quelle=b.reihe_quelle))
        if b.calibre:
            zeilen.append(_("Calibre writes its own values into the book the next time it sends it to the e-reader. "
                            "Change them in Calibre as well, otherwise your changes here get lost."))
        if b.meta_entwurf is not None:
            zeilen.append(_("Changed, not yet applied (Ctrl+Enter)."))
        elif b.meta_neu is not None or b.reihe_neu is not None:
            zeilen.append(_("Applied, not yet saved (Ctrl+S)."))
        self.hinweis.configure(text="\n".join(zeilen))

    def formular_werte(self):
        """Werte aus dem Formular; verborgene Felder behalten den bisherigen Stand."""
        b = self.buch
        w = self.aktuell(b) if b else {}
        for f in self.felder():
            w[f] = km._norm(self.var[f].get())
        return w

    # ================================================================ Bearbeiten
    def _getippt(self):
        b = self.buch
        if self._laden or not b or b.fehler:
            return
        werte = self.formular_werte()
        basis = self.basis(b)
        gleich = all(km._norm(werte.get(f, "")) == km._norm(basis.get(f, "")) for f in km.FELDER)
        b.meta_entwurf = None if gleich else werte
        self.app._geaendert(b)
        self._aktualisieren()

    def _aktualisieren(self):
        """Vergleichsspalten und Hinweise nach einer Änderung (ohne das Formular neu zu füllen)."""
        b = self.buch
        werte = self.formular_werte()
        cal = self.calibre(b)
        ko = getattr(b, "meta_koreader", None) or {}
        felder = self.felder()
        for feld, (__, __, c, ck, k, kk) in self.zeilen.items():
            self._vergleich(c, ck, feld, cal, werte, bool(cal) and feld in felder)
            self._vergleich(k, kk, feld, ko, werte, bool(ko) and feld in felder)
        self._hinweise()

    def von(self, quelle, feld):
        """← neben einem Feld: Wert aus Calibre bzw. KOReader ins Formular."""
        b = self.buch
        if not b:
            return
        andere = self.calibre(b) if quelle == "calibre" else (getattr(b, "meta_koreader", None) or {})
        if andere.get(feld):
            self.var[feld].set(andere[feld])

    def uebernehmen(self, b=None, werte=None):
        """Formular (oder werte) übernehmen: Reihe/Nummer nach reihe_neu, der Rest nach meta_neu."""
        b = b or self.buch
        if not b or b.fehler:
            self.app.status.set(_("Choose a book in the Metadata area first."))
            return
        if werte is None:
            werte = self.formular_werte() if b is self.buch else self.aktuell(b)
        b.meta_entwurf = None
        reihe = (werte.get("reihe", ""), werte.get("nummer", ""))
        datei = (b.meta.get("reihe", ""), b.meta.get("nummer", ""))
        b.reihe_neu = None if (km._norm(reihe[0]) == km._norm(datei[0]) and km.gleich("nummer", reihe[1], datei[1])) \
            else (km._norm(reihe[0]), km._norm(reihe[1]) if reihe[0] else "")
        rest = {f: werte.get(f, b.meta.get(f, "")) for f in km.FELDER if f not in REIHE}
        geaendert = [f for f in rest if km._norm(rest[f]) != km._norm(b.meta.get(f, ""))]
        b.meta_neu = rest if geaendert else None
        self.app._geaendert(b)
        if b is self.buch:
            self.anzeigen()
        self.app.status.set(f"{b.name}: " + (_("metadata applied, not yet saved.")
                                              if b.meta_neu is not None or b.reihe_neu is not None else _("unchanged.")))

    def verwerfen(self):
        b = self.buch
        if not b:
            return
        b.meta_entwurf = b.meta_neu = b.reihe_neu = None
        self.app._geaendert(b)
        self.anzeigen()
        self.app.status.set(f"{b.name}: " + _("metadata restored from the file."))

    def alle_von_calibre(self):
        b = self.buch
        if not b or self.app._bereich() != "metadaten":
            self.app.status.set(_("Choose a book in the Metadata area first."))
            return
        cal = self.calibre(b)
        if not cal:
            self.app.status.set(f"{b.name}: " + _("no Calibre data (metadata.calibre) for this book."))
            return
        felder = km.unterschiede(self.formular_werte(), cal, self.felder())
        for f in felder:
            self.var[f].set(cal[f])
        self.app.status.set(f"{b.name}: " + (ngettext("{n} value from Calibre in the form, not yet applied.",
                                                      "{n} values from Calibre in the form, not yet applied.",
                                                      len(felder)).format(n=len(felder))
                                              if felder else _("matches Calibre.")))

    def luecken_fuellen(self):
        """Alle Bücher: leere Felder aus Calibre füllen und übernehmen (Formular-Entwürfe bleiben unberührt)."""
        felder, buecher = 0, 0
        for b in self.app.buecher:
            if b.fehler or b.meta_entwurf is not None or not b.calibre:
                continue
            cal = self.calibre(b)
            werte = self.basis(b)
            leer = [f for f in self.felder() if cal.get(f) and not km._norm(werte.get(f, ""))
                    and (f != "nummer" or not werte.get("reihe") or km.gleich("reihe", werte["reihe"], cal.get("reihe", "")))]
            if not leer:
                continue
            for f in leer:
                werte[f] = cal[f]
            self.uebernehmen(b, werte)
            felder += len(leer)
            buecher += 1
        self.anzeigen()
        self.app.status.set(ngettext("{felder} values from Calibre in {n} book, not yet saved (Ctrl+S).",
                                     "{felder} values from Calibre in {n} books, not yet saved (Ctrl+S).", buecher)
                            .format(felder=felder, n=buecher) if buecher else
                            _("Nothing to fill: no book has empty fields that Calibre knows."))
