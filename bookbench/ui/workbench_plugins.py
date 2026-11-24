# -*- coding: utf-8 -*-
"""
workbench_plugins.py - Unterseiten Bookends und Bookshelf der KOReader-Werkbank (seit 1.4-beta2).
Nur Oberfläche; Dateiformate und Logik in preview/plugins.py, KOReader-Steuerung in
preview/workbench.py. Die Seiten stehen in der linken Spalte des Bereichs Vorschau (Unterseiten in
der Seitenleiste), das Bild von KOReader bleibt rechts daneben.

Ablauf (für beide gleich): Änderungen sind erst ein Entwurf und wirken nur in der Werkbank
(Wegwerf-Kopie des Profils). "Ins Profil speichern" schreibt sie ins Vorschau-Profil, "Verwerfen" liest
das Profil neu. Bei jedem Neustart der Werkbank schreibt in_kopie() die Entwürfe in die neue Kopie.

  Bookends    jede Änderung nach kurzer Pause sofort im Bild (Befehl "bookends <datei>", < 0,2 s)
  Bookshelf   Änderung -> Neustart der Werkbank auf dem Startbildschirm (~1,2 s; Bookshelf kann seine
              Einstellungen im laufenden KOReader nicht neu laden)
"""
import copy
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import keller_theme as kth
from bookbench.ui import panes as kpn
from bookbench.preview import plugins as kpl
from bookbench.i18n import _

PAUSE_BOOKENDS = 350                              # ms nach der letzten Eingabe, dann ins Bild
PAUSE_BOOKSHELF = 900                             # ms, dann Neustart (länger: kostet ~1,2 s)
BREITE = 360                                      # Umbruchbreite der Hinweise


def _zahl_oder_leer(text):
    text = text.strip().replace(",", ".")
    if not text:
        return None
    w = float(text)
    return int(w) if w.is_integer() else w


class _Seite:
    """Gemeinsames: Rahmen mit Scrollbalken, Kopf, Stand-Zeile, Entwurf."""
    plugin = ""

    def __init__(self, bereich, eltern):
        self.bereich = bereich
        self.app = bereich.app
        self.rahmen = ttk.Frame(eltern)
        self.roll = kpn.RollFlaeche(self.rahmen)
        self.roll.pack(fill="both", expand=True)
        self.innen = ttk.Frame(self.roll.innen, padding=(0, 0, 10, 8))
        self.innen.pack(fill="both", expand=True)
        self.kopf = ttk.Label(self.innen, text="", style="Hinweis.TLabel", wraplength=BREITE, justify="left")
        self.kopf.pack(anchor="w", fill="x")
        self.stand = ttk.Label(self.innen, text="", wraplength=BREITE, justify="left")
        self.stand.pack(anchor="w", fill="x", pady=(2, 8))
        self.info = None                         # kpl.erkennen()[plugin]
        self._job = None

    @property
    def ko(self):
        return kpl.ko_ordner(self.bereich.profil)

    def farben(self):
        self.roll.farbe(kth.PALETTE["dunkel" if self.app.dark_mode.get() else "hell"]["bg"])

    def _planen(self, ms, fn):
        if self._job:
            self.app.after_cancel(self._job)
        self._job = self.app.after(ms, self._ausfuehren, fn)

    def _ausfuehren(self, fn):
        self._job = None
        fn()

    def ungespeichert(self):
        return False

    def zuruecksetzen(self):
        """Neues Profil: Entwurf und geladenen Stand vergessen (beim nächsten Zeigen neu lesen)."""

    def fragen_ob_verwerfen(self):
        """Vor dem Neuladen (Profil vom E-Reader usw.): True = weitermachen."""
        if not self.ungespeichert():
            return True
        a = messagebox.askyesnocancel(
            self.plugin.capitalize(),
            _("The {plugin} settings have unsaved changes. Save them in the profile first?").format(
                plugin=self.plugin.capitalize()), parent=self.app)
        if a is None:
            return False
        if a:
            self.speichern()
        return True

    def stand_zeigen(self):
        if self.ungespeichert():
            self.stand.configure(text=_("● Unsaved changes - so far only in the picture. \"Save to profile\" keeps "
                                        "them."), foreground=self.app._mark_farben()["rot"])
        else:
            self.stand.configure(text=_("Same as in the profile. Back to the e-reader: comes with 1.4-beta4 (until "
                                        "then on the e-reader itself)."), foreground="")


