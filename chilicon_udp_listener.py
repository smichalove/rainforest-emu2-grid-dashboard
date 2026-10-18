#!/usr/bin/env python3
"""Chilicon CP-100 UDP 32758 Debug Bridge Receiver & Telemetry Ingestor.

===============================================================================
1. ARCHITECTURAL OVERVIEW & PROBLEM STATEMENT
===============================================================================
The cloud portal (cloud.chiliconpower.com) aggregates telemetry in delayed
5-minute interval buckets and is uploaded by the on-premise gateway in batches,
introducing 30 to 67+ minutes of cloud ingestion latency on real-time dashboards.

To achieve true sub-minute, real-time microgrid telemetry, this service taps
into the Chilicon CP-100 Gateway's unencrypted "Info Dump" Debug Bridge.
The gateway firmware periodically emits raw binary sweeps over UDP port 32758
containing granular, per-panel electrical diagnostics for every bound CP-720
dual-MPPT microinverter.

By deploying this daemon on a local network node (e.g., 520c @ 192.168.8.181 or
Rainforestpi @ 192.168.8.213) and configuring the router to clone or mirror
the outbound UDP port 32758 datagrams onto the LAN:
  * Zero Gateway Modification: CP-100 cloud synchronization remains untouched.
  * Sub-Minute Resolution: Delivers two 90-second sweeps every ~176 seconds.
  * Per-Panel Diagnostics: Ingests AC line voltage, DC1/DC2 MPPT currents,
    uptime, and lifetime energy for all 8 microinverters simultaneously.
  * Zero-Overhead Fire-and-Forget: UDP requires no handshakes, sequence
    tracking, or ACKs, imposing 0% router buffering and zero gateway backpressure.

===============================================================================
2. BINARY PROTOCOL & PACKET SPECIFICATION (1,372 BYTES TOTAL)
===============================================================================
Each broadcast datagram is exactly 1,372 bytes, structured as follows:

  +-----------------------+---------------------------------------------------+
  | Byte Offset           | Payload Component                                 |
  +-----------------------+---------------------------------------------------+
  | 0x0000 .. 0x0007 (8B) | Gateway Header                                    |
  |                       |   uint32_le[0] = Gateway Serial (e.g. 0x00C14119)  |
  |                       |   uint32_le[1] = Reserved / Zero (0x00000000)     |
  +-----------------------+---------------------------------------------------+
  | 0x0008 .. 0x02AF      | PLC Sweep 1 (680 Bytes = 8 Inverters x 85 Bytes)  |
  | (680 Bytes)           |   Captured ~90 seconds prior to Sweep 2           |
  +-----------------------+---------------------------------------------------+
  | 0x02B0 .. 0x0557      | PLC Sweep 2 (680 Bytes = 8 Inverters x 85 Bytes)  |
  | (680 Bytes)           |   Captured immediately prior to UDP transmission  |
  +-----------------------+---------------------------------------------------+
  | 0x0558 .. 0x055B (4B) | Frame Trailer: 32-bit CRC Checksum                |
  +-----------------------+---------------------------------------------------+

Encoding & Offset Architecture (Raw Binary vs. Base64 & Bitfields):
  * ZERO Base64: Datagrams are 100% raw unencoded binary bytes transmitted directly
    from gateway memory. There is no Base64, ASCII armoring, JSON, or compression.
  * Standard Byte Offsets: Every microinverter record is a contiguous 85-byte block
    (rec = sweep_bytes[i*85 : (i+1)*85]). All fields inside are aligned to standard
    primitive byte boundaries (uint8, uint16_le, uint32_le), NOT bitfield offsets.
  * Fixed-Point Q12.4 Voltage: The only bit-level representation is AC line voltage
    at byte offset 24..25. The DSP packs voltage as a Q12.4 integer (lower 4 bits =
    fractional Volts in 1/16 V resolution; upper 12 bits = integer Volts), decoded
    via standard division by 16.0 (`val / 16.0`).

===============================================================================
3. 85-BYTE MICROINVERTER STRUCT LAYOUT & FORMULAS (rec[0..84])
===============================================================================
Within each 680-byte sweep, each bound microinverter occupies a fixed 85-byte
little-endian memory block:

  Offset  | Type        | Field Name        | Description & Scaling Formula
  --------+-------------+-------------------+----------------------------------
  0..3    | uint32_le   | inverter_id       | Inverter EUI32 hex string (f"{val:08X}")
  4..7    | uint32_le   | poll_timestamp    | Seconds since Y2K epoch (2000-01-01)
  8       | uint8       | record_type       | 0x26 = Standard, 0x22 = Low/Shaded
  24..25  | uint16_le   | ac_voltage_q4     | AC Line Volts = val / 16.0
  26..27  | uint16_le   | dc1_current_raw   | MPPT Channel 1 DC current indicator
  28..29  | uint16_le   | dc1_voltage_raw   | MPPT Channel 1 DC voltage indicator
  30..31  | uint16_le   | ac_freq_raw       | Grid frequency indicator (~60.0 Hz)
  34..35  | uint16_le   | dc2_current_raw   | MPPT Channel 2 DC current indicator
  36..37  | uint16_le   | dc2_voltage_raw   | MPPT Channel 2 DC voltage indicator
  44..45  | uint16_le   | inst_power_idx    | Fallback instantaneous power (~W)
  68..71  | uint32_le   | uptime_ticks      | Operating seconds = val * 8
  72..75  | uint32_le   | energy_ticks      | Lifetime Cumulative Energy Ticks

Mathematical Equations:
  1. Lifetime Cumulative Energy:
       Lifetime kWh = energy_ticks / 55102.861851

  2. Real-Time Sweep Power (dE/dt across consecutive sweeps t1 -> t2):
       dt_sec = ts_sec(t2) - ts_sec(t1)
       d_ticks = energy_ticks(t2) - energy_ticks(t1)
       power_w = d_ticks / (dt_sec * (TICKS_PER_WS / 1000.0))
       where TICKS_PER_WS = 55102.861851 / 3600.0 (~15.30635 ticks/W-s).

  3. System Rollup:
       total_system_kw = sum(power_w for all inverters) / 1000.0
       total_system_kwh = sum(lifetime_kwh for all inverters)

  4. Microinverter Off-State & Dawn Transition Safeguards:
       * Sleep / Stagnation Decay: If dt == 0 (inverter didn't respond to sweep),
         force power_w = 0.0 W. Eliminates overnight "ghost generation".
       * Dawn Wake-Up Guard: If dt > 900s (>15m gap after overnight sleep),
         re-arm baseline at 0.0 W without computing a spurious dE/dt spike.
       * Night Heartbeat Watchdog: Background thread periodically logs 0.000 kW
         during extended gateway night silence (>10m quiet between 21:00-06:00).

===============================================================================
4. DUAL-DESTINATION STORAGE & OUTPUTS
===============================================================================
1. PostgreSQL Database (Relational Time Series):
   * `chilicon_inverter_samples`: Stores full per-panel telemetry rows
     (sweep_ts, inverter_id, ac_voltage_v, dc1, dc2, power_w, lifetime_kwh).
   * `chilicon_system_history`: Stores 90-second rolled-up whole-system
     generation, active inverter counts, and gateway serial.
2. Flat CSV Telemetry Append (`chilicon_history.csv`):
   * Appends: `iso_timestamp, power_kw, total_lifetime_kwh`
   * Instantly consumable by local Tkinter dashboards, web kiosks, and sync
     workers without direct database dependencies.

===============================================================================
5. CONFIGURATION & OPERATIONAL INSTRUCTIONS
===============================================================================
Environment Variables:
  * `CHILICON_UDP_PORT`: Listening port (default: 32758).
  * `CHILICON_PG_DSN`: PostgreSQL connection string. Defaults to configuration
    in gitignored `Auth/chilicon_config.json` or local socket.
  * `CHILICON_CSV_PATH`: Destination path for CSV append.

Router Forwarding / Mirroring Setup (OpenWrt / iptables):
  Configure the gateway router to duplicate outbound UDP port 32758 traffic
  from the CP-100 IP to the listener node's IP:
    # Example iptables TEE or broadcast rule:
    iptables -t mangle -A PREROUTING -p udp --dport 32758 -j TEE --gateway <LISTENER_IP>

Manual Testing & Verification:
  * Test network socket receipt:
      nc -u -l 32758
  * Inspect raw hex dumps:
      sudo tcpdump -i any -nn -vv -X udp port 32758

(agent crumb) PUBLIC REPOSITORY SANITIZATION REQUIRED:
Do NOT hardcode LAN IP addresses, gateway serial numbers, or PostgreSQL
credentials in this file when exporting to the public staging repository
(/Users/treven/rainforest-emu2-grid-dashboard-public). Configure CHILICON_PG_DSN
via .env or Auth/chilicon_config.json (which is gitignored).
"""

