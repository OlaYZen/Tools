#!/usr/bin/env bash
# Serve PadLab on http://localhost:8737 (WebHID needs a secure context; localhost counts).
cd "$(dirname "$0")"
PORT="${PORT:-8737}"
URL="http://localhost:${PORT}"
echo "PadLab running at ${URL}  (Ctrl+C to stop)"
( sleep 0.6; command -v xdg-open >/dev/null && xdg-open "$URL" >/dev/null 2>&1 ) &
exec python3 server.py "$PORT"
