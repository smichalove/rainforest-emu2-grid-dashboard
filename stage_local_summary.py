import os
import json
import time
import datetime
import csv
import statistics
import sys
import urllib.request
import urllib.error
import http.server
import socketserver
import math
import logging
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# -------------------------------------------------------------
# Configuration Constants
# -------------------------------------------------------------
SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR: str = os.environ.get("JETSON_BACKUP_PATH") or os.path.join(SCRIPT_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

# Local Telemetry CSV History Paths (read from SCP backup directory)
GRID_HISTORY: str = os.path.join(BACKUP_DIR, "grid_history.csv")
SE_HISTORY: str = os.path.join(BACKUP_DIR, "solaredge_history.csv")
SE_BATTERY_HISTORY: str = os.path.join(BACKUP_DIR, "solaredge_battery_history.csv")
SE_FLOW_HISTORY: str = os.path.join(BACKUP_DIR, "solaredge_flow_history.csv")
CHILICON_HISTORY: str = os.path.join(BACKUP_DIR, "chilicon_history.csv")

# Model configuration
DEFAULT_MODEL: str = os.environ.get("EDGE_MODEL", "gemma4-it-q4")
OLLAMA_ENDPOINT: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434/api/generate")

# Default coordinates for weather (Seattle area)
DEFAULT_LAT: str = os.environ.get("WEATHER_LAT", "47.6062")
DEFAULT_LON: str = os.environ.get("WEATHER_LON", "-122.3321")

# Well-known typical (sunrise, sunset) time strings for Seattle area by month.
# Used as a robust fallback when the weather API is unreachable or rate-limited.
SEATTLE_MONTHLY_DAYLIGHT_FALLBACKS: Dict[int, Tuple[str, str]] = {
    1: ("08:00", "16:30"),   # January
    2: ("07:30", "17:25"),   # February
    3: ("07:20", "19:15"),   # March (using average DST-adjusted times)
    4: ("06:15", "20:00"),   # April
    5: ("05:35", "20:45"),   # May
    6: ("05:10", "21:10"),   # June
    7: ("05:30", "21:00"),   # July
    8: ("06:10", "20:15"),   # August
    9: ("06:50", "19:15"),   # September
    10: ("07:35", "18:15"),  # October
    11: ("07:20", "16:40"),  # November
    12: ("07:50", "16:20"),  # December
}


def parse_timestamp(ts_str: str) -> Optional[datetime.datetime]:
    """Robust parser for naive datetime strings."""
    ts_str = ts_str.strip().replace('\x00', '')
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f"
    ):
        try:
            return datetime.datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    try:
        return datetime.datetime.fromisoformat(ts_str)
    except ValueError:
        return None


WEATHER_CACHE_FILE: str = os.path.join(SCRIPT_DIR, "weather_cache.json")

def fetch_weather(lat: str = DEFAULT_LAT, lon: str = DEFAULT_LON) -> Tuple[Optional[float], Optional[float], Optional[str], Optional[str]]:
    """Fetches today's weather forecast (max temp, cloud cover, sunrise, sunset) from Open-Meteo API with caching and fail-safe fallbacks."""
    now = time.time()
    
    # Check if we have a valid cache file
    cached_data = None
    if os.path.exists(WEATHER_CACHE_FILE):
        try:
            with open(WEATHER_CACHE_FILE, "r") as f:
                cached_data = json.load(f)
        except Exception:
            pass
            
    # Query API only if cache is older than 60 minutes (3600 seconds) or does not exist
    should_fetch = True
    if cached_data:
        cache_time = cached_data.get("timestamp", 0.0)
        if now - cache_time < 3600.0:
            should_fetch = False
            
    if not should_fetch and cached_data:
        logging.info("Using cached weather forecast on Jetson.")
        return (
            cached_data.get("temp_max"),
            cached_data.get("cloud_cover"),
            cached_data.get("sunrise"),
            cached_data.get("sunset")
        )

    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=temperature_2m_max,cloud_cover_mean,sunrise,sunset&timezone=auto"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode('utf-8'))
            daily = res.get("daily", {})
            temp_max = daily.get("temperature_2m_max", [None])[0]
            cloud_cover = daily.get("cloud_cover_mean", [None])[0]
            sunrise = daily.get("sunrise", [None])[0]
            sunset = daily.get("sunset", [None])[0]
            
            # If the response parsed successfully but contains empty/null arrays,
            # raise a ValueError to force cache/default fallback execution.
            if temp_max is None or cloud_cover is None:
                raise ValueError("API returned null parameters for weather indicators")
            
            # Save to cache file on success
            try:
                with open(WEATHER_CACHE_FILE, "w") as f:
                    json.dump({
                        "timestamp": now,
                        "temp_max": temp_max,
                        "cloud_cover": cloud_cover,
                        "sunrise": sunrise,
                        "sunset": sunset
                    }, f)
            except Exception as cache_err:
                logging.error(f"Failed to write weather cache: {cache_err}")
                    
            logging.info(f"Fetched weather: temp_max={temp_max}°C, cloud_cover={cloud_cover}%, sunrise={sunrise}, sunset={sunset}")
            return temp_max, cloud_cover, sunrise, sunset
    except Exception as e:
        logging.error(f"Error fetching weather forecast from Open-Meteo: {e}")
        # Fall back to cache on failure
        if cached_data:
            logging.info("Falling back to cached weather forecast on Jetson after API failure.")
            return (
                cached_data.get("temp_max"),
                cached_data.get("cloud_cover"),
                cached_data.get("sunrise"),
                cached_data.get("sunset")
            )
        # If no cache exists, seed with default baseline parameters to prevent NA displays
        logging.warning("No weather cache exists. Seeding with default baseline parameters (20°C, 25% cloud cover).")
        return 20.0, 25.0, None, None


def calculate_daylight_duration(sunrise_str: Optional[str], sunset_str: Optional[str]) -> float:
    """Calculates daylight duration in hours from sunrise/sunset ISO strings."""
    if not sunrise_str or not sunset_str:
        return 12.0
    try:
        sunrise = parse_timestamp(sunrise_str)
        sunset = parse_timestamp(sunset_str)
        if sunrise and sunset:
            return (sunset - sunrise).total_seconds() / 3600.0
    except Exception as e:
        logging.error(f"Error calculating daylight duration: {e}")
    return 12.0


def get_day_type_and_month() -> Tuple[str, str]:
    """Returns the current day type (Weekday/Weekend) and current month name."""
    now = datetime.datetime.now()
    day_type = "Weekend" if now.weekday() in (5, 6) else "Weekday"
    month_name = now.strftime("%B")
    return day_type, month_name


