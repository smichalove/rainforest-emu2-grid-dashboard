# Agent Development Guidelines

This document serves as the official instruction manual for any AI agent or developer contributing to this repository. Always refer to these guidelines before writing or modifying any code.

---

## 1. Security Compliance & Pre-Commit Checks

- **Gitleaks Execution:** 
  > [!IMPORTANT]
  > You must run `gitleaks` to scan for secrets and sensitive information before any git commit or sync operation.
  - Under no circumstances should hardcoded credentials, serial device addresses that leak proprietary details, or personal network settings be committed.

---

## 2. Python Coding & Readability Standards

All Python code must strictly follow the Google Python Style Guide and readability standards. Key requirements include:

### Strict Type Hinting
- Every function, method, and class attribute must be fully type-annotated.
- Avoid using `Any`. Be as specific as possible (e.g., use `List[str]`, `Dict[str, int]`, `Optional[float]`, etc.).

### Mandatory Docstrings
- **Module/File Headers:** Every `.py` file must contain a fully descriptive, architectural top-level module docstring at the very beginning of the file. This docstring must detail the file's role in the overall architecture (e.g., Tier 1 vs Tier 2), its primary responsibilities, interfaces, dependencies, and how it fits into the project pipeline, ensuring other agents and developers can easily understand its context.
- **Classes:** Every class must include a docstring explaining its purpose, state, and key responsibilities.
- **Functions and Methods:** Every function/method must contain a comprehensive docstring that details:
  - The behavior and purpose of the function.
  - **Args:** Clearly listed arguments with their expected types and descriptions.
  - **Returns:** The return type and description of the output.
  - **Raises:** Any exceptions that could be raised by the function.
  
  Example:
  ```python
  def read_serial_data(port: str, timeout: float) -> str:
      """Reads raw XML telemetry from the EMU-2 serial port.

      Args:
          port: The filesystem path to the serial device (e.g., '/dev/ttyACM0').
          timeout: The read timeout in seconds.

      Returns:
          A string containing the raw XML payload received.

      Raises:
          SerialException: If the serial interface cannot be accessed.
      """
  ```

### Descriptive Inline Comments
- Write descriptive, inline comments for non-trivial logic blocks.
- Document hardware-specific behavior (e.g., Raspberry Pi serial communication, Tkinter UI scaling hacks, X11 configuration workarounds).
- Comments should explain the *why* behind the implementation decisions, not just *what* the code does, to enable other developers and users to quickly understand and debug the dashboard.

---

## 3. Prompt Management Standards

- **External Prompt Files:** 
  > [!IMPORTANT]
  > LLM prompts shall always be drafted in separate external `.txt` files rather than hardcoded in the codebase.
  - The application must load and refresh the prompt template from the file on disk dynamically at runtime (e.g., right before invoking the model).
  - This allows developers or operators to tweak system instructions and prompt context in real-time without restarting or modifying the core dashboard source code.

- **Show Prompt Returns:**
  > [!IMPORTANT]
  > Whenever the agent or application runs a prompt (either through emulation, test scripts, or local executions), the agent must explicitly print and show the raw prompt return/response text to the user.
  - This ensures full human-in-the-loop auditability and visibility of LLM behavior, allowing real-time assessment of output quality.

- **No Direct Note Writing Capability:**
  > [!IMPORTANT]
  > The local model / VLM does NOT have any tools or APIs to write or modify user annotations (`user_annotations.json`). If the user asks the model to "log a note" or "add a note", the model must decline to do so, state its technical limitation, and instruct the user to use the client's built-in `/note <text>` shortcut directly.

---

## 4. Command Execution Guidelines

- **Command Explanations:**
  > [!IMPORTANT]
  > For every command executed or proposed on the terminal, the agent must provide a quick, one-line explanation of what the command does and why it is being executed.

- **Script Path Portability (Absolute / Resolved Paths):**
  > [!IMPORTANT]
  > When writing or modifying shell scripts (`.sh`), never use un-anchored relative paths (like `./`) for file interactions or script executions. Always dynamically resolve the script's directory (using `SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"`) or use home directory references (like `~/`) to ensure the script operates correctly regardless of the caller's working directory.

---

## 5. Dependency Pinned Requirements

- **Strict Dependency Pinning:**
  > [!IMPORTANT]
  > All Python dependencies listed in `requirements.txt` must be strictly pinned to exact versions (using `==` instead of loose range operators like `>=` or unpinned packages).
  - This ensures build determinism, prevents dependency drift, and complies with Snyk security scanner requirements to prevent vulnerable older package resolutions.

---

## 6. UI & Design Refactoring Guidelines

