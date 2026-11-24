#!/usr/bin/env python3
"""Auto-clicker with human-ish timing, scoped to one app, on Windows 10/11.

Left-clicks every 3-7s. Roughly 1 click in 20 turns into a short burst of
3-5 rapid clicks. Click rate is hard-capped at 7 CPS.

Just before each click the cursor glides to a new spot inside a small circle
(12px radius by default), so clicks don't all land on one dead-still pixel.

Clicks are only emitted while the target window (default: the Lunar Client
Minecraft window) is in the foreground. Alt-tab away and it pauses; come
back and it resumes.

Starts OFF. Press F9 to arm, Ctrl+C to quit. No dependencies — pure ctypes.
"""

import argparse
import ctypes
import ctypes.wintypes as w
import math
import os
import random
import re
import sys
import time

if os.name != "nt":
    sys.exit("This is the Windows version. On Linux use "
             "Linux/Scripts/Universal/autoclicker instead.")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---- win32 constants -------------------------------------------------------
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001  # relative motion; absolute would need ABSOLUTE too
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
PM_REMOVE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Marker stamped on our own injected events so the hook can ignore them.
EXTRA_INFO = 0x484F4C44  # "HOLD"

# Virtual-key codes (winuser.h), for the toggle key.
KEYS = {
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "q": 0x51, "e": 0x45, "r": 0x52, "f": 0x46, "tab": 0x09,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pause": 0x13, "scrolllock": 0x91,
}

# The game window's title carries its version ("Lunar Client 26.2 (v2.22...)"),
# so match a prefix rather than the whole string.
DEFAULT_TARGET = r"(?i)^Lunar Client \d"

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


# ---- structs ---------------------------------------------------------------
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
                ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", w.DWORD), ("wParamL", w.WORD), ("wParamH", w.WORD)]


