/* GT7 pit wall.

   Three streams arrive on one socket at different rates, because they change
   at different rates: `frame` at 60 Hz (current state), `stint` at 2 Hz (lap
   history, fuel projection, callouts) and `link` at 4 Hz (connection health).
   Live values are stored and painted on requestAnimationFrame; stint state is
   painted on arrival, since twice a second is already slower than the display.

   The lap table and the radio list are rebuilt only when their contents
   actually change, so a two-hour stint does not re-render 24 table rows 7000
   times for nothing. */

const $ = (id) => document.getElementById(id);
const SPARK = "▁▂▃▄▅▆▇█";

let liveFrame = null;
let paintedId = -1;
let seenCallouts = new Set();
let lastLapPainted = -1;
let linkState = null;

/* ---- small helpers ----------------------------------------------------- */

function lapTime(ms) {
  if (ms === null || ms === undefined || ms < 0) return "—:——.———";
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return `${m}:${String(s).padStart(2, "0")}.${String(ms % 1000).padStart(3, "0")}`;
}

function clock(ms) {
  if (ms === null || ms === undefined) return "—:——";
  const total = Math.floor(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/* Map a series onto block characters. Scaled to the series' own range, so a
   stint that only moves three degrees still shows its shape. */
function sparkline(values) {
  if (!values.length) return "";
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo;
  return values.map((v) => {
    const level = span < 0.5 ? 3 : Math.round(((v - lo) / span) * (SPARK.length - 1));
    return SPARK[Math.max(0, Math.min(SPARK.length - 1, level))];
  }).join("");
}

function tempClass(temp) {
  if (temp < 65) return "temp-cold";
  if (temp < 100) return "temp-good";
  return "temp-hot";
}

function deltaClass(ms) {
  if (ms === null) return "delta-near";
  const s = ms / 1000;
  if (s <= 0) return "delta-best";
  if (s < 0.5) return "delta-near";
  if (s < 1.5) return "delta-off";
  return "delta-far";
}

/* Steering is judged against the driver's own median, never a fixed number:
   a lap of the Nordschleife has far more corners than a lap of a short
   circuit, so an absolute threshold would be meaningless. */
function steerClass(lap, laps) {
  const rate = lap.corrections_per_minute;
  if (rate == null) return "count-none";
  const others = laps
    .filter((l) => l.number !== lap.number && l.corrections_per_minute != null)
    .map((l) => l.corrections_per_minute)
    .sort((a, b) => a - b);
  if (others.length < 2) return "count-zero";
  const median = others[Math.floor(others.length / 2)];
  if (rate > median * 1.4) return "count-many";
  if (rate > median * 1.15) return "count-some";
  return "count-zero";
}

function countClass(n, warn, bad) {
  if (n >= bad) return "count-many";
  if (n >= warn) return "count-some";
  return "count-zero";
}

/* ---- segment bars (the only live meters the engineer needs) ------------- */

function buildBar(el, count) {
  const frag = document.createDocumentFragment();
  for (let i = 0; i < count; i += 1) frag.appendChild(document.createElement("i"));
  el.replaceChildren(frag);
  el._lit = 0;
}
function setBar(el, fraction) {
  const cells = el.children;
  const lit = Math.max(0, Math.min(cells.length, Math.round(fraction * cells.length)));
  if (lit === el._lit) return;
  if (lit > el._lit) for (let i = el._lit; i < lit; i += 1) cells[i].classList.add("on");
  else for (let i = lit; i < el._lit; i += 1) cells[i].classList.remove("on");
  el._lit = lit;
}
for (const bar of document.querySelectorAll(".segbar")) buildBar(bar, Number(bar.dataset.segments));

/* ---- elements ---------------------------------------------------------- */

const el = {
  car: $("hd-car"), lap: $("hd-lap"), elapsed: $("hd-elapsed"), pos: $("hd-pos"),
  clock: $("hd-clock"), daylight: $("hd-daylight"),
  linkState: $("link-state"), linkRate: $("link-rate"), linkFmt: $("link-fmt"),
  calls: $("calls"), callsEmpty: $("calls-empty"),
  lapRows: $("lap-rows"), lapsEmpty: $("laps-empty"), stintCount: $("stint-count"),
  steerNote: $("steer-note"),
  fuTank: $("fu-tank"), fuBurn: $("fu-burn"), fuLaps: $("fu-laps"),
  fuTogo: $("fu-togo"), fuVerdict: $("fu-verdict"),
  tyFr: $("ty-fr"), tyLr: $("ty-lr"),
  paConsistency: $("pa-consistency"), paTrend: $("pa-trend"),
  rcPos: $("rc-pos"), rcCars: $("rc-cars"), rcNet: $("rc-net"), rcMoves: $("rc-moves"),
  speed: $("nw-speed"), gear: $("nw-gear"), rpm: $("nw-rpm"), grip: $("nw-grip"),
  boost: $("nw-boost"), best: $("nw-best"),
  throttle: $("bar-throttle"), brake: $("bar-brake"),
  steerWrap: $("nw-steer-wrap"), steerDot: $("nw-steer"),
  mapState: $("map-state"), mapLen: $("map-len"), fault: $("fault"), pit: $("pit"),
  deltaState: $("delta-state"), deltaTotal: $("delta-total"), deltaWorst: $("delta-worst"),
  mapRotate: $("map-rotate"), mapFlip: $("map-flip"),
  mapRename: $("map-rename"), mapForget: $("map-forget"),
  curtain: $("curtain"), curtainBody: $("curtain-body"),
};
const cornerEls = [...document.querySelectorAll(".corner")].map((node) => ({
  node, temp: node.querySelector(".corner-temp"), spark: node.querySelector(".spark"),
}));

/* ---- live values (60 Hz) ----------------------------------------------- */

function paintLive(t) {
  el.speed.textContent = Math.round(t.speed_kph);
  el.gear.textContent = t.gear_label;
  el.rpm.textContent = Math.round(t.rpm).toLocaleString("en-GB");
  setBar(el.throttle, t.throttle);
  setBar(el.brake, t.brake);

  // Steering exists only on format B. Hide the meter rather than pinning it
  // to centre, which would read as "the driver is going straight".
  if (t.steering === null || t.steering === undefined) {
    el.steerWrap.hidden = true;
  } else {
    el.steerWrap.hidden = false;
    // 0x128 saturates at exactly pi, so treat that as full lock either way.
    const fraction = Math.max(-1, Math.min(1, t.steering / Math.PI));
    el.steerDot.style.left = `${50 + fraction * 50}%`;
    el.steerDot.classList.toggle("at-lock", Math.abs(fraction) > 0.98);
  }

  el.car.textContent = t.car_code;
  el.pos.textContent = t.lap.cars > 0 ? `${t.lap.position} / ${t.lap.cars}` : "—";
  el.clock.textContent = t.environment.clock;
  el.daylight.textContent = t.environment.daylight;
  el.daylight.dataset.v = t.environment.daylight;

  el.grip.textContent = t.environment.grip_relative === null
    ? "—"
    : `${t.environment.grip_g.toFixed(2)}g · ${Math.round(t.environment.grip_relative * 100)}%`;
  el.boost.textContent = t.engine.has_turbo
    ? `${t.engine.boost_bar >= 0 ? "+" : ""}${t.engine.boost_bar.toFixed(2)}`
    : "n/a";
  el.fuTank.textContent = t.fuel.electric ? "EV" : t.fuel.level.toFixed(1);
}

let paintFault = null;

function frame() {
  try {
    if (liveFrame && liveFrame.packet_id !== paintedId) {
      paintedId = liveFrame.packet_id;
      paintLive(liveFrame);
    }
    drawMap();
    drawDelta();
  } catch (error) {
    // One bad frame must never freeze the dashboard. Before this, the
    // rAF call sat after the painting, so a single throw ended the loop
    // permanently and the screen stayed on its last good frame forever.
    reportFault(error);
  } finally {
    requestAnimationFrame(frame);
  }
}

/* Surface a paint fault instead of losing it to the console. Reported once
   per distinct message so a fault every frame cannot flood anything. */
function reportFault(error) {
  const message = `${error.name}: ${error.message}`;
  if (message === paintFault) return;
  paintFault = message;
  console.error("paint fault:", error);
  if (el.fault) {
    el.fault.textContent = message;
    el.fault.hidden = false;
  }
}
requestAnimationFrame(frame);

/* ---- stint state (2 Hz) ------------------------------------------------ */

function paintCallouts(callouts) {
  el.callsEmpty.hidden = callouts.length > 0;
  const keys = callouts.map((c) => c.key).join("|");
  if (keys === el.calls._keys) {
    // Same advice as last time - update the numbers, leave the DOM alone.
    callouts.forEach((c, i) => {
      const node = el.calls.children[i];
      if (!node) return;
      node.querySelector(".call-message").textContent = c.message;
      node.querySelector(".call-detail").textContent = c.detail;
    });
    return;
  }
  el.calls._keys = keys;

  const frag = document.createDocumentFragment();
  for (const c of callouts) {
    const li = document.createElement("li");
    li.className = `call sev-${c.severity}`;
    if (!seenCallouts.has(c.key)) li.classList.add("is-new");
    const message = document.createElement("div");
    message.className = "call-message";
    message.textContent = c.message;
    const detail = document.createElement("div");
    detail.className = "call-detail";
    detail.textContent = c.detail;
    li.append(message, detail);
    frag.appendChild(li);
  }
  el.calls.replaceChildren(frag);
  seenCallouts = new Set(callouts.map((c) => c.key));
}

function paintLaps(laps, steeringAvailable) {
  // An empty steer column is not a bug, it is format A. Say which.
  el.steerNote.textContent = steeringAvailable ? "" : "steer needs format B";
  el.lapsEmpty.hidden = laps.length > 0;
  el.stintCount.textContent = laps.length ? `${laps.length} laps recorded` : "";
  const newest = laps.length ? laps[laps.length - 1].number : -1;
  if (newest === lastLapPainted) return;
  const isFirstPaint = lastLapPainted === -1;
  lastLapPainted = newest;

  const frag = document.createDocumentFragment();
  // Newest first: the engineer reads the top of the table.
  for (const lap of [...laps].reverse()) {
    const tr = document.createElement("tr");
    tr.className = "lap-row" + (lap.is_best ? " is-best" : "");
    if (lap.number === newest && !isFirstPaint) tr.classList.add("is-new");
    const cells = [
      [String(lap.number), ""],
      [lapTime(lap.time_ms), "lap-time"],
      [lap.is_best ? "BEST" : (lap.delta_ms === null ? "—" : `+${(lap.delta_ms / 1000).toFixed(3)}`),
       deltaClass(lap.delta_ms)],
      [lap.fuel_used ? `${lap.fuel_used.toFixed(2)}` : "—", ""],
      [`${Math.round(lap.max_speed_kph)}`, ""],
      [String(lap.lockups), countClass(lap.lockups, 1, 3)],
      [String(lap.wheelspin), countClass(lap.wheelspin, 3, 6)],
      lap.steering_corrections == null
        ? ["—", "count-none"]
        : [String(lap.steering_corrections), steerClass(lap, laps)],
      [`${Math.round(lap.full_throttle_pct)}%`, ""],
    ];
    for (const [text, cls] of cells) {
      const td = document.createElement("td");
      td.textContent = text;
      if (cls) td.className = cls;
      tr.appendChild(td);
    }
    frag.appendChild(tr);
  }
  el.lapRows.replaceChildren(frag);
}

function paintFuel(stint, fuel) {
  const burn = fuel.per_lap;
  const remaining = fuel.laps_remaining;
  const toGo = stint.laps_to_go;
  const margin = fuel.margin_laps;

  el.fuBurn.textContent = burn === null ? "—" : `${burn.toFixed(2)} L`;
  el.fuLaps.textContent = remaining === null ? "—" : remaining.toFixed(1);
  el.fuTogo.textContent = toGo === null ? "—" : toGo;

  let text = "Waiting for two completed laps to measure burn.";
  let cls = "verdict";
  if (remaining === null) {
    // leave the waiting message
  } else if (margin === null) {
    text = `Fuel for ${remaining.toFixed(1)} more laps. No lap target set, so there is nothing to be short of.`;
  } else if (margin < 0) {
    const save = burn - (liveFrame ? liveFrame.fuel.level / toGo : burn);
    text = `Short by ${(-margin).toFixed(1)} laps. Save ${save.toFixed(2)} L a lap to reach the finish.`;
    cls = margin < -3 ? "verdict is-bad" : "verdict is-warn";
  } else {
    text = `${margin.toFixed(1)} laps in hand at this burn rate.`;
    cls = "verdict is-good";
  }
  el.fuVerdict.textContent = text;
  el.fuVerdict.className = cls;
}

function paintTyres(tyres) {
  const series = tyres.series || [];
  cornerEls.forEach((corner, i) => {
    const values = series[i] || [];
    const latest = values.length ? values[values.length - 1] : null;
    corner.temp.textContent = latest === null ? "—" : `${Math.round(latest)}°`;
    corner.spark.textContent = sparkline(values);
    corner.node.className = `corner ${latest === null ? "" : tempClass(latest)}`.trim();
  });

  const balance = tyres.balance;
  if (!balance) {
    el.tyFr.textContent = "—";
    el.tyLr.textContent = "—";
    return;
  }
  const fr = balance.front_rear;
  const lr = balance.left_right;
  el.tyFr.textContent = `${fr >= 0 ? "+" : ""}${fr.toFixed(1)}°`;
  el.tyFr.className = Math.abs(fr) > 12 ? "split-hot" : Math.abs(fr) > 7 ? "split-warn" : "split-ok";
  el.tyLr.textContent = `${lr >= 0 ? "+" : ""}${lr.toFixed(1)}°`;
  el.tyLr.className = Math.abs(lr) > 10 ? "split-warn" : "split-ok";
}

/* GT7 reports nothing about the pit lane; this is inferred from the limiter
   holding a speed no driver can, away from the racing line. */
function paintPits(pits) {
  if (!pits) {
    el.pit.hidden = true;
    return;
  }
  if (pits.in_pits) {
    const seconds = pits.elapsed_s === null ? "" : ` ${Math.round(pits.elapsed_s)}s`;
    el.pit.textContent = `PIT LANE${seconds}`;
    el.pit.className = "pit";
    el.pit.hidden = false;
  } else if (pits.stops > 0) {
    const last = pits.last;
    el.pit.textContent = last && last.duration_s !== null
      ? `${pits.stops} stop${pits.stops > 1 ? "s" : ""} · last ${Math.round(last.duration_s)}s`
      : `${pits.stops} stop${pits.stops > 1 ? "s" : ""}`;
    el.pit.className = "pit is-done";
    el.pit.hidden = false;
  } else {
    el.pit.hidden = true;
  }
}

function paintRace(race) {
  // Static files are served from disk, so a reloaded page can be newer than
  // the running server. Treat a missing section as "no data", not a crash.
  race = race || {};
  if (!race.position || !race.cars) {
    el.rcPos.textContent = "—";
    el.rcCars.textContent = "of —";
    el.rcNet.textContent = "Waiting for a race.";
    el.rcNet.className = "race-net";
    el.rcMoves.replaceChildren();
    return;
  }
  el.rcPos.textContent = `P${race.position}`;
  el.rcCars.textContent = `of ${race.cars}`;

  const gained = race.places_gained;
  if (gained === null || gained === 0) {
    el.rcNet.textContent = `Started P${race.start_position}. No places changed yet.`;
    el.rcNet.className = "race-net";
  } else {
    const word = gained > 0 ? "up" : "down";
    el.rcNet.textContent = `Started P${race.start_position} · ${word} ${Math.abs(gained)}`;
    el.rcNet.className = `race-net ${gained > 0 ? "is-up" : "is-down"}`;
  }

  const frag = document.createDocumentFragment();
  // Newest move first - the engineer cares what just happened.
  for (const move of [...(race.changes || [])].reverse()) {
    const li = document.createElement("li");
    const up = move.current < move.previous;
    li.className = up ? "up" : "down";
    li.textContent = `lap ${move.lap}  P${move.previous} → P${move.current}`;
    frag.appendChild(li);
  }
  el.rcMoves.replaceChildren(frag);
}

function paintStint(s) {
  el.lap.textContent = s.total_laps > 0 ? `${s.lap_number} / ${s.total_laps}` : `${s.lap_number}`;
  el.elapsed.textContent = clock(s.lap_elapsed_ms);
  el.best.textContent = lapTime(s.best_lap_ms);

  paintPits(s.pits);
  paintRace(s.race);
  paintCallouts(s.callouts);
  paintLaps(s.laps, s.steering_available);
  paintFuel(s, s.fuel);
  paintTyres(s.tyres);

  const consistency = s.pace.consistency_ms;
  el.paConsistency.textContent = consistency === null ? "—" : `${(consistency / 1000).toFixed(2)}s`;
  const trend = s.pace.trend_ms;
  if (trend === null) {
    el.paTrend.textContent = "—";
    el.paTrend.className = "";
  } else {
    el.paTrend.textContent = `${trend >= 0 ? "+" : ""}${(trend / 1000).toFixed(2)}s`;
    el.paTrend.className = trend > 300 ? "split-warn" : trend < -300 ? "" : "split-ok";
  }
}

/* ---- track map --------------------------------------------------------- */

/* The trace can run to thousands of segments, and the car dot moves at 60 Hz.
   Re-stroking the whole path every frame to move one dot is the obvious way to
   make this janky, so the path is rendered once to an offscreen canvas and
   only redrawn when points arrive or the box resizes. Each frame just blits
   that and draws the dot. */

const track = { gen: 0, x: [], z: [], s: [], closed: false, length: 0, bbox: null,
                lapNumber: 0, anchored: false, source: "live", id: null,
                name: null, lapsSeen: 0, pitLane: [] };
const mapCanvas = $("trackmap");
const mapCtx = mapCanvas.getContext("2d");
const traceCanvas = document.createElement("canvas");
let projection = null;
let traceDirty = true;

/* Orientation is purely a view choice - the engineer pictures a circuit the
   way they picture it, and no server data changes. Rotation in 90 degree steps
   plus a mirror covers all eight orientations. */
const VIEW_KEY = "gt7_map_view";
const view = loadView();

function loadView() {
  try {
    const saved = JSON.parse(localStorage.getItem(VIEW_KEY));
    if (saved && typeof saved.rotate === "number") {
      return { rotate: ((saved.rotate % 4) + 4) % 4, flip: Boolean(saved.flip) };
    }
  } catch (e) { /* corrupt or unavailable storage is not worth a broken map */ }
  return { rotate: 0, flip: false };
}

function saveView() {
  try {
    localStorage.setItem(VIEW_KEY, JSON.stringify(view));
  } catch (e) { /* private browsing - the map still works, it just forgets */ }
}

/* Map world (x, z) into view space. Applied before fitting, so the circuit
   always fills the panel whichever way round it is. */
function orient(x, z) {
  let u;
  let v;
  switch (view.rotate) {
    case 1: u = z; v = -x; break;
    case 2: u = -x; v = -z; break;
    case 3: u = -z; v = x; break;
    default: u = x; v = z;
  }
  return view.flip ? [-u, v] : [u, v];
}

const palette = getComputedStyle(document.documentElement);
const INPUT_COLOUR = [
  palette.getPropertyValue("--dim").trim() || "#59636f",   // 0 coasting
  "#7bbf57",                                               // 1 part throttle
  palette.getPropertyValue("--go").trim() || "#2fe06a",    // 2 full throttle
  palette.getPropertyValue("--hot").trim() || "#ff3b30",   // 3 braking
];
const CAR_COLOUR = palette.getPropertyValue("--cool").trim() || "#35c8ff";
const LOST_COLOUR = palette.getPropertyValue("--hot").trim() || "#ff3b30";
const GAINED_COLOUR = palette.getPropertyValue("--go").trim() || "#2fe06a";
const WARN_COLOUR = palette.getPropertyValue("--warn").trim() || "#ffb020";
const LANE_COLOUR = palette.getPropertyValue("--dim").trim() || "#59636f";

/* The pit road is drawn thin and quiet: it is context for the circuit, not
   part of a lap, and it must never read as the racing line. */
function drawPitLane(ctx, lane, project) {
  if (!lane || lane.length < 2) return;
  ctx.save();
  ctx.strokeStyle = LANE_COLOUR;
  ctx.lineWidth = 1.1;
  ctx.setLineDash([4, 3]);
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  const [x0, y0] = project(lane[0][0], lane[0][1]);
  ctx.moveTo(x0, y0);
  for (let i = 1; i < lane.length; i += 1) {
    const [x, y] = project(lane[i][0], lane[i][1]);
    ctx.lineTo(x, y);
  }
  ctx.stroke();
  ctx.restore();
}

/* Widen a bounding box to cover extra points, so a pit road that runs outside
   the circuit is not drawn off the edge of the canvas. */
function widen(bbox, points) {
  if (!points || !points.length) return bbox;
  let [minX, minZ, maxX, maxZ] = bbox;
  for (const [x, z] of points) {
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (z < minZ) minZ = z;
    if (z > maxZ) maxZ = z;
  }
  return [minX, minZ, maxX, maxZ];
}

/* Fit a world-space bounding box into a canvas, honouring the shared
   rotate/flip view so both maps always sit the same way round. */
function fitProjection(bbox, w, h, pad) {
  const [rawMinX, rawMinZ, rawMaxX, rawMaxZ] = bbox;
  let minU = Infinity, maxU = -Infinity, minV = Infinity, maxV = -Infinity;
  for (const [cx, cz] of [[rawMinX, rawMinZ], [rawMinX, rawMaxZ],
                          [rawMaxX, rawMinZ], [rawMaxX, rawMaxZ]]) {
    const [u, v] = orient(cx, cz);
    if (u < minU) minU = u;
    if (u > maxU) maxU = u;
    if (v < minV) minV = v;
    if (v > maxV) maxV = v;
  }
  const spanU = Math.max(1, maxU - minU);
  const spanV = Math.max(1, maxV - minV);
  const scale = Math.min((w - 2 * pad) / spanU, (h - 2 * pad) / spanV);
  const offX = (w - spanU * scale) / 2;
  const offY = (h - spanV * scale) / 2;
  return (x, z) => {
    const [u, v] = orient(x, z);
    return [offX + (u - minU) * scale, offY + (maxV - v) * scale];
  };
}

function onTrack(t) {
  if (t.generation !== track.gen || t.reset) {
    track.gen = t.generation;
    track.x.length = 0;
    track.z.length = 0;
    track.s.length = 0;
  }
  // Appending element by element: spreading thousands of values into push()
  // can overflow the argument stack.
  for (let i = 0; i < t.x.length; i += 1) {
    track.x.push(t.x[i]);
    track.z.push(t.z[i]);
    track.s.push(t.s[i]);
  }
  track.closed = t.closed;
  track.length = t.length;
  track.bbox = t.bbox;
  track.lapNumber = t.lap_number;
  track.anchored = t.anchored;
  track.source = t.source;
  track.id = t.track_id;
  track.name = t.name;
  track.lapsSeen = t.laps_seen;
  track.pitLane = t.pit_lane || [];
  traceDirty = true;

  el.mapLen.textContent = track.length >= 1000
    ? `${(track.length / 1000).toFixed(2)} km`
    : `${Math.round(track.length)} m`;
  // Say plainly whether this is a circuit we recognised or one still being
  // driven, so nobody reads a half-recorded trace as a saved outline.
  if (track.source === "saved") {
    el.mapState.textContent = track.lapsSeen > 1
      ? `${track.name} · ${track.lapsSeen} laps`
      : track.name;
  } else {
    el.mapState.textContent = track.closed
      ? `lap ${track.lapNumber}`
      : (track.anchored ? "recording from the line" : "recording");
  }
  el.mapState.classList.toggle("is-circuit", track.source === "saved" || track.closed);
  el.mapRename.hidden = track.source !== "saved";
  el.mapForget.hidden = track.source !== "saved";
}

/* Size a canvas to its box and return usable CSS dimensions, or null.

   The guard is on the *backing store*, not on clientWidth/clientHeight. A
   layout pixel is an integer, but multiplying by devicePixelRatio and rounding
   can still land on zero when the browser is zoomed out, and a zero-sized
   canvas makes getContext operations throw "could not create basic draw
   target" - which used to kill the whole paint loop. */
function fitCanvas(canvas, mirror) {
  const ratio = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  const dw = Math.round(w * ratio);
  const dh = Math.round(h * ratio);
  if (dw < 1 || dh < 1) return null;
  if (canvas.width !== dw || canvas.height !== dh) {
    canvas.width = dw;
    canvas.height = dh;
    if (mirror) {
      mirror.width = dw;
      mirror.height = dh;
    }
    traceDirty = true;
  }
  return { ratio, w, h };
}

function redrawTrace() {
  const ctx = traceCanvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  const w = mapCanvas.clientWidth;
  const h = mapCanvas.clientHeight;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, w, h);
  projection = null;
  if (!track.bbox || track.x.length < 2) return;

  // Both maps fit through the same helper, so a rotate or flip can never
  // leave one of them the other way round.
  const project = fitProjection(widen(track.bbox, track.pitLane), w, h, 14);
  projection = { project };
  const X = (x, z) => project(x, z)[0];
  const Y = (x, z) => project(x, z)[1];

  ctx.lineWidth = 2.4;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  // Batch by colour: one stroke per run, not one per segment.
  let current = null;
  for (let i = 1; i < track.x.length; i += 1) {
    const colour = INPUT_COLOUR[track.s[i]] || INPUT_COLOUR[0];
    if (colour !== current) {
      if (current) ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(X(track.x[i - 1], track.z[i - 1]), Y(track.x[i - 1], track.z[i - 1]));
      ctx.strokeStyle = colour;
      current = colour;
    }
    ctx.lineTo(X(track.x[i], track.z[i]), Y(track.x[i], track.z[i]));
  }
  if (current) ctx.stroke();

  drawPitLane(ctx, track.pitLane, project);

  // Start/finish. On a completed lap this is the actual line, because the
  // trace is anchored to GT7's lap counter rather than to wherever we
  // happened to connect.
  const [sx, sy] = project(track.x[0], track.z[0]);
  ctx.strokeStyle = palette.getPropertyValue("--ink").trim() || "#e8edf2";
  ctx.lineWidth = 2;
  ctx.globalAlpha = track.closed ? 0.95 : 0.45;
  ctx.beginPath();
  ctx.arc(sx, sy, 5, 0, Math.PI * 2);
  ctx.stroke();
  ctx.globalAlpha = 1;
}

function drawMap() {
  const box = fitCanvas(mapCanvas, traceCanvas);
  if (!box) return;
  const { ratio, w, h } = box;
  if (traceDirty) {
    redrawTrace();
    traceDirty = false;
  }
  mapCtx.setTransform(1, 0, 0, 1, 0, 0);
  mapCtx.clearRect(0, 0, mapCanvas.width, mapCanvas.height);
  mapCtx.drawImage(traceCanvas, 0, 0);
  mapCtx.setTransform(ratio, 0, 0, ratio, 0, 0);

  if (!projection) {
    mapCtx.fillStyle = palette.getPropertyValue("--dimmer").trim() || "#39424c";
    mapCtx.font = '11px "Azeret Mono", ui-monospace, monospace';
    mapCtx.fillText("drive to record the track", 12, h / 2);
    return;
  }
  if (!liveFrame) return;

  const [x, , z] = liveFrame.chassis.position;
  const [cx, cy] = projection.project(x, z);
  mapCtx.beginPath();
  mapCtx.arc(cx, cy, 4.5, 0, Math.PI * 2);
  mapCtx.fillStyle = CAR_COLOUR;
  mapCtx.shadowColor = CAR_COLOUR;
  mapCtx.shadowBlur = 9;
  mapCtx.fill();
  mapCtx.shadowBlur = 0;
}

function syncViewButtons() {
  el.mapRotate.textContent = `rotate ${view.rotate * 90}\u00b0`;
  el.mapFlip.classList.toggle("is-on", view.flip);
}
el.mapRotate.addEventListener("click", () => {
  view.rotate = (view.rotate + 1) % 4;
  saveView(); syncViewButtons(); traceDirty = true;
});
el.mapFlip.addEventListener("click", () => {
  view.flip = !view.flip;
  saveView(); syncViewButtons(); traceDirty = true;
});
syncViewButtons();

el.mapRename.addEventListener("click", async () => {
  if (!track.id) return;
  const name = window.prompt("Name this circuit", track.name || "");
  if (name === null) return;
  await fetch(`/api/tracks/${track.id}/name`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });
  // The next track message carries the new name; nothing to update here.
});

