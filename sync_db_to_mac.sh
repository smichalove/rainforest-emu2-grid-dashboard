#!/bin/bash
# sync_db_to_mac.sh
# Syncs active databases and telemetry logs from the Jetson edge server (default) or Raspberry Pi (fallback).

USE_PI=false
for arg in "$@"; do
    if [ "$arg" == "--pi" ]; then
        USE_PI=true
    fi
done

if [ "$USE_PI" = true ]; then
    PI_HOST="${PI_HOST:-rainforestpi}"
    PI_USER="${PI_USER:-steven}"
    echo "=== Pulling telemetry data directly from Raspberry Pi ($PI_HOST) ==="
    
    # 1. Trigger a safe SQLite hot-backup on the Pi to prevent copy corruption
    ssh "${PI_USER}@${PI_HOST}" "mkdir -p /home/steven/rainforest-emu2-grid-dashboard/sync_temp && python3 -c \"import sqlite3; conn=sqlite3.connect('/home/steven/rainforest-emu2-grid-dashboard/grid_history.db'); backup=sqlite3.connect('/home/steven/rainforest-emu2-grid-dashboard/sync_temp/grid_history_mac.db'); conn.backup(backup); conn.close(); backup.close()\""
    
    # 2. Sync the safe database snapshot to Mac
    rsync -avz --progress "${PI_USER}@${PI_HOST}:/home/steven/rainforest-emu2-grid-dashboard/sync_temp/grid_history_mac.db" ./grid_history.db
    
    # 3. Optionally sync the CSVs
    rsync -avz --progress --include="*.csv" --exclude="*" "${PI_USER}@${PI_HOST}:/home/steven/rainforest-emu2-grid-dashboard/" ./
else
    JETSON_HOST="${JETSON_HOST:-nvjetson}"
    JETSON_USER="${JETSON_USER:-steven}"
    echo "=== Pulling telemetry data from Jetson ($JETSON_HOST) ==="
    rsync -avz --progress "${JETSON_USER}@${JETSON_HOST}:/home/grid_backup/backups/grid_history.db" ./grid_history.db
    rsync -avz --progress --include="*.csv" --exclude="*" "${JETSON_USER}@${JETSON_HOST}:/home/grid_backup/backups/" ./
fi

echo "=== Sync Complete! ==="
