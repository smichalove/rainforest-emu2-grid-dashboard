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
