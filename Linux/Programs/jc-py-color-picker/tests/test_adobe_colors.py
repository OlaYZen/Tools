"""Lock the ported Adobe color math against known Joy-Con retail colors.

Run with:  python -m pytest tests/   (or)   python tests/test_adobe_colors.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jc_color_picker.adobe_colors import (  # noqa: E402
    HSL,
    _round,
    hex_to_rgb,
    hsl_to_rgb,
    rgb_to_hex,
    rgb_to_hsl,
)

# The eight retail body colors shipped in retail_colors.xml.
RETAIL = {
    "Grey": (0x82, 0x82, 0x82),
    "Neon Blue": (0x0A, 0xB9, 0xE6),
    "Neon Red": (0xFF, 0x3C, 0x28),
    "Neon Yellow": (0xE6, 0xFF, 0x00),
    "Neon Pink": (0xFF, 0x32, 0x78),
    "Neon Green": (0x1E, 0xDC, 0x00),
    "Red": (0xE1, 0x0F, 0x00),
    "Pro Black": (0x32, 0x32, 0x32),
}


def test_round_half_up():
    assert _round(0.0) == 0
    assert _round(0.49) == 0
    assert _round(0.5) == 1
    assert _round(2.5) == 3       # banker's rounding would give 2
    assert _round(254.5) == 255
    assert _round(99.999) == 100


def test_hex_helpers():
    assert rgb_to_hex(255, 60, 40) == "FF3C28"
    assert hex_to_rgb("#FF3C28") == (255, 60, 40)
    assert hex_to_rgb("0ab9e6") == (10, 185, 230)
    assert hex_to_rgb("abc") == (0xAA, 0xBB, 0xCC)


def test_hsl_clamping():
    hsl = HSL()
    hsl.H = 2.0
    hsl.S = -1.0
    hsl.L = 0.5
    assert hsl.H == 1.0
    assert hsl.S == 0.0
    assert hsl.L == 0.5


def test_round_trip_is_stable():
    """rgb -> hsl -> rgb must be a fixed point for every retail color.

    The picker relies on this: selecting a preset and reading it back must not
    drift the color.
    """
    for name, rgb in RETAIL.items():
        hsl = rgb_to_hsl(*rgb)
        back = hsl_to_rgb(hsl)
        assert back == rgb, f"{name}: {rgb} -> {back}"


def test_pure_primaries():
    assert hsl_to_rgb(rgb_to_hsl(255, 0, 0)) == (255, 0, 0)
    assert hsl_to_rgb(rgb_to_hsl(0, 255, 0)) == (0, 255, 0)
    assert hsl_to_rgb(rgb_to_hsl(0, 0, 255)) == (0, 0, 255)
    assert hsl_to_rgb(rgb_to_hsl(0, 0, 0)) == (0, 0, 0)
    assert hsl_to_rgb(rgb_to_hsl(255, 255, 255)) == (255, 255, 255)


def test_known_hsl_values():
    # Pure red: H=0, S=1, L=1
    hsl = rgb_to_hsl(255, 0, 0)
    assert abs(hsl.H - 0.0) < 1e-9
    assert abs(hsl.S - 1.0) < 1e-9
    assert abs(hsl.L - 1.0) < 1e-9
    # Mid grey 0x82: S=0, L=130/255
    hsl = rgb_to_hsl(0x82, 0x82, 0x82)
    assert hsl.S == 0.0
    assert abs(hsl.L - 130 / 255) < 1e-9


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run()
