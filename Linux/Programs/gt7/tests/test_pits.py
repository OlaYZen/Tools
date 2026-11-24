"""Pit detection. GT7 reports none of this, so it is inferred."""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path

import pytest

from gt7 import recorder
from gt7.packet import Telemetry, decode
from gt7.pits import PIT_MAX_KPH, PitDetector

FIXTURE = Path(__file__).parent / "fixtures" / "format_a.bin"
RADIUS = 400.0


@pytest.fixture(scope="module")
def base() -> Telemetry:
    return decode(next(iter(recorder.read(FIXTURE)))[1])


def on_racing_line(x: float, z: float) -> bool:
    return abs(math.hypot(x, z) - RADIUS) < 25.0


class Session:
    """Feeds frames at 60 Hz with a wall clock the test controls.

    The car is moved at the speed it reports. That is not decoration: the
    detector cross-checks the two, because a paused GT7 keeps streaming a
    frozen snapshot whose speed is perfectly steady.
    """

    def __init__(self, base: Telemetry, on_line=on_racing_line):
        self.base = base
        self.detector = PitDetector(on_line=on_line)
        self.now = 0.0

    def run(self, seconds: float, *, x: float, z: float, kph: float,
            rpm: float = 3300.0, lap: int = 3, jitter: float = 0.0) -> None:
        """Travel in a straight line from (x, z), covering ground at `kph`."""
        step = (kph / 3.6) / 60
        for i in range(int(seconds * 60)):
            speed = kph + (jitter if i % 2 else -jitter)
            self.detector.feed(dataclasses.replace(
                self.base, position=(x, 0.0, z + step * i), speed_mps=speed / 3.6,
                rpm=rpm, current_lap=lap), self.now)
            self.now += 1 / 60

    def stand(self, seconds: float, *, x: float, z: float, lap: int = 3) -> None:
        """Sit still, as a car does during the stop itself."""
        for _ in range(int(seconds * 60)):
            self.detector.feed(dataclasses.replace(
                self.base, position=(x, 0.0, z), speed_mps=0.0, rpm=900.0,
                current_lap=lap), self.now)
            self.now += 1 / 60

    def lap_wobbling(self, seconds: float, kph: float, jitter: float,
                     rpm: float = 7200.0, lap: int = 3) -> None:
        """Drive the racing line at a speed held only as well as a human can."""
        angle = 0.0
        step = ((kph / 3.6) / 60) / RADIUS
        for i in range(int(seconds * 60)):
            speed = kph + (jitter if i % 2 else -jitter)
            self.detector.feed(dataclasses.replace(
                self.base, position=(RADIUS * math.cos(angle), 0.0,
                                     RADIUS * math.sin(angle)),
                speed_mps=speed / 3.6, rpm=rpm, current_lap=lap), self.now)
            angle += step
            self.now += 1 / 60

    def lap(self, seconds: float, kph: float, rpm: float = 7200.0,
            lap: int = 3) -> None:
        """Drive along the racing line at `kph`, covering the right ground."""
        angle = 0.0
        step = ((kph / 3.6) / 60) / RADIUS
        for _ in range(int(seconds * 60)):
            self.detector.feed(dataclasses.replace(
                self.base, position=(RADIUS * math.cos(angle), 0.0,
                                     RADIUS * math.sin(angle)),
                speed_mps=kph / 3.6, rpm=rpm, current_lap=lap), self.now)
            angle += step
            self.now += 1 / 60


def test_racing_is_not_a_pit_stop(base):
    session = Session(base)
    session.lap(10.0, 240.0)
    assert session.detector.in_pits is False
    assert session.detector.stop_count == 0


def test_a_drag_limited_straight_is_not_a_pit_stop(base):
    """Flat out, speed plateaus too - the ceiling is what separates them."""
    session = Session(base)
    session.run(8.0, x=RADIUS, z=0.0, kph=330.0, rpm=7800.0, jitter=0.2)
    assert session.detector.in_pits is False


