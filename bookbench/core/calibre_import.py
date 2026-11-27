# -*- coding: utf-8 -*-
"""
calibre_import.py - einmaliger Import der Metadaten aus einer Calibre-Bibliothek (seit 1.3-beta4).
Ersetzt die geplante dauerhafte Calibre-Schnittstelle: Calibre-Daten einmal in die Bücher schreiben,
danach braucht man Calibre nicht mehr.

  finden(pfad)          metadata.db im Ordner (oder die Datei selbst), sonst None
  lesen(db)             (eintraege, spalten): je Calibre-Buch {"id", "uuid", "titel", "autor", "isbn",
                        "werte": {feld: text}, "beschreibung": text}; spalten = {"#label": Felddefinition}
  zuordnen(buecher, eintraege)   ({schluessel: (eintrag, art)}, [nicht zugeordnete Bücher]);
                        art = "uuid" | "isbn" | "titel" (Titel + erster Autor, nur wenn eindeutig)
  vorschlaege(werte, eintrag, felder, nur_leere)   [(feld, jetzt, neu)] - wo Calibre etwas anderes hat

metadata.db wird nur lesend geöffnet (sqlite "mode=ro"): Lesen stört ein laufendes Calibre nicht,
Schreiben von außen dagegen schon (Calibre hält die Daten im Speicher und schreibt sie zurück).

Aufbau der Datenbank (Calibre, db/schema): books (title, author_sort, series_index, uuid, …),
authors/series/publishers/tags/languages je mit books_*_link, identifiers (type, val), comments (HTML).
Eigene Spalten: custom_columns (label, name, datatype, display JSON, is_multiple, normalized);
normalisiert = Werte in custom_column_N, Zuordnung in books_custom_column_N_link (bei "series" mit extra =
Nummer), sonst custom_column_N (book, value). "composite" (berechnete Spalten) speichert Calibre nicht.
"""
import json
import re
import sqlite3
from pathlib import Path

from bookbench.core import metadata as km
from bookbench.core.library import _norm_titel, html_zu_text, nummer_text

UNBEKANNT = km.UNBEKANNT


def finden(pfad):
    p = Path(pfad).expanduser()
    if p.is_file() and p.name == "metadata.db":
        return p
    if (p / "metadata.db").is_file():
        return p / "metadata.db"
    return None


def _verbinden(db):
    uri = Path(db).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _definition(zeile):
    """Felddefinition wie Calibres field_metadata (so schreibt sie Calibre auch ins Buch)."""
    try:
        display = json.loads(zeile["display"] or "{}")
    except ValueError:
        display = {}
    art = zeile["datatype"]
    mehrfach = {}
    if zeile["is_multiple"] and art == "text":
        mehrfach = ({"cache_to_list": "|", "ui_to_list": "&", "list_to_ui": " & "} if display.get("is_names")
                    else {"cache_to_list": ",", "ui_to_list": ",", "list_to_ui": ", "})
    label = zeile["label"]
    return {"table": f"custom_column_{zeile['id']}", "column": "value", "datatype": art,
            "is_multiple": mehrfach, "kind": "field", "name": zeile["name"], "search_terms": ["#" + label],
            "label": label, "colnum": zeile["id"], "display": display, "is_custom": True,
            "is_category": art in ("text", "series", "enumeration", "rating") and bool(zeile["normalized"]),
            "link_column": "value", "category_sort": "value", "is_csp": False, "is_editable": True,
            "rec_index": 0, "key": "#" + label, "#value#": None, "#extra#": None}


def _spalten(con):
    erg = {}
    try:
        zeilen = con.execute("SELECT id, label, name, datatype, display, is_multiple, normalized, mark_for_delete "
                             "FROM custom_columns").fetchall()
    except sqlite3.Error:
        return erg
    for z in zeilen:
        if z["mark_for_delete"] or z["datatype"] == "composite":
            continue
        erg["#" + z["label"]] = (z, _definition(z))
    return erg


def _spaltenwerte(con, z):
    """{buch_id: Wert} einer eigenen Spalte (Listen bei Mehrfachwerten)."""
    n, erg = z["id"], {}
    try:
        if z["normalized"]:
            sql = (f"SELECT l.book AS book, v.value AS value FROM books_custom_column_{n}_link l "
                   f"JOIN custom_column_{n} v ON v.id = l.value ORDER BY l.id")
            for r in con.execute(sql):
                if z["is_multiple"]:
                    erg.setdefault(r["book"], []).append(r["value"])
                else:
                    erg[r["book"]] = r["value"]
        else:
            for r in con.execute(f"SELECT book, value FROM custom_column_{n}"):
                erg[r["book"]] = r["value"]
    except sqlite3.Error:
        pass
    return erg


