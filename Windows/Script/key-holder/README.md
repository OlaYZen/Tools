# key-holder (Windows)

Toggle-hold a single key down, but only while a chosen window is in the
foreground. Press F8 to arm; the key goes down. Alt-tab away and it releases
immediately; tab back and it presses again. Ctrl+C — or closing the console —
always releases before exiting.

Keys are sent with `SendInput` using hardware **scancodes**, so DirectInput /
DirectX games accept them. The toggle key comes from a system-wide low-level
keyboard hook and is still passed through to whatever has focus.

Linux counterpart: `Linux/Scripts/Universal/key-holder/key_holder.py`

## Requirements

- Windows 10 or 11
- Python 3 — no third-party packages, pure `ctypes`
- Run the console **as administrator** if the target game runs elevated.
  Windows blocks both the keyboard hook and injected input from reaching a
  higher-integrity process.

## Usage

```bat
python key_holder.py                      :: hold W in Lunar Client, toggle with F8
python key_holder.py shift                :: hold Shift instead
python key_holder.py w -k f10             :: toggle with F10
python key_holder.py -t "(?i)javaw"       :: gate on a different window
python key_holder.py --any-window         :: no focus gating at all
```

| Option | Default | Meaning |
| --- | --- | --- |
| `key` (positional) | `w` | key to hold down |
| `-k`, `--toggle` | `f8` | key that arms/disarms the hold |
| `-t`, `--target` | `(?i)^Lunar Client \d` | regex matched against the foreground window **title or exe name** |
| `--any-window` | off | disable focus gating; hold regardless of focus |

Valid keys for both `key` and `--toggle`:
`w a s d q e r f space shift ctrl alt tab up down left right f1`–`f12`

Because the regex is tried against both the window title and the executable
name, `"(?i)javaw"` and `"(?i)^Lunar Client"` are both valid ways to target
the same game.

## Status line

```
HOLDING 'w'            armed, target focused, key is down
WAITING (not focused)  armed, but something else has focus
OFF                    disarmed
```

## Notes

- Injected events are stamped with a marker so the hook ignores the script's
  own output and can't toggle itself.
- The foreground window is polled rather than hooked; the expensive part (the
  process image lookup) is cached until the window handle changes.
- Automating input can break server rules or trip anti-cheat. Your call.
