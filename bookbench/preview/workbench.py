# -*- coding: utf-8 -*-
"""
workbench.py - KOReader-Werkbank (seit 1.4): der Desktop-KOReader läuft unsichtbar im Hintergrund
(SDL ohne Bildschirm) und liefert auf Befehl Bilder der Seite. Keine Oberfläche.

Machbarkeit am 24.11.2026 beim Nutzer gemessen (tools/koreader_probe.py): Kaltstart ~1,2 s bis zum
ersten Bild, jedes weitere Bild 0,1 s; offscreen liefert die volle Geräteauflösung, Bookends und
Bookshelf zeichnen mit.

Wegwerf-Kopie des Vorschau-Profils, bei jedem Start neu (das Profil selbst bleibt unberührt, auch
der Lesestand und Verlauf):

  <profil>/werkbank/koreader     KO_HOME: Einstellungen, Patches, nur die erlaubten Plugins
  <profil>/werkbank/buecher      das gezeigte Buch (Kopie mit .sdr) bzw. die Blindtext-Bibliothek
  <profil>/werkbank/befehle      Befehle an KOReader: <Nummer>.cmd, eine Zeile
  <profil>/werkbank/bilder       Bilder (PNG), Name = Nummer des Befehls
  <profil>/werkbank/koreader.log KOReaders Ausgabe
  Schriften (XDG_DATA_HOME) kommen direkt aus <profil>/share (nur gelesen).

Plugins: nur die aus PLUGINS (Bookends, Bookshelf); andere eigene Plugins können ein Vollbild über
alles legen (beim Nutzer „silverfish“) und bleiben in der Werkbank draußen. KOReaders eingebaute
Plugins kommen mit KOReader selbst.

Steuerung: Der Patch 2-bookbench-workbench.lua (spät, nach dem Aufbau der Oberfläche) wartet, bis das
Buch bzw. der Startbildschirm da ist ("ready"), und liest dann alle 50 ms den Ordner befehle/:

  shot <pfad>   neu zeichnen, Bild schreiben (erst <pfad>.tmp, dann umbenennen)
  next / prev   eine Seite weiter/zurück (Buch: GotoViewRel, Startbildschirm: NextPage/PrevPage)
  bookends <datei>       Bookends-Vorlage aus settings/bookends_presets übernehmen (seit 1.4-beta2,
                         Bookends:applyPresetFile, wie Bookends' eigene Vorschau); nur auf der Leseseite
  bookends_enabled 0|1   Bookends ein-/ausschalten (Bookends:onSetBookends)
  tap <x> <y> / hold <x> <y>   Fingertipp bzw. langes Drücken auf den Bildschirm (seit 1.4-beta5): ein
                         "Gesture"-Ereignis wie von Input, geht an das oberste Fenster - so lassen sich z. B.
                         Bookshelfs Regal-Knöpfe bedienen
  quit          beenden
Hängt KOReader nach 5 s noch vor dem Buch (Dialog, Datei nicht unterstützt …), meldet der Patch
"stuck <oberstes Fenster>" und nimmt trotzdem Befehle an, damit das Bild zeigt, was KOReader zeigt.
Wachhund: Bookbench berührt befehle/alive alle 5 s; ist die Datei älter als 30 s (Bookbench abgestürzt),
beendet sich KOReader selbst.

Antworten auf stdout: "BOOKBENCH-WB ready <modus>", "BOOKBENCH-WB done <nummer> ok|error …".

  Werkbank(befund, profil)
    .starten(modus, buch, w, h, dpi, sw, sdr, bibliothek, anpassen)   modus "lesen" oder "bibliothek";
                           anpassen(ko_ordner) ändert die Wegwerf-Kopie vor dem Start (Entwürfe, seit 1.4-beta2)
    .bild() / .blaettern(+1|-1)   Befehl schicken, gibt die Nummer zurück
    .ereignisse()          neue Ereignisse (dicts, art: bereit, haengt, bild, erledigt, fehler, ende)
    .tippen(x, y, halten)  Fingertipp in Bildschirmpixeln
    .beenden()             KOReader beenden (erst freundlich, dann hart)
"""
import os
import queue
import shutil
import signal
import stat
import subprocess
import threading
import time
from pathlib import Path

