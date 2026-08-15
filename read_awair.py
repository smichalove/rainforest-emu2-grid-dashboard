#!/usr/bin/env python3
"""
Awair Element Local LAN Diagnostic Reader
Queries Awair Element directly over LAN (192.168.8.219) via its local REST API.
"""

import sys
import json
import urllib.request
import urllib.error
from datetime import datetime

AWAIR_IP = "192.168.8.219"
URL = f"http://{AWAIR_IP}/air-data/latest"

def fetch_awair_data():
    req = urllib.request.Request(URL, headers={"User-Agent": "RainforestGridDashboard/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"Error querying Awair local API at {URL}: {e}")
        return None

def c_to_f(c):
    return (c * 9/5) + 32

def main():
    data = fetch_awair_data()
    if not data:
        sys.exit(1)

    score = data.get("score", 0)
    temp_c = data.get("temp", 0.0)
    temp_f = c_to_f(temp_c)
    humid = data.get("humid", 0.0)
    co2 = data.get("co2", 0)
    voc = data.get("voc", 0)
    pm25 = data.get("pm25", 0)
    pm10 = data.get("pm10_est", 0)
    dew_point_c = data.get("dew_point", 0.0)
    dew_point_f = c_to_f(dew_point_c)
    timestamp_str = data.get("timestamp", datetime.now().isoformat())

    # Score rating
    if score >= 80:
        score_status = "GOOD"
        score_color = "\033[92m"  # Green
    elif score >= 60:
        score_status = "FAIR"
        score_color = "\033[93m"  # Yellow
    else:
        score_status = "POOR"
        score_color = "\033[91m"  # Red
    reset_color = "\033[0m"

    print("=" * 68)
    print("        AWAIR ELEMENT INDOOR AIR QUALITY DASHBOARD")
    print("=" * 68)
    print(f" Device IP:        {AWAIR_IP}")
    print(f" Sensor Telemetry: Direct Local LAN API (Port 80)")
    print(f" Reading Time:     {timestamp_str}")
    print("-" * 68)
    print()
    print(f" INDOOR AIR QUALITY SCORE:")
    print(f"   Score: {score_color}{score} / 100 ({score_status}){reset_color}")
    print()
    print(" SENSOR MEASUREMENTS:")
    print(f"   • Carbon Dioxide (CO2):  {co2} ppm")
    print(f"   • Volatile Chemicals (VOC): {voc} ppb")
    print(f"   • Fine Dust (PM2.5):     {pm25} µg/m³")
    print(f"   • Coarse Dust (PM10):    {pm10} µg/m³")
    print()
    print(" ENVIRONMENTAL CONDITIONS:")
    print(f"   • Temperature:    {temp_f:.1f}°F ({temp_c:.1f}°C)")
    print(f"   • Relative Humid: {humid:.1f}%")
    print(f"   • Dew Point:      {dew_point_f:.1f}°F ({dew_point_c:.1f}°C)")
    print("=" * 68)

if __name__ == "__main__":
    main()
