#!/bin/bash
set -e

echo "=== Rainforest EMU-2 Dashboard Setup ==="

echo "1. Creating Python virtual environment (venv)..."
python3 -m venv venv

echo "2. Installing requirements..."
source venv/bin/activate
pip install -r requirements.txt

echo "Suppressing Raspberry Pi OS desktop update popups for seamless kiosk mode..."
mkdir -p ~/.config/autostart
echo -e "[Desktop Entry]\nHidden=true" > ~/.config/autostart/pi-package.desktop
echo -e "[Desktop Entry]\nHidden=true" > ~/.config/autostart/gui-updater.desktop

echo "3. Setting up X11 Autostart (GUI safe)..."
cat <<EOF > ~/.config/autostart/grid-dashboard.desktop
[Desktop Entry]
Type=Application
Name=Grid Dashboard
Exec=$(pwd)/venv/bin/python $(pwd)/dashboard.py
StartupNotify=false
Terminal=false
EOF

echo "Autostart configured at ~/.config/autostart/grid-dashboard.desktop!"
echo "=== Setup Complete! ==="
