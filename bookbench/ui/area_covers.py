# -*- coding: utf-8 -*-
"""
area_covers.py - Bereich "Cover" von Bookbench: Titelbilder ansehen, ersetzen,
nachschlagen, exportieren. Die Logik steckt in kobo_cover (Bilder) und kobo_daten (EPUB).

  Bücherliste links (Bücher ohne Cover gelblich, kleine Cover mit ⚠)
  rechts das Cover so groß, wie Platz ist; liegt ein neues bereit, Datei und Neu nebeneinander
  Werkzeugleiste: Aus Datei, Nachschlagen, Alle ohne Cover, Groß, Verwerfen, Exportieren

Ein neues Cover ist wie ein übernommener Text: gelb, bis gespeichert wird (Strg+S, mit
Sicherung). Es wird beim Einsetzen ins Format des vorhandenen Covers gebracht (kobo_cover).
"""
import base64
import io
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import keller_theme as kth
from bookbench.core import covers as kc
from bookbench.i18n import _, ngettext

FORMATNAME = {"jpeg": "JPEG", "png": "PNG", "gif": "GIF", "webp": "WebP", "?": "?"}


def groesse_text(n):
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def foto(daten, max_w, max_h, master, vergroessern=2.0):
    """PhotoImage, eingepasst in max_w × max_h (höchstens `vergroessern`-fach vergrößert).
    Ohne Pillow nur PNG/GIF und nur verkleinert. None, wenn es nicht geht."""
    if not daten or max_w < 20 or max_h < 20:
        return None
    try:
        from PIL import Image, ImageTk
    except ImportError:
        try:
            roh = tk.PhotoImage(data=base64.b64encode(daten).decode(), master=master)
        except tk.TclError:
            return None
        f = max(1, -(-roh.width() // max_w), -(-roh.height() // max_h))
        return roh.subsample(f) if f > 1 else roh
    try:
        im = Image.open(io.BytesIO(daten))
        im.load()
    except Exception:
        return None
    faktor = min(max_w / im.width, max_h / im.height, vergroessern)
    w, h = max(1, round(im.width * faktor)), max(1, round(im.height * faktor))
    return ImageTk.PhotoImage(im.convert("RGB").resize((w, h), Image.LANCZOS), master=master)


def info_text(info, pfad=""):
    if not info:
        return _("no cover")
    w, h, fmt, n = info
    teile = [f"{w} × {h} px", FORMATNAME.get(fmt, fmt), groesse_text(n)]
    return "  ·  ".join(teile + ([pfad] if pfad else []))


class CoverBereich:
    def __init__(self, app):
        self.app = app
        self.buch = None
        self._fotos = []                         # Verweise halten, sonst räumt Tk die Bilder weg
        self._job = None
        s = self.seite = app._seite(_("Covers"), "cover")
        links = ttk.Frame(s)
        links.pack(side="left", fill="y")
        ttk.Label(links, text=_("Books:")).pack(anchor="w")
        self.liste = app._buchliste(links, self.anzeigen, self._status)
        rechts = ttk.Frame(s)
        rechts.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.kopf = ttk.Label(rechts, text=_("Choose a book on the left."), style="Ueberschrift.TLabel")
        self.kopf.pack(anchor="w")
        self.info = ttk.Label(rechts, text="", style="Hinweis.TLabel")
        self.info.pack(anchor="w", pady=(2, 6))
        unten = ttk.Frame(rechts)
        unten.pack(side="bottom", fill="x", pady=(6, 0))
        self.zeile_datei = ttk.Label(unten, text="", wraplength=900, justify="left")
        self.zeile_datei.pack(anchor="w")
        self.zeile_neu = ttk.Label(unten, text="", wraplength=900, justify="left")
        self.zeile_neu.pack(anchor="w")
        self.hinweis = ttk.Label(unten, text="", style="Hinweis.TLabel", wraplength=900, justify="left")
        self.hinweis.pack(anchor="w", pady=(2, 0))
        r = app._listenrahmen(rechts)
        r.pack(fill="both", expand=True)
        self.flaeche = tk.Canvas(r, highlightthickness=0, borderwidth=0, cursor="hand2")
        self.flaeche.pack(fill="both", expand=True)
        self.flaeche.bind("<Configure>", lambda e: self._spaeter_zeichnen())
        self.flaeche.bind("<Button-1>", lambda e: self.gross())       # Klick aufs Cover: groß

    # ================================================================ Werkzeugleiste
    def werkzeug(self, eltern):
        a = self.app
        a._wz_knopf(eltern, "bild", _("From file"), self.aus_datei,
                    _("Use an image file as the new cover (JPEG, PNG, GIF, WebP)"))
        a._wz_knopf(eltern, "suchen", _("Look up"), self.nachschlagen,
                    _("Look for covers of this book on Open Library and Google Books (free) and choose one"))
        a._wz_knopf(eltern, "neu_laden", _("All without cover"), self.alle_ohne,
                    _("For all books without a cover: take the largest cover found, in the background"))
        ttk.Separator(eltern, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)
        a._wz_knopf(eltern, "rueckgaengig", _("Discard"), self.verwerfen, _("Drop the new cover, keep the one in the file"))
        a._wz_knopf(eltern, "exportieren", _("Export …"), self.exportieren,
                    _("Save the cover shown as an image file"))

    # ================================================================ Liste
    def liste_fuellen(self, sortiert):
        vorher = self.buch
        self.liste.delete(0, "end")
        for b in sortiert:
            self.liste.insert("end", self.app._anzeigename(b))
        neu = self.app.nach_schluessel.get(vorher.schluessel) if vorher else None
        if neu:
            self.auswaehlen(neu)
        else:
            self.anzeigen()
        self.listenfarben()

    def auswaehlen(self, b):
        namen = list(self.liste.get(0, "end"))
        name = self.app._anzeigename(b)
        if name in namen:
            i = namen.index(name)
            self.liste.selection_clear(0, "end")
            self.liste.selection_set(i)
            self.liste.see(i)
            self.anzeigen()

    def klein(self, b):
        grenze = int(self.app.e.get("cover_klein") or 0)
        info = kc.bild_info(b.cover_neu) if b.cover_neu is not None else b.cover_info
        return bool(grenze and info and info[1] and info[1] < grenze)

    def fehlt(self, b):
        return not b.fehler and b.cover_neu is None and not b.cover_info

    def _warnung(self, b):
        if b.fehler:
            return b.fehler
        if self.fehlt(b):
            return _("no cover")
        if self.klein(b):
            info = kc.bild_info(b.cover_neu) if b.cover_neu is not None else b.cover_info
            return _("small cover ({w} × {h} px)").format(w=info[0], h=info[1])
        return None

    def _status(self, name):
        b = self.app._listen_buch.get(name)
        return (b.stand(), self._warnung(b)) if b else (None, None)

    def listenfarben(self):
        farbe = self.app.OHNEZEILE["dunkel" if self.app.dark_mode.get() else "hell"]
        for i, name in enumerate(self.liste.get(0, "end")):
            b = self.app._listen_buch.get(name)
            self.liste.itemconfigure(i, background=farbe if b is not None and self.fehlt(b) else "")

    def beim_zeigen(self):
        if not self.liste.curselection() and self.liste.size():
            self.liste.selection_set(0)
        self.anzeigen()

    # ================================================================ Anzeige
    def anzeigen(self):
        self.buch = b = self.app._aktuelles_buch(self.liste)
        if not b:
            self.kopf.configure(text=_("Choose a book on the left."))
            for lab in (self.info, self.zeile_datei, self.zeile_neu, self.hinweis):
                lab.configure(text="")
        else:
            self.kopf.configure(text=b.name)
            self.info.configure(text="  ·  ".join(x for x in (b.autor, f"{b.reihe} {b.nummer}".strip(), b.pfad.name) if x))
            self.zeile_datei.configure(text=_("In the file: {info}").format(info=info_text(b.cover_info, b.cover_datei)))
            if b.cover_neu is not None:
                i = kc.bild_info(b.cover_neu)
                self.zeile_neu.configure(text=_("New: {info} - from {quelle}; applied, not yet saved (Ctrl+S).").format(
                    info=info_text((i[0], i[1], i[2], len(b.cover_neu)) if i else None), quelle=b.cover_neu_quelle))
            else:
                self.zeile_neu.configure(text="")
            hinweise = []
            if self.klein(b):
                hinweise.append(_("⚠ Smaller than {n} px in height (limit in Settings > Covers).").format(
                    n=self.app.e.get("cover_klein")))
            if not kc.hat_pillow():
                hinweise.append(_("Without Pillow only PNG and GIF can be shown and nothing can be converted "
                                  "(pip install pillow)."))
            self.hinweis.configure(text="\n".join(hinweise))
        self.zeichnen()

    def _spaeter_zeichnen(self):
        if self._job:
            self.app.after_cancel(self._job)
        self._job = self.app.after(80, self.zeichnen)

    def zeichnen(self):
        self._job = None
        c = self.flaeche
        c.delete("all")
        self._fotos = []
        p = kth.PALETTE["dunkel" if self.app.dark_mode.get() else "hell"]
        c.configure(bg=p["feld"])
        b = self.buch
        w, h = c.winfo_width(), c.winfo_height()
        if not b or w < 40 or h < 40:
            return
        bilder = []
        if b.cover_info:
            bilder.append((_("In the file"), self._datei_bytes(b)))
        if b.cover_neu is not None:
            bilder.append((_("New"), b.cover_neu))
        if not bilder:
            c.create_text(w // 2, h // 2, text=_("No cover. \"From file\" or \"Look up\" adds one."),
                          fill=p["hinweis"], font=kth.schrift(11))
            return
        n = len(bilder)
        rand, unterschrift = 12, 22 if n > 1 else 0
        breite = (w - rand * (n + 1)) // n
        for i, (titel, daten) in enumerate(bilder):
            f = foto(daten, breite, h - 2 * rand - unterschrift, c)
            x = rand + i * (breite + rand) + breite // 2
            if f is None:
                c.create_text(x, h // 2, text=_("Cannot be shown (JPEG needs Pillow)."), fill=p["hinweis"],
                              width=breite)
                continue
            self._fotos.append(f)
            c.create_image(x, rand + unterschrift, image=f, anchor="n")
            if n > 1:
                c.create_text(x, rand, text=titel, fill=p["fg"], anchor="n", font=kth.schrift(10, fett=True))

    def _datei_bytes(self, b):
        """Bytes des Covers in der Datei; zwischengespeichert nach Pfad und Änderungszeit."""
        try:
            schl = (str(b.pfad), b.pfad.stat().st_mtime)
        except OSError:
            return None
        if getattr(self, "_cache_schl", None) != schl:
            from bookbench.core import library as kd
            self._cache_schl, self._cache_daten = schl, kd.cover_lesen(b.pfad)
        return self._cache_daten

    def aktuelle_bytes(self, b):
        return b.cover_neu if b.cover_neu is not None else self._datei_bytes(b)

    # ================================================================ Aktionen
    def _buch_noetig(self):
        if self.app._bereich() != "cover" or not self.buch:
            self.app.status.set(_("Choose a book in the Covers area first."))
            return None
        return self.buch

    def einsetzen(self, b, daten, quelle):
        """Neues Bild vorbereiten (Format des vorhandenen Covers, ggf. verkleinert) und übernehmen.
        Gibt True zurück, wenn es geklappt hat; Fehler stehen in der Statuszeile."""
        info = kc.bild_info(daten)
        if not info:
            self.app.status.set(f"{b.name}: " + _("not a readable image (JPEG, PNG, GIF or WebP)."))
            return False
        ziel = b.cover_info[2] if b.cover_info and b.cover_info[2] != "?" else (
            info[2] if info[2] in ("jpeg", "png") else "jpeg")
        try:
            neu = kc.vorbereiten(daten, ziel, int(self.app.e.get("cover_max_hoehe") or 0),
                                 int(self.app.e.get("cover_qualitaet") or 90))
        except RuntimeError:
            self.app.status.set(f"{b.name}: " + _("the image would have to be converted to {fmt}; that needs Pillow "
                                                  "(pip install pillow).").format(fmt=FORMATNAME[ziel]))
            return False
        except Exception as e:
            self.app.status.set(f"{b.name}: " + _("image could not be read ({fehler}).").format(fehler=e))
            return False
        b.cover_neu, b.cover_neu_quelle = neu, quelle
        self.app._geaendert(b)
        if b is self.buch:
            self.anzeigen()
        self.listenfarben()
        return True

    def aus_datei(self):
        b = self._buch_noetig()
        if not b:
            return
        p = filedialog.askopenfilename(parent=self.app, title=_("Choose the new cover"),
                                       filetypes=[(_("Images"), "*.jpg *.jpeg *.png *.gif *.webp"), (_("All files"), "*")])
        if not p:
            return
        try:
            daten = Path(p).read_bytes()
        except OSError as e:
            self.app.status.set(str(e))
            return
        if self.einsetzen(b, daten, Path(p).name):
            self.app.status.set(f"{b.name}: " + _("new cover applied, not yet saved (Ctrl+S)."))

    def _quellen(self):
        kc.MIN_HOEHE = int(self.app.e.get("cover_min_hoehe") or 300)
        return [q for q in ("openlibrary", "google") if self.app.e.get(f"cover_{q}", True)]

    def nachschlagen(self):
        b = self._buch_noetig()
        if not b:
            return
        if not self._quellen():
            self.app.status.set(_("All cover sources are switched off (Settings > Covers)."))
            return
        if self.app._arbeit:
            self.app.status.set(_("Still running: {arbeit}.").format(arbeit=self.app._arbeit))
            return
        ergebnis = {}

        def arbeit():
            ergebnis["k"] = kc.nachschlagen(b.titel, b.autor, b.isbn, self._quellen(),
                                            int(self.app.e.get("cover_anzahl") or 8))
            return ngettext("{n} cover found.", "{n} covers found.", len(ergebnis["k"])).format(n=len(ergebnis["k"]))

        def nachher():
            k = ergebnis.get("k")
            if not k:
                self.app.status.set(f"{b.name}: " + _("no cover found."))
                return
            wahl = AuswahlDialog(self.app, b, k, self._datei_bytes(b) if b.cover_info else None).ergebnis
            if wahl and self.einsetzen(b, wahl["daten"], wahl["url"]):
                self.app.status.set(f"{b.name}: " + _("cover from {quelle} applied, not yet saved (Ctrl+S).")
                                    .format(quelle=wahl["quelle"]))
        self.app.status.set(f"{b.name}: " + _("looking for covers …"))
        self.app.hintergrund(_("Looking up covers"), arbeit, nachher=nachher)

    def alle_ohne(self):
        offen = [b for b in self.app.buecher if self.fehlt(b)]
        if not offen:
            self.app.status.set(_("All books have a cover."))
            return
        if not self._quellen():
            self.app.status.set(_("All cover sources are switched off (Settings > Covers)."))
            return
        if self.app._arbeit:
            self.app.status.set(_("Still running: {arbeit}.").format(arbeit=self.app._arbeit))
            return
        if not messagebox.askyesno(_("All without cover"), ngettext(
                "{n} book has no cover. For it the largest cover found is taken; check it afterwards and "
                "save with Ctrl+S.\n\nStart?",
                "{n} books have no cover. For each the largest cover found is taken; check them afterwards and "
                "save with Ctrl+S.\n\nStart?", len(offen)).format(n=len(offen)), parent=self.app):
            return
        gefunden = {}
        quellen = self._quellen()

        def arbeit():
            for i, b in enumerate(offen, 1):
                self.app._q.put(("status", _("Looking up covers ({i}/{n}): {name} …").format(i=i, n=len(offen),
                                                                                         name=b.name)))
                try:
                    k = kc.nachschlagen(b.titel, b.autor, b.isbn, quellen, hoechstens=3)
                except Exception:
                    k = []
                if k:
                    gefunden[b.schluessel] = k[0]
            return ngettext("Covers: {n} of {gesamt} book found.", "Covers: {n} of {gesamt} books found.",
                            len(offen)).format(n=len(gefunden), gesamt=len(offen))

        def nachher():
            for schl, k in gefunden.items():
                b = self.app.nach_schluessel.get(schl)
                if b:
                    self.einsetzen(b, k["daten"], k["url"])
        self.app.hintergrund(_("Looking up covers"), arbeit, nachher=nachher)

    def verwerfen(self):
        b = self._buch_noetig()
        if not b or b.cover_neu is None:
            return
        b.cover_neu, b.cover_neu_quelle = None, ""
        self.app._geaendert(b)
        self.anzeigen()
        self.listenfarben()
        self.app.status.set(f"{b.name}: " + _("new cover discarded."))

    def exportieren(self):
        b = self._buch_noetig()
        if not b:
            return
        daten = self.aktuelle_bytes(b)
        info = kc.bild_info(daten) if daten else None
        if not info:
            self.app.status.set(f"{b.name}: " + _("no cover to export."))
            return
        endung = kc.ENDUNG[info[2]]
        name = "".join(z for z in b.titel if z not in '\\/:*?"<>|').strip() or "cover"
        p = filedialog.asksaveasfilename(parent=self.app, title=_("Export cover"), initialfile=f"{name}.{endung}",
                                         defaultextension="." + endung)
        if not p:
            return
        try:
            Path(p).write_bytes(daten)
        except OSError as e:
            self.app.status.set(str(e))
            return
        self.app.status.set(_("Cover saved: {datei}").format(datei=p))

    def gross(self, b=None):
        b = b or self.buch
        if not b:
            return
        daten = self.aktuelle_bytes(b)
        if not daten:
            self.app.status.set(f"{b.name}: " + _("no cover."))
            return
        GrossFenster(self.app, b, daten)

    def farben(self):
        self.listenfarben()
        self.zeichnen()


class GrossFenster(tk.Toplevel):
    """Cover so groß, wie der Bildschirm erlaubt. Klick oder Esc schließt."""

    def __init__(self, app, b, daten):
        super().__init__(app)
        self.title(b.name)
        self.transient(app)
        p = kth.PALETTE["dunkel" if app.dark_mode.get() else "hell"]
        self.configure(bg=p["bg"])
        hoehe = int(app.winfo_screenheight() * 0.85)
        breite = int(app.winfo_screenwidth() * 0.9)
        self.foto = foto(daten, breite, hoehe - 40, self, vergroessern=4.0)
        info = kc.bild_info(daten)
        if self.foto is None:
            ttk.Label(self, text=_("Cannot be shown (JPEG needs Pillow).")).pack(padx=20, pady=20)
        else:
            tk.Label(self, image=self.foto, borderwidth=0, bg=p["bg"]).pack(padx=8, pady=(8, 4))
        text = info_text((info[0], info[1], info[2], len(daten)) if info else None)
        ttk.Label(self, text=text + "  ·  " + _("Click or Esc closes."), style="Hinweis.TLabel").pack(pady=(0, 8))
        for ereignis in ("<Escape>", "<Button-1>"):
            self.bind(ereignis, lambda e: self.destroy())
        self.focus_set()


class AuswahlDialog(tk.Toplevel):
    """Gefundene Cover nebeneinander; Klick wählt, OK übernimmt. ergebnis: Kandidat oder None."""
    HOEHE = 260

    def __init__(self, app, b, kandidaten, aktuell=None):
        super().__init__(app)
        self.ergebnis = None
        self.kandidaten = kandidaten
        self.title(_("Choose a cover: {name}").format(name=b.name))
        self.transient(app)
        p = kth.PALETTE["dunkel" if app.dark_mode.get() else "hell"]
        self.p = p
        unten = ttk.Frame(self, padding=8)
        unten.pack(side="bottom", fill="x")
        ttk.Button(unten, text=_("Cancel"), command=self.destroy).pack(side="right")
        self.ok_knopf = ttk.Button(unten, text="OK", command=self.ok, state="disabled")
        self.ok_knopf.pack(side="right", padx=6)
        self.hinweis = ttk.Label(self, text=_("Click a cover to choose it, double-click takes it at once."),
                                 style="Hinweis.TLabel", padding=(10, 0))
        self.hinweis.pack(side="bottom", anchor="w")
        rahmen = ttk.Frame(self, padding=(8, 8, 8, 0))
        rahmen.pack(fill="both", expand=True)
        self.leinwand = tk.Canvas(rahmen, height=self.HOEHE + 60, highlightthickness=0, bg=p["feld"])
        sb = ttk.Scrollbar(rahmen, orient="horizontal", command=self.leinwand.xview)
        self.leinwand.configure(xscrollcommand=sb.set)
        self.leinwand.pack(fill="both", expand=True)
        sb.pack(fill="x")
        innen = tk.Frame(self.leinwand, bg=p["feld"])
        self.leinwand.create_window(0, 0, window=innen, anchor="nw")
        self.fotos, self.kacheln = [], []
        eintraege = ([(_("In the file"), {"daten": aktuell, "quelle": "", "w": 0, "h": 0}, False)] if aktuell else []) \
            + [(k["quelle"], k, True) for k in kandidaten]
        for titel, k, waehlbar in eintraege:
            info = kc.bild_info(k["daten"])
            f = foto(k["daten"], 220, self.HOEHE, self, vergroessern=1.0)
            kachel = tk.Frame(innen, bg=p["feld"], highlightthickness=3, highlightbackground=p["feld"], padx=4, pady=4)
            kachel.pack(side="left", padx=4, pady=4, anchor="n")
            if f is not None:
                self.fotos.append(f)
                tk.Label(kachel, image=f, bg=p["feld"], borderwidth=0).pack()
            else:
                tk.Label(kachel, text="?", bg=p["feld"], fg=p["fg"], width=20, height=10).pack()
            unterschrift = titel + (f"\n{info[0]} × {info[1]} px, {groesse_text(len(k['daten']))}" if info else "")
            tk.Label(kachel, text=unterschrift, bg=p["feld"], fg=p["fg"] if waehlbar else p["hinweis"],
                     font=kth.schrift(9), justify="center").pack(pady=(4, 0))
            if waehlbar:
                self.kacheln.append((kachel, k))
                for w in [kachel] + list(kachel.winfo_children()):
                    w.bind("<Button-1>", lambda e, kk=k: self.waehlen(kk))
                    w.bind("<Double-Button-1>", lambda e, kk=k: (self.waehlen(kk), self.ok()))
        innen.update_idletasks()
        self.leinwand.configure(scrollregion=(0, 0, innen.winfo_reqwidth(), innen.winfo_reqheight()))
        breite = max(560, min(innen.winfo_reqwidth() + 20, int(app.winfo_screenwidth() * .9)))
        self.geometry(f"{breite}x{self.HOEHE + 170}")
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self.ok())
        self.gewaehlt = None
        self.grab_set()
        self.wait_window()

    def waehlen(self, k):
        self.gewaehlt = k
        for kachel, kk in self.kacheln:
            farbe = self.p["akzent"] if kk is k else self.p["feld"]
            kachel.configure(highlightbackground=farbe, highlightcolor=farbe)
        self.ok_knopf.configure(state="normal")

    def ok(self):
        if self.gewaehlt is None:
            return
        self.ergebnis = self.gewaehlt
        self.destroy()
