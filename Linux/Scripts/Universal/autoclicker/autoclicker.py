#!/usr/bin/env python3
"""Auto-clicker with human-ish timing, scoped to one app, on Hyprland/Wayland.

Left-clicks every 3-7s. Roughly 1 click in 20 turns into a short burst of
3-5 rapid clicks. Click rate is hard-capped at 7 CPS.

Just before each click the cursor glides to a new spot inside a small circle
(12px radius by default), so clicks don't all land on one dead-still pixel.

Clicks are only emitted while the target window (default: the Lunar Client
Minecraft window) is focused. Alt-tab away and it pauses; come back and it
resumes. Focus is tracked live over Hyprland's IPC event socket.

Starts OFF. Press F9 to arm, Ctrl+C to quit.
"""

import argparse
import ctypes
import fcntl
import math
import os
import random
import re
import select
import struct
import sys
import time

# key_holder.py sits in a sibling folder and holds the shared uinput plumbing
# (constants, ioctls, keyboard discovery, Hyprland focus tracking).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "key-holder"))

from key_holder import (EV_KEY, EV_SYN, SYN_REPORT, BUS_USB, EVENT_FMT,
                        UI_DEV_CREATE, UI_DEV_DESTROY, UI_DEV_SETUP,
                        UI_SET_EVBIT, UI_SET_KEYBIT, _iow, UINPUT_IOCTL_BASE,
                        KEYS, find_keyboards, read_key_presses,
                        HyprlandFocus, DEFAULT_TARGET)

UI_SET_RELBIT = _iow(UINPUT_IOCTL_BASE, 102, ctypes.sizeof(ctypes.c_int))

EV_REL = 0x02
REL_X, REL_Y = 0x00, 0x01
BTN_LEFT = 0x110

VIRTUAL_NAME = "python-autoclicker"

# ---- timing ----------------------------------------------------------------
MAX_CPS = 7
MIN_INTERVAL = 1.0 / MAX_CPS  # hard floor, never exceeded

IDLE_INTERVAL = (3.0, 7.0)    # normal gap between clicks
BURST_INTERVAL = (0.15, 0.25) # gap inside a burst (~4-6.7 CPS)
BURST_CHANCE = 1 / 20         # how often a click becomes a burst
BURST_LENGTH = (3, 5)         # clicks per burst, inclusive
HOLD_DURATION = (0.04, 0.09)  # how long the button stays down

# ---- movement --------------------------------------------------------------
# The cursor wanders inside a small circle centred where it started, taking a
# new position just before each click. Motion is emitted as many small relative
# steps: 3D games read relative deltas from a grabbed pointer, so a single large
# jump reads as a teleport and breaks camera aiming.
DRIFT_RADIUS = 12             # px; how far from centre the cursor may stray
MOVE_DURATION = (0.08, 0.18)  # seconds to travel to a new spot
BURST_RADIUS = 3              # px; bursts only nudge, they don't wander
BURST_DURATION = (0.02, 0.05)
STEP_INTERVAL = 0.006         # ~165 Hz, in the range a real mouse reports at


def next_delay(burst_left, rng=random):
    """Decide the gap after a click. Returns (delay, burst_left, started_burst).

    burst_left is how many clicks still owed to an in-progress burst.
    """
    started_burst = False
    if burst_left > 0:
        burst_left -= 1
        delay = rng.uniform(*BURST_INTERVAL)
    elif rng.random() < BURST_CHANCE:
        # This click becomes the first of a burst; the rest follow rapidly.
        burst_left = rng.randint(*BURST_LENGTH) - 1
        started_burst = True
        delay = rng.uniform(*BURST_INTERVAL)
    else:
        delay = rng.uniform(*IDLE_INTERVAL)
    return max(delay, MIN_INTERVAL), burst_left, started_burst


