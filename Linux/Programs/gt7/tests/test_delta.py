"""Position-based lap deltas: where time was lost against a reference lap."""

from __future__ import annotations

import math

import pytest

from gt7.delta import DeltaTracker, LapTrace, bucket, compare

N = 600
RADIUS = 400.0


def lap(number: int, lap_ms: int, slow: tuple[int, int] | None = None,
        factor: float = 1.0) -> LapTrace:
    """A circular lap, optionally dawdling over one arc."""
    xs, zs, inputs, ticks = [], [], [], []
    tick = 0.0
    for i in range(N):
        angle = 2 * math.pi * i / N
        xs.append(RADIUS * math.cos(angle))
        zs.append(RADIUS * math.sin(angle))
        inputs.append(2)
        ticks.append(int(tick))
        tick += factor if (slow and slow[0] <= i < slow[1]) else 1.0
    return LapTrace(number, xs, zs, inputs, ticks, lap_ms)


def calibrated(reference: LapTrace, trace: LapTrace) -> LapTrace:
    """Give `trace` the lap time its tick count implies under `reference`."""
    span = trace.ticks[-1] - trace.ticks[0]
    trace.lap_ms = int(round(span * reference.ms_per_tick))
    return trace


def test_an_identical_lap_shows_no_delta():
    reference = lap(1, 60_000)
    result = compare(lap(2, 60_000), reference)
    assert result.total_ms == pytest.approx(0.0, abs=1.0)


def test_the_total_matches_the_lap_time_difference():
    reference = lap(1, 60_000)
    slower = calibrated(reference, lap(2, 0, slow=(200, 275), factor=3.0))
    result = compare(slower, reference)
    assert result.total_ms == pytest.approx(slower.lap_ms - reference.lap_ms, rel=0.01)


def test_the_loss_is_located_where_it_happened():
    reference = lap(1, 60_000)
    slower = calibrated(reference, lap(2, 0, slow=(200, 275), factor=3.0))
    result = compare(slower, reference)
    for index, _ms in result.worst(3):
        assert 190 <= index <= 285


def test_a_faster_lap_reads_as_time_gained():
    reference = lap(1, 60_000)
    quicker = calibrated(reference, lap(2, 0, slow=(100, 300), factor=0.5))
    result = compare(quicker, reference)
    assert result.total_ms < 0
    assert quicker.lap_ms < reference.lap_ms


def test_the_tick_rate_is_measured_not_assumed():
    """A lap timed at something other than 60 Hz must still come out right."""
    reference = lap(1, 90_000)          # 600 ticks declared as 90s
    assert reference.ms_per_tick == pytest.approx(90_000 / 599, rel=1e-6)
    slower = calibrated(reference, lap(2, 0, slow=(200, 275), factor=3.0))
    result = compare(slower, reference)
    assert result.total_ms == pytest.approx(slower.lap_ms - reference.lap_ms, rel=0.01)


def test_matching_does_not_jump_across_the_circuit():
    """A figure-of-eight crosses itself; the match must not teleport."""
    xs, zs, inputs, ticks = [], [], [], []
    for i in range(N):
        t = 2 * math.pi * i / N
        xs.append(RADIUS * math.sin(t))
        zs.append(RADIUS * math.sin(t) * math.cos(t))
        inputs.append(2)
        ticks.append(i)
    reference = LapTrace(1, xs, zs, inputs, ticks, 60_000)
    same = LapTrace(2, list(xs), list(zs), list(inputs), list(ticks), 60_000)
    result = compare(same, reference)
    # Identical laps over a self-crossing circuit must still read as zero.
    assert result.total_ms == pytest.approx(0.0, abs=50.0)


def test_too_short_a_lap_is_not_compared():
    tiny = LapTrace(1, [0.0, 1.0], [0.0, 1.0], [2, 2], [0, 1], 100)
    assert compare(tiny, lap(2, 60_000)) is None
    assert compare(lap(2, 60_000), tiny) is None


def test_bucketing_keeps_the_time_it_thins():
    reference = lap(1, 60_000)
    slower = calibrated(reference, lap(2, 0, slow=(200, 275), factor=3.0))
    result = compare(slower, reference)
    xs, zs, deltas = bucket(slower, result, target_points=200)
    assert len(xs) == len(zs) == len(deltas) < len(slower)
    # Thinning must not lose time; rounding costs a fraction of a millisecond.
    assert sum(deltas) == pytest.approx(result.total_ms, abs=len(deltas) * 0.005 + 0.5)


def test_the_reference_is_the_best_lap_and_updates():
    # Numbered from 2: lap 1 is the out-lap and is never counted.
    tracker = DeltaTracker()
    assert tracker.add_lap(lap(2, 60_000)) is None      # nothing to compare to
    assert tracker.reference.number == 2

    slower = tracker.add_lap(lap(3, 62_000))
    assert slower.reference_number == 2
    assert tracker.reference.number == 2                # 62s does not displace 60s

    quicker = tracker.add_lap(lap(4, 58_000))
    # Compared against what it beat, not against itself.
    assert quicker.reference_number == 2
    assert tracker.reference.number == 4


def test_a_lap_without_a_time_never_becomes_the_reference():
    tracker = DeltaTracker()
    tracker.add_lap(lap(2, 60_000))
    tracker.add_lap(lap(3, -1))          # GT7 reports -1 when it has no time
    assert tracker.reference.number == 2


# ---- the opening lap -------------------------------------------------------


def short_lap(number: int, lap_ms: int, points: int) -> LapTrace:
    """A lap that covers only part of the circuit, as a grid lap does."""
    xs, zs, inputs, ticks = [], [], [], []
    for i in range(points):
        angle = 2 * math.pi * i / N
        xs.append(RADIUS * math.cos(angle))
        zs.append(RADIUS * math.sin(angle))
        inputs.append(2)
        ticks.append(i)
    return LapTrace(number, xs, zs, inputs, ticks, lap_ms)


def test_the_opening_lap_never_becomes_the_reference():
    """A grid lap is short, so it would win on time and poison every delta."""
    tracker = DeltaTracker()
    assert tracker.add_lap(short_lap(1, 45_000, 450)) is None
    assert tracker.reference is None
    assert tracker.latest is None

    tracker.add_lap(lap(2, 60_000))
    assert tracker.reference.number == 2

    result = tracker.add_lap(lap(3, 60_500))
    assert result.reference_number == 2
    assert result.total_ms == pytest.approx(500, rel=0.1)


def test_the_opening_lap_is_not_drawn_either():
    """Its geometry stops at the line but starts on the grid: a partial lap."""
    tracker = DeltaTracker()
    tracker.add_lap(short_lap(1, 45_000, 450))
    assert tracker.latest is None


def test_is_out_lap_boundary():
    from gt7.delta import is_out_lap

    assert is_out_lap(0) is True
    assert is_out_lap(1) is True
    assert is_out_lap(2) is False
