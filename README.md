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
- **Preview** (Linux): the KOReader workbench - the desktop KOReader runs in the background with the settings of your e-reader and shows the page or start screen; settings pages for the plugins Bookends and Bookshelf with a live picture

English and German interface.

## Install

**Windows**: download `Bookbench_Setup_<version>.exe` from the
[releases](https://github.com/kepfle-git/Bookbench/releases) and run it. No administrator rights needed.

**Linux**: download the source code of the newest release (or clone the repository), then

```sh
./install.sh
```

This installs to `~/.local/share/bookbench` with a Python environment for the optional packages,
adds the command `bookbench` and a menu entry. Needs Python 3.9+ and Qt for Python (PySide6). If your
system has it (Arch: `sudo pacman -S pyside6`), it is used - Bookbench then looks like your other KDE
programs; otherwise install.sh installs PySide6-Essentials into the environment with pip (Debian/Ubuntu:
`python3-venv`). `./install.sh --uninstall` removes it.
For the preview install the desktop KOReader (e.g. AUR `koreader-bin` or Flatpak `rocks.koreader.KOReader`).

**Without installing**: `python3 start.py`; optional packages: `pip install -r requirements.txt`.

## Updates

Help > Check for updates. Installed copies look for new releases at start (can be turned off in
Settings > General > Updates) and update themselves.

Settings live in `%APPDATA%\Bookbench` (Windows) or `~/.config/bookbench` (Linux).

## Privacy

No account, no telemetry; the text of your books never leaves the computer. Bookbench only contacts
Google Books, Open Library or Claude (with your own key) when you look something up, and GitHub for the
update check (can be turned off). Details: [PRIVACY.md](PRIVACY.md).

## Building

The Windows setup is built by GitHub Actions from each release tag
([workflow](.github/workflows/windows-setup.yml)). By hand on Windows: `packaging\build_windows.bat installer`
(needs Python with the packages from `requirements.txt`, PyInstaller and Inno Setup 6).
Code signing: [CODE_SIGNING.md](CODE_SIGNING.md).

## License

Bookbench is free software under the [GNU General Public License v3.0](LICENSE): you may use, share and
change it; changed versions you pass on must stay under the GPL. Components included in the Windows setup
keep their own licenses, see [THIRD_PARTY_LICENSES.txt](THIRD_PARTY_LICENSES.txt).
Contributions are welcome; please follow the [code of conduct](CODE_OF_CONDUCT.md).