# ====================================================================== Bookends
class BookendsSeite(_Seite):
    plugin = kpl.BOOKENDS

    def __init__(self, bereich, eltern):
        super().__init__(bereich, eltern)
        self.datei = None                         # Dateiname der gezeigten Vorlage
        self.daten = None                         # Entwurf (dict)
        self.gespeichert = None                   # Stand im Profil (dict) bzw. None bei neuer Vorlage
        self.stand_profil = {"an": False, "aktiv": None}
        self.aktiv_neu = None                     # im Entwurf zur aktiven Vorlage gemacht
        self._namen = {}                          # Anzeigename -> Datei
        self._zeile = None                        # (pos, nr) für Stil/Größe
        self._fokus = None                        # zuletzt benutztes Textfeld (Token einfügen)
        self._laden_laeuft = False
        i = self.innen

        self.an_var = tk.BooleanVar()
        ttk.Checkbutton(i, text=_("Bookends switched on"), variable=self.an_var,
                        command=self._geaendert).pack(anchor="w")

        ttk.Label(i, text=_("Preset"), style="Ueberschrift.TLabel").pack(anchor="w", pady=(8, 0))
        self.wahl_var = tk.StringVar()
        self.wahl = ttk.Combobox(i, textvariable=self.wahl_var, state="readonly")
        self.wahl.pack(anchor="w", fill="x")
        self.wahl.bind("<<ComboboxSelected>>", lambda e: self._wahl_gewechselt())
        z = ttk.Frame(i)
        z.pack(anchor="w", fill="x", pady=(4, 0))
        for text, befehl in ((_("New"), self.neu), (_("Duplicate"), self.duplizieren), (_("Delete"), self.loeschen)):
            ttk.Button(z, text=text, command=befehl, style="Klein.TButton").pack(side="left", padx=(0, 4))
        self.aktiv_text = ttk.Label(i, text="", style="Hinweis.TLabel", wraplength=BREITE, justify="left")
        self.aktiv_text.pack(anchor="w", fill="x", pady=(4, 0))
        self.aktiv_knopf = ttk.Button(i, text=_("Make active"), command=self.aktiv_machen, style="Klein.TButton")
        self.aktiv_knopf.pack(anchor="w", pady=(2, 0))

        g = ttk.Frame(i)
        g.pack(anchor="w", fill="x", pady=(6, 0))
        g.columnconfigure(1, weight=1)
        self.name_var, self.beschr_var = tk.StringVar(), tk.StringVar()
        for r, (text, var) in enumerate(((_("Name"), self.name_var), (_("Description"), self.beschr_var))):
            ttk.Label(g, text=text).grid(row=r, column=0, sticky="w", padx=(0, 6), pady=1)
            e = ttk.Entry(g, textvariable=var)
            e.grid(row=r, column=1, sticky="we", pady=1)
            var.trace_add("write", lambda *a: self._kopf_geaendert())

        # -- Zeilen ----------------------------------------------------------------
        k = ttk.Frame(i)
        k.pack(anchor="w", fill="x", pady=(10, 0))
        ttk.Label(k, text=_("Lines"), style="Ueberschrift.TLabel").pack(side="left")
        self.token_knopf = ttk.Menubutton(k, text=_("Insert token"), style="Klein.TButton")
        self.token_knopf.pack(side="right")
        self.token_menue = tk.Menu(self.token_knopf, tearoff=False)
        self.token_knopf.configure(menu=self.token_menue)
        ttk.Label(i, text=_("One line per row; tokens like %title or %page_num are filled in by Bookends."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").pack(anchor="w", fill="x")
        self.texte = {}
        for pos, name in kpl.POSITIONEN:
            ttk.Label(i, text=_(name)).pack(anchor="w", pady=(4, 0))
            r = self.app._listenrahmen(i)
            r.pack(fill="x")
            t = tk.Text(r, height=2, width=20, wrap="none", undo=True, borderwidth=0, highlightthickness=0,
                        font=kth.schrift(10))
            t.pack(fill="x", padx=2, pady=1)
            t.bind("<<Modified>>", lambda e, p=pos: self._text_geaendert(p))
            for ev in ("<KeyRelease>", "<ButtonRelease-1>", "<FocusIn>"):
                t.bind(ev, lambda e, p=pos: self._zeile_gewaehlt(p), add="+")
            self.texte[pos] = t

        # -- aktuelle Zeile ------------------------------------------------------------
        self.zeile_kopf = ttk.Label(i, text=_("Line: click into a line above"), style="Ueberschrift.TLabel")
        self.zeile_kopf.pack(anchor="w", pady=(10, 0))
        zr = ttk.Frame(i)
        zr.pack(anchor="w", fill="x")
        ttk.Label(zr, text=_("Style")).pack(side="left")
        self.stil_var = tk.StringVar()
        self.stil = ttk.Combobox(zr, textvariable=self.stil_var, state="disabled", width=11,
                                 values=[_(t) for __, t in kpl.STILE])
        self.stil.pack(side="left", padx=(4, 10))
        self.stil.bind("<<ComboboxSelected>>", lambda e: self._zeilenwerte_uebernehmen())
        ttk.Label(zr, text=_("Size")).pack(side="left")
        self.groesse_var = tk.StringVar()
        self.groesse = ttk.Spinbox(zr, from_=4, to=80, width=5, textvariable=self.groesse_var, state="disabled",
                                   command=self._zeilenwerte_uebernehmen)
        self.groesse.pack(side="left", padx=(4, 10))
        self.groesse.bind("<KeyRelease>", lambda e: self._zeilenwerte_uebernehmen())
        self.gross_var = tk.BooleanVar()
        self.gross = ttk.Checkbutton(zr, text=_("Capitals"), variable=self.gross_var, state="disabled",
                                     command=self._zeilenwerte_uebernehmen)
        self.gross.pack(side="left")
        ttk.Label(i, text=_("Empty size = the general font size. Further line settings (font, nudging, bars in "
                            "the line) stay as they are; change them on the e-reader."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").pack(anchor="w", fill="x")

        # -- allgemein -------------------------------------------------------------------
        ttk.Label(i, text=_("General"), style="Ueberschrift.TLabel").pack(anchor="w", pady=(10, 0))
        ga = ttk.Frame(i)
        ga.pack(anchor="w", fill="x")
        self.allg_var = {}
        for r, (schl, text, vorgabe) in enumerate(kpl.ALLGEMEIN):
            ttk.Label(ga, text=_(text)).grid(row=r, column=0, sticky="w", padx=(0, 6), pady=1)
            v = self.allg_var[schl] = tk.StringVar()
            sp = ttk.Spinbox(ga, from_=0, to=400, width=6, textvariable=v, command=self._allgemein_geaendert)
            sp.grid(row=r, column=1, sticky="w", pady=1)
            sp.bind("<KeyRelease>", lambda e: self._allgemein_geaendert())
            ttk.Label(ga, text=_("empty = {wert}").format(wert=vorgabe if vorgabe is not None else
                                                          _("size of KOReader's status bar")),
                      style="Hinweis.TLabel").grid(row=r, column=2, sticky="w", padx=(6, 0))
        self.kuerzen_var = tk.StringVar(value="center")
        for wert, text in kpl.KUERZEN:
            ttk.Radiobutton(i, text=_(text), value=wert, variable=self.kuerzen_var,
                            command=self._allgemein_geaendert).pack(anchor="w")
        self.balken_text = ttk.Label(i, text="", style="Hinweis.TLabel", wraplength=BREITE, justify="left")
        self.balken_text.pack(anchor="w", fill="x", pady=(8, 0))

    def zuruecksetzen(self):
        self.datei = self.daten = self.gespeichert = None
        self.aktiv_neu = None

    # ------------------------------------------------------------------ Laden
    def neu_laden(self, datei=None):
        """Vorlagen und Stand aus dem Profil lesen; datei: diese zeigen (sonst die bisherige/aktive)."""
        self.info = kpl.erkennen(self.bereich.profil).get(kpl.BOOKENDS)
        if not self.info:
            return
        self.kopf.configure(text=_("Bookends {version} in the profile. Changes show in the picture at once.").format(
            version=self.info["version"] or "?"))
        self.stand_profil = kpl.bookends_stand(self.ko)
        self.aktiv_neu = None
        self.an_var.set(self.stand_profil["an"])
        self._tokens_fuellen()
        vl = kpl.vorlagen(self.ko)
        self._namen = {}
        for v in vl:
            name = v["name"] if v["name"] not in self._namen else f"{v['name']} ({v['datei']})"
            self._namen[name] = v["datei"]
        datei = datei or self.datei or self.stand_profil["aktiv"]
        if datei not in self._namen.values():
            datei = self.stand_profil["aktiv"] if self.stand_profil["aktiv"] in self._namen.values() else (
                vl[0]["datei"] if vl else None)
        self._vorlage_zeigen(datei)

    def _wahl_werte(self):
        werte = list(self._namen)
        if self.datei and self.datei not in self._namen.values():          # neue, noch nicht gespeicherte
            werte.append(self._anzeige(self.datei))
        self.wahl.configure(values=werte)

    def _anzeige(self, datei):
        for n, d in self._namen.items():
            if d == datei:
                return n
        return (self.daten or {}).get("name") or datei

    def _vorlage_zeigen(self, datei, daten=None):
        self.datei = datei
        if datei and daten is None:
            try:
                daten = kpl.vorlage_lesen(self.ko, datei)
                self.gespeichert = copy.deepcopy(daten)
            except (OSError, ValueError) as e:
                self.app.status.set(_("Preset {datei} could not be read: {fehler}").format(datei=datei, fehler=e))
                daten, self.gespeichert = None, None
        elif daten is not None:
            self.gespeichert = None                # neu, noch nicht im Profil
        self.daten = daten
        self._formular_fuellen()

    def _formular_fuellen(self):
        self._laden_laeuft = True
        try:
            self._wahl_werte()
            self.wahl_var.set(self._anzeige(self.datei) if self.datei else "")
            d = self.daten or {}
            self.name_var.set(d.get("name") or "")
            self.beschr_var.set(d.get("description") or "")
            for pos, t in self.texte.items():
                t.configure(state="normal")
                t.delete("1.0", "end")
                z = kpl.zeilen(d, pos)
                t.insert("1.0", "\n".join(z))
                t.configure(height=max(2, min(6, len(z) + 1)))
                t.edit_modified(False)
                t.edit_reset()
                if self.daten is None:
                    t.configure(state="disabled")
            for schl, v in self.allg_var.items():
                w = kpl.allgemein(d, schl)
                v.set("" if w is None else str(w))
            self.kuerzen_var.set(kpl.allgemein(d, "truncation_priority") or "center")
            self._zeile = None
            self._zeile_zeigen()
            balken = d.get("progress_bars") or []
            balken = balken if isinstance(balken, list) else list(balken.values())
            an = sum(1 for b in balken if isinstance(b, dict) and b.get("enabled"))
            self.balken_text.configure(text=_("Progress bars in this preset: {n} switched on. They are kept as they "
                                              "are; edit them on the e-reader for now.").format(n=an))
        finally:
            self._laden_laeuft = False
        self._aktiv_zeigen()
        self.stand_zeigen()

    def _aktiv_zeigen(self):
        aktiv = self.aktiv_neu or self.stand_profil["aktiv"]
        if not self.datei:
            text = _("No preset in the profile. \"New\" makes one.")
        elif self.datei == aktiv:
            text = _("This is the active preset (Bookends uses it on the e-reader).")
        else:
            text = _("Not active: on the e-reader Bookends uses \"{name}\". The picture shows this one.").format(
                name=self._anzeige(aktiv) if aktiv else "?")
        self.aktiv_text.configure(text=text)
        self.aktiv_knopf.configure(state="normal" if self.datei and self.datei != aktiv else "disabled")

    def _tokens_fuellen(self):
        m = self.token_menue
        m.delete(0, "end")
        gruppen = {}
        for gruppe, token, beschreibung in kpl.tokens(self.info["ordner"]) if self.info else []:
            if gruppe.lower() == "all":
                continue
            if gruppe not in gruppen:
                gruppen[gruppe] = tk.Menu(m, tearoff=False)
                m.add_cascade(label=gruppe, menu=gruppen[gruppe])
            gruppen[gruppe].add_command(label=f"{token}  -  {beschreibung}", command=lambda t=token: self._einfuegen(t))
        self.token_knopf.configure(state="normal" if gruppen else "disabled")

    # ------------------------------------------------------------------ Bearbeiten
    def ungespeichert(self):
        if self.daten is None:
            return False
        if self.gespeichert is None or self.daten != self.gespeichert:
            return True
        return self.an_var.get() != self.stand_profil["an"] or bool(self.aktiv_neu)

    def _einfuegen(self, token):
        t = self._fokus or self.texte["tc"]
        if self.daten is None:
            return
        t.insert("insert", token)
        t.focus_set()

    def _text_geaendert(self, pos):
        t = self.texte[pos]
        if not t.edit_modified():
            return
        t.edit_modified(False)
        if self._laden_laeuft or self.daten is None:
            return
        z = t.get("1.0", "end-1c").split("\n")
        while z and not z[-1].strip():
            z.pop()
        if z != kpl.zeilen(self.daten, pos):
            kpl.zeilen_setzen(self.daten, pos, z)
            t.configure(height=max(2, min(6, len(z) + 1)))
            self._zeile_gewaehlt(pos)
            self._geaendert()

    def _zeile_gewaehlt(self, pos):
        t = self.texte[pos]
        self._fokus = t
        nr = int(t.index("insert").split(".")[0])
        neu = (pos, nr) if self.daten is not None and nr <= len(kpl.zeilen(self.daten, pos)) else None
        if neu != self._zeile:
            self._zeile = neu
            self._zeile_zeigen()

    def _zeile_zeigen(self):
        self._laden_laeuft = True
        try:
            if not self._zeile:
                self.zeile_kopf.configure(text=_("Line: click into a line above"))
                for w in (self.stil, self.groesse, self.gross):
                    w.configure(state="disabled")
                self.stil_var.set("")
                self.groesse_var.set("")
                self.gross_var.set(False)
                return
            pos, nr = self._zeile
            name = dict(kpl.POSITIONEN)[pos]
            self.zeile_kopf.configure(text=_("Line: {position}, line {nr}").format(position=_(name), nr=nr))
            self.stil.configure(state="readonly")
            self.groesse.configure(state="normal")
            self.gross.configure(state="normal")
            stil = kpl.zeilenwert(self.daten, pos, "line_style", nr) or "regular"
            self.stil_var.set(_(dict(kpl.STILE).get(stil, kpl.STILE[0][1])))
            g = kpl.zeilenwert(self.daten, pos, "line_font_size", nr)
            self.groesse_var.set("" if g is None else str(g))
            self.gross_var.set(bool(kpl.zeilenwert(self.daten, pos, "line_uppercase", nr)))
        finally:
            self._laden_laeuft = False

    def _zeilenwerte_uebernehmen(self):
        if self._laden_laeuft or not self._zeile or self.daten is None:
            return
        pos, nr = self._zeile
        stil = next((k for k, t in kpl.STILE if _(t) == self.stil_var.get()), "regular")
        kpl.zeilenwert_setzen(self.daten, pos, "line_style", nr, None if stil == "regular" else stil)
        try:
            g = _zahl_oder_leer(self.groesse_var.get())
        except ValueError:
            return
        kpl.zeilenwert_setzen(self.daten, pos, "line_font_size", nr, g)
        kpl.zeilenwert_setzen(self.daten, pos, "line_uppercase", nr, True if self.gross_var.get() else None)
        self._geaendert()

    def _allgemein_geaendert(self):
        if self._laden_laeuft or self.daten is None:
            return
        for schl, v in self.allg_var.items():
            try:
                kpl.allgemein_setzen(self.daten, schl, _zahl_oder_leer(v.get()))
            except ValueError:
                return
        k = self.kuerzen_var.get()
        kpl.allgemein_setzen(self.daten, "truncation_priority", None if k == "center" and
                             kpl.allgemein(self.gespeichert or {}, "truncation_priority") is None else k)
        self._geaendert()

    def _kopf_geaendert(self):
        if self._laden_laeuft or self.daten is None:
            return
        for schl, var in (("name", self.name_var), ("description", self.beschr_var)):
            w = var.get().strip()
            if w:
                self.daten[schl] = w
            else:
                self.daten.pop(schl, None)
        self._geaendert(bild=False)

    def _geaendert(self, bild=True):
        if self._laden_laeuft:
            return
        self.stand_zeigen()
        if bild:
            self._planen(PAUSE_BOOKENDS, self.ins_bild)

    # ------------------------------------------------------------------ Werkbank
    def in_kopie(self, ko):
        """Vor dem Start der Werkbank: Entwurf in die Wegwerf-Kopie (Bookends lädt beim Start die aktive Vorlage)."""
        if self.daten is None or not self.datei:
            return
        kpl.vorlage_schreiben(ko, self.datei, self.daten)
        kpl.bookends_setzen(ko, an=self.an_var.get(), aktiv=self.datei)

    def ins_bild(self):
        """Entwurf in die laufende Werkbank: Vorlage schreiben, übernehmen lassen, neues Bild."""
        wb = self.bereich.werkbank
        if self.daten is None or not self.datei:
            return
        if self.bereich.modus_var.get() != "lesen":
            if self.bereich.unterseite() == self.plugin:  # nur von der eigenen Seite aus die Ansicht wechseln
                self.bereich.modus_setzen("lesen")        # startet neu, in_kopie() bringt den Entwurf mit
            return
        if not (wb and wb.laeuft() and wb.bereit):
            return                                        # beim nächsten Start über in_kopie()
        kpl.vorlage_schreiben(wb.ko, self.datei, self.daten)
        wb.bookends_an(self.an_var.get())
        wb.bookends(self.datei)
        wb.bild()
        self.bereich._takt_planen()

    def nach_start(self):
        """Werkbank ist bereit: nichts zu tun, in_kopie() hat den Entwurf schon hineingeschrieben."""

    def beim_zeigen(self):
        if self.daten is None:
            self.neu_laden()
        if self.bereich.modus_var.get() != "lesen":
            self.bereich.modus_setzen("lesen")

    # ------------------------------------------------------------------ Vorlagen
    def _wahl_gewechselt(self):
        datei = self._namen.get(self.wahl_var.get())
        if datei == self.datei:
            return
        if not self._verwerfen_erlaubt():
            self.wahl_var.set(self._anzeige(self.datei))
            return
        self.aktiv_neu = None
        self.an_var.set(self.stand_profil["an"])
        self._vorlage_zeigen(datei)
        self.ins_bild()

    def _verwerfen_erlaubt(self):
        if not self.ungespeichert():
            return True
        a = messagebox.askyesnocancel(_("Bookends"), _("The preset \"{name}\" has unsaved changes. Save them in the "
                                                       "profile?").format(name=self._anzeige(self.datei)),
                                      parent=self.app)
        if a is None:
            return False
        if a:
            self.speichern()
        return True

    def neu(self, vorlage=None):
        if not self.info or not self._verwerfen_erlaubt():
            return
        name = simpledialog.askstring(_("New preset"), _("Name of the new preset:"), parent=self.app,
                                      initialvalue=(vorlage or {}).get("name", "") and
                                      _("{name} (copy)").format(name=vorlage["name"]))
        if not name or not name.strip():
            return
        daten = copy.deepcopy(vorlage) if vorlage else kpl.leere_vorlage(name.strip())
        daten["name"] = name.strip()
        datei = kpl.dateiname(self.ko, name.strip())
        self._vorlage_zeigen(datei, daten)
        self.stand_zeigen()
        self.ins_bild()

    def duplizieren(self):
        if self.daten is not None:
            self.neu(self.daten)

    def loeschen(self):
        if not self.datei:
            return
        if self.gespeichert is None:                      # nur Entwurf: einfach weg
            self.datei = self.daten = None
            self.neu_laden()
            self.ins_bild()
            return
        if not messagebox.askyesno(_("Bookends"), _("Delete the preset \"{name}\" from the profile?").format(
                name=self._anzeige(self.datei)), parent=self.app):
            return
        try:
            (kpl.vorlagen_ordner(self.ko) / self.datei).unlink()
        except OSError as e:
            self.app.status.set(str(e))
            return
        if self.stand_profil["aktiv"] == self.datei:
            rest = kpl.vorlagen(self.ko)
            kpl.einstellungen_schreiben(kpl.bookends_datei(self.ko), {
                "active_preset_filename": rest[0]["datei"] if rest else None,
                "manual_active_preset_filename": rest[0]["datei"] if rest else None})
        kpl._profil_geaendert(self.bereich.profil, "bookends")
        self.app.status.set(_("Preset deleted from the profile."))
        self.datei = self.daten = None
        self.neu_laden()
        self.bereich.werkbank_starten(still=True)

    def aktiv_machen(self):
        if self.datei:
            self.aktiv_neu = self.datei
            self._aktiv_zeigen()
            self.stand_zeigen()

    # ------------------------------------------------------------------ Speichern
    def speichern(self):
        if self.daten is None or not self.datei:
            return False
        kpl.vorlage_schreiben(self.ko, self.datei, self.daten)
        kpl.bookends_setzen(self.ko, an=self.an_var.get(), aktiv=self.aktiv_neu)
        kpl._profil_geaendert(self.bereich.profil, "bookends")
        self.app.status.set(_("Bookends preset \"{name}\" saved in the profile.").format(name=self._anzeige(self.datei)))
        self.neu_laden(self.datei)
        return True

    def verwerfen(self):
        if self.ungespeichert() and not messagebox.askyesno(
                _("Bookends"), _("Discard the unsaved changes?"), parent=self.app):
            return
        datei = self.datei if self.gespeichert is not None else None
        self.datei = self.daten = None
        self.neu_laden(datei)
        self.ins_bild()


# ====================================================================== Bookshelf
class BookshelfSeite(_Seite):
    plugin = kpl.BOOKSHELF

    def __init__(self, bereich, eltern):
        super().__init__(bereich, eltern)
        self.datei_werte = None                   # settings.lua im Profil (dict), None = nicht geladen
        self.aenderungen = {}                     # Entwurf: Schlüssel -> Wert (None = löschen)
        self._laden_laeuft = False
        self.var = {}
        i = self.innen
        ttk.Label(i, text=_("Bookshelf has no way to reload its settings while running: after a change the "
                            "workbench restarts on the start screen (about a second)."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").pack(anchor="w", fill="x")
        for gruppe, gtext in kpl.BOOKSHELF_GRUPPEN:
            ttk.Label(i, text=_(gtext), style="Ueberschrift.TLabel").pack(anchor="w", pady=(10, 0))
            f = ttk.Frame(i)
            f.pack(anchor="w", fill="x")
            f.columnconfigure(1, weight=1)
            r = 0
            for schl, g, text, art, vorgabe, wahl in kpl.BOOKSHELF_WERTE:
                if g != gruppe:
                    continue
                if art == "an":
                    v = self.var[schl] = tk.BooleanVar()
                    ttk.Checkbutton(f, text=_(text), variable=v,
                                    command=lambda s=schl: self._wert_geaendert(s)).grid(row=r, column=0, columnspan=2,
                                                                                         sticky="w", pady=1)
                elif art == "zahl":
                    ttk.Label(f, text=_(text)).grid(row=r, column=0, sticky="w", padx=(0, 6), pady=1)
                    v = self.var[schl] = tk.StringVar()
                    sp = ttk.Spinbox(f, from_=0, to=400, width=6, textvariable=v,
                                     command=lambda s=schl: self._wert_geaendert(s))
                    sp.grid(row=r, column=1, sticky="w", pady=1)
                    sp.bind("<KeyRelease>", lambda e, s=schl: self._wert_geaendert(s))
                else:
                    ttk.Label(f, text=_(text)).grid(row=r, column=0, sticky="w", padx=(0, 6), pady=1)
                    v = self.var[schl] = tk.StringVar()
                    cb = ttk.Combobox(f, textvariable=v, state="readonly", width=16, values=[_(t) for __, t in wahl])
                    cb.grid(row=r, column=1, sticky="w", pady=1)
                    cb.bind("<<ComboboxSelected>>", lambda e, s=schl: self._wert_geaendert(s))
                r += 1

        # -- alle Schlüssel ---------------------------------------------------------------
        ttk.Label(i, text=_("All keys in the file"), style="Ueberschrift.TLabel").pack(anchor="w", pady=(12, 0))
        ttk.Label(i, text=_("For everything not listed above. Double-click a simple value to change it; tables "
                            "(shelves, modules, colours) can only be changed in Bookshelf itself. \"Default\" removes "
                            "the key, then Bookshelf's default applies."),
                  style="Hinweis.TLabel", wraplength=BREITE, justify="left").pack(anchor="w", fill="x")
        r = self.app._listenrahmen(i)
        r.pack(fill="x", pady=(4, 0))
        self.baum = ttk.Treeview(r, columns=("wert",), height=10, selectmode="browse")
        self.baum.heading("#0", text=_("Key"))
        self.baum.heading("wert", text=_("Value"))
        self.baum.column("#0", width=180, stretch=True)
        self.baum.column("wert", width=140, stretch=True)
        sb = ttk.Scrollbar(r, orient="vertical", command=self.baum.yview)
        self.baum.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.baum.pack(side="left", fill="x", expand=True)
        self.baum.bind("<Double-Button-1>", lambda e: self.schluessel_bearbeiten())
        z = ttk.Frame(i)
        z.pack(anchor="w", pady=(4, 0))
        ttk.Button(z, text=_("Change …"), style="Klein.TButton",
                   command=self.schluessel_bearbeiten).pack(side="left", padx=(0, 4))
        ttk.Button(z, text=_("Default"), style="Klein.TButton", command=self.schluessel_loeschen).pack(side="left")

    def zuruecksetzen(self):
        self.datei_werte, self.aenderungen = None, {}

    # ------------------------------------------------------------------ Werte
    def _wert(self, schl, vorgabe=None):
        if schl in self.aenderungen:
            w = self.aenderungen[schl]
            return vorgabe if w is None else w
        return (self.datei_werte or {}).get(schl, vorgabe)

    def neu_laden(self):
        self.info = kpl.erkennen(self.bereich.profil).get(kpl.BOOKSHELF)
        if not self.info:
            return
        self.kopf.configure(text=_("Bookshelf {version} in the profile ({datei}).").format(
            version=self.info["version"] or "?", datei=kpl.bookshelf_datei(self.ko).relative_to(self.ko)))
        self.datei_werte = kpl.bookshelf_lesen(self.ko)
        self.aenderungen = {}
        self._formular_fuellen()

    def _formular_fuellen(self):
        self._laden_laeuft = True
        try:
            for schl, __, __, art, vorgabe, wahl in kpl.BOOKSHELF_WERTE:
                w = self._wert(schl, vorgabe)
                if art == "an":
                    self.var[schl].set(bool(w))
                elif art == "zahl":
                    self.var[schl].set("" if w is None else str(w))
                else:
                    self.var[schl].set(_(dict(wahl).get(w, dict(wahl)[vorgabe])))
            self.baum.delete(*self.baum.get_children())
            alle = dict(self.datei_werte or {})
            alle.update({k: v for k, v in self.aenderungen.items()})
            for k in sorted(alle):
                if k in kpl.BOOKSHELF_INTERN or alle[k] is None:
                    continue
                self.baum.insert("", "end", iid=k, text=("● " if k in self.aenderungen else "") + k,
                                 values=(kpl.wert_text(alle[k]),))
        finally:
            self._laden_laeuft = False
        self.stand_zeigen()

    def _wert_geaendert(self, schl):
        if self._laden_laeuft or self.datei_werte is None:
            return
        __, __, __, art, vorgabe, wahl = next(x for x in kpl.BOOKSHELF_WERTE if x[0] == schl)
        v = self.var[schl].get()
        if art == "an":
            w = bool(v)
        elif art == "zahl":
            try:
                w = _zahl_oder_leer(v)
            except ValueError:
                return
        else:
            w = next((k for k, t in wahl if _(t) == v), vorgabe)
        self._setzen(schl, w, vorgabe)

    def _setzen(self, schl, w, vorgabe=None):
        im_profil = (self.datei_werte or {}).get(schl)
        if w == im_profil or (w is None and im_profil is None) or (w == vorgabe and im_profil is None):
            self.aenderungen.pop(schl, None)
        else:
            self.aenderungen[schl] = w
        self._formular_fuellen()
        self._planen(PAUSE_BOOKSHELF, self.ins_bild)

    def schluessel_bearbeiten(self):
        sel = self.baum.selection()
        if not sel:
            return
        schl = sel[0]
        alt = self._wert(schl)
        if isinstance(alt, (dict, list)) or alt is None:
            self.app.status.set(_("{schluessel} is a table: change it in Bookshelf itself.").format(schluessel=schl))
            return
        text = simpledialog.askstring(_("Bookshelf"), _("New value for {schluessel}:").format(schluessel=schl),
                                      initialvalue=kpl.wert_text(alt) if not isinstance(alt, bool) else
                                      ("true" if alt else "false"), parent=self.app)
        if text is None:
            return
        try:
            w = kpl.wert_aus_text(text, alt)
        except ValueError:
            self.app.status.set(_("\"{text}\" does not fit the value ({art}).").format(text=text,
                                                                                         art=type(alt).__name__))
            return
        self._setzen(schl, w)

    def schluessel_loeschen(self):
        sel = self.baum.selection()
        if sel:
            self._setzen(sel[0], None)

    def ungespeichert(self):
        return bool(self.aenderungen)

    # ------------------------------------------------------------------ Werkbank
    def in_kopie(self, ko):
        if self.aenderungen:
            kpl.bookshelf_schreiben(ko, self.aenderungen)

    def ins_bild(self):
        """Bookshelf kann nicht neu laden: Werkbank neu starten (Startbildschirm), in_kopie() bringt den Entwurf mit."""
        if self.bereich.unterseite() != self.plugin:
            return
        if self.bereich.modus_var.get() != "bibliothek":
            self.bereich.modus_setzen("bibliothek")
        else:
            self.bereich.werkbank_starten(still=True)

    def nach_start(self):
        pass

    def beim_zeigen(self):
        if self.datei_werte is None:
            self.neu_laden()
        if self.bereich.modus_var.get() != "bibliothek":
            self.bereich.modus_setzen("bibliothek")

    def speichern(self):
        if not self.aenderungen:
            return False
        kpl.bookshelf_schreiben(self.ko, self.aenderungen)
        kpl._profil_geaendert(self.bereich.profil, "bookshelf")
        self.app.status.set(_("Bookshelf settings saved in the profile ({n} changed).").format(n=len(self.aenderungen)))
        self.neu_laden()
        return True

    def verwerfen(self):
        if not self.aenderungen:
            return
        if not messagebox.askyesno(_("Bookshelf"), _("Discard the unsaved changes?"), parent=self.app):
            return
        self.neu_laden()
        self.ins_bild()
