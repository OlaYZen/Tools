# key-holder (Linux)

Toggle-hold a single key down, but only while a chosen window is focused.
Press F8 to arm; the key goes down. Alt-tab away and it releases immediately;
tab back and it presses again. Ctrl+C always releases before exiting.

Input is injected through a virtual **uinput** keyboard, so games that read the
kernel evdev stream see it as a real device. Focus is tracked live over
Hyprland's IPC event socket — no polling.

Windows counterpart: `Windows/Script/key-holder/key_holder.py`

## Requirements

- Python 3 — no third-party packages, pure `ctypes`
- Write access to `/dev/uinput` and read access to `/dev/input/event*`:
  ```sh
  sudo usermod -aG input $USER   # then log out and back in
  sudo modprobe uinput           # if /dev/uinput is missing
  ```
- **Hyprland** for focus gating. Under any other compositor, pass
  `--any-window` — the virtual keyboard itself works anywhere.

## Usage

```sh
./key_holder.py                       # hold W in Lunar Client, toggle with F8
./key_holder.py shift                 # hold Shift instead
./key_holder.py w -k f10              # toggle with F10
./key_holder.py -t '(?i)firefox'      # gate on a different window class
./key_holder.py --any-window          # no focus gating at all
```

| Option | Default | Meaning |
| --- | --- | --- |
| `key` (positional) | `w` | key to hold down |
| `-k`, `--toggle` | `f8` | key that arms/disarms the hold |
| `-t`, `--target` | `(?i)^Lunar Client \d` | regex matched against the focused window **class** |
| `--any-window` | off | disable focus gating; hold regardless of focus |

Valid keys for both `key` and `--toggle`:
`w a s d q e r f space shift ctrl alt tab up down left right f1`–`f12`

Get the window class of anything you want to target with:

```sh
hyprctl activewindow | grep class
```

## Status line

```
HOLDING 'w'            armed, target focused, key is down
WAITING (not focused)  armed, but something else has focus
OFF                    disarmed
```

## Notes

- The toggle key is read from every real keyboard under `/dev/input/`, so it
  works even while a game has the pointer grabbed. The key still passes
  through to the focused window.
- `autoclicker.py` imports the uinput plumbing from this file — keep the two
  folders as siblings.
- Automating input can break server rules or trip anti-cheat. Your call.
