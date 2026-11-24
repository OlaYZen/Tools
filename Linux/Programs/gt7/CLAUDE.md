# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

The system Python is externally managed and has no pytest. Use the venv for
everything:

```bash
./.venv/bin/python -m pytest tests -q          # all tests (no console needed)
./.venv/bin/python -m pytest tests/test_stint.py::test_position_change_is_tracked -q
./.venv/bin/python -m gt7 serve --port 8000    # web pit wall
./.venv/bin/python -m gt7 dash                 # terminal dashboard
node --check gt7/web/static/dash.js            # only JS syntax check available
```

Tests run entirely off `tests/fixtures/format_a.bin`, a recorded capture. They
need no PS5 and no network.

The default PS5 address is `192.168.1.67` (`DEFAULT_HOST` in `cli.py`);
override with `--host`.

## Only one telemetry client can run at a time

UDP `:33740` is bound exclusively — `SO_REUSEADDR` was deliberately removed
(see the comment in `client.start()`), because on UDP it lets a second process
silently take a share of the packets, leaving both clients showing frozen data
and neither reporting a fault. A second client now fails with `PortBusyError`.

This bites constantly during development: if a dashboard is already running,
`record`, `dump`, `probe` and a second `serve` will all refuse to start. Check
with `ss -lunp | grep 33740` before diagnosing anything else. Web tests call
`build_app()`, which binds the port on startup — the lifespan tolerates
`PortBusyError` so the server still boots and reports the fault through
`/api/link`.

## Architecture

Telemetry flows one way through four layers, each of which can be used alone:

```
crypto.py    Salsa20, format registry, magic check
   v
packet.py    one struct.unpack of the whole body -> Telemetry
   v
client.py    threaded UDP receiver, heartbeat, newest-frame slot
   v
derived.py / stint.py     values GT7 does not send
   v
web/server.py (FastAPI)  |  dashboard.py (rich TUI)
```

`GT7Client` keeps only the **newest** frame, never a queue: telemetry is a
current value, not a log. Both front ends sample that slot rather than draining
it. `on_frame` fires at packet rate (60 Hz) and is where `GripEstimator` and
`StintTracker` are fed — feeding them from the render loop would drop two
thirds of the samples.

### Protocol facts that will mislead you

Read `docs/protocol.md` before touching `crypto.py` or `packet.py`. The traps:

- **The IV XOR constant differs per format**: `0xDEADBEAF` for A (296 B),
  `0xDEADBEEF` for B (316 B). One letter apart, and the usual reason a decrypt
  fails. `decrypt()` picks it from the packet *length*, not from what was
  requested.
- **The console serves one telemetry session for the whole network**, and any
  heartbeat renews it — including one asking for a different format. A request
  is not a guarantee, which is why `GT7Client` exposes `active_format` and
  `format_mismatch` and the UIs display what actually arrived.
- **The `CAR_ON_TRACK` flag reads false during a race at 250 km/h.** Never gate
  motion logic on it; use `Telemetry.is_moving`. This silently disabled the grip
  estimator once.
- **Steering (`0x128`) is format B only**, and its raw sign is *positive for
  left*. `parse()` negates it so `wheel_rotation` is positive-for-right; do not
  "fix" that flip or the meter mirrors again. Scale is still unresolved (it
  saturates at exactly pi), so derive from sign and change, never degrees.
- **The console streams at 60 Hz while the game is paused**, serving a frozen
  snapshot. Any analysis tool must check a control channel (rpm, speed) is
  actually moving before concluding a field is dead.
- **Format A is fully mapped** — `gt7 survey <capture> --unknown-only` returns
  nothing. The 344-byte `~` format is not decryptable; two attacks in `tools/`
  failed (`docs/weather.md` records the search space).

`track.py` traces the circuit from the car's world position at `0x04`, never by
dead reckoning from speed and yaw — position is exact (path integration matches
reported speed to 0.1%), and dead reckoning would drift worst in long corners.
The trace goes out as a delta with a per-connection cursor and a `generation`
counter that means "discard", because a lap is thousands of points.

Lap 1 is an **out-lap** everywhere (`delta.is_out_lap`): a race starts on the
grid ahead of the line, so it is short and would become the fastest lap and
therefore the delta reference. `track.py` will not publish it as the circuit
either. `stint.py` already excludes it as "the lap in progress at attach" — do
not add a second rule there or lap 2 gets dropped too.

`delta.py` answers "where did he lose time" by matching position, since GT7
sends no sectors and no distance-round-lap. Two invariants to preserve: the lap
clock is `packet_id` (it survives dropped datagrams) with ms-per-tick measured
from GT7's reported lap time rather than assumed 60 Hz, and reference matching
only ever walks *forward* — an unrestricted nearest-point search jumps across a
hairpin and invents huge deltas. Report `LapComparison.total_ms`, never the sum
of `bucket()`'s output, which carries rounding error.

