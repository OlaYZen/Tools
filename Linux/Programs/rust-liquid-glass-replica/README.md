# liquid-glass

A transparent, floating pane of iOS 26-style **liquid glass** for Hyprland, in Rust.

It isn't frosted glass. The pane is a thick convex lens: the middle shows what is behind it
sharp, and the bevel along the edge refracts it, so the windows behind are bent and squeezed
around the rounded corners, with chromatic fringing on the rim and Fresnel light on the edge.

The look is a GLSL port of [ybouane/liquidglass](https://github.com/ybouane/liquidglass)
(`FS_GLASS`), with the same parameters and defaults.

## Run

```sh
cargo run --release
cargo run --release -- --preset ios            # rim highlights + a little vibrancy
cargo run --release -- --bevel dome --radius 999 --width 240 --height 240   # magnifier
cargo run --release -- --help                  # every parameter
```

- Drag the glass to move it, drag its shadow (the 20 px around it) to resize, `Esc`/`q` quits.
- **Right-click the glass** (or run `liquid-glass --settings`) for the settings window: every
  parameter as a slider, applied live as you drag it, presets, the panel size, and
  **Save as default**, which writes `~/.config/liquid-glass/settings.json`. Every new glass starts
  from that; command-line flags still override it.
- `--button` adds upstream's button feel: hover brightens, a press flattens the bevel.

## How it works

**Hyprland draws the glass.** The app sets Hyprland's `decoration:screen_shader` to the
generated glass shader (`shader.rs`). Hyprland runs it over every frame it composites, so the
shader samples the very frame it is drawing on:

- **Zero lag:** what the glass bends is the current frame, never a capture of an earlier one.
  A clock under the glass reads the same, to the millisecond, inside and outside it.
- **Near-zero GPU:** no captures, no copies, no rendering in this process at all. Pixels
  outside the glass cost two texel reads; the glass runs only when Hyprland draws a frame
  anyway, and an idle desktop draws none.
- **Exact:** bars, shadows, Hyprland's own blur, animations and video behind the glass are
  all simply there.

**The marker** (`marker.rs`). A screen shader takes no inputs, so the app tells it where the glass
is through a 92 × 4 px strip of coloured blocks in an overlay layer at the monitor's top-left
corner. The blocks hold the glass's rectangle, its press and hover state, and up to four windows
stacked above it, with a magic header and a checksum. The shader decodes them, paints the strip
over with what is beneath it, and draws nothing if the strip is missing or damaged.

**The window** (`wl.rs`). The glass's floating window is fully transparent and only takes input.
Dragging is cursor-locked: the app follows the pointer itself (every press grabs the pointer)
and updates the marker once per compositor frame. The real window is moved to the drop point
on release. Moves Hyprland makes itself (super+drag, keybinds) are followed by polling every
2 ms while they happen.

**Whole frames while the glass is on screen.** Hyprland runs the screen shader only over the
pixels damaged that frame and keeps the rest of each swapchain buffer from earlier frames. The
glass isn't local (each pixel bends in content from up to ~100 px away), so with a video playing
near it, glass pixels just outside the video's damage would go stale, at a different age in each
buffer the monitor flips between: flicker. So while the glass is visible the app sets
`debug:damage_tracking` to `1` (whole-monitor frames). Hyprland still draws nothing when nothing
changes; it costs ~4–5 % GPU while a video plays, and none when the glass is hidden.

**Live settings** (`gui.rs`, `control.rs`). The settings window is the same binary with egui. It
talks to the running glass over JSON lines on `$XDG_RUNTIME_DIR/liquid-glass/control.sock`. A new
look is a new shader for Hyprland to compile, so while a slider moves the glass applies the latest
look at most every 40 ms. The window closes itself when the glass quits.

**Your settings are borrowed, not lost.** The previous `screen_shader` and `damage_tracking` are
saved in `$XDG_RUNTIME_DIR/liquid-glass/` and put back on exit, on SIGINT/SIGTERM/SIGHUP, and
after a crash (on the next run). Only one instance runs at a time.

### Measured (RX 9070 XT, 2560×1440 @ 360 Hz, Hyprland 0.56)

| | |
|---|---|
| Lag behind the window it shows | 0 frames (same frame) |
| GPU, still desktop | +0 % |
| GPU, something animating behind at 360 Hz | +2 % (Hyprland's final pass through a shader) |
| GPU, video playing on the glass's monitor | +4–5 % (whole-monitor frames, see above) |
| App CPU | ~0.3 % of a core |

`--print-shader` prints the generated GLSL; `LIQUID_GLASS_DEBUG=1` logs every marker sent.

## The window rule

On start it installs these rules with `hyprctl eval` (they last until Hyprland reloads its config,
and are put back after a reload). To make them permanent, add them to your config and pass
`--no-rule`:

```lua
hl.window_rule({
    name  = "liquid-glass",
    match = { class = "^(liquid-glass)$" },

    float       = true,
    center      = true,
    no_blur     = true,   -- Hyprland's blur behind it would frost the glass
    no_shadow   = true,   -- the glass draws its own
    no_dim      = true,
    border_size = 0,
    rounding    = 0,
    decorate    = false,
    no_anim     = true,
})

hl.layer_rule({
    name    = "liquid-glass-marker",
    match   = { namespace = "^(liquid-glass-marker)$" },
    no_anim = true,           -- a fade would garble the marker for a moment
})
```

## Limits

- Hyprland only (Lua config, 0.55+; tested on 0.56.2), and it takes over
  `decoration:screen_shader` (and, while visible, `debug:damage_tracking`, which is global: your
  other monitors also redraw whole frames meanwhile) while it runs: another screen shader (e.g. HyprToys' Zoom) and the
  glass can't run at the same time.
- With a screen shader set, Hyprland can't scan a fullscreen game out directly. The glass hides
  itself over fullscreen windows, but the shader stays set while the app runs.
- Windows above the glass are cut out as rectangles (their rounded corners aren't followed), up
  to four at a time.
- Something covering the top-left corner where the marker lives (a notification there) hides
  the glass until it goes.
- `--blur` costs 12 extra samples per glass pixel; the default (0) is clear glass, as liquid
  glass is.
