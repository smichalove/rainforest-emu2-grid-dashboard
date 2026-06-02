# Implementation Plan: Monolithic Refactoring & Modularization

This document details the functional breakdown and boundaries for refactoring the monolithic `dashboard.py`, `render_local_plot.py`, and `stage_batch_summary.py` files. We group code into cohesive, single-responsibility modules under a new package named `dashboard_modules`.

---

## 1. Directory Structure

The new package structure will be organized as follows:

```
rainforest-emu2-grid-dashboard/
│
├── dashboard_modules/
│   ├── __init__.py           # Package exports
│   ├── config.py             # Global constants & styling parameters
│   ├── io.py                 # Centralized CSV & JSON file IO (Thread-safe)
│   ├── telemetry.py          # EMU-2 serial & XML parsing
│   ├── solar.py              # SolarEdge & Chillicon clients (CSV persistence via io.py)
│   ├── weather.py            # Open-Meteo clients (live & historical)
│   ├── spectral.py           # Gap interpolation, DFT, & SNR spectral math
│   └── ai.py                 # Gemini, Ollama, GCS Upload, and Batch API handling
│
├── dashboard.py              # Main Tkinter UI Application (Core Runner & Watchdog)
├── render_local_plot.py      # Local visualization emulator
├── stage_local_summary.py    # Local staging entry point
└── stage_batch_summary.py    # Cloud Batch API staging entry point
```

---

## 2. Special Architectural Considerations

### Data Acquisition Thread Safety & Portability
1.  **Thread Concurrency:** Real-time data acquisition runs on dedicated background threads to prevent UI freeze. The shared buffers (`self.usage`, `self.timestamps`, etc.) will continue to be protected via `self.data_lock = threading.Lock()` inside the main application class. The refactored data acquisition helpers in `dashboard_modules/telemetry.py` and `dashboard_modules/solar.py` are strictly stateless or thread-safe, returning parsed objects directly to the caller's thread rather than mutating shared global state.
2.  **Shared Loader Interface:** Both the real Pi dashboard (polling serial) and the Mac emulator (reading CSV files) will use the same unified file loaders from `telemetry.py` and `solar.py`, ensuring consistent parsing of historical data.

### Centralized JSON/CSV File IO Operations
To prevent filesystem corruptions (especially null-byte write loops caused by abrupt Raspberry Pi power cuts), all database files, caches, and log exports are centralized in `dashboard_modules/io.py`:
*   **Null-byte Stripping:** CSV readers proactively filter out null bytes (`\x00`) during parsing.
*   **Atomic JSON Writes:** Caches (e.g. `gemini_summary.json`) are written using temporary swap-files to prevent corruption if the dashboard is killed mid-write.

### Dependency Lazy Loading (Import Optimization)
To ensure the modular package remains lightweight and portable across different host nodes (Pi kiosk vs Jetson server vs local Mac), libraries will be imported conditionally:
*   **`serial`:** Imported on-demand inside `dashboard_modules/telemetry.py` only when initializing physical serial ports (avoiding crashes on machines without serial drivers).
*   **`google-genai` / `google.cloud.storage` / `httpx`:** Lazy-loaded inside `dashboard_modules/ai.py` only when active functions are invoked (avoiding missing module exceptions on nodes running headless or offline).
*   **`tkinter` / `PIL` / `matplotlib.backends`:** Kept strictly inside the UI entry points (`dashboard.py` and `render_local_plot.py`). Core computational modules (`spectral.py`, `config.py`) will remain headless and dependency-free.

---

## 3. Core Runner & Self-Healing Watchdog Orchestration

To guarantee continuous 24/7 operation on the Pi kiosk display, `dashboard.py` implements a core supervisor layer to monitor background threads and recover from hardware or API failures:

1.  **Thread-Level Self-Healing (Exception Isolation):**
    Each daemon thread (Serial Reader, SolarEdge API Poller, Chillicon API Poller, AI Summary fetcher) runs in an isolated `try...except Exception` event loop. If a temporary network timeout, API rate limit, or device lockup occurs, the thread logs the error, triggers an exponential backoff timer, and automatically attempts to reconnect/re-authenticate without letting the thread crash.