`library.py` saves completed laps and recognises them again by spatial lookup
against a grid hash (cell size == match tolerance). Two rules there exist
because the naive version was wrong: only shapes passing `is_loop` are saved
(closure *and* enclosed area — an out-and-back passes closure while enclosing
nothing), and a stored outline is replaced only by a lap that scores better on
accumulated occupancy, since always taking the newest lap let one excursion
overwrite a good map permanently. Score both laps *after* folding the new one
in, or the incumbent is judged against a record containing only itself. Matching is sticky on
purpose — three consecutive wins to adopt, twice that to drop — because a map
that flickered across a pit lane would be worse than none. Note the split in
`on_frame`: keeping a finished lap is an integer comparison and runs every
frame, while the spatial scan is throttled to 2 Hz. They were once throttled
together, which let a completed lap be missed when a tick fell the wrong side
of the boundary.

The published outline is **one lap between two lap-counter boundaries**, not a
growing trace: `closed` means "measured line to line", never "geometrically
back near the start". The lap in progress at attach is discarded for the same
reason `stint.py` discards it — it starts somewhere arbitrary. Map orientation
(rotate/flip) is client-side only; the fit is recomputed from the oriented
bounding box, so never assume the raw bbox maps to screen axes.

`pits.py` infers a pit stop from the limiter signature (speed held far tighter
than a human can, inside a plausible band) plus being off the recognised racing
line. **No stop may open on the out-lap** (`delta.is_out_lap`): nearly every GT7
race is a rolling start, where the game holds the whole field at one speed until
the line — a genuine limiter, so no speed test can refuse it, and it opened a
fictional stop on the grid almost every race and backfilled the first 250 m of
the racing line into the library as pit road. The cost is a stop that really
began on lap 1. Position corroborates a stop and must never gate one, on **entry or exit** — pit lanes range from
the far side of a circuit to a wall's width from the racing line, so no distance
separates them, and two attempts at a veto threshold (25 m, then 8 m) each
refused real stops. `ON_LINE_METRES` now only decides what `confidence` reports.
The accepted cost is that a perfectly steady speed on the racing line reads as a
stop; a real caution lap is ruled out by the speed-spread test instead, because
a human cannot hold a speed like a limiter. There is a test pinning that limit. Exit is on speed alone for the same
reason: the outline is one lap's line, so a car racing a different line reads
as off it and stayed flagged in the pits at 148 km/h, recording racing line
into the pit lane. `library.MAX_LANE_FRACTION` is the backstop for that, since
"longest lane wins" would otherwise enshrine the corrupt one.
Three guards exist because each was a false positive first: a speed
ceiling (flat out is drag-limited and plateaus too), a travelled-distance
cross-check (a paused GT7 streams a frozen snapshot whose speed is *perfectly*
steady, and `Flags.PAUSED` reads False while paused), and exit judged on
returning to racing rather than on the signature ending (the car is stationary
mid-stop). Laps containing a stop are kept out of the track library. The lane itself is
recorded and drawn as a thin dashed branch; its entry is backfilled from before
detection, bounded by *distance* rather than frames or time — both of those
scale with how fast frames arrive, and a caller pushing them faster than real
time put 2400 racing-line points into one pit road.

### What is inferred rather than received

GT7 sends no weather, no opponent data, and no per-lap anything. Three docs
record the evidence and should be updated alongside any claim about them:
`docs/weather.md`, `docs/opponents.md`, `docs/protocol.md`.

`stint.py` accumulates everything per-lap frame by frame between lap
boundaries. Two rules in it exist because real data broke them first:

- The lap already in progress when the tracker attaches is **discarded**. It
  once logged 1.88 L against the next lap's 6.98 L, halving the measured burn.
- Lock-ups and wheelspin are counted as **events** with a minimum frame run, not
  per frame, or one lap of continuous slip reports as sixty lock-ups.

`callouts()` turns all of it into radio phrases ranked critical/warn/info. That
list is the point of the web UI, so new derived values should generally end up
as a callout rather than another number on screen.

### Web layer

The `track` message carries the outline *and* the pit lane. Suppressing it
when there are no new outline points therefore withholds the lane too — a page
connected before a stop never saw one. Any send condition there has to account
for every part of the payload, not just the points.

Five streams share one WebSocket at different rates because they change at
different rates: `frame` 60 Hz, `stint`, `track` and `analysis` 2 Hz, `link` 4 Hz. Frames
only go out when `packet_id` advances.

The track canvas is absolutely positioned inside a `position: relative` box so
it cannot feed its own size back into the grid row and ratchet taller. The path
lives on an offscreen canvas, redrawn only when points arrive or the box
resizes.

`dash.js` stores live frames and paints in `requestAnimationFrame`; it paints
stint messages on arrival. Segment bars only touch cells whose state changed.
Static files are served from disk, so a reloaded page can be newer than the
running server — payload sections are guarded (`race = race || {}`) for that
reason.

The UI is a race engineer's screen, not a driver's: trends and projections over
instantaneous values, and no repeating flash anywhere. `--best` (purple) is
reserved for a fastest lap and nothing else.

## Conventions

- Comments explain *why*, especially where a value was measured off a live
  console rather than reasoned about. Several carry the observation that forced
  the design; keep that when editing.
- Anything asserted about the protocol should be backed by evidence in `docs/`
  or a test. Where a claim could not be verified, the limit is stated explicitly
  (for example whether `0x84` is live position or grid position) — preserve
  those hedges rather than tidying them into confident statements.
- Captures in `captures/` are raw ciphertext on purpose, so they stay useful for
  formats that cannot be decrypted yet.
