# Jetson Orin Nano Troubleshooting History

This file documents the troubleshooting history and hardware state of the Nvidia Jetson Orin Nano setup. It serves as a persistent context record to prevent losing progress across session resets.

---

## Current Status (Last Updated: May 29, 2026 - 8:35 AM)

### 1. Hardware Setup & Connections
- **Host Machine**: M2 Apple Silicon Mac.
- **Connection Cable**: Good high-quality **SUMPK USB C-to-C cable** plugged directly into the first Mac USB-C port and the Jetson's USB-C port.
- **Display Connections**: 
  - **RESOLVED**: Switched to a direct **DP-to-DP cable** (no adapter). Display is now fully working and showing the UEFI Boot / Shell interface.
- **Flash Storage Media**:
  - **microSD Card**: Flashed with **JetPack 5.1.2** (being replaced with JP 6.0).
  - **M.2 NVMe SSD**: Flashed with **JetPack 5.1.2** (being replaced with JP 6.0).

### 2. Verified UEFI / Storage States
- **UEFI Bootloader**: Functional. The internal QSPI NOR flash bootloader is working and displays the UEFI Shell on boot.
### Step 1: Flash JetPack 6.2 Image (Current Step)
- **Root Cause of previous issue**: Flashing JetPack 6.0 (L4T 36.3.0) on a motherboard with `36.4.3` firmware caused a kernel-firmware mismatch. The kernel booted but failed to initialize the PCIe controller, making the NVMe SSD invisible to the OS and dropping to a minimal initramfs shell.
- **Action**: The user is currently downloading the **JetPack 6.2 (L4T 36.4.3)** SD card image, which is the exact match for the motherboard firmware.
- The image will be flashed directly to the NVMe SSD via BalenaEtcher on the Mac.

### Step 2: Boot and Verify (In Progress)
- NVMe SSD flashed with JetPack 6.2 (matching `36.4.3` firmware) was inserted.
- **NVMe Detection Issue**: The Orico J-10 SSD uses a Realtek controller. When the Linux kernel boots, it attempts to enable advanced PCIe features (like ASPM and Gen3 speed), which causes the Realtek controller to fail link training and disappear from the kernel (`lspci` and `/proc/partitions` are empty).
- **FDT Device Tree Conflict**: The SD card image defaults to a standard Dev Kit DTB (`tegra234-p3767-0000-p3768-0000-a0.dtb`), which mismatches the "Super-Jetson" board layout, disabling the PCIe controller.
- **Current Action**: Successfully mounted the SSD EXT4 partition using Paragon extFS at `/Volumes/Untitled` and updated `/boot/extlinux/extlinux.conf` (updated root to `/dev/nvme0n1p1` and added `pcie_aspm=off`).
- **Update (May 29, 2026 - 2:30 PM)**:
  - Jetson booted successfully to the text login prompt bypassing OEM wizard. Login was validated via default user `nvidia` / `nvidia`.
  - Configured a new custom production user account: **`steven`** (password: `steven`). Copied SSH public keys and enabled passwordless sudo for `steven`.
  - Verified passwordless SSH connection to `steven@192.168.8.68`.
  - Discovered rootfs partition `/dev/nvme0n1p1` was restricted to 21GB default image size. Relocated backup GPT partition structures using `sgdisk -e /dev/nvme0n1` and expanded partition 1 to the end of the disk using `sgdisk -d 1 -n 1:3057664:0 /dev/nvme0n1`.
  - Upon rebooting, the boot failed and dropped to `initramfs` (emergency shell). 
  - **Root Cause**: The bootloader configuration file `/boot/extlinux/extlinux.conf` lost its required 6-space indentation on the `APPEND` line during offline file editing. This caused the bootloader to ignore the root partition path and PCIe workaround arguments.
  - **Resolution**: Mounted SSD on Mac, restored the 6-space indentation of `APPEND`, and safely unmounted/ejected it.
- **Next Steps**:
  1. Boot the Jetson and log in via `ssh steven@192.168.8.68`.
  2. Run `sudo resize2fs /dev/nvme0n1p1` to expand the filesystem to the full 1TB container.
  3. Install speedtest-cli: `sudo apt-get update && sudo apt-get install -y speedtest-cli`.
- **System Upgrade**: Run `sudo apt update && sudo apt upgrade -y` to ensure Vulkan, CUDA, and Tegra drivers are fully up to date.
- **Enable SSH**: Ensure the SSH server is enabled and started using `sudo systemctl enable --now ssh`.
- **Physical Assembly**: After verifying a successful boot to Linux, configuring SSH, and upgrading, powered down and assembled the board inside its chassis/case.
- **Hostname Configuration (May 29, 2026)**: Configured system hostname to **`nvjetson`** (updated `/etc/hostname` and `/etc/hosts`).


---

## Log of Failures & Resolutions

1. **Display Signal Failure (Resolved)**:
   - *Failure*: No display output on DisplayPort.
   - *Root Cause*: Attempted to use passive DP-to-HDMI adapters, which are incompatible with the Jetson's native DP output.
   - *Resolution*: Switched to a direct DP-to-DP cable.

2. **OS Image Version Mismatch (Resolved)**:
   - *Failure*: System kept returning to the UEFI Boot Manager or failing with "invalid parameter".
   - *Root Cause*: Motherboard firmware is JetPack 6.x (`36.4.3`), but the flashed SSD/SD images were JetPack 5.x (`5.1.2` / `5.1.3`).
   - *Resolution*: Downloaded and flashed JetPack 6.2 (matching `36.4.3`).

3. **Wrong JetPack 6.x Version Selection (Resolved)**:
   - *Failure*: Booted JetPack 6 image but NVMe SSD was not detected by the kernel.
   - *Root Cause*: Flashed JetPack 6.0 (`36.3.0`) which has an older kernel that mismatched the `36.4.3` firmware, disabling the PCIe controller.
   - *Resolution*: Downloaded and flashed JetPack 6.2 (L4T 36.4.3).

4. **PCIe / NVMe Link Training Failure (In Progress)**:
   - *Failure*: Even with matching JetPack 6.2, `/proc/partitions` is empty and no NVMe device is shown in initramfs.
   - *Root Cause*: The Orico J-10 SSD's Realtek controller has ASPM timing conflicts, causing the PCIe link to drop when the kernel initializes.
   - *Action*: Appended `pcie_aspm=off` in the UEFI boot options and conducting a cold boot test to resolve PCIe reset signal lockups.

### Step 3: Free Memory / Graphical State (GNOME)
- Previously, the system was configured for Headless Mode by adding `systemd.unit=multi-user.target` to `/boot/extlinux/extlinux.conf` to free up ~1.5 GB of unified memory for LLM execution.
- **RESTORED TO GRAPHICAL BOOT (May 29, 2026)**: Removed `systemd.unit=multi-user.target` from `/boot/extlinux/extlinux.conf`. On the next reboot (after physical rewiring), the Jetson will boot straight into the GNOME desktop.
- To toggle graphical target manually:
  - Default graphical target: `sudo systemctl set-default graphical.target`
  - Default headless target: `sudo systemctl set-default multi-user.target`

