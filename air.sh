#!/usr/bin/env bash
# Air Quality Quick Launcher
# Executes the combined indoor/outdoor air quality comparison dashboard

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "${SCRIPT_DIR}/read_combined_air.py" "$@"
