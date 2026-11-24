// WebHID drivers for controllers whose motion sensors aren't exposed by the
// Gamepad API: DualShock 4, DualSense (incl. Edge), Switch Pro Controller and Joy-Cons.
//
// Motion samples are normalised to one frame for every controller:
//   X = right, Y = up (out of the face), Z = toward the player
//   gyro in deg/s (pitch about X, yaw about Y, roll about Z), accel in g.

export const HID_FILTERS = [
  { vendorId: 0x054c, productId: 0x05c4 }, // DS4 v1
  { vendorId: 0x054c, productId: 0x09cc }, // DS4 v2
  { vendorId: 0x054c, productId: 0x0ba0 }, // DS4 USB dongle
  { vendorId: 0x054c, productId: 0x0ce6 }, // DualSense
  { vendorId: 0x054c, productId: 0x0df2 }, // DualSense Edge
  { vendorId: 0x057e, productId: 0x2009 }, // Switch Pro
  { vendorId: 0x057e, productId: 0x2006 }, // Joy-Con L
  { vendorId: 0x057e, productId: 0x2007 }, // Joy-Con R
  { vendorId: 0x057e, productId: 0x200e }, // Joy-Con charging grip
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const clamp01 = (v) => Math.max(0, Math.min(1, v));
const u8 = (v) => Math.round(clamp01(v) * 255);

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[i] = c >>> 0;
  }
  return t;
})();
function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
// Sony Bluetooth output reports end with a CRC32 over [0xA2, reportId, ...payload].
function sealBt(reportId, data) {
  const buf = new Uint8Array(data.length - 4 + 2);
  buf[0] = 0xa2; buf[1] = reportId;
  buf.set(data.subarray(0, data.length - 4), 2);
  const crc = crc32(buf);
  const n = data.length;
  data[n - 4] = crc & 0xff; data[n - 3] = (crc >>> 8) & 0xff;
  data[n - 2] = (crc >>> 16) & 0xff; data[n - 1] = (crc >>> 24) & 0xff;
  return data;
}

function reportLength(device, id, kind = 'outputReports') {
  for (const c of device.collections || []) {
    for (const r of c[kind] || []) {
      if (r.reportId !== id) continue;
      let bits = 0;
      for (const it of r.items || []) bits += it.reportSize * it.reportCount;
      return bits ? Math.ceil(bits / 8) : null;
    }
  }
  return null;
}
function hasReport(device, id, kind = 'outputReports') {
  return (device.collections || []).some((c) => (c[kind] || []).some((r) => r.reportId === id));
}

class HidPad {
  constructor(device) {
    this.device = device;
    this.name = device.productName || 'HID controller';
    this.transport = '?';
    this.battery = null; // { level 0-100, charging }
    this.touch = [];
    this.hasMotion = false;
    this.extraButtons = []; // buttons only readable over HID: { key, name, glyph }
    this.extraState = {};
    this.reportCount = 0;
    this.reportRate = 0;
    this._rateT = performance.now();
    this._lastT = 0;
    this.onMotion = null;
    this.onUpdate = null;
    this._onReport = (e) => this._handle(e);
  }
  get brand() { return 'playstation'; }
  get keepAliveMs() { return 1000; }
  async open() {
    if (!this.device.opened) await this.device.open();
    this.device.addEventListener('inputreport', this._onReport);
    await this.init();
  }
  async init() {}
  async close() {
    try { await this.setRumble(0, 0); } catch {}
    this.device.removeEventListener('inputreport', this._onReport);
    try { await this.device.close(); } catch {}
  }
  _tick() {
    this.reportCount++;
    const now = performance.now();
    if (now - this._rateT >= 1000) {
      this.reportRate = Math.round((this.reportCount * 1000) / (now - this._rateT));
      this.reportCount = 0; this._rateT = now;
    }
  }
  _wallDt() {
    const now = performance.now();
    const dt = this._lastT ? (now - this._lastT) / 1000 : 0;
    this._lastT = now;
    return dt;
  }
  _emit(gyro, accel, dt) {
    this.hasMotion = true;
    if (this.onMotion) this.onMotion({ gyro, accel, dt: Math.min(Math.max(dt, 0), 0.05) });
  }
  async setRumble() {}
  async setLightbar() {}
  get supportsLightbar() { return false; }
  get supportsAdaptive() { return false; }
  get supportsTouch() { return false; }
}

