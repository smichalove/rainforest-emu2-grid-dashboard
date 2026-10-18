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
