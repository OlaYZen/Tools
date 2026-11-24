# FH6 Dash

A simple FastAPI app that listens for **Forza Horizon 6 "Data Out"** UDP
telemetry, logs every packet, and shows it live on a web dashboard.

## How it works

FH6 streams a fixed **324-byte** UDP packet at the game's frame rate (one-way).
`forza.py` decodes the packet into named fields, `main.py` runs the UDP listener
+ FastAPI web server, and `dashboard.html` renders it live over a WebSocket.
(The dashboard file is re-read on every request, so editing it just needs a
browser refresh — no server restart.)

## Dashboard features

- **Shift assistant** — learns your engine's wheel-torque curve and each gear's
  ratio (sampled only at full throttle going straight, like you asked), then
  computes the optimal **upshift RPM** as the point where the next gear's wheel
  torque overtakes the current gear. Shift-light LED strip + live power/torque
  curve with the shift point marked. Do a clean full-throttle pull to calibrate.
- **Trail-braking graph** — throttle (green) and brake (red) areas with the
  steering trace overlaid for the last ~12 s, so you can see the brake bleeding
  off as you add steering/throttle through a corner.
- **Car identity** — the packet only sends a numeric `CarOrdinal` (plus class,
  PI, drivetrain, cylinders), not a name. The dash shows those specs and lets you
  **name each car once**; the name is saved to `cars.json` and shown automatically
  every time you're in that car again.
- **G-force meter** with a fading trail, **suspension** travel per corner, and
  **per-corner tire temp + slip** (slip ratio = traction/lock, slip angle =
  cornering, combined > 1 → losing grip).
- Speed / gear / power / torque / boost readouts + RPM bar; raw field table.

> **Tire temps:** FH6 Data Out transmits **one temperature per tire**. The
> in-game *Heat* screen's inner/middle/outer split is computed by the physics
> engine and is **not** part of the UDP stream, so it can't be shown here.
> The per-corner slip values are the closest actionable substitute.

## Setup

```bash
./start.sh          # creates the venv, installs deps, starts the app
./start.sh --sim    # same, plus the test simulator (no game needed)
```

Or manually:

```bash
pip install -r requirements.txt
python main.py
```

- **UDP telemetry listener:** `0.0.0.0:9999`
- **Web dashboard:** http://127.0.0.1:8000
- **Packet log:** `telemetry.log` (one JSON object per line, rotating at 25 MB)

## Configure Forza Horizon 6

In game: **SETTINGS → HUD AND GAMEPLAY**

| Setting           | Value                                            |
| ----------------- | ------------------------------------------------ |
| Data Out          | `On`                                             |
| Data Out IP       | `127.0.0.1` (same PC) or this machine's LAN IP   |
| Data Out IP Port  | `9999`                                           |

> The game uses ports **5200–5300** for its own socket, so don't use those.
> Data is only sent **while actively driving** — not in menus, replays, or pauses.

Override host/port/log path with env vars: `FH6_HOST`, `FH6_PORT`, `FH6_LOG`.

## Test without the game

```bash
python sim.py      # streams fake telemetry to 127.0.0.1:9999
```

Open the dashboard and you'll see the gauges move.

## Endpoints

| Route          | Description                                  |
| -------------- | -------------------------------------------- |
| `GET /`        | Live dashboard                               |
| `GET /api/latest` | Latest decoded frame as JSON              |
| `GET /api/fields` | Ordered list of all telemetry field names |
| `WS  /ws`      | Live frame stream (~30 Hz)                   |

## Packet reference

Format follows the official FH6 *Data Out* spec. It matches Forza Motorsport's
"Dash" format **plus** three FH6-only fields inserted after `NumCylinders`:
`CarGroup`, `SmashableVelDiff`, `SmashableMass`. It has **no** `TireWear` /
`TrackOrdinal` fields.