// ---------------------------------------------------------------- DualSense
// Third button byte of the input report: PS 0x01, touchpad 0x02, mute 0x04, and on
// the DualSense Edge also Fn and rear paddles (not exposed by the Gamepad API on Linux).
export const DS_EXTRA = [
  { key: 'x-mute', name: 'Mute', glyph: 'Mic', bit: 0x04 },
  { key: 'x-fnl', name: 'Left Fn', glyph: 'Fn L', bit: 0x10 },
  { key: 'x-fnr', name: 'Right Fn', glyph: 'Fn R', bit: 0x20 },
  { key: 'x-backl', name: 'Left back paddle', glyph: 'Back L', bit: 0x40 },
  { key: 'x-backr', name: 'Right back paddle', glyph: 'Back R', bit: 0x80 },
];

const DS_GYRO = 1 / 16.384; // nominal deg/s per LSB
const DS_ACC = 1 / 8192; // nominal g per LSB

class DualSense extends HidPad {
  constructor(device) {
    super(device);
    this.seq = 0;
    this._ts = null;
    this._requestedFull = false;
    this._lightbarInit = false;
    this.isEdge = device.productId === 0x0df2;
    this.extraButtons = this.isEdge ? DS_EXTRA : DS_EXTRA.slice(0, 1);
  }
  get supportsLightbar() { return true; }
  get supportsAdaptive() { return true; }
  get supportsTouch() { return true; }
  async init() {
    this.transport = hasReport(this.device, 0x31) ? 'bt' : 'usb';
    await this._requestFullMode();
  }
  async _requestFullMode() {
    if (this._requestedFull) return;
    this._requestedFull = true;
    // Reading the calibration feature report switches Bluetooth to the full 0x31 report.
    try { await this.device.receiveFeatureReport(0x05); } catch {}
  }
  _handle(e) {
    const d = e.data;
    let off;
    if (e.reportId === 0x01 && d.byteLength >= 60) { off = 0; this.transport = 'usb'; }
    else if (e.reportId === 0x31) { off = 1; this.transport = 'bt'; }
    else { if (e.reportId === 0x01) { this.transport = 'bt'; this._requestFullMode(); } return; }
    this._tick();

    const b2 = d.getUint8(off + 9);
    for (const x of this.extraButtons) this.extraState[x.key] = !!(b2 & x.bit);

    const g = (o) => d.getInt16(off + o, true);
    const ts = d.getUint32(off + 27, true);
    let dt;
    if (this._ts !== null) {
      dt = ((ts - this._ts) >>> 0) / 3e6;
      if (!(dt > 0.0003 && dt < 0.05)) dt = this._wallDt(); else this._wallDt();
    } else dt = this._wallDt();
    this._ts = ts;
    this._emit(
      [g(15) * DS_GYRO, g(17) * DS_GYRO, g(19) * DS_GYRO],
      [g(21) * DS_ACC, g(23) * DS_ACC, g(25) * DS_ACC], dt);

    this.touch = [0, 1].map((i) => {
      const o = off + 32 + i * 4;
      const c = d.getUint8(o), b1 = d.getUint8(o + 1), b2 = d.getUint8(o + 2), b3 = d.getUint8(o + 3);
      return { active: !(c & 0x80), x: (b1 | ((b2 & 0x0f) << 8)) / 1920, y: ((b2 >> 4) | (b3 << 4)) / 1080 };
    });
    const st = d.getUint8(off + 52);
    const lvl = st & 0x0f, chg = (st & 0xf0) >> 4;
    this.battery = { level: Math.min(100, lvl * 10 + 5), charging: chg === 0x1, full: chg === 0x2 };
    if (chg === 0x2) this.battery.level = 100;
    this.onUpdate?.();
  }
  _common() { return new Uint8Array(47); }
  async _send(common) {
    if (this.transport === 'bt') {
      const data = new Uint8Array(77);
      data[0] = (this.seq << 4) & 0xf0; this.seq = (this.seq + 1) & 0x0f;
      data[1] = 0x10;
      data.set(common, 2);
      await this.device.sendReport(0x31, sealBt(0x31, data));
    } else {
      const data = new Uint8Array(reportLength(this.device, 0x02) || 63 - 1);
      data.set(common, 0);
      await this.device.sendReport(0x02, data);
    }
  }
  async setRumble(strong, weak) {
    const c = this._common();
    c[0] = 0x01 | 0x02; // compatible vibration + haptics select
    c[38] = 0x04; // compatible vibration v2 (newer firmware)
    c[2] = u8(weak); // right / high-frequency
    c[3] = u8(strong); // left / low-frequency
    await this._send(c);
  }
  async setLightbar(r, g, b) {
    const c = this._common();
    c[1] = 0x04; // lightbar control
    if (!this._lightbarInit) { c[38] = 0x02; c[41] = 0x02; this._lightbarInit = true; }
    c[44] = r; c[45] = g; c[46] = b;
    await this._send(c);
  }
  // effects: { mode, start, end, force } per side (values 0-255)
  async setTriggerEffects(left, right) {
    const c = this._common();
    c[0] = 0x04 | 0x08;
    c.set(encodeTrigger(right), 10);
    c.set(encodeTrigger(left), 21);
    await this._send(c);
  }
}

