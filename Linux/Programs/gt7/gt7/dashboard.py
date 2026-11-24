"""Live terminal dashboard for GT7 telemetry."""

from __future__ import annotations

import time

from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .client import GT7Client
from .derived import GripEstimator
from .packet import Flags, Telemetry, format_lap_time, format_time_of_day

REFRESH_HZ = 20

# Colour ramp for tyre temperature (deg C).  GT7's sweet spot sits ~80-100.
_TYRE_BANDS = ((60, "blue"), (80, "cyan"), (100, "green"), (110, "yellow"), (999, "red"))


def _tyre_colour(temp: float) -> str:
    for limit, colour in _TYRE_BANDS:
        if temp < limit:
            return colour
    return "red"


def _bar(fraction: float, width: int, colour: str, *, track: str = "grey23") -> Text:
    """A solid horizontal meter."""
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * width)
    return Text("█" * filled, style=colour) + Text("─" * (width - filled), style=track)


def _rpm_bar(t: Telemetry, width: int) -> Text:
    """RPM meter with the car's own warning and limiter zones marked."""
    limiter = float(t.rpm_limiter) if t.rpm_limiter > 0 else max(t.rpm, 1.0)
    warn = float(t.rpm_warning) if t.rpm_warning > 0 else limiter * 0.9
    filled = round(min(t.rpm / limiter, 1.0) * width)
    warn_cell = round(min(warn / limiter, 1.0) * width)

    blink = bool(t.flags & Flags.REV_LIMITER)
    out = Text()
    for i in range(width):
        if i < filled:
            colour = "bold red" if blink else ("red" if i >= warn_cell else "green")
            out.append("█", style=colour)
        else:
            out.append("─", style="yellow" if i == warn_cell else "grey23")
    return out


def _kv(rows: list[tuple[str, RenderableType]], *, key_style: str = "grey62") -> Table:
    table = Table.grid(padding=(0, 1), expand=True)
    # Pin the label column to its longest entry; with expand=True rich would
    # otherwise starve it and truncate labels to "ride heig...".
    width = max((len(k) for k, _ in rows), default=0)
    table.add_column(style=key_style, no_wrap=True, width=width)
    table.add_column(justify="right", no_wrap=True)
    for key, value in rows:
        table.add_row(key, value)
    return table


def _header(client: GT7Client, t: Telemetry | None) -> Panel:
    if client.connected and t is not None:
        status = Text("● LIVE", style="bold green")
    else:
        status = Text("● WAITING", style="bold yellow")

    if client.format_mismatch and client.active_format is not None:
        # The console pins the format per session and renews it on every
        # heartbeat, so asking for another one mid-session changes nothing.
        fmt = Text.assemble(
            (client.active_format.name, "bold yellow"),
            (f" (asked {client.format.name}; session already open)", "yellow"),
        )
    else:
        fmt = Text(client.format.name, style="magenta")
    left = Text.assemble(status, "  ", (f"{client.host}", "cyan"), ("  fmt ", "grey62"), fmt)
    right = Text.assemble(
        (f"{client.packet_rate:5.1f}", "bold white"), (" pkt/s", "grey62"),
        ("   drop ", "grey62"), (str(client.dropped), "red" if client.dropped else "grey62"),
        ("   err ", "grey62"), (str(client.decode_errors), "red" if client.decode_errors else "grey62"),
    )
    if t is not None:
        right = Text.assemble(right, ("   car ", "grey62"), (str(t.car_code), "white"))

    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="right")
    grid.add_row(left, right)
    return Panel(grid, style="grey35", padding=(0, 1))


def _speed_panel(t: Telemetry) -> Panel:
    gear = Text(t.gear_label, style="bold white on grey19")
    suggested = t.suggested_gear_label
    shift = Text(f" ⟶ {suggested}", style="bold yellow") if suggested else Text("")

    body = Group(
        Align.center(Text.assemble(
            (f"{t.speed_kph:6.1f}", "bold white"), (" km/h", "grey62"),
        )),
        Align.center(Text.assemble((f"{t.speed_mph:5.1f} mph", "grey50"))),
        Text(""),
        Align.center(Text.assemble(("GEAR  ", "grey62"), gear, shift)),
        Text(""),
        Align.center(Text.assemble((f"{t.rpm:5.0f}", "bold white"), (" rpm", "grey62"))),
        _rpm_bar(t, 34),
        Align.center(Text(
            f"warn {t.rpm_warning} · lim {t.rpm_limiter} · max {t.top_speed_kph}",
            style="grey42",
        )),
    )
    return Panel(body, title="[bold]drive", border_style="grey35", padding=(0, 1))


