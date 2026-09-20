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
from typing import Any, Dict, List, Optional

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import pyemvue
from pyemvue.enums import Scale, Unit


logger = logging.getLogger(__name__)

class EmporiaVueClient:
    """Client for interacting with Emporia Vue energy monitoring systems via pyemvue.

    Attributes:
        username: Emporia Vue account username (email).
        token_file: Path to token storage JSON file.
        vue: PyEmVue API client instance.
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
        self.vue: pyemvue.PyEmVue = pyemvue.PyEmVue()

        # Ensure parent directory exists for token storage
        token_dir = os.path.dirname(os.path.abspath(self.token_file))
        if not os.path.exists(token_dir):
            os.makedirs(token_dir, exist_ok=True)

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
                keys = self.vue.login(token_storage_file=self.token_file)
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
            keys = self.vue.login(
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
        devices = self.vue.get_devices()
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
        scale: Scale = Scale.MINUTE,
        unit: Unit = Unit.KWH
    ) -> Dict[int, Any]:
        """Fetches current usage for all enumerated devices across channels.

        Args:
            scale: Sampling resolution (Scale.SECOND, Scale.MINUTE, Scale.HOUR, Scale.DAY).
            unit: Telemetry unit (Unit.KWH, Unit.VOLTS, etc.).

        Returns:
            Dictionary mapping device GIDs to channel usage data.
        """
        devices = self.vue.get_devices()
        device_gids = [d.device_gid for d in devices if hasattr(d, 'device_gid')]

        if not device_gids:
            logger.warning("No Emporia Vue device GIDs found.")
            return {}

        usage_dict = self.vue.get_device_list_usage(
            deviceGids=device_gids,
            instant=None,
            scale=scale.value if hasattr(scale, 'value') else scale,
            unit=unit.value if hasattr(unit, 'value') else unit
        )
        return usage_dict

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
