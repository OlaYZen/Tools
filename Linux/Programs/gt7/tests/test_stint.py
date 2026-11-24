"""Stint tracking and callout tests, driven by a synthetic race."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from gt7 import recorder
from gt7.packet import Telemetry, decode
from gt7.stint import StintTracker

FIXTURE = Path(__file__).parent / "fixtures" / "format_a.bin"
FRAMES_PER_LAP = 60


@pytest.fixture(scope="module")
def base() -> Telemetry:
    return decode(next(iter(recorder.read(FIXTURE)))[1])


def race(base: Telemetry, *, laps: int = 8, total_laps: int = 20,
         burn: float = 2.5, start_fuel: float = 40.0,
         lap_ms: int = 103_000, degrade: int = 0,
         rear_climb: float = 0.0, spin: bool = False) -> StintTracker:
    """Run a synthetic stint through the tracker."""
    tracker = StintTracker()
    now, fuel = 0.0, start_fuel
    for lap in range(1, laps + 1):
        for _ in range(FRAMES_PER_LAP):
            rear = 70 + lap * rear_climb
            frame = dataclasses.replace(
                base,
                current_lap=lap, total_laps=total_laps,
                last_lap_ms=(lap_ms + (lap - 2) * degrade) if lap > 1 else -1,
                fuel_level=max(fuel, 0.0), fuel_capacity=100.0,
                speed_mps=60.0, throttle=250 if spin else 10, brake=0,
                tyre_temp=(70.0, 72.0, rear, rear + 2),
                wheel_radps=(180.0, 180.0, 200.0 if spin else 180.0, 200.0 if spin else 180.0),
                tyre_radius=(0.33, 0.33, 0.33, 0.33),
            )
            tracker.feed(frame, now)
            now += 1 / 60
            fuel -= burn / FRAMES_PER_LAP
    return tracker


def test_lap_boundaries_close_one_lap_each(base):
    tracker = race(base, laps=8)
    # A record belongs to the lap that just *finished*. Seeing laps 1..8 on the
    # counter therefore yields records for 2..7: lap 1 is dropped because the
    # tracker cannot know it joined at its start rather than half-way through,
    # and lap 8 is still running.
    assert [lap.number for lap in tracker.laps] == list(range(2, 8))
    assert tracker.lap_number == 8


def test_fuel_burn_and_projection(base):
    tracker = race(base, laps=8, burn=2.5, start_fuel=40.0, total_laps=20)
    assert tracker.fuel_per_lap == pytest.approx(2.5, abs=0.05)
    # 8 laps burned from 40 L leaves 20 L -> 8 laps of fuel.
    assert tracker.laps_of_fuel == pytest.approx(8.0, abs=0.2)
    assert tracker.laps_to_go == 20 - 8 + 1
    assert tracker.fuel_margin == pytest.approx(8.0 - 13, abs=0.3)


def test_fuel_shortfall_produces_a_savings_target(base):
    tracker = race(base, laps=8, burn=2.5, start_fuel=40.0, total_laps=20)
    call = next(c for c in tracker.callouts() if c.key == "fuel-short")
    assert call.severity == "warn"
    assert "Save" in call.message and "to go" in call.message


def test_plenty_of_fuel_is_reported_as_good(base):
    tracker = race(base, laps=5, burn=0.5, start_fuel=90.0, total_laps=8)
    keys = {c.key for c in tracker.callouts()}
    assert "fuel-ok" in keys
    assert "fuel-short" not in keys


def test_critical_fuel_says_box_this_lap(base):
    tracker = race(base, laps=6, burn=5.0, start_fuel=32.0, total_laps=40)
    call = next(c for c in tracker.callouts() if c.key == "fuel-critical")
    assert call.severity == "critical"
    assert "Box" in call.message


def test_refuelling_discards_the_stale_burn_rate(base):
    tracker = race(base, laps=4, burn=2.5, start_fuel=40.0)
    assert tracker.fuel_per_lap is not None
    # A lap where fuel went up must not be averaged in as a negative burn.
    refuel = dataclasses.replace(tracker._latest, current_lap=99, fuel_level=90.0,
                                 last_lap_ms=103_000)
    tracker.feed(refuel, 1000.0)
    assert tracker.fuel_per_lap is None


def test_rear_overheating_is_called(base):
    tracker = race(base, laps=8, rear_climb=3.0)
    call = next(c for c in tracker.callouts() if c.key == "tyre-rear-hot")
    assert "Rears" in call.message
    assert tracker.tyre_balance["front_rear"] > 12


def test_balanced_tyres_produce_no_tyre_callout(base):
    tracker = race(base, laps=6, rear_climb=0.0)
    assert not [c for c in tracker.callouts() if c.key.startswith("tyre-")
                and c.key != "tyre-cold"]


def test_wheelspin_is_counted_as_events_not_frames(base):
    tracker = race(base, laps=4, spin=True)
    lap = tracker.laps[-1]
    # Sixty frames of continuous slip is one event, not sixty.
    assert lap.wheelspin == 1


def test_pace_degradation_shows_in_the_trend(base):
    tracker = race(base, laps=9, degrade=400)
    assert tracker.pace_trend_ms is not None
    assert tracker.pace_trend_ms > 0
    assert tracker.best_lap_ms == min(lap.time_ms for lap in tracker.laps)


def test_consistency_needs_three_laps(base):
    assert race(base, laps=3).consistency_ms is None
    assert race(base, laps=6).consistency_ms is not None


def test_a_new_car_resets_the_stint(base):
    tracker = race(base, laps=6)
    assert tracker.laps
    tracker.feed(dataclasses.replace(base, car_code=base.car_code + 1, current_lap=1), 9999.0)
    assert tracker.laps == []
    assert tracker.fuel_per_lap is None


def test_callouts_are_ordered_most_urgent_first(base):
    tracker = race(base, laps=8, burn=5.0, start_fuel=32.0, total_laps=40, rear_climb=3.0)
    severities = [c.severity for c in tracker.callouts()]
    rank = {"critical": 0, "warn": 1, "info": 2}
    assert severities == sorted(severities, key=lambda s: rank[s])


def test_electric_cars_get_no_fuel_advice(base):
    tracker = race(base, laps=5)
    tracker.feed(dataclasses.replace(tracker._latest, fuel_capacity=0.0), 500.0)
    assert not [c for c in tracker.callouts() if c.key.startswith("fuel")]


def test_the_lap_in_progress_when_we_attach_is_discarded(base):
    """Attaching mid-race must not record a fraction of a lap as a whole one.

    Observed live: the tracker joined part-way through lap 14 and logged it as
    using 1.88 L against the next lap's 6.98 L, halving the measured burn rate.
    """
    tracker = StintTracker()
    now, fuel = 0.0, 60.0

    def run_lap(lap: int, frames: int) -> None:
        nonlocal now, fuel
        for _ in range(frames):
            tracker.feed(dataclasses.replace(
                base, current_lap=lap, total_laps=0,
                last_lap_ms=103_000 if lap > 14 else -1,
                fuel_level=fuel, fuel_capacity=100.0, speed_mps=60.0,
            ), now)
            now += 1 / 60
            fuel -= 6.0 / FRAMES_PER_LAP  # a full lap costs 6 L

    run_lap(14, FRAMES_PER_LAP // 5)   # joined with 20% of the lap left
    run_lap(15, FRAMES_PER_LAP)
    run_lap(16, FRAMES_PER_LAP)

    assert [lap.number for lap in tracker.laps] == [15]
    assert tracker.laps[0].fuel_used == pytest.approx(6.0, abs=0.1)
    assert tracker.fuel_per_lap == pytest.approx(6.0, abs=0.1)


# ---- position --------------------------------------------------------------


def drive_positions(base: Telemetry, sequence: list[tuple[int, int]]) -> StintTracker:
    """Feed (position, frames) pairs at a steady 60 Hz."""
    tracker = StintTracker()
    now = 0.0
    for place, frames in sequence:
        for _ in range(frames):
            tracker.feed(dataclasses.replace(
                base, grid_position=place, cars_in_race=20,
                current_lap=5, speed_mps=60.0), now)
            now += 1 / 60
    return tracker


def test_position_change_is_tracked(base):
    tracker = drive_positions(base, [(13, 60), (11, 60)])
    assert tracker.position == 11
    assert tracker.start_position == 13
    assert tracker.places_gained == 2
    assert [(c.previous, c.current) for c in tracker.position_changes] == [(13, 11)]


def test_single_frame_flicker_is_not_reported_as_an_overtake(base):
    tracker = drive_positions(base, [(13, 60), (12, 3), (13, 60)])
    assert tracker.position == 13
    assert tracker.position_changes == []
    assert tracker.places_gained == 0


def test_losing_a_place_warns(base):
    tracker = drive_positions(base, [(11, 60), (13, 60)])
    assert tracker.places_gained == -2
    call = next(c for c in tracker.callouts() if c.key == "position-loss")
    assert call.severity == "warn"
    assert "P13" in call.message


def test_gaining_a_place_is_called_out(base):
    tracker = drive_positions(base, [(13, 60), (11, 60)])
    keys = {c.key for c in tracker.callouts()}
    assert "position-gain" in keys
    assert "position-net" in keys


def test_a_stale_position_change_stops_being_news(base):
    tracker = drive_positions(base, [(13, 60), (11, 60)])
    assert any(c.key == "position-gain" for c in tracker.callouts())
    # Same position, much later: the move is history, the standing is not.
    tracker.feed(dataclasses.replace(base, grid_position=11, cars_in_race=20,
                                     current_lap=9, speed_mps=60.0), 1000.0)
    keys = {c.key for c in tracker.callouts()}
    assert "position-gain" not in keys
    assert "position-net" in keys


def test_no_position_data_outside_a_race(base):
    tracker = drive_positions(base, [(0, 30)])
    assert tracker.position == 0
    assert tracker.places_gained is None
    assert not [c for c in tracker.callouts() if c.key.startswith("position")]


def test_a_static_position_field_produces_no_invented_movement(base):
    """If 0x84 turns out to be the pre-race place, nothing must be claimed."""
    tracker = drive_positions(base, [(7, 600)])
    assert tracker.places_gained == 0
    assert tracker.position_changes == []
    assert not [c for c in tracker.callouts() if c.key.startswith("position")]


# ---- steering (format B only) ----------------------------------------------


def steer_laps(base: Telemetry, angle_fn, laps: int = 4,
               frames: int = FRAMES_PER_LAP * 10) -> StintTracker:
    """Drive `laps` laps with a given steering-angle function of frame index."""
    tracker = StintTracker()
    now = 0.0
    for lap in range(1, laps + 1):
        for i in range(frames):
            tracker.feed(dataclasses.replace(
                base, current_lap=lap, last_lap_ms=60_000 if lap > 1 else -1,
                speed_mps=60.0, wheel_rotation=angle_fn(lap, i),
            ), now)
            now += 1 / 60
    return tracker


def test_steering_is_absent_on_format_a(base):
    tracker = race(base, laps=5)  # fixture frames carry no wheel_rotation
    assert tracker.steering_available is False
    assert all(lap.steering_corrections is None for lap in tracker.laps)
    assert all(lap.corrections_per_minute is None for lap in tracker.laps)
    assert not [c for c in tracker.callouts() if c.key.startswith("steering")]


def test_each_turning_point_counts_once(base):
    import math

    cycles = 5
    tracker = steer_laps(base, lambda lap, i: 0.5 * math.sin(
        2 * math.pi * cycles * i / (FRAMES_PER_LAP * 10)))
    assert tracker.steering_available is True
    # A sine wave turns twice per cycle, so five corners give ten corrections.
    assert tracker.laps[-1].steering_corrections == cycles * 2


def test_jitter_below_the_deadzone_is_not_sawing(base):
    import math

    tracker = steer_laps(base, lambda lap, i: 0.01 * math.sin(i / 2))
    assert tracker.laps[-1].steering_corrections == 0


def test_holding_a_constant_angle_is_not_a_correction(base):
    tracker = steer_laps(base, lambda lap, i: 0.4)
    assert tracker.laps[-1].steering_corrections == 0
    assert tracker.laps[-1].max_steering == pytest.approx(0.4)


def test_busy_hands_are_judged_against_the_driver_not_a_fixed_number(base):
    import math

    span = FRAMES_PER_LAP * 10

    def angle(lap, i):
        base_line = 0.5 * math.sin(2 * math.pi * 5 * i / span)
        saw = 0.10 * math.sin(2 * math.pi * 60 * i / span) if lap == 7 else 0.0
        return base_line + saw

    tracker = steer_laps(base, angle, laps=8)
    assert tracker.median_corrections_per_minute == pytest.approx(10.0, abs=0.5)
    call = next(c for c in tracker.callouts() if c.key == "steering-busy")
    assert "usual" in call.detail

    # The same absolute rate is unremarkable for a driver who always steers
    # that much, so a fixed threshold would be wrong.
    steady = steer_laps(base, lambda lap, i: angle(7, i), laps=8)
    assert not [c for c in steady.callouts() if c.key == "steering-busy"]


def test_the_opening_lap_never_reaches_the_stint_table(base):
    """A grid lap is short: its time and its fuel burn are both unrepresentative.

    The tracker already drops whatever lap was running when it attached, which
    covers this, so the guarantee is asserted rather than re-implemented.
    """
    tracker = StintTracker()
    now, fuel = 0.0, 100.0

    def drive(lap: int, reported_ms: int, frames: int, burn: float) -> None:
        nonlocal now, fuel
        for _ in range(frames):
            tracker.feed(dataclasses.replace(
                base, current_lap=lap, last_lap_ms=reported_ms, speed_mps=60.0,
                fuel_level=fuel, fuel_capacity=100.0), now)
            now += 1 / 60
            fuel -= burn / frames

    for _ in range(30):                       # sitting on the grid
        tracker.feed(dataclasses.replace(base, current_lap=0, last_lap_ms=-1,
                                         fuel_level=fuel, fuel_capacity=100.0), now)
        now += 1 / 60
    drive(1, -1, frames=20, burn=1.5)         # short grid lap, little fuel
    drive(2, 15_000, frames=60, burn=6.0)     # GT7: lap 1 took only 15s
    drive(3, 60_000, frames=60, burn=6.0)
    drive(4, 61_000, frames=60, burn=6.0)

    assert [lap.number for lap in tracker.laps] == [2, 3]
    assert tracker.best_lap_ms == 60_000       # not the 15s grid lap
    assert tracker.fuel_per_lap == pytest.approx(6.0, abs=0.1)
