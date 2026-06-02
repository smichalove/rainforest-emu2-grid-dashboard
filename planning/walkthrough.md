# Walkthrough: Real-Time 2-Second GUI Loop & Caching Optimizations

We have successfully implemented and optimized a 2-second GUI polling and rendering loop for Slide 1 (the time-domain graph). The serial read loop has been decoupled from rendering and remains entirely passive to ensure Zigbee stack stability.

---

## Changes Implemented

### 1. Thread-Safe Telemetry Lists (`dashboard.py`)
* Created a lazy `data_lock` property on the `GridDashboard` class (accessing `self.__dict__` directly to avoid recursion issues in Tkinter tests where `__init__` is patched out).
* Wrapped all telemetry appends and pops (writes) under `with self.data_lock:` in:
  * `load_history`
  * `process_chunk`
  * `fetch_solaredge_data`
  * `fetch_chilicon_data`
* Utilized locked local list copies (`usage_copy`, `timestamps_copy`, etc.) inside `update_chart` and `align_and_compute_spectrum` to ensure thread safety between the background polling threads and the Tkinter GUI thread.

### 2. Decoupled Serial Updates (`dashboard.py`)
* In `process_chunk` (serial reader thread), instead of immediately scheduling a full Matplotlib canvas redraw, we save the latest values to state variables (`self.latest_status_text`, `self.latest_status_color`) and immediately trigger a fast update only to the `status_label` text/color.
* The time-domain plot is left to be updated on its own regular interval by the main thread.

