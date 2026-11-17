# Patch notes

Everything that changed in diskmap, newest first. This file is compiled into the
program and is what the **Patch notes** overlay (`c`) shows.

Format: `## [version] - date`, or `## [version] - first day to release day` for a release made
over several days, then `### Added`, `### Changed`, `### Security`, `### Performance`, `### Stability`,
`### Fixed` or `### Removed` with one bullet per change. Security is something somebody could have
misused, Performance something that got quicker or lighter, Stability something that can no longer
crash, hang, leak or lose data, Fixed something that gave a wrong answer. An `x.y.0` release carries
a short title line under its heading: that title is what the overlay uses as the headline of the
whole series.

## [0.1.0] - 2026-11-17

First release: see where the space went

### Added
- A scan of any folder in the background, in parallel, with live counters; `q` stops it.
- The folder tree sorted by size, with subtree bars, percentages and file counts.
- The file types, by extension, with their share of the space and their treemap colour.
- A squarified cushion treemap in half blocks; clicking a rectangle finds its file, `z` zooms in.
- Focusing a file type lights up only its files in the treemap.
- Allocated or apparent size (`a`), a fresh scan (`r`) and opening a folder in the file manager (`o`).
- Help (`?`) and these patch notes (`c`) inside the program.
- The scan stays on one filesystem, btrfs subvolumes of it included, unless `-x` is given.
- A hard-linked file is counted once, and symbolic links are never followed.

## [0.0.0] - 2026-11-17

The empty project

### Added
- The project skeleton: `AGENTS.md`, `DESIGN.md`, the licence and these patch notes, compiled in.
