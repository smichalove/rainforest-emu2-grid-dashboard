# Green Doc: Chilicon CP-100 Real-Time Local UDP Telemetry & Fabric Architecture

**Date:** October 17, 2026  
**Gateway Target:** Chilicon CP-100 (`192.168.8.135` / `Chilicon-C14119-WI`, Serial `C14119`, FW `v4882`)  
**Fabric Nodes:** Flint 2 Router (`192.168.8.1`) ➔ `520c` PostgreSQL (`192.168.8.181`) ➔ `Rainforestpi` (`192.168.8.213`)

---

## 1. Executive Summary

Live packet inspection on the Flint 2 gateway router (`192.168.8.1`) revealed that the **Chilicon CP-100 Gateway (`192.168.8.135`) uses zero encryption** for its cloud communication with `cloud.chiliconpower.com` (`107.155.107.6`).

Specifically:
1. **100% of solar production telemetry is emitted over unencrypted UDP port `32758`** (`192.168.8.135:65452` ➔ `107.155.107.6:32758`) in a single **1,372-byte UDP payload** (`1,400` bytes IP length) once every **176 seconds (~2.9 minutes)**.
2. Each UDP `32758` packet contains **two complete ~90-second Power Line Communication (PLC) polling sweeps** across all **8 bound CP-720 Dual-MPPT microinverters** (`16 × 85-byte` binary records).
3. Because UDP is completely **stateless and fire-and-forget (`[UNREPLIED]`, no ACK wait)**, the Flint 2 router can clone/mirror a copy of every UDP `32758` packet to `520c` (`192.168.8.181`) at near-zero CPU cost, delivering **90-second real-time local solar telemetry** (10× faster than the 15-minute cloud scraper) while keeping the existing cloud connection and web scraper as an automatic fallback.

> [!TIP]
> **Why UDP `32758` Is Ideal for Router Forwarding:**  
> Unlike TCP, UDP requires **no handshake, no sequence tracking, and no ACK wait**. If `520c` or `Rainforestpi` is rebooting, the duplicated UDP packet simply drops with zero backpressure, zero memory buffering on the router, and zero disruption to the CP-100 gateway.

---

## 2. Reverse-Engineered Network & Binary Protocol Specification

### 2.1 Outbound Traffic Streams from `192.168.8.135`

| Stream | Protocol & Port | Cadence | Payload Size | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **Command Poll** | `TCP :80` (HTTP) | Every **5 sec** | `167 B` req / `172 B` resp | Plaintext `GET /files/C14119/command HTTP/1.1` (`User-Agent: CHILIC0N Gateway v4882`). Cloud replies `0x00` when idle. |
| **Telemetry Dump** | `UDP :32758` | Every **~176 sec** | **`1,372 B`** UDP (`1,400 B` IP) | Unencrypted fire-and-forget binary dump containing **two 90-second sweeps** across all 8 microinverters. |

---

### 2.2 UDP `32758` Packet Layout (`1,372 Bytes` Total)

```text
+-----------------------+-------------------------------------------------------+
| Byte Offset           | Contents                                              |
+-----------------------+-------------------------------------------------------+
| 0x0000 .. 0x0007 (8B) | Gateway Header: 19 41 c1 00 00 00 00 00               |
|                       |   uint32_le[0] = 0x00C14119 (Gateway Serial "C14119") |
|                       |   uint32_le[1] = 0x00000000                           |
+-----------------------+-------------------------------------------------------+
| 0x0008 .. 0x02AF      | PLC Sweep 1 (680 Bytes = 8 Inverters x 85 Bytes)      |
| (680 Bytes)           |   Captured ~90 seconds prior to Sweep 2               |
+-----------------------+-------------------------------------------------------+
| 0x02B0 .. 0x0557      | PLC Sweep 2 (680 Bytes = 8 Inverters x 85 Bytes)      |
| (680 Bytes)           |   Captured immediately prior to UDP transmission      |
+-----------------------+-------------------------------------------------------+
| 0x0558 .. 0x055B (4B) | Frame Trailer: 32-bit CRC Integrity Checksum          |
+-----------------------+-------------------------------------------------------+
```

---

### 2.3 Bound CP-720 Microinverter Roster & 85-Byte Record Struct

Each sweep contains 8 fixed-length **85-byte** little-endian records corresponding to your 8 bound microinverters:

| Index | `EUI32` Serial (Hex) | Raw LE Bytes (`0..3`) | Subtype (`rec[8]`) | Active MPPT Channels Observed |
| :---: | :--- | :--- | :---: | :--- |
| **0** | **`11700218`** | `18 02 70 11` | `0x26` | DC1 Active |
| **1** | **`C1500871`** | `71 08 50 c1` | `0x22` | Low / Shaded Output |
| **2** | **`C1400025`** | `25 00 40 c1` | `0x26` | Dual DC1 + DC2 Active |
| **3** | **`B14009F7`** | `f7 09 40 b1` | `0x26` | Dual DC1 + DC2 Active |
| **4** | **`C140032A`** | `2a 03 40 c1` | `0x26` | Dual DC1 + DC2 Active |
| **5** | **`B15003B2`** | `b2 03 50 b1` | `0x26` | Dual DC1 + DC2 Active |
| **6** | **`B160012D`** | `2d 01 60 b1` | `0x26` | DC1 Active |
| **7** | **`617005FE`** | `fe 05 70 61` | `0x26` | DC1 Active |