2.  **Global Supervisor Watchdog (Core Runner Recovery):**
    *   `dashboard.py` launches a background supervisor thread (`start_watchdog_loop`) that polls the state of all active background threads (`self.thread`, `self.se_thread`, `self.chilicon_thread`, `self.summary_thread`) every 60 seconds.
    *   If a thread crashes due to an unhandled hardware exception (e.g., USB device hard disconnection), the supervisor thread tears down the corrupted thread handle, executes clean-up hooks, and restarts the daemon loop fresh.
3.  **Hardware Port Recovery:**
    If the EMU-2 USB connection is severed, `telemetry.py`'s port scanning is re-invoked by the serial thread, continuously searching for a valid USB port until the hardware is reconnected.

---

## 4. Functional Breakdowns by Module

### A. `dashboard_modules/config.py`
This module encapsulates all global settings, environment loading, and hardware settings.

*   **Variables/Functional Sets:**
    *   `load_env_credentials()`: Parses `.env` and `auth/*.json` credentials. Returns SolarEdge keys, Chillicon login, and location coordinates.
    *   **Styling Tokens:** `IMPORT_COLOR`, `EXPORT_COLOR`, `EXPECTED_SOLAR_COLOR`, `CONSUMPTION_COLOR`, `SUMMARY_COLOR`, `SUMMARY_ALPHA`, `SUMMARY_FONT_SIZE`, `STATUS_FONT_SIZE`.
    *   **Intervals:** `SLIDE_1_DURATION_MS`, `SLIDE_2_DURATION_MS`, `BAUD` (115200).
    *   **Geographic Defaults:** `DEFAULT_LAT`, `DEFAULT_LON`, `DEFAULT_WEATHER_FALLBACK`.

---

### B. `dashboard_modules/io.py`
Centralizes all local file storage reads and writes.

*   **Functional Sets & Signatures:**
    *   `read_clean_csv(filepath: str) -> List[List[str]]`: Opens CSV files, strips null bytes, cleans whitespace, and returns rows as text lists.
    *   `write_csv_row(filepath: str, row: List[Any])`: Appends a row of variables to a CSV.
    *   `read_safe_json(filepath: str) -> Dict[str, Any]`: Loads JSON data, returning an empty dict if the file is missing or corrupted.
    *   `write_safe_json(filepath: str, data: Dict[str, Any])`: Writes JSON atomically via a temporary file exchange to prevent corruption during system outages.

---

### C. `dashboard_modules/telemetry.py`
Handles communication with the physical Rainforest EMU-2 USB dongle, serial loop, and local history parsing.

*   **Functional Sets & Signatures:**
    *   `find_emu2_port() -> str`: Searches system USB ports (`/dev/tty.usbserial*`, `/dev/ttyACM*`) to find the dongle.
    *   `hex_to_signed_int(hex_str: str, bits: int = 32) -> int`: Utility for binary decoding.
    *   `parse_xml_telemetry(xml_data: str) -> Optional[Tuple[datetime, float]]`: Parses the raw XML stream chunks into timestamps and demand (kW) values.
    *   `load_grid_history(filepath: str, cutoff_hours: int = 24) -> Tuple[List[datetime], List[float]]`: Reads historical measurements from CSV via `io.py`, filters by the 24-hour cutoff, and returns time/demand series.

---

### D. `dashboard_modules/solar.py`
Encapsulates external API queries and authentication states for the solar generation hardware.

*   **Functional Sets & Classes:**
    *   `class SolarEdgeClient`:
        *   `__init__(api_key: str, site_id: str, history_file: str)`
        *   `load_history() -> Tuple[List[datetime], List[float], List[datetime], List[float], List[float]]`: Reads solar/battery CSV tables using `io.py`.
        *   `fetch_data() -> Optional[Dict[str, Any]]`: Performs power and battery flow queries, writing to history via `io.py` if successful.
    *   `class ChilliconClient`:
        *   `__init__(username: str, password: str, installation_hash: str, history_file: str)`
        *   `load_history() -> Tuple[List[datetime], List[float], List[float]]`: Reads Chillicon power/energy history using `io.py`.
        *   `login() -> bool`: Signs in to the portal and stores cookie jar sessions.
        *   `fetch_data() -> Optional[Tuple[float, float]]`: Pulls live generation metrics and writes to CSV via `io.py`.

