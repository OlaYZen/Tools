/* Joy-Con Color Picker front-end.
 *
 * The color math below is a line-for-line mirror of jc_color_picker/adobe_colors.py
 * (itself a port of the original AdobeColors.cs).  Keeping the two in lock-step is
 * what makes the browser preview byte-identical to what the Python backend writes
 * to the controller.  If you change one, change the other.
 */

"use strict";

/* ============================ color math ============================ */

function rnd(val) {
  // Port of the custom Round(): truncate toward zero, round half up.
  let ret = Math.trunc(val);
  const temp = Math.trunc(val * 100);
  if (temp % 100 >= 50) ret += 1;
  return ret;
}
const clamp01 = (v) => (v > 1 ? 1 : v < 0 ? 0 : v);
const clampByte = (v) => (v > 255 ? 255 : v < 0 ? 0 : v | 0);

function hslToRgb(h, s, l) {
  h = clamp01(h); s = clamp01(s); l = clamp01(l);
  const max = rnd(l * 255);
  const min = rnd((1.0 - s) * (l / 1.0) * 255);
  const q = (max - min) / 255;
  let mid;
  if (h >= 0 && h <= 1 / 6) {
    mid = rnd((h - 0) * q * 1530 + min); return [max, mid, min];
  } else if (h <= 1 / 3) {
    mid = rnd(-((h - 1 / 6) * q) * 1530 + max); return [mid, max, min];
  } else if (h <= 0.5) {
    mid = rnd((h - 1 / 3) * q * 1530 + min); return [min, max, mid];
  } else if (h <= 2 / 3) {
    mid = rnd(-((h - 0.5) * q) * 1530 + max); return [min, mid, max];
  } else if (h <= 5 / 6) {
    mid = rnd((h - 2 / 3) * q * 1530 + min); return [mid, min, max];
  } else if (h <= 1.0) {
    mid = rnd(-((h - 5 / 6) * q) * 1530 + max); return [max, min, mid];
  }
  return [0, 0, 0];
}

function rgbToHsl(r, g, b) {
  let max, min;
  if (r > g) { max = r; min = g; } else { max = g; min = r; }
  if (b > max) max = b; else if (b < min) min = b;
  const diff = max - min;
  const l = max / 255;
  const s = max === 0 ? 0 : diff / max;
  const q = diff === 0 ? 0 : 60 / diff;
  let h;
  if (max === r) h = g < b ? (360 + q * (g - b)) / 360 : (q * (g - b)) / 360;
  else if (max === g) h = (120 + q * (b - r)) / 360;
  else if (max === b) h = (240 + q * (r - g)) / 360;
  else h = 0.0;
  return { h: clamp01(h), s: clamp01(s), l: clamp01(l) };
}

const toHex = (r, g, b) =>
  ((1 << 24) + (clampByte(r) << 16) + (clampByte(g) << 8) + clampByte(b)).toString(16).slice(1).toUpperCase();

function parseHex(text) {
  text = (text || "").replace(/[^0-9a-fA-F]/g, "");
  if (text.length === 3) text = text.split("").map((c) => c + c).join("");
  text = text.padStart(6, "0").slice(0, 6);
  return [parseInt(text.slice(0, 2), 16), parseInt(text.slice(2, 4), 16), parseInt(text.slice(4, 6), 16)];
}
const css = (r, g, b) => `rgb(${r},${g},${b})`;

/* ============================ app state ============================ */

const MODES = { H: "H", S: "S", B: "B", R: "R", G: "G", U: "U" }; // U = Blue channel
const SIZE = 256;     // 2D box content size
const SLH = 256;      // slider bar height

const state = {
  // the four controller colors as {r,g,b}
  colors: { body: [50, 50, 50], buttons: [255, 255, 255], left_grip: [70, 70, 70], right_grip: [70, 70, 70] },
  old: { body: [50, 50, 50], buttons: [255, 255, 255], left_grip: [70, 70, 70], right_grip: [70, 70, 70] },
  mode: "H",
  cmode: "bodybtn",         // "bodybtn" | "grips"
  target: "primary",        // "primary" | "secondary"
  rgb: [50, 50, 50],
  hsl: { h: 0, s: 0, l: 50 / 255 },
  presets: null,
  selectedSlot: null,       // {bank, index} of a user slot
  hasGrips: true,
};

