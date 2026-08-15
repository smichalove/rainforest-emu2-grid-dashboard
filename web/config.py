"""Configuration management for Rainforest Web Dashboard."""

import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("RAINFOREST_DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = DATA_DIR / "grid_history.db"
SUMMARY_PATH = DATA_DIR / "gemini_summary.json"

# CSV Data Paths
SOLAREDGE_CSV = DATA_DIR / "solaredge_history.csv"
BATTERY_CSV = DATA_DIR / "solaredge_battery_history.csv"
CHILICON_CSV = DATA_DIR / "chilicon_history.csv"

# Remote Collector (Pi) Details
PI_COLLECTOR_HOST = os.getenv("PI_COLLECTOR_HOST", "192.168.8.122")
PI_COLLECTOR_USER = os.getenv("PI_COLLECTOR_USER", "steven")
PI_COLLECTOR_PATH = os.getenv("PI_COLLECTOR_PATH", "/home/steven/rainforest-emu2-grid-dashboard")

# Direct Sensor Endpoints
PURPLEAIR_IP = os.getenv("PURPLEAIR_IP", "192.168.10.241")
AWAIR_IP = os.getenv("AWAIR_IP", "192.168.8.219")

# Server Config
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8000"))

# Slideshow Timings (seconds)
SLIDE_TIME_DOMAIN_SECS = int(os.getenv("SLIDE_TIME_DOMAIN_SECS", "45"))
SLIDE_FREQ_DOMAIN_SECS = int(os.getenv("SLIDE_FREQ_DOMAIN_SECS", "15"))

# Geographical Coordinates (for solar & weather)
DEFAULT_LAT = os.getenv("LATITUDE", "47.6062")
DEFAULT_LON = os.getenv("LONGITUDE", "-122.3321")
