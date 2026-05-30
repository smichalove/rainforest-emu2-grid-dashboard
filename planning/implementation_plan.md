# Goal: Integrate Native Ollama Querying into Dashboard.py

I deeply apologize—I completely misinterpreted your architectural intent. I built a convoluted external decoupled stager system (`stage_local_summary.py`) when you simply wanted `dashboard.py` to handle the Jetson natively via an inline command-line argument, exactly how it already handles Vertex AI. 

We will keep the external local stager script (`stage_local_summary.py`) in Git for local developer emulation and testing so other contributors can emulate grid telemetry and local LLM caching loops without requiring physical EMU-2 hardware. Production environments will run the Jetson direct-query logic natively via `dashboard.py`'s internal threading system.

## Proposed Changes

### `dashboard.py`
- **[MODIFY]** Add `self.local_llm: bool = "--localllm" in sys.argv` to the `__init__` constructor.
- **[MODIFY]** Update `fetch_gemini_summary(self)`:
  - If `self.local_llm` is true:
    - Load `gemma_prompt.txt` instead of `gemini_prompt.txt`.
    - Format the context block using the local JSON structure (Total Net Imported, Net Energy Credit, Peak Grid Demand, etc.).
    - Fire a native Python `urllib.request.urlopen` HTTP POST directly to `os.getenv("OLLAMA_HOST")` (`http://192.168.8.68:11434/api/generate`).
    - Parse the JSON response, cache it (optional, just for UI recovery), and directly update the `summary_text_obj` via `self.after()`.

### `run_dashboard_system.sh` & `~/.config/autostart/grid-dashboard.desktop`
- **[PRESERVE]** Keep `stage_local_summary.py` in the repository for local developer emulation and testing.
- **[MODIFY]** Update the Pi's autostart script to simply launch the GUI natively: 
  `python3 dashboard.py --localllm`

### `README.md`
- **[MODIFY]** Add comprehensive Jetson Orin Nano / NV build & setup instructions:
  - Installing and running Ollama on Jetson.
  - Pulling the local LLM model (`gemma2:2b`).
  - Configuring `.env` with `OLLAMA_HOST` and `EDGE_MODEL` (using generic placeholders like `<jetson-ip>` and noting standard network/firewall security best practices for exposed endpoints).
  - Adding helper `curl` commands to easily verify connection and inference responses from the local model before running the GUI.
  - Documenting usage of the new `--localllm` CLI flag.

### Cleanup (Google Cloud)
- We will still execute the GCP storage cleanup (deleting Vertex AI Batch GCS buckets and IAM roles) as requested to ensure zero accidental cloud costs.

## Verification Plan
1. Run a `curl` query locally to verify connectivity and inference response from the Jetson Ollama endpoint.
2. Launch `python3 dashboard.py --localllm` locally on the Mac to ensure it successfully triggers the Jetson and updates the UI inline.
3. Deploy the modified `dashboard.py` to the Pi.
4. Reboot the Pi to trigger the native GUI loop with the new argument.
