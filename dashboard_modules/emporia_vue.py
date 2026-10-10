"""Emporia Vue energy monitoring module using pyemvue.

This module provides AWS Cognito authentication (supporting cached session token
re-use and interactive zero-plaintext password entry), device enumeration, and
real-time circuit telemetry fetching.

Architectural Role:
    Integrates cloud-based circuit-level energy monitoring into the dashboard
    and external hardware power daemons to enable automated thermal cooling
    and circuit-specific telemetry analysis.
"""

import getpass
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import urllib.request
urllib.request.getproxies = lambda: {}

os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import random
import time

try:
    import pyemvue
except ImportError:
    pyemvue = None

logger = logging.getLogger(__name__)

# Category definitions and visual hex palettes
CATEGORY_COLORS: Dict[str, str] = {
    "Main & Grid": "#c084fc",           # Lavender / Purple
    "Compute & Lab": "#38bdf8",         # Sky Blue
    "Audio & Entertainment": "#4ade80", # Vibrant Green
    "Major Appliances": "#f87171",      # Coral Red
    "General Household": "#facc15",     # Amber Yellow
    "Balance": "#94a3b8",               # Slate Gray
}

def classify_circuit(circuit_name: str) -> tuple[str, str]:
    """Categorizes an electrical circuit or smart plug by functional zone.

    Args:
        circuit_name: Human-readable name of circuit or smart plug.

    Returns:
        Tuple of (Category Name, Hex Color String).
    """
    name_lower = (circuit_name or "").lower()

    # 0. Whole-Home Mains
    if "main" in name_lower and "right main" not in name_lower:
        return "Main & Grid", CATEGORY_COLORS["Main & Grid"]

    # 0. Balance (Unmonitored remainder: main - total)
    if any(k in name_lower for k in ["balance", "residual", "unmonitored", "other"]):
        return "Balance", CATEGORY_COLORS["Balance"]
    
    # 1. Compute & Lab
    if any(k in name_lower for k in [
        "office", "big-len", "giga", "macbook", "server", "homelab", "lem"
    ]):
        return "Compute & Lab", CATEGORY_COLORS["Compute & Lab"]
    
    # 2. Audio & Entertainment
    if any(k in name_lower for k in [
        "music", "audio", "amp", "avm", "tv", "right main"
    ]):
        return "Audio & Entertainment", CATEGORY_COLORS["Audio & Entertainment"]
    
    # 3. Major Appliances & HVAC
    if any(k in name_lower for k in [
        "a/c", "ac", "furnace", "heat", "dryer", "pump", "blower", "water heater", "charger"
    ]):
        return "Major Appliances", CATEGORY_COLORS["Major Appliances"]
    
    # 4. Default: General Household
    return "General Household", CATEGORY_COLORS["General Household"]


def _safe_usage_to_watts(val_obj: Any) -> float:
    """Safely extracts usage from a pyemvue channel/device object and converts 1S kWh to Watts."""
    raw = None
    if hasattr(val_obj, "usage"):
        raw = getattr(val_obj, "usage")
    elif isinstance(val_obj, (int, float)):
        raw = val_obj

    if raw is None:
        return 0.0
    try:
        val_float = float(raw)
    except (ValueError, TypeError):
        return 0.0

    # 1-second kWh to Watts: Watts = (kWh / 1s) * 3600s * 1000W/kW
    # If the value is already in Watts (> 100 on 1S interval is physically impossible for 1S kWh in a home)
    if val_float < 100.0:
        return val_float * 3600.0 * 1000.0
    return val_float


