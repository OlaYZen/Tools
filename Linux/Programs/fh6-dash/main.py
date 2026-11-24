"""
FH6 Dash — FastAPI app that listens for Forza Horizon 6 "Data Out" UDP
telemetry, logs every packet, and serves a live web dashboard.

Run:
    python main.py
    # or
    uvicorn main:app

Then in FH6: SETTINGS > HUD AND GAMEPLAY
    Data Out:         On
    Data Out IP:      127.0.0.1   (this machine)
    Data Out IP Port: 9999        (must match TELEMETRY_PORT below)

The web dashboard is served at http://127.0.0.1:8000
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

import forza

# ---------------------------------------------------------------------------
# Configuration (defaults per FH6 docs; override via environment variables).
# The game avoids ports 5200-5300 for its own socket, so 9999 is a safe default.
# ---------------------------------------------------------------------------
TELEMETRY_HOST = os.environ.get("FH6_HOST", "0.0.0.0")  # listen on all interfaces
TELEMETRY_PORT = int(os.environ.get("FH6_PORT", "9999"))
LOG_FILE = os.environ.get("FH6_LOG", "telemetry.log")

# ---------------------------------------------------------------------------
# Logging: every packet is written as one JSON line to telemetry.log (rotating),
# and a concise summary is printed to the console.
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fh6")

packet_log = logging.getLogger("fh6.packets")
packet_log.propagate = False
_handler = RotatingFileHandler(LOG_FILE, maxBytes=25 * 1024 * 1024, backupCount=3)
_handler.setFormatter(logging.Formatter("%(message)s"))
packet_log.addHandler(_handler)
packet_log.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Shared state: the most recent telemetry frame + a simple packet counter.
# ---------------------------------------------------------------------------
class State:
    def __init__(self):
        self.latest: dict | None = None
        self.count: int = 0
        self.last_sender: str | None = None


state = State()


class ForzaProtocol(asyncio.DatagramProtocol):
    """Receives and decodes FH6 UDP packets as they arrive."""

    def datagram_received(self, data: bytes, addr):
        try:
            frame = forza.parse(data)
        except ValueError as exc:
            log.warning("dropped packet from %s: %s", addr, exc)
            return

        state.latest = frame
        state.count += 1
        state.last_sender = f"{addr[0]}:{addr[1]}"

        # Log the full frame as a JSON line.
        packet_log.info(json.dumps(frame, separators=(",", ":")))

        # Console summary every 60 frames (~once per second at 60fps) so the
        # terminal stays readable while still showing it's alive.
        if state.count % 60 == 0:
            log.info(
                "#%d from %s | RaceOn=%s Gear=%s RPM=%.0f Speed=%.1f m/s",
                state.count,
                state.last_sender,
                frame["IsRaceOn"],
                frame["Gear"],
                frame["CurrentEngineRpm"],
                frame["Speed"],
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        ForzaProtocol, local_addr=(TELEMETRY_HOST, TELEMETRY_PORT)
    )
    log.info(
        "Listening for FH6 telemetry on udp://%s:%d  (logging to %s)",
        TELEMETRY_HOST,
        TELEMETRY_PORT,
        LOG_FILE,
    )
    log.info("Dashboard: http://127.0.0.1:8000")
    try:
        yield
    finally:
        transport.close()
        log.info("Stopped telemetry listener (%d packets received)", state.count)


app = FastAPI(title="FH6 Dash", lifespan=lifespan)


@app.get("/api/latest")
async def api_latest():
    """Most recent decoded telemetry frame (or status if none yet)."""
    return JSONResponse(
        {
            "received": state.count,
            "sender": state.last_sender,
            "frame": state.latest,
        }
    )


@app.get("/api/fields")
async def api_fields():
    """The ordered list of every field FH6 sends."""
    return JSONResponse({"fields": forza.FIELD_NAMES})


# ---------------------------------------------------------------------------
# Car name lookup: telemetry only sends a numeric CarOrdinal, so we let the user
# label each ordinal once. Names persist in cars.json ({ordinal: {make,model,year}}).
# ---------------------------------------------------------------------------
CARS_FILE = os.path.join(os.path.dirname(__file__), "cars.json")


def _load_cars() -> dict:
    try:
        with open(CARS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


@app.get("/api/cars")
async def api_cars():
    """All saved CarOrdinal -> name mappings."""
    return JSONResponse(_load_cars())


@app.post("/api/cars")
async def api_cars_save(entry: dict = Body(...)):
    """Save/update the make/model/year for a CarOrdinal."""
    ordinal = str(entry.get("ordinal", "")).strip()
    if not ordinal or ordinal in ("None", "0"):
        return JSONResponse({"error": "missing ordinal"}, status_code=400)
    cars = _load_cars()
    cars[ordinal] = {
        "make": str(entry.get("make", "")).strip(),
        "model": str(entry.get("model", "")).strip(),
        "year": str(entry.get("year", "")).strip(),
    }
    with open(CARS_FILE, "w", encoding="utf-8") as fh:
        json.dump(cars, fh, indent=2, sort_keys=True)
    log.info("saved car name for ordinal %s: %s", ordinal, cars[ordinal])
    return JSONResponse({"ok": True, "saved": cars[ordinal]})


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    """Push the latest frame to the dashboard ~30 times per second."""
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(
                {
                    "received": state.count,
                    "sender": state.last_sender,
                    "frame": state.latest,
                }
            )
            await asyncio.sleep(1 / 30)
    except WebSocketDisconnect:
        pass


DASHBOARD = os.path.join(os.path.dirname(__file__), "dashboard.html")


@app.get("/", response_class=HTMLResponse)
async def index():
    with open(DASHBOARD, encoding="utf-8") as fh:
        return fh.read()




if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
