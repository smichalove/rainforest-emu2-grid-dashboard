# Project Antigravity: Microgrid Network Topology & Inference Models

This document maintains the official record of the network hosts, hardware configurations, active database locations, and installed LLM/VLM models across the microgrid cluster.

---

## 1. Active Microgrid Topology

### 1.1 Jetson Orin Nano (Data & Math Node)
*   **Hostname**: `nvjetson`
*   **IP Address**: `192.168.8.68`
*   **Role**: Primary telemetry ingestion aggregator, stager daemon host (`stage_local_summary.py`), gRPC service manager, and active edge AI host.
*   **Hardware**:
    *   **CPU**: 6-core ARM Cortex-A78AE (Architecture: `aarch64`)
    *   **Memory**: 8 GB LPDDR5 (7.4 GiB usable + 7.7 GiB swap on ZRAM)
    *   **Storage**: 1 TB NVMe SSD (Model: `ORICO-J10`, Size: 953.9 GB)
    *   **GPU**: 1024-core NVIDIA Ampere (integrated/shared system RAM)
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

### 1.2 Jetson Orin Nano (Dedicated GPU AI Server)
*   **Hostname**: `nvagent`
*   **IP Address**: `192.168.8.45` (Currently Offline / Dead)
*   **Role**: Primary edge AI generation host for stager summaries (Standby/Offline).
*   **Hardware**:
    *   **CPU**: 6-core ARM Cortex-A78AE (Architecture: `aarch64`)
    *   **Memory**: 8 GB LPDDR5 (7.4 GiB usable + 7.7 GiB swap on ZRAM)
    *   **Storage**: 1 TB NVMe SSD (Model: `ORICO-J10`, Size: 953.9 GB)
    *   **GPU**: 1024-core NVIDIA Ampere (integrated/shared system RAM)
*   **OS**: Ubuntu Linux (JetPack)
*   **Active Ollama Models**:
    *   None (Device Offline)

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
    *   **OS/Arch**: Windows 10/11 x86_64 (PostgreSQL 17.10 on x86_64-windows)
    *   **CPU**: AMD Ryzen 9 5950X (16 Cores / 32 Threads)
    *   **Memory**: 128 GB RAM
    *   **GPU**: NVIDIA GeForce RTX 5080 (16 GB GDDR6X)
    *   **Storage**: Multi-drive layout (1.6 TB OS SSD, 16.7 TB D:, 7.5 TB I:, 1.8 TB J:, 14.9 TB O:, 1 TB T:) plus physical attached 1 TB SSD (`H:`) hosting the canonical photo catalog and project DB.
*   **Ollama Models**:
    *   `gemma4:12b` (Gemma 4 12B)

### 2.2 Windows Workstation (Developer Node)
*   **Hostname**: `i7dell` (DellI7)
*   **IP Address**: `192.168.8.113`
*   **Role**: Active developer workstation.
*   **Hardware**:
    *   **OS/Arch**: Windows 10/11 x86_64
    *   **CPU**: AMD Ryzen 9 5900X (12 Cores / 24 Threads)
    *   **Memory**: 96 GB RAM
    *   **GPU**: NVIDIA GeForce RTX 4070 Ti Super (16 GB GDDR6X)
*   **Ollama Models**:
    *   None active.

### 2.3 Local macOS Workstation (Developer Node)
*   **Hostname**: `Stevens-Air-2` (Local Mac)
*   **IP Address**: `192.168.8.71`
*   **Role**: Primary code interface, local plotting preview client, and local testing/LLM node.
*   **Hardware**:
    *   **CPU**: Apple M2 (Architecture: `arm64`)
    *   **Memory**: 8 GB LPDDR5
    *   **Storage**: 512 GB NVMe SSD (`460 GiB` APFS container size)
*   **OS**: macOS
*   **Ollama Models**:
    *   `gemma4-it-q4:latest` (Custom local 2B edge model)
        *   > [!NOTE]
        *   > **Performance Profile**: Runs a 4-bit quantized version of the model (~5–6 GB VRAM footprint). This requires half the memory bandwidth to read the weights during generation, achieving a fast **~10–15 seconds per batch**.

