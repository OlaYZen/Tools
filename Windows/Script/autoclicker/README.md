# autoclicker (Windows)

Left-clicks on a randomized, human-ish schedule, but only while a chosen
window is in the foreground. Press F9 to arm. Alt-tab away and it pauses; tab
back and it resumes. Ctrl+C — or closing the console — always releases the
button before exiting.

Clicks are sent with `SendInput`. The toggle key comes from a system-wide
low-level keyboard hook and is still passed through to whatever has focus.

Linux counterpart: `Linux/Scripts/Universal/autoclicker/autoclicker.py`

## Requirements

- Windows 10 or 11
- Python 3 — no third-party packages, pure `ctypes`
- Run the console **as administrator** if the target game runs elevated.
  Windows blocks both the keyboard hook and injected input from reaching a
  higher-integrity process.

## Usage

```bat
python autoclicker.py                     :: click in Lunar Client, toggle with F9
python autoclicker.py -k f7               :: toggle with F7
python autoclicker.py -t "(?i)javaw"      :: gate on a different window
python autoclicker.py -r 0                :: click in place, no cursor movement
python autoclicker.py --any-window        :: no focus gating at all
```

| Option | Default | Meaning |
| --- | --- | --- |
| `-k`, `--toggle` | `f9` | key that arms/disarms clicking |
| `-t`, `--target` | `(?i)^Lunar Client \d` | regex matched against the foreground window **title or exe name** |
| `--any-window` | off | disable focus gating; click into whatever is focused |
| `-r`, `--radius` | `12` | radius in px of the circle the cursor wanders in (`0` disables movement) |

Valid `--toggle` keys — a different set from the Linux build, and from
`key-holder`'s:
`f1`–`f12`, `q e r f tab insert delete home end pause scrolllock`

Because the regex is tried against both the window title and the executable
name, `"(?i)javaw"` and `"(?i)^Lunar Client"` are both valid ways to target
the same game.

## Timing

| | |
| --- | --- |
| Gap between clicks | 3–7 s |
| Burst chance | 1 in 20 clicks |
| Burst length | 3–5 clicks, 0.15–0.25 s apart |
| Button hold | 40–90 ms |
| Hard cap | 7 CPS, never exceeded |

Just before each click the cursor glides to a new random point inside the
drift circle, so clicks don't all land on one dead-still pixel. Motion is sent
as many small relative steps on a smoothstep curve at ~165 Hz — 3D games read
relative deltas from a captured pointer, and a single large jump reads as a
teleport. Mid-burst the cursor only nudges (3 px) instead of taking a full
stroll. Position is tracked as an internal offset rather than via
`GetCursorPos`, so the wander stays bounded even when the game has the pointer
captured and the reported cursor sits still.

Tune the constants at the top of the script if you want a different rhythm.

## Status line

```
CLICKING  |  clicks: 42  bursts: 3        armed, target focused
WAITING (not focused)  |  ...             armed, but something else has focus
OFF  |  ...                               disarmed
```

Arming, disarming, or losing focus resets the schedule, so no backlog of
clicks fires the moment the window comes back.

## Notes

- Injected events are stamped with a marker so the hook ignores the script's
  own output and can't toggle itself.
- Automating input can break server rules or trip anti-cheat. Your call.
