// SVG controller renderers. Every interactive part carries data attributes that
// main.js uses to animate it:
//   data-btn="N"      standard-mapping button index (gets .pressed)
//   data-stick="l|r"  outer group translated by the stick position
//   data-trigger="N"  trigger group (fill + depression by analog value)
//   data-motor="strong|weak"  rumble ripple rings
//   data-trumble="6|7"        trigger-rumble arcs

const VB = '0 -34 640 484';

const BODIES = {
  xbox: 'M 200 72 C 260 62, 380 62, 440 72 C 505 80, 548 100, 572 150 C 600 215, 628 330, 606 384 C 588 428, 532 430, 500 392 C 474 360, 456 330, 420 322 L 220 322 C 184 330, 166 360, 140 392 C 108 430, 52 428, 34 384 C 12 330, 40 215, 68 150 C 92 100, 135 80, 200 72 Z',
  playstation: 'M 150 80 C 230 66, 410 66, 490 80 C 545 90, 575 115, 590 160 C 612 230, 632 335, 610 392 C 592 434, 536 434, 506 398 C 480 366, 462 342, 428 338 L 212 338 C 178 342, 160 366, 134 398 C 104 434, 48 434, 30 392 C 8 335, 28 230, 50 160 C 65 115, 95 90, 150 80 Z',
  nintendo: 'M 196 74 C 258 64, 382 64, 444 74 C 512 84, 552 106, 574 156 C 602 222, 626 334, 602 388 C 582 430, 528 430, 498 394 C 472 362, 454 334, 418 326 L 222 326 C 186 334, 168 362, 142 394 C 112 430, 58 430, 38 388 C 14 334, 38 222, 66 156 C 88 106, 128 84, 196 74 Z',
};

const LAYOUTS = {
  xbox: {
    triggers: [{ idx: 6, x: 120, y: 0, w: 110, h: 42, rot: -12, label: 'LT' }, { idx: 7, x: 410, y: 0, w: 110, h: 42, rot: 12, label: 'RT' }],
    bumpers: [{ idx: 4, x: 116, y: 52, w: 118, h: 24, rot: -12, label: 'LB' }, { idx: 5, x: 406, y: 52, w: 118, h: 24, rot: 12, label: 'RB' }],
    sticks: { l: [180, 170], r: [392, 262] },
    dpad: [250, 262],
    face: { c: [462, 170], d: 38 },
    motors: { strong: [96, 330], weak: [544, 330] },
  },
  playstation: {
    triggers: [{ idx: 6, x: 86, y: 2, w: 108, h: 42, rot: -10, label: 'L2' }, { idx: 7, x: 446, y: 2, w: 108, h: 42, rot: 10, label: 'R2' }],
    bumpers: [{ idx: 4, x: 84, y: 56, w: 112, h: 24, rot: -10, label: 'L1' }, { idx: 5, x: 444, y: 56, w: 112, h: 24, rot: 10, label: 'R1' }],
    sticks: { l: [236, 266], r: [404, 266] },
    dpad: [140, 176],
    face: { c: [500, 176], d: 38 },
    motors: { strong: [84, 350], weak: [556, 350] },
  },
  nintendo: {
    triggers: [{ idx: 6, x: 118, y: 0, w: 110, h: 42, rot: -12, label: 'ZL' }, { idx: 7, x: 412, y: 0, w: 110, h: 42, rot: 12, label: 'ZR' }],
    bumpers: [{ idx: 4, x: 114, y: 54, w: 118, h: 24, rot: -12, label: 'L' }, { idx: 5, x: 408, y: 54, w: 118, h: 24, rot: 12, label: 'R' }],
    sticks: { l: [182, 172], r: [394, 262] },
    dpad: [252, 262],
    face: { c: [462, 172], d: 38 },
    motors: { strong: [98, 334], weak: [542, 334] },
  },
};