const $ = (id) => document.getElementById(id);
const box = $("box"), bctx = box.getContext("2d");
const slider = $("slider"), sctx = slider.getContext("2d");

/* which controller color key the primary/secondary picker maps to */
function targetKey(which) {
  const t = which || state.target;
  if (state.cmode === "grips") return t === "primary" ? "left_grip" : "right_grip";
  return t === "primary" ? "body" : "buttons";
}

function setColorFromRgb(r, g, b) {
  state.rgb = [r, g, b];
  state.hsl = rgbToHsl(r, g, b);
  syncCurrentTarget();
}
function setColorFromHsl(h, s, l) {
  state.hsl = { h: clamp01(h), s: clamp01(s), l: clamp01(l) };
  state.rgb = hslToRgb(h, s, l);
  syncCurrentTarget();
}
function syncCurrentTarget() {
  state.colors[targetKey()] = state.rgb.slice();
}

/* ============================ rendering ============================ */

// Color shown at box position (fx,fy in 0..1) for the current draw mode.
function boxFieldColor(fx, fy) {
  const { h, s, l } = state.hsl, [r, g, b] = state.rgb;
  switch (state.mode) {
    case "H": return hslToRgb(h, fx, 1 - fy);
    case "S": return hslToRgb(fx, s, 1 - fy);
    case "B": return hslToRgb(fx, 1 - fy, l);
    case "R": return [r, rnd(255 * (1 - fy)), rnd(255 * fx)];
    case "G": return [rnd(255 * (1 - fy)), g, rnd(255 * fx)];
    case "U": return [rnd(255 * fx), rnd(255 * (1 - fy)), b];
  }
}

// Apply a click/drag at box position (fx,fy in 0..1).
function boxApply(fx, fy) {
  const hsl = state.hsl;
  switch (state.mode) {
    case "H": setColorFromHsl(hsl.h, fx, 1 - fy); break;
    case "S": setColorFromHsl(fx, hsl.s, 1 - fy); break;
    case "B": setColorFromHsl(fx, 1 - fy, hsl.l); break;
    case "R": setColorFromRgb(state.rgb[0], rnd(255 * (1 - fy)), rnd(255 * fx)); break;
    case "G": setColorFromRgb(rnd(255 * (1 - fy)), state.rgb[1], rnd(255 * fx)); break;
    case "U": setColorFromRgb(rnd(255 * fx), rnd(255 * (1 - fy)), state.rgb[2]); break;
  }
}

// Marker position (0..1, 0..1) for the current color.
function boxMarker() {
  const { h, s, l } = state.hsl, [r, g, b] = state.rgb;
  switch (state.mode) {
    case "H": return [s, 1 - l];
    case "S": return [h, 1 - l];
    case "B": return [h, 1 - s];
    case "R": return [b / 255, 1 - g / 255];
    case "G": return [b / 255, 1 - r / 255];
    case "U": return [r / 255, 1 - g / 255];
  }
}

// Constant-component value t (0..1) shown by the slider for the current color.
function sliderValue() {
  const { h, s, l } = state.hsl, [r, g, b] = state.rgb;
  switch (state.mode) {
    case "H": return h; case "S": return s; case "B": return l;
    case "R": return r / 255; case "G": return g / 255; case "U": return b / 255;
  }
}
// Color of the slider bar at value t (t=1 top .. 0 bottom).
function sliderFieldColor(t) {
  const { h, s, l } = state.hsl, [r, g, b] = state.rgb;
  switch (state.mode) {
    case "H": return hslToRgb(t, 1, 1);
    case "S": return hslToRgb(h, t, l);
    case "B": return hslToRgb(h, s, t);
    case "R": return [rnd(255 * t), g, b];
    case "G": return [r, rnd(255 * t), b];
    case "U": return [r, g, rnd(255 * t)];
  }
}
function sliderApply(t) {
  const { h, s, l } = state.hsl, [r, g, b] = state.rgb;
  switch (state.mode) {
    case "H": setColorFromHsl(t, s, l); break;
    case "S": setColorFromHsl(h, t, l); break;
    case "B": setColorFromHsl(h, s, t); break;
    case "R": setColorFromRgb(rnd(255 * t), g, b); break;
    case "G": setColorFromRgb(r, rnd(255 * t), b); break;
    case "U": setColorFromRgb(r, g, rnd(255 * t)); break;
  }
}

