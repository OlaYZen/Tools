/*
 * PR list extras: for each pull request in a list, show
 *   - a size label (XS/S/M/L/XL by lines changed), tooltip "+12 −3 in 4 files"
 *   - the source branch next to the target branch: "feature-x → main"
 * Data comes from the Forgejo API (cached for 10 min per tab).
 */
(() => {
  "use strict";

  const TTL = 10 * 60e3;
  const CONCURRENCY = 4;

  const SIZES = [
    [10, "XS", "#2ea043"],
    [30, "S", "#3fb950"],
    [100, "M", "#d29922"],
    [500, "L", "#f0883e"],
    [Infinity, "XL", "#f85149"],
  ];

  // --- tiny request queue -------------------------------------------------
  const queue = [];
  let running = 0;
  function enqueue(job) {
    return new Promise((resolve, reject) => {
      queue.push({ job, resolve, reject });
      pump();
    });
  }
  function pump() {
    while (running < CONCURRENCY && queue.length) {
      const { job, resolve, reject } = queue.shift();
      running++;
      job().then(resolve, reject).finally(() => {
        running--;
        pump();
      });
    }
  }

  async function getPull(owner, repo, index) {
    const key = `rf-pr:${location.host}/${owner}/${repo}#${index}`;
    try {
      const cached = JSON.parse(sessionStorage.getItem(key) || "null");
      if (cached && Date.now() - cached.t < TTL) return cached;
    } catch { /* ignore */ }

    const pr = await enqueue(() => RF.apiGet(`/repos/${owner}/${repo}/pulls/${index}`));
    const data = {
      t: Date.now(),
      head: pr.head?.ref,
      headRepo: pr.head?.repo?.full_name ?? null,
      baseRepo: pr.base?.repo?.full_name ?? `${owner}/${repo}`,
      additions: pr.additions ?? null,
      deletions: pr.deletions ?? null,
      files: pr.changed_files ?? null,
    };
    try { sessionStorage.setItem(key, JSON.stringify(data)); } catch { /* quota */ }
    return data;
  }

  function sizePill(pr) {
    if (pr.additions == null || pr.deletions == null) return null;
    // AGit-flow PRs come back as +0 −0 in 0 files (stats not computed): show nothing rather than a wrong "XS".
    if (pr.additions + pr.deletions === 0 && !pr.files) return null;
    const lines = pr.additions + pr.deletions;
    const [, label, color] = SIZES.find(([max]) => lines < max);
    const pill = RF.span("rf-pill rf-pr-size", label);
    pill.style.setProperty("--rf-color", color);
    pill.title = `+${pr.additions} −${pr.deletions}${pr.files != null ? ` in ${pr.files} file${pr.files === 1 ? "" : "s"}` : ""}`;
    return pill;
  }

  function headBranch(pr) {
    if (!pr.head || pr.head.startsWith("refs/pull/")) return null; // AGit-flow: no real branch
    const wrap = RF.span("rf-pr-head");
    const a = document.createElement("a");
    const repoPath = pr.headRepo || pr.baseRepo;
    a.href = RF.url(`/${repoPath}/src/branch/${pr.head.split("/").map(encodeURIComponent).join("/")}`);
    const forked = pr.headRepo && pr.headRepo !== pr.baseRepo;
    a.textContent = forked ? `${pr.headRepo.split("/")[0]}:${pr.head}` : pr.head;
    a.title = forked ? `${pr.headRepo}:${pr.head}` : pr.head;
    wrap.append(a, RF.span("rf-pr-arrow", "→"));
    return wrap;
  }

  async function process(item) {
    if (item.hasAttribute("data-rf-pr")) return;
    const link = item.querySelector(".flex-item-title a.issue-title, .flex-item-title > a[href*='/pulls/']");
    const m = link && /\/([^/]+)\/([^/]+)\/pulls\/(\d+)(?:$|[?#])/.exec(link.getAttribute("href"));
    if (!m) return;
    item.setAttribute("data-rf-pr", "");

    let pr;
    try {
      pr = await getPull(m[1], m[2], m[3]);
    } catch (err) {
      console.debug("[Refined Forgejo] pr-list-extras:", err);
      return;
    }

    const pill = sizePill(pr);
    if (pill) link.after(pill);

    const branchBox = item.querySelector(".issue-meta-branch .branch, .issue-meta-branch");
    const head = headBranch(pr);
    if (branchBox && head) branchBox.prepend(head);
  }

  RF.register({
    id: "pr-list-extras",
    scan(root) {
      root.querySelectorAll(".flex-item").forEach((item) => {
        if (item.querySelector(".flex-item-title a[href*='/pulls/']")) process(item);
      });
    },
  });
})();
