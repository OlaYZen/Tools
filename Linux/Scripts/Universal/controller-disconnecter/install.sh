#!/usr/bin/env bash
# Install controller-disconnecter as a systemd --user unit (runs after login).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_NAME="controller-disconnecter.service"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_PATH="${UNIT_DIR}/${UNIT_NAME}"

mkdir -p "$UNIT_DIR"

cat >"$UNIT_PATH" <<EOF
[Unit]
Description=DualSense idle Bluetooth disconnect (controller-disconnecter)
Documentation=file://${SCRIPT_DIR}/controller-disconnecter.sh
After=graphical-session.target

[Service]
Type=simple
ExecStart=${SCRIPT_DIR}/controller-disconnecter.sh
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT_NAME"

echo ""
echo "Installed and started: $UNIT_PATH"
echo "  Status:  systemctl --user status $UNIT_NAME"
echo "  Logs:    journalctl --user -u $UNIT_NAME -f"
echo "  Stop:    systemctl --user stop $UNIT_NAME"
echo "  Disable: systemctl --user disable $UNIT_NAME"
echo ""
echo "This unit runs when your user session starts (login). To start the user"
echo "manager at boot before the first login (uncommon), run once:"
echo "  loginctl enable-linger \"$USER\""
echo ""