el.mapForget.addEventListener("click", async () => {
  if (!track.id) return;
  if (!window.confirm(`Forget ${track.name}? The outline is deleted.`)) return;
  await fetch(`/api/tracks/${track.id}`, { method: "DELETE" });
});

new ResizeObserver(() => { traceDirty = true; }).observe(mapCanvas);

/* ---- time-lost map ------------------------------------------------------ */

/* The same circuit, coloured by where the last lap gained or lost against the
   reference, with lock-ups and wheelspin marked on top. It shares the
   orientation controls with the trace map, so both stay the same way round. */

const deltaCanvas = $("deltamap");
const deltaCtx = deltaCanvas.getContext("2d");
let analysis = null;

function onAnalysis(a) {
  analysis = a;
  if (!a.available) {
    el.deltaState.textContent = a.reason;
    el.deltaState.classList.remove("is-circuit");
    el.deltaTotal.textContent = "";
    el.deltaTotal.className = "panel-note";
    el.deltaWorst.replaceChildren();
    return;
  }
  el.deltaState.textContent = `lap ${a.lap_number} vs lap ${a.reference_number}`;
  el.deltaState.classList.add("is-circuit");
  const seconds = a.total_ms / 1000;
  el.deltaTotal.textContent = `${seconds >= 0 ? "+" : ""}${seconds.toFixed(3)}s`;
  el.deltaTotal.className = `panel-note ${seconds > 0 ? "is-up" : "is-down"}`;

  const frag = document.createDocumentFragment();
  a.worst.forEach((spot, i) => {
    const li = document.createElement("li");
    const rank = document.createElement("span");
    rank.textContent = `${i + 1}.`;
    const loss = document.createElement("b");
    loss.textContent = `${(spot.ms / 1000).toFixed(2)}s`;
    const where = document.createElement("span");
    where.textContent = "lost here";
    li.append(rank, loss, where);
    frag.appendChild(li);
  });
  el.deltaWorst.replaceChildren(frag);
}

