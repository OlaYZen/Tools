import { renderController } from './controllers.js';
import { detectBrand, prettyName, buttonName, buttonGlyph, triggerNames, getPads, parseIds } from './gamepad.js';
import { HID_FILTERS, DS_EXTRA, createHidPad, hidSupported } from './hid.js';
import { RumbleEngine } from './rumble.js';
import { Motion } from './motion.js';
import { LineGraph, StickView } from './charts.js';

const $ = (id) => document.getElementById(id);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const pct = (v) => `${Math.round(v * 100)}%`;

// ------------------------------------------------------------------ state
const state = {
  selected: null, // gamepad index
  styleOverride: 'auto',
  brand: null,
  renderedBrand: null,
  prevButtons: {}, // key -> down (key = standard index, or 'x-…' for HID-only buttons)
  btnCounts: {},
  cells: new Map(), // key -> grid cell
  tested: new Map(), // pad id -> Set
  gridFor: null,
  rawFor: null,
  lastTs: 0, tsCount: 0, tsT: performance.now(), pollHz: 0,
  trig: [newTrig(), newTrig()],
  parallax: [0, 0],
  hid: null,
  lastInput: '',
  comboArmed: true,
};
function newTrig() { return { peak: 0, minStep: 1, presses: 0, down: false, full: false }; }

const motion = new Motion();
const stickL = new StickView($('stickL'), 'LEFT');
const stickR = new StickView($('stickR'), 'RIGHT');
const trigGraph = new LineGraph($('trigGraph'), { series: ['--accent', '#fbbd23'], min: 0, max: 1, labels: ['L', 'R'] });
const gyroGraph = new LineGraph($('gyroGraph'), { series: ['#ff6b7d', '#5fd068', '#6aa4ff'], min: -100, max: 100, auto: true, labels: ['pitch', 'yaw', 'roll'], unit: '°/s' });
const accelGraph = new LineGraph($('accelGraph'), { series: ['#ff6b7d', '#5fd068', '#6aa4ff'], min: -2, max: 2, labels: ['x', 'y', 'z'], unit: 'g' });

const currentPad = () => {
  const pads = getPads();
  return pads.find((p) => p.index === state.selected) || pads[0] || null;
};

const rumble = new RumbleEngine({
  getGamepad: currentPad,
  getHid: () => state.hid,
  onState: updateRumbleUi,
});

// ------------------------------------------------------------------ toast
let toastTimer;
function toast(msg, bad = false, ms = 3500) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.toggle('bad', bad);
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), ms);
}

// ------------------------------------------------------------------ controller svg
let parts = null;
function mountController(brand, edge) {
  $('padSvg').innerHTML = renderController(brand, { edge });
  const root = $('padSvg');
  const btns = new Map();
  root.querySelectorAll('[data-btn]').forEach((el) => {
    const i = /^\d+$/.test(el.dataset.btn) ? +el.dataset.btn : el.dataset.btn;
    if (!btns.has(i)) btns.set(i, []);
    btns.get(i).push(el);
  });
  const trig = {};
  root.querySelectorAll('[data-trigger]').forEach((g) => {
    const shell = g.querySelector('.t-shell');
    trig[g.dataset.trigger] = {
      g, fill: g.querySelector('.t-fill'),
      y: +shell.getAttribute('y'), h: +shell.getAttribute('height'),
    };
  });
  parts = {
    btns,
    sticks: { l: root.querySelector('[data-stick="l"]'), r: root.querySelector('[data-stick="r"]') },
    stickCaps: { l: root.querySelector('[data-stick="l"] .stick-cap'), r: root.querySelector('[data-stick="r"] .stick-cap') },
    trig,
    motors: {
      strong: [...root.querySelectorAll('[data-motor="strong"] circle')],
      weak: [...root.querySelectorAll('[data-motor="weak"] circle')],
    },
    trumble: { 6: root.querySelector('[data-trumble="6"]'), 7: root.querySelector('[data-trumble="7"]') },
    touch: [...root.querySelectorAll('[data-touch]')],
    lightbars: [...root.querySelectorAll('.lightbar')],
    pressed: new Set(),
  };
  state.renderedBrand = `${brand}|${edge}`;
  if (state.hid?.lightbar) setSvgLightbar(state.hid.lightbar);
}

function setSvgLightbar(hex) {
  pad3d?.setLightbar(hex);
  parts?.lightbars.forEach((el) => { el.setAttribute('fill', hex); el.style.filter = `drop-shadow(0 0 6px ${hex})`; });
}

function setPressed(i, on) {
  pad3d?.setButton(i, on);
  const els = parts?.btns.get(i);
  if (!els) return;
  if (on === parts.pressed.has(i)) return;
  on ? parts.pressed.add(i) : parts.pressed.delete(i);
  els.forEach((el) => el.classList.toggle('pressed', on));
}