function encodeTrigger(fx) {
  const b = new Uint8Array(11);
  switch (fx?.mode) {
    case 'rigid': b[0] = 0x01; b[1] = fx.start; b[2] = fx.force; break;
    case 'section': b[0] = 0x02; b[1] = fx.start; b[2] = Math.max(fx.end, fx.start + 1) & 0xff; b[3] = fx.force; break;
    case 'vibrate': b[0] = 0x06; b[1] = fx.end; b[2] = fx.force; b[3] = fx.start; break;
    default: b[0] = 0x05; // off
  }
  return b;
}

// ---------------------------------------------------------------- DualShock 4
class DualShock4 extends HidPad {
  constructor(device) { super(device); this._ts = null; this._requestedFull = false; }
  get supportsLightbar() { return true; }
  get supportsTouch() { return true; }
  async init() {
    this.transport = hasReport(this.device, 0x11) && !hasReport(this.device, 0x05) ? 'bt' : 'usb';
    await this._requestFullMode();
  }
  async _requestFullMode() {
    if (this._requestedFull) return;
    this._requestedFull = true;
    // Reading a calibration feature report enables the full 0x11 report over Bluetooth.
    for (const id of [0x05, 0x02]) { try { await this.device.receiveFeatureReport(id); break; } catch {} }
  }
  _handle(e) {
    const d = e.data;
    let off;
    if (e.reportId === 0x01 && d.byteLength >= 63) { off = 0; this.transport = 'usb'; }
    else if (e.reportId === 0x11) { off = 2; this.transport = 'bt'; }
    else { if (e.reportId === 0x01) { this.transport = 'bt'; this._requestFullMode(); } return; }
    this._tick();

    const g = (o) => d.getInt16(off + o, true);
    const ts = d.getUint16(off + 9, true);
    let dt;
    if (this._ts !== null) {
      dt = (((ts - this._ts) & 0xffff) * 16) / 3 / 1e6;
      if (!(dt > 0.0003 && dt < 0.05)) dt = this._wallDt(); else this._wallDt();
    } else dt = this._wallDt();
    this._ts = ts;
    this._emit(
      [g(12) * DS_GYRO, g(14) * DS_GYRO, g(16) * DS_GYRO],
      [g(18) * DS_ACC, g(20) * DS_ACC, g(22) * DS_ACC], dt);

    const s = d.getUint8(off + 29);
    const lvl = s & 0x0f, cable = !!(s & 0x10);
    this.battery = cable
      ? { level: Math.min(100, lvl * 10), charging: lvl < 11, full: lvl >= 11 }
      : { level: Math.min(100, lvl * 10 + 5), charging: false };

    this.touch = [0, 1].map((i) => {
      const o = off + 34 + i * 4;
      if (o + 3 >= d.byteLength) return { active: false, x: 0, y: 0 };
      const c = d.getUint8(o), b1 = d.getUint8(o + 1), b2 = d.getUint8(o + 2), b3 = d.getUint8(o + 3);
      return { active: !(c & 0x80), x: (b1 | ((b2 & 0x0f) << 8)) / 1920, y: ((b2 >> 4) | (b3 << 4)) / 942 };
    });
    this.onUpdate?.();
  }
  async _send(flags, fill) {
    const c = new Uint8Array(10);
    c[0] = flags;
    fill(c);
    if (this.transport === 'bt') {
      const data = new Uint8Array(77);
      data[0] = 0xc0; // HID + CRC
      data[1] = 0x00;
      data.set(c, 2);
      await this.device.sendReport(0x11, sealBt(0x11, data));
    } else {
      const data = new Uint8Array(reportLength(this.device, 0x05) || 31);
      data.set(c, 0);
      await this.device.sendReport(0x05, data);
    }
  }
  setRumble(strong, weak) {
    return this._send(0x01, (c) => { c[3] = u8(weak); c[4] = u8(strong); });
  }
  setLightbar(r, g, b) {
    return this._send(0x02, (c) => { c[5] = r; c[6] = g; c[7] = b; });
  }
}

// ---------------------------------------------------------------- Switch
const NS_GYRO = 0.070; // deg/s per LSB (±2000 dps)
const NS_ACC = 1 / 4096; // g per LSB (±8 g)

