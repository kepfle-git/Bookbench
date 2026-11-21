# Bookbench

A workbench for your KOReader library: fix chapter names, add blurbs and covers, build and copy
dictionaries, back up the KOReader settings of your e-reader and preview books with the desktop
KOReader.

- **Library**: all books of a folder (or of the connected e-reader) with series, chapters, blurb and cover state
- **Chapters**: names for chapters that only have numbers, suggested from the book text
- **Blurbs** and **covers**: look them up (Google Books, Open Library; optionally Claude), edit, save into the EPUB
- **Metadata** and **cover**: title, authors with sort names, series, publisher, language, ISBN, tags and your own Calibre columns, compared with Calibre and KOReader; a one-time import from a Calibre library (metadata.db) if you want to stop using Calibre
- **Dictionary**: StarDict dictionaries for KOReader, also built from a MediaWiki
- **E-reader**: Kobo, Kindle and PocketBook with KOReader over USB: backups of the KOReader settings, copying dictionaries
- **Preview** (Linux): open a book in the desktop KOReader with the settings of your e-reader

English and German interface.

## Install

**Windows**: download `Bookbench_Setup_<version>.exe` from the
[releases](https://github.com/kepfle-git/Bookbench/releases) and run it. No administrator rights needed.

**Linux**: download the source code of the newest release (or clone the repository), then

```sh
./install.sh
```

This installs to `~/.local/share/bookbench` with a Python environment for the optional packages,
adds the command `bookbench` and a menu entry. Needs Python 3.9+ with Tkinter
(Arch: `python tk`, Debian/Ubuntu: `python3-tk python3-venv`). `./install.sh --uninstall` removes it.
For the preview install the desktop KOReader (e.g. AUR `koreader-bin` or Flatpak `rocks.koreader.KOReader`).

**Without installing**: `python3 start.py`; optional packages: `pip install -r requirements.txt`.

## Updates

Help > Check for updates. Installed copies look for new releases at start (can be turned off in
Settings > General > Updates) and update themselves.

Settings live in `%APPDATA%\Bookbench` (Windows) or `~/.config/bookbench` (Linux).
