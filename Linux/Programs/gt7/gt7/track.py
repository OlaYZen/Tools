"""Track mapping from the car's own world position.

GT7 sends no track geometry, but it does send the car's world position at
`0x04` in metres, and that position is exact: integrating it over 15 seconds
of driving gave 234.1 km/h against a reported 233.8, with no jumps. So the map
is a literal trace of where the car went, not a dead-reckoned guess from speed
and yaw - which would drift, and drift worst in exactly the long corners you
most want drawn correctly.

The map is anchored to the start/finish line rather than to wherever the
dashboard happened to connect. GT7's lap counter marks that line, so:

  * the lap already running when we attach is discarded - it starts somewhere
    arbitrary and would draw a partial outline with a false start marker;
  * so is the opening lap of a race, which starts on the grid ahead of the
    line and therefore traces less than a full circuit;
  * the trace between two lap boundaries is exactly one lap, and that is what
    gets published as the circuit outline;
  * every later lap replaces it, which keeps the input colouring current.

Before a full lap exists the live trace is published as it builds, so the panel
shows something useful from the first corner.
"""

from __future__ import annotations

from enum import IntEnum

from .delta import LapTrace, is_out_lap
from .packet import Telemetry


class Input(IntEnum):
    """What the driver was doing at a point, packed small for the wire."""

    COAST = 0
    PARTIAL = 1
    THROTTLE = 2
    BRAKE = 3


#: Metres of travel between recorded points. Below this the trace gains
#: thousands of points that render identically; 3 m still resolves an apex.
MIN_MOVE = 3.0

#: A step larger than this is not driving - it is a race restart, a pit
#: teleport or a track change. Start a fresh trace rather than drawing a line
#: across the map.
JUMP = 200.0

#: A published lap must be at least this long, so a lap counter that ticks
#: twice in quick succession cannot publish a stub as if it were the circuit.
MIN_LAP_LENGTH = 200.0

#: Ring cap. At 3 m spacing this is 18 km, comfortably more than any circuit
#: lap, so a normal lap is never truncated.
MAX_POINTS = 6000

_BRAKE_ON = 0.03
_THROTTLE_ON = 0.03
_THROTTLE_FULL = 0.78


def classify(throttle: float, brake: float) -> Input:
    """Braking wins over throttle: overlap means the driver is still slowing."""
    if brake > _BRAKE_ON:
        return Input.BRAKE
    if throttle > _THROTTLE_FULL:
        return Input.THROTTLE
    if throttle > _THROTTLE_ON:
        return Input.PARTIAL
    return Input.COAST


