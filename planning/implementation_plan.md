# Implementation Plan: V3.2 Native SolarEdge Consumption & Grid Import Telemetry

The monolithic V3 refactoring and Jetson Edge AI integrations are complete. The next major architectural phase focuses on replacing overlapping, inferred data models with true native telemetry from the SolarEdge Revenue Grade Meter (RGM) and external CT clamps. This will perfectly align the dashboard's consumption statistics with your Emporia Vue measurements.

## Proposed Changes

### 1. SolarEdge API Upgrades

#### [MODIFY] [solar.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/solar.py)
- **Real-Time Snapshot (`currentPowerFlow`):**
  - Add support for the `/site/{siteId}/currentPowerFlow` endpoint.
  - Parse `LOAD` (`currentPower`) for total instantaneous house consumption.
  - Parse `GRID` via the `connections` array (`"FROM": "GRID", "TO": "LOAD"`) for active grid draw.
- **Historical Telemetry (`energyDetails`):**
  - Add support for the `/site/{siteId}/energyDetails` endpoint to pull quarter-hour historical curves matching Emporia.
  - Request parameters: `meters=Consumption,Purchased` & `timeUnit=QUARTER_OF_AN_HOUR`.
  - Extract `Consumption` (Total energy used by house) and `Purchased` (Input kWh pulled strictly from the utility grid).

### 2. Telemetry Realignment

#### [MODIFY] [telemetry.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/telemetry.py)
- Re-align the EMU-2 grid import/export math to gracefully hand off authority. When SolarEdge RGM data is present and active, prioritize the SolarEdge CT clamps as the primary source of truth for household load, using the EMU-2 serial stream purely as a redundant fallback or for split-second local visualization.

### 3. Dynamic Polling Optimization (API Quota Management)

#### [MODIFY] [dashboard.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard.py)
- Implement a dynamic background polling interval to prevent hitting the strict SolarEdge 300 requests/day limit.
- **Nighttime Polling Rule:** Since EMU-2 dashboard data is perfectly accurate when there is no solar or battery discharging, the API will **completely pause** overnight (e.g. from sunset to sunrise) *unless* the battery is actively discharging, preserving almost the entire 300 request quota for the daylight hours.

```bash
# Reference Interval Logic
get_optimal_interval() {
    local daylight_hours=$1
    local daily_quota=300
    local interval_sec=$(( daylight_hours * 3600 / daily_quota ))
    echo "$interval_sec"
}
```

## Verification Plan

### Automated Tests
- Introduce mocked JSON payloads for the `currentPowerFlow` and `energyDetails` endpoints in `tests/test_modules.py`.
- Verify the SolarEdge parser correctly extracts and isolates the `Consumption` and `Purchased` kWh values.

### Manual Verification
- Deploy to the Raspberry Pi kiosk.
- Visually verify that the dashboard's updated "Grid Import" and "Household Consumption" labels exactly match the live readouts from the Emporia Vue mobile app.

---

## 4. Phase 3.3: High-Speed gRPC Telemetry Streaming

As a long-term architectural goal (V4), the underlying data transport layer between the Pi kiosk and the Jetson AI server will be migrated from the current JSON/HTTP REST polling architecture to a high-speed, binary `gRPC` streaming model.

### Objectives
- **Replace JSON Payloads:** Use the pre-existing `protos/grid_telemetry.proto` definitions to serialize telemetry into lightweight binary structures, massively reducing network overhead on the LAN.
- **Bi-Directional Streaming:** Allow the Jetson to maintain an open gRPC channel with the Pi, streaming AI summaries and system anomalies asynchronously the exact millisecond they are detected, rather than waiting for the Pi's 60-second HTTP polling cycle.
- **Reduced Latency:** Eliminate the HTTP handshake overhead, significantly improving the Pi's render loop efficiency.

---

## 5. Future Refactoring: Modularizing `stage_local_summary.py`
- **Monolithic Audit Note:** The Jetson edge stager script `stage_local_summary.py` has expanded to over 1000 lines, combining server routing, weather fetching, telemetry calculations, DFT spectral processing, and Ollama integration in a single file. 
- **Action Plan:** Evaluate and modularize this stager in a future cleanup phase. Break it down into modular packages (e.g., similar to `dashboard_modules/` on the Pi) to separate logic concerns, improve maintainability, and ensure unit-test isolation.

---

## 6. Repository Module Map Reference
The codebase is decoupled into the following modular packages under the [dashboard_modules](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules) namespace to organize functionality and reduce cognitive overhead:

1. **[config.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/config.py)**: Centralizes GUI styling parameters (fonts, colors, coordinates, frame metrics) and default lat/lon constants.
2. **[io.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/io.py)**: Provides atomic, thread-safe JSON read/write handles and null-byte cleanup for telemetry CSV files.
3. **[telemetry.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/telemetry.py)**: Manages EMU-2 serial polling, signed hex-to-dec XML conversions, and rolling telemetry data arrays.
4. **[solar.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/solar.py)**: Handles SolarEdge and Chillicon Cloud API sessions, requests, cookies, and authentication.
5. **[weather.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/weather.py)**: Integrates current forecast and past 5-day weather history metrics via Open-Meteo REST calls.
6. **[spectral.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/spectral.py)**: Pure mathematical library for DTFT amplitude/phase calculation, curve derivatives (slopes), and signal SNR calculations.
7. **[ai.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/ai.py)**: Interfaces with Google Cloud Storage and Vertex AI GenAI SDKs for bulk baseline summary prediction jobs.

