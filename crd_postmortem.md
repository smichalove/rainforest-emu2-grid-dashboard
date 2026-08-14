# Post-Mortem: Chrome Remote Desktop Setup & Headless NVIDIA GPU Multi-Node Fixes (Session 2026-08-01)

## System Context & Problem Overview
During the setup of Chrome Remote Desktop on `big-len` (`192.168.8.51`) and `steven-len` (`192.168.8.156`), both headless Linux nodes running Ubuntu with installed NVIDIA Tesla P40 / Quadro P1000 GPUs repeatedly disconnected after initial pairing, showing `Last online: XX:XX PM` on `remotedesktop.google.com/access`.

Empirical investigation revealed four distinct root causes spanning GPU driver conflicts, Google Python 3 script bugs, missing `xauth` socket rules, and GNOME session manager crashes.

---

## 1. Dual NVIDIA GPU vs. Xorg Dummy Driver Conflict (`xserver-xorg-video-dummy`)
* **Failure:** Installing `chrome-remote-desktop` automatically installs `xserver-xorg-video-dummy`. By default, Chrome Remote Desktop attempts to launch `/usr/lib/xorg/Xorg` with the dummy driver. On nodes equipped with NVIDIA GPUs (Tesla P40 / Quadro P1000), `Xorg` detects the PCI IDs (`10de:1cb1`) of the NVIDIA GPUs without an active display output driver configured, causing `Xorg` to fail to open listening sockets on display `:20`.
* **Resolution:** Set `CHROME_REMOTE_DESKTOP_USE_XVFB=1` in the systemd service environment drop-in (`/etc/systemd/system/chrome-remote-desktop@steven.service.d/override.conf`). This forces Chrome Remote Desktop to use `Xvfb` (Virtual Framebuffer), which operates completely independently of physical GPU display hardware.

---

## 2. Missing `localhost` Magic Cookie in Google's `xauth` Cookie Generator
* **Failure:** In `/opt/google/chrome-remote-desktop/chrome-remote-desktop` (line 1651), Google's startup code executes `xauth add :20 . \`mcookie\``. This only registers an X11 authorization cookie for `hostname/unix:20`. When `xdpyinfo` runs during the server readiness check, it connects over the UNIX domain socket and checks `~/.Xauthority` for a matching `localhost/unix:20` key. Because `localhost/unix:20` was absent, `xdpyinfo` returned exit code 1 (`unable to open display ":20"`), causing `_wait_for_x()` to fail and tear down the host after 30 seconds.
* **Resolution:** Patched line 1651 in Google's Python wrapper script to execute:
  `COOKIE=\`mcookie\`; xauth add :%d . $COOKIE; xauth add localhost/unix:%d . $COOKIE`
  This guarantees that `xauth` registers the magic cookie for both `:20` and `localhost/unix:20`.

---

## 3. Python 3 String Formatting Tuple Mismatch in `_launch_server`
* **Failure:** When modifying the `xauth` string in `/opt/google/chrome-remote-desktop/chrome-remote-desktop` to include two `%d` placeholders (`:%d` and `localhost/unix:%d`), passing a scalar variable `% display` threw `TypeError: not enough arguments for format string`, crashing the Python process on startup with status 1/FAILURE.
* **Resolution:** Updated the format string argument to pass a two-element tuple `% (display, display)`.

---

## 4. `gnome-session` Wayland Abort & Systemd Target Conflicts in Headless Mode
* **Failure:** `gnome-session` on Ubuntu 26.04 uses systemd user units (`gnome-session@ubuntu.target`) and defaults to Wayland when launched from TTY. When Chrome Remote Desktop executed `exec /etc/X11/Xsession` or `exec /usr/bin/gnome-session`, `gnome-session` aborted with `A graphical session is already running! (core dumped)` because a physical login session was already active on `tty2`.
* **Resolution:** Installed `xfce4-session` (`sudo apt install xfce4-session xfce4-panel xfce4-terminal -y`) and configured `~/.chrome-remote-desktop-session` as follows:
  ```bash
  unset SESSION_MANAGER
  unset DBUS_SESSION_BUS_ADDRESS

  exec xfce4-session
  ```
  `xfce4-session` runs cleanly in an isolated virtual framebuffer display, uses 0% idle CPU, and never conflicts with local GNOME or systemd user units.

---

## Verification & Final Status
* **`big-len` (`192.168.8.51`)**: Successfully online and connected via Chrome Remote Desktop.
* **`steven-len` (`192.168.8.156`)**: Successfully online and connected via Chrome Remote Desktop.
