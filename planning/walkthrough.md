# Walkthrough - Jetson Orin Edge AI Integration & Local Sync (v2.0)

This walkthrough documents the final achievements for integrating the Nvidia Jetson Orin Nano local inference endpoint with the Raspberry Pi dashboard GUI, aligning paths, resolving constraints, and automating deployments.

---

## 1. Accomplishments & Refactoring

### A. Google Python Style Guide Compliance
We updated [dashboard.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard.py) to meet strict code conventions:
1. **Sorted & Grouped Imports:** Moved all standard library and third-party imports to the top of the file, categorized, and sorted alphabetically.
2. **Soft Dependencies:** Wrapped optional GenAI and HTTPX libraries inside a clean `try/except` block to prevent startup crashes when runs are executed without local model setups.
3. **Docstring Coverage:** Enhanced the `GridDashboard` class docstring to include all missing class-level variables (e.g., `local_llm`, `solar_off`, `chilicon_off`), and added `Returns:` blocks to methods that return values (`chilicon_login`, `find_emu2_port`, `generate_hourly_summaries`).

### B. Local LLM Prompt Key Alignment & Pre-handling
1. **Key Mismatch Fix:** Aligned prompt template hydration with all placeholders expected by `gemma_prompt.txt` (`total_imported`, `total_exported`, `se_generated`, `inferred_chilicon`, `net_credit`, `peak_grid_import`, `peak_se_pv`, `home_consumption`, `day_date`), eliminating the `KeyError: 'inferred_chilicon'` crash.
2. **2B Parameter Model Constraints Handling:** Documented and implemented Python pre-calculations of aggregate telemetry statistics prior to formatting. This minimizes prompt token footprint (optimizing GPU memory on the Jetson Orin Nano) and eliminates arithmetic/numeric hallucinations to which small 2B models are prone.
3. **Timestamp Watermark:** Added the exact generation timestamp (`Generated: YYYY-MM-DD HH:MM:SS`) to the watermark metadata string drawn behind the graph.

### C. Cache Alignment & Sync Path Fixes
1. **Cache Destination Standard:** Modified `dashboard.py` to always write the summary JSON cache directly to the repository folder (`~/rainforest-emu2-grid-dashboard/gemini_summary.json`), bypassing the legacy root home directory fallback.
2. **Local LLM Cache Writing:** Added JSON disk-cache writing inside the native `--localllm` code path to match the behavior of the Vertex AI path.
3. **Mac Sync Script Alignment:** Updated [view_dashboard.sh](file:///Users/treven/view_dashboard.sh) on the Mac to copy active, real-time CSV logs and the `gemini_summary.json` file from the repository subdirectory on the Pi, correcting the discrepancy where it copied outdated files from `~/`.

### D. Development Automation & Security
1. **Redeploy Script:** Created [redeploy.sh](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/redeploy.sh) to execute unit tests, copy code and configs to the Pi over SCP, clear Pi caches, and restart the Tkinter dashboard process in one single CLI command.
2. **Security Scan:** Ran `gitleaks detect` on the repository history to verify that no developer keys, credentials, or utility account secrets were committed. All 34 commits are confirmed clean.

---

## 2. Verification & Testing

### A. Unit Tests (Pytest)
We ran the hermetic unit tests locally to verify compilation and logic. All 13 tests passed successfully:
```text
======================== 13 passed, 1 warning in 0.87s =========================
```

### B. Live Verification & Render Preview
* **Pi Kiosk Execution:** The kiosk screen now renders the live grid demand plot and overlays the local Jetson summary narrative watermark with the exact timestamp.
* **Mac Preview Sync:** Running `~/view_dashboard.sh` on the Mac now successfully fetches and screenshots the active sunset telemetry (`SolarEdge PV: 0.000 kW`) and displays the edge model metadata string:
  `[Edge Model: gemma2:2b | Generated: 2026-05-29 21:12:00 | Inference Time: 14.5s]`
