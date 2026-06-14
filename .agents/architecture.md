# Decoupled Multi-Node Edge AI Dashboard Architecture

This document provides a comprehensive reference of the distributed architecture, data flow, and components of the EMU-2 Grid Dashboard system. It serves as persistent context for developers and AI agents.

---

## 1. System Topology & Node Roles

The system is distributed across three hardware nodes to isolate duties, ensuring responsive visual displays, low latency, and robust offline performance.

```mermaid
flowchart TD
    subgraph PiNode [Raspberry Pi Kiosk Node: rainforestpi]
        UI[dashboard.py / Tkinter GUI]
        LocalCache[gemini_summary.json]
    end

    subgraph Jetson1 [Jetson Orin #1: nvjetson (192.168.8.68)]
        Stager[stage_local_summary.py: port 5000 / gRPC 50051]
        DB[(grid_history.db - SQLite)]
    end

    subgraph Jetson2 [Jetson Orin #2: nvjetson2 (192.168.8.82)]
        API[FastAPI Server: port 8000]
        SDK[Google AI Edge SDK / MediaPipe / Ollama]
        GPU[Ampere GPU Core]
    end

    UI -->|1. Poll API / stream telemetry| Stager
    Stager -->|2. Read databases & run FFT| DB
    Stager -->|3. POST prompt payload| API
    API -->|4. Run model inference| SDK
    SDK -->|5. Compute acceleration| GPU
    GPU -->|6. Return generated tokens| SDK
    SDK -->|7. Return completed summary| API
    API -->|8. Return response JSON| Stager
    Stager -->|9. Write locally & return| UI
    UI -->|10. Cache summary text| LocalCache
```

### A. Client Display: Raspberry Pi Kiosk (`rainforestpi`)
*   **Role**: Graphical user interface, real-time telemetry polling, and user interaction.
*   **Core Software**: [dashboard.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard.py) (Tkinter, Matplotlib).
*   **Execution Profile**: Graphical (X11/Wayland), lightweight memory foot-print, completely decoupled from CUDA dependencies.
*   **State Store**: [gemini_summary.json](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/gemini_summary.json) (local caching).

### B. Data & Staging Daemon: Jetson Orin #1 (`nvjetson` / `192.168.8.68`)
*   **Role**: Telemetry ingestion, signal processing (FFT / SNR calculation), relational storage, and queue management.
*   **Core Software**: [stage_local_summary.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/stage_local_summary.py) (exposing HTTP port `5000` and secure gRPC on `50051`).
*   **Database Engine**: SQLite database stored in `backups/grid_history.db` (for production) containing joined high-frequency grid reads and low-frequency API telemetry.
*   **Reliability Mechanism**: Keeps an in-flight execution registry via `active_local_job.json`.

### C. Headless Inference Server: Jetson Orin #2 (`nvjetson2` / `192.168.8.82`)
*   **Role**: Dedicated GPU acceleration and Large Language Model execution.
*   **Core Software**: FastAPI server running the **Google AI Edge SDK** (MediaPipe) or containerized **Ollama** backends.
*   **Hardware Acceleration**: Direct access to NVIDIA Ampere Tegra cores using LiteRT/MediaPipe GPU delegates.
*   **Concurrency Constraint**: Because the underlying C++ inference graph is single-threaded, request streams are serialized using a mutex lock to prevent memory corruption/segmentation faults.

---

## 2. Communication Protocols & Security

*   **gRPC Streaming**: mTLS-secured gRPC stream on port `50051` for high-frequency telemetric sync and real-time inference alerts between nodes.
*   **Zero-Trust mTLS**: Authentication certificates are dynamically generated and distributed:
    *   **CA Certificate**: `Auth/certs/ca.crt` (shared between client/server).
    *   **Server Certificate**: `Auth/certs/server.crt` / `Auth/certs/server.key` (kept on the Orin).
    *   **Client Certificate**: `Auth/certs/client.crt` / `Auth/certs/client.key` (deployed on Pi).
*   **Legacy HTTP APIs**: Fallback API endpoints exposed on port `5000` (`/api/analyze`) for compatibility with legacy systems.

---

## 3. Database Schema & Ad-Hoc Analytics

All energy telemetry (grid usage, microinverter solar generation, and battery flow rates) is persisted to a unified SQLite database (`grid_history.db`). 

### Core Tables
1.  **`grid_history`**: High-frequency smart meter readings (approx. every 15 seconds) containing `timestamp` and `kw` (active grid power demand).
2.  **`solaredge_history`**: Lower-frequency SolarEdge inverter data containing solar PV production rate (`pv_kw`).
3.  **`solaredge_battery_history`**: Battery performance parameters including charge rate (`battery_kw`) and State of Charge percentage (`soc`).
4.  **`solaredge_flow_history`**: Full system household load rate (`load_power_kw`).
5.  **`chilicon_history`**: Microinverter-level AC power production (`power_kw`).

### Analytical Joins
Due to the mismatched sampling frequencies (15-second grid reads vs. 15-minute API feeds), queries must align records using an "As-Of" forward-filled subquery or standard window aggregation (15-minute buckets) to prevent data gaps.

---

## 4. Operational Resiliency

1.  **Dynamic Prompt Templates**: Prompt definitions are stored in external files (e.g. `gemma_hybrid_prompt.txt`) and loaded dynamically at execution time. This allows runtime adjustments without restarting application services.
2.  **Hardware Failures**: In the event of a power outage or system crash, the stager reads the state registry (`active_local_job.json`) upon reboot to restore the inference queue.
3.  **Noisy Signal Filtering**: If the serial reader reports line noise or drops, an autonomous script (`snr_analysis.py`) triggers rolling median smoothing window changes dynamically.
4.  **Data Imputation**: If the third-party solar/battery APIs fail, historical diurnal tables are read to fill gaps in the dataset, ensuring the graphs remain continuous.
