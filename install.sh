#!/usr/bin/env bash
# install.sh - Bookbench unter Linux für den aktuellen Benutzer einrichten (ohne root).
#
#   ./install.sh                 installieren bzw. auf diesen Stand bringen
#   ./install.sh --no-packages   ohne Python-Umgebung und Zusatzpakete (nur System-Python)
#   ./install.sh --uninstall     wieder entfernen (Einstellungen bleiben)
#
# Ergebnis (XDG_DATA_HOME, sonst ~/.local/share):
#   bookbench/programm/          start.py, bookbench/ … (das tauscht auch der Updater)
#   bookbench/venv/              Python-Umgebung mit --system-site-packages: ein PySide6 vom System
#                                (pacman -S pyside6) wird genommen - dann gibt es Breeze und den KDE-Dateidialog;
#                                sonst kommt PySide6-Essentials per pip in die Umgebung (Stil Fusion)
#   bookbench/installation.json  Marke für den Updater (art "linux")
#   ~/.local/bin/bookbench       Starter
#   applications/bookbench.desktop, icons/hicolor/256x256/apps/bookbench.png
# Einstellungen liegen in ~/.config/bookbench und werden nicht angefasst.
# Ausgaben auf Englisch (Release), Kommentare deutsch wie im übrigen Code.
set -euo pipefail

QUELLE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATEN="${XDG_DATA_HOME:-$HOME/.local/share}"
ZIEL="$DATEN/bookbench"
BIN="$HOME/.local/bin"
APPS="$DATEN/applications"
ICONS="$DATEN/icons/hicolor/256x256/apps"
PAKETE=(pillow wordfreq requests mwparserfromhell anthropic)
MARKE_STARTER="# created by Bookbench install.sh"

PYTHON="${PYTHON:-python3}"
PAKETE_AN=1
ENTFERNEN=0
JA=0

hilfe() {
    cat <<EOF
Bookbench installer for Linux (current user, no root needed)

  ./install.sh                 install or update to this version
  ./install.sh --no-packages   no Python environment and optional packages
  ./install.sh --uninstall     remove Bookbench (settings in ~/.config/bookbench stay)

Options:
  --python PATH    Python interpreter to use (default: python3)
  -y, --yes        do not ask
  -h, --help       this help

Installs to $ZIEL, the command bookbench to $BIN and a menu entry.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --no-packages) PAKETE_AN=0 ;;
        --uninstall) ENTFERNEN=1 ;;
        --python) shift; PYTHON="${1:?--python needs a path}" ;;
        -y|--yes) JA=1 ;;
        -h|--help) hilfe; exit 0 ;;
        *) echo "Unknown option: $1" >&2; hilfe >&2; exit 2 ;;
    esac
    shift
done

fragen() {   # fragen "Text" -> 0 bei ja
    [ "$JA" = 1 ] && return 0
    [ -t 0 ] || return 0                 # ohne Terminal (z. B. Skript): nicht hängen bleiben
    read -r -p "$1 [Y/n] " a
    case "$a" in [nN]*) return 1 ;; *) return 0 ;; esac
}

# ---------------------------------------------------------------- entfernen
if [ "$ENTFERNEN" = 1 ]; then
    fragen "Remove Bookbench from $ZIEL (settings stay)?" || exit 1
    if [ -f "$ZIEL/installation.json" ]; then
        rm -rf "$ZIEL"
    elif [ -e "$ZIEL" ]; then
        echo "$ZIEL has no installation.json - not removed (not installed by this script?)." >&2
    fi
    if [ -f "$BIN/bookbench" ] && grep -qF "$MARKE_STARTER" "$BIN/bookbench"; then
        rm -f "$BIN/bookbench"
    fi
    rm -f "$APPS/bookbench.desktop" "$ICONS/bookbench.png"
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$APPS" 2>/dev/null || true
    echo "Bookbench removed. Settings: ~/.config/bookbench"
    exit 0
fi

# ---------------------------------------------------------------- prüfen
if [ ! -f "$QUELLE/start.py" ] || [ ! -f "$QUELLE/bookbench/app.py" ]; then
    echo "start.py or bookbench/ not found next to install.sh ($QUELLE)." >&2
    exit 1
fi
case "$QUELLE/" in
    "$ZIEL/"*) echo "Run install.sh from the downloaded folder, not from the installed copy." >&2; exit 1 ;;
esac
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "$PYTHON not found. Install Python 3.9 or newer:" >&2
    echo "  Arch/EndeavourOS: sudo pacman -S python pyside6" >&2
    echo "  Debian/Ubuntu:    sudo apt install python3 python3-venv" >&2
    echo "  Fedora:           sudo dnf install python3" >&2
    exit 1
fi
PYTHON="$(command -v "$PYTHON")"
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo "Bookbench needs Python 3.9 or newer ($("$PYTHON" --version 2>&1))." >&2
    exit 1
fi
# Qt (seit 2.0): lieber das PySide6 des Systems (Breeze, KDE-Dateidialog), sonst per pip in die venv
QT_SYSTEM=0
if "$PYTHON" -c 'import PySide6.QtWidgets' 2>/dev/null; then
    QT_SYSTEM=1
elif [ "$PAKETE_AN" = 0 ] && ! { [ -x "$ZIEL/venv/bin/python" ] && "$ZIEL/venv/bin/python" -c 'import PySide6.QtWidgets' 2>/dev/null; }; then
    echo "Bookbench needs Qt (PySide6), which is missing for $PYTHON:" >&2
    echo "  Arch/EndeavourOS: sudo pacman -S pyside6" >&2
    echo "  Debian/Ubuntu:    sudo apt install python3-pyside6.qtwidgets" >&2
    echo "  or run ./install.sh without --no-packages (installs PySide6-Essentials with pip)" >&2
    exit 1