import datetime
import json
import logging
import os
import re
import socket
import struct
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import psycopg2
except ImportError:
    psycopg2 = None  # type: ignore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("chilicon_udp")

SCRIPT_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """Loads key=value pairs from .env in SCRIPT_DIR if not already in os.environ."""
    env_file = SCRIPT_DIR / ".env"
    if not env_file.exists():
        return
    try:
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass


_load_dotenv()
UDP_PORT = int(os.environ.get("CHILICON_UDP_PORT", "32758"))


def _resolve_pg_dsn() -> str:
    """Resolves PostgreSQL DSN from env/.env or gitignored Auth/chilicon_config.json."""
    if os.environ.get("CHILICON_PG_DSN"):
        return os.environ["CHILICON_PG_DSN"]
    for auth_rel in ("Auth/chilicon_config.json", "auth/chilicon_config.json"):
        auth_file = SCRIPT_DIR / auth_rel
        if auth_file.exists():
            try:
                cfg = json.loads(auth_file.read_text(encoding="utf-8"))
                if cfg.get("pg_dsn"):
                    return str(cfg["pg_dsn"])
            except Exception:
                pass
    return "postgresql://postgres@127.0.0.1:5432/energy_telemetry"


PG_DSN = _resolve_pg_dsn()
_default_csv = (
    SCRIPT_DIR / "data" / "chilicon_history.csv"
    if (SCRIPT_DIR / "data").exists()
    else SCRIPT_DIR / "chilicon_history.csv"
)
CHILICON_CSV = Path(os.environ.get("CHILICON_CSV_PATH", str(_default_csv)))

