"""Stint tracking and radio callouts.

The driver dashboard answers "what is the car doing right now". A race
engineer needs something else: what has changed over the stint, what it
predicts, and what to say on the radio about it. That requires accumulating
state across laps, which is what this module does.

GT7 gives a completed lap's time in `last_lap_ms` and the lap counter in
`current_lap`, so a lap boundary is detectable but a lap's *contents* are not
- there is no sector data and no distance-round-lap. Everything per-lap here
is therefore accumulated frame by frame between boundaries.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field

from .packet import Telemetry

#: Slip ratio thresholds. Slip is wheel surface speed over chassis speed, so
#: >1 is spinning up and <1 is locking. 8% either way clears the noise floor
#: while still catching anything a driver would feel.
SPIN_SLIP = 1.08
LOCK_SLIP = 0.92

#: An event must persist this long to count, so a single noisy frame over a
#: kerb does not get reported to the driver as a lock-up.
EVENT_MIN_FRAMES = 4

#: Pedal thresholds for attributing an event to throttle or brake.
ON_POWER = 0.5
ON_BRAKE = 0.3

#: How many recent laps feed the fuel-burn and consistency figures.
ROLLING_LAPS = 5

#: Steering movement below this is jitter, not input (radians).
STEER_DEADZONE = 0.02

#: A direction change only counts as a correction if the wheel travelled this
#: far since the last turning point. Without it, noise around a steady angle
#: reads as a driver sawing at the wheel.
STEER_MIN_EXCURSION = 0.08

#: Flag a lap only when its correction rate is this much above the driver's own
#: median. Absolute thresholds are meaningless - a lap of the Nordschleife has
#: far more corners than a lap of a short circuit - so the baseline is the
#: driver themselves.
STEER_BUSY_RATIO = 1.4

#: A position must hold for this many frames before it counts as a change.
#: Guards against a single odd frame being reported to the driver as an
#: overtake.
POSITION_CONFIRM_FRAMES = 12

#: A position change is worth mentioning on the radio for this long.
POSITION_CALL_SECONDS = 20.0


@dataclass(slots=True)
class LapRecord:
    number: int
    time_ms: int
    fuel_used: float
    tyre_temp: tuple[float, float, float, float]
    max_speed_kph: float
    lockups: int
    wheelspin: int
    full_throttle_pct: float
    braking_pct: float
    #: Where each lock-up or moment of wheelspin happened: (x, z, kind), with
    #: kind 0 for a lock-up and 1 for wheelspin. Position, not just a count,
    #: so the engineer can point at the corner rather than describe it.
    events: list[tuple[float, float, int]] = field(default_factory=list)
    #: Steering only exists in format B, so these stay None on format A.
    steering_corrections: int | None = None
    max_steering: float | None = None

    @property
    def corrections_per_minute(self) -> float | None:
        """Corrections normalised by lap time, so laps compare across tracks."""
        if self.steering_corrections is None or self.time_ms <= 0:
            return None
        return self.steering_corrections / (self.time_ms / 60_000)


@dataclass(slots=True)
class PositionChange:
    lap: int
    previous: int
    current: int
    at: float


@dataclass(slots=True)
class Callout:
    """One thing to tell the driver, phrased for the radio."""

    key: str          #: stable id, so the UI can tell a new callout from a repeat
    severity: str     #: critical | warn | info
    message: str      #: read this out
    detail: str = ""  #: the number behind it, for the engineer's own eyes


@dataclass(slots=True)
class _LapAccumulator:
    frames: int = 0
    throttle_frames: int = 0
    brake_frames: int = 0
    max_speed_kph: float = 0.0
    temp_sum: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    lockups: int = 0
    wheelspin: int = 0
    spin_run: int = 0
    lock_run: int = 0
    spin_counted: bool = False
    lock_counted: bool = False
    events: list[tuple[float, float, int]] = field(default_factory=list)
    steering_seen: bool = False
    max_steering: float = 0.0
    corrections: int = 0
    steer_dir: int = 0          #: -1 left, +1 right, 0 not yet established
    steer_extreme: float = 0.0  #: wheel angle at the last turning point


class StintTracker:
    """Accumulates a stint and turns it into things worth saying."""

    def __init__(self) -> None:
        self.laps: list[LapRecord] = []
        self.car_code: int = 0
        self.lap_number: int = 0
        self.total_laps: int = 0

        # Position is the only thing GT7 says about the rest of the field: a
        # place and a car count. There is no opponent data in the protocol, so
        # gaps in seconds cannot be computed - see docs/opponents.md.
        self.position: int = 0
        self.cars: int = 0
        self.start_position: int | None = None
        self.position_changes: list[PositionChange] = []
        self._pending_position: int = 0
        self._pending_frames: int = 0

        self._acc = _LapAccumulator()
        self._lap_start_fuel: float | None = None
        self._lap_start_time: float | None = None
        #: True until we have watched a lap from its own boundary. Whatever lap
        #: was already running when we attached is partial - its fuel delta,
        #: tyre averages and event counts all cover a fraction of a lap - so
        #: recording it would poison every statistic derived from it. Observed
        #: live: joining part-way through a lap logged it as burning 1.88 L
        #: against the next lap's 6.98 L, halving the measured burn rate.
        #: Costs one lap of data at the start of a session, deliberately: there
        #: is no way to tell "joined at the line" from "joined at the hairpin".
        self._lap_is_partial = True
        self._fuel_history: deque[float] = deque(maxlen=ROLLING_LAPS)
        self._latest: Telemetry | None = None
        self._now: float = 0.0

    # ---- ingest ---------------------------------------------------------

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]

    def feed(self, frame: Telemetry, now: float) -> None:
        if frame.car_code != self.car_code or frame.current_lap < self.lap_number:
            # New car or the lap counter went backwards: a different session.
            car = frame.car_code
            self.reset()
            self.car_code = car

        self._latest = frame
        self._now = now
        self.total_laps = frame.total_laps

        self._track_position(frame, now)

        if frame.current_lap != self.lap_number:
            self._close_lap(frame, now)
            self.lap_number = frame.current_lap

        if self._lap_start_fuel is None:
            self._lap_start_fuel = frame.fuel_level
            self._lap_start_time = now

        self._accumulate(frame)

    def _track_position(self, frame: Telemetry, now: float) -> None:
        """Follow the place counter, ignoring single-frame flicker."""
        place, cars = frame.grid_position, frame.cars_in_race
        if place <= 0 or cars <= 0:
            return  # not in a race, or the game has not populated it yet
        self.cars = cars

        if self.start_position is None:
            self.start_position = place
            self.position = place
            return

        if place == self.position:
            self._pending_frames = 0
            return

        # Require the new place to hold before believing it.
        if place != self._pending_position:
            self._pending_position = place
            self._pending_frames = 1
            return
        self._pending_frames += 1
        if self._pending_frames < POSITION_CONFIRM_FRAMES:
            return

        self.position_changes.append(PositionChange(
            lap=frame.current_lap, previous=self.position, current=place, at=now))
        self.position = place
        self._pending_frames = 0

    @property
    def places_gained(self) -> int | None:
        """Places made up since the stint began. Negative means places lost."""
        if self.start_position is None or not self.position:
            return None
        return self.start_position - self.position

    def _accumulate(self, frame: Telemetry) -> None:
        acc = self._acc
        acc.frames += 1
        acc.max_speed_kph = max(acc.max_speed_kph, frame.speed_kph)
        for i, temp in enumerate(frame.tyre_temp):
            acc.temp_sum[i] += temp

        throttle = frame.throttle / 255.0
        brake = frame.brake / 255.0
        if throttle > 0.98:
            acc.throttle_frames += 1
        if brake > 0.05:
            acc.brake_frames += 1

        if not frame.is_moving:
            return

        self._accumulate_steering(acc, frame)

        # Count events, not frames: a lock-up is one thing that happened, and
        # reporting "240 lock-ups" because it lasted four seconds is useless.
        spinning = throttle > ON_POWER and max(frame.tyre_slip) > SPIN_SLIP
        locking = brake > ON_BRAKE and min(frame.tyre_slip) < LOCK_SLIP

        if spinning:
            acc.spin_run += 1
            if acc.spin_run >= EVENT_MIN_FRAMES and not acc.spin_counted:
                acc.wheelspin += 1
                acc.spin_counted = True
                acc.events.append((frame.position[0], frame.position[2], 1))
        else:
            acc.spin_run = 0
            acc.spin_counted = False

        if locking:
            acc.lock_run += 1
            if acc.lock_run >= EVENT_MIN_FRAMES and not acc.lock_counted:
                acc.lockups += 1
                acc.lock_counted = True
                acc.events.append((frame.position[0], frame.position[2], 0))
        else:
            acc.lock_run = 0
            acc.lock_counted = False

    @staticmethod
    def _accumulate_steering(acc: _LapAccumulator, frame: Telemetry) -> None:
        """Count meaningful direction changes at the wheel.

        A turning-point counter with hysteresis: the wheel must travel
        STEER_MIN_EXCURSION back from its last extreme before the reversal
        counts. This deliberately measures only the *sign* of movement and how
        far it travelled, never an absolute angle - the scale of 0x128 is not
        fully pinned down (it saturates at exactly pi), so anything depending
        on its calibration would be built on sand. Counts and ratios survive
        that uncertainty; degrees would not.
        """
        angle = frame.wheel_rotation
        if angle is None:
            return  # format A carries no steering channel
        acc.steering_seen = True
        acc.max_steering = max(acc.max_steering, abs(angle))

        travel = angle - acc.steer_extreme
        if acc.steer_dir == 0:
            if abs(travel) > STEER_DEADZONE:
                acc.steer_dir = 1 if travel > 0 else -1
                acc.steer_extreme = angle
        elif acc.steer_dir > 0:
            if angle > acc.steer_extreme:
                acc.steer_extreme = angle          # still winding on
            elif acc.steer_extreme - angle > STEER_MIN_EXCURSION:
                acc.corrections += 1
                acc.steer_dir = -1
                acc.steer_extreme = angle
        else:
            if angle < acc.steer_extreme:
                acc.steer_extreme = angle
            elif angle - acc.steer_extreme > STEER_MIN_EXCURSION:
                acc.corrections += 1
                acc.steer_dir = 1
                acc.steer_extreme = angle

    def _close_lap(self, frame: Telemetry, now: float) -> None:
        acc = self._acc
        self._acc = _LapAccumulator()

        def open_next_lap() -> None:
            self._lap_start_fuel = frame.fuel_level
            self._lap_start_time = now

        # Attaching to a race in progress is not a lap boundary. The lap we
        # land in was already running, so it stays flagged partial.
        if self.lap_number == 0:
            open_next_lap()
            return

        # This is the first real boundary, so the lap that just ended is the
        # one we joined half-way through. Discard it - but the lap starting
        # now we will have seen in full.
        if self._lap_is_partial:
            self._lap_is_partial = False
            open_next_lap()
            return

        if acc.frames == 0 or frame.last_lap_ms <= 0:
            open_next_lap()
            return

        fuel_used = 0.0
        if self._lap_start_fuel is not None:
            fuel_used = self._lap_start_fuel - frame.fuel_level
        if fuel_used < 0:
            # Refuelled during the lap; the burn figure would be nonsense.
            self._fuel_history.clear()
            fuel_used = 0.0
        elif fuel_used > 0:
            self._fuel_history.append(fuel_used)

        self.laps.append(LapRecord(
            number=self.lap_number,
            time_ms=frame.last_lap_ms,
            fuel_used=fuel_used,
            tyre_temp=tuple(t / acc.frames for t in acc.temp_sum),  # type: ignore[arg-type]
            max_speed_kph=acc.max_speed_kph,
            lockups=acc.lockups,
            wheelspin=acc.wheelspin,
            full_throttle_pct=acc.throttle_frames / acc.frames * 100.0,
            braking_pct=acc.brake_frames / acc.frames * 100.0,
            events=list(acc.events),
            steering_corrections=acc.corrections if acc.steering_seen else None,
            max_steering=acc.max_steering if acc.steering_seen else None,
        ))
        self._lap_start_fuel = frame.fuel_level
        self._lap_start_time = now

    # ---- derived figures ------------------------------------------------

    @property
    def lap_elapsed_ms(self) -> int | None:
        """Time on the current lap. GT7 does not send this; it is wall clock."""
        if self._lap_start_time is None:
            return None
        return int((self._now - self._lap_start_time) * 1000)

    @property
    def recent(self) -> list[LapRecord]:
        return self.laps[-ROLLING_LAPS:]

    @property
    def fuel_per_lap(self) -> float | None:
        """Mean burn over recent laps, ignoring any lap that used nothing."""
        burns = [b for b in self._fuel_history if b > 0]
        return statistics.fmean(burns) if burns else None

    @property
    def laps_of_fuel(self) -> float | None:
        frame, burn = self._latest, self.fuel_per_lap
        if frame is None or burn is None or burn <= 0 or frame.is_ev:
            return None
        return frame.fuel_level / burn

    @property
    def laps_to_go(self) -> int | None:
        if not self.total_laps:
            return None
        return max(self.total_laps - self.lap_number + 1, 0)

    @property
    def fuel_margin(self) -> float | None:
        """Laps of fuel in hand at the finish. Negative means short."""
        remaining, to_go = self.laps_of_fuel, self.laps_to_go
        if remaining is None or to_go is None:
            return None
        return remaining - to_go

    @property
    def best_lap_ms(self) -> int | None:
        times = [lap.time_ms for lap in self.laps if lap.time_ms > 0]
        return min(times) if times else None

    @property
    def consistency_ms(self) -> float | None:
        """Standard deviation of recent lap times - lower is a happier driver."""
        times = [lap.time_ms for lap in self.recent if lap.time_ms > 0]
        return statistics.stdev(times) if len(times) >= 3 else None

    @property
    def pace_trend_ms(self) -> float | None:
        """Change in lap time across the recent window. Positive = slowing."""
        times = [lap.time_ms for lap in self.recent if lap.time_ms > 0]
        if len(times) < 3:
            return None
        half = len(times) // 2
        return statistics.fmean(times[half:]) - statistics.fmean(times[:half])

    @property
    def steering_available(self) -> bool:
        """False on format A, which carries no steering channel at all."""
        latest = self._latest
        return latest is not None and latest.wheel_rotation is not None

    @property
    def median_corrections_per_minute(self) -> float | None:
        """The driver's own baseline, excluding the lap being judged."""
        rates = [r for lap in self.laps[:-1]
                 if (r := lap.corrections_per_minute) is not None]
        return statistics.median(rates) if len(rates) >= 2 else None

    @property
    def tyre_balance(self) -> dict[str, float] | None:
        """Front/rear and left/right temperature splits, averaged over the lap."""
        if not self.laps:
            return None
        fl, fr, rl, rr = self.laps[-1].tyre_temp
        return {
            "front": (fl + fr) / 2,
            "rear": (rl + rr) / 2,
            "front_rear": (rl + rr) / 2 - (fl + fr) / 2,
            "left_right": (fl + rl) / 2 - (fr + rr) / 2,
        }

    def tyre_series(self, corner: int) -> list[float]:
        return [lap.tyre_temp[corner] for lap in self.laps]

    # ---- the point of all this ------------------------------------------

    def callouts(self) -> list[Callout]:
        """What to tell the driver, most urgent first."""
        out: list[Callout] = []
        frame = self._latest
        if frame is None:
            return out

        out += self._fuel_callouts(frame)
        out += self._position_callouts()
        out += self._tyre_callouts()
        out += self._driving_callouts()
        out += self._pace_callouts()

        rank = {"critical": 0, "warn": 1, "info": 2}
        out.sort(key=lambda c: rank[c.severity])
        return out

    def _fuel_callouts(self, frame: Telemetry) -> list[Callout]:
        if frame.is_ev:
            return []
        remaining, to_go = self.laps_of_fuel, self.laps_to_go
        if remaining is None:
            return []
        burn = self.fuel_per_lap or 0.0

        if remaining < 1.5:
            return [Callout("fuel-critical", "critical",
                            "Fuel critical. Box this lap.",
                            f"{frame.fuel_level:.1f} L, {remaining:.1f} laps at {burn:.2f} L/lap")]
        margin = self.fuel_margin
        if margin is not None and margin < 0 and to_go:
            # How much less per lap they must use to reach the finish.
            need = frame.fuel_level / to_go
            save = burn - need
            return [Callout("fuel-short", "warn",
                            f"Fuel for {remaining:.0f} laps, {to_go} to go. "
                            f"Save {save:.2f} a lap.",
                            f"short by {-margin:.1f} laps at {burn:.2f} L/lap")]
        if margin is not None and margin >= 0 and to_go:
            return [Callout("fuel-ok", "info",
                            f"Fuel is good. {remaining:.0f} laps in the tank, {to_go} to go.",
                            f"{margin:.1f} laps in hand")]
        return [Callout("fuel-laps", "info",
                        f"Fuel for {remaining:.0f} more laps.",
                        f"{burn:.2f} L/lap")]

    def _position_callouts(self) -> list[Callout]:
        """Position is all GT7 gives about the field, so say it well.

        No gaps: the protocol carries nothing about other cars, so an engineer
        gets places and nothing else. Saying "P11" with no time to the car
        ahead is still worth saying; inventing a gap would not be.
        """
        if not self.position or not self.cars:
            return []
        out: list[Callout] = []

        recent = [c for c in self.position_changes
                  if self._now - c.at <= POSITION_CALL_SECONDS]
        if recent:
            change = recent[-1]
            if change.current < change.previous:
                out.append(Callout("position-gain", "info",
                                   f"Up to P{change.current}.",
                                   f"from P{change.previous} on lap {change.lap}"))
            else:
                out.append(Callout("position-loss", "warn",
                                   f"Dropped to P{change.current}. Watch your mirrors.",
                                   f"from P{change.previous} on lap {change.lap}"))

        gained = self.places_gained
        if gained:
            direction = "up" if gained > 0 else "down"
            out.append(Callout("position-net", "info",
                               f"P{self.position} of {self.cars}, "
                               f"{direction} {abs(gained)} from your start.",
                               f"started P{self.start_position}"))
        return out

    def _tyre_callouts(self) -> list[Callout]:
        balance = self.tyre_balance
        if balance is None:
            return []
        out = []
        split = balance["front_rear"]
        if split > 12:
            out.append(Callout("tyre-rear-hot", "warn",
                               f"Rears are {split:.0f} over the fronts. "
                               "Ease the traction out of slow corners.",
                               f"front {balance['front']:.0f}° rear {balance['rear']:.0f}°"))
        elif split < -12:
            out.append(Callout("tyre-front-hot", "warn",
                               f"Fronts are {-split:.0f} over the rears. "
                               "Slow your hands in the long corners.",
                               f"front {balance['front']:.0f}° rear {balance['rear']:.0f}°"))

        side = balance["left_right"]
        if abs(side) > 10:
            hot, cold = ("left", "right") if side > 0 else ("right", "left")
            out.append(Callout("tyre-side", "info",
                               f"The {hot} side is {abs(side):.0f} hotter than the {cold}.",
                               "expected on a one-directional circuit"))

        coldest = min(balance["front"], balance["rear"])
        if coldest < 55 and len(self.laps) <= 2:
            out.append(Callout("tyre-cold", "info",
                               "Tyres are still cold. Build temperature before you push.",
                               f"{coldest:.0f}°"))
        return out

    def _driving_callouts(self) -> list[Callout]:
        if not self.laps:
            return []
        lap = self.laps[-1]
        out = []
        if lap.lockups >= 3:
            out.append(Callout("lockups", "warn",
                               f"{lap.lockups} lock-ups last lap. Ease the initial brake pressure.",
                               f"lap {lap.number}"))
        if lap.wheelspin >= 5:
            out.append(Callout("wheelspin", "warn",
                               f"{lap.wheelspin} moments of wheelspin. Be patient with the throttle.",
                               f"lap {lap.number}"))

        rate = lap.corrections_per_minute
        baseline = self.median_corrections_per_minute
        if rate is not None and baseline and rate > baseline * STEER_BUSY_RATIO:
            out.append(Callout("steering-busy", "info",
                               "Busier hands than usual. Try to settle the car "
                               "on one steering input.",
                               f"{rate:.0f} corrections a minute against your "
                               f"usual {baseline:.0f}"))
        return out

    def _pace_callouts(self) -> list[Callout]:
        best = self.best_lap_ms
        if best is None or not self.laps:
            return []
        last = self.laps[-1].time_ms
        if last <= 0:
            return []
        delta = (last - best) / 1000.0
        out = []
        if last == best and len(self.laps) > 1:
            out.append(Callout("pace-best", "info", "That is your best lap. Keep it there.",
                               f"{self._fmt(best)}"))
        elif delta > 1.5:
            trend = self.pace_trend_ms
            drifting = trend is not None and trend > 300
            out.append(Callout("pace-slow", "warn" if drifting else "info",
                               f"Last lap {delta:.1f} off your best."
                               + (" Pace is drifting." if drifting else ""),
                               f"last {self._fmt(last)}, best {self._fmt(best)}"))
        consistency = self.consistency_ms
        if consistency is not None and consistency < 300 and len(self.laps) >= 4:
            out.append(Callout("pace-consistent", "info",
                               "Lap times are consistent. Hold this rhythm.",
                               f"±{consistency / 1000:.2f}s over {len(self.recent)} laps"))
        return out

    @staticmethod
    def _fmt(ms: int) -> str:
        minutes, rest = divmod(ms, 60_000)
        return f"{minutes}:{rest // 1000:02d}.{rest % 1000:03d}"
