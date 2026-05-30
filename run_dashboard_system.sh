#!/bin/bash
# Navigate to project directory
cd /home/steven/rainforest-emu2-grid-dashboard

# Start the dashboard GUI natively pointing to local LLM inference
DISPLAY=:0 ./venv/bin/python -u dashboard.py --localllm > dashboard_gui.log 2>&1