---

## 7. Development Methodology Review

A programmatic review of current workflows and structural design has highlighted the following points:

### Core Strengths
- **Mandatory Pre-Commit Checks**: Running `pytest` and `gitleaks` prior to any deploy or commit successfully isolates bugs and protects API credentials.
- **Human-in-the-Loop Safe Deployment (Rule 13)**: The requirement for explicit `git diff` review and "LGTM" validation prevents unapproved developer versions from being pushed to production.
- **Resilient Fallback Design [DONE]**: Combining local file caching with client-side API throttling prevents `429 Too Many Requests` API locks from interrupting kiosk telemetry display. (Throttling with 15-minute cool-down and cache merge successfully implemented).

### Future Improvement Areas
- **Stage Script Refactoring**: The Jetson server helper script `stage_local_summary.py` has reached >1000 lines. Calculate functions and route handlers should be broken into modules similar to `dashboard_modules/`.
- **Complete Prompt Separation**: While core model instructions are externalized in text files, minor formatting prompts should be centralized to keep layout rules cleanly segregated from script logic.
- **Integration Test Execution**: Introduce a secondary testing tier running active queries against dummy/local stage servers to detect runtime network/schema drifts not covered by static mock tests.

> [!TIP]
> **Decoupled Architecture Cache Race Condition [DONE / RESOLVED]**: Multi-process architectures reading and writing to the same cache file (`gemini_summary.json`) are prone to race conditions if a background thread writes back using stale in-memory variables. We resolved this by modifying the GUI's `local_delta_loop` thread to merge and write back using fresh cache values read directly within the same loop iteration (`clean_baseline`), preventing stager lockups.

---

## 8. Logging Reference Map

To locate and trace runtime errors, use the following mapping between functional source code components and their target log files:

| Component / File | Execution Host | Active Log File Path / Access Command | Log Content Scope |
| :--- | :--- | :--- | :--- |
| **[dashboard.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard.py)** (Main GUI) | Raspberry Pi (`steven@rainforestpi`) | `/home/steven/dashboard.log` | Structured python `logging` output, weather fetch cool-downs, API errors, fallback triggers, thread status. |
| **[dashboard.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard.py)** (Process Output) | Raspberry Pi (`steven@rainforestpi`) | `/home/steven/rainforest-emu2-grid-dashboard/dashboard_gui.log` | Process standard output/stderr, Tkinter display warnings, fatal python tracebacks. |
| **[stage_batch_summary.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/stage_batch_summary.py)** (Vertex AI Stager) | Raspberry Pi (`steven@rainforestpi`) | `/home/steven/rainforest-emu2-grid-dashboard/stage_batch.log` | Cloud Batch job submission statuses, GCS file uploads, timer/interval countdowns. |
| **[stage_local_summary.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/stage_local_summary.py)** (Edge AI Server) | Jetson Orin Nano (`steven@192.168.8.68`) | `sudo journalctl -u jetson-grid-edge.service -n 100 --no-pager` | Incoming API request logs, Ollama generation stats, local weather math, DFT telemetry spectrum parsing. |
| **[dashboard_modules/*.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules)** (Shared Core Logic) | Dynamic (Pi / Jetson) | Inherits parent caller log path (e.g., `/home/steven/dashboard.log` or service journal). | Low-level serial communication, API session requests, mathematical DFT calculations. |

To follow live log streams:
- GUI terminal stream: `tail -f /home/steven/rainforest-emu2-grid-dashboard/dashboard_gui.log`
- Cloud Batch prediction loop stream: `tail -f /home/steven/rainforest-emu2-grid-dashboard/stage_batch.log`
- Jetson edge server stream: `ssh steven@192.168.8.68 "sudo journalctl -u jetson-grid-edge.service -f"`


## 9. Proposed UI Feature: Homeowner Energy Summary Slide

Based on developer/user experiments, we propose integrating a new fullscreen slide (or a modal overlay) that displays a friendly, conversational summary of recent microgrid performance. This will translate technical telemetry (kW, kWh, phase angles) into a simple, encouraging narrative for the homeowner.

### Candidate Summary Format (Generated by `gemma4-it-q4`):

```markdown
Hello there! I've analyzed your energy dashboard, and I have some fantastic news! Your system is working really well, generating a lot of savings and keeping your home powered efficiently.

### 💰 The Financial Snapshot
* **Net Credit:** System generated a net credit of $11.56.
* **Energy Flow:** Exported a huge amount of electricity (139.73 kWh) and only imported 78.89 kWh.

### ☀️ Solar Power & Battery Performance
* **Solar Generation:** SolarEdge panels produced 40.75 kWh of clean energy.
* **Battery Heroics (Flex Events):** Battery discharged 10.93 kWh during 4 PSE Flex events and received favorable reimbursement.

### ⚠️ Important Alert
* **Chillicon Gateway Disconnect:** The Chillicon WiFi Gateway went offline for ~15 hours during daylight. Verify the connection or network stability.
```

This feature will be evaluated as a potential Slide 3 or an expandable touch overlay in future dashboard releases (V4).

