# Persistent Rules for Antigravity

- **Network Configuration Restrictions:**
  > [!IMPORTANT]
  > *   Never write to, modify, or rewrite router network configurations, DNS settings, DHCP client/server leases, or wireless interface settings without explicit user permission.
  > *   **Do not remove or bypass the `Block_KVM_All_Forwarding` firewall rule** on the gateway router (`192.168.8.1`) for the KVM device (`12:35:2A:B1:F3:C8` / `192.168.8.188`). This device contains active phone-home reverse-proxy backdoors to Tencent Cloud and must remain completely isolated from the WAN.

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