def interpolate_gaps(series: List[Optional[float]]) -> List[float]:
    """Fills missing elements (None) in a list using linear interpolation."""
    n = len(series)
    result = list(series)
    non_none_indices = [i for i, x in enumerate(series) if x is not None]
    if not non_none_indices:
        return [0.0] * n
        
    first_valid_idx = non_none_indices[0]
    last_valid_idx = non_none_indices[-1]
    
    for i in range(first_valid_idx):
        result[i] = series[first_valid_idx]
    for i in range(last_valid_idx + 1, n):
        result[i] = series[last_valid_idx]
        
    for i in range(first_valid_idx + 1, last_valid_idx):
        if result[i] is None:
            prev_idx = i - 1
            while prev_idx >= first_valid_idx and result[prev_idx] is None:
                prev_idx -= 1
            next_idx = i + 1
            while next_idx <= last_valid_idx and result[next_idx] is None:
                next_idx += 1
                
            val_prev = result[prev_idx]
            val_next = result[next_idx]
            ratio = (i - prev_idx) / (next_idx - prev_idx)
            result[i] = val_prev + ratio * (val_next - val_prev)
            
    return [float(x) for x in result]


def extract_hourly_series(filepath: str, end_time: datetime.datetime, window_hours: int = 48) -> Tuple[List[float], float]:
    """Extracts a uniform hourly series from the history CSV, filling any gaps."""
    if not os.path.exists(filepath):
        return [0.0] * window_hours, float(end_time.hour)
        
    start_time = end_time - datetime.timedelta(hours=window_hours - 1)
    start_hour_dt = start_time.replace(minute=0, second=0, microsecond=0)
    
    target_dts = [start_hour_dt + datetime.timedelta(hours=i) for i in range(window_hours)]
    target_keys = [dt.strftime("%Y-%m-%d %H:00") for dt in target_dts]
    
    hourly_values = defaultdict(list)
    try:
        with open(filepath, 'r') as f:
            clean_lines = (line.replace('\x00', '') for line in f)
            reader = csv.reader(clean_lines)
            for row in reader:
                if len(row) >= 2:
                    ts = parse_timestamp(row[0])
                    if ts:
                        hour_key = ts.strftime("%Y-%m-%d %H:00")
                        try:
                            val = float(row[1])
                            hourly_values[hour_key].append(val)
                        except ValueError:
                            pass
    except Exception as e:
        logging.error(f"Error reading {filepath} in extract_hourly_series: {e}")
        
    series_raw: List[Optional[float]] = []
    for key in target_keys:
        vals = hourly_values[key]
        if vals:
            series_raw.append(sum(vals) / len(vals))
        else:
            series_raw.append(None)
            
    series = interpolate_gaps(series_raw)
    start_hour = float(target_dts[0].hour + target_dts[0].minute / 60.0)
    return series, start_hour


def extract_hourly_flow_series(filepath: str, end_time: datetime.datetime, col_idx: int, window_hours: int = 48) -> Tuple[List[float], float]:
    """Extracts a uniform hourly series from the flow history CSV at col_idx, filling gaps.

    Args:
        filepath: Filesystem path to the flow CSV.
        end_time: The end datetime of the target window.
        col_idx: Column index to parse from the CSV (e.g. 2 for load_power).
        window_hours: Number of hours in the history window.

    Returns:
        A tuple of (values_list, start_hour_float).
    """
    if not os.path.exists(filepath):
        return [0.0] * window_hours, float(end_time.hour)
        
    start_time = end_time - datetime.timedelta(hours=window_hours - 1)
    start_hour_dt = start_time.replace(minute=0, second=0, microsecond=0)
    
    target_dts = [start_hour_dt + datetime.timedelta(hours=i) for i in range(window_hours)]
    target_keys = [dt.strftime("%Y-%m-%d %H:00") for dt in target_dts]
    
    hourly_values = defaultdict(list)
    try:
        with open(filepath, 'r') as f:
            clean_lines = (line.replace('\x00', '') for line in f)
            reader = csv.reader(clean_lines)
            for row in reader:
                if len(row) > col_idx:
                    ts = parse_timestamp(row[0])
                    if ts:
                        hour_key = ts.strftime("%Y-%m-%d %H:00")
                        try:
                            val = float(row[col_idx])
                            hourly_values[hour_key].append(val)
                        except ValueError:
                            pass
    except Exception as e:
        logging.error(f"Error reading {filepath} in extract_hourly_flow_series: {e}")
        
    series_raw: List[Optional[float]] = []
    for key in target_keys:
        vals = hourly_values[key]
        if vals:
            series_raw.append(sum(vals) / len(vals))
        else:
            series_raw.append(None)
            
    series = interpolate_gaps(series_raw)
    start_hour = float(target_dts[0].hour + target_dts[0].minute / 60.0)
    return series, start_hour


def calculate_slope(series: List[float]) -> float:
    """Calculates the 3-hour regression slope on the final entries of the series.

    Args:
        series: A list of floats representing sequential hourly power readings.

    Returns:
        The linear regression slope over the last 3 hours in kW/hr.
    """
    if len(series) < 3:
        if len(series) >= 2:
            return series[-1] - series[-2]
        return 0.0
    # Why this works: For three equally spaced points t = [0, 1, 2], the least-squares
    # regression slope (y_2 - y_0) / 2 is mathematically identical to the average 
    # hourly rate of change between the first and last point. This filters out
    # single-point noise spikes while remaining computationally trivial.
    return (series[-1] - series[-3]) / 2.0


def format_decimal_hour(hour: float) -> str:
    """Converts a decimal hour value (e.g. 7.9) to HH:MM format (e.g. 07:54).

    Args:
        hour: The decimal hour value to format.

    Returns:
        A string representing the formatted time in HH:MM format.
    """
    h = int(hour)
    m = int(round((hour - h) * 60))
    if m == 60:
        h = (h + 1) % 24
        m = 0
    return f"{h:02d}:{m:02d}"


def detect_telemetry_gaps(filepath: str, baseline_dt: datetime.datetime, end_time: datetime.datetime) -> List[str]:
    """Scans the telemetry history file for any gaps > 30 minutes since baseline_dt.

    Args:
        filepath: Absolute path to the CSV history file.
        baseline_dt: The baseline datetime threshold.
        end_time: The current timestamp representing "now" for evaluation.

    Returns:
        A list of warning strings describing detected gaps.
    """
    warnings: List[str] = []
    if not os.path.exists(filepath):
        return warnings

    rows_ts: List[datetime.datetime] = []
    try:
        with open(filepath, 'r') as f:
            clean_lines = (line.replace('\x00', '') for line in f)
            reader = csv.reader(clean_lines)
            for row in reader:
                if len(row) >= 2:
                    ts = parse_timestamp(row[0])
                    if ts and ts >= baseline_dt:
                        rows_ts.append(ts)
    except Exception as e:
        logging.error(f"Error checking telemetry gaps in {filepath}: {e}")
        return warnings

    if not rows_ts:
        return warnings

    rows_ts.sort()
    # Check gap between consecutive recordings
    for i in range(len(rows_ts) - 1):
        gap_sec = (rows_ts[i+1] - rows_ts[i]).total_seconds()
        if gap_sec > 1800:  # 30 minutes
            gap_mins = gap_sec / 60.0
            warnings.append(
                f"Power outage or data gap of {gap_mins:.0f} minutes detected "
                f"from {rows_ts[i].strftime('%H:%M')} to {rows_ts[i+1].strftime('%H:%M')}."
            )
    # Check gap between last recorded point and the evaluation end_time
    gap_sec_now = (end_time - rows_ts[-1]).total_seconds()
    if gap_sec_now > 1800:
        gap_mins = gap_sec_now / 60.0
        warnings.append(
            f"Power outage or data gap of {gap_mins:.0f} minutes detected "
            f"from {rows_ts[-1].strftime('%H:%M')} to the current time."
        )

    return warnings


