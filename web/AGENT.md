# AGENTS.md - Web Kiosk ("The Head") Development Guide

This guide is for AI agents working within the `web/` directory of the Rainforest EMU-2 Grid Dashboard repository.

---

## 1. Package Mission & Boundaries

The `web/` package is the **Visualization Head** of the energy monitoring system:
- **Zero Ingestion Risk:** This package **never** reads from serial ports, writes to production databases, or runs heavy LLM training.
- **Read-Only Data Layer:** It queries `grid_history.db` exclusively via read-only SQLite connections (`file:?mode=ro`) and parses auxiliary CSVs (`solaredge_history.csv`, `solaredge_flow_history.csv`, `chilicon_history.csv`, `solaredge_battery_history.csv`).
- **Telemetry Sync:** `sync_service.py` pulls updated files from the Raspberry Pi Collector (`192.168.8.213` - `Rainforestpi`) to `data/` every 15 seconds.


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
    ├── index.html       # 3-Slide DOM structure matching physical VNC kiosk
    ├── assets/
    │   └── combined_logos.png  # Header logos badge (NVIDIA | Jetson | Pi | Gemini)
    ├── css/
    │   └── dashboard.css# High-contrast solid black theme (#000000)
    └── js/
        ├── app.js       # WebSocket client, clock, live metrics & 3-slide auto-cycle
        ├── charts.js    # Slide 1 (24h), Slide 2 (14d History), Slide 3 (DFT Spectrum) Chart.js
        └── vendor/
            └── chart.umd.min.js # Local offline Chart.js v4.4.7 bundle
```

---

## 3. Key Conventions for Agents Modifying This Code

### A. Frontend Visual Integrity
- **Physical Layout Match:** Any styling changes must preserve the look and feel captured in `vnc_kiosk.png` (solid black background, cyan headers, gold solar metrics, bright green/red net status).
- **No External CDN Dependencies:** All JavaScript and CSS libraries must remain vendored in `web/static/js/vendor/` to allow 100% offline operation on isolated LANs.
- **Responsive Viewport & Mobile Adaptation:** On desktop/kiosk displays (>= 769px), maintain fixed `100vw` / `100vh` without scrollbars, exactly matching the physical VNC kiosk display. On mobile viewports (<= 768px), enable vertical touch scrolling, stack metrics into compact cards, render the AI analysis narrative as a dedicated high-contrast glassmorphism card below the chart, and provide a fixed thumb-friendly bottom navigation bar with auto-cycle pause/resume toggle.

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
curl -s http://127.0.0.1:8000/api/telemetry/history14d
curl -s http://127.0.0.1:8000/api/telemetry/spectrum
curl -s "http://127.0.0.1:8000/api/summary?slide=2"
```

---

## 5. Backlog & TODOs

- [ ] **Battery Flex Event Rendering:** Represent battery discharge during PSE Flex events as negative values (below the X-axis, `-kW`) with shaded blue area fill in the time domain charts (`charts.js`), matching the physical kiosk Matplotlib representation.

