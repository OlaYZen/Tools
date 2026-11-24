#!/bin/sh
# Builds diskmap and installs it for the current user: both programs into ~/.local/bin, the
# icon, and the two launcher entries (the window, and the terminal program) that app
# launchers such as the HyprToys launcher, rofi and the desktop menus read.
#
# The entries name the binaries by absolute path: a launcher started by the compositor
# inherits its PATH from the session, which often lacks ~/.local/bin.
set -eu
cd "$(dirname "$0")/.."

BINDIR="${BINDIR:-$HOME/.local/bin}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"

cargo build --release
install -Dm755 target/release/diskmap "$BINDIR/diskmap"
install -Dm755 target/release/diskmap-gui "$BINDIR/diskmap-gui"
install -Dm644 packaging/diskmap.svg "$DATA/icons/hicolor/scalable/apps/diskmap.svg"
for entry in diskmap diskmap-terminal; do
    sed -e "s|@BINDIR@|$BINDIR|g" -e "s|@HOME@|$HOME|g" "packaging/$entry.desktop.in" > "$DATA/applications/$entry.desktop.tmp"
    mv "$DATA/applications/$entry.desktop.tmp" "$DATA/applications/$entry.desktop"
done
command -v update-desktop-database >/dev/null && update-desktop-database -q "$DATA/applications" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -qtf "$DATA/icons/hicolor" || true
echo "Installed diskmap $("$BINDIR/diskmap" --version | cut -d' ' -f2) to $BINDIR"
