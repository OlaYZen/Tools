# gt7

A live telemetry dashboard for Gran Turismo 7, and the tools used to reverse
engineer its wire protocol.

## Quick start

```bash
pip install -r requirements.txt
python -m gt7 --host 192.168.1.67
```

Then open **http://localhost:8000**. The server binds `0.0.0.0` by default, so
a second screen on the same network reaches it at this machine's IP.

GT7 must be running and past the main menu. The car does not have to be moving,
but most channels only come alive on track.

## The pit wall

The screen is built for a race engineer, not the driver. The driver already has
shift lights and a speedo in the car; the engineer has a monitor, a radio, and
two hours in front of it. So the priorities invert — trends and projections over
instantaneous values, tabular density over big numbers, and nothing flashing
anywhere, because what reads as urgent for three seconds in a cockpit is hostile
across a stint.

### Radio

The panel at the top left is the point of the screen: a prioritised list of
things to tell the driver, phrased as you would say them.

```
┌ warn ─────────────────────────────────────────┐
│ Fuel for 6 laps, 11 to go. Save 1.13 a lap.   │
│ short by 5.0 laps at 2.50 L/lap               │
└───────────────────────────────────────────────┘
┌ warn ─────────────────────────────────────────┐
│ Rears are 22 over the fronts.                 │
│ Ease the traction out of slow corners.        │
│ front 76° rear 98°                            │
└───────────────────────────────────────────────┘
```

Critical first, then warnings, then information. The message is the radio call;
the small line under it is the number behind the call, for the engineer's own
eyes. A new callout highlights once and then settles — it never repeats a flash.

Callouts cover fuel (burn rate, laps in the tank, a savings target when you are
short, and box-this-lap when it is critical), tyre balance (front/rear and
left/right splits, cold tyres early in a stint), driving (lock-ups and wheelspin
counted per lap), and pace (personal best, drift off the best, consistency).

### Track map

A top-down trace of the circuit with a dot for the car, coloured by what the
driver was doing — red braking, green full throttle, pale green part throttle,
grey coasting.

**The outline is one lap, measured line to line.** GT7's lap counter marks the
start/finish line, so the map is anchored to it rather than to wherever the
dashboard happened to connect: the lap already running when you attach is
discarded (it would put the start marker in the middle of a corner), the trace
between two boundaries is published as the circuit, and each later lap replaces
it so the braking-point colouring stays current. Until a full lap exists the
live trace is shown as it builds, labelled `recording` rather than a lap number.

Geometry alone never counts as a lap — coming back near where you started is
not proof, and a counter that ticks twice in seconds cannot publish a fragment
as the circuit.

### Saved circuits

Complete a lap and the circuit is kept. Drive it again — this session or next
week — and it is recognised from where the car is, so the **whole outline is on
screen before the first corner** rather than after a full lap. Re-driving a
known circuit refreshes its racing line rather than saving a duplicate, and the
panel shows the name and how many laps it has seen. `rename` and `forget` sit
in the panel header.

**Only circuits are saved.** A lap has to come back to its start *and* enclose
ground. Both tests are needed: closure alone accepts an out-and-back, which
returns to where it began while enclosing nothing, and enclosed area alone
accepts a lap that never came home. Measured on the metric used (enclosed area
over length squared): a circle scores 0.080, a 3:1 road course 0.053, a very
thin 15:1 circuit 0.013 — against 0.0012 for a point-to-point stage and exactly
0 for a straight or an out-and-back. Anything below 0.003 is not a circuit.
Libraries saved before this test existed are cleaned out on load, and the
server prints what it dropped rather than deleting quietly.

**The map is the line you actually drive, not the last lap you drove.** Each
circuit keeps a count of how often the car has been over every patch of ground,
and the stored outline is only replaced by a lap that runs over better-trodden
ground than the one already held. Previously the newest lap always won, so one
trip through the gravel overwrote a good map and it stayed wrong.

