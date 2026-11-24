/*
 * Fold lockfiles and generated files in diffs by default (package-lock.json,
 * go.sum, *.min.js, snapshots, files Forgejo marks Generated/Vendored …).
 * Uses Forgejo's own fold button, so unfolding works as usual.
 */
(() => {
  "use strict";

  const PATTERNS = [
    /(^|\/)(package-lock\.json|npm-shrinkwrap\.json|yarn\.lock|pnpm-lock\.yaml|bun\.lockb?|deno\.lock)$/,
    /(^|\/)(go\.sum|Cargo\.lock|composer\.lock|Gemfile\.lock|poetry\.lock|uv\.lock|Pipfile\.lock|pdm\.lock|flake\.lock|mix\.lock|pubspec\.lock|Podfile\.lock|packages\.lock\.json|gradle\.lockfile)$/,
    /\.min\.(js|css)$/,
    /\.(js|css)\.map$/,
    /(^|\/)__snapshots__\//,
    /\.snap$/,
  ];

  const isGeneratedPath = (path) => PATTERNS.some((re) => re.test(path));

  function hasGeneratedLabel(box) {
    const header = box.querySelector(".diff-file-header");
    return [...(header?.querySelectorAll(".ui.label") ?? [])].some((l) =>
      /^(generated|vendored)$/i.test(l.textContent.trim())
    );
  }

  function process(box) {
    if (box.hasAttribute("data-rf-fold")) return;
    box.setAttribute("data-rf-fold", "");
    const path = box.dataset.newFilename || box.dataset.oldFilename || "";
    if (!isGeneratedPath(path) && !hasGeneratedLabel(box)) return;
    if (location.hash && box.id && location.hash.startsWith(`#${box.id}`)) return; // linked to: keep open
    if (box.dataset.folded === "true") return;
    box.querySelector(".diff-file-header .fold-file")?.click();
    box.querySelector(".diff-file-name")?.append(RF.span("rf-pill rf-autofolded", "auto-folded"));
  }

  RF.register({
    id: "fold-generated-files",
    scan(root) {
      if (root.matches?.(".diff-file-box")) process(root);
      root.querySelectorAll(".diff-file-box[data-new-filename], .diff-file-box[data-old-filename]").forEach(process);
    },
  });
})();
