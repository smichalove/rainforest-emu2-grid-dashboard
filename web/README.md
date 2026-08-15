# Rainforest EMU-2 Web Kiosk ("The Head")

A modern, high-performance, real-time web-based kiosk dashboard for the Rainforest EMU-2 smart meter and microgrid monitoring system.

---

## 1. Overview & Architecture

This package acts as the **Visualization Head** in a decoupled energy monitoring architecture:
- **Collector Layer (Raspberry Pi):** Reads physical EMU-2 serial port and logs to `grid_history.db`.
- **Sync Engine (`sync_service.py`):** Automatically pulls the latest SQLite database and CSVs from the Pi to the server every 15 seconds over SSH.
- **Backend (`app.py`):** High-speed FastAPI application serving REST endpoints, WebSocket streaming, and static assets.
- **Frontend (`static/`):** Pure Vanilla HTML5/CSS/JS with local Chart.js hardware-accelerated canvas rendering, faithful to the physical Tkinter kiosk layout.

---

## 2. Package Structure

```text
web/
├── __init__.py               # Package descriptor
├── app.py                    # FastAPI ASGI application & WebSocket hub
├── config.py                 # Centralized configuration & environment loader
├── db_reader.py              # Safe read-only SQLite & CSV query engine
├── sensors.py                # Cached pollers for PurpleAir (192.168.10.241) & Awair
├── spectral_engine.py        # Discrete Fourier Transform (DFT) & SNR engine
├── sync_service.py           # Background rsync worker pulling from Pi Collector
├── requirements.txt          # Python dependencies
├── run_server.sh             # Local & 520c web service launcher
├── launch_kiosk.sh           # Chromium fullscreen launcher for Raspberry Pi
│
└── static/                   # Pure Vanilla Kiosk Frontend
    ├── index.html            # 2-Slide Kiosk DOM structure
    ├── assets/
    │   └── combined_logos.png# NVIDIA / Jetson / Pi / Gemini badge pill
    ├── css/
    │   └── dashboard.css     # High-contrast solid black theme (100vw/100vh)
    └── js/
        ├── app.js            # WebSocket client, live tiles & 2-slide rotation
        ├── charts.js         # Slide 1 (24h) and Slide 2 (DFT) Chart.js logic
        └── vendor/
            └── chart.umd.min.js # Local offline Chart.js bundle
```

---

## 3. API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Serves the fullscreen kiosk web app. |
| `GET` | `/api/telemetry/live` | Returns instantaneous Net Grid kW, Solar PV, Battery SoC, AQI, IAQ & Weather. |
| `GET` | `/api/telemetry/history` | Returns 24-hour time series dataset for Slide 1. |
| `GET` | `/api/telemetry/history14d` | Returns 14-day overview time series dataset. |
| `GET` | `/api/telemetry/spectrum` | Returns Discrete Fourier Transform (DFT) spectral harmonics for Slide 2. |
| `GET` | `/api/summary?slide=1` | Returns the narrative AI watermark summary for the specified slide. |
| `WS` | `/ws/telemetry` | WebSocket streaming live metrics every 5 seconds to connected displays. |

---

## 4. Quick Start

### A. Run Server (e.g. on 520c NAS or local workstation)
```bash
cd web
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./run_server.sh
```

### B. Launch Display on Raspberry Pi Kiosk
```bash
./web/launch_kiosk.sh http://192.168.8.181:8000
```
