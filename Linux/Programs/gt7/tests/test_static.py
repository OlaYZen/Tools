"""Invariants of the served page.

These are cheap guards against the class of bug that has actually bitten:
markup, styling and script drifting apart, and layout rules that quietly push
part of the dashboard off screen.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).parent.parent / "gt7" / "web" / "static"


@pytest.fixture(scope="module")
def html() -> str:
    return (STATIC / "index.html").read_text()


@pytest.fixture(scope="module")
def css() -> str:
    return (STATIC / "dash.css").read_text()


@pytest.fixture(scope="module")
def js() -> str:
    return (STATIC / "dash.js").read_text()


def test_every_element_the_script_reads_exists(html, js):
    ids = set(re.findall(r'id="([^"]+)"', html))
    read = set(re.findall(r'\$\("([^"]+)"\)', js))
    assert not (read - ids), f"script reads elements the page lacks: {read - ids}"


def test_no_grid_row_uses_a_bare_1fr(css):
    """A bare `1fr` is minmax(auto, 1fr) and cannot shrink.

    That is how the `now` strip - and with it the throttle and brake meters -
    got pushed off the bottom of the page when a second map was added.
    """
    for rule in re.findall(r"grid-template-rows:\s*([^;]+);", css):
        if "none" in rule:
            continue
        for track in rule.split():
            assert track != "1fr", (
                f"bare 1fr in `grid-template-rows: {rule.strip()}` - "
                "use minmax(0, 1fr) so the row can shrink"
            )


def test_both_canvases_are_styled_by_class_not_id(html, css):
    """Styling the first canvas by id left the second with no resolved box."""
    canvases = re.findall(r'<canvas id="(\w+)"', html)
    assert len(canvases) >= 2
    for name in canvases:
        assert f"#{name} {{" not in css, f"#{name} is styled by id; use a class"
    assert ".canvas-box > canvas" in css


def test_every_canvas_sits_in_a_relative_box(html):
    """The canvas is absolutely positioned so it cannot grow its own parent."""
    for match in re.finditer(r'<canvas id="\w+"', html):
        before = html[: match.start()]
        assert before.rstrip().endswith('<div class="canvas-box">')


def test_the_now_strip_still_carries_the_pedal_meters(html):
    for name in ("bar-throttle", "bar-brake"):
        assert f'id="{name}"' in html
        assert 'class="segbar"' in html or f'class="segbar" id="{name}"' in html


def test_segment_bars_declare_how_many_cells_they_want(html, js):
    """buildBar reads data-segments; a missing one silently yields NaN cells."""
    for match in re.finditer(r'class="segbar"[^>]*', html):
        assert "data-segments=" in match.group(0), match.group(0)
    assert "Number(bar.dataset.segments)" in js


def test_the_paint_loop_cannot_end_itself(js):
    """requestAnimationFrame must be rescheduled even when painting throws."""
    body = js[js.index("function frame()"):]
    body = body[: body.index("\n}")]
    assert "finally" in body, "one bad frame would freeze the dashboard"
    assert "requestAnimationFrame(frame)" in body


def test_classes_the_script_applies_are_all_styled(css, js):
    applied = set()
    for pattern in (r'classList\.(?:add|remove|toggle)\("([^"]+)"\)',
                    r'className = "([^"]*)"'):
        for match in re.findall(pattern, js):
            applied.update(part for part in match.split() if part)
    styled = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))
    missing = {name for name in applied if name not in styled}
    assert not missing, f"script applies unstyled classes: {sorted(missing)}"
