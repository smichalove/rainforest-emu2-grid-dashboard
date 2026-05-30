#!/bin/bash
# Sync dashboard telemetry and cache files from Raspberry Pi to the Mac
echo "Syncing data from Raspberry Pi..."
scp steven@Rainforestpi:~/rainforest-emu2-grid-dashboard/grid_history.csv /Users/treven/Documents/rainforest-emu2-grid-dashboard/
scp steven@Rainforestpi:~/rainforest-emu2-grid-dashboard/solaredge_history.csv /Users/treven/Documents/rainforest-emu2-grid-dashboard/
scp steven@Rainforestpi:~/rainforest-emu2-grid-dashboard/solaredge_battery_history.csv /Users/treven/Documents/rainforest-emu2-grid-dashboard/
scp steven@Rainforestpi:~/rainforest-emu2-grid-dashboard/chilicon_history.csv /Users/treven/Documents/rainforest-emu2-grid-dashboard/
scp steven@Rainforestpi:~/rainforest-emu2-grid-dashboard/gemini_summary.json /Users/treven/Documents/rainforest-emu2-grid-dashboard/
scp steven@Rainforestpi:~/rainforest-emu2-grid-dashboard/merged_summary.json /Users/treven/Documents/rainforest-emu2-grid-dashboard/ || true


echo "Launching local dashboard renderer..."
# Change to the repository directory so that relative paths resolve correctly
cd /Users/treven/Documents/rainforest-emu2-grid-dashboard/

# Run the local renderer script
python3 render_local_plot.py