Both laps are scored *after* the new one is counted, so neither is judged
against a record containing only itself, and a tie goes to the newer lap. That
matters in both directions: a clean map rejects an excursion outright, and a map
saved from a scrappy first lap recovers on the very next clean one — measured,
a 120 m excursion in the stored outline drops to 0 m after one good lap. Ground
visited on a single lap is forgotten once three laps have been seen, so one
mistake stops counting as evidence.

Recognition is spatial, not shape-matching: GT7 gives every circuit its own
coordinate space and reports the same world position for the same point every
session, so the question is simply which saved outline the last few hundred
metres land on. A grid hash whose cell size *is* the match tolerance (25 m)
makes that a handful of dictionary lookups rather than a scan over every stored
point.

It is deliberately sticky. A circuit that flickered in and out across a pit
lane or a shared section would be worse than no recognition at all, so a
candidate must win three consecutive checks before it is adopted and must fall
well below the adoption threshold before it is dropped. In practice that means
recognition lands about two seconds in. Length is checked too — a short layout
sharing most of its route with a longer one stays a separate circuit.

The library lives at `~/.local/share/gt7/tracks.json` (`--tracks` to move it),
is written via a temp file so an interrupted save cannot truncate it, and
survives a corrupt file or a bad row without losing the rest.

**One assumption worth naming:** that GT7 reports the same coordinates for the
same track across game restarts. It is near-certain — the position field is
deterministic within a session and each track has a fixed origin — but it has
not been verified across a console restart here. If it turned out false,
recognition would simply never match and you would get the live trace, which is
what you had before.

**Rotate and flip** to match how you picture the circuit. Rotation in 90°
steps plus a mirror gives all eight orientations, and your choice is remembered
in the browser. It is purely a view transform — no server data changes, and the
fit is recomputed from the oriented bounds so the circuit always fills the
panel whichever way round it is.

It is drawn from **the car's own world position** (`0x04`, metres), not
dead-reckoned from speed and yaw. That matters: integrating position over 15
seconds of driving gave 234.1 km/h against a reported 233.8 — a 0.1% agreement,
with no jumps. Dead reckoning would accumulate heading error and drift worst in
exactly the long corners you most want drawn correctly.

The trace is accumulated server-side and sent **as a delta** — a lap is
thousands of points, and re-sending them twice a second would dwarf the
telemetry. Each WebSocket connection carries its own cursor, and a `generation`
counter tells the client to discard its copy rather than append when the trace
restarts. A step over 200 m is a race restart or a pit teleport, not driving, so
it starts a fresh trace instead of drawing a line across the map.

Rendering keeps the path on an offscreen canvas and redraws it only when points
arrive or the box resizes; each frame just blits that and draws the dot, so the
60 Hz car position does not re-stroke thousands of segments.

### Time lost

A second map over the same circuit, coloured by where the last lap **gained or
lost time against the reference lap** — red losing, green gaining, grey where
the difference is noise. Lock-ups and wheelspin are marked on top, so "where he
lost it" and "why" sit on one picture, and the three biggest single losses are
listed underneath.

**The opening lap is skipped.** A race's lap 1 starts on the grid, ahead of the
start/finish line, so it covers less than a full circuit and posts a short
time. Left in, it wins on time, becomes the reference, and every honest lap
afterwards reads seconds slow — a 45 s grid lap made a clean 60.5 s lap report
`+15.5s`. It is treated as an out-lap: not the reference, not compared, and not
drawn, since its geometry stops at the line but starts on the grid. So a
comparison needs laps 2 and 3, and the panel says so rather than looking
broken.

GT7 sends no sector times and no distance-round-lap, so the delta is built from
position: for each point of the lap, find where the reference lap was at the
same *place* and compare how long each took to get there. Two details make it
read as driving rather than noise:

- **Time comes from `packet_id`, not the wall clock.** The counter advances once
  per simulation frame whether or not the datagram arrived, so a dropped packet
  costs a sample but never distorts the clock. The tick rate is measured per lap
  from GT7's own lap time rather than assumed to be 60 Hz.
- **Matching only walks forward.** A nearest-point search over the whole
  reference will happily jump to the other side of a hairpin, or back onto a
  straight crossed earlier, inventing large fake deltas. Progress round the lap
  stays monotonic.

Verified against a lap driven deliberately slowly over one arc: the map totals
+15100 ms against a true lap-time difference of +15100 ms, and the three worst
segments land inside the arc that was actually fumbled.

The headline figure comes from the unrounded comparison, never from summing the
thinned map — thinning preserves the time but costs a fraction of a millisecond
to rounding.

### Pit stops

GT7 has no pit flag, so this is inferred from two things a pit lane does that
nothing else on a circuit does.

**The limiter holds a speed no driver can hold.** In the lane the car sits on
one figure to within a fraction of a km/h for seconds together. A human cannot
do that, and neither can a car being driven hard.

**The pit lane is not on the racing line.** Once a circuit is recognised we
know where the line runs, so a car holding a limiter speed away from it is in
the pits rather than crawling round under caution. Without a recognised
circuit the speed signature stands alone, and the panel says so.

**Position corroborates; it never vetoes.** Some pit lanes are the far side of
a circuit, others are a wall's width from the racing line, and no single
distance separates those cases — so geometry is not allowed to overrule the
limiter. Detection fires with the lane anywhere from 2 m to 200 m off the line.
When the lane is clear of the track the panel reports `speed and position`;
when it runs alongside, it says `speed only — the lane runs beside the racing
line`, because position genuinely could not help.

This was a real bug twice over. First the *circuit-matching* tolerance (25 m,
deliberately generous so a different line still recognises the same track) was
borrowed to decide "on track or not", which vetoed every lane inside 25 m.
Tightening it to 8 m only moved the boundary — a lane hard against the track
was still refused.

The trade-off is stated rather than hidden: a car holding a speed to within a
fraction of a km/h *on* the racing line is indistinguishable from one doing it
in a lane beside the racing line, so it will read as a stop. What rules out a
genuine caution lap is that a human cannot hold a speed the way a limiter does
— the spread test catches it, not the geometry.

RPM plays no part. It is recorded, never tested — a formula car pulls 11,000
revs in the pit lane and that is not evidence of anything.

When a stop is *not* opened, `/api/stint` carries `blocked_by` and
`spread_kph` saying why — "speed varying by 4.2 km/h, more than a limiter
holds", "on the racing line at 80 km/h", "68 km/h is outside the pit band".
A missed stop should be explainable, not a mystery.

The limit itself is **learned, not hard-coded** — it varies by circuit and
series, so the detector looks for steadiness within a plausible band and then
reports the figure it found. A 74 km/h limiter is reported as 74 km/h; a 50 or
an 80 the same way.

Two details that took a false positive each to get right:

- **Flat out, speed plateaus too.** Drag-limited along a long straight the car
  holds 330 km/h as steadily as any limiter, so there is a ceiling on what
  counts as a pit speed.
- **A paused GT7 keeps streaming a frozen snapshot at 60 Hz** — perfectly
  steady speed, off the line, held indefinitely: the tidiest pit stop
  imaginable and entirely fictional. The `PAUSED` flag cannot catch it, having
  been measured False with the game plainly paused. What gives it away is that
  the car covers no ground, so the reported speed is cross-checked against the
  distance actually travelled.

Leaving is judged on racing speed alone — position cannot gate the exit any
more than it can gate the entry, since the outline is one lap's line and a car
racing a different one reads as off it. Left in, that stranded a car in pit
state at 148 km/h a minute after it left, quietly recording the racing line as
pit road. It is not judged on the limiter signature ending either — the car is stationary during the stop itself,
which would otherwise read as an instant exit. The header shows `PIT LANE 14s`
while in, then `1 stop · last 23s`, and the radio gets "In the pit lane" and
"Out of the pits after 23 seconds" with the stationary time behind it.

