"""Joy-Con Color Picker — a pure-Python Linux port of CTCaer's Joy-Con Toolkit
color picker.

The original is a Windows (C++/CLI + C#/WinForms) application.  This package
re-implements the color picker as a dependency-free Python project whose display
is plain HTML served over a local web server, and which can read/write the body,
button and grip colors of a real Joy-Con / Pro Controller on Linux through
``/dev/hidraw*``.

Sub-modules
-----------
``adobe_colors``  Faithful port of ``AdobeColors.cs`` (the HSB/HSL color math).
``presets``       Retail/grip preset data and user-preset persistence (colors.xml).
``joycon``        Pure-Python Joy-Con SPI-flash backend (+ a mock device).
``server``        Stdlib HTTP server: serves the web UI and a small JSON API.
"""

__version__ = "1.0.0"
__all__ = ["adobe_colors", "presets", "joycon", "server"]
