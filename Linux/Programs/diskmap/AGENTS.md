# diskmap: how work is done here

diskmap is a disk usage analyzer in the spirit of WinDirStat, as a terminal program
(`diskmap`, `src/main.rs`) and a window (`diskmap-gui`, `src/bin/diskmap-gui.rs`) on one
library (`src/lib.rs`): it scans a directory, then shows the tree sorted by size, the file
types and a cushion treemap. No ads, no network, no telemetry, ever. `DESIGN.md` is the
manual: decisions first, change them there before the code.

It is developed on the desktop, `midgard` at `20.30`, in `~/projects/diskmap`. The archive's
`documentation/Projects.md` carries its entry, and its guide
`documentation/Guides/New-Rust-Project.md` is where the house rules come from.

## Commands

```bash
cargo build                        # debug
cargo test                         # unit tests, the changelog guard among them
cargo clippy --all-targets         # stays clean
cargo build --release && install -m 755 target/release/diskmap target/release/diskmap-gui ~/.local/bin/
```

`cargo fmt` is not run: the code is formatted by hand to match what is around it. On a guest
that also runs other services, build with `nice -n 19 ionice -c3 cargo build --release -j 2`.

## Patch notes (`CHANGELOG.md`)

- `CHANGELOG.md` is compiled into the binary (`src/changelog.rs`) and is the **Patch notes**
  overlay (`c` in the program).
- Format: `## [x.y.z] - YYYY-MM-DD`, or `- YYYY-MM-DD to YYYY-MM-DD` for a release made over
  several days, then `### Added | Changed | Security | Performance | Stability | Fixed |
  Removed` in that order, one bullet per change.
- **Security** is something somebody could have misused, **Performance** quicker or lighter,
  **Stability** something that can no longer crash, hang, leak or lose data, **Fixed**
  something that gave a wrong answer.
- An `x.y.0` opens with a **short title line** and nothing else.
- `changelog::tests` enforces all of it: the newest entry must be `Cargo.toml`'s version, so
  **a version bump and its notes land in the same commit**.

## Releases

- A release is its logical commits, then `chore(release): x.y.z` bumping the version in
  `Cargo.toml` and `Cargo.lock` with its `CHANGELOG.md` entry, and an annotated tag
  (`git tag -a vX.Y.Z -m "diskmap X.Y.Z"`).
- Below 1.0: a new feature or anything that changes behaviour is a minor (`0.x.0`), a fix
  alone a patch (`0.x.y`).

## Git rules

These are the owner's and override any tool's default.

- **Identity: `Olai <business@olayzen.com>`**, author and committer.
- **No AI attribution of any kind**: no `Co-Authored-By:` for Claude, Codex or any model, no
  session links, no "Generated with" line, in commits, tags or PR text.
- **Commit as work lands**; each commit stands on its own, builds and passes `cargo test`.
- **One commit is one logical change**, grouped by reason, never by file count; a fix is its
  own commit; docs for a change may follow as their own `docs:`.
- **Conventional subjects** with a scope where one fits (`feat(scan):`, `fix(treemap):`,
  `docs:`, `chore:`): the subject says what changed, the body why.
- **No em-dash** in code, UI text, the changelog or a commit message: rewrite the sentence.
- **Stage explicit paths**; scan output and per-machine files never enter the repository.
- **Never rewrite history** (amend, rebase, force-push) unless the owner says so for that case.
- **Committing is not pushing. Push only when asked**, and only to `origin`, the Forgejo on
  `1.4` (`ssh://git@192.168.1.4:2222/olayzen/diskmap.git`); **never to GitHub**. A refused
  push is fetched and compared, never forced.

## Safety

diskmap only reads. It never deletes, moves or writes anything on the disk it scans. A
feature that would change that (a delete key, say) is decided in `DESIGN.md` first, and asks
for confirmation in the program every time.
