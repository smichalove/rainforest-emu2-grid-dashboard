# Walkthrough - Resilient Kiosk GUI Performance Optimization

This walkthrough summarizes the diagnosis, implementation, and verification of the fix for the Raspberry Pi kiosk screen and time freeze.

---

## 1. Problem & Root Cause Analysis

* **Symptom**: The system clock, slide transitions, and user interface on the physical kiosk display froze completely, while the background serial thread continued to log parsed telemetry data every 15 seconds.
* **Root Cause**: The recent 14-day history and proposer-verifier edge AI update expanded the loaded telemetry history database query window from 24 hours to 14 days (increasing the size of lists like `self.usage` and `self.timestamps` in memory from ~5,760 to ~80,000+ points).
* **Saturation**: The Matplotlib chart rendering logic synchronously looped over all elements in memory to build line segments and SolarEdge/Chillicon dictionary lookups. This caused `canvas.draw()` to take **7.6 to 8.8 seconds** on the Raspberry Pi's CPU. Because the update loop (`fast_render_loop`) is scheduled every **2.0 seconds**, it saturated the single GUI thread with an infinite backlog of paint requests, locking up the clock and slide transitions.

---

## 2. Implemented Changes

We resolved this by implementing **Option 1: High-Performance Slicing & Downsampling**:

### GUI Code Optimizations
* **[dashboard.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard.py)**:
  * Relocated `now` and `start_time` calculations to the top of `update_chart()`.
  * Utilized `bisect.bisect_left` to find the start index of the active view window in $O(\log N)$ time, and sliced all copied lists (`usage_copy`, `timestamps_copy`, `se_timestamps_copy`, `chilicon_timestamps_copy`, `se_load_power_timestamps_copy`) prior to rendering.
  * Added integer stride downsampling for Slide 2 (14-day view) using slice steps (`[::stride]`) when data points exceed 10,000, limiting plotted elements to $\approx 5,000$ points.
  * Corrected Matplotlib `date2num` to execute only on the sliced subset of points.
* **[render_local_plot.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/render_local_plot.py)**:
  * Replicated the identical binary-search slicing and downsampling logic in the offline preview rendering loops.
  * Standardized Google-style compliant docstrings for both class `__init__` constructors.

### Documentation & Troubleshooting Reference
* **[logs.md](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/logs.md)**: Created a persistent log catalog across all nodes (Mac, Pi, Jetson) and documented this specific GUI freeze diagnostic case for future operator reference.
* **[agent.md](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/agent.md#L145-L148)**: Added a TIP guideline instructing developer agents to refer to the `logs.md` inventory.

---

## 3. Verification Results

### Automated Tests
* Verified the local unit test suite passes cleanly with zero regressions:
  ```bash
  ./venv/bin/pytest
  # Outcome: 46 passed, 2 skipped in 1.48s
  ```

### Rendering Performance
* Timed the offline screenshot generator locally to measure CPU savings:
  * **Before**: Took **14.69 seconds** total (7.2s active CPU rendering time).
  * **After**: Took **10.41 seconds** total (2.3s active CPU rendering time).
* Checked the Pi kiosk logs after rebooting:
  * Slide 1 canvas draw times dropped from **~7,690ms** to **~850ms**, leaving a safe **1.15-second idle margin** on every 2-second cycle.
  * The clock and slide rotations are now fully responsive and rotating smoothly in production.

---

## 4. UI Visual Previews

The sliced and downsampled charts render cleanly, maintaining full resolution visual lines and continuous boundaries:

````carousel
![Slide 1 - 24-Hour Plot](/Users/treven/.gemini/antigravity-ide/brain/080c87c6-4e21-48cb-af3e-f9ca2696da11/dashboard_preview_full.jpeg)
<!-- slide -->
![Slide 2 - 14-Day History](/Users/treven/.gemini/antigravity-ide/brain/080c87c6-4e21-48cb-af3e-f9ca2696da11/dashboard_preview_slide2_full.jpeg)
<!-- slide -->
![Slide 3 - DFT Frequency Domain](/Users/treven/.gemini/antigravity-ide/brain/080c87c6-4e21-48cb-af3e-f9ca2696da11/dashboard_preview_slide3_full.jpeg)
````

---

## 5. Local Telemetry Sync Tool & Automation

A dedicated script, `sync_db_to_mac.sh`, was created to pull active databases (`grid_history.db`) and CSV telemetry logs from the remote hosts down to the developer's Mac environment.

* **Primary Mode (Nvidia Jetson)**: Pulls data using direct `rsync` from the `/home/grid_backup/backups/` directory on `nvjetson`. It uses the default SSH username `steven` to utilize passwordless SSH key authentication and resolve permission/password prompt issues.
* **Fallback Mode (Raspberry Pi)**: Run with the `--pi` flag.
  1. Triggers a safe SQLite hot-backup on the Pi using `sqlite3` to dump a clean snapshot to a temporary directory (`/home/steven/rainforest-emu2-grid-dashboard/sync_temp/grid_history_mac.db`).
  2. Runs `rsync` to pull the safe database copy and all `.csv` files from the Pi down to the Mac.

### LaunchAgent Automation & macOS Sandbox Bypass
To automate database synchronization every 15 minutes without encountering macOS sandboxing permissions issues (which block background daemons from reading/writing in the protected `~/Documents/` directory):
1. **Un-sandboxed Directory**: A folder `/Users/treven/rainforest_db/` was created directly under the home folder, containing:
   * `sync_db_to_mac.sh`
   * The synced `grid_history.db` database.
   * Synced CSV files.
2. **Transparent Symlinks**: Symbolic links are created in the workspace directory (`/Users/treven/Documents/rainforest-emu2-grid-dashboard/`) pointing to the files in `/Users/treven/rainforest_db/`. The Python dashboard program reads/writes through these symlinks seamlessly.
3. **LaunchAgent Plist**: The file `com.treven.sync_db_to_mac.plist` is registered with the user launchd agent to invoke `/Users/treven/rainforest_db/sync_db_to_mac.sh` every 900 seconds.

### Usage & Automation Control
```bash
# Manual sync from Nvidia Jetson (default)
/Users/treven/rainforest_db/sync_db_to_mac.sh

# Manual fallback sync directly from the Raspberry Pi kiosk
/Users/treven/rainforest_db/sync_db_to_mac.sh --pi

# Load/Unload the background Launchctl Daemon
launchctl load ~/Library/LaunchAgents/com.treven.sync_db_to_mac.plist
launchctl unload ~/Library/LaunchAgents/com.treven.sync_db_to_mac.plist
```

