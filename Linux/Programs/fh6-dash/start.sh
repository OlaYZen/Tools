#!/usr/bin/env bash
#
# Start FH6 Dash. Creates the virtualenv and installs dependencies on first run,
# then launches the telemetry listener + web dashboard.
#
# Usage:
#   ./start.sh            # normal start
#   ./start.sh --sim      # also launch the test simulator (no game needed)
#
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"
PY="$VENV/bin/python"

# 1. Create the venv if it doesn't exist yet.
if [[ ! -x "$PY" ]]; then
  echo ">> Creating virtualenv in $VENV ..."
  python3 -m venv "$VENV"
fi

# 2. Install / update dependencies (only when requirements.txt is newer than the stamp).
STAMP="$VENV/.deps-installed"
if [[ ! -f "$STAMP" || requirements.txt -nt "$STAMP" ]]; then
  echo ">> Installing dependencies ..."
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -r requirements.txt
  touch "$STAMP"
fi

# 3. Optionally start the test simulator in the background.
if [[ "${1:-}" == "--sim" ]]; then
  echo ">> Starting test simulator (fake telemetry) ..."
  "$PY" sim.py &
  SIM_PID=$!
  # Stop the simulator when this script exits.
  trap 'kill "$SIM_PID" 2>/dev/null || true' EXIT
fi

# 4. Launch the app.
echo ">> Starting FH6 Dash — dashboard at http://127.0.0.1:8000  (Ctrl-C to stop)"
exec "$PY" main.py