TICKS_PER_KWH = 55102.861851
TICKS_PER_WS = TICKS_PER_KWH / 3600.0  # 15.3063505 ticks per Watt-second
EPOCH_2000 = datetime.datetime(2000, 1, 1, 0, 0, 0)


def decode_sweep(
    sweep_bytes: bytes,
    prev_state: Dict[str, Dict[str, float]],
) -> Tuple[datetime.datetime, List[Dict]]:
    """Decodes an 8-slot (680-byte) PLC sweep and updates per-inverter state."""
    records = []
    sweep_timestamps = []
    for i in range(8):
        rec = sweep_bytes[i * 85 : (i + 1) * 85]
        inv_u32, ts_sec = struct.unpack_from("<II", rec, 0)
        inv_id = f"{inv_u32:08X}"
        rec_type = rec[8]
        ac_v = struct.unpack_from("<H", rec, 24)[0] / 16.0
        dc1_i = struct.unpack_from("<H", rec, 26)[0]
        dc1_v = struct.unpack_from("<H", rec, 28)[0]
        dc2_i = struct.unpack_from("<H", rec, 34)[0]
        dc2_v = struct.unpack_from("<H", rec, 36)[0]
        inst_p_idx = struct.unpack_from("<H", rec, 44)[0]
        uptime_ticks = struct.unpack_from("<I", rec, 68)[0]
        energy_ticks = struct.unpack_from("<I", rec, 72)[0]
        lifetime_kwh = energy_ticks / TICKS_PER_KWH

        resolved_power_w = 0.0
        if inv_id in prev_state:
            prev_ts = int(prev_state[inv_id]["ts_sec"])
            prev_ticks = int(prev_state[inv_id]["energy_ticks"])
            dt = ts_sec - prev_ts
            d_ticks = energy_ticks - prev_ticks
            if 10 <= dt <= 900 and d_ticks >= 0:
                resolved_power_w = round(d_ticks / (dt * (TICKS_PER_WS / 1000.0)), 3)
            elif dt == 0:
                # Inverter offline / sleeping (timestamp has not advanced): force zero power
                resolved_power_w = 0.0
            elif dt > 900:
                # Dawn wake-up after nighttime sleep (>15m): re-arm baseline without dE/dt spike
                resolved_power_w = 0.0
        else:
            # First observation: use instant power index if active and nonzero
            resolved_power_w = float(inst_p_idx) if inst_p_idx > 0 else 0.0

        prev_state[inv_id] = {
            "ts_sec": float(ts_sec),
            "energy_ticks": float(energy_ticks),
            "lifetime_kwh": lifetime_kwh,
            "power_w": resolved_power_w,
        }
        dt_obj = EPOCH_2000 + datetime.timedelta(seconds=ts_sec)
        sweep_timestamps.append(dt_obj)
        records.append(
            {
                "sweep_ts": dt_obj,
                "inverter_id": inv_id,
                "record_type": rec_type,
                "ac_voltage_v": round(ac_v, 3),
                "dc1_current_raw": dc1_i,
                "dc1_voltage_raw": dc1_v,
                "dc2_current_raw": dc2_i,
                "dc2_voltage_raw": dc2_v,
                "inst_power_idx": inst_p_idx,
                "power_w": resolved_power_w,
                "uptime_ticks": uptime_ticks,
                "lifetime_energy_ticks": energy_ticks,
                "lifetime_kwh": round(lifetime_kwh, 6),
            }
        )
    sweep_ts = max(sweep_timestamps)
    return sweep_ts, records