// ------------------------------------------------------------------ brand / tabs
function resolveBrand(gp) {
  if (state.styleOverride !== 'auto') return state.styleOverride;
  if (gp) return detectBrand(gp.id);
  if (state.hid) return state.hid.brand;
  return 'xbox';
}

function isEdge(gp) {
  if (state.hid) return !!state.hid.isEdge;
  if (!gp) return false;
  const { vendor, product } = parseIds(gp.id);
  return (vendor === 0x054c && product === 0x0df2) || /dualsense edge/i.test(gp.id);
}

function applyBrand(brand, edge) {
  edge = brand === 'playstation' && edge;
  if (brand === state.brand && state.renderedBrand === `${brand}|${edge}`) return;
  state.brand = brand;
  document.body.dataset.brand = brand;
  mountController(brand, edge);
  state.gridFor = null; // rebuild labels
  const [l, r] = triggerNames(brand);
  document.querySelector('#trigL .trig-label').textContent = l;
  document.querySelector('#trigR .trig-label').textContent = r;
  trigGraph.labels = [l, r];
  updateViewMode();
}

// ------------------------------------------------------------------ 3D view
// Brands with a real 3D model use it; everything else (or 2D chosen) uses the SVG.
const MODEL_FOR = { playstation: 'dualsense' };
let pad3d = null, pad3dState = 'idle'; // idle | loading | ready | failed
try { state.view = localStorage.getItem('padlab.view') || '3d'; } catch { state.view = '3d'; }

function want3D() {
  return state.view === '3d' && !!MODEL_FOR[state.brand] && pad3dState !== 'failed';
}

async function ensure3D() {
  if (pad3dState !== 'idle') return;
  pad3dState = 'loading';
  try {
    const { Pad3D, PROFILES } = await import('./model3d.js');
    if (!Pad3D.supported()) throw new Error('WebGL is not available');
    pad3d = new Pad3D($('pad3d'));
    window.padlab = { pad3d }; // handy for poking at the 3D view from devtools
    await pad3d.load(MODEL_FOR[state.brand], (f) => { $('pad3dLoading').textContent = `Loading 3D model… ${Math.round(f * 100)}%`; });
    const c = PROFILES[MODEL_FOR[state.brand]].credit;
    $('modelCredit').innerHTML = `3D model: <a href="${c.url}" target="_blank" rel="noopener">${escapeHtml(c.title)}</a> by ${escapeHtml(c.author)} (${c.license})`;
    pad3d.setAccent(getComputedStyle(document.body).getPropertyValue('--accent'));
    if (state.hid?.lightbar) pad3d.setLightbar(state.hid.lightbar);
    $('pad3dLoading').remove();
    pad3dState = 'ready';
  } catch (e) {
    console.error(e);
    pad3dState = 'failed';
    toast(`3D view unavailable (${e.message}). Using the 2D drawing.`, true, 6000);
  }
  updateViewMode();
}

function updateViewMode() {
  const has = !!MODEL_FOR[state.brand] && pad3dState !== 'failed';
  const use3d = want3D();
  if (use3d && pad3dState === 'idle') ensure3D();
  const show3d = use3d;
  $('pad3d').hidden = !show3d;
  $('tilt').hidden = show3d && pad3dState === 'ready';
  $('viewHint').hidden = !(show3d && pad3dState === 'ready');
  $('viewSeg').hidden = !has;
  $('viewSeg').querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.view === state.view));
  if (pad3d && pad3dState === 'ready') pad3d.setAccent(getComputedStyle(document.body).getPropertyValue('--accent'));
}

$('viewSeg').addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  state.view = b.dataset.view;
  try { localStorage.setItem('padlab.view', state.view); } catch {}
  updateViewMode();
});

const active3D = () => pad3dState === 'ready' && !$('pad3d').hidden;
let lastFrameT = performance.now();

function renderTabs() {
  const pads = getPads();
  const tabs = $('padTabs');
  const sig = pads.map((p) => `${p.index}:${p.id}`).join('|') + `#${state.selected}`;
  if (tabs.dataset.sig === sig) return;
  tabs.dataset.sig = sig;
  tabs.innerHTML = '';
  pads.forEach((p) => {
    const b = document.createElement('button');
    b.className = 'pad-tab' + (p.index === (currentPad()?.index) ? ' on' : '');
    b.innerHTML = `<i></i><span>${p.index + 1}. ${escapeHtml(prettyName(p.id))}</span>`;
    b.title = p.id;
    b.onclick = () => { state.selected = p.index; resetPerPad(); renderTabs(); };
    tabs.appendChild(b);
  });
}

