#!/usr/bin/env bash
set -euo pipefail

if [[ "$EUID" -eq 0 ]]; then
    echo "ERROR: Run as your normal desktop user, not root."
    exit 1
fi

INSTALL_DIR="$HOME/.local/share/xfce-kali-linux-snap"
AUTOSTART_FILE="$HOME/.config/autostart/xfce-kali-linux-snap.desktop"

echo "Uninstalling XFCE Kali Linux Snap..."

# Stop the installed application only.
pkill -f "^/usr/bin/python3 $INSTALL_DIR/hover_layout.py$" || true

rm -f "$AUTOSTART_FILE"
rm -rf "$INSTALL_DIR"

echo "SUCCESS: XFCE Kali Linux Snap uninstalled."
echo "Your settings in ~/.config/snaplayout/ are preserved."
