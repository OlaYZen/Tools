/*
 * Coloured relative times. Two schemes (options page):
 *
 *  - "heat" (default): smooth gradient (data-rf-heat + --rf-heat: 0–100 %)
 *    from green (< 1 hour) to orange ("6 months ago"), then muted + dimmed
 *    past that (data-rf-dim="1") and past 12 months ("2").
 *  - "freshness": age buckets (data-rf-age): minutes/hours green, days amber,
 *    weeks default, months/years faded.
 *
 * Re-evaluated every minute so colours follow the "x ago" text.
 */
(() => {
  "use strict";

  const SELECTOR = "relative-time[datetime], time[datetime]";
  const MIN = 60e3, HOUR = 60 * MIN, DAY = 24 * HOUR, MONTH = 30 * DAY;

  // --- heat: smooth green → orange gradient over 6 months ---
  // < 1 hour is pure green; then the colour moves continuously towards
  // orange, reaching it at "6 months ago". A square-root curve makes the
  // fade slow and even-looking: roughly
  //   1 day 6 % · 1 week 17 % · 1 month 37 % · 3 months 64 % · 6 months 97 %
  // Older: muted, dimmed (80 %, 60 % past a year).
  const HEAT_MIN = HOUR;
  // Forgejo floors calendar months, so "6 months ago" lasts until 7 calendar
  // months (~213 days). Keep everything that reads "6 months ago" coloured.
  const HEAT_MAX = 7 * 30.44 * DAY;

  /** 0 (green) … 100 (orange), one decimal. */
  function heatPercent(age) {
    if (age < HEAT_MIN) return 0;
    const linear = (age - HEAT_MIN) / (HEAT_MAX - HEAT_MIN);
    return Math.round(Math.sqrt(Math.min(1, linear)) * 1000) / 10;
  }

  // --- freshness buckets ---
  const BUCKETS = [
    [HOUR, "minutes"],
    [DAY, "hours"],
    [7 * DAY, "days"],
    [30 * DAY, "weeks"],
    [365 * DAY, "months"],
    [Infinity, "years"],
  ];

  function setData(el, key, value) {
    if (value == null) {
      if (key in el.dataset) delete el.dataset[key];
    } else if (el.dataset[key] !== value) {
      el.dataset[key] = value;
    }
  }

  let scheme = "heat";

  function tag(el, now) {
    const t = Date.parse(el.getAttribute("datetime"));
    if (Number.isNaN(t)) return;
    const age = Math.max(0, now - t); // future timestamps (clock skew) count as fresh

    if (scheme === "freshness") {
      setData(el, "rfAge", BUCKETS.find(([limit]) => age < limit)[1]);
      return;
    }
    if (age > HEAT_MAX) {
      setData(el, "rfHeat", null);
      el.style.removeProperty("--rf-heat");
      setData(el, "rfDim", age > 12 * MONTH ? "2" : "1");
    } else {
      setData(el, "rfDim", null);
      setData(el, "rfHeat", "");
      const pct = `${heatPercent(age)}%`;
      if (el.style.getPropertyValue("--rf-heat") !== pct) el.style.setProperty("--rf-heat", pct);
    }
  }

  function scan(root) {
    const now = Date.now();
    if (root.matches?.(SELECTOR)) tag(root, now);
    root.querySelectorAll(SELECTOR).forEach((el) => tag(el, now));
  }

  RF.register({
    id: "time-colors",
    phase: "late",
    init(settings) {
      scheme = settings.timeColorScheme === "freshness" ? "freshness" : "heat";
      document.documentElement.classList.add(`rf-tc-${scheme}`);
      setInterval(() => scan(document), MIN);
    },
    scan,
  });
})();
