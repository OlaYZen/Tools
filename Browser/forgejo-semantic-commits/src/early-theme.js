/*
 * GitHub dark colours — runs at document_start so the palette is applied
 * before the first paint (no flash of Forgejo colours).
 *
 * At document_start only <html data-theme="…"> is known, so this only acts
 * on Forgejo/Gitea/Codeberg built-in theme names. Custom theme names are
 * picked up later by the "github-dark" feature in the main bundle, which can
 * read the theme's --is-dark-theme variable once styles have loaded.
 */
(() => {
  "use strict";

  const api = globalThis.browser ?? globalThis.chrome;
  const html = document.documentElement;
  if (!html) return;

  const BUILTIN = /^(forgejo|gitea|codeberg)-|^arc-green$/;
  const COLOR_BLIND = /deuteranopia|protanopia|tritanopia/;

  function isDarkByName(name) {
    if (/dark|arc-green/.test(name)) return true;
    if (/auto/.test(name)) return matchMedia("(prefers-color-scheme: dark)").matches;
    return false;
  }

  function apply(name, dark) {
    html.classList.toggle("rf-ghdark", dark);
    html.classList.toggle("rf-ghdark-cb", dark && COLOR_BLIND.test(name));
  }

  const name = html.getAttribute("data-theme") || "";
  if (!BUILTIN.test(name)) return;

  // Apply immediately (before storage answers) to avoid a flash; undo if disabled.
  apply(name, isDarkByName(name));
  if (/auto/.test(name)) {
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => apply(name, isDarkByName(name)));
  }

  try {
    api.storage.sync.get({ "feature:github-dark": true }).then(
      (s) => { if (s["feature:github-dark"] === false) apply(name, false); },
      () => {}
    );
  } catch { /* storage unavailable: keep it on */ }
})();
