#!/usr/bin/env python3
"""Find out which format B field, if any, responds to the steering wheel.

Format A carries no steering channel at all, so its `steering` is always None -
a hidden meter there is correct, not broken. This checks format B.

Two modes, because only one program may hold the telemetry port:

    python tools/steering_probe.py --via http://localhost:6767
        Watches a dashboard you are already running. Start that dashboard with
        `--format B` first. No port conflict - this is only an HTTP client.

    python tools/steering_probe.py 192.168.1.67
        Binds the port itself, so every other GT7 client must be stopped. Waits
        for the port, then lets the console's session lapse before asking for
        format B, since any heartbeat renews the current session.

Either way: turn the wheel lock to lock while it watches.
"""

from __future__ import annotations

import json
import socket
import struct
import sys
import time
import urllib.request
from pathlib import Path

# Running a file inside tools/ puts tools/ on sys.path, not the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gt7.client import RECV_PORT, SEND_PORT, port_is_free  # noqa: E402
from gt7.crypto import FORMAT_B, decrypt  # noqa: E402

EXTRA_OFFSETS = (0x128, 0x12C, 0x130, 0x134, 0x138)

#: Control channels. If these are frozen too then the game was paused or in a
#: menu, and a "nothing responded" result says nothing about the extra fields.
#: Without this check the probe returns a confident false negative.
CONTROL_OFFSETS = ((0x3C, "rpm"), (0x4C, "speed m/s"), (0x94, "road plane x"))
CAPTURE_SECONDS = 40

#: Long, so it can just sit there and start the moment you stop your dashboard.
PORT_WAIT_SECONDS = 1800

#: A wheel turned lock to lock should swing far further than this. Anything
#: less and the field is not tracking the wheel.
RESPONDS_RANGE = 0.3


def _verdict(span: float) -> str:
    if span < 1e-6:
        return "dead - constant"
    if span > RESPONDS_RANGE:
        return "RESPONDS - wide swing"
    return "moves a little"


def watch_via_http(base_url: str) -> int:
    """Read `steering` from a dashboard that is already running."""
    print(f"[*] watching {base_url} for {CAPTURE_SECONDS}s")
    print("[*] TURN THE WHEEL LOCK TO LOCK NOW", flush=True)

    values: list[float] = []
    missing = 0
    start = time.monotonic()
    while time.monotonic() - start < CAPTURE_SECONDS:
        try:
            with urllib.request.urlopen(f"{base_url}/api/telemetry", timeout=2) as r:
                frame = json.load(r)["telemetry"]
        except Exception:
            time.sleep(0.5)
            continue
        angle = frame.get("steering")
        if angle is None:
            missing += 1
        else:
            values.append(angle)
        time.sleep(0.05)

    if missing and not values:
        print("[-] that dashboard is serving format A, where `steering` is absent")
        print("    rather than stuck. Stop it, wait 30s for the console's session")
        print("    to lapse, then start it again with `--format B`.")
        return 1
    if not values:
        print("[-] no telemetry at all from that dashboard")
        return 1

    lo, hi = min(values), max(values)
    changed = sum(1 for a, b in zip(values, values[1:]) if a != b)
    span = hi - lo
    print(f"[*] {len(values)} samples")
    print(f"    min {lo:+.4f}   max {hi:+.4f}   range {span:.4f}   changed {changed}")
    if span > RESPONDS_RANGE:
        print("[+] steering RESPONDS - 0x128 does track the wheel")
        return 0
    print("[-] steering did NOT move meaningfully.")
    print("    0x128 is not the steering channel, and the field needs relabelling.")
    return 1