- **No Unilateral Design Changes:**
  > [!IMPORTANT]
  > You must never make unilateral visual, structural, or layout design changes to the user interface (UI) without first presenting proposals, mockups, or options to the user for feedback and approval.
  - Attempt to resolve visual bugs (such as overlap, alignment, or readability issues) using local style adjustments (e.g. opacity, colors, margins, font sizes) before proposing any major structural layout redesign.

---

## 7. Git Commit & Sync Guidelines

- **Confirm Staging, Committing, and Pushing:**
  > [!IMPORTANT]
  > Never automatically stage, commit, or push files to git. You must always present the changes to the user first and ask for explicit confirmation that they are ready to commit and push.
  - This prevents cluttering the git history with incomplete or untested incremental changes, allowing the user to verify the application's working state first.

- **Avoid Chaining Execution Commands:**
  > [!IMPORTANT]
  > Never execute multiple modifying or deployment commands (such as copying files, installing packages, restarting processes, or running git operations) back-to-back in a single turn.
  - Break tasks into individual steps, check in with the user after key actions, and let them verify or provide feedback rather than forcing them to review and approve a large chain of commands all at once.

- **Manual Public Updates Only:**
  > [!IMPORTANT]
  > Never run `build_staging.py` or `./build_public_staging.sh` to update the public repository. Wiping the public directory dynamically is dangerous and risks losing public-only custom configurations, certs, or templates (such as `example_auth/`). Instead, always copy changed files individually using manual `cp` commands to update the public repository.

- **Version Control for Major Releases:**
  > [!IMPORTANT]
  > When delivering major feature updates or architectural shifts (such as V3), always create an annotated Git release tag (e.g., `git tag -a v3.0.0 -m "Release v3.0.0: ..."`), and push the tag to all remotes (`origin` and `backup`) to maintain clear historical records and prevent version confusion.

---

## 8. User Approval & Advice Guidelines

- **Always Wait for Explicit Consent on Advice/Proposals:**
  > [!IMPORTANT]
  > When proposing a design change, optimization, or architectural decision (such as altering a polling interval or adding a background loop), you must explain your advice/proposals and wait for the user's explicit consent or approval *before* implementing or executing the changes.
  - Never modify files or run deployment commands based on a proposal you just introduced without first letting the user review and confirm they want to proceed with that approach.

- **Present Multiple Options (High vs. Low Performance/Risk):**
  > [!IMPORTANT]
  > When proposing technical implementations, system configurations, coding designs, database queries/operations, or deployment paths, you must never unilaterally present a single solution, command, or implementation. You MUST present at least two options:
  > 1. An **Optimized / High-Performance Option** (detailing performance benefits, prerequisites, setup/compilation speed, and algorithmic efficiency).
  > 2. A **Simple / Low-Performance fallback Option** (detailing trade-offs, timelines, resource constraints, and ease of implementation).
  - Explicitly call out estimated execution times, risk of data loss, system overhead, and network/hardware bottlenecks for each option so the user can make an informed decision.
  - Use the choice between a slow live `dd` copy vs. a fast offline Mac clone as a standard baseline example of trade-offs in execution time and risk.

---

## 9. Log Inspection Guidelines

- **Human-in-the-Loop Log Sharing:**
  > [!IMPORTANT]
  > When executing background tasks, scripts, or system commands, you must keep the user actively in the loop by sharing and summarizing log outputs.
  - Never parse or analyze logs silently to make internal design decisions without explaining the log findings to the user first.
  - When debugging or running emulation scripts, output status details and progress metrics to the user so they can follow along.

- **Troubleshooting Inventory Reference:**
  > [!TIP]
  > Always refer to the [logs.md](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/logs.md) catalog in the root of the workspace for the current list of log files, their diagnostic purpose, and the commands to inspect them across all systems.

---

## 10. Network Topology & Hostnames

- **Jetson Orin Nano (Data & Math Node)**: `steven@nvjetson` (or `192.168.8.68`)
- **Jetson Orin Nano (Dedicated GPU AI Server)**: `steven@nvagent` (or `192.168.8.45`)
- **Raspberry Pi (Kiosk Display)**: `steven@rainforestpi` (or `192.168.8.70`)
- **Ubuntu GPU Server (Local Ollama/VLM Inference Server)**: `steven@ubunto-giga` (or `192.168.8.193`)
  * **CPU**: AMD Ryzen 5 5500 (6 Cores / 12 Threads)
  * **Motherboard**: Gigabyte AB350M-DS3H-CF (AMD B350 Chipset, BIOS Version F51g)
  * **RAM**: 32 GB DDR4
  * **GPU**: NVIDIA GeForce RTX 4060 (8 GB VRAM, CUDA 13.2 / Driver 595.71.05)
  * **Storage**: 1 TB SATA SSD (Root OS `/`) + 500 GB NVMe M.2 SSD (ext4, mounted at `/mnt/nvme`)
  * **OS**: Ubuntu 26.04 LTS

