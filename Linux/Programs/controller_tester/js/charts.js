// Canvas helpers: scrolling line graphs and stick visualisers.

function fit(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
  if (w && h && (canvas.width !== w || canvas.height !== h)) { canvas.width = w; canvas.height = h; }
  return { dpr, w: canvas.width, h: canvas.height };
}

const css = (name) => getComputedStyle(document.body).getPropertyValue(name).trim();

export class LineGraph {
  constructor(canvas, { series, min, max, length = 300, labels = [], unit = '', auto = false }) {
    this.c = canvas; this.ctx = canvas.getContext('2d');
    this.series = series; this.min = min; this.max = max; this.auto = auto;
    this.length = length; this.labels = labels; this.unit = unit;
    this.data = series.map(() => new Float32Array(length));
    this.head = 0;
  }
  push(values) {
    for (let i = 0; i < this.series.length; i++) this.data[i][this.head] = values[i] ?? 0;
    this.head = (this.head + 1) % this.length;
  }
  clear() { this.data.forEach((d) => d.fill(0)); }
  draw() {
    const { dpr, w, h } = fit(this.c);
    const ctx = this.ctx;
    ctx.clearRect(0, 0, w, h);
    let min = this.min, max = this.max;
    if (this.auto) {
      let m = 0;
      for (const d of this.data) for (const v of d) m = Math.max(m, Math.abs(v));
      max = Math.max(this.max, Math.ceil(m / 50) * 50); min = -max;
    }
    const y = (v) => h - ((v - min) / (max - min)) * h;
    ctx.lineWidth = 1 * dpr;
    ctx.strokeStyle = '#ffffff10';
    for (let i = 0; i <= 4; i++) { const yy = Math.round((h * i) / 4) + 0.5; ctx.beginPath(); ctx.moveTo(0, yy); ctx.lineTo(w, yy); ctx.stroke(); }
    if (min < 0 && max > 0) { ctx.strokeStyle = '#ffffff22'; ctx.beginPath(); ctx.moveTo(0, y(0)); ctx.lineTo(w, y(0)); ctx.stroke(); }
    ctx.lineWidth = 2 * dpr; ctx.lineJoin = 'round';
    this.series.forEach((color, si) => {
      const d = this.data[si];
      ctx.strokeStyle = color.startsWith('--') ? css(color) : color;
      ctx.beginPath();
      for (let i = 0; i < this.length; i++) {
        const v = d[(this.head + i) % this.length];
        const xx = (i / (this.length - 1)) * w, yy = y(Math.max(min, Math.min(max, v)));
        i ? ctx.lineTo(xx, yy) : ctx.moveTo(xx, yy);
      }
      ctx.stroke();
    });
    ctx.font = `${11 * dpr}px ui-monospace, monospace`;
    ctx.fillStyle = '#8a93a8';
    ctx.fillText(`${+max.toFixed(2)}${this.unit}`, 6 * dpr, 13 * dpr);
    ctx.fillText(`${+min.toFixed(2)}${this.unit}`, 6 * dpr, h - 6 * dpr);
    let lx = w - 8 * dpr;
    for (let i = this.labels.length - 1; i >= 0; i--) {
      const t = this.labels[i];
      const tw = ctx.measureText(t).width;
      lx -= tw;
      const col = this.series[i];
      ctx.fillStyle = col.startsWith('--') ? css(col) : col;
      ctx.fillText(t, lx, 13 * dpr);
      lx -= 10 * dpr;
    }
  }
}

export class StickView {
  constructor(canvas, label) {
    this.c = canvas; this.ctx = canvas.getContext('2d'); this.label = label;
    this.trail = [];
    this.reset();
  }
  reset() {
    this.buckets = new Float32Array(72);
    this.maxMag = 0;
  }
  // circularity: avg deviation of outer edge from the unit circle over sampled angles
  circularity() {
    let n = 0, err = 0;
    for (const m of this.buckets) if (m > 0.5) { n++; err += Math.abs(m - 1); }
    return n >= 36 ? { err: (err / n) * 100, coverage: n / 72 } : { err: null, coverage: n / 72 };
  }
  update(x, y, pressed) {
    const mag = Math.hypot(x, y);
    this.maxMag = Math.max(this.maxMag, mag);
    if (mag > 0.5) {
      const a = Math.atan2(y, x);
      const b = Math.floor(((a + Math.PI) / (2 * Math.PI)) * 72) % 72;
      this.buckets[b] = Math.max(this.buckets[b], mag);
    }
    this.trail.push([x, y]);
    if (this.trail.length > 40) this.trail.shift();
    this.draw(x, y, pressed);
  }
  draw(x, y, pressed) {
    const { dpr, w, h } = fit(this.c);
    const ctx = this.ctx;
    const accent = css('--accent');
    const r = Math.min(w, h) / 2 - 10 * dpr, cx = w / 2, cy = h / 2;
    ctx.clearRect(0, 0, w, h);
    // backdrop
    ctx.fillStyle = '#0e1017'; ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = '#ffffff14'; ctx.lineWidth = 1 * dpr;
    for (const f of [0.25, 0.5, 0.75, 1]) { ctx.beginPath(); ctx.arc(cx, cy, r * f, 0, Math.PI * 2); ctx.stroke(); }
    ctx.beginPath(); ctx.moveTo(cx - r, cy); ctx.lineTo(cx + r, cy); ctx.moveTo(cx, cy - r); ctx.lineTo(cx, cy + r); ctx.stroke();
    // deadzone reference
    ctx.fillStyle = '#ffffff08'; ctx.beginPath(); ctx.arc(cx, cy, r * 0.1, 0, Math.PI * 2); ctx.fill();
    // circularity outline
    ctx.strokeStyle = accent; ctx.globalAlpha = 0.55; ctx.lineWidth = 2 * dpr; ctx.beginPath();
    let started = false;
    for (let i = 0; i <= 72; i++) {
      const m = this.buckets[i % 72];
      if (m <= 0.5) { started = false; continue; }
      const a = ((i % 72) + 0.5) / 72 * Math.PI * 2 - Math.PI;
      const px = cx + Math.cos(a) * m * r, py = cy + Math.sin(a) * m * r;
      started ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
      started = true;
    }
    ctx.stroke(); ctx.globalAlpha = 1;
    // trail
    for (let i = 1; i < this.trail.length; i++) {
      const [ax, ay] = this.trail[i - 1], [bx, by] = this.trail[i];
      ctx.strokeStyle = accent; ctx.globalAlpha = i / this.trail.length * 0.6; ctx.lineWidth = 3 * dpr;
      ctx.beginPath(); ctx.moveTo(cx + ax * r, cy + ay * r); ctx.lineTo(cx + bx * r, cy + by * r); ctx.stroke();
    }
    ctx.globalAlpha = 1;
    // crosshair to point
    const px = cx + x * r, py = cy + y * r;
    ctx.strokeStyle = '#ffffff30'; ctx.setLineDash([4 * dpr, 4 * dpr]);
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(px, py); ctx.stroke(); ctx.setLineDash([]);
    ctx.shadowColor = accent; ctx.shadowBlur = 16 * dpr;
    ctx.fillStyle = pressed ? '#fff' : accent;
    ctx.beginPath(); ctx.arc(px, py, (pressed ? 11 : 8) * dpr, 0, Math.PI * 2); ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = '#8a93a8'; ctx.font = `600 ${12 * dpr}px system-ui, sans-serif`;
    ctx.fillText(this.label, 10 * dpr, 18 * dpr);
  }
}
