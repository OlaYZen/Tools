"""Values GT7 does not send, computed from values it does.

Nothing in here is telemetry. It is inference, and it is labelled as such
wherever it surfaces. The motivating case is track wetness: the protocol
carries no weather channel at all (see docs/weather.md), but grip is a
physical consequence of wetness, and grip *is* measurable from the motion
data the console sends.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .packet import Telemetry

G = 9.80665

#: Differentiate speed over this many frames (~83 ms at 60 Hz). One frame is
#: too noisy; much more and genuine braking peaks get smoothed away.
_DIFF_FRAMES = 5

#: Only trust a grip sample above this speed - below it, slip and yaw-rate
#: maths degenerate and parking manoeuvres produce nonsense peaks.
_MIN_SPEED_MPS = 8.0

#: Read the window at this percentile rather than its maximum. A kerb strike
#: or a light contact produces one violent frame; taking the max would let
#: that single frame define the car's grip for the rest of the session.
_PEAK_PERCENTILE = 0.95


@dataclass(slots=True)
class GripSample:
    longitudinal_g: float
    lateral_g: float

    @property
    def combined_g(self) -> float:
        return (self.longitudinal_g**2 + self.lateral_g**2) ** 0.5


@dataclass(slots=True)
class GripEstimator:
    """Rolling estimate of how much grip the car is finding.

    Longitudinal g comes from differentiating speed; lateral g from
    `yaw_rate x speed`, which is exact in steady-state cornering and close
    enough in transitions. The peak *combined* g over a window is a decent
    proxy for available friction, because a driver at the limit is using all
    of it in some direction.

    A wet track shows up as a drop in peak g - typically to roughly 60-80% of
    the same car's dry peak. Because the absolute number depends on the car
    and tyre compound, the useful output is `relative`: recent peak measured
    against the best this car has managed in the session, which self-calibrates
    without needing a lookup table.
    """

    window_seconds: float = 20.0
    _history: deque = field(default_factory=lambda: deque(maxlen=64), repr=False)
    _peaks: deque = field(default_factory=deque, repr=False)
    _session_best: dict[int, float] = field(default_factory=dict, repr=False)
    _car_code: int = 0

    def feed(self, frame: Telemetry, now: float) -> GripSample | None:
        """Add a frame. Returns the instantaneous sample, or None if unusable."""
        if frame.car_code != self._car_code:
            # New car: previous peaks say nothing about this one.
            self._car_code = frame.car_code
            self._history.clear()
            self._peaks.clear()

        self._history.append((now, frame.speed_mps, frame.angular_velocity[1]))
        self._expire(now)

        # Deliberately not gated on the CAR_ON_TRACK flag: it reads false
        # through an entire race at 250 km/h, which silently killed this
        # estimate. Motion is the honest test of whether motion data is real.
        if frame.paused or frame.speed_mps < _MIN_SPEED_MPS:
            return None
        if len(self._history) <= _DIFF_FRAMES:
            return None

        t1, v1, _ = self._history[-1]
        t0, v0, _ = self._history[-1 - _DIFF_FRAMES]
        dt = t1 - t0
        if dt <= 0:
            return None

        longitudinal = abs(v1 - v0) / dt / G
        lateral = abs(frame.angular_velocity[1] * frame.speed_mps) / G
        sample = GripSample(longitudinal, lateral)

        # Discard physically impossible spikes (teleports, race resets).
        if sample.combined_g > 5.0:
            return None

        self._peaks.append((now, sample.combined_g))

        # Compare the smoothed window figure - never a raw frame - against the
        # session best, so one violent frame cannot poison the baseline that
        # every later "vs best" reading is measured against.
        window_peak = self.recent_peak_g
        if window_peak is not None:
            best = self._session_best.get(frame.car_code, 0.0)
            if window_peak > best:
                self._session_best[frame.car_code] = window_peak
        return sample

    def _expire(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._peaks and self._peaks[0][0] < cutoff:
            self._peaks.popleft()

    @property
    def recent_peak_g(self) -> float | None:
        """Near-peak combined g in the rolling window.

        The 95th percentile, not the maximum - see `_PEAK_PERCENTILE`.
        """
        if not self._peaks:
            return None
        values = sorted(g for _, g in self._peaks)
        index = min(int(len(values) * _PEAK_PERCENTILE), len(values) - 1)
        return values[index]

    @property
    def session_best_g(self) -> float | None:
        return self._session_best.get(self._car_code) or None

    @property
    def relative(self) -> float | None:
        """Recent peak as a fraction of this car's best this session.

        ~1.0 means the car is finding as much grip as it ever has. A sustained
        drop to ~0.7 is what a wet track looks like - but so does a driver
        taking it easy, so read it alongside throttle and brake.
        """
        peak, best = self.recent_peak_g, self.session_best_g
        if peak is None or not best:
            return None
        return min(peak / best, 1.0)

    @property
    def confidence(self) -> str:
        """How much the estimate should be trusted, given what has been seen."""
        if self.session_best_g is None:
            return "no data"
        if len(self._peaks) < 30:
            return "warming up"
        if self.session_best_g < 0.6:
            return "no hard driving seen"
        return "ok"