function escapeHtml(s) { return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

function resetPerPad() {
  state.prevButtons = {};
  state.btnCounts = {};
  state.gridFor = null;
  state.rawFor = null;
  state.trig = [newTrig(), newTrig()];
  stickL.reset(); stickR.reset();
}

// ------------------------------------------------------------------ chips
function renderPadChips(gp) {
  const chips = [];
  if (gp) {
    const { vendor, product } = parseIds(gp.id);
    chips.push(`<span class="chip accent">${state.brand}</span>`);
    chips.push(`<span class="chip ${gp.mapping === 'standard' ? 'good' : 'warn'}">${gp.mapping === 'standard' ? 'standard mapping' : 'non-standard mapping'}</span>`);
    chips.push(`<span class="chip">${gp.buttons.length} buttons · ${gp.axes.length} axes</span>`);
    if (vendor) chips.push(`<span class="chip">${vendor.toString(16).padStart(4, '0')}:${product.toString(16).padStart(4, '0')}</span>`);
  }
  if (state.hid?.hasMotion) chips.push('<span class="chip good">gyro live</span>');
  const html = chips.join('');
  if ($('padChips').dataset.html !== html) { $('padChips').innerHTML = html; $('padChips').dataset.html = html; }
}

function renderRumbleChips(gp) {
  const caps = rumble.gamepadCaps(gp);
  const chips = [];
  if (gp) {
    chips.push(`<span class="chip ${caps.dual || caps.legacy ? 'good' : 'bad'}">dual rumble ${caps.dual || caps.legacy ? '✓' : '✗'}</span>`);
    chips.push(`<span class="chip ${caps.trigger ? 'good' : ''}">trigger rumble ${caps.trigger ? '✓' : '✗'}</span>`);
  }
  if (state.hid) chips.push('<span class="chip good">WebHID rumble ✓</span>');
  const html = chips.join('');
  if ($('rumbleChips').dataset.html !== html) { $('rumbleChips').innerHTML = html; $('rumbleChips').dataset.html = html; }
  document.body.classList.toggle('no-trigger-rumble', !caps.trigger);
  document.querySelector('[data-backend="gamepad"]').disabled = !(gp && (caps.dual || caps.legacy));
  document.querySelector('[data-backend="hid"]').disabled = !state.hid;
}

// ------------------------------------------------------------------ buttons grid
// Buttons only readable over WebHID (mute; DualSense Edge Fn + back paddles).
// When an Edge is seen through the Gamepad API without WebHID, they're shown locked.
function extraButtons(gp) {
  if (state.hid?.extraButtons?.length) return { list: state.hid.extraButtons, locked: false };
  if (isEdge(gp)) return { list: DS_EXTRA, locked: true };
  return { list: [], locked: false };
}
const gridSig = (gp) => { const x = extraButtons(gp); return `${gp.id}|${gp.buttons.length}|${state.brand}|${x.list.length}|${x.locked}`; };

function buildGrid(gp) {
  const grid = $('btnGrid');
  grid.innerHTML = '';
  state.cells = new Map();
  const std = gp.mapping === 'standard';
  const add = (key, glyph, name, sub, locked = false) => {
    const c = document.createElement('div');
    c.className = 'bcell' + (locked ? ' locked' : '');
    c.title = locked ? `${name}: click "Connect WebHID" to read this button` : name;
    c.innerHTML = `<div class="bc">${state.btnCounts[key] || 0}</div><div class="bn">${escapeHtml(glyph)}</div><div class="bi">${escapeHtml(sub)}</div><div class="bv"></div>`;
    grid.appendChild(c);
    state.cells.set(key, c);
  };
  for (let i = 0; i < gp.buttons.length; i++) add(i, buttonGlyph(state.brand, i, std), buttonName(state.brand, i, std), `${buttonName(state.brand, i, std)} · #${i}`);
  const x = extraButtons(gp);
  for (const b of x.list) add(b.key, b.glyph, b.name, x.locked ? 'needs WebHID' : `${b.name} · HID`, x.locked);
  $('btnHint').hidden = !x.locked;
  state.gridFor = gridSig(gp);
  if (!state.tested.has(gp.id)) state.tested.set(gp.id, new Set());
  const tested = state.tested.get(gp.id);
  state.cells.forEach((c, k) => c.classList.toggle('tested', tested.has(k)));
  updateProgress(gp);
}
function updateProgress(gp) {
  const t = state.tested.get(gp.id)?.size || 0;
  const total = state.cells.size;
  $('btnProgress').textContent = `${t} / ${total} tested`;
  $('btnProgress').className = 'chip' + (t >= total ? ' good' : '');
}

// Shared press handling for standard and HID-only buttons.
function handleButton(gp, key, down, value, glyph, name) {
  const cell = state.cells.get(key);
  if (down && !state.prevButtons[key]) {
    state.btnCounts[key] = (state.btnCounts[key] || 0) + 1;
    const tested = state.tested.get(gp?.id);
    if (tested && !tested.has(key)) { tested.add(key); cell?.classList.add('tested'); updateProgress(gp); }
    state.lastInput = `${glyph === name ? name : `${glyph}  ${name}`}${typeof key === 'number' ? ` (#${key})` : ''}`;
    $('lastInput').textContent = `▸ ${state.lastInput}`;
    if (cell) cell.querySelector('.bc').textContent = state.btnCounts[key];
  }
  state.prevButtons[key] = down;
  if (cell) {
    if (cell.classList.contains('down') !== down) cell.classList.toggle('down', down);
    cell.querySelector('.bv').style.width = pct(value);
  }
  if (key !== 6 && key !== 7) setPressed(key, down);
}

function updateHidButtons(gp) {
  const pad = state.hid;
  if (!pad?.extraButtons?.length) return;
  for (const b of pad.extraButtons) {
    const down = !!pad.extraState[b.key];
    handleButton(gp, b.key, down, down ? 1 : 0, b.glyph, b.name);
  }
}

// ------------------------------------------------------------------ raw panel
function buildRaw(gp) {
  const raw = $('raw');
  raw.innerHTML = '';
  gp.axes.forEach((_, i) => {
    const r = document.createElement('div');
    r.className = 'r axis';
    r.innerHTML = `<span>axis ${i}</span><div class="bar"><i></i></div><span class="v">0</span>`;
    raw.appendChild(r);
  });
  gp.buttons.forEach((_, i) => {
    const r = document.createElement('div');
    r.className = 'r';
    r.innerHTML = `<span>button ${i}</span><div class="bar"><i></i></div><span class="v">0</span>`;
    raw.appendChild(r);
  });
  state.rawFor = gp.id;
}
function updateRaw(gp) {
  const det = document.querySelector('.raw-card details');
  if (!det.open) return;
  if (state.rawFor !== gp.id || $('raw').children.length !== gp.axes.length + gp.buttons.length) buildRaw(gp);
  const rows = $('raw').children;
  gp.axes.forEach((v, i) => {
    const bar = rows[i].querySelector('i');
    bar.style.width = `${Math.abs(v) * 50}%`;
    bar.style.left = v < 0 ? `${50 + v * 50}%` : '50%';
    rows[i].querySelector('.v').textContent = v.toFixed(4);
  });
  gp.buttons.forEach((b, i) => {
    const row = rows[gp.axes.length + i];
    row.querySelector('i').style.width = pct(b.value);
    row.querySelector('.v').textContent = b.value.toFixed(3);
  });
}

// ------------------------------------------------------------------ per-frame
function frame() {
  requestAnimationFrame(frame);
  const gp = currentPad();
  if (gp && state.selected === null) state.selected = gp.index;
  renderTabs();
  applyBrand(resolveBrand(gp), isEdge(gp));
  $('stage').classList.toggle('empty', !gp && !state.hid);
  $('padName').textContent = gp ? prettyName(gp.id) : state.hid ? state.hid.name : 'No controller';
  renderPadChips(gp);
  renderRumbleChips(gp);

  if (gp) updateFromGamepad(gp);
  else if (rumble.active && rumble.usedBackend === 'gamepad' && !state.hid) rumble.stop();
  updateHidButtons(gp);

  if (!rumble.active) updateRumbleUi(rumble);
  updateRumbleVisuals();
  updateTilt(gp);
  updateMotionUi();
  updateHidLive();

  const now = performance.now();
  if (active3D()) { pad3d.setEdge(isEdge(gp)); pad3d.render(Math.min(0.1, (now - lastFrameT) / 1000)); }
  lastFrameT = now;
}

function updateFromGamepad(gp) {
  // poll rate (timestamp only changes when the device reports new data)
  if (gp.timestamp !== state.lastTs) { state.lastTs = gp.timestamp; state.tsCount++; }
  const now = performance.now();
  if (now - state.tsT >= 1000) {
    state.pollHz = Math.round((state.tsCount * 1000) / (now - state.tsT));
    state.tsCount = 0; state.tsT = now;
    $('pollRate').textContent = `${state.pollHz} updates/s`;
  }

  if (state.gridFor !== gridSig(gp)) buildGrid(gp);
  const std = gp.mapping === 'standard';
  gp.buttons.forEach((b, i) => {
    handleButton(gp, i, b.pressed || b.value > 0.5, b.value, buttonGlyph(state.brand, i, std), buttonName(state.brand, i, std));
  });

  // stop combo: Back/Select + Start
  if (std && gp.buttons[8]?.pressed && gp.buttons[9]?.pressed) {
    if (state.comboArmed && rumble.active) { rumble.stop(); toast('Rumble stopped (Select + Start)'); }
    state.comboArmed = false;
  } else state.comboArmed = true;

  // sticks
  const ax = gp.axes;
  const lx = ax[0] || 0, ly = ax[1] || 0, rx = ax[2] || 0, ry = ax[3] || 0;
  moveStick('l', lx, ly, gp.buttons[10]?.pressed);
  moveStick('r', rx, ry, gp.buttons[11]?.pressed);
  stickL.update(lx, ly, gp.buttons[10]?.pressed);
  stickR.update(rx, ry, gp.buttons[11]?.pressed);
  stickStats('stickLStats', stickL, lx, ly);
  stickStats('stickRStats', stickR, rx, ry);

  // triggers
  const lt = std ? gp.buttons[6]?.value ?? 0 : 0;
  const rt = std ? gp.buttons[7]?.value ?? 0 : 0;
  setTrigger(6, lt); setTrigger(7, rt);
  trigStats(0, lt, 'trigL'); trigStats(1, rt, 'trigR');
  trigGraph.push([lt, rt]);
  trigGraph.draw();

  updateRaw(gp);
}

function moveStick(side, x, y, pressed) {
  pad3d?.setStick(side, x, y, pressed);
  const g = parts?.sticks[side];
  if (!g) return;
  g.setAttribute('transform', `translate(${(x * 15).toFixed(2)} ${(y * 15).toFixed(2)})`);
  const cap = parts.stickCaps[side];
  cap.classList.toggle('moved', Math.hypot(x, y) > 0.15);
}

function stickStats(id, view, x, y) {
  const mag = Math.hypot(x, y);
  const ang = (Math.atan2(-y, x) * 180) / Math.PI;
  const c = view.circularity();
  const circ = c.err === null ? `${Math.round(c.coverage * 100)}% swept` : `${c.err.toFixed(1)}%`;
  $(id).innerHTML =
    `<span>x</span><b>${x.toFixed(3)}</b><span>y</span><b>${y.toFixed(3)}</b>` +
    `<span>distance</span><b>${mag.toFixed(3)}</b><span>angle</span><b>${mag > 0.1 ? ang.toFixed(0) + '°' : '—'}</b>` +
    `<span>circularity err</span><b>${circ}</b><span>max reach</span><b>${view.maxMag.toFixed(3)}</b>`;
}

function setTrigger(idx, v) {
  pad3d?.setTrigger(idx, v);
  const t = parts?.trig[idx];
  if (!t) return;
  const h = t.h * v;
  t.fill.setAttribute('y', (t.y + t.h - h).toFixed(1));
  t.fill.setAttribute('height', h.toFixed(1));
  t.g.setAttribute('transform', `translate(0 ${(v * 7).toFixed(2)})`);
  t.g.classList.toggle('active', v > 0.05);
}

function trigStats(i, v, id) {
  const s = state.trig[i];
  s.peak = Math.max(s.peak, v);
  if (v > 0.0005) s.minStep = Math.min(s.minStep, v);
  if (v >= 0.99) s.full = true;
  const down = v > 0.5;
  if (down && !s.down) s.presses++;
  s.down = down;
  const el = $(id);
  el.querySelector('.trig-bar i').style.width = pct(v);
  el.querySelector('.peak').style.left = `calc(${s.peak * 100}% - 2px)`;
  el.querySelector('.trig-num').textContent = `${(v * 100).toFixed(1)}%`;
  el.querySelector('.trig-meta').innerHTML =
    `peak ${(s.peak * 100).toFixed(1)}% · first registers at ${s.minStep < 1 ? (s.minStep * 100).toFixed(1) + '%' : '—'} · presses ${s.presses} · ` +
    (s.full ? '<span class="ok">full travel ✓</span>' : 'full travel —');
}

// ------------------------------------------------------------------ rumble visuals
let shakeT = 0;
function updateRumbleVisuals() {
  const [s, w, l, r] = rumble.active ? rumble.current : [0, 0, 0, 0];
  pad3d?.setRumble([s, w, l, r]);
  const amp = s * 5 + w * 2.5;
  const shake = $('shake');
  if (amp > 0.05) {
    const jx = (Math.random() - 0.5) * amp, jy = (Math.random() - 0.5) * amp;
    shake.style.transform = `translate(${jx.toFixed(2)}px, ${jy.toFixed(2)}px) rotate(${((Math.random() - 0.5) * amp * 0.25).toFixed(2)}deg)`;
  } else if (shake.style.transform) shake.style.transform = '';

  shakeT += 1 / 60;
  if (!parts) return;
  ringPulse(parts.motors.strong, s, 1.1);
  ringPulse(parts.motors.weak, w, 2.2);
  for (const [idx, v] of [[6, l], [7, r]]) {
    const el = parts.trumble[idx];
    if (!el) continue;
    el.style.opacity = v > 0.01 ? (0.4 + 0.6 * v * (0.6 + 0.4 * Math.sin(shakeT * 40))).toFixed(2) : '0';
    el.setAttribute('transform', v > 0.01 ? `translate(0 ${(Math.random() * -3 * v).toFixed(2)})` : '');
  }
}
function ringPulse(circles, v, speed) {
  circles.forEach((c, i) => {
    if (v < 0.01) { c.style.opacity = '0'; return; }
    const ph = (shakeT * speed + i / circles.length) % 1;
    c.setAttribute('r', (12 + ph * 46).toFixed(1));
    c.style.opacity = ((1 - ph) * v * 0.9).toFixed(2);
    c.style.strokeWidth = (1 + 4 * v * (1 - ph)).toFixed(2);
  });
}

// ------------------------------------------------------------------ tilt
function updateTilt(gp) {
  const tilt = $('tilt');
  if (state.hid?.hasMotion && $('tiltToggle').checked) {
    let { pitch, yaw, roll } = motion.euler();
    if ($('invP').checked) pitch = -pitch;
    if ($('invY').checked) yaw = -yaw;
    if ($('invR').checked) roll = -roll;
    pad3d?.setOrientation({ pitch, yaw, roll });
    tilt.style.transform = `rotateZ(${(-yaw).toFixed(2)}deg) rotateX(${(-pitch).toFixed(2)}deg) rotateY(${(-roll).toFixed(2)}deg)`;
    return;
  }
  // Without gyro: gentle parallax following the left stick.
  const tx = gp ? (gp.axes[0] || 0) : 0, ty = gp ? (gp.axes[1] || 0) : 0;
  state.parallax[0] += (tx - state.parallax[0]) * 0.12;
  state.parallax[1] += (ty - state.parallax[1]) * 0.12;
  pad3d?.setOrientation({ pitch: state.parallax[1] * 7, yaw: 0, roll: state.parallax[0] * 9 });
  tilt.style.transform = `rotateX(${(state.parallax[1] * 9).toFixed(2)}deg) rotateY(${(state.parallax[0] * 12).toFixed(2)}deg)`;
}

// ------------------------------------------------------------------ rumble UI
function updateRumbleUi(engine) {
  const [s, w, l, r] = engine.active ? engine.current : [0, 0, 0, 0];
  $('mStrong').style.width = pct(s);
  $('mWeak').style.width = pct(w);
  $('mLT').style.width = pct(l);
  $('mRT').style.width = pct(r);
  const inf = engine.mode === 'infinite';
  $('infiniteBtn').classList.toggle('on', inf);
  const el = engine.elapsed;
  const hh = Math.floor(el / 3600), mm = Math.floor((el % 3600) / 60), ss = Math.floor(el % 60);
  $('infiniteTimer').textContent = inf ? `${hh ? hh + ':' : ''}${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}` : '00:00';
  $('infiniteSub').textContent = inf ? 'Running · click, Esc, or Select + Start to stop' : 'Runs until you stop it · Esc to stop';
  let msg;
  if (engine.error) msg = engine.error;
  else if (engine.active) msg = `Rumbling via ${engine.usedBackend === 'hid' ? 'WebHID' : 'Gamepad API'} · ${engine.mode === 'infinite' ? 'unlimited' : 'timed'} · strong ${pct(s)} · weak ${pct(w)}`;
  else {
    const b = engine.resolveBackend();
    msg = b ? `Ready · output: ${b === 'hid' ? 'WebHID' : 'Gamepad API'}` : (currentPad() ? 'This controller has no vibration actuator in this browser. Try WebHID or Chrome.' : 'Connect a controller to test rumble.');
  }
  if ($('rumbleStatus').textContent !== msg) $('rumbleStatus').textContent = msg;
  $('rumbleStatus').style.color = engine.error ? 'var(--bad)' : '';
}

function bindSlider(id, out, fn, fmt = (v) => `${v}%`) {
  const el = $(id);
  const apply = () => { $(out).textContent = fmt(+el.value); fn(+el.value); };
  el.addEventListener('input', apply);
  apply();
}
bindSlider('strongSlider', 'strongOut', (v) => { rumble.levels.strong = v / 100; });
bindSlider('weakSlider', 'weakOut', (v) => { rumble.levels.weak = v / 100; });
bindSlider('ltSlider', 'ltOut', (v) => { rumble.levels.lt = v / 100; });
bindSlider('rtSlider', 'rtOut', (v) => { rumble.levels.rt = v / 100; });
bindSlider('durationSlider', 'durationOut', () => {}, (v) => `${(v / 1000).toFixed(1)} s`);

function segment(id, attr, fn) {
  const seg = $(id);
  seg.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b || b.disabled) return;
    seg.querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
    fn(b.dataset[attr]);
  });
}
segment('patternSeg', 'pattern', (p) => { rumble.pattern = p; rumble.lastSent = { gp: null, hid: null }; });
segment('backendSeg', 'backend', (b) => {
  const wasMode = rumble.mode;
  if (rumble.active) rumble.stop();
  rumble.backend = b;
  if (wasMode === 'infinite') rumble.start('infinite');
});