def generate_simulated_telemetry() -> List[Dict[str, Any]]:
    """Generates realistic fluctuating real-time circuit and plug telemetry.

    Accurately mirrors the physical electrical panel channels and 13 smart plugs
    documented in the system architecture topology, plus whole-home 200A mains
    and unmonitored residual load.

    Args:
        None.

    Returns:
        A list of dictionary objects representing circuits with instantaneous watts,
        category, and color assignments.
    """
    # Base profiles for panel circuits (Watts)
    panel_profiles = [
        {"name": "1 family room -office", "base_w": 580.0, "jitter": 90.0, "type": "panel"},
        {"name": "2 studio 2", "base_w": 65.0, "jitter": 15.0, "type": "panel"},
        {"name": "3 master bathroom 3", "base_w": 40.0, "jitter": 10.0, "type": "panel"},
        {"name": "4 garage 4", "base_w": 35.0, "jitter": 8.0, "type": "panel"},
        {"name": "5 unknown", "base_w": 18.0, "jitter": 5.0, "type": "panel"},
        {"name": "A/C (Ch 6 & 13)", "base_w": 0.0, "jitter": 0.0, "type": "panel"},
        {"name": "7 kitchen plugs", "base_w": 140.0, "jitter": 45.0, "type": "panel"},
        {"name": "8 Kitchen lights & plugs", "base_w": 75.0, "jitter": 20.0, "type": "panel"},
        {"name": "music room right main (Ch 10)", "base_w": 260.0, "jitter": 40.0, "type": "panel"},
        {"name": "bedroom floor heat (Ch 12)", "base_w": 0.0, "jitter": 0.0, "type": "panel"},
        {"name": "dryer (Ch 15)", "base_w": 0.0, "jitter": 0.0, "type": "panel"},
        {"name": "16 music room", "base_w": 95.0, "jitter": 15.0, "type": "panel"},
    ]

    # Base profiles for 13 smart plugs (Watts)
    plug_profiles = [
        {"name": "big-len UPS", "base_w": 310.0, "jitter": 35.0, "type": "plug"},
        {"name": "giga and lem", "base_w": 145.0, "jitter": 20.0, "type": "plug"},
        {"name": "MacBook", "base_w": 65.0, "jitter": 25.0, "type": "plug"},
        {"name": "bedroom ups", "base_w": 85.0, "jitter": 15.0, "type": "plug"},
        {"name": "avm 60", "base_w": 70.0, "jitter": 5.0, "type": "plug"},
        {"name": "kitchen tv", "base_w": 45.0, "jitter": 10.0, "type": "plug"},
        {"name": "music room fan", "base_w": 28.0, "jitter": 4.0, "type": "plug"},
        {"name": "dining room fan", "base_w": 24.0, "jitter": 3.0, "type": "plug"},
        {"name": "downstairs fan", "base_w": 26.0, "jitter": 3.0, "type": "plug"},
        {"name": "kitchen fan", "base_w": 30.0, "jitter": 4.0, "type": "plug"},
        {"name": "zoo spotlight", "base_w": 18.0, "jitter": 2.0, "type": "plug"},
        {"name": "coffee maker light", "base_w": 4.0, "jitter": 1.0, "type": "plug"},
        {"name": "kettle emporia", "base_w": 0.0, "jitter": 0.0, "type": "plug"},
    ]

    now = time.time()
    circuits: List[Dict[str, Any]] = []

    for item in panel_profiles + plug_profiles:
        jitter_val = random.uniform(-item["jitter"], item["jitter"]) if item["jitter"] > 0 else 0.0
        watts = max(0.0, item["base_w"] + jitter_val)
        cat_name, cat_color = classify_circuit(item["name"])
        
        circuits.append({
            "name": item["name"],
            "watts": round(watts, 1),
            "kw": round(watts / 1000.0, 3),
            "category": cat_name,
            "color": cat_color,
            "type": item["type"],
            "timestamp": now,
        })

    # Calculate panel branch total (monitored branch circuits)
    total_monitored_watts = round(sum(c["watts"] for c in circuits if c["type"] == "panel"), 1)

    # Realistic whole-home main power
    balance_base = 235.0  # Matches ~235W baseline from app
    balance_jitter = random.uniform(-25.0, 25.0)
    expected_balance = round(max(15.0, balance_base + balance_jitter), 1)

    mains_watts = round(total_monitored_watts + expected_balance, 1)

    # Strictly: balance === main - total
    balance_watts = round(mains_watts - total_monitored_watts, 1)

    # 1. Whole-Home Main
    main_cat, main_color = classify_circuit("200A Mains")
    circuits.append({
        "name": "200A Mains",
        "watts": mains_watts,
        "kw": round(mains_watts / 1000.0, 3),
        "category": main_cat,
        "color": main_color,
        "type": "main",
        "timestamp": now,
    })

    # 2. Balance (Unmonitored remainder: main - total)
    bal_cat, bal_color = classify_circuit("Balance")
    circuits.append({
        "name": "Balance",
        "watts": balance_watts,
        "kw": round(balance_watts / 1000.0, 3),
        "category": bal_cat,
        "color": bal_color,
        "type": "balance",
        "timestamp": now,
    })

    return circuits


