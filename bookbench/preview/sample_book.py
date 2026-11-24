# -*- coding: utf-8 -*-
"""
sample_book.py - Blindtext-Bücher für die KOReader-Werkbank (seit 1.4). Keine Oberfläche.

  blindtext_buch(ziel, ...)     kleines EPUB 3 mit drei Kapiteln Blindtext, auf Wunsch mit Cover
  bibliothek(ordner, anzahl)    Blindtext-Bücher mit farbigen Covern in zwei Reihen (Startbildschirm)
  png(breite, hoehe, farbe, streifen)   einfaches PNG ohne Pillow

Titel, Autor und Reihe stehen in den Metadaten, damit Bookends-Platzhalter etwas zeigen.
"""
import struct
import zipfile
import zlib
from pathlib import Path

LOREM = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore "
         "et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut "
         "aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum "
         "dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui "
         "officia deserunt mollit anim id est laborum.")
FARBEN = ((150, 30, 30), (30, 90, 150), (40, 120, 60), (120, 80, 20), (90, 40, 120), (30, 110, 110),
          (60, 60, 60), (160, 100, 30))


def png(breite, hoehe, farbe, streifen):
    """Fläche mit hellem Querstreifen als PNG-Bytes."""
    zeilen = bytearray()
    for y in range(hoehe):
        zeilen.append(0)
        zeilen.extend(bytes(streifen if hoehe * 0.55 < y < hoehe * 0.7 else farbe) * breite)

    def block(art, daten):
        return struct.pack(">I", len(daten)) + art + daten + struct.pack(">I", zlib.crc32(art + daten) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + block(b"IHDR", struct.pack(">IIBBBBB", breite, hoehe, 8, 2, 0, 0, 0))
            + block(b"IDAT", zlib.compress(bytes(zeilen), 9)) + block(b"IEND", b""))


def blindtext_buch(ziel, titel="Lorem Ipsum", autor="Dolor Sit", reihe="Bookbench", nr=1, cover=None,
                   kennung="bookbench-sample", kapitel_anzahl=3):
    ziel = Path(ziel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    kapitel = [(f"Chapter {i}", [LOREM] * 14) for i in range(1, kapitel_anzahl + 1)]
    items = "".join(f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>'
                    for i in range(len(kapitel)))
    spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(kapitel)))
    with zipfile.ZipFile(ziel, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile '
                   'full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        if cover:
            items += '<item id="cover" href="cover.png" media-type="image/png" properties="cover-image"/>'
            z.writestr("OEBPS/cover.png", cover)
        z.writestr("OEBPS/content.opf", f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">{kennung}</dc:identifier>
<dc:title>{titel}</dc:title><dc:creator>{autor}</dc:creator><dc:language>en</dc:language>
<meta property="dcterms:modified">2026-11-24T00:00:00Z</meta>{'<meta name="cover" content="cover"/>' if cover else ''}
<meta name="calibre:series" content="{reihe}"/><meta name="calibre:series_index" content="{nr}"/></metadata>
<manifest>{items}<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest>
<spine>{spine}</spine></package>''')
        nav = "".join(f'<li><a href="c{i}.xhtml">{t}</a></li>' for i, (t, __) in enumerate(kapitel))
        z.writestr("OEBPS/nav.xhtml", '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
                   'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Nav</title></head><body>'
                   f'<nav epub:type="toc"><ol>{nav}</ol></nav></body></html>')
        for i, (t, absaetze) in enumerate(kapitel):
            text = "".join(f"<p>{a}</p>" for a in absaetze)
            z.writestr(f"OEBPS/c{i}.xhtml", '<?xml version="1.0" encoding="utf-8"?><html '
                       f'xmlns="http://www.w3.org/1999/xhtml"><head><title>{t}</title></head><body>'
                       f'<h1>{t}</h1>{text}</body></html>')
    return ziel


def bibliothek(ordner, anzahl=8):
    """Blindtext-Bücher mit Cover für den Startbildschirm (Bookshelf, Dateimanager)."""
    ordner = Path(ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    for i in range(anzahl):
        blindtext_buch(ordner / f"Sample Book {i + 1}.epub", titel=f"Sample Book {i + 1}",
                       autor=("Lorem Ipsum", "Dolor Sit")[i % 2], reihe=("Sample", "Second Sample")[i % 2],
                       nr=i // 2 + 1, cover=png(300, 450, FARBEN[i % len(FARBEN)], (235, 235, 235)),
                       kennung=f"bookbench-sample-{i + 1}")
    return ordner