function needPad() {
  if (!currentPad() && !state.hid) { toast('Connect a controller first: press any button on it.', true); return false; }
  return true;
}

$('infiniteBtn').addEventListener('click', () => {
  if (rumble.mode === 'infinite') { rumble.stop(); return; }
  if (!needPad()) return;
  rumble.start('infinite');
});
$('playBtn').addEventListener('click', () => { if (needPad()) rumble.start('timed', +$('durationSlider').value); });
$('stopBtn').addEventListener('click', () => rumble.stop());
document.querySelectorAll('[data-quick]').forEach((b) => b.addEventListener('click', () => {
  if (!needPad()) return;
  const levels = {
    left: { strong: 1, weak: 0, lt: 0, rt: 0 },
    right: { strong: 0, weak: 1, lt: 0, rt: 0 },
    both: { strong: 1, weak: 1, lt: 0, rt: 0 },
    lt: { strong: 0, weak: 0, lt: 1, rt: 0 },
    rt: { strong: 0, weak: 0, lt: 0, rt: 1 },
  }[b.dataset.quick];
  rumble.start('timed', 1000, { levels, pattern: 'constant' });
}));
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && rumble.active) { rumble.stop(); toast('Rumble stopped'); }
});
window.addEventListener('beforeunload', () => rumble.stop());

