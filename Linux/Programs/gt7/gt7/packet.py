"""Decoder for the 296-byte GT7 Simulator Interface packet ("format A").

Offsets below were verified live against a PS5 running GT7 (see README for
the evidence trail).  Every field is little-endian; the struct format string
`_FMT` is a single contiguous description of the whole 0x128-byte body, so
the parse is one `struct.unpack` with no manual seeking.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntFlag

from .crypto import decrypt, format_for

PACKET_SIZE = 296
EXT_SIZE = 316  # format B: the 296-byte body plus five extra floats


class Flags(IntFlag):
    """Bitfield at offset 0x8E."""

    #: Named as the community names it, but observed false during a race at
    #: 250 km/h - see `Telemetry.on_track`. Prefer `Telemetry.is_moving`.
    CAR_ON_TRACK = 1 << 0
    PAUSED = 1 << 1
    LOADING = 1 << 2
    IN_GEAR = 1 << 3
    HAS_TURBO = 1 << 4
    REV_LIMITER = 1 << 5
    HANDBRAKE = 1 << 6
    LIGHTS = 1 << 7
    HIGH_BEAM = 1 << 8
    LOW_BEAM = 1 << 9
    ASM = 1 << 10
    TCS = 1 << 11


# One contiguous little-endian description of offsets 0x000 -> 0x128.
_FMT = (
    "<"
    "I"      # 0x000 magic "0S7G"
    "3f"     # 0x004 position x/y/z (m, world)
    "3f"     # 0x010 velocity x/y/z (m/s, world)
    "4f"     # 0x01C rotation i/j/k + orientation-to-north
    "3f"     # 0x02C angular velocity x/y/z (rad/s)
    "f"      # 0x038 ride height (m)
    "f"      # 0x03C engine rpm
    "I"      # 0x040 nonce seed (plaintext garbage - it is the clear-text IV)
    "f"      # 0x044 fuel level
    "f"      # 0x048 fuel capacity (0.0 on electric cars)
    "f"      # 0x04C speed (m/s)
    "f"      # 0x050 turbo boost (x100 kPa; bar = value - 1.0)
    "f"      # 0x054 oil pressure
    "f"      # 0x058 water temp (hardcoded 85.0 by the game)
    "f"      # 0x05C oil temp (hardcoded 110.0 by the game)
    "4f"     # 0x060 tyre surface temp FL/FR/RL/RR
    "I"      # 0x070 packet id (monotonic, ~60/s)
    "H"      # 0x074 current lap
    "H"      # 0x076 laps in race
    "i"      # 0x078 best lap (ms, -1 if none)
    "i"      # 0x07C last lap (ms, -1 if none)
    "i"      # 0x080 time of day (ms since midnight)
    "h"      # 0x084 pre-race grid position
    "h"      # 0x086 cars in race
    "h"      # 0x088 rev-warning rpm
    "h"      # 0x08A rev-limiter rpm
    "H"      # 0x08C calculated top speed (km/h)
    "H"      # 0x08E flags
    "B"      # 0x090 gear nibbles: low = current, high = suggested
    "B"      # 0x091 throttle 0-255
    "B"      # 0x092 brake 0-255
    "B"      # 0x093 padding
    "3f"     # 0x094 road plane normal x/y/z
    "f"      # 0x0A0 road plane distance
    "4f"     # 0x0A4 wheel angular speed FL/FR/RL/RR (rad/s)
    "4f"     # 0x0B4 tyre radius FL/FR/RL/RR (m)
    "4f"     # 0x0C4 suspension travel FL/FR/RL/RR
    "8f"     # 0x0D4 reserved / unused (all zero in observed builds)
    "f"      # 0x0F4 clutch pedal 0-1
    "f"      # 0x0F8 clutch engagement 0-1
    "f"      # 0x0FC rpm after clutch (gearbox input shaft)
    "f"      # 0x100 transmission top-speed ratio
    "8f"     # 0x104 gear ratios (unused gears read 0.0)
    "I"      # 0x124 car code
)
_STRUCT = struct.Struct(_FMT)
assert _STRUCT.size == PACKET_SIZE, _STRUCT.size

# Format B appends five floats at 0x128.  Steering is confirmed against a real
# wheel; the other four are named from their behaviour and community convention
# and are flagged unverified in `docs/protocol.md`.
_EXT_FMT = (
    "<"
    "f"   # 0x128 steering, radians. Raw sign is positive-for-LEFT; parse()
          #       flips it so Telemetry.wheel_rotation is positive-for-right.
    "f"   # 0x12C unnamed - tracks yaw rate; motion-rig "sway" candidate
    "f"   # 0x130 unnamed - zero in all captures so far
    "f"   # 0x134 unnamed - tracks speed; motion-rig "surge" candidate
    "f"   # 0x138 unnamed - zero in all captures so far
)
_EXT_STRUCT = struct.Struct(_EXT_FMT)
assert _EXT_STRUCT.size == EXT_SIZE - PACKET_SIZE, _EXT_STRUCT.size

_CORNERS = ("FL", "FR", "RL", "RR")


@dataclass(slots=True)
class Telemetry:
    """One decoded frame. Raw units are as the game sends them."""

    position: tuple[float, float, float]
    velocity: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    angular_velocity: tuple[float, float, float]
    ride_height: float
    rpm: float
    fuel_level: float
    fuel_capacity: float
    speed_mps: float
    boost_raw: float
    oil_pressure: float
    water_temp: float
    oil_temp: float
    tyre_temp: tuple[float, float, float, float]
    packet_id: int
    current_lap: int
    total_laps: int
    best_lap_ms: int
    last_lap_ms: int
    time_of_day_ms: int
    grid_position: int
    cars_in_race: int
    rpm_warning: int
    rpm_limiter: int
    top_speed_kph: int
    flags: Flags
    gear: int
    suggested_gear: int
    throttle: int
    brake: int
    road_plane: tuple[float, float, float]
    road_plane_distance: float
    wheel_radps: tuple[float, float, float, float]
    tyre_radius: tuple[float, float, float, float]
    suspension: tuple[float, float, float, float]
    reserved: tuple[float, ...]
    clutch: float
    clutch_engagement: float
    rpm_after_clutch: float
    transmission_top_speed: float
    gear_ratios: tuple[float, ...]
    car_code: int

    #: Format B only (None on format A).  Positive = right, which is the
    #: opposite of the raw packet's sign - see parse().
    wheel_rotation: float | None = None
    #: The unflipped value straight off the wire, kept so protocol work does
    #: not have to reason through the correction.
    raw_wheel_rotation: float | None = None
    ext_unknown_12c: float | None = None
    ext_unknown_130: float | None = None
    ext_unknown_134: float | None = None
    ext_unknown_138: float | None = None

    @property
    def has_extended(self) -> bool:
        return self.wheel_rotation is not None

    # ---- derived conveniences -------------------------------------------

    @property
    def speed_kph(self) -> float:
        return self.speed_mps * 3.6

    @property
    def speed_mph(self) -> float:
        return self.speed_mps * 2.236936

    @property
    def boost_bar(self) -> float:
        """Boost in bar relative to atmospheric (negative = vacuum)."""
        return self.boost_raw - 1.0

    @property
    def throttle_pct(self) -> float:
        return self.throttle / 255.0 * 100.0

    @property
    def brake_pct(self) -> float:
        return self.brake / 255.0 * 100.0

    @property
    def fuel_pct(self) -> float:
        if self.fuel_capacity <= 0:
            return 100.0  # EV / fuel-less car
        return self.fuel_level / self.fuel_capacity * 100.0

    @property
    def is_ev(self) -> bool:
        return self.fuel_capacity <= 0.0

    @property
    def gear_label(self) -> str:
        """Gear nibble 0 is reverse, 15 is neutral, 1..n are the forward gears."""
        return {0: "R", 15: "N"}.get(self.gear, str(self.gear))

    @property
    def suggested_gear_label(self) -> str:
        """15 in the high nibble means "no suggestion"."""
        return "" if self.suggested_gear == 15 else {0: "R"}.get(
            self.suggested_gear, str(self.suggested_gear)
        )

    @property
    def on_track(self) -> bool:
        """Flag bit 0. Do not trust this to mean "the car is driving".

        Measured false throughout a race at 208-249 km/h, so it tracks
        something narrower than its community name suggests - most likely
        whether *you* are driving, as opposed to watching a replay. Use
        `is_moving` to decide whether motion data is meaningful.
        """
        return bool(self.flags & Flags.CAR_ON_TRACK)

    @property
    def is_moving(self) -> bool:
        """The car is under way and the sim is running.

        Derived from motion rather than from flag bit 0, which is unreliable
        for this purpose.
        """
        return not self.paused and self.speed_mps > 0.5

    @property
    def paused(self) -> bool:
        return bool(self.flags & Flags.PAUSED)

    @property
    def tyre_slip(self) -> tuple[float, float, float, float]:
        """Per-wheel slip ratio: surface speed / chassis speed.

        >1 means the wheel is spinning up, <1 means it is locking.  Undefined
        at a standstill, where we report 1.0 (no slip).
        """
        if self.speed_mps < 0.5:
            return (1.0, 1.0, 1.0, 1.0)
        return tuple(  # type: ignore[return-value]
            abs(w * r) / self.speed_mps
            for w, r in zip(self.wheel_radps, self.tyre_radius)
        )

    @property
    def active_gear_ratios(self) -> tuple[float, ...]:
        return tuple(r for r in self.gear_ratios if r > 0.0)

    def corner(self, attr: str) -> dict[str, float]:
        """Zip a 4-tuple field with FL/FR/RL/RR labels."""
        return dict(zip(_CORNERS, getattr(self, attr)))


def parse(plain: bytes) -> Telemetry:
    """Parse an already-decrypted body (296 B format A, or 316 B format B)."""
    v = _STRUCT.unpack_from(plain, 0)
    gear_bits = v[40]
    frame = Telemetry(
        position=v[1:4],
        velocity=v[4:7],
        rotation=v[7:11],
        angular_velocity=v[11:14],
        ride_height=v[14],
        rpm=v[15],
        # v[16] is the clear-text nonce seed - not telemetry, skipped.
        fuel_level=v[17],
        fuel_capacity=v[18],
        speed_mps=v[19],
        boost_raw=v[20],
        oil_pressure=v[21],
        water_temp=v[22],
        oil_temp=v[23],
        tyre_temp=v[24:28],
        packet_id=v[28],
        current_lap=v[29],
        total_laps=v[30],
        best_lap_ms=v[31],
        last_lap_ms=v[32],
        time_of_day_ms=v[33],
        grid_position=v[34],
        cars_in_race=v[35],
        rpm_warning=v[36],
        rpm_limiter=v[37],
        top_speed_kph=v[38],
        flags=Flags(v[39] & 0x0FFF),
        gear=gear_bits & 0x0F,
        suggested_gear=(gear_bits >> 4) & 0x0F,
        throttle=v[41],
        brake=v[42],
        road_plane=v[44:47],
        road_plane_distance=v[47],
        wheel_radps=v[48:52],
        tyre_radius=v[52:56],
        suspension=v[56:60],
        reserved=v[60:68],
        clutch=v[68],
        clutch_engagement=v[69],
        rpm_after_clutch=v[70],
        transmission_top_speed=v[71],
        gear_ratios=v[72:80],
        car_code=v[80],
    )
    if len(plain) >= EXT_SIZE:
        (
            raw_steering,
            frame.ext_unknown_12c,
            frame.ext_unknown_130,
            frame.ext_unknown_134,
            frame.ext_unknown_138,
        ) = _EXT_STRUCT.unpack_from(plain, PACKET_SIZE)
        # GT7 signs steering the opposite way round to the convention every
        # other telemetry tool uses: the raw field goes *positive* when the
        # driver turns left. Confirmed live against a wheel - a dashboard fed
        # the raw value shows left inputs deflecting right. Flip it once here,
        # so every consumer downstream gets positive = right and nobody has to
        # remember the quirk.
        frame.raw_wheel_rotation = raw_steering
        frame.wheel_rotation = -raw_steering
    return frame


def decode(datagram: bytes) -> Telemetry:
    """Decrypt and parse one raw UDP datagram (format auto-detected by size)."""
    return parse(decrypt(datagram))


def format_lap_time(ms: int) -> str:
    """Render a lap time; the game uses -1 for 'no time set'."""
    if ms is None or ms < 0:
        return "--:--.---"
    minutes, rem = divmod(ms, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{minutes:d}:{seconds:02d}.{millis:03d}"


def format_time_of_day(ms: int) -> str:
    total = max(ms, 0) // 1000
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours % 24:02d}:{minutes:02d}:{seconds:02d}"
