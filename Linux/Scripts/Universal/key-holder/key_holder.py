#!/usr/bin/env python3
"""Toggle-hold a key (default: w) on Wayland via a virtual uinput keyboard.

Starts with the hold OFF. Press F8 to toggle it on/off. Ctrl+C to quit.

Needs read access to /dev/input/event* and write access to /dev/uinput —
you're in the `input` group, so it just works.
"""

import argparse
import ctypes
import fcntl
import glob
import json
import os
import re
import select
import socket
import struct
import sys
import time

# ---- linux/uinput.h + linux/input.h ----------------------------------------
UINPUT_IOCTL_BASE = ord("U")
EVDEV_IOCTL_BASE = ord("E")


def _iow(base, nr, size):
    return (1 << 30) | (size << 16) | (base << 8) | nr


def _ior(base, nr, size):
    return (2 << 30) | (size << 16) | (base << 8) | nr


def _io(base, nr):
    return (base << 8) | nr


UI_DEV_CREATE = _io(UINPUT_IOCTL_BASE, 1)
UI_DEV_DESTROY = _io(UINPUT_IOCTL_BASE, 2)
UI_DEV_SETUP = _iow(UINPUT_IOCTL_BASE, 3, 92)  # sizeof(struct uinput_setup)
UI_SET_EVBIT = _iow(UINPUT_IOCTL_BASE, 100, ctypes.sizeof(ctypes.c_int))
UI_SET_KEYBIT = _iow(UINPUT_IOCTL_BASE, 101, ctypes.sizeof(ctypes.c_int))

KEY_MAX = 0x2FF
KEY_BYTES = (KEY_MAX + 1) // 8
EVIOCGNAME = _ior(EVDEV_IOCTL_BASE, 0x06, 256)


def EVIOCGBIT(ev, length):
    return _ior(EVDEV_IOCTL_BASE, 0x20 + ev, length)


# struct input_event { struct timeval time; __u16 type; __u16 code; __s32 value; }
# Native ("@") sizing matters: timeval uses long (8 bytes on 64-bit), so the
# kernel expects a 24-byte record. A "<" prefix would make long 4 bytes -> EINVAL.
EVENT_FMT = "@llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FMT)

EV_SYN, EV_KEY = 0x00, 0x01
SYN_REPORT = 0
BUS_USB = 0x03

VIRTUAL_NAME = "python-holdkey"

# The game window's class carries its version ("Lunar Client 26.2 (v2.22...)"),
# so match a prefix. The trailing digit keeps this from matching the launcher,
# whose class is the run-together "lunarclient".
DEFAULT_TARGET = r"(?i)^Lunar Client \d"

# Codes from linux/input-event-codes.h.
KEYS = {
    "w": 17, "a": 30, "s": 31, "d": 32,
    "q": 16, "e": 18, "r": 19, "f": 33,
    "space": 57, "shift": 42, "ctrl": 29, "alt": 56, "tab": 15,
    "up": 103, "down": 108, "left": 105, "right": 106,
    "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64,
    "f7": 65, "f8": 66, "f9": 67, "f10": 68, "f11": 87, "f12": 88,
}


# ---- output device ---------------------------------------------------------
class VirtualKeyboard:
    """A virtual keyboard that can hold exactly one key down."""

    def __init__(self, keycode, name=VIRTUAL_NAME):
        self.keycode = keycode
        self.held = False
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(self.fd, UI_SET_KEYBIT, keycode)
        setup = struct.pack("@4H80sI", BUS_USB, 0x1234, 0x5678, 1,
                            name.encode(), 0)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        # Give the compositor a moment to notice the new device.
        time.sleep(0.3)

    def _emit(self, etype, code, value):
        os.write(self.fd, struct.pack(EVENT_FMT, 0, 0, etype, code, value))

    def set_held(self, held):
        if held == self.held:
            return
        self._emit(EV_KEY, self.keycode, 1 if held else 0)
        self._emit(EV_SYN, SYN_REPORT, 0)
        self.held = held

    def close(self):
        try:
            self.set_held(False)
        except OSError as e:
            print(f"warning: could not send key release: {e}", file=sys.stderr)
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(self.fd)


