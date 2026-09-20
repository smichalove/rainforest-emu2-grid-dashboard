#!/usr/bin/env python3
"""Standalone CLI test runner for Emporia Vue authentication & circuit enumeration.

Usage:
    # First time login (will prompt interactively for password, saving tokens to Auth/emporia_tokens.json):
    python3 read_emporia_vue.py --username your_email@example.com

    # Subsequent runs (uses cached tokens, no password required):
    python3 read_emporia_vue.py

    # Force re-authentication (prompts for password and updates token file):
    python3 read_emporia_vue.py --force-login

    # Test mode with synthetic mock devices:
    python3 read_emporia_vue.py --emulate
"""

import argparse
import json
import logging
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Prevent macOS proxy resolution delays and metadata polling
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

print("==================================================")
print("      EMPORIA VUE TELEMETRY & CIRCUIT ENUMERATOR   ")
print("==================================================")
print("Loading Emporia Vue client modules...", flush=True)
from dashboard_modules.emporia_vue import EmporiaVueClient
print("Ready!\n", flush=True)

logging.basicConfig(
    level=logging.WARNING,  # Keep logging clean for interactive CLI
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)




def create_emulated_client() -> EmporiaVueClient:
    """Creates a mock EmporiaVueClient for testing without live credentials.

    Args:
        None.

    Returns:
        EmporiaVueClient configured with emulated device hardware tree.

    Raises:
        None.
    """
    client = EmporiaVueClient(username="demo@example.com", token_file="scratch/emulated_tokens.json")

    # Mock get_device_tree
    def mock_get_device_tree():
        return [
            {
                "device_gid": 10001,
                "device_name": "Main Panel Vue 2",
                "model": "VUE002",
                "firmware": "2.1.0",
                "connected": True,
                "channels": [
                    {"channel_num": "1,2", "name": "Main Grid Mains", "channel_multiplier": 1.0, "type": "Mains"},
                    {"channel_num": "1", "name": "Heat Pump Outdoor Unit", "channel_multiplier": 1.0, "type": "50A CT"},
                    {"channel_num": "2", "name": "Air Handler / Blower", "channel_multiplier": 1.0, "type": "50A CT"},
                    {"channel_num": "3", "name": "EV Charger (Level 2)", "channel_multiplier": 1.0, "type": "50A CT"},
                    {"channel_num": "4", "name": "IT Server Rack / Homelab", "channel_multiplier": 1.0, "type": "50A CT"},
                    {"channel_num": "5", "name": "Kitchen Microwave & Oven", "channel_multiplier": 1.0, "type": "50A CT"},
                    {"channel_num": "6", "name": "Electric Water Heater", "channel_multiplier": 1.0, "type": "50A CT"},
                ],
                "nested_devices": []
            }
        ]

    client.login = lambda password=None, interactive=True: True
    client.get_device_tree = mock_get_device_tree
    return client


def main() -> None:
    """Primary CLI entrypoint for authenticating and querying Emporia Vue devices.

    Args:
        None.

    Returns:
        None.

    Raises:
        SystemExit: If authentication fails.
    """
    parser.add_argument("--username", "-u", type=str, help="Emporia Vue account username (email)")
    parser.add_argument("--token-file", type=str, default="Auth/emporia_tokens.json", help="Path to token JSON file")
    parser.add_argument("--force-login", action="store_true", help="Force fresh login with password prompt")
    parser.add_argument("--emulate", action="store_true", help="Run with mock/emulated device hardware")
    parser.add_argument("--poll", action="store_true", help="Poll live usage after enumerating circuits")
    args = parser.parse_args()

    if args.emulate:

        print("[EMULATION MODE] Running with synthetic hardware devices...\n")
        client = create_emulated_client()
        devices = client.get_device_tree()
        print(client.format_circuit_summary(devices))
        return

    # Delete token file if force login is requested
    if args.force_login and os.path.exists(args.token_file):
        print(f"[FORCE LOGIN] Removing existing token file: {args.token_file}")
        os.remove(args.token_file)

    client = EmporiaVueClient(username=args.username, token_file=args.token_file)

    sys.stdout.flush()
    success = client.login(interactive=True)

    if not success:
        print("\n[ERROR] Authentication failed. Exiting.")
        sys.exit(1)

    print("\n[SUCCESS] Authenticated successfully!")

    print("\nDiscovering connected Emporia Vue devices and expansion channels...")
    devices = client.get_device_tree()

    print("\n" + client.format_circuit_summary(devices))

    if args.poll:
        print("\nFetching current live usage...")
        try:
            usage = client.fetch_realtime_usage()
            print(json.dumps(usage, indent=2, default=str))
        except Exception as e:
            print(f"[WARNING] Could not fetch real-time usage: {e}")

    print("\n[COMPLETE] Session tokens saved to:", os.path.abspath(args.token_file))


if __name__ == "__main__":
    main()
