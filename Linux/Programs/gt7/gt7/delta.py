"""Where a lap gained or lost time against a reference lap.

GT7 sends no distance-round-lap and no sector times, so a delta has to be built
from position: for each point of one lap, find where the reference lap was at
the same *place*, and compare how long each took to get there. That is how real
delta systems work, and world position is exact enough to do it (integrating it
matches reported speed to 0.1%).

Two details make the difference between a delta that reads well and one that is
noise:

**Time comes from `packet_id`, not the wall clock.** The counter advances once
per simulation frame whether or not the datagram reached us, so a dropped UDP
packet costs a sample but never distorts the clock. The tick rate is not
assumed either - GT7 reports the lap time, and the tick count is known, so
milliseconds-per-tick is measured per lap rather than hard-coded to 60 Hz.

**Matching walks forward.** Nearest-point search over the whole reference will
happily jump to the other side of a hairpin, or back onto a straight the car
crossed earlier, producing large fake deltas. The search only ever moves
forward from the previous match, so progress round the lap stays monotonic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Fallback when a lap time is missing and ticks cannot be calibrated.
NOMINAL_MS_PER_TICK = 1000.0 / 60.0

#: How far ahead of the last match to look for the nearest reference point.
#: Wide enough to absorb a much faster or slower lap, narrow enough that the
#: search cannot wander to an unrelated part of the circuit.
SEARCH_AHEAD = 120

#: Points closer together than this are the same place for matching purposes.
SNAP_METRES = 40.0

#: A race's opening lap starts on the grid, which sits ahead of the
#: start/finish line, so it covers less than a full lap and its time is not
#: comparable with the rest. Left in, it becomes the fastest lap and therefore
#: the reference, and every honest lap afterwards reads as seconds slow.
#: Time trials have the same shape with an out-lap. Treat it as one.
OUT_LAP = 1


def is_out_lap(number: int) -> bool:
    """True for a lap that is not comparable with a flying lap."""
    return number <= OUT_LAP


@dataclass(slots=True)
class LapTrace:
    """One lap's path through space and time."""

    number: int
    xs: list[float]
    zs: list[float]
    inputs: list[int]
    #: Console frame counter at each point. Only differences matter.
    ticks: list[int]
    #: GT7's own time for the lap, used to calibrate the tick rate.
    lap_ms: int

    @property
    def ms_per_tick(self) -> float:
        span = self.ticks[-1] - self.ticks[0] if len(self.ticks) > 1 else 0
        if span <= 0 or self.lap_ms <= 0:
            return NOMINAL_MS_PER_TICK
        return self.lap_ms / span

    def elapsed_ms(self, index: int) -> float:
        return (self.ticks[index] - self.ticks[0]) * self.ms_per_tick

    def __len__(self) -> int:
        return len(self.xs)


@dataclass(slots=True)
class LapComparison:
    """Per-segment time lost (+) or gained (-) against a reference lap."""

    lap_number: int
    reference_number: int
    lap_ms: int
    reference_ms: int
    #: One entry per point of the compared lap. Positive means the car took
    #: longer over that segment than the reference did.
    segment_ms: list[float] = field(default_factory=list)
    #: Running total of the above, so the map can show a delta at any point.
    cumulative_ms: list[float] = field(default_factory=list)

    @property
    def total_ms(self) -> float:
        return self.cumulative_ms[-1] if self.cumulative_ms else 0.0

    def worst(self, count: int = 3) -> list[tuple[int, float]]:
        """The (index, ms) of the biggest individual time losses."""
        ranked = sorted(enumerate(self.segment_ms), key=lambda p: -p[1])
        return [(i, ms) for i, ms in ranked[:count] if ms > 0]