def test_the_limiter_off_the_racing_line_is_a_pit_stop(base):
    session = Session(base)
    session.run(5.0, x=RADIUS - 60, z=0.0, kph=74.0, jitter=0.2)
    assert session.detector.in_pits is True
    assert session.detector.stop_count == 1
    # The limit is measured, not assumed: it varies by circuit and series.
    assert session.detector.limit_kph == pytest.approx(74.0, abs=0.5)


def test_the_limiter_speed_is_learned_whatever_it_is(base):
    for limit in (50.0, 60.0, 80.0):
        session = Session(base)
        session.run(5.0, x=RADIUS - 60, z=0.0, kph=limit, jitter=0.2)
        assert session.detector.limit_kph == pytest.approx(limit, abs=0.5)


def test_crawling_under_caution_is_not_a_pit_stop(base):
    """A driver holding a slow speed by hand cannot hold it like a limiter.

    Position used to rule this out, but a pit lane can run a wall's width from
    the racing line, so geometry cannot be allowed to veto. What separates them
    is that a limiter is electronically exact and a human is not.
    """
    session = Session(base)
    session.lap_wobbling(8.0, 60.0, jitter=3.0, rpm=3000.0)
    assert session.detector.in_pits is False
    assert "varying" in session.detector.blocked_by


def test_a_stationary_car_is_still_in_the_pits(base):
    """Exit is judged on getting back to racing, not on the limiter ending."""
    session = Session(base)
    session.run(5.0, x=RADIUS - 60, z=0.0, kph=74.0, jitter=0.2)
    assert session.detector.in_pits is True
    session.stand(12.0, x=RADIUS - 60, z=0.0)
    assert session.detector.in_pits is True
    assert session.detector.current.stationary_s == pytest.approx(12.0, abs=0.5)


def test_leaving_the_pits_closes_the_stop(base):
    session = Session(base)
    session.run(5.0, x=RADIUS - 60, z=0.0, kph=74.0, jitter=0.2)
    session.stand(10.0, x=RADIUS - 60, z=0.0)
    session.lap(5.0, 200.0)
    detector = session.detector
    assert detector.in_pits is False
    assert detector.stop_count == 1
    stop = detector.last_completed
    assert stop.lap == 3
    assert stop.duration_s == pytest.approx(15.0, abs=1.0)
    assert stop.stationary_s == pytest.approx(10.0, abs=0.5)


def test_a_brief_slow_moment_is_not_a_stop(base):
    """The hold is what stops a moment of steady throttle triggering it."""
    session = Session(base)
    session.run(1.5, x=RADIUS - 60, z=0.0, kph=74.0, jitter=0.2)
    assert session.detector.in_pits is False


def test_wobbling_speed_is_not_a_limiter(base):
    """A driver cannot hold a speed the way a limiter does."""
    session = Session(base)
    session.run(8.0, x=RADIUS - 60, z=0.0, kph=74.0, jitter=4.0)
    assert session.detector.in_pits is False


def test_without_a_recognised_circuit_speed_has_to_stand_alone(base):
    session = Session(base, on_line=lambda x, z: None)
    session.run(5.0, x=0.0, z=0.0, kph=74.0, jitter=0.2)
    assert session.detector.in_pits is True
    assert "speed only" in session.detector.confidence


def test_confidence_reports_whether_position_was_used(base):
    session = Session(base)
    session.run(5.0, x=RADIUS - 60, z=0.0, kph=74.0, jitter=0.2)
    assert session.detector.confidence == "speed and position"


def test_a_lap_with_a_stop_is_flagged(base):
    session = Session(base)
    session.run(5.0, x=RADIUS - 60, z=0.0, kph=74.0, jitter=0.2, lap=7)
    assert session.detector.lap_had_a_stop(7) is True
    assert session.detector.lap_had_a_stop(6) is False