def _inputs_panel(t: Telemetry) -> Panel:
    rows: list[tuple[str, RenderableType]] = [
        ("throttle", Text.assemble(_bar(t.throttle / 255, 22, "green"), f" {t.throttle_pct:3.0f}%")),
        ("brake", Text.assemble(_bar(t.brake / 255, 22, "red"), f" {t.brake_pct:3.0f}%")),
        ("clutch", Text.assemble(_bar(t.clutch, 22, "cyan"), f" {t.clutch * 100:3.0f}%")),
    ]
    if t.has_extended and t.wheel_rotation is not None:
        # Centre-origin meter: left lock .. centre .. right lock (+-1 rad shown).
        steer = max(-1.0, min(1.0, t.wheel_rotation))
        width = 22
        centre = width // 2
        cell = centre + round(steer * centre)
        bar = Text()
        for i in range(width):
            if i == cell:
                bar.append("█", style="bold magenta")
            elif i == centre:
                bar.append("│", style="grey42")
            else:
                bar.append("─", style="grey23")
        rows.append(("steering", Text.assemble(bar, f" {t.wheel_rotation:+5.2f}r")))

    aids = Text()
    for label, flag, colour in (
        ("TCS", Flags.TCS, "yellow"), ("ASM", Flags.ASM, "yellow"),
        ("HBK", Flags.HANDBRAKE, "red"), ("LIGHT", Flags.LIGHTS, "cyan"),
        ("HIGH", Flags.HIGH_BEAM, "cyan"), ("TURBO", Flags.HAS_TURBO, "magenta"),
    ):
        on = bool(t.flags & flag)
        aids.append(f" {label} ", style=f"bold black on {colour}" if on else "grey30")
    return Panel(Group(_kv(rows), Text(""), Align.center(aids)),
                 title="[bold]inputs", border_style="grey35", padding=(0, 1))


def _lap_panel(t: Telemetry) -> Panel:
    laps = f"{t.current_lap}" + (f" / {t.total_laps}" if t.total_laps else "")
    best = format_lap_time(t.best_lap_ms)
    last = format_lap_time(t.last_lap_ms)
    delta = Text("--", style="grey42")
    if t.best_lap_ms > 0 and t.last_lap_ms > 0:
        diff = (t.last_lap_ms - t.best_lap_ms) / 1000.0
        delta = Text(f"{diff:+.3f}s", style="green" if diff <= 0 else "red")

    rows: list[tuple[str, RenderableType]] = [
        ("lap", Text(laps, style="bold white")),
        ("best", Text(best, style="bold magenta")),
        ("last", Text(last, style="white")),
        ("delta", delta),
        ("position", Text(f"{t.grid_position} / {t.cars_in_race}"
                          if t.cars_in_race > 0 else "-", style="white")),
        ("time of day", Text(format_time_of_day(t.time_of_day_ms), style="grey62")),
    ]
    state = []
    if t.paused:
        state.append(Text(" PAUSED ", style="bold black on yellow"))
    if t.flags & Flags.LOADING:
        state.append(Text(" LOADING ", style="bold black on cyan"))
    body: list[RenderableType] = [_kv(rows)]
    if state:
        line = Text()
        for chunk in state:
            line.append_text(chunk)
            line.append(" ")
        body += [Text(""), Align.center(line)]
    return Panel(Group(*body), title="[bold]session", border_style="grey35",
                 padding=(0, 1))


