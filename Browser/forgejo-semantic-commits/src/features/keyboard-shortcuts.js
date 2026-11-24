/*
 * GitHub-style keyboard shortcuts. Press ? for the list.
 */
(() => {
  "use strict";

  const repoLink = (sub) => () => {
    const r = RF.repo();
    if (!r) return RF.toast("Not inside a repository");
    location.href = r.path + sub;
  };

  async function goToFile() {
    const existing = document.querySelector('a[href*="/find/"]');
    if (existing) return (location.href = existing.href);
    const r = RF.repo();
    if (!r) return RF.toast("Not inside a repository");
    // Current branch from the URL if we're browsing one, otherwise the default branch.
    const m = /\/(?:src|find|commits)\/branch\/(.+?)(?:\/|$)/.exec(location.pathname.slice(r.path.length));
    let branch = m && m[1];
    if (!branch) {
      try {
        branch = (await RF.apiGet(`/repos/${r.owner}/${r.name}`)).default_branch;
      } catch {
        return RF.toast("Couldn't look up the default branch");
      }
    }
    location.href = `${r.path}/find/branch/${branch}`;
  }

  function permalink() {
    const a = [...document.querySelectorAll('a[href*="/src/commit/"]')].find((x) => /permalink/i.test(x.textContent));
    if (!a) return RF.toast("No permalink on this page");
    const target = new URL(a.href);
    target.hash = location.hash;
    history.replaceState(history.state, "", target.href);
    navigator.clipboard?.writeText(target.href).then(
      () => RF.toast("Permalink copied and URL updated"),
      () => RF.toast("URL updated to permalink")
    );
  }

  function focusSearch() {
    const input = document.querySelector(
      'input[name="q"]:not([type="hidden"]), .repo-search input, #navbar input[type="search"]'
    );
    if (!input) return RF.toast("No search box on this page");
    input.focus();
    input.select();
  }

  // [keys, description, action]
  const SHORTCUTS = [
    ["?", "Show this help", () => toggleHelp()],
    ["/", "Focus the search box", focusSearch],
    ["t", "Go to file", goToFile],
    ["y", "Permalink: pin URL to the current commit (and copy it)", permalink],
    ["g c", "Go to Code", repoLink("")],
    ["g i", "Go to Issues", repoLink("/issues")],
    ["g p", "Go to Pull requests", repoLink("/pulls")],
    ["g a", "Go to Actions", repoLink("/actions")],
    ["g r", "Go to Releases", repoLink("/releases")],
    ["g w", "Go to Wiki", repoLink("/wiki")],
    ["g m", "Go to Commits", repoLink("/commits")],
    ["g s", "Go to repository Settings", repoLink("/settings")],
    ["g n", "Go to Notifications", () => (location.href = RF.url("/notifications"))],
    ["g d", "Go to Dashboard", () => (location.href = RF.url("/"))],
  ];

  let help = null;
  function toggleHelp() {
    if (help) {
      help.remove();
      help = null;
      return;
    }
    help = document.createElement("div");
    help.className = "rf-kbd-overlay";
    const box = document.createElement("div");
    box.className = "rf-kbd-box";
    const h = document.createElement("h3");
    h.textContent = "Keyboard shortcuts";
    box.append(h);
    const table = document.createElement("table");
    for (const [keys, desc] of SHORTCUTS) {
      const tr = document.createElement("tr");
      const k = document.createElement("td");
      for (const key of keys.split(" ")) {
        const kbd = document.createElement("kbd");
        kbd.textContent = key;
        k.append(kbd, " ");
      }
      const d = document.createElement("td");
      d.textContent = desc;
      tr.append(k, d);
      table.append(tr);
    }
    box.append(table);
    help.append(box);
    help.addEventListener("click", (e) => e.target === help && toggleHelp());
    document.body.append(help);
  }

  let prefix = "";
  let prefixTimer = 0;

  function onKey(e) {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || RF.isTyping(e)) return;
    if (e.key === "Escape" && help) return toggleHelp();

    const combo = prefix ? `${prefix} ${e.key}` : e.key;
    const match = SHORTCUTS.find(([keys]) => keys === combo);
    if (match) {
      e.preventDefault();
      prefix = "";
      match[2]();
      return;
    }
    // Start a two-key sequence ("g …")?
    if (!prefix && SHORTCUTS.some(([keys]) => keys.startsWith(`${e.key} `))) {
      prefix = e.key;
      clearTimeout(prefixTimer);
      prefixTimer = setTimeout(() => (prefix = ""), 1500);
      return;
    }
    prefix = "";
  }

  RF.register({
    id: "keyboard-shortcuts",
    init() {
      document.addEventListener("keydown", onKey);
    },
  });
})();
