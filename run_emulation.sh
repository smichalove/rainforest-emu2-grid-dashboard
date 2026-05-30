#!/bin/bash
# run_emulation.sh
# Syncs latest data from the Pi and executes the Vertex AI batch submission emulation.

set -e

PI_IP="192.168.8.213"
PI_USER="steven"
LOCAL_REPO="/Users/treven/Documents/rainforest-emu2-grid-dashboard"

echo "=== 1. Syncing latest history logs from Pi ($PI_IP) ==="
scp "$PI_USER@$PI_IP:~/grid_history.csv" "$LOCAL_REPO/"
scp "$PI_USER@$PI_IP:~/solaredge_history.csv" "$LOCAL_REPO/"
scp "$PI_USER@$PI_IP:~/solaredge_battery_history.csv" "$LOCAL_REPO/"
scp "$PI_USER@$PI_IP:~/rainforest-emu2-grid-dashboard/chilicon_history.csv" "$LOCAL_REPO/"

echo -e "\n=== 2. Setting up virtual environment on Mac ==="
if [ ! -d "$LOCAL_REPO/venv" ]; then
    echo "Creating virtual environment venv..."
    python3 -m venv "$LOCAL_REPO/venv"
    source "$LOCAL_REPO/venv/bin/activate"
    echo "Installing google-cloud-storage and google-genai..."
    pip install --upgrade pip
    pip install google-cloud-storage google-genai
else
    source "$LOCAL_REPO/venv/bin/activate"
fi

echo -e "\n=== 3. Launching Gemini Batch Emulation Script ==="
python3 "$LOCAL_REPO/emulate_power_meter_batch.py"