// Face-button labels by position: bottom, right, left, top (standard indices 0..3).
const FACE = {
  xbox: [['A', '--c-a'], ['B', '--c-b'], ['X', '--c-x'], ['Y', '--c-y']],
  playstation: [['cross', '--c-a'], ['circle', '--c-b'], ['square', '--c-x'], ['triangle', '--c-y']],
  nintendo: [['B', '--c-a'], ['A', '--c-b'], ['Y', '--c-x'], ['X', '--c-y']],
};

function psSymbol(kind, x, y) {
  const s = `class="sym" fill="none" stroke="var(--fc)" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"`;
  switch (kind) {
    case 'cross': return `<path ${s} d="M ${x - 7} ${y - 7} L ${x + 7} ${y + 7} M ${x + 7} ${y - 7} L ${x - 7} ${y + 7}"/>`;
    case 'circle': return `<circle ${s} cx="${x}" cy="${y}" r="8.5"/>`;
    case 'square': return `<rect ${s} x="${x - 7.5}" y="${y - 7.5}" width="15" height="15" rx="1"/>`;
    case 'triangle': return `<path ${s} d="M ${x} ${y - 9} L ${x + 9} ${y + 6} L ${x - 9} ${y + 6} Z"/>`;
  }
  return '';
}

function faceButtons(brand, L) {
  const [cx, cy] = L.face.c, d = L.face.d;
  const pos = [[cx, cy + d], [cx + d, cy], [cx - d, cy], [cx, cy - d]];
  return `<circle class="well" cx="${cx}" cy="${cy}" r="66" opacity=".25"/>` + FACE[brand].map(([label, color], i) => {
    const [x, y] = pos[i];
    const inner = brand === 'playstation' ? psSymbol(label, x, y) : `<text class="lbl" x="${x}" y="${y + 1}">${label}</text>`;
    return `<g data-btn="${i}" class="face" style="--fc: var(${color})">
      <circle class="part" cx="${x}" cy="${y}" r="20"/>
      <circle cx="${x}" cy="${y - 3}" r="14" fill="#ffffff08"/>
      ${inner}
    </g>`;
  }).join('');
}

function dpad([cx, cy]) {
  const a = 17, l = 40;
  const arm = (idx, x, y, w, h, tri) => `<g data-btn="${idx}">
      <rect class="part" x="${x}" y="${y}" width="${w}" height="${h}" rx="6"/>
      <path d="${tri}" fill="var(--part-text)" opacity=".55"/>
    </g>`;
  return `<circle class="well" cx="${cx}" cy="${cy}" r="56"/>
    ${arm(12, cx - a, cy - l - 2, a * 2, l - 4, `M ${cx} ${cy - l + 6} l 6 9 h -12 z`)}
    ${arm(13, cx - a, cy + 6, a * 2, l - 4, `M ${cx} ${cy + l - 6} l 6 -9 h -12 z`)}
    ${arm(14, cx - l - 2, cy - a, l - 4, a * 2, `M ${cx - l + 6} ${cy} l 9 -6 v 12 z`)}
    ${arm(15, cx + 6, cy - a, l - 4, a * 2, `M ${cx + l - 6} ${cy} l -9 -6 v 12 z`)}
    <rect class="part" x="${cx - a}" y="${cy - a}" width="${a * 2}" height="${a * 2}" fill="var(--part)" stroke="none"/>
    <circle cx="${cx}" cy="${cy}" r="7" fill="#00000040"/>`;
}

function stick(side, [cx, cy]) {
  const idx = side === 'l' ? 10 : 11;
  return `<circle class="well" cx="${cx}" cy="${cy}" r="50"/>
    <circle cx="${cx}" cy="${cy}" r="44" fill="#00000055"/>
    <g data-stick="${side}">
      <g data-btn="${idx}" class="stick-cap">
        <circle class="cap" cx="${cx}" cy="${cy}" r="35"/>
        <circle class="cap-ring" cx="${cx}" cy="${cy}" r="27"/>
        <circle class="cap-dot" cx="${cx}" cy="${cy}" r="14"/>
      </g>
    </g>`;
}