from bookbench.preview import emulator as kv
from bookbench.preview import sample_book
from bookbench.i18n import _

ORDNER = "werkbank"
PATCH = "2-bookbench-workbench.lua"
PLUGINS = ("bookends", "bookshelf")
MARKE = "BOOKBENCH-WB "
BLINDTEXT = "Lorem Ipsum.epub"

PATCH_TEXT = r'''-- Written by Bookbench for its KOReader workbench (only in a throw-away copy of the profile).
-- Waits until the book or the start screen is up, then reads commands from a folder.
local dir = os.getenv("BOOKBENCH_WB")
if not dir or dir == "" then return end
local mode = os.getenv("BOOKBENCH_WB_MODE") or "read"
local function say(msg)
    io.stdout:write("BOOKBENCH-WB " .. msg .. "\n")
    io.stdout:flush()
end
local ok, UIManager = pcall(require, "ui/uimanager")
if not ok then say("error no-uimanager") return end
local Device = require("device")
local Event = require("ui/event")
local lfs = require("libs/libkoreader-lfs")

local function shot(path)
    local screen = Device.screen
    if type(screen.shot) == "function" then return screen:shot(path) end
    if screen.bb and type(screen.bb.writePNG) == "function" then return screen.bb:writePNG(path) end
    error("no screenshot function")
end
local function reader()
    local R = package.loaded["apps/reader/readerui"]
    return R and R.instance
end
local function filemanager()
    local F = package.loaded["apps/filemanager/filemanager"]
    return F and F.instance
end
local function bookends(r)
    if type(r.bookends) == "table" and r.bookends.applyPresetFile then return r.bookends end
    for _, m in ipairs(r) do
        if type(m) == "table" and type(m.applyPresetFile) == "function" then return m end
    end
end

local function top_widget()
    local st = UIManager._window_stack
    local w = st and st[#st] and st[#st].widget
    if not w then return "none" end
    local name = w.name or w.title or ""
    local text = w.text or ""
    if type(text) ~= "string" then text = "" end
    text = text:gsub("%s+", " ")
    return (tostring(name) .. " " .. text):sub(1, 300)
end

local function run(cmd)
    local verb, arg = cmd:match("^(%S+)%s*(.*)$")
    if verb == "shot" then
        UIManager:forceRePaint()
        local tmp = arg .. ".tmp"
        shot(tmp)
        os.rename(tmp, arg)
        return "ok"
    elseif verb == "next" or verb == "prev" then
        local d = verb == "next" and 1 or -1
        local r = reader()
        if r and r.document then
            r:handleEvent(Event:new("GotoViewRel", d))
        else
            UIManager:sendEvent(Event:new(d > 0 and "NextPage" or "PrevPage"))
        end
        return "ok"
    elseif verb == "bookends" or verb == "bookends_enabled" then
        local r = reader()
        if not (r and r.document) then return "error no-reader" end
        local be = bookends(r)
        if not be then return "error no-bookends" end
        if verb == "bookends" then
            local okp, err = be:applyPresetFile(arg)
            if not okp then return "error " .. tostring(err) end
        else
            be:onSetBookends(arg == "1")
        end
        -- Bookends repaints on the next tick; "shot" may come before that, so mark it now
        be.dirty = true
        be._tick_cache = nil
        UIManager:setDirty(r, "ui")
        return "ok"
    elseif verb == "tap" or verb == "hold" then
        local x, y = arg:match("^(%-?%d+)%s+(%-?%d+)$")
        if not x then return "error bad-arguments" end
        local Geom = require("ui/geometry")
        local okt, T = pcall(require, "ui/time")
        local now = okt and T.now() or os.time()
        local pos = Geom:new{ x = tonumber(x), y = tonumber(y), w = 0, h = 0 }
        UIManager:sendEvent(Event:new("Gesture", { ges = verb, pos = pos, time = now }))
        if verb == "hold" then
            UIManager:sendEvent(Event:new("Gesture", { ges = "hold_release", pos = pos, time = now }))
        end
        return "ok"
    elseif verb == "quit" then
        UIManager:quit()
        return "ok"
    end
    return "error unknown-command " .. tostring(verb)
end

local function poll()
    local names = {}
    for f in lfs.dir(dir) do
        if f:match("%.cmd$") then names[#names + 1] = f end
    end
    table.sort(names)
    for _, f in ipairs(names) do
        local p = dir .. "/" .. f
        local fh = io.open(p, "r")
        local cmd = fh and fh:read("*l") or ""
        if fh then fh:close() end
        os.remove(p)
        local okrun, res = pcall(run, cmd)
        say("done " .. f:gsub("%.cmd$", "") .. " " .. (okrun and res or ("error " .. tostring(res))))
    end
    UIManager:scheduleIn(0.05, poll)
end

-- Bookbench touches "alive" every few seconds. If it stops (Bookbench crashed or was killed),
-- KOReader quits by itself instead of running on unseen.
local alive = dir .. "/alive"
local function watchdog()
    local t = lfs.attributes(alive, "modification")
    if t and os.time() - t > 30 then
        say("error bookbench-gone")
        UIManager:quit()
        return
    end
    UIManager:scheduleIn(2, watchdog)
end
UIManager:scheduleIn(2, watchdog)

local polling = false
local function wait(n)
    local r = reader()
    if (mode == "library" and filemanager()) or (mode ~= "library" and r and r.document) then
        say("ready " .. mode)
        if not polling then
            polling = true
            UIManager:scheduleIn(0.05, poll)
        end
        return
    end
    if n == 50 and not polling then
        -- after 5 s still no book: say what is on top and accept commands anyway (picture, taps)
        say("stuck " .. top_widget())
        polling = true
        UIManager:scheduleIn(0.05, poll)
    end
    if n > 600 then
        say("error timeout")
        UIManager:quit()
        return
    end
    UIManager:scheduleIn(0.1, function() wait(n + 1) end)
end
UIManager:scheduleIn(0.1, function() wait(0) end)
'''