def wait_for_port(timeout: float = PORT_WAIT_SECONDS) -> bool:
    print("[*] waiting for the telemetry port to free up "
          "(stop any running dashboard)...", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_is_free():
            print("[+] port is free", flush=True)
            return True
        time.sleep(2)
    return False


def _wait_until_live(sock: socket.socket, host: str,
                     timeout: float = 900.0) -> bool:
    """Block until the sim is actually running, not paused on a frozen frame."""
    print("[*] waiting for the game to be unpaused and moving...", flush=True)
    recent: list[float] = []
    beat = 0.0
    announced = 0.0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now - beat > 2.0:
            sock.sendto(FORMAT_B.heartbeat, (host, SEND_PORT))
            beat = now
        try:
            payload, _ = sock.recvfrom(4096)
        except socket.timeout:
            continue
        if len(payload) != FORMAT_B.size:
            continue
        plain = decrypt(payload)
        recent.append(struct.unpack_from("<f", plain, 0x3C)[0])  # rpm
        if len(recent) > 120:
            recent.pop(0)
        if len(recent) == 120 and len(set(recent)) > 5:
            return True
        if now - announced > 15:
            announced = now
            print("    still paused (rpm frozen) - unpause when ready", flush=True)
    return False


def capture_direct(host: str) -> int:
    if not wait_for_port():
        print("[-] port never freed up")
        return 1

    # The console pins the wire format per session and every heartbeat renews
    # it, so a format B request only takes once the old session has lapsed.
    print("[*] letting the console's session lapse (30s)...", flush=True)
    time.sleep(30)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", RECV_PORT))
    sock.settimeout(0.5)
    sock.sendto(FORMAT_B.heartbeat, (host, SEND_PORT))

    # The console keeps streaming at 60 Hz while the game is paused, handing
    # out a frozen snapshot. Capturing that produces a confident false
    # negative, so wait until the sim is genuinely running first.
    if not _wait_until_live(sock, host):
        print("[-] the game stayed paused. Unpause, get on track, and rerun.")
        sock.close()
        return 1

    print(f"[*] LIVE - TURN THE WHEEL LOCK TO LOCK "
          f"for the next {CAPTURE_SECONDS}s", flush=True)
    series: dict[int, list[float]] = {off: [] for off in EXTRA_OFFSETS}
    control: dict[int, list[float]] = {off: [] for off, _ in CONTROL_OFFSETS}
    frames = 0
    sizes: dict[int, int] = {}
    beat = 0.0
    start = time.monotonic()
    while time.monotonic() - start < CAPTURE_SECONDS:
        now = time.monotonic()
        if now - beat > 2.0:
            sock.sendto(FORMAT_B.heartbeat, (host, SEND_PORT))
            beat = now
        try:
            payload, _ = sock.recvfrom(4096)
        except socket.timeout:
            continue
        sizes[len(payload)] = sizes.get(len(payload), 0) + 1
        if len(payload) != FORMAT_B.size:
            continue
        plain = decrypt(payload)
        for off in EXTRA_OFFSETS:
            series[off].append(struct.unpack_from("<f", plain, off)[0])
        for off, _ in CONTROL_OFFSETS:
            control[off].append(struct.unpack_from("<f", plain, off)[0])
        frames += 1
    sock.close()

    print(f"[*] packet sizes seen: {sizes}", flush=True)
    if FORMAT_B.size not in sizes:
        print("[-] the console never sent format B - its session had not lapsed.")
        print("    Stop every client, wait a minute, and run this again.")
        return 1

    print(f"[*] {frames} format B frames\n")

    # Control first: is the sim actually running?
    print("control channels (proof the game was live):")
    live = False
    for off, name in CONTROL_OFFSETS:
        values = control[off]
        changed = sum(1 for a, b in zip(values, values[1:]) if a != b)
        if changed:
            live = True
        print(f"  0x{off:03x} {name:<14} min {min(values):10.4f}  max {max(values):10.4f}"
              f"  changed {changed}")
    if not live:
        print("\n[-] every control channel is frozen too, so the game was paused")
        print("    or sitting in a menu. This run proves nothing about steering.")
        print("    Get on track and moving, then run it again.")
        return 1
    print()

    print(f"{'offset':>7} {'min':>10} {'max':>10} {'range':>10} {'changed':>8}  verdict")
    responded = []
    for off in EXTRA_OFFSETS:
        values = series[off]
        lo, hi = min(values), max(values)
        changed = sum(1 for a, b in zip(values, values[1:]) if a != b)
        span = hi - lo
        if span > RESPONDS_RANGE:
            responded.append(off)
        print(f"  0x{off:03x} {lo:10.4f} {hi:10.4f} {span:10.4f} "
              f"{changed:8d}  {_verdict(span)}")

    print()
    if responded == [0x128]:
        print("[+] 0x128 alone responded - it is the steering channel.")
    elif responded:
        print(f"[!] responded: {', '.join(hex(o) for o in responded)}")
        print("    If 0x128 is not among them, the field is mislabelled.")
    else:
        print("[-] nothing responded. If you really turned the wheel, format B")
        print("    carries no steering channel and 0x128 needs relabelling.")
    return 0


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--via":
        return watch_via_http(sys.argv[2].rstrip("/"))
    return capture_direct(sys.argv[1] if len(sys.argv) > 1 else "192.168.1.67")


if __name__ == "__main__":
    raise SystemExit(main())