def get_top_active_loads(
    circuits: List[Dict[str, Any]],
    n: int = 3,
    last_update_ts: Optional[float] = None
) -> Tuple[str, List[Dict[str, Any]]]:
    """Calculates top active consumer loads and formats a compact header status string.

    Args:
        circuits: List of circuit dictionary records.
        n: Number of top loads to include in the compact pill.
        last_update_ts: Epoch timestamp of last successful fetch.

    Returns:
        Tuple of (formatted_header_string, sorted_circuits_list).
    """
    if not circuits:
        return "⚡ Top: Awaiting Telemetry...", []

    # Sort descending by real-time power (Watts)
    sorted_circuits = sorted(circuits, key=lambda c: c.get("watts", 0.0), reverse=True)
    # Filter out whole-home mains and summary totals so the status pill reflects top individual consumer loads
    top_items = [
        c for c in sorted_circuits
        if c.get("type") not in ("main", "total")
        and c.get("category") not in ("Main & Grid", "Total Monitored")
        and c.get("watts", 0.0) > 5.0
    ][:n]

    if not top_items:
        pill_body = "All circuits idle"
    else:
        parts = []
        for c in top_items:
            # Shorten display label for header bounds
            name = c.get("name", "Unknown")
            short_name = (
                name.replace("1 family room -office", "Office")
                .replace("music room right main (Ch 10)", "Music Main")
                .replace("16 music room", "Music Room")
                .replace("8 Kitchen lights & plugs", "Kitchen")
                .replace("7 kitchen plugs", "Kitchen")
                .replace("big-len UPS", "Big-Len")
                .replace("giga and lem", "Giga/Lem")
                .replace("A/C (Ch 6 & 13)", "A/C")
                .replace("bedroom ups", "Bed UPS")
            )
            if len(short_name) > 10:
                short_name = short_name[:10].strip()
            
            watts_val = int(round(c.get("watts", 0.0)))
            parts.append(f"{short_name} {watts_val}W")
        
        pill_body = " | ".join(parts)

    age_str = ""
    if last_update_ts is not None and last_update_ts > 0:
        elapsed = max(0, int(time.time() - last_update_ts))
        age_str = f" ({elapsed}s ago)"

    pill_text = f"⚡ Top: {pill_body}{age_str}"
    return pill_text, sorted_circuits


