// Gamepad API helpers: brand detection and human-readable button names.

export function parseIds(id) {
  // Chrome: "Name (STANDARD GAMEPAD Vendor: 054c Product: 0ce6)"
  // Firefox: "054c-0ce6-Name"
  let m = id.match(/Vendor:\s*([0-9a-f]{4})\s*Product:\s*([0-9a-f]{4})/i);
  if (m) return { vendor: parseInt(m[1], 16), product: parseInt(m[2], 16) };
  m = id.match(/^([0-9a-f]{1,4})-([0-9a-f]{1,4})-/i);
  if (m) return { vendor: parseInt(m[1], 16), product: parseInt(m[2], 16) };
  return { vendor: 0, product: 0 };
}

export function detectBrand(id) {
  const { vendor } = parseIds(id);
  const s = id.toLowerCase();
  if (vendor === 0x054c) return 'playstation';
  if (vendor === 0x057e) return 'nintendo';
  if (vendor === 0x045e) return 'xbox';
  if (/xbox|xinput|microsoft/.test(s)) return 'xbox';
  if (/nintendo|switch|pro controller|joy-?con/.test(s)) return 'nintendo';
  if (/dualsense|dualshock|playstation|sony|ps[345]|^wireless controller/.test(s)) return 'playstation';
  return 'xbox';
}

export function prettyName(id) {
  let name = id.replace(/\s*\((STANDARD GAMEPAD\s*)?Vendor:.*\)\s*$/i, '').replace(/^[0-9a-f]{1,4}-[0-9a-f]{1,4}-/i, '').trim();
  return name || 'Gamepad';
}

const NAMES = {
  xbox: ['A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT', 'View', 'Menu', 'LS', 'RS', 'D-Up', 'D-Down', 'D-Left', 'D-Right', 'Xbox', 'Share'],
  playstation: ['Cross', 'Circle', 'Square', 'Triangle', 'L1', 'R1', 'L2', 'R2', 'Create', 'Options', 'L3', 'R3', 'D-Up', 'D-Down', 'D-Left', 'D-Right', 'PS', 'Touchpad'],
  nintendo: ['B', 'A', 'Y', 'X', 'L', 'R', 'ZL', 'ZR', 'Minus', 'Plus', 'LS', 'RS', 'D-Up', 'D-Down', 'D-Left', 'D-Right', 'Home', 'Capture'],
};
const GLYPHS = { playstation: ['✕', '○', '□', '△'] };

export function buttonName(brand, i, standard = true) {
  if (!standard) return `B${i}`;
  return (NAMES[brand] || NAMES.xbox)[i] ?? `B${i}`;
}

export function buttonGlyph(brand, i, standard = true) {
  if (standard && GLYPHS[brand] && i < 4) return GLYPHS[brand][i];
  if (standard && i >= 12 && i <= 15) return ['↑', '↓', '←', '→'][i - 12];
  return buttonName(brand, i, standard);
}

export function triggerNames(brand) {
  return { xbox: ['LT', 'RT'], playstation: ['L2', 'R2'], nintendo: ['ZL', 'ZR'] }[brand] || ['LT', 'RT'];
}

export function getPads() {
  const list = navigator.getGamepads ? navigator.getGamepads() : [];
  return Array.from(list).filter(Boolean);
}
