"""FastAPI server for the GT7 web dashboard.

The console pushes UDP at 60 Hz into a background thread (`GT7Client`), which
keeps only the newest frame.  The WebSocket loop samples that slot rather than
consuming a queue: telemetry is a *current value*, not a log, so a slow client
should see the latest frame on reconnect, never a backlog of stale ones.

Frames are only sent when `packet_id` advances, so a browser asking for 120 Hz
still receives the console's true 60.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..client import GT7Client, PortBusyError
from ..crypto import BY_NAME
from ..derived import GripEstimator
from ..stint import StintTracker
from ..delta import DeltaTracker, bucket
from ..library import TrackLibrary
from ..pits import ON_LINE_METRES, PitDetector
from ..track import TrackMap
from ..packet import Flags, Telemetry, format_time_of_day

STATIC = Path(__file__).parent / "static"

#: Cap on how fast a client may ask to be updated.  The console only produces
#: 60 frames a second; anything above this is wasted wakeups.
MAX_HZ = 60.0
MIN_HZ = 1.0


def _daylight(time_of_day_ms: int) -> str:
    hours = (max(time_of_day_ms, 0) // 3_600_000) % 24
    if 6 <= hours < 18:
        return "day"
    if hours in (5, 18, 19):
        return "dusk"
    return "night"


def telemetry_payload(t: Telemetry, client: GT7Client, grip: GripEstimator) -> dict:
    """One frame, shaped for the browser.

    Units are resolved here rather than in JavaScript so the display layer
    never has to know that speed arrives in m/s or boost as absolute pressure.
    """
    delta_ms = None
    if t.best_lap_ms > 0 and t.last_lap_ms > 0:
        delta_ms = t.last_lap_ms - t.best_lap_ms

    return {
        "packet_id": t.packet_id,
        "car_code": t.car_code,
        "speed_kph": t.speed_kph,
        "speed_mph": t.speed_mph,
        "rpm": t.rpm,
        "rpm_warning": t.rpm_warning,
        "rpm_limiter": t.rpm_limiter,
        "top_speed_kph": t.top_speed_kph,
        "gear": t.gear,
        "gear_label": t.gear_label,
        "suggested_gear": t.suggested_gear_label,
        "throttle": t.throttle / 255.0,
        "brake": t.brake / 255.0,
        "clutch": t.clutch,
        "clutch_engagement": t.clutch_engagement,
        "rpm_after_clutch": t.rpm_after_clutch,
        "steering": t.wheel_rotation,
        "lap": {
            "current": t.current_lap,
            "total": t.total_laps,
            "best_ms": t.best_lap_ms,
            "last_ms": t.last_lap_ms,
            "delta_ms": delta_ms,
            "position": t.grid_position,
            "cars": t.cars_in_race,
        },
        "tyres": {
            "temp": list(t.tyre_temp),
            "slip": [round(v, 4) for v in t.tyre_slip],
            "suspension": list(t.suspension),
            "radius": list(t.tyre_radius),
        },
        "fuel": {
            "level": t.fuel_level,
            "capacity": t.fuel_capacity,
            "pct": t.fuel_pct,
            "electric": t.is_ev,
        },
        "engine": {
            "boost_bar": t.boost_bar,
            "has_turbo": bool(t.flags & Flags.HAS_TURBO),
            "oil_pressure": t.oil_pressure,
            "water_temp": t.water_temp,
            "oil_temp": t.oil_temp,
        },
        "chassis": {
            "position": list(t.position),
            "velocity": list(t.velocity),
            "angular_velocity": list(t.angular_velocity),
            "ride_height": t.ride_height,
            "heading": t.rotation[3],
            "gear_ratios": list(t.active_gear_ratios),
            "final_drive": t.transmission_top_speed,
        },
        "environment": {
            "clock": format_time_of_day(t.time_of_day_ms),
            "daylight": _daylight(t.time_of_day_ms),
            # GT7 sends no weather channel; grip is inferred. See docs/weather.md.
            "grip_g": grip.recent_peak_g,
            "grip_relative": grip.relative,
            "grip_confidence": grip.confidence,
            "reserved_active": any(v != 0.0 for v in t.reserved),
        },
        "flags": {
            "on_track": t.on_track,
            "paused": t.paused,
            "loading": bool(t.flags & Flags.LOADING),
            "in_gear": bool(t.flags & Flags.IN_GEAR),
            "rev_limiter": bool(t.flags & Flags.REV_LIMITER),
            "handbrake": bool(t.flags & Flags.HANDBRAKE),
            "lights": bool(t.flags & Flags.LIGHTS),
            "high_beam": bool(t.flags & Flags.HIGH_BEAM),
            "asm": bool(t.flags & Flags.ASM),
            "tcs": bool(t.flags & Flags.TCS),
        },
    }


class Outline:
    """Tracks which outline the map is showing, and when it was replaced.

    The map draws either a recognised saved circuit or the live trace, and it
    swaps between them as the car is recognised or lost. Clients hold their own
    copy of the points, so they need one number that changes whenever the thing
    being drawn is a *different* thing.
    """

    def __init__(self) -> None:
        self.generation = 0
        self._key: tuple | None = None

    def sync(self, key: tuple) -> int:
        if key != self._key:
            self._key = key
            self.generation += 1
        return self.generation


def track_payload(track: TrackMap, library: TrackLibrary, outline: Outline,
                  cursor: int, pits: PitDetector | None = None) -> dict:
    """The outline to draw, as a delta from `cursor`.

    Only new points go out: a lap is thousands of them and re-sending twice a
    second would dwarf the telemetry. `generation` tells the client when to
    throw its copy away instead of appending.
    """
    # The lane being driven right now takes precedence, so it appears on the
    # map during the stop rather than only once it is over and saved.
    live_stop = (pits.current or pits.last_completed) if pits is not None else None
    lane: list[list[float]] = []
    if live_stop is not None and len(live_stop.path) >= 4:
        lane = [[round(x, 1), round(z, 1)] for x, z in live_stop.path]

    saved = library.by_id(library.active_id)
    if saved is not None:
        # Recognised circuit: the full outline is available immediately, with
        # no need to complete a lap first.
        total = len(saved.points)
        start = min(max(cursor, 0), total)
        tail = saved.points[start:]
        body = {
            "source": "saved",
            "track_id": saved.id,
            "name": saved.name,
            "laps_seen": saved.laps_seen,
            "closed": True,
            "anchored": True,
            "lap_number": 0,
            "length": saved.length,
            "points": total,
            "bbox": saved.bbox,
            "cursor": total,
            "pit_lane": lane or saved.pit_lane,
            "x": [p[0] for p in tail],
            "z": [p[1] for p in tail],
            "s": [int(p[2]) for p in tail],
        }
        generation = outline.sync(("saved", saved.id, saved.laps_seen))
    else:
        nxt, xs, zs, inputs = track.since(cursor)
        box = track.bbox
        body = {
            "source": "live",
            "track_id": None,
            "name": None,
            "laps_seen": 0,
            "closed": track.closed,
            # One lap measured line to line only once `closed`; before that it
            # starts wherever the dashboard happened to attach.
            "anchored": track.anchored,
            "lap_number": track.lap_number,
            "length": round(track.length, 1),
            "points": track.total_points,
            "bbox": [round(v, 1) for v in box] if box else None,
            "cursor": nxt,
            "pit_lane": lane,
            "x": xs,
            "z": zs,
            "s": inputs,
        }
        generation = outline.sync(("live", None, track.generation))

    body["generation"] = generation
    body["reset"] = cursor == 0
    return body


def analysis_payload(delta: DeltaTracker, stint: StintTracker) -> dict:
    """Where the last lap lost time, and what the car was doing when it did.

    Two layers over the same geometry: the lap coloured by time gained or lost
    against the reference, and markers for every lock-up and moment of
    wheelspin. Together they answer "where did he lose it" and "why" on one
    picture.
    """
    comparison = delta.comparison
    lap = delta.latest
    events = stint.laps[-1].events if stint.laps else []

    if comparison is None or lap is None or not len(lap):
        return {
            "available": False,
            # Say why, or an engineer watching lap 2 tick past wonders what
            # is broken. The opening lap never counts.
            "reason": ("no reference yet - the opening lap is skipped, so this "
                       "needs two more"
                       if delta.reference is None else "waiting for the next lap"),
            "events": [[round(x, 1), round(z, 1), kind] for x, z, kind in events],
        }

    xs, zs, deltas = bucket(lap, comparison)
    worst = [
        {"x": round(lap.xs[i], 1), "z": round(lap.zs[i], 1), "ms": round(ms, 1)}
        for i, ms in comparison.worst(3)
    ]
    return {
        "available": True,
        "lap_number": comparison.lap_number,
        "reference_number": comparison.reference_number,
        "lap_ms": comparison.lap_ms,
        "reference_ms": comparison.reference_ms,
        # Authoritative, from the unrounded comparison - never the sum of the
        # bucketed deltas below, which carry rounding error.
        "total_ms": round(comparison.total_ms, 1),
        "x": xs,
        "z": zs,
        "d": deltas,
        "bbox": [min(xs), min(zs), max(xs), max(zs)] if xs else None,
        "events": [[round(x, 1), round(z, 1), kind] for x, z, kind in events],
        "worst": worst,
    }


def pit_payload(pits: PitDetector, now: float) -> dict:
    """Pit-lane state. GT7 reports none of this; it is inferred - see pits.py."""
    stop = pits.current or pits.last_completed
    return {
        "in_pits": pits.in_pits,
        "stops": pits.stop_count,
        "elapsed_s": (round(v, 1) if (v := pits.elapsed_s(now)) is not None else None),
        "limit_kph": pits.limit_kph,
        "confidence": pits.confidence,
        # Why the last frame did not open a stop, so a missed one can be
        # explained rather than guessed at.
        "blocked_by": pits.blocked_by,
        "spread_kph": pits.spread_kph,
        "last": None if stop is None else {
            "lap": stop.lap,
            "duration_s": (round(stop.duration_s, 1)
                           if stop.duration_s is not None else None),
            "stationary_s": round(stop.stationary_s, 1),
        },
    }


def stint_payload(stint: StintTracker, pits: PitDetector | None = None,
                  now: float = 0.0) -> dict:
    """Everything accumulated across the stint, plus what to say about it.

    Sent on its own cadence rather than with each frame: none of it changes
    faster than once a lap, and the lap table would otherwise be re-sent sixty
    times a second for no reason.
    """
    balance = stint.tyre_balance
    best = stint.best_lap_ms
    # The pit lane is the engineer's business, so its callouts belong in the
    # same ranked list rather than a panel of their own.
    calls = list(stint.callouts())
    if pits is not None:
        calls += pits.callouts(now)
    rank = {"critical": 0, "warn": 1, "info": 2}
    calls.sort(key=lambda c: rank[c.severity])
    return {
        # Steering is a format B channel; format A carries none at all, and the
        # UI needs to say so rather than showing an empty meter.
        "steering_available": stint.steering_available,
        "steering_baseline": stint.median_corrections_per_minute,
        "lap_number": stint.lap_number,
        "total_laps": stint.total_laps,
        "laps_to_go": stint.laps_to_go,
        "lap_elapsed_ms": stint.lap_elapsed_ms,
        "best_lap_ms": best,
        "laps": [
            {
                "number": lap.number,
                "time_ms": lap.time_ms,
                "delta_ms": (lap.time_ms - best) if best else None,
                "is_best": best is not None and lap.time_ms == best,
                "fuel_used": round(lap.fuel_used, 3),
                "tyre_temp": [round(v, 1) for v in lap.tyre_temp],
                "max_speed_kph": round(lap.max_speed_kph, 1),
                "lockups": lap.lockups,
                "wheelspin": lap.wheelspin,
                "full_throttle_pct": round(lap.full_throttle_pct, 1),
                "braking_pct": round(lap.braking_pct, 1),
                "steering_corrections": lap.steering_corrections,
                "corrections_per_minute": (
                    round(r, 1) if (r := lap.corrections_per_minute) is not None else None
                ),
            }
            for lap in stint.laps[-24:]
        ],
        "fuel": {
            "per_lap": stint.fuel_per_lap,
            "laps_remaining": stint.laps_of_fuel,
            "margin_laps": stint.fuel_margin,
        },
        "pace": {
            "consistency_ms": stint.consistency_ms,
            "trend_ms": stint.pace_trend_ms,
        },
        "pits": pit_payload(pits, now) if pits is not None else None,
        # Position and field size are everything GT7 says about the other
        # cars. There is no opponent telemetry, so no gaps - docs/opponents.md.
        "race": {
            "position": stint.position or None,
            "cars": stint.cars or None,
            "start_position": stint.start_position,
            "places_gained": stint.places_gained,
            "changes": [
                {"lap": c.lap, "previous": c.previous, "current": c.current}
                for c in stint.position_changes[-6:]
            ],
        },
        "tyres": {
            "balance": balance,
            "series": [stint.tyre_series(i)[-24:] for i in range(4)],
        },
        "callouts": [
            {"key": c.key, "severity": c.severity, "message": c.message, "detail": c.detail}
            for c in calls
        ],
    }


def link_payload(client: GT7Client, error: str | None = None) -> dict:
    """Connection health - separate from telemetry so it survives a dead car."""
    active = client.active_format
    return {
        "error": error,
        "connected": client.connected,
        "host": client.host,
        "requested_format": client.format.name,
        "active_format": active.name if active else None,
        "format_mismatch": client.format_mismatch,
        "packet_rate": round(client.packet_rate, 1),
        "packets": client.packets,
        "dropped": client.dropped,
        "decode_errors": client.decode_errors,
    }


def build_app(ps5_host: str, fmt: str = "A",
              library_path: Path | None = None) -> FastAPI:
    client = GT7Client(ps5_host, BY_NAME[fmt])
    grip = GripEstimator()
    stint = StintTracker()
    track = TrackMap()
    delta = DeltaTracker()
    library = TrackLibrary(library_path)
    # Bind the pit-detection tolerance here: "on the racing line" for deciding
    # against a pit stop is a much tighter question than "is this the same
    # circuit", and ON_LINE_METRES is the figure for the former.
    pits = PitDetector(
        on_line=lambda x, z: library.near_active(x, z, ON_LINE_METRES))
    outline = Outline()
    app_state_pruned = library.pruned_on_load
    recognition = {"checked": 0.0, "saved_lap": 0}

    def on_frame(frame: Telemetry) -> None:
        now = time.monotonic()
        grip.feed(frame, now)
        stint.feed(frame, now)
        track.feed(frame)
        was_in_pits = pits.in_pits
        pits.feed(frame, now)
        if was_in_pits and not pits.in_pits:
            finished = pits.last_completed
            if finished is not None:
                library.remember_pit_lane(library.active_id, finished.path)

        # Keeping a finished lap is an integer comparison, so it runs every
        # frame. Throttling it alongside the spatial scan meant a lap could be
        # missed entirely when a tick fell the wrong side of the boundary.
        if track.closed and track.lap_number != recognition["saved_lap"]:
            recognition["saved_lap"] = track.lap_number
            # A lap through the pit lane is not the racing line. Letting it
            # into the library would teach the map a road the car only uses
            # when it stops.
            if not pits.lap_had_a_stop(track.lap_number):
                library.remember(track.xs, track.zs, track.inputs, track.length)
            if track.last_lap is not None:
                delta.add_lap(track.last_lap)
            return

        # Recognition is the expensive half - a spatial scan over the library -
        # and a car cannot leave a circuit between frames, so 2 Hz is plenty.
        if now - recognition["checked"] >= 0.5:
            recognition["checked"] = now
            library.update_match(*track.recent())

    client.on_frame = on_frame

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # A busy telemetry port must not stop the server booting. The page
        # should load and explain the problem; a dashboard that refuses to
        # start tells the user nothing about why.
        try:
            client.start()
        except PortBusyError as exc:
            app.state.client_error = exc.args[1] if len(exc.args) > 1 else str(exc)
            yield
            return
        try:
            yield
        finally:
            client.stop()

    app = FastAPI(title="GT7 telemetry", lifespan=lifespan, docs_url="/api/docs")
    app.state.client = client
    app.state.grip = grip
    app.state.stint = stint
    app.state.track = track
    app.state.library = library
    app.state.pits = pits
    app.state.pruned_tracks = app_state_pruned
    app.state.delta = delta
    app.state.client_error = None

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/link")
    async def api_link() -> JSONResponse:
        """Connection health only - always answers, even with no car on track."""
        return JSONResponse(link_payload(client, app.state.client_error))

    @app.get("/api/telemetry")
    async def api_telemetry() -> JSONResponse:
        """The most recent frame, or 503 if the console has not sent one."""
        frame = client.latest
        if frame is None:
            return JSONResponse(
                {"detail": "no telemetry yet",
                 "link": link_payload(client, app.state.client_error)},
                status_code=503,
            )
        return JSONResponse({"link": link_payload(client, app.state.client_error),
                             "telemetry": telemetry_payload(frame, client, grip),
                             "stint": stint_payload(stint, pits, time.monotonic())})

    @app.get("/api/track")
    async def api_track(since: int = Query(default=0)) -> JSONResponse:
        """The outline to draw. `since` fetches only points after a cursor."""
        return JSONResponse(track_payload(track, library, outline, max(since, 0), pits))

    @app.get("/api/analysis")
    async def api_analysis() -> JSONResponse:
        """Time lost against the reference lap, with lock-up positions."""
        return JSONResponse(analysis_payload(delta, stint))

    @app.get("/api/tracks")
    async def api_tracks() -> JSONResponse:
        """Every saved circuit, newest first."""
        return JSONResponse({
            "active_id": library.active_id,
            "tracks": [
                {"id": t.id, "name": t.name, "length": t.length,
                 "laps_seen": t.laps_seen, "points": len(t.points)}
                for t in sorted(library.tracks, key=lambda t: -t.created)
            ],
        })

    @app.post("/api/tracks/{track_id}/name")
    async def api_rename(track_id: str, body: dict) -> JSONResponse:
        saved = library.rename(track_id, str(body.get("name", "")))
        if saved is None:
            return JSONResponse({"detail": "no such track"}, status_code=404)
        return JSONResponse({"id": saved.id, "name": saved.name})

    @app.delete("/api/tracks/{track_id}")
    async def api_forget(track_id: str) -> JSONResponse:
        if not library.forget(track_id):
            return JSONResponse({"detail": "no such track"}, status_code=404)
        return JSONResponse({"forgotten": track_id})

    @app.get("/api/stint")
    async def api_stint() -> JSONResponse:
        """Lap history, fuel projection and the current radio callouts."""
        return JSONResponse(stint_payload(stint, pits, time.monotonic()))

    @app.websocket("/ws")
    async def ws(socket: WebSocket, hz: float = Query(default=60.0)) -> None:
        await socket.accept()
        interval = 1.0 / min(max(hz, MIN_HZ), MAX_HZ)
        last_id: int | None = None
        last_link = 0.0
        last_stint = 0.0
        # Each connection carries its own trace cursor, so two browsers do not
        # steal each other's place in the stream.
        track_cursor = 0
        track_generation = track.generation
        track_lane_len = -1
        try:
            while True:
                frame = client.latest
                now = time.monotonic()

                if frame is not None and frame.packet_id != last_id:
                    last_id = frame.packet_id
                    await socket.send_json({
                        "type": "frame",
                        "telemetry": telemetry_payload(frame, client, grip),
                    })

                # Stint state moves at most once a lap. 2 Hz keeps the elapsed
                # clock honest without re-sending the lap table constantly.
                if now - last_stint >= 0.5:
                    last_stint = now
                    await socket.send_json({
                        "type": "stint",
                        "stint": stint_payload(stint, pits, now),
                    })
                    await socket.send_json({
                        "type": "analysis",
                        "analysis": analysis_payload(delta, stint),
                    })

                    if outline.generation != track_generation:
                        track_generation = outline.generation
                        track_cursor = 0      # a different outline; resend it
                    body = track_payload(track, library, outline, track_cursor, pits)
                    track_cursor = body["cursor"]
                    # A recognised circuit is a fixed outline: once sent there
                    # is nothing to add, so do not ship an empty message twice
                    # a second for the rest of the stint. But the pit lane
                    # travels in this same message and keeps growing during a
                    # stop, so "no new outline points" is not the same as
                    # "nothing to say" - suppressing on that alone meant a
                    # page that connected before the stop never saw the lane.
                    lane_len = len(body["pit_lane"])
                    if body["x"] or body["reset"] or lane_len != track_lane_len:
                        track_lane_len = lane_len
                        await socket.send_json({"type": "track", "track": body})

                # Link health changes slowly; 4 Hz is plenty and keeps the
                # socket warm while the car sits in a menu sending nothing.
                if now - last_link >= 0.25:
                    last_link = now
                    await socket.send_json({
                        "type": "link",
                        "link": link_payload(client, app.state.client_error),
                    })

                await asyncio.sleep(interval)
        except (WebSocketDisconnect, RuntimeError):
            pass

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def serve(ps5_host: str, fmt: str = "A", host: str = "0.0.0.0",
          port: int = 6767, library_path: Path | None = None) -> None:
    import uvicorn

    uvicorn.run(build_app(ps5_host, fmt, library_path), host=host, port=port,
                log_level="warning", access_log=False)
