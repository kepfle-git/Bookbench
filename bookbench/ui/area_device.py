# -*- coding: utf-8 -*-
"""
area_device.py - Bereich "E-Reader" (Kennung "kobo") von Bookbench: angeschlossenen
E-Reader (Kobo, Kindle, PocketBook) anzeigen, KOReader-Einstellungen sichern und
zurückspielen, Wörterbücher kopieren, auswerfen. Die Logik steckt in device/device.py,
hier nur die Oberfläche.

  Kopf          Modell, Laufwerk, Firmware, KOReader-Version, freier Platz
  Sicherungen   Liste der Sicherungen links, Teile (Häkchen) rechts
  Wörterbücher  Quelle auf dem Rechner, Stand je Wörterbuch auf dem Gerät

Das Gerät wird alle drei Sekunden gesucht (Hilfsthread), damit Anstecken und
Abziehen ohne Knopfdruck erkannt werden. Langsames (Sichern, Zurückspielen,
Kopieren, Auswerfen) läuft über app.hintergrund().
"""
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import keller_theme as kth
from bookbench.device import device as kg
from bookbench.device import models as km
from bookbench.i18n import N_, _, ngettext

KURZ = {"einstellungen": _("Settings"), "settings": _("Statistics/plugins"), "buchdaten": _("Book data"),
        "anpassungen": _("Tweaks"), "kobo": _("Kobo settings")}
# Kennungen aus device.woerterbuecher (Namen aus der Zeit, als es nur Kobos gab)
STAND_TEXT = {"aktuell": _("up to date"), "veraltet": _("outdated on the e-reader"),
              "fehlt": _("missing on the e-reader"), "nur auf dem Kobo": _("only on the e-reader"), "kein Kobo": "-"}
BEREICH = N_("E-reader")
# Anlass einer Sicherung (steht in der ZIP); "vor dem Zurückspielen" schrieben Versionen bis 0.16
ANLASS = {"vor_zurueckspielen": _("before restoring"), "vor dem Zurückspielen": _("before restoring")}


