// Orientation estimate from gyro + accelerometer (Mahony-style complementary filter).
// Frame: X right, Y up (out of the controller face), Z toward the player.

const D2R = Math.PI / 180;
const R2D = 180 / Math.PI;

function qmul(a, b) {
  return [
    a[0] * b[0] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3],
    a[0] * b[1] + a[1] * b[0] + a[2] * b[3] - a[3] * b[2],
    a[0] * b[2] - a[1] * b[3] + a[2] * b[0] + a[3] * b[1],
    a[0] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[0],
  ];
}
function qnorm(q) {
  const n = Math.hypot(q[0], q[1], q[2], q[3]) || 1;
  return q.map((v) => v / n);
}
function qmat(q) {
  const [w, x, y, z] = q;
  return [
    [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
    [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
    [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
  ];
}
function mtmul(a, b) { // aᵀ·b
  const r = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++)
    for (let k = 0; k < 3; k++) r[i][j] += a[k][i] * b[k][j];
  return r;
}

export class Motion {
  constructor() { this.reset(); }

  reset() {
    this.q = [1, 0, 0, 0];
    this.ref = [1, 0, 0, 0];
    this.bias = [0, 0, 0];
    this.gyro = [0, 0, 0];
    this.accel = [0, 0, 0];
    this.inited = false;
    this.samples = 0;
    this.calib = null;
    this.calibMsg = '';
    this.pendingRecenter = true;
  }

  push({ gyro, accel, dt }) {
    this.samples++;
    if (this.calib) this._calibSample(gyro);
    const g = [gyro[0] - this.bias[0], gyro[1] - this.bias[1], gyro[2] - this.bias[2]];
    this.gyro = g;
    this.accel = accel;

    const an = Math.hypot(accel[0], accel[1], accel[2]);
    if (!this.inited) {
      if (an < 0.5) return;
      this.q = fromTwoVectors(accel.map((v) => v / an), [0, 1, 0]);
      this.inited = true;
      return;
    }

    let gx = g[0] * D2R, gy = g[1] * D2R, gz = g[2] * D2R;
    if (an > 0.75 && an < 1.25) {
      const a = accel.map((v) => v / an);
      const [w, x, y, z] = this.q;
      // estimated "up" in body frame = Rᵀ·(0,1,0)
      const v = [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)];
      const e = [a[1] * v[2] - a[2] * v[1], a[2] * v[0] - a[0] * v[2], a[0] * v[1] - a[1] * v[0]];
      const kp = 1.2;
      gx += kp * e[0]; gy += kp * e[1]; gz += kp * e[2];
    }
    const dq = qmul(this.q, [0, gx, gy, gz]);
    this.q = qnorm(this.q.map((v, i) => v + 0.5 * dq[i] * dt));

    if (this.pendingRecenter && this.samples > 40) { this.recenter(); this.pendingRecenter = false; }
  }

  recenter() { this.ref = this.q.slice(); }

  // Euler angles (deg) of the current orientation relative to the recenter pose.
  // R = Ry(yaw)·Rx(pitch)·Rz(roll)
  euler() {
    const R = mtmul(qmat(this.ref), qmat(this.q));
    const pitch = Math.asin(Math.max(-1, Math.min(1, -R[1][2])));
    const roll = Math.atan2(R[1][0], R[1][1]);
    const yaw = Math.atan2(R[0][2], R[2][2]);
    return { pitch: pitch * R2D, yaw: yaw * R2D, roll: roll * R2D };
  }

  startCalibration(ms = 1500) {
    this.calib = { until: performance.now() + ms, n: 0, sum: [0, 0, 0], sq: [0, 0, 0] };
    this.calibMsg = 'Calibrating… keep the controller still';
  }

  _calibSample(raw) {
    const c = this.calib;
    for (let i = 0; i < 3; i++) { c.sum[i] += raw[i]; c.sq[i] += raw[i] * raw[i]; }
    c.n++;
    if (performance.now() < c.until) return;
    this.calib = null;
    if (c.n < 20) { this.calibMsg = 'Not enough samples. Try again.'; return; }
    const mean = c.sum.map((s) => s / c.n);
    const sd = c.sq.map((s, i) => Math.sqrt(Math.max(0, s / c.n - mean[i] * mean[i])));
    if (Math.max(...sd) > 2.5) { this.calibMsg = 'The controller moved during calibration. Set it down and try again.'; return; }
    this.bias = mean;
    this.calibMsg = `Gyro calibrated (bias ${mean.map((v) => v.toFixed(2)).join(', ')} °/s)`;
    this.recenter();
  }
}

function fromTwoVectors(u, v) {
  const d = u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
  if (d < -0.9999) return [0, 1, 0, 0];
  const c = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  return qnorm([1 + d, c[0], c[1], c[2]]);
}
