/*
 * Semantic commit labels: "feat(api)!: add x" → [feat | api] [BREAKING] add x
 */
(() => {
  "use strict";

  // Mid-tone colours; CSS mixes them with the page's text colour so the pills
  // stay readable in both light and dark themes.
  const TYPES = {
    feat:     { color: "#2ea043", desc: "A new feature" },
    fix:      { color: "#f85149", desc: "A bug fix" },
    docs:     { color: "#388bfd", desc: "Documentation only changes" },
    style:    { color: "#db61a2", desc: "Formatting, whitespace, etc. (no code change)" },
    refactor: { color: "#a371f7", desc: "Code change that neither fixes a bug nor adds a feature" },
    perf:     { color: "#f0883e", desc: "A code change that improves performance" },
    test:     { color: "#d29922", desc: "Adding or correcting tests" },
    build:    { color: "#bc8c4b", desc: "Build system or external dependencies" },
    ci:       { color: "#39c5cf", desc: "CI configuration files and scripts" },
    chore:    { color: "#8b949e", desc: "Other changes that don't modify src or test files" },
    revert:   { color: "#cf222e", desc: "Reverts a previous commit" },
    security: { color: "#e5534b", desc: "Security fix or hardening" },
    deps:     { color: "#bc8c4b", desc: "Dependency updates" },
    release:  { color: "#8957e5", desc: "Release / version bump" },
    i18n:     { color: "#3fb9a8", desc: "Translations / internationalisation" },
    wip:      { color: "#9e6a03", desc: "Work in progress" },
  };

  const ALIASES = {
    feature: "feat", features: "feat",
    bugfix: "fix", hotfix: "fix", bug: "fix",
    doc: "docs",
    tests: "test",
    refactoring: "refactor",
    performance: "perf",
    dep: "deps",
    chores: "chore",
    sec: "security",
    l10n: "i18n",
  };

  // type, optional (scope), optional !, colon, at least one space.
  const PREFIX_RE = /^(\s*)([A-Za-z0-9]+)(?:\(([^()\n]{1,60})\))?(!)?:[ \t]+(?=\S)/;

  // Places a commit summary or PR title shows up in Forgejo / Gitea.
  const SELECTOR = [
    'a[href*="/commit/"]',     // commit lists, latest-commit bar, file table
    ".commit-summary",         // single-commit page header
    "#issue-title",            // PR / issue page header
    "a.issue-title",           // PR / issue lists (older)
    ".flex-item-title > a",    // PR / issue lists (newer)
  ].join(",");

  const DONE_ATTR = "data-rf-sc";

  function firstTextNode(el) {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP),
    });
    return walker.nextNode();
  }

  function buildBadges(type, raw, scope, breaking, settings) {
    const def = TYPES[type];
    const wrap = RF.span("rf-sc-badges");

    const badge = RF.span("rf-sc-badge");
    badge.style.setProperty("--rf-color", def.color);
    badge.title = `${raw}${scope ? `(${scope})` : ""}${breaking ? "!" : ""} — ${def.desc}`;
    badge.append(RF.span("rf-sc-type", type));
    if (scope && settings.showScope) badge.append(RF.span("rf-sc-scope", scope));
    wrap.append(badge);

    if (breaking) {
      const br = RF.span("rf-sc-badge rf-sc-breaking", "breaking");
      br.style.setProperty("--rf-color", "#f85149");
      br.title = "Breaking change";
      wrap.append(br);
    }
    return wrap;
  }

  function decorate(el, settings) {
    if (el.hasAttribute(DONE_ATTR)) return;
    el.setAttribute(DONE_ATTR, "");
    if (el.closest(".rf-sc-badges") || el.querySelector(".rf-sc-badges")) return;

    const tn = firstTextNode(el);
    if (!tn) return;

    // Handle chained prefixes such as "WIP: feat(ui): …" (max 3).
    for (let i = 0; i < 3; i++) {
      const m = PREFIX_RE.exec(tn.nodeValue);
      if (!m) return;

      const raw = m[2];
      const key = raw.toLowerCase();
      const type = ALIASES[key] || key;
      if (!TYPES[type]) return;

      tn.nodeValue = tn.nodeValue.slice(m[0].length);
      tn.parentNode.insertBefore(buildBadges(type, raw, m[3], !!m[4], settings), tn);
    }
  }

  RF.register({
    id: "semantic-commits",
    scan(root, settings) {
      if (root.matches?.(SELECTOR)) decorate(root, settings);
      root.querySelectorAll(SELECTOR).forEach((el) => decorate(el, settings));
    },
  });
})();