def kopiename(buch):
    """Name der Kopie in der Werkbank: "x.kepub" (ohne .epub) wird zu "x.kepub.epub" - KOReader kennt keine
    Endung .kepub und öffnet die Datei sonst nicht ("not supported", seit 1.4-beta5)."""
    name = Path(buch).name
    return name + ".epub" if name.lower().endswith(".kepub") else name


FENSTER = "fenster"                              # Wegwerf-Kopie für "In KOReader öffnen" (seit 1.4-beta6)
ZWISCHENSPEICHER = "werkbank-cache"              # Cover-Zwischenspeicher über Neustarts hinweg
# KOReaders/CoverBrowsers Buchinfo-Datenbank (Cover, Metadaten; Bookshelf liest sie) und Bookshelfs eigener
# Zwischenspeicher. Ohne sie musste jeder Start der Werkbank die Cover neu auslesen (Befund beta5).
BEHALTEN = ("settings/bookinfo_cache.sqlite3", "cache")


def arbeitsordner(profil, ordner=ORDNER):
    return Path(profil) / ordner


def _zwischenspeicher_sichern(arbeit, ziel):
    for rel in BEHALTEN:
        q = Path(arbeit) / "koreader" / rel
        if q.exists():
            z = Path(ziel) / rel
            kv._leeren(z)
            z.parent.mkdir(parents=True, exist_ok=True)
            (shutil.copytree if q.is_dir() else shutil.copy2)(q, z)


