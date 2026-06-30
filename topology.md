# Project Antigravity: Microgrid Network Topology & Inference Models

This document maintains the official record of the network hosts, hardware configurations, active database locations, and installed LLM/VLM models across the microgrid cluster.

---

## 1. Active Microgrid Topology

### 1.1 Jetson Orin Nano (Data & Math Node)
*   **Hostname**: `nvjetson`
*   **IP Address**: `192.168.8.68`
*   **Role**: Primary telemetry ingestion aggregator, stager daemon host (`stage_local_summary.py`), and gRPC service manager.
*   **Hardware**:
    *   **CPU**: 6-core ARM Cortex-A78AE (Architecture: `aarch64`)
    *   **Memory**: 8 GB LPDDR5 (7.4 GiB usable + 7.7 GiB swap on ZRAM)
    *   **Storage**: 1 TB NVMe SSD (Model: `ORICO-J10`, Size: 953.9 GB)
    *   **GPU**: 1024-core NVIDIA Ampere (integrated/shared system RAM)
*   **OS**: Ubuntu Linux (JetPack)

### 1.2 Jetson Orin Nano (Dedicated GPU AI Server)
*   **Hostname**: `nvagent`
*   **IP Address**: `192.168.8.45` (Currently Offline / Dead)
*   **Role**: Primary edge AI generation host for stager summaries.
*   **Hardware**: Jetson Orin Nano (8 GB shared system RAM/VRAM)
*   **OS**: Ubuntu Linux (JetPack)
*   **Active Ollama Models**:
    *   `gemma4-vision-q4:latest` (VLM - 4.1 GB)
    *   `gemma4-it-q4:latest` (Default Edge Model - 3.1 GB)
    *   `gemma4-e2b-q4:latest` (Edge 2B - 3.4 GB)
    *   `gemma2-edge:latest` (1.7 GB)
    *   `gemma2:2b-instruct-q4_K_M` (1.7 GB)
    *   `gemma2:9b-instruct-q3_K_M` (4.8 GB)
    *   `gemma2:9b` (5.4 GB)
    *   `gemma2:2b` (1.6 GB)

### 1.3 Ubuntu Dedicated AI Server (High-Performance Node)
*   **Hostname**: `ubunto-giga`
*   **IP Address**: `192.168.8.193`
*   **Role**: Primary interactive REPL chat host; active stager daemon fallback node.
*   **Hardware**:
    *   **CPU**: AMD Ryzen 5 5500 (6 Cores / 12 Threads, Architecture: `x86_64`)
    *   **Memory**: 32 GB DDR4 (30 GiB usable)
    *   **Storage**: 1.5 TB Total (512 GB NVMe SSD `SAMSUNG MZVLB512HAJQ-000L7` + 1 TB SATA SSD `Samsung SSD 860 EVO`)
    *   **GPU**: NVIDIA GeForce RTX 4060 (8 GB GDDR6 VRAM)
    *   **Motherboard**: Gigabyte AB350M-DS3H-CF (BIOS F51g)
*   **OS**: Ubuntu 26.04 LTS
*   **Active Ollama Models**:
    *   `gemma4-it-q4:latest` (Default Fallback Model - 3.1 GB)
    *   `gemma2:9b` (High-Performance 9B Model - 5.4 GB)

### 1.4 Raspberry Pi (Kiosk Display)
*   **Hostname**: `rainforestpi`
*   **IP Address**: `192.168.8.122` (DHCP updated; formerly `192.168.8.70`)
*   **Role**: Kiosk frontend, rendering telemetry plots and streaming summaries from the stager daemon.
*   **Hardware**:
    *   **CPU**: Broadcom BCM2711 / Quad-core ARM Cortex-A72 (Architecture: `aarch64`)
    *   **Memory**: 4 GB LPDDR4 (3.7 GiB usable)
    *   **Storage**: 64 GB MicroSD card (`/dev/mmcblk0p2`, 58 GB partition size)
*   **OS**: Raspberry Pi OS (Debian)

---

## 2. Workstations & Core Services

### 2.1 Windows Workstation (Native PostgreSQL Database Server)
*   **Hostname**: `i7office`
*   **IP Address**: `192.168.8.82`
*   **Role**: Active database server hosting the canonical `photo_catalog` database (PostgreSQL 17).
*   **Hardware**:
    *   **OS/Arch**: Windows 10/11 x86_64
    *   **GPU**: NVIDIA GeForce RTX 5080
    *   **Storage**: Attached physical `H:` drive hosting the project/database files.
*   **Ollama Models**:
    *   `gemma4:12b` (Gemma 4 12B)

### 2.2 Windows Workstation (Developer Node)
*   **Hostname**: `i7dell`
*   **Role**: Developer workstation (Currently Shutdown / Skipped).
*   **Hardware**:
    *   **GPU**: NVIDIA GeForce RTX 4070
*   **Ollama Models**:
    *   None active.

### 2.3 Local macOS Workstation (Developer Node)
*   **Hostname**: `Stevens-Air-2` (Local Mac)
*   **Role**: Primary code interface, local plotting preview client, and local testing node.
*   **Hardware**:
    *   **CPU**: Apple M2 (Architecture: `arm64`)
    *   **Memory**: 8 GB LPDDR5
    *   **Storage**: 512 GB NVMe SSD (`460 GiB` APFS container size)
*   **OS**: macOS

---

## 3. Staging & Diagnostics (Offline)

### 3.1 Ubuntu GPU Server (Former Staging Server)
*   **Hostname**: `steven-len`
*   **IP Address**: `192.168.8.156` (formerly `192.168.8.51`)
*   **Role**: Used strictly as an offline schema testing and model benchmark sandbox.
*   **Hardware**:
    *   **CPU**: Intel Xeon W-2135 (6 Cores / 12 Threads, Architecture: `x86_64`)
    *   **Memory**: 64 GB ECC DDR4 (61 GiB usable)
    *   **Storage**: 2 TB SATA SSD (Model: `SSD 2TB`, Size: 1.9 TB)
    *   **GPU**: NVIDIA Quadro P1000 (4 GB) + NVIDIA GeForce GTX 1050 Ti (4 GB)
*   **OS**: Ubuntu Linux
*   **Active Ollama Models**:
    *   `gemma2-9b-custom` (Offloaded to CPU memory - 5.73 tokens/s)
    *   `gemma2-2b-custom` (17.25 tokens/s)
