"""Weather clients querying forecast and historical parameters from Open-Meteo.

Decouples weather fetching and data structure parsing from UI loops.
"""

import datetime
import json
import logging
import urllib.request
from typing import Any, Dict, Optional

# Local config defaults
from .config import DEFAULT_LAT, DEFAULT_LON


def fetch_live_weather(lat: str = DEFAULT_LAT, lon: str = DEFAULT_LON) -> Dict[str, Optional[float]]:
    """Fetches the live weather from Open-Meteo API.

    Args:
        lat: Latitude of target location.
        lon: Longitude of target location.

    Returns:
        A dictionary containing:
        - "temp": float or None
        - "weather_code": float or None
        - "cloud_cover": float or None
    """
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code,cloud_cover&timezone=auto"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            res = json.loads(response.read().decode('utf-8'))
            current = res.get("current", {})
            return {
                "temp": current.get("temperature_2m"),
                "weather_code": current.get("weather_code"),
                "cloud_cover": current.get("cloud_cover")
            }
    except Exception as e:
        logging.error(f"Error fetching live weather from Open-Meteo: {e}")
        return {}


def calculate_epa_pm25_aqi(pm25: float) -> tuple[int, str, str]:
    """Calculates official US EPA PM2.5 AQI, Category description, and Hex Color code."""
    try:
        c = round(float(pm25), 1)
    except Exception:
        return 0, "Unknown", "#a0aec0"

    if c <= 12.0:
        aqi = ((50 - 0) / (12.0 - 0.0)) * (c - 0.0) + 0
        category = "Good"
        color = "#22c55e"  # Green
    elif c <= 35.4:
        aqi = ((100 - 51) / (35.4 - 12.1)) * (c - 12.1) + 51
        category = "Moderate"
        color = "#eab308"  # Yellow
    elif c <= 55.4:
        aqi = ((150 - 101) / (55.4 - 35.5)) * (c - 35.5) + 101
        category = "Unhealthy for Sensitive"
        color = "#f97316"  # Orange
    elif c <= 150.4:
        aqi = ((200 - 151) / (150.4 - 55.5)) * (c - 55.5) + 151
        category = "Unhealthy"
        color = "#ef4444"  # Red
    elif c <= 250.4:
        aqi = ((300 - 201) / (250.4 - 150.5)) * (c - 150.5) + 201
        category = "Very Unhealthy"
        color = "#a855f7"  # Purple
    else:
        aqi = ((500 - 301) / (500.4 - 250.5)) * (c - 250.5) + 301
        category = "Hazardous"
        color = "#991b1b"  # Dark Red / Maroon

    return round(aqi), category, color


def fetch_live_purple_air(ip: str = "192.168.10.241", router_host: str = "root@192.168.8.1") -> Dict[str, Any]:
    """Fetches live PurpleAir telemetry directly or via router SSH proxy.

    Returns:
        Dict with keys: "aqi", "category", "color", "pm25", "temp_f", "humidity"
    """
    url = f"http://{ip}/json"
    data = None
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Antigravity-Dashboard/1.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode('utf-8'))
    except Exception:
        pass

    if not data:
        try:
            import subprocess
            cmd = ["ssh", "-o", "ConnectTimeout=4", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", router_host, f"curl -s http://{ip}/json"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            if res.returncode == 0 and res.stdout.strip().startswith("{"):
                data = json.loads(res.stdout)
        except Exception as e:
            logging.error(f"Error fetching PurpleAir from router proxy: {e}")

    if data:
        try:
            pm25_a = float(data.get("pm2_5_atm", 0))
            pm25_b = float(data.get("pm2_5_atm_b", 0))
            pm25_avg = (pm25_a + pm25_b) / 2.0 if (pm25_a and pm25_b) else (pm25_a or pm25_b)
            aqi, category, color = calculate_epa_pm25_aqi(pm25_avg)
            return {
                "aqi": aqi,
                "category": category,
                "color": color,
                "pm25": pm25_avg,
                "temp_f": data.get("current_temp_f"),
                "humidity": data.get("current_humidity")
            }
        except Exception as e:
            logging.error(f"Error parsing PurpleAir JSON payload: {e}")

    return {}



def fetch_historical_weather(lat: str = DEFAULT_LAT, lon: str = DEFAULT_LON) -> Dict[str, Dict[str, Any]]:
    """Fetches daily average cloud cover, sunrise, and sunset times from Open-Meteo API.

    Loads the past 5 days of metrics.

    Args:
        lat: Latitude of target location.
        lon: Longitude of target location.

    Returns:
        A dictionary mapping date string "YYYY-MM-DD" to weather parameters:
        - "cloud_cover": float
        - "sunrise_hour": float
        - "sunset_hour": float
    """
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&past_days=5&daily=cloud_cover_mean,sunrise,sunset&timezone=auto"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode('utf-8'))
            daily = res.get("daily", {})
            times = daily.get("time", [])
            cloud_covers = daily.get("cloud_cover_mean", [])
            sunrises = daily.get("sunrise", [])
            sunsets = daily.get("sunset", [])
            
            weather_data: Dict[str, Dict[str, Any]] = {}
            for i, t_str in enumerate(times):
                sr_hour: float = 5.25
                ss_hour: float = 21.25
                if i < len(sunrises) and sunrises[i]:
                    try:
                        sr_dt = datetime.datetime.fromisoformat(sunrises[i])
                        sr_hour = sr_dt.hour + sr_dt.minute / 60.0
                    except Exception:
                        pass
                if i < len(sunsets) and sunsets[i]:
                    try:
                        ss_dt = datetime.datetime.fromisoformat(sunsets[i])
                        ss_hour = ss_dt.hour + ss_dt.minute / 60.0
                    except Exception:
                        pass
                
                cc = cloud_covers[i] if (i < len(cloud_covers) and cloud_covers[i] is not None) else 45.0
                
                weather_data[t_str] = {
                    "cloud_cover": cc,
                    "sunrise_hour": sr_hour,
                    "sunset_hour": ss_hour
                }
            return weather_data
    except Exception as e:
        logging.error(f"Error fetching historical weather from Open-Meteo: {e}")
        return {}
