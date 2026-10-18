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

### A. Frontend Visual Integrity & Universal Card Layout
- **Universal Card-Based Presentation:** [`web/static/css/dashboard.css`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/web/static/css/dashboard.css) uses the responsive card-based layout across all desktop and mobile viewports (`max-width: 1280px` centered container, `overflow-y: auto`, 3-column metric cards for SolarEdge PV / Chillicon PV / House Load, dedicated glassmorphism AI narrative card beneath the chart canvas, and fixed bottom slide navigation dock with tap-to-pause timer pill).
- **Stacked Solar & Energy-Balance House Load (`web/db_reader.py` & `web/static/js/charts.js`):**
  - Asynchronous time series (`grid_history`, `solaredge_history.csv`, `chilicon_history.csv`, `solaredge_battery_history.csv`) are projected onto a uniform 5-minute time grid (`_interp_to_grid()`) up to the current timestamp, using ISO `'T'` timestamp cutoffs (`%Y-%m-%dT%H:%M:%S`) for SQLite queries.
  - **House Load** is computed via physical energy conservation (`max(0.0, Net Grid + SolarEdge PV + Chillicon PV + Battery Discharge - Battery Charge)`).
  - SolarEdge PV (gold) and Chillicon PV (orange) render as stacked bars (`stack: 'solar'`).
  - Weather header displays Open-Meteo ambient forecast alongside PurpleAir local sensor temperature `(Actual: XX°F)`.
- **No External CDN Dependencies:** All JavaScript and CSS libraries must remain vendored in `web/static/js/vendor/` to allow 100% offline operation on isolated LANs.

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

---

## 5. Backlog & Completed Milestones

- [x] **Chilicon Local UDP `32758` Real-Time Ingestion:** Deployed `/etc/init.d/chilicon-rebroadcast` on the Flint 2 router (`192.168.8.1`) to rebroadcast outbound 1,372-byte UDP `32758` telemetry packets from the Chilicon CP-100 Gateway (`192.168.8.135:65452` ➔ `107.155.107.6:32758`, emitted every ~176s with two 90-second PLC sweeps across all 8 microinverters) to `520c` (`192.168.8.181:32758`) and `Rainforestpi` (`192.168.8.213:32758`). [`chilicon_udp_listener.py`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/chilicon_udp_listener.py) ingests per-inverter diagnostics into PostgreSQL (`energy_telemetry`) on `520c` and appends 90-second rolled-up system telemetry to `chilicon_history.csv` on both nodes.
- [ ] **Battery Flex Event Rendering:** Represent battery discharge during PSE Flex events as negative values (below the X-axis, `-kW`) with shaded blue area fill in the time domain charts (`charts.js`), matching the physical kiosk Matplotlib representation.


