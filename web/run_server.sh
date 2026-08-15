#!/usr/bin/env bash
# ==============================================================================
# Run Rainforest Web Kiosk Service (FastAPI + Uvicorn)
# Target Host: 520c NAS (192.168.8.181) or local dev
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export WEB_HOST="${WEB_HOST:-0.0.0.0}"
export WEB_PORT="${WEB_PORT:-8000}"
export RAINFOREST_DATA_DIR="${RAINFOREST_DATA_DIR:-$SCRIPT_DIR/data}"
export PI_COLLECTOR_HOST="${PI_COLLECTOR_HOST:-192.168.8.122}"

# Create data directory if missing
mkdir -p "$RAINFOREST_DATA_DIR"

# Activate virtual environment if present
if [ -d "./venv" ]; then
    source ./venv/bin/activate
elif [ -d "$HOME/venv" ]; then
    source "$HOME/venv/bin/activate"
fi

echo "=========================================================="
echo " Starting Rainforest EMU-2 Web Kiosk Server"
echo " Host:      $WEB_HOST"
echo " Port:      $WEB_PORT"
echo " Data Dir:  $RAINFOREST_DATA_DIR"
echo " Pi Source: $PI_COLLECTOR_HOST"
echo " URL:       http://127.0.0.1:$WEB_PORT"
echo "=========================================================="

exec uvicorn web.app:app --host "$WEB_HOST" --port "$WEB_PORT" --workers 1
