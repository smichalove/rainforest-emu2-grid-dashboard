#!/bin/bash
# redeploy.sh
# Automates running unit tests, copying code, clearing cache files, and restarting the dashboard on the Pi.

set -e

echo "=== Skipping local unit tests ==="
# ./venv/bin/python3 -m unittest tests/emulation/test_grpc_contract.py
# ./venv/bin/pytest tests/

echo "=== Compiling Protobuf contract locally ==="
./venv/bin/python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. protos/grid_telemetry.proto

echo "=== Copying dashboard.py, dashboard_modules, stubs, and logos to the Pi ==="
ssh steven@rainforestpi "mkdir -p ~/rainforest-emu2-grid-dashboard/scratch ~/rainforest-emu2-grid-dashboard/protos"
scp scratch/combined_logos_small.png steven@rainforestpi:~/rainforest-emu2-grid-dashboard/scratch/
scp -r dashboard_modules steven@rainforestpi:~/rainforest-emu2-grid-dashboard/
scp protos/grid_telemetry_pb2*.py steven@rainforestpi:~/rainforest-emu2-grid-dashboard/protos/
scp dashboard.py read_purple_air.py repl_client.py stage_batch_summary.py snr_analysis.py *prompt.txt README.md run_dashboard_system.sh backup_to_jetson.sh .env requirements.txt steven@rainforestpi:~/rainforest-emu2-grid-dashboard/
ssh steven@rainforestpi "chmod +x ~/rainforest-emu2-grid-dashboard/backup_to_jetson.sh"

echo "=== Copying AI staging code, stubs, and .env to the Jetson Orin Nano ==="
ssh steven@nvjetson "mkdir -p ~/rainforest-emu2-grid-dashboard/protos"
scp protos/grid_telemetry_pb2*.py steven@nvjetson:~/rainforest-emu2-grid-dashboard/protos/
scp -r dashboard_modules read_purple_air.py repl_client.py stage_local_summary.py stage_batch_summary.py snr_analysis.py *prompt.txt .env requirements.txt steven@nvjetson:~/rainforest-emu2-grid-dashboard/

ssh steven@nvjetson "
  sudo cp -r ~/rainforest-emu2-grid-dashboard/dashboard_modules /home/grid_backup/ && \
  sudo cp -r ~/rainforest-emu2-grid-dashboard/protos /home/grid_backup/ && \
  sudo cp ~/rainforest-emu2-grid-dashboard/stage_local_summary.py /home/grid_backup/ && \
  sudo cp ~/rainforest-emu2-grid-dashboard/snr_analysis.py /home/grid_backup/ && \
  sudo cp ~/rainforest-emu2-grid-dashboard/*prompt.txt /home/grid_backup/ && \
  sudo cp ~/rainforest-emu2-grid-dashboard/.env /home/grid_backup/ && \
  sudo cp ~/rainforest-emu2-grid-dashboard/requirements.txt /home/grid_backup/ && \
  sudo chown -R grid_backup:grid_backup /home/grid_backup/dashboard_modules /home/grid_backup/protos /home/grid_backup/.env /home/grid_backup/requirements.txt /home/grid_backup/stage_local_summary.py /home/grid_backup/snr_analysis.py /home/grid_backup/*prompt.txt && \
  sudo mkdir -p /etc/systemd/system/jetson-grid-edge.service.d && \
  echo -e '[Service]\nExecStart=\nExecStart=/home/grid_backup/venv/bin/python3 /home/grid_backup/stage_local_summary.py --port 5000\nEnvironment=\"JETSON_BACKUP_PATH=/home/grid_backup/backups\"' | sudo tee /etc/systemd/system/jetson-grid-edge.service.d/override.conf > /dev/null && \
  sudo systemctl daemon-reload && \
  sudo systemctl restart jetson-grid-edge
"

echo "=== Restarting the dashboard process on the Pi ==="
ssh steven@rainforestpi "pkill -f 'dashboard.py' 2>/dev/null" || true
ssh steven@rainforestpi "DISPLAY=:0 nohup ~/rainforest-emu2-grid-dashboard/run_dashboard_system.sh </dev/null >/dev/null 2>&1 &"

echo "=== Redeployment complete! ==="
