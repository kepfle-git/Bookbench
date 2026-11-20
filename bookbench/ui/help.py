# -*- coding: utf-8 -*-
"""
help.py - Versionsnummer und Hilfefenster von Bookbench.

  VERSION        bei jeder Änderung hochzählen
  THEMEN         (Elternthema, Kennung, Titel, Text), übersetzt; **fett**, Aufzählungen mit "-",
                 [[kennung]] = Verweis auf ein anderes Thema (zeigt dessen Titel, anklickbar)
  thema(bereich) Kennung des Themas zu einem Bereich
  HilfeFenster   Suche und Gliederung links, Text rechts; zeige(kennung) springt hin

Die Kennungen sind die Bereiche von App._bereich() bzw. feste Namen; "einst_<seite>" gehört zur
Seite <seite> des Einstellungsdialogs. Sie ändern sich mit der Sprache nicht.
"""
import re
import tkinter as tk
from tkinter import ttk

import keller_theme as kth
from bookbench.i18n import _

PROGRAMM = "Bookbench"
VERSION = "1.3-beta2"

# (Elternthema, Kennung, Titel, Text). Übersetzt beim Import. Text: **fett**, Aufzählungen mit "-",
# [[kennung]] = Verweis.
THEMEN = [
    ("", "ueberblick", _("Overview"), _("""
Bookbench edits EPUB and KEPUB files for KOReader: **chapter names** and levels in the table of contents, **blurbs**, **covers** and **metadata** (title, authors, series …). It also manages your own **dictionaries**, backs up the KOReader settings of the **e-reader** and, on Linux and macOS, shows a book in a **preview** with the settings from the e-reader.

**Workflow**
- Open a folder (Ctrl+O): the books folder on the e-reader, a copy on the computer or the Calibre library.
- In **Chapters** check the suggestions, change them if needed, apply them.
- In **Blurbs** and **Metadata** (with the cover) fill in what is missing, apply it.
- **Save** (Ctrl+S) writes all applied changes to the files. A backup of every file is made first.

Only the table of contents and the metadata (and the cover image) are changed, never the book text. Reading positions and highlights in KOReader stay valid.

**More**
- [[status]] - what the coloured dots and ⚠ mean
- [[tasten]]
- [[dateien]] - where settings, caches and backups are
- [[kosten]] - what is free, what costs money, what leaves the computer
- [[bereiche]] - one chapter per area
- [[einstellungen]] - every setting explained
- [[fehler]]
""")),
    ("ueberblick", "status", _("Status and markers"), _("""
The strip to the right of the book lists shows the status of each book:
- **red** ●: changed, not yet applied
- **yellow** ●: applied, not yet saved
- **green** ●: saved (since opening)
- **⚠**: something needs a look. In Chapters: questionable chapter names that are not decided yet; in Blurbs: no blurb; in Covers: no cover or a small one; everywhere: the file cannot be read.

Hovering over the strip explains the status in the status bar. The title bar shows an asterisk (*) after the version as long as something is not saved.

**Backgrounds**
- In the chapter table questionable rows are **red**; a click shows the reason in the status bar. **Yellowish**: only a number, no name found.
- In the lists of Blurbs and Covers, books without a blurb or cover have a **⚠** in the strip; the sidebar shows how many, like for Chapters.

The strip can be switched off: Settings > General > Interface ([[einst_oberflaeche]]).
""")),
    ("ueberblick", "tasten", _("Keyboard shortcuts"), _("""
**Everywhere**
- **Ctrl+O** open a folder, **F5** reload it
- **Ctrl+S** save
- **Ctrl+Enter** apply (current book, or the dictionary form)
- **Ctrl+F** search field of the current area (Chapters, Blurbs, Covers, Preview, Dictionary), otherwise of the library; **Esc** in a search field empties it
- **Ctrl+B** collapse and expand the sidebar
- **Ctrl+1 … 7** choose an area in the order of the sidebar (7: Preview, Linux/macOS only)
- **F1** help for the current area; in the settings: help for the page shown

**Chapter table**
- **Double-click** or **F2** edits the new name, **Enter** confirms, **Esc** cancels, **Del** restores the original
- **Tab** / **Shift+Tab** (or **Alt+→** / **Alt+←**): level down / up

**Dialogs**
- **Enter** = OK, **Esc** = cancel; in the cover choice a **double-click** takes a cover at once
""")),
    ("ueberblick", "dateien", _("Files and folders"), _("""
**Settings folder** (Windows: %APPDATA%\\Bookbench, Linux: ~/.config/bookbench)
- **einstellungen.json**: all settings, including the API key (plain text).
- **tocfix_entscheidungen.json**: applied chapter names, so they are suggested again for other copies of the same book.
- **blurbs_cache.json**: looked-up blurbs and what was already tried without success.
- **vorschau/**: the profile of the preview (Linux/macOS).
Until version 0.23 the two JSON files were next to the program; until 0.24 the folder was called Kobo-Werkstatt (the old name). Both are copied over once. Settings > Advanced shows the paths and opens the folder ([[einst_erweitert]]).

**Backup folder** (default: Bookbench Backups in your user folder)
- Backups of the books before each save: <name>_YYYYMMDD_HHMMSS.epub.
- **KOReader/**: backups of the KOReader settings from the E-reader area.
- **Wörterbücher/**: dictionary files before they are built again.

**In the book folder**
- Nothing is created next to the books. Only the EPUB files themselves change when saving.

**On the e-reader**
- Only what you copy or restore yourself: KOReader settings (in the KOReader folder, e.g. .adds/koreader on a Kobo, [[kobo_geraete]]), dictionaries (data/dict in the KOReader folder), and the books when the e-reader folder is opened and saved.
""")),
    ("ueberblick", "kosten", _("Costs and privacy"), _("""
**Free, without a key**
- Google Books and Open Library: blurbs ([[klappentexte_nachschlagen]]) and covers ([[cover_aendern]]). Sent: ISBN, title and author of the book.
- Everything else in the program runs on the computer only.

**Costs money: Claude (Anthropic API)**
- Blurbs that the free sources do not have: about 1 to 2 cents per book, with web search about 1 cent more.
- Dictionary: summarizing wiki articles, cross-checking, filling gaps with Claude: from a few cents per entry; before larger jobs the estimated cost is asked.
- You need your own API key (console.anthropic.com), billed by Anthropic. Without a key nothing goes to Claude.
- Sent: title, author, series and language of the book, the profile's instructions; for the dictionary the term, topic and article text. **Book text never leaves the computer** - searching the books for names happens locally.

**Avoiding costs**
- Results are kept in the cache; looking up again costs nothing ([[dateien]]).
- From Calibre costs nothing and is used first.
- Look up all only asks Claude for books the free sources do not know, and asks before it starts.
""")),
    ("", "bereiche", _("Areas"), _("""
The sidebar on the left switches between the areas (Ctrl+1 … 7):
- [[bibliothek]] - all books in a table
- [[kapitel]] - chapter names and levels
- [[klappentexte]] - blurbs
- [[metadaten]] - title, authors, series, publisher, language, ISBN, tags, own fields and the cover
- [[woerterbuch]] - your own dictionaries
- [[kobo]] - the connected e-reader: backups, dictionaries, ejecting
- [[vorschau]] - a book in the desktop KOReader (Linux/macOS)

The toolbar has the buttons of the current area on the left; on the right, separated, are the ones that always apply: Open, Reload, Save and Help. [[speichern]] applies to all book areas together.
""")),
    ("bereiche", "suche_filter", _("Search and filters in the lists"), _("""
Above the book lists of **Chapters**, **Blurbs**, **Metadata** and **Preview** there is a search field and (except in Preview) a filter. Each list has its own; they do not affect each other or the library.

- **Search** finds parts of the title, series or author, case does not matter. **✕** or **Esc** in the field empties search and filter.
- When a filter is active, the line above says how many books are shown: "Books: 3 of 12".
- The book you are working on stays selected as long as it fits. If it no longer fits, the next fitting book below is selected (otherwise the one above).
- **Apply** alone does not refill the list, so the book does not vanish while you work on it. Only changing search or filter, **Reload** or **Apply all** takes it out.
- If a hidden book is opened from elsewhere (double-click in the library), search and filter of that list are reset.
- Ctrl+F jumps to the search field of the current area.

**Filters**
- **Chapters**: With suggestions, Questionable names (⚠, not yet decided), Some without names (single entries only with a number), Changed chapters (applied or edited, not yet saved).
- **Blurbs**: No blurb, Only in Calibre (no blurb in the file, but Calibre has a description: **From Calibre**), Changed blurb.
- **Metadata**: Changed metadata or cover, Differs from Calibre, No author sort, No language, No ISBN, Edited in KOReader, No cover, Small cover (below the limit in [[einst_cover]]).
- **Preview**: search only.

Search and filters are not remembered; after a restart all books are shown again.
""")),
    ("bereiche", "bibliothek", _("Library"), _("""
All books of the opened folder (with all subfolders) with series, number, author, state of the chapters, blurb and cover.

- A click on a column header sorts (▲ ascending, ▼ descending), a second click reverses. Moving, hiding and widths of the columns: [[bibliothek_spalten]].
- **Search** filters by title, series and author; the **filter** shows only changed books, unreadable files or books whose series is not in the EPUB. Filters by chapters, blurbs and covers are above the lists of those areas ([[suche_filter]]).
- **Double-click** opens the book in the Chapters area.

**Columns**
- **Chapters**: **suggestions** (the book text has chapter names the table of contents lacks), **without names** (only numbers, nothing in the text either), **no names found** (only a few matches - probably coincidence, so nothing is suggested), **ok**, **ok (2 without names)** (almost all have names, single ones only a number, e.g. a prologue).
- **Blurb**: where it comes from (Google Books, Calibre, a website), "yes" if unknown, "in Calibre" if only Calibre has one, "changed".
- **Cover**: size of the title image in pixels, "changed" for a new one not yet saved.
- **Series**: from the EPUB; if it is only in Calibre or KOReader's data, the status bar says where from ([[bibliothek_calibre]]).
- **Publisher**, **Language**, **ISBN**: hidden at first; show them with a right-click on a header or View > Library columns.

**Filters** All books, Changed (anything not yet saved, or saved since opening), Unreadable files, No series in the EPUB.
""")),
    ("bibliothek", "bibliothek_spalten", _("Columns: sorting, moving, widths"), _("""
**Sorting**
- A click on a column header sorts by it, a second click reverses. The arrow ▲ (ascending) or ▼ (descending) shows the column.
- Series sorts by series, then number, then title; No. by number; Cover by the height in pixels (no cover first).
- Right-click on a header: **Sort ascending** / **Sort descending** for this column.

**Moving columns**
- Drag a header sideways (hold the mouse button or touchpad, move at least a few pixels): a blue line shows where it goes. Releasing there does not sort.
- Without dragging: right-click on the header > **Move "…" left** / **right**.

**Showing and hiding**
- Right-click on a header, or View > **Library columns**: one tick per column. A shown column comes back at its usual place. The last column cannot be hidden.

**Widths**
- Drag the line between two headers. The widths stay exactly as drawn, also after resizing the window or a restart; no column stretches by itself. If the columns are wider than the window, a scroll bar appears below.
- **Fit columns to the window** spreads the visible columns over the width, keeping their proportions.
- **Reset columns**: usual order, all columns, default widths fitted to the window.

Order, shown columns, widths and sorting are remembered in the settings.
""")),
    ("bibliothek", "bibliothek_calibre", _("Calibre and series"), _("""
**From Calibre** (toolbar of the library) takes series, number and blurb from Calibre's **metadata.calibre**, but only where the EPUB has nothing - existing data is never overwritten. Then save as usual (Ctrl+S); after that the data is in the book itself, and KOReader, Bookshelf and the reading software of the e-reader see it without Calibre too.

**Where the file is**
Calibre writes metadata.calibre into the root folder of the e-reader when transferring books. It is searched for in the opened folder and in all folders above it; for a copy on the computer simply copy the file into the books folder too. Books are matched by path, file name, Calibre UUID or title and author.

**Where a series comes from**
- From the EPUB (Calibre or EPUB 3 notation).
- Only in metadata.calibre: shown, the status bar says so, the filter **No series in the EPUB** lists these books.
- Only in KOReader's own book data (metadata edited in KOReader, folder .sdr next to the book): shown too - this only works if the folder with the .sdr folders is opened, e.g. the e-reader directly.

In the Blurbs area, **From Calibre** puts Calibre's description of a single book into the text field.
""")),
    ("bereiche", "kapitel", _("Chapters"), _("""
The books on the left, the table of contents on the right: **Entry** (as in the book), **New** (suggestion or own name), **Note**. Below are the first lines of book text at the selected entry.

The lines in front of the entries show the levels: **├** an entry followed by more on the same level, **└** the last one below its parent, **│** the parent level continues.

**Names**
- **Double-click** on a row (or F2) edits the new name. Leave it empty or press **Del** = original.
- **Apply** (Ctrl+Enter) applies what is in the New column - including the unchanged suggestions.
- **Apply all** applies the suggestions of all books that have no questionable entries and are not being edited.
- **Suggestions** resets the book to the suggestions, **Original** to the unchanged table of contents (including the levels).

Where suggestions come from: the lines below a chapter number in the book text (how many: [[einst_kapitel]]).

**More**
- [[suche_filter]]
- [[kapitel_ebenen]]
- [[kapitel_fragwuerdig]]
""")),
    ("kapitel", "kapitel_ebenen", _("Changing levels"), _("""
- Select entries (several with Ctrl- or Shift-click), then **Tab** or **Alt+→** (or **Down** in the toolbar) moves them one level down, **Shift+Tab** or **Alt+←** (or **Up**) one level up.
- Sub-entries move along, as in Word's outline view.
- An entry can be at most one level deeper than the one above; the first one is always at the top. What is not possible is said in the status bar.
- Column Note: "Level 2 → 3". Apply and save as with the names.
- When saving, the nesting in nav.xhtml and toc.ncx is rebuilt; the entries themselves (links, names, IDs) stay unchanged, reading positions in KOReader stay valid. Bookends (%chap_title_1 etc.) follows it.
- If nav.xhtml and toc.ncx have a different number of entries, the levels of this book cannot be changed; the status bar gives the reason.
""")),
    ("kapitel", "kapitel_fragwuerdig", _("Questionable names and decisions"), _("""
**Questionable** (red background, ⚠ in the list) are:
- the same name several times in the book,
- very short or very long names,
- chapters without names between chapters with names,
- books with only a few matches.
A click on the row shows the reason in the status bar. Apply the name, change it or put the original back - after applying, the entry no longer counts as questionable.

**Yellowish** rows have only a number and nothing was found in the text; a double-click lets you enter your own name.

**Decisions**
Applied names are remembered in **tocfix_entscheidungen.json** in the settings folder ([[dateien]]). If the same book turns up again (another copy, after a new transfer from Calibre), these names are suggested at once.
""")),
    ("bereiche", "klappentexte", _("Blurbs"), _("""
The books on the left, the blurb on the right. The text can be edited directly.

- Books without a blurb have a **⚠** in the list. If Calibre has a description for the book, the status bar says so when the mouse is over the ⚠.
- **Apply** (Ctrl+Enter) applies the text, **Discard** restores the text from the file. An empty field applied = remove the blurb.
- Below the text: where it comes from. This is also saved in the EPUB (meta bookbench:blurb-source) and shown in the Blurb column of the library.
- **From Calibre** puts Calibre's description into the text field ([[bibliothek_calibre]]).

After saving, re-read the book information in KOReader (Cover browser > Extract and cache book information), otherwise Bookshelf still shows the old state.

**More**
- [[suche_filter]]
- [[klappentexte_nachschlagen]]
- [[klappentexte_profile]]
""")),
    ("klappentexte", "klappentexte_nachschlagen", _("Looking up blurbs"), _("""
**Look up** (one book) and **Look up all** (all without a blurb, in the background) go through these steps until one has a text:
- **Google Books**, then **Open Library**: by ISBN, otherwise by title and author; the edition in the book's language is preferred. Free, no key ([[kosten]]).
- **Claude** with the first source profile that fits the book ([[klappentexte_profile]]): fetches the pages of the profile and copies the publisher blurb word for word. About 1 to 2 cents.

A text that is too short or too long is not taken (limits: [[einst_klappentexte]]). What was found is not applied at once: it is in the text field (red) until you apply it.

**Look up all**
- Skips books for which Calibre has a description - **From Calibre** is there for those, and it costs nothing.
- Asks before starting if Claude could be needed, with the maximum cost.
- Without an API key only the free sources are asked, without an error message.

**Cache**
What was found and what was already tried is in **blurbs_cache.json** ([[dateien]]). Looking up again costs nothing. If a profile is changed, Claude tries again for the books it covers; the free sources are asked again only after a network error. The cache can be emptied: [[einst_erweitert]].

Claude needs an API key and the package **anthropic** (pip install anthropic): [[einst_klappentexte_claude]].
""")),
    ("klappentexte", "klappentexte_profile", _("Source profiles"), _("""
A source profile tells Claude where to look for a blurb. They are set up under Settings > Books > Blurbs > Source profiles ([[einst_klappentexte_profile]]). The **first active profile that fits** the book is used.

**Fields**
- **Applies to**: parts of the publisher, series or author, separated by commas, case does not matter; one match is enough. All empty: every book.
- **Pages to fetch**: addresses with placeholders, one per line, fetched in this order, e.g. https://stormlightarchive.fandom.com/wiki/{title}.
- **Placeholders**: {title}, {author}, {series} become wiki page names (spaces as _); {title_q} and {author_q} are for search addresses (?q=…); {base} is the title without "Omnibus" (lines with {base} are skipped for other books, lines with {series} for books without a series). Lines with unknown placeholders are skipped.
- **Further allowed sites**: Claude may only fetch pages from these and the sites of the addresses above.
- **Section with the blurb**: what the section is usually called there ("Official Description"). A hint for Claude.
- **Topic**: e.g. "Star Wars"; a hint for Claude.
- **Web search**: if no page fits, search once in the allowed sites; a profile without any sites searches the whole web (publisher pages first, then big bookshops) and may search twice.

**Included**
- **Lexicanum (Warhammer 40,000)**: for Black Library / Games Workshop and the Warhammer series. Lexicanum, then the Fandom wiki.
- **Web search**: for all other books.
Both can be changed, switched off or deleted; **Defaults** brings them back.

**Tips**
- A fan wiki for a series ("Fandom") usually has the blurb: one line with {title}, section "Official Description".
- Put specific profiles above general ones; the web search profile belongs at the bottom.
""")),
    ("bereiche", "metadaten", _("Metadata"), _("""
The books on the left, in the middle a form with the metadata stored in the book: **title**, **authors**, **author sort**, **series** and **number**, **publisher**, **language**, **ISBN** and **tags**, followed by your **own fields** from Calibre columns ([[metadaten_felder]]). On the right the **cover** ([[cover]]).

- Type in the fields; the book turns red (changed, not applied). **Apply** (Ctrl+Enter or Enter in a field) makes it yellow, **Save** (Ctrl+S) writes it into the file, with backup.
- **Discard** restores the values and the cover from the file. This also drops a series taken over with **From Calibre** in the library.
- Several authors are separated with **&**, as in Calibre: "Dan Abnett & Graham McNeill". The **author sort** works the same way ("Abnett, Dan & McNeill, Graham"); with as many names as authors each author gets his own, otherwise the first one gets the whole text.
- **Number** may have decimals, e.g. 1.5 or 0.9 for a story between two books. A comma is turned into a point when applying, as in Calibre.
- **Tags** are separated with commas.
- **Language** as a code, e.g. en, de or en-GB. KOReader uses it for hyphenation.
- Below the form Bookbench warns about an invalid ISBN, a missing language or title, a number without series and values that do not fit an own field (e.g. letters in a number column).
- If Calibre or KOReader have a different value, it is shown below the field: **← Calibre: …**. A click on ← puts it into the field ([[metadaten_calibre]]).

The file name is never changed: KOReader keeps reading positions and highlights in a folder named after the file (.sdr), they would be lost.

After saving, KOReader only shows the new values after re-reading the book information (Cover browser > Extract and cache book information).

**More**
- [[metadaten_calibre]] - comparing with Calibre and KOReader
- [[metadaten_felder]]
- [[cover]]
- [[suche_filter]]
""")),
    ("metadaten", "metadaten_calibre", _("Calibre and KOReader"), _("""
**Calibre**
If Calibre's **metadata.calibre** is found ([[bibliothek_calibre]]) and the comparison is on ([[einst_calibre]]), Calibre's value is shown below every field where it differs: **← Calibre: …**. A click on **←** puts the value into the field. Matching values are not shown.

- **From Calibre** (toolbar) puts all differing values of this book into the form - check them, then apply.
- **Fill gaps** works on all books, but only on fields that are empty in the book. It applies directly (yellow); save afterwards.
- A **⚠** in the list means title, authors, series or number differ from Calibre. The filter **Differs from Calibre** also counts the other fields.
- Calibre stores languages as three letters (eng); Bookbench compares them with the two-letter codes of the book (en) and takes over the short form.

**Important:** When Calibre sends a book to the e-reader again, it writes its own values into the file. Change the metadata in Calibre as well, otherwise your changes in Bookbench are overwritten. If you no longer use Calibre, switch the comparison off: [[einst_calibre]].

**KOReader**
If you edited the book information in KOReader itself (Book information > long-press a field), KOReader keeps it in **custom_metadata.lua** in the .sdr folder next to the book and shows it **instead of** the values in the file. Bookbench shows these values below the fields as **← KOReader: …** (only when the folder with the .sdr folders is opened, e.g. the e-reader directly) and points it out below the form. The filter **Edited in KOReader** lists these books. To make KOReader show the file again, reset the fields in KOReader.
""")),
    ("metadaten", "metadaten_felder", _("Own fields"), _("""
In Calibre you can add columns of your own (Preferences > Add your own columns), e.g. a subtitle with the lookup name **#subtitle**. Bookbench shows such columns as further fields below the usual ones - which ones and with what label, you decide in [[einst_metadaten]]. **From Calibre** there adds all columns found in metadata.calibre at once.

- Bookbench reads and writes the columns the way Calibre stores them in the book: in EPUB 2 one entry per column, in EPUB 3 all own columns together in one entry. Columns you do not show stay untouched.
- If the book does not have a column yet, Bookbench takes its definition (type, how values are separated) from metadata.calibre, so Calibre recognises it when adding the book again. Without metadata.calibre a plain text column is written.
- Columns with several values ("Ampersand separated text", "Comma separated text") are shown joined with " & " or ", ". Careful: a text containing **&** is then split into two values, just like in Calibre.
- Number columns (whole numbers, decimals, rating) only take numbers, yes/no columns yes or no; dates are shown without time.
- KOReader only knows title, authors, series, language, tags and description; own fields are for Calibre and for you.
""")),
    ("metadaten", "cover", _("Cover"), _("""
The cover is shown right of the form, as large as there is room. **Click on the cover** (also the small one in Chapters and Blurbs) shows it as large as the screen allows; click or Esc closes it. A right-click opens a menu with all cover actions.

- Below the cover: size in pixels, format, file size and where it is in the EPUB.
- **From file …**, **Look up**, **Export …** (saves the cover shown as an image file) and **Discard new** are below the cover; **All without cover** is in the toolbar.
- As long as a new cover is not saved, the old one and the new one are shown next to or below each other.
- Books without a cover and covers lower than the limit have a **⚠** in the list ([[einst_cover]]); the filters **No cover** and **Small cover** list them.

After saving, re-read the book information in KOReader (Cover browser > Extract and cache book information), otherwise the cover browser still shows the old cover.

**More**
- [[cover_aendern]]
- [[cover_bild]]
""")),
    ("cover", "cover_aendern", _("Changing and looking up covers"), _("""
- **From file** takes an image file (JPEG, PNG, GIF, WebP).
- **Look up** searches Open Library and Google Books (free, no key) by ISBN, title and author and shows what was found side by side, with size; a click chooses, OK takes it, a double-click takes it at once. Tiny preview images are left out.
- **All without cover** does that in the background for all books without a cover and takes the largest image found. Check them afterwards.
- **Discard** drops the new cover. **Ctrl+S** saves, with a backup as always.

The sources, the smallest height that counts and how many to choose from: [[einst_cover_nachschlagen]].

**Tips**
- Open Library often has large scans, sometimes of another edition (another cover). Google Books has the publisher's image, usually smaller.
- In the Edit menu the same actions work from Chapters and Blurbs; the program switches to Metadata with the same book.
""")),
    ("cover", "cover_bild", _("What happens to the image"), _("""
- The new cover keeps the **format** and the **file name** of the old one (a PNG becomes a JPEG if the old cover is a JPEG). That way the manifest and a title page that shows the image stay valid.
- It is shrunk only if it is higher than the limit in the settings (0 = never); it is never enlarged ([[einst_cover]]). If nothing has to be converted or shrunk, the file goes into the book unchanged, byte for byte.
- A book without a cover gets cover-bookbench.jpg next to the content.opf, an entry in the manifest (EPUB 3: properties="cover-image") and <meta name="cover"> (EPUB 2; KOReader reads both).
- Converting and shrinking need **Pillow** (pip install pillow), showing JPEG images too. Without Pillow only an image in the right format can be inserted unchanged.
- Transparent areas become white when converting to JPEG.
""")),
    ("bereiche", "woerterbuch", _("Dictionary"), _("""
Your own dictionaries for KOReader: read, edit, fill missing terms, build from a wiki, build the files. The dictionary is chosen at the top; Bookbench remembers all that were ever opened or created.

**Types**
- **from a wiki**: a database like the one of wikidict.py (wikidict.sqlite in the working folder; wh40kdict.sqlite from earlier versions is still recognized). Entries come from wiki articles ([[woerterbuch_aufbau]]), plus your own.
- **own entries**: a database without a wiki; entries by hand or from Claude, missing terms from the lookup history and from the books (frequent names).
- **StarDict folder**: a finished dictionary without a database, e.g. a copy on the go, one from the e-reader or from the web. That is enough for reading and editing.

**New …** creates a dictionary (working folder, name in KOReader, file name, topic for Claude, for wiki dictionaries the wiki address and optionally a second site for cross-checking). **Open …** takes a working folder (with wikidict.sqlite) or a folder with an .ifo file; it also searches below (also under .adds), so e.g. the root of an e-reader backup is enough. With several matches you get a choice. **Properties …** changes name, topic, spoilers and the books filter. **Remove from list** only takes it out of the list, the files stay.

**More**
- [[woerterbuch_anzeigen]]
- [[woerterbuch_bearbeiten]]
- [[woerterbuch_aufbau]]
- [[woerterbuch_unterwegs]]
""")),
    ("woerterbuch", "woerterbuch_anzeigen", _("Views and missing terms"), _("""
- **Entries**: everything in the dictionary. The search also finds other names ("Strider" finds Aragorn).
- **Missing terms**: names from the books without an entry (from the step Search books) and **words that were looked up in KOReader and are missing** (⚠, first). The lookup history comes from the connected e-reader, otherwise from the newest backup of the KOReader settings ([[kobo_sicherungen]]). Everyday words in lower case are left out.
- Which looked-up words belong to which dictionary is decided by the searched books and the **books filter** in the properties (parts of title, series or author). Without either, all of them belong.
- **Ignored and removed**: terms that no longer count as missing, and entries taken out; **Remove** or **Bring back** brings them back.
- **Steps** (only with a database): [[woerterbuch_aufbau]].
""")),
    ("woerterbuch", "woerterbuch_bearbeiten", _("Editing entries and Claude"), _("""
**Editing**
- Form: name, category, short description, other names (comma-separated; KOReader also finds the entry under these), sections (a line with **#** is the heading, the text below it). Below that the preview of how the entry looks in KOReader.
- Entries from other dictionaries that do not have this structure are edited as **HTML** or **text**.
- **Apply** (Ctrl+Enter) saves your own version (yellow), **Discard** undoes changes in the form (red = not applied). Own versions always win, even if things are summarized again later. **Discard own version (original)** (Dictionary menu) discards them. **New** adds a term by hand.

**Claude ▾** (for the chosen term; the result is always a draft to check; topic and spoilers from the properties)
- **Search the web**: web search anywhere, text only from the pages found, which are given as the source in the entry. About 2-4 cents.
- **Summarize from a page**: give an address, Claude reads only that page.
- **From own knowledge**: without a source; the entry says "unverified", the list shows ⚠.
- If Claude finds the full name ("Baggins" -> "Bilbo Baggins"), the searched name becomes another name of the entry.

Costs and what is sent: [[kosten]].
""")),
    ("woerterbuch", "woerterbuch_aufbau", _("Steps and building"), _("""
**Steps** (the steps of wikidict.py, with status, options and output; **Cancel** stops at the next intermediate step, what was done so far stays saved)
- **1. Load titles**: all article titles of the wiki.
- **2. Search books**: choose the books folder; finds the titles in the books, names without an article become gaps. The book text never leaves the computer.
- **3. Load articles**: only the ones that occur.
- **4. Summarize**: Claude writes the entries; batch costs half as much but takes time (minutes to hours). The estimated cost is asked for confirmation first.
- **5. Cross-check**: compare with the second site and fill gaps from there.
- **6. Build**.
Dictionaries without a wiki only have Search books and Build. The packages requests, mwparserfromhell, wordfreq and anthropic are needed.

**Build** writes the dictionary files: for databases into the folder of the last build (you are asked the first time), for StarDict folders into the folder itself, backed up first (backup folder, subfolder Wörterbücher). Then copy them to the e-reader ([[kobo_woerterbuecher]]) and restart KOReader. Green = built since opening.

wikidict.py on the command line also includes your own entries when building.
""")),
    ("woerterbuch", "woerterbuch_unterwegs", _("On the go without a database"), _("""
Open the StarDict folder (e.g. the copy on the e-reader or on a stick) and edit it. Bookbench records the changes in **bookbench.json** in this folder (it does not go to the e-reader).

Back home in the database: Properties > **Take changes from a StarDict folder**, otherwise the next build overwrites them.
""")),
    ("bereiche", "kobo", _("E-reader"), _("""
Shows the connected e-reader with KOReader - Kobo, Kindle or PocketBook: model, drive, firmware, KOReader version, free space.

**Detection**
- Automatically every few seconds ([[einst_kobo]]), by the folders in the root of a drive ([[kobo_geraete]]). Copies of the e-reader on the hard disk (backups with a .kobo folder and the like) do not count, only the root of a drive.
- Searched: on Linux /run/media, /media and /mnt, on Windows all drives; also the opened books folder and the folders above it.
- With several connected e-readers a list appears next to the name.

**Books** opens the whole e-reader in Library, Chapters, Blurbs and Covers. Then metadata.calibre is found automatically too.

**When connecting** Bookbench opens the books on the e-reader by itself if no other folder is open; otherwise it asks. Can be changed: [[einst_kobo]].

**More**
- [[kobo_geraete]]
- [[kobo_sicherungen]]
- [[kobo_woerterbuecher]]
- [[kobo_auswerfen]]
""")),
    ("kobo", "kobo_geraete", _("Kobo, Kindle, PocketBook"), _("""
KOReader keeps its settings in its own installation folder. Where that is depends on the device:

- **Kobo** (and tolino from 2024 on, Kobo hardware): folder **.kobo** in the root, KOReader in **.adds/koreader**, extra fonts in **fonts**. Model, serial number and firmware come from .kobo/version; an unknown model shows the number on the type plate (e.g. N428) instead.
- **Kindle**: folders **documents** and **system** in the root, KOReader in **koreader**, extra fonts in **fonts**.
- **PocketBook**: folder **applications** (with **koreader** inside) and **system/config**, KOReader in **applications/koreader**, the device's own fonts in **system/fonts**.

Kindle and PocketBook put no readable model data on the drive; the area then only shows the kind of device. For the preview choose the model by hand if needed ([[vorschau_bildschirm]]).

Newer Kindles and Android devices only connect via MTP and do not appear as a drive, so they are not found. On Linux a file manager can still copy their files to a folder on the computer; open that folder or use it as the dictionary source. On Windows there is no way from the program.

Only the Kobo was tested on a real device so far; Kindle and PocketBook follow the KOReader source code.
""")),
    ("kobo", "kobo_sicherungen", _("Backups of the KOReader settings"), _("""
- **Back up** packs the parts ticked on the right into a ZIP file in the subfolder **KOReader** of the backup folder (KOReader_YYYYMMDD_HHMMSS.zip). The newest backups are kept ([[einst_kobo]]).
- **Restore** (or double-click) writes the ticked parts from the selected backup back. Files with the same name are overwritten, others stay. The current state is backed up first (reason "before restoring").
- When a backup is selected, the status bar shows its contents, device and KOReader version; backups from another device are pointed out.

**Parts**
- **Settings**: settings.reader.lua, defaults.custom.lua.
- **Statistics and plugin data**: folder settings - reading statistics, history, Bookends presets (settings/bookends_presets), Silverfish.
- **Book data**: the .sdr folders next to the books - reading position, highlights, notes.
- **Style tweaks and patches**.
- **Kobo settings**: Kobo eReader.conf of the Kobo software (off by default, only on a Kobo).

A backup notes the kind of device. It can be restored to another kind (e.g. from the Kobo to a Kindle): the KOReader folder then lands where KOReader is on the connected device. Folders stored in the settings (home folder, last book) still point to the old device; KOReader asks for them again if needed.

After restoring, KOReader takes over the files at the next start, i.e. after ejecting. KOReader writes its settings when it closes; changing something on the e-reader without closing KOReader overwrites the restored state.

The preview can take its profile from a backup too ([[vorschau_profil]]).
""")),
    ("kobo", "kobo_woerterbuecher", _("Copying dictionaries"), _("""
- **Choose source**: a folder on the computer somewhere inside which the dictionaries are ([[einst_kobo]]). It is searched up to 8 levels deep (at most 5000 folders; hidden folders like .adds are searched too, so a copy of the e-reader works as well; only large folders without dictionaries like .git, .cache, AppData, Windows and KOReader's plugins, fonts, cache are skipped). A dictionary is a folder with an .ifo file, e.g. My-Dictionary. If there are several folders with the same name, the one with the newest .ifo wins; the column **Folder in the source** shows which one was found.
- Status of each dictionary: **up to date**, **outdated on the e-reader** or **missing on the e-reader** (both red), **only on the e-reader**.
- **Dictionary** (toolbar) copies the selected ones, without a selection all that are not up to date, to data/dict/<name>/ in the KOReader folder (Kobo: .adds/koreader/data/dict). Files in the target that no longer exist in the source are deleted there.
- **Double-click** opens the dictionary in the Dictionary area: the registered one that was built into this folder, otherwise the folder from the source itself. A dictionary that is only on the e-reader is opened there after asking; changes are then saved on the e-reader.
""")),
    ("kobo", "kobo_auswerfen", _("Ejecting"), _("""
**Eject** unmounts the e-reader (Linux: udisksctl, Windows: like "Eject" in Explorer). Then the cable can come off.

If something was written to the e-reader in this session (backup restored, dictionary copied, books saved), the program reminds you when quitting. The reminder can be switched off: [[einst_kobo]].

**Library on the e-reader**
If the opened library is on the e-reader and has unsaved changes, Bookbench asks before ejecting: save, discard or cancel. After ejecting, the library is closed.

If the e-reader disappears without ejecting (cable pulled), a bar above the areas says so. The library stays visible, but saving is refused until the e-reader is back; the changes stay in memory as long as Bookbench is open. **Close library** in the bar (or in the File menu) or **Reload** discards them.

**If ejecting fails**
On Linux ejecting fails while a program still has a file or folder on the e-reader open, often the file manager that opened when the e-reader was connected. Bookbench first tries three times (thumbnails or the file search often let go by themselves), then lists these programs and offers **Retry**. Only your own programs can be seen.
- Dolphin: change to another folder, also in other tabs and in the terminal panel, or close the window.
- Dolphin's terminal panel (F4) follows the folder shown in Dolphin and keeps running when it is hidden: Bookbench then names the terminal panel in a Dolphin window. Opening another folder in Dolphin moves it away.
- That KDE opens the file manager when the e-reader is connected can be switched off in the KDE system settings (removable storage / device actions).
""")),
    ("bereiche", "vorschau", _("Preview"), _("""
Shows a book in the **desktop KOReader** as it looks on the device: font, margins, headers and footers from Bookends, style tweaks and patches. Only on Linux and macOS; there is no official KOReader for Windows, so the area is missing there.

**Installing KOReader** (optional, only needed for this)
- Arch/EndeavourOS: **yay -S koreader-bin**
- Flatpak: **flatpak install flathub rocks.koreader.KOReader**
- or put the AppImage from github.com/koreader/koreader/releases into ~/Applications or ~/Downloads
It is searched in this order: own path ([[einst_vorschau]]), koreader in PATH, macOS applications folder, AppImage, Flatpak. Preview menu > **Find KOReader** after installing.

**More**
- [[suche_filter]]
- [[vorschau_profil]]
- [[vorschau_starten]]
- [[vorschau_bildschirm]]
""")),
    ("vorschau", "vorschau_profil", _("Profile"), _("""
The preview runs in its own profile in the settings folder (subfolder vorschau, [[dateien]]). A normal KOReader installation on the computer stays untouched.

- **From the e-reader** rebuilds the profile from the connected e-reader: settings.reader.lua, folder settings (with the Bookends presets), styletweaks, patches, the plugins you installed (the built-in ones come with the desktop KOReader) and the fonts from KOReader's fonts folder and from the font folder of the device ([[kobo_geraete]]).
- **From backup** takes settings, settings folder, styletweaks and patches from the backup selected in the E-reader area, otherwise from the newest ([[kobo_sicherungen]]). Plugins and fonts are in no backup; they stay as they are. So you have to take the profile from the e-reader at least once.
- When taking a profile and before every start, these are removed from the settings: **screen_dpi** (it would override the screen size of the preview), plugin paths and the last files/folders on the e-reader. In the profile, book data is always next to the book.
""")),
    ("vorschau", "vorschau_starten", _("Starting and output"), _("""
**Start** (or double-click)
- The selected book is copied with its book data (.sdr) to vorschau/buecher and opened there. KOReader writes to the book data while reading; that way the original stays untouched, on the e-reader too.
- Book data is searched: next to the book, on the connected e-reader (same file name), in the backup. Without book data the general settings apply, so font size and margins may differ.
- **Other file** shows a book that is not in the opened library.

**KOReader output**
At the bottom of the area is what KOReader reports at start and while running. After it closes, the status bar gives the number of warnings and errors, for example a patch that does not run on the computer because it needs something specific to the e-reader.
""")),
    ("vorschau", "vorschau_bildschirm", _("Screen and device"), _("""
The window copies the screen of a device: size in pixels, pixel density, colour or black and white (black and white switches off the colours in KOReader, as on the device). Which device is under the size buttons:
- **Automatic** (default): the device the profile was taken from (From the e-reader, or the device noted in the backup), otherwise the connected e-reader, otherwise the Libra Colour - then with a ⚠.
- Kindle and PocketBook note no model, so automatic falls back to the Libra Colour for them; choose **Own size** there.
- **Settings > Device > Preview**: a fixed Kobo or tolino model, or **Own size** for other e-readers with KOReader (pixels in portrait format and ppi from the data sheet) - [[einst_vorschau]].

A Libra Colour has 1264 × 1680 pixels at 300 dpi; hardly any screen is that tall.
- **Fitted to the screen** takes the height of the screen and lowers the DPI to match; KOReader sizes fonts and spacing by the DPI, so the page looks the same, only coarser.
- **Half size**: half the pixels and half the DPI.
- **Full size** is pixel-exact, but the window then goes beyond the screen.
A screenshot from KOReader (menu or gesture) always has the full resolution of the window.
""")),
    ("", "speichern", _("Saving and backups"), _("""
**Save** (Ctrl+S) writes all applied changes (yellow) of all books: chapter names and levels, blurbs, series, covers. Changes that were not applied (red) are not saved.

**Backups**
- Before saving, every affected file is copied to the backup folder: **<name>_YYYYMMDD_HHMMSS.epub**. The newest backups of each book are kept ([[einst_speichern]]).
- Do not put the backup folder on the e-reader: otherwise KOReader shows the backups as books. The default is a folder in the user directory.
- To go back: copy the backup over the book (rename it back to the original name).

**What is written**
- Only the files inside the EPUB that changed (nav.xhtml, toc.ncx, content.opf, the cover image); everything else is copied unchanged. The file "mimetype" stays first and uncompressed, as the EPUB rules require.
- Saving goes to a temporary file first and replaces the book only when that worked.

After saving, KOReader only shows new metadata after re-reading the book information (Cover browser > Extract and cache book information).
""")),
    ("", "einstellungen", _("Settings"), _("""
File > **Settings …** opens the settings. The tree on the left has groups with pages below them; a group page shows what its pages are for. **Help** (or F1) in the dialog opens the chapter of the page shown here.

**OK** saves, **Cancel** forgets the changes. Most settings apply at once; chapter settings after reloading (F5), the language after the automatic restart.

All settings are in **einstellungen.json** in the settings folder ([[dateien]]). Export, import and resetting: [[einst_erweitert]].

**Pages**
- General: [[einst_darstellung]], [[einst_oberflaeche]], [[einst_start]]
- [[einst_speichern]]
- Books: [[einst_kapitel]], [[einst_klappentexte]] ([[einst_klappentexte_profile]], [[einst_klappentexte_claude]]), [[einst_cover]] ([[einst_cover_nachschlagen]]), [[einst_metadaten]], [[einst_calibre]]
- Device: [[einst_kobo]], [[einst_vorschau]]
- [[einst_erweitert]]
""")),
    ("einstellungen", "einst_darstellung", _("Language and theme"), _("""
**Language** (default: automatic)
- Automatic: German if the system language is German, otherwise English (Windows: language of the interface; Linux: LANGUAGE, LC_ALL, LC_MESSAGES, LANG).
- When it changes, the program restarts by itself; folder, area, selected book and window stay. If changes are open, it asks first; with No the new language applies at the next start.

**Theme** (default: like the system)
- Light, dark, or like the system: follows the light/dark setting of Windows or KDE/GNOME, checked at start.
""")),
    ("einstellungen", "einst_oberflaeche", _("Interface"), _("""
- **Status strip next to the lists** (default: on): coloured dots and ⚠ ([[status]]). Also under View.
- **Show tooltips** (default: on) and **Delay** (default: 600 ms): explanations when the mouse stays over a button.
- **Show covers in Chapters and Blurbs** (default: on) and **Height** (default: 96 px): the small cover next to the book title; a click shows it large. Also under View > Cover.
- **Sidebar expanded** (default: on): with names and counters, or only symbols. Ctrl+B switches at any time; the last state is remembered.
""")),
    ("einstellungen", "einst_start", _("Startup"), _("""
- **Open the last folder** (default: on): the books folder that was open when the program was last closed, if it still exists - for the e-reader only when it is connected. Off: the program starts empty; File > Recently opened still has the folders.
- **Area at start** (default: Library): always the library, or the area that was shown last.

A folder given on the command line (start.py <folder>) is always opened.
""")),
    ("einstellungen", "einst_updates", _("Updates"), _("""
**This copy** says how Bookbench was installed: with the Windows setup, with install.sh or not at all (source code, e.g. a git clone). Only installed copies can update themselves ([[updates]]). **Check now** looks right away, with the values on this page (also before OK).

**Automatic check** (default: at start, at most once a day): off, at every start, at most once a day or once a week. It runs a few seconds after the start in the background. Only a newer version opens a window; without network there is only a note in the status line. Source code copies never check automatically.

**Skipped version**: shown when a version was skipped in the update window. **Show again** brings its window back at the next check.

**Include pre-releases** (default: off): also releases marked as pre-release on GitHub.

The releases come from github.com/kepfle-git/Bookbench; that is fixed in the program. Without signing in GitHub allows 60 requests per hour, far more than the check needs.
""")),
    ("einstellungen", "einst_speichern", _("Saving and backups"), _("""
- **Backup folder** (default: Bookbench Backups in the user folder): books are copied here before each save ([[speichern]]). The E-reader area uses its subfolder KOReader, the dictionary its subfolder Wörterbücher. Not on the e-reader.
- **Backups per book** (default: 5): the newest ones are kept, older ones are deleted when saving.
""")),
    ("einstellungen", "einst_kapitel", _("Chapters"), _("""
- **Subtitle lines per chapter** (default: 1): how many lines below a chapter number make up the suggested name. Some books have three (e.g. place, time, person); with 3 all of them are joined with " / ".
- **Write entries in capitals normally** (default: off): THE SHIRE becomes The Shire, A LONG-EXPECTED PARTY becomes A Long-Expected Party. Small words (a, of, the …) stay lower case except at the start.

Both apply after reloading (F5), because the suggestions are made when reading the books. See also [[kapitel]].
""")),
    ("einstellungen", "einst_klappentexte", _("Blurbs"), _("""
The page shows the order of the sources ([[klappentexte_nachschlagen]]).

- **Ask Google Books and Open Library first** (default: on): free, no key. Off: every look-up goes to Claude straight away.
- **Shortest blurb** (default: 80 characters): shorter texts from a source are not taken - often only a teaser line or "A novel".
- **Longest blurb** (default: 4000 characters): longer texts are not taken - usually a plot summary or a whole article.
The limits apply to all sources (free ones and Claude), not to text you enter yourself.
""")),
    ("einst_klappentexte", "einst_klappentexte_profile", _("Source profiles"), _("""
The list of profiles in the order in which they are checked. The first active one that fits a book is used; what the fields mean: [[klappentexte_profile]].

- **New …** puts a new profile at the top (otherwise the general web search would come first).
- **Edit …** (or double-click), **Delete**, **Up**, **Down**.
- **Defaults** puts the included profiles back; your own profiles are removed.
- "(off)" in front of "Applies to": the profile is switched off and skipped.

Changes count after OK. If a profile changes, Claude looks up again for its books; books it already found stay as they are.
""")),
    ("einst_klappentexte", "einst_klappentexte_claude", _("Claude API"), _("""
- **API key**: from console.anthropic.com (account with credit). Empty: the environment variable ANTHROPIC_API_KEY is used. Stored in plain text in einstellungen.json ([[dateien]]) - keep that in mind when exporting the settings.
- **Model** (default: claude-haiku-5-5): choose from the list; Haiku is enough for looking things up and is the cheapest. **Load list** asks Anthropic with the API key for the models available right now (newest first). A name can also be typed in.
- **Estimated cost per book** (default: 0.015 $): only for the question before Look up all; the real cost depends on page length and searches.

Also needed: the package **anthropic** (pip install anthropic). What is sent: [[kosten]].
""")),
    ("einstellungen", "einst_cover", _("Covers"), _("""
**Inserting a new cover** ([[cover_bild]])
- **Shrink to at most this height** (default: 0 = never): your e-reader shows at most its screen height (e.g. 1680 px on a Libra Colour); larger images only make the file bigger. Images are never enlarged.
- **JPEG quality** (default: 90): only when an image is converted or shrunk; otherwise it is taken unchanged. 90 is barely distinguishable from the original; below 75 artefacts become visible.

**Marking**
- **Mark covers below this height** (default: 800 px, 0 = never): ⚠ in the Metadata area and its filter "Small cover".
""")),
    ("einst_cover", "einst_cover_nachschlagen", _("Looking up covers"), _("""
**Sources** (both free, no key; [[kosten]])
- **Open Library** (default: on): often large scans, sometimes of another edition.
- **Google Books** (default: on): the publisher's image, usually smaller.

**Which images count**
- **Smallest height** (default: 300 px): smaller images are left out (preview thumbnails, placeholders).
- **At most this many to choose from** (default: 8): each image is downloaded, so more takes longer. All without cover takes at most 3 per book and uses the largest.
""")),
    ("einstellungen", "einst_metadaten", _("Metadata"), _("""
**Own fields** ([[metadaten_felder]])
- The list holds one Calibre column per row: **lookup name** (as in Calibre, with #, e.g. #subtitle) and the **label** Bookbench shows. Default: none.
- Select a row to change it below, **Add / change** takes the two fields (an existing lookup name is changed, a new one added). **Delete**, **Up** and **Down** work on the selected row; the order is the order in the form.
- **From Calibre** adds all own columns found in the metadata.calibre of the opened folder, with Calibre's labels. Delete the ones you do not want.
""")),
    ("einstellungen", "einst_calibre", _("Calibre"), _("""
- **Compare with Calibre** (default: on): Bookbench reads Calibre's metadata.calibre (root of the e-reader, or the opened folder and the folders above it) and shows its values: in [[metadaten_calibre]] for comparing, in the library and in Blurbs for taking over series and blurbs ([[bibliothek_calibre]]).
- Off: metadata.calibre is ignored, the Calibre buttons disappear from the toolbars, the Calibre entries in the Edit menu only give a hint. Useful once Bookbench has replaced Calibre for you.
- Switching off applies at once, switching on after reloading (F5).
""")),
    ("einstellungen", "einst_kobo", _("E-reader"), _("""
**Detection**
- **Look for the e-reader every** (default: 3 seconds): how often the program checks whether an e-reader is connected or unplugged ([[kobo]]).
- **When an e-reader is connected** (default: open its books, ask if another folder is open): or always ask, or do nothing ([[kobo]]).

**Backups**
- **Backups of the KOReader settings** (default: 10): this many stay in the subfolder KOReader of the backup folder, including the backup before each restore ([[kobo_sicherungen]]).

**Dictionaries**
- **Dictionaries (folder on the computer)**: where the dictionaries to copy are ([[kobo_woerterbuecher]]). Also set by Choose source in the E-reader area.

**Ejecting**
- **Remind me to eject when quitting** (default: on): only if something was written to the e-reader in this session ([[kobo_auswerfen]]).
""")),
    ("einstellungen", "einst_vorschau", _("Preview"), _("""
Only on Linux and macOS.

- **Desktop KOReader** (default: empty = search): only fill in if it is not found by itself ([[vorschau]]). **flatpak** always takes the Flatpak rocks.koreader.KOReader, also when KOReader is installed normally too ([[fehler]]).
- **Device shown** (default: automatic): automatic, any Kobo or tolino model from the list (with size and ppi), or **Own size** with width, height (pixels in portrait format), ppi and colour screen for other e-readers with KOReader. See [[vorschau_bildschirm]].
""")),
    ("einstellungen", "einst_erweitert", _("Advanced"), _("""
**Files of the program**
- Shows where settings, chapter decisions and blurb cache are ([[dateien]]); **Open settings folder** opens it in the file manager.

**Blurb cache**
- Shows how many entries it has. **Empty …** deletes it: afterwards everything is looked up again, and Claude costs again.

**Export and import**
- **Export settings …** writes all settings to a JSON file, e.g. to take them to another computer. It contains the API key.
- **Import settings …** replaces the current settings with those from the file (unknown entries are ignored). The language applies at the next start.

**Reset**
- **Reset all settings …** puts everything back to the defaults. Kept: opened folders, the list of dictionaries, window size, language and the API key.
""")),
    ("", "updates", _("Installing and updating"), _("""
**Installing**
- **Windows**: Bookbench_Setup_<version>.exe from the release page on GitHub. It installs for the current user without administrator rights (%LOCALAPPDATA%\\Programs\\Bookbench); as administrator "for all users" can be chosen. Start menu entry, desktop shortcut optional. Uninstall in the Windows settings under Apps; the settings in %APPDATA%\\Bookbench stay.
- **Linux**: download the source code of the release (or clone the repository) and run **./install.sh** in it. It copies the program to ~/.local/share/bookbench/programm, sets up a Python environment there (venv) with the optional packages, a command **bookbench** in ~/.local/bin and a menu entry. **./install.sh --uninstall** removes all that again; the settings in ~/.config/bookbench stay. Needs Python 3.9 or newer with Tkinter (Arch: python and tk; Debian/Ubuntu: python3-tk and python3-venv).
- Without installing: **python start.py** in the program folder; the optional packages then come from pip (README).

**Updating**
- **Help > Check for updates …** looks for the newest release on GitHub ([[einst_updates]]). Installed copies also look by themselves at start.
- A newer version shows its changes (formatted like on GitHub, links open in the browser), with **Install now** for installed copies.
- **Install now** on Windows: downloads the setup, closes Bookbench, installs the new version over the old one and starts it again.
- **Install now** on Linux: downloads the new version, replaces the program folder and restarts Bookbench; the Python environment stays.
- Before closing Bookbench asks about unsaved changes and ejecting, like when quitting. Saying no keeps the download; Install now later uses it.
- The setup is checked against the file SHA256SUMS of the release; a damaged download is not installed.
- **Skip this version**: no more window for it at start; the manual check still shows it.
- A copy running from source code (git clone) is not replaced; update it with git pull.

The **desktop KOReader** for the preview (Linux only) is not part of the installation ([[vorschau]]).
""")),
    ("", "fehler", _("Troubleshooting"), _("""
**KOReader still shows the old chapter names, blurb or cover**
- KOReader keeps its own copy of the book information. Cover browser > long-press the book or menu > **Extract and cache book information** (or for the whole folder). The table of contents is read anew when the book is opened.

**JPEG covers are not shown**
- The package **Pillow** is missing: pip install pillow. Without it only PNG and GIF can be shown.

**"No API key" or nothing goes to Claude**
- Key under [[einst_klappentexte_claude]] or the environment variable ANTHROPIC_API_KEY; package anthropic installed? Without a key only the free sources are asked.

**API error**
- The status bar shows Anthropic's message: no credit, wrong key, model name unknown, overloaded. The book does not count as tried and is looked up again next time.

**Google Books / Open Library: network error**
- Behind a proxy or offline nothing can be reached; the book is not marked as tried. Google sometimes limits requests without a key: try again later.

**The e-reader is not found**
- On the e-reader confirm the connection (KOReader: USB mass storage, or the device's own software: Connect).
- Newer Kindles and Android devices only connect via MTP, without a drive ([[kobo_geraete]]).
- Then wait a few seconds or E-reader menu > **Find e-reader**. Is the drive mounted (Linux: file manager)? If needed, open the books folder on the e-reader: then its root counts too.

**Restored settings are gone again**
- KOReader writes its settings when it closes. Eject first, then start KOReader - do not change anything in a KOReader that was already running.

**A chapter level cannot be changed**
- nav.xhtml and toc.ncx of this book have a different number of entries; the status bar names the reason ([[kapitel_ebenen]]).

**Preview: window too large or patches fail**
- Choose "Fitted to the screen" ([[vorschau_bildschirm]]). Patches that need Kobo hardware fail on the computer; the output at the bottom of the area says which.

**Preview: KOReader closes at once ("device/kobo/device.lua" in the output)**
- The desktop KOReader takes the computer for an e-reader: up to at least version 2026.07 it recognizes the device by files such as /usr/bin/hwdetect (Arch/EndeavourOS: package hwdetect), /bin/kobo_config.sh or /proc/usid. KOReader alone does the same.
- Normally this does not happen in the preview: Bookbench puts a start patch (1-bookbench-desktop.lua) into the profile that hides these files from KOReader. It does not count as one of your patches and never goes to the e-reader. It does not work if patches are switched off in KOReader; then Bookbench says so and which file it is.
- Way out: KOReader as Flatpak (flatpak install flathub rocks.koreader.KOReader), it does not see these files. Enter **flatpak** under Settings > Device > Preview > Desktop KOReader ([[einst_vorschau]]), so that it is taken even if KOReader is also installed normally. Or remove the file if nothing else needs it.

**Something else**
- The status bar always has the last message. Backups of all saved books are in the backup folder ([[speichern]]).
""")),
]

