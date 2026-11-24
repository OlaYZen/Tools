// Rumble engine: patterns, timed / unlimited playback, Gamepad API + WebHID backends.
//
// Unlimited mode: browsers cap a single Gamepad API effect at 5 s, so the engine
// keeps re-issuing the effect before it expires. For WebHID devices it re-sends
// the motor report at a keep-alive interval. Either way it runs until stopped.

const GP_MAX_MS = 5000;
const GP_KEEPALIVE_MS = 1000;
const MIN_SEND_GAP_MS = 35;

const PATTERNS = {
  constant: () => [1, 1, 1, 1],
  pulse: (t) => { const on = (t % 0.5) < 0.25 ? 1 : 0; return [on, on, on, on]; },
  heartbeat: (t) => { const p = t % 1.1; const on = p < 0.12 || (p > 0.24 && p < 0.38) ? 1 : 0; return [on, on, on, on]; },
  ramp: (t) => { const v = (t % 2) / 2; return [v, v, v, v]; },
  wave: (t) => { const v = 0.5 - 0.5 * Math.cos((2 * Math.PI * t) / 1.6); return [v, v, v, v]; },
  alternate: (t) => (t % 0.8) < 0.4 ? [1, 0, 1, 0] : [0, 1, 0, 1],
  quake: () => [0.35 + Math.random() * 0.65, 0.35 + Math.random() * 0.65, Math.random(), Math.random()],
};

export class RumbleEngine {
  constructor({ getGamepad, getHid, onState }) {
    this.getGamepad = getGamepad;
    this.getHid = getHid;
    this.onState = onState;
    this.levels = { strong: 1, weak: 1, lt: 0, rt: 0 };
    this.pattern = 'constant';
    this.backend = 'auto';
    this.run = null; // { mode, start, end, levels, pattern }
    this.current = [0, 0, 0, 0];
    this.lastSent = { gp: null, hid: null };
    this.lastSendAt = { gp: 0, hid: 0 };
    this.hidBusy = false;
    this.error = '';
    this.timer = setInterval(() => this.tick(), 20);
    document.addEventListener('visibilitychange', () => {
      // Chrome silences gamepad haptics while hidden; force a resend when we come back.
      if (!document.hidden) this.lastSent = { gp: null, hid: null };
    });
  }

  gamepadCaps(gp = this.getGamepad()) {
    const va = gp?.vibrationActuator;
    const legacy = gp?.hapticActuators?.[0];
    const effects = va?.effects;
    return {
      dual: !!va && (!effects || effects.includes('dual-rumble')),
      trigger: !!va && Array.isArray(effects) && effects.includes('trigger-rumble'),
      legacy: !va && !!legacy?.pulse,
    };
  }

  resolveBackend() {
    const gp = this.getGamepad();
    const hid = this.getHid();
    const caps = this.gamepadCaps(gp);
    const gpOk = gp && (caps.dual || caps.legacy);
    if (this.backend === 'gamepad') return gpOk ? 'gamepad' : null;
    if (this.backend === 'hid') return hid ? 'hid' : null;
    if (gpOk) return 'gamepad';
    if (hid) return 'hid';
    return null;
  }

  start(mode, durationMs = 1000, override = null) {
    const now = performance.now();
    this.run = {
      mode,
      start: now,
      end: mode === 'infinite' ? Infinity : now + durationMs,
      levels: override?.levels || null,
      pattern: override?.pattern || null,
    };
    this.lastSent = { gp: null, hid: null };
    this.tick();
  }

  stop() {
    this.run = null;
    this.current = [0, 0, 0, 0];
    const gp = this.getGamepad();
    try { gp?.vibrationActuator?.reset?.(); } catch {}
    try { gp?.hapticActuators?.[0]?.pulse?.(0, 1); } catch {}
    const hid = this.getHid();
    if (hid) hid.setRumble(0, 0).catch(() => {});
    this.lastSent = { gp: null, hid: null };
    this.emit();
  }

  get active() { return !!this.run; }
  get mode() { return this.run?.mode || null; }
  get elapsed() { return this.run ? (performance.now() - this.run.start) / 1000 : 0; }

  compute(now) {
    const r = this.run;
    const t = (now - r.start) / 1000;
    const lv = r.levels || this.levels;
    const fn = PATTERNS[r.pattern || this.pattern] || PATTERNS.constant;
    const m = fn(t);
    return [lv.strong * m[0], lv.weak * m[1], lv.lt * m[2], lv.rt * m[3]];
  }

  tick() {
    if (!this.run) return;
    const now = performance.now();
    if (now >= this.run.end) { this.stop(); return; }
    this.current = this.compute(now);
    const backend = this.resolveBackend();
    this.error = backend ? '' : 'No rumble-capable output for this controller.';
    if (backend === 'gamepad') this.sendGamepad(now);
    else if (backend === 'hid') this.sendHid(now);
    this.usedBackend = backend;
    this.emit();
  }

  changed(prev, cur) {
    return !prev || cur.some((v, i) => Math.abs(v - prev[i]) > 0.01);
  }

  sendGamepad(now) {
    const gp = this.getGamepad();
    if (!gp) return;
    const cur = this.current;
    const due = now - this.lastSendAt.gp >= GP_KEEPALIVE_MS;
    if (!(due || this.changed(this.lastSent.gp, cur))) return;
    if (now - this.lastSendAt.gp < MIN_SEND_GAP_MS) return;
    const remaining = this.run.end - now;
    const duration = Math.max(50, Math.min(GP_MAX_MS, remaining));
    const caps = this.gamepadCaps(gp);
    const [s, w, l, r] = cur;
    try {
      if (gp.vibrationActuator) {
        const useTrig = caps.trigger && (l > 0 || r > 0 || this.lastSent.gp?.[2] > 0 || this.lastSent.gp?.[3] > 0);
        const params = { startDelay: 0, duration, strongMagnitude: s, weakMagnitude: w };
        if (useTrig) Object.assign(params, { leftTrigger: l, rightTrigger: r });
        gp.vibrationActuator.playEffect(useTrig ? 'trigger-rumble' : 'dual-rumble', params)
          .catch((e) => { this.error = `Gamepad API: ${e.message || e}`; });
      } else if (caps.legacy) {
        gp.hapticActuators[0].pulse(Math.max(s, w), duration);
      }
    } catch (e) {
      this.error = `Gamepad API: ${e.message || e}`;
    }
    this.lastSent.gp = cur.slice();
    this.lastSendAt.gp = now;
  }

  sendHid(now) {
    const hid = this.getHid();
    if (!hid || this.hidBusy) return;
    const cur = this.current;
    const due = now - this.lastSendAt.hid >= hid.keepAliveMs;
    if (!(due || this.changed(this.lastSent.hid, cur))) return;
    if (now - this.lastSendAt.hid < MIN_SEND_GAP_MS) return;
    this.hidBusy = true;
    this.lastSent.hid = cur.slice();
    this.lastSendAt.hid = now;
    hid.setRumble(cur[0], cur[1])
      .catch((e) => { this.error = `WebHID: ${e.message || e}`; })
      .finally(() => { this.hidBusy = false; });
  }

  emit() { this.onState?.(this); }
}
