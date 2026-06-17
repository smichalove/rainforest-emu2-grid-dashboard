# System Log Inventory & Debugging Guide

This document lists and details all diagnostic, process, and error log files across the grid dashboard topology: the **Local Development Machine (mac)**, the **Raspberry Pi (Kiosk Display)**, and the **Jetson Orin Nano (Edge AI Server)**.

---

## 1. Raspberry Pi (Kiosk Display)

These logs monitor hardware communication, Tkinter UI event loops, local stagers, and X11 display settings.

| Log Path (Relative to `~`) | Primary Writer | Logging Purpose / Key Indicators |
| :--- | :--- | :--- |
| `~/rainforest-emu2-grid-dashboard/dashboard_gui.log` | `dashboard.py` (via `run_dashboard_system.sh` stdout redirection) | **Active stdout/stderr GUI log.** Logs: <br> - Current XML parsed demand values<br> - Matplotlib canvas draw durations (`Canvas draw took ... ms`) <br> - Thread crashes and standard stdout output. |
| `~/dashboard.log` | `dashboard.py` (via standard `logging` library file handler) | **Persistent python logging.** Logs initialization stages, client auth steps, thread spawning notifications, and internal exceptions. |
| `~/rainforest-emu2-grid-dashboard/stage_batch.log` | `stage_batch_summary.py` (via stdout redirection) | **Batch stager log.** Details local batch calculations, SQLite data migrations, and weather lookup outputs. |
| `~/dashboard_console.log` | `dashboard.py` (Console hook) | Redirected raw stdout/stderr console prints. |
| `~/dashboard_debug.log` | `dashboard.py` (Debug hook) | Verbose debugging and telemetry parse tracebacks. |
| `/home/steven/.xsession-errors` | X11 Display Server / LightDM | **Display and window-manager logs.** Use this to check if X11, the window manager, or Chromium kiosk modes crashed or if VNC connections had authority errors. |

### Diagnostic Commands

* **Read Active GUI Logs:**
  ```bash
  ssh steven@rainforestpi "tail -n 50 ~/rainforest-emu2-grid-dashboard/dashboard_gui.log"
  ```
* **Follow GUI Logs in Real-time:**
  ```bash
  ssh steven@rainforestpi "tail -f ~/rainforest-emu2-grid-dashboard/dashboard_gui.log"
  ```
* **Check GUI Process Status and CPU Load:**
  ```bash
  ssh steven@rainforestpi "ps aux | grep [d]ashboard.py"
  ```

---

## 2. Nvidia Jetson Orin Nano (Edge AI Server)

These logs monitor the local Gemma 2 2B / Ollama Edge AI models, stager processes, and gRPC communication.

| Log Source / System Unit | Primary Writer | Logging Purpose / Key Indicators |
| :--- | :--- | :--- |
| `systemd: jetson-grid-edge.service` | `stage_local_summary.py` (gRPC edge daemon) | **Primary Edge Stager log.** Logs:<br> - gRPC request ingress/egress contract compliance<br> - Ollama LLM query status and completion times<br> - Battery calculation states (PSE Flex events) and DFT spectral math performance. |
| `systemd: ollama.service` | Ollama edge inference server | **Ollama system service log.** Tracks GPU/CPU model loading states, token inference speed metrics, and memory utilization limits. |

### Diagnostic Commands

* **Read Stager Logs (systemd):**
  ```bash
  ssh steven@nvjetson "sudo journalctl -u jetson-grid-edge -n 50"
  ```
* **Follow Stager Logs in Real-time:**
  ```bash
  ssh steven@nvjetson "sudo journalctl -u jetson-grid-edge -f"
  ```
* **Inspect Ollama Inference Server Logs:**
  ```bash
  ssh steven@nvjetson "sudo journalctl -u ollama -n 50 --no-pager"
  ```

---

## 3. Local Development Machine (Mac)

Used during offline verification, simulation runs, and local UI rendering tests.

| Log Path | Primary Writer | Logging Purpose / Key Indicators |
| :--- | :--- | :--- |
| `~/dashboard.log` | `dashboard.py` (local execution) | **Local GUI execution logs.** Logs setup details and API calls made locally. |
| Stdout/stderr | `render_local_plot.py` | **Offline rendering output.** Output printed to terminal when executing `./plot_and_open.sh` to trace file load details. |

### Diagnostic Commands

* **Read Local Dashboard Log:**
  ```bash
  tail -n 50 ~/dashboard.log
  ```
* **Run Local Verification with Console Redirection:**
  ```bash
  ./venv/bin/python3 render_local_plot.py --screenshot --close
  ```

---

## 4. Known Troubleshooting Cases

### Case 1: GUI Freeze & Clock Sticking (Tkinter Event Loop Saturation)

* **Symptom**:
  * The GUI screen, slide transitions, and clock label on the kiosk freeze completely (typically sticking at the rotation timestamp).
  * The background threads remain fully operational, and the serial ingestion log (`dashboard_gui.log`) continues to print `Parsed Demand: ...` entries every 15 seconds.
* **Diagnosis (Using logs)**:
  * Look for the canvas draw duration logs in `dashboard_gui.log`:
    ```text
    2026-06-17 11:01:14,007 - INFO - Canvas draw took 7690.45 ms (Slide 1)
    2026-06-17 11:01:22,861 - INFO - Canvas draw took 8800.96 ms (Slide 2)
    ```
  * If the draw time exceeds **2,000ms**, the GUI thread is running slower than the update cycle scheduled via `self.after(2000, self.fast_render_loop)`.
  * This creates an infinite backlog of draw requests in the Tkinter event queue, locking the main thread.
* **Root Cause**:
  * Telemetry history arrays copy and pass all data points (e.g. past 14 days, which is $\approx 80,000$ points) to the Matplotlib LineCollection and segment building loops instead of slicing/limiting them to the active chart window.
* **Resolution**:
  * Implement slicing and integer stride downsampling (Option 1) in `update_chart()` to restrict the plotted points to a maximum of $\approx 5,000$ points (reducing render times to <150ms).
  * Restart the kiosk application via `./redeploy.sh` to purge the backlogged queue.

