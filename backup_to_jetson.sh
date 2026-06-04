#!/bin/bash
# backup_to_jetson.sh
# Incremental telemetry backup script from Raspberry Pi Kiosk to Jetson Orin Nano SSD.

set -u

# Read environment variables if available, with fallbacks
JETSON_HOST="${JETSON_HOST:-192.168.8.68}"
JETSON_USER="${JETSON_USER:-grid_backup}"
if [ -z "${JETSON_BACKUP_PATH:-}" ]; then
    BACKUP_DIR="/home/grid_backup/backups"
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

# 2. Run incremental rsync backup of CSV history and JSON cache files
echo "[INFO] Syncing data files to Jetson Orin Nano SSD..." >> "$LOG_FILE"
if rsync -avz --include="*.csv" --include="*.json" --exclude="*" "${LOCAL_DIR}/" "${JETSON_USER}@${JETSON_HOST}:${BACKUP_DIR}/" >> "$LOG_FILE" 2>&1; then
    echo "[SUCCESS] Telemetry backup complete: $(date)" >> "$LOG_FILE"
else
    echo "[ERROR] Rsync transfer failed. Check SSH permissions." >> "$LOG_FILE"
    exit 1
fi
