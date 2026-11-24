/*
 * Refined Forgejo — core.
 * Loads settings, detects Forgejo/Gitea, runs enabled features on the page and
 * on anything added later (htmx swaps, expanded sections …).
 */
var RF = (() => {
  "use strict";

  const api = globalThis.browser ?? globalThis.chrome;
  const features = [];

  function register(feature) {
    features.push(feature);
  }

  function span(className, text) {
    const s = document.createElement("span");
    s.className = className;
    if (text != null) s.textContent = text;
    return s;
  }

  function parseHosts(text) {
    return String(text || "")
      .split(/[\s,]+/)
      .map((h) => h.trim().toLowerCase())
      .filter(Boolean);
  }

  // Sub-path Forgejo is served from ("" or e.g. "/git"), read from window.config.
  let appSubUrl = "";

  function looksLikeForgejo() {
    // Every Forgejo/Gitea page boots with an inline `window.config = { appSubUrl: … }`.
    for (const s of document.querySelectorAll("script:not([src])")) {
      const t = s.textContent;
      if (t.includes("window.config") && t.includes("appSubUrl")) {
        const m = /appSubUrl\s*:\s*['"]([^'"]*)['"]/.exec(t);
        if (m) appSubUrl = m[1].replace(/\/$/, "");
        return true;
      }
    }
    const meta = [...document.querySelectorAll(
      'meta[name="author"], meta[name="keywords"], meta[name="description"], meta[name="generator"]'
    )].map((m) => (m.content || "").toLowerCase()).join(" ");
    return /forgejo|gitea/.test(meta);
  }

  /** Absolute URL for a path on this Forgejo instance ("/api/v1/…" → "https://host/sub/api/v1/…"). */
  function url(path) {
    return new URL(appSubUrl + path, document.baseURI).href;
  }

  /** Current repo from the repo header, e.g. { owner, name, path: "/owner/name" } (path includes sub-URL). */
  function repo() {
    const a = document.querySelector(".repo-header .flex-item-title a:last-of-type, .repo-title a:last-of-type");
    const href = a?.getAttribute("href");
    if (!href) return null;
    const parts = href.slice(appSubUrl.length).split("/").filter(Boolean);
    if (parts.length < 2) return null;
    return { owner: parts[0], name: parts[1], path: href.replace(/\/$/, "") };
  }

  // content.fetch runs as the page (same-origin, page cookies) in Firefox; elsewhere fall back to fetch.
  const pageFetch = globalThis.content?.fetch
    ? (...a) => globalThis.content.fetch(...a)
    : (...a) => globalThis.fetch(...a);

  /** GET a Forgejo API path as the signed-in user. */
  async function apiGet(path) {
    const res = await pageFetch(url(`/api/v1${path}`), { credentials: "same-origin", headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error(`${res.status} ${path}`);
    // Parse here rather than res.json() so we get plain objects, not page-realm wrappers.
    return JSON.parse(await res.text());
  }

  /** GET any same-site URL (e.g. an href from the page) as text. */
  async function fetchText(href) {
    const res = await pageFetch(new URL(href, document.baseURI).href, { credentials: "same-origin" });
    if (!res.ok) throw new Error(`${res.status} ${href}`);
    return res.text();
  }

  /** Brief message at the bottom of the screen. */
  function toast(message) {
    const t = span("rf-toast", message);
    document.body.append(t);
    setTimeout(() => t.remove(), 2200);
  }

  function isTyping(e) {
    const t = e.target;
    return t instanceof Element && (t.closest("input, textarea, select, [contenteditable=''], [contenteditable='true']") != null);
  }

  function defaults() {
    const d = { showScope: true, botUsers: "", timeColorScheme: "heat", extraHosts: "", disabledHosts: "" };
    for (const f of RF_FEATURES) d[`feature:${f.id}`] = f.default;
    return d;
  }

  function safely(feature, fn) {
    try {
      fn();
    } catch (err) {
      console.error(`[Refined Forgejo] ${feature.id}:`, err);
    }
  }

  async function start() {
    let settings = defaults();
    try {
      settings = { ...settings, ...(await api.storage.sync.get(settings)) };
    } catch {
      /* storage unavailable: keep defaults */
    }

    const host = location.hostname.toLowerCase();
    if (parseHosts(settings.disabledHosts).includes(host)) return;
    if (!parseHosts(settings.extraHosts).includes(host) && !looksLikeForgejo()) return;

    const active = features.filter((f) => settings[`feature:${f.id}`] !== false);

    // Phases: "first" = page structure (layout, theme) before anything else,
    // "normal" = labels/co-authors/etc. right after, "late" = cosmetic polish
    // (date colours, absolute dates) in idle time so it never delays the rest.
    const PHASES = ["first", "normal", "late"];
    const phaseOf = (f) => (PHASES.includes(f.phase) ? f.phase : "normal");
    const inPhase = (p) => active.filter((f) => phaseOf(f) === p);

    // Per-feature timing: localStorage.setItem("rf-debug", "1") and reload.
    let debug = false;
    try { debug = localStorage.getItem("rf-debug") === "1"; } catch { /* ignore */ }
    const timed = (f, what, fn) => {
      if (!debug) return safely(f, fn);
      const t0 = performance.now();
      safely(f, fn);
      const ms = performance.now() - t0;
      if (ms >= 0.5) console.debug(`[Refined Forgejo] ${f.id} ${what}: ${ms.toFixed(1)} ms`);
    };

    const idle = (fn) =>
      (globalThis.requestIdleCallback ? requestIdleCallback(fn, { timeout: 700 }) : setTimeout(fn, 50));

    const runPhase = (p, root) => {
      for (const f of inPhase(p)) {
        if (root === document && f.init) timed(f, "init", () => f.init(settings));
        if (f.scan) timed(f, "scan", () => f.scan(root, settings));
      }
    };

    const t0 = performance.now();
    runPhase("first", document);
    runPhase("normal", document);
    idle(() => {
      runPhase("late", document);
      if (debug) console.debug(`[Refined Forgejo] all phases done ${(performance.now() - t0).toFixed(1)} ms after start`);
    });

    const scanAll = (root) => {
      for (const f of active) if (f.scan && phaseOf(f) !== "late") timed(f, "scan+", () => f.scan(root, settings));
      const late = inPhase("late");
      if (late.length) idle(() => { for (const f of late) if (f.scan && root.isConnected) timed(f, "scan+", () => f.scan(root, settings)); });
    };

    let pending = [];
    let scheduled = false;
    new MutationObserver((mutations) => {
      for (const mu of mutations) {
        for (const n of mu.addedNodes) {
          if (n.nodeType === Node.ELEMENT_NODE && !n.className?.toString().startsWith("rf-")) pending.push(n);
        }
      }
      if (pending.length && !scheduled) {
        scheduled = true;
        requestAnimationFrame(() => {
          const nodes = pending;
          pending = [];
          scheduled = false;
          for (const n of nodes) if (n.isConnected) scanAll(n);
        });
      }
    }).observe(document.body, { childList: true, subtree: true });
  }

  return { api, register, span, start, url, repo, apiGet, fetchText, toast, isTyping };
})();
