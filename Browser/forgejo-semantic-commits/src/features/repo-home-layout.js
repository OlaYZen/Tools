/*
 * GitHub-style repository home page:
 *   left:  branch row, file list, README
 *   right: About (description, website, topics, Readme / License / Activity /
 *          stars / watching / forks / size), Releases, Packages, Languages
 * Branch/tag counts move next to the branch selector and the commit count
 * into the latest-commit bar, like GitHub.
 *
 * Everything is moved (not copied), so Forgejo's own buttons keep working.
 */
(() => {
  "use strict";

  // --- helpers ---------------------------------------------------------------
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  /** Octicon from Forgejo's own asset folder, tinted with currentColor via a CSS mask. */
  function icon(name) {
    const i = el("span", "rf-gh-icon");
    i.style.setProperty("--rf-icon", `url("${RF.url(`/assets/img/svg/octicon-${name}.svg`)}")`);
    i.setAttribute("aria-hidden", "true");
    return i;
  }

  function link(href, iconName, ...content) {
    const a = el("a", "rf-gh-meta-link");
    a.href = href;
    if (iconName) a.append(icon(iconName));
    a.append(...content);
    return a;
  }

  const countFrom = (node) => node?.textContent.replace(/\s+/g, " ").match(/\d[\d.,]*\s*[kKmM]?/)?.[0].replace(/\s/g, "") ?? null;

  // --- licence detection -----------------------------------------------------
  const LICENSES = [
    [/GNU AFFERO GENERAL PUBLIC LICENSE[\s\S]{0,200}Version 3/i, "AGPL-3.0 license"],
    [/GNU LESSER GENERAL PUBLIC LICENSE[\s\S]{0,200}Version 3/i, "LGPL-3.0 license"],
    [/GNU LESSER GENERAL PUBLIC LICENSE[\s\S]{0,200}Version 2\.1/i, "LGPL-2.1 license"],
    [/GNU GENERAL PUBLIC LICENSE[\s\S]{0,200}Version 3/i, "GPL-3.0 license"],
    [/GNU GENERAL PUBLIC LICENSE[\s\S]{0,200}Version 2/i, "GPL-2.0 license"],
    [/Apache License[\s\S]{0,100}Version 2\.0/i, "Apache-2.0 license"],
    [/Mozilla Public License,?\s*(Version|v\.?)\s*2\.0/i, "MPL-2.0 license"],
    [/European Union Public Licen[cs]e[\s\S]{0,50}1\.2/i, "EUPL-1.2 license"],
    [/This is free and unencumbered software released into the public domain/i, "Unlicense"],
    [/CC0 1\.0 Universal/i, "CC0-1.0 license"],
    [/Permission is hereby granted, free of charge/i, "MIT license"],
    [/Permission to use, copy, modify, and\/or distribute this software for any/i, "ISC license"],
    [/Redistribution and use in source and binary forms[\s\S]*Neither the name/i, "BSD-3-Clause license"],
    [/Redistribution and use in source and binary forms/i, "BSD-2-Clause license"],
  ];

  async function licenseName(fileHref) {
    const key = `rf-license:${location.host}${fileHref}`;
    try {
      const cached = sessionStorage.getItem(key);
      if (cached) return cached;
    } catch { /* ignore */ }
    const text = (await RF.fetchText(fileHref.replace("/src/", "/raw/"))).slice(0, 4000);
    const name = LICENSES.find(([re]) => re.test(text))?.[1] ?? "View license";
    try { sessionStorage.setItem(key, name); } catch { /* ignore */ }
    return name;
  }

  // --- sidebar sections ------------------------------------------------------
  function aboutSection(container, repoPath) {
    const box = el("section", "rf-gh-box");
    box.append(el("h2", "rf-gh-h2", "About"));

    const desc = container.querySelector(":scope > .repo-description");
    const descText = desc?.querySelector(".description")?.textContent.trim();
    const website = desc?.querySelector("a.link");
    const topics = container.querySelector(":scope > #repo-topics");
    const hasTopics = topics && topics.querySelector(".repo-topic");

    if (descText) box.append(el("p", "rf-gh-desc", descText));
    if (website) {
      const a = el("a", "rf-gh-website");
      a.href = website.href;
      a.rel = "nofollow noopener";
      a.append(icon("link"), el("span", null, website.textContent.trim().replace(/^https?:\/\//, "").replace(/\/$/, "")));
      box.append(a);
    }
    if (!descText && !website && !hasTopics) {
      box.append(el("p", "rf-gh-muted rf-gh-desc-empty", "No description, website, or topics provided."));
    }
    // Move Forgejo's own nodes so edit buttons (topic manager etc.) keep working.
    if (desc) { desc.classList.add("rf-gh-hidden"); box.append(desc); }
    if (topics) { topics.classList.add("rf-gh-topics"); box.append(topics); }

    const meta = el("ul", "rf-gh-meta");
    const li = (...nodes) => { const l = el("li"); l.append(...nodes); meta.append(l); return l; };

    if (document.querySelector("#readme")) li(link("#readme", "book", "Readme"));

    const licenseFile = [...document.querySelectorAll("#repo-files-table a[href*='/src/']")].find((a) =>
      /^(licen[cs]e|copying|unlicense)(\.(md|txt|rst))?$/i.test(a.textContent.trim())
    );
    if (licenseFile) {
      const label = el("span", null, "License");
      li(link(licenseFile.getAttribute("href"), "law", label));
      licenseName(licenseFile.getAttribute("href")).then((n) => (label.textContent = n)).catch(() => {});
    }

    const activity = document.querySelector(`a.item[href="${repoPath}/activity"]`);
    if (activity) li(link(activity.getAttribute("href"), "pulse", "Activity"));

    const counter = (suffix, iconName, noun) => {
      const a = document.querySelector(`.repo-header a.label[href="${repoPath}/${suffix}"], .repo-buttons a.label[href="${repoPath}/${suffix}"]`);
      if (!a) return;
      li(link(a.getAttribute("href"), iconName, el("strong", null, a.textContent.trim()), ` ${noun}`));
    };
    counter("stars", "star", "stars");
    counter("watchers", "eye", "watching");
    const forks = document.querySelector(`.repo-header a.label[href="${repoPath}/forks"], .repo-buttons a.label[href="${repoPath}/forks"]`);
    if (forks) li(link(forks.getAttribute("href"), "repo-forked", el("strong", null, forks.textContent.trim()), " forks"));

    const size = container.querySelector(".repository-summary .repository-menu span.item");
    if (size) {
      const s = el("span", "rf-gh-meta-link");
      s.title = size.getAttribute("data-tooltip-content") || "";
      s.append(icon("database"), el("strong", null, size.querySelector("b")?.textContent.trim() ?? ""), ` ${size.textContent.replace(/\s+/g, " ").trim().replace(/^[\d.,]+\s*/, "")}`);
      li(s);
    }

    box.append(meta);
    return box;
  }

  function releasesSection(repoPath, r) {
    const tab = document.querySelector(`a.item[href="${repoPath}/releases"]`);
    if (!tab) return null;
    const count = countFrom(tab.querySelector(".label")) ?? countFrom(tab);
    const box = el("section", "rf-gh-box");
    const h = el("h2", "rf-gh-h2");
    const ha = el("a", "rf-gh-h2-link", "Releases");
    ha.href = tab.getAttribute("href");
    if (count) ha.append(el("span", "rf-gh-counter", count));
    h.append(ha);
    box.append(h);

    if (!count || count === "0") {
      box.append(el("p", "rf-gh-muted", "No releases published"));
      return box;
    }

    const latest = el("div", "rf-gh-release");
    box.append(latest);
    RF.apiGet(`/repos/${r.owner}/${r.name}/releases/latest`).then((rel) => {
      const a = el("a", "rf-gh-release-link");
      a.href = rel.html_url || `${repoPath}/releases/tag/${encodeURIComponent(rel.tag_name)}`;
      a.append(icon("tag"));
      const body = el("div");
      const title = el("div", "rf-gh-release-title");
      title.append(el("strong", null, rel.name || rel.tag_name), el("span", "rf-gh-latest", "Latest"));
      const when = document.createElement("relative-time");
      when.setAttribute("datetime", rel.published_at || rel.created_at);
      when.setAttribute("tense", "past");
      when.textContent = new Date(rel.published_at || rel.created_at).toLocaleDateString();
      const date = el("div", "rf-gh-muted rf-gh-small");
      date.append(when);
      body.append(title, date);
      a.append(body);
      latest.append(a);
      const n = parseInt(String(count).replace(/[.,]/g, ""), 10);
      if (n > 1) {
        const more = el("a", "rf-gh-more", `+ ${n - 1} release${n - 1 === 1 ? "" : "s"}`);
        more.href = tab.getAttribute("href");
        box.append(more);
      }
    }).catch(() => latest.remove());
    return box;
  }

  function packagesSection(repoPath) {
    const tab = document.querySelector(`a.item[href="${repoPath}/packages"]`);
    const count = tab && countFrom(tab.querySelector(".label"));
    if (!tab || !count) return null;
    const box = el("section", "rf-gh-box");
    const h = el("h2", "rf-gh-h2");
    const a = el("a", "rf-gh-h2-link", "Packages");
    a.href = tab.getAttribute("href");
    a.append(el("span", "rf-gh-counter", count));
    h.append(a);
    box.append(h);
    return box;
  }

  function languagesSection(container) {
    const items = [...container.querySelectorAll(".repository-summary #language-stats li")].map((li) => ({
      color: li.querySelector(".color-icon")?.style.backgroundColor || "#ccc",
      name: li.querySelector("span")?.textContent.trim() ?? "",
      pct: (li.textContent.match(/([\d.]+)\s*%/) || [])[1],
    })).filter((x) => x.name && x.pct);
    if (!items.length) return null;

    const box = el("section", "rf-gh-box");
    box.append(el("h2", "rf-gh-h2", "Languages"));
    const bar = el("div", "rf-gh-langbar");
    for (const l of items) {
      const s = el("span", "rf-gh-langbar-slice");
      s.style.width = `${l.pct}%`;
      s.style.backgroundColor = l.color;
      s.title = `${l.name} ${l.pct}%`;
      bar.append(s);
    }
    const list = el("ul", "rf-gh-langs");
    for (const l of items) {
      const item = el("li");
      const dot = el("span", "rf-gh-langdot");
      dot.style.backgroundColor = l.color;
      item.append(dot, el("strong", null, l.name), el("span", "rf-gh-muted", `${l.pct}%`));
      list.append(item);
    }
    box.append(bar, list);
    return box;
  }

  // --- main column tweaks ----------------------------------------------------
  function moveCounts(container, main) {
    const menu = container.querySelector(".repository-summary .repository-menu");
    if (!menu) return;
    const row = main.querySelector(".repo-button-row");
    const branches = menu.querySelector("a[href$='/branches']");
    const tags = menu.querySelector("a[href$='/tags']");
    if (row && (branches || tags)) {
      const box = el("div", "rf-gh-refcounts");
      for (const [a, iconName] of [[branches, "git-branch"], [tags, "tag"]]) {
        if (!a) continue;
        const n = a.querySelector("b")?.textContent.trim();
        const word = a.textContent.replace(/\s+/g, " ").trim().replace(/^[\d.,]+\s*/, "");
        box.append(link(a.getAttribute("href"), iconName, el("strong", null, n), ` ${word}`));
      }
      // after the branch dropdown (first child of the row)
      const first = row.firstElementChild;
      if (first) first.after(box); else row.prepend(box);
    }
    const commits = menu.querySelector("a[href*='/commits/']");
    const latest = main.querySelector(".latest-commit");
    if (commits && latest) {
      const n = commits.querySelector("b")?.textContent.trim();
      const a = link(commits.getAttribute("href"), "history", el("strong", null, n), " Commits");
      a.classList.add("rf-gh-commits");
      // GitHub puts "N Commits" at the right end of the latest-commit row, next to the time.
      // Newer Forgejo: <thead><tr><th>…</th><th class="… age"> ; older: <td>.
      const right = latest.closest("tr")?.querySelector(":is(th, td).age, :is(th, td).right");
      if (right) right.prepend(a);
      else latest.append(a);
    }
  }

  // --- assemble ----------------------------------------------------------------
  function build() {
    const container = document.querySelector(".page-content.repository > .ui.container");
    if (!container || container.hasAttribute("data-rf-gh")) return;
    // Only the repository root page has the summary bar.
    const summary = container.querySelector(":scope > .repository-summary");
    const files = container.querySelector(":scope > #repo-files-table");
    if (!summary || !files) return;
    const r = RF.repo();
    if (!r) return;
    container.setAttribute("data-rf-gh", "");

    const layout = el("div", "rf-gh-layout");
    const main = el("div", "rf-gh-main");
    const side = el("aside", "rf-gh-side");
    side.setAttribute("aria-label", "About this repository");

    // Build the sidebar first: it reads from nodes that are about to move.
    const sections = [
      aboutSection(container, r.path),
      releasesSection(r.path, r),
      packagesSection(r.path),
      languagesSection(container),
    ].filter(Boolean);
    side.append(...sections);

    // Everything from the branch row down goes into the main column.
    const start = container.querySelector(":scope > .repo-button-row") || files;
    let n = start;
    const moving = [];
    while (n) { moving.push(n); n = n.nextElementSibling; }
    summary.before(layout);
    main.append(...moving);
    layout.append(main, side);

    moveCounts(container, main);
    summary.classList.add("rf-gh-hidden");
    document.documentElement.classList.add("rf-gh-on");
  }

  RF.register({
    id: "repo-home-layout",
    phase: "first",
    scan(root) {
      if (root === document) build();
    },
  });
})();