class TrackMap:
    """A trace of where the car has been, anchored to the start/finish line."""

    def __init__(self) -> None:
        #: Bumped whenever what clients should draw is replaced wholesale -
        #: a completed lap, a restart, a new car. Clients hold their own copy
        #: and only ever receive new points, so they need a signal that says
        #: "throw away what you have" rather than "here is more".
        self.generation = 1

        #: The published outline: one complete lap once we have one, otherwise
        #: the live trace as it builds.
        self.xs: list[float] = []
        self.zs: list[float] = []
        self.inputs: list[int] = []
        self.length = 0.0

        #: True once the outline is a real lap measured line to line.
        self.closed = False
        #: Which lap the published outline came from.
        self.lap_number = 0

        self._pend_x: list[float] = []
        self._pend_z: list[float] = []
        self._pend_s: list[int] = []
        #: Console frame counter at each point. This is the lap clock: it
        #: advances once per simulation frame whether or not the datagram
        #: arrived, so a dropped packet costs a sample but not accuracy.
        self._pend_t: list[int] = []
        self._pend_len = 0.0

        #: The most recently completed lap, with its timing, for delta work.
        self.last_lap: LapTrace | None = None

        self._last: tuple[float, float] | None = None
        self._lap = 0
        self._anchored = False  #: have we crossed a line and started clean?
        self._car_code = 0
        self._dropped = 0

    # ---- ingest ---------------------------------------------------------

    def reset(self) -> None:
        self.generation += 1
        self.xs = []
        self.zs = []
        self.inputs = []
        self.length = 0.0
        self.closed = False
        self.lap_number = 0
        self.last_lap = None
        self._clear_pending()
        self._last = None
        self._anchored = False
        self._dropped = 0

    def _clear_pending(self) -> None:
        self._pend_x = []
        self._pend_z = []
        self._pend_s = []
        self._pend_t = []
        self._pend_len = 0.0

    def feed(self, frame: Telemetry) -> None:
        if frame.car_code != self._car_code:
            car = frame.car_code
            self.reset()
            self._car_code = car
            self._lap = frame.current_lap

        if frame.current_lap != self._lap:
            self._cross_line(frame)
            self._lap = frame.current_lap

        x, _, z = frame.position
        if self._last is None:
            self._append(x, z, frame)
            return

        step = ((x - self._last[0]) ** 2 + (z - self._last[1]) ** 2) ** 0.5
        if step < MIN_MOVE:
            return  # parked, or crawling - do not clutter the trace
        if step > JUMP:
            # Restart, teleport or a new track. Never draw the line across.
            self.reset()
            self._lap = frame.current_lap
            self._append(x, z, frame)
            return

        self._pend_len += step
        self._append(x, z, frame)

        if not self.closed:
            # No complete lap yet, so publish the live trace as it builds -
            # an empty panel until the first line crossing would be worse.
            self.length = self._pend_len

    def _cross_line(self, frame: Telemetry) -> None:
        """The lap counter moved: we are on the start/finish line."""
        if (self._anchored and self._pend_len >= MIN_LAP_LENGTH
                and not is_out_lap(self._lap)):
            # Exactly one lap, measured line to line. This is the circuit.
            self.last_lap = LapTrace(
                number=self._lap,
                xs=list(self._pend_x), zs=list(self._pend_z),
                inputs=list(self._pend_s), ticks=list(self._pend_t),
                lap_ms=frame.last_lap_ms,
            )
            self.xs = list(self._pend_x)
            self.zs = list(self._pend_z)
            self.inputs = list(self._pend_s)
            self.length = self._pend_len
            self.closed = True
            self.lap_number = self._lap
            self.generation += 1
            self._dropped = 0
        else:
            # The lap we attached part-way through starts somewhere arbitrary;
            # drawing it would put the start marker in the middle of a corner.
            self._anchored = True
            if not self.closed:
                self.xs = []
                self.zs = []
                self.inputs = []
                self.length = 0.0
                self.generation += 1
                self._dropped = 0

        self._clear_pending()

    def _append(self, x: float, z: float, frame: Telemetry) -> None:
        state = int(classify(frame.throttle / 255.0, frame.brake / 255.0))
        self._pend_x.append(x)
        self._pend_z.append(z)
        self._pend_s.append(state)
        self._pend_t.append(frame.packet_id)
        self._last = (x, z)
        if len(self._pend_x) > MAX_POINTS:
            self._pend_x.pop(0)
            self._pend_z.pop(0)
            self._pend_s.pop(0)
            self._pend_t.pop(0)

        if not self.closed:
            self.xs.append(x)
            self.zs.append(z)
            self.inputs.append(state)
            if len(self.xs) > MAX_POINTS:
                self.xs.pop(0)
                self.zs.pop(0)
                self.inputs.pop(0)
                self._dropped += 1

    # ---- read -----------------------------------------------------------

    def recent(self, count: int = 200) -> tuple[list[float], list[float]]:
        """The last stretch actually driven, for recognising the circuit.

        Deliberately the pending buffer, not the published outline: once an
        outline is frozen at a lap boundary it stops following the car, and
        matching would freeze with it.
        """
        return self._pend_x[-count:], self._pend_z[-count:]

    @property
    def anchored(self) -> bool:
        """True once a lap boundary has been crossed and the trace is clean.

        Until then the outline starts wherever the dashboard connected, which
        the panel should say rather than implying it is a real lap.
        """
        return self._anchored

    @property
    def total_points(self) -> int:
        """Points ever published this generation, including any dropped.

        Cursors count in this space, so eviction from the ring cannot make a
        client silently re-request points that no longer exist.
        """
        return self._dropped + len(self.xs)

    @property
    def bbox(self) -> tuple[float, float, float, float] | None:
        """(min_x, min_z, max_x, max_z), or None with nothing to draw."""
        if not self.xs:
            return None
        return (min(self.xs), min(self.zs), max(self.xs), max(self.zs))

    def since(self, cursor: int) -> tuple[int, list[float], list[float], list[int]]:
        """Points published after `cursor`, plus the cursor to use next time."""
        start = max(cursor - self._dropped, 0)
        if start >= len(self.xs):
            return self.total_points, [], [], []
        return (
            self.total_points,
            [round(v, 1) for v in self.xs[start:]],
            [round(v, 1) for v in self.zs[start:]],
            self.inputs[start:],
        )
