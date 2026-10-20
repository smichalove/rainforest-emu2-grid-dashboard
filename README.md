# EMU-2 Grid Dashboard

![EMU-2 Grid Dashboard Preview - Slide 1 (Time Domain)](dashboard_preview.jpeg)
![EMU-2 Grid Dashboard Preview - Slide 2 (Frequency Domain)](dashboard_preview_slide2.jpeg)

A robust, 24-hour real-time grid monitoring dashboard using a Rainforest EMU-2 smart meter connected to a Raspberry Pi. It automatically boots into a fullscreen kiosk mode over HDMI, safely bypasses modern Wayland graphic quirks, and seamlessly persists data to SQLite and local CSVs to survive power outages.

> [!IMPORTANT]
> **Core Architecture & Agentic Edge AI Capabilities:**
> This repository provides a complete, edge-intelligent ecosystem for home microgrids:
> * **Unified Microgrid Plotting:** Real-time 24-hour rolling visualization of smart meter grid consumption (Rainforest EMU-2/Eagle), SolarEdge solar PV generation, battery storage flow, and Chillicon microinverter data on a single dashboard layout.
> * **Interactive Chat Interface (REPL):** A CLI dialog interface allowing you to query historical telemetry, analyze solar efficiency, and consult a local LLM/VLM in real-time.
> * **Agentic Context & User Annotations:** The ability to log user annotations (e.g. appliance runs, Puget Sound Energy Flex events) that are automatically timestamped, stored persistently, and injected dynamically into LLM prompts as contextual intelligence.
> 
> *All Edge AI, chat, and agentic context features are fully supported on a **single NVIDIA Jetson Orin Nano** (8GB VRAM) running local Ollama inference models. Due to severe hardware and memory constraints, a standalone Raspberry Pi kiosk deployment **does not support local offline inference**; hence, the local chat interface and agentic capabilities require the Jetson (or an equivalent external Ollama server) to function. Alternatively, developers wishing to run these agentic and chat features in the cloud using Google Gemini must switch from the default cost-optimized cloud GCS batch mode (which only compiles baselines every 4 hours) to direct real-time Vertex AI API usage.*

> [!NOTE]
> **Product & Compatibility Note:** The Rainforest EMU-2 is a legacy hardware product that has been discontinued. For deployments using current-generation hardware, the **Rainforest EAGLE 3** features a local API that outputs a very similar XML structure, making this dashboard framework highly compatible and adaptable for it.

