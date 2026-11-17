# diskmap: design

## Decisions

1. **Two front ends on one engine: a terminal program and a window, never a web page.**
   `diskmap` runs in any terminal, on the desktop and over SSH on every guest, which is
   where a full disk usually is (`ratatui` with `crossterm`). `diskmap-gui` is a native
   window for the desktop, laid out like WinDirStat (`eframe`/`egui`), started from an app
   launcher. The scan, the treemap, the formatting and the patch notes are the `diskmap`
   library both are built on (`src/lib.rs`), so they count and draw the same.
2. **The window opens on a choice of disk** when it is started without a path, as it is from
   a launcher: one entry per real filesystem (no `/proc`, tmpfs or container overlays), at its
   shortest mount point, with its size and free space from `statvfs`, plus a folder field.
3. **Read only.** diskmap never deletes, moves or writes on the disk it scans. Opening a
   folder in the file manager (`xdg-open`) is the one outward action, and it changes nothing.
4. **No network, no ads, no telemetry, no update check.** Nothing in it talks to anything.
5. **Allocated size by default**, as `du` counts it (`st_blocks × 512`): that is what fills a
   disk. `a` switches to the apparent size (`st_size`), and the tree re-sorts.
6. **A hard-linked file is counted once**, at the first path the scan meets, keyed on
   `(st_dev, st_ino)`. Directories are never followed through symbolic links; a link counts
   as its own small entry.
7. **One filesystem by default.** The scan does not cross into other mounts (`/proc`, a NAS
   share, a USB disk, a container overlay) unless `-x`/`--cross-filesystems` is given. "Other"
   is decided by the filesystem id in `/proc/self/mountinfo`, not by `st_dev`: on btrfs every
   subvolume has its own `st_dev`, so `/home` on the same partition as `/` would otherwise be
   left out. A folder whose `st_dev` changes is entered when it is a mount of the same
   filesystem or not a mount point at all (an unmounted subvolume); without `/proc` the
   `st_dev` rule is all there is.
   On btrfs the total can exceed what `df` reports: `st_blocks` counts compressed files at
   their uncompressed size and cannot see extents shared by reflinks and snapshots. `du`
   counts the same way.
8. **The scan runs in the background, in parallel** (`rayon`, one task per directory), and the
   screen shows its progress until it is done. A directory that cannot be read is counted in
   the status bar, not shown as an error dialog.
9. **The treemap is a squarified cushion treemap**, as WinDirStat draws it: rectangles laid out
   by Bruls, Huizing and van Wijk's squarified algorithm, shaded by van Wijk and van de
   Wetering's cushions so the nesting reads without borders. The window draws it at the
   screen's own resolution. In the terminal each cell is two pixels
   high (the `▀` half block, foreground the top pixel, background the bottom), which doubles
   the vertical resolution.
10. **Colours are by file type.** The extensions taking the most space get a colour each from
   a fixed palette, the rest are grey; the extension list on the right is the legend.
11. **Patch notes are compiled in** and shown with `c`, the house rule for every project.
12. **No configuration file, no systemd unit.** It is a program run by hand, with no state
    between runs; `packaging/` holds only a desktop entry that opens it in a terminal.

## The terminal screen

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

## The window

A toolbar (new scan, rescan, allocated or apparent, treemap on or off, patch notes), the tree
in the middle, the file types on the right and the treemap along the bottom, both panels
resizable, and the selection's path and size in the status bar. The tree opens with the arrows
or a double click and moves with the arrow keys. Hovering the treemap names the file under the
pointer; a click selects it in the tree, a double click zooms there. Clicking a type lights up
only its files, a second click shows them all again. A right click on a row or a rectangle
offers zooming there, opening the folder in the file manager and copying the path.

## Considered and rejected

- **A web UI on FinUI.** The house stack for anything with a browser front end, but a disk
  analyzer looks at the disk it runs on, which would mean a server with sign-in on every box.
- **Only a window, or only a terminal program.** A window alone is useless over SSH on the
  guests; a terminal alone cannot be started from the launcher as a desktop app. Both, on
  one library, cost little.
- **GTK4 for the window**, as Hyprdash and HyprToys are built. egui needs no system libraries
  beyond what the compositor provides and draws the treemap texture directly.
- **`jwalk` or `walkdir`.** A hand-written recursion over `rayon` gives the tree directly,
  with sizes summed on the way back up, and no second pass to build it.
