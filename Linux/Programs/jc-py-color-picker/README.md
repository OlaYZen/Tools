# Joy-Con Color Picker (pure-Python Linux port)

A Linux port of the **color picker** from
[CTCaer's Joy-Con Toolkit](https://gbatemp.net/threads/tool-joy-con-toolkit-v1-0.478560/)
— the original is a Windows app written in C++/CLI + C# WinForms. This rewrite is
**pure Python with zero third-party dependencies**; the display is plain **HTML**
served from a small local web server, and it can read/write the body, button and
grip colors of a real **Joy-Con / Pro Controller** directly through Linux
`/dev/hidraw*`.

![Joy-Con Color Picker](http://ctcaer.com/wii/jc6.png)
*(reference image of the original tool)*

## Highlights

- **Faithful Adobe-style picker** — the 260×260 color field + vertical slider with
  all six draw modes (Hue / Saturation / Brightness / Red / Green / Blue), ported
  pixel-mapping-for-pixel-mapping from the original `ctrl2DColorBox` /
  `ctrlVerticalColorSlider`.
- **Identical color math** — `AdobeColors.cs` is ported to `adobe_colors.py` and
  mirrored in `web/app.js`, so the on-screen preview matches what gets written to
  flash, byte for byte (locked by `tests/`).
- **Body / buttons / grips** — pick the two Joy-Con colors, or switch to *Grips*
  mode for the Pro Controller's left/right grip colors.
- **Presets** — the Nintendo retail colors + grip colors, plus two banks of your
  own savable swatches persisted to `colors.xml` (the *same* format the original
  tool used — the files are interchangeable).
- **Hex / RGB / HSB inputs** with mouse-wheel nudging, and a screen **eyedropper**
  (via the browser EyeDropper API).
- **Real hardware I/O** over `/dev/hidraw*` (SPI flash `0x6050`), or a built-in
  **mock device** so the whole UI works with no controller attached.

## Requirements

- Python **3.9+** (standard library only — nothing to `pip install`).
- For real hardware: a Joy-Con/Pro Controller paired over **Bluetooth**, and
  read/write access to its `/dev/hidraw*` node (see *Hardware access* below).

## Run

```bash
./run.py                 # auto-detect a controller (else mock) and open a browser
./run.py --mock          # force the in-memory mock device
./run.py --port 8753 --no-browser
python -m jc_color_picker # same thing, if you prefer the module form
```

Then use the page at <http://127.0.0.1:8753/>.

## Hardware access

Reading/writing a controller needs access to its hidraw device. The included
udev rule grants it to the logged-in user:

```bash
sudo cp 99-nintendo-controllers.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Reconnect the controller, then click the **⟳** button (or restart). If no
accessible device is found the app drops to the **mock** device and everything
except actual hardware writes keeps working.

> **Heads-up:** writing colors changes the controller's SPI flash. The hardware
> path was ported carefully from the original toolkit but could not be tested
> against a physical device in this environment. **Back up your SPI first** (the
> original toolkit, or any `joycontrol`/`hid` dumper, can do this) before writing.
> Bluetooth is the supported transport; a USB-connected Pro Controller needs a
> separate USB handshake that is out of scope here.

## How it maps to the original

| Original (Windows) | This port |
| --- | --- |
| `AdobeColors.cs` | `jc_color_picker/adobe_colors.py` (+ mirror in `web/app.js`) |
| `ctrl2DColorBox.cs`, `ctrlVerticalColorSlider.cs` | `<canvas>` rendering in `web/app.js` |
| `frmJoyConColorPicker.cs` (form logic, presets) | `web/*` + `jc_color_picker/presets.py` |
| `colors.xml` / `retail_colors.xml` | same files, `jc_color_picker/presets.py` |
| `get_spi_data` / `write_spi_data` (`jctool.cpp`) | `jc_color_picker/joycon.py` (hidraw) |
| WinForms window | local web server (`jc_color_picker/server.py`) + HTML |

## Project layout

```
jc-py-color-picker/
├── run.py                       # launcher
├── pyproject.toml               # packaging (no deps)
├── 99-nintendo-controllers.rules
├── jc_color_picker/
│   ├── adobe_colors.py          # color math (port of AdobeColors.cs)
│   ├── presets.py               # retail/grip presets + colors.xml persistence
│   ├── joycon.py                # pure-Python hidraw backend + mock device
│   ├── server.py                # stdlib HTTP server + JSON API
│   ├── retail_colors.xml        # bundled retail preset data
│   └── web/                     # the HTML display
│       ├── index.html
│       ├── style.css
│       └── app.js
└── tests/
    └── test_adobe_colors.py
```

## Tests

```bash
python tests/test_adobe_colors.py     # or: python -m pytest tests/
```

## License

The original Joy-Con Toolkit is GPL-2.0; this port keeps that license. The color
picker derives from Danny Blanchard's *Adobe Color Picker Clone* and CTCaer's
Joy-Con adaptation.
