# Refined Forgejo

Firefox / Zen extension that makes Forgejo (and Gitea) nicer to use, in the spirit of Refined GitHub. Every feature can be switched on or off in the extension's preferences.

## Features

| Feature | What it does |
|---|---|
| **GitHub dark colours** | When a dark Forgejo/Gitea theme is active (incl. *auto* in dark mode), its colour variables are replaced with GitHub's dark palette: `#0d1117` page, `#161b22` panels, `#010409` header bars, `#30363d` borders, `#e6edf3` text, blue `#4493f8` links, green primary buttons and the coral active-tab underline. Applied at page start, so no flash. Colour-blind themes (deuteranopia/protanopia/tritanopia) keep their own diff colours. Light themes are left alone. |
| **Sticky navbar** | The top navigation bar stays at the top while scrolling (the repository header scrolls normally). Forgejo's own sticky diff toolbar, file tree and file headers are pushed below it, and anchor links land below it. |
| **GitHub-style repository page** | The repo home gets GitHub's layout: branch row, files and README on the left; a sidebar on the right with **About** (description, website, topic pills, Readme / license name / Activity / stars / watching / forks / size), **Releases** (latest release with a *Latest* badge, "+ N releases"), **Packages** and **Languages** (segmented bar + list). Branch/tag counts sit next to the branch selector and "N Commits" in the latest-commit row. Below ~1000 px the sidebar stacks above the files. |
| **Co-authors** | `Co-authored-by: Name <email>` trailers show like GitHub: stacked avatars and "Author and Co-author" / "Author and N others" (hover for names) in commit lists, on commit pages and in the latest-commit bar. `user@noreply.<host>` co-authors link to their Forgejo profile. Co-authors/authors named "Claude …" (or `@anthropic.com`) get a Claude avatar (`CLAUDE_AVATAR` in `co-authors.js`); avatars that fail to load fall back to Forgejo's default. |
| **Commit trailers** | Every other `…-by:` trailer — `Reviewed-by`, `Signed-off-by`, `Acked-by`, `Tested-by`, `Reported-by`, `Suggested-by`, `Helped-by`, `Approved-by`, `Assisted-by`, `Requested-by`, `Mentored-by`, `Inspired-by` and any unknown `Something-by` — shows as a chip per type (icon + avatars, hover for names/emails) after the message in commit lists and the latest-commit bar, and as a "Reviewed by ◯ Name" list on the commit page. The author's own `Signed-off-by` is hidden. Trailers without an email are supported. |
| **Semantic commit labels** | `feat(api)!: add token endpoint` → **[feat · api] [BREAKING]** add token endpoint. Works in commit lists, the repo home page, single commit pages and PR/issue lists. Chained prefixes (`WIP: feat: …`) get one label each. |
| **Coloured relative times** | Every date is coloured by age on a smooth gradient: **green** under an hour, fading slowly through yellow to **orange** at "6 months ago" (roughly 6 % orange at 1 day, 17 % at 1 week, 37 % at 1 month, 64 % at 3 months). Older dates are muted and dimmed to 80 %, and 60 % past a year. Alternative *Freshness* scheme in the options (green < 1 day, amber < 1 week, faded after a month). Re-coloured every minute. |
| **Absolute-date toggle** | Click any date to switch the whole page between "2 hours ago" and "2026-11-04 13:13" (local time). Remembered per site. |
| **Collapse timeline noise** | In PRs/issues, runs of 3+ events (labels, review requests, force-pushes, pushed commits …) between comments fold into one "Show N hidden events (added, requested, force-pushed)" line. |
| **Collapse bot comments** | Comments from renovate, dependabot, `*-bot`, `*[bot]`, `*-actions` … collapse to their header with a "bot · show" button. Add your own bot names in the options. |
| **Fold lockfiles & generated files** | `package-lock.json`, `go.sum`, `Cargo.lock`, `*.min.js`, snapshots and files Forgejo marks Generated/Vendored are folded in diffs (uses Forgejo's own fold button). |
| **PR list: size & source branch** | Each PR in a list gets an **XS / S / M / L / XL** label (lines changed; hover for `+a −d in n files`) and its source branch: `user:feature → main`. Data from the Forgejo API, cached 10 min per tab. |
| **Keyboard shortcuts** | `?` help · `/` search · `t` go to file · `y` permalink (pins the URL to the commit and copies it) · `g c` code · `g i` issues · `g p` PRs · `g a` actions · `g r` releases · `g w` wiki · `g m` commits · `g s` settings · `g n` notifications · `g d` dashboard. |

Sticky diff file headers aren't included: Forgejo already has them.

Recognised commit types: `feat` `fix` `docs` `style` `refactor` `perf` `test` `build` `ci` `chore` `revert` `security` `deps` `release` `i18n` `wip`, plus aliases (`feature`, `hotfix`, `bugfix`, `doc`, `tests`, `l10n` …). Unknown prefixes are left untouched.

## Install

### Temporary (development; removed when the browser restarts)
1. Open `about:debugging#/runtime/this-firefox`
2. **Load Temporary Add-on…** → pick `manifest.json` in this folder.

### Permanent
Release builds of Firefox and Zen only install signed add-ons. Either:
- **Sign it as unlisted on AMO** (free, private):
  ```
  npx web-ext sign --channel=unlisted --api-key=… --api-secret=…
  ```
  and install the `.xpi` it produces. API keys: https://addons.mozilla.org/developers/addon/api/key/
- Or use Firefox Developer Edition/Nightly with `xpinstall.signatures.required = false` and install `refined-forgejo.xpi` via `about:addons` → ⚙ → *Install Add-on From File…*

Firefox MV3 treats host access as opt-in: after installing, open the add-on's **Permissions** tab in `about:addons` and allow access to your Forgejo site (or all sites).

## Settings

`about:addons` → Refined Forgejo → **Preferences**: toggle each feature, force-enable on hosts that auto-detection misses, or disable on specific hosts. Reload Forgejo tabs after saving.

## How it works

- `src/core.js` detects Forgejo/Gitea (every page of both has an inline `window.config = { appSubUrl … }`), loads settings, runs each enabled feature on the page, and re-runs them on content added later (htmx swaps etc.) through a `MutationObserver`. On any other site it exits right away.
- `src/feature-list.js` holds the feature metadata, shared with the options page.
- `src/features/<id>.js` + `.css` is one feature each.

### Load order & performance
- `src/early-theme.js` + `src/github-dark.css` run at `document_start` (before first paint).
- The main bundle runs at `document_end` (HTML parsed, before images/avatars finish loading).
- Features run in phases: `phase: "first"` (layout, theme) → `"normal"` (default) → `"late"` (date colours, absolute dates) in idle time.
- Per-feature timings: run `localStorage.setItem("rf-debug", "1")` in the page console and reload; timings appear as `[Refined Forgejo] … ms` debug messages.

### Adding a feature
1. Add `{ id, name, description, default }` to `src/feature-list.js`.
2. Create `src/features/<id>.js`:
   ```js
   (() => {
     RF.register({
       id: "<id>",
       init(settings) { /* once per page, optional */ },
       scan(root, settings) { /* on the page and on every added subtree; must be idempotent */ },
     });
   })();
   ```
3. List the `.js` (before `src/main.js`) and any `.css` in `manifest.json`.

## Build the .xpi

```powershell
Compress-Archive -Path manifest.json,src,options,icons -DestinationPath refined-forgejo.zip -Force; Move-Item refined-forgejo.zip refined-forgejo.xpi -Force
```
