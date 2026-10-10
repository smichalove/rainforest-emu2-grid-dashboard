# AGENTS.md - Rainforest EMU-2 Grid Dashboard Architecture & Development Guide

This guide is the primary reference manual for AI agents and developers working across this repository.

---

## 1. Overall System Architecture & Node Roles

The microgrid telemetry and monitoring platform operates across several specialized nodes:

| Host / Node | IP / Interface | Hardware / Role | Primary Responsibilities |
|---|---|---|---|
| **`Rainforestpi`** | `192.168.8.213` | Raspberry Pi 4 (HDMI/VNC) | USB serial reader (`/dev/ttyACM0`) for Rainforest EMU-2 smart meter, SQLite ingestion (`grid_history.db`), and 3-slide Matplotlib display (`dashboard.py`). |
| **`nvjetson`** | `192.168.8.68` | NVIDIA Jetson Orin Nano (8GB) | High-performance edge stager (`grpc_server.py:50051`), Discrete Fourier Transform (DFT) math engine, and gRPC telemetry streaming pipeline. |
| **`Stevens-Mini-2`** | `192.168.8.103:11434` | Apple M4 Mac Mini (16GB RAM) | **Primary Master Inference Node**: Executes `gemma4-it-q4:latest` with expanded 16,384-token context window (`num_ctx: 16384`) powering the multi-turn ReAct SQL agent loop. |
| **`mac-m1-max`** | `192.168.8.22:11434` | Apple M1 Max (32GB RAM) | **Secondary Failover Node**: Standard Ollama host with verified tool-calling support. |
| **`520c`** | `192.168.8.181` | Intel Xeon + RTX 4060 (8GB) | **FastAPI Web Kiosk Mirror** (Port 8000) & **Tertiary Accelerated Failover** (Port 11434). |
| **`ubunto-giga`** | `192.168.8.193:11434` | Linux GPU Workstation | Auxiliary Ollama completion host. |
| **`i7office`** | `192.168.8.82:11434` | Windows Workstation | Fallback Ollama completion host. |
| **`iTACH_AYRE`** | `192.168.8.122` | Dedicated Power Pi | Background audio power management (`powerd.py`), Global Caché IR/relay control, Emporia Vue 200A mains monitoring, and TP-Link fan management. |

---

## 2. 3-Slide Touchscreen & Web Kiosk Rotation

Both the physical touchscreen kiosk (`Rainforestpi`) and the FastAPI web mirror (`520c @ 192.168.8.181:8000`) cycle through three distinct operational slides:

1. **Slide 1 (24-Hour Time Domain)**: High-resolution net grid kW, house load, stacked solar generation (SolarEdge NW array + Chillicon SW microinverters), and battery State of Charge (SoC %) volume mapped to the negative floor ($-10.0$ to $0.0\text{ kW}$).
2. **Slide 2 (Zoom - 14-Day History Overview)**: Multi-day energy progression with an interactive ReAct AI agent narrative analyzing seasonal sun shifts, solar vs load balance, and battery economics.
3. **Slide 3 (Circuit Breakdown & DFT Spectrum)**: Real-time whole-home circuit telemetry (Emporia Vue 200A mains, sub-panels, smart plugs) and frequency-domain harmonic analysis.

---

## 3. 14-Day ReAct Agent Loop (`dashboard_modules/agent_loop.py`)

- **Interactive ReAct Architecture:** Executes up to 5 iterations of SQLite tool calls (`query_db`) across `analysis_history` and `grid_history` using `<tool_call>{"tool": "query_db", "sql": "..."}</tool_call>` protocol.
- **Pre-Injected 14-Day Matrix:** `get_14day_daily_breakdown_table()` injects a complete day-by-day table directly into the prompt (Date, Day of Week, Net Import/Export, Solar PV, Battery Charge/Discharge, Peak kW, House Load, and ⚡ PSE Flex Event flags).
- **Seasonality & Sun Cycles:** `get_seasonality_context()` computes month-specific Pacific Northwest solar elevation, sunrise, sunset, and daylight hours (e.g. October 11.2h daylight, 18:31 sunset) paired with diurnal load profiles (Morning Ramp, Midday Solar Soak, Evening Peak, Overnight Baseload).
- **16GB Unified Memory Exploitation:** Allocates `num_ctx = 16384` and `num_predict = 2048` with a 300-record SQL truncation threshold, fully utilizing the headroom on `Stevens-Mini-2`.
- **Failover Sequence:** Rotates sequentially through `192.168.8.103` -> `192.168.8.22` -> `192.168.8.181` -> `192.168.8.193` -> `192.168.8.82`. Notice `192.168.8.31` (`mac-m3-max`) is excluded due to running a non-standard Ollama proxy lacking tool calls.

---

## 4. Web Kiosk Package (`web/`)

The `web/` directory provides the lightweight FastAPI/HTML5 visualization head:
- **Zero Ingestion Risk:** Never connects to hardware serial ports or writes to production databases.
- **Read-Only SQLite:** Queries `grid_history.db` exclusively via read-only SQLite connections (`file:?mode=ro`).
- **Telemetry Sync:** Background worker pulls updated telemetry files from `Rainforestpi` (`192.168.8.213`) every 15 seconds.
- **Offline Vendoring:** Zero CDN dependencies; Chart.js v4.4.7 is vendored locally in `web/static/js/vendor/chart.umd.min.js`.
- **Mobile UI Compatibility:** Responsive CSS media queries (`@media (max-width: 768px)`) adapt the interface into a touch-friendly smartphone view (stacked status cards, dedicated AI narrative card below the chart, 44px thumb navigation with auto-cycle pause/resume toggle) while keeping the exact desktop kiosk display untouched.

---

## 5. Security & Rule Compliance

- **Gitleaks Scan:** Always run `gitleaks detect` before pushing to git to ensure no credentials or secrets are committed.
- **Read-Only SQL:** SQL tool queries must strictly be `SELECT` statements; non-SELECT mutations are rejected with security errors.
- **Network Boundaries:** Never bypass firewall rules (`Block_KVM_All_Forwarding` on `192.168.8.204` or `Block_8_81_IP_Forwarding` on `192.168.8.81`).
- **Detailed Rules:** Refer to `.agents/rules/agent.md` and `.agents/AGENTS.md` for permanent agent operating instructions.
