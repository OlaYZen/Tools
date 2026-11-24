"""Detecting a pit stop, which GT7 does not report.

There is no pit flag in the telemetry, but a pit lane leaves two signatures
that nothing else on a race track does.

**The limiter holds a speed no driver can hold.** In the pit lane the car is
speed-limited, so it sits on one figure to within a fraction of a km/h for
seconds at a time. A human cannot do that, and neither can a car being driven
in anger.

**The pit lane is not on the racing line.** Once a circuit has been recognised
we know where the line runs, so a car holding a limiter speed away from it is
in the pits rather than crawling round under caution.

The limit itself is deliberately not hard-coded. It varies by circuit and by
series, so the detector looks for *steadiness* within a plausible band and then
reports the speed it found - which is the pit limit, learned rather than
assumed.

**The opening lap is not evidence of anything.** Nearly every GT7 race is a
rolling start: the game drives the whole field round at one held speed before
the line, which is the limiter signature exactly - steady to a fraction of a
km/h, inside the pit band, covering ground. No speed test can separate it from
a pit lane, because it *is* a limiter. So no stop may open on the out-lap.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from .delta import is_out_lap
from .packet import Telemetry
from .stint import Callout

#: How long the limiter signature must hold before it counts. Long enough that
#: a moment of steady throttle cannot trigger it.
HOLD_SECONDS = 3.0

#: Total spread of speed across the window. A limiter holds far tighter than
#: this; a driver holding a constant throttle does not.
SPEED_SPREAD_KPH = 1.5

#: Plausible pit limits. The upper bound matters: flat out along a long
#: straight the car is drag-limited and its speed also plateaus, so without a
#: ceiling the Mulsanne would read as a pit lane.
PIT_MIN_KPH = 20.0
PIT_MAX_KPH = 120.0

#: A limiter holds speed while the car covers ground. GT7 keeps streaming a
#: frozen snapshot at 60 Hz while the game is paused, which is a *perfectly*
#: steady speed and would otherwise read as the tidiest pit stop ever seen -
#: and the PAUSED flag cannot be relied on to catch it, having been measured
#: False with the game plainly paused. So the reported speed has to be
#: consistent with the distance actually travelled. Half is generous: it allows
#: for a window that straddles a corner.
MIN_TRAVEL_FRACTION = 0.5

#: Spacing for points kept along the pit lane. Coarser than the circuit trace
#: because the lane is short and drawn thin.
LANE_SPACING = 4.0

#: How far back to recover the pit entry from. Bounded by distance rather than
#: by time or frame count: both of those depend on how fast frames arrive, and
#: a caller pushing them faster than real time can hold whole laps inside the
#: window - which is how a pit road ended up with 2400 racing-line points in it.
#: A pit entry road is a few hundred metres; a lap is not.
MAX_BACKFILL_METRES = 250.0

#: How close to the stored outline counts as being on the racing line.
#:
#: This *corroborates* a stop; it never vetoes one. Some pit lanes are the far
#: side of a circuit, others are a wall's width from the racing line, and no
#: single distance separates those cases. Geometry that can be right next to
#: the track cannot be allowed to overrule the limiter, so the speed signature
#: decides and position only adjusts how confident the answer is.
ON_LINE_METRES = 8.0

#: Leaving the pits is judged on being back on the racing line at racing
#: speed, not on the limiter signature ending - the car is stationary during
#: the stop itself, which would otherwise read as an immediate exit.
EXIT_SECONDS = 2.0
EXIT_SPEED_KPH = PIT_MAX_KPH


@dataclass(slots=True)
class PitStop:
    lap: int
    entered_at: float
    left_at: float | None = None
    #: Whether the car was clear of the racing line when the stop opened.
    #: Corroboration only - a lane beside the track still counts as a stop.
    off_racing_line: bool = False
    #: The road taken through the lane, so the map can draw it. Backfilled at
    #: entry from the detector's window: the limiter has to hold for seconds
    #: before a stop is called, by which point the car is already well down
    #: the lane, and a pit road drawn from halfway along is worse than none.
    path: list[tuple[float, float]] = field(default_factory=list)
    #: Seconds the car was actually stationary, which is the part a strategist
    #: can influence, as opposed to the pit lane transit.
    stationary_s: float = 0.0

    @property
    def duration_s(self) -> float | None:
        if self.left_at is None:
            return None
        return self.left_at - self.entered_at


@dataclass(slots=True)
class PitDetector:
    """Watches for the pit-lane signature in a stream of frames."""

    #: Answers "is this point on the racing line?", or None when no circuit is
    #: recognised. The caller binds the tolerance - see ON_LINE_METRES - so the
    #: detector never has to know how circuit matching measures distance.
    on_line: Callable[[float, float], bool | None] | None = None

    #: Why the last frame did not open a stop. Exposed so a missed stop can be
    #: explained instead of guessed at.
    blocked_by: str | None = None
    #: The speed spread measured over the window, which is what separates a
    #: limiter from a driver.
    spread_kph: float | None = None

    in_pits: bool = False
    entered_at: float | None = None
    stops: list[PitStop] = field(default_factory=list)
    #: The limiter speed we measured, once we have seen one.
    limit_kph: float | None = None
    #: Whether position could be used, so the UI can say how sure this is.
    used_position: bool = False

    #: Bounded only as a runaway backstop. The real bound is the time-based
    #: prune in feed(); sizing this to an assumed 60 Hz meant a faster caller
    #: silently truncated the window below HOLD_SECONDS, and the signature
    #: could then never fire at all.
    _window: deque = field(default_factory=lambda: deque(maxlen=4000), repr=False)
    _off_line_since: float | None = None
    _on_line_since: float | None = None
    _car_code: int = 0

    def reset(self) -> None:
        self.in_pits = False
        self.entered_at = None
        self.stops = []
        self.limit_kph = None
        self.used_position = False
        self._window.clear()
        self._off_line_since = None
        self._on_line_since = None

    # ---- ingest ---------------------------------------------------------

    def feed(self, frame: Telemetry, now: float) -> None:
        if frame.car_code != self._car_code:
            car = frame.car_code
            self.reset()
            self._car_code = car

        if frame.paused:
            return

        x0, _, z0 = frame.position
        self._window.append((now, frame.speed_kph, frame.rpm, x0, z0))
        # Keep a little more than the hold, or pruning to exactly HOLD_SECONDS
        # leaves the window forever just short of spanning it and the signature never
        # fires.
        cutoff = now - HOLD_SECONDS * 1.25
        while self._window and self._window[0][0] < cutoff:
            self._window.popleft()

        x, _, z = frame.position
        on_line = self.on_line(x, z) if self.on_line else None
        if on_line is not None:
            self.used_position = True

        if self.in_pits:
            self._watch_for_exit(frame, now, on_line)
        else:
            self._watch_for_entry(frame, now, on_line)

        if self.in_pits and self.stops:
            stop = self.stops[-1]
            if frame.speed_kph < 1.0:
                stop.stationary_s += 1 / 60
            self._extend_path(stop, x, z)

    def _approach(self) -> list[tuple[float, float]]:
        """The last stretch of road before the limiter was confirmed.

        Walked backwards until MAX_BACKFILL_METRES of ground is covered, so
        what comes back is a length of road rather than a number of frames.
        """
        out: list[tuple[float, float]] = []
        travelled = 0.0
        previous: tuple[float, float] | None = None
        for entry in reversed(self._window):
            point = (entry[3], entry[4])
            if previous is not None:
                travelled += ((point[0] - previous[0]) ** 2
                              + (point[1] - previous[1]) ** 2) ** 0.5
                if travelled > MAX_BACKFILL_METRES:
                    break
            out.append(point)
            previous = point
        out.reverse()
        return out

    @staticmethod
    def _extend_path(stop: PitStop, x: float, z: float) -> None:
        """Add a point to the pit road, skipping ground already covered."""
        if stop.path:
            last = stop.path[-1]
            if ((x - last[0]) ** 2 + (z - last[1]) ** 2) ** 0.5 < LANE_SPACING:
                return
        stop.path.append((x, z))

    def _limiter_signature(self, now: float) -> float | None:
        """Mean speed if the window looks like a limiter, else None."""
        if len(self._window) < 2:
            return None
        if now - self._window[0][0] < HOLD_SECONDS:
            return None
        # Judge only the most recent HOLD_SECONDS, not the whole buffer.
        recent = [entry for entry in self._window if entry[0] >= now - HOLD_SECONDS]
        if len(recent) < 2:
            return None
        speeds = [entry[1] for entry in recent]
        spread = max(speeds) - min(speeds)
        self.spread_kph = round(spread, 2)
        mean = sum(speeds) / len(speeds)
        if spread > SPEED_SPREAD_KPH:
            self.blocked_by = (f"speed varying by {spread:.1f} km/h, more than a "
                               f"limiter holds ({SPEED_SPREAD_KPH})")
            return None
        if not (PIT_MIN_KPH <= mean <= PIT_MAX_KPH):
            self.blocked_by = (f"{mean:.0f} km/h is outside the pit band "
                               f"({PIT_MIN_KPH:.0f}-{PIT_MAX_KPH:.0f})")
            return None

        # Did the car actually go anywhere? A frozen stream says it did not.
        span = recent[-1][0] - recent[0][0]
        travelled = 0.0
        for previous, entry in zip(recent, recent[1:]):
            travelled += ((entry[3] - previous[3]) ** 2
                          + (entry[4] - previous[4]) ** 2) ** 0.5
        expected = (mean / 3.6) * span
        if travelled < expected * MIN_TRAVEL_FRACTION:
            self.blocked_by = (f"reported {mean:.0f} km/h but covered "
                               f"{travelled:.0f} m in {span:.1f}s - a frozen stream")
            return None
        return mean

    def _watch_for_entry(self, frame: Telemetry, now: float,
                         on_line: bool | None) -> None:
        # A rolling start is a limiter, just not the pit one: GT7 holds the
        # field at a single speed until the line, which passes the spread test,
        # sits inside the pit band and covers real ground, so every test here
        # agrees it is a stop. Observed live - a race opened with a "pit stop"
        # on the grid, and because the lane is recorded from before detection
        # it wrote the start of the racing line into the library as pit road.
        # The out-lap is already not a comparable lap in delta.py, track.py and
        # stint.py; it is not usable evidence here either. The cost is a stop
        # that genuinely began on lap 1 - vanishingly rare, and preferable to
        # opening one every single race.
        if is_out_lap(frame.current_lap):
            self.blocked_by = (f"lap {frame.current_lap} is the out-lap - a "
                               f"rolling start holds the whole field at one "
                               f"speed, which reads as a limiter")
            return

        limit = self._limiter_signature(now)
        if limit is None:
            return
        self.blocked_by = None

        self.in_pits = True
        self.entered_at = now
        self.limit_kph = round(limit, 1)
        stop = PitStop(lap=frame.current_lap, entered_at=now,
                       off_racing_line=on_line is False)
        for x, z in self._approach():
            self._extend_path(stop, x, z)
        self.stops.append(stop)
        self._on_line_since = None

    def _watch_for_exit(self, frame: Telemetry, now: float,
                        on_line: bool | None) -> None:
        # Speed alone, for the same reason position cannot veto an entry: the
        # stored outline is one particular lap's line, so a car racing on a
        # different line reads as "not on the line" and would never leave pit
        # state. Observed live - a car at 148 km/h still flagged in the pits a
        # minute after leaving, quietly recording the racing line into the
        # pit lane.
        back = frame.speed_kph > EXIT_SPEED_KPH
        if not back:
            self._on_line_since = None
            return
        if self._on_line_since is None:
            self._on_line_since = now
        elif now - self._on_line_since >= EXIT_SECONDS:
            self.in_pits = False
            self.entered_at = None
            self._on_line_since = None
            if self.stops and self.stops[-1].left_at is None:
                self.stops[-1].left_at = now

    # ---- read -----------------------------------------------------------

    @property
    def stop_count(self) -> int:
        return len(self.stops)

    @property
    def current(self) -> PitStop | None:
        if self.in_pits and self.stops:
            return self.stops[-1]
        return None

    @property
    def last_completed(self) -> PitStop | None:
        for stop in reversed(self.stops):
            if stop.left_at is not None:
                return stop
        return None

    def elapsed_s(self, now: float) -> float | None:
        if self.entered_at is None:
            return None
        return now - self.entered_at

    def lap_had_a_stop(self, lap: int) -> bool:
        """True if a stop began on this lap - so it is not a representative lap."""
        return any(stop.lap == lap for stop in self.stops)

    def callouts(self, now: float) -> list[Callout]:
        """What to say about the pit lane, if anything."""
        if self.in_pits:
            elapsed = self.elapsed_s(now) or 0.0
            stationary = self.current.stationary_s if self.current else 0.0
            detail = f"{elapsed:.0f}s in the lane"
            if stationary > 0.5:
                detail += f", {stationary:.0f}s stationary"
            if self.limit_kph:
                detail += f" · limiter {self.limit_kph:.0f} km/h"
            return [Callout("pit-in", "info", "In the pit lane.", detail)]

        stop = self.last_completed
        if stop is not None and stop.left_at is not None \
                and now - stop.left_at <= 20.0:
            return [Callout("pit-out", "info",
                            f"Out of the pits after {stop.duration_s:.0f} seconds.",
                            f"{stop.stationary_s:.0f}s stationary on lap {stop.lap}")]
        return []

    @property
    def confidence(self) -> str:
        """How much corroboration the current answer has."""
        if not self.used_position:
            return "speed only - no circuit recognised yet"
        stop = self.current or self.last_completed
        if stop is not None and not stop.off_racing_line:
            # A lane hard against the racing line looks the same as the track
            # from here. The limiter is still the evidence; say that plainly.
            return "speed only - the lane runs beside the racing line"
        return "speed and position"