// ------------------------------------------------------------------ other controls
$('styleSelect').addEventListener('change', (e) => { state.styleOverride = e.target.value; });
$('stickResetBtn').addEventListener('click', () => { stickL.reset(); stickR.reset(); });
$('trigResetBtn').addEventListener('click', () => { state.trig = [newTrig(), newTrig()]; trigGraph.clear(); });
$('btnResetBtn').addEventListener('click', () => {
  const gp = currentPad();
  if (gp) state.tested.set(gp.id, new Set());
  state.btnCounts = {};
  state.gridFor = null;
});
$('calibBtn').addEventListener('click', () => motion.startCalibration());
$('recenterBtn').addEventListener('click', () => motion.recenter());

window.addEventListener('gamepadconnected', (e) => {
  toast(`Connected: ${prettyName(e.gamepad.id)}`);
  if (state.selected === null) state.selected = e.gamepad.index;
});
window.addEventListener('gamepaddisconnected', (e) => {
  toast(`Disconnected: ${prettyName(e.gamepad.id)}`, true);
  if (state.selected === e.gamepad.index) {
    if (rumble.active && rumble.usedBackend === 'gamepad') rumble.stop();
    state.selected = null;
    resetPerPad();
  }
});

// ------------------------------------------------------------------ WebHID
const HID_KIND = (d) => {
  if (d.vendorId === 0x057e) return { 0x2006: 'Joy-Con (L)', 0x2007: 'Joy-Con (R)', 0x200e: 'Joy-Con grip' }[d.productId] || 'Switch Pro Controller';
  if (d.productId === 0x0ce6) return 'DualSense';
  if (d.productId === 0x0df2) return 'DualSense Edge';
  return 'DualShock 4';
};

