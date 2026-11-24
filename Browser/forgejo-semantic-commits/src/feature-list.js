/*
 * Feature metadata, shared by the content scripts and the options page.
 * To add a feature: add an entry here, create src/features/<id>.js that calls
 * RF.register({ id, init?, scan? }), and list the file in manifest.json.
 */
var RF_FEATURES = [
  {
    id: "semantic-commits",
    name: "Semantic commit labels",
    description: "Shows Conventional Commit prefixes (feat:, fix(api):, chore!: …) as coloured label pills.",
    default: true,
  },
  {
    id: "time-colors",
    name: "Coloured relative times",
    description: "Colours every date by age: green under an hour, fading slowly to orange at 6 months, then dimmed.",
    default: true,
  },
  {
    id: "github-dark",
    name: "GitHub dark colours",
    description: "When a dark Forgejo theme is active, use GitHub's dark palette (backgrounds, borders, text, blue links, green buttons). Colour-blind themes keep their diff colours.",
    default: true,
  },
  {
    id: "sticky-header",
    name: "Sticky navbar",
    description: "Keeps the top navigation bar at the top while scrolling. Diff toolbars and file headers stack below it.",
    default: true,
  },
  {
    id: "repo-home-layout",
    name: "GitHub-style repository page",
    description: "Repo home with files and README on the left and an About / Releases / Packages / Languages sidebar on the right.",
    default: true,
  },
  {
    id: "co-authors",
    name: "Co-authors & commit trailers",
    description: "Co-authored-by like GitHub (stacked avatars, “Author and Co-author”), plus chips/lists for Reviewed-by, Signed-off-by, Tested-by, Acked-by and every other “…-by:” trailer.",
    default: true,
  },
  {
    id: "absolute-dates",
    name: "Absolute-date toggle",
    description: "Click any date to switch the whole page between “2 hours ago” and “2026-11-04 13:13”. Remembered per site.",
    default: true,
  },
  {
    id: "timeline-collapse",
    name: "Collapse timeline noise",
    description: "Folds runs of 3+ events (labels, review requests, pushes …) between comments into one “Show N events” line.",
    default: true,
  },
  {
    id: "hide-bot-comments",
    name: "Collapse bot comments",
    description: "Collapses comments from renovate, dependabot, *-bot, *-actions … to their header line.",
    default: true,
  },
  {
    id: "fold-generated-files",
    name: "Fold lockfiles & generated files",
    description: "Folds package-lock.json, go.sum, Cargo.lock, *.min.js, snapshots and files marked Generated in diffs.",
    default: true,
  },
  {
    id: "pr-list-extras",
    name: "PR list: size & source branch",
    description: "Adds an XS–XL size label and the source branch (“feature → main”) to pull request lists. Uses the Forgejo API.",
    default: true,
  },
  {
    id: "keyboard-shortcuts",
    name: "Keyboard shortcuts",
    description: "GitHub-style shortcuts: t go to file, y permalink, g i / g p / g c … Press ? on any page for the list.",
    default: true,
  },
];