## 11. Avoid hardcoding values
- use parameters when possible or run time args
- when using global values they should be formatted like `SUMMARY_COLOR: str = 'deepskyblue'` and placed after imports (where logical) or like `SUMMARY_FONT_SIZE: int = 10`

---

## 12. Local Render Verification Rule

- **Always Verify Local Render Prior to Production Deployment:**
  > [!IMPORTANT]
  > Before committing, pushing, or redeploying any GUI/rendering code to production (the kiosk), you must always generate and verify the local plot rendering (e.g. running `./plot_and_open.sh` or `render_local_plot.py`) to confirm that all slides, watermarks, data lines, and stacked bar charts display correctly.

---

## 13. Production Deployment Safety (LGTM Rule)

- **Mandatory Code Diff & LGTM Before Deployment:**
  > [!IMPORTANT]
  > You must never run any deployment commands or scripts (such as `./redeploy.sh`) to copy code to production hardware (the Raspberry Pi kiosk or the Jetson server) without first:
  > 1. Running `git diff` to view the exact changes.
  > 2. Presenting the detailed code differences to the user.
  > 3. Obtaining their explicit **"LGTM"** or **"Approve deployment"** confirmation.
  - This ensures that unreviewed, experimental, or unapproved code changes in the workspace are never accidentally pushed to production.

---

## 14. High-Risk & Destructive Operations Guardrails

- **Mandatory Caution Warnings for Destructive Commands:**
  > [!CAUTION]
  > Before executing or proposing any command or script that performs destructive operations on disks, filesystems, or critical directories (such as `dd`, `mkfs`, `fdisk`, or recursive deletions), you MUST explicitly warn the user.
  - The warning must use a prominent `> [!CAUTION]` block detailing the exact target device or folder path, the risk of permanent data loss, and a prompt for verification.
  - Never execute or present a destructive command box without first providing this explicit warning.

---

## 15. Repository File Map & Deployment Architecture

This section serves as a direct reference for developers and agents to understand where files run and how they interact.

### Architecture Overview

```mermaid
graph TD
    subgraph Raspberry Pi (Kiosk Display)
        dashboard.py[dashboard.py GUI Kiosk]
        grpc_client[grpc_client.py Channel Mgr]
        stage_batch_summary.py[stage_batch_summary.py GCS stager]
        backup_sh[backup_to_jetson.sh rsync]
        cache_json[gemini_summary.json Local Cache]
    end

    subgraph Jetson Orin Nano (AI Edge Server)
        stager[stage_local_summary.py Daemon]
        grpc_server[grpc_server.py Server Mgr]
        ollama[(Ollama Local LLM: gemma4-it-q4)]
    end

    dashboard.py -- Read/Write --> cache_json
    dashboard.py -- Trigger --> backup_sh
    backup_sh -- scp CSVs --> stager
    dashboard.py --> grpc_client
    grpc_client -- gRPC/mTLS port 50051 --> grpc_server
    grpc_server --> stager
    stager -- Request --> ollama
    stager -- Response --> grpc_server
    grpc_server -- Stream Tokens --> grpc_client
    grpc_client -- Stream Tokens --> dashboard.py
```

### File Map & Roles

#### Core Application (Runs on Raspberry Pi)
- **[dashboard.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard.py)**: Main kiosk entry point. Starts Tkinter fullscreen GUI, runs thread pool watchdogs, and spawns the 5-minute local delta loop that triggers `backup_to_jetson.sh` and queries the Jetson stager daemon via secure gRPC client.
- **[backup_to_jetson.sh](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/backup_to_jetson.sh)**: Executed by `dashboard.py` on the Pi. Syncs telemetry CSVs and cache configs incrementally to the Jetson Orin Nano `grid_backup` home directory.
- **[run_dashboard_system.sh](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/run_dashboard_system.sh)**: Kiosk autostart helper that launches the background GCS batch stager and the main GUI process.
- **[stage_batch_summary.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/stage_batch_summary.py)**: Pi-side decoupled stager script running every 4 hours to upload historical telemetry to GCS and retrieve cloud baselines.

