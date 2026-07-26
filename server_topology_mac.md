# Gemma Photo Cataloger - macOS Server Topology

This document details the system architecture and network topology utilized by the `gemma_cataloger` photo cataloging pipeline when orchestrated natively from a **macOS client/host** (such as the developer's MacBook Air or Mac Mini).

The pipeline uses a hybrid orchestration model: it runs the core directory crawling and database transactions natively on the macOS host, while offloading heavy Vision-Language Model (VLM) frame scans and text-based Ollama curation to dedicated GPU inference servers across the local area network (LAN).

> [!TIP]
> **Combined Network Curation Throughput (Live Measured — 2026-07-04)**: With the concurrent worker pool active, the network distributes VLM queries in parallel to the local workstation and the remote Dell RTX 4070 Ti SUPER, achieving high-throughput visual cataloging without saturating any single GPU.

---

## 1. Core Nodes (macOS Perspective)

### Local macOS Orchestrator & Client (MacBook Air @ `192.168.8.71` / Mac Mini @ `192.168.8.103`)
*   **Role**: Runs the main Python pipeline scripts, crawls target directories, reads EXIF/video headers natively, compiles contact sheets in-memory, and writes metadata directly to PostgreSQL.
*   **Hardware**: Apple Silicon M-series (Unified Memory Architecture - UMA).
*   **Storage Access**: Mounts external storage arrays via macOS paths (e.g., `/Volumes/HDrive/Wan_project`).
*   **Key Services**:
    *   **Curation Pipeline (`clean_database_artists.py`)**: Runs natively in Python on macOS.
    *   **PostgreSQL Client Connection**: Connects to the local or remote PostgreSQL database instance.
    *   **Fast XML Sync (`sync_pg_to_jriver_xml.py`)**: Natively generates and updates JRiver `_JRSidecar.xml` sidecar files in under 7 seconds for target folders.

### Remote VLM Inference Server ("Dell Server" @ `192.168.8.113`)
*   **Role**: Primary remote GPU server providing high-throughput vision API endpoints.
*   **Hostname**: `DellI7`
*   **Hardware**: NVIDIA GeForce RTX 4070 Ti SUPER (16GB VRAM), AMD Ryzen 9 5900X, 64GB RAM.
*   **Endpoint**: `http://192.168.8.113:8000/analyze` (VLM) / `http://192.168.8.113:8000/describe` (FastAPI).
*   **Key Services**:
    *   **FastAPI / Uvicorn API (`remote_server.py`)**: Quantized Gemma 4 (12B IT) VLM in 4-bit NF4 using BitsAndBytes.

### Remote Ollama Curation Server ("Giga Server" @ `192.168.8.193`)
*   **Role**: Primary remote GPU server for text-based curation and Ollama models.
*   **Hostname**: `ubunto-giga`
*   **Hardware**: Ubuntu Linux, NVIDIA GeForce RTX 4060 (8GB VRAM).
*   **Endpoint**: `http://192.168.8.193:11434/api/generate` (Ollama running `gemma4-it-q4:latest`).

### Remote Ollama Curation Server ("Mac Mini" @ `192.168.8.103`)
*   **Role**: Apple Silicon curation node.
*   **Hardware**: Mac Mini M4 (16GB Unified RAM).
*   **Key Services**:
    *   **Ollama Service**: Port `11434` running `gemma4:e4b` for text curation. (Vision models are bypassed here to avoid llama-server architecture bugs).

### Remote WSL Workstation ("i7office" @ `192.168.8.82`)
*   **Role**: Host for the main PostgreSQL database and WSL2 orchestration pipelines.
*   **WSL2 SSH Access**: Programmatic and terminal access to WSL is available from macOS via `ssh workbench@i7office` (or `ssh workbench@192.168.8.82`).

---

## 2. Directory & Path Mapping Matrix

Because target music and video assets are stored on external shares, paths must be resolved dynamically between Windows, WSL, and macOS environments:

| Drive/Volume | Windows Target | WSL2 Path | macOS Native Path |
| :--- | :--- | :--- | :--- |
| **H Drive (Project)** | `H:\Wan_project` | `/mnt/h/Wan_project` | `/Volumes/HDrive/Wan_project` |
| **D Drive (Music)** | `D:\Users\steven\Music` | `/mnt/d/Users/steven/Music` | `/Volumes/i7office/Users/steven/Music` |

---

## 3. macOS Execution Workflows

### 1. Run Music & Video Curation
To run curation recursively against target folders on the `H:` drive natively from your macOS terminal:
```bash
python3 clean_database_artists.py --dir "/Volumes/HDrive/Wan_project/wont_v1_vid" --force-vlm
```

### 2. Sync PostgreSQL to JRiver XML Sidecars
To write the JRiver sidecar XML files directly from macOS:
```bash
python3 sync_pg_to_jriver_xml.py
```

### 3. Run Database Chat REPL
To start the interactive natural language database client in PostgreSQL mode:
```bash
export DB_BACKEND=postgresql
python3 db_chat_repl.py --remote
```

### 4. Mount Remote Shares (i7office)
To mount the `i7office` SMB shares passwordlessly in your macOS environment (utilizing stored Keychain credentials):
```bash
/Users/treven/Desktop/mount_i7office.sh
```
* **Keychain Matching:** The script uses the hostname `i7office` and domain-prefixed username `i7office;Steven` to match the exact keychain entry.
* **Volume Mapping:** If `/Volumes/i7office` is missing, you must map it to the actual mount point (`/Volumes/D`) by creating a symbolic link (requires root):
  ```bash
  sudo ln -s /Volumes/D /Volumes/i7office
  ```
