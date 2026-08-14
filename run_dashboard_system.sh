#!/bin/bash
# Navigate to project directory
cd /home/steven/rainforest-emu2-grid-dashboard

# Start the background stager process
# ./venv/bin/python -u stage_batch_summary.py > stage_batch.log 2>&1 &

# Start the dashboard GUI natively in decoupled/cloud/edge mode
# Auto-detect connected HDMI outputs to force display mirroring on startup
HDMI_DEVS=$(DISPLAY=:0 xrandr | grep " connected" | awk '{print $1}')
HDMI_PRIMARY=$(echo "$HDMI_DEVS" | grep -E '^HDMI(-A)?-?[01]' | head -n 1)
HDMI_SECONDARY=$(echo "$HDMI_DEVS" | grep -E '^HDMI(-A)?-?[12]' | grep -v "$HDMI_PRIMARY" | head -n 1)

# Fallback if names are different
if [ -z "$HDMI_PRIMARY" ] || [ -z "$HDMI_SECONDARY" ]; then
    HDMI_PRIMARY=$(echo "$HDMI_DEVS" | sed -n '1p')
    HDMI_SECONDARY=$(echo "$HDMI_DEVS" | sed -n '2p')
fi

if [ -n "$HDMI_PRIMARY" ] && [ -n "$HDMI_SECONDARY" ]; then
    DISPLAY=:0 xrandr --output "$HDMI_SECONDARY" --mode 1024x768 --same-as "$HDMI_PRIMARY" || true
elif [ -n "$HDMI_PRIMARY" ]; then
    DISPLAY=:0 xrandr --output "$HDMI_PRIMARY" --mode 1024x768 || true
fi
PYTHON_BIN=$(which python3)
if [ -f "./venv/bin/python" ]; then
    PYTHON_BIN="./venv/bin/python"
fi

DISPLAY=:0 $PYTHON_BIN -u dashboard.py > dashboard_gui.log 2>&1