def _datum(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return iso or "?"


class KoboBereich:
    def __init__(self, app):
        self.app = app
        self.wurzeln, self.wurzel, self.info = [], None, {}
        self.vorhanden = {}                      # Teil -> Dateien auf dem Gerät
        self.geschrieben = False                 # in dieser Sitzung etwas aufs Gerät geschrieben
        self._suche_laeuft = False
        self._sicherungen = {}                   # iid -> Inhaltsverzeichnis
        self._dicts = []
        self._quellen = (None, 0.0, [])          # (Quelle, Zeitpunkt, Wörterbuch-Ordner) - Suche kann dauern
        s = self.seite = app._seite(_(BEREICH), "kobo")

        # -- Kopf -------------------------------------------------------------
        kopf = ttk.Frame(s)
        kopf.pack(fill="x")
        self.titel = ttk.Label(kopf, text=_("No e-reader connected."), font=kth.schrift(12, fett=True))
        self.titel.pack(side="left", anchor="w")
        self.wahl_var = tk.StringVar()
        self.wahl = ttk.Combobox(kopf, textvariable=self.wahl_var, state="readonly", width=30)
        self.wahl.bind("<<ComboboxSelected>>", lambda e: self._gewaehlt(Path(self.wahl_var.get())))
        self.zeile = ttk.Label(s, text="", style="Hinweis.TLabel")
        self.zeile.pack(anchor="w", pady=(2, 10))

        # -- Wörterbücher (unten; zuerst eingepackt, damit sie nicht verdrängt werden)
        unten = ttk.Frame(s)
        unten.pack(side="bottom", fill="x")
        ttk.Label(unten, text=_("Dictionaries: computer → e-reader"), style="Ueberschrift.TLabel").pack(
            anchor="w", pady=(12, 0))
        q = ttk.Frame(unten)
        q.pack(fill="x", pady=(0, 4))
        self.quelle_label = ttk.Label(q, text="", style="Hinweis.TLabel")
        self.quelle_label.pack(side="left")
        ttk.Button(q, text=_("Choose source …"), command=self.quelle_waehlen).pack(side="right")
        r2 = app._listenrahmen(unten)
        r2.pack(fill="x")
        d = self.dict_baum = ttk.Treeview(r2, columns=("name", "stand", "ordner"), show="headings",
                                          selectmode="extended", height=4)
        d.heading("name", text=_("Dictionary"), anchor="w")
        d.heading("stand", text=_("On the e-reader"), anchor="w")
        d.heading("ordner", text=_("Folder in the source"), anchor="w")
        d.column("name", width=200, stretch=True)
        d.column("stand", width=170, stretch=False)
        d.column("ordner", width=300, stretch=True)
        sb2 = ttk.Scrollbar(r2, orient="vertical", command=d.yview)
        d.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y")
        d.pack(side="left", fill="both", expand=True)
        d.bind("<Double-1>", lambda e: self.woerterbuch_kopieren())

        # -- Sicherungen --------------------------------------------------------
        ttk.Label(s, text=_("Backups of the KOReader settings"), style="Ueberschrift.TLabel").pack(anchor="w")
        self.ordner_label = ttk.Label(s, text="", style="Hinweis.TLabel")
        self.ordner_label.pack(anchor="w", pady=(0, 4))
        mitte = ttk.Frame(s)
        mitte.pack(fill="both", expand=True)
        links = ttk.Frame(mitte)
        links.pack(side="left", fill="both", expand=True)
        r = app._listenrahmen(links)
        r.pack(fill="both", expand=True)
        b = self.baum = ttk.Treeview(r, columns=("datum", "geraet", "anlass", "inhalt", "groesse"), show="headings",
                                     selectmode="browse", height=7)
        # Summe wie vor der Spalte Gerät (620), sonst wird die Spalte Teile rechts zu schmal;
        # Datum und Gerät (Kobo Libra Colour) sollen ganz zu sehen sein
        for c, t, w, dehnen in (("datum", _("Date"), 122, False), ("geraet", _("Device"), 132, False),
                                ("anlass", _("Reason"), 110, False), ("inhalt", _("Contents"), 186, True),
                                ("groesse", _("Size"), 70, False)):
            b.heading(c, text=t, anchor="w")
            b.column(c, width=w, stretch=dehnen, anchor="e" if c == "groesse" else "w")
        sb = ttk.Scrollbar(r, orient="vertical", command=b.yview)
        b.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        b.pack(side="left", fill="both", expand=True)
        b.bind("<<TreeviewSelect>>", lambda e: self._sicherung_gewaehlt())
        b.bind("<Double-1>", lambda e: self.zurueckspielen())

        rechts = ttk.Frame(mitte, padding=(14, 0, 0, 0))
        rechts.pack(side="left", fill="y")
        ttk.Label(rechts, text=_("Parts (for backing up and restoring)")).pack(anchor="w", pady=(0, 4))
        self.teil_var, self.teil_info, self.teil_knopf = {}, {}, {}
        gewaehlt = set(app.e.get("kobo_teile") or [])
        for k, name, beschreibung, __, __ in kg.TEILE:
            v = self.teil_var[k] = tk.BooleanVar(value=k in gewaehlt)
            self.teil_knopf[k] = ttk.Checkbutton(rechts, text=name, variable=v, command=self._teile_merken)
            self.teil_knopf[k].pack(anchor="w")
            ttk.Label(rechts, text=beschreibung, style="Hinweis.TLabel", wraplength=360,
                      justify="left").pack(anchor="w", padx=(22, 0))
            self.teil_info[k] = ttk.Label(rechts, text="", style="Hinweis.TLabel")
            self.teil_info[k].pack(anchor="w", padx=(22, 0), pady=(0, 6))

        self.anzeigen()
        app.after(200, self._regelmaessig)

    # ================================================================ Werkzeugleiste
    def werkzeug(self, eltern):
        a = self.app
        a._wz_knopf(eltern, "oeffnen", _("Books"), self.buecher_oeffnen,
                    _("Open the books on the e-reader in Library, Chapters and Blurbs"))
        ttk.Separator(eltern, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
        a._wz_knopf(eltern, "sichern", _("Back up"), self.sichern,
                    _("Back up the chosen parts of the KOReader settings into a ZIP file"))
        a._wz_knopf(eltern, "zurueckschreiben", _("Restore"), self.zurueckspielen,
                    _("Write the chosen parts from the selected backup to the e-reader (double-click)"))
        ttk.Separator(eltern, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
        a._wz_knopf(eltern, "woerterbuch", _("Dictionary"), self.woerterbuch_kopieren,
                    _("Selected dictionaries (otherwise all that are not up to date) to data/dict in the KOReader "
                      "folder"))
        ttk.Separator(eltern, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
        a._wz_knopf(eltern, "auswerfen", _("Eject"), self.auswerfen,
                    _("Unmount the e-reader; then the cable can come off"))

    # ================================================================ Suchen
    def _regelmaessig(self):
        self.suchen(still=True)
        self.app.after(max(1, int(self.app.e.get("kobo_suche_sekunden") or 3)) * 1000, self._regelmaessig)

    def suchen(self, still=True):
        if self._suche_laeuft:
            return
        self._suche_laeuft = True
        zusaetzlich = [self.app.ordner] if self.app.ordner else []

        def arbeit():
            try:
                gefunden = kg.geraete_finden(zusaetzlich)
            except Exception:                              # nie den Takt abreißen lassen
                gefunden = []
            self.app._q.put(("rueckruf", lambda: self._gefunden(gefunden, still)))
        threading.Thread(target=arbeit, daemon=True).start()

    def _gefunden(self, gefunden, still):
        self._suche_laeuft = False
        if gefunden == self.wurzeln and self.wurzel in gefunden + [None]:
            if not still:
                self.app.status.set(f"{self.info.get('artname') or 'Kobo'}: {self.wurzel}" if self.wurzel
                                    else _("No e-reader found."))
            if not still and self.wurzel:
                self._gewaehlt(self.wurzel)                # Angaben auffrischen
            return
        vorher = self.wurzel
        self.wurzeln = gefunden
        self.wurzel = vorher if vorher in gefunden else (gefunden[0] if gefunden else None)
        if self.wurzel is None:
            self.info, self.vorhanden = {}, {}
            self.anzeigen()
            if vorher:
                self.app.status.set(_("E-reader no longer connected."))
            return
        self._gewaehlt(self.wurzel)
        if self.wurzel != vorher:
            self.app.status.set(_("{modell} connected: {ordner}").format(modell=self.info.get("modell", "?"),
                                                                         ordner=self.wurzel))

    def _gewaehlt(self, wurzel):
        self.wurzel = wurzel
        self.info = kg.geraet_info(wurzel)
        self.anzeigen()

        def arbeit():
            try:
                vorhanden = kg.teile_ermitteln(wurzel)
            except OSError:
                vorhanden = {}
            groessen = {k: kg.summe(wurzel, v) for k, v in vorhanden.items()}
            self.app._q.put(("rueckruf", lambda: self._teile(wurzel, vorhanden, groessen)))
        threading.Thread(target=arbeit, daemon=True).start()

    def _teile(self, wurzel, vorhanden, groessen):
        if wurzel != self.wurzel:
            return
        self.vorhanden = vorhanden
        art = self.info.get("art") or kg.STANDARD_ART
        for k, lab in self.teil_info.items():
            moeglich = kg.NUR_BEI.get(k, art) == art
            self.teil_knopf[k].state(["!disabled"] if moeglich else ["disabled"])
            if not moeglich:
                lab.configure(text=_("not on a {geraet}").format(geraet=kg.art_name(art)))
            elif k in vorhanden:
                n = len(vorhanden[k])
                lab.configure(text=ngettext("on the e-reader: {n} file, {groesse}",
                                            "on the e-reader: {n} files, {groesse}", n)
                              .format(n=n, groesse=kg.groesse_text(groessen[k])))
            else:
                lab.configure(text=_("not on the e-reader"))

    # ================================================================ Anzeige
    def sicherungsordner(self):
        return Path(self.app.e["sicherungsordner"]) / "KOReader"

    def anzeigen(self):
        i = self.info
        if self.wurzel:
            self.titel.configure(text=i.get("modell") or i.get("artname") or "?")
            teile = [str(self.wurzel)]
            if i.get("art", "kobo") != "kobo":
                teile.append(_("KOReader folder {ordner}").format(ordner=kg.ko_ordner(i["art"])))
            if i.get("modellnummer") and not km.modell(i["modellnummer"]):
                teile.append(_("model number {nr} unknown").format(nr=i["modellnummer"]))
            if i.get("firmware"):
                teile.append(f"Firmware {i['firmware']}")
            teile.append(f"KOReader {i['koreader']}" if i.get("koreader") else _("KOReader not installed"))
            if i.get("frei") is not None:
                teile.append(_("{frei} of {gesamt} free").format(frei=kg.groesse_text(i["frei"]),
                                                               gesamt=kg.groesse_text(i["gesamt"])))
            self.zeile.configure(text="  ·  ".join(teile))
        else:
            self.titel.configure(text=_("No e-reader connected."))
            self.zeile.configure(text=_("Connect the Kobo, Kindle or PocketBook by USB and confirm the connection "
                                        "on the device (KOReader: USB mass storage). It is detected automatically."))
            for k, lab in self.teil_info.items():
                lab.configure(text="")
                self.teil_knopf[k].state(["!disabled"])
        if len(self.wurzeln) > 1:
            self.wahl.configure(values=[str(w) for w in self.wurzeln])
            self.wahl_var.set(str(self.wurzel))
            self.wahl.pack(side="left", padx=12)
        else:
            self.wahl.pack_forget()
        self.ordner_label.configure(text=_("Folder: {ordner}").format(ordner=self.sicherungsordner()))
        self._sicherungen_fuellen()
        self._woerterbuecher_fuellen()

    def _sicherungen_fuellen(self):
        b = self.baum
        alt = b.selection()
        b.delete(*b.get_children())
        self._sicherungen = {}
        for s in kg.sicherungen(self.sicherungsordner()):
            iid = s["pfad"]
            self._sicherungen[iid] = s
            inhalt = ", ".join(KURZ.get(k, k) for k in s.get("teile", {}))
            try:
                groesse = kg.groesse_text(Path(iid).stat().st_size)
            except OSError:
                groesse = "?"
            anlass = s.get("anlass") or ""
            geraet = (s.get("geraet") or {}).get("modell") or kg.art_name(s.get("art"))
            b.insert("", "end", iid=iid, values=(_datum(s.get("datum")), geraet, ANLASS.get(anlass, anlass), inhalt,
                                                 groesse))
        if alt and b.exists(alt[0]):
            b.selection_set(alt[0])

    def _woerterbuch_quelle(self):
        return self.app.e.get("woerterbuch_quelle") or ""

    def _woerterbuecher_fuellen(self):
        d = self.dict_baum
        alt = set(d.selection())
        d.delete(*d.get_children())
        quelle = self._woerterbuch_quelle()
        self.quelle_label.configure(text=_("Source on this computer: {quelle}").format(quelle=quelle) if quelle else
                                    _("Source on this computer: not chosen yet (folder with the dictionary, e.g. "
                                      "My-Dictionary, or a folder with several)"))
        self._dicts = kg.woerterbuecher(quelle, self.wurzel, self._woerterbuch_ordner(quelle))
        for name, stand, ordner in self._dicts:
            tags = ("warn",) if stand in ("veraltet", "fehlt") else ()
            try:
                rel = str(Path(ordner).relative_to(quelle)) if ordner else ""
            except ValueError:
                rel = str(ordner)
            d.insert("", "end", iid=name, values=(name, STAND_TEXT.get(stand, stand), "" if rel == "." else rel),
                     tags=tags)
            if name in alt:
                d.selection_add(name)
        self.zaehler()

    def _woerterbuch_ordner(self, quelle, neu=False):
        """Wörterbuch-Ordner der Quelle; die Suche läuft höchstens alle 10 s neu."""
        q, zeit, ordner = self._quellen
        if neu or q != quelle or time.time() - zeit > 10:
            ordner = kg.woerterbuch_quellen(quelle)
            self._quellen = (quelle, time.time(), ordner)
        return ordner

    def zaehler(self):
        offen = sum(1 for __, st, __ in self._dicts if st in ("veraltet", "fehlt")) if self.wurzel else 0
        # Seitenleiste: Zähler rechtsbündig in schmaler Spalte - "(angeschlossen)" lief in den Namen
        text = f"{_(BEREICH)} ({offen} ⚠)" if offen else (f"{_(BEREICH)} (✓)" if self.wurzel else _(BEREICH))
        self.app.nb.tab(self.seite, text=text)

    def farben(self, modus, warnfarbe):
        self.dict_baum.tag_configure("warn", background=warnfarbe[modus])

    def _sicherung_gewaehlt(self):
        sel = self.baum.selection()
        s = self._sicherungen.get(sel[0]) if sel else None
        if not s:
            return
        g = s.get("geraet") or {}
        teile = [f"{KURZ.get(k, k)} ({t.get('dateien', 0)})" for k, t in s.get("teile", {}).items()]
        text = _("Backup of {datum}:").format(datum=_datum(s.get("datum"))) + " " + ", ".join(teile)
        if g.get("seriennummer"):
            text += f"  ·  {g.get('modell', 'Kobo')} {g['seriennummer']}"
        elif s.get("art") and s["art"] != "kobo":
            text += f"  ·  {g.get('modell') or kg.art_name(s['art'])}"
            if self.info.get("seriennummer") and g["seriennummer"] != self.info["seriennummer"]:
                text += " - " + _("a different device than the connected one")
        if g.get("koreader"):
            text += f", KOReader {g['koreader']}"
        self.app.status.set(text)

    def _teile_merken(self):
        self.app.e["kobo_teile"] = [k for k, v in self.teil_var.items() if v.get()]

    def _gewaehlte_teile(self):
        return [k for k, v in self.teil_var.items() if v.get()]

    # ================================================================ Aktionen
    def _bereit(self):
        if self.app._arbeit:
            self.app.status.set(_("Still running: {arbeit}.").format(arbeit=self.app._arbeit))
            return False
        if not self.wurzel or not self.wurzel.exists():
            self.app.status.set(_("No e-reader connected."))
            return False
        return True

    def buecher_oeffnen(self):
        if self._bereit() and self.app._aenderungen_verwerfen_ok():
            self.app.laden(self.wurzel)
            self.app.nb.select(self.app.seite_bibliothek)

    def sichern(self):
        if not self._bereit():
            return
        teile = [k for k in self._gewaehlte_teile() if k in self.vorhanden]
        if not teile:
            self.app.status.set(_("None of the chosen parts exist on the e-reader - nothing to back up."))
            return
        wurzel, info, ziel = self.wurzel, dict(self.info), self.sicherungsordner()
        anzahl = int(self.app.e["kobo_sicherungen_anzahl"])

        def arbeit():
            p = kg.sichern(wurzel, ziel, teile, info, anzahl)
            return _("Backed up: {name} ({groesse}).").format(name=p.name, groesse=kg.groesse_text(p.stat().st_size))
        self.app.hintergrund(_("Back up"), arbeit, nachher=self.anzeigen)

    def zurueckspielen(self):
        if not self._bereit():
            return
        sel = self.baum.selection()
        s = self._sicherungen.get(sel[0]) if sel else None
        if not s:
            self.app.status.set(_("Select a backup in the list."))
            return
        ziel_art = self.info.get("art") or kg.STANDARD_ART
        quell_art = s.get("art") or kg.STANDARD_ART
        teile = [k for k in self._gewaehlte_teile() if k in s.get("teile", {})
                 and kg.NUR_BEI.get(k, ziel_art) == ziel_art]
        if not teile:
            self.app.status.set(_("The selected backup contains none of the chosen parts."))
            return
        g = s.get("geraet") or {}
        anderes = (g.get("seriennummer") and self.info.get("seriennummer")
                   and g["seriennummer"] != self.info["seriennummer"])
        hinweis = ""
        if quell_art != ziel_art:
            hinweis = "\n\n" + _("The backup comes from a {quelle}, the connected device is a {ziel}. The KOReader "
                                  "folder is written to {ordner}. Folders stored in the settings (home folder, "
                                  "last book) still point to the {quelle}; KOReader asks for them again if "
                                  "needed.").format(quelle=kg.art_name(quell_art), ziel=kg.art_name(ziel_art),
                                                    ordner=kg.ko_ordner(ziel_art))
        elif anderes:
            hinweis = "\n\n" + _("The backup comes from a different device.")
        if not messagebox.askyesno(
                _("Restore"),
                _("Write from the backup of {datum} to the e-reader:").format(datum=_datum(s.get("datum"))) + "\n\n"
                + "\n".join(f"- {kg.TEIL_NAME[k]}" for k in teile) + hinweis
                + "\n\n" + _("Files with the same name on the e-reader are overwritten, others stay. "
                              "The current state is backed up first."), parent=self.app):
            return
        wurzel, info, ziel, pfad = self.wurzel, dict(self.info), self.sicherungsordner(), s["pfad"]
        anzahl = int(self.app.e["kobo_sicherungen_anzahl"])
        vorhanden = [k for k in teile if k in self.vorhanden]

        def arbeit():
            if vorhanden:
                # +1: die gerade angelegte Sicherung darf die zurückgespielte nicht verdrängen
                kg.sichern(wurzel, ziel, vorhanden, info, anzahl + 1, anlass="vor_zurueckspielen")
            n = kg.zurueckspielen(pfad, wurzel, teile)
            return ngettext("{n} file restored. KOReader reads it at the next start (after ejecting).",
                            "{n} files restored. KOReader reads them at the next start (after ejecting).", n).format(n=n)
        self.geschrieben = True
        self.app.hintergrund(_("Restore"), arbeit, nachher=lambda: self._gewaehlt(self.wurzel))

    def quelle_waehlen(self):
        o = filedialog.askdirectory(parent=self.app, title=_("Choose the dictionary folder"),
                                    initialdir=self._woerterbuch_quelle() or str(Path.home()))
        if not o:
            return
        self.app.e["woerterbuch_quelle"] = o
        self._woerterbuecher_fuellen()
        if not self._woerterbuch_ordner(o):
            self.app.status.set(_("There is no dictionary in this folder (no .ifo file, not even up to {n} levels "
                                  "deeper).").format(n=kg.SUCHTIEFE))
        else:
            self.app.status.set(ngettext("{n} dictionary found.", "{n} dictionaries found.", len(self._dicts))
                                .format(n=len(self._dicts)))

    def woerterbuch_kopieren(self):
        if not self._bereit():
            return
        quellen = {q.name: q for q in self._woerterbuch_ordner(self._woerterbuch_quelle(), neu=True)}
        if not quellen:
            self.app.status.set(_("Choose the source first (folder with the dictionary)."))
            return
        sel = [n for n in self.dict_baum.selection() if n in quellen]
        if not sel:
            sel = [n for n, st, __ in self._dicts if n in quellen and st != "aktuell"]
        if not sel:
            self.app.status.set(_("All dictionaries on the e-reader are up to date."))
            return
        wurzel = self.wurzel
        ziele = [quellen[n] for n in sel]

        def arbeit():
            n = sum(kg.woerterbuch_kopieren(q, wurzel) for q in ziele)
            return (ngettext("Dictionary copied: {namen} ({n} file).", "Dictionary copied: {namen} ({n} files).", n)
                    .format(namen=", ".join(q.name for q in ziele), n=n) + " " +
                    _("In KOReader it appears under the dictionary settings after a restart."))
        self.geschrieben = True
        self.app.hintergrund(_("Copying dictionary"), arbeit, nachher=self._woerterbuecher_fuellen)

    def auswerfen(self):
        if not self._bereit():
            return
        a = self.app
        offen = sum(1 for b in a.buecher if b.stand() in ("rot", "gelb"))
        auf_geraet = a.ordner and Path(a.ordner).resolve().is_relative_to(Path(self.wurzel).resolve())
        if offen and auf_geraet and not messagebox.askyesno(
                _("Eject"), ngettext("{n} book on the e-reader has unsaved changes. After ejecting it can no longer "
                                     "be saved. Eject anyway?",
                                     "{n} books on the e-reader have unsaved changes. After ejecting they can no "
                                     "longer be saved. Eject anyway?", offen).format(n=offen), parent=a):
            return
        wurzel = self.wurzel

        def arbeit():
            ok, meldung = kg.auswerfen(wurzel)
            if not ok:
                raise RuntimeError(_("Ejecting failed: {meldung}. Eject in the file manager.").format(meldung=meldung))
            self.geschrieben = False
            return _("E-reader ejected, the cable can come off.")
        a.hintergrund(_("Eject"), arbeit, nachher=lambda: self.suchen(still=True))

    def vermerken(self, pfad):
        """Die Oberfläche hat etwas unter pfad gespeichert - liegt das auf dem Gerät?"""
        try:
            if self.wurzel and Path(pfad).resolve().is_relative_to(Path(self.wurzel).resolve()):
                self.geschrieben = True
        except (OSError, ValueError):
            pass

    def beenden_ok(self):
        """Erinnerung ans Auswerfen beim Beenden. False: nicht beenden."""
        if not (self.app.e.get("auswerfen_erinnern", True) and self.geschrieben
                and self.wurzel and self.wurzel.exists()):
            return True
        antwort = messagebox.askyesnocancel(
            _(BEREICH), _("Data was written to the e-reader. Eject before unplugging, otherwise data may be "
                          "missing.\n\nEject now?"), parent=self.app)
        if antwort is None:
            return False
        if antwort:
            ok, meldung = kg.auswerfen(self.wurzel)
            if not ok:
                messagebox.showwarning(_(BEREICH), _("Ejecting failed: {meldung}").format(meldung=meldung) + "\n\n" +
                                       _("Eject in the file manager."),
                                       parent=self.app)
        return True