function renderBox() {
  const img = bctx.createImageData(SIZE, SIZE);
  const d = img.data;
  for (let y = 0; y < SIZE; y++) {
    const fy = y / SIZE;
    for (let x = 0; x < SIZE; x++) {
      const [r, g, b] = boxFieldColor(x / SIZE, fy);
      const i = (y * SIZE + x) * 4;
      d[i] = r; d[i + 1] = g; d[i + 2] = b; d[i + 3] = 255;
    }
  }
  bctx.putImageData(img, 0, 0);
  // marker
  const [mx, my] = boxMarker();
  const px = mx * SIZE, py = my * SIZE;
  const hsl = rgbToHsl(...state.rgb);
  bctx.lineWidth = 1.5;
  bctx.strokeStyle = hsl.l < 200 / 255 ? "#fff" : "#000";
  bctx.beginPath();
  bctx.arc(px, py, 6, 0, Math.PI * 2);
  bctx.stroke();
}

function renderSlider() {
  const w = slider.width;
  const img = sctx.createImageData(w, SLH);
  const d = img.data;
  for (let y = 0; y < SLH; y++) {
    const t = 1 - y / SLH;
    const [r, g, b] = sliderFieldColor(t);
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      d[i] = r; d[i + 1] = g; d[i + 2] = b; d[i + 3] = 255;
    }
  }
  sctx.putImageData(img, 0, 0);
  // marker line
  const y = (1 - sliderValue()) * SLH;
  sctx.fillStyle = "#fff";
  sctx.strokeStyle = "#000";
  sctx.lineWidth = 1;
  sctx.beginPath();
  sctx.moveTo(0, y); sctx.lineTo(w, y); sctx.stroke();
  sctx.fillRect(0, Math.max(0, y - 1.5), w, 3);
  sctx.strokeRect(0, Math.max(0, y - 1.5), w, 3);
}

/* ============================ UI sync ============================ */

function setInput(id, val) {
  const el = $(id);
  if (document.activeElement !== el) el.value = val;
}

function refreshAll() {
  const [r, g, b] = state.rgb;
  const { h, s, l } = state.hsl;
  setInput("inH", rnd(h * 360));
  setInput("inS", rnd(s * 100));
  setInput("inB", rnd(l * 100));
  setInput("inR", r);
  setInput("inG", g);
  setInput("inU", b);
  setInput("inHex", toHex(r, g, b));

  // swatches
  $("swNewPrimary").style.background = css(...state.colors[targetKey("primary")]);
  $("swOldPrimary").style.background = css(...state.old[targetKey("primary")]);
  $("swNewSecondary").style.background = css(...state.colors[targetKey("secondary")]);
  $("swOldSecondary").style.background = css(...state.old[targetKey("secondary")]);

  renderBox();
  renderSlider();
  updateDeviceColorsView();
}

/* ============================ box & slider input ============================ */

function canvasPos(canvas, ev, h) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = (h || canvas.height) / rect.height;
  let x = (ev.clientX - rect.left) * scaleX;
  let y = (ev.clientY - rect.top) * scaleY;
  return [x, y];
}

