"""Record and replay raw telemetry.

Captures are stored as the *ciphertext* the console sent, with arrival
timestamps.  Keeping the raw bytes means a capture stays useful for protocol
work even after the decoder changes - including for formats we cannot decrypt
yet.

Wire format: a short header, then repeated [f64 t][u16 len][len bytes].
"""

from __future__ import annotations

import socket
import struct
import time
from collections.abc import Iterator
from pathlib import Path

from .client import RECV_PORT, SEND_PORT
from .crypto import BY_NAME, PacketFormat

MAGIC = b"GT7CAP01"
_HEADER = struct.Struct("<8sB")
_FRAME = struct.Struct("<dH")


def record(host: str, path: Path, seconds: float, fmt: PacketFormat | str = "A") -> int:
    """Capture `seconds` of raw datagrams to `path`. Returns the packet count."""
    fmt = BY_NAME[fmt] if isinstance(fmt, str) else fmt
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # No SO_REUSEADDR - see the note in client.start().
    sock.bind(("0.0.0.0", RECV_PORT))
    sock.settimeout(0.5)

    count = 0
    start = time.monotonic()
    next_beat = 0.0
    with path.open("wb") as fh:
        fh.write(_HEADER.pack(MAGIC, ord(fmt.heartbeat)))
        while True:
            now = time.monotonic()
            if now - start >= seconds:
                break
            if now >= next_beat:
                sock.sendto(fmt.heartbeat, (host, SEND_PORT))
                next_beat = now + 2.0
            try:
                payload, _ = sock.recvfrom(4096)
            except socket.timeout:
                continue
            fh.write(_FRAME.pack(now - start, len(payload)))
            fh.write(payload)
            count += 1
    sock.close()
    return count


def read(path: Path) -> Iterator[tuple[float, bytes]]:
    """Yield (timestamp, raw datagram) pairs from a capture."""
    data = path.read_bytes()
    magic, _hb = _HEADER.unpack_from(data, 0)
    if magic != MAGIC:
        raise ValueError(f"{path} is not a GT7 capture")
    pos = _HEADER.size
    while pos + _FRAME.size <= len(data):
        ts, length = _FRAME.unpack_from(data, pos)
        pos += _FRAME.size
        if pos + length > len(data):
            break
        yield ts, data[pos : pos + length]
        pos += length


def replay(path: Path, realtime: bool = True) -> Iterator[bytes]:
    """Yield datagrams from a capture, optionally pacing them as recorded."""
    start = time.monotonic()
    for ts, payload in read(path):
        if realtime:
            delay = ts - (time.monotonic() - start)
            if delay > 0:
                time.sleep(delay)
        yield payload
