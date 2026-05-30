# Native Dashboard Jetson Integration

- `[x]` Add `--localllm` flag to `sys.argv` parsing in `dashboard.py`
- `[x]` Add native Ollama HTTP POST execution to `fetch_gemini_summary()` in `dashboard.py`
- `[x]` Refactor imports to adhere to Google Python Style Guide
- `[x]` Clean up legacy stager scripts from the Pi (preserving stage_local_summary.py)
- `[x]` Deploy `dashboard.py` to the Pi and update `autostart` configuration
- `[x]` Update `README.md` with NV (Jetson Orin Nano) build and setup instructions (including verification curl examples)
- `[x]` Verify UI updates correctly natively on the Pi
