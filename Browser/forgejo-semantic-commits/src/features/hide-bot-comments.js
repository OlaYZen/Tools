/*
 * Collapse comments from bots (renovate, dependabot, forgejo-actions, *-bot …)
 * down to their header line, with a "Show" button. Extra bot usernames can be
 * added in the options. The PR/issue description itself is never hidden.
 */
(() => {
  "use strict";

  const BOT_RE = /(\[bot\]$|[-_]bot$|^bot[-_]|^renovate|^dependabot|-actions$|^github-actions|^forgejo-actions|^gitea-actions)/i;

  function isBot(name, extra) {
    return BOT_RE.test(name) || extra.has(name.toLowerCase());
  }

  function process(item, extra) {
    if (item.hasAttribute("data-rf-bot")) return;
    item.setAttribute("data-rf-bot", "");
    const author = item.querySelector(".comment-header a.author")?.textContent.trim();
    if (!author || !isBot(author, extra)) return;
    if (location.hash && item.id && location.hash === `#${item.id}`) return; // linked to: keep open

    item.classList.add("rf-bot-collapsed");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "rf-link-button rf-bot-toggle";
    btn.textContent = "bot · show";
    btn.addEventListener("click", () => {
      const collapsed = item.classList.toggle("rf-bot-collapsed");
      btn.textContent = collapsed ? "bot · show" : "bot · hide";
    });
    item.querySelector(".comment-header-left")?.append(btn);
  }

  RF.register({
    id: "hide-bot-comments",
    scan(root, settings) {
      const extra = new Set(
        String(settings.botUsers || "").split(/[\s,]+/).map((s) => s.trim().toLowerCase()).filter(Boolean)
      );
      const sel = ".timeline-item.comment:not(.first)";
      if (root.matches?.(sel)) process(root, extra);
      root.querySelectorAll(sel).forEach((el) => process(el, extra));
    },
  });
})();
