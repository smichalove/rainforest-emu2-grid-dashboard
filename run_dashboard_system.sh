#!/bin/bash
# Navigate to project directory
cd /home/steven/rainforest-emu2-grid-dashboard

# Start the background stager process
# ./venv/bin/python -u stage_batch_summary.py > stage_batch.log 2>&1 &

# Start the dashboard GUI natively in decoupled/cloud/edge mode
# Force HDMI displays to mirror on startup
DISPLAY=:0 xrandr --output HDMI-2 --mode 1024x768 --same-as HDMI-1 || true

DISPLAY=:0 ./venv/bin/python -u dashboard.py > dashboard_gui.log 2>&1

