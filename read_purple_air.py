#!/usr/bin/env python3
"""
PurpleAir Live Sensor Reader & Diagnostic Tool
Fetches and parses real-time environmental data directly from local PurpleAir sensor
and incorporates registration metadata (Sensor Index: 320498, Read Key: GC4C1V07NDLO8VGC).
"""

import sys
import json
import urllib.request
import subprocess
from datetime import datetime

# Sensor Credentials & Registration Metadata
SENSOR_MAC = "f0:24:f9:c6:67:d1"
SENSOR_INDEX = 320498
SENSOR_READ_KEY = "GC4C1V07NDLO8VGC"
SENSOR_IP = "192.168.10.241"
ROUTER_HOST = "root@192.168.8.1"


def fetch_sensor_data(ip=SENSOR_IP):
    """Attempts direct HTTP fetch first, fallback to router SSH if local subnet is isolated."""
    url = f"http://{ip}/json"

    # Try direct local connection
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Antigravity-PurpleAir/1.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode('utf-8'))
                data["_fetch_method"] = "Direct Local HTTP"
                return data
    except Exception:
        pass

    # Fallback to SSH curl via router 192.168.8.1
    try:
        cmd = ["ssh", "-o", "ConnectTimeout=4", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", ROUTER_HOST, f"curl -s http://{ip}/json"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        if result.returncode == 0 and result.stdout.strip().startswith("{"):
            data = json.loads(result.stdout)
            data["_fetch_method"] = "Router Gateway Proxy (192.168.8.1)"
            return data
    except Exception as e:
        print(f"[!] Error fetching PurpleAir telemetry: {e}")

    return None


def calculate_epa_pm25_aqi(pm25):
    """Calculates official US EPA PM2.5 Air Quality Index (AQI) from concentration (ug/m3)."""
    c = round(float(pm25), 1)
    if c <= 12.0:
        aqi = ((50 - 0) / (12.0 - 0.0)) * (c - 0.0) + 0
        category = "Good"
        color = "\033[92m"  # Green
    elif c <= 35.4:
        aqi = ((100 - 51) / (35.4 - 12.1)) * (c - 12.1) + 51
        category = "Moderate"
        color = "\033[93m"  # Yellow
    elif c <= 55.4:
        aqi = ((150 - 101) / (55.4 - 35.5)) * (c - 35.5) + 101
        category = "Unhealthy for Sensitive Groups"
        color = "\033[38;5;208m"  # Orange
    elif c <= 150.4:
        aqi = ((200 - 151) / (150.4 - 55.5)) * (c - 55.5) + 151
        category = "Unhealthy"
        color = "\033[91m"  # Red
    elif c <= 250.4:
        aqi = ((300 - 201) / (250.4 - 150.5)) * (c - 150.5) + 201
        category = "Very Unhealthy"
        color = "\033[95m"  # Purple
    else:
        aqi = ((500 - 301) / (500.4 - 250.5)) * (c - 250.5) + 301
        category = "Hazardous"
        color = "\033[35m"  # Maroon

    return round(aqi), category, color


def print_dashboard(data):
    if not data:
        print("[!] No data available from PurpleAir sensor.")
        return

    reset_color = "\033[0m"
    bold = "\033[1m"
    cyan = "\033[96m"
    dim = "\033[2m"

    sensor_id = data.get("SensorId", SENSOR_MAC)
    geo_name = data.get("Geo", "PurpleAir-67d1")
    place = data.get("place", "outside")
    uptime_sec = data.get("uptime", 0)
    uptime_str = f"{uptime_sec // 3600}h {(uptime_sec % 3600) // 60}m {uptime_sec % 60}s"
    method = data.get("_fetch_method", "Unknown")

    # Environmental Metrics
    temp_f = data.get("current_temp_f", 0)
    temp_c = (temp_f - 32) * 5 / 9 if temp_f else 0
    humidity = data.get("current_humidity", 0)
    dewpoint_f = data.get("current_dewpoint_f", 0)
    pressure = data.get("pressure", 0)

    # Particle Concentrations (Channel A & B average)
    pm25_a = float(data.get("pm2_5_atm", 0))
    pm25_b = float(data.get("pm2_5_atm_b", 0))
    pm25_avg = (pm25_a + pm25_b) / 2.0 if (pm25_a and pm25_b) else (pm25_a or pm25_b)

    aqi, category, color = calculate_epa_pm25_aqi(pm25_avg)

    pm1_0 = float(data.get("pm1_0_atm", 0))
    pm10_0 = float(data.get("pm10_0_atm", 0))

    # Diagnostics
    rssi = data.get("rssi", "N/A")
    wlstate = data.get("wlstate", "N/A")
    ssid = data.get("ssid", "N/A")
    version = data.get("version", "N/A")
    http_success = data.get("httpsuccess", 0)
    http_sends = data.get("httpsends", 0)

    print("\n" + "=" * 68)
    print(f"{bold}{cyan}        PURPLEAIR LIVE SENSOR DASHBOARD - {geo_name}{reset_color}")
    print("=" * 68)

    print(f" {bold}MAC / Device ID:{reset_color}  {sensor_id}")
    print(f" {bold}Sensor Index:{reset_color}     {SENSOR_INDEX}  |  {bold}Read Key:{reset_color} {SENSOR_READ_KEY}")
    print(f" {bold}Location Type:{reset_color}    {place.title()} (Public Visibility)  |  {bold}Firmware:{reset_color} v{version}")
    print(f" {bold}Telemetry Route:{reset_color}  {method}")
    print(f" {bold}Device Uptime:{reset_color}    {uptime_str}  |  {bold}Wi-Fi Signal:{reset_color} {rssi} dBm ({wlstate})")
    print(f" {bold}Cloud Sync Status:{reset_color} {http_success}/{http_sends} HTTP uploads successful ({http_success / max(1, http_sends) * 100:.1f}%)")
    print("-" * 68)

    print(f"\n {bold}AIR QUALITY INDEX (US EPA PM2.5):{reset_color}")
    print(f"   {color}{bold}AQI Score: {aqi} - {category.upper()}{reset_color}")
    print(f"   {dim}PM2.5 Avg Concentration: {pm25_avg:.2f} µg/m³ (Ch A: {pm25_a:.2f}, Ch B: {pm25_b:.2f}){reset_color}")

    print(f"\n {bold}PARTICULATE MATTER BREAKDOWN:{reset_color}")
    print(f"   • PM1.0  (Ultra-fine): {pm1_0:>6.2f} µg/m³")
    print(f"   • PM2.5  (Fine):       {pm25_avg:>6.2f} µg/m³")
    print(f"   • PM10.0 (Coarse):     {pm10_0:>6.2f} µg/m³")

    print(f"\n {bold}ENVIRONMENTAL TELEMETRY:{reset_color}")
    print(f"   • Temperature:    {temp_f}°F ({temp_c:.1f}°C)")
    print(f"   • Relative Humid: {humidity}%")
    print(f"   • Dew Point:      {dewpoint_f}°F")
    print(f"   • Barometer:      {pressure:.2f} hPa")

    print("\n" + "=" * 68 + "\n")


if __name__ == "__main__":
    ip = sys.argv[1] if len(sys.argv) > 1 else SENSOR_IP
    telemetry = fetch_sensor_data(ip)
    print_dashboard(telemetry)