def compute_dft_coefficients(series: List[float], start_hour: float, period_hours: float) -> Tuple[float, float]:
    """Computes normalized amplitude and peak time-of-day hour for a specific period in hours.

    Args:
        series: List of floats representing hourly measurements.
        start_hour: Time of day (float, 0-23) of the first element in the series.
        period_hours: Target period (e.g. 24.0 for diurnal, 12.0 for semi-diurnal).

    Returns:
        A tuple of (normalized_amplitude_kW, peak_hour_of_day).
    """
    n_samples = len(series)
    if n_samples == 0:
        return 0.0, 0.0
        
    # k represents the exact frequency bin corresponding to the target period:
    # k = total samples / period length. (e.g., k = 48 / 24 = 2.0 cycles per 48 hours)
    k = float(n_samples) / period_hours
    re, im = 0.0, 0.0
    
    # Standard Discrete Fourier Transform accumulation loop
    for n in range(n_samples):
        angle = (2.0 * math.pi * k * n) / n_samples
        re += series[n] * math.cos(angle)
        im += -series[n] * math.sin(angle)
        
    # Normalized Peak Amplitude: 2 * magnitude / N (DC / mean is handled separately)
    amp = 2.0 * math.sqrt(re**2 + im**2) / n_samples
    
    # Phase Angle: Represents the offset angle in radians from the start of the sequence.
    # We use atan2(im, re) to preserve quadrant sign.
    angle = math.atan2(im, re)
    
    # Peak Hour of Day Mapping:
    # A cosine wave x_n = A cos(w*n + theta) peaks when (w*n + theta) = 0 (modulo 2pi).
    # Since w = 2pi*k/N, the sample offset n_peak = -theta * N / (2pi*k).
    # Adding start_hour and mapping modulo period_hours yields the exact peak hour of the day.
    peak = (start_hour - angle * period_hours / (2.0 * math.pi)) % period_hours
    
    return amp, peak


def compute_dft(series: List[float], start_hour: float) -> Dict[str, float]:
    """Computes Discrete Fourier Transform (DFT) for diurnal and semi-diurnal components of a single series."""
    amp_24, peak_24 = compute_dft_coefficients(series, start_hour, 24.0)
    amp_12, peak_12 = compute_dft_coefficients(series, start_hour, 12.0)
    
    ratio = amp_12 / amp_24 if amp_24 > 0 else 0.0
    
    return {
        "solar_24h_amp": amp_24,
        "solar_24h_peak_hour": peak_24,
        "grid_24h_amp": amp_24,
        "grid_12h_amp": amp_12,
        "grid_12h_peak_hour": peak_12,
        "grid_bimodal_ratio": ratio
    }


def calculate_grid_stats(filepath: str) -> Tuple[float, float]:
    """Calculates historical mean and standard deviation of grid demand from history CSV."""
    if not os.path.exists(filepath):
        return 0.0, 1.0
    vals = []
    try:
        with open(filepath, 'r') as f:
            clean_lines = (line.replace('\x00', '') for line in f)
            reader = csv.reader(clean_lines)
            for row in reader:
                if len(row) >= 2:
                    try:
                        vals.append(float(row[1]))
                    except ValueError:
                        pass
    except Exception as e:
        logging.error(f"Error calculating grid stats: {e}")
    if not vals:
        return 0.0, 1.0
    mean_val = sum(vals) / len(vals)
    if len(vals) > 1:
        var_val = sum((x - mean_val) ** 2 for x in vals) / (len(vals) - 1)
        std_val = math.sqrt(var_val)
    else:
        std_val = 1.0
    return mean_val, std_val


def calculate_solar_tod_stats(filepath: str, target_hour: int) -> Tuple[float, float]:
    """Computes mean and std dev of solar power for a specific hour block from history CSV."""
    if not os.path.exists(filepath):
        return 0.0, 0.0
    vals = []
    try:
        with open(filepath, 'r') as f:
            clean_lines = (line.replace('\x00', '') for line in f)
            reader = csv.reader(clean_lines)
            for row in reader:
                if len(row) >= 2:
                    ts_str = row[0].strip().replace('\x00', '')
                    try:
                        if len(ts_str) >= 13:
                            hour = int(ts_str[11:13])
                            if hour == target_hour:
                                vals.append(float(row[1]))
                    except ValueError:
                        pass
    except Exception as e:
        logging.error(f"Error calculating solar TOD stats: {e}")
    if not vals:
        return 0.0, 0.0
    mean_val = sum(vals) / len(vals)
    if len(vals) > 1:
        var_val = sum((x - mean_val) ** 2 for x in vals) / (len(vals) - 1)
        std_val = math.sqrt(var_val)
    else:
        std_val = 0.0
    return mean_val, std_val


def calculate_solar_correlation(se_filepath: str, ch_filepath: str) -> float:
    """Computes Pearson correlation coefficient between SolarEdge and Chillicon outputs during daylight hours (6 AM to 8 PM)."""
    if not os.path.exists(se_filepath) or not os.path.exists(ch_filepath):
        return 0.0
        
    se_data = {}
    try:
        with open(se_filepath, 'r') as f:
            clean_lines = (line.replace('\x00', '') for line in f)
            reader = csv.reader(clean_lines)
            for row in reader:
                if len(row) >= 2:
                    ts_str = row[0].strip().replace('\x00', '')
                    if len(ts_str) >= 16:
                        key = ts_str[:15] # YYYY-MM-DD HH:M
                        try:
                            hour = int(ts_str[11:13])
                            if 6 <= hour <= 20:
                                se_data[key] = float(row[1])
                        except ValueError:
                            pass
    except Exception as e:
        logging.error(f"Error reading SolarEdge for correlation: {e}")
        
    ch_data = {}
    try:
        with open(ch_filepath, 'r') as f:
            clean_lines = (line.replace('\x00', '') for line in f)
            reader = csv.reader(clean_lines)
            for row in reader:
                if len(row) >= 2:
                    ts_str = row[0].strip().replace('\x00', '')
                    if len(ts_str) >= 16:
                        key = ts_str[:15]
                        try:
                            hour = int(ts_str[11:13])
                            if 6 <= hour <= 20:
                                ch_data[key] = float(row[1])
                        except ValueError:
                            pass
    except Exception as e:
        logging.error(f"Error reading Chillicon for correlation: {e}")
        
    common_keys = set(se_data.keys()).intersection(set(ch_data.keys()))
    if len(common_keys) < 5:
        return 0.0
        
    x = [se_data[k] for k in common_keys]
    y = [ch_data[k] for k in common_keys]
    
    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    
    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den_x = sum((xi - mean_x) ** 2 for xi in x)
    den_y = sum((yi - mean_y) ** 2 for yi in y)
    
    if den_x == 0 or den_y == 0:
        return 0.0
        
    return num / math.sqrt(den_x * den_y)


