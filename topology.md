# Project Antigravity: Microgrid Network Topology & Inference Models

This document maintains the official record of the network hosts, hardware configurations, active database locations, and installed LLM/VLM models across the microgrid cluster.

---

## 1. Active Microgrid Topology

### 1.1 Jetson Orin Nano (Data & Math Node)
*   **Hostname**: `nvjetson`
*   **IP Address**: `192.168.8.68`
*   **Role**: Primary telemetry ingestion aggregator, stager daemon host (`stage_local_summary.py`), and gRPC service manager.
*   **Hardware**: Jetson Orin Nano (8 GB shared system RAM/VRAM)
*   **OS**: Ubuntu Linux (JetPack)

### 1.2 Jetson Orin Nano (Dedicated GPU AI Server)
*   **Hostname**: `nvagent`
*   **IP Address**: `192.168.8.45`
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
    *   **CPU**: AMD Ryzen 5 5500 (6 Cores / 12 Threads)
    *   **RAM**: 32 GB DDR4
    *   **GPU**: NVIDIA GeForce RTX 4060 (8 GB GDDR6 VRAM)
    *   **Motherboard**: Gigabyte AB350M-DS3H-CF (BIOS F51g)
*   **OS**: Ubuntu 26.04 LTS
*   **Active Ollama Models**:
    *   `gemma4-it-q4:latest` (Default Fallback Model - 3.1 GB)
    *   `gemma2:9b` (High-Performance 9B Model - 5.4 GB)

### 1.4 Raspberry Pi (Kiosk Display Display)
*   **Hostname**: `rainforestpi`
*   **IP Address**: `192.168.8.70`
*   **Role**: Kiosk frontend, rendering telemetry plots and streaming summaries from the stager daemon.
*   **Hardware**: Raspberry Pi 4 Model B
*   **OS**: Raspberry Pi OS (Debian)

---

## 2. Workstations & Core Services

### 2.1 Windows Workstation (Native PostgreSQL Database Server)
*   **Hostname**: `i7office`
*   **IP Address**: `192.168.8.82`
*   **Role**: Active database server hosting the canonical `photo_catalog` database (PostgreSQL 17).
*   **Hardware**:
    *   **GPU**: NVIDIA GeForce RTX 5080
*   **Ollama Models**:
    *   `gemma4:12b` (Gemma 4 12B)

### 2.2 Windows Workstation (Developer Node)
*   **Hostname**: `i7dell`
*   **Role**: Developer workstation.
*   **Hardware**:
    *   **GPU**: NVIDIA GeForce RTX 4070
*   **Ollama Models**:
    *   `gemma4:12b` (Gemma 4 12B)

---

## 3. Staging & Diagnostics (Offline)

### 3.1 Ubuntu GPU Server (Former Staging Server)
*   **Hostname**: `steven-len`
*   **IP Address**: `192.168.8.156` (formerly `192.168.8.51`)
*   **Role**: Used strictly as an offline schema testing and model benchmark sandbox.
*   **Hardware**:
    *   **CPU**: Intel Xeon W-2135 (6 Cores)
    *   **RAM**: 64 GB ECC DDR4
    *   **GPU**: NVIDIA Quadro P1000 (4 GB) + NVIDIA GeForce GTX 1050 Ti (4 GB)
*   **Active Ollama Models**:
    *   `gemma2-9b-custom` (Offloaded to CPU memory - 5.73 tokens/s)
    *   `gemma2-2b-custom` (17.25 tokens/s)
