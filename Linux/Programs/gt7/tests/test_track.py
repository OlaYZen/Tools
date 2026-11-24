"""Track mapping tests. Geometry is checked against shapes with known answers."""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path

import pytest

from gt7 import recorder
from gt7.packet import Telemetry, decode
from gt7.track import JUMP, MAX_POINTS, MIN_MOVE, Input, TrackMap, classify

FIXTURE = Path(__file__).parent / "fixtures" / "format_a.bin"


@pytest.fixture(scope="module")
def base() -> Telemetry:
    return decode(next(iter(recorder.read(FIXTURE)))[1])


def at(base: Telemetry, x: float, z: float, *, throttle: int = 250,
       brake: int = 0, lap: int = 1) -> Telemetry:
    return dataclasses.replace(base, position=(x, 0.0, z), current_lap=lap,
                               throttle=throttle, brake=brake)


def drive_circle(base: Telemetry, radius: float, steps: int,
                 revolutions: float = 1.0, lap: int = 1) -> TrackMap:
    track = TrackMap()
    total = int(steps * revolutions)
    for i in range(total + 1):
        angle = 2 * math.pi * i / steps
        track.feed(at(base, radius * math.cos(angle), radius * math.sin(angle),
                      lap=lap))
    return track


def drive_laps(base: Telemetry, track: TrackMap, radius: float, steps: int,
               lap: int, start: int = 0, count: int | None = None) -> None:
    """Drive part or all of one lap of a circle, tagged with a lap number."""
    for i in range(start, start + (steps if count is None else count)):
        angle = 2 * math.pi * i / steps
        track.feed(at(base, radius * math.cos(angle), radius * math.sin(angle),
                      lap=lap))


def test_classify_prefers_braking_over_overlapping_throttle():
    # Trail braking shows both pedals; the car is still slowing.
    assert classify(0.9, 0.5) is Input.BRAKE
    assert classify(0.9, 0.0) is Input.THROTTLE
    assert classify(0.2, 0.0) is Input.PARTIAL
    assert classify(0.0, 0.0) is Input.COAST


def test_trace_measures_a_known_circumference(base):
    radius = 300.0
    track = drive_circle(base, radius, 900)
    assert track.length == pytest.approx(2 * math.pi * radius, rel=0.01)
    assert track.bbox == pytest.approx((-radius, -radius, radius, radius), abs=1.0)


def test_geometry_alone_does_not_make_a_circuit(base):
    """Returning near the start is not proof of a lap - GT7's counter is."""
    assert drive_circle(base, 300.0, 900).closed is False


def test_a_lap_measured_line_to_line_becomes_the_outline(base):
    radius, steps = 300.0, 900
    track = TrackMap()
    # Attach a third of the way into lap 5, then run laps 6 and 7 in full.
    drive_laps(base, track, radius, steps, lap=5, start=300, count=600)
    assert track.closed is False
    assert track.anchored is False

    drive_laps(base, track, radius, steps, lap=6)
    assert track.anchored is True      # crossed the line, trace restarted
    assert track.closed is False       # but no complete lap published yet

    drive_laps(base, track, radius, steps, lap=7)
    assert track.closed is True
    assert track.lap_number == 6
    assert track.length == pytest.approx(2 * math.pi * radius, rel=0.01)


def test_the_outline_starts_on_the_start_finish_line(base):
    radius, steps = 300.0, 900
    track = TrackMap()
    # Attach mid-corner, well away from the line at angle 0.
    drive_laps(base, track, radius, steps, lap=5, start=300, count=600)
    drive_laps(base, track, radius, steps, lap=6)
    drive_laps(base, track, radius, steps, lap=7)

    angle = math.degrees(math.atan2(track.zs[0], track.xs[0]))
    assert angle == pytest.approx(0.0, abs=2.0)   # the line, not where we joined


def test_each_new_lap_replaces_the_outline(base):
    radius, steps = 300.0, 900
    track = TrackMap()
    drive_laps(base, track, radius, steps, lap=1)
    drive_laps(base, track, radius, steps, lap=2)
    drive_laps(base, track, radius, steps, lap=3)
    assert track.lap_number == 2
    generation = track.generation

    drive_laps(base, track, radius, steps, lap=4)
    assert track.lap_number == 3
    assert track.generation > generation   # clients must discard and redraw


