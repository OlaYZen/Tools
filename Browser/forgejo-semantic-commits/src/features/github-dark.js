/*
 * GitHub dark colours — fallback for custom theme names that early-theme.js
 * can't recognise at document_start: once styles are loaded, Forgejo/Gitea
 * dark themes expose --is-dark-theme: true.
 */
(() => {
  "use strict";

  const COLOR_BLIND = /deuteranopia|protanopia|tritanopia/;

  function check() {
    const html = document.documentElement;
    const dark = getComputedStyle(html).getPropertyValue("--is-dark-theme").trim() === "true";
    html.classList.toggle("rf-ghdark", dark);
    html.classList.toggle("rf-ghdark-cb", dark && COLOR_BLIND.test(html.getAttribute("data-theme") || ""));
  }

  RF.register({
    id: "github-dark",
    phase: "first",
    init() {
      // --is-dark-theme must be read without our override class interfering;
      // it is a theme flag, not a colour, so our CSS never changes it.
      check();
      matchMedia("(prefers-color-scheme: dark)").addEventListener("change", check);
    },
  });
})();
