"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

from . import analyze, dashboard, recorder
from .client import (
    PORT_BUSY_HELP,
    RECV_PORT,
    SEND_PORT,
    GT7Client,
    PortBusyError,
    port_is_free,
)
from .crypto import BY_NAME, BY_SIZE, FORMATS, decrypt
from .packet import format_lap_time, parse

DEFAULT_HOST = "192.168.1.67"


def _p(msg: str) -> None:
    print(msg, flush=True)


def _other_listeners() -> str:
    """Best-effort check for another process holding the telemetry port."""
    try:
        out = subprocess.run(["ss", "-lunp"], capture_output=True, text=True,
                             timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    hits = [ln.split("users:")[-1].strip()
            for ln in out.splitlines() if f":{RECV_PORT} " in ln]
    return ", ".join(hits)


def cmd_dash(args: argparse.Namespace) -> int:
    dashboard.run(args.host, args.format)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the web dashboard."""
    try:
        from .web import serve
    except ImportError:
        _p("the web dashboard needs FastAPI and uvicorn:")
        _p("    pip install 'fastapi' 'uvicorn[standard]'")
        return 1

    # Check the telemetry port before handing control to uvicorn, so a busy
    # port reads as one clear line instead of a traceback out of the server's
    # startup path.
    if not port_is_free():
        _p(f"[!] {PORT_BUSY_HELP}")
        busy = _other_listeners()
        if busy:
            _p(f"    holding it: {busy}")
        return 1
    shown = "localhost" if args.bind in ("0.0.0.0", "::") else args.bind
    _p(f"[*] GT7 {args.host} -> http://{shown}:{args.port}")
    if args.bind == "0.0.0.0":
        _p("    reachable from other devices on your network at this machine's IP")
    tracks = Path(args.tracks) if getattr(args, "tracks", None) else None
    # Report what the loop test throws out, rather than deleting quietly.
    from .library import TrackLibrary
    dropped = TrackLibrary(tracks).pruned_on_load
    if dropped:
        _p(f"[*] forgot {len(dropped)} saved map(s) that were not circuits: "
           f"{', '.join(dropped)}")
    serve(args.host, args.format, host=args.bind, port=args.port,
          library_path=tracks)
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Ask the console for each format in turn and report what comes back.

    Read the caveat this prints.  The console pins the wire format for the
    life of a telemetry session and renews that session on every heartbeat,
    so a probe loop can only see a format change if the session is already
    dead when it starts.  Otherwise every trial faithfully reports whatever
    the open session is serving.
    """
    _p("[!] note: the console runs ONE telemetry session for the whole network,")
    _p("    and any heartbeat - including one asking for a different format -")
    _p("    renews it. Another client anywhere on your LAN will therefore pin")
    _p("    the format and make every trial below report that one format.")
    others = _other_listeners()
    if others:
        _p(f"[!] something else is already listening on :{RECV_PORT}: {others}")
        _p("    stop it first, or this probe is measuring that client's session.")
    served: set[str] = set()
    for fmt in FORMATS:
        _p(f"[*] cooling down {args.cooldown}s so any open session can lapse...")
        time.sleep(args.cooldown)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", RECV_PORT))
        sock.settimeout(0.5)
        sock.sendto(fmt.heartbeat, (args.host, SEND_PORT))

        sizes: dict[int, int] = {}
        ok = bad = 0
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline:
            try:
                payload, _ = sock.recvfrom(4096)
            except socket.timeout:
                continue
            sizes[len(payload)] = sizes.get(len(payload), 0) + 1
            try:
                decrypt(payload)
                ok += 1
            except Exception:
                bad += 1
        sock.close()
        if not sizes:
            _p(f"    heartbeat {fmt.heartbeat!r} -> no reply   [{fmt.name}: {fmt.note}]")
            continue
        names = []
        for size in sizes:
            observed = BY_SIZE.get(size)
            names.append(observed.name if observed else f"?{size}B")
            served.update(names)
        tag = "" if names == [fmt.name] else f"  <- served {'/'.join(names)}, not {fmt.name}"
        _p(f"    heartbeat {fmt.heartbeat!r} -> sizes={sizes} decoded={ok} "
           f"failed={bad}   [{fmt.name}: {fmt.note}]{tag}")
    if len(served) == 1 and len(FORMATS) > 1:
        _p("")
        _p(f"[!] every trial returned format {served.pop()}: a session was already")
        _p("    open throughout, so this run says nothing about format support.")
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    """Print one annotated packet - decrypted hex plus the parsed fields."""
    client = GT7Client(args.host, args.format)
    with client:
        if client.wait_for_frame(args.timeout) is None:
            _p("no telemetry received (is GT7 running and past the menu?)")
            return 1
        frame = client.latest
    assert frame is not None
    raw = None
    # Re-capture one raw datagram so we can show the ciphertext-derived dump.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", RECV_PORT))
    sock.settimeout(1.0)
    sock.sendto(BY_NAME[args.format].heartbeat, (args.host, SEND_PORT))
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        try:
            payload, _ = sock.recvfrom(4096)
        except socket.timeout:
            continue
        try:
            raw = decrypt(payload)
            break
        except Exception:
            continue
    sock.close()

    if raw is not None:
        _p(analyze.hexdump(raw))
        _p("")
    _p(json.dumps({
        "packet_id": frame.packet_id,
        "car_code": frame.car_code,
        "speed_kph": round(frame.speed_kph, 2),
        "rpm": frame.rpm,
        "gear": frame.gear_label,
        "throttle_pct": round(frame.throttle_pct, 1),
        "brake_pct": round(frame.brake_pct, 1),
        "flags": [f.name for f in type(frame.flags) if f & frame.flags],
        "best_lap": format_lap_time(frame.best_lap_ms),
        "last_lap": format_lap_time(frame.last_lap_ms),
        "tyre_temp": frame.corner("tyre_temp"),
        "tyre_slip": dict(zip(("FL", "FR", "RL", "RR"),
                              [round(v, 4) for v in frame.tyre_slip])),
        "gear_ratios": [round(r, 4) for r in frame.active_gear_ratios],
        "extended": frame.has_extended,
        "wheel_rotation": frame.wheel_rotation,
    }, indent=2))
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    path = Path(args.output)
    _p(f"[*] recording {args.seconds}s of format {args.format} to {path}")
    count = recorder.record(args.host, path, args.seconds, args.format)
    _p(f"[+] {count} datagrams, {path.stat().st_size} bytes")
    return 0 if count else 1


def cmd_survey(args: argparse.Namespace) -> int:
    """Classify every 4-byte slot in a capture - constant, counter, or live."""
    frames = analyze.decrypt_all(payload for _, payload in recorder.read(Path(args.capture)))
    if not frames:
        _p("no decryptable frames in capture")
        return 1
    _p(f"[*] {len(frames)} frames\n")
    rows = [r for r in analyze.survey(frames)
            if not (args.unknown_only and r["field"])]
    if not rows:
        _p("every 4-byte slot in this format is mapped - no unknowns left.")
        return 0
    _p(f"{'off':>6} {'kind':<12} {'chg':>6} {'min':>14} {'max':>14}  field")
    for rec in rows:
        _p(f"0x{rec['offset']:04x} {rec['kind']:<12} {rec['changes']:>6} "
           f"{rec['min']:>14.6g} {rec['max']:>14.6g}  {rec['field']}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    """Compare two captures and report slots that behave differently.

    Intended for hunting conditionally-populated fields - notably weather.
    Record the same car on the same track in two conditions, then diff.
    """
    left = analyze.decrypt_all(p for _, p in recorder.read(Path(args.before)))
    right = analyze.decrypt_all(p for _, p in recorder.read(Path(args.after)))
    if not left or not right:
        _p("one of the captures had no decryptable frames")
        return 1
    _p(f"[*] {args.before}: {len(left)} frames   {args.after}: {len(right)} frames")

    rows = analyze.compare(left, right)
    if args.activated_only:
        rows = [r for r in rows if r["verdict"] == "activated"]
    if not rows:
        _p("")
        _p("no slot changed behaviour between these captures.")
        _p("if the two really were different conditions, the packet carries no")
        _p("field for it.")
        return 0

    _p("")
    _p(f"{'off':>6} {'verdict':<12} {'before':>24} {'after':>24}  field")
    for r in rows:
        before = f"{r['a_min']:.4g} .. {r['a_max']:.4g}"
        after = f"{r['b_min']:.4g} .. {r['b_max']:.4g}"
        mark = " (expected)" if r["expected"] else ""
        _p(f"0x{r['offset']:04x} {r['verdict']:<12} {before:>24} {after:>24}  "
           f"{r['field']}{mark}")

    interesting = [r for r in rows if not r["expected"]]
    activated = [r for r in interesting if r["verdict"] == "activated"]
    _p("")
    if activated:
        _p(f"[+] {len(activated)} slot(s) went from always-zero to live. These are")
        _p("    the signature of a field that only exists in the second condition.")
    elif not interesting:
        _p("[*] nothing beyond the fields that drift between any two captures")
        _p("    (position, clock, counters). No condition-dependent field here.")
    return 0


def cmd_csv(args: argparse.Namespace) -> int:
    """Stream telemetry to CSV for offline analysis."""
    cols = ["t", "packet_id", "lap", "speed_kph", "rpm", "gear", "throttle", "brake",
            "boost_bar", "fuel", "x", "y", "z",
            "tyre_fl", "tyre_fr", "tyre_rl", "tyre_rr",
            "slip_fl", "slip_fr", "slip_rl", "slip_rr"]
    out = open(args.output, "w") if args.output else sys.stdout
    try:
        print(",".join(cols), file=out)
        start = time.monotonic()
        seen: int | None = None

        def emit(f) -> None:
            nonlocal seen
            if f.packet_id == seen:
                return
            seen = f.packet_id
            row = [f"{time.monotonic() - start:.3f}", f.packet_id, f.current_lap,
                   f"{f.speed_kph:.3f}", f"{f.rpm:.0f}", f.gear_label,
                   f.throttle, f.brake, f"{f.boost_bar:.3f}", f"{f.fuel_level:.2f}",
                   *(f"{v:.3f}" for v in f.position),
                   *(f"{v:.2f}" for v in f.tyre_temp),
                   *(f"{v:.4f}" for v in f.tyre_slip)]
            print(",".join(str(c) for c in row), file=out)

        with GT7Client(args.host, args.format, on_frame=emit):
            deadline = time.monotonic() + args.seconds if args.seconds else None
            while deadline is None or time.monotonic() < deadline:
                time.sleep(0.2)
                out.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if args.output:
            out.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gt7", description="GT7 live telemetry")
    ap.add_argument("--host", default=DEFAULT_HOST, help="PS5 IP address")
    ap.add_argument("--format", default="A", choices=[f.name for f in FORMATS],
                    help="wire format to request (A=296B, B=316B +motion, ~=uncracked)")
    sub = ap.add_subparsers(dest="cmd")

    w = sub.add_parser("serve", help="web dashboard (default)")
    w.add_argument("--bind", default="0.0.0.0", help="address to serve on")
    w.add_argument("--port", type=int, default=6767)
    w.add_argument("--tracks", help="saved circuit library "
                                    "(default: ~/.local/share/gt7/tracks.json)")
    w.set_defaults(func=cmd_serve)

    d = sub.add_parser("dash", help="terminal dashboard")
    d.set_defaults(func=cmd_dash)

    p = sub.add_parser("probe", help="ask the console for each format and report")
    p.add_argument("--duration", type=float, default=2.5)
    p.add_argument("--cooldown", type=float, default=30.0,
                   help="seconds to let an open session lapse before each trial; "
                        "no value is reliable (see docs/protocol.md)")
    p.set_defaults(func=cmd_probe)

    du = sub.add_parser("dump", help="annotated hex + parsed fields for one packet")
    du.add_argument("--timeout", type=float, default=12.0)
    du.set_defaults(func=cmd_dump)

    r = sub.add_parser("record", help="capture raw datagrams to a file")
    r.add_argument("output")
    r.add_argument("--seconds", type=float, default=10.0)
    r.set_defaults(func=cmd_record)

    s = sub.add_parser("survey", help="classify every byte slot in a capture")
    s.add_argument("capture")
    s.add_argument("--unknown-only", action="store_true",
                   help="show only offsets with no mapped field")
    s.set_defaults(func=cmd_survey)

    df = sub.add_parser("diff", help="compare two captures for condition-dependent fields")
    df.add_argument("before")
    df.add_argument("after")
    df.add_argument("--activated-only", action="store_true",
                    help="show only always-zero -> live slots (weather hunting)")
    df.set_defaults(func=cmd_diff)

    c = sub.add_parser("csv", help="stream telemetry to CSV")
    c.add_argument("-o", "--output")
    c.add_argument("--seconds", type=float, default=0.0, help="0 = until Ctrl-C")
    c.set_defaults(func=cmd_csv)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        # Bare `gt7` opens the web dashboard; `gt7 dash` still gives the TUI.
        args.bind, args.port, args.tracks = "0.0.0.0", 6767, None
        args.func = cmd_serve
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except PortBusyError as exc:
        # One machine, one telemetry client. Say so plainly rather than
        # dumping a traceback about a socket.
        _p(f"[!] {exc.args[1] if len(exc.args) > 1 else exc}")
        busy = _other_listeners()
        if busy:
            _p(f"    holding it: {busy}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