def test_a_stub_lap_is_not_published_as_the_circuit(base):
    """A counter that ticks twice in seconds must not publish a fragment."""
    track = TrackMap()
    for lap in (1, 2, 3):
        for i in range(10):
            track.feed(at(base, i * 5.0, 0.0, lap=lap))   # only ~45 m
    assert track.closed is False


def test_a_straight_line_is_not_a_circuit(base):
    track = TrackMap()
    for i in range(400):
        track.feed(at(base, i * 5.0, 0.0))
    assert track.closed is False
    assert track.length == pytest.approx(399 * 5.0, rel=0.01)


def test_crawling_does_not_clutter_the_trace(base):
    track = TrackMap()
    for i in range(500):
        track.feed(at(base, i * (MIN_MOVE / 10), 0.0))  # ten times too fine
    # Points land on the sampling grid, not on every frame.
    assert len(track.xs) < 60


def test_a_teleport_starts_a_fresh_trace(base):
    track = TrackMap()
    for i in range(100):
        track.feed(at(base, i * 5.0, 0.0))
    generation = track.generation
    length = track.length
    assert length > 0

    track.feed(at(base, 5.0 + JUMP * 10, 0.0))
    assert track.generation == generation + 1
    assert track.length == 0.0
    assert len(track.xs) == 1
    assert track.closed is False


def test_changing_car_starts_a_fresh_trace(base):
    track = TrackMap()
    for i in range(100):
        track.feed(at(base, i * 5.0, 0.0))
    generation = track.generation
    track.feed(dataclasses.replace(at(base, 0.0, 0.0), car_code=base.car_code + 1))
    assert track.generation > generation
    assert len(track.xs) == 1


def test_inputs_are_recorded_along_the_trace(base):
    track = TrackMap()
    for i in range(60):
        braking = i % 2 == 0
        track.feed(at(base, i * 5.0, 0.0,
                      throttle=0 if braking else 250,
                      brake=200 if braking else 0))
    assert set(track.inputs) == {int(Input.BRAKE), int(Input.THROTTLE)}


def test_cursor_returns_only_new_points(base):
    track = TrackMap()
    for i in range(50):
        track.feed(at(base, i * 5.0, 0.0))
    cursor, xs, zs, inputs = track.since(0)
    assert len(xs) == len(zs) == len(inputs) == 50
    assert cursor == 50

    # Nothing new yet.
    cursor2, xs2, _, _ = track.since(cursor)
    assert xs2 == []
    assert cursor2 == cursor

    for i in range(50, 60):
        track.feed(at(base, i * 5.0, 0.0))
    _, xs3, _, _ = track.since(cursor)
    assert len(xs3) == 10


def test_the_ring_cap_does_not_break_cursors(base):
    """Once old points are evicted a stale cursor must not resend or skip."""
    track = TrackMap()
    for i in range(MAX_POINTS + 200):
        track.feed(at(base, i * (MIN_MOVE + 1), 0.0))
    assert len(track.xs) == MAX_POINTS
    assert track.total_points == MAX_POINTS + 200

    # A cursor pointing at long-evicted points yields what is still held,
    # never a negative slice or a crash.
    cursor, xs, _, _ = track.since(0)
    assert len(xs) == MAX_POINTS
    assert cursor == track.total_points
    _, empty, _, _ = track.since(cursor)
    assert empty == []


def test_empty_map_has_no_bbox():
    track = TrackMap()
    assert track.bbox is None
    assert track.since(0) == (0, [], [], [])


def test_the_opening_lap_is_not_published_as_the_circuit(base):
    """A race's lap 1 starts on the grid, so it traces less than a circuit."""
    radius, steps = 300.0, 900
    track = TrackMap()
    # Sitting on the grid before the lights, then racing laps 1, 2 and 3.
    drive_laps(base, track, radius, steps, lap=0, count=10)
    drive_laps(base, track, radius, steps, lap=1)
    drive_laps(base, track, radius, steps, lap=2)
    assert track.closed is False          # lap 1 must not become the outline
    assert track.last_lap is None

    drive_laps(base, track, radius, steps, lap=3)
    assert track.closed is True
    assert track.lap_number == 2          # the first lap that counts
    assert track.last_lap.number == 2
