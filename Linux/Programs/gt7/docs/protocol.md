# GT7 Simulator Interface — protocol notes

Everything here was verified against a live PS5 (`192.168.1.67`) running GT7.
Where a field is *not* confirmed, it says so.

## Transport

| | |
|---|---|
| Heartbeat | UDP → console **:33739**, one byte |
| Telemetry | UDP ← console **:33740**, ~60 Hz |
| Source port | ephemeral on the console (observed 56577), so bind `0.0.0.0:33740` and ignore the source port |

The console never streams unprompted. Send a heartbeat, get telemetry, re-send
to keep it alive. This client re-arms every 2 s.

### Session lifetime is longer than folklore says

The commonly cited figure is "the stream stops after ~10 s of silence". That is
wrong: from a **single** heartbeat and never another, the stream ran for
**24.6 s** before stopping. A separate run was still receiving at 60 s, but that
one turned out to be confounded (see below), so 24.6 s is the number to trust.

Closing the receiving socket does **not** tear the session down: after
`close()`, packets kept arriving for at least 20 s, so the console ignores the
resulting ICMP port-unreachable.

### The console serves one session at a time — for the whole network

**The byte you send selects the wire format, but only when it opens a new
session.** While a session is live the format is fixed, and *any* heartbeat
renews it — including one asking for a different format. Asking for `B` during
an `A` session just keeps the `A` session alive.

Critically, this is **not per client**. The console runs one telemetry session,
and a second program anywhere on the network holds it open for everyone. This
cost real time to find: a stretch of experiments concluded that `B` and `~`
could not be selected at all, because a `gt7 dash` left running in another
terminal was re-arming an `A` session every 2 s the entire time. With nothing
else running, format selection works perfectly on the first try:

```
heartbeat 'A' -> 296 B    heartbeat 'B' -> 316 B
heartbeat 'A' -> 296 B    heartbeat '~' -> 344 B
```

So before probing formats, **check that nothing else is talking to the
console**:

```bash
ss -lunp | grep 33740     # anything already listening?
```

Two clients on the same host is doubly bad: this client sets `SO_REUSEADDR`, so
a second instance binds `:33740` successfully and then silently steals packets
from the first.

Because a stale session can never be fully ruled out, the client does not trust
its own request. It decrypts by *observed packet length* and reports the format
actually being served — `GT7Client.active_format` and `.format_mismatch` — and
the dashboard shows `fmt A (asked B; session already open)` rather than
mislabelling the data.

| Heartbeat | Size | Status |
|---|---|---|
| `A` | 296 B | fully decoded |
| `B` | 316 B | fully decoded — format A plus five floats |
| `~` | 344 B | **encryption not cracked** (see below) |

## Encryption

Salsa20. The key is the 32-byte prefix of the ASCII string:

```
Simulator Interface Packet GT7 ver 0.0
└──────────────── 32 bytes ─────┘
```

The nonce is derived per packet from a 32-bit seed the console leaves **in the
clear** at offset `0x40` of the ciphertext:

```
seed  = u32le(ciphertext[0x40:0x44])
nonce = u32le(seed ^ XOR) || u32le(seed)
```

The XOR constant is the *only* thing that differs between formats — and the
difference is a single letter:

| Format | XOR constant |
|---|---|
| A (296 B) | `0xDEADBEAF` |
| B (316 B) | `0xDEADBEEF` |

`0xDEADBE**A**F` for A, `0xDEADBE**E**F` for B. Easy to misread; if a packet
fails to decrypt, check this first.

### Verifying a decrypt

Two independent checks, both used by this client:

1. `plaintext[0x00:0x04] == b"0S7G"` (`0x47375330` as a little-endian u32).
2. The game hardcodes **water temp `85.0`** at `0x58` and **oil temp `110.0`**
   at `0x5C`. These are constants in every packet, in every car, and make an
   excellent oracle when you are searching for an unknown key or nonce.

### The `~` (344-byte) format is not cracked

The console answers the `~` heartbeat with well-formed 344-byte datagrams, but
none of the following recovers a valid magic or the temperature constants:

