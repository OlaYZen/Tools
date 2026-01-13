#!/usr/bin/env bash
set -euo pipefail

# Kill the "disconnector" process by common identifiers.
# Usage:
#   ./kill_disconnector.sh           # send SIGTERM (graceful)
#   ./kill_disconnector.sh -9        # send SIGKILL (force)
#   ./kill_disconnector.sh --force   # alias for -9

signal=""
if [[ "${1:-}" == "-9" || "${1:-}" == "--force" ]]; then
  signal="-9"
fi

patterns=(
  "controller-disconnecter"
  "main.py"
  "disconnector"
)

killed_any=false

for pat in "${patterns[@]}"; do
  if pgrep -f "$pat" >/dev/null 2>&1; then
    if [[ -n "$signal" ]]; then
      pkill -f $signal "$pat" || true
    else
      pkill -f "$pat" || true
    fi
    killed_any=true
  fi
done

# Also attempt to stop a systemd service named like "disconnector" if present
if command -v systemctl >/dev/null 2>&1; then
  if systemctl list-units --type=service --all | grep -q "disconnector"; then
    # Try user service first (no sudo), then system service
    systemctl --user stop disconnector.service >/dev/null 2>&1 || true
    sudo systemctl stop disconnector.service >/dev/null 2>&1 || true
    killed_any=true
  fi
fi

if [[ "$killed_any" == false ]]; then
  echo "No disconnector process found."
else
  if [[ -n "$signal" ]]; then
    echo "Disconnector processes force-killed (SIGKILL)."
  else
    echo "Disconnector processes signaled to terminate (SIGTERM)."
  fi
fi


