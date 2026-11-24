/*
 * Commit trailers ("…-by: Name <email>"), in the commit list, on the single
 * commit page and in the latest-commit bar:
 *   - Co-authored-by: GitHub style — stacked avatars and
 *     "Author and Co-author" / "Author and N others".
 *   - Every other "…-by:" trailer (Reviewed-by, Signed-off-by, Acked-by,
 *     Tested-by, Reported-by, Suggested-by, Helped-by, Approved-by, …, and
 *     unknown ones): a chip per trailer type with an icon and avatars
 *     (hover for names); on the commit page a "Reviewed by  ◯ Name" list.
 *   - Signed-off-by from the author themself is hidden (DCO noise).
 */
(() => {
  "use strict";

  // Key (anything ending in "-by"), name, optional <email>.
  const TRAILER = /^[ \t]*([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*-by):[ \t]*([^<\n]*?)[ \t]*(?:<([^<>\s]+@[^<>\s]+)>)?[ \t]*$/gim;

  // Known trailers: label + Forgejo octicon. Unknown "…-by" keys get a label
  // derived from the key and the person icon.
  const KINDS = {
    "reviewed-by": ["Reviewed by", "code-review"],
    "signed-off-by": ["Signed off by", "verified"],
    "acked-by": ["Acked by", "thumbsup"],
    "tested-by": ["Tested by", "beaker"],
    "reported-by": ["Reported by", "report"],
    "suggested-by": ["Suggested by", "light-bulb"],
    "helped-by": ["Helped by", "people"],
    "approved-by": ["Approved by", "check-circle"],
    "assisted-by": ["Assisted by", "tools"],
    "requested-by": ["Requested by", "comment"],
    "mentored-by": ["Mentored by", "people"],
    "inspired-by": ["Inspired by", "heart"],
  };
  const MAX_STACK = 3; // avatars shown, author included
  const AVATAR_SIZE = 64;

  // --- MD5 (Forgejo's /avatar/{hash} route uses md5 of the lower-cased email) ---
  const K = Array.from({ length: 64 }, (_, i) => Math.floor(Math.abs(Math.sin(i + 1)) * 2 ** 32) >>> 0);
  const S = [7, 12, 17, 22, 5, 9, 14, 20, 4, 11, 16, 23, 6, 10, 15, 21];

  function md5(str) {
    const bytes = new TextEncoder().encode(str);
    const len = bytes.length;
    const nBlocks = ((len + 8) >> 6) + 1;
    const w = new Uint32Array(nBlocks * 16);
    for (let i = 0; i < len; i++) w[i >> 2] |= bytes[i] << ((i % 4) * 8);
    w[len >> 2] |= 0x80 << ((len % 4) * 8);
    w[nBlocks * 16 - 2] = len * 8;
    let a0 = 0x67452301, b0 = 0xefcdab89, c0 = 0x98badcfe, d0 = 0x10325476;
    for (let blk = 0; blk < nBlocks; blk++) {
      let A = a0, B = b0, C = c0, D = d0;
      for (let i = 0; i < 64; i++) {
        let F, g;
        if (i < 16) { F = (B & C) | (~B & D); g = i; }
        else if (i < 32) { F = (D & B) | (~D & C); g = (5 * i + 1) % 16; }
        else if (i < 48) { F = B ^ C ^ D; g = (3 * i + 5) % 16; }
        else { F = C ^ (B | ~D); g = (7 * i) % 16; }
        F = (F + A + K[i] + w[blk * 16 + g]) >>> 0;
        A = D; D = C; C = B;
        const s = S[(i >> 4) * 4 + (i % 4)];
        B = (B + ((F << s) | (F >>> (32 - s)))) >>> 0;
      }
      a0 = (a0 + A) >>> 0; b0 = (b0 + B) >>> 0; c0 = (c0 + C) >>> 0; d0 = (d0 + D) >>> 0;
    }
    return [a0, b0, c0, d0]
      .map((x) => [0, 8, 16, 24].map((s) => ((x >>> s) & 255).toString(16).padStart(2, "0")).join(""))
      .join("");
  }

  // --- parsing -------------------------------------------------------------
  /**
   * → { coAuthors: [person], groups: [{ key, label, icon, people: [person] }] }
   * person = { name, email, username } (email may be "", username null)
   */
  function parseTrailers(message) {
    const host = new URL(document.baseURI).hostname.toLowerCase();
    const groups = new Map();
    for (const m of String(message).matchAll(TRAILER)) {
      const key = m[1].toLowerCase();
      const email = (m[3] || "").trim().toLowerCase();
      const name = m[2].trim() || email;
      if (!name) continue;
      // user@noreply.<this host> is a Forgejo account on this instance.
      const [local, domain] = email.split("@");
      const username = email && domain === `noreply.${host}` ? local : null;
      if (!groups.has(key)) groups.set(key, { key, people: [], seen: new Set() });
      const g = groups.get(key);
      const id = email || name.toLowerCase();
      if (g.seen.has(id)) continue;
      g.seen.add(id);
      g.people.push({ name, email, username });
    }
    const coAuthors = groups.get("co-authored-by")?.people ?? [];
    groups.delete("co-authored-by");
    return {
      coAuthors,
      groups: [...groups.values()].map(({ key, people }) => {
        const [label, icon] = KINDS[key] ?? [
          key.replace(/-by$/, " by").replace(/-/g, " ").replace(/^./, (c) => c.toUpperCase()),
          "person",
        ];
        return { key, label, icon, people };
      }),
    };
  }

  const parseCoAuthors = (message) => parseTrailers(message).coAuthors;

  // --- Claude avatar ---------------------------------------------------------
  // Forgejo has no avatar for AI co-authors like "Claude Opus 5.5
  // <noreply@anthropic.com>". Simple original icon (terracotta tile, white
  // sparkle), inlined so it needs no web_accessible_resources or network.
  const CLAUDE_AVATAR =
    "data:image/svg+xml," +
    encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">' +
        '<rect width="32" height="32" rx="6" fill="#D97757"/>' +
        '<g stroke="#fff" stroke-width="2.6" stroke-linecap="round">' +
        '<path d="M16 6.5v19M6.5 16h19M9.3 9.3l13.4 13.4M22.7 9.3 9.3 22.7"/>' +
        "</g></svg>"
    );

  const isClaude = (name, email) =>
    /^claude\b/i.test(String(name || "").trim()) || /@anthropic\.com$/i.test(String(email || ""));

  // --- rendering -----------------------------------------------------------
  const who = (p) => (p.email ? `${p.name} <${p.email}>` : p.name);

  function avatar(co, px = 28) {
    const img = document.createElement("img");
    img.className = "ui avatar tw-align-middle rf-ca-avatar";
    img.width = img.height = px;
    img.alt = "";
    img.loading = "lazy";
    img.title = who(co);
    if (isClaude(co.name, co.email)) {
      img.src = CLAUDE_AVATAR;
      img.classList.add("rf-ca-claude");
      return img;
    }
    // Try in order: the Forgejo user's avatar, the avatar-by-email route, Forgejo's
    // default avatar. Some instances answer the email route with an error (e.g.
    // gravatar disabled and no matching user) - never leave a broken image.
    const sources = [
      co.username && RF.url(`/user/avatar/${encodeURIComponent(co.username)}/${AVATAR_SIZE}`),
      co.email && RF.url(`/avatar/${md5(co.email)}?size=${AVATAR_SIZE}`),
      RF.url("/assets/img/avatar_default.png"),
    ].filter(Boolean);
    img.addEventListener("error", () => {
      sources.shift();
      if (sources.length) img.src = sources[0];
      else img.remove(); // nothing loads: drop it rather than show a broken icon
    });
    img.src = sources[0];
    return img;
  }

  function nameNode(co) {
    if (co.username) {
      const a = document.createElement("a");
      a.className = "muted";
      a.href = RF.url(`/${encodeURIComponent(co.username)}`);
      a.textContent = co.name;
      a.title = co.email;
      return a;
    }
    const s = RF.span("rf-ca-name", co.name);
    if (co.email) s.title = co.email;
    return s;
  }

  /** Author name + username of a commit's author box (for de-duplication). */
  function authorOf(box) {
    const link = box.querySelector("a.author-wrapper, a[href]:not(.sha)");
    const img = box.querySelector("img.avatar");
    return {
      name: (link?.textContent || img?.title || "").trim().toLowerCase(),
      user: (link?.getAttribute("href") || "").split("/").filter(Boolean).pop()?.toLowerCase(),
    };
  }
  const isPerson = (p, a) =>
    p.name.toLowerCase() === a.name || (p.username && p.username.toLowerCase() === a.user);

  function trailerIcon(name) {
    const i = RF.span("rf-tr-icon");
    i.style.setProperty("--rf-icon", `url("${RF.url(`/assets/img/svg/octicon-${name}.svg`)}")`);
    i.setAttribute("aria-hidden", "true");
    return i;
  }

  /** Drop the author's own Signed-off-by; drop empty groups. */
  function visibleGroups(groups, author) {
    return groups
      .map((g) => (g.key === "signed-off-by" ? { ...g, people: g.people.filter((p) => !isPerson(p, author)) } : g))
      .filter((g) => g.people.length);
  }

  /** Compact chips for list rows: [icon ◯◯ +N] per trailer type. */
  function chips(groups) {
    const wrap = RF.span("rf-tr-chips");
    for (const g of groups) {
      const chip = RF.span(`rf-tr-chip rf-tr-${g.key}`);
      chip.title = `${g.label}:\n${g.people.map(who).join("\n")}`;
      chip.setAttribute("aria-label", `${g.label} ${g.people.map((p) => p.name).join(", ")}`);
      chip.append(trailerIcon(g.icon));
      for (const p of g.people.slice(0, 3)) chip.append(avatar(p, 16));
      if (g.people.length > 3) chip.append(RF.span("rf-tr-more", `+${g.people.length - 3}`));
      wrap.append(chip);
    }
    return wrap;
  }

  /** Full list for the single commit page: "Reviewed by  ◯ Name, ◯ Name". */
  function trailerList(groups) {
    const list = document.createElement("div");
    list.className = "rf-tr-list";
    for (const g of groups) {
      const row = document.createElement("div");
      row.className = `rf-tr-row rf-tr-${g.key}`;
      const label = RF.span("rf-tr-label");
      label.append(trailerIcon(g.icon), g.label);
      row.append(label);
      const people = RF.span("rf-tr-people");
      for (const p of g.people) {
        const person = RF.span("rf-tr-person");
        person.append(avatar(p, 20), nameNode(p));
        people.append(person);
      }
      row.append(people);
      list.append(row);
    }
    return list;
  }

  function renderChips(target, groups, place = "append") {
    if (!groups.length || target.querySelector(":scope > .rf-tr-chips, :scope + .rf-tr-chips")) return;
    const c = chips(groups);
    if (place === "after") target.after(c);
    else target.append(c);
  }

  function render(box, coAuthors) {
    if (box.hasAttribute("data-rf-ca")) return;
    box.setAttribute("data-rf-ca", "");

    const img = box.querySelector("img.avatar");
    const link = box.querySelector("a.author-wrapper, a[href]:not(.sha)");
    if (!img || !link) return;

    // Drop co-authors that are the author themself.
    const authorName = link.textContent.trim().toLowerCase();
    const authorUser = (link.getAttribute("href") || "").split("/").filter(Boolean).pop()?.toLowerCase();
    const cos = coAuthors.filter(
      (c) => c.name.toLowerCase() !== authorName && (!c.username || c.username.toLowerCase() !== authorUser)
    );
    if (!cos.length) return;

    const everyone = [img.title || link.textContent.trim(), ...cos.map((c) => c.name)];

    // Stacked avatars.
    const stack = RF.span("rf-ca-stack");
    stack.title = everyone.join(", ");
    img.before(stack);
    stack.append(img);
    for (const co of cos.slice(0, MAX_STACK - 1)) stack.append(avatar(co));
    if (cos.length > MAX_STACK - 1) stack.append(RF.span("rf-ca-more", `+${cos.length - (MAX_STACK - 1)}`));

    // "and Co-author" / "and N others"
    const names = RF.span("rf-ca-names", "and ");
    if (cos.length === 1) {
      names.append(nameNode(cos[0]));
    } else {
      const others = RF.span("rf-ca-others", `${cos.length} others`);
      others.title = cos.map((c) => c.name).join("\n");
      names.append(others);
    }
    link.after(names);
  }

  /** Commits *authored* by Claude: swap Forgejo's blank avatar for the Claude one. */
  function claudeAuthorAvatar(box) {
    if (box.hasAttribute("data-rf-claude")) return;
    box.setAttribute("data-rf-claude", "");
    const link = box.querySelector("a.author-wrapper, a[href]:not(.sha), strong");
    const img = box.querySelector("img.avatar");
    const name = (img?.title || link?.textContent || "").trim();
    if (img && isClaude(name)) {
      img.src = CLAUDE_AVATAR;
      img.removeAttribute("srcset");
      img.classList.add("rf-ca-claude");
    }
  }

  // --- where commits appear --------------------------------------------------
  function scanTables(root) {
    root.querySelectorAll("td.author").forEach((td) => {
      const box = td.querySelector(".tw-flex") || td;
      claudeAuthorAvatar(box);
      const tr = td.closest("tr");
      const body = tr?.querySelector("pre.commit-body");
      if (!body || tr.hasAttribute("data-rf-tr")) return;
      tr.setAttribute("data-rf-tr", "");
      const { coAuthors, groups } = parseTrailers(body.textContent);
      const author = authorOf(box);
      if (coAuthors.length) render(box, coAuthors);
      const shown = visibleGroups(groups, author);
      const msg = tr.querySelector("td.message .message-wrapper");
      if (shown.length && msg) renderChips(msg, shown, "after");
    });
  }

  function scanCommitPage(root) {
    if (document.querySelector("td.author")) return; // a list, not a single commit
    root.querySelectorAll("div.author").forEach(claudeAuthorAvatar);
    const body = document.querySelector(".commit-header pre.commit-body, pre.commit-body");
    if (!body) return;
    const { coAuthors, groups } = parseTrailers(body.textContent);
    root.querySelectorAll("div.author").forEach((box) => {
      if (coAuthors.length) render(box, coAuthors);
      if (box.hasAttribute("data-rf-tr")) return;
      box.setAttribute("data-rf-tr", "");
      const shown = visibleGroups(groups, authorOf(box));
      if (shown.length) box.after(trailerList(shown));
    });
  }

  async function commitMessage(owner, repo, sha) {
    const key = `rf-msg:${location.host}/${owner}/${repo}@${sha}`;
    try {
      const cached = sessionStorage.getItem(key);
      if (cached != null) return cached;
    } catch { /* ignore */ }
    const c = await RF.apiGet(`/repos/${owner}/${repo}/git/commits/${sha}`);
    const msg = c?.commit?.message ?? "";
    try { sessionStorage.setItem(key, msg); } catch { /* quota */ }
    return msg;
  }

  function scanLatestCommit(root) {
    root.querySelectorAll(".latest-commit").forEach(async (box) => {
      if (box.hasAttribute("data-rf-ca-fetch")) return;
      box.setAttribute("data-rf-ca-fetch", "");
      claudeAuthorAvatar(box);
      const href = box.querySelector('a.sha[href*="/commit/"], a[href*="/commit/"]')?.getAttribute("href") || "";
      const m = /\/([^/]+)\/([^/]+)\/commit\/([0-9a-f]{7,64})/i.exec(href);
      if (!m) return;
      try {
        const { coAuthors, groups } = parseTrailers(await commitMessage(m[1], m[2], m[3]));
        const author = authorOf(box);
        if (coAuthors.length) render(box, coAuthors);
        renderChips(box, visibleGroups(groups, author));
      } catch (err) {
        console.debug("[Refined Forgejo] co-authors:", err);
      }
    });
  }

  RF.register({
    id: "co-authors",
    scan(root) {
      const el = root === document ? document : root;
      scanTables(el);
      scanCommitPage(el);
      scanLatestCommit(el);
    },
  });

  RF.coAuthorsInternals = { md5, parseCoAuthors, parseTrailers }; // for testing
})();