def test_changing_car_clears_the_stops(base):
    session = Session(base)
    session.run(5.0, x=RADIUS - 60, z=0.0, kph=74.0, jitter=0.2)
    assert session.detector.stop_count == 1
    session.detector.feed(dataclasses.replace(base, car_code=base.car_code + 1),
                          session.now)
    assert session.detector.stop_count == 0
    assert session.detector.in_pits is False


def test_callouts_say_what_is_happening(base):
    session = Session(base)
    session.run(5.0, x=RADIUS - 60, z=0.0, kph=74.0, jitter=0.2)
    calls = session.detector.callouts(session.now)
    assert [c.key for c in calls] == ["pit-in"]
    assert "pit lane" in calls[0].message.lower()

    session.stand(10.0, x=RADIUS - 60, z=0.0)
    session.lap(5.0, 200.0)
    calls = session.detector.callouts(session.now)
    assert [c.key for c in calls] == ["pit-out"]
    assert "seconds" in calls[0].message


def test_pit_max_is_below_racing_speed():
    assert PIT_MAX_KPH < 150


def test_a_paused_game_is_not_a_pit_stop(base):
    """GT7 streams a frozen snapshot at 60 Hz while paused.

    Perfectly steady speed, off the racing line, held indefinitely - the
    tidiest pit stop imaginable, and entirely fictional. The PAUSED flag
    cannot catch it either: it was measured False with the game plainly
    paused. What gives it away is that the car covers no ground.
    """
    detector = PitDetector(on_line=lambda x, z: False)
    now = 0.0
    for _ in range(int(8 * 60)):
        detector.feed(dataclasses.replace(
            base, position=(1000.0, 0.0, 1000.0), speed_mps=74.0 / 3.6,
            rpm=3300.0, current_lap=3), now)
        now += 1 / 60
    assert detector.in_pits is False
    assert detector.stop_count == 0


def test_speed_must_agree_with_ground_covered(base):
    """Half speed for the distance is still a stalled stream, not a limiter."""
    detector = PitDetector(on_line=lambda x, z: False)
    now = 0.0
    creep = (74.0 / 3.6) / 60 * 0.2          # moving at a fifth of the claim
    for i in range(int(8 * 60)):
        detector.feed(dataclasses.replace(
            base, position=(1000.0, 0.0, 1000.0 + creep * i),
            speed_mps=74.0 / 3.6, rpm=3300.0, current_lap=3), now)
        now += 1 / 60
    assert detector.in_pits is False


# ---- the pit road on the map ----------------------------------------------


def test_the_lane_is_recorded_as_a_path(base):
    session = Session(base)
    session.run(8.0, x=RADIUS - 60, z=0.0, kph=74.0, jitter=0.2)
    stop = session.detector.current
    assert stop is not None
    assert len(stop.path) > 10
    # Spaced out, not one point per frame.
    assert len(stop.path) < 8.0 * 60


def test_the_lane_includes_the_entry_before_detection(base):
    """The limiter must hold for seconds first, by which point the car is well
    down the lane. A pit road drawn from halfway along is worse than none."""
    session = Session(base)
    session.run(8.0, x=RADIUS - 60, z=0.0, kph=74.0, jitter=0.2)
    first = session.detector.current.path[0]
    assert first[1] < 5.0            # back at the entry, not 60 m in


def test_standing_still_does_not_flood_the_lane(base):
    session = Session(base)
    session.run(5.0, x=RADIUS - 60, z=0.0, kph=74.0, jitter=0.2)
    before = len(session.detector.current.path)
    session.stand(20.0, x=RADIUS - 60, z=100.0)
    after = len(session.detector.current.path)
    assert after - before <= 2