# ---- output device ---------------------------------------------------------
class VirtualMouse:
    """A virtual mouse that can press its left button."""

    def __init__(self, name=VIRTUAL_NAME):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(self.fd, UI_SET_KEYBIT, BTN_LEFT)
        # libinput only treats a device as a pointer if it has relative axes
        # alongside the buttons, so advertise them even though we never move.
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_REL)
        fcntl.ioctl(self.fd, UI_SET_RELBIT, REL_X)
        fcntl.ioctl(self.fd, UI_SET_RELBIT, REL_Y)
        setup = struct.pack("@4H80sI", BUS_USB, 0x1234, 0x5679, 1,
                            name.encode(), 0)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        time.sleep(0.3)  # let the compositor notice the new device
        self.ox = self.oy = 0  # offset from where the cursor started

    def _emit(self, etype, code, value):
        os.write(self.fd, struct.pack(EVENT_FMT, 0, 0, etype, code, value))

    def drift(self, radius=DRIFT_RADIUS, duration=MOVE_DURATION):
        """Glide to a new random point inside the circle, then stop.

        Position is tracked as our own offset from where we started rather than
        read back from the compositor, so the wander stays bounded even while a
        game holds the pointer grabbed and no absolute cursor exists.
        """
        # Uniform over the disc's area: sqrt() keeps points from bunching up
        # in the middle the way a plain uniform radius would.
        r = radius * math.sqrt(random.random())
        angle = random.uniform(0, 2 * math.pi)
        dx = r * math.cos(angle) - self.ox
        dy = r * math.sin(angle) - self.oy
        if math.hypot(dx, dy) < 1.0:
            return

        steps = max(2, int(random.uniform(*duration) / STEP_INTERVAL))
        sent_x = sent_y = 0
        for i in range(1, steps + 1):
            p = i / steps
            eased = p * p * (3 - 2 * p)  # smoothstep: ease in and out, no jerk
            # Emit the difference between where we should be and where we have
            # actually put the cursor, so rounding never accumulates error.
            step_x = round(dx * eased) - sent_x
            step_y = round(dy * eased) - sent_y
            if step_x or step_y:
                if step_x:
                    self._emit(EV_REL, REL_X, step_x)
                if step_y:
                    self._emit(EV_REL, REL_Y, step_y)
                self._emit(EV_SYN, SYN_REPORT, 0)
                sent_x += step_x
                sent_y += step_y
            time.sleep(STEP_INTERVAL)
        self.ox += sent_x
        self.oy += sent_y

    def click(self, hold=None):
        self._emit(EV_KEY, BTN_LEFT, 1)
        self._emit(EV_SYN, SYN_REPORT, 0)
        time.sleep(hold if hold is not None else random.uniform(*HOLD_DURATION))
        self._emit(EV_KEY, BTN_LEFT, 0)
        self._emit(EV_SYN, SYN_REPORT, 0)

    def close(self):
        try:
            self._emit(EV_KEY, BTN_LEFT, 0)  # never leave the button stuck
            self._emit(EV_SYN, SYN_REPORT, 0)
        except OSError as e:
            print(f"warning: could not release button: {e}", file=sys.stderr)
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(self.fd)


# ---- main ------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="Randomized auto-clicker that only fires while a target window is focused.")
    p.add_argument("-k", "--toggle", default="f9", choices=sorted(KEYS),
                   help="key that arms/disarms clicking (default: f9)")
    p.add_argument("-t", "--target", default=DEFAULT_TARGET,
                   help="regex matched against the focused window class "
                        f"(default: {DEFAULT_TARGET!r})")
    p.add_argument("--any-window", action="store_true",
                   help="disable focus gating and click into whatever is focused")
    p.add_argument("-r", "--radius", type=float, default=DRIFT_RADIUS,
                   help=f"radius in px of the circle the cursor wanders in "
                        f"(default: {DRIFT_RADIUS}, 0 disables movement)")
    args = p.parse_args()

    target = re.compile(args.target)

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
                     "Use --any-window to click regardless of focus.")

    try:
        mouse = VirtualMouse()
    except PermissionError:
        sys.exit("No access to /dev/uinput. Try: sudo usermod -aG input $USER (then re-login)")
    except FileNotFoundError:
        sys.exit("/dev/uinput missing. Try: sudo modprobe uinput")

    print(f"Listening on: {', '.join(name for _, name in keyboards)}")
    if focus:
        print(f"Target window: /{args.target}/  (currently: {focus.window_class or 'none'})")
    else:
        print("Target window: ANY (focus gating disabled)")
    print(f"{args.toggle.upper()} arms clicking. Ctrl+C to quit.")

    key_fds = [fd for fd, _ in keyboards]
    armed = False
    clicks = bursts = 0
    burst_left = 0
    next_click_at = 0.0

    def on_target():
        return focus is None or bool(target.search(focus.window_class))

    def status(extra=""):
        if not armed:
            state = "OFF"
        elif on_target():
            state = "CLICKING"
        else:
            state = "WAITING (not focused)"
        print(f"\r\033[K{state}  |  clicks: {clicks}  bursts: {bursts}  {extra}",
              end="", flush=True)

    status()
    try:
        while True:
            active = armed and on_target()
            timeout = max(0.0, next_click_at - time.monotonic()) if active else None
            watch = key_fds + ([focus] if focus else [])
            ready, _, _ = select.select(watch, [], [], timeout)

            was_active = active
            for src in ready:
                if src is focus:
                    if not focus.update():
                        print("\nHyprland IPC closed; exiting.")
                        return
                else:
                    for code in read_key_presses(src):
                        if code == toggle_code:
                            armed = not armed
                            burst_left = 0  # don't resume a burst after a pause
                            next_click_at = time.monotonic()

            # Focus or arm state may have flipped; resync the schedule so we
            # don't fire a backlog of clicks the moment the window regains focus.
            active = armed and on_target()
            if active != was_active:
                burst_left = 0
                next_click_at = time.monotonic()
                status()

            if active and time.monotonic() >= next_click_at:
                # Reposition before clicking, the way a hand does. Mid-burst the
                # gap is only ~0.2s, so nudge instead of taking a full stroll.
                if burst_left:
                    mouse.drift(BURST_RADIUS, BURST_DURATION)
                elif args.radius:
                    mouse.drift(args.radius)
                mouse.click()
                clicks += 1
                delay, burst_left, started = next_delay(burst_left)
                if started:
                    bursts += 1
                next_click_at = time.monotonic() + delay
                status("BURST" if burst_left else "")
    except KeyboardInterrupt:
        pass
    finally:
        mouse.close()
        for fd in key_fds:
            os.close(fd)
        if focus:
            focus.events.close()
        print("\nStopped.")


if __name__ == "__main__":
    main()