function attachDrag(canvas, onMove, h) {
  let dragging = false;
  const handle = (ev) => {
    const [x, y] = canvasPos(canvas, ev, h);
    onMove(x, y);
  };
  canvas.addEventListener("pointerdown", (ev) => {
    dragging = true; canvas.setPointerCapture(ev.pointerId); handle(ev);
  });
  canvas.addEventListener("pointermove", (ev) => { if (dragging) handle(ev); });
  canvas.addEventListener("pointerup", () => { dragging = false; });
  canvas.addEventListener("pointercancel", () => { dragging = false; });
}

attachDrag(box, (x, y) => {
  const fx = clamp01(x / SIZE), fy = clamp01(y / SIZE);
  boxApply(fx, fy);
  refreshAll();
});
attachDrag(slider, (x, y) => {
  const t = clamp01(1 - y / SLH);
  sliderApply(t);
  refreshAll();
}, SLH);

/* ============================ numeric / hex inputs ============================ */

function commitNumeric(id) {
  const v = parseInt($(id).value, 10);
  if (Number.isNaN(v)) { refreshAll(); return; }
  const { h, s, l } = state.hsl, [r, g, b] = state.rgb;
  switch (id) {
    case "inH": setColorFromHsl(Math.min(v, 360) / 360, s, l); break;
    case "inS": setColorFromHsl(h, Math.min(v, 100) / 100, l); break;
    case "inB": setColorFromHsl(h, s, Math.min(v, 100) / 100); break;
    case "inR": setColorFromRgb(Math.min(v, 255), g, b); break;
    case "inG": setColorFromRgb(r, Math.min(v, 255), b); break;
    case "inU": setColorFromRgb(r, g, Math.min(v, 255)); break;
  }
  refreshAll();
}

["inH", "inS", "inB", "inR", "inG", "inU"].forEach((id) => {
  const el = $(id);
  el.addEventListener("input", () => commitNumeric(id));
  el.addEventListener("blur", () => commitNumeric(id));
  // mouse-wheel nudges the value, like the original tool
  el.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    const max = id === "inH" ? 360 : id === "inS" || id === "inB" ? 100 : 255;
    let v = parseInt(el.value, 10) || 0;
    v += ev.deltaY < 0 ? 1 : -1;
    if (v < 0 || v > max) return;
    el.value = v; commitNumeric(id);
  }, { passive: false });
});

$("inHex").addEventListener("input", () => {
  const t = $("inHex").value.replace(/[^0-9a-fA-F]/g, "");
  if (t.length === 6) { setColorFromRgb(...parseHex(t)); refreshAll(); }
});
$("inHex").addEventListener("blur", () => { setColorFromRgb(...parseHex($("inHex").value)); refreshAll(); });

/* ============================ mode + target radios ============================ */

document.querySelectorAll('input[name="mode"]').forEach((el) => {
  el.addEventListener("change", () => { if (el.checked) { state.mode = el.value; refreshAll(); } });
});
document.querySelectorAll('input[name="target"]').forEach((el) => {
  el.addEventListener("change", () => {
    if (!el.checked) return;
    state.target = el.value;
    setColorFromRgb(...state.colors[targetKey()]);
    refreshAll();
  });
});

/* old swatch click reverts */
$("swOldPrimary").addEventListener("click", () => {
  document.querySelector('input[name="target"][value="primary"]').checked = true;
  state.target = "primary";
  const k = targetKey();
  state.colors[k] = state.old[k].slice();
  setColorFromRgb(...state.colors[k]); refreshAll();
});
$("swOldSecondary").addEventListener("click", () => {
  document.querySelector('input[name="target"][value="secondary"]').checked = true;
  state.target = "secondary";
  const k = targetKey();
  state.colors[k] = state.old[k].slice();
  setColorFromRgb(...state.colors[k]); refreshAll();
});

/* controller mode (body/buttons vs grips) */
document.querySelectorAll('input[name="cmode"]').forEach((el) => {
  el.addEventListener("change", () => {
    if (!el.checked) return;
    state.cmode = el.value;
    const grips = state.cmode === "grips";
    $("lblPrimary").textContent = grips ? "Grip (L)" : "Body";
    $("lblSecondary").textContent = grips ? "Grip (R)" : "Buttons";
    setColorFromRgb(...state.colors[targetKey()]);
    renderPresets();
    refreshAll();
  });
});

