# -*- coding: utf-8 -*-
"""
area_metadata.py - Bereich "Metadaten" von Bookbench: Titel, Autoren, Reihe, Verlag, Sprache,
ISBN, Schlagwörter und frei wählbare eigene Calibre-Spalten im OPF bearbeiten, rechts daneben das
Cover (seit 1.3-beta2, wie in Calibres Metadaten-Dialog; ui/area_covers.CoverBereich).
Die Logik steckt in core/metadata (Lesen/Schreiben, Vergleich); gespeichert wird über library.speichern.

  Bücherliste links mit Suche und Filter (geändert, weicht von Calibre ab, ohne Cover …)
  Mitte das Formular: Feld | Wert im Buch, darunter (nur wenn abweichend) "← Calibre: …" bzw.
      "← KOReader: …"; ← übernimmt den Wert ins Feld
  rechts das Cover mit seinen Knöpfen
  Werkzeugleiste: Übernehmen, Verwerfen, Aus Calibre, Lücken füllen (nur mit Calibre-Abgleich),
      Alle ohne Cover

Eigene Felder: Einstellung meta_spalten = [[Suchname, Bezeichnung]], z. B. [["#subtitle", "Untertitel"]].
Stände wie überall: im Formular geändert = rot (buch.meta_entwurf), übernommen = gelb (buch.meta_neu,
Reihe/Nummer über buch.reihe_neu wie beim Übernehmen aus Calibre in der Bibliothek, Cover über cover_neu).
Die Oberfläche ist absichtlich dünn (Plan 2.0: Umstieg auf Qt).
"""
import tkinter as tk
from tkinter import ttk

from bookbench.core import metadata as km
from bookbench.i18n import N_, _, ngettext
from bookbench.ui import area_covers as kbc
from bookbench.ui import list_filter as klf

