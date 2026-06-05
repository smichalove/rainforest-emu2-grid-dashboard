"""Centralized configuration, color tokens, and credential loaders for the grid dashboard.

This module loads credentials from environment variables and local JSON auth
files, and defines styling parameters used by both the GUI and local plots.
"""

import json
import logging
import os
from typing import Dict, Optional, Tuple

# Rainforest EMU-2 hardware communication settings
BAUD: int = 115200

# Gemini / Vertex AI Summary Display Settings
SUMMARY_FONT_SIZE: int = 10
SUMMARY_ALPHA: float = 0.55
SUMMARY_COLOR: str = 'deepskyblue'

# Real-time Status Label Settings (clipping-prevented size)
STATUS_FONT_SIZE: int = 24

# Default location coordinates (Issaquah/Seattle region)
DEFAULT_LAT: str = os.environ.get("WEATHER_LAT", "47.5760")
DEFAULT_LON: str = os.environ.get("WEATHER_LON", "-122.0193")

DEFAULT_WEATHER_FALLBACK: Dict[str, float] = {
    "cloud_cover": 45.0,
    "sunrise_hour": 5.25,
    "sunset_hour": 21.25
}

# Color tokens for grid status and line plot
IMPORT_COLOR: str = '#f43f5e'          # Modern rose/crimson red
EXPORT_COLOR: str = '#00ff00'          # Classic neon green
EXPECTED_SOLAR_COLOR: str = '#ffff00'  # Bright yellow for expected weather-modulated solar
CONSUMPTION_COLOR: str = '#ff5e00'     # Neon orange for household consumption

# Slide Rotation Interval Settings (in milliseconds)
SLIDE_1_DURATION_MS: int = 90000       # 1.5 minutes
SLIDE_2_DURATION_MS: int = 15000       # 15 seconds


def load_env_credentials() -> Tuple[Dict[str, Optional[str]], Dict[str, Optional[str]]]:
    """Loads environment variables and parses local credentials files.

    Returns:
        A tuple of two dictionaries:
            - SolarEdge credentials: {"api_key": ..., "site_id": ...}
            - Chillicon credentials: {"username": ..., "password": ..., "installation_hash": ...}
    """
    home_dir: str = os.path.expanduser('~')
    script_dir: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Load local .env file if it exists
    env_path = os.path.join(script_dir, ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
            logging.info("Loaded environment variables from local .env file.")
        except Exception as env_err:
            logging.warning(f"Could not parse local .env file: {env_err}")

    # Auto-discover and configure service account credentials path
    possible_paths = [
        os.path.join(script_dir, "Auth/service_account.json"),
        os.path.join(script_dir, "auth/service_account.json"),
        os.path.join(home_dir, "Auth/service_account.json"),
        os.path.join(home_dir, "auth/service_account.json")
    ]
    for path in possible_paths:
        if os.path.exists(path):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
            logging.info(f"Using service account key found at: {path}")
            break

    # Load SolarEdge config
    solaredge_credentials = {
        "api_key": os.environ.get("SOLAREDGE_API_KEY"),
        "site_id": os.environ.get("SOLAREDGE_SITE_ID"),
    }
    se_paths = [
        os.path.join(script_dir, "Auth/solaredge_config.json"),
        os.path.join(script_dir, "auth/solaredge_config.json"),
        os.path.join(home_dir, "Auth/solaredge_config.json"),
        os.path.join(home_dir, "auth/solaredge_config.json")
    ]
    for path in se_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                    if not solaredge_credentials["api_key"]:
                        solaredge_credentials["api_key"] = data.get("api_key")
                    if not solaredge_credentials["site_id"]:
                        solaredge_credentials["site_id"] = data.get("site_id")
                    logging.info(f"Loaded SolarEdge credentials from: {path}")
                    break
            except Exception as e:
                logging.warning(f"Could not parse credentials file {path}: {e}")

    # Load Chillicon config
    chilicon_credentials = {
        "username": os.environ.get("CHILICON_USERNAME"),
        "password": os.environ.get("CHILICON_PASSWORD"),
        "installation_hash": os.environ.get("CHILICON_INSTALLATION_HASH"),
    }
    chilicon_paths = [
        os.path.join(script_dir, "Auth/chilicon_config.json"),
        os.path.join(script_dir, "auth/chilicon_config.json"),
        os.path.join(home_dir, "Auth/chilicon_config.json"),
        os.path.join(home_dir, "auth/chilicon_config.json")
    ]
    for path in chilicon_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                    if not chilicon_credentials["username"]:
                        chilicon_credentials["username"] = data.get("username")
                    if not chilicon_credentials["password"]:
                        chilicon_credentials["password"] = data.get("password")
                    if not chilicon_credentials["installation_hash"]:
                        chilicon_credentials["installation_hash"] = data.get("installation_hash")
                    logging.info(f"Loaded Chillicon credentials from: {path}")
                    break
            except Exception as e:
                logging.warning(f"Could not parse Chillicon credentials file {path}: {e}")

    return solaredge_credentials, chilicon_credentials
