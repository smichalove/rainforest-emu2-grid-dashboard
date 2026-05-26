# EMU-2 Grid Dashboard

![EMU-2 Grid Dashboard Preview](dashboard_preview.jpeg)

A robust, 24-hour real-time grid monitoring dashboard using a Rainforest EMU-2 smart meter connected to a Raspberry Pi. It automatically boots into a fullscreen kiosk mode over HDMI, safely bypasses modern Wayland graphic quirks, and seamlessly persists data to a CSV to survive power outages.

## Hardware Requirements
- **Raspberry Pi** (Pi 3 or 4 recommended)
- **Rainforest EMU-2** connected via USB (`/dev/ttyACM0`)
- **HDMI Monitor** (The script dynamically scales to fullscreen, mimicking commercial 10" or larger solar dashboards)

## Key Features
- **Real-Time Data Parsing**: Decodes raw XML telemetry (`<InstantaneousDemand>`) directly from the EMU-2 serial port.
- **Rolling 24-Hour Graph**: Features a dynamic rolling 24-hour X-axis with the newest readings always positioned on the far right, ensuring the graph is always fully populated with historical context.
- **Persistent Data**: Logs data automatically to `grid_history.csv` every 15 seconds and retroactively reloads the graph immediately upon boot.
- **Hands-Free Kiosk Mode**: Configured to boot completely headless and automatically launch into fullscreen without sleeping.
- **Gemini Background Summaries**: Uses a background thread to call the Gemini 2.5 Flash model (via Vertex AI or Developer API Key) to analyze power trends and render a blue narrative watermark summary directly on the graph background, formatted with smart 80-character line wrapping.

---

## AI Background Summaries & Authentication

The dashboard integrates the **`google-genai`** SDK to query Gemini every 30 minutes in a non-blocking background thread. The generated summary is cached locally to disk (defaulting to `~/gemini_summary.json` if run from outside the repo) and loads instantly on startup.

### Authentication Setup
The dashboard automatically searches for credentials using one of the following methods:
1. **Google Cloud Service Account JSON (Headless/Vertex AI):**
   - Place the service account JSON key at `~/Auth/service_account.json` (or `auth/service_account.json` in the application directory).
   - The script routes queries via Vertex AI using the project `<your-gcp-project-id>` and location `global`.
   - Detailed instructions on setting up your Vertex AI Google Cloud account and generating service account keys can be found in the [veo-video-creation-workflow README](https://github.com/<your-github-username>/veo-video-creation-workflow/blob/main/README.md).
2. **Developer API Key:**
   - Create a `.env` file in the same directory as `dashboard.py` and define:
     ```env
     GEMINI_API_KEY="your_api_key_here"
     ```

### SolarEdge API Configuration
To enable SolarEdge PV generation overlay and mathematical analysis in the Gemini prompt, configure your SolarEdge API credentials inside `~/Auth/solaredge_config.json` (or `auth/solaredge_config.json` in the application directory):
```json
{
  "api_key": "your_solaredge_api_key",
  "site_id": "your_solaredge_site_id"
}
```

---

## Complete Setup Instructions

### 0. Clone the Repository
Clone this repository directly to your user's home directory on the Raspberry Pi:
```bash
cd ~
git clone https://github.com/<your-github-username>/rainforest-emu2-grid-dashboard.git
cd rainforest-emu2-grid-dashboard
```

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
Add the following configuration (be sure to replace `username` with your Pi's actual user account name, e.g. `steven` or `pi`):
```ini
[Desktop Entry]
Type=Application
Name=Grid Dashboard
Exec=/usr/bin/python3 /home/username/rainforest-emu2-grid-dashboard/dashboard.py
StartupNotify=false
Terminal=false
```

### 4. Install Dependencies & X11 Autostart
Modern Debian distributions (like Bookworm on Raspberry Pi) enforce PEP 668, preventing direct `pip` installations. 
1. Clone the repository to your Raspberry Pi.
2. Run the deployment script to create the Python virtual environment, install dependencies, configure the X11 autostart so the dashboard launches fullscreen automatically on boot, and suppress Raspberry Pi OS update popups for a seamless kiosk experience.

```bash
chmod +x install.sh
./install.sh
```

**Manual `venv` setup (if not using the install script):**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 5. Running Manually & Graceful Teardown
If you ever need to manually stop and restart the dashboard while the desktop is running, press `Ctrl+C` in your SSH terminal or close the window (by clicking the screen or pressing `Escape`). 

The script registers OS signal handlers (`SIGINT`, `SIGTERM`), which guarantees that:
- Background threads are stopped cleanly.
- The USB serial interface port (`/dev/ttyACM0`) is released.

To run manually:
```bash
export DISPLAY=:0 && python3 dashboard.py
```
*(Note: If you receive a `couldn't connect` error because the HDMI is sitting at the root login screen, inject it using: `sudo XAUTHORITY=/var/run/lightdm/root/:0 DISPLAY=:0 python3 dashboard.py`)*

If you do not have a SolarEdge solar system configured and want to completely disable SolarEdge telemetry querying, history loading, bar chart plotting, and aligned aggregations, run the dashboard using the `--solaroff` option:
```bash
python3 dashboard.py --solaroff
```

## Development & Security
- Always run `gitleaks` prior to committing or syncing any changes to GitHub.