async function connectHid(device) {
  if (state.hid) await disconnectHid();
  const pad = createHidPad(device);
  pad.kindName = HID_KIND(device);
  pad.onMotion = (s) => motion.push(s);
  try {
    await pad.open();
  } catch (e) {
    console.error(e);
    toast(`Couldn't open ${pad.kindName}: ${e.message}. On Linux, install the udev rule (see README) and replug the controller.`, true, 9000);
    return;
  }
  state.hid = pad;
  motion.reset();
  setTimeout(() => { if (state.hid === pad) motion.startCalibration(); }, 700);
  $('hidDot').classList.add('on');
  $('hidBtnLabel').textContent = `${pad.kindName} · disconnect`;
  $('motionEmpty').hidden = true;
  $('motionBody').hidden = false;
  $('psExtra').hidden = !pad.supportsLightbar;
  $('adaptiveExtra').hidden = !pad.supportsAdaptive;
  toast(`WebHID connected: ${pad.kindName}`);
}

async function disconnectHid() {
  const pad = state.hid;
  if (!pad) return;
  if (rumble.active && rumble.usedBackend === 'hid') rumble.stop();
  state.hid = null;
  await pad.close();
  $('hidDot').classList.remove('on');
  $('hidBtnLabel').textContent = 'Connect WebHID · gyro & extras';
  $('motionEmpty').hidden = false;
  $('motionBody').hidden = true;
  $('psExtra').hidden = true;
  $('adaptiveExtra').hidden = true;
  $('hidInfo').innerHTML = '<p class="muted">Not connected.</p>';
  $('hidChips').innerHTML = '';
  $('tilt').style.transform = '';
}

