# autoclicker (Linux)

Left-clicks on a randomized, human-ish schedule, but only while a chosen
window is focused. Press F9 to arm. Alt-tab away and it pauses; tab back and
it resumes. Ctrl+C always releases the button before exiting.

Clicks come from a virtual **uinput** mouse, so games that read the kernel
evdev stream see a real device. Focus is tracked live over Hyprland's IPC
event socket — no polling.

Windows counterpart: `Windows/Script/autoclicker/autoclicker.py`

## Requirements

- Python 3 — no third-party packages, pure `ctypes`
- Write access to `/dev/uinput` and read access to `/dev/input/event*`:
  ```sh
  sudo usermod -aG input $USER   # then log out and back in
  sudo modprobe uinput           # if /dev/uinput is missing
  ```
- **Hyprland** for focus gating. Under any other compositor, pass
  `--any-window` — the virtual mouse itself works anywhere.
- The sibling `../key-holder/key_holder.py`, which carries the shared uinput
  plumbing. Keep the two folders next to each other.

## Usage

```sh
./autoclicker.py                      # click in Lunar Client, toggle with F9
./autoclicker.py -k f7                # toggle with F7
./autoclicker.py -t '(?i)firefox'     # gate on a different window class
./autoclicker.py -r 0                 # click in place, no cursor movement
./autoclicker.py --any-window         # no focus gating at all
```

| Option | Default | Meaning |
| --- | --- | --- |
| `-k`, `--toggle` | `f9` | key that arms/disarms clicking |
| `-t`, `--target` | `(?i)^Lunar Client \d` | regex matched against the focused window **class** |
| `--any-window` | off | disable focus gating; click into whatever is focused |
| `-r`, `--radius` | `12` | radius in px of the circle the cursor wanders in (`0` disables movement) |

Valid `--toggle` keys:
`w a s d q e r f space shift ctrl alt tab up down left right f1`–`f12`

Get the window class of anything you want to target with:

```sh
hyprctl activewindow | grep class
```

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
relative deltas from a grabbed pointer, and a single large jump reads as a
teleport. Mid-burst the cursor only nudges (3 px) instead of taking a full
stroll. Position is tracked as an internal offset, so the wander stays bounded
even when the game has the pointer captured.

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

- The toggle key is read from every real keyboard under `/dev/input/`, so it
  works even while a game has the pointer grabbed. The key still passes
  through to the focused window.
- Automating input can break server rules or trip anti-cheat. Your call.
