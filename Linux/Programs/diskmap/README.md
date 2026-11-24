# diskmap

A disk usage analyzer for Linux, in the spirit of WinDirStat, as a window and as a terminal
program: it scans a directory, then shows the tree sorted by size, the file types and a
cushion treemap. It only reads, and it talks to nothing: no ads, no promotions, no update
checks, no telemetry.

## Install it

```bash
packaging/install.sh
```

That builds both programs, installs them in `~/.local/bin` and adds two entries to the app
launcher (HyprToys, rofi, any desktop menu): **diskmap**, the window, and **diskmap
(terminal)**, the terminal program on the home folder.

## Run it

```bash
diskmap-gui             # the window: choose a disk or a folder
diskmap-gui ~/Videos    # the window, scanning a folder at once
diskmap                 # the terminal program, on the current directory
diskmap /               # the root filesystem, without crossing into other mounts
diskmap -x /mnt         # crossing mount points
```

Press `?` inside for the keys, `c` for the patch notes. `DESIGN.md` explains how it counts.

## Licence

GPL-3.0-only. See `LICENSE`.