def test_the_lane_is_attached_to_the_recognised_circuit(tmp_path, base):
    import math as _math

    from gt7.library import TrackLibrary

    library = TrackLibrary(tmp_path / "tracks.json", autoload=False)
    xs = [RADIUS * _math.cos(2 * _math.pi * i / 400) for i in range(400)]
    zs = [RADIUS * _math.sin(2 * _math.pi * i / 400) for i in range(400)]
    saved = library.remember(xs, zs, [2] * 400, 2 * _math.pi * RADIUS)
    assert saved.pit_lane == []

    lane = [(RADIUS - 60, z * 4.0) for z in range(40)]
    assert library.remember_pit_lane(saved.id, lane) is True
    assert len(saved.pit_lane) == 40

    # A shorter traversal must not replace a fuller one.
    assert library.remember_pit_lane(saved.id, lane[:10]) is False
    assert len(saved.pit_lane) == 40

    # And it survives a reload.
    library.persist()
    reloaded = TrackLibrary(tmp_path / "tracks.json")
    assert len(reloaded.tracks[0].pit_lane) == 40


def test_a_scrap_of_a_lane_is_not_stored(tmp_path, base):
    import math as _math

    from gt7.library import TrackLibrary

    library = TrackLibrary(tmp_path / "tracks.json", autoload=False)
    xs = [RADIUS * _math.cos(2 * _math.pi * i / 400) for i in range(400)]
    zs = [RADIUS * _math.sin(2 * _math.pi * i / 400) for i in range(400)]
    saved = library.remember(xs, zs, [2] * 400, 2 * _math.pi * RADIUS)
    assert library.remember_pit_lane(saved.id, [(0.0, 0.0), (1.0, 1.0)]) is False
    assert saved.pit_lane == []


def test_detection_does_not_depend_on_the_arrival_rate(base):
    """The window is bounded by time, not by an assumed 60 Hz frame rate."""
    for rate in (30, 60, 120, 240):
        detector = PitDetector(on_line=lambda x, z: False)
        now = 0.0
        step = (74.0 / 3.6) / rate
        for i in range(int(6 * rate)):
            detector.feed(dataclasses.replace(
                base, position=(340.0, 0.0, step * i), speed_mps=74.0 / 3.6,
                rpm=3300.0, current_lap=3), now)
            now += 1 / rate
        assert detector.in_pits is True, f"missed the stop at {rate} Hz"


def test_the_backfill_cannot_drag_in_whole_laps(base):
    """Only the frames that proved the limiter are recovered, not the buffer.

    The window is bounded by time, so a caller feeding faster than real time
    can hold minutes of history in it; taking all of that as the pit road put
    2400 racing-line points into a lane that should have had eighty.
    """
    detector = PitDetector(on_line=lambda x, z: False)
    now = 0.0
    # Several laps of racing fed with the clock barely advancing, as happens
    # when a test or a replay pushes frames faster than 60 Hz.
    for i in range(2400):
        angle = 2 * math.pi * i / 600
        detector.feed(dataclasses.replace(
            base, position=(RADIUS * math.cos(angle), 0.0, RADIUS * math.sin(angle)),
            speed_mps=220 / 3.6, rpm=7200.0, current_lap=2), now)
        now += 1 / 6000
    # Then a real-time pit stop.
    step = (74.0 / 3.6) / 60
    for i in range(int(6 * 60)):
        detector.feed(dataclasses.replace(
            base, position=(340.0, 0.0, step * i), speed_mps=74.0 / 3.6,
            rpm=3300.0, current_lap=3), now)
        now += 1 / 60
    assert detector.in_pits is True
    assert len(detector.current.path) < 200


# ---- how close is "on the racing line" ------------------------------------


def test_a_lane_beside_the_track_is_still_a_pit_stop(base):
    """A pit lane runs 10-20 m from the racing line, not 30.

    Borrowing the circuit-matching tolerance (25 m) for this decision declared
    such a lane to be "on track" and vetoed the stop - a Super Formula car
    sitting on its limiter went undetected because of it.
    """
    from gt7.pits import ON_LINE_METRES

    assert ON_LINE_METRES < 15.0, "must be tighter than a pit lane's offset"

    for offset in (12.0, 15.0, 20.0, 25.0):
        detector = PitDetector(
            on_line=lambda x, z, o=offset: abs(math.hypot(x, z) - RADIUS) < ON_LINE_METRES)
        now = 0.0
        step = (80.0 / 3.6) / 60
        for i in range(int(6 * 60)):
            angle = step * i / (RADIUS - offset)
            r = RADIUS - offset
            detector.feed(dataclasses.replace(
                base, position=(r * math.cos(angle), 0.0, r * math.sin(angle)),
                speed_mps=80.0 / 3.6, rpm=9000.0, current_lap=3), now)
            now += 1 / 60
        assert detector.in_pits is True, f"missed a lane {offset} m from the line"


