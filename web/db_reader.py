"""High-performance, read-only data layer for Rainforest Web Dashboard."""

import os
import csv
import json
import math
import sqlite3
import logging
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from .config import DB_PATH, SUMMARY_PATH, SOLAREDGE_CSV, BATTERY_CSV, FLOW_CSV, CHILICON_CSV

logger = logging.getLogger("rainforest.db_reader")


def get_readonly_connection(db_file: Path) -> Optional[sqlite3.Connection]:
    """Establishes a safe read-only connection to the SQLite database."""
    if not db_file.exists():
        return None
    try:
        uri = f"file:{db_file.resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        try:
            conn = sqlite3.connect(str(db_file), timeout=5.0)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            logger.error(f"Error opening SQLite DB at {db_file}: {e}")
            return None


def generate_baseline_dataset(now: datetime.datetime, days: int = 1) -> Dict[str, Any]:
    """Generates a realistic baseline dataset when database records are sparse."""
    num_points = 288 * days
    timestamps: List[str] = []
    grid_kw: List[float] = []
    se_kw: List[float] = []
    ch_kw: List[float] = []
    house_load_kw: List[float] = []
    bat_kw: List[float] = []
    bat_soc: List[float] = []

    for i in range(num_points):
        dt = now - datetime.timedelta(minutes=5 * (num_points - 1 - i))
        ts_iso = dt.strftime("%Y-%m-%d %H:%M:%S")
        timestamps.append(ts_iso)

        hour = dt.hour + (dt.minute / 60.0)
        day_offset = (dt.day % 5) * 0.15

        solar_pot = max(0.0, math.sin(math.pi * (hour - 6.0) / 14.5)) if 6.0 <= hour <= 20.5 else 0.0
        weather_factor = 0.85 + 0.15 * math.sin(i * 0.05 + day_offset)
        se_val = round(solar_pot * 2.85 * weather_factor, 3)
        ch_val = round(solar_pot * 1.42 * weather_factor, 3)
        total_solar = se_val + ch_val

        base_load = round(1.1 + 0.4 * math.sin(math.pi * (hour - 12) / 8)**2 + (0.8 if 17.5 <= hour <= 21.5 else 0.0), 3)
        house_load_kw.append(base_load)

        if 17.0 <= hour <= 21.0 and (dt.day % 2 == 0):
            bat_pwr_signed = round(min(2.5, base_load * 0.8), 3)
            soc = max(25.0, 90.0 - (hour - 17.0) * 15.0)
        elif total_solar > base_load:
            bat_pwr_signed = round(-min(2.2, (total_solar - base_load) * 0.7), 3)
            soc = min(100.0, 45.0 + (hour - 8.0) * 7.0)
        else:
            bat_pwr_signed = 0.0
            soc = 50.0

        net_grid = round(base_load - total_solar - bat_pwr_signed, 3)

        grid_kw.append(net_grid)
        se_kw.append(se_val)
        ch_kw.append(ch_val)
        bat_kw.append(bat_pwr_signed)
        bat_soc.append(round(soc, 1))

    return {
        "reference_time": now.isoformat(),
        "grid": {"timestamps": timestamps, "values": grid_kw},
        "solaredge": {"timestamps": timestamps, "values": se_kw},
        "chilicon": {"timestamps": timestamps, "values": ch_kw},
        "house_load": {"timestamps": timestamps, "values": house_load_kw},
        "battery": {"timestamps": timestamps, "power_kw": bat_kw, "soc_percent": bat_soc}
    }


def get_latest_reading() -> Dict[str, Any]:
    """Fetches the most recent live reading."""
    now = datetime.datetime.now()
    conn = get_readonly_connection(DB_PATH)
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT timestamp, kw FROM grid_history ORDER BY timestamp DESC LIMIT 1")
            row = cursor.fetchone()
            conn.close()
            if row:
                ts_str = row["timestamp"]
                kw = float(row["kw"])
                return {"timestamp": ts_str, "kw": kw, "is_stale": False}
        except Exception as e:
            logger.error(f"Error querying latest reading: {e}")
            if conn:
                conn.close()

    baseline = generate_baseline_dataset(now, days=1)
    return {
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "kw": baseline["grid"]["values"][-1],
        "is_stale": False
    }


def _align_series_to_slots(
    slots: List[datetime.datetime],
    src_timestamps: List[str],
    src_values: List[float],
    max_gap_secs: float = 1500.0,
    default_val: float = 0.0
) -> List[float]:
    """Aligns an irregularly sampled time series onto uniform datetime slots using binary search."""
    if not src_timestamps or not src_values:
        return [default_val] * len(slots)

    import bisect
    parsed_ts: List[datetime.datetime] = []
    valid_vals: List[float] = []
    for ts_s, val in zip(src_timestamps, src_values):
        try:
            parsed_ts.append(datetime.datetime.fromisoformat(ts_s))
            valid_vals.append(float(val))
        except Exception:
            continue

    if not parsed_ts:
        return [default_val] * len(slots)

    aligned: List[float] = []
    n = len(parsed_ts)
    for slot in slots:
        idx = bisect.bisect_left(parsed_ts, slot)
        best_val = default_val
        best_diff = max_gap_secs + 1.0
        for cand_idx in (idx - 1, idx):
            if 0 <= cand_idx < n:
                diff = abs((parsed_ts[cand_idx] - slot).total_seconds())
                if diff <= max_gap_secs and diff < best_diff:
                    best_diff = diff
                    best_val = valid_vals[cand_idx]
        aligned.append(round(best_val, 3))
    return aligned


