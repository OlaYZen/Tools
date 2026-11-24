/*
 * Collapse timeline noise: runs of 3+ consecutive events (label changes, review
 * requests, force-pushes, pushed commits …) between comments in PRs/issues are
 * folded into one "Show N events" line.
 */
(() => {
  "use strict";

  const NOISE = ".timeline-item.event, .timeline-item.commits-list";
  const MIN_EVENTS = 3;

  function verb(item) {
    // "crystal added 2 commits <time>" → "added"
    const author = item.querySelector("a.author, .author")?.textContent.trim() ?? "";
    const text = item.querySelector(".text")?.textContent.replace(/\s+/g, " ").trim() ?? "";
    const rest = author && text.startsWith(author) ? text.slice(author.length) : text;
    return rest.trim().split(" ")[0]?.toLowerCase() || "";
  }

  function collapse(run) {
    const events = run.filter((el) => el.matches(".event"));
    if (events.length < MIN_EVENTS) return;
    // Don't hide what a link points at.
    if (location.hash && run.some((el) => el.id && `#${el.id}` === location.hash)) return;

    const verbs = [...new Set(events.map(verb).filter(Boolean))].slice(0, 4);
    const bar = document.createElement("div");
    bar.className = "rf-tl-bar";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "rf-link-button";
    btn.textContent = `Show ${events.length} hidden events`;
    bar.append(btn);
    if (verbs.length) bar.append(RF.span("rf-tl-verbs", ` (${verbs.join(", ")})`));

    for (const el of run) el.classList.add("rf-tl-hidden");
    run[0].before(bar);
    btn.addEventListener("click", () => {
      for (const el of run) el.classList.remove("rf-tl-hidden");
      bar.remove();
    });
  }

  function process(timeline) {
    if (timeline.hasAttribute("data-rf-tl")) return;
    timeline.setAttribute("data-rf-tl", "");
    let run = [];
    for (const child of [...timeline.children]) {
      if (child.matches(NOISE)) {
        run.push(child);
      } else if (child.matches(".timeline-item, .timeline-item-group")) {
        collapse(run);
        run = [];
      }
      // Other children (#flash-message, #insert-timeline …) neither break nor join a run.
    }
    collapse(run);
  }

  RF.register({
    id: "timeline-collapse",
    scan(root) {
      if (root !== document) return; // only on full page load
      document.querySelectorAll(".ui.timeline").forEach(process);
    },
  });
})();