def _grid(trace: LapTrace) -> dict[tuple[int, int], list[int]]:
    cells: dict[tuple[int, int], list[int]] = {}
    for i, (x, z) in enumerate(zip(trace.xs, trace.zs)):
        cells.setdefault((int(x // SNAP_METRES), int(z // SNAP_METRES)), []).append(i)
    return cells


def compare(lap: LapTrace, reference: LapTrace) -> LapComparison | None:
    """Compare `lap` against `reference`, point by point along the track."""
    if len(lap) < 4 or len(reference) < 4:
        return None

    cells = _grid(reference)
    result = LapComparison(
        lap_number=lap.number, reference_number=reference.number,
        lap_ms=lap.lap_ms, reference_ms=reference.lap_ms,
    )

    cursor = 0          # last matched index in the reference
    previous = 0
    running = 0.0
    result.segment_ms.append(0.0)
    result.cumulative_ms.append(0.0)

    for i in range(1, len(lap)):
        cursor = _nearest_ahead(lap.xs[i], lap.zs[i], reference, cells, cursor)
        if cursor <= previous:
            # No forward progress on the reference - a hairpin apex, or the car
            # stopped. Charge the whole segment as lost time rather than
            # inventing a negative gain from a stale match.
            lap_dt = lap.elapsed_ms(i) - lap.elapsed_ms(i - 1)
            running += lap_dt
            result.segment_ms.append(lap_dt)
            result.cumulative_ms.append(running)
            continue

        lap_dt = lap.elapsed_ms(i) - lap.elapsed_ms(i - 1)
        ref_dt = reference.elapsed_ms(cursor) - reference.elapsed_ms(previous)
        segment = lap_dt - ref_dt
        running += segment
        result.segment_ms.append(segment)
        result.cumulative_ms.append(running)
        previous = cursor

    return result


def _nearest_ahead(x: float, z: float, reference: LapTrace,
                   cells: dict[tuple[int, int], list[int]], cursor: int) -> int:
    """Closest reference point at or after `cursor`, within the search window."""
    best_index = cursor
    best_distance = float("inf")
    cx, cz = int(x // SNAP_METRES), int(z // SNAP_METRES)
    limit = cursor + SEARCH_AHEAD

    for dx in (-1, 0, 1):
        for dz in (-1, 0, 1):
            for i in cells.get((cx + dx, cz + dz), ()):
                if i < cursor or i > limit:
                    continue
                distance = (reference.xs[i] - x) ** 2 + (reference.zs[i] - z) ** 2
                if distance < best_distance:
                    best_distance = distance
                    best_index = i

    if best_distance == float("inf"):
        # Off the reference line entirely - a spin, a cut, or the pit lane.
        # Walk on by one so the comparison keeps advancing.
        return min(cursor + 1, len(reference) - 1)
    return best_index


def bucket(lap: LapTrace, comparison: LapComparison,
           target_points: int = 400) -> tuple[list[float], list[float], list[float]]:
    """Thin a comparison for the wire without losing any of the time.

    Sampling every Nth point would throw away the deltas in between and the
    map would no longer add up to the lap time difference. Each kept point
    therefore carries the sum of the segments it stands for.

    Rounding still costs a millisecond or so across a lap, which is fine for
    colouring a map but not for a headline figure - report `total_ms` from the
    comparison itself, never the sum of these buckets.
    """
    if not len(lap):
        return [], [], []
    stride = max(1, len(lap) // max(target_points, 1))
    xs: list[float] = []
    zs: list[float] = []
    deltas: list[float] = []
    carried = 0.0
    for i in range(len(lap)):
        carried += comparison.segment_ms[i]
        if i % stride == 0 or i == len(lap) - 1:
            xs.append(round(lap.xs[i], 1))
            zs.append(round(lap.zs[i], 1))
            deltas.append(round(carried, 2))
            carried = 0.0
    return xs, zs, deltas


class DeltaTracker:
    """Keeps the reference lap and compares each new lap against it."""

    def __init__(self) -> None:
        self.reference: LapTrace | None = None
        self.latest: LapTrace | None = None
        self.comparison: LapComparison | None = None

    def reset(self) -> None:
        self.reference = None
        self.latest = None
        self.comparison = None

    def add_lap(self, lap: LapTrace) -> LapComparison | None:
        """Record a completed lap and compare it to the best one so far.

        Compared *before* the reference is updated, so a new fastest lap is
        still shown against what it beat rather than against itself.

        The out-lap is dropped entirely rather than merely kept out of the
        reference: its geometry stops at the line but starts on the grid, so
        even drawing it would show a partial circuit.
        """
        if is_out_lap(lap.number):
            return None
        self.latest = lap
        if self.reference is not None and self.reference.number != lap.number:
            self.comparison = compare(lap, self.reference)
        else:
            self.comparison = None

        if lap.lap_ms > 0 and (self.reference is None
                               or lap.lap_ms < self.reference.lap_ms):
            self.reference = lap
        return self.comparison
