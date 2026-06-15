# nvagent Build & Provisioning Log

This file tracks the setup, configuration steps, and troubleshooting history for provisioning the new GPU Inference Node (`nvagent` / `192.168.8.82`). It also serves as a record of failures and course corrections.

---

## 1. Node Profile & Architecture Role

*   **Hostname**: `nvagent`
*   **Target IP**: `192.168.8.82` (DHCP reserved or static)
*   **Hardware**: Nvidia Jetson Orin Nano (8GB Unified Memory)
*   **Storage**: 1TB PCIe M.2 NVMe SSD (cloned from `nvjetson`)
*   **OS/Firmware**: JetPack 6.2 (L4T 36.4.3) - UEFI Bootloader `36.4.3-gcid-38968081`
*   **Primary Duty**: Headless Inference Server running Ollama (`gemma4-it-q4` model) and Google AI Edge SDK pipelines.
*   **Disabled Services**: Relational telemetry data stager (`stage_local_summary.py` on ports 5000/50051) is disabled on this node to isolate GPU resource usage.

---

## 2. Provisioning Checklist

- [x] **Task 1: Complete System Clone**
  - Completed: Cloned exactly 1,024,209,543,168 bytes (1.0 TB) block-by-block.
- [x] **Task 2: Physical Installation**
  - Completed: Cloned SSD installed in the M.2 slot of the new Jetson, booted, and network-connected.
- [x] **Task 3: Hostname & SSH Configuration**
  - Completed: Hostname set to `nvagent`. SSH host keys successfully regenerated locally on the device (`ssh-keygen -A`) to avoid duplicate key conflicts on the network.
- [x] **Task 4: Service De-confliction**
  - Completed: Stopped and disabled the background stager systemd service (`jetson-grid-edge.service`) to prevent network port and DB staging conflicts.
- [ ] **Task 5: Verification & Connectivity**
  - Confirm the new `nvagent` node can receive gRPC prompts from `nvjetson` or `rainforestpi` and stream back Ollama tokens.

---

## 3. Deployment Options & Performance Profiles

During provisioning, the following methods were available. They are documented here to align with the repository's performance guidelines:

### Option A: Live Clone via `dd` on active Jetson (Current Method)
*   **Description**: Run `dd` from `/dev/nvme0n1` directly to target SSD `/dev/sda` over USB.
*   **Performance**: **Low**. Bottlenecked by USB 2.0 negotiating speeds (~46 MB/s). Takes ~6 hours to copy a full 1TB drive regardless of how empty the source disk is.
*   **Risk**: **Moderate**. Running a clone of a live filesystem can carry small risks of filesystem dirty states, and there is no safeguard to prevent overwriting the wrong target disk.

### Option B: Offline Disk Clone on Mac Host (Recommended for speed)
*   **Description**: Connect both the source SSD and target SSD to a Mac host via USB enclosures and use BalenaEtcher's **Clone Drive** tool.
*   **Performance**: **High**. Operates at native NVMe/USB 3.2 speeds (500–1000 MB/s). Completes the entire 1TB clone in **15 to 20 minutes**.
*   **Risk**: **Low**. Offline filesystem prevents dirty writes. Requires removing the source SSD from the working Jetson.

---

## 4. Incident Log & Agent Failures (June 14, 2026)

To maintain transparency and ensure system safety, the following failures occurred and have been resolved via codebase rule amendments:

### Failure 1: Lack of Destructive Command Warning
*   **Description**: The agent proposed a block-level raw writing command (`sudo dd ... of=/dev/sda`) to copy the system drive without providing a prominent caution or warning block, despite the user explicitly asking what would happen to their partitions.
*   **Consequence**: The Windows backup partitions on `/dev/sda` were immediately overwritten and erased without an upfront verification prompt or caution flag.
*   **Remedy**: Added **Section 14: High-Risk & Destructive Operations Guardrails** to the official development guidelines ([agent.md](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/agent.md)). The rule enforces that any command modifying disks, partitions, or critical data must be preceded by a prominent `> [!CAUTION]` block.

### Failure 2: Recommending Non-Performant Method Without Options
*   **Description**: The agent proposed the live `dd` copy (taking 6 hours over a slow USB 2.0 port) as the default option without evaluating the actual data occupancy (disk is mostly empty) and without offering the faster Mac-based offline clone (15–20 minutes).
*   **Consequence**: The system copy was started using a highly unoptimized, slow path.
*   **Remedy**: Updated Section 8 of the guidelines to require that agents always present at least two options (**Optimized/High-Performance** vs. **Simple/Fallback**) detailing execution times, hardware bottlenecks, and data-loss risks before any hardware flashing or deployment work.