TITEL = {k: t for __, k, t, __ in THEMEN}
VERWEIS = re.compile(r"\[\[(\w+)\]\]")


def thema(bereich):
    """Kennung des Hilfethemas zu einem Bereich (wie App._bereich); sonst der Überblick."""
    return bereich if bereich in TITEL else THEMEN[0][1]


def klartext(text):
    """Text ohne Auszeichnung, Verweise als Titel (für die Suche)."""
    return VERWEIS.sub(lambda m: TITEL.get(m.group(1), m.group(1)), text).replace("**", "")


class HilfeFenster(tk.Toplevel):
    def __init__(self, app, thema=None):
        super().__init__(app)
        self.app = app
        self.title(f"{PROGRAMM} - " + _("Help"))
        self.geometry("980x620")
        self.minsize(640, 380)
        self.verlauf = []
        links = ttk.Frame(self, padding=(8, 8, 0, 8))
        links.pack(side="left", fill="y")
        self.suche = tk.StringVar()
        z = ttk.Frame(links)
        z.pack(fill="x", pady=(0, 6))
        ttk.Label(z, text=_("Search:")).pack(side="left")
        self.suchfeld = ttk.Entry(z, textvariable=self.suche)
        self.suchfeld.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.suche.trace_add("write", lambda *a: self._suchen())
        self.suchfeld.bind("<Return>", lambda e: self._erster_treffer())
        self.suchfeld.bind("<Escape>", lambda e: (self.suche.set(""), "break")[1])
        rahmen = tk.Frame(links, highlightthickness=1, borderwidth=0)
        rahmen.pack(fill="both", expand=True)
        self.baum = ttk.Treeview(rahmen, show="tree", selectmode="browse", height=20)
        self.baum.column("#0", width=270)
        sb = ttk.Scrollbar(rahmen, orient="vertical", command=self.baum.yview)
        self.baum.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.baum.pack(side="left", fill="both", expand=True)
        self.treffer_text = ttk.Label(links, text="", style="Hinweis.TLabel")
        self.treffer_text.pack(anchor="w", pady=(4, 0))
        rechts = ttk.Frame(self, padding=8)
        rechts.pack(side="left", fill="both", expand=True)
        oben = ttk.Frame(rechts)
        oben.pack(fill="x", pady=(0, 4))
        self.zurueck_knopf = ttk.Button(oben, text="← " + _("Back"), command=self.zurueck, state="disabled")
        self.zurueck_knopf.pack(side="left")
        self.pfad = ttk.Label(oben, text="", style="Hinweis.TLabel")
        self.pfad.pack(side="left", padx=10)
        trahmen = tk.Frame(rechts, highlightthickness=1, borderwidth=0)
        trahmen.pack(fill="both", expand=True)
        self.text = tk.Text(trahmen, wrap="word", borderwidth=0, highlightthickness=0, padx=12, pady=10,
                            font=kth.schrift(10), cursor="arrow", spacing1=1, spacing3=2)
        tsb = ttk.Scrollbar(trahmen, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure("fett", font=kth.schrift(10, fett=True))
        self.text.tag_configure("titel", font=kth.schrift(13, fett=True), spacing3=8)
        self.text.tag_configure("punkt", lmargin1=8, lmargin2=26)
        self.text.tag_configure("verweis", underline=True)
        self.text.tag_bind("verweis", "<Enter>", lambda e: self.text.configure(cursor="hand2"))
        self.text.tag_bind("verweis", "<Leave>", lambda e: self.text.configure(cursor="arrow"))
        self._rahmen = (rahmen, trahmen)
        self._baum_fuellen()
        self.baum.bind("<<TreeviewSelect>>", lambda e: self._anzeigen())
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Alt-Left>", lambda e: self.zurueck())
        self.bind("<Control-f>", lambda e: (self.suchfeld.focus_set(), self.suchfeld.select_range(0, "end")))
        self.farben()
        self.zeige(thema or THEMEN[0][1])

    def _baum_fuellen(self, nur=None):
        self.baum.delete(*self.baum.get_children())
        for eltern, kennung, titel, __ in THEMEN:
            if nur is not None:
                if kennung in nur:
                    self.baum.insert("", "end", iid=kennung, text=titel)
                continue
            self.baum.insert(eltern if eltern and self.baum.exists(eltern) else "", "end", iid=kennung,
                             text=titel, open=not eltern)

    def farben(self):
        p = kth.PALETTE["dunkel" if self.app.dark_mode.get() else "hell"]
        for r in self._rahmen:
            r.configure(highlightbackground=p["rahmen"], highlightcolor=p["rahmen"], bg=p["feld"])
        self.text.configure(bg=p["feld"], fg=p["feld_fg"])
        self.text.tag_configure("verweis", foreground=p["akzent"])
        self.text.tag_configure("treffer", background="#f5d76e" if not self.app.dark_mode.get() else "#7a6420",
                                foreground=p["feld_fg"])

    # -- Suche ---------------------------------------------------------------------------
    def _suchen(self):
        such = self.suche.get().strip().casefold()
        if not such:
            self._baum_fuellen()
            self.treffer_text.configure(text="")
            if self.verlauf:
                self.zeige(self.verlauf[-1], merken=False)
            return
        woerter = such.split()
        treffer = [k for __, k, t, x in THEMEN
                   if all(w in (t + " " + klartext(x)).casefold() for w in woerter)]
        self._baum_fuellen(set(treffer))
        self.treffer_text.configure(text=_("{n} topics found").format(n=len(treffer)) if treffer
                                    else _("Nothing found."))
        if treffer:
            sel = self.baum.selection()
            if not sel or sel[0] not in treffer:
                self.baum.selection_set(treffer[0])
            else:
                self._anzeigen()

    def _erster_treffer(self):
        kinder = self.baum.get_children()
        if kinder:
            self.baum.selection_set(kinder[0])
            self.baum.focus_set()

    # -- Anzeige ----------------------------------------------------------------------------
    def zeige(self, thema, merken=True):
        if thema not in TITEL:                         # z. B. einst_allgemein: Gruppen ohne eigenes Thema
            thema = "einstellungen" if thema.startswith("einst_") else THEMEN[0][1]
        if self.suche.get() and not self.baum.exists(thema):
            self.suche.set("")
        if self.baum.exists(thema):
            self._merken = merken
            self.baum.selection_set(thema)
            self.baum.see(thema)
            self._anzeigen()
        self.lift()

    def zurueck(self):
        if len(self.verlauf) > 1:
            self.verlauf.pop()
            self.zeige(self.verlauf.pop())

    def _pfad(self, kennung):
        eltern = {k: e for e, k, __, __ in THEMEN}
        teile, k = [], eltern.get(kennung)
        while k:
            teile.insert(0, TITEL[k])
            k = eltern.get(k)
        return " › ".join(teile)

    def _anzeigen(self):
        sel = self.baum.selection()
        thema = next((t for t in THEMEN if sel and t[1] == sel[0]), None)
        if thema is None:
            return
        __, kennung, titel, text = thema
        if getattr(self, "_merken", True) and (not self.verlauf or self.verlauf[-1] != kennung):
            self.verlauf.append(kennung)
        self._merken = True
        self.zurueck_knopf.configure(state="normal" if len(self.verlauf) > 1 else "disabled")
        self.pfad.configure(text=self._pfad(kennung))
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", titel + "\n", "titel")
        for i_zeile, zeile in enumerate(text.strip("\n").split("\n")):
            tags = ()
            if zeile.startswith("- "):
                zeile, tags = "•  " + zeile[2:], ("punkt",)
            for i, teil in enumerate(re.split(r"\*\*(.+?)\*\*", zeile)):
                for j, stueck in enumerate(VERWEIS.split(teil)):
                    if j % 2:                           # Verweis
                        ziel = stueck
                        tag = f"v_{ziel}"
                        self.text.insert("end", TITEL.get(ziel, ziel), tags + ("verweis", tag))
                        self.text.tag_bind(tag, "<Button-1>", lambda e, z=ziel: self.zeige(z))
                    elif stueck:
                        self.text.insert("end", stueck, tags + (("fett",) if i % 2 else ()))
            self.text.insert("end", "\n", tags)
        self.text.yview_moveto(0)
        self._markieren()
        self.text.configure(state="disabled")

    def _markieren(self):
        self.text.tag_remove("treffer", "1.0", "end")
        for w in self.suche.get().strip().split():
            start = "1.0"
            while True:
                pos = self.text.search(w, start, stopindex="end", nocase=True)
                if not pos:
                    break
                ende = f"{pos}+{len(w)}c"
                self.text.tag_add("treffer", pos, ende)
                start = ende
        erster = self.text.tag_nextrange("treffer", "1.0")
        if erster:
            self.text.see(erster[0])