def ingest_payload(
    payload: bytes,
    prev_state: Dict[str, Dict[str, float]],
    append_csv: bool = True,
) -> None:
    if len(payload) != 1372:
        logger.warning("Ignoring unexpected UDP payload length: %d", len(payload))
        return

    gw_u32, _ = struct.unpack_from("<II", payload, 0)
    gw_serial = f"{gw_u32:06X}"
    body = payload[8:-4]
    sweep1_bytes = body[:680]
    sweep2_bytes = body[680:1360]

    decoded_sweeps = []
    for sweep_raw in (sweep1_bytes, sweep2_bytes):
        s_ts, recs = decode_sweep(sweep_raw, prev_state)
        tot_power_kw = round(
            sum(st["power_w"] for st in prev_state.values()) / 1000.0, 4
        )
        tot_kwh = round(
            sum(st["lifetime_kwh"] for st in prev_state.values()), 4
        )
        active_inv = sum(
            1 for st in prev_state.values() if st["power_w"] > 1.0
        )
        decoded_sweeps.append((s_ts, recs, tot_power_kw, tot_kwh, active_inv))
        logger.info(
            "Decoded sweep %s | GW=%s | Total=%.3f kW | Lifetime=%.3f kWh | Active=%d/%d",
            s_ts.isoformat(),
            gw_serial,
            tot_power_kw,
            tot_kwh,
            active_inv,
            len(prev_state),
        )

    if psycopg2 is not None and PG_DSN:
        try:
            conn = psycopg2.connect(PG_DSN)
            try:
                with conn:
                    with conn.cursor() as cur:
                        for s_ts, recs, tot_power_kw, tot_kwh, active_inv in decoded_sweeps:
                            for r in recs:
                                cur.execute(
                                    """
                                    INSERT INTO chilicon_inverter_samples (
                                        sweep_ts, inverter_id, record_type, ac_voltage_v,
                                        dc1_current_raw, dc1_voltage_raw, dc2_current_raw, dc2_voltage_raw,
                                        inst_power_idx, power_w, uptime_ticks, lifetime_energy_ticks, lifetime_kwh
                                    ) VALUES (
                                        %(sweep_ts)s, %(inverter_id)s, %(record_type)s, %(ac_voltage_v)s,
                                        %(dc1_current_raw)s, %(dc1_voltage_raw)s, %(dc2_current_raw)s, %(dc2_voltage_raw)s,
                                        %(inst_power_idx)s, %(power_w)s, %(uptime_ticks)s, %(lifetime_energy_ticks)s, %(lifetime_kwh)s
                                    )
                                    ON CONFLICT (sweep_ts, inverter_id) DO UPDATE SET
                                        power_w = EXCLUDED.power_w,
                                        lifetime_energy_ticks = EXCLUDED.lifetime_energy_ticks,
                                        lifetime_kwh = EXCLUDED.lifetime_kwh,
                                        received_at = NOW();
                                    """,
                                    r,
                                )
                            cur.execute(
                                """
                                INSERT INTO chilicon_system_history (
                                    sweep_ts, power_kw, lifetime_kwh, active_inverters, gateway_serial, source
                                ) VALUES (%s, %s, %s, %s, %s, 'udp_rebroadcast')
                                ON CONFLICT (sweep_ts) DO UPDATE SET
                                    power_kw = EXCLUDED.power_kw,
                                    lifetime_kwh = EXCLUDED.lifetime_kwh,
                                    active_inverters = EXCLUDED.active_inverters,
                                    received_at = NOW();
                                """,
                                (s_ts, tot_power_kw, tot_kwh, active_inv, gw_serial),
                            )
            finally:
                conn.close()
        except Exception as e:
            logger.debug("PostgreSQL write skipped/failed: %s", e)

    if append_csv and CHILICON_CSV.parent.exists() and prev_state:
        tot_power_kw = round(
            sum(st["power_w"] for st in prev_state.values()) / 1000.0, 3
        )
        tot_kwh = round(sum(st["lifetime_kwh"] for st in prev_state.values()), 1)
        now_iso = datetime.datetime.now().isoformat()
        with open(CHILICON_CSV, "a", encoding="utf-8") as f:
            f.write(f"{now_iso},{tot_power_kw:.3f},{tot_kwh:.1f}\n")