def _zwischenspeicher_holen(quelle, ko):
    for rel in BEHALTEN:
        q = Path(quelle) / rel
        if q.exists():
            z = Path(ko) / rel
            kv._leeren(z)
            z.parent.mkdir(parents=True, exist_ok=True)
            (shutil.copytree if q.is_dir() else shutil.copy2)(q, z)


def arbeitsprofil(profil, modus="lesen", plugins=PLUGINS, bibliothek=None, ordner=ORDNER, patch=True):
    """Legt die Wegwerf-Kopie neu an. Gibt den Ordner zurück. bibliothek: Ordner mit Büchern für den
    Startbildschirm (sonst Blindtext-Bücher). Im Lesemodus liegt die .sdr neben dem Buch ("doc"),
    beim Startbildschirm zentral im KO_HOME ("dir"), damit nichts neben die echten Bücher geschrieben wird.
    plugins=None: alle Plugins des Profils (Fenster). patch=False: ohne Werkbank-Patch (Fenster).
    Der Cover-Zwischenspeicher der letzten Kopie wird aufgehoben und wieder eingesetzt."""
    profil = Path(profil)
    arbeit = arbeitsordner(profil, ordner)
    speicher = profil / ZWISCHENSPEICHER
    if arbeit.is_dir():
        try:
            _zwischenspeicher_sichern(arbeit, speicher)
        except OSError:
            pass
    kv._leeren(arbeit)
    ko = arbeit / "koreader"
    shutil.copytree(kv._ko(profil), ko, symlinks=True)
    try:
        _zwischenspeicher_holen(speicher, ko)
    except OSError:
        pass
    erlaubt = set(plugins) if plugins is not None else None
    if erlaubt is not None and (ko / "plugins").is_dir():
        for p in (ko / "plugins").iterdir():
            if p.name.removesuffix(".koplugin") not in erlaubt:
                kv._leeren(p)
    (ko / "patches").mkdir(parents=True, exist_ok=True)
    for alt in (ko / "patches").glob("*bookbench-probe*"):
        alt.unlink()
    # "Alle Patches aus" (.patches_disabled) würde auch den Werkbank-Patch abschalten: stattdessen die
    # Patches des Nutzers einzeln ausschalten (seit 1.4-beta4)
    aus = ko / "patches" / ".patches_disabled"
    if patch and aus.exists():
        aus.unlink()
        for p in (ko / "patches").glob("*.lua"):
            p.rename(p.with_name(p.name + ".disabled"))
    if patch:
        (ko / "patches" / PATCH).write_text(PATCH_TEXT, encoding="utf-8")
    kv.desktop_patch_schreiben(arbeit)
    for teil in ("befehle", "bilder", "buecher"):
        (arbeit / teil).mkdir(parents=True, exist_ok=True)
    einst = ko / "settings.reader.lua"
    setzen = {"document_metadata_folder": "doc" if modus == "lesen" else "dir"}
    if modus == "bibliothek":
        if not bibliothek:
            bibliothek = sample_book.bibliothek(arbeit / "buecher")
        setzen["home_dir"] = str(bibliothek)
        try:
            alt = dict(kv.lua_zerlegen(einst.read_text(encoding="utf-8"))[1]).get("start_with", "")
        except OSError:
            alt = ""
        if not alt or "last" in alt:                    # "zuletzt gelesenes Buch" gibt es hier nicht
            setzen["start_with"] = "filemanager"
    else:
        setzen["home_dir"] = str(arbeit / "buecher")
    kv.einstellungen_anpassen(einst, setzen=setzen)
    return arbeit