fi
VERSION="$(sed -n 's/^VERSION = "\([^"]*\)".*/\1/p' "$QUELLE/bookbench/version.py" 2>/dev/null | head -n 1)"
echo "Installing Bookbench ${VERSION:-?} to $ZIEL"

# ---------------------------------------------------------------- Programm kopieren
# Erst daneben aufbauen, dann tauschen (wie der Updater): ein Abbruch lässt das Alte stehen.
mkdir -p "$ZIEL"
rm -rf "$ZIEL/programm.neu" "$ZIEL/programm.alt"
mkdir "$ZIEL/programm.neu"
for f in start.py bookbench install.sh README.md LICENSE LICENSE.txt requirements.txt; do
    [ -e "$QUELLE/$f" ] && cp -a "$QUELLE/$f" "$ZIEL/programm.neu/"
done
find "$ZIEL/programm.neu" -name __pycache__ -type d -prune -exec rm -rf {} +
[ -d "$ZIEL/programm" ] && mv "$ZIEL/programm" "$ZIEL/programm.alt"
mv "$ZIEL/programm.neu" "$ZIEL/programm"
rm -rf "$ZIEL/programm.alt"

# ---------------------------------------------------------------- Python-Umgebung
LAUF_PYTHON="$PYTHON"
if [ "$PAKETE_AN" = 1 ]; then
    if [ ! -x "$ZIEL/venv/bin/python" ]; then
        echo "Creating Python environment (venv) ..."
        if ! "$PYTHON" -m venv --system-site-packages "$ZIEL/venv"; then
            echo "Could not create a venv (Debian/Ubuntu: sudo apt install python3-venv). Using $PYTHON." >&2
            rm -rf "$ZIEL/venv"
        fi
    fi
    if [ -x "$ZIEL/venv/bin/python" ]; then
        LAUF_PYTHON="$ZIEL/venv/bin/python"
        if [ "$QT_SYSTEM" = 1 ]; then
            # PySide6 vom System: ein früher per pip geholtes in der venv würde es verdecken
            if "$LAUF_PYTHON" -m pip show --quiet PySide6-Essentials >/dev/null 2>&1; then
                echo "Using the system's PySide6; removing the pip copy from the environment ..."
                "$LAUF_PYTHON" -m pip uninstall --quiet -y PySide6-Essentials shiboken6 >/dev/null 2>&1 || true
            fi
        else
            echo "Installing Qt (PySide6-Essentials, about 100 MB) ..."
            if ! "$LAUF_PYTHON" -m pip install --quiet --upgrade PySide6-Essentials; then
                echo "PySide6 could not be installed (no network?). Bookbench needs it." >&2
                echo "  Arch/EndeavourOS: sudo pacman -S pyside6, then run ./install.sh again" >&2
                exit 1
            fi
        fi
        echo "Installing optional packages: ${PAKETE[*]} ..."
        if ! "$LAUF_PYTHON" -m pip install --quiet --upgrade "${PAKETE[@]}"; then
            echo "Some packages could not be installed (no network?). Bookbench still runs;" >&2
            echo "run ./install.sh again later for JPEG covers, better synonyms and Claude." >&2
        fi
    elif [ "$QT_SYSTEM" = 0 ]; then
        echo "Without a Python environment PySide6 cannot be installed. Install it for $PYTHON:" >&2
        echo "  Arch/EndeavourOS: sudo pacman -S pyside6" >&2
        echo "  Debian/Ubuntu:    sudo apt install python3-venv python3-pyside6.qtwidgets" >&2
        exit 1
    fi
elif [ -x "$ZIEL/venv/bin/python" ]; then
    LAUF_PYTHON="$ZIEL/venv/bin/python"       # vorhandene Umgebung weiter nutzen
fi

# ---------------------------------------------------------------- Marke, Starter, Menü
"$PYTHON" - "$ZIEL/installation.json" "${VERSION:-}" "$LAUF_PYTHON" "$QUELLE" <<'EOF'
import json, sys
from datetime import datetime
pfad, version, python, quelle = sys.argv[1:5]
json.dump({"art": "linux", "version": version, "python": python, "quelle": quelle,
           "datum": datetime.now().isoformat(timespec="seconds")}, open(pfad, "w"), indent=1)
EOF

mkdir -p "$BIN" "$APPS" "$ICONS"
cat > "$BIN/bookbench" <<EOF
#!/bin/sh
$MARKE_STARTER
if [ -x "$ZIEL/venv/bin/python" ]; then P="$ZIEL/venv/bin/python"; else P="$PYTHON"; fi
exec "\$P" "$ZIEL/programm/start.py" "\$@"
EOF
chmod +x "$BIN/bookbench"

cp "$ZIEL/programm/bookbench/ui/bookbench.png" "$ICONS/bookbench.png"
cat > "$APPS/bookbench.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Bookbench
Comment=Chapter names, blurbs, covers and dictionaries for KOReader
Comment[de]=Kapitelnamen, Klappentexte, Cover und Wörterbücher für KOReader
Exec="$BIN/bookbench"
Icon=$ICONS/bookbench.png
Terminal=false
Categories=Office;
StartupWMClass=Bookbench
EOF
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$APPS" 2>/dev/null || true

echo
echo "Done. Start Bookbench from the menu or with: bookbench"
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "Note: $BIN is not in PATH; start it with $BIN/bookbench or add it to PATH." ;;
esac
echo "Optional for the preview: the desktop KOReader (e.g. AUR koreader-bin, Flatpak rocks.koreader.KOReader)."
echo "Updates: Help > Check for updates in Bookbench."