def _liste(con, sql):
    erg = {}
    for r in con.execute(sql):
        erg.setdefault(r[0], []).append(r[1])
    return erg


def lesen(db):
    con = _verbinden(db)
    try:
        autoren = _liste(con, "SELECT l.book, a.name FROM books_authors_link l JOIN authors a ON a.id = l.author "
                              "ORDER BY l.id")
        reihen = {b: v[0] for b, v in _liste(con, "SELECT l.book, s.name FROM books_series_link l "
                                                   "JOIN series s ON s.id = l.series").items()}
        verlage = {b: v[0] for b, v in _liste(con, "SELECT l.book, p.name FROM books_publishers_link l "
                                                    "JOIN publishers p ON p.id = l.publisher").items()}
        tags = _liste(con, "SELECT l.book, t.name FROM books_tags_link l JOIN tags t ON t.id = l.tag ORDER BY t.name")
        sprachen = _liste(con, "SELECT l.book, g.lang_code FROM books_languages_link l "
                               "JOIN languages g ON g.id = l.lang_code ORDER BY l.item_order")
        isbns = {b: v[0] for b, v in _liste(con, "SELECT book, val FROM identifiers WHERE type = 'isbn'").items()}
        texte = {r[0]: r[1] for r in con.execute("SELECT book, text FROM comments")}
        spalten = _spalten(con)
        werte_spalten = {k: _spaltenwerte(con, z) for k, (z, __) in spalten.items()}
        eintraege = []
        for b in con.execute("SELECT * FROM books ORDER BY id"):
            i = b["id"]
            titel = b["title"] or ""
            namen = [a for a in autoren.get(i, []) if a not in UNBEKANNT]
            isbn = re.sub(r"[^\dXx]", "", isbns.get(i) or "").upper()
            w = {"titel": "" if titel in UNBEKANNT else titel, "autoren": " & ".join(namen),
                 "autor_sort": (b["author_sort"] or "") if namen else "",
                 "reihe": reihen.get(i, ""), "nummer": nummer_text(b["series_index"]) if reihen.get(i) else "",
                 "verlag": verlage.get(i, ""),
                 "datum": km.datum_norm((b["pubdate"] if "pubdate" in b.keys() else "") or ""),
                 "sprache": km.sprache_kurz((sprachen.get(i) or [""])[0]),
                 "isbn": isbn, "schlagwoerter": ", ".join(tags.get(i, []))}
            for k, (__, fm) in spalten.items():
                if i in werte_spalten[k]:
                    w[k] = km.spalten_text(dict(fm, **{"#value#": werte_spalten[k][i]}))
            eintraege.append({"id": i, "uuid": b["uuid"] or "", "titel": w["titel"],
                              "autor": namen[0] if namen else "", "isbn": isbn, "werte": w,
                              "beschreibung": html_zu_text(texte.get(i) or "")})
        return eintraege, {k: fm for k, (__, fm) in spalten.items()}
    finally:
        con.close()


def zuordnen(buecher, eintraege):
    nach_uuid = {e["uuid"]: e for e in eintraege if e["uuid"]}
    nach_isbn, nach_titel = {}, {}
    for e in eintraege:
        if e["isbn"]:
            nach_isbn.setdefault(e["isbn"], []).append(e)
        nach_titel.setdefault((_norm_titel(e["titel"]), _norm_titel(e["autor"])), []).append(e)
    erg, ohne = {}, []
    for b in buecher:
        if b.fehler:
            continue
        e, art = None, ""
        if b.uuid and b.uuid in nach_uuid:
            e, art = nach_uuid[b.uuid], "uuid"
        isbn = (b.meta or {}).get("isbn", "")
        if e is None and isbn and len(nach_isbn.get(isbn, [])) == 1:
            e, art = nach_isbn[isbn][0], "isbn"
        if e is None:
            autor = km.liste((b.meta or {}).get("autoren", "") or b.autor)
            treffer = nach_titel.get((_norm_titel(b.titel), _norm_titel(autor[0] if autor else "")), [])
            if len(treffer) == 1:
                e, art = treffer[0], "titel"
        if e is None:
            ohne.append(b)
        else:
            erg[b.schluessel] = (e, art)
    return erg, ohne


def vorschlaege(werte, eintrag, felder, nur_leere=False):
    """[(feld, jetzt, neu)]: Felder, in denen Calibre einen Wert hat, der abweicht (nur_leere: nur dort, wo
    das Buch nichts hat)."""
    erg = []
    for f in felder:
        neu = km._norm(eintrag["werte"].get(f, ""))
        jetzt = km._norm(werte.get(f, ""))
        if not neu or km.gleich(f, jetzt, neu):
            continue
        if nur_leere and jetzt:
            continue
        erg.append((f, jetzt, neu))
    return erg
