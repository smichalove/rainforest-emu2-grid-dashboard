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