function trigger(t) {
  const cx = t.x + t.w / 2, cy = t.y + t.h / 2;
  return `<g transform="rotate(${t.rot} ${cx} ${cy})">
      <g data-trigger="${t.idx}" class="trigger">
        <clipPath id="clipT${t.idx}"><rect x="${t.x}" y="${t.y}" width="${t.w}" height="${t.h}" rx="16"/></clipPath>
        <rect class="t-shell" x="${t.x}" y="${t.y}" width="${t.w}" height="${t.h}" rx="16"/>
        <rect class="t-fill" clip-path="url(#clipT${t.idx})" x="${t.x}" y="${t.y + t.h}" width="${t.w}" height="0"/>
        <text class="t-lbl" x="${cx}" y="${t.y + 20}">${t.label}</text>
      </g>
      <path data-trumble="${t.idx}" class="t-rumble" d="M ${t.x + 6} ${t.y - 6} Q ${cx} ${t.y - 26} ${t.x + t.w - 6} ${t.y - 6}"/>
    </g>`;
}

function bumper(b) {
  const cx = b.x + b.w / 2, cy = b.y + b.h / 2;
  return `<g transform="rotate(${b.rot} ${cx} ${cy})">
      <g data-btn="${b.idx}" class="bumper">
        <rect class="part" x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" rx="14"/>
        <text class="lbl small" x="${cx}" y="${b.y + 11}">${b.label}</text>
      </g>
    </g>`;
}

function motors(L) {
  return Object.entries(L.motors).map(([k, [x, y]]) =>
    `<g data-motor="${k}">${[0, 1, 2].map(() => `<circle class="motor" cx="${x}" cy="${y}" r="10"/>`).join('')}</g>`).join('');
}

const pill = (idx, x, y, w, h, content = '', rot = 0) => `<g transform="rotate(${rot} ${x} ${y})"><g data-btn="${idx}">
    <rect class="part" x="${x - w / 2}" y="${y - h / 2}" width="${w}" height="${h}" rx="${Math.min(w, h) / 2}"/>${content}
  </g></g>`;

function centerButtons(brand) {
  if (brand === 'xbox') {
    return `
      ${pill(8, 272, 170, 26, 26, `<path d="M 266 166 h 8 v 8 h -8 z M 270 163 h 8 v 8" fill="none" stroke="var(--part-text)" stroke-width="1.6"/>`)}
      ${pill(9, 368, 170, 26, 26, `<path d="M 362 165 h 12 M 362 170 h 12 M 362 175 h 12" stroke="var(--part-text)" stroke-width="1.8"/>`)}
      ${pill(17, 320, 182, 26, 14)}
      <g data-btn="16">
        <circle class="part" cx="320" cy="112" r="24" />
        <circle cx="320" cy="112" r="16" fill="none" stroke="var(--accent)" stroke-width="3" opacity=".9"/>
        <path d="M 312 104 L 328 120 M 328 104 L 312 120" stroke="var(--accent)" stroke-width="3" stroke-linecap="round"/>
      </g>`;
  }
  if (brand === 'playstation') {
    return `
      <g data-btn="17" class="touch-btn">
        <rect class="part" x="228" y="76" width="184" height="104" rx="14"/>
        <rect x="236" y="84" width="168" height="88" rx="10" fill="#ffffff06"/>
        <circle class="touch-pt" data-touch="0" cx="320" cy="128" r="9"/>
        <circle class="touch-pt" data-touch="1" cx="320" cy="128" r="9"/>
      </g>
      <rect class="lightbar" x="219" y="84" width="5" height="88" rx="2.5" fill="var(--accent)" opacity=".8"/>
      <rect class="lightbar" x="416" y="84" width="5" height="88" rx="2.5" fill="var(--accent)" opacity=".8"/>
      ${pill(8, 200, 98, 12, 26, '', -20)}
      ${pill(9, 440, 98, 12, 26, '', 20)}
      <g data-btn="16">
        <circle class="part" cx="320" cy="262" r="17"/>
        <text class="lbl small" x="320" y="263">PS</text>
      </g>
      <g data-btn="x-mute">
        <rect class="part" x="305" y="294" width="30" height="11" rx="5.5"/>
      </g>`;
  }
  // nintendo
  return `
    ${pill(8, 266, 128, 26, 26, `<path d="M 259 128 h 14" stroke="var(--part-text)" stroke-width="3" stroke-linecap="round"/>`)}
    ${pill(9, 374, 128, 26, 26, `<path d="M 367 128 h 14 M 374 121 v 14" stroke="var(--part-text)" stroke-width="3" stroke-linecap="round"/>`)}
    <g data-btn="17">
      <rect class="part" x="276" y="170" width="24" height="24" rx="5"/>
      <circle cx="288" cy="182" r="6" fill="none" stroke="var(--part-text)" stroke-width="2"/>
    </g>
    <g data-btn="16">
      <circle class="part" cx="352" cy="182" r="14"/>
      <path d="M 344 184 L 352 176 L 360 184 M 346 183 v 6 h 12 v -6" fill="none" stroke="var(--part-text)" stroke-width="2" stroke-linejoin="round"/>
    </g>`;
}