### 2.4 Remote macOS Workstation (Curation Node)
*   **Hostname**: `Stevens-Mini-2` (Mac Mini M4)
*   **IP Address**: `192.168.8.103` (2.5 GbE Interface `en8`)
*   **Role**: High-performance Apple Silicon curation node.
*   **Hardware**:
    *   **CPU**: Apple M4 (10-Core CPU, Architecture: `arm64`)
    *   **Memory**: 16 GB Unified Memory (UMA)
*   **OS**: macOS
*   **Active Ollama Models**:
    *   `gemma4:e4b` (Text-only curation)
        *   > [!NOTE]
        *   > **Performance Profile**: Runs the higher precision `e4b` model. Depending on the exact template, 8-bit or higher precision doubles the memory bandwidth pressure and mathematical calculations per token, resulting in a slower **~55–60 seconds per batch** despite the M4 hardware.

---

## 3. Staging & Diagnostics (Offline)

### 3.1 Ubuntu GPU Server (Old Staging Server)
*   **Hostname**: `steven-len`
*   **IP Address**: `192.168.8.156`
*   **MAC Address**: `a4:ae:11:11:26:38`
*   **Role**: Used strictly as an offline schema testing and model benchmark sandbox.
*   **Hardware**:
    *   **CPU**: Intel Xeon W-2135 (6 Cores / 12 Threads, Architecture: `x86_64`)
    *   **Memory**: 64 GB ECC DDR4
    *   **GPU**: NVIDIA Quadro P1000 (4 GB) + NVIDIA GeForce GTX 1050 Ti (4 GB)
    *   **Storage**: 3 TB Seagate HDD (Model: `ST3000DM001-1CH166`, Root system filesystem with ~2.6 TB available)
*   **OS**: Ubuntu Linux

### 3.2 Ubuntu GPU Workstation (New Workstation Build)
*   **Hostname**: `len-big` (alias `big-len`)
*   **IP Address**: `192.168.8.51` (pinned via router DHCP lease)
*   **MAC Address**: `a4:ae:11:1d:19:2c`
*   **Role**: High-speed database sync staging, edge Ollama model host, and primary file storage sandbox.
*   **Hardware**:
    *   **CPU**: Intel Xeon W-2135 (6 Cores / 12 Threads, Architecture: `x86_64`)
    *   **Memory**: 64 GB RAM
    *   **Storage**: 500GB Samsung NVMe SSD (Root) + 2TB SATA HDD (Mounted at `/mnt/storage` for overflow)
    *   **GPU**: NVIDIA Tesla P40 (24 GB VRAM) + NVIDIA Quadro P1000 (4 GB VRAM)
*   **OS**: Ubuntu 26.04 LTS (Kernel 7.0)

### 3.3 Ubuntu NAS Node ("Lenovo NAS")
*   **Hostname**: `520c`
*   **IP Address**: `192.168.8.198`
*   **MAC Address**: `f4:93:9f:ec:de:96`
*   **Role**: Network-attached storage (NAS) and backup storage target.
*   **Hardware**:
    *   **CPU**: Intel Xeon W-2133 (6 Cores / 12 Threads, Architecture: `x86_64`)
    *   **Memory**: 48 GB RAM (45 GiB usable)
    *   **Storage**: 256 GB FIKWOT FX520 NVMe SSD (System Root) + 2x 3 TB SATA HDDs (Mounted at `/srv/nas/storage1` and `/srv/nas/storage2` separately, ext4)
    *   **GPU**: NVIDIA GeForce GTX 750 Ti (2 GB VRAM) + NVIDIA Quadro P620 (2 GB VRAM)
*   **OS**: Ubuntu 26.04 LTS (Kernel 7.0)

---

## 4. Network Infrastructure

### 4.1 Primary Home Gateway Router
*   **Hostname**: `GL-MT6000_upstairs`
*   **IP Address**: `192.168.8.1`
*   **Role**: Primary internet gateway, DHCP/DNS server, and upstream WAN router.
*   **Hardware**:
    *   **Model**: GL.iNet GL-MT6000 (Flint 2)
    *   **CPU**: Quad-core MediaTek MT7986 (ARMv8 rev 4)
    *   **Memory**: 1 GB RAM (1013 MB usable)
    *   **Storage**: 8 GB eMMC (7.2 GB overlay size)
