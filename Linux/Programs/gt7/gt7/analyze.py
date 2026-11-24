"""Protocol-analysis helpers - the tools used to map the packet.

`hexdump` annotates a decoded packet against the known field map so unmapped
bytes stand out.  `survey` watches every 4-byte slot across a capture and
reports how each one behaves, which is how you tell a constant from a counter
from a live float.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable, Sequence

from .crypto import decrypt
from .packet import PACKET_SIZE

#: (offset, length, name) for every field we have identified.
FIELD_MAP: tuple[tuple[int, int, str], ...] = (
    (0x00, 4, "magic"), (0x04, 12, "position xyz"), (0x10, 12, "velocity xyz"),
    (0x1C, 16, "rotation ijk + north"), (0x2C, 12, "angular velocity xyz"),
    (0x38, 4, "ride height"), (0x3C, 4, "engine rpm"), (0x40, 4, "IV seed (clear)"),
    (0x44, 4, "fuel level"), (0x48, 4, "fuel capacity"), (0x4C, 4, "speed m/s"),
    (0x50, 4, "turbo boost"), (0x54, 4, "oil pressure"), (0x58, 4, "water temp"),
    (0x5C, 4, "oil temp"), (0x60, 16, "tyre temp FL FR RL RR"), (0x70, 4, "packet id"),
    (0x74, 2, "current lap"), (0x76, 2, "laps in race"), (0x78, 4, "best lap ms"),
    (0x7C, 4, "last lap ms"), (0x80, 4, "time of day ms"), (0x84, 2, "grid position"),
    (0x86, 2, "cars in race"), (0x88, 2, "rpm warning"), (0x8A, 2, "rpm limiter"),
    (0x8C, 2, "top speed kph"), (0x8E, 2, "flags"), (0x90, 1, "gear nibbles"),
    (0x91, 1, "throttle"), (0x92, 1, "brake"), (0x93, 1, "padding"),
    (0x94, 12, "road plane xyz"), (0xA0, 4, "road plane dist"),
    (0xA4, 16, "wheel rad/s"), (0xB4, 16, "tyre radius"), (0xC4, 16, "suspension"),
    (0xD4, 32, "reserved (zero)"), (0xF4, 4, "clutch"), (0xF8, 4, "clutch engagement"),
    (0xFC, 4, "rpm after clutch"), (0x100, 4, "transmission top speed"),
    (0x104, 32, "gear ratios"), (0x124, 4, "car code"),
    (0x128, 4, "wheel rotation (fmt B)"), (0x12C, 4, "ext unknown (fmt B)"),
    (0x130, 4, "ext unknown (fmt B)"), (0x134, 4, "ext unknown (fmt B)"),
    (0x138, 4, "ext unknown (fmt B)"),
)


def field_at(offset: int) -> str:
    for start, length, name in FIELD_MAP:
        if start <= offset < start + length:
            return name
    return ""


def hexdump(plain: bytes, width: int = 16) -> str:
    """Annotated hex dump of a decrypted packet."""
    lines = []
    for base in range(0, len(plain), width):
        row = plain[base : base + width]
        names: list[str] = []
        for i in range(len(row)):
            name = field_at(base + i)
            if name and name not in names:
                names.append(name)
        ascii_col = "".join(chr(c) if 32 <= c < 127 else "." for c in row)
        lines.append(
            f"{base:04x}  {row.hex(' '):<{width * 3}} |{ascii_col:<{width}}|  "
            + ", ".join(names)
        )
    return "\n".join(lines)


def _f32(buf: bytes, off: int) -> float:
    return struct.unpack_from("<f", buf, off)[0]


def survey(frames: Sequence[bytes], step: int = 4) -> list[dict[str, object]]:
    """Classify every 4-byte slot across a set of decrypted frames.

    Returns one record per offset with the observed range, how often it
    changed, and a guess at what kind of value it holds.
    """
    if not frames:
        return []
    size = min(len(f) for f in frames)
    out: list[dict[str, object]] = []
    for off in range(0, size - 3, step):
        floats = [_f32(f, off) for f in frames]
        ints = [struct.unpack_from("<I", f, off)[0] for f in frames]
        changes = sum(1 for a, b in zip(ints, ints[1:]) if a != b)
        finite = [v for v in floats if math.isfinite(v)]
        sane = finite and all(abs(v) < 1e9 for v in finite)

        if changes == 0:
            kind = "constant"
        elif all(b - a == 1 for a, b in zip(ints, ints[1:])):
            kind = "counter(+1)"
        elif sane and len(set(floats)) > len(floats) * 0.5:
            kind = "float(live)"
        elif sane:
            kind = "float"
        else:
            kind = "int/bits"

        out.append({
            "offset": off,
            "field": field_at(off),
            "kind": kind,
            "changes": changes,
            "min": min(finite) if finite else float("nan"),
            "max": max(finite) if finite else float("nan"),
            "u32_first": ints[0],
        })
    return out


#: Slots that drift between *any* two captures simply because time passed or
#: the car moved. They are never evidence of a condition-dependent field, and
#: reporting them unmarked buries a real find in noise.
EXPECTED_DRIFT: frozenset[int] = frozenset({
    0x04, 0x08, 0x0C,   # position
    0x44,               # fuel level (monotonically consumed)
    0x70,               # packet id (counter)
    0x74,               # lap counter
    0x78, 0x7C,         # best / last lap
    0x80,               # time of day
})


def constant_zero_offsets(frames: Sequence[bytes], step: int = 4) -> set[int]:
    """4-byte slots that are zero in every frame."""
    if not frames:
        return set()
    size = min(len(f) for f in frames)
    return {
        off for off in range(0, size - 3, step)
        if all(f[off : off + 4] == b"\x00\x00\x00\x00" for f in frames)
    }


def compare(a: Sequence[bytes], b: Sequence[bytes], step: int = 4) -> list[dict[str, object]]:
    """Find slots that behave differently between two captures.

    This is how you hunt a conditionally-populated field: capture the same
    car and track under two conditions, and look for a slot that is dead in
    one capture and alive in the other. `verdict` ranks what was found:

      activated   zero throughout A, non-zero in B  <- the smoking gun
      silenced    the reverse
      range-shift both alive, but over disjoint value ranges

    Slots that merely differ in value are ignored; on a moving car nearly
    every slot does.
    """
    if not a or not b:
        return []
    size = min(min(len(f) for f in a), min(len(f) for f in b))
    zeros_a = constant_zero_offsets(a, step)
    zeros_b = constant_zero_offsets(b, step)

    out: list[dict[str, object]] = []
    for off in range(0, size - 3, step):
        fa = [_f32(f, off) for f in a]
        fb = [_f32(f, off) for f in b]
        dead_a, dead_b = off in zeros_a, off in zeros_b

        if dead_a and not dead_b:
            verdict = "activated"
        elif dead_b and not dead_a:
            verdict = "silenced"
        elif dead_a and dead_b:
            continue
        else:
            lo_a, hi_a = min(fa), max(fa)
            lo_b, hi_b = min(fb), max(fb)
            if math.isfinite(lo_a) and math.isfinite(lo_b) and (hi_a < lo_b or hi_b < lo_a):
                verdict = "range-shift"
            else:
                continue

        out.append({
            "offset": off,
            "field": field_at(off),
            "verdict": verdict,
            "expected": off in EXPECTED_DRIFT,
            "a_min": min(fa), "a_max": max(fa),
            "b_min": min(fb), "b_max": max(fb),
        })
    order = {"activated": 0, "silenced": 1, "range-shift": 2}
    out.sort(key=lambda r: (r["expected"], order[r["verdict"]], r["offset"]))
    return out


def decrypt_all(datagrams: Iterable[bytes]) -> list[bytes]:
    """Decrypt datagrams, silently skipping any that fail."""
    frames = []
    for payload in datagrams:
        try:
            frames.append(decrypt(payload))
        except Exception:
            continue
    return frames


def unmapped_offsets(size: int = PACKET_SIZE) -> list[int]:
    """Byte offsets not covered by FIELD_MAP - the remaining unknowns."""
    covered = set()
    for start, length, _ in FIELD_MAP:
        covered.update(range(start, start + length))
    return [o for o in range(size) if o not in covered]