function drawDelta() {
  const box = fitCanvas(deltaCanvas);
  if (!box) return;
  const { ratio, w, h } = box;
  deltaCtx.setTransform(ratio, 0, 0, ratio, 0, 0);
  deltaCtx.clearRect(0, 0, w, h);

  if (!analysis || !analysis.available || !analysis.bbox) {
    deltaCtx.fillStyle = palette.getPropertyValue("--dimmer").trim() || "#39424c";
    deltaCtx.font = '11px "Azeret Mono", ui-monospace, monospace';
    deltaCtx.fillText(analysis ? analysis.reason : "waiting for laps", 12, h / 2);
    return;
  }

  const project = fitProjection(widen(analysis.bbox, track.pitLane), w, h, 14);
  drawPitLane(deltaCtx, track.pitLane, project);

  // Scale colour to this lap's own worst segment: an absolute scale would
  // wash out a tidy lap and saturate a scruffy one.
  let peak = 0;
  for (const ms of analysis.d) peak = Math.max(peak, Math.abs(ms));
  peak = Math.max(peak, 1);

  deltaCtx.lineWidth = 3;
  deltaCtx.lineJoin = "round";
  deltaCtx.lineCap = "round";
  for (let i = 1; i < analysis.x.length; i += 1) {
    const ms = analysis.d[i];
    const weight = Math.min(Math.abs(ms) / peak, 1);
    // Below a tenth of the worst segment the difference is noise, not driving.
    const colour = weight < 0.1
      ? (palette.getPropertyValue("--dim").trim() || "#59636f")
      : (ms > 0 ? LOST_COLOUR : GAINED_COLOUR);
    const [x0, y0] = project(analysis.x[i - 1], analysis.z[i - 1]);
    const [x1, y1] = project(analysis.x[i], analysis.z[i]);
    deltaCtx.globalAlpha = weight < 0.1 ? 0.5 : 0.45 + 0.55 * weight;
    deltaCtx.strokeStyle = colour;
    deltaCtx.beginPath();
    deltaCtx.moveTo(x0, y0);
    deltaCtx.lineTo(x1, y1);
    deltaCtx.stroke();
  }
  deltaCtx.globalAlpha = 1;

  // Lock-ups and wheelspin on top - the "why" over the "where".
  for (const [ex, ez, kind] of analysis.events) {
    const [x, y] = project(ex, ez);
    deltaCtx.beginPath();
    deltaCtx.arc(x, y, 3.5, 0, Math.PI * 2);
    deltaCtx.fillStyle = kind === 0 ? LOST_COLOUR : WARN_COLOUR;
    deltaCtx.fill();
  }

  // The car, so the engineer can tie the picture to where the driver is now.
  if (liveFrame) {
    const [cx, , cz] = liveFrame.chassis.position;
    const [x, y] = project(cx, cz);
    deltaCtx.beginPath();
    deltaCtx.arc(x, y, 4, 0, Math.PI * 2);
    deltaCtx.fillStyle = CAR_COLOUR;
    deltaCtx.fill();
  }
}

