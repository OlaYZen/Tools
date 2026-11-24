"""Pure-Python Joy-Con / Pro-Controller backend (Linux ``/dev/hidraw*``).

This re-implements the SPI-flash color read/write of CTCaer's Joy-Con Toolkit
(``get_spi_data`` / ``write_spi_data`` in ``jctool.cpp``) without any third-party
dependency — it talks to the controller's hidraw character device directly.

Protocol (Bluetooth HID, from the Nintendo Switch reverse-engineering project)
----------------------------------------------------------------------------
Every command is an **output report 0x01** ("Rumble + subcommand"), 49 bytes:

    byte 0      0x01            (report id / command)
    byte 1      timer           (global packet counter, low nibble)
    byte 2..9   rumble (neutral, left zero here as the original tool does)
    byte 10     subcommand      (0x10 = SPI read, 0x11 = SPI write)
    byte 11..14 SPI offset      (uint32, little-endian)
    byte 15     SPI size        (uint8)
    byte 16..   write payload   (write only)

The controller answers with **input report 0x21**:

    byte 0      0x21
    ...
    byte 13     ack             (0x90 for a read reply, 0x80 for a write reply)
    byte 14     subcommand echo (0x10 / 0x11)
    byte 15..18 SPI offset echo (read reply)
    byte 20..   data            (read reply)

Colors live at SPI ``0x6050`` (12 bytes):

    0x6050  body   RGB
    0x6053  buttons RGB
    0x6056  left grip  RGB   (Pro Controller, firmware 5.0.0+)
    0x6059  right grip RGB   (Pro Controller, firmware 5.0.0+)

Joy-Cons store only the 6-byte body+buttons block; the Pro Controller stores all
12 bytes.

.. note::
   This path needs read/write access to ``/dev/hidraw*`` (root, or a udev rule —
   see the README) and a controller connected over **Bluetooth**.  When no
   accessible device is present the server falls back to :class:`MockJoyCon` so
   the color picker is still fully usable; "writing" is then simulated in memory.
   The hardware path could not be exercised in this build environment, so treat
   it as carefully-ported-but-untested and keep a backup of your SPI first.
"""

from __future__ import annotations

import glob
import os
import select
import struct
from dataclasses import dataclass

NINTENDO_VID = 0x057E

# product id -> (display name, kind, has_grip_colors)
DEVICE_TYPES = {
    0x2006: ("Joy-Con (L)", "joycon_l", False),
    0x2007: ("Joy-Con (R)", "joycon_r", False),
    0x2009: ("Pro Controller", "pro", True),
    0x200E: ("Charging Grip", "grip", False),
}

COLOR_SPI_OFFSET = 0x6050
REPORT_LEN = 49

SUBCMD_SPI_READ = 0x10
SUBCMD_SPI_WRITE = 0x11

Colors = dict  # {"body": "RRGGBB", "buttons": ..., "left_grip": ..., "right_grip": ...}


class JoyConError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Device discovery
# ---------------------------------------------------------------------------

def _parse_uevent(path: str) -> dict:
    info: dict = {}
    try:
        with open(path, "r") as fh:
            for line in fh:
                if "=" in line:
                    key, _, val = line.partition("=")
                    info[key.strip()] = val.strip()
    except OSError:
        pass
    return info


def discover_devices() -> list[dict]:
    """Return a list of connected Nintendo controllers found via sysfs.

    Each entry: ``{"path": "/dev/hidraw3", "vendor": 0x057e, "product": 0x2007,
    "name": "Joy-Con (R)", "kind": "joycon_r", "has_grips": False}``.
    """
    found: list[dict] = []
    for sys_dir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        name = os.path.basename(sys_dir)
        uevent = _parse_uevent(os.path.join(sys_dir, "device", "uevent"))
        hid_id = uevent.get("HID_ID", "")
        # HID_ID = BUS:VENDOR:PRODUCT, e.g. 0005:0000057E:00002007
        parts = hid_id.split(":")
        if len(parts) != 3:
            continue
        try:
            vendor = int(parts[1], 16)
            product = int(parts[2], 16)
        except ValueError:
            continue
        if vendor != NINTENDO_VID or product not in DEVICE_TYPES:
            continue
        disp, kind, has_grips = DEVICE_TYPES[product]
        found.append(
            {
                "path": f"/dev/{name}",
                "vendor": vendor,
                "product": product,
                "name": uevent.get("HID_NAME", disp),
                "kind": kind,
                "has_grips": has_grips,
            }
        )
    return found


# ---------------------------------------------------------------------------
# Real hidraw backend
# ---------------------------------------------------------------------------

