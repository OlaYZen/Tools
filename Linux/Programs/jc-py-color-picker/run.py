#!/usr/bin/env python3
"""Convenience launcher — equivalent to ``python -m jc_color_picker``.

Lets you run the app straight from a checkout without installing it:

    ./run.py            # auto-detect a controller (else mock), open the browser
    ./run.py --mock     # force the in-memory mock device
    ./run.py --help     # all options
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jc_color_picker.server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
