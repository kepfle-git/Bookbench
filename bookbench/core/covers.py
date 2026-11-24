# -*- coding: utf-8 -*-
"""
covers.py - Titelbilder: Größe erkennen, für das EPUB aufbereiten, nachschlagen.
Keine Oberfläche; Lesen und Schreiben im EPUB steckt in kobo_daten.

  bild_info(daten)                (Breite, Höhe, Format) aus dem Dateikopf, ohne Pillow
  vorbereiten(daten, format, …)   Bild ins Zielformat bringen, ggf. verkleinern (Pillow)
  nachschlagen(titel, autor, isbn, quellen)
                                  Kandidaten von Open Library und Google Books (kostenlos)

Format im EPUB: Ein vorhandenes Cover wird im selben Format und unter demselben Namen
ersetzt (JPEG bleibt JPEG). So bleiben Manifest und eine Titelseite, die das Bild zeigt,
gültig. Nur ein Buch ohne Cover bekommt eine neue Datei (JPEG) samt Manifest-Eintrag.
"""
import io
import json
import struct
import urllib.parse
import urllib.request

from bookbench.core import blurbs

OL_COVERS = "https://covers.openlibrary.org"
OL = "https://openlibrary.org"
GOOGLE = "https://www.googleapis.com/books/v1/volumes"
MEDIENTYP = {"jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}
ENDUNG = {"jpeg": "jpg", "png": "png", "gif": "gif", "webp": "webp"}
MIN_HOEHE = 300            # kleinere Kandidaten sind Vorschaubildchen, nicht brauchbar


# ---------------------------------------------------------------- Größe und Format
def bild_info(daten):
    """(Breite, Höhe, Format) oder None. Liest nur den Dateikopf; Format: jpeg, png, gif, webp."""
    if not daten or len(daten) < 16:
        return None
    try:
        if daten[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", daten[16:24])
            return w, h, "png"
        if daten[:6] in (b"GIF87a", b"GIF89a"):
            w, h = struct.unpack("<HH", daten[6:10])
            return w, h, "gif"
        if daten[:4] == b"RIFF" and daten[8:12] == b"WEBP":
            art = daten[12:16]
            if art == b"VP8X":
                return 1 + int.from_bytes(daten[24:27], "little"), 1 + int.from_bytes(daten[27:30], "little"), "webp"
            if art == b"VP8 ":
                w, h = struct.unpack("<HH", daten[26:30])
                return w & 0x3FFF, h & 0x3FFF, "webp"
            if art == b"VP8L":
                b = int.from_bytes(daten[21:25], "little")
                return (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1, "webp"
            return None
        if daten[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(daten):
                if daten[i] != 0xFF:
                    i += 1
                    continue
                marke = daten[i + 1]
                if marke in (0xD8, 0x01) or 0xD0 <= marke <= 0xD7:
                    i += 2
                    continue
                laenge = struct.unpack(">H", daten[i + 2:i + 4])[0]
                if marke in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", daten[i + 5:i + 9])
                    return w, h, "jpeg"
                i += 2 + laenge
    except struct.error:
        return None
    return None


def hat_pillow():
    import importlib.util
    return importlib.util.find_spec("PIL") is not None


def vorbereiten(daten, ziel_format=None, max_hoehe=0, qualitaet=90):
    """Bild fürs EPUB: im Zielformat (None = so lassen), höchstens max_hoehe Pixel hoch (0 = nie
    verkleinern). Ohne Pillow geht nur "so lassen"; dann RuntimeError, wenn umgewandelt werden müsste.
    Gibt die Bytes zurück."""
    info = bild_info(daten)
    if not info:
        raise ValueError("unknown image format")
    w, h, fmt = info
    ziel_format = ziel_format or fmt
    if ziel_format == fmt and not (max_hoehe and h > max_hoehe):
        return daten                                     # nichts zu tun: Original unverändert
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("Pillow")
    im = Image.open(io.BytesIO(daten))
    im.load()
    if max_hoehe and im.height > max_hoehe:
        im = im.resize((max(1, round(im.width * max_hoehe / im.height)), max_hoehe), Image.LANCZOS)
    aus = io.BytesIO()
    if ziel_format == "jpeg":
        if im.mode not in ("RGB", "L"):
            hinten = Image.new("RGB", im.size, "white")       # Transparenz auf Weiß, wie auf dem Papier
            hinten.paste(im, mask=im.convert("RGBA").split()[-1])
            im = hinten
        im.save(aus, "JPEG", quality=int(qualitaet), optimize=True, progressive=False)
    elif ziel_format == "png":
        im.save(aus, "PNG", optimize=True)
    elif ziel_format == "gif":
        im.convert("P", palette=Image.ADAPTIVE).save(aus, "GIF")
    elif ziel_format == "webp":
        im.save(aus, "WEBP", quality=int(qualitaet))
    else:
        raise ValueError(ziel_format)
    return aus.getvalue()


# ---------------------------------------------------------------- Nachschlagen
def _holen(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Bookbench (cover lookup)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _json(url):
    return json.loads(_holen(url).decode("utf-8"))


def _kandidat(url, quelle):
    """Bild laden und prüfen; None bei Fehler, Platzhalter oder zu klein."""
    try:
        daten = _holen(url)
    except Exception:
        return None
    info = bild_info(daten)
    if not info or info[1] < MIN_HOEHE:
        return None
    return {"url": url, "quelle": quelle, "daten": daten, "w": info[0], "h": info[1], "format": info[2]}


def _ol_urls(titel, autor, isbn, basis_covers, basis):
    urls = []
    if isbn:
        urls.append(f"{basis_covers}/b/isbn/{isbn}-L.jpg?default=false")
    p = {"title": titel, "fields": "key,title,author_name,cover_i,edition_count", "limit": 5}
    if autor:
        p["author"] = autor.split(",")[0]
    try:
        for d in _json(f"{basis}/search.json?" + urllib.parse.urlencode(p)).get("docs") or []:
            if d.get("cover_i"):
                urls.append(f"{basis_covers}/b/id/{d['cover_i']}-L.jpg?default=false")
    except Exception:
        pass
    return urls


def _https(url):
    """Google liefert die Bildadressen mit http://; books.google.com kann auch https."""
    return url.replace("http://books.google.", "https://books.google.")


def _google_urls(titel, autor, isbn, basis):
    q = f"isbn:{isbn}" if isbn else f'intitle:"{titel}"' + (f' inauthor:"{autor.split(",")[0]}"' if autor else "")
    urls = []
    try:
        for item in _json(f"{basis}?" + urllib.parse.urlencode(blurbs.google_parameter(
                {"q": q, "maxResults": 5}))).get("items") or []:
            links = (item.get("volumeInfo") or {}).get("imageLinks") or {}
            for k in ("extraLarge", "large", "medium"):
                if links.get(k):
                    urls.append(_https(links[k]))
                    break
            else:
                if links.get("thumbnail"):                # zoom=0 liefert die größte Fassung, wenn es eine gibt
                    urls.append(_https(links["thumbnail"]).replace("zoom=1", "zoom=0").replace("&edge=curl", ""))
    except Exception:
        pass
    return urls


def nachschlagen(titel, autor="", isbn="", quellen=("openlibrary", "google"), hoechstens=8):
    """Kandidaten [{url, quelle, daten, w, h, format}], größte zuerst, ohne doppelte Bilder."""
    urls = []
    if "openlibrary" in quellen:
        urls += [(u, "Open Library") for u in _ol_urls(titel, autor, isbn, OL_COVERS, OL)]
    if "google" in quellen:
        urls += [(u, "Google Books") for u in _google_urls(titel, autor, isbn, GOOGLE)]
    erg, gesehen = [], set()
    for url, quelle in list(dict.fromkeys(urls))[:hoechstens * 2]:
        k = _kandidat(url, quelle)
        if k and k["daten"] not in gesehen:
            gesehen.add(k["daten"])
            erg.append(k)
        if len(erg) >= hoechstens:
            break
    return sorted(erg, key=lambda k: -k["w"] * k["h"])
