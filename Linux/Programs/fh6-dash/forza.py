"""
Forza Horizon 6 "Data Out" telemetry packet parser.

The game streams one-way UDP packets at the game's frame rate. The packet is a
fixed 324-byte little-endian struct. This module decodes it into a plain dict.

Layout taken from the official FH6 "Data Out" documentation. The only difference
from Forza Motorsport's "Dash" format is three extra fields inserted after
NumCylinders (CarGroup, SmashableVelDiff, SmashableMass) and the absence of the
TireWear / TrackOrdinal fields.
"""

import struct

# (name, struct_format_char) in exact packet order.
#   i = S32, I = U32, f = F32, H = U16, B = U8, b = S8
_FIELDS = [
    ("IsRaceOn", "i"),
    ("TimestampMS", "I"),
    ("EngineMaxRpm", "f"),
    ("EngineIdleRpm", "f"),
    ("CurrentEngineRpm", "f"),
    ("AccelerationX", "f"),
    ("AccelerationY", "f"),
    ("AccelerationZ", "f"),
    ("VelocityX", "f"),
    ("VelocityY", "f"),
    ("VelocityZ", "f"),
    ("AngularVelocityX", "f"),
    ("AngularVelocityY", "f"),
    ("AngularVelocityZ", "f"),
    ("Yaw", "f"),
    ("Pitch", "f"),
    ("Roll", "f"),
    ("NormalizedSuspensionTravelFrontLeft", "f"),
    ("NormalizedSuspensionTravelFrontRight", "f"),
    ("NormalizedSuspensionTravelRearLeft", "f"),
    ("NormalizedSuspensionTravelRearRight", "f"),
    ("TireSlipRatioFrontLeft", "f"),
    ("TireSlipRatioFrontRight", "f"),
    ("TireSlipRatioRearLeft", "f"),
    ("TireSlipRatioRearRight", "f"),
    ("WheelRotationSpeedFrontLeft", "f"),
    ("WheelRotationSpeedFrontRight", "f"),
    ("WheelRotationSpeedRearLeft", "f"),
    ("WheelRotationSpeedRearRight", "f"),
    ("WheelOnRumbleStripFrontLeft", "i"),
    ("WheelOnRumbleStripFrontRight", "i"),
    ("WheelOnRumbleStripRearLeft", "i"),
    ("WheelOnRumbleStripRearRight", "i"),
    ("WheelInPuddleFrontLeft", "i"),
    ("WheelInPuddleFrontRight", "i"),
    ("WheelInPuddleRearLeft", "i"),
    ("WheelInPuddleRearRight", "i"),
    ("SurfaceRumbleFrontLeft", "f"),
    ("SurfaceRumbleFrontRight", "f"),
    ("SurfaceRumbleRearLeft", "f"),
    ("SurfaceRumbleRearRight", "f"),
    ("TireSlipAngleFrontLeft", "f"),
    ("TireSlipAngleFrontRight", "f"),
    ("TireSlipAngleRearLeft", "f"),
    ("TireSlipAngleRearRight", "f"),
    ("TireCombinedSlipFrontLeft", "f"),
    ("TireCombinedSlipFrontRight", "f"),
    ("TireCombinedSlipRearLeft", "f"),
    ("TireCombinedSlipRearRight", "f"),
    ("SuspensionTravelMetersFrontLeft", "f"),
    ("SuspensionTravelMetersFrontRight", "f"),
    ("SuspensionTravelMetersRearLeft", "f"),
    ("SuspensionTravelMetersRearRight", "f"),
    ("CarOrdinal", "i"),
    ("CarClass", "i"),
    ("CarPerformanceIndex", "i"),
    ("DrivetrainType", "i"),
    ("NumCylinders", "i"),
    # --- FH6-specific fields (not in Forza Motorsport) ---
    ("CarGroup", "I"),
    ("SmashableVelDiff", "f"),
    ("SmashableMass", "f"),
    # -----------------------------------------------------
    ("PositionX", "f"),
    ("PositionY", "f"),
    ("PositionZ", "f"),
    ("Speed", "f"),
    ("Power", "f"),
    ("Torque", "f"),
    ("TireTempFrontLeft", "f"),
    ("TireTempFrontRight", "f"),
    ("TireTempRearLeft", "f"),
    ("TireTempRearRight", "f"),
    ("Boost", "f"),
    ("Fuel", "f"),
    ("DistanceTraveled", "f"),
    ("BestLap", "f"),
    ("LastLap", "f"),
    ("CurrentLap", "f"),
    ("CurrentRaceTime", "f"),
    ("LapNumber", "H"),
    ("RacePosition", "B"),
    ("Accel", "B"),
    ("Brake", "B"),
    ("Clutch", "B"),
    ("HandBrake", "B"),
    ("Gear", "B"),
    ("Steer", "b"),
    ("NormalizedDrivingLine", "b"),
    ("NormalizedAIBrakeDifference", "b"),
]

FIELD_NAMES = [name for name, _ in _FIELDS]

# "<" = little-endian, standard sizes, no alignment padding.
# A trailing pad byte ("x") brings the total from 323 -> 324 bytes.
_STRUCT = struct.Struct("<" + "".join(fmt for _, fmt in _FIELDS) + "x")
PACKET_SIZE = _STRUCT.size  # 324

assert PACKET_SIZE == 324, f"expected 324-byte packet, got {PACKET_SIZE}"


def parse(data: bytes) -> dict:
    """Decode a raw FH6 telemetry packet into {field_name: value}.

    Raises ValueError if the packet is not the expected length.
    """
    if len(data) != PACKET_SIZE:
        raise ValueError(
            f"unexpected packet size {len(data)} bytes (expected {PACKET_SIZE})"
        )
    values = _STRUCT.unpack(data)
    return dict(zip(FIELD_NAMES, values))


def pack(values: dict) -> bytes:
    """Inverse of parse(): build a 324-byte packet from a field dict.

    Missing fields default to 0. Useful for the test simulator.
    """
    ordered = [values.get(name, 0) for name in FIELD_NAMES]
    return _STRUCT.pack(*ordered)