---

### E. `dashboard_modules/weather.py`
Queries weather parameters from the Open-Meteo meteorological endpoints.

*   **Functional Sets & Signatures:**
    *   `fetch_live_weather(lat: str, lon: str) -> Dict[str, Optional[float]]`: Retrieves current temperature, cloud cover, and daily sunrise/sunset timings.
    *   `fetch_historical_weather(lat: str, lon: str) -> Dict[str, Dict[str, Any]]`: Pulls historical 5-day coordinates to calibrate weather-modulated curves.

---

### F. `dashboard_modules/spectral.py`
Contains all signal processing, uniform grid alignments, discrete transforms, and noise floor math.

*   **Functional Sets & Signatures:**
    *   `interpolate_gaps(timestamps: List[datetime], series: List[Optional[float]], max_gap_minutes: int = 10) -> List[float]`: Resamples raw telemetry onto uniform 15-second grids while preserving outage markers.
    *   `compute_dft(amplitudes: List[float], num_cycles: float) -> complex`: Standard 1D transform calculation.
    *   `align_and_compute_spectra(grid_data, solar_data, consumption_data) -> SpectralOutput`: Computes and aligns power vectors for Slide 2 overlay rendering.
    *   `calculate_snr_db(freqs: List[float], amplitudes: List[float], peak_freq: float, signal_half_width: float = 0.05) -> float`: Relies on `snr_analysis.py` algorithms to map prediction metrics.

---

### G. `dashboard_modules/ai.py`
Centralizes all local and cloud-based AI/LLM models, prompt builders, Cloud Storage (GCS) uploading, and Gemini Batch API operations.

*   **Functional Sets & Signatures:**
    *   `fetch_gemini_summary(prompt_template_path: str, context_data: Dict[str, Any], local_llm: bool = False) -> str`: Invokes local Ollama or remote Vertex endpoint using text prompt templates.
    *   `generate_hourly_summaries(history_data) -> str`: Aggregates usage arrays into structured text lists.
    *   `calculate_local_deltas(...) -> str`: Evaluates grid imports/exports against historical baselines.
    *   `upload_to_gcs(local_path: str, gcs_path: str, bucket_name: str) -> str`: Safely uploads batched JSON files to GCS bucket for Batch processing.
    *   `poll_batch_job(client, job_name: str) -> str`: Proactively checks remote Batch job status until completion.
    *   `download_and_parse_output(dest_uri: str) -> str`: Downloads the output token stream from the completed Batch GCS path.

---

## 4. UI & Entry Point Integration Plan

Both UI scripts and daemon entry points will import from `dashboard_modules` package:

*   **`dashboard.py` Responsibility:**
    *   Draw the Tkinter frames, labels, headers, and hardware logos.
    *   Manage Matplotlib figure canvas mounts and slide-rotation transitions (`rotate_slides`).
    *   Run the supervisor watchdog loop (`start_watchdog_loop`) to ensure background thread health.
    *   Delegate serial logging to `telemetry.py` and AI summaries to `ai.py`.

*   **`render_local_plot.py` Responsibility:**
    *   Mock GUI window container and local PNG/JPEG chart export.

*   **`stage_batch_summary.py` Responsibility:**
    *   Background daemon that imports `ai.py` and runs the scheduled cycle (`run_batch_cycle`).

---

## 5. Verification Plan

1.  **Phase 0.1: Build Modules & Stubs:** Create all files in `dashboard_modules/`.
2.  **Phase 0.2: Port Helper Tests:** Update `tests/test_signal.py` and `tests/test_parser.py` to import from `dashboard_modules` package. Verify existing tests pass:
    ```bash
    pytest tests/
    ```
3.  **Phase 0.3: UI Swap:** Replace monolithic logic in `dashboard.py`, `render_local_plot.py`, and `stage_batch_summary.py` with modular imports.
4.  **Phase 0.4: Visual Rendering Validation:** Run `./plot_and_open.sh` to confirm Slide 1 and Slide 2 visuals match the production layout precisely.