class EmporiaVueClient:
    """Client for interacting with Emporia Vue energy monitoring systems via pyemvue.

    Attributes:
        username: Emporia Vue account username (email).
        token_file: Path to token storage JSON file.
        vue: PyEmVue API client instance.
        last_fetch_timestamp: Epoch timestamp of latest telemetry fetch.
    """

    def __init__(
        self,
        username: Optional[str] = None,
        token_file: str = "Auth/emporia_tokens.json"
    ) -> None:
        """Initializes the EmporiaVueClient.

        Args:
            username: Emporia Vue account email/username. If not provided,
                reads EMPORIA_USERNAME environment variable or prompts interactively.
            token_file: File path to save and restore AWS Cognito auth tokens.

        Returns:
            None.

        Raises:
            OSError: If directory creation for the token file fails.
        """
        self.username: str = username or os.environ.get("EMPORIA_USERNAME", "smichalove@gmail.com")
        self.token_file: str = token_file
        self.vue = None
        self.last_fetch_timestamp: float = 0.0
        self.cached_circuits: List[Dict[str, Any]] = []

        # Ensure parent directory exists for token storage
        token_dir = os.path.dirname(os.path.abspath(self.token_file))
        if not os.path.exists(token_dir):
            os.makedirs(token_dir, exist_ok=True)

    def _get_vue(self) -> Any:
        """Returns the pyemvue instance, lazily importing on first use."""
        global pyemvue
        if self.vue is None:
            if pyemvue is None:
                import pyemvue
            self.vue = pyemvue.PyEmVue()
        return self.vue

    def login(
        self,
        password: Optional[str] = None,
        interactive: bool = True
    ) -> bool:
        """Authenticates with Emporia Vue services using pyemvue.

        Attempts token restore first, falling back to interactive zero-plaintext
        password prompt if cached tokens are expired or missing.

        Args:
            password: Optional plaintext password. If None and interactive is True,
                prompts via getpass.
            interactive: Whether to prompt for username/password via stdin.

        Returns:
            True if authentication succeeded, False otherwise.

        Raises:
            None: Catches authentication exceptions and logs them cleanly.
        """
        # 1. Try restoring from token file first if it exists
        if os.path.exists(self.token_file):
            try:
                print(f"Checking cached tokens in {self.token_file}...", end="", flush=True)
                logger.info(f"Attempting login using cached tokens from {self.token_file}...")
                keys = self._get_vue().login(token_storage_file=self.token_file)
                if keys:
                    print(" Valid cached tokens loaded.", flush=True)
                    logger.info("Successfully authenticated using cached tokens.")
                    return True
                else:
                    print(" Tokens expired or invalid.", flush=True)
            except Exception as e:
                print(f" Cached tokens invalid ({e}).", flush=True)
                logger.warning(f"Cached token login failed: {e}. Falling back to fresh password login.")

        # 2. Need username
        if not self.username:
            if interactive:
                print("\nEmporia Vue Username required.")
                sys.stdout.flush()
                self.username = input("Emporia Vue Username (email): ").strip()
            else:
                logger.error("No username provided and interactive mode disabled.")
                return False

        # 3. Prompt for password if not provided
        if not password and interactive:
            print(f"\n[AUTHENTICATION REQUIRED] Account: {self.username}")
            print("Password will NOT be stored on disk; only Cognito session tokens will be saved.")
            sys.stdout.flush()
            password = getpass.getpass("Enter Emporia Vue Password: ").strip()

        if not password:
            logger.error("No password provided for Emporia Vue login.")
            return False

        # 4. Perform fresh login & save tokens
        try:
            print(f"Connecting to AWS Cognito for {self.username}...", end="", flush=True)
            logger.info(f"Authenticating with Emporia Vue API as {self.username}...")
            keys = self._get_vue().login(
                username=self.username,
                password=password,
                token_storage_file=self.token_file
            )
            if keys:
                print(" Authenticated successfully! Saved tokens.", flush=True)
                logger.info(f"Login successful. Saved tokens to {self.token_file}.")
                return True
            else:
                print(" Failed (no tokens returned).", flush=True)
                logger.error("Emporia Vue login returned no tokens.")
                return False
        except Exception as err:
            print(f" Authentication failed: {err}", flush=True)
            logger.error(f"Emporia Vue authentication failed: {err}")
            return False

    def get_device_tree(self) -> List[Dict[str, Any]]:
        """Queries and returns all connected Emporia Vue devices and channels.

        Args:
            None.

        Returns:
            A list of dictionary objects describing each device, nested sub-devices,
            and expansion CT channels.

        Raises:
            None: PyEmVue handles network errors internally.
        """
        vue = self._get_vue()
        devices = vue.get_devices()
        structured_devices: List[Dict[str, Any]] = []

        for device in devices:
            device_info = self._parse_vue_device(device)
            structured_devices.append(device_info)

        return structured_devices

    def _parse_vue_device(self, device: Any) -> Dict[str, Any]:
        """Parses a pyemvue VueDevice object into a dictionary representation."""
        channels_info = []
        if hasattr(device, 'channels') and device.channels:
            for ch in device.channels:
                channels_info.append({
                    "channel_num": getattr(ch, 'channel_num', None),
                    "name": getattr(ch, 'name', f"Channel {getattr(ch, 'channel_num', '')}"),
                    "channel_multiplier": getattr(ch, 'channel_multiplier', 1.0),
                    "type": str(getattr(ch, 'channel_type', '')),
                })

        nested_devices_info = []
        if hasattr(device, 'nested_devices') and device.nested_devices:
            for nested in device.nested_devices.values():
                nested_devices_info.append(self._parse_vue_device(nested))

        return {
            "device_gid": getattr(device, 'device_gid', None),
            "device_name": getattr(device, 'device_name', 'Unknown Device'),
            "model": getattr(device, 'model', ''),
            "firmware": getattr(device, 'firmware', ''),
            "connected": getattr(device, 'connected', True),
            "channels": channels_info,
            "nested_devices": nested_devices_info
        }

    def fetch_realtime_usage(
        self,
        scale: Any = "1S",
        unit: Any = "KilowattHours"
    ) -> Dict[int, Any]:
        """Fetches current usage for all enumerated devices across channels.

        Args:
            scale: Sampling resolution (Scale.SECOND, Scale.MINUTE, Scale.HOUR, Scale.DAY).
            unit: Telemetry unit (Unit.KWH, Unit.VOLTS, etc.).

        Returns:
            Dictionary mapping device GIDs to channel usage data.
        """
        vue = self._get_vue()
        devices = vue.get_devices()
        device_gids = [d.device_gid for d in devices if hasattr(d, 'device_gid')]

        if not device_gids:
            logger.warning("No Emporia Vue device GIDs found.")
            return {}

        try:
            from pyemvue.enums import Scale, Unit
            scale_val = Scale.SECOND.value
            unit_val = Unit.KWH.value
        except Exception:
            scale_val = "1S"
            unit_val = "KilowattHours"

        usage_dict = vue.get_device_list_usage(
            deviceGids=device_gids,
            instant=None,
            scale=scale_val,
            unit=unit_val
        )
        return usage_dict or {}

    def get_circuit_telemetry(self, use_simulator: bool = False) -> List[Dict[str, Any]]:
        """Retrieves structured real-time circuit power readings.

        Falls back cleanly to the synthetic simulator if offline, unauthenticated,
        or explicitly requested.

        Args:
            use_simulator: Force synthetic telemetry generation without API query.

        Returns:
            List of circuit telemetry dictionaries.
        """
        if use_simulator:
            self.last_fetch_timestamp = time.time()
            self.cached_circuits = generate_simulated_telemetry()
            return self.cached_circuits

        try:
            # Attempt live retrieval
            vue = self._get_vue()
            if not hasattr(vue, 'auth') or not vue.auth:
                if not self.login(interactive=False):
                    logger.info("Emporia login unavailable; falling back to simulated telemetry.")
                    return self.get_circuit_telemetry(use_simulator=True)

            tree = self.get_device_tree()
            usage = self.fetch_realtime_usage(scale="1S", unit="KilowattHours")
            
            circuits: List[Dict[str, Any]] = []
            now = time.time()
            mains_watts = 0.0
            panel_branch_watts = 0.0

            for dev in tree:
                gid = dev.get("device_gid")
                dev_name = dev.get("device_name", "")
                dev_u = usage.get(gid)
                ch_dict = dev_u.channels if dev_u and hasattr(dev_u, "channels") else (dev_u.get("channels", {}) if isinstance(dev_u, dict) else {})

                # Main panel channels
                for ch in dev.get("channels", []):
                    c_num = str(ch.get("channel_num"))
                    c_name = ch.get("name") or f"Ch {c_num}"
                    ch_u = ch_dict.get(c_num) or ch_dict.get(int(c_num) if c_num.isdigit() else 0)
                    watts = _safe_usage_to_watts(ch_u)

                    c_lower = c_name.lower()
                    if c_num in ["1,2,3", "1,2"] or ("main" in c_lower and "right main" not in c_lower and "left" not in c_lower):
                        mains_watts += max(0.0, watts)
                        continue

                    cat_name, cat_color = classify_circuit(c_name)
                    panel_branch_watts += max(0.0, watts)
                    circuits.append({
                        "name": c_name,
                        "watts": round(watts, 1),
                        "kw": round(watts / 1000.0, 3),
                        "category": cat_name,
                        "color": cat_color,
                        "type": "panel",
                        "timestamp": now,
                    })

                # Standalone smart plugs (SSO001 or devices outside main panel)
                if not dev.get("channels") or dev.get("model") == "SSO001" or (isinstance(dev.get("model"), str) and dev.get("model", "").startswith("SSO") and gid != 100920):
                    plug_u = ch_dict.get("1") or ch_dict.get(1) or ch_dict.get("1,2,3")
                    plug_w = _safe_usage_to_watts(plug_u)
                    cat_name, cat_color = classify_circuit(dev_name)
                    circuits.append({
                        "name": dev_name,
                        "watts": round(plug_w, 1),
                        "kw": round(plug_w / 1000.0, 3),
                        "category": cat_name,
                        "color": cat_color,
                        "type": "plug",
                        "timestamp": now,
                    })

                # Nested smart plugs
                for nested in dev.get("nested_devices", []):
                    n_gid = nested.get("device_gid")
                    n_name = nested.get("device_name") or "Smart Plug"
                    n_dev_u = usage.get(n_gid)
                    n_ch_dict = n_dev_u.channels if n_dev_u and hasattr(n_dev_u, "channels") else (n_dev_u.get("channels", {}) if isinstance(n_dev_u, dict) else {})
                    plug_u = n_ch_dict.get("1") or n_ch_dict.get(1) or n_ch_dict.get("1,2,3")
                    plug_w = _safe_usage_to_watts(plug_u)
                    cat_name, cat_color = classify_circuit(n_name)
                    circuits.append({
                        "name": n_name,
                        "watts": round(plug_w, 1),
                        "kw": round(plug_w / 1000.0, 3),
                        "category": cat_name,
                        "color": cat_color,
                        "type": "plug",
                        "timestamp": now,
                    })

            # Calculate Main and Balance strictly as: balance === main - total
            total_monitored_watts = round(panel_branch_watts, 1)

            if mains_watts <= 0:
                mains_watts = total_monitored_watts

            balance_watts = round(max(0.0, mains_watts - total_monitored_watts), 1)

            main_cat, main_color = classify_circuit("200A Mains")
            circuits.append({
                "name": "200A Mains",
                "watts": round(mains_watts, 1),
                "kw": round(mains_watts / 1000.0, 3),
                "category": main_cat,
                "color": main_color,
                "type": "main",
                "timestamp": now,
            })

            bal_cat, bal_color = classify_circuit("Balance")
            circuits.append({
                "name": "Balance",
                "watts": round(balance_watts, 1),
                "kw": round(balance_watts / 1000.0, 3),
                "category": bal_cat,
                "color": bal_color,
                "type": "balance",
                "timestamp": now,
            })

            if circuits:
                self.last_fetch_timestamp = now
                self.cached_circuits = circuits
                return circuits
            else:
                return self.get_circuit_telemetry(use_simulator=True)

        except Exception as e:
            logger.warning(f"Error fetching live Emporia usage: {e}; falling back to simulator.")
            return self.get_circuit_telemetry(use_simulator=True)

    def format_circuit_summary(self, devices: Optional[List[Dict[str, Any]]] = None) -> str:
        """Formats enumerated devices and channels into a human-readable text string.

        Args:
            devices: Optional list of device dicts. If None, queries get_device_tree().

        Returns:
            Formatted multi-line text summary.
        """
        if devices is None:
            devices = self.get_device_tree()

        lines = ["=== EMPORIA VUE ENUMERATED DEVICES & CIRCUITS ==="]
        if not devices:
            lines.append("No devices found.")
            return "\n".join(lines)

        for dev in devices:
            dev_name = dev.get("device_name") or "Vue Device"
            gid = dev.get("device_gid")
            model = dev.get("model") or "N/A"
            lines.append(f"\nDevice: {dev_name} (GID: {gid}, Model: {model})")

            channels = dev.get("channels", [])
            if channels:
                lines.append("  Channels / Circuits:")
                for ch in channels:
                    c_num = ch.get("channel_num")
                    c_name = ch.get("name") or f"Channel {c_num}"
                    lines.append(f"    - [Ch {c_num}] {c_name}")

            nested = dev.get("nested_devices", [])
            if nested:
                lines.append("  Sub-Devices / Expansion Monitors:")
                for n_dev in nested:
                    n_name = n_dev.get("device_name")
                    n_gid = n_dev.get("device_gid")
                    lines.append(f"    * {n_name} (GID: {n_gid})")
                    for ch in n_dev.get("channels", []):
                        c_num = ch.get("channel_num")
                        c_name = ch.get("name") or f"Channel {c_num}"
                        lines.append(f"      - [Ch {c_num}] {c_name}")

        lines.append("==================================================")
        return "\n".join(lines)
