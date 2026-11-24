#!/usr/bin/env python3
"""
KDE Linux Discord/Vesktop muter.

Saves the currently focused window, switches to Discord/Vesktop, sends
Ctrl+Shift+M (mute) or Ctrl+Shift+D (deafen), then restores focus.

Requirements
------------
  xdotool   – window focus/search  (pacman -S xdotool)
  ydotool   – Wayland key injection (pacman -S ydotool)
              ydotoold daemon must be running:
                systemctl --user enable --now ydotool
  flask     – HTTP server           (pip install flask)

KDE Wayland note
----------------
Discord and Vesktop normally run through XWayland, so xdotool works fine.
If you force native-Wayland mode (--ozone-platform=wayland) they become
invisible to xdotool; use the XWayland launch flag instead:
    vesktop --no-sandbox --ozone-platform=x11
"""

import os
import re
import subprocess
import threading
import time

from flask import Flask, jsonify

app = Flask(__name__)

# ── Config ─────────────────────────────────────────────────────────────────
# Window class names tried in order for each tool
DISCORD_CLASSES_XDOTOOL = ["vesktop", "Vesktop", "discord", "Discord"]

# Seconds between Discord-window rediscovery
DISCORD_CACHE_TTL = 10

# ── KDE guard ───────────────────────────────────────────────────────────────
def _assert_kde():
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "kde" not in desktop:
        raise RuntimeError(
            f"This script requires KDE Plasma. "
            f"Current desktop: {os.environ.get('XDG_CURRENT_DESKTOP', 'unknown')}"
        )

# ── xdotool helpers ────────────────────────────────────────────────────────
def _xdotool(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["xdotool", *args],
        capture_output=True, text=True,
    )


def _qdbus(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["qdbus", *args],
        capture_output=True, text=True, timeout=2,
    )


def get_focused_window() -> str | None:
    """Return the currently focused X11 window ID.

    Tries xdotool first (works for XWayland apps).  Falls back to KWin's
    D-Bus interface, which also knows about native Wayland windows — it
    returns the X11 client ID for XWayland clients and the internal KWin
    handle for native Wayland clients (both are usable with wmctrl).
    """
    r = _xdotool("getactivewindow")
    wid = r.stdout.strip()
    if r.returncode == 0 and wid:
        print(f"[DEBUG] Focused window (xdotool): {wid}")
        return wid

    # xdotool can't see native Wayland windows — ask KWin directly
    try:
        r2 = _qdbus("org.kde.KWin", "/KWin", "activeWindow")
        wid2 = r2.stdout.strip()
        if r2.returncode == 0 and wid2 and wid2 != "0":
            print(f"[DEBUG] Focused window (qdbus KWin): {wid2}")
            return wid2
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    print(f"[WARN]  Could not get focused window: {r.stderr.strip()}")
    return None


def get_discord_window() -> str | None:
    """Find the first Discord/Vesktop window by WM_CLASS."""
    for cls in DISCORD_CLASSES_XDOTOOL:
        r = _xdotool("search", "--class", cls)
        if r.returncode == 0 and r.stdout.strip():
            wid = r.stdout.strip().splitlines()[0]
            print(f"[DEBUG] Found Discord window (class={cls}): {wid}")
            return wid
    print("[ERROR] Discord/Vesktop window not found")
    return None


