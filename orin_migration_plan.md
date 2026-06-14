# Migration Plan - Nvidia Jetson Orin Edge AI Dashboard

This document outlines the architectural plan for migrating the AI-generated telemetry summaries from **Google Cloud Vertex AI** to a local **Nvidia Jetson Orin** ecosystem running local Large Language Models (LLMs). This setup allows operators to choose between low-cost cloud scale (Raspberry Pi + Vertex AI) and fully self-contained multi-node edge execution (Raspberry Pi + Nvidia Orin).

---

## Architectural Comparison

| Feature | Cloud Architecture (Pi + Vertex AI) | Local Edge Architecture (Pi + Multi-Node Orin) |
| :--- | :--- | :--- |
| **Edge Hardware** | Raspberry Pi 3 / 4 / 5 | Raspberry Pi (GUI) + Nvidia Jetson Orin #1 (Stager) + Nvidia Jetson #2 (Inference) |
| **LLM Backend** | Vertex AI (Gemini 2.5 Flash) | Local Ollama or Google AI Edge SDK / MediaPipe (Gemma 2 2B/9B, Llama-3, Phi-3) |
| **Inference Cost** | Pay-per-token (discounted via Batch API) | $0.00 (Pure electricity) |
| **Processing Latency** | ~10–15 mins (Platform queuing) | Variable based on local GPU queue (usually 10–20 seconds) |
| **Data Privacy** | Telemetry sent to GCP | 100% On-Prem / Offline |

---

## Local Edge Architecture Block Diagram

```mermaid
flowchart TD
    subgraph PiNode [Raspberry Pi Kiosk Node]
        UI[dashboard.py / Tkinter GUI]
        LocalCache[gemini_summary.json]
    end

    subgraph Jetson1 [Jetson Orin #1 (Data & Math Node)]
        Stager[stage_local_summary.py: port 5000]
        DB[(grid_history.db - Synced)]
        Watchdog[active_local_job.json]
    end

    subgraph Jetson2 [Jetson Orin #2 (Dedicated Inference Node)]
        API[FastAPI Server: port 8000]
        SDK[Google AI Edge SDK / MediaPipe / Ollama]
        GPU[Ampere GPU Core]
    end

    UI -->|1. Polling: /api/analyze| Stager
    Stager -->|2. Read Telemetry| DB
    Stager -->|3. POST Prompt JSON| API
    API -->|4. Query LLM Engine| SDK
    SDK -->|5. Compute Acceleration| GPU
    GPU -->|6. Return Tokens| SDK
    SDK -->|7. Return Summary| API
    API -->|8. Return Response JSON| Stager
    Stager -->|9. Respond with Cache Data| UI
    UI -->|10. Render Background Text| LocalCache
```

---

## Technical Integration Details

### 1. Local Inference Daemon (Ollama & Google AI Edge SDK)
We leverage **Ollama** or **Google AI Edge SDK / MediaPipe** as the local server backend running on the Nvidia Jetson Orin. 
* **Ollama Interface**: Exposes a standard OpenAI-compatible API endpoint locally at `http://localhost:11434/api/generate`.
* **Google AI Edge SDK Interface**: Exposes a lightweight FastAPI endpoint at `http://localhost:8000/generate` using MediaPipe LLM Inference to run quantized Gemma 2B-IT models directly on GPU.
* **Model Choices**:
  - `gemma2:2b` or `gemma-2b-it-gpu.bin` (optimized for fast edge inference under 2 GB VRAM footprint).
  - `gemma2:9b` (for higher-logical reasoning on a dedicated 8GB/16GB Orin unit).
  - `phi3:mini-128k-instruct` (excellent performance and large context window).

### 2. Standalone Local Watchdog Script (`stage_local_summary.py`)
The Orin stager runs as a background service (`jetson-grid-edge`) that processes telemetry and interacts with the LLM engines:

#### A. Telemetry Collection & Prompting
- Aggregates the local history databases and CSVs (Grid, SolarEdge, Chillicon) into hourly records.
- Loads the prompt template dynamically from `gemma_hybrid_prompt.txt` or model-adapted local prompts.

#### B. Asynchronous Local Request Queue & Watchdog
In local environments, GPU cores are often shared with video transcoding, object detection (YOLO), or home automation models. This can cause local inference requests to queue or take several minutes to run.
- **In-flight Registry**: When sending the request to Ollama or the AI Edge API, the script writes `active_local_job.json` containing the request parameters, active prompt, and system timestamp.
- **Polling Loop**: The script polls the task status. If a reboot or process crash occurs, it reads `active_local_job.json` and resumes checking the task or re-submits it if the engine daemon was reset, maintaining reliable state.
- **Metadata Tagging**: Appends processing metadata to the summary:
   `[Edge Model: Gemma-2B | Inference Time: 12.4s]`

