/*
 * Sticky navbar: the top navigation bar stays at the top while scrolling.
 * Its height is measured into --rf-sticky-h so Forgejo's own sticky diff
 * toolbar / file tree / file headers sit below it instead of sliding under it,
 * and anchor links land below it.
 */
(() => {
  "use strict";

  function measure() {
    const nav = document.querySelector("#navbar");
    // Floor, not round: rounding up a fractional height (display scaling) leaves a hairline gap.
    const h = nav ? Math.floor(nav.getBoundingClientRect().height) : 0;
    document.documentElement.style.setProperty("--rf-nav-h", `${h}px`);
    document.documentElement.style.setProperty("--rf-sticky-h", `${h}px`);
  }

  RF.register({
    id: "sticky-header",
    phase: "first",
    init() {
      const nav = document.querySelector("#navbar");
      if (!nav) return;
      document.documentElement.classList.add("rf-sticky");
      measure();
      new ResizeObserver(measure).observe(nav);
    },
  });
})();