if (!hidSupported()) {
  $('hidConnectBtn').disabled = true;
  $('hidBtnLabel').textContent = 'WebHID not available (use Chrome/Edge)';
} else {
  $('hidConnectBtn').addEventListener('click', async () => {
    if (state.hid) { await disconnectHid(); return; }
    try {
      const [device] = await navigator.hid.requestDevice({ filters: HID_FILTERS });
      if (device) await connectHid(device);
    } catch (e) { toast(`WebHID: ${e.message}`, true); }
  });
  navigator.hid.addEventListener('disconnect', (e) => {
    if (state.hid?.device === e.device) { toast('WebHID device disconnected', true); disconnectHid(); }
  });
  navigator.hid.addEventListener('connect', (e) => {
    if (!state.hid) connectHid(e.device);
  });
  // Re-open a device the user already granted access to.
  navigator.hid.getDevices().then((devs) => {
    const d = devs.find((d) => HID_FILTERS.some((f) => f.vendorId === d.vendorId && f.productId === d.productId));
    if (d && !state.hid) connectHid(d);
  });
}

$('lightbarApply').addEventListener('click', async () => {
  const pad = state.hid;
  if (!pad?.supportsLightbar) return;
  const hex = $('lightbarColor').value;
  const n = parseInt(hex.slice(1), 16);
  try {
    await pad.setLightbar((n >> 16) & 255, (n >> 8) & 255, n & 255);
    pad.lightbar = hex;
    setSvgLightbar(hex);
  } catch (e) { toast(`Lightbar: ${e.message}`, true); }
});

