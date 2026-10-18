# Persistent Rules for Antigravity

- **Network Configuration & Credential Security Restrictions:**
  > [!IMPORTANT]
  > *   Never write to, modify, or rewrite router network configurations, DNS settings, DHCP client/server leases, or wireless interface settings without explicit user permission.
  > *   **Do not remove or bypass the `Block_KVM_All_Forwarding` firewall rule** on the gateway router (`192.168.8.1`) for the KVM device (`12:35:2A:B1:F3:C8` / `192.168.8.204`). This device contains active phone-home reverse-proxy backdoors to Tencent Cloud and must remain completely isolated from the WAN.
  > *   **Do not remove or bypass the `Block_8_81_IP_Forwarding` or `Block_MacM1Pro_MAC_Forwarding` firewall rules** on the gateway router (`192.168.8.1`) for `mac-m1-pro` (`f8:e4:3b:c7:1e:e7` / `192.168.8.81`). This host is permanently quarantined from outbound WAN/Internet access and is strictly confined to intra-LAN cluster communication.
  > *   **Never store or write plain-text passwords** or sensitive system credentials in any markdown (`.md`) or documentation files in this repository.

- **Startup Context & Topology Awareness:**
  > [!IMPORTANT]
  > At the very start of every session, task, or after a system restart, the agent MUST immediately read this `AGENTS.md` file and the `server_topology.md` (or `topology.md`) file in the workspace to establish full context about hostnames, IPs, SSH credentials, and system rules. Do not guess credentials or ask the user for context already documented in these files.

- **System OS Migration & Cloning Rules (Postmortem - 2026-07-25):**
  > [!IMPORTANT]
  > *   **Private Mount Propagation:** When bind-mounting host virtual directories (like `/dev`, `/sys`, `/proc`, `/run`) into a target directory for a chroot, always set mount propagation to private (e.g. `mount --make-rprivate /mnt/target` or `mount --make-private`) immediately after mounting the target root. This prevents unmount commands inside the target from propagating back to the host, which unmounts the host's `/dev/pts` and crashes the active terminal session.
  > *   **Rebuild Initramfs:** Whenever a boot filesystem UUID changes or `/etc/fstab` is modified on a new boot drive, the kernel's initial RAM-disk must be rebuilt natively using `sudo update-initramfs -u -k all` before swapping hardware. Failing to do so causes the boot process to use cached, out-of-date fstab UUID entries (like old EFI partition mappings), causing boot-hangs and dropping the host to emergency mode.
  > *   **Root Privilege Queries:** Always execute `blkid` and similar hardware/partition query utilities with root/sudo permissions. Running them as a standard user returns blank parameters, which will corrupt configuration generation templates.

---

# Post-Mortem: Gemma 2 to Gemma 4 Edge Model Upgrades (Session 2026-07-25)

### 1. Legacy Model Hardcoding Mismatches
* **Failure:** Setup scripts (`setup_orin_local_llm.sh`), emulation scripts (`emulate_hybrid_stager.py`), and test mocks (`tests/test_parser.py`) were hardcoded to download, query, or mock `gemma2:2b`. This conflicted with the active edge stager configuration in `stage_local_summary.py` which defaulted to `gemma4-it-q4`, causing model configuration inconsistencies.
* **Resolution:** Upgraded all hardcoded references to target `gemma4-it-q4` (Instruct) and `gemma4-vision-q4` (Vision) models. Verified that the entire `pytest` suite ran 100% green (57/57 tests passing).
* **WSL2 Compilation Verification:** Successfully triggered a custom script execution inside WSL2 on `i7office` to download base weights, compile the Modelfiles, and register both `gemma4-it-q4:latest` and `gemma4-vision-q4:latest` models locally.

---

# Post-Mortem: Chrome Remote Desktop Setup & Headless NVIDIA GPU Multi-Node Fixes (Session 2026-08-01)

### 1. Dual NVIDIA GPU vs. Xorg Dummy Driver Conflict (`xserver-xorg-video-dummy`)
* **Failure:** Installing `chrome-remote-desktop` automatically installs `xserver-xorg-video-dummy`. By default, Chrome Remote Desktop attempts to launch `/usr/lib/xorg/Xorg` with the dummy driver. On nodes equipped with NVIDIA GPUs (Tesla P40 / Quadro P1000), `Xorg` detects the PCI IDs (`10de:1cb1`) of the NVIDIA GPUs without an active display output driver configured, causing `Xorg` to fail to open listening sockets on display `:20`.
* **Resolution:** Set `CHROME_REMOTE_DESKTOP_USE_XVFB=1` in the systemd service environment drop-in (`/etc/systemd/system/chrome-remote-desktop@steven.service.d/override.conf`). This forces Chrome Remote Desktop to use `Xvfb` (Virtual Framebuffer), which operates completely independently of physical GPU display hardware.

### 2. Missing `localhost` Magic Cookie in Google's `xauth` Cookie Generator
* **Failure:** In `/opt/google/chrome-remote-desktop/chrome-remote-desktop` (line 1651), Google's startup code executes `xauth add :20 . \`mcookie\``. This only registers an X11 authorization cookie for `hostname/unix:20`. When `xdpyinfo` runs during the server readiness check, it connects over the UNIX domain socket and checks `~/.Xauthority` for a matching `localhost/unix:20` key. Because `localhost/unix:20` was absent, `xdpyinfo` returned exit code 1 (`unable to open display ":20"`), causing `_wait_for_x()` to fail and tear down the host after 30 seconds.
* **Resolution:** Patched line 1651 in Google's Python wrapper script to execute:
  `COOKIE=\`mcookie\`; xauth add :%d . $COOKIE; xauth add localhost/unix:%d . $COOKIE`
  This guarantees that `xauth` registers the magic cookie for both `:20` and `localhost/unix:20`.

### 3. Python 3 String Formatting Tuple Mismatch in `_launch_server`
* **Failure:** When modifying the `xauth` string in `/opt/google/chrome-remote-desktop/chrome-remote-desktop` to include two `%d` placeholders (`:%d` and `localhost/unix:%d`), passing a scalar variable `% display` threw `TypeError: not enough arguments for format string`, crashing the Python process on startup with status 1/FAILURE.
* **Resolution:** Updated the format string argument to pass a two-element tuple `% (display, display)`.

