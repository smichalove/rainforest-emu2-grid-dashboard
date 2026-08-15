#!/usr/bin/env bash
# ==============================================================================
# Launch Fullscreen Chromium Kiosk on Raspberry Pi
# Target URL: http://192.168.8.181:8000 (520c NAS)
# ==============================================================================

KIOSK_URL="${1:-http://192.168.8.181:8000}"

echo "=========================================================="
echo " Launching Chromium Kiosk on Raspberry Pi"
echo " Target URL: $KIOSK_URL"
echo "=========================================================="

# Disable screen blanking & power saving
xset s noblank 2>/dev/null || true
xset s off 2>/dev/null || true
xset -dpms 2>/dev/null || true

# Hide mouse cursor when inactive if unclutter is installed
which unclutter >/dev/null 2>&1 && unclutter -idle 0.5 -root &

# Launch Chromium in dedicated kiosk profile
exec chromium-browser \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-translate \
    --disable-features=TranslateUI \
    --disable-session-crashed-bubble \
    --check-for-update-interval=31536000 \
    --touch-events=enabled \
    --overscroll-history-navigation=0 \
    --user-data-dir="/tmp/chromium_kiosk_profile" \
    "$KIOSK_URL"