def _engine_panel(t: Telemetry) -> Panel:
    fuel_colour = "green" if t.fuel_pct > 30 else "yellow" if t.fuel_pct > 12 else "bold red"
    rows: list[tuple[str, RenderableType]] = []
    if t.is_ev:
        rows.append(("fuel", Text("n/a (electric)", style="grey42")))
    else:
        rows.append(("fuel", Text.assemble(
            _bar(t.fuel_pct / 100, 16, fuel_colour),
            f" {t.fuel_level:5.1f}/{t.fuel_capacity:.0f} L",
        )))
    if t.flags & Flags.HAS_TURBO:
        # Boost is reported as absolute pressure; 1.0 == atmospheric.
        span = max(abs(t.boost_bar), 1.0)
        rows.append(("boost", Text.assemble(
            _bar(abs(t.boost_bar) / span, 16, "magenta" if t.boost_bar > 0 else "blue"),
            f" {t.boost_bar:+5.2f} bar",
        )))
    rows += [
        ("oil press", Text(f"{t.oil_pressure:.2f}", style="white")),
        ("oil temp", Text(f"{t.oil_temp:.0f} °C", style="grey62")),
        ("water temp", Text(f"{t.water_temp:.0f} °C", style="grey62")),
        ("clutch rpm", Text(f"{t.rpm_after_clutch:.0f}", style="white")),
    ]
    return Panel(_kv(rows), title="[bold]engine", border_style="grey35", padding=(0, 1))


def _tyre_panel(t: Telemetry) -> Panel:
    temps = t.corner("tyre_temp")
    slips = dict(zip(("FL", "FR", "RL", "RR"), t.tyre_slip))
    susp = t.corner("suspension")

    def cell(corner: str) -> Text:
        temp = temps[corner]
        slip = slips[corner]
        # >1 spinning up, <1 locking; 3% either way is the usual noise floor.
        if slip > 1.03:
            slip_style = "bold red"
        elif slip < 0.97:
            slip_style = "bold yellow"
        else:
            slip_style = "grey62"
        return Text.assemble(
            (f"{corner}  ", "grey50"),
            (f"{temp:5.1f}°", _tyre_colour(temp)), "\n",
            ("slip ", "grey42"), (f"{slip:5.3f}", slip_style), "\n",
            ("susp ", "grey42"), (f"{susp[corner]:+5.3f}", "grey62"),
        )

    grid = Table.grid(padding=(0, 3), expand=True)
    grid.add_column(justify="center")
    grid.add_column(justify="center")
    grid.add_row(cell("FL"), cell("FR"))
    grid.add_row(Text(""), Text(""))
    grid.add_row(cell("RL"), cell("RR"))
    return Panel(grid, title="[bold]tyres", border_style="grey35", padding=(0, 1))


def _chassis_panel(t: Telemetry) -> Panel:
    x, y, z = t.position
    vx, vy, vz = t.velocity
    ax, ay, az = t.angular_velocity
    rows: list[tuple[str, RenderableType]] = [
        ("position", Text(f"{x:8.1f} {y:7.1f} {z:8.1f}", style="grey62")),
        ("velocity", Text(f"{vx:8.2f} {vy:7.2f} {vz:8.2f}", style="grey62")),
        ("ang vel", Text(f"{ax:+7.3f} {ay:+7.3f} {az:+7.3f}", style="grey62")),
        ("ride height", Text(f"{t.ride_height * 1000:.0f} mm", style="white")),
        ("heading", Text(f"{t.rotation[3]:+.3f}", style="white")),
        ("road dist", Text(f"{t.road_plane_distance:+.3f}", style="grey62")),
    ]
    body: list[RenderableType] = [_kv(rows)]
    ratios = t.active_gear_ratios
    if ratios:
        # Own line, no indent: an 8-speed box needs the full panel width.
        gearing = Text(no_wrap=False, overflow="fold")
        for i, ratio in enumerate(ratios, start=1):
            live = i == t.gear
            gearing.append(f"{ratio:.2f}", style="bold white" if live else "grey42")
            if i != len(ratios):
                gearing.append(" ", style="grey42")
        body += [
            Text(""),
            Text(f"gearing · final drive {t.transmission_top_speed:.3f}", style="grey62"),
            gearing,
        ]
    return Panel(Group(*body), title="[bold]chassis", border_style="grey35",
                 padding=(0, 1))


