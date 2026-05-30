#!/bin/bash
# redeploy.sh
# Automates running unit tests, copying code, clearing cache files, and restarting the dashboard on the Pi.

set -e

echo "=== Running local unit tests ==="
pytest tests/

echo "=== Copying dashboard.py, README.md, and run_dashboard_system.sh to the Pi ==="
scp dashboard.py README.md run_dashboard_system.sh steven@rainforestpi:~/rainforest-emu2-grid-dashboard/

echo "=== Clearing remote summary cache files on the Pi ==="
ssh steven@rainforestpi "rm -f ~/gemini_summary.json ~/rainforest-emu2-grid-dashboard/gemini_summary.json"

echo "=== Restarting the dashboard process on the Pi ==="
ssh steven@rainforestpi "killall python || true"
ssh steven@rainforestpi "nohup ~/rainforest-emu2-grid-dashboard/run_dashboard_system.sh > /dev/null 2>&1 &"

echo "=== Redeployment complete! ==="
