#!/usr/bin/env bash
# Emporia Vue Telemetry & Circuit Enumerator Quick Launcher
# Activates local venv, sets AWS/Python environment optimizations, and runs read_emporia_vue.py

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# Activate virtual environment if present
if [ -d "${SCRIPT_DIR}/venv" ]; then
    source "${SCRIPT_DIR}/venv/bin/activate"
fi

# Environment optimizations to prevent botocore network metadata stalls and buffer lags
export AWS_EC2_METADATA_DISABLED=true
export AWS_DEFAULT_REGION=us-east-1
export PYTHONUNBUFFERED=1
export NO_PROXY="*"
export no_proxy="*"


exec python3 "${SCRIPT_DIR}/read_emporia_vue.py" "$@"