## Hardware Requirements
- **Raspberry Pi** (Pi 3, 4, or 5 recommended)
- **Rainforest EMU-2** connected via USB (`/dev/ttyACM0`)
- **HDMI Monitor** (The script dynamically scales to fullscreen, mimicking commercial 10" or larger solar dashboards)
- **NVIDIA Jetson Orin Nano / Orin Nano Super Developer Kit** (Optional) - Dedicated local AI server (minimum 8GB unified memory recommended) to run decoupled local Edge AI offline. For a fully optimized, lag-free setup, a **second Jetson Orin** can be added to run the Google AI Edge SDK (MediaPipe) or Ollama as a dedicated headless inference server.

## Connecting to Your Smart Meter (PSE & Others)
Because the monitor reads data directly from the Zigbee wireless network inside your utility's smart meter, it must be paired and provisioned with the meter:
1. **Purchase the Device**: Rainforest monitors can be purchased directly from the [Rainforest US Retail Store](https://rainforest-store-us.myshopify.com/).
2. **Contact Puget Sound Energy (PSE)**: Call PSE Customer Care at **1-888-225-5773** and ask them to pair/provision a **"Home Area Network (HAN) device."** You will need to provide them with the device's **MAC Address** and **Install Code** printed on the label on the back of the monitor.
3. **Other Utilities**: If your utility provider is not PSE, contact your utility's customer service or search their website for "HAN provisioning" or "Smart Meter pairing" to follow their specific activation process.

## Key Features
- **Real-Time Data Parsing**: Decodes raw XML telemetry (`<InstantaneousDemand>`) directly from the EMU-2 serial port.
- **Rolling 24-Hour Graph**: Features a dynamic rolling 24-hour X-axis with the newest readings always positioned on the far right, ensuring the graph is always fully populated with historical context.
- **Persistent Data**: Logs grid demand automatically to an optimized SQLite database `grid_history.db` every 15 seconds (with automatic one-time migration of legacy `grid_history.csv` files on first boot), SolarEdge PV and battery storage to local CSVs every 15 seconds (via local Modbus TCP) or 15 minutes (via Cloud API), and Chilicon production to `chilicon_history.csv` every 90–180 seconds via local UDP broadcast (with 15-minute cloud fallback), retroactively reloading the graph and historical context immediately upon boot.
- **SolarEdge Local Modbus TCP & Cloud Fallback**: High-frequency 15-second local SunSpec Modbus TCP telemetry querying Model 102 (Inverter AC power), Model 203 (Subpanel meter), and Model 713 (DER Storage Status / Battery SoC) with zero cloud dependency and automatic fallback to SolarEdge Cloud REST API.
- **Chilicon Real-Time UDP 32758 Debug Bridge & Cloud Fallback**: Captures raw binary datagrams broadcast by the on-premise Chilicon CP-100 Gateway on port 32758, delivering ~90-second PLC sweeps across all 8 microinverters (AC voltage, MPPT currents, uptime, lifetime energy) to PostgreSQL and local CSVs with automatic fallback to the Chilicon Cloud API.
- **Multi-Sensor Microgrid KCL Calibration**: Reconciles dual heterogeneous solar arrays (SolarEdge + Chilicon) anchored at the Rainforest EMU-2 utility revenue meter ($\pm 0.5\%$), calculating whole-home load via Kirchhoff's Current Law and eliminating single-inverter subpanel CT blind spots within sub-percent ($0.47\%$) closure accuracy.
- **Stacked Solar PV Chart**: Stacks the actual Chilicon generation (plotted as a bright neon yellow cap) on top of the SolarEdge PV bars (warm gold base) on a unified 10-minute grid, displaying your total combined solar output on the secondary Y-axis.
- **Hands-Free Kiosk Mode**: Configured to boot completely headless and automatically launch into fullscreen without sleeping.
- **AI Background Summaries**: Renders a narrative, statistical, and mathematical analysis summary directly on the graph background, formatted with smart 80-character line wrapping. Supports both Google Cloud Vertex AI and fully local Nvidia Jetson-based edge models (Ollama/Gemma 4).

---

## AI Background Summaries & Authentication

The dashboard displays a narrative, statistical, and mathematical analysis summary directly on the graph watermark. To optimize resource consumption and isolate heavy inference loops from the real-time GUI, the dashboard utilizes a **Decoupled Architecture**:
- **Baseline Summary Generation (every 4 hours)**: Feeds bulk historical telemetry to the stager to update and cache a high-fidelity baseline summary.
- **Real-Time Delta Updates (every 15 minutes)**: Pulls lightweight delta updates and overlays them using the local edge server on the Nvidia Jetson.

The prompt includes hourly aggregated Net Grid import/export statistics, SolarEdge solar generation, battery stats (`Battery_Avg_kW` average discharge rate and `Battery_SoC` average charge percentage), and actual Chillicon generation (`Chillicon_Avg_kW`). This enables the model to make highly accurate summaries and correctly separate battery dispatch behavior during Puget Sound Energy (PSE) Flex events (reimbursed at a premium rate of **$0.50 / kWh** instead of the standard $0.19 / kWh) from your actual solar arrays' generation without needing mathematical inference.

> [!WARNING]
> **Prompt Personalization Warning:** The system prompts (such as `gemma_hybrid_prompt.txt` and `gemini_prompt.txt`) are heavily customized for the developer's specific microgrid layout, geographical/climatological constraints (e.g. South-West and North-West facing solar arrays, Seattle daylight windows), utility rates (Puget Sound Energy's standard and Flex event tiers), and lack of an EV (Electric Vehicle).
> Before publishing or deploying this project in your own environment, you should review and profile these prompts. We recommend using a powerful AI (such as Gemini) to adapt and tune these system instructions, orientation angles, and billing rules to match your specific home configuration and local utility plans.
### Supported AI Models

The architecture supports both cloud-based LLM APIs and local edge inference, depending on your deployment preferences:

#### 1. Cloud-Based Models (Google Cloud Vertex AI)
* **`gemini-2.5-flash`** (Default): Primary model used for compiling large 24-hour historical baselines. Runs via high-speed direct API or cost-optimized GCS batch jobs (with a 50% discount per token).
* **`gemini-2.5-pro`** (Optional): Can be configured for deeper qualitative microgrid reports or complex utility policy reasoning.

#### 2. Local Edge Models (NVIDIA Jetson Ollama)
* **`gemma4-it-q4`** (Default): A custom edge-optimized 5.1B Instruct model (using `Q4_K_M` GGUF quantization). Fits in **1.6 GB** of active VRAM, offering extremely fast, low-latency delta and DFT summary predictions on constrained edge hardware.
* **`gemma4-vision-q4`** (Optional): Compiled using the `F16` multimodal projector adapter. Allows the local stager to perform visual analysis of the generated dashboard plots.

### Authentication Setup
The dashboard automatically authenticates using Vertex AI on Google Cloud:
1. **Google Cloud Service Account JSON:**
   - Place your service account JSON credentials key at `~/Auth/service_account.json` (or `auth/service_account.json` in the application directory).
   - The application dynamically sets the `GOOGLE_APPLICATION_CREDENTIALS` environment variable to point to this JSON file.
2. **GCP Project Configuration:**
   - Create a `.env` file in the same directory as `dashboard.py` and define your Google Cloud project and location:
     ```env
     GCP_PROJECT="your-gcp-project-id"
     GOOGLE_CLOUD_LOCATION="global"
     ```

### SolarEdge Setup & Configuration (Modbus TCP & Cloud API)

The dashboard supports two mutually compatible methods for integrating SolarEdge PV generation, battery storage flow, and whole-home load telemetry:
1. **Local SunSpec Modbus TCP (Recommended):** High-frequency 15-second polling directly over your local network, zero cloud dependency, no rate limits, and sub-second latency.
2. **SolarEdge Cloud Monitoring Web API (Fallback):** 15-minute polling via SolarEdge's official REST API (`/currentPowerFlow`), useful when installer SetApp access is unavailable.

The system dynamically prefers local Modbus TCP if `modbus_host` is configured, automatically falling back to the Cloud Monitoring API if the local connection is unreachable.

---

#### Option 1: Local SunSpec Modbus TCP Setup (15-Second Polling)

SolarEdge HD-Wave and Energy Hub inverters support the open SunSpec Modbus over TCP protocol on port `1502`.

##### Step A: Enable Modbus TCP via SolarEdge SetApp
1. **Connect to Inverter Wi-Fi:** Toggle the inverter's ON/OFF/P switch to **`P`** for $\le 2$ seconds (or scan the QR code on the inverter casing) to activate the internal Wi-Fi access point (`SE-XXXXXXXX`).
2. **Open SolarEdge SetApp:** Connect your smartphone to the inverter Wi-Fi network and launch the SetApp installer application.
3. **Enable Modbus TCP:**
   - Navigate to: **Communication** $\rightarrow$ **RS485-1** (or **LAN / Ethernet**) $\rightarrow$ **Protocol** $\rightarrow$ Select **SunSpec (Non-SE Logger)** or **Modbus TCP**.
   - Set **Port** to `1502`.
   - Set **Device ID / Unit ID** to `1`.
4. **Connect to Home LAN:** Ensure the inverter is connected to your local network via Ethernet or Wi-Fi, and configure a static DHCP IP reservation on your router (e.g., `<inverter-ip>`).

##### Step B: SunSpec Model Telemetry Mapping
The dashboard queries holding registers using standard Modbus Function Code `0x03` with zero external dependencies (pure Python `socket` + `struct`):
* **Model 102 (Registers `40069–40118`, Inverter AC Power):** Reads `I_AC_Power` (offset 14) and `I_AC_Power_SF` (offset 15) to compute calibrated AC power in Watts ($P = \text{Raw} \times 10^{\text{SF}}$).
* **Model 203 (Registers `40362–40391`, Revenue-Grade Meter):** Reads `M_AC_Power` (offset 18) and `M_AC_Power_SF` (offset 22) for subpanel grid import/export.
* **Model 713 (Registers `41438–41446`, DER Storage Status):** Reads `SoC` (offset 4, uint16) and `Pct_SF` (offset 8, int16) to report real-time battery State of Charge ($0.0–100.0\%$). *(Note: Model 703 is static grid configuration holding a fixed nominal baseline; dynamic battery charge resides in Model 713).*

---

#### Option 2: SolarEdge Cloud Monitoring API Setup (15-Minute Polling)

If you do not have SetApp commissioning access, you can use the official Cloud Web API:
1. Log in to your SolarEdge Monitoring Portal (`https://monitoring.solaredge.com`).
2. Navigate to **Admin** $\rightarrow$ **Site Access** $\rightarrow$ **API Access**.
3. Accept the terms of use and click **Generate API Key**. Copy your **API Key** and **Site ID**.
   *(Note: If the Admin tab is missing, contact your solar installer to request API access for your account.)*

---

#### Configuration File (`solaredge_config.json`)

Save your credentials in `~/Auth/solaredge_config.json` (or `auth/solaredge_config.json` in the project root):

```json
{
  "modbus_host": "<inverter-ip>",
  "modbus_port": 1502,
  "api_key": "your_solaredge_api_key",
  "site_id": "your_solaredge_site_id"
}
```

Or configure via environment variables in `.env`:
```env
SOLAREDGE_MODBUS_HOST="<inverter-ip>"
SOLAREDGE_MODBUS_PORT=1502
SOLAREDGE_API_KEY="your_solaredge_api_key"
SOLAREDGE_SITE_ID="your_solaredge_site_id"
```

*Note: If both Modbus and Cloud credentials are provided, the dashboard queries Modbus TCP every 15 seconds, falling back to the 15-minute Cloud API only if Modbus is unreachable.*

### Chillicon Cloud API Configuration
To enable the Chillicon Cloud API integration, configure your login credentials inside `~/Auth/chilicon_config.json` (or `auth/chilicon_config.json` in the application directory):
```json
{
  "username": "your_chilicon_email",
  "password": "your_chilicon_password",
  "installation_hash": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
}
```
*Note: To find your `installation_hash`, log in to your account at `https://cloud.chiliconpower.com`, click on your solar installation dashboard, and inspect the URL in your browser's address bar. The long hexadecimal string at the end of the URL is your installation hash:*
`https://cloud.chiliconpower.com/installation/abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890`

---

## Chilicon CP-100 Real-Time UDP 32758 Debug Bridge

To eliminate the ~67-minute cloud ingestion lag caused by delayed 5-minute interval bucket uploads on `cloud.chiliconpower.com`, the dashboard can tap directly into the on-premise Chilicon CP-100 Gateway's unencrypted **UDP "Info Dump" Debug Bridge** on port `32758`.

```mermaid
flowchart LR
    GW["Chilicon CP-100 Gateway<br/>&lt;gateway-ip&gt;:65452"]
    RTR["Gateway Router<br/>&lt;router-ip&gt;"]
    CLOUD["Chilicon Cloud<br/>107.155.107.6:32758"]
    PG["Local Telemetry Server<br/>&lt;server-ip&gt;:32758"]
    PI["Raspberry Pi Kiosk<br/>&lt;pi-ip&gt;"]

    GW -->|"UDP :32758 (1,372 B)<br/>Every ~176s (2x 90s Sweeps)"| RTR
    RTR -->|"Original Packet<br/>(WAN)"| CLOUD
    RTR ==>|"Cloned UDP :32758 Packet<br/>(Stateless Mirror / 0% CPU)"| PG
    PG -->|"1. Store 8-Inverter 90s Series in PostgreSQL<br/>2. Update chilicon_history.csv"| PG
    PI <-->|"Reads chilicon_history.csv<br/>(Cloud Fallback Guard)"| PG
```

### 1. The "Debug Bridge Rebroadcast" Architecture
* **Passive Router Rebroadcast:** The CP-100 Gateway transmits an unencrypted 1,372-byte binary UDP datagram every ~176.3 seconds (~2.9 minutes) to `cloud.chiliconpower.com:32758`. By configuring your router to mirror or clone these outbound packets onto the local subnet (`0.0.0.0:32758`), any local server or Raspberry Pi receives live 90-second telemetry as a stateless broadcast beacon.
* **Zero Modification & Zero Backpressure:** The gateway's native cloud sync remains 100% operational. Because UDP is connectionless (`[UNREPLIED]`), dropped packets impose 0% router memory buffering and zero CPU overhead.
* **The "Ham Radio Relay" Pattern (Bypassing CP-100 Firmware Display Bugs):** In amateur (ham) radio, a digipeater or cross-band gateway receives high-frequency RF packets on an antenna, demodulates the raw frame, and immediately re-transmits the untouched digital payload over IP/UDP without interpreting or modifying the data. In this architecture, the **CP-100 Gateway acts purely as a physical ham radio relay**:
  1. It uses its specialized analog hardware to demodulate the low-frequency 132 kHz Power Line Carrier (PLC) RF transmissions coming down the AC copper wiring from the CP-720 dual-inverters on your roof.
  2. It immediately emits the raw unencoded memory buffer out over UDP port 32758.

  **Why This Matters (The Gateway Display Bug):** The CP-100's embedded GUI firmware contains known aggregation and display bugs: in low-light / diffuse conditions or when an inverter has asymmetric MPPT channels, the gateway's internal display software applies an integer zero-floor truncation, rendering healthy inverters as solid black **`0 W` / `0 W`** "failed" tiles on its LCD and falsely depressing the main dial calculation (often leading solar technicians to mistakenly diagnose healthy microinverters as failed hardware). By treating the CP-100 purely as a physical RF-to-UDP relay and computing true physical power ($dE/dt$) from the raw 32-bit DSP hardware tick accumulators in `chilicon_udp_listener.py`, you bypass the buggy gateway UI entirely—recovering real-time AC voltage, DC MPPT voltage, and true solar generation that the physical gateway screen completely blacks out.

### 2. Binary Frame & Inverter Record Layout (`1,372 Bytes`)
Each datagram contains two consecutive 90-second Power Line Communication (PLC) sweeps across all 8 bound CP-720 dual-MPPT microinverters:
* **Gateway Header (`0..7`, 8 Bytes):** Little-endian gateway serial (`uint32_le[0]` e.g. `0x00A1B2C3`) + 4 reserved zero bytes.
* **PLC Sweep 1 (`8..687`, 680 Bytes):** 8 microinverters $\times$ 85-byte C struct (captured ~90 seconds prior).
* **PLC Sweep 2 (`688..1367`, 680 Bytes):** 8 microinverters $\times$ 85-byte C struct (current sweep).
* **Frame Trailer (`1368..1371`, 4 Bytes):** 32-bit CRC checksum.

#### Microinverter Struct Layout & Decoding Formulas (`rec[0..84]`)
* **Raw Binary (Zero Base64):** 100% unencoded C struct memory dump. All scalar fields are byte-aligned little-endian primitives (`<I`, `<H`, `B`).
* **Fixed-Point Q12.4 AC Voltage:** Offset `24..25` stores AC line voltage packed as Q12.4 (`val / 16.0` = `243.88 V AC`).
* **Lifetime Cumulative Energy:** Offset `72..75` (`<I`) represents cumulative energy ticks calibrated with the AC RMS scaling factor ($\text{RMS\_FACTOR} = \sqrt{2} \approx 1.41421356$) at **77,927.2144 ticks / kWh** ($\text{Lifetime kWh} = \text{ticks} / 77927.2144$).
* **Real-Time Sweep Power ($dE/dt$):** Power per inverter $i$ is calculated between Sweep 1 ($t_1$) and Sweep 2 ($t_2$):
  $$P_{\text{Watts}, i} = \frac{\text{ticks}_{i}(t_2) - \text{ticks}_{i}(t_1)}{(t_{2,i} - t_{1,i}) \times 0.02164645}$$
  where $0.02164645 = \frac{77927.2144}{3,600,000\text{ W*s/kWh}}$ ticks per Watt-second, matching the physical CP-100 Gateway console display down to the milliwatt.

### 3. Off-State, Dawn Transition & Night Silence Safeguards
To eliminate spurious power spikes at dawn and prevent stale positive daytime generation from "sticking" in memory overnight:
1. **Sleep / Stagnation Decay ($\Delta t = 0 \to 0.0\text{ W}$):** At dusk, when solar irradiance drops below the microinverter DSP operating threshold (~22V DC), the gateway continues polling, but uncontacted inverter timestamps freeze. Whenever $\Delta t = 0$, power is forced immediately to `0.0 W`.
2. **Dawn Cold Wake-Up Guard ($\Delta t > 900\text{s}$ Anti-Spike Filter):** When inverters wake after 8–10 hours of darkness, $\Delta t \approx 28,800\text{s}$. The listener treats any gap $> 15\text{ minutes}$ as a cold wake-up, seeds power at `0.0 W`, and re-arms baseline counters so valid generation begins on the subsequent 90s sweep.
3. **Overnight Silence Heartbeat Watchdog:** If the gateway halts UDP broadcasts during deep night (21:00–06:00), a background watchdog thread logs a synthetic `0.000 kW` heartbeat row to PostgreSQL and `chilicon_history.csv` every 15 minutes, ensuring seamless zero-baseline rendering on all dashboard charts.

### 4. Kiosk Local Priority & Cloud Fallback Guard
In `dashboard_modules/solar.py`:
* **Local Telemetry Priority:** `ChilliconClient.fetch_data()` inspects `chilicon_history.csv`. If a sample was written within $\le 360\text{ seconds}$ (6 minutes), it returns the local reading directly, preventing delayed cloud scrapes from overriding real-time UDP data.
* **Sunset Cloud Bucket Guard:** If forced to query the cloud API after dusk, the client only uses historical 5-minute interval buckets if they are recent ($\le 3\text{ buckets} / 15\text{ minutes}$ old), preventing daytime solar values from persisting after sunset.

### 5. Running the UDP Listener Daemon
Launch the listener daemon on your local server:
```bash
python3 chilicon_udp_listener.py --port 32758 --csv /path/to/chilicon_history.csv --bind-ip 0.0.0.0
```
Optional PostgreSQL logging:
```bash
python3 chilicon_udp_listener.py --port 32758 --csv chilicon_history.csv --pg-dsn "postgresql://postgres:password@localhost:5432/energy_telemetry"
```

---

## Decoupled Architecture (Pi & Cloud Batch)

For production systems, this repository supports a **decoupled architecture**. This separates the resource-heavy LLM inference from the real-time Tkinter GUI process.

You can configure this using the `LLM_MODE` setting in your `.env` file:
* **`LLM_MODE=direct` (Default)**: The GUI runs an inline background thread that queries the remote Vertex AI API directly every 15 minutes. Best for simple, out-of-the-box local developer testing.
* **`LLM_MODE=decoupled`**: The GUI runs as a pure cache consumer, disabling internal API calls and polling `gemini_summary.json` every 10 seconds for updates. This lets the local Jetson edge server or an external background stager update the cache.

### Cloud Batch Staging (Raspberry Pi)
When running `LLM_MODE=decoupled` on the Raspberry Pi:
* Run the background script `stage_batch_summary.py` in a separate screen or service session.
* This script compiles the telemetry data, uploads it to GCS, schedules a **Vertex AI Batch Prediction** job, and polls the job state.
* **Significant Cost Savings**: Vertex AI Batch predictions offer a **50% discount** per token compared to direct synchronous API calls. Additionally, polling the job status is a metadata query which is **100% free** under Google Cloud, allowing the stager to check frequently without incurring any API polling costs.
* It persists the active job state to `active_batch_job.json` to safely resume polling even across unexpected reboots (watchdog recovery).

Detailed instructions on how to set up the necessary Google Cloud Storage buckets, service accounts, and permissions for the Vertex AI Batch prediction environment can be found in the [Gemini Photo Batch Workflow repository](https://github.com/smichalove/Gemini_Photo_Batch_Workflow).

## gRPC & SQLite Local Decoupled Architecture

For local Edge AI deployments (Nvidia Jetson Orin), the communication protocol is upgraded from HTTP/REST to **gRPC** on port `50051` with mutual TLS (mTLS) zero-trust authentication. This provides high-performance telemetry streaming and real-time AI response token rendering:

```mermaid
flowchart TD
    subgraph Pi [Raspberry Pi Kiosk]
        GUI[dashboard.py / Tkinter GUI]
        Client[grpc_client.py]
    end
    subgraph Jetson [Nvidia Jetson Orin]
        Server[grpc_server.py: port 50051]
        Ollama[Ollama / Local LLM Engine]
        DB[(backups/grid_history.db)]
    end

    GUI -->|1. Request telemetry update| Client
    Client -->|2. Secure gRPC stream (port 50051)| Server
    Server -->|3. Query historical records| DB
    Server -->|4. Trigger GPU inference| Ollama
    Ollama -->|5. Yield response tokens| Server
    Server -->|6. gRPC streaming response| Client
    Client -->|7. Render text word-by-word| GUI
```

### Key Technical Integrations:
1. **Secure gRPC Streaming**: Real-time token streaming allows generated summaries to render word-by-word on the dashboard display as they are generated by the local LLM, completely bypassing HTTP request-blocking latency.
2. **Relational Database Storage**: Mismatched telemetry streams (15-second grid meter reads and 15-minute SolarEdge/Chillicon API feeds) are stored and structured in a unified SQLite database (`backups/grid_history.db`). 
3. **mTLS Authentication**: Communication between the client and server is fully encrypted and authenticated mutually using client and server TLS certificates signed by a custom Local Certificate Authority.

---

## Local Edge AI (Jetson / Nvidia Hardware) Setup

To perform inference completely offline on local Nvidia hardware (such as an Nvidia Jetson Orin Nano) without cloud API costs or dependencies, the dashboard supports a **Jetson-Centric Edge Server Architecture**. 

### Architectural Overview & Reasoning

Instead of running mathematical integrations and LLM queries directly on the Raspberry Pi (which has constrained CPU/memory and is prone to SD card failure under continuous disk writes), the dashboard offloads the heavy lifting to the Jetson Orin:

1. **Computational Offloading:** The Jetson Orin performs all quantitative telemetry math (integrals, peaks, rolling averages, standard deviations, and Pearson correlation coefficients), computes a **Discrete Fourier Transform (DFT)** to analyze 24-hour diurnal and 12-hour bimodal sinus rhythms, calculates time-domain curve slopes (derivatives) over 3-hour windows, and runs local LLM inference via Ollama.
2. **Automated Backup & SD Card Longevity:** On each analysis cycle, the Pi dashboard transfers its database snapshot and CSV telemetry files directly to the Jetson's NVMe SSD using `rsync`. This provides automatic remote backups and protects the Pi's SD card from continuous disk scans.
3. **Predictor-Driven Modeling:** The Jetson edge server fetches local forecasts (temperature, cloud cover, sunrise, and sunset) from the Open-Meteo API. It dynamically calculates the daylight duration (length of day) to scale solar sinus width expectations, classifies day types (weekday vs. weekend demand profiles), and monitors recent curve slopes to ground the local edge model within its 2048-token context window.

```mermaid
sequenceDiagram
    autonumber
    
    box rgb(30, 41, 59) Cloud & Pi Batch Baseline Pipeline (Asynchronous)
    participant Stager as stage_batch_summary.py (on Pi)
    participant GCS as Google Cloud Storage
    participant Vertex as Vertex AI (Gemini 2.5 Flash)
    participant Cache as gemini_summary.json (Pi Cache)
    end
    
    box rgb(17, 24, 39) Local Jetson Delta Pipeline (Every 15 mins)
    participant Pi as Raspberry Pi (dashboard.py)
    participant JS as Jetson 1 Server (stage_local_summary.py)
    participant J2 as Jetson 2 (Ollama / AI Edge SDK)
    end

    %% Cloud Batch Flow
    Note over Stager: Asynchronous loop (e.g. 4-hour cycle)
    Stager->>Stager: Parse database & CSVs
    Stager->>GCS: Upload staging_request.jsonl
    Stager->>Vertex: Create Batch Prediction Job
    Vertex-->>GCS: Write predictions.jsonl when done
    Stager->>GCS: Poll & Download predictions.jsonl
    Stager->>Cache: Save/Overwrite baseline summary text & timestamp
    
    %% Local Delta Flow
    Note over Pi: Every 15 minutes
    Pi->>JS: rsync database snapshot & CSV files to Jetson backup directory
    Pi->>Cache: Read baseline summary text & timestamp
    Pi->>JS: HTTP POST /api/analyze (baseline text, timestamp)
    
    Note over JS: Math Phase on Jetson
    JS->>JS: Fetch today's weather forecast from Open-Meteo API
    JS->>JS: Read database & CSV files locally
    JS->>JS: Compute delta metrics (kWh/kW) since baseline timestamp
    JS->>JS: Calculate quantitative stats (std dev, rolling averages)
    JS->>JS: Adjust solar anomaly thresholds based on cloud cover %
    JS->>JS: Format comparative prompt using gemma_hybrid_prompt.txt
    
    JS->>J2: POST /generate (payload prompt)
    J2->>J2: GPU Inference (Gemma 2 2B / Gemma 4)
    J2-->>JS: Return response text
    
    JS-->>Pi: HTTP Response (local delta text)
    Note over Pi: GUI Rendering
    Pi->>Pi: Update split-screen Matplotlib text & redraw canvas
```

### 1. Ollama Installation & Model Setup
On your Nvidia Jetson Orin:

#### Step A: Install Ollama
Install the official Ollama service (which supports ARM64/JetPack out of the box):
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

#### Step B: Allocate Swap Space on the SSD
The larger model weights (such as `gemma4-it-q4` or 9B models) can exhaust the shared unified memory of a Jetson Orin (such as an Orin Nano 4GB or 8GB), causing the inference runner process to crash (e.g., returning EOF or exit code -1). To prevent this, configure a 4GB swap space on the SSD:
```bash
# 1. Allocate a 4GB file
sudo fallocate -l 4G /swapfile

# 2. Secure file permissions
sudo chmod 600 /swapfile

# 3. Format as swap space
sudo mkswap /swapfile

# 4. Activate it instantly
sudo swapon /swapfile

# 5. Persist across system reboots
echo '/swapfile swap swap defaults 0 0' | sudo tee -a /etc/fstab
```

#### Step B.1: Drop OS Page Cache (CUDA driver OOM Prevention)
Nvidia's unified memory architecture on Tegra/Jetson shares the 8 GB RAM pool between CPU and GPU. Under continuous file indexing and telemetry logging, the Linux Page Cache (`buff/cache`) can consume almost all available memory pages. While normal user-space processes can evict page caches dynamically, the Nvidia CUDA driver requires contiguous physical pages and will fail immediately during model loading (`cudaMalloc failed: out of memory`) if it cannot find contiguous blocks.

To prevent CUDA model loading errors, release cached pages before initializing the service or loading the model:
```bash
# Flush page cache, dentries, and inodes
sudo sync && sudo sysctl -w vm.drop_caches=3
```

#### Step C: Build the Optimized Custom Model (`gemma4-it-q4`)
To run inference stably on unified memory hardware (such as an Nvidia Jetson Orin Nano 8GB), we use a pre-quantized `Q4_K_M` GGUF version of the 5.1B Instruct model from Hugging Face. This reduces the weight footprint to **3.2 GB** (consuming only **1.6 GB** in active GPU VRAM):

```bash
# 1. Download the quantized weights from Hugging Face
curl -L -o /tmp/gemma-4-e2b-it-q4_k_m.gguf https://huggingface.co/FamilyDad/gemma-4-E2B-it-GGUF/resolve/main/gemma-4-E2B-it-Q4_K_M.gguf

# 2. Create the Modelfile with optimized limits
cat << 'EOF' > Modelfile
FROM /tmp/gemma-4-e2b-it-q4_k_m.gguf
PARAMETER num_ctx 4096
EOF

# 3. Register the custom edge-optimized model in Ollama
ollama create gemma4-it-q4 -f Modelfile
```

#### Step C.1: (Optional) Register the Multimodal Vision Model (`gemma4-vision-q4`)
If you wish to test or run visual queries on your dashboard plots:
```bash
# 1. Download the multimodal vision projector adapter
curl -L -o /tmp/mmproj-f16.gguf https://huggingface.co/FamilyDad/gemma-4-E2B-it-GGUF/resolve/main/mmproj-F16.gguf

# 2. Create the Modelfile linking the weights and projector
cat << 'EOF' > Modelfile_vision
FROM /tmp/gemma-4-e2b-it-q4_k_m.gguf
ADAPTER /tmp/mmproj-f16.gguf
EOF

# 3. Register the vision model
ollama create gemma4-vision-q4 -f Modelfile_vision
```

#### Step D: Jetson-Stats (`jtop`) Installation
Install `jetson-stats` to monitor system resources, memory consumption, and GPU utilization:
```bash
# 1. Install pip
sudo apt update
sudo apt install -y python3-pip

# 2. Install jetson-stats via pip
sudo pip3 install jetson-stats

# 3. Restart the telemetry service
sudo systemctl restart jtop.service
```
*(Note: You may need to reboot the board or re-login for the command group changes to take effect.)*

#### Step E: Grant Hardware-Acceleration Access
To ensure background daemon services (like `grid_backup` running the stager script) can access the GPU hooks via JetPack without permission errors, add the daemon user and your primary user to the `video` group:
```bash
# 1. Add current user and backup daemon user to the video group
sudo usermod -aG video $USER
sudo usermod -aG video grid_backup

# 2. Restart Ollama to pick up the new group permissions
sudo systemctl restart ollama
```

### 2. Configure SSH Public Key & Security Hardening
Since the Raspberry Pi is a physical kiosk, its local SSH private key is vulnerable to extraction if the device is compromised. To enforce the **Principle of Least Privilege**, we create a dedicated, low-privilege account on the Jetson and restrict the SSH key strictly to `rsync` sync operations.

#### Step A: Create a Restricted User on the Jetson
On the Jetson, create a user `grid_backup` with no `sudo` privileges and shell login disabled:
```bash
# Create the user with nologin shell to prevent shell access
sudo useradd -m -s /usr/sbin/nologin grid_backup

# Create the target backup directory and change ownership
sudo mkdir -p /home/grid_backup/backups
sudo chown -R grid_backup:grid_backup /home/grid_backup/backups
```

#### Step B: Set Up the SSH Public Key
1. **Generate SSH key on the Pi** (if not already present):
   ```bash
   ssh-keygen -t rsa -b 4096 -N "" -f ~/.ssh/id_rsa
   ```
2. **Copy the Pi's public key to the Jetson's new account**:
   ```bash
   ssh-copy-id -i ~/.ssh/id_rsa.pub grid_backup@<jetson-ip>
   ```

#### Step C: Restrict SSH Key Command Execution
On the Jetson, edit `/home/grid_backup/.ssh/authorized_keys` and prepend options to the Pi's public key (the line beginning with `ssh-rsa ...`) to enforce command restriction. This forces the key to only be usable for `rsync` file syncing to the backups folder using the restricted `rrsync` utility:
```text
restrict,command="/usr/bin/rrsync /home/grid_backup/backups/" ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQD...
```
* `restrict`: Blocks port forwarding, agent forwarding, X11 forwarding, and shell allocation.
* `command="..."`: Restricts the incoming SSH connection to ONLY execute rsync commands within the `/home/grid_backup/backups/` directory, preventing interactive terminal access or file reads/writes outside the target directory.

> [!WARNING]
> **Strict SSH Directory Permissions Required:** SSH will reject public key authentication if directory permissions are too open. If `rsync` still prompts for a password after copying the key, run these commands on the **Jetson** to secure the `grid_backup` SSH configuration folder:
> ```bash
> chmod 700 /home/grid_backup/.ssh
> chmod 600 /home/grid_backup/.ssh/authorized_keys
> ```
> If these are group-writeable, the SSH daemon falls back to interactive password prompts, causing the Pi's background daemon sync thread to fail.

### 3. Mutual TLS (mTLS) Certificate Setup
Secure gRPC streaming requires mutual TLS (mTLS) certificates for zero-trust authentication between the client (Pi kiosk) and the server (Jetson Orin).
Run the certificate generator script in the repository:
```bash
python3 tests/emulation/generate_certs.py
```
This script runs `openssl` to automatically compile a custom Local Certificate Authority (CA) and sign certificate/key pairs:
- **CA files**: `Auth/certs/ca.crt`
- **Server files**: `Auth/certs/server.crt`, `Auth/certs/server.key`
- **Client files**: `Auth/certs/client.crt`, `Auth/certs/client.key`

*Note: In production, copy the CA and client certs to the Raspberry Pi kiosk `Auth/certs/` folder, and keep all files (including server key/cert) on the Jetson.*

### 4. Relational Database Initialization & CSV Migration
Before launching, initialize the local databases and load historical CSV files:
1. **Initialize databases**:
   ```bash
   python3 migrate_local_db.py
   ```
   This initializes `backups/grid_history.db` and `backups/analysis_history.db` with the required schema and indexes.
2. **Import CSV History**:
   ```bash
   python3 migrate_all_csvs_to_db.py
   ```
   This reads historical CSV logs (SolarEdge PV generation, battery discharge, and Chillicon microinverters) and inserts them into separate relational tables in `backups/grid_history.db`.

### 5. Launching the Jetson Edge Server
Start the stager daemon on your Nvidia Jetson Edge Server:
```bash
python3 stage_local_summary.py --port=5000
```
This launches the telemetry receiver HTTP server on port `5000` (for backwards compatibility) and the secure gRPC server on port `50051` side-by-side with mTLS enabled.

### 6. Configure Dashboard Environment (Pi)
Configure the connection properties in the `.env` file on the Pi:
```env
LLM_MODE="decoupled"
JETSON_HOST="<your-jetson-ip>"
JETSON_USER="<your-jetson-username>"
JETSON_BACKUP_PATH="/home/<your-jetson-username>/rainforest-emu2-grid-dashboard/backups/"
JETSON_PORT=5000
```

### 7. Running the Decoupled System
1. **Start the GUI on the Pi**:
   ```bash
   python3 dashboard.py
   ```
   In `decoupled` mode, it will poll the baseline summaries locally, run the background `rsync` syncs, and hit the Jetson HTTP server every 15 minutes for local delta updates.
2. **Start the Cloud Batch Stager (Optional)**:
   If you want to feed high-fidelity Cloud Vertex AI baselines to the local system, run `stage_batch_summary.py` on the Pi:
   ```bash
   python3 stage_batch_summary.py
   ```

---

## Codebase Architecture & Modules

The dashboard architecture has been completely refactored from a monolithic script into a clean, portable Python package structure (`dashboard_modules/`). This ensures clear separation of concerns, headless execution on Edge servers, and robust thread safety.

### 1. `dashboard_modules/` Package
* **`config.py`**: Centralizes global styling, API keys, and environment variables.
* **`db.py`**: Manages the SQLite telemetry database (`grid_history.db`), handling schema initialization, thread-safe write queues, automatic migration from legacy CSV data, and historical querying.
* **`io.py`**: A dedicated, thread-safe file handling layer. It features null-byte stripping for corrupted CSV lines and uses atomic swap-files for JSON caches to completely eliminate file corruption during sudden power losses.
* **`telemetry.py`**: Handles raw serial polling, XML parsing, and database history operations for the Rainforest EMU-2 hardware.
* **`solar.py`**: Manages API clients, session cookies, and authentication for SolarEdge and Chillicon external endpoints.
* **`weather.py`**: Performs asynchronous requests to Open-Meteo for cloud cover and sunrise/sunset metrics.
* **`spectral.py`**: A pure, headless mathematical library executing Discrete Fourier Transforms (DFT), signal gap interpolations, and SNR noise floor calculations.
* **`ai.py`**: Integrates the `google-genai` SDK, Vertex AI Batch upload pipelines, and local Ollama interactions.

### 2. UI & Daemon Entry Points
* **`dashboard.py`**: The main Tkinter Kiosk GUI application. It acts as a supervisor, launching the headless data acquisition threads and rendering Matplotlib canvases. It includes a built-in watchdog that detects API timeouts or serial crashes and safely heals/restarts the threads.
* **`render_local_plot.py`**: A mock emulator that generates static PNGs of the dashboard using offline history databases and CSVs, allowing developers to test UI layout changes without physical hardware.
* **`stage_batch_summary.py`**: Background cron job that feeds bulk arrays of telemetry to Google Cloud Vertex AI to cache high-fidelity baseline LLM summaries.
* **`stage_local_summary.py`**: Lightweight HTTP daemon built for Nvidia Jetson servers to receive telemetry arrays, perform frequency-domain spectral math, and run fast local LLM inferences (`gemma4-it-q4`) on live deltas.
* **`snr_analysis.py`**: Standalone mathematical helper module implementing DTFT spectrum and signal SNR calculators.

---

## Complete Setup Instructions

### 0. Clone the Repository
Clone this repository directly to your user's home directory on the Raspberry Pi:
```bash
cd ~
git clone https://github.com/<your-github-username>/rainforest-emu2-grid-dashboard.git
cd rainforest-emu2-grid-dashboard
```

### 1. Revert to X11 (Debian Bookworm)
Modern Raspberry Pi OS uses Wayland, which severely limits X11 forwarding and headless Tkinter display configurations over SSH. Revert to the highly stable X11 (LightDM) backend:
```bash
sudo raspi-config
# Navigate to: Advanced Options -> Wayland -> Choose X11
sudo reboot
```

### 2. Disable Screen Blanking
To prevent the HDMI screen from going to sleep after 10 minutes of inactivity, create an autostart script that disables power-management on boot:
```bash
mkdir -p ~/.config/autostart
nano ~/.config/autostart/disable-blanking.desktop
```
Add the following configuration:
```ini
[Desktop Entry]
Type=Application
Name=Disable Blanking
Exec=/usr/bin/xset s off -dpms
StartupNotify=false
Terminal=false
```

### 3. Autostart the Dashboard
Create a second desktop entry to automatically launch the python dashboard when the desktop environment finishes loading:
```bash
nano ~/.config/autostart/grid-dashboard.desktop
```
Add the following configuration (be sure to replace `username` with your Pi's actual user account name, e.g. `steven` or `pi`):
```ini
[Desktop Entry]
Type=Application
Name=Grid Dashboard
Exec=/home/username/rainforest-emu2-grid-dashboard/run_dashboard_system.sh
StartupNotify=false
Terminal=false
```

### 4. Install Dependencies & X11 Autostart
Modern Debian distributions (like Bookworm on Raspberry Pi) enforce PEP 668, preventing direct `pip` installations. 
1. Clone the repository to your Raspberry Pi.
2. Run the deployment script to create the Python virtual environment, install dependencies, configure the X11 autostart so the dashboard launches fullscreen automatically on boot, and suppress Raspberry Pi OS update popups for a seamless kiosk experience.

```bash
chmod +x install.sh
./install.sh
```

**Manual `venv` setup (if not using the install script):**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 5. Running Manually & Graceful Teardown
If you ever need to manually stop and restart the dashboard while the desktop is running, press `Ctrl+C` in your SSH terminal or close the window (by clicking the screen or pressing `Escape`). 

The script registers OS signal handlers (`SIGINT`, `SIGTERM`), which guarantees that:
- Background threads are stopped cleanly.
- The USB serial interface port (`/dev/ttyACM0`) is released.

To run manually:

#### A. Direct Mode (Standard Inline API)
```bash
export DISPLAY=:0 && python3 dashboard.py
```

#### B. Decoupled Mode (Vertex AI Batch)
1. Start the background staging worker:
   ```bash
   ./venv/bin/python -u stage_batch_summary.py > stage_batch.log 2>&1 &
   ```
2. Launch the dashboard GUI in cache-polling mode:
   ```bash
   LLM_MODE=decoupled export DISPLAY=:0 && ./venv/bin/python -u dashboard.py
   ```
*(Note: If you receive a `couldn't connect` error because the HDMI is sitting at the root login screen, inject it using: `sudo XAUTHORITY=/var/run/lightdm/root/:0 DISPLAY=:0 python3 dashboard.py`)*

#### C. Local Edge AI Mode (Ollama)
```bash
export DISPLAY=:0 && python3 dashboard.py --localllm
```

If you do not have a SolarEdge solar system configured and want to completely disable SolarEdge telemetry querying, history loading, bar chart plotting, and aligned aggregations, run the dashboard using the `--solaroff` option:
```bash
python3 dashboard.py --solaroff
```

If you wish to completely disable Chillicon Cloud API querying, history loading, bar chart plotting, and aligned aggregations, run the dashboard using the `--chiliconoff` option:
```bash
python3 dashboard.py --chiliconoff
```

Both flags can be stacked to run a pure grid demand dashboard without any solar integrations:
```bash
python3 dashboard.py --solaroff --chiliconoff
```

## Development Emulation & Cost Analysis

To validate the Vertex AI batch submission system and measure real-world performance, latency, and cost savings without waiting days for telemetry logs, we implemented a complete local emulation pipeline:

### 1. The Emulation Pipeline
The script `emulate_power_meter_batch.py` simulates real-world usage over an extended time:
* **Bulk Prompt Generation:** Hydrates `gemini_prompt.txt` using historical logs and mathematical variations to construct 150 unique, realistic 24-hour summary requests.
* **Batch Structuring:** Groups the 150 requests into 10 concurrent batch files (`.jsonl`).
* **GCS Stage & Submit:** Uploads the manifests to Google Cloud Storage and schedules the Vertex AI Batch jobs synchronously.
* **Submission Latency:** The local JSONL preparation executes in **<0.002 seconds**, and concurrent GCS upload + Vertex AI submission of all 10 batches completes in **11.2 seconds**.

### 2. Cost-Benefit Results
Based on Vertex AI pricing for `gemini-2.5-flash`:
* **Standard Online API Cost:** $0.075 per 1M input / $0.30 per 1M output tokens.
* **Vertex AI Batch API Cost:** $0.0375 per 1M input / $0.15 per 1M output tokens.
* **Verified Savings:** Standardizing on Vertex AI Batch predictions provides a **50% token cost discount**, making long-term continuous grid analysis highly economical.

## Development & Security
- Always run `gitleaks` prior to committing or syncing any changes to GitHub.

### AI Agent & Developer Guidelines
For human developers and AI coding agents, this repository provides specialized rules, instructions, and architectural references within the [.agents/](.agents) directory:
*   [agent.md](.agents/rules/agent.md): Development guidelines, styling specifications, security requirements, and commit conventions.
*   [architecture.md](.agents/architecture.md): A detailed reference of the decoupled multi-node edge AI topology, data flows, and database schemas.
*   [token-guard.md](.agents/rules/token-guard.md): Guidelines on token limits and context optimization.

Before implementing any changes, AI agents **MUST** read the guidelines in [agent.md](.agents/rules/agent.md) and refer to the system design in [architecture.md](.agents/architecture.md).

---

## Mathematical & Frequency-Domain Grounding (DFT & Slopes)

To give the local edge LLM a deep physical understanding of the electrical system, the Jetson Edge Server translates raw time-domain database and CSV telemetry into the frequency domain using a zero-dependency Discrete Fourier Transform (DFT) and computes time-domain rate-of-change slopes.

### 1. Discrete Fourier Transform (Diurnal & Semi-Diurnal Harmonics)
For a 48-hour time series of hourly measurements $x = [x_0, \dots, x_{47}]$, we compute the complex DFT coefficient $X_k$ for specific frequency bins $k$:
* **Solar Diurnal Rhythm ($k = 2$):** Analyzes the 24-hour cycle. The amplitude $A_{24}$ represents the strength of the solar day (collapsing to near zero on overcast days). The phase angle $\phi_{24}$ is converted to the exact peak solar hour of day (e.g. 13.2h).
* **Grid Semi-Diurnal Rhythm ($k = 4$):** Analyzes the 12-hour cycle (morning and evening bimodal peaks). The Grid Bimodality Ratio ($A_{12}/A_{24}$) indicates if the house is following normal bimodal usage peaks (ratio > 1.0) or flatlining due to continuous EV charging or massive exports (ratio < 0.5).

### 2. Peak Hour of Day Mapping
A cosine component peaks when the phase argument equals zero. The peak hour of day $H_{\text{peak}}$ is mapped from the start hour of the series $H_{\text{start}}$ and the phase angle $\phi_k$ (in radians):
$$H_{\text{peak}} = \left(H_{\text{start}} - \phi_k \cdot \frac{T}{2\pi}\right) \pmod T$$
Where $T$ is the period length in hours (24.0 for diurnal, 12.0 for semi-diurnal).

### 3. Rate-of-Change Slopes (Derivatives)
To capture sudden cloud shading drops (occlusions) or rapid appliance startups, the server calculates the first derivative over the last 3 hours. Using a 3-point linear regression slope (least-squares fit), the mathematics simplifies to:
$$\text{Slope} = \frac{x_{N-1} - x_{N-3}}{2} \quad \text{(kW/hr)}$$
This filters out single-point sensor noise while providing a smooth average rate of change.

### 4. Few-Shot Logical Test Cases
To guide the LLM's reasoning engine contextually, few-shot examples representing normal operations, solar occlusion collapses, and grid flatline anomalies are embedded in `gemma_hybrid_prompt.txt`. This ensures the model treats the metrics as physical bounds and produces deterministic, concise outputs.

## DBeaver Ad-Hoc SQL Analysis

The consolidated SQLite database (`backups/grid_history.db`) allows you to run SQL queries and joins across high-frequency grid reads and low-frequency SolarEdge/Chillicon API metrics.

### DBeaver Connection & Caching Note
> [!IMPORTANT]
> **Schema Cache Refresh**: Autocomplete and syntax highlighting in DBeaver's SQL Editor are sticky. When you add new tables or alter schemas via external python scripts (e.g. `migrate_all_csvs_to_db.py`), DBeaver may not recognize the new tables or columns. To clear DBeaver's local schema cache, right-click the database connection and select **Disconnect**, then right-click and choose **Connect**.

### Sample Queries

#### Option A: The "As-Of" Join (Forward-Filling last known value)
Aligns the lower-frequency APIs to the high-frequency Rainforest grid readings by joining the **latest known battery/solar state** recorded at or before each 15-second grid reading, completely eliminating NULLs:

```sql
SELECT 
    gh.timestamp AS time_key,
    gh.kw AS grid_kw,
    
    (SELECT battery_kw FROM solaredge_battery_history sbh 
     WHERE sbh.timestamp <= gh.timestamp 
     ORDER BY sbh.timestamp DESC LIMIT 1) AS battery_kw,
     
    (SELECT soc FROM solaredge_battery_history sbh 
     WHERE sbh.timestamp <= gh.timestamp 
     ORDER BY sbh.timestamp DESC LIMIT 1) AS battery_soc,
     
    (SELECT load_power_kw FROM solaredge_flow_history sfh 
     WHERE sfh.timestamp <= gh.timestamp 
     ORDER BY sfh.timestamp DESC LIMIT 1) AS household_load_kw,
     
    (SELECT pv_kw FROM solaredge_history sh 
     WHERE sh.timestamp <= gh.timestamp 
     ORDER BY sh.timestamp DESC LIMIT 1) AS solaredge_pv_kw,
     
    (SELECT power_kw FROM chilicon_history ch 
     WHERE ch.timestamp <= gh.timestamp 
     ORDER BY ch.timestamp DESC LIMIT 1) AS chilicon_pv_kw
FROM grid_history gh
WHERE gh.timestamp >= '2026-06-08T00:00:00'
ORDER BY gh.timestamp ASC
LIMIT 100;
```

#### Option B: The 15-Minute Bucket Join (Standard Aggregation)
Groups the high-frequency grid data and low-frequency metrics into uniform 15-minute time buckets (`00`, `15`, `30`, `45`) to compare average power rates without gaps:

```sql
WITH grid_15m AS (
    SELECT 
        strftime('%Y-%m-%d %H:', timestamp) || 
          printf('%02d:00', (CAST(strftime('%M', timestamp) AS INT) / 15) * 15) AS time_bucket,
        AVG(kw) AS avg_grid_kw
    FROM grid_history
    WHERE timestamp >= '2026-06-08T00:00:00'
    GROUP BY time_bucket
),
battery_15m AS (
    SELECT 
        strftime('%Y-%m-%d %H:', timestamp) || 
          printf('%02d:00', (CAST(strftime('%M', timestamp) AS INT) / 15) * 15) AS time_bucket,
        AVG(battery_kw) AS avg_battery_kw,
        AVG(soc) AS avg_soc
    FROM solaredge_battery_history
    WHERE timestamp >= '2026-06-08T00:00:00'
    GROUP BY time_bucket
),
solar_15m AS (
    SELECT 
        strftime('%Y-%m-%d %H:', timestamp) || 
          printf('%02d:00', (CAST(strftime('%M', timestamp) AS INT) / 15) * 15) AS time_bucket,
        AVG(pv_kw) AS avg_pv_kw
    FROM solaredge_history
    WHERE timestamp >= '2026-06-08T00:00:00'
    GROUP BY time_bucket
)
SELECT 
    g.time_bucket,
    g.avg_grid_kw,
    b.avg_battery_kw,
    b.avg_soc,
    s.avg_pv_kw
FROM grid_15m g
LEFT JOIN battery_15m b ON g.time_bucket = b.time_bucket
LEFT JOIN solar_15m s ON g.time_bucket = s.time_bucket
ORDER BY g.time_bucket ASC
LIMIT 100;
```

---

## Future Scalability & Memory Management
To prevent long-term file I/O latency, memory spikes, or SD card wear from infinitely expanding telemetry logs on the Raspberry Pi kiosk, a future roadmap has been drafted:
* See [retention_and_memory_management_plan.md](planning/retention_and_memory_management_plan.md) for architectural options (including logrotate + tail primitives, SQLite databases, and hourly analytics compression) to optimize resource consumption and downstream ML performance on local networks.

---

## Interactive Context-Aware REPL Client (CLI)

An interactive, terminal-based REPL chat client (`repl_client.py`) is included to let developers hold natural-language dialogues with the local VLM server, analyzing microgrid telemetry alongside saved user notes.

### Core Capabilities
* **Automatic Telemetry Aggregation**: When you type a query, the client reads the last 48 hours of SQLite data and CSV telemetry, generates a formatted hourly summary table, and prepends it to the LLM system prompt context dynamically.
* **OS-Level Signal Handling**: Prevents terminal hanging by handling `SIGINT` (Ctrl-C) cleanly, allowing you to exit back to the shell safely at any time while keeping raw terminal formatting in sync.
* **Flexible `/paste` Mode**: Type `/paste` or `/multiline` anywhere in your prompt to input raw multiline blocks (e.g. system logs) without the shell splitting them. Pressing `Ctrl-C` inside paste mode cancels the paste buffer and returns you to the normal prompt.
* **Persistent Dialogue Archiving**: Logs all REPL conversations locally to `repl_chat_log.jsonl` in the sync folder for future offline analysis.
* **Smart Database `/note` Logging**: Append `/note <message>` to any query. The client automatically infers the target timestamp from your conversation and logs the note to `user_annotations.json`.
* **VLM-Powered `/summary` Command**: Type `/summary` to load all historical database annotations and conversation logs (ignoring time window filters) and trigger the local model to write a comprehensive natural-language synthesis of appliance signatures and server events.

### Setup and Running the CLI
1. Ensure the SQLite database and SolarEdge/Chillicon CSV files are synced to your local telemetry folder (defaults to `~/rainforest_db`).
2. Run your local VLM server or Ollama endpoint (e.g. `localhost:11434` running `gemma4-it-q4:latest`).
3. Set your configuration overrides in a `.env` file at the root level if different from default:
   ```env
   LOCAL_SERVER_URL=http://localhost:11434/api/chat
   OLLAMA_MODEL=gemma4-it-q4:latest
   RAINFOREST_SYNC_DIR=~/rainforest_db
   ```
4. Start the interactive REPL client:
   ```bash
   python3 repl_client.py
   ```
5. Run the logic validation tests:
   ```bash
   python3 test_repl_logic.py
   ```

---

## Multi-Sensor Microgrid Calibration & Metrology Accuracy

In a **non-homogeneous residential microgrid** combining multiple independent solar generation systems (such as an upstream AC-coupled Chilicon CP-100 / CP-720 microinverter array alongside a downstream DC-coupled SolarEdge hybrid inverter and battery), a single inverter's subpanel CT cannot see branch loads or solar backfeeds located upstream of its CT clamps.

By anchoring whole-home energy balance at the **Rainforest EMU-2 Utility Revenue Meter** (ANSI C12.20 `±0.5%` accuracy) and applying Kirchhoff's Current Law (KCL) across both solar arrays:

$$P_{\text{House Load}} = \max\!\left(0.0,\; P_{\text{EMU2}} + P_{\text{SolarEdge}} + P_{\text{Chilicon}} + P_{\text{Battery}}\right)$$

### Empirical 5-Sensor Calibration & Error Propagation Summary
Simultaneous cross-validation against an independent **200A Split-Core Mains CT (`Emporia Vue Gen 2`)** at the main distribution panel service lugs confirms sub-percent closure across all hardware telemetry streams:

| Derivation / Reference Frame | Formula | Measured / Derived Value | Uncertainty (`±3%` Solar) | Closure Delta |
| :--- | :--- | :--- | :--- | :--- |
| **Node A (Service Entrance Inflow)** | $P_{\text{Chilicon}}\;(1.687\text{ kW}) + P_{\text{EMU2}}\;(-0.648\text{ kW})$ | **`1.0390 kW`** (`1,039.0 W` predicted) vs. **`1.0324 kW`** (`Emporia 200A Mains CT`) | `±50.7 W` (RSS) | **`+6.6 W` (`0.64%`)** |
| **Node B (Whole-Home Load)** | $P_{\text{EMU2}}\;(-0.648) + P_{\text{Chilicon}}\;(1.687) + P_{\text{SolarEdge}}\;(0.358)$ | **`1.3970 kW`** (`1,397.0 W` KCL Balance) vs. **`1.3904 kW`** (`Emporia Mains + SolarEdge`) | `±51.8 W` (`±3.71%` RSS) / `±64.5 W` (`±4.62%` Linear) | **`+6.6 W` (`0.47%`)** |

See [calibration_test_report.md](calibration_test_report.md) for the complete 5-sensor KCL node analysis, AC RMS ($\sqrt{2}$) microinverter calibration verification, and $\pm 3\%$ error propagation math.
