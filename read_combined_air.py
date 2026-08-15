#!/usr/bin/env python3
"""
Combined Air Quality Diagnostic & Comparison Tool
Fetches live telemetry from both Indoor Awair Element (192.168.8.219)
and Outdoor PurpleAir (192.168.10.241 / 192.168.8.1 gateway).

Displays raw comparative readings alongside standardized US EPA PM2.5 AQI
and EPA relative humidity corrected metrics formatted via tabulate.
Shows temperature and dew point in both °F and °C.
"""

import sys
import json
import urllib.request
import urllib.error
import subprocess
from datetime import datetime

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

AWAIR_IP = "192.168.8.219"
AWAIR_URL = f"http://{AWAIR_IP}/air-data/latest"

PURPLE_IP = "192.168.10.241"
PURPLE_URL = f"http://{PURPLE_IP}/json"
ROUTER_HOST = "root@192.168.8.1"


def fetch_awair_data():
    """Fetch live data from local Awair Element."""
    req = urllib.request.Request(AWAIR_URL, headers={"User-Agent": "RainforestGridDashboard/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode('utf-8'))
                data["_status"] = "OK"
                return data
    except Exception as e:
        return {"_status": f"Error: {e}"}


def fetch_purple_data():
    """Fetch live data from local PurpleAir sensor (direct or router SSH fallback)."""
    # 1. Direct fetch
    try:
        req = urllib.request.Request(PURPLE_URL, headers={'User-Agent': 'Antigravity-PurpleAir/1.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode('utf-8'))
                data["_route"] = "Direct Local HTTP"
                data["_status"] = "OK"
                return data
    except Exception:
        pass

    # 2. SSH proxy via router
    try:
        cmd = ["ssh", "-o", "ConnectTimeout=4", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", ROUTER_HOST, f"curl -s http://{PURPLE_IP}/json"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        if result.returncode == 0 and result.stdout.strip().startswith("{"):
            data = json.loads(result.stdout)
            data["_route"] = "Router Gateway Proxy (192.168.8.1)"
            data["_status"] = "OK"
            return data
    except Exception:
        pass

    return {"_status": "Offline / Unreachable"}


def calculate_epa_pm25_aqi(pm25):
    """Calculates official US EPA PM2.5 Air Quality Index (AQI) from concentration (ug/m3)."""
    c = round(float(pm25), 1)
    if c < 0:
        c = 0.0

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
        category = "Unhealthy (Sens.)"
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


def calculate_epa_rh_corrected_pm25(raw_pm25, rh_percent):
    """
    Applies official US EPA 2021 PurpleAir RH Correction equation:
    PM2.5_EPA = 0.524 * Raw_PM2.5 - 0.0862 * RH + 5.75
    """
    try:
        pm = float(raw_pm25)
        rh = float(rh_percent)
        epa_pm = (0.524 * pm) - (0.0862 * rh) + 5.75
        return max(0.0, epa_pm)
    except Exception:
        return float(raw_pm25)


def c_to_f(c):
    return (c * 9 / 5) + 32


def f_to_c(f):
    return (f - 32) * 5 / 9


def main():
    reset = "\033[0m"
    bold = "\033[1m"
    cyan = "\033[96m"
    dim = "\033[2m"

    awair = fetch_awair_data()
    purple = fetch_purple_data()

    print("\n" + "=" * 92)
    print(f"{bold}{cyan}             INDOOR vs OUTDOOR AIR QUALITY COMPARATIVE DASHBOARD{reset}")
    print(f"{dim}             Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Local Network Telemetry{reset}")
    print("=" * 92 + "\n")

    # 1. Awair Parsing
    awair_ok = awair.get("_status") == "OK"
    if awair_ok:
        awair_pm25 = float(awair.get("pm25", 0))
        awair_pm10 = float(awair.get("pm10_est", 0))
        awair_co2 = awair.get("co2", 0)
        awair_voc = awair.get("voc", 0)
        awair_score = awair.get("score", 0)
        awair_temp_c = float(awair.get("temp", 0))
        awair_temp_f = c_to_f(awair_temp_c)
        awair_rh = float(awair.get("humid", 0))
        awair_dp_c = float(awair.get("dew_point", 0))
        awair_dp_f = c_to_f(awair_dp_c)

        awair_aqi, awair_cat, awair_col = calculate_epa_pm25_aqi(awair_pm25)
    else:
        awair_pm25 = awair_pm10 = awair_co2 = awair_voc = awair_score = 0
        awair_temp_c = awair_temp_f = awair_rh = awair_dp_c = awair_dp_f = 0
        awair_aqi = 0
        awair_cat = "N/A"
        awair_col = reset

    # 2. PurpleAir Parsing
    purple_ok = purple.get("_status") == "OK"
    if purple_ok:
        pm25_a = float(purple.get("pm2_5_atm", 0))
        pm25_b = float(purple.get("pm2_5_atm_b", 0))
        purple_pm25_raw = (pm25_a + pm25_b) / 2.0 if (pm25_a and pm25_b) else (pm25_a or pm25_b)
        purple_pm10 = float(purple.get("pm10_0_atm", 0))
        purple_temp_f = float(purple.get("current_temp_f", 0))
        purple_temp_c = f_to_c(purple_temp_f)
        purple_rh = float(purple.get("current_humidity", 0))
        purple_dp_f = float(purple.get("current_dewpoint_f", 0))
        purple_dp_c = f_to_c(purple_dp_f)

        purple_pm25_epa = calculate_epa_rh_corrected_pm25(purple_pm25_raw, purple_rh)

        purple_raw_aqi, purple_raw_cat, purple_raw_col = calculate_epa_pm25_aqi(purple_pm25_raw)
        purple_epa_aqi, purple_epa_cat, purple_epa_col = calculate_epa_pm25_aqi(purple_pm25_epa)
    else:
        purple_pm25_raw = purple_pm25_epa = purple_pm10 = 0
        purple_temp_f = purple_temp_c = purple_rh = purple_dp_f = purple_dp_c = 0
        purple_raw_aqi = purple_epa_aqi = 0
        purple_raw_cat = purple_epa_cat = "N/A"
        purple_raw_col = purple_epa_col = reset

    # --- TABLE 1: STANDARDIZED US EPA PM2.5 AQI COMPARISON ---
    t1_headers = ["Location / Sensor", "Metric / Score", "PM2.5 Conc.", "EPA AQI Category"]
    t1_rows = [
        [
            "Indoor (Awair Element)",
            f"EPA AQI: {awair_col}{bold}{awair_aqi}{reset} (Awair Score: {awair_score}/100)",
            f"{awair_pm25:.1f} µg/m³",
            f"{awair_col}{awair_cat}{reset}"
        ],
        [
            "Outdoor (PurpleAir - Raw)",
            f"EPA AQI: {purple_raw_col}{bold}{purple_raw_aqi}{reset}",
            f"{purple_pm25_raw:.1f} µg/m³",
            f"{purple_raw_col}{purple_raw_cat}{reset}"
        ],
        [
            "Outdoor (PurpleAir - EPA RH)",
            f"EPA AQI: {purple_epa_col}{bold}{purple_epa_aqi}{reset}",
            f"{purple_pm25_epa:.1f} µg/m³",
            f"{purple_epa_col}{purple_epa_cat}{reset} *(Recommended)*"
        ]
    ]

    print(f"{bold}1. STANDARDIZED US EPA PM2.5 AQI COMPARISON{reset}")
    if HAS_TABULATE:
        print(tabulate(t1_rows, headers=t1_headers, tablefmt="fancy_grid"))
    else:
        for r in t1_rows:
            print(" | ".join(r))
    print()

    # --- TABLE 2: RAW TELEMETRY COMPARATIVE MATRIX ---
    if awair_ok and purple_ok:
        pm25_raw_diff = purple_pm25_raw - awair_pm25
        pm25_epa_diff = purple_pm25_epa - awair_pm25
        pm10_diff = purple_pm10 - awair_pm10
        temp_f_diff = purple_temp_f - awair_temp_f
        temp_c_diff = purple_temp_c - awair_temp_c
        rh_diff = purple_rh - awair_rh
        dp_f_diff = purple_dp_f - awair_dp_f
        dp_c_diff = purple_dp_c - awair_dp_c

        t2_headers = ["Measurement Parity", "Indoor (Awair)", "Outdoor (PurpleAir)", "Delta (Out - In)"]
        t2_rows = [
            [
                "PM2.5 (Raw Laser)",
                f"{awair_pm25:.1f} µg/m³",
                f"{purple_pm25_raw:.1f} µg/m³",
                f"{pm25_raw_diff:+.1f} µg/m³"
            ],
            [
                "PM2.5 (EPA Corrected)",
                f"{awair_pm25:.1f} µg/m³",
                f"{purple_pm25_epa:.1f} µg/m³",
                f"{pm25_epa_diff:+.1f} µg/m³"
            ],
            [
                "PM10.0 (Coarse Dust)",
                f"{awair_pm10:.1f} µg/m³",
                f"{purple_pm10:.1f} µg/m³",
                f"{pm10_diff:+.1f} µg/m³"
            ],
            [
                "Temperature",
                f"{awair_temp_f:.1f} °F ({awair_temp_c:.1f} °C)",
                f"{purple_temp_f:.1f} °F ({purple_temp_c:.1f} °C)",
                f"{temp_f_diff:+.1f} °F ({temp_c_diff:+.1f} °C)"
            ],
            [
                "Relative Humidity",
                f"{awair_rh:.1f} %",
                f"{purple_rh:.1f} %",
                f"{rh_diff:+.1f} %"
            ],
            [
                "Dew Point",
                f"{awair_dp_f:.1f} °F ({awair_dp_c:.1f} °C)",
                f"{purple_dp_f:.1f} °F ({purple_dp_c:.1f} °C)",
                f"{dp_f_diff:+.1f} °F ({dp_c_diff:+.1f} °C)"
            ]
        ]

        print(f"{bold}2. RAW TELEMETRY COMPARATIVE MATRIX{reset}")
        if HAS_TABULATE:
            print(tabulate(t2_rows, headers=t2_headers, tablefmt="fancy_grid"))
        else:
            for r in t2_rows:
                print(" | ".join(r))
        print()

    # --- TABLE 3: INDOOR-ONLY GAS & CHEMICAL TELEMETRY ---
    if awair_ok:
        co2_status = "\033[92mGood\033[0m" if awair_co2 < 800 else ("\033[93mFair\033[0m" if awair_co2 < 1000 else "\033[91mHigh\033[0m")
        voc_status = "\033[92mGood\033[0m" if awair_voc < 333 else ("\033[93mFair\033[0m" if awair_voc < 1000 else "\033[91mHigh\033[0m")

        t3_headers = ["Indoor Gas Metric", "Current Value", "Baseline Target", "Status"]
        t3_rows = [
            ["Carbon Dioxide (CO2)", f"{awair_co2} ppm", "< 800 ppm", co2_status],
            ["Volatile Organic Compounds (VOC)", f"{awair_voc} ppb", "< 333 ppb", voc_status]
        ]

        print(f"{bold}3. INDOOR-ONLY GAS & CHEMICAL TELEMETRY (Awair Element){reset}")
        if HAS_TABULATE:
            print(tabulate(t3_rows, headers=t3_headers, tablefmt="fancy_grid"))
        else:
            for r in t3_rows:
                print(" | ".join(r))

    print("\n" + "=" * 92 + "\n")


if __name__ == "__main__":
    main()
