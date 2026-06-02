#!/bin/bash
# Re-generate the kiosk dashboard preview, then open the preview image.

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "Generating kiosk dashboard preview screenshot..."
python3 render_local_plot.py --screenshot --close

echo "Opening dashboard preview..."
open dashboard_preview.jpeg

echo "Done!"
