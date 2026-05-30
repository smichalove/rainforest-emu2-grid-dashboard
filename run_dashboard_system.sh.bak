#!/bin/bash
# Navigate to project directory
cd /home/steven/rainforest-emu2-grid-dashboard

# Start the background batch staging worker
./venv/bin/python -u stage_batch_summary.py > stage_batch.log 2>&1 &

# Start the dashboard GUI in decoupled mode
LLM_MODE=decoupled DISPLAY=:0 ./venv/bin/python -u dashboard.py > dashboard_gui.log 2>&1