def bibliothek_vorbereiten(arbeit, buecher, hoechstens=50, zuerst=None):
    """Startbildschirm mit der echten Bibliothek (seit 1.4-beta5): Buchdaten (.sdr neben den Büchern) in den
    zentralen Buchdaten-Ordner der Kopie spiegeln (document_metadata_folder "dir": KO_HOME/docsettings +
    voller Pfad ohne letzte Endung + .sdr), damit Fortschritt und Status zu sehen sind, und daraus einen
    Leseverlauf (history.lua) bauen, neueste zuerst - Bookshelf zeigt oben das zuletzt gelesene Buch.
    In die Bibliothek selbst wird nichts geschrieben. Gibt die Zahl der Bücher im Verlauf zurück.
    zuerst: dieses Buch steht als zuletzt gelesen ganz oben (Buchauswahl auf dem Startbildschirm, 1.4-beta6)."""
    ko = Path(arbeit) / "koreader"
    verlauf = []
    liste = list(buecher)
    if zuerst and Path(zuerst) not in [Path(b) for b in liste]:
        liste.append(zuerst)
    for buch in liste:
        buch = Path(buch)
        sdr = buch.with_name(kv._sdr_name(buch))
        dateien = sorted(sdr.glob("metadata.*.lua")) if sdr.is_dir() else []
        if not dateien:
            continue
        ziel = ko / "docsettings" / (str(buch.parent).lstrip("/")) / sdr.name
        try:
            shutil.copytree(sdr, ziel, dirs_exist_ok=True)
            zeit = int(max(p.stat().st_mtime for p in dateien))
        except OSError:
            continue
        verlauf.append({"file": str(buch), "time": zeit})
    if zuerst:
        verlauf = [e for e in verlauf if e["file"] != str(zuerst)]
        neueste = max([e["time"] for e in verlauf] + [int(time.time())])
        verlauf.append({"file": str(zuerst), "time": neueste + 1})
    verlauf.sort(key=lambda e: -e["time"])
    from bookbench.core import lua_data
    (ko / "history.lua").write_text("return " + lua_data.schreiben(verlauf[:hoechstens]) + "\n", encoding="utf-8")
    return min(len(verlauf), hoechstens)