### 3. File System Decoupled Cache
The dashboard UI (`dashboard.py`) running on the Raspberry Pi remains 100% untouched. It continues to poll the stager HTTP endpoint (`/api/analyze`) and updates `gemini_summary.json` locally, rendering the AI summary text directly onto the Tkinter canvas.

-----

## Jetson Orin Provisioning & Display Optimization

### 1. Out-of-the-Box SDK Flashing
To prepare a new Jetson Orin from scratch:
- **SD Card vs. M.2 NVMe SSD Setup**: **[Highly Recommended]** While you can boot from a microSD card, it is strongly recommended to install a **PCIe M.2 NVMe SSD** (Type 2280 is fully supported in the carrier board's underside slot; SATA M.2 drives are not supported). Booting the JetPack OS from an NVMe SSD provides 10x–20x faster read/write speeds, accelerating local model weight loads into memory, and prevents storage corruption issues caused by continuous 15-second telemetry CSV write cycles.
- **Flashing via NVIDIA SDK Manager**: To boot directly from the M.2 NVMe SSD, flash the JetPack OS onto the SSD using the **NVIDIA SDK Manager** from an Ubuntu host PC. If the SSD is currently formatted (e.g. as Windows NTFS), the SDK Manager flashing process will automatically format it to the Linux-native **ext4** filesystem, wiping the drive clean.
- **Initial Boot Configuration**: You have two options to complete the Ubuntu configuration wizard (creating user, network, language) on first boot:
  - **Option A (Headed)**: Connect your monitor (using the DisplayPort-to-HDMI adapter) and plug in a USB keyboard and mouse to navigate the graphical installer.
  - **Option B (Headless Serial)**: Connect a micro-USB (or USB-C) debug cable from the Orin's recovery port to your host PC/Mac. Open a terminal emulator (e.g. `screen /dev/ttyUSB0 115200` on Mac/Linux or PuTTY on Windows) to complete the entire configuration wizard headlessly over the serial console.
- **Network Provisioning Tip**: **[Highly Recommended]** Hardwire the Orin to a **2.5 Gbps network backbone** during initial setup. The CUDA runtimes, JetPack libraries, Docker container dependencies, and local LLM GGUF model files (especially the 5.5 GB Gemma 2 9B) total more than 20–30 GB of downloads, which can bottleneck on standard Wi-Fi.

### 2. Display Model & Kiosk Optimization (X11 vs. GNOME)
By default, JetPack installs the heavy **GNOME 3 Desktop Environment** running on X11. This GUI consumes over **1.2 GB of RAM** and active CPU/GPU cycles, which restricts resources available for local LLM inference (crucial on the 4GB/8GB Orin Nano).

To optimize the graphics display:
- **Display Connection Sizing Warning**: The Jetson Orin Nano Developer Kit **does not support DisplayPort (DP) Alt Mode over USB-C**. You cannot drive a monitor from the USB-C port. Instead, you must use the physical **DisplayPort (DP)** connector on the carrier board, pairing it with a standard DP-to-HDMI adapter or cable to drive your HDMI kiosk monitor.
- **Why X11 is Preferred**: Unlike Wayland (used on Raspberry Pi OS Bookworm), the Jetson Linux graphics driver stack is deeply optimized for X11, offering flawless hardware-accelerated rendering and reliable fullscreen scaling for Tkinter/Matplotlib.

- **Action Plan - Lightweight Openbox Kiosk**:
  Instead of running GNOME, we will configure a minimal X11 session using **Openbox** (a highly lightweight window manager that uses < 50MB of RAM):
  1. Install Openbox and X11 utility tools:
     ```bash
     sudo apt-get install --no-install-recommends openbox xorg x11-xserver-utils
     ```
  2. Configure X11 autostart (`~/.config/openbox/autostart`) to launch only the screen blanking disable rules and the dashboard:
     ```bash
     # Disable screen blanking & DPMS
     xset s off -dpms
     # Run dashboard fullscreen
     python3 dashboard.py
     ```
  3. Change the lightdm display manager configuration to boot straight into the Openbox Kiosk session automatically.
  4. This preserves maximum memory (saving ~1GB of RAM) and GPU cores to run models like `phi3:mini` at peak inference speeds.

---

## Local Edge Model & Dockerized Installation

### 1. Disk Space and Storage Sizing
A **128GB SSD** is more than sufficient for this deployment without requiring external storage:
- **Base OS & JetPack**: Occupies ~30–40 GB.
- **Docker Images & Runtimes**: Occupies ~5–10 GB.
- **Model Storage**: Quantized GGUF models are highly compact:
  - **Phi-3 Mini (3.8B - 4-bit Quant)**: **~2.2 GB**
  - **Llama-3 (8B - 4-bit Quant)**: **~4.7 GB**
- **Available Margin**: You will have over **60 GB of free space** left on the SSD for system log rotation and telemetry cache.

### 2. Recommended Models & Unified Memory (8GB RAM) Constraints
Because the **Jetson Orin Nano 8GB** features a **Unified Memory Architecture (UMA)**, the 8GB of system RAM is shared dynamically between the 6-core CPU and the Ampere GPU.
- **Operating System Overhead**: A default Ubuntu desktop boot leaves ~6.5 GB of free RAM. Swapping to our recommended **Openbox Kiosk Mode** recovers ~1 GB, leaving ~7.5 GB for models and runtime storage.
  - **Gemma 2 9B (4-bit Quant: ~5.5 GB VRAM)**: **[Recommended for Dedicated setups]** If the Jetson Orin Nano is dedicated strictly to this project and configured with our **Openbox Kiosk Mode**, you will have ~6.8 GB of free unified memory. This easily fits the 5.5 GB model size, making it highly viable. It provides state-of-the-art logical reasoning and mathematical parsing of telemetry data.
  - **Gemma 2 2B (4-bit Quant: ~1.6 GB VRAM)**: **[Highly Recommended for Shared setups]** Runs at blistering inference speeds (>30 tokens/sec), uses minimal memory, and leaves plenty of free RAM if you plan to share the Orin with other concurrent AI workloads (like robotics or object detection).
  - **Phi-3 Mini (3.8B, 128k context - 4-bit Quant: ~2.2 GB VRAM)**: Excellent analytical skills for parsing long history streams while maintaining a safe memory margin.
  - **Llama-3 (8B, 4-bit Quant: ~4.7 GB VRAM)**: Runs stably with high analytical output under Openbox Kiosk on a dedicated unit.



### 3. Installation Guide (Dockerized Ollama)
Using Docker with the **NVIDIA Container Toolkit** is the most reliable, clean, and self-healing deployment mechanism on JetPack.

#### Step A: Enable NVIDIA Container Toolkit
Ensure Docker is installed and the NVIDIA runtime is registered (pre-installed in modern JetPack images):
```bash
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

#### Step B: Instantiate Ollama Container
Launch the official Ollama container with GPU access, mapped persistent storage, and automatic restart policies to survive sudden edge device crashes or reboots:
```bash
docker run -d \
  --gpus all \
  --restart unless-stopped \
  -v ollama:/root/.ollama \
  -p 11434:11434 \
  --name ollama \
  ollama/ollama
```

#### Step C: Download and Cache the Target Model
Instruct Ollama to fetch and cache the model locally inside the persistent volume container:
```bash
# Pulls and loads Google Gemma 2 (9B version) into GPU memory
docker exec -d ollama ollama run gemma2:9b

# Or for the ultra-lightweight 2B version:
# docker exec -d ollama ollama run gemma2:2b
```
The local API is now accessible to the staging script (`stage_local_summary.py`) at `http://localhost:11434/api/generate`.

---

## Output Drift Testing & Evaluation Framework

To ensure that swapping from Vertex AI (Gemini 2.5 Flash) to a local edge model (Gemma 2 9B / 2B) does not degrade summary quality, we will implement a rigorous comparison test suite:

### 1. Test Harness Design
We will build a test script `compare_models.py` that runs offline:
- **Test Prompts**: Feed a set of 20 diverse historical telemetry prompt manifests (containing standard solar days, high-demand winter days, net export summer days, and battery-discharge Flex Event days) to both endpoints.
- **Concurrent Executions**: Call both the Vertex AI Batch API and local Ollama API to collect matching response pairs.

### 2. Evaluated Drift Dimensions

| Metric Dimension | Verification & Assertion Criteria |
| :--- | :--- |
| **Mathematical Accuracy** | Verify that both models calculate identical Net Grid totals, Solar peaks, and Flex Event battery discharge volumes without hallucinating. |
| **Constraint Compliance** | Assert that the local model respects formatting instructions (e.g. strict 80-character line wrapping limits, bullet-point layout structures, and avoidance of system headers). |
| **Semantic Equivalence** | Verify that the qualitative tone (e.g. detecting high usage anomalies or highlighting solar generation efficiency) is consistently represented. |
| **Structure Similarity** | Compute cosine similarity on TF-IDF representation or embedding distance to mathematically score how close the edge output is to the Vertex baseline. |

### 3. Execution & Reporting
The script will output an evaluation report detailing comparison metrics for each test case. This lets developers identify if the edge model requires customized few-shot prompt adjustments to align with the Vertex AI outputs.