// DualSense Edge: Fn buttons under the sticks and the two rear paddles. The paddles
// sit on the underside of the grips, so they're drawn dashed ("seen through" the body).
function edgeExtras() {
  const paddle = (key, cx, cy, rot, label) => `<g transform="rotate(${rot} ${cx} ${cy})"><g data-btn="${key}" class="paddle">
      <rect class="part" x="${cx - 30}" y="${cy - 10}" width="60" height="20" rx="10"/>
      <text class="lbl small" x="${cx}" y="${cy + 1}">${label}</text>
    </g></g>`;
  return `
    <g data-btn="x-fnl"><rect class="part" x="226" y="321" width="22" height="10" rx="5"/><text class="lbl tiny" x="237" y="312">Fn</text></g>
    <g data-btn="x-fnr"><rect class="part" x="392" y="321" width="22" height="10" rx="5"/><text class="lbl tiny" x="403" y="312">Fn</text></g>
    ${paddle('x-backl', 96, 376, 28, 'BACK L')}
    ${paddle('x-backr', 544, 376, -28, 'BACK R')}`;
}

export function renderController(brand, { edge = false } = {}) {
  if (!LAYOUTS[brand]) brand = 'xbox';
  const L = LAYOUTS[brand];
  return `<svg viewBox="${VB}" xmlns="http://www.w3.org/2000/svg" aria-label="${brand} controller">
    <defs>
      <linearGradient id="bodyGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" style="stop-color: var(--body-hi)"/>
        <stop offset=".55" style="stop-color: var(--body)"/>
        <stop offset="1" style="stop-color: var(--body-edge)"/>
      </linearGradient>
      <radialGradient id="shine" cx=".35" cy=".2" r=".7">
        <stop offset="0" stop-color="#fff" stop-opacity=".18"/>
        <stop offset="1" stop-color="#fff" stop-opacity="0"/>
      </radialGradient>
    </defs>
    ${L.triggers.map(trigger).join('')}
    <path class="body" d="${BODIES[brand]}"/>
    <path d="${BODIES[brand]}" fill="url(#shine)" pointer-events="none"/>
    ${L.bumpers.map(bumper).join('')}
    ${brand === 'playstation' ? `<path d="M 212 338 L 428 338 C 440 300, 430 230, 420 190 L 220 190 C 210 230, 200 300, 212 338 Z" fill="var(--part)" opacity=".92"/>` : ''}
    ${motors(L)}
    ${dpad(L.dpad)}
    ${stick('l', L.sticks.l)}
    ${stick('r', L.sticks.r)}
    ${faceButtons(brand, L)}
    ${centerButtons(brand)}
    ${brand === 'playstation' && edge ? edgeExtras() : ''}
  </svg>`;
}
