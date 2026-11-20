# -*- coding: utf-8 -*-
"""
updater.py - neue Versionen von Bookbench über die GitHub-Releases finden, herunterladen und
einspielen. Keine Oberfläche (die steckt in ui/updates.py).

  installationsart()          "windows" (Installer), "linux" (install.sh) oder "quelltext"
  version_tupel(text)         "v0.27" -> (0, 27); neuer(a, b); version_text("v1.1-beta1") -> "1.1-beta1"
  release_holen(repo, ...)    neueste Veröffentlichung als dict (Version, Text, Dateien, Seite)
  datei_fuer(release, art)    was für diese Installationsart heruntergeladen wird
  herunterladen(...)          Datei holen, mit Fortschritt; prüfen() gegen SHA256SUMS
  linux_einspielen(...)       Quelltext-ZIP der Veröffentlichung gegen den Programmordner tauschen
  windows_starten(setup)      Installer still starten (Bookbench beendet sich danach)

Wie eine Veröffentlichung aussieht (siehe tools/make_release.py): Tag "v<Version>", als Datei
Bookbench_Setup_<Version>.exe für Windows und SHA256SUMS mit den Prüfsummen. Linux nimmt das
Quelltext-ZIP der Veröffentlichung (zipball_url); das Release-Repo enthält nur Programmdaten.

Installation unter Linux (install.sh): ~/.local/share/bookbench/ mit programm/ (start.py,
bookbench/ …), venv/ (Python mit den Zusatzpaketen) und installation.json. Getauscht wird nur
programm/; venv/ und die Einstellungen (~/.config/bookbench) bleiben.

Das Release-Repo ist öffentlich und fest eingetragen (REPO); wer aus einem Fork aktualisieren
will, ändert REPO. Ohne Anmeldung erlaubt GitHub 60 API-Abfragen pro Stunde und Adresse - für eine
Suche pro Start reicht das. (Bis 1.0.3 gab es einen Token für das damals private Repo.)
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from bookbench.i18n import _

API = "https://api.github.com"            # in Tests ersetzbar
REPO = "kepfle-git/Bookbench"
SETUP_MUSTER = re.compile(r"^Bookbench[_-]Setup[_-].*\.exe$", re.I)
SUMMEN = "SHA256SUMS"
AGENT = "Bookbench-Updater"
ZEITLIMIT = 20
PROGRAMM = Path(__file__).resolve().parent.parent.parent      # Ordner mit start.py
MARKE = "installation.json"                                   # neben programm/ (install.sh)


class UpdateFehler(RuntimeError):
    pass


# -- Installation ----------------------------------------------------------------------------
def installation(programm=None):
    """(art, angaben): "windows" bei der gebauten .exe (PyInstaller), "linux" wenn install.sh
    das Programm eingerichtet hat (installation.json neben programm/), sonst "quelltext"
    (z. B. ein git-Klon, der sich nicht selbst überschreiben soll)."""
    if getattr(sys, "frozen", False):
        return ("windows" if sys.platform.startswith("win") else "gebaut"), {}
    p = Path(programm or PROGRAMM)
    marke = p.parent / MARKE
    if p.name == "programm" and marke.is_file():
        try:
            angaben = json.loads(marke.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            angaben = {}
        if angaben.get("art") == "linux":
            return "linux", angaben
    return "quelltext", {}


def installationsart(programm=None):
    return installation(programm)[0]


# -- Versionen --------------------------------------------------------------------------------
# Vorabversionen: 1.1-alpha1 < 1.1-beta1 < 1.1-rc1 < 1.1 (seit 1.1-beta1; ältere Updater lesen
# "1.1-beta1" als 1.1 - sie bieten die Vorabversion an, danach vergleicht schon der neue Code)
VORAB = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "rc": 2}
_VERSION = re.compile(r"(\d+(?:\.\d+)*)(?:[-. ]?(alpha|beta|rc|a|b)(?![a-z])\.?(\d*))?", re.I)


def version_tupel(text):
    """'v0.27' / 'Bookbench 0.27.1' -> (0, 27, 1); ohne Zahlen (). Nur die Zahlen (ohne -beta1)."""
    m = _VERSION.search(text or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def version_text(text):
    """'v1.1-beta1' -> '1.1-beta1', 'v0.27' -> '0.27' (Anzeige, Vergleich mit VERSION)."""
    m = _VERSION.search(text or "")
    if not m:
        return text or ""
    return m.group(1) + (f"-{m.group(2).lower()}{m.group(3)}" if m.group(2) else "")


def _schluessel(text, n):
    """Vergleichsschlüssel: Zahlen auf n Stellen aufgefüllt, dann Stufe (Vorabversion vor fertig)."""
    m = _VERSION.search(text or "")
    zahlen = list(version_tupel(text))
    zahlen += [0] * (n - len(zahlen))
    if m and m.group(2):
        return zahlen, (0, VORAB[m.group(2).lower()], int(m.group(3) or 0))
    return zahlen, (1, 0, 0)


def neuer(a, b):
    """Ist Version a neuer als b? 0.27 > 0.26.3, 0.27 == 0.27.0, 1.1 > 1.1-rc1 > 1.1-beta2 > 1.0.6."""
    n = max(len(version_tupel(a)), len(version_tupel(b)))
    return _schluessel(a, n) > _schluessel(b, n)


def gleich(a, b):
    return not neuer(a, b) and not neuer(b, a)


# -- Netz -------------------------------------------------------------------------------------
class _OhneWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _oeffnen(url, accept="application/vnd.github+json", zeitlimit=ZEITLIMIT):
    """GET mit Weiterleitungen von Hand (der Accept-Kopf soll mitgehen, die Anzahl ist begrenzt)."""
    oeffner = urllib.request.build_opener(_OhneWeiterleitung)
    for __ in range(6):
        kopf = {"User-Agent": AGENT, "Accept": accept}
        try:
            return oeffner.open(urllib.request.Request(url, headers=kopf), timeout=zeitlimit)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urllib.parse.urljoin(url, e.headers["Location"])
                continue
            raise
    raise UpdateFehler(_("Too many redirects."))


def _fehlertext(e, repo):
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 404:
            return _("No release found for {repo} (the repository does not exist or has no release yet)."
                     ).format(repo=repo)
        if e.code in (401, 403, 429):
            return _("GitHub refused the request ({code}), probably too many requests in the last hour; try "
                     "again later.").format(code=e.code)
        return _("GitHub answered with error {code}.").format(code=e.code)
    grund = getattr(e, "reason", e)
    return _("No connection to GitHub ({fehler}).").format(fehler=grund)


def _json(url, repo):
    try:
        with _oeffnen(url) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UpdateFehler(_fehlertext(e, repo)) from e


def _release(daten):
    tag = daten.get("tag_name") or ""
    return {"version": version_text(tag), "tag": tag,
            "name": daten.get("name") or tag, "text": daten.get("body") or "",
            "datum": (daten.get("published_at") or "")[:10], "seite": daten.get("html_url") or "",
            "vorab": bool(daten.get("prerelease")), "zipball": daten.get("zipball_url") or "",
            "dateien": [{"name": a.get("name", ""), "url": a.get("url", ""), "groesse": a.get("size") or 0,
                         "browser": a.get("browser_download_url", "")} for a in daten.get("assets") or []]}


def release_holen(repo=REPO, vorab=False):
    """Neueste Veröffentlichung (ohne Entwürfe; Vorabversionen nur mit vorab=True)."""
    repo = (repo or REPO).strip().strip("/")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise UpdateFehler(_("Repository must look like owner/name, not \"{repo}\".").format(repo=repo))
    if not vorab:
        return _release(_json(f"{API}/repos/{repo}/releases/latest", repo))
    liste = [d for d in _json(f"{API}/repos/{repo}/releases?per_page=20", repo) if not d.get("draft")]
    if not liste:
        raise UpdateFehler(_fehlertext(urllib.error.HTTPError("", 404, "", {}, None), repo))
    erg = None
    for rel in (_release(d) for d in liste):
        if erg is None or neuer(rel["version"], erg["version"]):
            erg = rel
    return erg


def datei_fuer(release, art):
    """(name, url, accept) des Downloads für die Installationsart oder None."""
    if art == "windows":
        for d in release["dateien"]:
            if SETUP_MUSTER.match(d["name"]):
                return d["name"], d["url"], "application/octet-stream"
        return None
    if art == "linux" and release.get("zipball"):
        return f"bookbench-{release['version']}.zip", release["zipball"], "application/vnd.github+json"
    return None


def herunterladen(url, ziel, accept="application/octet-stream", fortschritt=None, abbruch=None):
    """Lädt nach ziel (erst als .teil, dann umbenannt). fortschritt(geladen, gesamt) wird
    zwischendurch aufgerufen, abbruch() -> True bricht ab."""
    ziel = Path(ziel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    teil = ziel.with_name(ziel.name + ".teil")
    try:
        with _oeffnen(url, accept, zeitlimit=60) as r, open(teil, "wb") as f:
            gesamt = int(r.headers.get("Content-Length") or 0)
            geladen = 0
            while True:
                if abbruch and abbruch():
                    raise UpdateFehler(_("Download cancelled."))
                stueck = r.read(1 << 16)
                if not stueck:
                    break
                f.write(stueck)
                geladen += len(stueck)
                if fortschritt:
                    fortschritt(geladen, gesamt)
        os.replace(teil, ziel)
    except (urllib.error.URLError, OSError) as e:
        teil.unlink(missing_ok=True)
        raise UpdateFehler(_("Download failed ({fehler}).").format(fehler=getattr(e, "reason", e))) from e
    except BaseException:
        teil.unlink(missing_ok=True)
        raise
    return ziel


def sha256(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for stueck in iter(lambda: f.read(1 << 20), b""):
            h.update(stueck)
    return h.hexdigest()


def summen_holen(release):
    """{dateiname: sha256} aus der Datei SHA256SUMS der Veröffentlichung, {} ohne."""
    d = next((d for d in release["dateien"] if d["name"] == SUMMEN), None)
    if not d:
        return {}
    try:
        with _oeffnen(d["url"], "application/octet-stream") as r:
            text = r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        raise UpdateFehler(_("Could not load the checksums ({fehler}).").format(fehler=getattr(e, "reason", e))) from e
    summen = {}
    for zeile in text.splitlines():
        teile = zeile.split()
        if len(teile) >= 2 and re.fullmatch(r"[0-9a-fA-F]{64}", teile[0]):
            summen[teile[-1].lstrip("*")] = teile[0].lower()
    return summen


def pruefen(pfad, name, summen):
    """True: Prüfsumme stimmt, None: keine angegeben (Quelltext-ZIP), sonst UpdateFehler."""
    soll = summen.get(name)
    if not soll:
        return None
    if sha256(pfad) != soll:
        raise UpdateFehler(_("Checksum of {name} does not match - the download is damaged or not the "
                             "published file.").format(name=name))
    return True


def download_ordner():
    return Path(tempfile.gettempdir()) / "bookbench_update"


# -- Einspielen -------------------------------------------------------------------------------
def _version_im_ordner(ordner):
    hilfe = Path(ordner) / "bookbench" / "ui" / "help.py"
    try:
        m = re.search(r'^VERSION = "([^"]+)"', hilfe.read_text(encoding="utf-8"), re.M)
    except OSError:
        return ""
    return m.group(1) if m else ""


def version_im_zip(zip_pfad):
    """Version aus bookbench/ui/help.py im Quelltext-ZIP (ohne Auspacken), "" wenn nicht lesbar."""
    try:
        with zipfile.ZipFile(zip_pfad) as z:
            name = next((n for n in z.namelist() if n.endswith("bookbench/ui/help.py")
                         and n.count("/") <= 3), None)
            if not name:
                return ""
            text = z.read(name).decode("utf-8", "replace")
    except (OSError, zipfile.BadZipFile, KeyError):
        return ""
    m = re.search(r'^VERSION = "([^"]+)"', text, re.M)
    return m.group(1) if m else ""


def vorhandene_datei_ok(pfad, name, summen, erwartet=""):
    """Darf ein schon geladener Download (früher abgebrochenes Update) wiederverwendet werden?
    Nur mit passender Prüfsumme; ohne Prüfsumme (Quelltext-ZIP unter Linux) nur, wenn die Version
    im ZIP stimmt - sonst würde eine einmal falsche Datei bei jedem Versuch wieder genommen."""
    if pruefen(pfad, name, summen):
        return True
    if summen.get(name):
        return False
    ist = version_im_zip(pfad)
    return bool(erwartet and ist and gleich(ist, erwartet))


def linux_einspielen(zip_pfad, programm=None, erwartet=""):
    """Tauscht programm/ gegen den Inhalt des Quelltext-ZIPs (GitHub legt alles in einen
    Ordner <besitzer>-<repo>-<commit>/). Erst wird daneben ausgepackt und geprüft (start.py,
    bookbench/, Version), dann umbenannt: programm -> programm.alt, neu -> programm; zum
    Schluss wird programm.alt gelöscht. Geht unterwegs etwas schief, bleibt das alte stehen.
    Gibt die eingespielte Version zurück."""
    programm = Path(programm or PROGRAMM).resolve()
    if installationsart(programm) != "linux":
        raise UpdateFehler(_("This copy was not installed with install.sh; it is not replaced."))
    neu = programm.with_name(programm.name + ".neu")
    alt = programm.with_name(programm.name + ".alt")
    for p in (neu, alt):
        if p.exists():
            shutil.rmtree(p)
    try:
        neu.mkdir()
        with zipfile.ZipFile(zip_pfad) as z:
            for zi in z.infolist():
                ziel = (neu / zi.filename).resolve()
                if neu not in ziel.parents and ziel != neu:   # keine Pfade außerhalb
                    raise UpdateFehler(_("The archive contains unsafe paths."))
            z.extractall(neu)
        eintraege = [p for p in neu.iterdir()]
        wurzel = eintraege[0] if len(eintraege) == 1 and eintraege[0].is_dir() else neu
        if not (wurzel / "start.py").is_file() or not (wurzel / "bookbench" / "app.py").is_file():
            raise UpdateFehler(_("The archive does not contain Bookbench (start.py and bookbench/ are missing)."))
        version = _version_im_ordner(wurzel)
        if erwartet and version and not gleich(version, erwartet):
            raise UpdateFehler(_("The archive contains version {ist} instead of {soll}.").format(
                ist=version, soll=erwartet))
        if wurzel != neu:                                # Inhalt eine Ebene hoch
            for p in list(wurzel.iterdir()):
                shutil.move(str(p), str(neu / p.name))
            wurzel.rmdir()
    except (OSError, zipfile.BadZipFile) as e:
        shutil.rmtree(neu, ignore_errors=True)
        raise UpdateFehler(_("Unpacking failed ({fehler}).").format(fehler=e)) from e
    except BaseException:
        shutil.rmtree(neu, ignore_errors=True)
        raise
    os.replace(programm, alt)
    try:
        os.replace(neu, programm)
    except OSError as e:
        os.replace(alt, programm)                        # zurück zum alten Stand
        raise UpdateFehler(_("Replacing the program failed ({fehler}).").format(fehler=e)) from e
    shutil.rmtree(alt, ignore_errors=True)
    _marke_nachtragen(programm, version)
    return version


def _marke_nachtragen(programm, version):
    marke = Path(programm).parent / MARKE
    try:
        angaben = json.loads(marke.read_text(encoding="utf-8"))
        angaben["version"] = version
        marke.write_text(json.dumps(angaben, ensure_ascii=False, indent=1), encoding="utf-8")
    except (OSError, ValueError):
        pass


def windows_modus(exe=None, lokal=None):
    """"/CURRENTUSER" oder "/ALLUSERS": wie die laufende Installation eingerichtet ist. Ohne
    diese Angabe zeigt das Setup trotz /SILENT die Frage "nur für mich / für alle"
    (PrivilegesRequiredOverridesAllowed=dialog), unter Wine nachgestellt. Pro Benutzer liegt
    Bookbench unter %LOCALAPPDATA%, für alle unter Program Files."""
    exe = Path(exe or sys.executable).resolve()
    lokal = lokal if lokal is not None else os.environ.get("LOCALAPPDATA", "")
    if not lokal:                                       # unbekannt (kein Windows): Standard des Setups
        return "/CURRENTUSER"
    try:
        return "/CURRENTUSER" if exe.is_relative_to(Path(lokal).resolve()) else "/ALLUSERS"
    except (OSError, ValueError):
        return "/CURRENTUSER"


def windows_befehl(setup, modus=None):
    """Installer still, ohne Rückfrage; er übernimmt Ordner und Aufgaben der vorhandenen
    Installation und startet Bookbench danach selbst (bookbench.iss, [Run] mit WizardSilent)."""
    return [str(setup), "/SILENT", "/SP-", "/NOCANCEL", "/NORESTART", "/CLOSEAPPLICATIONS",
            modus or windows_modus()]


def windows_starten(setup, popen=subprocess.Popen):
    return popen(windows_befehl(setup), close_fds=True)
