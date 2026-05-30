#!/bin/bash
# Navigate to project directory
cd /home/steven/rainforest-emu2-grid-dashboard

# Start the dashboard GUI natively in decoupled/cloud/edge mode
DISPLAY=:0 ./venv/bin/python -u dashboard.py > dashboard_gui.log 2>&1