### 4. `gnome-session` Wayland Abort & Systemd Target Conflicts in Headless Mode
* **Failure:** `gnome-session` on Ubuntu 26.04 uses systemd user units (`gnome-session@ubuntu.target`) and defaults to Wayland when launched from TTY. When Chrome Remote Desktop executed `exec /etc/X11/Xsession` or `exec /usr/bin/gnome-session`, `gnome-session` aborted with `A graphical session is already running! (core dumped)` because a physical login session was already active on `tty2`.
* **Resolution:** Installed `xfce4-session` (`sudo apt install xfce4-session xfce4-panel xfce4-terminal -y`) and configured `~/.chrome-remote-desktop-session` to launch `exec xfce4-session`. `xfce4-session` runs cleanly in an isolated virtual framebuffer display, uses 0% idle CPU, and never conflicts with local GNOME or systemd user units.

---

# Post-Mortem: PurpleAir Integration & Kiosk Pi Node Deployment (Session 2026-08-13)

### 1. PurpleAir Outbound NAT & Setup AP Fallback
* **Failure:** PurpleAir sensor `67d1` (`f0:24:f9:c6:67:d1` / `192.168.10.241`) remained in setup AP mode because the `iot` firewall zone on the upstairs router (`192.168.8.1`) had MASQUERADE NAT disabled (`masq='0'`). Outbound HTTP uploads were emitted with private source IPs and dropped by the WAN, preventing the cloud handshake.
* **Resolution:** Executed `uci set firewall.@zone[4].masq='1'` and committed firewall rules on `192.168.8.1`. The sensor completed HTTP cloud handshakes (`100% success`) and shut off its setup AP broadcast.

### 2. Kiosk Node IP Target & Multi-Host Misconfiguration
* **Failure:** `~/.ssh/config` and `redeploy.sh` were hardcoded to point `Host rainforestpi` to `192.168.8.122`. The active physical kiosk display and VNC session was running on **`192.168.8.213`**. Deployments were restarting an offline/secondary node while a legacy August 9th process (`PID 1181`) held the display on `192.168.8.213`.
* **Resolution:** Corrected `~/.ssh/config` to point `rainforestpi` to `192.168.8.213`. Authorized `steven@Rainforestpi`'s public key in `/etc/dropbear/authorized_keys` on `192.168.8.1` for router proxying. Terminated stale processes and updated `redeploy.sh` with `pkill -f 'dashboard.py'`.

### 3. Header Widget Layout & Display Font Bounds
* **Failure:** Displaying the full string `Air Quality: AQI 76 (Moderate - 23.8 µg/m³)` on small touchscreen displays (`592x448` resolution) caused vertical and horizontal overflow, pushing the right-hand solar metrics off screen.
* **Resolution:** Compacted the AQI widget text to `AQI: 76 (Moderate)` and adjusted header font scaling from 32/14pt to 24/11pt with 1px padding, ensuring crisp rendering across all display resolutions.

---

# Post-Mortem: Rainforest EMU-2 Web Kiosk & Decoupled Architecture (Session 2026-08-15)

### 1. Dual-Pi Node Disambiguation (`192.168.8.213` vs `192.168.8.122`)
* **Failure:** Background telemetry sync on `520c` was initially pointed at `192.168.8.122`. `192.168.8.122` is the AYRE / iTACH audio power daemon Pi (`powerd.py`), which contained a stale copy of `grid_history.db` from August 13 and no solar CSVs. The active physical kiosk and EMU-2 serial logger runs on **`192.168.8.213`** (`Rainforestpi`).
* **Resolution:** Established SSH trust between `520c` (`192.168.8.181`), `len-big` (`192.168.8.51`), and `Rainforestpi` (`192.168.8.213`). Updated `PI_COLLECTOR_HOST = "192.168.8.213"` in `web/config.py`.

### 2. House Load Computation vs Direct SolarEdge Flow Meter
* **Failure:** The web dashboard initially estimated House Load using the energy conservation formula (`Net Grid + Total Solar + Battery`), which reported `4.651 kW` while the physical kiosk reported `1.890 kW` (a ~2.76 kW discrepancy).
* **Resolution:** Added direct parsing of `solaredge_flow_history.csv` (column index 2 `load_power`) to `web/db_reader.py` and `web/app.py`. The web frontend now displays the exact same consumption meter reading as the physical kiosk.

### 3. Battery "Cup Filling with Water" Negative Floor Mapping
* **Design:** Replicated the physical Matplotlib kiosk's battery visualization in Chart.js (`charts.js`). Battery State of Charge ($0–100\%$) is mathematically mapped into the negative quadrant ($-10.0$ to $0.0\text{ kW}$):
  `const batteryFill = (bat.soc_percent || []).map(soc => (parseFloat(soc || 0) * 0.1) - 10.0);`
  Configured `fill: { target: { value: -10.0 } }` with translucent blue shading (`rgba(30, 64, 175, 0.45)`) so the volume fills from the $-10.0\text{ kW}$ floor up to the zero baseline as the battery charges, avoiding positive-axis clutter.

### 4. Zero-CDN Offline Asset Vendoring
* **Design:** Bundled Chart.js v4.4.7 directly into `web/static/js/vendor/chart.umd.min.js`. All scripts and stylesheets are served locally from `520c`, enabling reliable offline rendering across air-gapped or isolated LAN subnets.

---

# Post-Mortem: macOS Apple Silicon Touch ID, iMessage Attestation & Password Invalidation (Session 2026-09-01)

### 1. Apple Account Password Change & Hardware Attestation Bottleneck
* **Trigger:** The Apple Account password was changed on August 29, 2026, invalidating all pre-existing master OAuth session tokens, refresh tokens, and CloudKit Keychains (CKKS) across local daemon sessions.
* **Failure:** Because third-party kernel extensions (`com.iboysoft.BitLockerVolume` and `com.paragon-software.filesystems.extfs`) required setting the host to **"Reduced Security"**, the standalone Messages app failed initial cryptographic hardware attestation challenges with Apple's servers (`akd: Attestation map does not contain the cert attestation` -> `AKAuthenticationError Code=-7034`), resulting in the red UI error *"An unknown error occurred"*.
* **Collateral Biometrics Failure:** Token invalidation and local keybag desynchronization crashed `securityd` and corrupted OpenDirectory user record mapping (`opendirectoryd: Code 4200`), causing `biometrickitd` to return `err:0x105 (userUUIDs: null)` and purge enrolled Touch ID fingerprint templates.
* **Resolution:** 
  1. Restarted directory and biometric daemons (`sudo killall biometrickitd opendirectoryd`).
  2. Purged stale biometric template caches (`bioutil -p` and `sudo bioutil -p -s`).
  3. Re-enrolled the primary fingerprint (`Finger 1`) in **System Settings -> Touch ID & Password**.
  4. Renewed the master Apple Account authentication token directly through **System Settings -> Apple Account** rather than the standalone Messages splash screen, re-establishing valid session tokens across all daemons.
