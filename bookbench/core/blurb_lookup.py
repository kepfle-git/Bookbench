# -*- coding: utf-8 -*-
"""
blurb_lookup.py - Klappentexte nachschlagen, ohne Oberfläche (seit 2.0-beta3 aus tk/app.py gelöst).

Reihenfolge je Buch: die kostenlosen Quellen (Google Books, Open Library; Einstellung kostenlos), dann
Claude mit dem passenden Quellprofil (core/blurbs). Was schon versucht wurde, steht im Zwischenspeicher
(blurbs_cache.json, Schlüssel "Titel|Autor") und kostet beim nächsten Mal nichts:
    {"blurb": …, "source": …}              gefunden
    {"none": true, "versucht": [...]}      nichts gefunden; "frei" bzw. "claude:<Profilkennung>"
    null                                   bis 0.20: im Lexicanum nichts gefunden

  schluessel(b)               "Titel|Autor"
  api_client(e)               (client, fehlertext) - anthropic mit dem Schlüssel aus den Einstellungen
  plan(buecher, cache, e)     [(Buch, Schritte, schon versucht)] ohne bereits Versuchtes
  ohne_claude(plan)           derselbe Plan nur mit den kostenlosen Schritten
  zaehlen(plan)               (mit_claude, mit_frei)
  ausfuehren(plan, client, e, melden, ergebnis)   im Hilfsthread; melden(text) für die Statuszeile,
                              ergebnis(b, schluessel, eintrag) je Buch (eintrag für den Zwischenspeicher
                              oder None, wenn nichts zu merken ist); gibt den Abschlusstext zurück
  quelle_text(...), zusammenfassung(zaehler, mehrere)
"""
import hashlib
import os
from types import SimpleNamespace

from bookbench.core import blurbs
from bookbench.core import settings as kei
from bookbench.i18n import _, ngettext


def schluessel(b):
    return f"{b.titel}|{b.autor}"


def api_client(e):
    try:
        import anthropic
    except ImportError:
        return None, _("The anthropic package is missing.\n\npip install anthropic")
    key = e.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None, _("No API key. Settings > Blurbs.")
    return anthropic.Anthropic(api_key=key), None


def versucht(cache, schl):
    if schl not in cache:
        return set()
    eintrag = cache[schl]
    if eintrag is None:                 # gilt für das Lexicanum-Profil, wie es auch eingestellt ist
        return {"claude:lexicanum"}
    return set(eintrag.get("versucht") or [])


def profil_kennung(p):
    """Ändern sich Seiten, Suche oder Hinweise eines Profils, wird neu nachgeschlagen."""
    inhalt = "|".join(str(p.get(k, "")) for k in ("seiten", "domains", "abschnitt", "thema", "websuche"))
    return f"{blurbs.profile_id(p)}-{hashlib.sha1(inhalt.encode('utf-8')).hexdigest()[:8]}"


def plan(buecher, cache, e):
    profile = kei.klappentext_profile(e)
    erg = []
    for b in buecher:
        schl = schluessel(b)
        if (cache.get(schl) or {}).get("blurb"):
            erg.append((b, [], set()))
            continue
        v, schritte = versucht(cache, schl), []
        if e.get("kostenlos", True) and "frei" not in v:
            schritte.append("frei")
        p = blurbs.profile_for(profile, b.verlag, b.reihe, b.autor)
        if p and not {"claude:" + profil_kennung(p), "claude:" + blurbs.profile_id(p)} & v:
            schritte.append(("claude", p))
        erg.append((b, schritte, v))
    return erg


def zaehlen(pl):
    mit_claude = sum(1 for __, sch, __ in pl if any(isinstance(x, tuple) for x in sch))
    mit_frei = sum(1 for __, sch, __ in pl if "frei" in sch)
    return mit_claude, mit_frei


def ohne_claude(pl):
    return [(b, [x for x in sch if x == "frei"], v) for b, sch, v in pl]