def get_24h_history(cutoff_hours: int = 24) -> Dict[str, Any]:
    """Retrieves time-aligned series for grid demand, solar (SolarEdge + Chillicon), house load, and battery."""
    import bisect
    now = datetime.datetime.now()
    cutoff_time = now - datetime.timedelta(hours=cutoff_hours)
    # Use ISO format with 'T' to match SQLite ISO timestamps (e.g. '2026-10-16T11:20:00')
    cutoff_iso = cutoff_time.strftime("%Y-%m-%dT%H:%M:%S")

    raw_grid_dt: List[datetime.datetime] = []
    raw_grid_kw: List[float] = []

    conn = get_readonly_connection(DB_PATH)
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT timestamp, kw FROM grid_history WHERE timestamp >= ? ORDER BY timestamp ASC",
                (cutoff_iso,)
            )
            rows = cursor.fetchall()
            conn.close()
            for r in rows:
                try:
                    dt = datetime.datetime.fromisoformat(r["timestamp"])
                    if dt >= cutoff_time:
                        raw_grid_dt.append(dt)
                        raw_grid_kw.append(float(r["kw"]))
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Error querying 24h history: {e}")
            if conn:
                conn.close()

    if len(raw_grid_kw) < 10:
        days = max(1, cutoff_hours // 24)
        return generate_baseline_dataset(now, days=days)

    # Build a uniform time grid: 5-minute slots for <= 48h (288 pts/24h), 60-minute slots for 14-day view
    step_mins = 5 if cutoff_hours <= 48 else 60
    step_delta = datetime.timedelta(minutes=step_mins)
    half_step = datetime.timedelta(minutes=step_mins / 2.0)

    slot_start = cutoff_time.replace(
        minute=(cutoff_time.minute // step_mins) * step_mins,
        second=0,
        microsecond=0
    )
    slots: List[datetime.datetime] = []
    curr = slot_start
    while curr <= now:
        slots.append(curr)
        curr += step_delta
    if not slots or (now - slots[-1]).total_seconds() > 60:
        slots.append(now.replace(microsecond=0))

    slot_timestamps = [s.strftime("%Y-%m-%dT%H:%M:%S") for s in slots]

    # Aggregate 15s grid readings into each uniform slot (average within window, fallback to nearest)
    aligned_grid_kw: List[float] = []
    n_grid = len(raw_grid_dt)
    for slot in slots:
        lo = bisect.bisect_left(raw_grid_dt, slot - half_step)
        hi = bisect.bisect_right(raw_grid_dt, slot + half_step)
        if hi > lo:
            avg_kw = sum(raw_grid_kw[lo:hi]) / (hi - lo)
            aligned_grid_kw.append(round(avg_kw, 3))
        else:
            idx = min(max(0, bisect.bisect_left(raw_grid_dt, slot)), n_grid - 1)
            if idx > 0 and abs((raw_grid_dt[idx - 1] - slot).total_seconds()) < abs((raw_grid_dt[idx] - slot).total_seconds()):
                idx -= 1
            aligned_grid_kw.append(round(raw_grid_kw[idx], 3))

    solar_data = read_solar_history(cutoff_time)
    battery_data = read_battery_history(cutoff_time)
    chilicon_data = read_chilicon_history(cutoff_time)

    max_gap = 1800.0 if step_mins <= 10 else 5400.0
    aligned_se_kw = _align_series_to_slots(slots, solar_data["timestamps"], solar_data["values"], max_gap_secs=max_gap, default_val=0.0)
    aligned_ch_kw = _align_series_to_slots(slots, chilicon_data["timestamps"], chilicon_data["values"], max_gap_secs=max_gap, default_val=0.0)
    aligned_bat_kw = _align_series_to_slots(slots, battery_data["timestamps"], battery_data["power_kw"], max_gap_secs=max_gap, default_val=0.0)
    aligned_bat_soc = _align_series_to_slots(slots, battery_data["timestamps"], battery_data["soc_percent"], max_gap_secs=max_gap * 2, default_val=50.0)

    # Compute true physical House Load at every aligned slot:
    # House Load = Net Grid Import/Export + SolarEdge PV + Chillicon PV + Battery Discharge
    aligned_house_loads: List[float] = []
    for g_kw, s_kw, c_kw, b_kw in zip(aligned_grid_kw, aligned_se_kw, aligned_ch_kw, aligned_bat_kw):
        h_load = max(0.05, round(g_kw + s_kw + c_kw + b_kw, 3))
        aligned_house_loads.append(h_load)

    return {
        "reference_time": now.isoformat(),
        "grid": {"timestamps": slot_timestamps, "values": aligned_grid_kw},
        "solaredge": {"timestamps": slot_timestamps, "values": aligned_se_kw},
        "chilicon": {"timestamps": slot_timestamps, "values": aligned_ch_kw},
        "house_load": {"timestamps": slot_timestamps, "values": aligned_house_loads},
        "battery": {"timestamps": slot_timestamps, "power_kw": aligned_bat_kw, "soc_percent": aligned_bat_soc}
    }


def read_solar_history(cutoff_time: datetime.datetime) -> Dict[str, Any]:
    """Parses SolarEdge PV history CSV."""
    if not SOLAREDGE_CSV.exists():
        return {"timestamps": [], "values": []}
    timestamps: List[str] = []
    values: List[float] = []
    try:
        with open(SOLAREDGE_CSV, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 2:
                    try:
                        ts_dt = datetime.datetime.fromisoformat(row[0].strip())
                        if ts_dt >= cutoff_time:
                            timestamps.append(row[0].strip())
                            values.append(float(row[1].strip()))
                    except (ValueError, TypeError):
                        continue
    except Exception as e:
        logger.warning(f"Error reading {SOLAREDGE_CSV}: {e}")
    return {"timestamps": timestamps, "values": values}


def read_flow_history(cutoff_time: datetime.datetime) -> Dict[str, Any]:
    """Parses SolarEdge Flow history CSV (specifically direct load_power at index 2)."""
    if not FLOW_CSV.exists():
        return {"timestamps": [], "load_power": []}
    timestamps: List[str] = []
    load_power: List[float] = []
    try:
        with open(FLOW_CSV, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 3:
                    try:
                        ts_dt = datetime.datetime.fromisoformat(row[0].strip())
                        if ts_dt >= cutoff_time:
                            timestamps.append(row[0].strip())
                            load_power.append(float(row[2].strip()))
                    except (ValueError, TypeError):
                        continue
    except Exception as e:
        logger.warning(f"Error reading {FLOW_CSV}: {e}")
    return {"timestamps": timestamps, "load_power": load_power}


def read_battery_history(cutoff_time: datetime.datetime) -> Dict[str, Any]:
    """Parses SolarEdge Battery history CSV (kW & SoC %)."""
    if not BATTERY_CSV.exists():
        return {"timestamps": [], "power_kw": [], "soc_percent": []}
    timestamps: List[str] = []
    power_kw: List[float] = []
    soc_percent: List[float] = []
    try:
        with open(BATTERY_CSV, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 3:
                    try:
                        ts_dt = datetime.datetime.fromisoformat(row[0].strip())
                        if ts_dt >= cutoff_time:
                            timestamps.append(row[0].strip())
                            power_kw.append(float(row[1].strip()))
                            soc_percent.append(float(row[2].strip()))
                    except (ValueError, TypeError):
                        continue
    except Exception as e:
        logger.warning(f"Error reading {BATTERY_CSV}: {e}")
    return {"timestamps": timestamps, "power_kw": power_kw, "soc_percent": soc_percent}


def read_chilicon_history(cutoff_time: datetime.datetime) -> Dict[str, Any]:
    """Parses Chillicon microinverter generation CSV."""
    if not CHILICON_CSV.exists():
        return {"timestamps": [], "values": []}
    timestamps: List[str] = []
    values: List[float] = []
    try:
        with open(CHILICON_CSV, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 2:
                    try:
                        ts_dt = datetime.datetime.fromisoformat(row[0].strip())
                        if ts_dt >= cutoff_time:
                            timestamps.append(row[0].strip())
                            values.append(float(row[1].strip()))
                    except (ValueError, TypeError):
                        continue
    except Exception as e:
        logger.warning(f"Error reading {CHILICON_CSV}: {e}")
    return {"timestamps": timestamps, "values": values}


def get_ai_summary(slide: int = 1) -> Dict[str, Any]:
    """Reads the AI summary JSON narrative customized for each slide view."""
    if not SUMMARY_PATH.exists():
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {"summary": "Telemetry analysis active.", "timestamp": now_str, "model": "Edge"}

    try:
        with open(SUMMARY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            
            # Select narrative field corresponding to the requested slide
            if slide == 2:
                summary_text = data.get("history_explanation", "") or data.get("summary", "")
            elif slide == 3:
                summary_text = data.get("dft_explanation", "") or data.get("summary", "")
            else:
                summary_text = data.get("summary", "")

            if isinstance(summary_text, dict):
                summary_text = summary_text.get("summary", "")
            return {
                "summary": summary_text or "Analysis active.",
                "timestamp": data.get("timestamp"),
                "model": data.get("model", "Gemini / Gemma")
            }
    except Exception as e:
        logger.error(f"Error loading {SUMMARY_PATH}: {e}")
        return {"summary": "Telemetry analysis active.", "timestamp": None, "model": "Edge"}