#### Modular Package (`dashboard_modules/` - Used on both Pi & Jetson)
- **[config.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/config.py)**: Central config file specifying colors, slide durations, font sizes, coordinates, and credential parser methods.
- **[io.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/io.py)**: Thread-safe file readers/writers featuring null-byte stripping for CSVs and atomic writes for JSON.
- **[telemetry.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/telemetry.py)**: Handles EMU-2 USB serial port auto-discovery, XML parsing, and history loading.
- **[solar.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/solar.py)**: Clients that authenticate and poll SolarEdge API and Chillicon panel updates.
- **[weather.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/weather.py)**: Fetcher for Open-Meteo forecasts with exponential failure backoffs.
- **[spectral.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/spectral.py)**: Math module calculating DFT coefficients, diurnal rhythm amplitude, and bimodal ratios.
- **[ai.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/ai.py)**: Interface client for Gemini API and Ollama generation queries.
- **[grpc_client.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/grpc_client.py)**: Encapsulates gRPC connection management, loads secure credentials, and queries telemetry analysis stream.
- **[grpc_server.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/grpc_server.py)**: Encapsulates secure gRPC server listening, database insertions, and maps background DFT metrics.

#### Edge AI Server (Runs on Jetson Orin Nano)
- **[stage_local_summary.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/stage_local_summary.py)**: Executed by systemd as the edge server listening on port 5000 (HTTP REST) and port 50051 (secure gRPC mTLS). It reads telemetry records, performs DFT and SNR math calculations, and streams token summaries using local Ollama models.
- **[snr_analysis.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/snr_analysis.py)**: Standalone mathematical helper file implementing DTFT spectrum and signal SNR calculators.

#### Verification & Testing (Runs on developer workstation)
- **[render_local_plot.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/render_local_plot.py)**: Mock desktop Tkinter GUI application that displays Slide 1 and Slide 2 layouts without hardware interfaces, simulating slide rotation, weather checks, and telemetry rendering.
- **[plot_and_open.sh](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/plot_and_open.sh)**: Utility script that runs `render_local_plot.py` to capture and verify Matplotlib renderings.

#### Prompt Templates
- **[gemma_hybrid_prompt.txt](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/gemma_hybrid_prompt.txt)**: Prompt template used by `stage_local_summary.py` to analyze time-domain metrics.
- **[gemma_dft_prompt.txt](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/gemma_dft_prompt.txt)**: Prompt template used by `stage_local_summary.py` to analyze frequency-domain SNR rhythms.

---

## 16. Implementation Plan & Roadmap Integrity

- **Preserve Uncommitted Plans & Roadmaps:**
  > [!IMPORTANT]
  > You must never run git operations (such as `git checkout` or `git restore`) or file writes that overwrite or discard uncommitted planning milestones, gRPC specifications, or future architecture roadmaps in [planning/implementation_plan.md](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/planning/implementation_plan.md). 
  - Always read the complete file first and ensure that any changes (e.g., adding logging references or caveats) are merged or appended cleanly without truncating other sections.

- **Proactive Status Updates:**
  - You must keep all roadmap files, task lists (`task.md`), and planning documents up-to-date. As soon as a feature is completed, tested, or deployed, update its status using explicit **[DONE]**, **[RESOLVED]**, or `[x]` checkmarks.

---

## 17. SQLite Database Schema & Telemetry Semantics

Any AI agent interacting with this repository or writing telemetry query code must conform to the following schema and semantic rules:

### Database: `grid_history.db`
This database serves as the unified storage for raw and aggregated microgrid metrics.

1. **`grid_history`** (overall net household grid demand)
   - `timestamp` (TEXT PRIMARY KEY) - ISO format naive timestamp (`YYYY-MM-DDTHH:MM:SS.mmmmmm`)
   - `kw` (REAL NOT NULL) - Net grid power demand in kW. **Positive values = importing** power from utility grid; **Negative values = exporting/feeding** power back to the grid.
   - Index: `idx_grid_timestamp ON grid_history(timestamp)`

2. **`solaredge_history`** (Northwest Solar PV array generation)
   - `timestamp` (TEXT PRIMARY KEY) - ISO format timestamp (`YYYY-MM-DDTHH:MM:SS`)
   - `pv_kw` (REAL NOT NULL) - Northwest (NW) SolarEdge solar PV array generation in kW.
   - Index: `idx_se_timestamp ON solaredge_history(timestamp)`

3. **`solaredge_battery_history`** (battery power flow and SoC status)
   - `timestamp` (TEXT PRIMARY KEY) - ISO format timestamp (`YYYY-MM-DDTHH:MM:SS`)
   - `battery_kw` (REAL NOT NULL) - Battery power charging/discharging in kW. **Positive values = charging/storing** energy; **Negative values = discharging/releasing** energy back to the house/grid.
   - `soc` (REAL NOT NULL) - State of charge percentage (0.0 to 100.0).
   - Index: `idx_se_bat_timestamp ON solaredge_battery_history(timestamp)`

