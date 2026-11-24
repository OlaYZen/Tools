#!/usr/bin/env python3
"""Toggle-hold a key (default: w) on Windows 10/11.

Starts with the hold OFF. Press F8 to arm it. Ctrl+C to quit.

The key is only held while the target window (default: the Lunar Client
Minecraft window) is in the foreground. Alt-tab away and it releases
immediately; come back and it presses again.

Uses SendInput with hardware scancodes (so DirectInput/DirectX games see it)
and a system-wide low-level keyboard hook for the toggle key.
No dependencies — pure ctypes.
"""

import argparse
import ctypes
import ctypes.wintypes as w
import os
import re
import sys
import time

if os.name != "nt":
    sys.exit("This is the Windows version. On Linux use "
             "Linux/Scripts/Universal/key-holder instead.")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---- win32 constants -------------------------------------------------------
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
LLKHF_INJECTED = 0x00000010
PM_REMOVE = 0x0001
MAPVK_VK_TO_VSC_EX = 0x04
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# The game window's title carries its version ("Lunar Client 26.2 (v2.22...)"),
# so match a prefix rather than the whole string.
DEFAULT_TARGET = r"(?i)^Lunar Client \d"

# Marker stamped on our own injected events so the hook can ignore them.
EXTRA_INFO = 0x484F4C44  # "HOLD"

# Virtual-key codes (winuser.h). Scancodes are derived at runtime.
KEYS = {
    "w": 0x57, "a": 0x41, "s": 0x53, "d": 0x44,
    "q": 0x51, "e": 0x45, "r": 0x52, "f": 0x46,
    "space": 0x20, "shift": 0xA0, "ctrl": 0xA2, "alt": 0xA4, "tab": 0x09,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}

# Keys that live on the extended half of the scancode table.
EXTENDED_VKS = {0x26, 0x28, 0x25, 0x27, 0xA3, 0xA5}  # arrows, RCtrl, RAlt

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


# ---- structs ---------------------------------------------------------------
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
                ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", w.DWORD), ("wParamL", w.WORD), ("wParamH", w.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


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
user32.MapVirtualKeyW.argtypes = [w.UINT, w.UINT]
user32.MapVirtualKeyW.restype = w.UINT
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, w.HINSTANCE, w.DWORD]
user32.SetWindowsHookExW.restype = w.HHOOK
user32.CallNextHookEx.argtypes = [w.HHOOK, ctypes.c_int, w.WPARAM, w.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [w.HHOOK]
kernel32.GetModuleHandleW.argtypes = [w.LPCWSTR]
kernel32.GetModuleHandleW.restype = w.HINSTANCE
user32.GetForegroundWindow.restype = w.HWND
user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.GetWindowTextLengthW.argtypes = [w.HWND]
user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
kernel32.OpenProcess.restype = w.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR,
                                                ctypes.POINTER(w.DWORD)]
kernel32.CloseHandle.argtypes = [w.HANDLE]


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
class VirtualKey:
    """Holds exactly one key down via synthesized scancode input."""

    def __init__(self, vk):
        self.vk = vk
        self.held = False
        self.extended = vk in EXTENDED_VKS
        self.scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC_EX) & 0xFF
        if not self.scan:
            raise RuntimeError(f"no scancode for virtual key {vk:#x}")

    def _send(self, keyup):
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if keyup else 0)
        if self.extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.ki = KEYBDINPUT(wVk=0, wScan=self.scan, dwFlags=flags,
                            time=0, dwExtraInfo=EXTRA_INFO)
        if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
            raise ctypes.WinError(ctypes.get_last_error())

    def set_held(self, held):
        if held == self.held:
            return
        self._send(keyup=not held)
        self.held = held

    def close(self):
        try:
            self.set_held(False)
        except OSError as e:
            print(f"warning: could not send key release: {e}", file=sys.stderr)


# ---- main ------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="Toggle-hold a key on Windows. Starts OFF; press the toggle key to start.")
    p.add_argument("key", nargs="?", default="w", choices=sorted(KEYS),
                   help="key to hold (default: w)")
    p.add_argument("-k", "--toggle", default="f8", choices=sorted(KEYS),
                   help="key that toggles the hold (default: f8)")
    p.add_argument("-t", "--target", default=DEFAULT_TARGET,
                   help="regex matched against the foreground window title or exe "
                        f"(default: {DEFAULT_TARGET!r})")
    p.add_argument("--any-window", action="store_true",
                   help="disable focus gating and hold regardless of focus")
    args = p.parse_args()

    toggle_vk = KEYS[args.toggle]
    kb = VirtualKey(KEYS[args.key])
    focus = None if args.any_window else ForegroundWindow(re.compile(args.target))

    armed = False

    def on_target():
        return focus is None or focus.matches()

    def status():
        if not armed:
            state = "OFF"
        elif kb.held:
            state = f"HOLDING '{args.key}'"
        else:
            state = "WAITING (not focused)"
        print(f"\r\033[K{state}", end="", flush=True)

    def on_key(nCode, wParam, lParam):
        nonlocal armed
        if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            ev = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            # Ignore anything we injected ourselves.
            if ev.vkCode == toggle_vk and ev.dwExtraInfo != EXTRA_INFO:
                armed = not armed
                kb.set_held(armed and on_target())
                status()
        # Always pass the key through to the focused window.
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    callback = HOOKPROC(on_key)  # keep a reference; GC would break the hook
    hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, callback,
                                    kernel32.GetModuleHandleW(None), 0)
    if not hook:
        kb.close()
        sys.exit(f"Failed to install keyboard hook: {ctypes.WinError(ctypes.get_last_error())}")

    # Release the key if the console window is closed or Ctrl+Break is used.
    HANDLER = ctypes.WINFUNCTYPE(w.BOOL, w.DWORD)
    handler = HANDLER(lambda ctrl_type: (kb.close(), False)[1])
    kernel32.SetConsoleCtrlHandler(handler, True)

    print("Listening: system-wide keyboard hook")
    if focus:
        focus.matches()  # prime the cache so the first status line is accurate
        print(f"Target window: /{args.target}/  (currently: {focus.description})")
    else:
        print("Target window: ANY (focus gating disabled)")
    print(f"{args.toggle.upper()} arms holding '{args.key}'. Ctrl+C to quit.")
    status()

    msg = w.MSG()
    try:
        # PeekMessage rather than GetMessage: a blocking GetMessage would swallow
        # Ctrl+C, since Python only runs signal handlers between bytecodes.
        while True:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            # Re-checked every tick, so losing focus releases the key right
            # away rather than leaving it stuck down in another window.
            want = armed and on_target()
            if want != kb.held:
                kb.set_held(want)
                status()
            time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        user32.UnhookWindowsHookEx(hook)
        kb.close()
        print("\nReleased.")


if __name__ == "__main__":
    main()