/* ============================ eyedropper ============================ */

$("btnEyedrop").addEventListener("click", async () => {
  if (!("EyeDropper" in window)) {
    setStatus("Your browser has no EyeDropper API (try Chromium/Chrome).", "err");
    return;
  }
  try {
    const res = await new window.EyeDropper().open();
    setColorFromRgb(...parseHex(res.sRGBHex));
    refreshAll();
  } catch (_) { /* cancelled */ }
});

/* ============================ presets ============================ */

let showGrips = false;

function makeSwatchBtn(hex, tip, opts = {}) {
  const btn = document.createElement("button");
  btn.className = "swatch-btn" + (opts.empty ? " empty" : "");
  btn.style.background = "#" + hex;
  btn.title = tip || ("#" + hex);
  if (opts.onClick) btn.addEventListener("click", () => opts.onClick(btn));
  return btn;
}

function isEmptySlot(sw) { return (sw.hex || "").toUpperCase() === "505050" && !sw.tooltip; }

function renderPresets() {
  const p = state.presets;
  if (!p) return;
  $("presetRowTitle").textContent = showGrips ? "Retail Grips" : "Retail Colors";
  $("btnSwitchGrips").textContent = showGrips ? "Retail" : "Grips";

  const retailRow = $("retailRow");
  retailRow.innerHTML = "";
  const fixed = showGrips ? p.retail_grips : [...p.retail_body, ...p.retail_buttons];
  fixed.forEach((sw) => {
    retailRow.appendChild(makeSwatchBtn(sw.hex, sw.tooltip, {
      onClick: () => { setColorFromRgb(...parseHex(sw.hex)); clearSlotSelection(); refreshAll(); },
    }));
  });

  renderBank("retailUserRow", p.retail_user, "retail_user");
  renderBank("userRow", p.user, "user");
}

function renderBank(rowId, bank, bankName) {
  const row = $(rowId);
  row.innerHTML = "";
  bank.forEach((sw, idx) => {
    const empty = isEmptySlot(sw);
    const btn = makeSwatchBtn(sw.hex, sw.tooltip, {
      empty,
      onClick: (b) => selectSlot(bankName, idx, b),
    });
    btn.dataset.bank = bankName;
    btn.dataset.idx = idx;
    row.appendChild(btn);
  });
}

function clearSlotSelection() {
  state.selectedSlot = null;
  document.querySelectorAll(".swatch-btn.selected").forEach((b) => b.classList.remove("selected"));
  $("btnUpdatePreset").disabled = true;
  $("btnClearPreset").disabled = true;
}

function selectSlot(bank, idx, btn) {
  document.querySelectorAll(".swatch-btn.selected").forEach((b) => b.classList.remove("selected"));
  btn.classList.add("selected");
  state.selectedSlot = { bank, idx };
  $("btnUpdatePreset").disabled = false;
  $("btnClearPreset").disabled = false;
  // clicking a non-empty user slot also loads its color
  const sw = state.presets[bank][idx];
  if (!isEmptySlot(sw)) { setColorFromRgb(...parseHex(sw.hex)); refreshAll(); }
}

$("btnSwitchGrips").addEventListener("click", () => { showGrips = !showGrips; renderPresets(); });

$("btnUpdatePreset").addEventListener("click", () => {
  if (!state.selectedSlot) return;
  const { bank, idx } = state.selectedSlot;
  const hex = toHex(...state.rgb);
  const name = prompt("Preset name (optional):", state.presets[bank][idx].tooltip || "") || "";
  state.presets[bank][idx] = { hex, tooltip: name };
  savePresets();
  renderPresets();
});

$("btnClearPreset").addEventListener("click", () => {
  if (!state.selectedSlot) return;
  const { bank, idx } = state.selectedSlot;
  state.presets[bank][idx] = { hex: "505050", tooltip: "" };
  savePresets();
  clearSlotSelection();
  renderPresets();
});

