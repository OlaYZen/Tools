# The rest of the grid

**GT7 does not transmit anything about the other cars.** No opponent
positions, no lap times, no gaps. The only thing the protocol says about the
field is your own place in it and how many cars are running.

This document is the evidence, because an engineer asking for a gap deserves to
know whether it is missing or merely unimplemented.

## The counting argument

It does not depend on decryption. Across all three wire formats:

| Format | Size | Bytes not accounted for |
|---|---|---|
| A | 296 B | **0** |
| B | 316 B | 16 (four floats, two of them always `0.0`) |
| `~` | 344 B | 48 (still encrypted) |

Now the cost of carrying opponents, for a 20-car grid:

| What | Bytes |
|---|---|
| 19 opponents' positions (3 floats each) | 228 |
| 19 opponents, bare minimum (u16 place + i32 gap) | 114 |

The largest unexplained space anywhere in the protocol is **48 bytes**. Even the
most frugal encoding of a 20-car grid needs more than twice that. There is no
packet here that could carry the field, whatever the `~` format's encryption
hides.

## There is no second channel either

Checked directly against a live console mid-race:

- **TCP scan** of ports 33700–33800 plus every port a PS5 is known to open:
  one hit, **9295**, which is Remote Play. Nothing from GT7.
- **Passive UDP listen** on 104 ports around the telemetry pair for 25 seconds
  during a race: **no unprompted traffic at all**. The console speaks only when
  spoken to, and only on 33739/33740.
- **Heartbeat probe** of ports 33735–33745 and a few others: **no port other
  than 33739 answers**.

So the Simulator Interface is the whole interface, and it is a single-car feed.
The name is accurate.

## What you do get

Two fields, both in format A:

| Offset | Field |
|---|---|
| `0x84` | your position |
| `0x86` | cars in the race |

### One caveat about `0x84`

Community documentation calls this field the *pre-race or qualifying* position,
which would make it fixed for the whole race rather than live. Observation here
is not conclusive either way: it read `13 / 20` in one session and `1 / 20` in
another, and across the laps watched live it held steady at `1 / 20` — from a
car that was leading, so a static and a live field look identical.

`StintTracker` therefore treats it as live but does not depend on it: it records
a change only after the new value holds for 12 frames, and if the field turns
out to be static then `places_gained` stays 0 and no position callouts fire.
Nothing is invented either way.

To settle it, watch the Race panel while overtaking someone. If the number
moves, it is live.

## What the app does with it

The **Race** panel shows your place, the field size, where you started and the
net places gained or lost, plus a log of each change with the lap it happened
on. Position changes become radio callouts:

```
[info] Up to P11.                     from P13 on lap 5
[info] P11 of 20, up 2 from your start.
[warn] Dropped to P14. Watch your mirrors.
```

The panel also states the limit on screen, so nobody hunts for a gap readout
that cannot exist:

> No gaps: GT7 sends telemetry for your car only, so there is nothing about the
> cars ahead or behind. Places are all the protocol carries.

## If you need real gaps

They have to come from somewhere other than this protocol — reading the on-screen
timing board with OCR from a capture card, or a game mode that exposes more.
Nothing in the UDP interface will give them to you.
