#!/usr/bin/env bash
set -euo pipefail

if [[ "$EUID" -eq 0 ]]; then
    echo "ERROR: Run installer as your normal desktop user, not root."
    exit 1
fi

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/share/xfce-kali-linux-snap"
AUTOSTART_DIR="$HOME/.config/autostart"
CONFIG_DIR="$HOME/.config/snaplayout"

echo "Installing XFCE Kali Linux Snap..."

sudo apt-get update
sudo apt-get install -y \
    python3 \
    python3-gi \
    python3-xlib \
    python3-pil \
    gir1.2-gtk-3.0 \
    wmctrl \
    xdotool \
    x11-utils

mkdir -p "$INSTALL_DIR" "$AUTOSTART_DIR" "$CONFIG_DIR"

install -m 644 "$SOURCE_DIR/layoutku.py" "$INSTALL_DIR/layoutku.py"
install -m 644 "$SOURCE_DIR/hover_layout.py" "$INSTALL_DIR/hover_layout.py"

cat > "$AUTOSTART_DIR/xfce-kali-linux-snap.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Version=1.0
Name=XFCE Kali Linux Snap
Comment=Windows 11 Style Snap Layout for XFCE
Exec=/usr/bin/python3 $INSTALL_DIR/hover_layout.py
Icon=preferences-desktop-display
Terminal=false
X-GNOME-Autostart-enabled=true
OnlyShowIn=XFCE;
StartupNotify=false
DESKTOP

chmod 644 "$AUTOSTART_DIR/xfce-kali-linux-snap.desktop"

echo
echo "SUCCESS: XFCE Kali Linux Snap installed!"
echo "Application: $INSTALL_DIR"
echo "Autostart: $AUTOSTART_DIR/xfce-kali-linux-snap.desktop"
echo "Log out and log in to start automatically."