- 166 candidate keys — the known key at every offset, version-string variants
  (`ver 0.0` … `ver 2.9`), GT6/GTS-style strings, and every 32-byte window of each
- every 4-byte-aligned nonce-seed offset in the packet (0x00–0x154)
- 771 XOR constants, including the whole `0xDEADBExx` and `0xDEADxxxx` families
  and `0xxxxxxxEF`/`0xxxxxxxAF` patterns
- both nonce word orders

That is ~2.1×10⁸ trial decryptions, all negative. So `~` uses either a
different key, a nonce not derived from a single in-packet u32, or a different
derivation entirely. Recovering it almost certainly needs the game binary
rather than black-box search. `gt7 probe` will still show the console
answering, and `gt7 record --format '~'` captures the raw ciphertext.

## Packet layout (format A, 296 B / 0x128)

All little-endian. Offsets confirmed against live data.

| Offset | Type | Field | Notes |
|---|---|---|---|
| `0x00` | u32 | magic | `0x47375330` |
| `0x04` | 3×f32 | position x, y, z | metres, world space |
| `0x10` | 3×f32 | velocity x, y, z | m/s, world space |
| `0x1C` | 4×f32 | rotation i, j, k + heading | heading is orientation relative to north, −1…1 |
| `0x2C` | 3×f32 | angular velocity x, y, z | rad/s |
| `0x38` | f32 | ride height | metres |
| `0x3C` | f32 | engine RPM | |
| `0x40` | u32 | **nonce seed** | plaintext here is not telemetry |
| `0x44` | f32 | fuel level | `0.0` capacity ⇒ electric car |
| `0x48` | f32 | fuel capacity | |
| `0x4C` | f32 | speed | m/s — ×3.6 for km/h |
| `0x50` | f32 | turbo boost | absolute; **bar = value − 1.0** |
| `0x54` | f32 | oil pressure | |
| `0x58` | f32 | water temp | hardcoded `85.0` |
| `0x5C` | f32 | oil temp | hardcoded `110.0` |
| `0x60` | 4×f32 | tyre surface temp | FL, FR, RL, RR — °C |
| `0x70` | u32 | packet id | monotonic; gaps = dropped packets |
| `0x74` | u16 | current lap | |
| `0x76` | u16 | laps in race | |
| `0x78` | i32 | best lap | ms, `-1` if unset |
| `0x7C` | i32 | last lap | ms, `-1` if unset |
| `0x80` | i32 | time of day | ms since midnight |
| `0x84` | i16 | grid position | |
| `0x86` | i16 | cars in race | |
| `0x88` | i16 | rev warning RPM | |
| `0x8A` | i16 | rev limiter RPM | |
| `0x8C` | u16 | calculated top speed | km/h |
| `0x8E` | u16 | flags | see below |
| `0x90` | u8 | gear nibbles | low = current, high = suggested |
| `0x91` | u8 | throttle | 0–255 |
| `0x92` | u8 | brake | 0–255 |
| `0x93` | u8 | padding | |
| `0x94` | 3×f32 | road plane normal | |
| `0xA0` | f32 | road plane distance | |
| `0xA4` | 4×f32 | wheel angular speed | rad/s, FL FR RL RR |
| `0xB4` | 4×f32 | tyre radius | metres |
| `0xC4` | 4×f32 | suspension travel | |
| `0xD4` | 8×f32 | reserved | zero in every capture |
| `0xF4` | f32 | clutch pedal | 0–1 |
| `0xF8` | f32 | clutch engagement | 0–1 |
| `0xFC` | f32 | RPM after clutch | gearbox input shaft |
| `0x100` | f32 | final drive / top-speed ratio | |
| `0x104` | 8×f32 | gear ratios | unused gears read `0.0` |
| `0x124` | u32 | car code | |

`gt7 survey <capture> --unknown-only` reports **no unmapped bytes** in format A.

### Gear nibbles (`0x90`)

`current = b & 0x0F`, `suggested = b >> 4`. Current `0` is reverse and `15` is
neutral; a suggested value of `15` means "no suggestion".