class HidRawJoyCon:
    """Talks to a real controller over ``/dev/hidraw*``."""

    mock = False

    def __init__(self, device: dict):
        self.device = device
        self.name = device["name"]
        self.kind = device["kind"]
        self.has_grips = device["has_grips"]
        self.path = device["path"]
        self._timer = 0
        self._fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)

    # -- low level ---------------------------------------------------------
    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None

    def _next_timer(self) -> int:
        t = self._timer & 0xF
        self._timer = (self._timer + 1) & 0xFF
        return t

    def _build_report(self, subcmd: int, offset: int, size: int, payload: bytes = b"") -> bytes:
        buf = bytearray(REPORT_LEN)
        buf[0] = 0x01
        buf[1] = self._next_timer()
        # bytes 2..9 are rumble data, left as neutral zeros (matches jctool.cpp)
        buf[10] = subcmd
        struct.pack_into("<IB", buf, 11, offset & 0xFFFFFFFF, size & 0xFF)
        if payload:
            buf[16 : 16 + len(payload)] = payload
        return bytes(buf)

    def _write(self, data: bytes) -> None:
        os.write(self._fd, data)

    def _read(self, timeout: float = 0.2) -> bytes:
        ready, _, _ = select.select([self._fd], [], [], timeout)
        if not ready:
            return b""
        try:
            return os.read(self._fd, 362)
        except BlockingIOError:
            return b""

    # -- SPI ---------------------------------------------------------------
    def spi_read(self, offset: int, size: int, attempts: int = 20) -> bytes:
        for _ in range(attempts):
            self._write(self._build_report(SUBCMD_SPI_READ, offset, size))
            for _ in range(9):
                reply = self._read()
                if len(reply) >= 0x14 + size and reply[0] == 0x21:
                    if reply[0x0D] == 0x90 and reply[0x0E] == 0x10:
                        echoed = struct.unpack_from("<I", reply, 0x0F)[0]
                        if echoed == offset:
                            return bytes(reply[0x14 : 0x14 + size])
        raise JoyConError(f"SPI read at {offset:#06x} failed (no reply)")

    def spi_write(self, offset: int, payload: bytes, attempts: int = 20) -> None:
        for _ in range(attempts):
            self._write(self._build_report(SUBCMD_SPI_WRITE, offset, len(payload), payload))
            for _ in range(9):
                reply = self._read()
                if len(reply) >= 0x0F and reply[0] == 0x21:
                    if reply[0x0D] == 0x80 and reply[0x0E] == 0x11:
                        return
        raise JoyConError(f"SPI write at {offset:#06x} failed (no ack)")

    # -- colors ------------------------------------------------------------
    def read_colors(self) -> Colors:
        raw = self.spi_read(COLOR_SPI_OFFSET, 12)
        return _decode_colors(raw)

    def write_colors(self, colors: Colors) -> None:
        payload = _encode_colors(colors)
        # Joy-Cons only have the 6-byte body+buttons block; the Pro Controller
        # has the full 12 bytes (incl. grips).
        size = 12 if self.has_grips else 6
        self.spi_write(COLOR_SPI_OFFSET, payload[:size])

    def info(self) -> dict:
        return {
            "connected": True,
            "mock": False,
            "name": self.name,
            "kind": self.kind,
            "has_grips": self.has_grips,
            "path": self.path,
        }


# ---------------------------------------------------------------------------
# Mock backend (no hardware / no permissions)
# ---------------------------------------------------------------------------

class MockJoyCon:
    """In-memory stand-in so the picker works without a real controller."""

    mock = True

    def __init__(self, kind: str = "pro"):
        self.kind = kind
        self.has_grips = kind == "pro"
        self.name = {
            "joycon_l": "Joy-Con (L)",
            "joycon_r": "Joy-Con (R)",
            "pro": "Pro Controller",
        }.get(kind, "Pro Controller") + " (mock)"
        self.path = "(mock)"
        # Seed with the classic grey retail Pro-Controller colors.
        self._spi = bytearray(
            bytes.fromhex("323232") + bytes.fromhex("FFFFFF")
            + bytes.fromhex("464646") + bytes.fromhex("464646")
        )

    def read_colors(self) -> Colors:
        return _decode_colors(bytes(self._spi))

    def write_colors(self, colors: Colors) -> None:
        payload = _encode_colors(colors)
        size = 12 if self.has_grips else 6
        self._spi[:size] = payload[:size]

    def close(self) -> None:
        pass

    def info(self) -> dict:
        return {
            "connected": True,
            "mock": True,
            "name": self.name,
            "kind": self.kind,
            "has_grips": self.has_grips,
            "path": self.path,
        }


# ---------------------------------------------------------------------------
# Encode / decode helpers
# ---------------------------------------------------------------------------

def _decode_colors(raw: bytes) -> Colors:
    raw = (raw + b"\x00" * 12)[:12]
    def hx(i: int) -> str:
        return f"{raw[i]:02X}{raw[i + 1]:02X}{raw[i + 2]:02X}"
    return {
        "body": hx(0),
        "buttons": hx(3),
        "left_grip": hx(6),
        "right_grip": hx(9),
    }


def _encode_colors(colors: Colors) -> bytes:
    def to_bytes(key: str, default: str) -> bytes:
        value = (colors.get(key) or default).lstrip("#")
        return bytes.fromhex(value[:6].rjust(6, "0"))
    return (
        to_bytes("body", "000000")
        + to_bytes("buttons", "000000")
        + to_bytes("left_grip", "000000")
        + to_bytes("right_grip", "000000")
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def open_device(prefer_mock: bool = False, mock_kind: str = "pro"):
    """Return a usable backend.

    Tries the first accessible real controller; on absence or permission error
    falls back to :class:`MockJoyCon`.  ``prefer_mock=True`` forces the mock.
    """
    if not prefer_mock:
        for dev in discover_devices():
            try:
                return HidRawJoyCon(dev)
            except PermissionError:
                continue
            except OSError:
                continue
    return MockJoyCon(kind=mock_kind)