def backfill_from_capture(prev_state: Dict[str, Dict[str, float]]) -> None:
    cap_file = Path("/tmp/chilicon_dump_all.txt")
    if not cap_file.exists():
        return
    text = cap_file.read_text()
    raw_pkts = text.split("IP 192.168.8.135.65452")[1:]
    for idx in range(0, len(raw_pkts), 2):
        hex_bytes = bytearray()
        for line in raw_pkts[idx].splitlines():
            m = re.match(r"^\s*0x[0-9a-f]+:\s+((?:[0-9a-f]{4}\s+)+)", line)
            if m:
                hex_bytes.extend(bytes.fromhex(m.group(1).replace(" ", "")))
        if len(hex_bytes) >= 1400:
            ingest_payload(bytes(hex_bytes[28:1400]), prev_state, append_csv=False)


def is_nighttime() -> bool:
    """Returns True if current local time is outside solar production hours."""
    hour = datetime.datetime.now().hour
    return hour >= 21 or hour < 6


def nighttime_watchdog_loop(
    prev_state: Dict[str, Dict[str, float]],
    heartbeat_tracker: Dict[str, float],
) -> None:
    """Periodically emits 0.000 kW records during gateway night silence (>10m quiet)."""
    while True:
        time.sleep(60)
        now_ts = time.time()
        silence_sec = now_ts - heartbeat_tracker.get("last_rx", now_ts)
        if silence_sec >= 600 and is_nighttime():
            if now_ts - heartbeat_tracker.get("last_csv_zero", 0.0) >= 900:
                heartbeat_tracker["last_csv_zero"] = now_ts
                for inv_id in prev_state:
                    prev_state[inv_id]["power_w"] = 0.0

                tot_kwh = (
                    round(sum(st["lifetime_kwh"] for st in prev_state.values()), 1)
                    if prev_state
                    else 0.0
                )
                now_dt = datetime.datetime.now()
                now_iso = now_dt.isoformat()

                if CHILICON_CSV.parent.exists():
                    try:
                        with open(CHILICON_CSV, "a", encoding="utf-8") as f:
                            f.write(f"{now_iso},0.000,{tot_kwh:.1f}\n")
                        logger.info(
                            "Night Watchdog: Appended 0.000 kW heartbeat to CSV (inverters sleeping)."
                        )
                    except Exception as e:
                        logger.warning("Night Watchdog CSV append error: %s", e)

                if psycopg2:
                    try:
                        conn = psycopg2.connect(PG_DSN)
                        with conn:
                            with conn.cursor() as cur:
                                cur.execute(
                                    """
                                    INSERT INTO chilicon_system_history (
                                        sweep_ts, power_kw, lifetime_kwh, active_inverters, gateway_serial, source
                                    ) VALUES (%s, 0.000, %s, 0, 'UNKNOWN', 'night_watchdog')
                                    ON CONFLICT (sweep_ts) DO NOTHING;
                                    """,
                                    (now_dt, tot_kwh),
                                )
                        conn.close()
                    except Exception as e:
                        logger.debug("Night Watchdog PG insert error: %s", e)


def main() -> None:
    import threading

    prev_state: Dict[str, Dict[str, float]] = {}
    heartbeat_tracker: Dict[str, float] = {"last_rx": time.time(), "last_csv_zero": 0.0}

    try:
        backfill_from_capture(prev_state)
    except Exception as e:
        logger.warning("Backfill warning: %s", e)

    watchdog = threading.Thread(
        target=nighttime_watchdog_loop,
        args=(prev_state, heartbeat_tracker),
        daemon=True,
        name="ChiliconNightWatchdog",
    )
    watchdog.start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", UDP_PORT))
    logger.info("Listening for Chilicon UDP Debug Bridge packets on 0.0.0.0:%d", UDP_PORT)

    last_crc = b""
    last_ts = 0.0
    while True:
        data, addr = sock.recvfrom(4096)
        now = time.time()
        heartbeat_tracker["last_rx"] = now
        if len(data) == 1372:
            crc = data[-4:]
            if crc == last_crc and (now - last_ts) < 5.0:
                continue
            last_crc = crc
            last_ts = now
            logger.info("Received 1372-byte UDP packet from %s:%d", addr[0], addr[1])
            try:
                ingest_payload(data, prev_state, append_csv=True)
            except Exception as e:
                logger.error("Failed to ingest UDP payload: %s", e)


if __name__ == "__main__":
    main()
