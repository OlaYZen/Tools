# Weather in GT7 telemetry

**Short answer: there isn't any.** No rain state, no track wetness, no radar.
This document is the evidence, because "I couldn't find it" and "it isn't
there" are different claims and only one of them is worth trusting.

## Weather radar — definitively not present

The radar is a UI overlay drawn by the game, not something it transmits. The
argument is a counting one, and it does not depend on decryption:

| Format | Size | Unaccounted bytes |
|---|---|---|
| A | 296 B | **0** |
| B | 316 B | 16 (four floats, two of them always `0.0`) |
| `~` | 344 B | 48 (still encrypted) |

A rain map of even trivial resolution — say 16×16 cells at one byte each —
needs 256 bytes. The largest format has 48 unexplained bytes in total. There is
no packet in this protocol that could carry a radar image, whatever the
encryption hides.

## Track wetness — not in any format we can read

**Format A (296 B) is fully mapped.** Every 4-byte slot has an identified
field; `gt7 survey <capture> --unknown-only` returns nothing. There is no
wetness channel among them.

The only spare space is the 32-byte reserved block at `0xD4`–`0xF3`. Checked
live across 481 consecutive packets: **one distinct value, all zeros**.

```
481 packets, 1 distinct values of the 32-byte reserved block
   00 00 00 00 ... 00
all zero: True
```

**Format B (316 B)** adds five floats. `0x128` is steering; `0x130` and `0x138`
are `0.0` in every capture; `0x12C` tracks yaw rate and `0x134` tracks speed.
None behaves like a surface-condition value.

**Format `~` (344 B)** has 48 unknown bytes and remains encrypted. It is the
only place a weather field could still be hiding. Two independent attacks have
now failed on it:

1. `tools/crack.py` — magic and hardcoded-temperature oracles, ~2.1×10⁸ trials.
2. `tools/crack_structural.py` — a **layout-free** oracle. A correctly
   decrypted packet is full of structural zeros (76 of 316 bytes in format B);
   ciphertext has none. Seeing ≥12 zeros in 344 random bytes has probability
   ~10⁻¹¹, so this oracle finds a correct key even if the format's header and
   layout are completely different. Best score across the whole search: **11
   zeros**, which is exactly what chance produces. Nothing was found.

### The honest limit of this claim

Every capture above was taken in the conditions the console happened to be in,
and I could not set up a wet race to test against. So the accurate statement is
*"the reserved block is zero in all conditions observed"*, not *"it is zero
always"*. A field that only exists when it rains would look exactly like this
until it rains.

That gap is closable in about two minutes, by you:

```bash
gt7 record dry.bin --seconds 60   # dry race
gt7 record wet.bin --seconds 60   # same car, same track, in rain
gt7 diff dry.bin wet.bin
```

`diff` reports any 4-byte slot that was **always zero in the first capture and
alive in the second** — the exact signature of a conditionally-populated field.
If it prints nothing, the packet carries no weather data and the question is
settled. (The tool is validated against a synthetic wetness field planted at
`0xD4`, which it flags as `activated`.)

## What *is* environmental

One thing, and it is genuinely useful: **time of day** at `0x80`, in
milliseconds since midnight. That gives day/night and dusk, which the dashboard
shows. Endurance races change light over time and this tracks it exactly.

## The nearest useful substitute: inferred grip

Since wetness is not transmitted, the dashboard shows what wetness *does*
instead. Wet asphalt reduces available friction, and friction is measurable
from motion data the console does send:

- **longitudinal g** — speed differentiated over 5 frames (~83 ms)
- **lateral g** — `yaw rate × speed`, exact in steady-state cornering

The 95th percentile of combined g over a 20-second window is a reasonable proxy
for available grip. The percentile matters: taking the maximum would let a
single kerb strike define the car's grip for the whole session.

Because the absolute figure depends entirely on car and tyre compound, the
useful reading is **`vs best`** — recent grip against the best that same car
has managed this session. It self-calibrates, with no lookup table.

```
peak grip                         1.42 g
vs best                ████████░░░░  71%
```

**Read this as a hint, not a measurement.** It is inference, not telemetry, and
the dashboard labels it so. A driver lifting off looks identical to a wet
track. It is only meaningful when compared against hard driving in the same car,
which is why `GripEstimator.confidence` reports `warming up` or
`no hard driving seen` until there is enough data to be worth reading.
