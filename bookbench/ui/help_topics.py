# -*- coding: utf-8 -*-
"""
help_topics.py - Texte der Hilfe (ohne Oberfläche; das Fenster steht in ui/help.py).

  THEMEN          (Elternthema, Kennung, Titel, Text), nur markiert (N_) - übersetzt wird beim Abruf,
                  damit ein Sprachwechsel ohne Neustart wirkt
  themen()        THEMEN übersetzt
  titel()         {kennung: übersetzter Titel}
  thema(bereich)  Kennung des Themas zu einem Bereich
  klartext(text, titel)   Text ohne Auszeichnung, Verweise als Titel (für die Suche)

Text: **fett**, Aufzählungen mit "-", [[kennung]] = Verweis auf ein anderes Thema (zeigt dessen Titel,
anklickbar). Die Kennungen sind die Bereiche des Hauptfensters bzw. feste Namen; "einst_<seite>" gehört
zur Seite <seite> des Einstellungsdialogs. Sie ändern sich mit der Sprache nicht.
"""
import re

from bookbench.i18n import N_, _

# (Elternthema, Kennung, Titel, Text)
THEMEN = [
    ("", "ueberblick", N_("Overview"), N_("""
Bookbench edits EPUB and KEPUB files for KOReader: **chapter names** and levels in the table of contents, **blurbs**, **covers** and **metadata** (title, authors, series …). It also manages your own **dictionaries**, backs up the KOReader settings of the **e-reader** and, on Linux and macOS, shows a book in a **preview** with the settings from the e-reader.

**Workflow**
- Open a folder (Ctrl+O): the books folder on the e-reader, a copy on the computer or the Calibre library.
- In **Table of contents** check the suggestions, change them if needed, apply them.
- In **Metadata** (with blurb and cover) fill in what is missing, apply it.
- **Save** (Ctrl+S) writes all applied changes to the files. A backup of every file is made first.

Only the table of contents and the metadata (and the cover image) are changed, never the book text. Reading positions and highlights in KOReader stay valid.

**More**
- [[status]] - what the coloured dots and the small pictograms mean
- [[tasten]]
- [[dateien]] - where settings, caches and backups are
- [[kosten]] - what is free, what costs money, what leaves the computer
- [[bereiche]] - one chapter per area
- [[einstellungen]] - every setting explained
- [[fehler]]
""")),
    ("ueberblick", "status", N_("Status and markers"), N_("""
The strip to the right of the book lists shows the status of each book:
- **red** ●: changed, not yet applied
- **yellow** ●: applied, not yet saved
- **green** ●: saved (since opening)

Next to the dot small **pictograms** show what is missing or needs a look - each list only those that belong to its area. The **sidebar** shows the same pictograms per area, each with the number of books.

- **Torn page** (red): the file cannot be read.
- **Question mark** (orange): questionable chapter names, not yet decided.
- **Light bulb** (blue): chapter suggestions waiting to be applied.
- **Speech bubble** (grey): no blurb.
- **Picture** (grey): no cover. **Small picture with corners** (orange): cover lower than the limit ([[einst_cover]]).
- **Not-equal sign** (orange): title, authors, series or number differ from Calibre.
- **Label with !** (orange): missing language or an invalid ISBN.
- **Two books with a dashed gap** (orange, sidebar and Book series only): series with missing numbers ([[reihen]]).
- **Floppy disk** (yellow, sidebar only): books with changes that are not saved yet.
- In Dictionary and E-reader: **book** (words looked up without result), **e-reader with !** (dictionaries missing or outdated), **tick** (connected).
- In Library and E-reader: **two arrows** (blue, books to sync with the e-reader) and **arrows against each other** (orange, changed on the computer and on the e-reader), see [[kobo_abgleich]].

Colours: red = error, orange = check it, grey = missing, blue = information, yellow = not saved. Hovering over the strip or a sidebar entry explains the markers. If the markers of an area do not fit into one line of the sidebar, they move to a second line below the name.

In the **library** dot and pictograms are in a column of their own, **Status**, always on the left: a right-click on a column header hides or shows it, its width can be dragged, a click on it sorts (unreadable files first, then the books with the most markers). The title bar shows an asterisk (*) after the version as long as something is not saved.

**Backgrounds**
- In the chapter table questionable rows are **red**; a click shows the reason in the status bar. **Yellowish**: only a number, no name found.

The strip can be switched off: Settings > General > Interface ([[einst_oberflaeche]]). Single pictograms can be hidden per place (sidebar, book lists, status column of the library): [[einst_marken]].
""")),
    ("ueberblick", "tasten", N_("Keyboard shortcuts"), N_("""
**Everywhere**
- **Ctrl+O** open a folder, **F5** reload it
- **Ctrl+I** add books ([[bibliothek_hinzufuegen]])
- **Ctrl+S** save
- **Ctrl+Enter** apply (current book, or the dictionary form)
- **Ctrl+F** search field of the current area (Table of contents, Metadata, Book series, Dictionary), otherwise of the library; **Esc** in a search field empties it
- **Ctrl+B** collapse and expand the sidebar
- **Ctrl+1 … 8** choose an area in the order of the sidebar (8: Preview, Linux/macOS only)
- **F1** help for the current area; in the settings: help for the page shown

**Chapter table**
- **Double-click** or **F2** edits the new name, **Enter** confirms, **Esc** cancels, **Del** restores the original
- **Tab** / **Shift+Tab** (or **Alt+→** / **Alt+←**): level down / up

**Dialogs**
- **Enter** = OK, **Esc** = cancel; in the cover choice a **double-click** takes a cover at once
""")),
    ("ueberblick", "dateien", N_("Files and folders"), N_("""
**Settings folder** (Windows: %APPDATA%\\Bookbench, Linux: ~/.config/bookbench)
- **einstellungen.json**: all settings, including the API key (plain text).
- **tocfix_entscheidungen.json**: applied chapter names, so they are suggested again for other copies of the same book.
- **blurbs_cache.json**: looked-up blurbs and what was already tried without success.
- **vorschau/**: the profile of the preview (Linux/macOS).
- **einlese-cache/**: what was read from the books, per library, so unchanged books open faster ([[einst_bibliothek]]).
Until version 0.23 the two JSON files were next to the program; until 0.24 the folder was called Kobo-Werkstatt (the old name). Both are copied over once. Settings > Advanced shows the paths and opens the folder ([[einst_erweitert]]).

**Backup folder** (default: Bookbench Backups in your user folder)
- Backups of the books before each save: <name>_YYYYMMDD_HHMMSS.epub.
- **KOReader/**: backups of the KOReader settings from the E-reader area.
- **Wörterbücher/**: dictionary files before they are built again.

**In the book folder**
- Nothing is created next to the books; the EPUB files themselves change when saving. A library on this computer ([[bibliothek_rechner]]) gets a hidden folder .bookbench with library.json (folder scheme, e-reader).

**On the e-reader**
- Only what you copy or restore yourself: KOReader settings (in the KOReader folder, e.g. .adds/koreader on a Kobo, [[kobo_geraete]]), dictionaries (data/dict in the KOReader folder), and the books when the e-reader folder is opened and saved.
""")),
    ("ueberblick", "kosten", N_("Costs and privacy"), N_("""
**Free, without a key**
- Google Books and Open Library: blurbs ([[klappentexte_nachschlagen]]) and covers ([[cover_aendern]]). Sent: ISBN, title and author of the book. Google Books without a key shares one daily quota with everyone else; an own key (also free) gives you your own ([[einst_online]]).
- Everything else in the program runs on the computer only, apart from the update check (GitHub, can be switched off: [[einst_updates]]), building a dictionary from a wiki (the wiki you enter) and, when you agree, installing a missing package (pypi.org). No telemetry.

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
    ("", "bereiche", N_("Areas"), N_("""
The sidebar on the left switches between the areas (Ctrl+1 … 8):
- [[bibliothek]] - all books in a table
- [[kapitel]] - table of contents: chapter names and levels
- [[metadaten]] - title, authors, series, publisher, language, ISBN, tags, own fields, blurb and cover
- [[reihen]] - all series with their books, missing numbers and reading state
- [[sammlungen]] - KOReader's collections: own lists of books in your own order
- [[woerterbuch]] - your own dictionaries
- [[kobo]] - the connected e-reader: backups, dictionaries, ejecting
- [[vorschau]] - a book in the desktop KOReader (Linux/macOS)

The toolbar has the buttons of the current area on the left; on the right, separated, Open, Reload and Save (only in Library, Table of contents, Metadata and Book series - the areas with the books of the folder) and Help. [[speichern]] applies to all book areas together. The **Edit** menu only holds the commands of the area shown; Dictionary, E-reader and Preview have menus of their own.

The **book lists** on the left of Table of contents and Metadata (and the list of the dictionary; in the Preview the left column) can be made wider or narrower by dragging the divider to their right; the width is remembered, a double-click on the divider restores the default. A name that does not fit is shown completely in a tooltip when the mouse is over it, together with what its pictograms mean.
""")),
    ("bereiche", "suche_filter", N_("Search and filters in the lists"), N_("""
Above the book lists of **Table of contents** and **Metadata** there is a search field and a filter (the Preview has a book selection instead of a list since 1.4). Each list has its own; they do not affect each other or the library.

- **Search** finds parts of the title, series or author, case does not matter. **×** in the field empties the search, **Esc** search and filter.
- When a filter is active, the line above says how many books are shown: "Books: 3 of 12".
- The book you are working on stays selected as long as it fits. If it no longer fits, the next fitting book below is selected (otherwise the one above).
- **Apply** alone does not refill the list, so the book does not vanish while you work on it. Only changing search or filter, **Reload** or **Apply all** takes it out.
- If a hidden book is opened from elsewhere (double-click in the library), search and filter of that list are reset.
- Ctrl+F jumps to the search field of the current area.

**Filters**
- **Table of contents**: With suggestions, Questionable names (⚠, not yet decided), Some without names (single entries only with a number), Changed chapters (applied or edited, not yet saved).
- **Metadata**: Changed, No blurb, Blurb only in Calibre, Differs from Calibre, No author sort, No language, No ISBN, Edited in KOReader, No cover, Small cover (below the limit in [[einst_cover]]).

Search and filters are not remembered; after a restart all books are shown again.
""")),
    ("bereiche", "bibliothek", N_("Library"), N_("""
All books of the opened folder (with all subfolders) with series, number, author, state of the chapters, blurb and cover.

- A click on a column header sorts (▲ ascending, ▼ descending), a second click reverses. Moving, hiding and widths of the columns: [[bibliothek_spalten]].
- **Search** filters by title, series and author; the **filter** shows only changed books, unreadable files or books whose series is not in the EPUB. Filters by chapters, blurbs and covers are above the lists of those areas ([[suche_filter]]).
- **Double-click** opens the book in the Table of contents area; under Settings > General > Interface it can be Metadata, the Preview or KOReader instead ([[einst_oberflaeche]]).
- **Right-click** on a book: open it in Table of contents, Metadata, the Preview or start it in KOReader (Preview and KOReader not on Windows). The entry marked "Double-click" is the one the double-click uses. **Show series** jumps to the book in [[reihen]]; **Move to series …** and **Add to collection** work on all selected books ([[reihen]], [[sammlungen]]).
- **Several books**: Ctrl+click and Shift+click select more than one; right-click > **Edit metadata of n books** takes them to the Metadata area for editing together ([[metadaten_mehrere]]), **Remove advert text from n books** works on just those; **Look up metadata …** opens the look-up window for the selected books ([[metadaten_nachschlagen]]).
- **New books**: File > Add books (Ctrl+I) or drag them onto the window ([[bibliothek_hinzufuegen]]); a library on this computer instead of the e-reader: [[bibliothek_rechner]].
- **Advert lines** like OceanofPDF.com: Edit > Remove advert text … ([[bibliothek_cleaner]]).

**Columns**
- **Chapters**: **suggestions** (the book text has chapter names the table of contents lacks), **without names** (only numbers, nothing in the text either), **no names found** (only a few matches - probably coincidence, so nothing is suggested), **ok**, **ok (2 without names)** (almost all have names, single ones only a number, e.g. a prologue).
- **Blurb**: where it comes from (Google Books, Calibre, a website), "yes" if unknown, "in Calibre" if only Calibre has one, "changed".
- **Cover**: size of the title image in pixels, "changed" for a new one not yet saved.
- **Series**: from the EPUB; if it is only in Calibre or KOReader's data, the status bar says where from ([[bibliothek_calibre]]).
- **Publisher**, **Language**, **ISBN**, **Published**: hidden at first; show them with a right-click on a header or View > Library columns.
- **Read status**, **Last read**, **Reading time**: what KOReader knows about your reading - unread, 53 %, finished, on hold ([[bibliothek_lesestand]]). Last read and Reading time are hidden at first.
- **Status** (left): the coloured dot and the pictograms of each book ([[status]]).

**Filters** All books, Changed (anything not yet saved, or saved since opening), Unreadable files, No series in the EPUB; Unread, Currently reading, Finished, On hold from KOReader's reading state ([[bibliothek_lesestand]]).
""")),
    ("bibliothek", "bibliothek_hinzufuegen", N_("Adding books"), N_("""
File > **Add books …** (Ctrl+I) opens a window for new books. Put EPUB or KEPUB files in with **Add files …**, **Add folder …** (with all subfolders) or simply drag them onto the window or the main window.

**The list**
- One row per file with title, author, series, number and where it will go (**→** path in the library, following the folder scheme, [[bibliothek_ordnerschema]]).
- **Action** per book: Add, Skip, Replace existing, Keep both. Several rows at once: select them and use **Set action for selected …**.
- **⧉ Possible duplicate**: the library already has the book, recognised in this order by the Calibre ID, the ISBN, or title and first author (ignoring case, punctuation and a leading "The"). Duplicates are set to Skip; you decide.
- **Replace existing** overwrites the existing file **at its path**, so KOReader keeps the reading position and highlights (they are stored next to the file name). A backup is made first ([[speichern]]).
- **Keep both** adds the new copy next to it; if the path is taken, " (2)" is added to the name.
- Unreadable files are shown with ⚠ and skipped.

**Checking metadata**
On the right: title, authors, author sort, series, number and ISBN of the selected book. Changes go into the copy in the library, the original file stays as it is; the target path follows at once. Everything else (blurb, cover, own fields) afterwards in the Metadata area.

**Add n books** copies the books, then the library is read again (only the new books really, thanks to the reading cache, [[einst_bibliothek]]) and the first new book is selected. Unsaved changes in the library must be saved or discarded first.

Bookbench does not convert to KEPUB: EPUB is fine for KOReader, existing KEPUB files are taken as they are.
""")),
    ("bibliothek", "bibliothek_ordnerschema", N_("Folder scheme"), N_("""
The folder scheme says where a new book goes inside the library, e.g. **{author_sort}/[{series}/][{series_index:2} - ]{title}** gives "Abnett, Dan/The Horus Heresy/01 - Horus Rising.epub", and for a book without a series "Abnett, Dan/Ravenor.epub".

- Placeholders like in Calibre: {title}, {authors}, {author} (first author), {author_sort}, {series}, {series_index}, {publisher}, {language}, {isbn}.
- **{series_index:2}** fills up to two digits with zeros (3 → 03; 1.5 stays 1.5).
- **[…]**: the part in square brackets is left out when a placeholder in it is empty.
- Characters that Windows or the e-reader do not allow (: ? * " < > | \\ /) become _.

**Where the scheme comes from**
1. Saved for this library (Settings > Books > Library and import, [[einst_bibliothek]]).
2. Otherwise detected from the books: Bookbench puts the metadata of every book into its path and looks for the scheme most books follow. It is used if at least half of the books match, and saved with the first books added.
3. Otherwise the default from the settings.

Existing books are never moved or renamed - not even when the scheme changes.
""")),
    ("bibliothek", "bibliothek_rechner", N_("Library on this computer"), N_("""
Since 2.1 the main copy of the books can live in a folder on this computer, like in Calibre, and the e-reader gets them from there. Editing directly on the e-reader keeps working as before.

**New library from e-reader** (File menu): copies all books of the connected e-reader into a folder on this computer, with the same folder structure. KOReader's .sdr folders (reading positions, highlights) stay on the e-reader. The folder scheme is detected from the books ([[bibliothek_ordnerschema]]) and the new library is opened. Running it again into the same folder only copies what is missing or different.

**.bookbench folder**: the library folder gets a hidden folder .bookbench with library.json (folder scheme, which e-reader belongs to it). It lies in the library folder on purpose: if the folder moves or is synced between Windows and Linux, this comes along.

New or changed books get to the e-reader (and back) with the sync in the E-reader area ([[kobo_abgleich]]).
""")),
    ("bibliothek", "bibliothek_cleaner", N_("Removing advert text"), N_("""
Some books carry lines like "OceanofPDF.com" at the end of each chapter. **Edit > Remove advert text …** (in the Library area) searches all books for them, **right-click a book in the library > Remove advert text …** only that book.

**The window**
- One entry per book with its places, each with the text around it: …before ⟦found⟧ after….
- **Removes**: *whole <div>* (or p, a …) - the text stands in a container of its own, the container goes too, so no empty line stays behind. *Text only* - the text stands in a paragraph with other content, only the text goes.
- Everything is checked; untick places or whole books you want to keep.
- **Remove n places** writes the books right away (a backup is made first, [[speichern]]) and reads them again. Books with unsaved changes are skipped; save or discard first, then **Search again**.
- **Patterns …** opens the settings ([[einst_cleaner]]).

A **link** whose address matches counts too, however it is labelled: it is shown as label → address (e.g. "Download more books → https://oceanofpdf.com") and removed as a whole. Matches in other attributes (an image file name, a class) do not count.

Text in the head of a file (e.g. the title of a chapter file) is not touched. KOReader may shift a bookmark or the reading position in the same chapter by a line.
""")),
    ("bibliothek", "bibliothek_lesestand", N_("Reading state from KOReader"), N_("""
Bookbench shows what KOReader knows about your reading. It only **reads** it and never writes anything back - mark a book as finished in KOReader itself.

**Where it comes from**
- **Status, progress, rating, highlights** from the book's data folder next to it (Book.sdr/metadata.epub.lua): KOReader writes "reading", "finished" or "on hold" (older KOReader: "abandoned") there, and how far you are. A book without such a folder was never opened: **unread**.
- **Reading time, pages read, last read** from KOReader's reading statistics (settings/statistics.sqlite3 in the KOReader folder of the e-reader), if the statistics plugin is on. Bookbench finds the book there by KOReader's own checksum, otherwise by title and first author.

**When it is read**
- **Folder on the e-reader** opened (or the e-reader itself): fresh on every reading-in (F5).
- **Library on this computer** linked with the e-reader ([[kobo_abgleich]]): when the e-reader is connected, Bookbench reads the state of all books there and notes it in the library's library.json. Without the e-reader you see that note; the library header says from when (the tooltip names the e-reader). Books that were not on the e-reader count as unread.
- Other folders: only if .sdr folders lie next to the books (a copy of the e-reader), without statistics.

**Where you see it**
- Library: columns **Read status** (unread, 53 %, finished, on hold), **Last read** and **Reading time** (the last two hidden at first: right-click on a header), sortable; filters **Unread**, **Currently reading**, **Finished**, **On hold**.
- Status bar when a book is selected, and the line above the form in the Metadata area: finished on …, last read, reading time, pages read, rating stars, highlights.
""")),
    ("bibliothek", "bibliothek_spalten", N_("Columns: sorting, moving, widths"), N_("""
**Sorting**
- A click on a column header sorts by it, a second click reverses. The arrow ▲ (ascending) or ▼ (descending) shows the column.
- Series sorts by series, then number, then title; No. by number; Cover by the height in pixels (no cover first); Status puts unreadable files first, then the books with the most markers.
- Right-click on a header: **Sort ascending** / **Sort descending** for this column.

**Moving columns**
- Drag a header sideways (hold the mouse button or touchpad): the column moves along and stays where you release it.
- Without dragging: right-click on the header > **Move "…" left** / **right**.

**Showing and hiding**
- Right-click on a header, or View > **Library columns**: one tick per column. A shown column comes back at its usual place. The last column cannot be hidden.
- **Status** is always the first column and cannot be moved; it can be hidden like the others.

**Widths**
- Drag the line between two headers. The widths stay exactly as drawn, also after resizing the window or a restart; no column stretches by itself. If the columns are wider than the window, a scroll bar appears below.
- As long as no width has been drawn, the columns are fitted to the window whenever its size changes.
- **Status** is as wide as the book with the most pictograms needs, unless you drag it.
- **Fit columns to the window** spreads the visible columns over the width, keeping their proportions.
- **Reset columns**: usual order, all columns, default widths fitted to the window.

Order, shown columns, widths and sorting are remembered in the settings.
""")),
    ("bibliothek", "bibliothek_calibre", N_("Calibre and series"), N_("""
**Series and blurbs from Calibre** (toolbar of the library) takes series, number and blurb from Calibre's **metadata.calibre**, but only where the EPUB has nothing - existing data is never overwritten. Then save as usual (Ctrl+S); after that the data is in the book itself, and KOReader, Bookshelf and the reading software of the e-reader see it without Calibre too.

**Where the file is**
Calibre writes metadata.calibre into the root folder of the e-reader when transferring books. It is searched for in the opened folder and in all folders above it; for a copy on the computer simply copy the file into the books folder too. Books are matched by path, file name, Calibre UUID or title and author.

**Where a series comes from**
- From the EPUB (Calibre or EPUB 3 notation).
- Only in metadata.calibre: shown, the status bar says so, the filter **No series in the EPUB** lists these books.
- Only in KOReader's own book data (metadata edited in KOReader, folder .sdr next to the book): shown too - this only works if the folder with the .sdr folders is opened, e.g. the e-reader directly.

In the Metadata area, **From Calibre** next to the blurb puts Calibre's description of a single book into the text field.
""")),
    ("bereiche", "kapitel", N_("Table of contents"), N_("""
The books on the left, the table of contents on the right: **Entry** (as in the book), **New** (suggestion or own name), **Note**. Below are the first lines of book text at the selected entry.

The table of contents is a tree: sub-entries are indented below their parent, the small arrow in front folds them in and out.

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
    ("kapitel", "kapitel_ebenen", N_("Changing levels"), N_("""
- Select entries (several with Ctrl- or Shift-click), then **Tab** or **Alt+→** (or **Down** in the toolbar) moves them one level down, **Shift+Tab** or **Alt+←** (or **Up**) one level up.
- Sub-entries move along, as in Word's outline view.
- An entry can be at most one level deeper than the one above; the first one is always at the top. What is not possible is said in the status bar.
- Column Note: "Level 2 → 3". Apply and save as with the names.
- When saving, the nesting in nav.xhtml and toc.ncx is rebuilt; the entries themselves (links, names, IDs) stay unchanged, reading positions in KOReader stay valid. Bookends (%chap_title_1 etc.) follows it.
- If nav.xhtml and toc.ncx have a different number of entries, the levels of this book cannot be changed; the status bar gives the reason.
""")),
    ("kapitel", "kapitel_fragwuerdig", N_("Questionable names and decisions"), N_("""
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
    ("bereiche", "metadaten", N_("Metadata"), N_("""
The books on the left, in the middle a form with the metadata stored in the book: **title**, **authors**, **author sort**, **series** and **number**, **publisher**, **published**, **language**, **ISBN** and **tags**, followed by your **own fields** from Calibre columns ([[metadaten_felder]]). Below the form the **blurb** ([[klappentexte]]), on the right the **cover** ([[cover]]).

Several books at once: select them with Ctrl+click or Shift+click in the list ([[metadaten_mehrere]]).

- Type in the fields; the book turns red (changed, not applied). **Apply** (Ctrl+Enter or Enter in a field) applies form and blurb and makes the book yellow, **Save** (Ctrl+S) writes it into the file, with backup.
- **Discard** restores values, blurb and cover from the file. This also drops a series taken over with **Series and blurbs from Calibre** in the library.
- Several authors are separated with **&**, as in Calibre: "Dan Abnett & Graham McNeill". The **author sort** works the same way ("Abnett, Dan & McNeill, Graham"); with as many names as authors each author gets his own, otherwise the first one gets the whole text.
- **Number** sits behind the series and only takes numbers; the arrows (or arrow up/down, mouse wheel) count up and down. It may have decimals, e.g. 1.5 or 0.9 for a story between two books; a comma is turned into a point, as in Calibre.
- **to** behind the number is only for a **collection** (omnibus): an omnibus of books 1 to 3 gets number 1 and to 3; leave it empty for a single book. Calibre and KOReader only know one number, so they see 1 and sort the omnibus where book 1 would be. Bookbench keeps the last number in the book itself (an extra entry Calibre and KOReader leave alone), shows "1–3" in the library and counts 2 and 3 as present in [[reihen]]. **Number series** keeps the range: after an omnibus 1–3 the next book gets 4.
- **Tags** are separated with commas.
- **Suggestions:** authors, series, publisher, language, tags and own text fields suggest values from the other books while you type; **arrow down** in an empty field shows all. With several authors or tags the suggestion is for the part after the last & or comma.
- **Language** as a code, e.g. en, de or en-GB. KOReader uses it for hyphenation.
- **Published** is the publication date (dc:date in the book, where Calibre and KOReader read it): 2015, 2015-03 or 2015-03-01; 1.3.2015 or 3.2015 are turned into that form when applying. A year and a full date of the same year count as equal when comparing with Calibre. Can be switched off in [[einst_metadaten]].
- Below the form Bookbench warns about an invalid ISBN, an impossible date, a missing language or title, a number without series and values that do not fit an own field (e.g. letters in a number column).
- If Calibre or KOReader have a different value, it is shown behind the field (below it when there is not enough room): **← Calibre: …**. A click on ← puts it into the field ([[metadaten_calibre]]). This needs Calibre's metadata.calibre next to the books; without it there is nothing to compare, and the one-time import ([[calibre_import]]) is the way to take Calibre's values.

The cover panel on the right can be made wider or narrower with the divider between form and cover; the width is remembered, a double-click on the divider restores the default.

The file name is never changed: KOReader keeps reading positions and highlights in a folder named after the file (.sdr), they would be lost.

After saving, KOReader only shows the new values after re-reading the book information (Cover browser > Extract and cache book information).

**Toolbar**: Apply, Discard, **Look up …** ([[metadaten_nachschlagen]]), From Calibre (only with the Calibre comparison on), **Complete ▾** for all books: look up all missing blurbs, look up all missing covers, import from a Calibre library ([[calibre_import]]), fill metadata gaps from Calibre; **Several books ▾** for the selected books ([[metadaten_mehrere]]).

**Markers** in the list show what a book lacks: speech bubble (blurb), picture (cover), not-equal sign (Calibre), label (language/ISBN) - see [[status]].

**More**
- [[metadaten_nachschlagen]] - looking up metadata, blurb and cover
- [[metadaten_mehrere]] - editing several books at once
- [[metadaten_calibre]] - comparing with Calibre and KOReader
- [[calibre_import]] - taking Calibre's data over once
- [[metadaten_felder]]
- [[klappentexte]]
- [[cover]]
- [[suche_filter]]
""")),
    ("metadaten", "metadaten_nachschlagen", N_("Looking up metadata"), N_("""
**Look up …** in the toolbar of the Metadata area (also Edit > Look up metadata … and right-click in the library) asks Google Books and Open Library for the selected book and shows what they know, like Calibre's "Download metadata". Free; an own Google Books key avoids the shared quota ([[einst_online]]).

**Search**
- Title, author and ISBN come from the book and can be changed; Enter or **Search** searches again.
- **Language**: "Same as the book" (or the preferred language from [[einst_klappentexte]]). Another language searches without the ISBN - an ISBN belongs to exactly one edition, the one of your book - and only finds editions in that language. Their title may be a translation: type it into the title field if nothing turns up.

**Hits** (left) with a small cover, title, author, publisher, date, language and source. Open Library often has several editions under one work; its hits come without ISBN for that reason.

**Comparison** (right): one row per field - Now (the book) and Hit - plus subtitle (if you have an own field like #subtitle, [[metadaten_felder]]), blurb (whole text as tooltip) and cover (both images).
- Ticked at first are only fields the book does not have. Values the book already has are only replaced if you tick them; equal values show (=) and cannot be ticked.
- A click on a row ticks or unticks it. **Open the hit's page** shows the source in the browser.
- Tags from Google Books are its categories ("Fiction / Science Fiction" becomes Fiction, Science Fiction).

**Apply** puts the ticked values into the book like the form does (yellow), the blurb as applied and the cover through the cover panel (format and size as set in [[einst_cover]]). **Save** (Ctrl+S) writes them with backup.

**Several books** selected ([[metadaten_mehrere]]): the window goes through them one after another - **Apply and next** (Ctrl+Enter) or **Skip**. After the last book it closes; the status bar says how many were changed.
""")),
    ("metadaten", "metadaten_mehrere", N_("Several books at once"), N_("""
Select several books in the list on the left: **Ctrl+click** adds or removes a book, **Shift+click** selects a range, **Ctrl+A** (or Several books ▾ > Select all books in the list) selects everything the search and filter show. In the library, select books the same way and right-click > **Edit metadata of n books**.

**The form with several books**
- A field shows the value all selected books share. Where they differ it stays empty with **(various)** in grey.
- Only fields you **type into** count; their label turns red. A field you empty is cleared in all books. Fields you do not touch keep each book's own value - so you can set the publisher of 20 books without touching their titles.
- **Authors**, **tags** and own list fields have a choice behind them: **Replace** (the field gets exactly what you typed), **Add** (your values are added, nothing twice) or **Remove** (your values are taken out, upper/lower case does not matter). Separate several values with & (authors) or a comma (tags).
- **Apply** (Ctrl+Enter) first shows a **preview**: every book with the fields that change, before and after, and warnings (e.g. an impossible date). Apply there puts the values into the books like the form (yellow); **Save** (Ctrl+S) writes them, with a backup of each file.
- **Discard** asks, then restores metadata, blurb and cover of all selected books that have changes.
- Blurb and cover stay empty while several books are selected; they are edited one book at a time.

**Several books ▾** (toolbar)
- **Number series …**: numbers the selected books in the order of the list, from a start value with a step (0.5 gives 1, 1.5, 2 …). Optionally gives them all the same series; empty keeps each book's series. Sort or filter the list first if the order is not right.
- **Search and replace …**: in one field of the selected books (with one book selected: only that one). Without **regular expression** the text is taken literally; with it, \\1 in the replacement inserts the first group. **Match case** is off by default. The window counts the books with a match.
- **Author sort from authors**: sets the author sort the way Calibre does by default ("Dan Abnett & Nick Kyme" → "Abnett, Dan & Kyme, Nick").
- All three show the preview first, like Apply.
""")),
    ("metadaten", "metadaten_calibre", N_("Calibre and KOReader"), N_("""
**Calibre**
If Calibre's **metadata.calibre** is found ([[bibliothek_calibre]]) and the comparison is on ([[einst_metadaten]]), Calibre's value is shown next to (or below) every field where it differs: **← Calibre: …**. A click on **←** puts the value into the field. Matching values are not shown.

- **From Calibre** (toolbar) puts all differing values of this book into the form - check them, then apply.
- **Complete ▾ > Fill metadata gaps from Calibre** (also in the Edit menu of the library) works on all books, but only on fields that are empty in the book. It applies directly (yellow); save afterwards.
- A **not-equal sign** in the list means title, authors, series or number differ from Calibre. The filter **Differs from Calibre** also counts the other fields.
- Calibre stores languages as three letters (eng); Bookbench compares them with the two-letter codes of the book (en) and takes over the short form.

**Important:** When Calibre sends a book to the e-reader again, it writes its own values into the file. Change the metadata in Calibre as well, otherwise your changes in Bookbench are overwritten. If you no longer use Calibre, switch the comparison off: [[einst_metadaten]].

**KOReader**
If you edited the book information in KOReader itself (Book information > long-press a field), KOReader keeps it in **custom_metadata.lua** in the .sdr folder next to the book and shows it **instead of** the values in the file. Bookbench shows these values next to the fields as **← KOReader: …** (only when the folder with the .sdr folders is opened, e.g. the e-reader directly) and points it out below the form. The filter **Edited in KOReader** lists these books. To make KOReader show the file again, reset the fields in KOReader.
""")),
    ("metadaten", "metadaten_felder", N_("Own fields"), N_("""
In Calibre you can add columns of your own (Preferences > Add your own columns), e.g. a subtitle with the lookup name **#subtitle**. Bookbench shows such columns as further fields below the usual ones - which ones and with what label, you decide in [[einst_metadaten]]. The label is yours and is not translated: a column named "Untertitel" in Calibre stays "Untertitel" in the English interface until you rename it there. **From Calibre** there adds all columns found in metadata.calibre at once.

- Bookbench reads and writes the columns the way Calibre stores them in the book: in EPUB 2 one entry per column, in EPUB 3 all own columns together in one entry. Columns you do not show stay untouched.
- If the book does not have a column yet, Bookbench takes its definition (type, how values are separated) from metadata.calibre, so Calibre recognises it when adding the book again. Without metadata.calibre a plain text column is written.
- Columns with several values ("Ampersand separated text", "Comma separated text") are shown joined with " & " or ", ". Careful: a text containing **&** is then split into two values, just like in Calibre.
- Number columns (whole numbers, decimals, rating) only take numbers, yes/no columns yes or no; dates are shown without time.
- KOReader only knows title, authors, series, language, tags and description; own fields are for Calibre and for you.
""")),
    ("metadaten", "calibre_import", N_("Import from Calibre"), N_("""
If you want to stop using Calibre, take its metadata over once into the books: **File > Import from Calibre library …** (also in **Complete ▾** in the Metadata area).

1. Choose the folder of your Calibre library, the one with **metadata.db** (in Calibre: right-click the library button > Show folder). Bookbench remembers it. The database is only read, so Calibre may stay open.
2. Bookbench matches the books of the opened folder with Calibre: by the Calibre ID in the book (UUID), the ISBN, or title and first author. Only unique matches count; books without a match are listed on the tab **Not matched**.
3. The table shows every field where Calibre has a different value: book, field, value in the book, value from Calibre. Untick rows you do not want (click on the box or press Space). **Only empty fields** shows only fields that are empty in the book. **Blurbs** adds Calibre's descriptions.
4. If Calibre has own columns (e.g. #subtitle) that are not fields yet, **Add as own fields** adds them ([[metadaten_felder]]); then their values appear in the table too.
5. **Apply ticked** applies the values (yellow), then save with Ctrl+S.

Afterwards switch the Calibre comparison off ([[einst_metadaten]]) if Calibre does not manage the books anymore. Calibre's own fields like date added, rating stars or read status only come along as own columns.
""")),
    ("metadaten", "klappentexte", N_("Blurb"), N_("""
The blurb is below the form in the Metadata area. The text can be edited directly; the divider between form and blurb can be dragged (a double-click puts it back below the form). If the form no longer fits above it, it gets a scrollbar (the mouse wheel scrolls it too).

- Books without a blurb have a **speech bubble** in the list. If Calibre has a description for the book, the status bar says so when the mouse is over it; the filter **Blurb only in Calibre** lists these books.
- **Apply** (Ctrl+Enter) applies the text together with the form, **Discard** restores both from the file. An empty field applied = remove the blurb.
- **Look up** and **From Calibre** are small buttons above the text; **Complete ▾** in the toolbar looks up all missing blurbs. The window **Look up …** (toolbar) shows the blurbs of several editions to choose from, also in another language ([[metadaten_nachschlagen]]).
- Below the text: where it comes from. This is also saved in the EPUB (meta bookbench:blurb-source) and shown in the Blurb column of the library.

After saving, re-read the book information in KOReader (Cover browser > Extract and cache book information), otherwise Bookshelf still shows the old state.

**More**
- [[suche_filter]]
- [[klappentexte_nachschlagen]]
- [[klappentexte_profile]]
""")),
    ("klappentexte", "klappentexte_nachschlagen", N_("Looking up blurbs"), N_("""
**Look up** (one book, above the blurb) and **Complete ▾ > Look up all missing blurbs** (all without a blurb, in the background) go through these steps until one has a text:
- **Google Books**, then **Open Library**: by ISBN, otherwise by title and author; the edition in the book's language is preferred. Free; for Google Books an own key is optional ([[kosten]]).
- **Language**: normally the book's own (dc:language). With another **preferred language** ([[einst_klappentexte]]), e.g. German for your English books, the search goes without the ISBN (it belongs to the English edition) and only finds editions in that language; Claude is told to take the blurb of that edition. Works best where the title is the same in both languages (Eisenhorn); for a translated title use the window Look up … and type the title there ([[metadaten_nachschlagen]]).
- **Claude** with the first source profile that fits the book ([[klappentexte_profile]]): fetches the pages of the profile and copies the publisher blurb word for word. About 1 to 2 cents.

A text that is too short or too long is not taken (limits: [[einst_klappentexte]]). What was found is not applied at once: it is in the text field (red) until you apply it.

**Look up all**
- Skips books for which Calibre has a description - **From Calibre** is there for those, and it costs nothing.
- Asks before starting if Claude could be needed, with the maximum cost.
- Without an API key only the free sources are asked, without an error message.

**When nothing is found**
The message at the end says per source why, and below the blurb the result of the last look-up stays as long as the book has no text:
- **daily quota used up (429)**: Google Books without a key shares one daily quota with everyone else and often answers like this. An own key ([[einst_online]]) gives you your own quota.
- **book found, but no blurb stored**: the source knows the book but has no description (Open Library often).
- **book not found**: no matching title and author (or ISBN).
A quota or network error is not remembered as tried; the next look-up asks that source again.

**Cache**
What was found and what was already tried is in **blurbs_cache.json** ([[dateien]]). Looking up again costs nothing. Another preferred language has entries of its own, so an English hit does not stop the German look-up. If a profile is changed, Claude tries again for the books it covers; the free sources are asked again only after a network error. The cache can be emptied: [[einst_erweitert]].

Claude needs an API key and the package **anthropic** (pip install anthropic): [[einst_online]].
""")),
    ("klappentexte", "klappentexte_profile", N_("Source profiles"), N_("""
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
    ("metadaten", "cover", N_("Cover"), N_("""
The cover is shown right of the form, as large as there is room. **Click on the cover** (also the small one in Table of contents) shows it as large as the screen allows; a second click on the cover, a click into the window or Esc closes it. Choosing another book closes it too. A right-click opens a menu with all cover actions.

- Below the cover: size in pixels, format, file size and where it is in the EPUB.
- **From file …**, **Look up**, **Export …** (saves the cover shown as an image file) and **Discard new** are below the cover; **Complete ▾ > Look up all missing covers** is in the toolbar.
- As long as a new cover is not saved, the old one and the new one are shown next to or below each other.
- Books without a cover have a **picture**, covers lower than the limit a **small picture** in the list ([[einst_cover]]); the filters **No cover** and **Small cover** list them.

After saving, re-read the book information in KOReader (Cover browser > Extract and cache book information), otherwise the cover browser still shows the old cover.

**More**
- [[cover_aendern]]
- [[cover_bild]]
""")),
    ("cover", "cover_aendern", N_("Changing and looking up covers"), N_("""
- **From file** takes an image file (JPEG, PNG, GIF, WebP).
- **Look up** searches Open Library and Google Books (free, no key) by ISBN, title and author and shows what was found side by side, with size; a click chooses, OK takes it, a double-click takes it at once. Tiny preview images are left out.
- **Complete ▾ > Look up all missing covers** does that in the background for all books without a cover and takes the largest image found. Check them afterwards.
- **Discard** drops the new cover. **Ctrl+S** saves, with a backup as always.

The sources, the smallest height that counts and how many to choose from: [[einst_cover_nachschlagen]].

**Tips**
- Open Library often has large scans, sometimes of another edition (another cover). Google Books has the publisher's image, usually smaller.
- The Edit menu has the same actions while Metadata is shown; **Look up all missing covers** also in the library.
""")),
    ("cover", "cover_bild", N_("What happens to the image"), N_("""
- The new cover keeps the **format** and the **file name** of the old one (a PNG becomes a JPEG if the old cover is a JPEG). That way the manifest and a title page that shows the image stay valid.
- It is shrunk only if it is higher than the limit in the settings (0 = never); it is never enlarged ([[einst_cover]]). If nothing has to be converted or shrunk, the file goes into the book unchanged, byte for byte.
- A book without a cover gets cover-bookbench.jpg next to the content.opf, an entry in the manifest (EPUB 3: properties="cover-image") and <meta name="cover"> (EPUB 2; KOReader reads both).
- Converting and shrinking need **Pillow** (pip install pillow); showing works without it. Without Pillow only an image in the right format can be inserted unchanged.
- Transparent areas become white when converting to JPEG.
""")),
    ("bereiche", "reihen", N_("Book series"), N_("""
All series of the opened folder in one list, each with its books below it (click the arrow or **Expand all**). Books in the same series are found by the series name; upper/lower case and extra spaces do not matter.

**Columns of a series**
- **No.**: lowest and highest number.
- **Author**: the authors of its books (all of them in the tooltip).
- **Read status**: how many books are finished, from KOReader's reading state ([[bibliothek_lesestand]]). Empty as long as Bookbench knows nothing about your reading.
- **Next**: the book you are reading (the one with the lowest number if several), otherwise the first unread one. Books on hold are skipped. In the list of books it is in **bold**.
- **Missing**: missing numbers, numbers that appear twice and books without a number.

**Missing numbers** are the whole numbers from 1 to the highest number that no book has. They are shown in grey between the books where they are missing (e.g. "missing (4)" at 3–6). Numbers with decimals like 0.9 or 1.5 (novellas, short stories between two novels) never count as missing, and they do not fill a gap either: with 0.9, 1.5 and 2, number 1 is missing. A series that starts at 0 is fine. Series numbered above 999 (years and the like) are not checked. A series with missing numbers gets the gap pictogram, in the list and in the sidebar ([[status]]).

**Search and filter**: the search looks in the series name and in titles and authors of its books. Filters: All series, With gaps, Numbers to check (duplicates, books without number), Started not finished, Not started, Finished, and **Books without series** (a plain list of the books that have no series yet).

**Commands**
- **Number series …** (toolbar, or right-click on a series): selects the books of the series in the [[metadaten]] area in the order of their numbers and opens Number series there ([[metadaten_mehrere]]). After the preview the new numbers are applied (yellow) and shown here right away; **Save** (Ctrl+S) writes them.
- Right-click on a series: **Edit metadata of n books** (all books of the series in the Metadata area), **Show series in Library** (library search set to the series name), **Move whole series …** (rename it, or merge it into another), **Collection from series** (a collection with its books in number order, [[sammlungen]]) and **Add to collection**.
- **Move to series …** (right-click on books, several with Ctrl+click or Shift+click; also in the library): choose a series from the list or type a new one, and what happens to the numbers - keep them, add the books at the end of the series (after its highest number) or number them from a start value. A collection (omnibus 1–3) keeps its range. An empty series removes series and number. The preview shows every change first; Save (Ctrl+S) writes it.
- Double-click (or Enter) on a book opens it like in the library ([[einst_oberflaeche]]); right-click offers the other places and **Show in Library**. In the library, right-click > **Show series** jumps here.

**Collections (omnibus)**: a book with a range in Metadata (number 1, to 3) covers 1, 2 and 3. It shows "1–3", and below it the books it contains, named after the top entries of its table of contents when there are enough of them (otherwise "in this collection"). Having book 2 on its own as well does not count as a duplicate.

Series and numbers that are applied but not yet saved already count here.
""")),
    ("bereiche", "sammlungen", N_("Collections"), N_("""
KOReader's **collections** are your own lists of books: Favorites, "To read", a custom omnibus. KOReader shows them in the file manager (Collections) and Bookshelf can show them as shelves. A book can be in several collections; it stays where it is, a collection only points to it.

**Where they are saved**
- In a **library on this computer** ([[bibliothek_rechner]]) in its .bookbench/library.json. The sync in the E-reader area takes them to the e-reader and brings changes made there back ([[kobo_abgleich]]).
- With the **e-reader** opened directly: in KOReader's settings/collection.lua on the e-reader, backed up before every change. KOReader reads it when it starts next.
- In any other folder there are no collections.
Every change is saved at once (no Save needed).

**On the left** the collections, Favorites first. **New …**, **Rename …**, **Delete** (the books stay; Favorites cannot be renamed or deleted).

**On the right** the entries of the selected collection in reading order, with series and read status. Drag entries to another place, or use **Move up** / **Move down**. **Add books …** chooses books from the library (several with Ctrl+click), **Remove** (or Del) takes entries out of the collection. **Sort by series number** sorts by series and number. A double-click opens a book. Once Bookbench has set the order, KOReader shows the collection sorted by hand, in that order.

**Paste reading order …** (toolbar) creates a collection from a list, e.g. the reading order of an omnibus on heresyomnibus.com: copy the list from the page and paste it. One entry per line like "2. The Wolf of Ash and Fire (EoT) by Graham McNeill"; number, the short name of an anthology in brackets and "by …" are optional, also on lines of their own. Each line is matched to a book of the library by title (a series before a colon, upper/lower case and punctuation do not matter) and author; the window shows the result at once.
- Lines with the short name of an anthology are **stories in an anthology**: Bookbench looks for the title in the tables of contents of all books and makes it a story entry (see below).
- What is not found becomes a grey **placeholder** that keeps its place. **Choose …** replaces it with a book, or for a story with an entry of an anthology. Placeholders are not written to the e-reader, but the numbering there leaves their place free.

**Stories in anthologies** ([[sammlungen_geschichten]]): **Add story …** picks a book and an entry of its table of contents. The story then is an entry of the collection like a book.

**From other areas**: right-click in the library or in Book series > **Add to collection** (an existing one or a new one); in Book series also **Collection from series**.
""")),
    ("sammlungen", "sammlungen_geschichten", N_("Stories in anthologies"), N_("""
A KOReader collection can only hold whole files. With Bookbench's patch **2-bookbench-stories** on the e-reader it can also hold a story inside an anthology - without cutting the story out into a file of its own.

**In Bookbench**: **Add story …** in the Collections area. On the left the books (the search also looks into their tables of contents), on the right the table of contents of the selected book. One entry = the story runs to the next entry of the same or a higher level; several entries in a row = a story with parts, from the first to the last. The title is that of the entry, it can be changed. Stories from a pasted reading order are found by title. Entries are matched in KOReader by their title (and which one it is, if the title appears more than once), so **save** changed chapter names before syncing.

**On the e-reader** (patch needed - **Install patch** in the Collections area when the e-reader is opened directly, or Preview > Patches):
- The collection shows the story at its place, with "in <anthology>" and ✓ or a percentage once it was read.
- Tapping opens the anthology right at the start of the story, or where you stopped. The story has a **reading position of its own**: the anthology keeps its own (KOReader's progress of the anthology is put back when you leave the story).
- At the **end of the story** (when you turn past its last page) a window offers: **Next: …** (the next entry of the collection, book or story), **Back to "collection"**, **Read on in this book** (leave the story and go on in the anthology from here) and **Back to the last page**.
- **Long-press** a story: open it, open the book normally, mark it read or unread.
- Arranging a collection by hand in KOReader keeps the stories at their new place until Bookbench writes the collection anew.

**Reading state**: the patch notes progress and "read" per story in settings/bookbench_stories_state.lua on the e-reader. Bookbench shows it in the Collections area when the e-reader is opened directly.

**Limits**: only EPUB (reflowable books). The time KOReader's statistics count goes to the anthology. Bookshelf's collection shelves show only the books, not the stories.

The files on the e-reader: settings/collection.lua (the books, as KOReader knows them), settings/bookbench_stories.lua (the stories, written by Bookbench), settings/bookbench_stories_state.lua (written by the patch).
""")),
    ("bereiche", "woerterbuch", N_("Dictionary"), N_("""
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
    ("woerterbuch", "woerterbuch_anzeigen", N_("Views and missing terms"), N_("""
- **Entries**: everything in the dictionary. The search also finds other names ("Strider" finds Aragorn).
- **Missing terms**: names from the books without an entry (from the step Search books) and **words that were looked up in KOReader and are missing** (dictionary pictogram in the list, first). The lookup history comes from the connected e-reader, otherwise from the newest backup of the KOReader settings ([[kobo_sicherungen]]). Everyday words in lower case are left out.
- Which looked-up words belong to which dictionary is decided by the searched books and the **books filter** in the properties (parts of title, series or author). Without either, all of them belong.
- **Ignored and removed**: terms that no longer count as missing, and entries taken out; **Remove** or **Bring back** brings them back.
- **Steps** (only with a database): [[woerterbuch_aufbau]].
""")),
    ("woerterbuch", "woerterbuch_bearbeiten", N_("Editing entries and Claude"), N_("""
**Editing**
- Form: name, category, short description, other names (comma-separated; KOReader also finds the entry under these), sections (a line with **#** is the heading, the text below it). Below that the preview of how the entry looks in KOReader.
- Entries from other dictionaries that do not have this structure are edited as **HTML** or **text**.
- **Apply** (Ctrl+Enter) saves your own version (yellow), **Discard** undoes changes in the form (red = not applied). Own versions always win, even if things are summarized again later. **Discard own version (original)** (Dictionary menu) discards them. **New** adds a term by hand.

**Claude ▾** (for the chosen term; the result is always a draft to check; topic and spoilers from the properties)
- **Search the web**: web search anywhere, text only from the pages found, which are given as the source in the entry. About 2-4 cents.
- **Summarize from a page**: give an address, Claude reads only that page.
- **From own knowledge**: without a source; the entry says "unverified", the list shows the dictionary pictogram.
- If Claude finds the full name ("Baggins" -> "Bilbo Baggins"), the searched name becomes another name of the entry.

Costs and what is sent: [[kosten]].
""")),
    ("woerterbuch", "woerterbuch_aufbau", N_("Steps and building"), N_("""
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
    ("woerterbuch", "woerterbuch_unterwegs", N_("On the go without a database"), N_("""
Open the StarDict folder (e.g. the copy on the e-reader or on a stick) and edit it. Bookbench records the changes in **bookbench.json** in this folder (it does not go to the e-reader).

Back home in the database: Properties > **Take changes from a StarDict folder**, otherwise the next build overwrites them.
""")),
    ("bereiche", "kobo", N_("E-reader"), N_("""
Shows the connected e-reader with KOReader - Kobo, Kindle or PocketBook: model, drive, firmware, KOReader version, free space.

**Detection**
- Automatically every few seconds ([[einst_kobo]]), by the folders in the root of a drive ([[kobo_geraete]]). Copies of the e-reader on the hard disk (backups with a .kobo folder and the like) do not count, only the root of a drive.
- Searched: on Linux /run/media, /media and /mnt, on Windows all drives; also the opened books folder and the folders above it.
- With several connected e-readers a list appears next to the name.

**Books: computer ↔ e-reader** (top): compares the library on this computer with the e-reader and copies changes in both directions ([[kobo_abgleich]]).

**Books** opens the whole e-reader in Library, Table of contents and Metadata. Then metadata.calibre is found automatically too.

**When connecting** Bookbench opens the books on the e-reader by itself if no other folder is open; otherwise it asks. If the e-reader is linked with a library on this computer, that library is opened instead and compared. Can be changed: [[einst_kobo]].

**More**
- [[kobo_abgleich]]
- [[kobo_geraete]]
- [[kobo_sicherungen]]
- [[kobo_woerterbuecher]]
- [[kobo_auswerfen]]
""")),
    ("kobo", "kobo_abgleich", N_("Syncing books"), N_("""
At the top of the E-reader area: the books of the library on this computer ([[bibliothek_rechner]]) compared with those on the connected e-reader. You can edit on both sides; the sync brings them together.

**Linking**
- **New library from e-reader** links the new library with this e-reader at once.
- Otherwise **Link library …** chooses the folder. The link is remembered per e-reader (serial number; Kindle/PocketBook: kind, model and drive name) and noted in the library's library.json. **Other library …** changes it.

**Reading state**
When the linked e-reader is connected, Bookbench also reads KOReader's reading state (status, progress, reading time) and notes it in the library ([[bibliothek_lesestand]]). Nothing is written to the e-reader for that.

**How changes are found**
After every sync Bookbench notes for each book its size and date on both sides and a checksum of its content (.bookbench/abgleich.json in the library folder). Next time each side is compared with that note, so it is clear on which side a book changed. A different date alone does not count: the e-reader's file system stores times in local time with a 2-second grid, after the switch to summer time all files can look an hour off. The checksum is only computed when size or date differ, so the e-reader is not read completely every time.

**The list** (only books with something to do)
- **new on the computer** → to the e-reader (checked). **only on the e-reader** → to the computer (checked).
- **changed on the computer** / **changed on the e-reader**: copied to the other side (checked).
- **changed on both sides**: *Leave as it is* by default; choose which side wins. Below the list the differences: title, authors, series and other metadata, chapter names and number, which files in the EPUB differ.
- **deleted on the e-reader** / **deleted on the computer**: deleting it on the other side is offered, but not checked. Or copy it back.
- Selecting a row shows what differs or what the state means.
- **Collections** ([[sammlungen]]) are in the same list, after the books, as "Collection: name", with the same states: new, changed on one side, changed on both sides, deleted. For a collection only the books that are on the e-reader count; a book of the collection that is not synced yet is not a difference (KOReader drops entries whose file it cannot find). Placeholders stay on the computer. Before collection.lua on the e-reader is changed, it is backed up.

**Sync n books** (also in the toolbar) asks first, then copies. Always to the same path, so KOReader's .sdr folders (reading position, highlights) fit; they are never touched, not even when deleting. A file that is overwritten or deleted goes to the backup folder first ([[einst_speichern]]). Books with unsaved changes in the open library are not overwritten. Afterwards the library is read again and compared once more.

**When it runs**
- When the e-reader is connected: the linked library is opened instead of the books on the e-reader (or asked, [[einst_kobo]]), then compared. The result goes to the status bar; the sidebar shows **two arrows** (books to sync) and **arrows against each other** (changed on both sides) at Library and E-reader.
- After saving in the library, and with **Compare**.
""")),
    ("kobo", "kobo_geraete", N_("Kobo, Kindle, PocketBook"), N_("""
KOReader keeps its settings in its own installation folder. Where that is depends on the device:

- **Kobo** (and tolino from 2024 on, Kobo hardware): folder **.kobo** in the root, KOReader in **.adds/koreader**, extra fonts in **fonts**. Model, serial number and firmware come from .kobo/version; an unknown model shows the number on the type plate (e.g. N428) instead.
- **Kindle**: folders **documents** and **system** in the root, KOReader in **koreader**, extra fonts in **fonts**.
- **PocketBook**: folder **applications** (with **koreader** inside) and **system/config**, KOReader in **applications/koreader**, the device's own fonts in **system/fonts**.

Kindle and PocketBook put no readable model data on the drive; the area then only shows the kind of device. For the preview choose the model by hand if needed ([[vorschau_bildschirm]]).

Newer Kindles and Android devices only connect via MTP and do not appear as a drive, so they are not found. On Linux a file manager can still copy their files to a folder on the computer; open that folder or use it as the dictionary source. On Windows there is no way from the program.

Only the Kobo was tested on a real device so far; Kindle and PocketBook follow the KOReader source code.
""")),
    ("kobo", "kobo_sicherungen", N_("Backups of the KOReader settings"), N_("""
- **Back up** packs the parts ticked on the right into a ZIP file in the subfolder **KOReader** of the backup folder (KOReader_YYYYMMDD_HHMMSS.zip). The newest backups are kept ([[einst_speichern]]).
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
    ("kobo", "kobo_woerterbuecher", N_("Copying dictionaries"), N_("""
- **Choose source**: a folder on the computer somewhere inside which the dictionaries are ([[einst_kobo]]). It is searched up to 8 levels deep (at most 5000 folders; hidden folders like .adds are searched too, so a copy of the e-reader works as well; only large folders without dictionaries like .git, .cache, AppData, Windows and KOReader's plugins, fonts, cache are skipped). A dictionary is a folder with an .ifo file, e.g. My-Dictionary. If there are several folders with the same name, the one with the newest .ifo wins; the column **Folder in the source** shows which one was found.
- Status of each dictionary: **up to date**, **outdated on the e-reader** or **missing on the e-reader** (both red), **only on the e-reader**.
- **Dictionary** (toolbar) copies the selected ones, without a selection all that are not up to date, to data/dict/<name>/ in the KOReader folder (Kobo: .adds/koreader/data/dict). Files in the target that no longer exist in the source are deleted there.
- **Double-click** opens the dictionary in the Dictionary area: the registered one that was built into this folder, otherwise the folder from the source itself. A dictionary that is only on the e-reader is opened there after asking; changes are then saved on the e-reader.
""")),
    ("kobo", "kobo_auswerfen", N_("Ejecting"), N_("""
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
    ("bereiche", "vorschau", N_("Preview"), N_("""
The **KOReader workbench**: the desktop KOReader runs invisibly in the background with the settings from your e-reader and shows the page or the start screen as it looks on the device - font, margins, headers and footers from Bookends, the shelves of Bookshelf, style tweaks and patches. Only on Linux and macOS; there is no official KOReader for Windows, so the area is missing there.

**Installing KOReader** (optional, only needed for this)
- Arch/EndeavourOS: **yay -S koreader-bin**
- Flatpak: **flatpak install flathub rocks.koreader.KOReader**
- or put the AppImage from github.com/koreader/koreader/releases into ~/Applications or ~/Downloads
It is searched in this order: own path ([[einst_vorschau]]), koreader in PATH, macOS applications folder, AppImage, Flatpak. Preview menu > **Find KOReader** after installing.

**More**
- [[vorschau_werkbank]]
- [[vorschau_lesen]]
- [[vorschau_patches]]
- [[vorschau_bookends]]
- [[vorschau_bookshelf]]
- [[vorschau_profil]]
- [[vorschau_rueckweg]]
- [[vorschau_starten]]
- [[vorschau_bildschirm]]
""")),
    ("vorschau", "vorschau_werkbank", N_("Workbench"), N_("""
**View**
- **Reading page**: the chosen book, opened. ◀ and ▶ turn pages, so does a click into the picture (left third back, otherwise forward, as on the e-reader) and the arrow keys once the picture has the focus.
- **Start screen**: KOReader without a book - the file browser or Bookshelf, whatever the profile starts with. **With sample books** shows eight sample books with covers; **with the opened library** shows the books of the library opened in Bookbench, with their reading progress (from the book data next to the books) and the most recently read ones first - Bookshelf's top area then shows your current book. The book selected under **Book** counts as the one read last. Nothing is written into the library. The same choice is on the Bookshelf page.
- Covers: KOReader reads them from the books in the background, the first time for every book. Bookbench keeps KOReader's cover cache between restarts (vorschau/werkbank-cache) and takes new pictures after 1.5, 4, 8 and 15 seconds; **New picture** takes one at any time.

**Tapping in KOReader**
- On the start screen a click into the picture is a tap at that spot - Bookshelf's shelf buttons (Home, Recent, Series …), its menus, a book. A right-click is a long press.
- On the reading page a click turns pages; Ctrl+click taps (for example to open KOReader's menus), right-click is a long press.
- **Swiping**: drag with the left mouse button held down; KOReader gets a swipe in that direction. The **mouse wheel** turns pages on the reading page; on the start screen it swipes up or down (with Shift sideways), for example to scroll Bookshelf's lists.
- If KOReader does not get to the book within 5 seconds (a question, an unsupported file …), Bookbench says what is on top and shows KOReader's screen; a click taps there, so a dialog can be answered.
- Books named .kepub (without .epub) are opened as .kepub.epub; KOReader does not know the shorter ending.

**Book**
- **Sample text** (default): three chapters of Lorem ipsum with title, author and series, enough for the Bookends placeholders.
- A book of the opened library, or **Other file …** (button below the book selection). Its book data (.sdr) is searched next to the book, on the connected e-reader and in the backup, so font size and margins are those of the e-reader. From the library: right-click on a book > **Open in Preview**.

**How it works**
KOReader starts without a window (SDL offscreen) at the full resolution of the device ([[vorschau_bildschirm]]); the picture is fitted into the area. Starting takes about a second, every further picture a tenth of a second. Changing the view or the book restarts it; **Restart** does it by hand. Bookbench stops it when closing; if Bookbench crashes, it stops by itself after 30 seconds.

It works on a throw-away copy of the profile (folder vorschau/werkbank), new at every start: reading position, history and settings of the profile stay untouched. Only the plugins Bookends and Bookshelf are loaded - other plugins can lay a full screen over everything. The built-in plugins of KOReader are there as always.

**Open in KOReader** (toolbar) starts the full KOReader in a window as before, for trying out menus: [[vorschau_starten]].
""")),
    ("vorschau", "vorschau_lesen", N_("Font and margins"), N_("""
Below Preview, **Font and margins** holds KOReader's own general reading settings - what "Set as default" in KOReader's reading menu (the bottom menu while reading) stores in settings.reader.lua. The page appears as soon as there is a profile ([[vorschau_profil]]).

**Font**: the font (the family names of the fonts in the profile and in the desktop KOReader; you can also type a name), size, weight, line spacing, word spacing (scaling and reduction), word expansion, kerning, hinting, contrast (gamma), and whether the book's embedded fonts and style are used.
**Margins**: left and right, top, bottom, and whether top and bottom stay the same. In KOReader's units. The margins of Bookends are on the Bookends page ([[vorschau_bookends]]).

Empty fields use KOReader's defaults. Changes are a draft until **Save to profile**; KOReader reads these values when it opens a book, so the workbench restarts after a change (about a second) and switches to the reading page.

**Values of the book shown**
KOReader stores font and margins in the book data (.sdr) of every book it has opened once - all of them, when the book is closed. There they win over the general values, which therefore only apply to books never opened before. The section shows which values the book in the workbench brings along.
**Ignore the book's own values in the workbench** removes them from the copy of the book data in the workbench, so the general values show. The book data of the book itself stays untouched. The sample text never has book data.
""")),
    ("vorschau", "vorschau_sperrbildschirm", N_("Sleep screen"), N_("""
Below Preview, **Sleep screen** holds KOReader's sleep screen options (Screen > Sleep screen in KOReader's menu, stored in settings.reader.lua). The page appears as soon as there is a profile ([[vorschau_profil]]).

While the page is open, the workbench shows the sleep screen as the e-reader would when it goes to sleep, without putting KOReader to sleep. **Show again** brings it back (a click into the picture can close it, like a tap on the e-reader); **Back to the page** closes it. Leaving the page closes it as well. KOReader reads these values when it starts, so the workbench restarts after a change (about a second).

**Wallpaper**: cover of the book, a chosen image or book cover, a random image from a folder, reading progress, book status or leave the screen as it is - and for images: border fill, stretch (optionally up to a limit), crop, rotate for best fit, images in order instead of random.
Paths are the ones on the e-reader (on a Kobo /mnt/onboard/…). **Choose …** takes a file or folder on the connected e-reader. Anything from elsewhere is copied into the profile (folder koreader/screensaver; for a folder only the images directly in it) and goes to the e-reader with **To the e-reader …** ([[vorschau_rueckweg]]). Images elsewhere on the e-reader (outside the KOReader folder) only show in the workbench while it is connected.

**Ignore the book cover**: no cover for books on hold, for finished books, or when the e-reader is locked in the file browser (only with the wallpaper "cover of the book").

**Message**: show a message, its text (empty = KOReader's "Sleeping"), the shape (box or banner across the screen), its height (0 bottom, 50 middle, 100 top), opacity, and the background fill when the screen is left as it is. **Insert** adds placeholders such as %T title, %A author, %S series, %p percent read, %C chapter title, %P chapter percent, %b battery. The placeholders and the shape/height/opacity exist since KOReader 2025.10.

**After waking up**: whether the sleep screen stays after waking (seconds, until a tap, until the "Exit sleep screen" gesture), the message for the gesture, and whether reboot/power-off messages are hidden.

**Picture next to the message** (with a picture and a message): KOReader lays the message over the picture. Bookbench's patch 2-bookbench-screensaver moves the picture into the free space next to the message instead, so nothing of the cover is hidden ([[vorschau_patches]]). **Add patch** copies it into the profile; with **To the e-reader …** it goes onto the e-reader like any patch. **Keep the picture clear of the message** switches it on and off (on by default once the patch is there); **Keep the picture in the middle** keeps the same gap above and below (smaller picture) instead of using the larger free space. If there is too little room (message in the middle with "middle"), KOReader draws as usual. Without the patch in the profile the two switches are hidden.

Fields that do nothing with the current choice are hidden (KOReader's menu greys them out); **Ignore the book cover** only appears with the book cover as wallpaper. Changes are a draft until **Save to profile**.
""")),
    ("vorschau", "vorschau_patches", N_("Patches"), N_("""
Below Preview, **Patches** lists the user patches of the profile (folder koreader/patches) as KOReader's patch management does (Tools > More tools > Patch management on the e-reader).

- Patches are grouped by when they run: early once after an update (0), early (1), late after the start (2), before quitting (8), when quitting (9) - the first digit of the file name. Files without such a number or without .lua never run and are not listed.
- ☑ on, ☐ off. Double-click, Space or **On/off** switches. Like KOReader, Bookbench renames the file: off = ".disabled" behind ".lua".
- **Switch off all patches** is KOReader's main switch (file .patches_disabled). In the workbench Bookbench switches the patches off one by one instead, so its own patch keeps running.
- ⚠ marks a patch that failed in the workbench; select it to see KOReader's message. Many patches need the e-reader (a Kobo-only function, the frontlight …) and can never run on the computer - that says nothing about the e-reader.
- **Show …** opens the patch read-only. **Add …** copies a .lua file into the profile (without a number it gets "2-", otherwise KOReader would never run it); **Delete** removes one. Adding and deleting change the profile at once.

**Patches from Bookbench**
Patches Bookbench brings along, with their state (not in the profile, in the profile, another version) and **Add** or **Update**. They are also attached to every Bookbench release on GitHub, for copying into koreader/patches on the e-reader by hand.
- **2-bookbench-subtitle**: reads the subtitle and calibre's custom columns straight from each EPUB on the e-reader. Bookshelf gets the token **%subtitle** (top panel, list lines, cover labels, [if:subtitle]); **%calibre{name}** in Bookshelf and Bookends also finds columns stored in the book, without calibre's metadata.calibre (a value in the book wins). Subtitle = the column #subtitle, otherwise the EPUB 3 subtitle. Bookbench writes these columns into the book when you edit them in Metadata. The patch hooks into Bookshelf's and Bookends' insides; if a new version changes them, the values stay empty and nothing else breaks.
- **2-bookbench-stories**: stories inside anthologies as entries of a collection - KOReader opens the story right inside the anthology, with a reading position of its own, and offers the next entry at its end ([[sammlungen_geschichten]]).
- **2-bookbench-screensaver**: sleep screen with a picture and a message - the picture moves into the free space next to the message instead of lying under it. Switch and options on the page Sleep screen ([[vorschau_sperrbildschirm]]). It only adjusts how KOReader puts picture and message together; if KOReader changes that, the sleep screen looks as without the patch.

Switching on and off is a draft until **Save to profile**. Patches run when KOReader starts, so the workbench restarts after every change. To bring patches onto the e-reader: **To the e-reader …** ([[vorschau_rueckweg]]). Bookbench's internal patches (1-bookbench-desktop, 2-bookbench-workbench) are not listed.
""")),
    ("vorschau", "vorschau_bookends", N_("Bookends settings"), N_("""
If the profile contains the plugin **Bookends**, the sidebar shows **Bookends** below Preview. Its settings page sits in the left column; the picture stays on the right and shows every change after a short pause (a tenth of a second, KOReader keeps running). The workbench switches to the reading page for this.

At the top: the preset shown and **Bookends switched on**. Below them the page has three tabs: **Lines**, **Progress bars** and **Preset** (managing presets, colours, general values). A tab with unsaved changes has a red ●. Within a tab, a click on a bold heading folds a section away or opens it. Bookbench remembers the tab and which sections are open.

**Draft and profile**
- Changes are a draft at first: they only show in the picture. The red line says so.
- **Save to profile** (toolbar) writes the preset and the switch into the preview profile; **Discard** goes back to what is in the profile.
- **To the e-reader …** (toolbar) writes the saved changes to the e-reader: [[vorschau_rueckweg]].
- **From the e-reader** and **From backup** replace the profile; if Bookbench has changed something in it, it asks first.

**Presets** (tab Preset)
- Bookends keeps everything you see in presets (one file each). The **active** preset is the one Bookends uses on the e-reader; another one can be shown and edited, the picture then shows that one. **Make active** marks it, saving makes it active in the profile.
- **New**, **Duplicate**, **Delete**. Name and description are what Bookends shows in its preset manager.

**Lines**
- Six positions (top and bottom, each left, centre, right), shown as a small page that grows with the column: a click on one shows its lines below (the button shows the first line, +n for more lines, – for an empty position). One line per row. Tokens such as %title, %chap_title or %page_num are filled in by Bookends; **Insert token** lists those of the installed Bookends version, sorted like in Bookends.
- Below the text field: **Insert token**, **Special characters**, then **B**, **I**, **U** and **Colour …**, which put tags around the selected text of the line you used last (without a selection an empty pair at the cursor): [b]bold[/b], [i]italic[/i], [u]underlined[/u], [c=#RRGGBB]…[/c] for a colour of your choice; **Condition …** and **Examples** see below. That is how a part of a line gets its own colour; the colour of all lines is set on the tab Preset.
- **Special characters** is a menu with Bookends' symbols (battery, book, arrows, blocks, separators …), in groups as in Bookends. A click inserts at the cursor of the line you used last; "dynamic" symbols insert their token (%batt_icon changes with the battery). The symbols come from KOReader's symbol font (nerdfonts/symbols.ttf); Bookbench shows them in the lines as small pictures and takes the font from the profile (fonts of the e-reader) or from the desktop KOReader.
- **Extra top/bottom margin** (and **extra left/right margin** for the corners) moves only this position away from the edge, in pixels - not the whole header or footer. Bookends calls it the same.
- Click into a line (section **Selected line**) to set its **style** (bold, italic), **size** (empty = the general size), **font**, **capitals** and **move line**: ← → and ↑ ↓ in pixels, negative = left or up, **Back to 0** sets both to 0. Inserting or deleting lines keeps the settings with their line.
- **Font**: "Default" is Bookends' general font. Then the font families (UI font, serif, sans-serif …; in brackets the font KOReader takes for them, set in KOReader under the font menu), then one entry per font family of the profile - the fonts of the e-reader. Bookbench stores the path on the e-reader, as Bookends does; in the workbench it uses the copy in the profile. A font from another e-reader that is not in the profile shows with ⚠.
- **Show on**: all pages, or only odd or even pages (for example page numbers on the outer side).
- **Bar in this line**: the token %bar draws a progress bar inside the line. **Insert bar** adds it, **Remove bar** takes it out again. Only for a line with a bar the bar fields appear: chapter or book, chapter ticks (book only), style, fill direction, thickness and unread thickness in pixels (empty thickness = as high as the text), then colours and markers as for the progress bars (below).
- **Conditions in this line**: Bookends shows a part of a line only under a condition, written into the text as [if:condition]then[else]otherwise[/if] - for example [if:batt<20]LOW %batt_icon[/if] or [if:page=odd]%title[else]%chap_title[/if]. The list shows the conditions of the selected line (nested ones below their outer one; the one at the cursor is selected).
- **New …** (or **Condition …** below the text field) opens a window: one or more parts, each with **not**, a field from Bookends' list (battery, Wi-Fi, page odd/even, book %, time, weekday, series …; **Other field …** for anything else, such as calibre{mood}), a comparison (=, ≠, <, >, ≤, ≥ or "has a value") and a value; joined by **and** or **or**. Below: the finished condition, the **then** text and optionally an **otherwise** text. Selected text of the line becomes the then text.
- **Edit …** (or double-click) opens the same window for the selected condition. Conditions with brackets or a mix of and/or are edited as text (**Edit as text**). **Dissolve** removes a condition and keeps its then text.
- **Examples** (below the text field) inserts Bookends' ready-made lines (Kindle-style time left, battery bars, weekend …).

**Progress bars**
Up to eight bars across the page, independent of the lines. Choose a bar in the list (✓ = switched on, with its edge), then **Switched on**; only a switched-on bar shows its fields: chapter or book, chapter ticks, style, fill direction, **Edge** (top, bottom, left, right), thickness (diameter for round bars) and unread thickness, distance from the edge and the margins at both ends. A bar set to "Position relative to line text" on the e-reader shows its distance from the line text instead; switching that on or off stays on the e-reader.
- **Own colours and ticks**: switched off, Bookends takes the colours of the style. Switched on: colour of the read and unread part, chapter ticks, border and ticks on the read part (click a field: choose a colour, back to the default, or transparent), whether the tick colour is inverted on the read part, tick height (%), tick width (× the normal width) and border thickness.
- **Markers**: a small mark on the bar at a reading position - start of the reading session, where the book was opened, bookmarks, or today's start. One on top, one below; for each the style (chevron or solid), size (%), offset (px) and colour.

**Colours** (tab Preset)
Text colour (default = the colour of the book text), symbol colour (default = like the text) and the background behind the top and bottom lines (default = none) - for all lines of the preset. On a black-and-white screen Bookends shows colours as grey. If the e-reader of the profile has no colour screen (model table, or the device chosen under View), every colour field - here, for bars, markers and the Grey … button below the text field - asks for a grey in % black instead, as Bookends' own menu does there, and colours set elsewhere show as the grey the e-reader will display.

**General** (tab Preset)
Font size and scale, the four margins, the gap before texts overlap and what is shortened first. Empty fields use Bookends' defaults.

Bookends is a plugin by AndyHazz (github.com/AndyHazz/bookends.koplugin); Bookbench only reads and writes its files. Newer Bookends versions can change the format; unknown parts stay as they are.
""")),
    ("vorschau", "vorschau_bookshelf", N_("Bookshelf settings"), N_("""
If the profile contains the plugin **Bookshelf**, the sidebar shows **Bookshelf** below Preview. The workbench switches to the start screen for this.

Bookshelf cannot reload its settings while KOReader runs. After a change, the workbench therefore restarts after a short pause (about a second) and then shows the new start screen.

**Draft and profile** work as for Bookends ([[vorschau_bookends]]): first only in the picture, **Save to profile** keeps them, **Discard** goes back.

The page has five tabs: **Appearance** (theme, wallpaper, plank, decoration, colours), **Home** (top panel and its modules), **Navigation** (start menu, shelves, footer and buttons), **Layout** (columns and rows, font sizes, covers and spines, display) and **All** (all keys in the file). A tab with unsaved changes has a red ●. Within a tab, a click on a bold heading folds a section away or opens it. Bookbench remembers the tab and which sections are open.

**Theme**
- **Default theme**: the theme every shelf wears unless it has its own. **Custom theme** is your own look (wallpaper, plank, colours below), **Plain** Bookshelf's plain look, and every theme pack in the profile. A theme is a layer over the custom theme: it replaces only the parts it brings.
- **Light or dark**: automatic (like KOReader's night mode) or fixed.
- **Theme per shelf**: each shelf can wear its own theme or follow the default.
- Theme packs are folders in settings/bookshelf/ornaments with a theme/theme.json. New ones come from Bookshelf's theme library on the e-reader; take the profile again afterwards.

**Wallpaper, plank, colours** (of the custom theme)
- **Wallpaper**: a picture from settings/bookshelf/wallpapers, a second one for full screen shelves, how strongly the panels over it are shaded, transparent buttons, blur under the panels, inverting in night mode. **Add picture …** copies a picture into the profile at once.
- **Plank**: oak, colour only, or a plank from a theme pack.
- **Colours**: day and night colour for each part (text, progress bar, plank, menu bar …). Click a field to choose; "-" is the default, ✕ resets day and night. Grey is stored as Bookshelf does (as a grey level). Without a colour screen on the profile's e-reader a click asks for a grey in % black, and colours show as the grey the e-reader will display.

**Decoration (ornaments)**
- **How often per shelf**: none, rarely, often (default), always. Ornaments only appear on spine shelves.
- The list shows all ornaments of the profile (loose files and packs); a double-click switches a piece or a whole pack off and on.

**Top panel**
- **Shows**: the current book (hero card) or Bookshelf's modules (clock, quote …). Arranging the modules stays in Bookshelf.
- **Lines of the hero card**: status line, rating, title, author, metadata, description, tags, progress (✓ = shown). For each: **Shown**, the text with tokens (**Insert token** lists Bookshelf's tokens), size, alignment, bold, capitals; **Default** goes back to Bookshelf's default for that line. [if:token]…[/if] shows a part only if the token has a value; an empty text leaves the line out.
- Rating and tags are buttons, not text: only on/off, size and alignment; for tags also which kinds (authors, series, collections, genres, folder) and how many rows.
- **Subtitle** puts the book's subtitle into the line ([if:subtitle]%subtitle[/if]; in the metadata line instead of the series). It needs the patch 2-bookbench-subtitle in the profile and on the e-reader ([[vorschau_patches]]).

**Modules in the top panel**
- The modules shown when the top panel is set to modules, with their position: page, column and row of the top-left cell, width and height in grid cells - or **Place automatically**. The panel has 1 or 2 rows and 2 to 8 columns depending on the screen; Bookshelf moves a module that does not fit or overlaps another.
- **Add** offers Bookshelf's modules (clock, quote, weather …). Three ask for a choice in a submenu: **Action** (one of Bookshelf's standard actions: reading calendar, Wi-Fi, night mode, sleep …), **Shelf** (a shelf with books, not a stack) and **Ornament** (a piece from the profile). **Choice** changes it for the selected module; the list shows it after the module's name. **Up**/**Down** change the order, **Remove** takes one out.

**Start menu**
- The entries of Bookshelf's start menu as a tree: entries, modules (▣), dividers and folders (one level deep, as in Bookshelf).
- **Add**: a folder, a divider, a module, or one of Bookshelf's standard entries (reading calendar, Wi-Fi, night mode, sleep …; the name is stored in Bookbench's language). It goes behind the selected entry.
- **Up**/**Down** within its level, **Folder** moves an entry into a folder or out of it, **Rename …** (or double-click), **Remove**. Other actions and the icons are set in Bookshelf's start menu editor.

**Shelves**
- The shelves above the books: ☑ shown, ☐ hidden (double-click or **On/off**; one stays shown), order, name, and how a shelf is shown (covers, list, spines, automatic).
- **Add > New shelf …** makes a shelf: the source (whole library, recently read, latest added, favourites, your own collection, a folder of the e-reader - as folders or flattened -, a stack for each series, author, genre … or a shelf of shelves), the name (follows the source until you change it) and how it is shown. Sorting starts as Bookshelf sets it for a new shelf; sorting and filters are changed in Bookshelf. **Add** also brings back a standard shelf that was removed (home, recent, series …).
- As long as Bookshelf has not written modules, start menu or shelves into its file, it uses its defaults: Bookbench shows these (with a note) and writes them with the first change, with the names in Bookbench's language - as Bookshelf does in its own.

**More settings**
- A selection of settings that change the look (footer and buttons on the tab Navigation; columns and rows, font sizes, covers and spines, display on the tab Layout), with Bookshelf's defaults where the file has no value.
- **All** (all keys in the file): everything in settings/bookshelf/settings.lua, also what is not on the other tabs. Double-click (or **Change …**) changes a simple value (number, text, on/off) in its type. Tables - shelves, modules, the start menu - can only be changed in Bookshelf itself or on the other tabs (colours, theme and ornaments per shelf, the hero card, modules, start menu, shelves). **Default** removes the key, then Bookshelf's default applies. Changed keys have a ●.
- Values Bookshelf writes by itself while running (current shelf and page, version notes) are not listed.

Bookshelf is a plugin by AndyHazz (github.com/AndyHazz/bookshelf.koplugin); Bookbench only reads and writes its settings file.
""")),
    ("vorschau", "vorschau_profil", N_("Profile"), N_("""
The preview runs in its own profile in the settings folder (subfolder vorschau, [[dateien]]). A normal KOReader installation on the computer stays untouched.

- **From the e-reader** rebuilds the profile from the connected e-reader: settings.reader.lua, folder settings (with the Bookends presets), styletweaks, patches, the plugins you installed (the built-in ones come with the desktop KOReader) and the fonts from KOReader's fonts folder and from the font folder of the device ([[kobo_geraete]]).
- **From backup** takes settings, settings folder, styletweaks and patches from the backup selected in the E-reader area, otherwise from the newest ([[kobo_sicherungen]]). Plugins and fonts are in no backup; they stay as they are. So you have to take the profile from the e-reader at least once.
- When taking a profile and before every start, these are removed from the settings: **screen_dpi** (it would override the screen size of the preview), plugin paths and the last files/folders on the e-reader. In the profile, book data is always next to the book.
""")),
    ("vorschau", "vorschau_rueckweg", N_("To the e-reader"), N_("""
**To the e-reader …** (toolbar) writes what you changed in the preview profile to the connected e-reader - the way back after Bookends, Bookshelf, font and margins, patches.

**What is offered**
- When the profile is taken from the e-reader (or from a backup), Bookbench notes the state of the files it compares (folder vorschau/basis). Offered is what changed in the profile since then: Bookends presets and bookends.lua, Bookshelf's settings, wallpapers and ornaments, patches (also switched off = renamed, added, deleted), style tweaks, and KOReader's settings (settings.reader.lua) key by key.
- ⚠ **Conflict**: the same file or key was changed on the e-reader too since the profile was taken. Not preselected - transferring it replaces the e-reader's change.
- What changed only on the e-reader (KOReader writes all the time: positions, statistics) is left alone. Databases (statistics, cover cache) are never transferred.
- Device-specific settings are never offered: screen DPI, paths and last files, frontlight, Wi-Fi, migration notes and the like. **Never offer** hides further settings for good (it only applies to keys, not files).
- A profile taken before 1.4-beta6 has no noted state: then profile and e-reader are compared directly, and only areas Bookbench has changed are preselected. Take the profile again to get the exact comparison.

**Transferring**
- Tick what should go (click the box, Space, **On/off**, **All**, **None**, **Suggestion**) and **Transfer**. Before writing, the KOReader settings of the e-reader are backed up (E-reader area, reason "before writing from the preview").
- Settings are written key by key into the e-reader's settings.reader.lua; everything else in it stays.
- Unsaved drafts on the workbench pages are asked about first.
- Afterwards eject the e-reader; KOReader reads the changes at its next start. If KOReader is running on the e-reader while you transfer (rare over USB), it may overwrite settings.reader.lua when it closes.
""")),
    ("vorschau", "vorschau_starten", N_("Starting and output"), N_("""
**Open in KOReader** (toolbar, always the first button)
- Starts the full desktop KOReader in a window, with menus and all plugins of the profile - for trying things out. The workbench keeps running beside it ([[vorschau_werkbank]]).
- It shows what the workbench shows: the reading page with the selected book, or the start screen (with sample books or the opened library, the selected book as the one read last).
- Since 1.4-beta6 it works on its own throw-away copy of the profile (vorschau/fenster), with the drafts of the workbench pages.
- **Changes from KOReader** (since 2.2-beta5): when the window is closed, Bookbench shows what you changed in KOReader's menus - KOReader settings key by key, Bookends presets and switches, Bookshelf, patches, style tweaks, sleep screen images - and you choose what goes into the profile (like **To the e-reader …**, with **Never offer** for keys you never want). Values KOReader and the plugins write by themselves (positions, caches, window size, Bookshelf's own state) are left out. ⚠ = changed in the profile too since the window was opened - not preselected. Later: Preview > **Changes from the KOReader window …**, until KOReader is opened again. From the profile, **To the e-reader …** brings the changes to the e-reader.
- The selected book (the sample text too) is copied with its book data (.sdr) into that copy and opened there. KOReader writes to the book data while reading; that way the original stays untouched, on the e-reader too.
- Book data is searched: next to the book, on the connected e-reader (same file name), in the backup. Without book data the general settings apply, so font size and margins may differ.
- **Other file …** (below the book selection) shows a book that is not in the opened library.

**KOReader output**
Under **Profile, device and output** (click to unfold) is what KOReader reports at start and while running: the workbench's output (vorschau/werkbank/koreader.log), after **Open in KOReader** that of the window (vorschau/fenster/koreader.log). After it closes, the status bar gives the number of warnings and errors, for example a patch that does not run on the computer because it needs something specific to the e-reader.
""")),
    ("vorschau", "vorschau_bildschirm", N_("Screen and device"), N_("""
The workbench and the window copy the screen of a device: size in pixels, pixel density, colour or black and white (black and white switches off the colours in KOReader, as on the device). The workbench always uses the full size. Which device it is stands under **Profile, device and output**:
- **Automatic** (default): the device the profile was taken from (From the e-reader, or the device noted in the backup), otherwise the connected e-reader, otherwise the Libra Colour - then with a ⚠.
- Kindle and PocketBook note no model, so automatic falls back to the Libra Colour for them; choose **Own size** there.
- **Settings > Device > Preview**: a fixed Kobo or tolino model, or **Own size** for other e-readers with KOReader (pixels in portrait format and ppi from the data sheet) - [[einst_vorschau]].

For **Open in KOReader** (window) the size is chosen there: a Libra Colour has 1264 × 1680 pixels at 300 dpi; hardly any screen is that tall.
- **Fitted to the screen** takes the height of the screen and lowers the DPI to match; KOReader sizes fonts and spacing by the DPI, so the page looks the same, only coarser.
- **Half size**: half the pixels and half the DPI.
- **Full size** is pixel-exact, but the window then goes beyond the screen.
A screenshot from KOReader (menu or gesture) always has the full resolution of the window.
""")),
    ("", "speichern", N_("Saving and backups"), N_("""
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
    ("", "einstellungen", N_("Settings"), N_("""
File > **Settings …** opens the settings. The tree on the left has groups with pages below them; a group page shows what its pages are for. **Help** (or F1) in the dialog opens the chapter of the page shown here.

**OK** saves, **Cancel** forgets the changes. Most settings apply at once, the language too (without a restart); chapter settings after reloading (F5).

All settings are in **einstellungen.json** in the settings folder ([[dateien]]). Export, import and resetting: [[einst_erweitert]].

**Pages**
- General: [[einst_darstellung]], [[einst_oberflaeche]], [[einst_start]]
- [[einst_speichern]]
- Books: [[einst_bibliothek]], [[einst_cleaner]], [[einst_kapitel]], [[einst_klappentexte]] ([[einst_klappentexte_profile]]), [[einst_cover]] ([[einst_cover_nachschlagen]]), [[einst_metadaten]]
- Device: [[einst_kobo]], [[einst_vorschau]]
- [[einst_online]]
- [[einst_erweitert]]

Options that only matter with another setting (e.g. the tooltip delay, the Claude model) only appear when that setting is on.
""")),
    ("einstellungen", "einst_darstellung", N_("Language and theme"), N_("""
**Language** (default: automatic)
- Automatic: German if the system language is German, otherwise English (Windows: language of the interface; Linux: LANGUAGE, LC_ALL, LC_MESSAGES, LANG).
- The change applies at once, without a restart: folder, area, selected book, unsaved changes and window stay.

**Theme** (default: like the system)
- Light and dark use the colours of the Keller design guide (Qt style Fusion).
- Like the system: style and colours of the desktop, checked at start. On KDE with the system's PySide6 (Arch: pyside6) that is Breeze, as in the other KDE programs; with PySide6 from pip it is Fusion with the colours of the system.
""")),
    ("einstellungen", "einst_oberflaeche", N_("Interface"), N_("""
- **Status strip next to the lists** (default: on): coloured dots and pictograms ([[status]]). Also under View.
- **Show tooltips** (default: on) and **Delay** (default: 600 ms): explanations when the mouse stays over a button.
- **Show cover in Table of contents** (default: on) and **Height** (default: 96 px): the small cover next to the book title; a click shows it large. Also under View > Cover.
- **Double-click on a book opens it in** (default: Table of contents): Table of contents, Metadata, the Preview (the book is selected there) or KOReader (selects it in the Preview and starts the desktop KOReader). Preview and KOReader only where the Preview exists (not on Windows). A right-click on a book in the library offers all of them.
- **Sidebar expanded** (default: on): with names and counters, or only symbols. Ctrl+B switches at any time; the last state is remembered.

Which pictograms are shown where: [[einst_marken]].
""")),
    ("einst_oberflaeche", "einst_marken", N_("Status symbols"), N_("""
One row per pictogram ([[status]]), one column per place:
- **Sidebar**: the pictograms with numbers next to the areas.
- **Book lists**: the narrow lists in Table of contents and Metadata, and the list of Book series.
- **Library**: the column Status in the library.

Default: everything on. A switched-off pictogram is only hidden; the filters (e.g. No cover) and sorting by status still count it. The coloured dot for changed, applied and saved is not affected; the whole strip next to the lists can be switched off under [[einst_oberflaeche]]. **All on** and **All off** set every box.

Dictionary, e-reader and "connected" only exist in the sidebar; gaps in a series only in the sidebar and in Book series.
""")),
    ("einstellungen", "einst_start", N_("Startup"), N_("""
- **Open the last folder** (default: on): the books folder that was open when the program was last closed, if it still exists - for the e-reader only when it is connected. Off: the program starts empty; File > Recently opened still has the folders.
- **Area at start** (default: Library): always the library, or the area that was shown last.

A folder given on the command line (start.py <folder>) is always opened.
""")),
    ("einstellungen", "einst_updates", N_("Updates"), N_("""
**This copy** says how Bookbench was installed: with the Windows setup, with install.sh or not at all (source code, e.g. a git clone). Only installed copies can update themselves ([[updates]]). **Check now** looks right away, with the values on this page (also before OK).

**Automatic check** (default: at start, at most once a day): off, at every start, at most once a day or once a week. It runs a few seconds after the start in the background. Only a newer version opens a window; without network there is only a note in the status line. Source code copies never check automatically.

**Skipped version**: shown when a version was skipped in the update window. **Show again** brings its window back at the next check.

**Include pre-releases** (default: off): also releases marked as pre-release on GitHub.

The releases come from github.com/kepfle-git/Bookbench; that is fixed in the program. Without signing in GitHub allows 60 requests per hour, far more than the check needs.
""")),
    ("einstellungen", "einst_speichern", N_("Saving and backups"), N_("""
- **Backup folder** (default: Bookbench Backups in the user folder): books are copied here before each save ([[speichern]]). The E-reader area uses its subfolder KOReader, the dictionary its subfolder Wörterbücher. Not on the e-reader.
- **Backups per book** (default: 5): the newest ones are kept, older ones are deleted when saving.
- **Backups of the KOReader settings** (default: 10): backups made in the E-reader area; this many stay in the subfolder KOReader, including the backup before each restore ([[kobo_sicherungen]]).
""")),
    ("einstellungen", "einst_bibliothek", N_("Library and import"), N_("""
**Folder scheme**
- **This library**: only when a library on this computer is open. Where Add books puts new books ([[bibliothek_ordnerschema]]). **Detect from the books** looks for the scheme most books follow; the line below shows an example with a book of the library, or what is wrong with the scheme. Saved in the library folder (.bookbench/library.json).
- **Default for new libraries** (default: {author_sort}/[{series}/][{series_index:2} - ]{title}, like Calibre): used when a library has no scheme of its own and none can be detected. **Reset to Calibre-like default** puts it back.

**Reading cache**
- **Remember read books** (default: on): Bookbench remembers what it read from each book (table of contents, metadata, cover size) together with size and date of the file, and only reads changed files again. KOReader's book data (.sdr) counts too. Stored per library in the settings folder (einlese-cache), not in the library folder.
- **Empty reading cache**: the next opening reads all books again.
""")),
    ("einstellungen", "einst_cleaner", N_("Advert text"), N_("""
Patterns for Remove advert text ([[bibliothek_cleaner]]).

- One pattern per line, case does not matter (default: OceanofPDF.com).
- A line in **/slashes/** is a regular expression, e.g. /downloaded from \\S+/ for "Downloaded from" followed by any address.
- The line below shows how many patterns there are, or what is wrong with a regular expression. Invalid patterns are not saved.
- **Reset to default** puts back OceanofPDF.com.
""")),
    ("einstellungen", "einst_kapitel", N_("Chapters"), N_("""
- **Subtitle lines per chapter** (default: 1): how many lines below a chapter number make up the suggested name. Some books have three (e.g. place, time, person); with 3 all of them are joined with " / ".
- **Write entries in capitals normally** (default: off): THE SHIRE becomes The Shire, A LONG-EXPECTED PARTY becomes A Long-Expected Party. Small words (a, of, the …) stay lower case except at the start.

Both apply after reloading (F5), because the suggestions are made when reading the books. See also [[kapitel]].
""")),
    ("einstellungen", "einst_klappentexte", N_("Blurbs"), N_("""
The page shows the order of the sources ([[klappentexte_nachschlagen]]).

- **Ask Google Books and Open Library first** (default: on): free, no key. Off: every look-up goes to Claude straight away.
- The own Google Books key is under [[einst_online]].
- **Preferred language when looking up** (default: same as the book): another language looks for the blurb of an edition in that language, without the ISBN, for the free sources and for Claude's source profiles ([[klappentexte_nachschlagen]]). It is also the default language in the window Look up metadata ([[metadaten_nachschlagen]]). Blurbs already found or applied stay as they are.
- **Shortest blurb** (default: 80 characters): shorter texts from a source are not taken - often only a teaser line or "A novel".
- **Longest blurb** (default: 4000 characters): longer texts are not taken - usually a plot summary or a whole article.
The limits apply to all sources (free ones and Claude), not to text you enter yourself.
""")),
    ("einst_klappentexte", "einst_klappentexte_profile", N_("Source profiles"), N_("""
The list of profiles in the order in which they are checked. The first active one that fits a book is used; what the fields mean: [[klappentexte_profile]].

- **New …** puts a new profile at the top (otherwise the general web search would come first).
- **Edit …** (or double-click), **Delete**, **Up**, **Down**.
- **Defaults** puts the included profiles back; your own profiles are removed.
- "(off)" in front of "Applies to": the profile is switched off and skipped.

Changes count after OK. If a profile changes, Claude looks up again for its books; books it already found stay as they are.
""")),
    ("einstellungen", "einst_online", N_("Online services"), N_("""
Keys for the services Bookbench asks on the internet; both are stored in plain text in einstellungen.json ([[dateien]]) - keep that in mind when exporting the settings. What is sent where: [[kosten]].

**Google Books**
- **Own Google Books API key** (default: empty): for looking up blurbs and covers. Without a key Google Books often answers "quota exceeded", because everyone without a key shares one daily quota. An own key is free: in the Google Cloud Console create a project, enable the **Books API** and create an **API key** under Credentials. If Google rejects it, the look-up says so.

**Claude API** (blurbs from source profiles, dictionary entries)
- **API key**: from console.anthropic.com (account with credit). Empty: the environment variable ANTHROPIC_API_KEY is used. Model and cost estimate only appear with a key.
- **Model** (default: claude-haiku-5-5): choose from the list; Haiku is enough for looking things up and is the cheapest. **Load list** asks Anthropic with the API key for the models available right now (newest first). A name can also be typed in.
- **Estimated cost per book** (default: 0.015 $): only for the question before looking up all missing blurbs; the real cost depends on page length and searches.

Also needed: the package **anthropic** (pip install anthropic). What is sent: [[kosten]].
""")),
    ("einstellungen", "einst_cover", N_("Covers"), N_("""
**Inserting a new cover** ([[cover_bild]])
- **Shrink to at most this height** (default: 0 = never): your e-reader shows at most its screen height (e.g. 1680 px on a Libra Colour); larger images only make the file bigger. Images are never enlarged.
- **JPEG quality** (default: 90): only when an image is converted or shrunk; otherwise it is taken unchanged. 90 is barely distinguishable from the original; below 75 artefacts become visible.

**Marking**
- **Mark covers below this height** (default: 800 px, 0 = never): ⚠ in the Metadata area and its filter "Small cover".
""")),
    ("einst_cover", "einst_cover_nachschlagen", N_("Looking up covers"), N_("""
**Sources** (both free, no key needed; Google Books uses your own key if there is one, [[einst_online]]; [[kosten]])
- **Open Library** (default: on): often large scans, sometimes of another edition.
- **Google Books** (default: on): the publisher's image, usually smaller.

**Which images count**
- **Smallest height** (default: 300 px): smaller images are left out (preview thumbnails, placeholders).
- **At most this many to choose from** (default: 8): each image is downloaded, so more takes longer. Looking up all missing covers takes at most 3 per book and uses the largest.
""")),
    ("einstellungen", "einst_metadaten", N_("Metadata and Calibre"), N_("""
**Calibre**
- **Compare with Calibre** (default: on): Bookbench reads Calibre's metadata.calibre (root of the e-reader, or the opened folder and the folders above it) and shows its values: in [[metadaten_calibre]] for comparing, in the library and in Blurbs for taking over series and blurbs ([[bibliothek_calibre]]).
- Off: metadata.calibre is ignored and the Calibre buttons and menu entries disappear. Useful once Bookbench has replaced Calibre for you.
- Switching off applies at once, switching on after reloading (F5).
- The one-time import from a Calibre library (metadata.db) works independently of this setting: [[calibre_import]].

**Fields**
- **Publication date** (default: on): shows the field Published in the form (dc:date in the book) and lets the library show the column Published (hidden at first, View > Library columns).

**Own fields** ([[metadaten_felder]])
- The list holds one Calibre column per row: **lookup name** (as in Calibre, with #, e.g. #subtitle) and the **label** Bookbench shows. Default: none.
- Select a row to change it below, **Add / change** takes the two fields (an existing lookup name is changed, a new one added). **Delete**, **Up** and **Down** work on the selected row; the order is the order in the form.
- **From Calibre** adds all own columns found in the metadata.calibre of the opened folder, with Calibre's labels. Delete the ones you do not want.
""")),
    ("einstellungen", "einst_kobo", N_("E-reader"), N_("""
**Detection**
- **Look for the e-reader every** (default: 3 seconds): how often the program checks whether an e-reader is connected or unplugged ([[kobo]]).
- **When an e-reader is connected** (default: open its books, ask if another folder is open): or always ask, or do nothing ([[kobo]]). If the e-reader is linked with a library on this computer, "its books" means that library; it is compared with the e-reader afterwards ([[kobo_abgleich]]).

**Copying dictionaries**
- **Copy dictionaries from (folder on the computer)**: where the dictionaries to copy are ([[kobo_woerterbuecher]]). Also set by Choose source in the E-reader area.

How many KOReader backups are kept: [[einst_speichern]].

**Ejecting**
- **Remind me to eject when quitting** (default: on): only if something was written to the e-reader in this session ([[kobo_auswerfen]]).
""")),
    ("einstellungen", "einst_vorschau", N_("Preview"), N_("""
Only on Linux and macOS.

- **Desktop KOReader** (default: empty = search): only fill in if it is not found by itself ([[vorschau]]). **flatpak** always takes the Flatpak rocks.koreader.KOReader, also when KOReader is installed normally too ([[fehler]]).
- **Device shown** (default: automatic): automatic, any Kobo or tolino model from the list (with size and ppi), or **Own size** with width, height (pixels in portrait format), ppi and colour screen for other e-readers with KOReader. See [[vorschau_bildschirm]].
""")),
    ("einstellungen", "einst_erweitert", N_("Advanced"), N_("""
**Files of the program**
- Shows where settings, chapter decisions and blurb cache are ([[dateien]]); **Open settings folder** opens it in the file manager.

**Blurb cache**
- Shows how many entries it has. **Empty …** deletes it: afterwards everything is looked up again, and Claude costs again.

**Export and import**
- **Export settings …** writes all settings to a JSON file, e.g. to take them to another computer. It contains the API key.
- **Import settings …** replaces the current settings with those from the file (unknown entries are ignored). The language too applies at once.

**Reset**
- **Reset all settings …** puts everything back to the defaults. Kept: opened folders, the list of dictionaries, window size, language and the API key.
""")),
    ("", "updates", N_("Installing and updating"), N_("""
**Installing**
- **Windows**: Bookbench_Setup_<version>.exe from the release page on GitHub. It installs for the current user without administrator rights (%LOCALAPPDATA%\\Programs\\Bookbench); as administrator "for all users" can be chosen. Start menu entry, desktop shortcut optional. Uninstall in the Windows settings under Apps; the settings in %APPDATA%\\Bookbench stay.
- **Linux**: download the source code of the release (or clone the repository) and run **./install.sh** in it. It copies the program to ~/.local/share/bookbench/programm, sets up a Python environment there (venv) with the optional packages, a command **bookbench** in ~/.local/bin and a menu entry. **./install.sh --uninstall** removes all that again; the settings in ~/.config/bookbench stay. Needs Python 3.9 or newer and Qt for Python (PySide6): if the system has it (Arch: sudo pacman -S pyside6), it is used - then Bookbench looks like the other KDE programs and uses the KDE file dialog; otherwise install.sh puts PySide6-Essentials into the Python environment with pip (Debian/Ubuntu: python3-venv needed).
- Without installing: **python start.py** in the program folder; the optional packages then come from pip (README).

**Updating**
- **Help > Check for updates …** looks for the newest release on GitHub ([[einst_updates]]). Installed copies also look by themselves at start.
- A newer version shows its changes (formatted like on GitHub, links open in the browser), with **Install now** for installed copies.
- **Install now** on Windows: downloads the setup, closes Bookbench, installs the new version over the old one and starts it again.
- **Install now** on Linux: downloads the new version, replaces the program folder and restarts Bookbench; the Python environment stays.
- From 1.x to 2.0 on Linux: the update only replaces the program files. If PySide6 is missing afterwards, Bookbench says so at the next start and offers to install it with pip (or: sudo pacman -S pyside6, then start again).
- Before closing Bookbench asks about unsaved changes and ejecting, like when quitting. Saying no keeps the download; Install now later uses it.
- The setup is checked against the file SHA256SUMS of the release; a damaged download is not installed.
- **Skip this version**: no more window for it at start; the manual check still shows it.
- A copy running from source code (git clone) is not replaced; update it with git pull.

The **desktop KOReader** for the preview (Linux only) is not part of the installation ([[vorschau]]).
""")),
    ("", "fehler", N_("Troubleshooting"), N_("""
**KOReader still shows the old chapter names, blurb or cover**
- KOReader keeps its own copy of the book information. Cover browser > long-press the book or menu > **Extract and cache book information** (or for the whole folder). The table of contents is read anew when the book is opened.

**JPEG covers are not shown**
- The package **Pillow** is missing: pip install pillow. Without it only PNG and GIF can be shown.

**"No API key" or nothing goes to Claude**
- Key under [[einst_online]] or the environment variable ANTHROPIC_API_KEY; package anthropic installed? Without a key only the free sources are asked.

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
- Choose "Fitted to the screen" ([[vorschau_bildschirm]]). Patches that need Kobo hardware fail on the computer; the output under **Profile, device and output** says which (workbench: vorschau/werkbank/koreader.log).

**Preview: the workbench shows no picture**
- The line under ◀ ▶ says what KOReader reports. **Restart** tries again; a profile from the e-reader is needed ([[vorschau_profil]]). If KOReader itself does not start, the same causes as for the window apply (below).

**Preview: KOReader closes at once ("device/kobo/device.lua" in the output)**
- The desktop KOReader takes the computer for an e-reader: up to at least version 2026.07 it recognizes the device by files such as /usr/bin/hwdetect (Arch/EndeavourOS: package hwdetect), /bin/kobo_config.sh or /proc/usid. KOReader alone does the same.
- Normally this does not happen in the preview: Bookbench puts a start patch (1-bookbench-desktop.lua) into the profile that hides these files from KOReader. It does not count as one of your patches and never goes to the e-reader. It does not work if patches are switched off in KOReader; then Bookbench says so and which file it is.
- Way out: KOReader as Flatpak (flatpak install flathub rocks.koreader.KOReader), it does not see these files. Enter **flatpak** under Settings > Device > Preview > Desktop KOReader ([[einst_vorschau]]), so that it is taken even if KOReader is also installed normally. Or remove the file if nothing else needs it.

**Something else**
- The status bar always has the last message. Backups of all saved books are in the backup folder ([[speichern]]).
""")),
]


VERWEIS = re.compile(r"\[\[(\w+)\]\]")


def themen():
    """[(Elternthema, Kennung, Titel, Text)] in der eingestellten Sprache."""
    return [(e, k, _(t), _(x)) for e, k, t, x in THEMEN]


def titel():
    return {k: _(t) for __, k, t, __ in THEMEN}


def thema(bereich):
    """Kennung des Hilfethemas zu einem Bereich; sonst der Überblick."""
    return bereich if any(k == bereich for __, k, __, __ in THEMEN) else THEMEN[0][1]


def klartext(text, titel_von=None):
    """Text ohne Auszeichnung, Verweise als Titel (für die Suche)."""
    t = titel_von if titel_von is not None else titel()
    return VERWEIS.sub(lambda m: t.get(m.group(1), m.group(1)), text).replace("**", "")