class Werkbank:
    def __init__(self, befund, profil, ordner=ORDNER, fenster=False):
        """fenster=True: voller KOReader im Fenster (In KOReader öffnen) auf einer eigenen Wegwerf-Kopie,
        mit allen Plugins, ohne Werkbank-Patch (keine Bilder, keine Befehle)."""
        self.befund = befund
        self.profil = Path(profil)
        self.ordner = ordner
        self.fenster = fenster
        self.prozess = None
        self.modus = None
        self.buch = None
        self._q = queue.Queue()
        self._nr = 0
        self._gesendet = {}                      # Nummer -> (Befehl, Zeitpunkt)
        self._start = 0.0
        self.bereit = False
        self.haengt = False                      # KOReader steckt vor dem Buch (Dialog o. Ä.)
        self.verlauf = 0

    @property
    def arbeit(self):
        return arbeitsordner(self.profil, self.ordner)

    def laeuft(self):
        return self.prozess is not None and self.prozess.poll() is None

    def starten(self, modus, buch, w, h, dpi, sw=False, sdr=None, bibliothek=None, plugins=PLUGINS, anpassen=None,
                buecher=None, zuerst=None):
        """modus "lesen": buch (Pfad) oder None für das Blindtext-Buch; "bibliothek": Startbildschirm.
        anpassen(ko): Entwürfe in die Wegwerf-Kopie schreiben, bevor KOReader startet."""
        if not self.befund:
            raise RuntimeError(_("Desktop KOReader not found."))
        if not (kv._ko(self.profil) / "settings.reader.lua").is_file():
            raise RuntimeError(_("The profile is empty: take it from the e-reader or from a backup first."))
        self.beenden()
        if self.fenster:
            plugins = None
        arbeit = arbeitsprofil(self.profil, modus, plugins, bibliothek, ordner=self.ordner, patch=not self.fenster)
        if modus == "lesen":
            if buch:
                kopie = arbeit / "buecher" / kopiename(buch)
                shutil.copy2(buch, kopie)
                kv._sdr_kopieren(sdr, arbeit / "buecher" / kv._sdr_name(kopie))
                if kopie.name != Path(buch).name:          # x.kepub -> x.kepub.epub: Buchdaten heißen nach der Endung
                    d = arbeit / "buecher" / kv._sdr_name(kopie)
                    alt, neu = d / "metadata.kepub.lua", d / "metadata.epub.lua"
                    if alt.is_file() and not neu.exists():
                        alt.rename(neu)
            else:
                kopie = sample_book.blindtext_buch(arbeit / "buecher" / BLINDTEXT)
        else:
            kopie = None
            self.verlauf = (bibliothek_vorbereiten(arbeit, buecher if bibliothek else [], zuerst=zuerst)
                            if (bibliothek and buecher) or zuerst else 0)
        if anpassen:                                  # nach dem Buch: Buchdaten können mit angepasst werden
            anpassen(arbeit / "koreader")
        variablen = kv.umgebung(arbeit, w, h, dpi, sw)
        variablen["XDG_DATA_HOME"] = str(self.profil / "share")
        if not self.fenster:
            variablen.update({"BOOKBENCH_WB": str(arbeit / "befehle"),
                              "BOOKBENCH_WB_MODE": "library" if modus == "bibliothek" else "read",
                              "SDL_VIDEODRIVER": "offscreen", "SDL_VIDEO_DRIVER": "offscreen"})
        befehl = self._befehl(variablen, kopie, bibliothek)
        if self.befund["art"] == "appimage":
            p = Path(self.befund["pfad"])
            if not os.access(p, os.X_OK):
                p.chmod(p.stat().st_mode | stat.S_IXUSR)
        self._q = queue.Queue()
        self._gesendet = {}
        self.bereit = self.haengt = False
        self.modus, self.buch = modus, buch
        self._start = time.monotonic()
        if self.fenster:                              # eigenständig: Ausgabe in die Datei, läuft nach Bookbench weiter
            log = open(arbeit / kv.LOG, "w", encoding="utf-8", errors="replace")
            try:
                self.prozess = subprocess.Popen(befehl, env=dict(os.environ, **variablen), cwd=arbeit, stdout=log,
                                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                                start_new_session=True)
            except OSError as e:
                self.prozess = None
                raise RuntimeError(_("KOReader could not be started: {fehler}").format(fehler=e))
            finally:
                log.close()
            return self.prozess
        try:
            self.prozess = subprocess.Popen(befehl, env=dict(os.environ, **variablen), cwd=arbeit,
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            stdin=subprocess.DEVNULL, text=True, errors="replace", bufsize=1,
                                            start_new_session=True)
        except OSError as e:
            self.prozess = None
            raise RuntimeError(_("KOReader could not be started: {fehler}").format(fehler=e))
        threading.Thread(target=self._lesen, args=(self.prozess, arbeit / kv.LOG), daemon=True).start()
        threading.Thread(target=self._lebenszeichen, args=(self.prozess, arbeit / "befehle" / "alive"),
                         daemon=True).start()
        return self.prozess

    @staticmethod
    def _lebenszeichen(prozess, datei, takt=5):
        """Solange KOReader läuft, alle paar Sekunden "alive" berühren (Wachhund im Patch, 30 s)."""
        while prozess.poll() is None:
            try:
                datei.touch()
            except OSError:
                pass
            time.sleep(takt)

    def _befehl(self, variablen, kopie, bibliothek):
        if self.befund["art"] == "flatpak":
            freigaben = [f"--filesystem={self.profil}"] + ([f"--filesystem={bibliothek}:ro"] if bibliothek else [])
            return (["flatpak", "run"] + freigaben + [f"--env={k}={v}" for k, v in variablen.items()]
                    + [kv.FLATPAK_ID] + ([str(kopie)] if kopie else []))
        return [self.befund["pfad"]] + ([str(kopie)] if kopie else [])

    def _lesen(self, prozess, log_pfad):
        with open(log_pfad, "w", encoding="utf-8", errors="replace") as log:
            for zeile in prozess.stdout:
                log.write(zeile)
                log.flush()
                i = zeile.find(MARKE)
                if i < 0:
                    continue
                teile = zeile[i + len(MARKE):].strip().split(" ", 2)
                jetzt = time.monotonic()
                if teile[0] == "ready":
                    self._q.put({"art": "bereit", "dauer": jetzt - self._start})
                elif teile[0] == "stuck":
                    self._q.put({"art": "haengt", "text": " ".join(teile[1:]).strip()})
                elif teile[0] == "done" and len(teile) >= 3:
                    befehl, gesendet = self._gesendet.pop(teile[1], ("", jetzt))
                    ergebnis = teile[2]
                    e = {"art": "erledigt", "nr": teile[1], "befehl": befehl, "dauer": jetzt - gesendet,
                         "ok": ergebnis == "ok", "text": ergebnis}
                    if befehl.startswith("shot ") and ergebnis == "ok":
                        e["art"], e["pfad"] = "bild", Path(befehl[5:])
                    self._q.put(e)
                elif teile[0] == "error":
                    self._q.put({"art": "fehler", "text": " ".join(teile[1:])})
        self._q.put({"art": "ende", "code": prozess.wait()})

    def senden(self, befehl):
        """Befehl an KOReader; gibt seine Nummer zurück (None, wenn KOReader nicht läuft)."""
        if not self.laeuft():
            return None
        self._nr += 1
        nr = f"{self._nr:08d}"
        if befehl == "shot":
            befehl = f"shot {self.arbeit / 'bilder' / (nr + '.png')}"
        self._gesendet[nr] = (befehl, time.monotonic())
        tmp = self.arbeit / "befehle" / f"{nr}.tmp"
        tmp.write_text(befehl + "\n", encoding="utf-8")
        os.replace(tmp, tmp.with_suffix(".cmd"))
        return nr

    def bild(self):
        return self.senden("shot")

    def tippen(self, x, y, halten=False):
        return self.senden(f"{'hold' if halten else 'tap'} {int(x)} {int(y)}")

    def blaettern(self, richtung):
        return self.senden("next" if richtung > 0 else "prev")

    @property
    def ko(self):
        """KO_HOME der Wegwerf-Kopie (dorthin schreiben Entwürfe, bevor sie per Befehl gelten)."""
        return self.arbeit / "koreader"

    def bookends(self, datei):
        """Bookends-Vorlage (Datei in ko/settings/bookends_presets) im laufenden KOReader übernehmen."""
        return self.senden(f"bookends {datei}")

    def bookends_an(self, an):
        return self.senden(f"bookends_enabled {1 if an else 0}")

    def ereignisse(self):
        neu = []
        while True:
            try:
                e = self._q.get_nowait()
            except queue.Empty:
                return neu
            if e["art"] == "bereit":
                self.bereit, self.haengt = True, False
            elif e["art"] == "haengt":
                self.haengt = True
            neu.append(e)

    def alte_bilder_weg(self, behalten=None):
        """Bilder bis auf das zuletzt gezeigte löschen (sonst sammeln sie sich beim Blättern)."""
        for p in (self.arbeit / "bilder").glob("*.png"):
            if behalten is None or p != Path(behalten):
                try:
                    p.unlink()
                except OSError:
                    pass

    def beenden(self, warten=2.0):
        p, self.prozess = self.prozess, None
        self.bereit = False
        if p is None or p.poll() is not None:
            return
        try:
            nr = f"{self._nr + 1:08d}"
            (self.arbeit / "befehle" / f"{nr}.cmd").write_text("quit\n", encoding="utf-8")
            self._nr += 1
            p.wait(timeout=warten)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                p.kill()
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
