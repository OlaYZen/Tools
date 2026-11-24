"""Tests run against a recorded capture, so no console is needed."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from gt7 import analyze, crypto, recorder
from gt7.packet import EXT_SIZE, PACKET_SIZE, Flags, decode, format_lap_time, parse

FIXTURE = Path(__file__).parent / "fixtures" / "format_a.bin"


@pytest.fixture(scope="module")
def datagrams() -> list[bytes]:
    return [payload for _, payload in recorder.read(FIXTURE)]


@pytest.fixture(scope="module")
def frames(datagrams: list[bytes]) -> list[bytes]:
    return [crypto.decrypt(d) for d in datagrams]


def test_capture_is_format_a(datagrams):
    assert datagrams
    assert {len(d) for d in datagrams} == {PACKET_SIZE}


def test_every_packet_decrypts_and_carries_the_magic(frames):
    for plain in frames:
        assert struct.unpack_from("<I", plain, 0)[0] == crypto.MAGIC


def test_hardcoded_temperatures_are_the_decrypt_oracle(frames):
    # The game emits these as constants; they double as a correctness check
    # independent of the magic.
    for plain in frames:
        assert struct.unpack_from("<ff", plain, 0x58) == (85.0, 110.0)


def test_packet_id_increments_by_one(frames):
    ids = [parse(p).packet_id for p in frames]
    assert all(b - a == 1 for a, b in zip(ids, ids[1:]))


def test_wrong_xor_constant_is_rejected(datagrams):
    # Format B's constant must not decode a format A packet - this is the
    # one-letter difference that makes decryption fail silently otherwise.
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(datagrams[0], iv_xor=crypto.FORMAT_B.iv_xor)


def test_format_is_detected_from_length(datagrams):
    assert crypto.format_for(datagrams[0]) is crypto.FORMAT_A
    assert crypto.format_for(b"\x00" * EXT_SIZE) is crypto.FORMAT_B


def test_uncracked_format_reports_why(datagrams):
    with pytest.raises(crypto.DecryptionError, match="not decryptable"):
        crypto.decrypt(b"\x00" * crypto.FORMAT_TILDE.size)


def test_short_packet_is_rejected():
    with pytest.raises(crypto.DecryptionError, match="too short"):
        crypto.decrypt(b"\x00" * 8)


def test_parsed_values_are_physically_sane(datagrams):
    t = decode(datagrams[0])
    assert t.water_temp == 85.0 and t.oil_temp == 110.0
    assert 0 <= t.rpm < 20_000
    assert 0 <= t.speed_kph < 500
    assert 0 <= t.throttle <= 255 and 0 <= t.brake <= 255
    assert len(t.gear_ratios) == 8
    assert t.active_gear_ratios == tuple(sorted(t.active_gear_ratios, reverse=True))
    assert t.car_code > 0
    assert not t.has_extended  # format A carries no extension


def test_gear_nibbles():
    plain = bytearray(crypto.decrypt(next(recorder.read(FIXTURE))[1]))
    for raw, gear, suggested in ((0xF1, 1, ""), (0xF0, 0, ""), (0x40, 0, "4"), (0x35, 5, "3")):
        plain[0x90] = raw
        t = parse(bytes(plain))
        assert t.gear == gear
        assert t.suggested_gear_label == suggested
    plain[0x90] = 0xFF
    assert parse(bytes(plain)).gear_label == "N"


def test_flags_decode():
    assert Flags(0b11001) == (Flags.CAR_ON_TRACK | Flags.IN_GEAR | Flags.HAS_TURBO)


def test_lap_time_formatting():
    assert format_lap_time(-1) == "--:--.---"
    assert format_lap_time(103_332) == "1:43.332"
    assert format_lap_time(0) == "0:00.000"


def test_slip_is_neutral_at_standstill(datagrams):
    t = decode(datagrams[0])
    if t.speed_mps < 0.5:
        assert t.tyre_slip == (1.0, 1.0, 1.0, 1.0)


def test_format_a_has_no_unmapped_bytes():
    assert analyze.unmapped_offsets(PACKET_SIZE) == []


def test_survey_identifies_the_packet_counter(frames):
    records = {r["offset"]: r for r in analyze.survey(frames)}
    assert records[0x70]["kind"] == "counter(+1)"
    assert records[0x58]["kind"] == "constant"  # water temp


def test_round_trip_through_the_recorder(tmp_path, datagrams):
    path = tmp_path / "rt.bin"
    with path.open("wb") as fh:
        fh.write(recorder._HEADER.pack(recorder.MAGIC, ord("A")))
        for i, payload in enumerate(datagrams[:5]):
            fh.write(recorder._FRAME.pack(i * 0.016, len(payload)))
            fh.write(payload)
    assert [p for _, p in recorder.read(path)] == datagrams[:5]


def test_recorder_rejects_foreign_files(tmp_path):
    path = tmp_path / "junk.bin"
    path.write_bytes(b"NOTGT7CAPTURE" * 4)
    with pytest.raises(ValueError, match="not a GT7 capture"):
        list(recorder.read(path))


def test_hexdump_annotates_known_fields(frames):
    dump = analyze.hexdump(frames[0])
    assert "engine rpm" in dump
    assert "IV seed (clear)" in dump
    assert dump.startswith("0000  30 53 37 47")


def test_client_reports_the_format_actually_served(datagrams):
    """A client asking for B but served A must say so, not mislabel the data."""
    from gt7.client import GT7Client

    client = GT7Client("192.0.2.1", "B")  # never started; no socket needed
    assert client.active_format is None
    assert not client.format_mismatch

    client._ingest(datagrams[0], now=0.0)  # a format A packet
    assert client.active_format is crypto.FORMAT_A
    assert client.format_mismatch is True
    assert client.latest is not None
    assert client.decode_errors == 0


def test_client_counts_dropped_packets(datagrams):
    from gt7.client import GT7Client

    client = GT7Client("192.0.2.1", "A")
    client._ingest(datagrams[0], now=0.0)
    client._ingest(datagrams[3], now=0.1)  # skipped two
    assert client.dropped == 2


# ---- weather / environment -------------------------------------------------


def test_reserved_block_is_zero_throughout(frames):
    """The only spare space in format A. If GT7 ever uses it, this fails."""
    for plain in frames:
        assert plain[0xD4:0xF4] == bytes(32)


def test_no_unexplained_bytes_that_could_hold_weather():
    # The counting argument in docs/weather.md depends on this staying true.
    assert analyze.unmapped_offsets(PACKET_SIZE) == []


def test_diff_detects_a_conditionally_populated_field(frames):
    """Plant a wetness-like value in the reserved block; diff must flag it."""
    wet = []
    for i, plain in enumerate(frames):
        buf = bytearray(plain)
        struct.pack_into("<f", buf, 0xD4, 0.35 + i * 0.001)
        wet.append(bytes(buf))

    rows = analyze.compare(frames, wet)
    assert [r["offset"] for r in rows] == [0xD4]
    assert rows[0]["verdict"] == "activated"


def test_diff_is_quiet_when_nothing_changed(frames):
    assert analyze.compare(frames, frames) == []


def test_grip_estimator_ignores_a_parked_car(datagrams):
    from gt7.derived import GripEstimator

    est = GripEstimator()
    for i, payload in enumerate(datagrams):
        assert est.feed(decode(payload), i / 60.0) is None
    assert est.recent_peak_g is None
    assert est.relative is None
    assert est.confidence == "no data"


class _FakeFrame:
    on_track = True
    paused = False
    car_code = 42
    angular_velocity = (0.0, 0.0, 0.0)

    def __init__(self, speed: float) -> None:
        self.speed_mps = speed


def _steady_braking(spike_g: float = 1.0, frames_n: int = 600):
    from gt7.derived import GripEstimator

    est = GripEstimator()
    speed, t = 80.0, 0.0
    for i in range(frames_n):
        g = spike_g if i == frames_n // 2 else 1.0
        speed = max(15.0, speed - 9.80665 / 60 * g)
        t += 1 / 60
        est.feed(_FakeFrame(speed), t)
    return est


def test_grip_estimator_measures_a_known_deceleration():
    est = _steady_braking()
    assert est.recent_peak_g == pytest.approx(1.0, abs=0.05)
    assert est.relative == pytest.approx(1.0, abs=0.05)
    assert est.confidence == "ok"


def test_grip_baseline_survives_a_single_violent_frame():
    """A kerb strike must not become the car's grip baseline forever."""
    clean = _steady_braking(spike_g=1.0).session_best_g
    spiked = _steady_braking(spike_g=3.0).session_best_g
    assert spiked == pytest.approx(clean, abs=0.05)


