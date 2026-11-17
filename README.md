# diskmap

A disk usage analyzer for the Linux terminal, in the spirit of WinDirStat: it scans a
directory, then shows the tree sorted by size, the file types and a cushion treemap. It only
reads, and it talks to nothing: no ads, no promotions, no update checks, no telemetry.

## Run it

```bash
cargo build --release
install -m 755 target/release/diskmap ~/.local/bin/diskmap

diskmap                 # the current directory
diskmap /               # the root filesystem, without crossing into other mounts
diskmap -x /mnt         # crossing mount points
```

Press `?` inside for the keys, `c` for the patch notes. `DESIGN.md` explains how it counts.

## Licence

GPL-3.0-only. See `LICENSE`.
