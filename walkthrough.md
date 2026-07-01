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

---

## 6. Kiosk HDMI Display Mirroring & noVNC Keepalives

### Display Mirroring Configuration
* **Problem**: After a Raspberry Pi reboot, the dual HDMI kiosk monitors defaulted to an extended desktop layout. The hardcoded `xrandr --output HDMI-2 ... --same-as HDMI-1` command failed silently on boot because modern kernels assign dynamic names to HDMI outputs (e.g. `HDMI-A-1/2` or `HDMI-0/1`), causing the rainforest telemetry widget to be clipped off-screen.
* **Resolution**: 
  1. Replaced the hardcoded outputs in [run_dashboard_system.sh](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/run_dashboard_system.sh) with a dynamic auto-detection block that parses `xrandr` outputs and automatically mirrors whatever connected screens are found.
  2. Diagnosed network timeouts between the Mac and Pi as a dynamic bridge/hardware flow-offloading lockup on the downstairs router (`Flint2_downstairs`). Rebooted the downstairs router, restoring direct network connectivity and allowing the Mac to sync database files directly.
  3. Reverted the temporary SSH/SCP `ProxyJump` tunnels in [redeploy.sh](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/redeploy.sh) to keep the production deployment pipeline direct and clean.
  4. Fixed a sorting comparison mismatch in [tests/test_daily_summary_query.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/tests/test_daily_summary_query.py) by checking for exact expected daily counts.
  5. Successfully redeployed, terminating duplicate Tkinter processes and starting a single, correctly-mirrored instance of the dashboard.


### noVNC Timeout & Keepalive (Heartbeats - Reverted)
* **Problem**: Inactive browser sessions using the HTML-based noVNC proxy disconnected frequently and forced users to manually re-login because browser tab suspension and default socket inactivity drop idle WebSocket connections.
* **Attempted Resolution**:
  1. Modified `/etc/systemd/system/novnc-websockify.service` on the Pi to add `--heartbeat 15` in `ExecStart`.
  2. Reloaded systemd (`systemctl daemon-reload`) and restarted the service (`systemctl restart novnc-websockify`).
* **Reversion**: The heartbeat configuration made the connection unreliable and caused disconnection issues. The service configuration has been completely reverted to its original state (removing the `--heartbeat 15` parameter), systemd has been reloaded, and the `novnc-websockify` service restarted to restore the baseline VNC setup.

---

## 7. System Prompt Table Constraint Optimization & Edge AI Annotations Fix

### System Prompt Enhancements
* **[repl_system_prompt.txt](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/repl_system_prompt.txt)**:
  * Removed the restriction limiting sub-hourly/minute-level queries to `grid_history` only, enabling the model to target any high-resolution tables (like `solaredge_flow_history` for household load).
  * Documented that the dashboard **white line** represents the household load / consumption (Appliance Load).
  * Added clear instructions regarding the database naive ISO standard `'T'` separator vs. space-separated references (e.g., converting `{current_time}` space-separated strings to `'T'` strings in comparisons to avoid returning zero rows).
  * Documented the SolarEdge API latency of 1 to 4 hours compared to the real-time (15-second update) nature of the smart meter `grid_history`.
* **[gemma_agent_prompt.txt](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/gemma_agent_prompt.txt)**:
  * Synchronized the critical warning guidelines, including the "white line is house load" definition, the SQLite naive ISO standard `'T'` separator warning, the Watt-to-kW unit scaling warning, battery Flex Event detection mathematical indicators (`delta_bat_discharge > 0.1`), and the SolarEdge API latency details. This ensures the autonomous anomaly diagnostics agent has identical constraints to the interactive REPL client.

### Annotations Window Filtering Fix
* **[stage_local_summary.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/stage_local_summary.py)**:
  * Modified the annotation query filter to look at a relative sliding **48-hour window** from the current system time, instead of only checking since the baseline timestamp (`>= baseline_dt`). This prevents annotations from being completely hidden on baseline expiration/regeneration, ensuring the Edge AI daemon (`nvagent`) receives full user context.

