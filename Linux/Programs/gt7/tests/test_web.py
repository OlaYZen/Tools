"""Web layer tests. No console and no network - a fixture frame is enough."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from gt7 import recorder  # noqa: E402
from gt7.client import GT7Client  # noqa: E402
from gt7.derived import GripEstimator  # noqa: E402
from gt7.packet import decode  # noqa: E402
from gt7.stint import StintTracker  # noqa: E402
from gt7.web.server import (  # noqa: E402
    build_app,
    link_payload,
    stint_payload,
    telemetry_payload,
)

FIXTURE = Path(__file__).parent / "fixtures" / "format_a.bin"


@pytest.fixture(scope="module")
def frame():
    payload = next(iter(recorder.read(FIXTURE)))[1]
    return decode(payload)


@pytest.fixture(scope="module")
def client():
    return GT7Client("192.0.2.1", "A")  # never started


def test_payload_resolves_units_so_the_browser_never_has_to(frame, client):
    body = telemetry_payload(frame, client, GripEstimator())
    # speed arrives in m/s; the browser must receive both display units
    assert body["speed_kph"] == pytest.approx(frame.speed_mps * 3.6)
    assert body["speed_mph"] == pytest.approx(frame.speed_mps * 2.236936)
    # throttle/brake arrive 0-255; the browser must receive 0-1
    assert 0.0 <= body["throttle"] <= 1.0
    assert 0.0 <= body["brake"] <= 1.0
    # boost arrives as absolute pressure; the browser must receive bar
    assert body["engine"]["boost_bar"] == pytest.approx(frame.boost_raw - 1.0)


def test_payload_is_json_safe(frame, client):
    import json

    body = telemetry_payload(frame, client, GripEstimator())
    assert json.loads(json.dumps(body)) == body


def test_delta_is_absent_until_two_laps_exist(frame, client):
    body = telemetry_payload(frame, client, GripEstimator())
    if frame.best_lap_ms <= 0 or frame.last_lap_ms <= 0:
        assert body["lap"]["delta_ms"] is None
    else:
        assert body["lap"]["delta_ms"] == frame.last_lap_ms - frame.best_lap_ms


def test_link_payload_reports_the_served_format_not_the_requested_one(frame):
    asked_b = GT7Client("192.0.2.1", "B")
    body = link_payload(asked_b)
    assert body["requested_format"] == "B"
    assert body["active_format"] is None  # nothing received yet
    assert body["format_mismatch"] is False

    asked_b._ingest(next(iter(recorder.read(FIXTURE)))[1], now=0.0)  # a format A packet
    body = link_payload(asked_b)
    assert body["active_format"] == "A"
    assert body["format_mismatch"] is True


def test_grip_fields_are_null_until_there_is_data(frame, client):
    body = telemetry_payload(frame, client, GripEstimator())
    env = body["environment"]
    assert env["grip_g"] is None
    assert env["grip_relative"] is None
    assert env["grip_confidence"] == "no data"
    # GT7 sends no weather; the only environmental channel is the clock.
    assert set(env) == {"clock", "daylight", "grip_g", "grip_relative",
                        "grip_confidence", "reserved_active"}
    assert env["reserved_active"] is False


def test_daylight_buckets():
    from gt7.web.server import _daylight

    hour = 3_600_000
    assert _daylight(12 * hour) == "day"
    assert _daylight(2 * hour) == "night"
    assert _daylight(18 * hour) == "dusk"


def test_telemetry_endpoint_is_503_before_the_console_speaks():
    app = build_app("192.0.2.1", "A")  # unroutable; no telemetry will arrive
    with TestClient(app) as http:
        assert http.get("/api/link").status_code == 200
        response = http.get("/api/telemetry")
        assert response.status_code == 503
        assert response.json()["detail"] == "no telemetry yet"


def test_page_and_assets_are_served():
    app = build_app("192.0.2.1", "A")
    with TestClient(app) as http:
        page = http.get("/")
        assert page.status_code == 200
        assert "GT7 pit wall" in page.text
        for asset in ("/static/dash.css", "/static/dash.js"):
            assert http.get(asset).status_code == 200


def test_websocket_streams_stint_and_link_without_a_car():
    """Three streams share the socket; both slow ones must arrive unprompted."""
    app = build_app("192.0.2.1", "A")
    with TestClient(app) as http, http.websocket_connect("/ws?hz=20") as socket:
        seen = {}
        for _ in range(6):
            message = socket.receive_json()
            seen[message["type"]] = message
            if {"link", "stint"} <= seen.keys():
                break
        assert {"link", "stint"} <= seen.keys()
        assert seen["link"]["link"]["connected"] is False
        assert seen["stint"]["stint"]["laps"] == []
        # No car has ever sent a frame, so there is nothing to say on the radio.
        assert seen["stint"]["stint"]["callouts"] == []


# ---- stint payload ---------------------------------------------------------


def test_stint_payload_exposes_position_but_never_gaps():
    """The payload must not imply opponent data the protocol does not carry."""
    body = stint_payload(StintTracker())
    assert set(body["race"]) == {"position", "cars", "start_position",
                                 "places_gained", "changes"}
    assert body["race"]["position"] is None
    assert body["race"]["changes"] == []
    # Nothing anywhere claims a gap, interval or opponent.
    flat = repr(body).lower()
    for word in ("gap", "interval", "opponent", "ahead", "behind"):
        assert word not in flat


def test_stint_payload_is_json_safe_when_empty():
    import json

    body = stint_payload(StintTracker())
    assert json.loads(json.dumps(body)) == body
    assert body["laps"] == []
    assert body["callouts"] == []
    assert body["fuel"]["per_lap"] is None


def test_stint_endpoint_answers_before_any_lap():
    app = build_app("192.0.2.1", "A")
    with TestClient(app) as http:
        response = http.get("/api/stint")
        assert response.status_code == 200
        assert response.json()["laps"] == []


# ---- track map -------------------------------------------------------------


def test_track_payload_sends_only_the_delta(tmp_path):
    import dataclasses

    from gt7.library import TrackLibrary
    from gt7.track import TrackMap
    from gt7.web.server import Outline, track_payload

    frame = decode(next(iter(recorder.read(FIXTURE)))[1])
    track = TrackMap()
    library = TrackLibrary(tmp_path / "tracks.json", autoload=False)
    outline = Outline()
    for i in range(40):
        track.feed(dataclasses.replace(frame, position=(i * 5.0, 0.0, 0.0)))

    first = track_payload(track, library, outline, 0)
    assert first["reset"] is True
    assert first["source"] == "live"
    assert len(first["x"]) == 40
    assert first["bbox"] is not None

    for i in range(40, 50):
        track.feed(dataclasses.replace(frame, position=(i * 5.0, 0.0, 0.0)))

    second = track_payload(track, library, outline, first["cursor"])
    assert second["reset"] is False
    assert len(second["x"]) == 10          # only the new ones
    assert len(second["x"]) == len(second["z"]) == len(second["s"])


def test_track_endpoint_is_empty_before_anyone_drives():
    app = build_app("192.0.2.1", "A")
    with TestClient(app) as http:
        body = http.get("/api/track").json()
        assert body["x"] == []
        assert body["bbox"] is None
        assert body["closed"] is False


def test_websocket_sends_a_track_message():
    import dataclasses

    frame = decode(next(iter(recorder.read(FIXTURE)))[1])
    app = build_app("192.0.2.1", "A")
    with TestClient(app) as http:
        for i in range(30):
            app.state.track.feed(dataclasses.replace(frame, position=(i * 5.0, 0.0, 0.0)))
        with http.websocket_connect("/ws?hz=20") as socket:
            seen = {}
            for _ in range(8):
                message = socket.receive_json()
                seen[message["type"]] = message
                if "track" in seen:
                    break
            assert "track" in seen
            body = seen["track"]["track"]
            assert len(body["x"]) == 30
            assert body["reset"] is True


def test_saved_circuit_endpoints(tmp_path):
    import math

    from gt7.library import TrackLibrary

    path = tmp_path / "tracks.json"
    seed = TrackLibrary(path, autoload=False)
    xs, zs, inputs = [], [], []
    for i in range(400):
        a = 2 * math.pi * i / 400
        xs.append(300 * math.cos(a))
        zs.append(300 * math.sin(a))
        inputs.append(2)
    saved = seed.remember(xs, zs, inputs, 2 * math.pi * 300)

    app = build_app("192.0.2.1", "A", library_path=path)
    with TestClient(app) as http:
        listing = http.get("/api/tracks").json()
        assert [t["id"] for t in listing["tracks"]] == [saved.id]

        renamed = http.post(f"/api/tracks/{saved.id}/name", json={"name": "Spa"})
        assert renamed.json()["name"] == "Spa"
        assert http.post("/api/tracks/nope/name", json={"name": "x"}).status_code == 404

        assert http.delete(f"/api/tracks/{saved.id}").status_code == 200
        assert http.get("/api/tracks").json()["tracks"] == []
        assert http.delete(f"/api/tracks/{saved.id}").status_code == 404


def test_a_recognised_circuit_is_served_instead_of_the_live_trace(tmp_path):
    import math

    from gt7.library import MATCH_HOLD, TrackLibrary

    path = tmp_path / "tracks.json"
    seed = TrackLibrary(path, autoload=False)
    xs, zs, inputs = [], [], []
    for i in range(400):
        a = 2 * math.pi * i / 400
        xs.append(300 * math.cos(a))
        zs.append(300 * math.sin(a))
        inputs.append(2)
    seed.remember(xs, zs, inputs, 2 * math.pi * 300)
    seed.rename(seed.tracks[0].id, "Monza")

    app = build_app("192.0.2.1", "A", library_path=path)
    with TestClient(app) as http:
        library = app.state.library
        library.active_id = None
        for _ in range(MATCH_HOLD):
            library.update_match(xs[:150], zs[:150])

        body = http.get("/api/track").json()
        assert body["source"] == "saved"
        assert body["name"] == "Monza"
        assert body["closed"] is True
        assert len(body["x"]) > 100          # the whole outline, no lap needed


def test_cmd_serve_wires_every_option_through(monkeypatch, tmp_path):
    """`serve()` starts uvicorn, so nothing else exercises its signature.

    This gap let `--tracks` reach a `serve()` that had never gained the
    parameter, which only surfaced as a TypeError at launch.
    """
    import argparse

    from gt7 import cli, web

    captured = {}

    def fake_serve(ps5_host, fmt="A", host="0.0.0.0", port=6767, library_path=None):
        captured.update(ps5_host=ps5_host, fmt=fmt, host=host, port=port,
                        library_path=library_path)

    monkeypatch.setattr(web, "serve", fake_serve)
    monkeypatch.setattr(cli, "port_is_free", lambda *a, **k: True)

    args = argparse.Namespace(host="10.0.0.5", format="B", bind="127.0.0.1",
                              port=9999, tracks=str(tmp_path / "t.json"))
    assert cli.cmd_serve(args) == 0
    assert captured["ps5_host"] == "10.0.0.5"
    assert captured["fmt"] == "B"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9999
    assert captured["library_path"] == tmp_path / "t.json"


def test_serve_and_build_app_agree_on_their_parameters():
    import inspect

    from gt7.web.server import build_app, serve

    serve_params = set(inspect.signature(serve).parameters)
    build_params = set(inspect.signature(build_app).parameters)
    # Everything build_app needs must be reachable from serve.
    assert build_params <= serve_params


# ---- time-lost map ---------------------------------------------------------


def test_analysis_says_why_it_has_nothing_yet():
    from gt7.delta import DeltaTracker
    from gt7.stint import StintTracker
    from gt7.web.server import analysis_payload

    body = analysis_payload(DeltaTracker(), StintTracker())
    assert body["available"] is False
    assert "reference" in body["reason"]
    assert body["events"] == []


def test_analysis_reports_the_authoritative_total(tmp_path):
    """The headline delta must come from the comparison, not the thinned map."""
    import math

    from gt7.delta import DeltaTracker, LapTrace
    from gt7.stint import StintTracker
    from gt7.web.server import analysis_payload

    def lap(number, lap_ms, slow=None, factor=1.0):
        xs, zs, inputs, ticks = [], [], [], []
        tick = 0.0
        for i in range(600):
            a = 2 * math.pi * i / 600
            xs.append(400 * math.cos(a))
            zs.append(400 * math.sin(a))
            inputs.append(2)
            ticks.append(int(tick))
            tick += factor if (slow and slow[0] <= i < slow[1]) else 1.0
        return LapTrace(number, xs, zs, inputs, ticks, lap_ms)

    # Numbered from 2: lap 1 is the out-lap and is never counted.
    tracker = DeltaTracker()
    reference = lap(2, 60_000)
    tracker.add_lap(reference)
    slower = lap(3, 0, slow=(200, 275), factor=3.0)
    slower.lap_ms = int(round((slower.ticks[-1] - slower.ticks[0])
                              * reference.ms_per_tick))
    tracker.add_lap(slower)

    body = analysis_payload(tracker, StintTracker())
    assert body["available"] is True
    assert body["lap_number"] == 3
    assert body["reference_number"] == 2
    assert body["total_ms"] == pytest.approx(slower.lap_ms - 60_000, rel=0.01)
    assert len(body["x"]) == len(body["z"]) == len(body["d"])
    assert body["bbox"] is not None
    assert len(body["worst"]) == 3


def test_lockups_reach_the_analysis_with_positions(tmp_path):
    import dataclasses
    import math

    frame = decode(next(iter(recorder.read(FIXTURE)))[1])
    app = build_app("192.0.2.1", "A", library_path=tmp_path / "t.json")
    with TestClient(app) as http:
        pid = 0
        for lap in (1, 2, 3):
            for i in range(600):
                a = 2 * math.pi * i / 600
                pid += 1
                braking = lap == 2 and 210 <= i < 240
                app.state.client.on_frame(dataclasses.replace(
                    frame, position=(400 * math.cos(a), 0.0, 400 * math.sin(a)),
                    current_lap=lap, packet_id=pid, last_lap_ms=60_000,
                    speed_mps=60.0,
                    throttle=0 if braking else 250, brake=220 if braking else 0,
                    wheel_radps=(100.0, 100.0, 181.0, 181.0) if braking
                    else (181.0,) * 4,
                    tyre_radius=(0.33,) * 4))

        body = http.get("/api/analysis").json()
        assert body["events"], "a lock-up should have been recorded"
        for x, z, kind in body["events"]:
            assert kind in (0, 1)
            # On the circle, so the marker is a real place, not a stub.
            assert math.hypot(x, z) == pytest.approx(400, rel=0.05)


def test_the_pit_lane_reaches_a_client_that_connected_first(tmp_path):
    """The lane travels in the track message, which used to be suppressed.

    Once a recognised circuit's outline has been sent there are no new points,
    so the message stopped going out - and the pit lane appearing later never
    reached a browser that was already connected.
    """
    import dataclasses
    import math

    from gt7.library import MATCH_HOLD, TrackLibrary

    frame = decode(next(iter(recorder.read(FIXTURE)))[1])
    path = tmp_path / "tracks.json"
    seed = TrackLibrary(path, autoload=False)
    xs = [400 * math.cos(2 * math.pi * i / 400) for i in range(400)]
    zs = [400 * math.sin(2 * math.pi * i / 400) for i in range(400)]
    seed.remember(xs, zs, [2] * 400, 2 * math.pi * 400)

    app = build_app("192.0.2.1", "A", library_path=path)
    with TestClient(app) as http:
        library = app.state.library
        library.active_id = None
        for _ in range(MATCH_HOLD):
            library.update_match(xs[:150], zs[:150])

        with http.websocket_connect("/ws?hz=20") as socket:
            outline = None
            for _ in range(8):
                message = socket.receive_json()
                if message["type"] == "track":
                    outline = message["track"]
                    break
            assert outline is not None
            assert outline["pit_lane"] == []      # no stop yet

            # A stop happens after the outline was already delivered.
            detector = app.state.pits
            detector.in_pits = True
            from gt7.pits import PitStop
            detector.stops.append(PitStop(
                lap=4, entered_at=0.0,
                path=[(340.0, z * 4.0) for z in range(40)]))

            lane = None
            for _ in range(20):
                message = socket.receive_json()
                if message["type"] == "track" and message["track"]["pit_lane"]:
                    lane = message["track"]["pit_lane"]
                    break
            assert lane is not None, "the lane never reached the client"
            assert len(lane) == 40