Nothing filters the drawn lane by distance from the track: only point spacing
along it, and how far back the entry is recovered. A lane running immediately
beside the racing line is drawn just the same.

The lane itself is drawn on both maps as a **thin dashed line** branching off
the circuit, in the same quiet grey as coasting — it is context, not a racing
line. It appears while the stop is happening rather than only once it is over,
and is saved with the circuit so it is there the next time you drive it. The
fullest traversal wins, so a stop entered late does not replace a complete one,
and the map fit is widened to cover it so a lane running outside the circuit
cannot be drawn off the edge.

The entry is recovered from before detection. The limiter has to hold for three
seconds before a stop is called, by which point the car is well down the lane,
and a pit road drawn from halfway along is worse than none. That recovery is
bounded by **distance**, not by frames or seconds: a pit entry is a few hundred
metres and a lap is not.

A lap containing a stop is **not** fed to the track library: the pit lane is not
the racing line, and letting it in would teach the map a road the car only uses
when it stops.

### Race

Your place, the field size, where you started, net places gained or lost, and a
log of every change with the lap it happened on. Position changes become radio
callouts — "Up to P11", "Dropped to P14, watch your mirrors".

**There are no gaps to other cars, and there cannot be.** GT7 transmits
telemetry for your car only. The counting argument settles it without needing
to decrypt anything: the largest unexplained space anywhere in the protocol is
48 bytes, while the most frugal possible encoding of a 20-car grid — a place and
a gap per car — needs 114. A scan of the console found no second channel either:
one open TCP port (9295, Remote Play), no unprompted UDP on 104 ports watched
through a race, and no port but 33739 answering a heartbeat. Full evidence in
[`docs/opponents.md`](docs/opponents.md).

The panel says so on screen, so nobody hunts for a readout that cannot exist.

### Steering

Steering lives at `0x128` and exists **only in format B**, so run
`python -m gt7 --format B serve` to get it. On format A the column reads `—`
and the table says `steer needs format B` rather than leaving you guessing.

The live meter in the bottom strip reads from the centre out, because that is
what the input is — a signed deflection from straight, not a level.

Per lap, the table counts **steering corrections**: turning points at the
wheel, with hysteresis so noise around a steady angle is not mistaken for a
driver sawing. That count is judged against the driver's own median rather than
a fixed number, because a lap of the Nordschleife has far more corners than a
lap of a short circuit:

```
[info] Busier hands than usual. Try to settle the car on one steering input.
       120 corrections a minute against your usual 10
```

**GT7 signs steering backwards.** The raw field goes positive when the driver
turns *left*, so a meter fed the raw value mirrors: left deflects right. The
parser flips it once, so `wheel_rotation` is positive = right everywhere
downstream, with `raw_wheel_rotation` kept for protocol work.

Everything here depends on the *sign* and *size of changes* at the wheel, never
on an absolute angle — `0x128` saturates at exactly pi and the physical lock it
represents is unresolved. See [`docs/protocol.md`](docs/protocol.md).

### Stint table

Every completed lap, newest first, with lap time, delta to best, fuel used, top
speed, lock-ups, wheelspin, steering corrections and full-throttle percentage. The fastest lap is
marked in the timing-screen purple, which is reserved for that and nothing else.

### Fuel and tyres

Fuel shows tank, measured burn per lap, laps remaining and laps to go, then
states plainly whether you make the finish and by how much. Tyres show each
corner's stint-long temperature trend as a sparkline, plus the front/rear and
left/right splits.

### Derived, not received

Most of this is not in the telemetry. GT7 sends a lap counter and a completed
lap time — no sector times, no distance round the lap, no fuel-per-lap, no
weather. Everything per-lap here is accumulated frame by frame between lap
boundaries, in `gt7/stint.py`:

