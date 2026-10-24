#!/bin/sh
# Starts the Wall server and opens the wall display fullscreen (Raspberry Pi / Linux).
cd "$(dirname "$0")"
python3 server.py &
sleep 3
BROWSER=$(command -v chromium-browser || command -v chromium || command -v google-chrome)
exec "$BROWSER" --kiosk --noerrdialogs --disable-infobars \
  --autoplay-policy=no-user-gesture-required http://localhost:8765