$('adaptiveApply').addEventListener('click', async () => {
  const pad = state.hid;
  if (!pad?.supportsAdaptive) return;
  const read = (side) => {
    const el = document.querySelector(`.adaptive-side[data-side="${side}"]`);
    return {
      mode: el.querySelector('.at-mode').value,
      start: +el.querySelector('.at-start').value,
      end: +el.querySelector('.at-end').value,
      force: +el.querySelector('.at-force').value,
    };
  };
  try {
    await pad.setTriggerEffects(read('left'), read('right'));
    toast('Trigger effects applied. Press L2 / R2 to feel them.');
  } catch (e) { toast(`Adaptive triggers: ${e.message}`, true); }
});

let hidInfoT = 0;
function updateHidLive() {
  const pad = state.hid;
  if (!pad) return;
  const now = performance.now();
  // touchpad
  if (pad.supportsTouch) {
    pad3d?.setTouch(pad.touch);
    pad.touch.forEach((t, i) => {
      const el = $(`touch${i}`);
      if (el) {
        el.style.display = t.active ? 'block' : 'none';
        if (t.active) { el.style.left = `${clamp(t.x, 0, 1) * 100}%`; el.style.top = `${clamp(t.y, 0, 1) * 100}%`; }
      }
      const pt = parts?.touch[i];
      if (pt) {
        pt.style.opacity = t.active ? '1' : '0';
        if (t.active) { pt.setAttribute('cx', (236 + clamp(t.x, 0, 1) * 168).toFixed(1)); pt.setAttribute('cy', (84 + clamp(t.y, 0, 1) * 88).toFixed(1)); }
      }
    });
  }
  if (now - hidInfoT < 250) return;
  hidInfoT = now;
  const b = pad.battery;
  const bat = b ? `<span class="battery"><span class="bar"><i style="width:${b.level}%"></i></span>${b.level}%${b.charging ? ' ⚡ charging' : b.full ? ' · full' : ''}</span>` : '—';
  $('hidInfo').innerHTML = `
    <dt>Device</dt><dd>${escapeHtml(pad.kindName)}</dd>
    <dt>Connection</dt><dd>${pad.transport === 'bt' ? 'Bluetooth' : pad.transport === 'usb' ? 'USB' : '—'}</dd>
    <dt>Report rate</dt><dd>${pad.reportRate} Hz</dd>
    <dt>Battery</dt><dd>${bat}</dd>
    <dt>Motion</dt><dd>${pad.hasMotion ? 'streaming' : 'waiting for full reports…'}</dd>`;
  const chips = `<span class="chip good">connected</span><span class="chip">${pad.transport.toUpperCase()}</span>`;
  if ($('hidChips').innerHTML !== chips) $('hidChips').innerHTML = chips;
}

function updateMotionUi() {
  if (!state.hid) return;
  const g = motion.gyro, a = motion.accel;
  const f = (v, d = 1) => (v >= 0 ? ' ' : '') + v.toFixed(d);
  $('gX').textContent = f(g[0]); $('gY').textContent = f(g[1]); $('gZ').textContent = f(g[2]);
  $('aX').textContent = f(a[0], 2); $('aY').textContent = f(a[1], 2); $('aZ').textContent = f(a[2], 2);
  const e = motion.euler();
  $('oP').textContent = `${e.pitch.toFixed(0)}°`; $('oY').textContent = `${e.yaw.toFixed(0)}°`; $('oR').textContent = `${e.roll.toFixed(0)}°`;
  gyroGraph.push(g); gyroGraph.draw();
  accelGraph.push(a); accelGraph.draw();
  if ($('calibStatus').textContent !== motion.calibMsg) $('calibStatus').textContent = motion.calibMsg;
}

// ------------------------------------------------------------------ go
applyBrand('xbox', false);
updateRumbleUi(rumble);
requestAnimationFrame(frame);