def calculate_deltas(baseline_dt: datetime.datetime) -> Dict[str, float]:
    """Calculates delta metrics since the baseline timestamp by parsing CSV files."""
    # 1. Grid import, export, and peak demand
    delta_import = 0.0
    delta_export = 0.0
    delta_peak = 0.0
    
    if os.path.exists(GRID_HISTORY):
        rows = []
        try:
            with open(GRID_HISTORY, 'r') as f:
                clean_lines = (line.replace('\x00', '') for line in f)
                reader = csv.reader(clean_lines)
                for row in reader:
                    if len(row) >= 2:
                        ts = parse_timestamp(row[0])
                        if ts and ts >= baseline_dt:
                            try:
                                val = float(row[1])
                                rows.append((ts, val))
                            except ValueError:
                                pass
        except Exception as e:
            logging.error(f"Error reading grid history for deltas: {e}")
            
        if rows:
            rows.sort(key=lambda x: x[0])
            for i in range(len(rows) - 1):
                t_curr, p_curr = rows[i]
                t_next, _ = rows[i+1]
                dt_hours = (t_next - t_curr).total_seconds() / 3600.0
                if dt_hours > 0 and dt_hours <= 1.0:
                    if p_curr > 0:
                        delta_import += p_curr * dt_hours
                        delta_peak = max(delta_peak, p_curr)
                    else:
                        delta_export += abs(p_curr) * dt_hours
            # Final point to now
            t_last, p_last = rows[-1]
            dt_hours = (datetime.datetime.now() - t_last).total_seconds() / 3600.0
            if dt_hours > 0 and dt_hours <= 0.5:
                if p_last > 0:
                    delta_import += p_last * dt_hours
                    delta_peak = max(delta_peak, p_last)
                else:
                    delta_export += abs(p_last) * dt_hours

    # 2. SolarEdge Generation
    se_kwh = 0.0
    if os.path.exists(SE_HISTORY):
        rows = []
        try:
            with open(SE_HISTORY, 'r') as f:
                clean_lines = (line.replace('\x00', '') for line in f)
                reader = csv.reader(clean_lines)
                for row in reader:
                    if len(row) >= 2:
                        ts = parse_timestamp(row[0])
                        if ts and ts >= baseline_dt:
                            try:
                                val = float(row[1])
                                rows.append((ts, val))
                            except ValueError:
                                pass
        except Exception as e:
            logging.error(f"Error reading SolarEdge history for deltas: {e}")
            
        if rows:
            rows.sort(key=lambda x: x[0])
            for i in range(len(rows) - 1):
                t_curr, p_curr = rows[i]
                t_next, _ = rows[i+1]
                dt_hours = (t_next - t_curr).total_seconds() / 3600.0
                if dt_hours > 0 and dt_hours <= 1.0:
                    se_kwh += p_curr * dt_hours
            # Final point to now
            t_last, p_last = rows[-1]
            dt_hours = (datetime.datetime.now() - t_last).total_seconds() / 3600.0
            if dt_hours > 0 and dt_hours <= 0.5:
                se_kwh += p_last * dt_hours

    # 3. Chillicon Generation
    ch_kwh = 0.0
    if os.path.exists(CHILICON_HISTORY):
        rows = []
        try:
            with open(CHILICON_HISTORY, 'r') as f:
                clean_lines = (line.replace('\x00', '') for line in f)
                reader = csv.reader(clean_lines)
                for row in reader:
                    if len(row) >= 2:
                        ts = parse_timestamp(row[0])
                        if ts and ts >= baseline_dt:
                            try:
                                val = float(row[1])
                                rows.append((ts, val))
                            except ValueError:
                                pass
        except Exception as e:
            logging.error(f"Error reading Chillicon history for deltas: {e}")
            
        if rows:
            rows.sort(key=lambda x: x[0])
            for i in range(len(rows) - 1):
                t_curr, p_curr = rows[i]
                t_next, _ = rows[i+1]
                dt_hours = (t_next - t_curr).total_seconds() / 3600.0
                if dt_hours > 0 and dt_hours <= 1.0:
                    ch_kwh += p_curr * dt_hours
            # Final point to now
            t_last, p_last = rows[-1]
            dt_hours = (datetime.datetime.now() - t_last).total_seconds() / 3600.0
            if dt_hours > 0 and dt_hours <= 0.5:
                ch_kwh += p_last * dt_hours

    delta_solar = se_kwh + ch_kwh

    # 4. Battery activity
    delta_bat_charge = 0.0
    delta_bat_discharge = 0.0
    if os.path.exists(SE_BATTERY_HISTORY):
        rows = []
        try:
            with open(SE_BATTERY_HISTORY, 'r') as f:
                clean_lines = (line.replace('\x00', '') for line in f)
                reader = csv.reader(clean_lines)
                for row in reader:
                    if len(row) >= 2:
                        ts = parse_timestamp(row[0])
                        if ts and ts >= baseline_dt:
                            try:
                                val = float(row[1])
                                rows.append((ts, val))
                            except ValueError:
                                pass
        except Exception as e:
            logging.error(f"Error reading battery history for deltas: {e}")
            
        if rows:
            rows.sort(key=lambda x: x[0])
            for i in range(len(rows) - 1):
                t_curr, p_curr = rows[i]
                t_next, _ = rows[i+1]
                dt_hours = (t_next - t_curr).total_seconds() / 3600.0
                if dt_hours > 0 and dt_hours <= 1.0:
                    if p_curr > 0:
                        delta_bat_discharge += p_curr * dt_hours
                    else:
                        delta_bat_charge += abs(p_curr) * dt_hours
            # Final point to now
            t_last, p_last = rows[-1]
            dt_hours = (datetime.datetime.now() - t_last).total_seconds() / 3600.0
            if dt_hours > 0 and dt_hours <= 0.5:
                if p_last > 0:
                    delta_bat_discharge += p_last * dt_hours
                else:
                    delta_bat_charge += abs(p_last) * dt_hours

    # 5. SolarEdge Load Flow (integrated load energy)
    delta_se_load = 0.0
    if os.path.exists(SE_FLOW_HISTORY):
        rows = []
        try:
            with open(SE_FLOW_HISTORY, 'r') as f:
                clean_lines = (line.replace('\x00', '') for line in f)
                reader = csv.reader(clean_lines)
                for row in reader:
                    if len(row) >= 3:
                        ts = parse_timestamp(row[0])
                        if ts and ts >= baseline_dt:
                            try:
                                val = float(row[2])  # load_power is at index 2
                                rows.append((ts, val))
                            except ValueError:
                                pass
        except Exception as e:
            logging.error(f"Error reading SolarEdge flow history for load deltas: {e}")
            
        if rows:
            rows.sort(key=lambda x: x[0])
            for i in range(len(rows) - 1):
                t_curr, p_curr = rows[i]
                t_next, _ = rows[i+1]
                dt_hours = (t_next - t_curr).total_seconds() / 3600.0
                if dt_hours > 0 and dt_hours <= 1.0:
                    delta_se_load += p_curr * dt_hours
            # Final point to now
            t_last, p_last = rows[-1]
            dt_hours = (datetime.datetime.now() - t_last).total_seconds() / 3600.0
            if dt_hours > 0 and dt_hours <= 0.5:
                delta_se_load += p_last * dt_hours

    return {
        "delta_import": delta_import,
        "delta_export": delta_export,
        "delta_peak": delta_peak,
        "delta_solar": delta_solar,
        "delta_bat_charge": delta_bat_charge,
        "delta_bat_discharge": delta_bat_discharge,
        "delta_se_load": delta_se_load
    }


