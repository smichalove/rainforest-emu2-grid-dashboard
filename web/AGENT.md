# AGENTS.md - Web Kiosk ("The Head") Development Guide

This guide is for AI agents working within the `web/` directory of the Rainforest EMU-2 Grid Dashboard repository.

---

## 1. Package Mission & Boundaries

The `web/` package is the **Visualization Head** of the energy monitoring system:
- **Zero Ingestion Risk:** This package **never** reads from serial ports, writes to production databases, or runs heavy LLM training.
- **Read-Only Data Layer:** It queries `grid_history.db` exclusively via read-only SQLite connections (`file:?mode=ro`) and parses auxiliary CSVs (`solaredge_history.csv`, `chilicon_history.csv`, `solaredge_battery_history.csv`).
- **Telemetry Sync:** `sync_service.py` pulls updated files from the Raspberry Pi Collector (`192.168.8.122`) to `data/` every 15 seconds.

---

## 2. Architecture & File Roles

```text
web/
├── app.py               # FastAPI application, WebSocket hub (/ws/telemetry), REST endpoints
├── config.py            # Environment variables, sensor IPs (PurpleAir, Awair), paths
├── db_reader.py         # Read-only SQLite queries, baseline generators, CSV parsing
├── sensors.py           # TTL-cached (45s) live pollers for PurpleAir (192.168.10.241), Awair (192.168.8.219), and Open-Meteo
├── spectral_engine.py   # Discrete Fourier Transform (DFT) math, harmonic curves & SNR
├── sync_service.py      # Background rsync worker pulling telemetry from Pi over SSH
├── requirements.txt     # Python dependencies (fastapi, uvicorn, websockets, httpx, numpy)
├── run_server.sh        # Uvicorn production server launcher
├── launch_kiosk.sh      # Chromium fullscreen launcher for Raspberry Pi
│
└── static/              # Pure Vanilla Frontend (No build tools / no Node.js required)
    ├── index.html       # 2-Slide DOM structure matching physical VNC kiosk
    ├── assets/
    │   └── combined_logos.png  # Header logos badge (NVIDIA | Jetson | Pi | Gemini)
    ├── css/
    │   └── dashboard.css# High-contrast solid black theme (#000000)
    └── js/
        ├── app.js       # WebSocket client, clock, live metrics & 2-slide auto-cycle
        ├── charts.js    # Slide 1 (24h Time Domain) & Slide 2 (DFT Spectrum) Chart.js
        └── vendor/
            └── chart.umd.min.js # Local offline Chart.js v4.4.7 bundle
```

---

## 3. Key Conventions for Agents Modifying This Code

### A. Frontend Visual Integrity
- **Physical Layout Match:** Any styling changes must preserve the look and feel captured in `vnc_kiosk.png` (solid black background, cyan headers, gold solar metrics, bright green/red net status).
- **No External CDN Dependencies:** All JavaScript and CSS libraries must remain vendored in `web/static/js/vendor/` to allow 100% offline operation on isolated LANs.
- **Responsive Viewport:** Maintain `100vw` / `100vh` without vertical or horizontal scrollbars.

### B. Backend Concurrency & Reliability
- **Non-blocking Endpoints:** Use `async` route handlers in `app.py`. Offload blocking SQLite or file I/O using `asyncio.to_thread()`.
- **In-Memory Caching:** All direct sensor calls (PurpleAir, Awair, Weather) in `sensors.py` must use TTL caching (`CACHE_TTL_SECS = 45`) to prevent sensor flooding.
- **Resilient Fallbacks:** If the live database is warming up or empty, `db_reader.py` must return clean diurnal baseline data rather than empty arrays or 500 errors.

---

## 4. Running & Validating

```bash
# Start local server
cd web
./run_server.sh

# Test REST endpoints
curl -s http://127.0.0.1:8000/api/telemetry/live
curl -s http://127.0.0.1:8000/api/telemetry/history
curl -s http://127.0.0.1:8000/api/telemetry/spectrum
```