def quelle_text(quelle, art, fehler="", n=None):
    """Ergebnis einer kostenlosen Quelle als Text (n: Anzahl Bücher für die Zusammenfassung)."""
    if art == blurbs.FEHLER:
        return f"{quelle}: {fehler}" + (f" ({n}×)" if n and n > 1 else "")
    if art == blurbs.KEIN_TEXT:
        if n is None:
            return _("{quelle}: book found, but no blurb stored").format(quelle=quelle)
        return ngettext("{quelle}: no blurb stored for {n} book", "{quelle}: no blurb stored for {n} books",
                        n).format(quelle=quelle, n=n)
    if n is None:
        return _("{quelle}: book not found").format(quelle=quelle)
    return ngettext("{quelle}: {n} book not found", "{quelle}: {n} books not found", n).format(quelle=quelle, n=n)


def zusammenfassung(zaehler, mehrere):
    """Abschlussmeldung je Quelle: Fehler (z. B. Kontingent erschöpft), kein Text, nicht gefunden."""
    teile = [quelle_text(q, art, fehler, n if mehrere else None)
             for (q, art, fehler), n in sorted(zaehler.items(), key=lambda x: (x[0][1] != blurbs.FEHLER, x[0]))]
    return ("; ".join(teile) + ".") if teile else ""


def einstellungen_anwenden(e):
    blurbs.MIN_LAENGE = int(e.get("kt_min", 80))
    blurbs.MAX_LAENGE = int(e.get("kt_max", 4000))
    blurbs.GOOGLE_KEY = e.get("google_key", "") or ""


def ausfuehren(pl, client, e, melden, ergebnis, ohne_schluessel=False):
    args = SimpleNamespace(model=e["modell"])
    zaehler = {}                                    # (Quelle, Kennung, Fehlertext) -> Anzahl Bücher
    gefunden = 0
    for i, (b, schritte, v) in enumerate(pl, 1):
        treffer = None
        for schritt in schritte:
            melden(_("Looking up ({i}/{n}): {name} …").format(i=i, n=len(pl), name=b.name))
            if schritt == "frei":
                bericht = []
                treffer, fehler = blurbs.free_look_up(b.titel, b.autor, b.isbn, b.sprache, bericht=bericht)
                for eintrag in bericht:
                    if eintrag[1] != blurbs.TREFFER:
                        zaehler[eintrag] = zaehler.get(eintrag, 0) + 1
                # Ergebnis je Quelle am Buch merken (die Klappentext-Tafel zeigt es), nur ohne Treffer
                b.kt_nachschlag = "" if treffer else "; ".join(quelle_text(*x) for x in bericht)
                if not fehler and not treffer:      # Netzfehler (auch 429): nicht als versucht merken
                    v.add("frei")
            else:
                try:
                    treffer = blurbs.look_up(client, args, b.titel, b.autor, b.reihe, schritt[1], b.sprache)
                except Exception as fehler:
                    melden(f"{b.name}: " + _("API error ({fehler})").format(fehler=fehler))
                    continue
                if not treffer:
                    v.add("claude:" + profil_kennung(schritt[1]))
            if treffer:
                break
        if treffer:
            gefunden += 1
            ergebnis(b, schluessel(b), treffer)
        elif schritte:
            ergebnis(b, schluessel(b), {"none": True, "versucht": sorted(v)})
        else:
            ergebnis(b, schluessel(b), None)
    text = ngettext("Look-up finished ({n} book).", "Look-up finished ({n} books).", len(pl)).format(n=len(pl))
    if len(pl) > 1:
        text += " " + ngettext("{n} blurb found.", "{n} blurbs found.", gefunden).format(n=gefunden)
    quellen = zusammenfassung(zaehler, len(pl) > 1)
    if quellen:
        text += " " + quellen
    if ohne_schluessel:
        text += " " + _("Claude was not asked (no API key).")
    return text
