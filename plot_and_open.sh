#!/bin/bash
# Re-generate the kiosk dashboard preview, then open the preview image.

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "Generating kiosk dashboard preview screenshot..."
./venv/bin/python3 render_local_plot.py --screenshot --close

echo "Opening dashboard previews..."
if [ -f "dashboard_preview_full.jpeg" ]; then
    open dashboard_preview_full.jpeg
    open dashboard_preview_slide2_full.jpeg
    open dashboard_preview_slide3_full.jpeg
else
    open dashboard_preview.jpeg
    open dashboard_preview_slide2.jpeg
    open dashboard_preview_slide3.jpeg
fi

echo "Done!"
