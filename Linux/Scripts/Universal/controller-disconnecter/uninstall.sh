#!/usr/bin/env bash
# Remove the systemd --user unit for controller-disconnecter.
set -euo pipefail

UNIT_NAME="controller-disconnecter.service"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_PATH="${UNIT_DIR}/${UNIT_NAME}"

if [[ -f "$UNIT_PATH" ]]; then
    systemctl --user disable --now "$UNIT_NAME" 2>/dev/null || true
    rm -f "$UNIT_PATH"
    systemctl --user daemon-reload
    echo "Removed $UNIT_PATH"
else
    echo "No unit file at $UNIT_PATH (nothing to do)."
fi
