/*
 * Click any "x ago" to switch every date on the page between relative and
 * absolute (2026-11-04 13:13). The choice is remembered per Forgejo site.
 */
(() => {
  "use strict";

  const KEY = "rf-absolute-dates";
  const ON_CLASS = "rf-abs-on";

  // Local time, unambiguous across locales: 2026-11-04 13:13
  const pad = (n) => String(n).padStart(2, "0");
  const fmt = {
    format: (t) => {
      const d = new Date(t);
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    },
  };

  function load() {
    try { return localStorage.getItem(KEY) === "1"; } catch { return false; }
  }
  function save(on) {
    try { localStorage.setItem(KEY, on ? "1" : "0"); } catch { /* ignore */ }
  }

  function apply(on) {
    document.documentElement.classList.toggle(ON_CLASS, on);
  }

  function addAbsolute(rel) {
    if (rel.hasAttribute("data-rf-abs")) return;
    rel.setAttribute("data-rf-abs", "");
    const t = Date.parse(rel.getAttribute("datetime"));
    if (Number.isNaN(t)) return;
    // A <time datetime> so the time-colors feature colours it too.
    const abs = document.createElement("time");
    abs.className = "rf-abs-date";
    abs.setAttribute("datetime", rel.getAttribute("datetime"));
    abs.textContent = fmt.format(t);
    abs.title = "Click to show relative dates";
    rel.after(abs);
  }

  function onClick(e) {
    const hit = e.target instanceof Element && e.target.closest("relative-time, .rf-abs-date");
    if (!hit) return;
    e.preventDefault();
    e.stopPropagation();
    const on = !document.documentElement.classList.contains(ON_CLASS);
    apply(on);
    save(on);
  }

  RF.register({
    id: "absolute-dates",
    phase: "late",
    init() {
      apply(load());
      document.addEventListener("click", onClick, true);
    },
    scan(root) {
      if (root.matches?.("relative-time[datetime]")) addAbsolute(root);
      root.querySelectorAll("relative-time[datetime]").forEach(addAbsolute);
    },
  });
})();