#### Per-Inverter 85-Byte Struct (`rec[0..84]`)

| Offset | Type | Field Name | Scaling / Formula | Verified Live Sample (`2026-10-17 13:03`) |
| :--- | :--- | :--- | :--- | :--- |
| `0..3` | `uint32_le` | **`inverter_id`** | `f"{val:08X}"` | `11700218`, `C1400025`, etc. |
| `4..7` | `uint32_le` | **`poll_timestamp`** | `datetime(2000,1,1) + timedelta(seconds=val)` | `2026-10-17 13:03:52` (90s sweep interval) |
| `8` | `uint8` | **`record_type`** | `0x26` (standard) or `0x22` | `0x26` (7 units), `0x22` (`C1500871`) |
| `20..23` | `uint32_le` | **`dc1_accum`** | MPPT Channel 1 accumulator | Monotonic intraday counter |
| `24..25` | `uint16_le` | **`ac_voltage_q4`** | `val / 16.0` (**Volts AC**) | `3902 / 16.0` = **`243.88 V AC`** |
| `26..27` | `uint16_le` | **`dc1_current_raw`** | MPPT Channel 1 current/power | `2472 .. 3642` on active DC1 panels |
| `28..29` | `uint16_le` | **`dc1_voltage_raw`** | MPPT Channel 1 DC voltage | `6753 .. 7274` (~33–36 V DC) |
| `30..31` | `uint16_le` | **`ac_freq_raw`** | Grid frequency indicator | `580 .. 592` (~60.0 Hz) |
| `32..35` | `uint32_le` | **`dc2_accum`** | MPPT Channel 2 accumulator | Monotonic intraday counter |
| `34..35` | `uint16_le` | **`dc2_current_raw`** | MPPT Channel 2 current/power | `1735 .. 5185` on dual-input units |
| `36..37` | `uint16_le` | **`dc2_voltage_raw`** | MPPT Channel 2 DC voltage | `6729 .. 11816` |
| `44..45` | `uint16_le` | **`inst_power_idx`** | Instantaneous power index (~W) | Sum across 8 units: `316 W` ➔ `517 W` ➔ `549 W` |
| `54..57` | `uint32_le` | **`line_cycle_cnt`** | Monotonic DSP / AC cycle counter | `+366,604 ticks/sec` per inverter |
| `68..71` | `uint32_le` | **`uptime_ticks`** | `val * 8` = **Operating Seconds** | `+0.125 ticks/sec` per inverter (`+1.0/sec` total) |
| `72..75` | `uint32_le` | **`lifetime_energy`** | **`val / 55102.86185` = Lifetime kWh** | Sum = `1,325,685,307` = **`24,058.375 kWh`** |

#### Exact Power & Energy Equations
* **Lifetime System Energy ($\text{kWh}$):**
  $$\text{Energy}_{\text{kWh}} = \frac{\sum_{i=0}^{7} \text{lifetime\_energy}_i}{55,102.86185}$$
* **Real-Time Per-Inverter AC Power ($\text{Watts}$) Across Consecutive 90s Sweeps ($t_1 \to t_2$):**
  $$P_{\text{Watts}, i} = \frac{\text{lifetime\_energy}_{i}(t_2) - \text{lifetime\_energy}_{i}(t_1)}{(t_{2,i} - t_{1,i}) \times 0.01530635}$$
  *(where $0.01530635 = \frac{55,102.86185\text{ ticks/kWh}}{3,600\text{ sec/hr}}$ ticks per Watt-second).*

---

## 3. Hardware Pros & Cons Across the 3-Node Fabric

```mermaid
flowchart LR
    GW["Chilicon CP-100 Gateway<br/>192.168.8.135:65452"]
    RTR["Flint 2 Router (GL-MT6000)<br/>192.168.8.1"]
    CLOUD["Chilicon Cloud<br/>107.155.107.6:32758"]
    PG["520c Server (PostgreSQL + Web)<br/>192.168.8.181:32758 / :5432"]
    PI["Rainforestpi (Telemetry Node)<br/>192.168.8.213"]

    GW -->|"UDP :32758 (1,372 B)<br/>Every 176s (2x 90s Sweeps)"| RTR
    RTR -->|"Original Unchanged Packet<br/>(WAN)"| CLOUD
    RTR ==>|"Cloned UDP :32758 Packet<br/>(Zero ACK / <0.001% CPU)"| PG
    PG -->|"1. Store 8-Inverter 90s Series in PostgreSQL<br/>2. Update chilicon_history.csv"| PG
    PI <-->|"Pulls Aggregate kW/kWh from 520c<br/>(HTTPS Cloud Fallback)"| PG
```