def test_a_perfectly_steady_speed_on_the_line_reads_as_a_stop(base):
    """The known limit of this approach, asserted rather than hidden.

    A car holding a speed to within a fraction of a km/h *on* the racing line
    is indistinguishable from one doing it in a lane beside the racing line -
    the signals are identical. Since pit lanes can run right against the
    track, the detector believes the limiter and reports reduced confidence
    rather than refusing the stop.
    """
    session = Session(base)
    session.lap(8.0, 80.0, rpm=3000.0)
    assert session.detector.in_pits is True
    assert "beside the racing line" in session.detector.confidence


def test_high_rpm_is_irrelevant(base):
    """RPM is recorded but never gates detection - a formula car revs hard."""
    detector = PitDetector(on_line=lambda x, z: False)
    now = 0.0
    step = (80.0 / 3.6) / 60
    for i in range(int(6 * 60)):
        detector.feed(dataclasses.replace(
            base, position=(340.0, 0.0, step * i), speed_mps=80.0 / 3.6,
            rpm=12_000.0, current_lap=3), now)
        now += 1 / 60
    assert detector.in_pits is True
    assert detector.limit_kph == pytest.approx(80.0, abs=0.5)


def test_a_missed_stop_says_why(base):
    """Wobbling speed should name itself, not fail silently."""
    session = Session(base)
    session.run(8.0, x=RADIUS - 60, z=0.0, kph=80.0, jitter=4.0)
    assert session.detector.in_pits is False
    assert session.detector.blocked_by is not None
    assert "varying" in session.detector.blocked_by
    assert session.detector.spread_kph > 1.5


def test_a_lane_hard_against_the_racing_line_is_detected(base):
    """Some pit lanes are a wall's width from the track, not a field away."""
    for offset in (3.0, 5.0, 8.0, 12.0, 25.0, 60.0):
        detector = PitDetector(
            on_line=lambda x, z: abs(math.hypot(x, z) - RADIUS) < 8.0)
        now = 0.0
        radius = RADIUS - offset
        step = ((80.0 / 3.6) / 60) / radius
        angle = 0.0
        for _ in range(int(6 * 60)):
            detector.feed(dataclasses.replace(
                base, position=(radius * math.cos(angle), 0.0,
                                radius * math.sin(angle)),
                speed_mps=80.0 / 3.6, rpm=11_000.0, current_lap=3), now)
            angle += step
            now += 1 / 60
        assert detector.in_pits is True, f"missed a lane {offset} m from the line"


def test_confidence_says_when_position_could_not_help(base):
    detector = PitDetector(on_line=lambda x, z: True)      # lane beside the track
    now = 0.0
    step = (80.0 / 3.6) / 60
    for i in range(int(6 * 60)):
        detector.feed(dataclasses.replace(
            base, position=(340.0, 0.0, step * i), speed_mps=80.0 / 3.6,
            rpm=11_000.0, current_lap=3), now)
        now += 1 / 60
    assert detector.in_pits is True
    assert "beside the racing line" in detector.confidence


def test_position_still_raises_confidence_when_it_can(base):
    detector = PitDetector(on_line=lambda x, z: False)     # clearly off the line
    now = 0.0
    step = (80.0 / 3.6) / 60
    for i in range(int(6 * 60)):
        detector.feed(dataclasses.replace(
            base, position=(340.0, 0.0, step * i), speed_mps=80.0 / 3.6,
            rpm=11_000.0, current_lap=3), now)
        now += 1 / 60
    assert detector.confidence == "speed and position"


