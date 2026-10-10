#!/bin/bash
# run_mock.sh - Launches local macOS GridDashboard mock preview inside venv

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=================================================="
echo "   EMU-2 GRID MONITOR — LOCAL PREVIEW RUNNER"
echo "=================================================="
echo "Starting preview inside Python virtualenv..."

# Launch using project venv and established local renderer
exec ./venv/bin/python3 render_local_plot.py --slide=3 "$@"