REIHE = ("reihe", "nummer")
FELDBREITE = 24            # Zeichen (Mindestbreite); alle Felder gleich breit, sie füllen den Platz neben dem Cover
COVER_BREITE = 280         # px, Tafel mit dem Cover rechts


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
        self.kopf = ttk.Label(rechts, text=_("Choose a book on the left."), style="Ueberschrift.TLabel")
        self.kopf.pack(anchor="w")
        self.info = ttk.Label(rechts, text="", style="Hinweis.TLabel")
        self.info.pack(anchor="w", pady=(2, 8))
        koerper = ttk.Frame(rechts)
        koerper.pack(fill="both", expand=True)
        # Cover zuerst einpacken: es behält seine Breite, das Formular nimmt den Rest
        tafel = ttk.Frame(koerper, width=COVER_BREITE)
        tafel.pack(side="right", fill="y", padx=(16, 0))
        tafel.pack_propagate(False)
        mitte = ttk.Frame(koerper)
        mitte.pack(side="left", fill="both", expand=True, anchor="n")
        self.formular = ttk.Frame(mitte)
        self.formular.pack(anchor="nw", fill="x")
        self.formular.columnconfigure(1, weight=1)
        self.hinweis = ttk.Label(mitte, text="", style="Hinweis.TLabel", justify="left")
        self.hinweis.pack(anchor="w", pady=(10, 0), fill="x")
        self.hinweis.bind("<Configure>", lambda e: self.hinweis.configure(wraplength=max(300, e.width - 4)))
        self.cover = kbc.CoverBereich(app, tafel, self)
        app.cover = self.cover                     # app.cover bleibt der Zugang für Bibliothek, Menü und Tests
        self.var, self.zeilen = {}, {}
        self.felder_bauen()

    def felder_bauen(self):
        """Formularzeilen (neu) bauen: feste Felder, dann die eigenen Spalten aus den Einstellungen."""
        for w in self.formular.winfo_children():
            w.destroy()
        self.var, self.zeilen = {}, {}
        for i, feld in enumerate(self.felder()):
            lab = ttk.Label(self.formular, text=self.name(feld) + ":")
            lab.grid(row=2 * i, column=0, sticky="w", padx=(0, 8), pady=(3, 0))
            v = self.var[feld] = tk.StringVar()
            ein = ttk.Entry(self.formular, textvariable=v, width=FELDBREITE)
            ein.grid(row=2 * i, column=1, sticky="we", pady=(3, 0))
            ein.bind("<Return>", lambda e: (self.uebernehmen(), "break")[1])
            v.trace_add("write", lambda *a: self._getippt())
            unter = ttk.Frame(self.formular)
            unter.grid(row=2 * i + 1, column=1, sticky="we")
            vergleich = {}
            for quelle, text in (("calibre", "Calibre"), ("koreader", "KOReader")):
                z = ttk.Frame(unter)
                pfeil = ttk.Label(z, text="←", cursor="hand2", style="Ueberschrift.TLabel", padding=(2, 0, 4, 0))
                pfeil.pack(side="left")
                pfeil.bind("<Button-1>", lambda e, q=quelle, f=feld: self.von(q, f))
                wert = ttk.Label(z, text="", style="Hinweis.TLabel", justify="left")
                wert.pack(side="left", fill="x", expand=True)
                wert.bind("<Configure>", lambda e, w=wert: w.configure(wraplength=max(150, e.width - 4)))
                wert.text_vorne = text
                vergleich[quelle] = (z, wert)
            self.zeilen[feld] = (lab, ein, vergleich)

    # ================================================================ Werkzeugleiste
    def werkzeug(self, eltern):
        a = self.app
        a._wz_knopf(eltern, "uebernehmen", _("Apply"), self.uebernehmen, _("Apply the form for this book (Ctrl+Enter)"))
        a._wz_knopf(eltern, "rueckgaengig", _("Discard"), self.verwerfen,
                    _("Restore metadata and cover from the file (also drops a series taken from Calibre)"))
        if self.calibre_an():
            ttk.Separator(eltern, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
            a._wz_knopf(eltern, "oeffnen", _("From Calibre"), self.alle_von_calibre,
                        _("Put every value from metadata.calibre that differs into the form (this book)"))
            a._wz_knopf(eltern, "pruefen", _("Fill gaps"), self.luecken_fuellen,
                        _("All books: take values from metadata.calibre only where the book has none"))
        ttk.Separator(eltern, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
        a._wz_knopf(eltern, "neu_laden", _("All without cover"), self.cover.alle_ohne,
                    _("For all books without a cover: take the largest cover found, in the background"))

    # ================================================================ Werte
    def calibre_an(self):
        return bool(self.app.e.get("calibre_an", True))

    def eigene(self):
        """[(Suchname, Bezeichnung)] der eigenen Felder aus den Einstellungen."""
        erg = []
        for e in self.app.e.get("meta_spalten") or []:
            if isinstance(e, (list, tuple)) and e and str(e[0]).startswith("#"):
                erg.append((str(e[0]), str(e[1]) if len(e) > 1 and e[1] else str(e[0])))
        return erg

    def felder(self):
        return list(km.FELDER) + [s for s, __ in self.eigene()]

    def name(self, feld):
        return _(km.NAMEN[feld]) if feld in km.NAMEN else dict(self.eigene()).get(feld, feld)

    def definitionen(self, b):
        """Definitionen der eigenen Spalten: aus Calibre, darüber die aus dem Buch."""
        d = km.calibre_definitionen(b.calibre) if b and b.calibre else {}
        d.update(getattr(b, "meta_defs", None) or {})
        return {k: v for k, v in d.items() if k in self.felder()}

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
        return km.calibre_werte(b.calibre) if b.calibre and self.calibre_an() else {}

    def abweichend(self, b, felder=None):
        cal = self.calibre(b)
        return km.unterschiede(self.aktuell(b), cal, felder or self.felder()) if cal else []

    def _warnung(self, b):
        if b.fehler:
            return b.fehler
        teile = []
        if b.meta.get("isbn") and not km.isbn_ok(self.aktuell(b).get("isbn", "")):
            teile.append(_("ISBN not valid"))
        wichtig = self.abweichend(b, km.WICHTIG)
        if wichtig:
            teile.append(_("differs from Calibre: {felder}").format(felder=", ".join(self.name(f) for f in wichtig)))
        c = self.cover.warnung(b)
        if c:
            teile.append(c)
        return "; ".join(teile) or None

    def warnungen(self):
        return sum(1 for b in self.app.buecher if self._warnung(b))

    # ================================================================ Liste
    def filter(self):
        return [("alle", N_("All books"), None),
                ("geaendert", N_("Changed metadata or cover"),
                 lambda b: b.meta_entwurf is not None or b.meta_neu is not None or b.reihe_neu is not None
                 or b.cover_neu is not None),
                ("calibre", N_("Differs from Calibre"), lambda b: bool(self.abweichend(b))),
                ("sort", N_("No author sort"), lambda b: not b.fehler and not self.aktuell(b).get("autor_sort")),
                ("sprache", N_("No language"), lambda b: not b.fehler and not self.aktuell(b).get("sprache")),
                ("isbn", N_("No ISBN"), lambda b: not b.fehler and not self.aktuell(b).get("isbn")),
                ("koreader", N_("Edited in KOReader"), lambda b: bool(getattr(b, "meta_koreader", None))),
                ("fehlt", N_("No cover"), lambda b: self.cover.fehlt(b)),
                ("klein", N_("Small cover"), lambda b: self.cover.klein(b))]

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
        werte = self.aktuell(b) if b else {}
        for feld, (__, ein, __) in self.zeilen.items():
            self.var[feld].set(werte.get(feld, "") if b else "")
            ein.configure(state="normal" if b and not b.fehler else "disabled")
        self._laden = False
        self.cover.anzeigen()
        if not b:
            self.kopf.configure(text=_("Choose a book on the left."))
            self.info.configure(text="")
            self.hinweis.configure(text="")
            self._vergleiche({})
            return
        self.kopf.configure(text=b.name)
        self.info.configure(text=b.pfad.name)
        self._aktualisieren()

    def _vergleiche(self, werte):
        """Unter jedem Feld: abweichender Wert aus Calibre/KOReader mit ← davor (sonst nichts)."""
        b = self.buch
        quellen = {"calibre": self.calibre(b) if b else {},
                   "koreader": (getattr(b, "meta_koreader", None) or {}) if b else {}}
        for feld, (__, __, vergleich) in self.zeilen.items():
            for quelle, (z, lab) in vergleich.items():
                w = quellen[quelle].get(feld, "")
                if w and not km.gleich(feld, werte.get(feld, ""), w):
                    lab.configure(text=f"{lab.text_vorne}: {w}")
                    z.pack(anchor="w", fill="x")
                else:
                    z.pack_forget()

    def _hinweise(self, werte):
        b = self.buch
        zeilen = ["⚠ " + t for __, t in km.pruefen(werte, self.definitionen(b))]
        if b.fehler:
            zeilen.insert(0, "⚠ " + b.fehler)
        if getattr(b, "meta_koreader", None):
            zeilen.append(_("KOReader has its own book information for this book (edited on the e-reader). KOReader "
                            "shows those values instead of the ones in the file; reset them there (Book information "
                            "> long-press a field) if the file should count."))
        if not b.reihe_datei[0] and b.reihe_quelle and b.reihe_neu is None:
            zeilen.append(_("The series {reihe} only comes from the {quelle} data, not from the file; ← next to "
                            "Series puts it into the form.").format(reihe=b.reihe, quelle=b.reihe_quelle))
        if b.calibre and self.calibre_an():
            zeilen.append(_("Calibre writes its own values into the book the next time it sends it to the e-reader. "
                            "Change them in Calibre as well, otherwise your changes here get lost."))
        if b.meta_entwurf is not None:
            zeilen.append(_("Changed, not yet applied (Ctrl+Enter)."))
        elif b.meta_neu is not None or b.reihe_neu is not None:
            zeilen.append(_("Applied, not yet saved (Ctrl+S)."))
        self.hinweis.configure(text="\n".join(zeilen))

    def formular_werte(self):
        """Werte aus dem Formular; Felder ohne Zeile behalten den bisherigen Stand."""
        b = self.buch
        w = self.aktuell(b) if b else {}
        for f in self.zeilen:
            w[f] = km._norm(self.var[f].get())
        return w

    # ================================================================ Bearbeiten
    def _getippt(self):
        b = self.buch
        if self._laden or not b or b.fehler:
            return
        werte = self.formular_werte()
        basis = self.basis(b)
        gleich = all(km._norm(werte.get(f, "")) == km._norm(basis.get(f, "")) for f in set(werte) | set(basis))
        b.meta_entwurf = None if gleich else werte
        self.app._geaendert(b)
        self._aktualisieren()

    def _aktualisieren(self):
        werte = self.formular_werte()
        self._vergleiche(werte)
        self._hinweise(werte)

    def von(self, quelle, feld):
        """← unter einem Feld: Wert aus Calibre bzw. KOReader ins Formular."""
        b = self.buch
        if not b:
            return
        andere = self.calibre(b) if quelle == "calibre" else (getattr(b, "meta_koreader", None) or {})
        if andere.get(feld) and feld in self.var:
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
        reihe = (km._norm(werte.get("reihe", "")), km.nummer_norm(werte.get("nummer", "")))
        datei = (b.meta.get("reihe", ""), b.meta.get("nummer", ""))
        b.reihe_neu = None if (reihe[0] == km._norm(datei[0]) and km.gleich("nummer", reihe[1], datei[1])) \
            else (reihe[0], reihe[1] if reihe[0] else "")
        rest = {f: werte[f] for f in werte if f not in REIHE}
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
        b.cover_neu, b.cover_neu_quelle = None, ""
        self.app._geaendert(b)
        self.anzeigen()
        self.app.status.set(f"{b.name}: " + _("metadata and cover restored from the file."))

    def _calibre_noetig(self):
        if not self.calibre_an():
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
        cal = self.calibre(b)
        if not cal:
            self.app.status.set(f"{b.name}: " + _("no Calibre data (metadata.calibre) for this book."))
            return
        felder = km.unterschiede(self.formular_werte(), cal, list(self.zeilen))
        for f in felder:
            self.var[f].set(cal[f])
        self.app.status.set(f"{b.name}: " + (ngettext("{n} value from Calibre in the form, not yet applied.",
                                                      "{n} values from Calibre in the form, not yet applied.",
                                                      len(felder)).format(n=len(felder))
                                              if felder else _("matches Calibre.")))

    def luecken_fuellen(self):
        """Alle Bücher: leere Felder aus Calibre füllen und übernehmen (Formular-Entwürfe bleiben unberührt)."""
        if not self._calibre_noetig():
            return
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
