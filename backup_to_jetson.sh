#!/bin/bash
# backup_to_jetson.sh
# Incremental telemetry backup script from Raspberry Pi Kiosk to Jetson Orin Nano SSD.

set -u

# Read environment variables if available, with fallbacks
JETSON_HOST="${JETSON_HOST:-192.168.8.68}"
JETSON_USER="${JETSON_USER:-grid_backup}"
if [ -z "${JETSON_BACKUP_PATH:-}" ]; then
    BACKUP_DIR="."
else
    BACKUP_DIR="${JETSON_BACKUP_PATH}"
fi
LOCAL_DIR="/home/steven/rainforest-emu2-grid-dashboard"
LOG_FILE="${LOCAL_DIR}/scratch/backup_history.log"

# Create scratch directory if missing
mkdir -p "${LOCAL_DIR}/scratch"

echo "=== Telemetry Backup Started: $(date) ===" >> "$LOG_FILE"

# 1. Verify network path to Jetson edge server
if ! ping -c 1 "$JETSON_HOST" > /dev/null 2>&1; then
    echo "[ERROR] Jetson Edge Server ($JETSON_HOST) is unreachable. Aborting backup." >> "$LOG_FILE"
    exit 1
fi

# 2. Prepare sync snapshot directory
echo "[INFO] Preparing database and CSV snapshots..." >> "$LOG_FILE"
SYNC_TEMP="${LOCAL_DIR}/sync_temp"
mkdir -p "$SYNC_TEMP"

# Safely backup grid_history.db using Python's SQLite backup API
if ! python3 -c "import sqlite3; conn=sqlite3.connect('${LOCAL_DIR}/grid_history.db'); backup=sqlite3.connect('${SYNC_TEMP}/grid_history.db'); conn.backup(backup); conn.close(); backup.close()" >> "$LOG_FILE" 2>&1; then
    echo "[ERROR] SQLite database backup failed." >> "$LOG_FILE"
    exit 1
fi

# Copy current solar/battery CSVs to sync directory (ignoring missing files)
cp "${LOCAL_DIR}"/solaredge*.csv "$SYNC_TEMP/" 2>/dev/null
cp "${LOCAL_DIR}"/chilicon*.csv "$SYNC_TEMP/" 2>/dev/null

# 3. Run incremental rsync backup of the sync directory
echo "[INFO] Syncing data files to Jetson Orin Nano SSD..." >> "$LOG_FILE"
if rsync -avz --delete --exclude="analysis_history.db" "${SYNC_TEMP}/" "${JETSON_USER}@${JETSON_HOST}:${BACKUP_DIR}/" >> "$LOG_FILE" 2>&1; then
    echo "[SUCCESS] Telemetry backup complete: $(date)" >> "$LOG_FILE"
    # Clean up local SQLite snapshot file
    rm -f "${SYNC_TEMP}/grid_history.db"
else
    echo "[ERROR] Rsync transfer failed. Check SSH permissions." >> "$LOG_FILE"
    exit 1
fi