def test_leaving_at_racing_speed_ends_the_stop_wherever_the_car_is(base):
    """Exit cannot depend on position either.

    The stored outline is one lap's line, so a car racing on a different line
    reads as "off the line" and used to stay flagged in the pits - observed
    live at 148 km/h a minute after leaving, all the while recording the
    racing line into the pit lane.
    """
    detector = PitDetector(on_line=lambda x, z: False)   # never on the line
    now = 0.0
    step = (80.0 / 3.6) / 60
    for i in range(int(6 * 60)):
        detector.feed(dataclasses.replace(
            base, position=(340.0, 0.0, step * i), speed_mps=80.0 / 3.6,
            rpm=11_000.0, current_lap=3), now)
        now += 1 / 60
    assert detector.in_pits is True
    lane_at_exit = len(detector.current.path)

    fast = (200.0 / 3.6) / 60
    z = step * 6 * 60
    for i in range(int(5 * 60)):
        detector.feed(dataclasses.replace(
            base, position=(340.0, 0.0, z + fast * i), speed_mps=200.0 / 3.6,
            rpm=9000.0, current_lap=3), now)
        now += 1 / 60
    assert detector.in_pits is False
    stop = detector.last_completed
    assert stop is not None and stop.duration_s is not None
    # And the lane stopped growing the moment the stop closed.
    assert len(stop.path) < lane_at_exit + 40


def test_a_lane_longer_than_the_lap_is_refused(tmp_path):
    """A stop that failed to close records racing line as pit road."""
    import math as _math

    from gt7.library import TrackLibrary

    library = TrackLibrary(tmp_path / "tracks.json", autoload=False)
    xs = [400 * _math.cos(2 * _math.pi * i / 400) for i in range(400)]
    zs = [400 * _math.sin(2 * _math.pi * i / 400) for i in range(400)]
    saved = library.remember(xs, zs, [2] * 400, 2 * _math.pi * 400)

    sane = [(340.0, z * 4.0) for z in range(40)]
    assert library.remember_pit_lane(saved.id, sane) is True

    # 2 km of "lane" against a 2.5 km lap: that is a lap, not a pit road.
    runaway = [(340.0, z * 4.0) for z in range(500)]
    assert library.remember_pit_lane(saved.id, runaway) is False
    assert len(saved.pit_lane) == 40


# ---- the rolling start ------------------------------------------------------


def test_a_rolling_start_is_not_a_pit_stop(base):
    """Almost every GT7 race begins with the field held at one speed.

    That is a limiter - it is steady to a fraction of a km/h, it sits inside
    the pit band and the car covers the ground to match - so every speed test
    here agrees with it. Only the lap number says otherwise, and it opened a
    fictional stop on the grid at the start of nearly every race.
    """
    for lap in (0, 1):
        session = Session(base)
        session.run(12.0, x=RADIUS - 60, z=0.0, kph=70.0, jitter=0.2, lap=lap)
        assert session.detector.in_pits is False, f"opened a stop on lap {lap}"
        assert session.detector.stop_count == 0
        assert "out-lap" in session.detector.blocked_by


def test_a_rolling_start_records_no_pit_lane(base):
    """The lane is backfilled from before detection, so a stop opened on the
    formation lap wrote the first 250 m of the racing line into the library as
    pit road.
    """
    session = Session(base)
    session.lap(12.0, 70.0, rpm=3000.0, lap=1)
    assert session.detector.stops == []


def test_the_out_lap_guard_does_not_wedge_the_detector(base):
    """Refusing the opening lap must not cost the real stop that follows."""
    session = Session(base)
    session.run(12.0, x=RADIUS - 60, z=0.0, kph=70.0, jitter=0.2, lap=1)
    session.lap(20.0, 220.0, lap=2)
    session.run(5.0, x=RADIUS - 60, z=0.0, kph=74.0, jitter=0.2, lap=2)
    assert session.detector.in_pits is True
    assert session.detector.stop_count == 1
    assert session.detector.current.lap == 2
