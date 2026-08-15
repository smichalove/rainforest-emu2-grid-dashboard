# Persistent Rules for Antigravity

- **Network Configuration & Credential Security Restrictions:**
  > [!IMPORTANT]
  > *   Never write to, modify, or rewrite router network configurations, DNS settings, DHCP client/server leases, or wireless interface settings without explicit user permission.
  > *   **Do not remove or bypass the `Block_KVM_All_Forwarding` firewall rule** on the gateway router (`192.168.8.1`) for the KVM device (`12:35:2A:B1:F3:C8` / `192.168.8.204`). This device contains active phone-home reverse-proxy backdoors to Tencent Cloud and must remain completely isolated from the WAN.
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



