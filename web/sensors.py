"""Live Sensor Aggregator for PurpleAir, Awair, and Open-Meteo Weather."""

import time
import json
import logging
import urllib.request
from typing import Dict, Any, Optional

from .config import PURPLEAIR_IP, AWAIR_IP, DEFAULT_LAT, DEFAULT_LON

logger = logging.getLogger("rainforest.sensors")

# In-memory sensor cache (60s TTL)
_sensor_cache: Dict[str, Any] = {
    "purpleair": {"data": None, "fetched_at": 0},
    "awair": {"data": None, "fetched_at": 0},
    "weather": {"data": None, "fetched_at": 0}
}
CACHE_TTL_SECS = 45


def calculate_epa_aqi(pm25: float) -> Dict[str, Any]:
    """Calculates official US EPA PM2.5 AQI, Category, and Color."""
    try:
        c = round(float(pm25), 1)
    except Exception:
        return {"aqi": 0, "category": "Unknown", "color": "#64748b"}

    if c <= 12.0:
        aqi = round(((50 - 0) / (12.0 - 0.0)) * (c - 0.0) + 0)
        category = "Good"
        color = "#22c55e"
    elif c <= 35.4:
        aqi = round(((100 - 51) / (35.4 - 12.1)) * (c - 12.1) + 51)
        category = "Moderate"
        color = "#eab308"
    elif c <= 55.4:
        aqi = round(((150 - 101) / (55.4 - 35.5)) * (c - 35.5) + 101)
        category = "Sensitive"
        color = "#f97316"
    elif c <= 150.4:
        aqi = round(((200 - 151) / (150.4 - 55.5)) * (c - 55.5) + 151)
        category = "Unhealthy"
        color = "#ef4444"
    else:
        aqi = 300
        category = "Hazardous"
        color = "#7c3aed"

    return {"aqi": aqi, "category": category, "color": color, "pm25": c}


def fetch_purpleair(ip: str = PURPLEAIR_IP) -> Dict[str, Any]:
    """Queries the local PurpleAir sensor JSON endpoint."""
    now = time.time()
    if _sensor_cache["purpleair"]["data"] and (now - _sensor_cache["purpleair"]["fetched_at"] < CACHE_TTL_SECS):
        return _sensor_cache["purpleair"]["data"]

    url = f"http://{ip}/json"
    result = {"online": False, "pm2_5": 0.0, "aqi": 0, "category": "Offline", "color": "#64748b"}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RainforestWebDashboard/1.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            pm2_5_a = float(data.get("pm2_5_atm", 0.0))
            pm2_5_b = float(data.get("pm2_5_atm_b", pm2_5_a))
            avg_pm25 = (pm2_5_a + pm2_5_b) / 2.0
            
            epa = calculate_epa_aqi(avg_pm25)
            result = {
                "online": True,
                "pm2_5": round(avg_pm25, 1),
                "aqi": epa["aqi"],
                "category": epa["category"],
                "color": epa["color"],
                "temp_f": data.get("current_temp_f"),
                "humidity": data.get("current_humidity")
            }
    except Exception as e:
        logger.debug(f"PurpleAir offline at {ip}: {e}")

    _sensor_cache["purpleair"] = {"data": result, "fetched_at": now}
    return result


def fetch_awair(ip: str = AWAIR_IP) -> Dict[str, Any]:
    """Queries local Awair Element air data endpoint."""
    now = time.time()
    if _sensor_cache["awair"]["data"] and (now - _sensor_cache["awair"]["fetched_at"] < CACHE_TTL_SECS):
        return _sensor_cache["awair"]["data"]

    url = f"http://{ip}/air-data/latest"
    result = {"online": False, "score": 0, "co2": 0, "voc": 0, "temp_c": 0.0, "temp_f": 0.0, "humid": 0.0}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RainforestWebDashboard/1.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            temp_c = float(data.get("temp", 20.0))
            temp_f = round((temp_c * 9.0 / 5.0) + 32.0, 1)
            result = {
                "online": True,
                "score": data.get("score", 0),
                "co2": data.get("co2", 0),
                "voc": data.get("voc", 0),
                "temp_f": temp_f,
                "humid": round(float(data.get("humid", 0)), 1)
            }
    except Exception as e:
        logger.debug(f"Awair offline at {ip}: {e}")

    _sensor_cache["awair"] = {"data": result, "fetched_at": now}
    return result


def fetch_weather(lat: str = DEFAULT_LAT, lon: str = DEFAULT_LON) -> Dict[str, Any]:
    """Queries Open-Meteo for live ambient temperature & solar cloud cover."""
    now = time.time()
    if _sensor_cache["weather"]["data"] and (now - _sensor_cache["weather"]["fetched_at"] < 300):
        return _sensor_cache["weather"]["data"]

    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code,cloud_cover&timezone=auto"
    result = {"online": False, "temp_f": 68.0, "cloud_cover": 0, "description": "Sunny"}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RainforestWebDashboard/1.0"})
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            cur = data.get("current", {})
            temp_c = cur.get("temperature_2m", 20.0)
            temp_f = round((temp_c * 9.0 / 5.0) + 32.0, 1)
            clouds = cur.get("cloud_cover", 0)
            code = cur.get("weather_code", 0)

            desc = "Clear"
            if clouds > 70:
                desc = "Overcast"
            elif clouds > 30:
                desc = "Partly Cloudy"
            if code in [51, 53, 55, 61, 63, 65, 80, 81]:
                desc = "Rain / Showers"

            result = {
                "online": True,
                "temp_f": temp_f,
                "cloud_cover": clouds,
                "description": desc
            }
    except Exception as e:
        logger.warning(f"Error fetching weather: {e}")

    _sensor_cache["weather"] = {"data": result, "fetched_at": now}
    return result