*   **OS**: OpenWrt (GL.iNet custom firmware based on 21.02-SNAPSHOT, Kernel 5.4.238)

### 4.2 Downstairs Wireless Access Point
*   **Hostname**: `Flint2_downstairs`
*   **IP Address**: `192.168.8.2`
*   **Role**: Downstairs Wi-Fi coverage extension (Access Point mode), bridged via a 2.5G physical ethernet backhaul.
*   **Hardware**:
    *   **Model**: GL.iNet GL-MT6000 (Flint 2)
    *   **CPU**: Quad-core MediaTek MT7986 (ARMv8 rev 4)
    *   **Memory**: 1 GB RAM (1013 MB usable)
    *   **Storage**: 8 GB eMMC (7.2 GB overlay size)
*   **OS**: OpenWrt (GL.iNet custom firmware based on 21.02-SNAPSHOT, Kernel 5.4.238)

### 4.3 KVM-over-IP Management Device
*   **Hostname**: `ONE KVM`
*   **Model**: One-E3 (running BusyBox Linux with Dropbear SSH `2016.74`)
*   **IP Address**: `192.168.8.188` (MAC Address: `12:35:2A:B1:F3:C8` on interface `eth0`)
*   **Role**: Remote hardware diagnostics interface for server boot troubleshooting.
*   **Security Restrictions**: Permanently blocked from outbound forwarding to the internet (WAN) or other local subnets via the router firewall rule `Block_KVM_All_Forwarding` on the `GL-MT6000_upstairs` gateway to prevent its built-in reverse proxy (FRP) and Tencent Cloud phone-home web socket from communicating.


---

## 5. Home Datacenter Architectural & Capability Analysis

### 5.1 What the Datacenter Represents About the Owner
The composition of this home compute environment reflects a highly advanced power user, most likely an AI software engineer, systems architect, or quantitative hardware researcher. It stands as a testament to:
*   **Extreme Sovereign Localism (Zero-Cloud)**: By running local edge LLMs/VLMs (Gemma 4/2), local database services (PostgreSQL 17), and offline telemetry aggregation, the owner rejects external cloud dependencies. Data privacy, security, and absolute self-reliance are core design principles.
*   **Production-Grade Engineering in a Domestic Setting**: Integrating dual bridged enterprise-speed 2.5G routers, multi-node compute redundancy (Jetson edge fallbacks to high-performance workstations), and secure TLS-encrypted gRPC pipelines represents a level of infrastructure maturity usually reserved for enterprise datacenters.
*   **Hardware Enthusiast & Pragmatist**: The owner combines cutting-edge consumer computing parts (NVIDIA RTX 5080 and RTX 4070 Ti Super) for deep learning/data work, alongside optimized, low-power ARM architecture (Jetson Orin Nanos and Raspberry Pi) for continuous, 24/7 background telemetry duties.

### 5.2 Technical Capabilities & Workload Distribution
The home cluster represents a massive, multi-tiered computational platform:
1.  **AI & Parallel Computing Tier**: 
    *   Equipped with a total of **32 GB GPU VRAM** across dev workstations (RTX 5080 16GB + RTX 4070 Ti Super 16GB), plus **8 GB VRAM** on the dedicated AI fallback server (RTX 4060) and integrated Jetson cores.
    *   Capable of performing massive offline inference, custom model quantization, and local multi-agent feedback loops (proposer-verifier patterns) completely disconnected from the WAN.
2.  **High-Capacity Data & Storage Tier**:
    *   `i7office` acts as the massive centralized data vault, packing **128 GB of RAM** and over **53 TB of storage array** (including SSDs and high-capacity HDDs), running production-level PostgreSQL. 
3.  **Low-Power Telemetry & Resiliency Tier**:
    *   Utilizes dual Jetson Orin Nano systems to run signal processing math (DFT/FFT) and stager ingestion without keeping energy-hungry x86 workstations powered on 24/7.
    *   Visual representation via a dedicated, mirrored dual-HDMI Raspberry Pi 4 kiosk, serving as the physical diagnostic bridge to the entire household microgrid.