function encodeSwitchRumble(amp, freqHigh = 320, freqLow = 160) {
  amp = clamp01(amp);
  if (amp <= 0.001) return [0x00, 0x01, 0x40, 0x40];
  const hfEnc = Math.round(Math.log2(freqHigh / 10) * 32);
  const lfEnc = Math.round(Math.log2(freqLow / 10) * 32);
  const hf = (hfEnc - 0x60) * 4;
  const lf = lfEnc - 0x40;
  let a;
  if (amp > 0.23) a = Math.round(Math.log2(amp * 8.7) * 32);
  else if (amp > 0.12) a = Math.round(Math.log2(amp * 17) * 16);
  else a = Math.round(Math.log2(amp * 17) * 16); // approx for very low values
  a = Math.max(1, Math.min(100, a));
  const hfAmp = a * 2;
  const lfAmp = Math.floor(a / 2) + 64;
  return [hf & 0xff, (hfAmp + ((hf >> 8) & 0xff)) & 0xff, (lf + ((lfAmp >> 8) & 0xff)) & 0xff, lfAmp & 0xff];
}

class SwitchPad extends HidPad {
  constructor(device) {
    super(device);
    this.counter = 0;
    this.rumble = [0x00, 0x01, 0x40, 0x40, 0x00, 0x01, 0x40, 0x40];
    this.got30 = false;
    this.gotAny = false;
    const p = device.productId;
    this.kind = p === 0x2006 ? 'joycon-l' : p === 0x2007 ? 'joycon-r' : p === 0x200e ? 'grip' : 'pro';
  }
  get brand() { return 'nintendo'; }
  get keepAliveMs() { return 100; }
  async init() {
    this.transport = hasReport(this.device, 0x80) ? 'usb' : 'bt';
    await sleep(300);
    if (!this.got30) {
      if (this.transport === 'usb' && !this.gotAny) {
        try {
          await this.device.sendReport(0x80, new Uint8Array([0x02])); await sleep(60);
          await this.device.sendReport(0x80, new Uint8Array([0x04])); await sleep(60);
        } catch {}
      }
      await this._subcmd(0x03, [0x30]); // full input report mode
      await sleep(60);
    }
    await this._subcmd(0x40, [0x01]); // enable IMU
    await sleep(60);
    await this._subcmd(0x48, [0x01]); // enable vibration
  }
  _pad(id, bytes, fallback) {
    const data = new Uint8Array(Math.max(reportLength(this.device, id) || fallback, bytes.length));
    data.set(bytes);
    return data;
  }
  async _subcmd(cmd, args) {
    const bytes = [this.counter++ & 0x0f, ...this.rumble, cmd, ...args];
    try { await this.device.sendReport(0x01, this._pad(0x01, bytes, 48)); } catch (e) { console.warn('switch subcmd', cmd, e); }
  }
  _handle(e) {
    this.gotAny = true;
    if (e.reportId !== 0x30) return;
    this.got30 = true;
    this._tick();
    const d = e.data;
    if (d.byteLength < 48) return;
    const bat = d.getUint8(1) >> 4;
    this.battery = { level: Math.min(100, ((bat >> 1) & 0x7) * 25), charging: !!(bat & 0x1) };
    this.transport = this.transport === '?' ? 'bt' : this.transport;
    const wall = this._wallDt();
    for (let i = 0; i < 3; i++) {
      const o = 12 + i * 12;
      const ax = d.getInt16(o, true), ay = d.getInt16(o + 2, true), az = d.getInt16(o + 4, true);
      const gx = d.getInt16(o + 6, true), gy = d.getInt16(o + 8, true), gz = d.getInt16(o + 10, true);
      // Switch axes: x forward, y left, z up  →  X right, Y up, Z toward player
      this._emit([-gy * NS_GYRO, gz * NS_GYRO, -gx * NS_GYRO], [-ay * NS_ACC, az * NS_ACC, -ax * NS_ACC],
        wall > 0 && wall < 0.05 ? wall / 3 : 0.005);
    }
    this.onUpdate?.();
  }
  async setRumble(strong, weak) {
    let l = strong, r = weak;
    if (this.kind === 'joycon-l' || this.kind === 'joycon-r') l = r = Math.max(strong, weak);
    // Left actuator gets a lower, beefier frequency pair to mimic the "strong" motor.
    const left = encodeSwitchRumble(l, 220, 120);
    const right = encodeSwitchRumble(r, 320, 160);
    this.rumble = [...left, ...right];
    const bytes = [this.counter++ & 0x0f, ...this.rumble];
    await this.device.sendReport(0x10, this._pad(0x10, bytes, 9));
  }
}

export function createHidPad(device) {
  if (device.vendorId === 0x057e) return new SwitchPad(device);
  if (device.productId === 0x0ce6 || device.productId === 0x0df2) return new DualSense(device);
  return new DualShock4(device);
}

export const hidSupported = () => 'hid' in navigator;