def calculate_flow_stats(baseline_dt: datetime.datetime) -> Dict[str, float]:
    """Calculates min, max, and average load_power from flow history since baseline.

    Args:
        baseline_dt: The baseline datetime threshold.

    Returns:
        A dictionary containing keys 'load_min', 'load_max', and 'load_avg'.
    """
    load_vals = []
    if os.path.exists(SE_FLOW_HISTORY):
        try:
            with open(SE_FLOW_HISTORY, 'r') as f:
                clean_lines = (line.replace('\x00', '') for line in f)
                reader = csv.reader(clean_lines)
                for row in reader:
                    if len(row) >= 3:
                        ts = parse_timestamp(row[0])
                        if ts and ts >= baseline_dt:
                            try:
                                val = float(row[2])  # load_power is at index 2
                                load_vals.append(val)
                            except ValueError:
                                pass
        except Exception as e:
            logging.error(f"Error reading flow history for stats: {e}")
            
    if load_vals:
        return {
            "load_min": min(load_vals),
            "load_max": max(load_vals),
            "load_avg": sum(load_vals) / len(load_vals)
        }
    return {
        "load_min": 0.0,
        "load_max": 0.0,
        "load_avg": 0.0
    }


def query_local_ollama(prompt: str, model: str) -> str:
    """Queries local Ollama generation API synchronously."""
    payload = {
        "model": model,
        "prompt": prompt,
        "system": "You are a precise, low-overhead edge AI energy assistant.",
        "stream": False,
        "options": {
            "num_predict": 2048,
            "num_ctx": 8192
        }
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        OLLAMA_ENDPOINT, 
        data=data, 
        headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            res_body = response.read().decode('utf-8')
            res_data = json.loads(res_body)
            return res_data.get("response", "").strip()
    except Exception as e:
        logging.error(f"Ollama API error: {e}")
        raise


def calculate_remaining_lines(baseline_text: str, max_allowed: int = 30) -> int:
    """Calculates the remaining text line budget for the local LLM summary.

    Simulates word wrapping at 100 characters per line to estimate the physical
    wrapped lines of the baseline summary on the kiosk layout, and subtracts
    it from the maximum allowed lines.

    Args:
        baseline_text: The multi-line baseline summary string.
        max_allowed: The maximum physical text lines allowed on the kiosk layout.

    Returns:
        The remaining line count budget for the local LLM's output.

    Raises:
        None
    """
    import textwrap
    wrapped_lines: int = 0
    for line in baseline_text.split('\n'):
        if line.strip():
            wrapped_lines += len(textwrap.wrap(line, width=100))
        else:
            wrapped_lines += 1
            
    # Subtract baseline wrapped lines and a safety margin (including metadata line)
    remaining: int = max_allowed - wrapped_lines - 1
    return max(3, remaining)


def run_analysis_workflow(baseline_ts_str: str, baseline_text: str, batch_interval_hours: int = 4) -> Dict[str, Any]:
    """Runs the quantitative modeling and local LLM summary generation workflow."""
    baseline_dt = parse_timestamp(baseline_ts_str)
    if not baseline_dt:
        raise ValueError(f"Could not parse baseline timestamp: {baseline_ts_str}")
        
    # 1. Fetch weather forecast (with sunrise/sunset)
    temp_max, cloud_cover, sunrise, sunset = fetch_weather()
    
    # Establish fallback daylight window from month climatology if API is offline
    current_month = datetime.datetime.now().month
    fallback_sunrise, fallback_sunset = SEATTLE_MONTHLY_DAYLIGHT_FALLBACKS.get(current_month, ("06:00", "18:00"))
    
    sunrise_time = fallback_sunrise
    if sunrise:
        try:
            parts = sunrise.split("T")
            sunrise_time = parts[1][:5] if len(parts) > 1 else sunrise[:5]
        except Exception:
            pass

    sunset_time = fallback_sunset
    if sunset:
        try:
            parts = sunset.split("T")
            sunset_time = parts[1][:5] if len(parts) > 1 else sunset[:5]
        except Exception:
            pass
            
    # Calculate daylight duration from actual weather datetimes if available;
    # otherwise, compute duration from fallback time strings.
    if sunrise and sunset:
        daylight_duration = calculate_daylight_duration(sunrise, sunset)
    else:
        try:
            sr_h, sr_m = map(int, sunrise_time.split(":"))
            ss_h, ss_m = map(int, sunset_time.split(":"))
            daylight_duration = (ss_h + ss_m / 60.0) - (sr_h + sr_m / 60.0)
        except Exception:
            daylight_duration = 12.0
            
    day_type, month_name = get_day_type_and_month()
    
    # 2. Integrate recent telemetry deltas
    deltas = calculate_deltas(baseline_dt)
    flow_stats = calculate_flow_stats(baseline_dt)
    
    # 3. Extract 48-hour hourly telemetry series for DFT and Slope analysis
    now_dt = datetime.datetime.now()
    grid_series, start_hour = extract_hourly_series(GRID_HISTORY, now_dt, 48)
    se_series, _ = extract_hourly_series(SE_HISTORY, now_dt, 48)
    ch_series, _ = extract_hourly_series(CHILICON_HISTORY, now_dt, 48)
    
    # Combined Solar series (SolarEdge + Chillicon)
    solar_series = [s + c for s, c in zip(se_series, ch_series)]
    
    # 4. Compute Fourier (DFT) spectral metrics
    # Compute individual diurnal amplitudes and peak hours for NW (SolarEdge) and SW (Chillicon) arrays
    se_24h_amp, se_24h_peak_hour = compute_dft_coefficients(se_series, start_hour, 24.0)
    ch_24h_amp, ch_24h_peak_hour = compute_dft_coefficients(ch_series, start_hour, 24.0)
    
    solar_24h_amp, solar_24h_peak_hour = compute_dft_coefficients(solar_series, start_hour, 24.0)
    grid_24h_amp, _ = compute_dft_coefficients(grid_series, start_hour, 24.0)
    grid_12h_amp, grid_12h_peak_hour = compute_dft_coefficients(grid_series, start_hour, 12.0)
    grid_bimodal_ratio = grid_12h_amp / grid_24h_amp if grid_24h_amp > 0 else 0.0
    
    # 4b. Compute rhythm SNR metrics via standalone module
    import snr_analysis
    freqs = [0.05 + 0.01 * i for i in range(400)]
    grid_amp_spec = snr_analysis.compute_dtft_spectrum(grid_series, freqs)
    solar_amp_spec = snr_analysis.compute_dtft_spectrum(solar_series, freqs)
    
    # Load battery series to calculate true household consumption (Grid + Solar + Battery)
    bat_series, _ = extract_hourly_series(SE_BATTERY_HISTORY, now_dt, 48)
    consumption_series = [g + s + b for g, s, b in zip(grid_series, solar_series, bat_series)]
    consumption_amp_spec = snr_analysis.compute_dtft_spectrum(consumption_series, freqs)
    
    snrs = snr_analysis.analyze_spectra_snr(freqs, grid_amp_spec, solar_amp_spec, consumption_amp_spec)
    
    # 5. Compute Time-Domain Slopes (Derivatives)
    solar_slope = calculate_slope(solar_series)
    grid_slope = calculate_slope(grid_series)
    
    # 6. Perform standard statistical calculations
    grid_mean, grid_std = calculate_grid_stats(GRID_HISTORY)
    current_hour_now = datetime.datetime.now().hour
    se_mean, se_std = calculate_solar_tod_stats(SE_HISTORY, current_hour_now)
    solar_corr = calculate_solar_correlation(SE_HISTORY, CHILICON_HISTORY)
    
    # Calculate battery round-trip efficiency
    battery_rte = 0.0
    if deltas["delta_bat_charge"] > 0:
        battery_rte = deltas["delta_bat_discharge"] / deltas["delta_bat_charge"]
        
    # Z-Score of the live peak grid demand
    z_score_peak = 0.0
    if grid_std > 0:
        z_score_peak = (deltas["delta_peak"] - grid_mean) / grid_std
        
    # 7. Statistical anomaly flagging & prompt decoration
    warnings = []
    
    # Check grid import Z-score
    if z_score_peak > 2.5:
        warnings.append(f"Statistically significant peak grid load spike detected (Z-Score: {z_score_peak:.2f}).")
        
    # Adjust solar baseline dynamically based on cloud cover
    # Sum the historical hourly SolarEdge means for each specific hour in the window,
    # weighted by the fraction of the hour elapsed since the baseline timestamp.
    expected_solar_kwh = 0.0
    h_start = baseline_dt.hour
    h_end = datetime.datetime.now().hour
    if baseline_dt.date() == datetime.datetime.now().date():
        for hr in range(h_start, h_end + 1):
            hr_mean, _ = calculate_solar_tod_stats(SE_HISTORY, hr)
            weight = 1.0
            if hr == h_start:
                weight = (60.0 - baseline_dt.minute) / 60.0
            elif hr == h_end:
                weight = datetime.datetime.now().minute / 60.0
            expected_solar_kwh += hr_mean * weight
            
    if cloud_cover is not None:
        # Scale down expectation based on cloudiness
        expected_solar_kwh *= ((100.0 - cloud_cover) / 100.0)
        
    if expected_solar_kwh > 0:
        solar_deficit_ratio = (expected_solar_kwh - deltas["delta_solar"]) / expected_solar_kwh
        # Flag if we have a solar deficit greater than standard deviations/margins
        if solar_deficit_ratio > 0.40 and deltas["delta_solar"] < expected_solar_kwh:
            if cloud_cover is not None and cloud_cover > 60:
                warnings.append(f"Solar PV yield is low, corresponding to forecasted overcast skies ({cloud_cover}% cloud cover).")
            else:
                warnings.append(f"Unexpected solar yield deficit detected relative to clear sky baselines (yield deficit: {solar_deficit_ratio*100:.1f}%).")
                
    # Check solar correlation coefficient
    if solar_corr < 0.70 and deltas["delta_solar"] > 0.5:
        # Check if Chillicon (SW) peaks earlier than SolarEdge (NW).
        # Normal diurnal phase separation between SW and NW arrays is typically 1.0 to 5.0 hours.
        phase_diff = (se_24h_peak_hour - ch_24h_peak_hour) % 24
        if not (1.0 <= phase_diff <= 5.0):
            warnings.append(
                f"Solar Edge and Chillicon PV outputs show low correlation (r={solar_corr:.2f}) "
                f"with atypical phase separation (Peak hours: SE={se_24h_peak_hour:.1f}, CH={ch_24h_peak_hour:.1f}), "
                f"suggesting sensor drift or micro-grid shading."
            )
        
    # Check for telemetry gaps (power outages or recording halts) in GRID_HISTORY since baseline
    outage_warnings = detect_telemetry_gaps(GRID_HISTORY, baseline_dt, datetime.datetime.now())
    warnings.extend(outage_warnings)
        
    # Format warning context to append to LLM instructions
    warning_context = ""
    if warnings:
        warning_context = "\nStatistical Anomaly Warnings (Keep these in mind for your analysis):\n" + "\n".join(f"- {w}" for w in warnings)
        
    # Calculate available line budget for local edge model
    remaining_lines: int = calculate_remaining_lines(baseline_text)
        
    # 8. Load and format prompt template
    prompt_template = None
    prompt_path = os.path.join(SCRIPT_DIR, "gemma_hybrid_prompt.txt")
    if os.path.exists(prompt_path):
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
        except Exception as e:
            logging.error(f"Failed to read prompt template: {e}")
            
    if not prompt_template:
        # Fallback template matching the schema of gemma_hybrid_prompt.txt
        prompt_template = """Baseline Summary (Generated at {baseline_time}):
{baseline_text}

Current Date and Time: {current_time}
Live Telemetry since baseline ({baseline_time} to {current_time}):
- Net Grid Import: {delta_import:.2f} kWh
- Net Grid Export: {delta_export:.2f} kWh
- Peak Grid Demand: {delta_peak:.2f} kW
- Solar PV Generation: {delta_solar:.2f} kWh
- Battery Energy Charged: {delta_bat_charge:.2f} kWh
- Battery Energy Discharged: {delta_bat_discharge:.2f} kWh
- SolarEdge Appliance Load (Approx) Energy: {delta_se_load:.2f} kWh
- SolarEdge Appliance Load (Approx) Power: Min {se_load_min:.2f} kW | Max {se_load_max:.2f} kW | Avg {se_load_avg:.2f} kW

=== ENVIRONMENTAL & SEASONAL PREDICTORS ===
- Current Month: {month_name}
- Day Type: {day_type}
- Daylight Duration: {daylight_duration:.1f} hours
- Expected Max Temperature: {expected_temp_max:.1f}°C
- Expected Cloud Cover: {expected_cloud_cover:.0f}%

=== FREQUENCY DOMAIN (DFT) METRICS ===
- Solar Diurnal (24h) Amplitude: {solar_24h_amp:.2f} kW
- Solar Diurnal Peak Hour: {solar_24h_peak_hour}
- Grid Diurnal (24h) Amplitude: {grid_24h_amp:.2f} kW
- Grid Semi-Diurnal (12h) Amplitude: {grid_12h_amp:.2f} kW
- Grid Bimodal peak hour (12h): {grid_12h_peak_hour}
- Grid Bimodal Ratio (12h/24h): {grid_bimodal_ratio:.2f}

=== RHYTHM SNR (SIGNAL-TO-NOISE RATIO) METRICS ===
- Grid Diurnal (24h) SNR: {grid_24h_snr_db:.1f} dB
- Grid Semi-Diurnal (12h) SNR: {grid_12h_snr_db:.1f} dB
- Solar Diurnal (24h) SNR: {solar_24h_snr_db:.1f} dB
- Household Consumption Diurnal (24h) SNR: {consumption_24h_snr_db:.1f} dB
- Household Consumption Semi-Diurnal (12h) SNR: {consumption_12h_snr_db:.1f} dB

=== TIME-DOMAIN SLOPE (RATE OF CHANGE) METRICS ===
- Recent Solar Power Slope (dS/dt): {solar_slope:.2f} kW/hr
- Recent Net Grid Demand Slope (dG/dt): {grid_slope:.2f} kW/hr

=== OUTPUT SPACE CONSTRAINT ===
Your output MUST fit within exactly {remaining_lines} lines of text (with 100 characters max per line). Ensure the entire response is under {remaining_lines} lines.

Output:
"""

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # We pass 0.0 if None for clean string formatting
    weather_temp = temp_max if temp_max is not None else 0.0
    weather_clouds = cloud_cover if cloud_cover is not None else 0.0
    solar_weather_modulation = (100.0 - weather_clouds) / 100.0
    
    formatted_prompt = prompt_template.format(
        baseline_time=baseline_ts_str,
        baseline_text=baseline_text,
        current_time=now_str,
        delta_import=deltas["delta_import"],
        delta_export=deltas["delta_export"],
        delta_peak=deltas["delta_peak"],
        delta_solar=deltas["delta_solar"],
        delta_bat_charge=deltas["delta_bat_charge"],
        delta_bat_discharge=deltas["delta_bat_discharge"],
        delta_se_load=deltas["delta_se_load"],
        se_load_min=flow_stats["load_min"],
        se_load_max=flow_stats["load_max"],
        se_load_avg=flow_stats["load_avg"],
        expected_temp_max=weather_temp,
        expected_cloud_cover=weather_clouds,
        solar_weather_modulation=solar_weather_modulation,
        month_name=month_name,
        day_type=day_type,
        sunrise_time=sunrise_time,
        sunset_time=sunset_time,
        daylight_duration=daylight_duration,
        solar_24h_amp=solar_24h_amp,
        solar_24h_peak_hour=format_decimal_hour(solar_24h_peak_hour),
        se_24h_peak_hour=format_decimal_hour(se_24h_peak_hour),
        ch_24h_peak_hour=format_decimal_hour(ch_24h_peak_hour),
        grid_24h_amp=grid_24h_amp,
        grid_12h_amp=grid_12h_amp,
        grid_12h_peak_hour=format_decimal_hour(grid_12h_peak_hour),
        grid_bimodal_ratio=grid_bimodal_ratio,
        solar_slope=solar_slope,
        grid_slope=grid_slope,
        grid_24h_snr_db=snrs["grid_24h_snr_db"],
        grid_12h_snr_db=snrs["grid_12h_snr_db"],
        solar_24h_snr_db=snrs["solar_24h_snr_db"],
        consumption_24h_snr_db=snrs["consumption_24h_snr_db"],
        consumption_12h_snr_db=snrs["consumption_12h_snr_db"],
        warning_context=f"\nStatistical Anomaly Warnings (Keep these in mind for your analysis):\n{warning_context}" if warning_context else "",
        batch_interval_hours=batch_interval_hours,
        remaining_lines=remaining_lines
    )
        
    # 9. Query Ollama for Time-Domain Analysis
    model_name: str = DEFAULT_MODEL
    logging.info(f"Submitting query to Ollama model {model_name}...")
    llm_response: str = query_local_ollama(formatted_prompt, model_name)
    
    # 10. Load and format DFT prompt template
    dft_prompt_template: Optional[str] = None
    dft_prompt_path: str = os.path.join(SCRIPT_DIR, "gemma_dft_prompt.txt")
    if os.path.exists(dft_prompt_path):
        try:
            with open(dft_prompt_path, 'r', encoding='utf-8') as f:
                dft_prompt_template = f.read()
        except Exception as e:
            logging.error(f"Failed to read DFT prompt template: {e}")
    if not dft_prompt_template:
        dft_prompt_template = """You are a precise edge AI energy analyst. Write a 2-sentence explanation of these frequency metrics.
- Solar Diurnal (24h) Amplitude: {solar_24h_amp:.2f} kW
- Solar Diurnal Peak Hour: {solar_24h_peak_hour}
- Solar Weather Modulation Factor: {solar_weather_modulation:.2f}
- Grid Bimodality Ratio (12h/24h): {grid_bimodal_ratio:.2f}
- Solar Edge & Chillicon Correlation: {solar_corr:.2f}
- Phase Separation: {phase_diff:.1f} hours
- Grid Diurnal (24h) SNR: {grid_24h_snr_db:.1f} dB
- Grid Semi-Diurnal (12h) SNR: {grid_12h_snr_db:.1f} dB
- Solar Diurnal (24h) SNR: {solar_24h_snr_db:.1f} dB

Explanation:
"""

    phase_diff: float = (se_24h_peak_hour - ch_24h_peak_hour) % 24
    formatted_dft_prompt: str = dft_prompt_template.format(
        solar_24h_amp=solar_24h_amp,
        solar_24h_peak_hour=format_decimal_hour(solar_24h_peak_hour),
        solar_weather_modulation=solar_weather_modulation,
        grid_24h_amp=grid_24h_amp,
        grid_12h_amp=grid_12h_amp,
        grid_12h_peak_hour=format_decimal_hour(grid_12h_peak_hour),
        grid_bimodal_ratio=grid_bimodal_ratio,
        phase_diff=phase_diff,
        solar_corr=solar_corr,
        sunrise_time=sunrise_time,
        sunset_time=sunset_time,
        grid_24h_snr_db=snrs["grid_24h_snr_db"],
        grid_12h_snr_db=snrs["grid_12h_snr_db"],
        solar_24h_snr_db=snrs["solar_24h_snr_db"]
    )
    
    logging.info("Submitting query for DFT explanation to Ollama...")
    dft_response: str = query_local_ollama(formatted_dft_prompt, model_name)
    
    return {
        "response": llm_response,
        "dft_explanation": dft_response,
        "metrics": {
            "temp_max": temp_max,
            "cloud_cover": cloud_cover,
            "solar_weather_modulation": solar_weather_modulation,
            "z_score_peak": z_score_peak,
            "battery_rte": battery_rte,
            "solar_correlation": solar_corr,
            "daylight_duration": daylight_duration,
            "solar_24h_amp": solar_24h_amp,
            "solar_24h_peak_hour": solar_24h_peak_hour,
            "se_24h_peak_hour": se_24h_peak_hour,
            "ch_24h_peak_hour": ch_24h_peak_hour,
            "grid_bimodal_ratio": grid_bimodal_ratio,
            "solar_slope": solar_slope,
            "grid_slope": grid_slope,
            "grid_24h_snr_db": snrs["grid_24h_snr_db"],
            "grid_12h_snr_db": snrs["grid_12h_snr_db"],
            "solar_24h_snr_db": snrs["solar_24h_snr_db"],
            "consumption_24h_snr_db": snrs["consumption_24h_snr_db"],
            "consumption_12h_snr_db": snrs["consumption_12h_snr_db"]
        }
    }


# Global variables for background full-history DFT calculation caching
cached_full_history_data: Dict[str, Any] = {}
cached_data_lock = threading.Lock()


def run_full_history_math() -> None:
    """Calculates full-history DFT spectrum and updates the global cache."""
    global cached_full_history_data
    try:
        from dashboard_modules import telemetry, solar, weather, spectral
        
        # Load full history from backups
        # (Using cutoff_hours=999999 to load everything)
        ts, u = telemetry.load_grid_history(GRID_HISTORY, cutoff_hours=999999)
        if not ts:
            logging.info("Background Math: No grid history loaded.")
            return
            
        se_client = solar.SolarEdgeClient("", "", SE_HISTORY, SE_BATTERY_HISTORY)
        se_ts, se_p, bat_ts, bat_power, _ = se_client.load_history(cutoff_hours=999999)
        
        ch_client = solar.ChilliconClient("", "", "", CHILICON_HISTORY)
        ch_ts, ch_p, _ = ch_client.load_history(cutoff_hours=999999)
        
        weather_map = weather.fetch_historical_weather()
        
        logging.info(f"Background Math: Computing spectrum for {len(ts)} grid points...")
        freqs, grid_amp, solar_amp, expected_solar_amp, consumption_amp = spectral.align_and_compute_spectra(
            ts, u, se_ts, se_p, ch_ts, ch_p, weather_map, se_battery_timestamps=bat_ts, se_battery_power=bat_power
        )
        
        with cached_data_lock:
            cached_full_history_data = {
                "freqs": freqs,
                "grid_amp": grid_amp,
                "solar_amp": solar_amp,
                "expected_solar_amp": expected_solar_amp,
                "consumption_amp": consumption_amp
            }
        logging.info("Background Math: Successfully calculated and cached full-history DFT.")
    except Exception as e:
        logging.error(f"Background Math failed: {e}")


def background_full_history_math_loop() -> None:
    """Background thread that runs full-history DFT math every 30 minutes."""
    # Run initially after a brief sleep to let the server startup settle
    time.sleep(5)
    while True:
        try:
            logging.info("Background Math: Starting full-history DFT calculation...")
            run_full_history_math()
        except Exception as e:
            logging.error(f"Background Math Loop Error: {e}")
        
        time.sleep(1800)  # Run every 30 minutes


class AnalyzeHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/api/analyze':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                payload = json.loads(post_data.decode('utf-8'))
                baseline_ts_str = payload.get("baseline_timestamp")
                baseline_text = payload.get("baseline_text", "")
                batch_interval_hours = payload.get("batch_interval_hours", 4)
                
                if not baseline_ts_str:
                    self.send_error_response("Missing baseline_timestamp")
                    return
                
                logging.info(f"Received API analysis request. Baseline timestamp: {baseline_ts_str}, Batch Interval: {batch_interval_hours}h")
                response_data = run_analysis_workflow(baseline_ts_str, baseline_text, batch_interval_hours)
                
                # Inject cached full-history spectrum
                with cached_data_lock:
                    if cached_full_history_data:
                        response_data["full_history_spectrum"] = cached_full_history_data
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response_data).encode('utf-8'))
            except Exception as e:
                logging.error(f"Error handling POST /api/analyze: {e}")
                self.send_error_response(str(e))
        else:
            self.send_response(404)
            self.end_headers()
            
    def send_error_response(self, msg):
        self.send_response(400)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode('utf-8'))
        
    def log_message(self, format, *args):
        # Log HTTP requests using standard logging config
        logging.info("%s - - %s" % (self.address_string(), format%args))


