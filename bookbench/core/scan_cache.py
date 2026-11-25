# -*- coding: utf-8 -*-
"""
scan_cache.py - Zwischenspeicher fürs Einlesen der Bibliothek (seit 2.1).

Einlesen heißt: jedes EPUB öffnen, OPF, Inhaltsverzeichnis und Kapitelanfänge lesen (toc_fix.analyse_book).
Das dauert bei ein paar hundert Büchern spürbar, und ab 2.1 liest Bookbench öfter ein (Bibliothek auf dem
Rechner, Import, Abgleich mit dem Reader). Der Zwischenspeicher merkt sich je Datei das Ergebnis vor dem
Anwenden der Kapitel-Entscheidungen (die ändern sich unabhängig von der Datei) und einen Stempel:

    (Größe, Änderungszeit der Datei, Änderungszeit von custom_metadata.lua im .sdr, Version, max_sub)

Stimmt der Stempel, wird nicht neu gelesen. Abgelegt als pickle im Einstellungsordner
(einlese-cache/<Prüfsumme des Ordnerpfads>.pickle), nicht im Bibliotheksordner: pickle aus einem fremden
oder synchronisierten Ordner zu laden hieße, dort liegenden Code auszuführen. Der Zwischenspeicher ist nur
Tempo, kein Zustand - geht er verloren, wird eben neu gelesen.

  Zwischenspeicher(ordner)    .holen(pfad, max_sub) -> Buch | None, .ablegen(pfad, max_sub, buch), .sichern()
  leeren()                    alle Zwischenspeicher löschen (Einstellungen > Erweitert)
"""
import hashlib
import os
import pickle
import shutil
from pathlib import Path

from bookbench import i18n as ks
from bookbench.version import VERSION

FORMAT = 1


def ordner():
    return ks.einstellungsordner() / "einlese-cache"


def leeren():
    shutil.rmtree(ordner(), ignore_errors=True)


def _sdr_datei(pfad):
    p = Path(pfad)
    name = p.name
    stamm = name[:name.rfind(".")] if "." in name else name      # x.kepub.epub → x.kepub.sdr (wie KOReader)
    return p.with_name(stamm + ".sdr") / "custom_metadata.lua"


def stempel(pfad, max_sub):
    try:
        st = os.stat(pfad)
    except OSError:
        return None
    try:
        sdr = os.stat(_sdr_datei(pfad)).st_mtime_ns
    except OSError:
        sdr = 0
    return (st.st_size, st.st_mtime_ns, sdr, VERSION, FORMAT, int(max_sub))


class Zwischenspeicher:
    def __init__(self, bibliothek, datei=None):
        schluessel = hashlib.sha1(str(Path(bibliothek).resolve()).encode("utf-8")).hexdigest()[:16]
        self.datei = Path(datei) if datei else ordner() / f"{schluessel}.pickle"
        self.alt = {}
        self.neu = {}
        self.treffer = 0
        try:
            with open(self.datei, "rb") as f:
                d = pickle.load(f)
            if isinstance(d, dict) and d.get("format") == FORMAT:
                self.alt = d.get("eintraege") or {}
        except Exception:
            self.alt = {}

    def holen(self, pfad, max_sub):
        st = stempel(pfad, max_sub)
        e = self.alt.get(str(pfad))
        if st is None or not e or e[0] != st:
            return None
        try:
            buch = pickle.loads(e[1])
        except Exception:
            return None
        self.neu[str(pfad)] = e
        self.treffer += 1
        return buch

    def ablegen(self, pfad, max_sub, buch):
        st = stempel(pfad, max_sub)
        if st is None or getattr(buch, "fehler", ""):
            return
        try:
            self.neu[str(pfad)] = (st, pickle.dumps(buch, protocol=pickle.HIGHEST_PROTOCOL))
        except Exception:
            pass

    def sichern(self):
        """Nur die Einträge dieses Durchlaufs schreiben (gelöschte Bücher fallen damit heraus)."""
        try:
            self.datei.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.datei.with_suffix(".tmp")
            with open(tmp, "wb") as f:
                pickle.dump({"format": FORMAT, "eintraege": self.neu}, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, self.datei)
        except OSError:
            pass