def _environment_panel(t: Telemetry, grip: GripEstimator) -> Panel:
    """Environment and inferred grip.

    GT7 sends no weather channel at all - no rain, no wetness, no radar (see
    docs/weather.md). Time of day is the only real environmental datum in the
    packet. Grip below it is *inferred* from motion, not received, and is
    labelled that way so it is never mistaken for telemetry.
    """
    hours = (max(t.time_of_day_ms, 0) // 3_600_000) % 24
    if 6 <= hours < 18:
        daylight = Text("day", style="yellow")
    elif hours in (5, 18, 19):
        daylight = Text("twilight", style="magenta")
    else:
        daylight = Text("night", style="blue")

    rows: list[tuple[str, RenderableType]] = [
        ("clock", Text(format_time_of_day(t.time_of_day_ms), style="white")),
        ("daylight", daylight),
    ]

    peak, relative = grip.recent_peak_g, grip.relative
    if peak is None:
        rows.append(("grip", Text(f"— ({grip.confidence})", style="grey42")))
    else:
        rows.append(("peak grip", Text(f"{peak:.2f} g", style="white")))
        if relative is None:
            rows.append(("vs best", Text(f"— ({grip.confidence})", style="grey42")))
        else:
            # Sustained low relative grip is what a wet track looks like -
            # but so does a driver going easy, so never assert weather here.
            colour = "green" if relative > 0.9 else "yellow" if relative > 0.75 else "red"
            rows.append(("vs best", Text.assemble(
                _bar(relative, 12, colour), f" {relative * 100:3.0f}%")))

    live = [(i, v) for i, v in enumerate(t.reserved) if v != 0.0]
    if live:
        rows.append(("reserved", Text(f"NON-ZERO @{live[0][0]}!", style="bold red")))
    else:
        rows.append(("reserved", Text("all zero", style="grey42")))

    note = Text("grip is inferred, not sent · GT7 has no weather channel",
                style="grey42", no_wrap=False, overflow="fold")
    return Panel(Group(_kv(rows), Text(""), note),
                 title="[bold]environment", border_style="grey35", padding=(0, 1))


def _waiting(client: GT7Client) -> Panel:
    return Panel(
        Align.center(Group(
            Text(""),
            Text("waiting for telemetry", style="bold yellow"),
            Text(""),
            Text(f"heartbeat '{client.format.heartbeat.decode()}' -> "
                 f"{client.host}:33739", style="grey62"),
            Text("listening on 0.0.0.0:33740", style="grey62"),
            Text(""),
            Text("GT7 must be running and past the main menu.", style="grey42"),
            Text("If you just switched format, the console keeps the old", style="grey42"),
            Text("stream for ~10s before honouring the new heartbeat.", style="grey42"),
            Text(""),
        )),
        border_style="yellow",
    )


def build(client: GT7Client, grip: GripEstimator | None = None) -> RenderableType:
    t = client.latest
    layout = Layout()
    layout.split_column(
        Layout(_header(client, t), name="header", size=3),
        Layout(name="body"),
    )
    if t is None:
        layout["body"].update(_waiting(client))
        return layout

    layout["body"].split_row(Layout(name="left"), Layout(name="mid"), Layout(name="right"))
    layout["body"]["left"].split_column(
        Layout(_speed_panel(t), size=12),
        Layout(_inputs_panel(t)),
    )
    layout["body"]["mid"].split_column(
        Layout(_tyre_panel(t), size=12),
        Layout(_engine_panel(t)),
    )
    right = [Layout(_lap_panel(t), size=10), Layout(_chassis_panel(t), size=13)]
    if grip is not None:
        right.append(Layout(_environment_panel(t, grip)))
    layout["body"]["right"].split_column(*right)
    return layout


def run(host: str, fmt: str = "A") -> None:
    """Open a live dashboard until Ctrl-C."""
    console = Console()
    grip = GripEstimator()
    # Feed the estimator at packet rate (60 Hz), not at redraw rate (20 Hz),
    # or two thirds of the braking peaks never reach it.
    client = GT7Client(host, fmt, on_frame=lambda f: grip.feed(f, time.monotonic()))
    with client, Live(build(client, grip), console=console, screen=True,
                      refresh_per_second=REFRESH_HZ, transient=False) as live:
        try:
            while True:
                live.update(build(client, grip))
                time.sleep(1.0 / REFRESH_HZ)
        except KeyboardInterrupt:
            pass
    console.print(
        f"[grey62]{client.packets} packets, {client.dropped} dropped, "
        f"{client.decode_errors} decode errors[/]"
    )
