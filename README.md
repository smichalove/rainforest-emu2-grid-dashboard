# EMU-2 Grid Dashboard

A robust, 24-hour real-time grid monitoring dashboard using a Rainforest EMU-2 smart meter connected to a Raspberry Pi. It automatically boots into a fullscreen kiosk mode over HDMI, safely bypasses modern Wayland graphic quirks, and seamlessly persists data to a CSV to survive power outages.

## Hardware Requirements
- **Raspberry Pi** (Pi 3 or 4 recommended)
- **Rainforest EMU-2** connected via USB (`/dev/ttyACM0`)
- **HDMI Monitor** (The script dynamically scales to fullscreen, mimicking commercial 10" or larger solar dashboards)

## Key Features
- **Real-Time Data Parsing**: Decodes raw XML telemetry (`<InstantaneousDemand>`) directly from the EMU-2 serial port.
- **Fixed 24-Hour Graph**: Features a fixed `Midnight-to-Midnight` X-axis to accurately plot daily trends without using a confusing, fast-sliding window.
- **Persistent Data**: Logs data automatically to `grid_history.csv` every 15 seconds and retroactively reloads the graph immediately upon boot.
- **Hands-Free Kiosk Mode**: Configured to boot completely headless and automatically launch into fullscreen without sleeping.

---

## Complete Setup Instructions

### 1. Revert to X11 (Debian Bookworm)
Modern Raspberry Pi OS uses Wayland, which severely limits X11 forwarding and headless Tkinter display configurations over SSH. Revert to the highly stable X11 (LightDM) backend:
```bash
sudo raspi-config
# Navigate to: Advanced Options -> Wayland -> Choose X11
sudo reboot
```

### 2. Disable Screen Blanking
To prevent the HDMI screen from going to sleep after 10 minutes of inactivity, create an autostart script that disables power-management on boot:
```bash
mkdir -p ~/.config/autostart
nano ~/.config/autostart/disable-blanking.desktop
```
Add the following configuration:
```ini
[Desktop Entry]
Type=Application
Name=Disable Blanking
Exec=/usr/bin/xset s off -dpms
StartupNotify=false
Terminal=false
```

### 3. Autostart the Dashboard
Create a second desktop entry to automatically launch the python dashboard when the desktop environment finishes loading:
```bash
nano ~/.config/autostart/grid-dashboard.desktop
```
Add the following configuration:
```ini
[Desktop Entry]
Type=Application
Name=Grid Dashboard
Exec=/usr/bin/python3 /home/steven/dashboard.py
StartupNotify=false
Terminal=false
```

### 4. Install Dependencies
Make sure you have all required Python libraries installed:
```bash
pip3 install -r requirements.txt
```

### 5. Running Manually (Troubleshooting)
If you ever need to manually stop and restart the dashboard while the desktop is running, press `Ctrl+C` in your SSH terminal and run:
```bash
export DISPLAY=:0 && python3 dashboard.py
```
*(Note: If you receive a `couldn't connect` error because the HDMI is sitting at the root login screen, inject it using: `sudo XAUTHORITY=/var/run/lightdm/root/:0 DISPLAY=:0 python3 dashboard.py`)*

## Development & Security
- Always run `gitleaks` prior to committing or syncing any changes to GitHub.
