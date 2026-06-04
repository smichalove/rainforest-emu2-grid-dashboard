#!/bin/bash
# redeploy.sh
# Automates running unit tests, copying code, clearing cache files, and restarting the dashboard on the Pi.

set -e

echo "=== Running local unit tests ==="
pytest tests/

echo "=== Copying dashboard.py, dashboard_modules, README.md, run_dashboard_system.sh, backup_to_jetson.sh, and logos to the Pi ==="
ssh steven@rainforestpi "mkdir -p ~/rainforest-emu2-grid-dashboard/scratch"
scp scratch/combined_logos_small.png steven@rainforestpi:~/rainforest-emu2-grid-dashboard/scratch/
scp -r dashboard_modules steven@rainforestpi:~/rainforest-emu2-grid-dashboard/
scp dashboard.py snr_analysis.py *prompt.txt README.md run_dashboard_system.sh backup_to_jetson.sh .env steven@rainforestpi:~/rainforest-emu2-grid-dashboard/
ssh steven@rainforestpi "chmod +x ~/rainforest-emu2-grid-dashboard/backup_to_jetson.sh"

echo "=== Copying AI staging code and prompt to the Jetson Orin Nano ==="
scp stage_local_summary.py stage_batch_summary.py snr_analysis.py gemma_hybrid_prompt.txt gemma_dft_prompt.txt steven@192.168.8.68:~/rainforest-emu2-grid-dashboard/
ssh steven@192.168.8.68 "sudo cp ~/rainforest-emu2-grid-dashboard/stage_local_summary.py /home/grid_backup/ && sudo cp ~/rainforest-emu2-grid-dashboard/snr_analysis.py /home/grid_backup/ && sudo cp ~/rainforest-emu2-grid-dashboard/gemma_hybrid_prompt.txt /home/grid_backup/ && sudo cp ~/rainforest-emu2-grid-dashboard/gemma_dft_prompt.txt /home/grid_backup/ && sudo chown grid_backup:grid_backup /home/grid_backup/stage_local_summary.py /home/grid_backup/snr_analysis.py /home/grid_backup/gemma_hybrid_prompt.txt /home/grid_backup/gemma_dft_prompt.txt && sudo mkdir -p /etc/systemd/system/jetson-grid-edge.service.d && echo -e '[Service]\nEnvironment=\"JETSON_BACKUP_PATH=/home/steven/rainforest-emu2-grid-dashboard/backups\"' | sudo tee /etc/systemd/system/jetson-grid-edge.service.d/override.conf > /dev/null && sudo systemctl daemon-reload && sudo systemctl restart jetson-grid-edge"



echo "=== Restarting the dashboard process on the Pi ==="
ssh steven@rainforestpi "killall python || true"
ssh steven@rainforestpi "nohup ~/rainforest-emu2-grid-dashboard/run_dashboard_system.sh < /dev/null > /dev/null 2>&1 &"

echo "=== Redeployment complete! ==="