* **Reference Runbook:** Documented complete diagnostic steps and recovery workflows in [`macos_touchid_troubleshooting_runbook.md`](file:///Users/treven/macos_touchid_troubleshooting_runbook.md).

---

# Post-Mortem: MDM-Managed Mac M1 Pro (8.81) WAN Isolation & Firewall Policy (Session 2026-09-02)

### 1. Host Quarantining & Traffic Containment
* **Objective:** Prevent `mac-m1-pro` (`192.168.8.81` / MAC `f8:e4:3b:c7:1e:e7`), an MDM-managed Apple Silicon node, from leaking telemetry, corporate VPN, or sending any outbound traffic outside the local network, while keeping its local inference API accessible to the cluster.
* **Resolution:** Configured two complementary firewall rules on the OpenWrt gateway router (`192.168.8.1`):
  1. `Block_8_81_IP_Forwarding`: Matches `src='lan'`, `dest='*'`, `src_ip='192.168.8.81'`, `target='REJECT'`.
  2. `Block_MacM1Pro_MAC_Forwarding`: Matches `src='lan'`, `dest='*'`, `src_mac='f8:e4:3b:c7:1e:e7'`, `target='REJECT'`.
* **Kernel & Architecture Verification:**
  * In iptables, both rules populate `zone_lan_forward` with `-j reject`, dropping any forwarded packet attempting to reach `wan`, `guest`, `iot`, or external zones.
  * Because intra-LAN traffic on `192.168.8.0/24` traverses the Linux bridge (`br-lan`) at Layer 2 and `net.bridge.bridge-nf-call-iptables = 0`, local cluster API calls (e.g. from `len-big` or `i7office` to `8.81` on port 8000) remain completely uninhibited (0.0% packet loss, ~3.6ms latency).
  * Confirmed that `Block_KVM_All_Forwarding` (`192.168.8.204`) was preserved untouched.

---

# Post-Mortem: Hybrid Weather & PurpleAir Sensor Temperature Integration (Session 2026-09-20)

### 1. Dual Temperature Telemetry & Header Layout
* **Requirement:** The dashboard header previously rendered only Open-Meteo API ambient temperature (`temperature_2m` in °C) and cloud cover. The user requested displaying the on-premise local temperature measured by the PurpleAir sensor (`192.168.10.241`) alongside the API forecast on the same line.
* **Resolution:** 
  * Extracted `temp_f` from `cached_purple_air` in [`dashboard.py`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard.py#L1126-L1139).
  * Appended the sensor reading using the format ` (Actual: <temp>°F)`, producing a unified header display: `18.9°C (Actual: 66°F) | Partly Cloudy`.
  * Added `self.last_valid_sensor_temp` state caching to prevent UI regressions to `"N/A"` during transient network or router proxy timeouts.
  * Connected `_apply_weather_update()` to trigger `self.update_weather_display()` immediately when background telemetry arrives.

### 2. Display Bounds & Typography Verification
* **Check:** Verified the kiosk's physical screen geometry on `rainforestpi` (`192.168.8.213`) using `DISPLAY=:0`. Confirmed native resolution is `1024x768` (well above the older 592px inner subframe bounds), ensuring zero horizontal overflow or collision with the right-column solar PV and grid metrics.
* **Deployment:** Synced updated `dashboard.py` to `steven@rainforestpi:~/rainforest-emu2-grid-dashboard/` and verified process restart with serial hardware lock on `/dev/ttyACM0`.

---

# System Architecture: Audio Power Management Pi (192.168.8.122) & Emporia Vue Telemetry (Session 2026-09-23)

### 1. Power Management Node Identity & Cluster Disambiguation
* **Host Identity:** `192.168.8.122` (`steven@raspberrypi`, static lease `iTACH_AYRE`, MAC `88:a2:9e:05:02:c2`).
* **Active Service:** Runs `/usr/bin/python3 /home/steven/iTACH_AYRE/powerd.py` continuously in the background (15-second evaluation loop).
* **Role Disambiguation:**
  * **`192.168.8.122` (`iTACH_AYRE`):** Dedicated audio power sequencing and thermal safety daemon (`powerd.py`).
  * **`192.168.8.213` (`Rainforestpi`):** Dedicated physical touchscreen kiosk display (`dashboard.py`) and Rainforest EMU-2 smart meter USB reader (`/dev/ttyACM0`).

### 2. Local Hardware vs. Cloud API Architecture
* **Local LAN Protocols (Zero Internet Dependency):**
  * **Global Caché iTach WF2IR/IP2IR (`192.168.8.125:4998`):** Raw TCP socket connection.
    * Port 2: Physical contact closure sensor querying `getstate,1:2` to track Anthem processor power state (`0` = OFF, `1` = ON).
    * Port 1: Infrared transmitter emitting 36kHz toggle pulses for Ayre V-1xe power amplifier.
    * Port 3: Infrared transmitter emitting discrete 38kHz ON / 36kHz OFF for Ayre AX-7 integrated amplifier.
  * **Global Caché iTach IP2CC (`192.168.8.128:4998`):** Raw TCP socket connection pulsing contact closure relay 1 (0.5s pause) for power sequencing.
  * **TP-Link Kasa Smart Plug (`192.168.8.36`):** Local asyncio TCP/KLAP protocol via `python-kasa` controlling equipment rack cooling fans.
  * **Music Server Wake-on-LAN:** UDP magic packets broadcast to `192.168.86.255` on Anthem power-up transition.
* **Cloud API (Emporia Vue Gen 2):**
  * **No Local API:** Factory stock Emporia Vue firmware possesses NO local HTTP/TCP endpoint or on-premise REST API.
  * **Authentication:** Queries AWS Cognito session tokens cached on disk in `Auth/emporia_tokens.json` via the `pyemvue` library.
  * **Thermal Safety Guard:** Monitors Channel 10 (`music room right main`, GID `100920`). If power draw exceeds 600.0 Watts during standalone amplifier playback (even with Anthem OFF), cooling fans remain ON.
  * **Fail-Safe Policy:** If Emporia cloud requests time out or fail, `powerd.py` strictly defaults fans to **ON** to prevent equipment rack thermal damage.

### 3. Full-Panel Circuit Telemetry & Smart Plug Enumeration
* **Batch Telemetry Capability:** A single batched call (`vue.get_device_list_usage`) with cached tokens retrieves real-time 1-second power draw across all electrical circuits and connected smart devices simultaneously:
  * **Main Electrical Panel (Vue Gen 2 - GID `100920`):**
    * `Channel 1,2,3`: Whole-Home 200A Mains
    * `Channel 1`: `1 family room -office`
    * `Channel 2`: `2 studio 2`
    * `Channel 3`: `3 master bathroom 3`
    * `Channel 4`: `4 garage 4`
    * `Channel 5`: `5 unknown`
    * `Channel 6 & 13`: `A/C`
    * `Channel 7`: `7 kitchen plugs`
    * `Channel 8`: `8 Kitchen 8 lights and plugs`
    * `Channel 9`: `9 furnace`
    * `Channel 10`: `music room right main` (Monitored by `powerd.py`)
    * `Channel 12`: `bedroom floor heat`
    * `Channel 15`: `dryer`
    * `Channel 16`: `16 music room`
  * **13 Connected Smart Plugs (Model `SSO001`):**
    * `music room fan dining room` (`448343`), `big-len UPS` (`455750`), `dining room fan` (`455754`), `kitchen tv` (`455763`), `bedroom ups` (`455768`), `MacBook` (`461168`), `zoo spotlight` (`463191`), `kettle emporia` (`466190`), `downstairs fan` (`466192`), `kitchen fan` (`482342`), `coffee maker light` (`482353`), `giga and lem` (`484653`), `avm 60` (`488187`).
* **Integration Asset:** Reusable client module is implemented in [`dashboard_modules/emporia_vue.py`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/emporia_vue.py) (`EmporiaVueClient`), ready for dashboard visualization on `520c` (`192.168.8.181:8000`).

---

# System Architecture: 14-Day ReAct Agent Loop, 16GB Apple Silicon Migration & Ollama Failover (Session 2026-10-09)

### 1. 14-Day Historical Analysis Upgrade (Slide 2)
* **Problem:** Slide 2 on the physical kiosk and web interface historically utilized single-shot completions with terse, robotic prompts (`gemma_history_prompt.txt` / `gemma_verify_history_prompt.txt`), resulting in dry mechanical metric regurgitations rather than an interactive diagnostic narrative.
* **Resolution:** Implemented `run_14day_agentic_history_loop()` in [`dashboard_modules/agent_loop.py`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/agent_loop.py) and wired it directly into the gRPC edge streaming pipeline ([`dashboard_modules/grpc_server.py`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/grpc_server.py)). The agent executes an interactive ReAct loop allowing up to 5 iterations of read-only SQLite tool calls (`query_db`) across `analysis_history` and `grid_history`.

### 2. Exploiting 16GB Unified Memory Headroom (M4 Mac Mini)
* **Context Expansion:** Migrated primary inference off constrained Jetson Orin Nano hardware to `Stevens-Mini-2` (`192.168.8.103:11434` - Apple M4 Mac Mini, 16GB Unified Memory). With `gemma4-it-q4:latest` consuming ~3.1 GB weights, over 12GB of unified RAM is available.
  * Increased `num_ctx` from 4,096 / 8,192 to **16,384** tokens across all stagers and clients.
  * Increased `num_predict` to **2,048** tokens with temperature set to `0.25`.
  * Expanded SQL query result truncation limit from 50 to **300** records.
* **Telemetry Matrix Pre-Injection:** `get_14day_daily_breakdown_table()` queries `analysis_history` to pre-populate a 14-day daily performance table directly into the prompt (Date, Day of Week, Net Import/Export, Solar PV, Battery Charge/Discharge, Peak kW, House Load, and ⚡ PSE Flex Event flags).
* **Diurnal & Seasonal Context Engine:** `get_seasonality_context()` dynamically computes Pacific Northwest solar elevation and daylight hours (e.g. October sunrise 07:18 / sunset 18:31, 11.2h daylight), pairing it with diurnal profiles (Morning Ramp, Midday Solar Soak, Evening Peak / Flex window, Overnight Baseload) to ground narratives in seasonal transitions.

### 3. Ollama Sequential Rotation & Tool-Call Reliability
* **Topology Rebalancing:**
  * **`mac-m3-max` (`192.168.8.31`):** Identified as running a non-standard Ollama service lacking reliable tool-calling support. Omitted from the ReAct tool-call rotation chain.
  * **Verified Standard Tool Endpoints:**
    1. `Stevens-Mini-2` (`192.168.8.103:11434` - Apple M4 Mac Mini 16GB, Primary)
    2. `mac-m1-max` (`192.168.8.22:11434` - Apple Silicon M1 Max 32GB, Secondary)
    3. `520c` (`192.168.8.181:11434` - Intel Xeon + RTX 4060 8GB, Tertiary)
    4. `ubunto-giga` (`192.168.8.193:11434` - Secondary GPU host, Auxiliary)
    5. `i7office` (`192.168.8.82:11434` - Windows host, Fallback)

### 4. Web Kiosk 3-Slide Mirror Alignment (`520c` @ `192.168.8.181:8000`)
* **Backend:** Updated `get_ai_summary()` in [`web/db_reader.py`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/web/db_reader.py) to return `history_explanation` for `slide=2` and `dft_explanation` for `slide=3`.
* **Frontend:** Updated [`web/static/index.html`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/web/static/index.html) and [`web/static/js/app.js`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/web/static/js/app.js) to render all 3 slides (Slide 1: 24h Time Domain, Slide 2: Zoom - 14-Day History, Slide 3: DFT Spectrum), matching the physical kiosk layout.

---

# System Architecture: Mobile Responsive UI Wrapper & Touch Controls (Session 2026-10-10)

### 1. Viewport Adaptation & Safe Area Insets
* **Problem:** Accessing the FastAPI web kiosk (`520c @ 192.168.8.181:8000`) on smartphones resulted in horizontal clipping, cramped 3-column headers, and unreadable AI text watermarks overlaying the charts.
* **Resolution:** Implemented CSS media queries (`@media (max-width: 768px)`) in [`web/static/css/dashboard.css`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/web/static/css/dashboard.css) and updated [`web/static/index.html`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/web/static/index.html) with `viewport-fit=cover`.
  * **Scrolling:** Enabled smooth vertical touch scrolling (`overflow-y: auto`, `-webkit-overflow-scrolling: touch`) while maintaining the fixed $100\text{vw} \times 100\text{vh}$ kiosk mode on screens $\ge 769\text{px}$.
  * **Header Layout:** Restructured the header into a clean mobile flow:
    1. Top row: Live Time, Date, Weather & AQI.
    2. Status line: Centered Net Grid Import/Export badge.
    3. Quick metrics: 3-column touch cards for SolarEdge PV, Chillicon PV, and House Load.

### 2. Dedicated AI Narrative Card & Chart Aspect Ratio
* **Decoupling Watermark from Canvas:** On desktop, the AI narrative renders as a floating watermark inside the chart. On mobile devices ($\le 768\text{px}$), the `.ai-watermark` container transforms into a dedicated glassmorphism card positioned beneath the chart canvas:
  * Features `background: rgba(15, 23, 42, 0.85)` with a cyan glowing border, backdrop blur (`12px`), and an `⚡ AI Microgrid Analyst` badge header.
  * Formatted with high-contrast text (`#f1f5f9`), 1.55 line-height, and word wrapping for comfortable reading on small screens.
* **Chart Height & Geometry Recalculation:** Configured canvas height to `280px` on mobile and hooked `switchSlide()` and `window.resize` listeners in [`web/static/js/app.js`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/web/static/js/app.js) to trigger `chart.resize()` on hidden slide transitions.

### 3. Thumb-Friendly Dock & Auto-Cycle Pause
* **Navigation Bar:** Fixed bottom touch dock (`padding-bottom: max(10px, env(safe-area-inset-bottom))`) with 44px minimum touch targets for Slide 1 (24h), Slide 2 (14d), and Slide 3 (DFT).
* **Pause/Resume Control:** Added `toggleAutoCycle()` on the countdown timer pill (`#timer-tag`) allowing users to tap the pill to freeze the auto-cycle while reading detailed AI narratives or inspecting charts.

---

# Post-Mortem: 520c Storage2 (8TB HDD) Bad Block Recovery & MergerFS/NFS Restoration (Session 2026-10-11)

### 1. Root Failure & Cascade Mechanics
* **Trigger:** Following a reboot of `520c` (`192.168.8.181`), its secondary storage brick `/dev/sdb1` (`/srv/nas/storage2`, Seagate 8TB BarraCuda `ST8000DM004-2CX1` on SATA port 7 / `ata7.00`) encountered physical media read failures (`UNC` uncorrectable errors / `Medium Error: Data synchronization mark error`) in the ext4 journal block cluster (`976812913–976813055`) and directory inode tables.
* **Kernel Disablement Cascade:** Boot-time `systemd-fsck` executed non-interactive `fsck.ext4 -a /dev/sdb1`. Repeated 28-second hardware timeouts triggered multiple SATA bus resets, causing the kernel's `libata` layer to give up and disable the port (`ata7.00: disable device`).
* **Cluster Impact:**
  * `srv-nas-storage2.mount` failed with status 4 (`UNEXPECTED INCONSISTENCY; RUN fsck MANUALLY`).
  * `mergerfs-music.service` failed its dependency requirement for `storage2`.
  * `nfs-server` was left exporting an empty underlying directory, causing remote Mac Mini clients (`Stevens-Mini-2` @ `192.168.8.103`) to report `Stale NFS file handle`.
  * The root filesystem temporarily reported 100% saturation because writes were diverted to unmounted directory roots.

### 2. Forensic Discovery & Deadlock Clearance
* **Deadlock Diagnosis:** Attempts to run interactive `sudo fsck.ext4 -y /dev/sdb1` returned `/dev/sdb1 is in use`. Investigation revealed systemd's background check (`PID 671: fsck.ext4 -a -C5 /dev/sdb1`) was holding an exclusive block device lock in uninterruptible disk-wait (`D`).
* **Deadlock Clearance:** Terminated the blocking background check (`sudo kill -9 671`).
* **Boot-Loop Prevention:** `/etc/fstab` had `<pass>` set to `2` on `storage2`. Updated `/etc/fstab` using `sudo sed -i 's/storage2 ext4 defaults,nofail 0 2/storage2 ext4 defaults,nofail 0 0/' /etc/fstab` so systemd will never trigger blocking, non-interactive checks during boot that cause the SATA controller to trip out.
* **Hardware Re-Arm:** Cleanly rebooted `520c` to reset the AHCI controller and re-establish the SATA link (`ata7: SATA link up 3.0 Gbps`).

### 3. Multi-Pass Filesystem Repair & Directory Salvage
* **Pass 1 (Journal Replay & Directory Inode Reconstruction):**
  * Executed `sudo fsck.ext4 -y /dev/sdb1`.
  * Replayed and committed journal transactions across bad blocks, moving past the defective sector into Pass 1.
  * Extensively reconstructed corrupted directory structures, fixing missing `.` and `..` references and repairing file type attributes across deep subdirectory trees (e.g. `/music/iTunes/iTunes Media/Home Videos`).
  * As designed in `ext4`, `e2fsck` saved modifications and safely halted with `storage2: ***** FILE SYSTEM WAS MODIFIED *****` upon hitting an unused group inode checksum boundary.
* **Pass 2 (Bitmap Finalization & Doubly-Allocated Inode Reconciliation):**
  * Unmounted the partially repaired volume and completed the final allocation bitmap reconciliation pass (`sudo fsck.ext4 -y /dev/sdb1`), clearing doubly-allocated inode errors.

### 4. Service Restoration & Migration Verification
* **Restoration:** Executed `sudo systemctl restart srv-nas-storage2.mount mergerfs-music.service nfs-server`.
* **Verification:** Confirmed both storage bricks mounted (`/srv/nas/storage2` 7.3TB total, 5.6TB free) and unified pool `/home/steven/music_pool` fully restored (**10TB total, 5.6TB free, 43% used**).
* **Write Capability:** Verified write capability with `mkdir -p /home/steven/music_pool/avid_distrution/art`.
* **Sync Resumption:** Successfully synchronized the entire Avid distribution release suite (`avid_distribution_tool.py`, `alblum_publish.md`, `all_album_lyrics.md`, artwork, and master audio). Confirmed the 4-worker rsync migration pipeline from Windows `i7office` (`192.168.8.82`) resumed writing high-res music collections into `storage2` at wire speed.

---

# System Architecture & Post-Mortem: JRiver Media Center 36 Edge Migration & High-Scale Root Playlist Restoration (Session 2026-10-12)

### 1. 8GB Jetson Orin Edge Memory Headroom vs. OOM Kills
* **Failure:** Ingesting and querying an enterprise-scale music library (100,000+ tracks) on an 8GB NVIDIA Jetson Orin Nano (`nvagent` @ `192.168.8.45`) using unconstrained MCWS search queries (`Files/Search?Query=[Media Type]=[Audio]&Action=JSON`) caused JRiver's internal C++ JSON serializer to allocate 14+ GB of virtual memory (`total-vm: 13941244kB`). The Linux kernel Out-Of-Memory (OOM) killer terminated `mediacenter36` mid-process.
* **Resolution:** Replaced bulk library dumps with targeted per-album queries (`[Album]="..."`) taking only ~34ms each. Combined this with local memoization (`album_cache` and `title_cache`), keeping Python client RAM consumption under 20MB and preventing JRiver memory ballooning. In addition, massive 18,000+ track smartlist query dumps (`JAZZ BLUS CHAT.mpl`) were filtered from standard playlist batches to protect real-time host stability.

### 2. SACD Virtual Track Indexing (`.iso;\d+`)
* **Failure:** Super Audio CD (SACD) tracks exist virtually within 2GB–4GB `.iso` disk image containers. Standard filesystem path matching fails because individual track files do not exist as discrete files on the NFS share.
* **Resolution:** Implemented Tier-1 pre-caching of all 8,677 SACD tracks via a single lightweight MCWS search query (`[File Type]=sacd,dsf,dff`) in 2.6 seconds. Extracted track regex mappings (`([^\x00\r\n\\/]+\.iso;\d+)`) to map virtual `.iso;track` URIs directly to JRiver database keys before evaluating playlists.

### 3. MCWS Security Architecture & Read-Only Guest Traps
* **Failure:** Even after setting user credentials in JRiver's GUI dialog, playlist modification calls (`Playlist/Clear`, `Playlist/AddFiles`, `Playlist/Create`) returned `HTTP Error 401: Access denied`.
* **Root Cause:** In JRiver's Media Network security model, if the master switch `Authenticate` is disabled (`Authenticate=i:"0"` in `~/.jriver/Media Center 36/Settings/User Settings.ini`), JRiver defaults all web service (MCWS) connections—even from `127.0.0.1` (localhost)—to Read-Only Guest status (`<Item Name="ReadOnly">1</Item>`).
* **Resolution:** Toggled `Authenticate=i:"1"` in `User Settings.ini` and restarted JRiver. Authenticating with configured credentials returned `<Item Name="ReadOnly">0</Item>` (Full Write Access), unlocking all modification endpoints.

### 4. Zero Sidebar Clutter In-Place Root Playlist Injection
* **Design:** Bypassed JRiver's native GUI `.mpl` file import, which pollutes the library tree by nesting all imported playlists into an unwanted `"Imported Playlists"` subfolder.
* **Execution:** Designed and executed a custom REST API engine ([`restore_master_playlists.py`](file:///home/steven/restore_master_playlists.py)) that creates playlists natively at the library root. Matched keys are injected in 100-track chunks with 10ms pacing to protect JRiver's SQLite/database commit loop and maintain continuous ALSA audio streaming buffers.
* **Ingestion Benchmark:** Evaluated 132 canonical `.mpl` playlist blueprints from the NAS (`/mnt/520c/music/playlists/`) encompassing 53,144 tracks. Successfully resolved and injected **52,965 tracks (99.7% match rate)** into root playlists with zero sidebar clutter.

### 5. High-Resolution Audio Buffer Protection (Ayre QB-9 Twenty)
* **Audio Buffer Tuning:** `nvagent` streams bit-perfect DSD128 (DoP) at 352.8 kHz to the Ayre QB-9 Twenty DAC.
* **Configuration:** Tuned with a 400ms ALSA hardware buffer and 2.0s secondary JRiver pre-buffering. Paced background MCWS REST operations ensure 0% CPU starvation, preventing ALSA buffer underruns (XRUNs) during active playback.

---

# System Architecture: Web Kiosk Universal Card Layout, Time-Grid Alignment & GL-RM1 KVM (Session 2026-10-17)

### 1. GL.iNet Comet (GL-RM1) Remote KVM Deployment
* **Host Identity:** `192.168.8.178` (`glkvm`, MAC `94:83:c4:72:88:b6`), Tailscale IP `100.65.68.120`.
* **TLS & Local CA:** Generated a 10-year local Root CA (`~/glkvm-certs/glkvm-rootCA.crt`, trusted in macOS System Keychain) and signed a SAN TLS certificate covering `glkvm`, `glkvm.local`, `192.168.8.178`, and `100.65.68.120`, installed into `/etc/kvmd/user/ssl/` on the KVM.

### 2. Universal Card-Based Web Kiosk Presentation (`520c` @ `192.168.8.181:8000`)
* **Layout Unification:** Promoted the responsive card-based presentation in [`web/static/css/dashboard.css`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/web/static/css/dashboard.css) to be the universal default across all desktop and mobile browsers (`max-width: 1280px` centered container, 3-column metric cards, dedicated glassmorphism AI narrative card below the chart canvas, and fixed bottom slide navigation dock).
* **24h & 14d Time-Grid Alignment (`web/db_reader.py`):**
  * Fixed SQLite timestamp string comparison in `get_24h_time_domain()` by formatting `cutoff_str` with an ISO `'T'` separator (`%Y-%m-%dT%H:%M:%S`), restoring full 24-hour `grid_history` retrieval.
  * Implemented `_interp_to_grid()` to project asynchronous series (`grid_history`, `solaredge_history.csv`, `chilicon_history.csv`, `solaredge_battery_history.csv`) onto a uniform 5-minute time grid up to the current timestamp.
  * Computed physical energy-balance **House Load** (`max(0.0, Net Grid + SolarEdge PV + Chillicon PV + Battery Discharge - Battery Charge)`) across both live metrics and historical series, and stacked SolarEdge + Chillicon PV generation bars in [`web/static/js/charts.js`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/web/static/js/charts.js).
  * Restored PurpleAir local ambient temperature `(Actual: XX°F)` alongside the Open-Meteo forecast in [`web/static/js/app.js`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/web/static/js/app.js).

---

# System Architecture: Chilicon CP-100 Gateway (`192.168.8.135`) & Local UDP `32758` Telemetry Protocol (Session 2026-10-17)

> [!CAUTION]
> **`(agent crumb)` — PUBLIC REPOSITORY SANITIZATION REQUIRED:**  
> All concrete LAN IP addresses (`192.168.8.1`, `192.168.8.135`, `192.168.8.181`, `192.168.8.213`), hardware MAC addresses (`88:da:1a:83:e1:21`, `94:83:c4:72:88:b6`), Chilicon Gateway serial numbers (`C14119`), Microinverter `EUI32` hardware IDs (`11700218`, `C1500871`, etc.), and PostgreSQL credentials/DSNs in this section and in `chilicon_udp_telemetry_design.md` / `chilicon_udp_listener.py` are **strictly private cluster context**.  
> Whenever syncing or copying code/docs to the public staging repository (`/Users/treven/rainforest-emu2-grid-dashboard-public`), **MUST sanitize** these values to generic placeholders (`<router-ip>`, `<gateway-ip>`, `<postgres-host>`, `<gateway-serial>`, `CHILICON_PG_DSN` via `.env` / `Auth/`).

### 1. Gateway Hardware Identity & Network Behavior
* **Host Identity:** `192.168.8.135` (DHCP hostname `Chilicon-C14119-WI`, MAC `88:da:1a:83:e1:21`, Gateway Serial/ID **`C14119`**, Firmware **`CHILIC0N Gateway v4882`**).
* **Inbound Ports:** **0 open TCP/UDP ports** on LAN (runs bare-metal RTOS + `lwIP` stack with no local listening HTTP server).
* **Physical Developer Menu:** Accessed on the gateway touchscreen via `Menu` ➔ `Setting Screen` ➔ hidden button in the **very top-left corner** ➔ password recorded in official Chilicon Gateway Visual User Manual. Shows `UDP Info Dump Port: 32758` under `Settings` and `Info Dump` (`udpTxPayloadCount`) under `OOK Menu`.
* **Two Unencrypted Outbound Traffic Streams to `cloud.chiliconpower.com` (`107.155.107.6`):**
  1. **5-Second Command Poll (`TCP :80`):**
     Plaintext HTTP `GET /files/C14119/command HTTP/1.1` (`Host: cloud.chiliconpower.com:80`, `User-Agent: CHILIC0N Gateway v4882`). Server replies `HTTP/1.1 200 OK` with 1-byte `application/octet-stream` body (`0x00` = no command queued).
  2. **176-Second (~2.9 Min) Telemetry Push (`UDP :32758`):**
     Unencrypted, fire-and-forget (`[UNREPLIED]`) UDP datagram from `192.168.8.135:65452` ➔ `107.155.107.6:32758` (`1,400` bytes IP / **`1,372` bytes UDP payload**). **100% of solar production telemetry is transmitted in this UDP `32758` packet.**

### 2. Reverse-Engineered UDP `32758` Binary Frame Specification (`1,372 Bytes`)
Each 1,372-byte UDP payload contains two complete ~90-second Power Line Communication (PLC) polling sweeps across all **8 bound CP-720 Dual-MPPT microinverters**:

| Byte Offset | Size | Type | Description |
| :--- | :--- | :--- | :--- |
| `0..7` | `8 B` | `<II` | **Gateway Header:** `19 41 c1 00 00 00 00 00` (`0x00C14119` = Gateway Serial `C14119`, `0x00000000`) |
| `8..687` | `680 B` | `8 × 85 B` | **PLC Sweep 1:** 85-byte telemetry struct for each of the 8 microinverters (~90s prior) |
| `688..1367` | `680 B` | `8 × 85 B` | **PLC Sweep 2:** 85-byte telemetry struct for each of the 8 microinverters (current sweep) |
| `1368..1371` | `4 B` | `<I` | **Frame Trailer:** 32-bit CRC checksum |

### 3. Bound CP-720 Microinverter Roster & 85-Byte Telemetry Struct
* **8 Bound Microinverters (in array order `0..7`):**
  `0`: `11700218` | `1`: `C1500871` | `2`: `C1400025` | `3`: `B14009F7` | `4`: `C140032A` | `5`: `B15003B2` | `6`: `B160012D` | `7`: `617005FE`
* **Per-Inverter 85-Byte Record Layout (`rec[0..84]`, Little-Endian):**
  * `rec[0:4]` (`<I`): Microinverter 32-bit Hardware ID (`EUI32`, e.g. `0x11700218`).
  * `rec[4:8]` (`<I`): **Poll Timestamp** in seconds since `2000-01-01 00:00:00` local time (`datetime(2000, 1, 1) + timedelta(seconds=ts)`).
  * `rec[8]` (`uint8`): Record subtype (`0x26` on normal dual-channel records; `0x22` on `C1500871`).
  * `rec[20:24]` (`<I`) & `rec[32:36]` (`<I`): Dual-MPPT DC Channel 1 & DC Channel 2 accumulators.
  * `rec[24:26]` (`<H`): **AC Grid Voltage** in `Q12.4` fixed-point (`val / 16.0` = **`~242.5V–245.5V AC`**).
  * `rec[26:28]` (`<H`) & `rec[34:36]` (`<H`): Dual-MPPT DC1 & DC2 current/power readings (`11700218`, `B160012D`, `617005FE` active on DC1; `C1400025`, `B14009F7`, `C140032A`, `B15003B2` active on both DC1 & DC2; `C1500871` low/shaded on DC2).
  * `rec[44:46]` (`<H`): Instantaneous per-inverter AC power index (~Watts).
  * `rec[68:72]` (`<I`): Monotonic **Inverter Operating Uptime Counter** (`0.125 ticks/sec` per inverter = `1.000 tick/sec` across all 8 inverters).
  * `rec[72:76]` (`<I`): Monotonic **Lifetime AC Energy Counter** per inverter:
    * Scale factor: **`55,102.86185 ticks / kWh`** (`= 55.10286 ticks / Wh = 15.30635 ticks / Watt-second`).
    * **Lifetime Energy (kWh):** `sum(u32_72) / 55102.86185` (matches Chilicon Cloud `24,058.375 kWh`).
    * **Real-Time AC Power (Watts) per 90s Sweep:** For each inverter $i$, $P_i = \frac{\text{u32\_72}_{i,t_2} - \text{u32\_72}_{i,t_1}}{(t_{2,i} - t_{1,i}) \times 0.01530635}$.

### 4. Deployed Router UDP `32758` Debug Bridge Rebroadcaster & Dual-Node Ingestion
* **Flint 2 Router Service (`root@192.168.8.1`):**
  * Managed by OpenWrt `procd` via `/etc/init.d/chilicon-rebroadcast`, `/usr/bin/chilicon_rebroadcast_runner.sh`, and `/usr/bin/chilicon_rebroadcast.lua` (documented on-router at `/root/AGENTS.md`).
  * Passively captures outbound 1,372-byte UDP `32758` frames from `192.168.8.135` on `br-lan` (`tcpdump -i br-lan -l -nn -xx "src host 192.168.8.135 and udp dst port 32758"`) and rebroadcasts identical 1,372-byte raw UDP payloads to:
    * `192.168.8.181:32758` (`520c` PostgreSQL & Web Kiosk server)
    * `192.168.8.213:32758` (`Rainforestpi` Physical Kiosk & Telemetry Collector)
    * `192.168.8.255:32758` (Subnet broadcast)
* **`520c` PostgreSQL & Web Kiosk Listener (`192.168.8.181`):**
  * Dedicated PostgreSQL database `energy_telemetry` (`chilicon_inverter_samples` for per-panel 90s diagnostics + `chilicon_system_history` for rolled-up system kW/kWh).
  * Runs [`chilicon_udp_listener.py`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/chilicon_udp_listener.py) to persist both 90-second sweeps to PostgreSQL and append to `data/chilicon_history.csv`.
* **`Rainforestpi` Edge Listener & Measured ARM Performance (`192.168.8.213`):**
  * Launched automatically via [`run_dashboard_system.sh`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/run_dashboard_system.sh) and synced via [`redeploy.sh`](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/redeploy.sh).
  * Runs in lightweight CSV-only edge mode when `psycopg2` is absent, appending directly to `/home/steven/rainforest-emu2-grid-dashboard/chilicon_history.csv`.
  * **Measured Pi ARM Cortex-A72 Benchmark:** Decodes 1,000 sweeps (`8,000` inverter records) in `135.08 ms` (**`270 µs` per 1,372-byte UDP packet** = **`0.00015%` CPU duty cycle** at the 176s gateway interval, **`13.2 MB` RSS** / `0.7%` RAM, `0%` idle CPU while blocked on `sock.recvfrom()`).

### 5. Microinverter Off-State, Dawn Transition & Nighttime Watchdog Safeguards
* **Dusk & Off-State Stagnation Decay ($\Delta t = 0 \to 0.0\text{ W}$):**
  * When solar irradiance drops below the microinverter operating threshold (~22V DC), the CP-720 DSP shuts down. The CP-100 gateway continues polling internal slots, but the uncontacted inverter's timestamp `ts_sec` stops advancing.
  * In `chilicon_udp_listener.py`, whenever $\Delta t = 0$ between sweeps or consecutive packets, `power_w` is immediately forced to **`0.0 W`**. This prevents the critical failure mode where stale positive daytime generation persists in memory overnight.
* **Dawn Cold Wake-Up Guard ($\Delta t > 900\text{s}$ Anti-Spike Filter):**
  * When panels re-energize after 8–10 hours of darkness, an inverter's first response reports a timestamp delta $\Delta t \approx 28,800\text{s}$. Calculating $\Delta E / \Delta t$ across that gap yields math errors or transient power spikes.
  * Any interval $\Delta t > 900\text{s}$ (15 minutes) is categorized as a cold wake-up: `power_w` is seeded at `0.0 W`, the baseline accumulator is re-armed, and true $dE/dt$ generation commences cleanly on the subsequent sweep 90 seconds later.
* **Overnight Silence Heartbeat Watchdog:**
  * During deep night hours (21:00–06:00), the CP-100 gateway may throttle or halt UDP debug broadcasts altogether.
  * A dedicated background thread monitors elapsed silence. If no UDP packet arrives for $> 10$ minutes at night:
    1. Sets all active inverters to `0.0 W` in memory.
    2. Writes a synthetic heartbeat row (`power_kw = 0.000`, `active_inverters = 0`) to PostgreSQL (`chilicon_system_history`).
    3. Atomically appends a `(timestamp, 0.000, lifetime_kwh)` row to `chilicon_history.csv` every 15 minutes.
  * Ensures the Web Kiosk and physical display maintain continuous, gap-free zero baselines through midnight without UI flatlines.

### 6. Kiosk Client Priority & Cloud Scraper Fallback Guard (`dashboard_modules/solar.py`)
* **Local UDP Telemetry Priority:**
  * In `ChilliconClient.fetch_data()`, the client inspects `chilicon_history.csv` before making outbound HTTPS requests to `cloud.chiliconpower.com`.
  * If a fresh sample exists written within the last 360 seconds (6 minutes), the client directly returns `(power_kw, energy_wh, timestamp)`, preventing delayed 67-minute cloud scrapes from overwriting live 90-second local UDP data.
* **Sunset Cloud Bucket Guard:**
  * If the cloud API returns `power_kw == 0.0` but contains historical 5-minute interval buckets in `parsed[0]`, the client previously fell back to the last non-negative bucket indefinitely.
  * Hardened the fallback: only fall back to the last non-negative 5-minute bucket if it is recent ($\le 3\text{ buckets} / 15\text{ minutes}$ old). If the last non-negative bucket is older (e.g. from midday or pre-sunset), the client strictly preserves `0.000 kW`, preventing daytime solar from "sticking" after dusk.

### 7. Public Staging Sanitization Guidelines & Zero-Leak Guarantee
* When synchronizing or copying code/documentation to `/Users/treven/rainforest-emu2-grid-dashboard-public/`:
  * Never commit raw private fabric IPs (`192.168.8.x`), router MACs, Chilicon Gateway serials (`C14119`), or microinverter EUI32 hex identifiers (`11700218`, etc.).
  * Replace with placeholders: `<router-ip>`, `<gateway-ip>`, `<postgres-host>`, `<gateway-serial>`, or load them securely via `.env` / `Auth/` configuration files.
  * Do NOT run `build_public_staging.sh`; stage and verify modifications manually.