def test_grip_resets_when_the_car_changes():
    from gt7.derived import GripEstimator

    est = GripEstimator()
    for i in range(200):
        est.feed(_FakeFrame(80.0 - i * 0.1), i / 60.0)
    assert est.recent_peak_g is not None

    class Other(_FakeFrame):
        car_code = 999

    est.feed(Other(80.0), 200 / 60.0)
    assert est.recent_peak_g is None  # history cleared for the new car


def test_steering_sign_is_flipped_to_positive_is_right(datagrams):
    """GT7 signs steering positive-for-left; we expose positive-for-right.

    Confirmed against a real wheel: a dashboard fed the raw value showed left
    inputs deflecting the meter right. If this flip is ever removed, the meter
    silently mirrors again.
    """
    from gt7.packet import EXT_SIZE

    plain = bytearray(crypto.decrypt(datagrams[0]))
    plain.extend(bytes(EXT_SIZE - len(plain)))  # promote to a format B body

    struct.pack_into("<f", plain, 0x128, 0.75)   # raw positive = driver turned LEFT
    frame = parse(bytes(plain))
    assert frame.raw_wheel_rotation == pytest.approx(0.75)
    assert frame.wheel_rotation == pytest.approx(-0.75)   # negative = left

    struct.pack_into("<f", plain, 0x128, -0.75)  # raw negative = turned RIGHT
    frame = parse(bytes(plain))
    assert frame.wheel_rotation == pytest.approx(0.75)    # positive = right


def test_format_a_has_no_steering_at_all(datagrams):
    frame = decode(datagrams[0])
    assert frame.wheel_rotation is None
    assert frame.raw_wheel_rotation is None