### Verification & Redeployment
* Ran all 57 local unit tests successfully.
* Redeployed changes to the active Raspberry Pi kiosk and Jetson edge server via `./redeploy.sh`.
* Verified local plot rendering generates previews cleanly using `./plot_and_open.sh`.

---

## 8. Speedtest CLI Installation & Network Performance Audits

To measure local link throughput and diagnose any remaining LAN bottlenecks, we installed the official Speedtest by Ookla CLI (`aarch64`) on both GL.iNet Flint 2 routers.

### Installation
1. Pulled the statically linked `aarch64` `speedtest` binary from the Raspberry Pi kiosk (`/usr/bin/speedtest`).
2. Transferred it to the upstairs router (`192.168.8.1`) and downstairs router (`192.168.8.2`) under `/usr/bin/speedtest` using SCP (utilizing the `-O` legacy SCP protocol flag since Dropbear does not run SFTP).
3. Made the binaries executable via `chmod +x /usr/bin/speedtest`.

### Speedtest Audit Results

* **Upstairs Main Router (`192.168.8.1` / GL-MT6000)**:
  * **ISP**: Comcast Cable
  * **Latency**: 13.42 ms (jitter: 6.67ms)
  * **Download**: **1890.24 Mbps**
  * **Upload**: **331.96 Mbps**
  * **Packet Loss**: 0.5%
  * **Result Link**: [Result URL](https://www.speedtest.net/result/c/cb28bab2-e216-4f68-aace-b0ad5f2655f3)

* **Downstairs AP (`192.168.8.2` / Flint 2)**:
  * **ISP**: Comcast Cable
  * **Latency**: 18.03 ms (jitter: 0.77ms)
  * **Download**: **1964.53 Mbps**
  * **Upload**: **345.89 Mbps**
  * **Packet Loss**: 0.0%
  * **Result Link**: [Result URL](https://www.speedtest.net/result/c/d345c806-f30f-466d-aca0-d7b52d0176dd)

* **Key Observation**:
  * The physical ports on both routers are negotiating correctly at `2500` Mbps (2.5 Gbps).
  * The initial limit of ~926 Mbps on the downstairs AP was caused by a physical bridge switch downstairs that was supposed to be bypassed but was disconnected from power / incorrectly routed. Once this physical bridge issue was resolved, the speedtest download rate on the downstairs router reached **1,964.53 Mbps**, fully verifying the 2.5 Gbps backbone capacity.
  * Note that raw single-threaded `iperf3` tests between the two routers still report ~780-920 Mbps due to the single-core CPU overhead of running the local iperf network daemon on embedded hardware, whereas actual routed and bridged client data is accelerated via hardware offloading and runs at full line rate.

---

## 9. Local RAG Database Sync & Stale `analysis_history.db` Issue Resolution

### Problem & Discovery
During interactive REPL testing (`repl_client.py`), the local LLM agent returned inaccurate counts of PSE Flex events (e.g., returning 13 or 98 events instead of the actual count).
We diagnosed that the agent was querying a stale local copy of `analysis_history.db` on the Mac (`/Users/treven/Documents/rainforest-emu2-grid-dashboard/backups/analysis_history.db`), which had not been updated since June 24.
The active `sync_db_to_mac.sh` script did not include `analysis_history.db` in its `rsync` sync rules, causing the local RAG engine to query data from two days prior.

### Resolution
1. **[sync_db_to_mac.sh](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/sync_db_to_mac.sh)**: Added an explicit `rsync` rule to synchronize `/home/grid_backup/backups/analysis_history.db` from the Jetson node to `/Users/treven/rainforest_db/analysis_history.db` on the Mac.
2. **[repl_client.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/repl_client.py)**: Modified the database attachment logic in `query_db` to look for `analysis_history.db` in the un-sandboxed `SYNC_DIR` first (where the launchd daemon places synchronized files) before falling back to the project root directory.
3. **Execution**: Copied the updated script to `/Users/treven/rainforest_db/sync_db_to_mac.sh` and ran it manually. The database synchronized successfully at **32.70 MB/s**, resolving the stale database issue.







‹