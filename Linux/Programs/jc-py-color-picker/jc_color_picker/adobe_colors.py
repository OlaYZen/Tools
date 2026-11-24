"""Faithful Python port of ``jc_colorpicker/AdobeColors.cs``.

This is the canonical color model used by the Joy-Con Color Picker.  Despite the
``HSL`` name (kept from the original Adobe Color Picker Clone by Danny Blanchard),
the algorithm is really Adobe Photoshop's *HSB/HSV* model:

    L (a.k.a. "brightness") = max(R, G, B) / 255
    S (saturation)         = (max - min) / max
    H (hue)                = standard 6-sector hue, normalised to 0..1

The conversions below are a line-for-line translation of the C# source so that
the Python backend and the JavaScript front-end (``web/app.js``) produce byte
-identical colors.  In particular the custom ``round`` (round-half-up via integer
truncation) is reproduced exactly — Python's built-in ``round`` uses banker's
rounding and would give different results.

All H/S/L values are floats in ``[0, 1]``.  RGB values are ints in ``[0, 255]``.
"""

from __future__ import annotations

from dataclasses import dataclass


def _round(val: float) -> int:
    """Port of the original ``Round(double)`` helper.

    ``ret = (int)val; if ((int)(val*100) % 100) >= 50: ret += 1``

    Truncates toward zero (like a C cast) and rounds half *up*.  Only meaningful
    for the non-negative values used throughout the picker.
    """
    ret_val = int(val)              # C-style truncation toward zero
    temp = int(val * 100)
    if (temp % 100) >= 50:
        ret_val += 1
    return ret_val


def _clamp01(value: float) -> float:
    if value > 1:
        return 1.0
    if value < 0:
        return 0.0
    return value


@dataclass
class HSL:
    """Mutable H/S/L triple, each component clamped to ``[0, 1]``.

    Mirrors ``AdobeColors.HSL``.  Attribute access goes through ``__setattr__``
    so assignments are clamped exactly like the C# property setters.
    """

    H: float = 0.0
    S: float = 0.0
    L: float = 0.0

    def __setattr__(self, name: str, value: float) -> None:
        if name in ("H", "S", "L"):
            value = _clamp01(float(value))
        object.__setattr__(self, name, value)

    def copy(self) -> "HSL":
        return HSL(self.H, self.S, self.L)


def hsl_to_rgb(hsl: HSL) -> tuple[int, int, int]:
    """Port of ``AdobeColors.HSL_to_RGB``.  Returns an ``(r, g, b)`` tuple."""
    max_ = _round(hsl.L * 255)
    min_ = _round((1.0 - hsl.S) * (hsl.L / 1.0) * 255)
    q = (max_ - min_) / 255

    h = hsl.H
    if 0 <= h <= 1 / 6:
        mid = _round(((h - 0) * q) * 1530 + min_)
        return (max_, mid, min_)
    if h <= 1 / 3:
        mid = _round(-((h - 1 / 6) * q) * 1530 + max_)
        return (mid, max_, min_)
    if h <= 0.5:
        mid = _round(((h - 1 / 3) * q) * 1530 + min_)
        return (min_, max_, mid)
    if h <= 2 / 3:
        mid = _round(-((h - 0.5) * q) * 1530 + max_)
        return (min_, mid, max_)
    if h <= 5 / 6:
        mid = _round(((h - 2 / 3) * q) * 1530 + min_)
        return (mid, min_, max_)
    if h <= 1.0:
        mid = _round(-((h - 5 / 6) * q) * 1530 + max_)
        return (max_, min_, mid)
    return (0, 0, 0)


def rgb_to_hsl(r: int, g: int, b: int) -> HSL:
    """Port of ``AdobeColors.RGB_to_HSL``.  Accepts ``(r, g, b)`` ints 0..255."""
    hsl = HSL()

    if r > g:
        max_, min_ = r, g
    else:
        max_, min_ = g, r
    if b > max_:
        max_ = b
    elif b < min_:
        min_ = b

    diff = max_ - min_

    # Luminance / brightness.
    hsl.L = max_ / 255

    # Saturation.
    if max_ == 0:
        hsl.S = 0
    else:
        hsl.S = diff / max_

    # Hue.  R at 0/360 deg, G at 120 deg, B at 240 deg.
    if diff == 0:
        q = 0
    else:
        q = 60 / diff

    if max_ == r:
        if g < b:
            hsl.H = (360 + q * (g - b)) / 360
        else:
            hsl.H = (q * (g - b)) / 360
    elif max_ == g:
        hsl.H = (120 + q * (b - r)) / 360
    elif max_ == b:
        hsl.H = (240 + q * (r - g)) / 360
    else:
        hsl.H = 0.0

    return hsl


# ---------------------------------------------------------------------------
# Convenience helpers used by the rest of the package (not in the C# original).
# ---------------------------------------------------------------------------

def rgb_to_hex(r: int, g: int, b: int) -> str:
    """``(255, 60, 40) -> 'FF3C28'`` (upper-case, no leading '#')."""
    return f"{r & 0xFF:02X}{g & 0xFF:02X}{b & 0xFF:02X}"


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    """Parse ``'#FF3C28'`` / ``'ff3c28'`` -> ``(255, 60, 40)``."""
    value = value.strip().lstrip("#")
    if len(value) == 3:  # short form, e.g. 'abc' -> 'aabbcc'
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise ValueError(f"invalid hex color: {value!r}")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