- **fuel burn** — tank level differenced across lap boundaries, refuelling
  detected and discarded rather than averaged in as a negative
- **lock-ups and wheelspin** — slip ratio crossed with pedal position, counted
  as *events* with a four-frame minimum, so one lap of continuous slip is one
  event and not sixty
- **current lap elapsed** — wall clock since the boundary, since GT7 does not
  send it
- **grip** — inferred from acceleration; GT7 has no weather channel at all
  (see [`docs/weather.md`](docs/weather.md))
- **steering corrections** — turning points counted with hysteresis, then
  normalised per minute and compared to the driver's own median
- **places gained** — differenced against the position first seen, and only
  after a new value holds for 12 frames, so flicker is never called as an
  overtake

### HTTP API

| Route | |
|---|---|
| `GET /` | the pit wall |
| `GET /api/link` | connection health; always answers, even with no car on track |
| `GET /api/telemetry` | most recent frame, or `503` if the console has sent nothing |
| `GET /api/stint` | lap history, fuel projection, race position and the current callouts |
| `GET /api/track` | the outline to draw; `?since=<cursor>` fetches only new points |
| `GET /api/analysis` | time lost against the reference lap, with lock-up positions |
| `GET /api/tracks` | every saved circuit |
| `POST /api/tracks/{id}/name` | rename a saved circuit |
| `DELETE /api/tracks/{id}` | forget a saved circuit |
| `GET /api/docs` | generated OpenAPI docs |
| `WS /ws?hz=60` | live stream: `frame` at 60 Hz, `stint`, `track` and `analysis` at 2 Hz, `link` at 4 Hz |

The three streams run at different rates because they change at different
rates. Nothing in the stint moves faster than once a lap, so re-sending the lap
table sixty times a second would be waste.

A terminal dashboard is still available with `python -m gt7 dash` if you want
telemetry without a browser.

## Commands

| Command | What it does |
|---|---|
| `serve` | web pit wall (default) |
| `dash` | terminal dashboard |
| `probe` | ask the console for each wire format and report what came back |
| `dump` | annotated hex dump of one packet, plus the parsed fields as JSON |
| `record <file>` | capture raw datagrams for later analysis |
| `survey <file>` | classify every 4-byte slot in a capture: constant, counter, or live float |
| `diff <a> <b>` | compare two captures for condition-dependent fields (weather hunting) |
| `csv [-o file]` | stream telemetry to CSV |

Global flags: `--host` (PS5 IP) and `--format` (`A`, `B`, or `~`).

```bash
python -m gt7 serve --port 8000              # web pit wall
python -m gt7 probe                          # what does this console support?
python -m gt7 --format B serve               # adds the steering channel
python -m gt7 record lap.bin --seconds 60    # capture a lap
python -m gt7 survey lap.bin --unknown-only  # what is still unmapped?
python -m gt7 csv -o lap.csv --seconds 120   # log for offline analysis
python -m gt7 diff dry.bin wet.bin           # does anything change in the rain?
```

## Weather

**GT7 transmits no weather data** — no rain state, no track wetness, no radar.
This is established, not assumed; the evidence is in
[`docs/weather.md`](docs/weather.md). The short version:

- Format A's 296 bytes are **fully mapped** — there is no weather field among
  them, and the one spare region (`0xD4`–`0xF3`) is all zeros across every
  packet captured.
- The radar cannot be there on a counting argument alone: the largest format has
  48 unexplained bytes in total, and a 16×16 rain map needs 256.
- The `~` format's 48 unknown bytes are the only remaining hiding place, and two
  attacks on it have failed — including a **layout-free** one that would find
  the key even if the format were structured completely differently.

Time of day (`0x80`) is the only real environmental channel, and the dashboard
shows it as clock plus day/dusk/night.