# ---- input devices ---------------------------------------------------------
def find_keyboards(toggle_code):
    """Open every real input device that can emit the toggle key."""
    found = []
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue  # not readable, not ours to worry about
        try:
            name_buf = bytearray(256)
            fcntl.ioctl(fd, EVIOCGNAME, name_buf)
            name = name_buf.split(b"\x00")[0].decode(errors="replace")

            keybits = bytearray(KEY_BYTES)
            fcntl.ioctl(fd, EVIOCGBIT(EV_KEY, KEY_BYTES), keybits)
            supports_toggle = bool(keybits[toggle_code // 8] & (1 << (toggle_code % 8)))

            if supports_toggle and name != VIRTUAL_NAME:
                found.append((fd, name))
                continue
        except OSError:
            pass
        os.close(fd)
    return found


def read_key_presses(fd):
    """Yield keycodes for key-down events (ignores repeats and releases)."""
    try:
        data = os.read(fd, EVENT_SIZE * 64)
    except (BlockingIOError, OSError):
        return
    for i in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
        _, _, etype, code, value = struct.unpack_from(EVENT_FMT, data, i)
        if etype == EV_KEY and value == 1:
            yield code


# ---- focus tracking --------------------------------------------------------
class HyprlandFocus:
    """Tracks the focused window's class via Hyprland's IPC sockets.

    .socket.sock answers one-off queries; .socket2.sock streams events, so
    focus changes arrive as they happen instead of being polled for.
    """

    def __init__(self):
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if not sig or not runtime:
            raise RuntimeError("not running under Hyprland "
                               "(HYPRLAND_INSTANCE_SIGNATURE unset)")
        self.dir = os.path.join(runtime, "hypr", sig)
        if not os.path.isdir(self.dir):
            raise RuntimeError(f"Hyprland IPC directory missing: {self.dir}")

        self.events = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.events.connect(os.path.join(self.dir, ".socket2.sock"))
        self.events.setblocking(False)
        self._buf = b""
        self.window_class = self._query_active()

    def _query_active(self):
        """Ask for the currently focused window, for our starting state."""
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(os.path.join(self.dir, ".socket.sock"))
            s.sendall(b"j/activewindow")
            chunks = []
            while True:
                chunk = s.recv(8192)
                if not chunk:
                    break
                chunks.append(chunk)
        try:
            return json.loads(b"".join(chunks)).get("class") or ""
        except (json.JSONDecodeError, AttributeError):
            return ""  # nothing focused

    def fileno(self):
        return self.events.fileno()

    def update(self):
        """Drain pending events. Returns False if Hyprland closed the socket."""
        try:
            data = self.events.recv(65536)
        except BlockingIOError:
            return True
        if not data:
            return False
        self._buf += data
        *lines, self._buf = self._buf.split(b"\n")
        for line in lines:
            name, _, payload = line.decode(errors="replace").partition(">>")
            if name == "activewindow":
                # Payload is "class,title"; titles may contain commas.
                self.window_class = payload.split(",", 1)[0]
        return True


# ---- main ------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="Toggle-hold a key on Wayland. Starts OFF; press the toggle key to start.")
    p.add_argument("key", nargs="?", default="w", choices=sorted(KEYS),
                   help="key to hold (default: w)")
    p.add_argument("-k", "--toggle", default="f8", choices=sorted(KEYS),
                   help="key that toggles the hold (default: f8)")
    p.add_argument("-t", "--target", default=DEFAULT_TARGET,
                   help="regex matched against the focused window class "
                        f"(default: {DEFAULT_TARGET!r})")
    p.add_argument("--any-window", action="store_true",
                   help="disable focus gating and hold regardless of focus")
    args = p.parse_args()

    target = re.compile(args.target)
    hold_code = KEYS[args.key]
    toggle_code = KEYS[args.toggle]

    keyboards = find_keyboards(toggle_code)
    if not keyboards:
        sys.exit(f"No readable keyboard exposing '{args.toggle}' found under /dev/input/.\n"
                 "Try: sudo usermod -aG input $USER (then re-login)")

    focus = None
    if not args.any_window:
        try:
            focus = HyprlandFocus()
        except (RuntimeError, OSError) as e:
            sys.exit(f"Focus tracking unavailable: {e}\n"
                     "Use --any-window to hold regardless of focus.")

    try:
        kb = VirtualKeyboard(hold_code)
    except PermissionError:
        sys.exit("No access to /dev/uinput. Try: sudo usermod -aG input $USER (then re-login)")
    except FileNotFoundError:
        sys.exit("/dev/uinput missing. Try: sudo modprobe uinput")

    print(f"Listening on: {', '.join(name for _, name in keyboards)}")
    if focus:
        print(f"Target window: /{args.target}/  (currently: {focus.window_class or 'none'})")
    else:
        print("Target window: ANY (focus gating disabled)")
    print(f"{args.toggle.upper()} arms holding '{args.key}'. Ctrl+C to quit.")

    key_fds = [fd for fd, _ in keyboards]
    armed = False

    def on_target():
        return focus is None or bool(target.search(focus.window_class))

    def status():
        if not armed:
            state = "OFF"
        elif kb.held:
            state = f"HOLDING '{args.key}'"
        else:
            state = "WAITING (not focused)"
        print(f"\r\033[K{state}", end="", flush=True)

    status()
    try:
        while True:
            ready, _, _ = select.select(key_fds + ([focus] if focus else []), [], [])
            for src in ready:
                if src is focus:
                    if not focus.update():
                        print("\nHyprland IPC closed; exiting.")
                        return
                else:
                    for code in read_key_presses(src):
                        if code == toggle_code:
                            armed = not armed

            # Recomputed after every event, so losing focus releases the key
            # right away rather than leaving it stuck down in another window.
            kb.set_held(armed and on_target())
            status()
    except KeyboardInterrupt:
        pass
    finally:
        kb.close()
        for fd in key_fds:
            os.close(fd)
        if focus:
            focus.events.close()
        print("\nReleased.")


if __name__ == "__main__":
    main()