### Flags (`0x8E`)

| Bit | Meaning |
|---|---|
| 0 | car on track |
| 1 | paused |
| 2 | loading / processing |
| 3 | in gear |
| 4 | has turbo |
| 5 | rev limiter / blink alert |
| 6 | handbrake |
| 7 | lights |
| 8 | high beam |
| 9 | low beam |
| 10 | ASM |
| 11 | TCS |

### Cross-checks that confirmed the map

- water `85.0` / oil `110.0` land exactly on `0x58` / `0x5C`
- `0xFC` (RPM after clutch) equals `0x3C` (engine RPM) with the clutch out, and
  drops to `0.0` with the clutch in while engagement `0xF8` goes to `0.0`
- `0x70` increments by exactly 1 per packet across a 480-packet capture
- `0x80` decoded to `12:00:21`, matching the in-game clock
- best/last lap decoded to `1:43.332`
- gear ratios read `2.987 2.201 1.805 1.500 1.279 1.078` — a plausible 6-speed,
  with the remaining two slots `0.0`

## Format B extras (316 B / 0x13C)

Format B is byte-identical to A for the first 296 bytes, then adds five floats.
**Only the first is identified with confidence.**

| Offset | Field | Confidence |
|---|---|---|
| `0x128` | steering, radians, signed. **Raw sign is positive-for-LEFT** | **confirmed** against a real wheel — see below |
| `0x12C` | unknown | moves every frame; correlated ~0.5 with yaw rate. Community convention calls this "sway" |
| `0x130` | unknown | `0.0` in every capture so far |
| `0x134` | unknown | tracked speed exactly in one idle capture; "surge" candidate |
| `0x138` | unknown | `0.0` in every capture so far |

### `0x128` is steering, and its sign runs backwards

Confirmed by turning a real wheel and watching the field: `0x128` tracks
steering input. Two things about it will catch you out.

**The sign is inverted relative to every other telemetry convention.** The raw
field goes *positive when the driver turns left*. A dashboard that feeds the raw
value into a centre-origin meter shows left inputs deflecting right, which is
exactly the bug this cost. `parse()` therefore negates it once, so
`Telemetry.wheel_rotation` is **positive = right** like everything else, and
`Telemetry.raw_wheel_rotation` keeps the unflipped value for protocol work.

**It saturates at exactly pi.** One captured frame — a car at 16 km/h in first
gear — holds `3.1415927410125732`, which is pi to the bit (`0x40490FDB`), i.e.
exactly 180.000 degrees.

An analog input almost never lands on a transcendental constant by chance. That
is a clamp: the field is bounded at `±pi` and had saturated. What it does *not*
tell us is what physical lock `pi` corresponds to — a 180-degree wheel, a
900-degree wheel normalised to the range, or a controller stick at full
deflection.

An analog input almost never lands on a transcendental constant by chance, so
that is a clamp: the field is bounded at `±pi`. What it does *not* tell us is
what physical lock `pi` corresponds to — a 180-degree wheel, a 900-degree wheel
normalised into the range, or a stick at full deflection.

So the *identity* of the field is settled but its *scale* is not. Anything built
on it should depend on the sign and the size of changes, not on an absolute
angle. `StintTracker` counts turning points and normalises against the driver's
own median; it never reports degrees. The live meter draws deflection as a
fraction of `pi`, which is honest whatever `pi` turns out to mean.

`tools/steering_probe.py` is the tool that settles questions like this. It
checks control channels (rpm, speed) before drawing any conclusion, because
**the console keeps streaming at a full 60 Hz while the game is paused**,
serving a frozen snapshot. Without that check it reported a confident "nothing
responded" from 2399 frames of a paused game.

These were characterised with the car **stationary**, which is why four of five
are unresolved — a stationary car exercises almost none of them. To finish the
job, drive a lap and run:

```bash
gt7 --format B record drive.bin --seconds 60
gt7 survey drive.bin
```

Then compare the `0x128`–`0x138` rows against the known motion channels
(velocity `0x10`, angular velocity `0x2C`, speed `0x4C`).
