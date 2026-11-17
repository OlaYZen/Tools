# diskmap: design

## Decisions

1. **A terminal program, not a window and not a web page.** It runs in any terminal on the
   desktop and over SSH on every guest, which is where a full disk usually is. Built on
   `ratatui` with `crossterm`.
2. **Read only.** diskmap never deletes, moves or writes on the disk it scans. Opening a
   folder in the file manager (`xdg-open`) is the one outward action, and it changes nothing.
3. **No network, no ads, no telemetry, no update check.** Nothing in it talks to anything.
4. **Allocated size by default**, as `du` counts it (`st_blocks × 512`): that is what fills a
   disk. `a` switches to the apparent size (`st_size`), and the tree re-sorts.
5. **A hard-linked file is counted once**, at the first path the scan meets, keyed on
   `(st_dev, st_ino)`. Directories are never followed through symbolic links; a link counts
   as its own small entry.
6. **One filesystem by default.** The scan does not cross into other mounts (`/proc`, a NAS
   share, a snapshot) unless `-x`/`--cross-filesystems` is given.
7. **The scan runs in the background, in parallel** (`rayon`, one task per directory), and the
   screen shows its progress until it is done. A directory that cannot be read is counted in
   the status bar, not shown as an error dialog.
8. **The treemap is a squarified cushion treemap**, as WinDirStat draws it: rectangles laid out
   by Bruls, Huizing and van Wijk's squarified algorithm, shaded by van Wijk and van de
   Wetering's cushions so the nesting reads without borders. Each terminal cell is two pixels
   high (the `▀` half block, foreground the top pixel, background the bottom), which doubles
   the vertical resolution.
9. **Colours are by file type.** The extensions taking the most space get a colour each from
   a fixed palette, the rest are grey; the extension list on the right is the legend.
10. **Patch notes are compiled in** and shown with `c`, the house rule for every project.
11. **No configuration file, no systemd unit.** It is a program run by hand, with no state
    between runs; `packaging/` holds only a desktop entry that opens it in a terminal.

## Screen

```
┌ Tree ─────────────────────────────────────────┐┌ Types ──────────┐
│ ▾ /home/olayzen      ██████████  100%  412 G  ││ ■ .mkv   180 G  │
│   ▸ Videos           ████▌        45%  186 G  ││ ■ .iso    40 G  │
│   ▸ projects         ██           18%   74 G  ││ ■ .rlib   22 G  │
└───────────────────────────────────────────────┘└─────────────────┘
┌ Treemap ───────────────────────────────────────────────────────────┐
│ (cushion treemap of the tree's root, the selection outlined)       │
└────────────────────────────────────────────────────────────────────┘
 /home/olayzen/Videos  ·  186 G  ·  2 431 files  ·  allocated   ? help
```

## Keys

| Key | Does |
|---|---|
| `↑` `↓` `PgUp` `PgDn` `Home` `End` | move in the focused list |
| `→` / `Enter` | open a folder in the tree |
| `←` | close a folder, or go to its parent |
| `Tab` | switch focus between the tree and the types |
| `t` | show or hide the treemap |
| `z` | zoom the treemap to the selected folder; `Z` back to the root |
| `a` | allocated or apparent size |
| `o` | open the selected folder in the file manager |
| `r` | scan again |
| `c` | patch notes |
| `?` | help |
| `q` / `Esc` | quit (Esc closes an overlay first) |

Clicking a rectangle in the treemap selects that file in the tree; clicking a row in a list
selects it; the wheel scrolls. While the types list has focus, the treemap lights up only the
selected type's files.

## Considered and rejected

- **A web UI on FinUI.** The house stack for anything with a browser front end, but a disk
  analyzer looks at the disk it runs on, which would mean a server with sign-in on every box.
- **A native window (egui).** Closest to WinDirStat, but useless over SSH on the guests.
- **`jwalk` or `walkdir`.** A hand-written recursion over `rayon` gives the tree directly,
  with sizes summed on the way back up, and no second pass to build it.