async function savePresets() {
  try {
    await fetch("/api/presets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ retail_user: state.presets.retail_user, user: state.presets.user }),
    });
    setStatus("Presets saved to colors.xml.", "ok");
  } catch (e) { setStatus("Failed to save presets: " + e, "err"); }
}

/* ============================ device ============================ */

function setStatus(msg, kind) {
  const el = $("statusLine");
  el.textContent = msg || "";
  el.className = "status" + (kind ? " " + kind : "");
}

function applyDeviceInfo(info) {
  const pill = $("devicePill");
  pill.classList.toggle("live", info.connected && !info.mock);
  pill.classList.toggle("mock", !!info.mock);
  $("deviceName").textContent = info.name || "No controller";
  state.hasGrips = !!info.has_grips;
  // grips controls only make sense on a Pro Controller
  document.querySelectorAll(".dc.grips").forEach((e) => e.classList.toggle("hidden", !state.hasGrips));
}

function loadColors(colors) {
  if (!colors) return;
  for (const k of ["body", "buttons", "left_grip", "right_grip"]) {
    if (colors[k]) { state.colors[k] = parseHex(colors[k]); state.old[k] = parseHex(colors[k]); }
  }
  setColorFromRgb(...state.colors[targetKey()]);
}

function updateDeviceColorsView() {
  const c = state.colors;
  const set = (id, key) => {
    const el = $(id);
    el.textContent = "#" + toHex(...c[key]);
    el.parentElement.style.setProperty("--swatch", css(...c[key]));
  };
  set("dcBody", "body"); set("dcButtons", "buttons");
  set("dcLeft", "left_grip"); set("dcRight", "right_grip");
}

$("btnRead").addEventListener("click", async () => {
  setStatus("Reading from controller…");
  try {
    const r = await fetch("/api/device/read", { method: "POST" });
    const j = await r.json();
    if (j.colors) { loadColors(j.colors); refreshAll(); setStatus("Read OK.", "ok"); }
    else setStatus(j.error || "Read failed.", "err");
  } catch (e) { setStatus("Read failed: " + e, "err"); }
});

$("btnWrite").addEventListener("click", async () => {
  const payload = {};
  for (const k of ["body", "buttons", "left_grip", "right_grip"]) payload[k] = toHex(...state.colors[k]);
  setStatus("Writing to controller…");
  try {
    const r = await fetch("/api/device/write", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ colors: payload }),
    });
    const j = await r.json();
    if (j.ok) {
      loadColors(j.colors); refreshAll();
      setStatus("Colors written to the controller.", "ok");
    } else setStatus(j.error || "Write failed.", "err");
  } catch (e) { setStatus("Write failed: " + e, "err"); }
});

$("btnReconnect").addEventListener("click", async () => {
  setStatus("Scanning…");
  try {
    const r = await fetch("/api/device/connect", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    const info = await r.json();
    applyDeviceInfo(info);
    setStatus(info.mock ? "No controller found — using mock device." : "Connected: " + info.name, info.mock ? "" : "ok");
    const cr = await fetch("/api/device/read", { method: "POST" });
    const cj = await cr.json();
    if (cj.colors) { loadColors(cj.colors); refreshAll(); }
  } catch (e) { setStatus("Scan failed: " + e, "err"); }
});

/* ============================ boot ============================ */

async function boot() {
  try {
    const r = await fetch("/api/state");
    const s = await r.json();
    state.presets = s.presets;
    applyDeviceInfo(s.device || {});
    if (s.colors) loadColors(s.colors);
    renderPresets();
    if (s.device && s.device.mock) {
      setStatus("Mock device active — colors are simulated. Connect a controller and click ⟳.");
    }
  } catch (e) {
    setStatus("Could not reach the backend: " + e, "err");
  }
  // default selection: H mode, primary target
  state.mode = "H";
  setColorFromRgb(...state.colors[targetKey()]);
  refreshAll();
}

boot();
