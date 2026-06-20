#!/bin/bash
# Re-generate the kiosk dashboard preview, then open the preview image.

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "Generating kiosk dashboard preview screenshot..."
./venv/bin/python3 render_local_plot.py --screenshot --close

echo "Opening dashboard previews..."
if [ -f "1_slide_full.jpeg" ]; then
    open 1_slide_full.jpeg
    open 2_slide_full.jpeg
    open 3_slide_full.jpeg
else
    open 1_slide.jpeg
    open 2_slide.jpeg
    open 3_slide.jpeg
fi

echo "Done!"