def focus_window(wid: str) -> bool:
    """Activate a window by ID using the best available method.

    Strategy (in order):
    1. wmctrl -ia  — sends _NET_ACTIVE_WINDOW with source=pager; KDE honours
                     this even with focus-stealing protection enabled, and it
                     works for any XWayland window.
    2. xdotool windowactivate --sync  — EWMH fallback.
    3. xdotool windowraise + windowfocus  — last resort (often blocked by KWin).
    """
    if not wid:
        return False

    # wmctrl needs a hex window ID
    try:
        hex_wid = hex(int(wid))
        r = subprocess.run(
            ["wmctrl", "-ia", hex_wid],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0:
            print(f"[DEBUG] Activated {wid} via wmctrl")
            return True
    except (ValueError, FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # xdotool windowactivate
    r = _xdotool("windowactivate", "--sync", wid)
    if r.returncode == 0:
        print(f"[DEBUG] Activated {wid} via xdotool windowactivate")
        return True

    # Last resort
    r1 = _xdotool("windowraise", wid)
    r2 = _xdotool("windowfocus", "--sync", wid)
    ok = r1.returncode == 0 and r2.returncode == 0
    print(f"[{'DEBUG' if ok else 'WARN'}] focus_window({wid}) windowraise+focus: ok={ok}")
    return ok


# ── ydotool key injection ──────────────────────────────────────────────────
# Scancodes used by ydotool (evdev key codes)
_KEY_CODES = {
    "m": 50,   # KEY_M
    "d": 32,   # KEY_D
}


def send_key_ydotool(key_letter: str) -> bool:
    """Send Ctrl+Shift+<key> via ydotool (works on Wayland)."""
    code = _KEY_CODES.get(key_letter.lower())
    if code is None:
        print(f"[ERROR] Unknown key: {key_letter}")
        return False
    try:
        subprocess.run(
            [
                "ydotool", "key",
                "29:1",          # Left Ctrl  down
                "42:1",          # Left Shift down
                f"{code}:1",     # Key down
                f"{code}:0",     # Key up
                "42:0",          # Left Shift up
                "29:0",          # Left Ctrl  up
            ],
            check=True,
            capture_output=True,
        )
        print(f"[INFO]  Sent Ctrl+Shift+{key_letter.upper()} via ydotool")
        return True
    except FileNotFoundError:
        print("[ERROR] ydotool not found – is it installed and ydotoold running?")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] ydotool failed: {e.stderr.strip() if e.stderr else e}")
    return False


def send_key_xdotool(key_letter: str) -> bool:
    """Fallback: send Ctrl+Shift+<key> via xdotool (X11 only)."""
    try:
        subprocess.run(
            ["xdotool", "key", f"ctrl+shift+{key_letter}"],
            check=True, capture_output=True,
        )
        print(f"[INFO]  Sent Ctrl+Shift+{key_letter.upper()} via xdotool (fallback)")
        return True
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"[ERROR] xdotool key send failed: {e}")
    return False


# ── Discord window cache ────────────────────────────────────────────────────
_discord_wid: str | None = None
_discord_ts: float = 0.0


def get_discord_window_cached() -> str | None:
    global _discord_wid, _discord_ts
    if _discord_wid is None or time.time() - _discord_ts > DISCORD_CACHE_TTL:
        _discord_wid = get_discord_window()
        _discord_ts = time.time()
    return _discord_wid


# ── Core toggle ────────────────────────────────────────────────────────────
def toggle_discord(key_letter: str) -> bool:
    print(f"\n[INFO]  === DISCORD TOGGLE: Ctrl+Shift+{key_letter.upper()} ===")

    original_wid = get_focused_window()
    discord_wid  = get_discord_window_cached()

    if not discord_wid:
        print("[ERROR] Aborting: Discord/Vesktop not running.")
        return False

    # Switch to Discord
    focus_window(discord_wid)
    time.sleep(0.08)   # let KWin complete the focus switch

    # Send keybind — prefer ydotool, fall back to xdotool
    sent = send_key_ydotool(key_letter)
    if not sent:
        sent = send_key_xdotool(key_letter)

    # Give Discord time to register the shortcut before we pull focus away
    time.sleep(0.2)

    # Restore original window
    if original_wid and original_wid != discord_wid:
        print("[DEBUG] Restoring focus to original window…")
        focus_window(original_wid)
    else:
        print("[INFO]  No focus restore needed (Discord was already focused)")

    print(f"[INFO]  === TOGGLE COMPLETE (sent={sent}) ===\n")
    return sent


def _toggle_async(key_letter: str):
    threading.Thread(target=toggle_discord, args=(key_letter,), daemon=True).start()


# ── Flask routes ────────────────────────────────────────────────────────────
@app.route("/mute", methods=["POST"])
def mute():
    _toggle_async("m")
    return jsonify({"status": "ok", "action": "mute toggled"})


@app.route("/deafen", methods=["POST"])
def deafen():
    _toggle_async("d")
    return jsonify({"status": "ok", "action": "deafen toggled"})


@app.route("/status", methods=["GET"])
def status():
    discord_wid = get_discord_window_cached()
    return jsonify({
        "kde": True,
        "discord_window": discord_wid,
        "discord_found": discord_wid is not None,
    })


# ── Entry point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _assert_kde()
    print("[INFO]  KDE Discord Muter starting on http://localhost:8784")
    print("[INFO]  POST /mute   → Ctrl+Shift+M")
    print("[INFO]  POST /deafen → Ctrl+Shift+D")
    print("[INFO]  GET  /status → Discord window info")
    app.run(host="127.0.0.1", port=8784)