class _INPUTUNION(ctypes.Union):
    # MOUSEINPUT is the largest member; it sets the union's size.
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", w.DWORD), ("u", _INPUTUNION)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", w.DWORD), ("scanCode", w.DWORD), ("flags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]


LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
HOOKPROC = ctypes.CFUNCTYPE(LRESULT, ctypes.c_int, w.WPARAM, w.LPARAM)

user32.SendInput.argtypes = [w.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = w.UINT
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, w.HINSTANCE, w.DWORD]
user32.SetWindowsHookExW.restype = w.HHOOK
user32.CallNextHookEx.argtypes = [w.HHOOK, ctypes.c_int, w.WPARAM, w.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [w.HHOOK]
user32.GetForegroundWindow.restype = w.HWND
user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.GetWindowTextLengthW.argtypes = [w.HWND]
user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
kernel32.GetModuleHandleW.argtypes = [w.LPCWSTR]
kernel32.GetModuleHandleW.restype = w.HINSTANCE
kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
kernel32.OpenProcess.restype = w.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR,
                                                ctypes.POINTER(w.DWORD)]
kernel32.CloseHandle.argtypes = [w.HANDLE]

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
# steps: 3D games read relative deltas from a captured pointer, so a single
# large jump reads as a teleport and breaks camera aiming.
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


# ---- focus tracking --------------------------------------------------------
class ForegroundWindow:
    """Reports whether the foreground window matches the target.

    Windows has no focus event stream we can read without a second hook, so
    this polls GetForegroundWindow (very cheap). The expensive part -- the
    process image lookup -- is cached and only redone when the HWND changes.
    """

    def __init__(self, pattern):
        self.pattern = pattern
        self._hwnd = None
        self._matches = False
        self.description = ""

    @staticmethod
    def _title(hwnd):
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    @staticmethod
    def _exe(hwnd):
        pid = w.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            size = w.DWORD(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return ""
            return os.path.basename(buf.value)
        finally:
            kernel32.CloseHandle(handle)

    def matches(self):
        hwnd = user32.GetForegroundWindow()
        if hwnd != self._hwnd:
            self._hwnd = hwnd
            title = self._title(hwnd) if hwnd else ""
            exe = self._exe(hwnd) if hwnd else ""
            self.description = title or exe or "none"
            # Match either the title or the executable name, so a regex like
            # "javaw" works as well as one matching the visible title.
            self._matches = bool(self.pattern.search(title) or
                                 (exe and self.pattern.search(exe)))
        return self._matches


# ---- output ----------------------------------------------------------------
class VirtualMouse:
    """Synthesizes left-button clicks at the current cursor position."""

    def __init__(self):
        self.down = False
        self.ox = self.oy = 0  # offset from where the cursor started

    def _send(self, flags, dx=0, dy=0):
        inp = INPUT(type=INPUT_MOUSE)
        inp.mi = MOUSEINPUT(dx=dx, dy=dy, mouseData=0, dwFlags=flags,
                            time=0, dwExtraInfo=EXTRA_INFO)
        if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
            raise ctypes.WinError(ctypes.get_last_error())

    def drift(self, radius=DRIFT_RADIUS, duration=MOVE_DURATION):
        """Glide to a new random point inside the circle, then stop.

        Position is tracked as our own offset from where we started rather than
        read back with GetCursorPos, so the wander stays bounded even while a
        game has the pointer captured and the reported cursor sits still.
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
                self._send(MOUSEEVENTF_MOVE, step_x, step_y)
                sent_x += step_x
                sent_y += step_y
            time.sleep(STEP_INTERVAL)
        self.ox += sent_x
        self.oy += sent_y

    def click(self, hold=None):
        self._send(MOUSEEVENTF_LEFTDOWN)
        self.down = True
        time.sleep(hold if hold is not None else random.uniform(*HOLD_DURATION))
        self._send(MOUSEEVENTF_LEFTUP)
        self.down = False

    def close(self):
        if not self.down:
            return
        try:
            self._send(MOUSEEVENTF_LEFTUP)  # never leave the button stuck
        except OSError as e:
            print(f"warning: could not release button: {e}", file=sys.stderr)


# ---- main ------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="Randomized auto-clicker that only fires while a target window is focused.")
    p.add_argument("-k", "--toggle", default="f9", choices=sorted(KEYS),
                   help="key that arms/disarms clicking (default: f9)")
    p.add_argument("-t", "--target", default=DEFAULT_TARGET,
                   help="regex matched against the foreground window title or exe "
                        f"(default: {DEFAULT_TARGET!r})")
    p.add_argument("--any-window", action="store_true",
                   help="disable focus gating and click into whatever is focused")
    p.add_argument("-r", "--radius", type=float, default=DRIFT_RADIUS,
                   help=f"radius in px of the circle the cursor wanders in "
                        f"(default: {DRIFT_RADIUS}, 0 disables movement)")
    args = p.parse_args()

    toggle_vk = KEYS[args.toggle]
    focus = None if args.any_window else ForegroundWindow(re.compile(args.target))
    mouse = VirtualMouse()

    armed = False
    clicks = bursts = 0
    burst_left = 0
    next_click_at = 0.0

    def on_target():
        return focus is None or focus.matches()

    def status(extra=""):
        if not armed:
            state = "OFF"
        elif on_target():
            state = "CLICKING"
        else:
            state = "WAITING (not focused)"
        print(f"\r\033[K{state}  |  clicks: {clicks}  bursts: {bursts}  {extra}",
              end="", flush=True)

    def on_key(nCode, wParam, lParam):
        nonlocal armed, burst_left, next_click_at
        if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            ev = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            # Ignore anything we injected ourselves.
            if ev.vkCode == toggle_vk and ev.dwExtraInfo != EXTRA_INFO:
                armed = not armed
                burst_left = 0  # don't resume a burst after a pause
                next_click_at = time.monotonic()
                status()
        # Always pass the key through to the focused window.
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    callback = HOOKPROC(on_key)  # keep a reference; GC would break the hook
    hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, callback,
                                    kernel32.GetModuleHandleW(None), 0)
    if not hook:
        sys.exit(f"Failed to install keyboard hook: {ctypes.WinError(ctypes.get_last_error())}")

    # Release the button if the console window is closed or Ctrl+Break is used.
    HANDLER = ctypes.WINFUNCTYPE(w.BOOL, w.DWORD)
    handler = HANDLER(lambda ctrl_type: (mouse.close(), False)[1])
    kernel32.SetConsoleCtrlHandler(handler, True)

    if focus:
        focus.matches()  # prime the cache so the first status line is accurate
        print(f"Target window: /{args.target}/  (currently: {focus.description})")
    else:
        print("Target window: ANY (focus gating disabled)")
    print(f"{args.toggle.upper()} arms clicking. Ctrl+C to quit.")
    status()

    msg = w.MSG()
    was_active = False
    try:
        while True:
            # PeekMessage rather than GetMessage: a blocking GetMessage would
            # swallow Ctrl+C and stall the click schedule between keystrokes.
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            active = armed and on_target()
            # Focus may have flipped; resync so we don't fire a backlog of
            # clicks the moment the window regains focus.
            if active != was_active:
                burst_left = 0
                next_click_at = time.monotonic()
                was_active = active
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

            time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        user32.UnhookWindowsHookEx(hook)
        mouse.close()
        print("\nStopped.")


if __name__ == "__main__":
    main()