Since wetness is not sent, the dashboard shows what wetness *does*: an
**inferred grip** readout built from longitudinal and lateral acceleration,
reported against the best that same car has managed this session, so it
self-calibrates per car and tyre.

```
peak grip                         1.42 g
vs best                ████████░░░░  71%
```

It is labelled as inference everywhere it appears, because a driver lifting off
looks exactly like a wet track. Treat it as a hint.

**To settle the question yourself**, in about two minutes:

```bash
python -m gt7 record dry.bin --seconds 60   # dry race
python -m gt7 record wet.bin --seconds 60   # same car and track, in rain
python -m gt7 diff dry.bin wet.bin
```

`diff` flags any slot that was always zero in the first capture and alive in the
second. If it prints nothing, the packet carries no weather data.

## Library use

```python
from gt7 import GT7Client

with GT7Client("192.168.1.67") as client:
    client.wait_for_frame()
    t = client.latest
    print(f"{t.speed_kph:.0f} km/h  {t.rpm:.0f} rpm  gear {t.gear_label}")
    print(t.corner("tyre_temp"))   # {'FL': 82.3, 'FR': 84.1, ...}
    print(t.tyre_slip)             # >1 spinning up, <1 locking
```

`GT7Client(host, fmt, on_frame=...)` also takes a callback driven at packet rate.

## Protocol

Full details, including the field map and the evidence behind it, are in
[`docs/protocol.md`](docs/protocol.md). The short version:

- Send one byte to UDP **:33739**; receive ~60 Hz telemetry on UDP **:33740**.
  The byte selects the format (`A` → 296 B, `B` → 316 B, `~` → 344 B).
- Packets are **Salsa20**-encrypted with the 32-byte prefix of
  `Simulator Interface Packet GT7 ver 0.0`.
- The nonce comes from a plaintext 32-bit seed at offset `0x40`:
  `u32le(seed ^ XOR) || u32le(seed)`.
- **The XOR constant differs per format**: `0xDEADBEAF` for A, `0xDEADBEEF` for
  B. One letter apart, and the usual reason a decrypt fails.
- Format A is **fully mapped** — `survey --unknown-only` reports no unknown
  bytes. Format B adds five floats, of which only steering (`0x128`) is
  confidently identified.
- The 344-byte `~` format is **not cracked**. A ~2.1×10⁸-trial search over keys,
  seed offsets and XOR constants came back empty; see `docs/protocol.md`.

## Notes from the wire

Two things cost real time to work out, so they are worth repeating:

**The console serves one telemetry session for the whole network.** The wire
format is fixed when a session opens, and *any* heartbeat renews it — including
one asking for a different format. So a second client anywhere on your LAN
holds the format open for everybody. This is the single easiest way to waste an
hour: a `gt7 dash` left running in another terminal made `B` and `~` look
unselectable for a long stretch of this work. Before probing formats:

```bash
ss -lunp | grep 33740     # is something already listening?
```

With nothing else running, format selection works first time. A single
heartbeat keeps the stream alive ~25 s, and closing your socket does not stop
it.

Because a stale session can never be ruled out, the client **decrypts by
observed packet length** rather than by what it asked for, and reports the
truth — the dashboard shows `fmt A (asked B; session already open)` instead of
quietly mislabelling the data.

**Decrypt by packet length, not by what you requested.** Because of the above,
during a format switch you briefly receive the old format. Keying the XOR
constant off `len(payload)` turns that into a few harmless frames instead of a
burst of decode errors.

## Tests

```bash
python -m pytest tests -q
```

The tests run against a recorded capture, so they need no console.

## Requirements

Python 3.11+ and `pycryptodomex`. The web dashboard needs `fastapi` and
`uvicorn`; the terminal dashboard needs `rich`. All are in `requirements.txt`.

The page loads two typefaces from Google Fonts and falls back to system faces
offline. Nothing else is fetched from the network.