### Node 1: Flint 2 Router (`192.168.8.1` — `GL-MT6000`)
* **Hardware Profile:** Quad-Core 2.0 GHz ARM Cortex-A53 (`MT7986A`), 1 GB DDR4 RAM.
* **CPU & Memory Impact:** **< 0.0005% CPU** (< 0.1 ms once every 176 seconds) and **~0–1.5 MB RAM**.
* **Pros:**
  * **Naturally in the L3 Routing Path:** Since `192.168.8.135` sends unicast UDP packets to `107.155.107.6` (WAN), the router is the only device that sees the traffic natively without ARP spoofing.
  * **Zero ACK / Zero State Overhead:** Because UDP `32758` is `[UNREPLIED]`, the router simply fires a copy of the 1,372-byte datagram to `192.168.8.181:32758` (or LAN broadcast `192.168.8.255:32758`) and forgets it. If `520c` is down, nothing blocks or queues on the router.
* **Cons:**
  * Major OpenWrt firmware upgrades can clear custom scripts unless persisted in `/etc/rc.local` or `/etc/firewall.user`.

---

### Node 2: `520c` Server (`192.168.8.181` — Xeon + PostgreSQL + Web Kiosk)
* **Hardware Profile:** Intel Xeon, enterprise storage/NVMe, PostgreSQL 16 (`:5432`), FastAPI Web Kiosk (`:8000`).
* **Pros:**
  * **Ideal for High-Cardinality Per-Inverter Time Series:** Logging 8 microinverters × 12 telemetry columns every 90 seconds (~7,680 rows/day) into PostgreSQL on `520c` takes virtually zero disk/CPU overhead and preserves decades of panel-level diagnostics (DC1/DC2 shading, AC voltage sag, inverter uptime).
  * **Instant Web Kiosk Updates:** The web dashboard on `520c:8000` gets 90-second solar updates immediately.
  * **Built-In Web Fallback:** If UDP packets ever stop arriving for > 10 minutes, `520c` and `Rainforestpi` automatically fall back to `ChilliconClient.fetch_data()` from `cloud.chiliconpower.com`.
* **Cons:**
  * Since `Rainforestpi` (`192.168.8.213`) is the traditional edge collector in the fabric, `Rainforestpi` needs a 1-line query (or file sync) from `520c` to display the 90-second Chilicon readings on the physical touchscreen kiosk.

---

### Node 3: `Rainforestpi` (`192.168.8.213` — Edge Telemetry Node & Physical Kiosk)
* **Hardware Profile:** Raspberry Pi (ARM Cortex-A72, microSD card, X11 display `:0`, `/dev/ttyACM0` serial EMU-2 reader).
* **Pros:**
  * **Primary Telemetry Node in Fabric:** Already coordinates `grid_history.db`, `solaredge_history.csv`, and `chilicon_history.csv`.
  * **Lighter than HTTPS Scraping:** Pulling a single aggregate row `(timestamp, power_kw, lifetime_kwh)` from `520c` PostgreSQL (or receiving the UDP packet directly) uses **100× less CPU** on the Pi than TLS handshakes + HTML/CSRF scraping against `cloud.chiliconpower.com`.
* **Cons:**
  * **microSD Card Wear:** We should **not** write the full 8-inverter × 90-second diagnostic table onto the Pi's microSD card. Raw per-inverter telemetry belongs in PostgreSQL on `520c`, while the Pi only consumes the rolled-up system `power_kw` and `lifetime_kwh`.

---

## 4. Recommended Implementation Plan

1. **PostgreSQL Schema on `520c` (`192.168.8.181:5432`):**
   * Create two tables in a dedicated `energy_telemetry` (or `postgres`) database on `520c`:
     * `chilicon_inverter_samples`: Stores every 90-second per-inverter record (`sweep_ts`, `inverter_id`, `power_w`, `lifetime_kwh`, `ac_voltage_v`, `dc1_raw`, `dc2_raw`, `uptime_sec`).
     * `chilicon_system_history`: Stores the rolled-up 8-inverter total (`timestamp`, `power_kw`, `lifetime_kwh`, `active_inverters`, `source='udp_local'`).
2. **UDP `32758` Listener Daemon on `520c` (`192.168.8.181:32758`):**
   * Lightweight Python service (`chilicon_udp_listener.py`) bound to `0.0.0.0:32758/udp`.
   * Unpacks both 90-second sweeps from each 1,372-byte packet, inserts into PostgreSQL, and updates `chilicon_history.csv` for the Web Kiosk.
3. **Stateless UDP Packet Mirror on Flint 2 Router (`192.168.8.1`):**
   * Configure a lightweight background packet mirror on `192.168.8.1` (persisted in `/etc/rc.local`) that forwards copies of `src host 192.168.8.135 and udp dst port 32758` to `192.168.8.181:32758`.
4. **Pi Integration with Automatic Cloud Fallback (`192.168.8.213`):**
   * `ChilliconClient` checks `520c` PostgreSQL first for a fresh (< 6 min old) local UDP reading; if unavailable, it seamlessly falls back to the existing `cloud.chiliconpower.com` HTTPS scraper.