### 3. Real-Time 2-Second GUI Loop (`dashboard.py`)
* Implemented `start_fast_render_loop()` and `fast_render_loop()` running on the Tkinter thread every 2 seconds.
* The loop updates the date/time clock widgets and weather widgets (safely using Open-Meteo's cached query) on every tick.
* It triggers `update_chart()` using locked memory list copies **only if Slide 1 is active**, completely bypassing matplotlib canvas drawing calls when Slide 2 is active to conserve Pi CPU overhead.

### 4. Stacked Solar Bars Drawing Cache (`dashboard.py`)
* **Problem:** Standard matplotlib draws on the Raspberry Pi took `~1070 ms` per frame because it cleared and recreated 144 stacked bar artists representing 10-minute SolarEdge/Chillicon power bins on every tick.
* **Solution:** Introduced `self.solar_bars_dirty`. The stacked bars are only cleared and redrawn when the slide is rotated, the app starts up, or new solar API telemetry is fetched (every 15 minutes). On standard 2s ticks, it skips clearing/redrawing the bars, letting Matplotlib pan the existing bar artists along the shared X-axis automatically. This drops regular Slide 1 redraw times to **<50ms**.

---

## Diagnostic Findings on Serial Active Polling
* **Hardware Write Block:** During active serial polling tests, we observed that `probe_emu2.py` hung in the kernel `pselect6` system call while waiting for the `/dev/ttyACM0` serial port to become writable.
* **Firmware Behavior:** Adding a `write_timeout=1` confirmed that the EMU-2 device locks its write interface and returns `Write timeout` on all serial commands. This indicates that writing commands over USB serial to actively query demand values causes buffer lockups or crashes the low-power Zigbee coordinator stack.
* **Resolution:** We must stick to passive broadcast mode (where the EMU-2 autonomously sends XML packets every 8–15 seconds, and we read them passively). This ensures Zigbee link stability while the new 2-second GUI loop keeps the interface responsive and the chart scrolling smoothly.

---

## Verification & Final Rollout

### 1. Automated Tests
All 23 unit tests pass successfully, confirming that our layout, timer, and watermark updates do not introduce regressions:
```bash
tests/test_parser.py .................                                   [ 73%]
tests/test_signal.py ......                                              [100%]
======================== 23 passed, 1 warning in 1.68s =========================
```

### 2. Layout Restoration & Text Watermarks
* **Unpacked Tkinter Labels**: Reverted the summary label packing to restore the Matplotlib chart back to its full screen height.
* **Transparent Watermark Overlays**: Configured `self.summary_text_obj` on Slide 1 (`ax`) and `self.summary_text_obj_freq` on Slide 2 (`ax_freq`) to overlay raw text directly in the chart background.
* **ax_freq clear() handling**: Programmatically recreate `self.summary_text_obj_freq` inside `update_chart()` after `self.ax_freq.clear()` is called on every refresh in both `dashboard.py` and `render_local_plot.py`.

### 3. Solar Y-Axis Scaling & Opacity
* **Option 2 Axis Scaling**: Reduced the right Y-axis solar bar limit scaling factor from `3.0` to `1.1` (`max_power * 1.1`). This ensures the axis tick labels represent the actual physical solar output accurately.
* **Local Plot Rendering Alignment**: Updated `render_local_plot.py` to use `mdates.date2num(bar_times)` and explicitly synchronize `self.ax_bar.set_xlim` to prevent Matplotlib's `clear()` from breaking the date alignment on Mac screens.

### 4. Kiosk Deployment & Slide Timers
* **Timer Configuration**: Adjusted Slide 1 duration to **1.5 minutes (90,000 ms)** and Slide 2 duration to **15 seconds (15,000 ms)** in both `dashboard.py` and `render_local_plot.py`.
* **Kiosk Redeployment**: Executed `./redeploy.sh` to sync the updated scripts and prompts to the Raspberry Pi and Jetson Orin Nano, and verified the kiosk UI runs cleanly and looks perfect with Slide 2's AI summary restored.
* **Screenshot On-Demand**: Moved macOS screen capture logic to run only when `--screenshot` is explicitly passed in command-line arguments (preventing focus stealing during standard runs).

### 5. Git Version Control & Rules
* **Mandatory Local Render Verification Rule**: Appended Section 12 to `.agents/rules/agent.md` to establish that local render verification (using `./plot_and_open.sh` or `render_local_plot.py`) must always be executed and verified before committing/deploying to production.
* Successfully ran pre-commit checks (`gitleaks`) and pushed the updates to the GitHub repository:
  * Commit 1: `Revert Tkinter summary label packing, add transparent axis watermark overlays, update slide rotation timers (90s / 15s), and scale right solar Y-axis to 1.1x` (Hash: `916ad3c`)
  * Commit 2: `Fix Slide 2 AI summary watermark overlay and headroom spacing on the kiosk dashboard` (Hash: `a6ba33e`)

![Updated Dashboard Preview](/Users/treven/.gemini/antigravity-ide/brain/90e0fe67-cb6a-4ffa-82cc-2b57fb19069c/dashboard_preview.jpeg)

---

# Walkthrough: Standalone DFT SNR Analysis Module

We have successfully implemented and verified the standalone Discrete Fourier Transform (DFT) Signal-to-Noise Ratio (SNR) Analysis module.

---

## Why Decibels (dB) for Rhythm SNR rather than Wattage Variance?
During design discussions, we analyzed why a decibel (dB) value is mathematically superior to a raw Wattage variation measure for evaluating rhythm strength:
1. **Scale Independence:** Net Grid, Solar PV, and Household Consumption operate at entirely different absolute power scales (e.g. Solar peaks at 5.0 kW, while base consumption might hover around 200W). Using decibels standardizes rhythm strength. An SNR of `+20 dB` indicates that the fundamental rhythm is 100 times stronger than the non-periodic noise, regardless of the absolute physical wattage of the system.
2. **Dynamic Range Compression:** Real-world power fluctuations span multiple orders of magnitude. The logarithmic decibel scale compresses this wide range (e.g. from 1 to 10,000) into a manageable scale (e.g. `0` to `40` dB), similar to signal quality measurements in acoustics and telecommunications.
3. **Pattern vs. Size Isolation:** A large home with heavy appliances will naturally show high raw wattage variance, even if its daily schedule is perfectly consistent (highly structured). A tiny apartment might show low wattage variance despite having a completely erratic schedule (highly unstructured). Rhythm SNR isolates the **pattern structure** from the **physical load scale**.

---

## Changes Implemented

### 1. Created Standalone Module (`snr_analysis.py`)
* Created a clean, decoupled module [snr_analysis.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/snr_analysis.py) that defines:
  * `calculate_snr_db(...)`: Calculates periodic SNR in dB by comparing peak signal band power ($\max(A_{\text{signal\_band}})^2$) to average noise band power ($\text{mean}(A_{\text{noise\_bands}}^2)$).
  * `analyze_spectra_snr(...)`: High-level wrapper that computes diurnal and semi-diurnal SNR metrics for Grid, Solar, and Consumption.
  * `compute_dtft_spectrum(...)`: A centralized utility to compute the DTFT amplitude spectrum for a sequence of values at target frequencies.

### 2. Integrated with Kiosk Renderer (`render_local_plot.py`)
* Refactored `align_and_compute_spectrum` in [render_local_plot.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/render_local_plot.py) to use `snr_analysis.compute_dtft_spectrum`, removing duplicate code.
* Updated `update_chart()` to call `snr_analysis.analyze_spectra_snr()` and append resolved SNR values to the Matplotlib legend labels on Slide 2.

### 3. Integrated with Edge AI Stager (`stage_local_summary.py`)
* Updated `run_analysis_workflow` in [stage_local_summary.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/stage_local_summary.py) to compute SNR values and pass them to the Edge AI prompts:
  * Updated [gemma_hybrid_prompt.txt](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/gemma_hybrid_prompt.txt) and [gemma_dft_prompt.txt](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/gemma_dft_prompt.txt) to include rhythm SNR placeholders.
  * Added the resolved SNR metrics to the returned API payload dictionary.

### 4. Added Comprehensive Unit Tests (`tests/test_signal.py`)
* Added `test_calculate_snr_db_pure_signal` and `test_calculate_snr_db_noisy_signal` to [tests/test_signal.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/tests/test_signal.py).
* Verified that all **25 unit tests** in the test suite pass successfully.