/* ---- link -------------------------------------------------------------- */

function paintLink(l, socketOpen) {
  linkState = l;
  el.linkRate.textContent = l.packet_rate.toFixed(1);
  el.linkFmt.textContent = l.format_mismatch
    ? `${l.active_format} (asked ${l.requested_format})`
    : (l.active_format || l.requested_format);

  let cls = "link";
  let text = "no telemetry";
  if (!socketOpen) {
    cls += " is-down";
    text = "server unreachable";
  } else if (l.error) {
    cls += " is-down";
    text = "telemetry port busy";
  } else if (l.connected) {
    cls += l.format_mismatch ? " is-warn" : " is-live";
    text = l.format_mismatch ? "live · format pinned" : "live";
  } else {
    cls += " is-warn";
  }
  el.linkState.className = cls;
  el.linkState.textContent = text;

  const waiting = !socketOpen || !l.connected || Boolean(l.error);
  el.curtain.hidden = !waiting;
  if (waiting) {
    if (!socketOpen) {
      el.curtainBody.textContent = "Lost the pit wall server. Retrying automatically.";
    } else if (l.error) {
      el.curtainBody.textContent = l.error;
    } else {
      el.curtainBody.textContent =
        "Start a race in GT7. The console only sends data once you are past the main menu.";
    }
  }
}

/* ---- socket ------------------------------------------------------------ */

let retryDelay = 500;

function connect() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/ws?hz=60`);

  socket.addEventListener("open", () => { retryDelay = 500; });
  socket.addEventListener("message", (event) => {
    // A malformed message must not take the socket down with it; the next
    // one is half a second away.
    try {
      const message = JSON.parse(event.data);
      if (message.type === "frame") liveFrame = message.telemetry;
      else if (message.type === "stint") paintStint(message.stint);
      else if (message.type === "track") onTrack(message.track);
      else if (message.type === "analysis") onAnalysis(message.analysis);
      else if (message.type === "link") paintLink(message.link, true);
    } catch (error) {
      reportFault(error);
    }
  });
  socket.addEventListener("close", () => {
    if (linkState) paintLink(linkState, false);
    else el.curtain.hidden = false;
    setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 5000);
  });
  socket.addEventListener("error", () => socket.close());
}
connect();