4. **`solaredge_flow_history`** (integrated house power flow records)
   - `timestamp` (TEXT PRIMARY KEY) - ISO format timestamp (`YYYY-MM-DDTHH:MM:SS`)
   - `pv_power_kw` (REAL NOT NULL) - Combined active Solar PV production in kW.
   - `load_power_kw` (REAL NOT NULL) - Total household load/consumption power draw in kW.
   - `grid_import_kw` (REAL NOT NULL) - Active grid import in kW.
   - `grid_export_kw` (REAL NOT NULL) - Active grid export in kW.
   - Index: `idx_se_flow_timestamp ON solaredge_flow_history(timestamp)`

5. **`chilicon_history`** (Southwest Solar PV array generation)
   - `timestamp` (TEXT PRIMARY KEY) - ISO format timestamp (`YYYY-MM-DDTHH:MM:SS`)
   - `power_kw` (REAL NOT NULL) - Southwest (SW) Solar PV array microinverter generation in kW.
   - `lifetime_wh` (REAL NOT NULL) - Cumulative lifetime energy production in Wh.
   - Index: `idx_ch_timestamp ON chilicon_history(timestamp)`

### Database: `analysis_history.db`
Stores Edge AI daily summary history and frequency metrics.

1. **`analysis_history`**
   - `timestamp` (TEXT PRIMARY KEY) - Timestamp of execution.
   - `baseline_timestamp` (TEXT), `baseline_text` (TEXT), `summary_text` (TEXT), `dft_explanation` (TEXT).
   - `delta_import`, `delta_export`, `delta_peak`, `delta_solar`, `delta_se_solar`, `delta_ch_solar`, `delta_bat_charge`, `delta_bat_discharge`, `delta_se_load` (all REAL).
   - `se_load_min`, `se_load_max`, `se_load_avg` (REAL).
   - `expected_temp_max`, `expected_cloud_cover` (REAL).
   - `spectral_metrics_json` (TEXT - JSON serialized DFT amplitudes/SNRs).
   - `escalation_status` (TEXT), `escalation_timestamp` (TEXT).

### Critical Semantic Disambiguation Warnings
> [!IMPORTANT]
> * **Chilicon vs. Chiller**: `chilicon_history` tracks Southwest (SW) Solar PV array generation. It is **NOT** a chiller or cooling load database.
> * **No Chiller Table**: The microgrid has no separate sub-meter table tracking chiller consumption. Any chiller load is bundled under the general household load (`load_power_kw` in `solaredge_flow_history`).
> * **EV Vehicles**: The homeowner does **NOT** own an electric vehicle. Never mention EV, EV charging, or car charging under any circumstances.

### SQLite Timestamp Comparison Warning (T vs Space Format)
> [!WARNING]
> * **ISO Timestamp T Separator**: Timestamps in the SQLite databases (`local_repl.db` / `grid_history` / `solaredge_flow_history`) use the ISO standard **`T`** separator (e.g., `2026-06-22T07:23:59.302981`).
> * **Format Mismatches**: When comparing or querying timestamps using string filters, always include the `T` separator in raw string literals (e.g., `'2026-06-22T07:18:33'`). 
> * **Avoid Native datetime()**: Avoid using SQLite's native `datetime()` function directly in comparisons (e.g., `datetime('2026-06-22 07:18:33')`), as it outputs space-separated strings. Because the character `'T'` is lexicographically greater than a space `' '`, comparisons like `timestamp <= datetime(...)` will fail to match any rows.

### Mathematical Integration Warning (kW vs. kWh)
> [!WARNING]
> * **No Direct Summation on Raw Data**: The database tables (`grid_history`, `solaredge_history`, `chilicon_history`, `solaredge_battery_history`) store raw, periodic **instantaneous power readings (kW)** at irregular intervals (e.g. 5 to 15 minutes). Running a simple `SUM(kw)` or `SUM(pv_kw)` query directly on the raw tables will yield an incorrect result that is 4x to 12x too large.
> * **Riemann Sum Requirement**: To compute energy (kWh) over a duration, you must write queries or code that computes the time-weighted integral: $\text{Energy} = \sum \left( \text{Power}_i \times \Delta t_i \right)$, where $\Delta t_i$ is the time difference in hours between samples.
> * **Hourly Average Tables**: If you are using pre-aggregated hourly average tables (where each row represents a distinct 1-hour interval), summing the hourly average power (kW) values is mathematically correct because the time delta is $\Delta t = 1$ hour.


