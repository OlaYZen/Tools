"""UDP client for the GT7 Simulator Interface.

The console does not stream unprompted.  You send a single-byte heartbeat to
UDP/33739 and it replies with ~60 telemetry datagrams per second on UDP/33740
for roughly ten seconds, then falls silent.  Re-sending the heartbeat keeps it
alive; the byte you send selects the wire format.

One wrinkle worth knowing, learned the hard way: **the format is fixed for the
life of a telemetry session, and every heartbeat renews that session.**  Ask
for 'B' while an 'A' session is live and you keep getting 'A' - indefinitely,
because your 'B' heartbeat is itself what keeps the 'A' session alive.  The
only way to change format is to stop sending heartbeats entirely and let the
session lapse, which takes far longer than the commonly cited ten seconds.

So the requested format is a request, not a guarantee.  This client decrypts
by *observed packet length* rather than by what it asked for, and exposes the
format actually being served as `active_format`, so a mismatch shows up as a
readable state instead of a stream of decode errors.
"""

from __future__ import annotations

import errno
import socket
import threading
import time
from collections import deque
from collections.abc import Callable

from .crypto import (
    BY_NAME,
    FORMAT_A,
    DecryptionError,
    PacketFormat,
    decrypt,
    format_for,
)
from .packet import Telemetry, parse

SEND_PORT = 33739
RECV_PORT = 33740

#: Measured, not assumed: a single heartbeat keeps the console streaming for
#: over a minute, and each further heartbeat renews it.  Re-arming every 2s is
#: comfortably inside that.
HEARTBEAT_INTERVAL = 2.0


class PortBusyError(OSError):
    """Another program already holds the telemetry port."""


PORT_BUSY_HELP = (
    f"UDP port {RECV_PORT} is already in use - another GT7 telemetry client "
    "is running. Stop it first; two clients on one machine split the packet "
    "stream between them."
)


def port_is_free(bind_addr: str = "0.0.0.0") -> bool:
    """Check the telemetry port without starting anything.

    Lets a caller fail early with a readable message instead of letting the
    bind blow up somewhere inside a server framework's startup.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind((bind_addr, RECV_PORT))
    except OSError:
        return False
    finally:
        probe.close()
    return True


class GT7Client:
    """Threaded receiver for GT7 telemetry.

    Use as a context manager; read `latest` for the most recent frame, or pass
    an `on_frame` callback to be driven at packet rate.
    """

    def __init__(
        self,
        host: str,
        fmt: PacketFormat | str = FORMAT_A,
        on_frame: Callable[[Telemetry], None] | None = None,
        bind_addr: str = "0.0.0.0",
    ) -> None:
        self.host = host
        self.format = BY_NAME[fmt] if isinstance(fmt, str) else fmt
        self.on_frame = on_frame
        self.bind_addr = bind_addr

        self.latest: Telemetry | None = None
        self.connected = False

        #: The format the console is actually serving, which is not necessarily
        #: the one we asked for - see the module docstring.
        self.active_format: PacketFormat | None = None

        # rolling stats
        self.packets = 0
        self.decode_errors = 0
        self.dropped = 0  # gaps in the console's packet_id sequence
        self._recent = deque(maxlen=180)  # arrival timestamps, for packet rate
        self._last_id: int | None = None
        self._last_rx = 0.0

        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> GT7Client:
        if self._thread is not None:
            raise RuntimeError("client already started")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Deliberately NOT SO_REUSEADDR. On UDP that option lets a second
        # program bind the same port and quietly take a share of the packets,
        # leaving both clients showing frozen data and neither reporting a
        # fault. Failing to bind is far better than half-working. UDP has no
        # TIME_WAIT, so nothing is lost by omitting it: the port is reusable
        # the instant the previous socket closes.
        try:
            sock.bind((self.bind_addr, RECV_PORT))
        except OSError as exc:
            sock.close()
            if exc.errno == errno.EADDRINUSE:
                raise PortBusyError(exc.errno, PORT_BUSY_HELP) from exc
            raise
        sock.settimeout(0.5)
        self._sock = sock
        self._thread = threading.Thread(target=self._run, name="gt7-rx", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def __enter__(self) -> GT7Client:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # ---- internals -------------------------------------------------------

    def _heartbeat(self) -> None:
        if self._sock is not None:
            self._sock.sendto(self.format.heartbeat, (self.host, SEND_PORT))

    def _run(self) -> None:
        assert self._sock is not None
        self._heartbeat()
        next_beat = time.monotonic() + HEARTBEAT_INTERVAL
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_beat:
                self._heartbeat()
                next_beat = now + HEARTBEAT_INTERVAL
            try:
                payload, _ = self._sock.recvfrom(4096)
            except socket.timeout:
                if now - self._last_rx > 3.0:
                    self.connected = False
                continue
            except OSError:
                break
            self._ingest(payload, now)

    def _ingest(self, payload: bytes, now: float) -> None:
        observed = format_for(payload)
        try:
            frame = parse(decrypt(payload))
        except DecryptionError:
            self.decode_errors += 1
            self.active_format = observed
            return

        with self._lock:
            self.packets += 1
            self.connected = True
            self._last_rx = now
            self._recent.append(now)
            if self._last_id is not None:
                gap = frame.packet_id - self._last_id
                if gap > 1:
                    self.dropped += gap - 1
            self._last_id = frame.packet_id
            self.latest = frame
            self.active_format = observed

        if self.on_frame is not None:
            self.on_frame(frame)

    # ---- stats -----------------------------------------------------------

    #: Arrivals older than this do not count toward the rate, so a stalled
    #: stream decays to zero instead of reporting its last healthy figure
    #: forever. Without this a starved client reads "live, 60 pkt/s" while
    #: showing frozen data - which is worse than showing nothing.
    RATE_WINDOW = 3.0

    @property
    def packet_rate(self) -> float:
        """Observed packets/second over the last few seconds."""
        with self._lock:
            cutoff = time.monotonic() - self.RATE_WINDOW
            recent = [t for t in self._recent if t >= cutoff]
            if len(recent) < 2:
                return 0.0
            span = recent[-1] - recent[0]
            return (len(recent) - 1) / span if span > 0 else 0.0

    @property
    def format_mismatch(self) -> bool:
        """True when the console is serving a format we did not ask for."""
        return self.active_format is not None and self.active_format is not self.format

    def wait_for_frame(self, timeout: float = 10.0) -> Telemetry | None:
        """Block until the first frame arrives (or `timeout` elapses)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.latest is not None:
                return self.latest
            time.sleep(0.05)
        return None
