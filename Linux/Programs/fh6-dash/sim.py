"""
Test simulator: streams realistic fake FH6 telemetry so you can try the
dashboard without the game. Models an engine torque curve, gear ratios, and a
repeating lap of full-throttle straights + trail-braking corners.

    python sim.py            # sends to 127.0.0.1:9999 at 60 Hz
    python sim.py 127.0.0.1 9999
"""

import math
import socket
import sys
import time

import forza

host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
port = int(sys.argv[2]) if len(sys.argv) > 2 else 9999

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
print(f"Sending simulated FH6 telemetry to {host}:{port} at 60 Hz (Ctrl-C to stop)")

MAX_RPM = 7600.0
IDLE_RPM = 950.0
SHIFT_RPM = 7000.0
# engine rpm per (m/s of road speed) for each gear; index 0 unused
GEAR_RPM_PER_MS = [0, 235, 172, 134, 107, 87, 71]
TOP_GEAR = len(GEAR_RPM_PER_MS) - 1


def engine_torque(rpm):
    """A plausible torque curve (Nm): rises to a mid-range peak, tapers off."""
    peak = 520.0 * math.exp(-(((rpm - 4700) / 2600) ** 2))
    return max(120.0, 150.0 + peak)


dt = 1 / 60
t = 0.0
speed = 22.0           # m/s
gear = 2
phase = "straight"     # "straight" | "corner"
phase_t = 0.0
throttle = 1.0
brake = 0.0
steer = 0.0

while True:
    t += dt
    phase_t += dt

    if phase == "straight":
        throttle, brake = 1.0, 0.0
        steer *= 0.8                                   # straighten out
        rpm = speed * GEAR_RPM_PER_MS[gear]
        accel = (14.0 - 1.6 * gear) * throttle         # gear-dependent pull
        speed += accel * dt
        if rpm >= SHIFT_RPM and gear < TOP_GEAR:
            gear += 1                                  # upshift
        if gear == TOP_GEAR and rpm >= SHIFT_RPM - 200:
            phase, phase_t = "corner", 0.0
    else:  # corner: lift, trail-brake in, downshift, turn, power out
        throttle = max(0.0, (phase_t - 2.6) / 1.0)     # back to power late
        brake = max(0.0, 1.0 - phase_t / 2.4)          # trail off the brake
        steer = math.sin(min(phase_t, 3.2) / 3.2 * math.pi) * 0.85
        speed += (-18.0 * brake - 0.5) * dt
        speed = max(20.0, speed)
        rpm = speed * GEAR_RPM_PER_MS[gear]
        while rpm < 3200 and gear > 2:                 # downshift
            gear -= 1
            rpm = speed * GEAR_RPM_PER_MS[gear]
        if phase_t > 3.6:
            phase = "straight"

    rpm = max(IDLE_RPM, min(MAX_RPM, speed * GEAR_RPM_PER_MS[gear]))
    tq = engine_torque(rpm)
    power_w = tq * rpm * 2 * math.pi / 60.0

    slip_ratio = brake * 0.9 + (throttle if gear <= 3 else 0) * 0.3
    slip_angle = abs(steer) * 1.25
    combined_f = math.hypot(slip_ratio * 0.7, slip_angle)
    combined_r = math.hypot(slip_ratio, slip_angle * 0.8)
    lat = steer
    lon = (throttle * 0.6 - brake)

    frame = {
        "IsRaceOn": 1,
        "TimestampMS": int(t * 1000) & 0xFFFFFFFF,
        "EngineMaxRpm": MAX_RPM,
        "EngineIdleRpm": IDLE_RPM,
        "CurrentEngineRpm": rpm,
        "AccelerationX": lat * 13.0,
        "AccelerationZ": lon * 11.0,
        "Speed": speed,
        "Power": power_w,
        "Torque": tq,
        "Boost": (rpm / MAX_RPM) * 16 * throttle,
        "Fuel": 0.8,
        "Gear": gear,
        "Accel": int(throttle * 255),
        "Brake": int(brake * 255),
        "Steer": int(steer * 110),
        "RacePosition": 3,
        "LapNumber": int(t // 40),
        "BestLap": 92.531,
        "LastLap": 95.012,
        "CurrentLap": t % 100,
        "CurrentRaceTime": t,
        "CarPerformanceIndex": 815,
        "NormalizedSuspensionTravelFrontLeft": 0.5 - lat * 0.3 - lon * 0.2,
        "NormalizedSuspensionTravelFrontRight": 0.5 + lat * 0.3 - lon * 0.2,
        "NormalizedSuspensionTravelRearLeft": 0.5 - lat * 0.3 + lon * 0.2,
        "NormalizedSuspensionTravelRearRight": 0.5 + lat * 0.3 + lon * 0.2,
        "SuspensionTravelMetersFrontLeft": 0.08 + lat * 0.04,
        "SuspensionTravelMetersFrontRight": 0.08 - lat * 0.04,
        "SuspensionTravelMetersRearLeft": 0.08 + lat * 0.04,
        "SuspensionTravelMetersRearRight": 0.08 - lat * 0.04,
        "TireTempFrontLeft": 70 + combined_f * 22 + max(0, lat) * 10,
        "TireTempFrontRight": 70 + combined_f * 22 + max(0, -lat) * 10,
        "TireTempRearLeft": 78 + combined_r * 20 + max(0, lat) * 8,
        "TireTempRearRight": 78 + combined_r * 20 + max(0, -lat) * 8,
        "TireSlipRatioFrontLeft": slip_ratio * 0.7,
        "TireSlipRatioFrontRight": slip_ratio * 0.7,
        "TireSlipRatioRearLeft": slip_ratio,
        "TireSlipRatioRearRight": slip_ratio,
        "TireSlipAngleFrontLeft": slip_angle,
        "TireSlipAngleFrontRight": slip_angle,
        "TireSlipAngleRearLeft": slip_angle * 0.8,
        "TireSlipAngleRearRight": slip_angle * 0.8,
        "TireCombinedSlipFrontLeft": combined_f,
        "TireCombinedSlipFrontRight": combined_f,
        "TireCombinedSlipRearLeft": combined_r,
        "TireCombinedSlipRearRight": combined_r,
    }
    sock.sendto(forza.pack(frame), (host, port))
    time.sleep(dt)