def main() -> None:
    port = 5000
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.startswith("--port="):
                try:
                    port = int(arg.split("=", 1)[1])
                except ValueError:
                    pass
                    
    # Read environment configs if present
    env_path = os.path.join(SCRIPT_DIR, ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
            logging.info("Loaded .env config file for server.")
        except Exception as e:
            logging.error(f"Could not load .env file: {e}")

    global DEFAULT_MODEL, OLLAMA_ENDPOINT
    DEFAULT_MODEL = os.environ.get("EDGE_MODEL", DEFAULT_MODEL)
    OLLAMA_ENDPOINT = os.environ.get("OLLAMA_HOST", OLLAMA_ENDPOINT)

    # Allow address reuse
    socketserver.TCPServer.allow_reuse_address = True
    handler = AnalyzeHTTPRequestHandler
    
    # Start the background full-history DFT math thread
    math_thread = threading.Thread(target=background_full_history_math_loop, daemon=True)
    math_thread.start()
    logging.info("Started background full-history DFT math thread.")
    
    with socketserver.TCPServer(("", port), handler) as httpd:
        logging.info(f"Jetson Edge HTTP Server started on port {port}. Model: {DEFAULT_MODEL}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        logging.info("Jetson Edge HTTP Server stopped.")

if __name__ == "__main__":
    main()
