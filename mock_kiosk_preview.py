#!/usr/bin/env python3
"""Standalone local preview runner for GridDashboard on macOS.

Launches the Tkinter dashboard in windowed mode (1024x768) with real-time
Emporia circuit telemetry (simulated or live via cached tokens).
"""

import argparse
import os
import sys
import time

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
# Force macOS proxy resolution bypass and AWS metadata disabling
import urllib.request
urllib.request.getproxies = lambda: {}
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

# Enable windowed mode for Mac preview
os.environ["KIOSK_WINDOWED"] = "1"


def parse_args():
    parser = argparse.ArgumentParser(description="Run local macOS GridDashboard preview.")
    parser.add_argument(
        "--live-emporia",
        action="store_true",
        help="Attempt live Emporia API query using cached tokens in Auth/emporia_tokens.json."
    )
    parser.add_argument(
        "--slide",
        type=int,
        choices=[1, 2, 3],
        default=3,
        help="Initial slide to display (default: 3 for Circuit & Device Breakdown)."
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.live_emporia:
        os.environ["EMPORIA_SIMULATE"] = "1"
        mode_str = "SIMULATED TELEMETRY (16 panel circuits + 13 smart plugs + 200A Mains + Balance)"
    else:
        mode_str = "LIVE EMPORIA (using Auth/emporia_tokens.json)"

    print("=" * 65)
    print("      EMU-2 GRID MONITOR — LOCAL MAC PREVIEW RUNNER")
    print("=" * 65)
    print(f"Mode:          {mode_str}")
    print(f"Initial Slide: Slide {args.slide}")
    print("Window Size:   1024 x 768 (Non-fullscreen)")
    print("Controls:      Press <Escape> or close window to exit.")
    print("=" * 65)

    from render_local_plot import OfflineViewer
    sys.argv = ["render_local_plot.py", f"--slide={args.slide}"]
    if args.live_emporia:
        sys.argv.append("--live-emporia")
    
    viewer = OfflineViewer()
    viewer.mainloop()


if __name__ == "__main__":
    main()
