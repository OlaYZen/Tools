// Real 3D controller view (three.js). Loads a .glb, splits its merged meshes into
// the physical parts (buttons, sticks, triggers…) by finding disconnected geometry
// islands, and animates each part from controller input.
//
// Model space for the DualSense profile: X = right, Y = toward the top edge,
// Z = out of the face (sticks point +Z).

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const DEG = Math.PI / 180;

// Island matching rules: an island belongs to a part when its bbox centre is
// within `tol` of `at` (x, y), its centre z is inside `z`, and its largest
// dimension is below `max`.
const FACE_Z = [0.2, 0.45];
export const PROFILES = {
  dualsense: {
    url: 'models/dualsense.glb',
    credit: { title: 'Playstation 5 Dualsense', author: 'AHarmlessPotato', url: 'https://sketchfab.com/3d-models/playstation-5-dualsense-878c1f882808477ab81c2fe86d5a3936', license: 'CC BY 4.0' },
    parts: [
      { key: 0, at: [0.62, 0.13], z: FACE_Z, tol: 0.045 }, // cross
      { key: 1, at: [0.77, 0.28], z: FACE_Z, tol: 0.045 }, // circle
      { key: 2, at: [0.48, 0.28], z: FACE_Z, tol: 0.045 }, // square
      { key: 3, at: [0.62, 0.42], z: FACE_Z, tol: 0.045 }, // triangle
      { key: 4, kind: 'bumper', at: [-0.62, 0.58], z: [0, 0.25], tol: 0.06 },
      { key: 5, kind: 'bumper', at: [0.62, 0.58], z: [0, 0.25], tol: 0.06 },
      { key: 6, kind: 'trigger', at: [-0.61, 0.53], z: [-0.3, 0], tol: 0.06 },
      { key: 7, kind: 'trigger', at: [0.61, 0.53], z: [-0.3, 0], tol: 0.06 },
      { key: 8, at: [-0.47, 0.49], z: FACE_Z, tol: 0.04 }, // create
      { key: 9, at: [0.47, 0.49], z: FACE_Z, tol: 0.04 }, // options
      { key: 10, kind: 'stick', at: [-0.32, 0], z: FACE_Z, tol: 0.06 },
      { key: 11, kind: 'stick', at: [0.32, 0], z: FACE_Z, tol: 0.06 },
      { key: 12, at: [-0.62, 0.38], z: FACE_Z, tol: 0.04 }, // d-pad up
      { key: 13, at: [-0.63, 0.18], z: FACE_Z, tol: 0.04 }, // down
      { key: 14, at: [-0.72, 0.28], z: FACE_Z, tol: 0.04 }, // left
      { key: 15, at: [-0.52, 0.27], z: FACE_Z, tol: 0.04 }, // right
      { key: 16, at: [0, 0.01], z: [0.18, 0.35], tol: 0.075, max: 0.16 }, // PS logo button
      { key: 17, kind: 'touchpad', at: [0, 0.41], z: [0.18, 0.35], tol: 0.04, max: 0.9 },
      { key: 'x-mute', at: [0, -0.1], z: [0.18, 0.3], tol: 0.03, max: 0.12 },
      { key: 'lightbar', kind: 'static', at: [0, 0.51], z: [0.18, 0.3], tol: 0.03, max: 0.9 },
    ],
    press: 0.014,
    stick: { pivotZ: 0.2, max: 22 * DEG, click: 0.02 },
    trigger: { hingeY: 0.63, hingeZ: -0.02, max: -26 * DEG },
    bumper: [0, -0.004, -0.018],
    touchpad: { x0: -0.36, x1: 0.36, y0: 0.6, y1: 0.24 },
    motors: { strong: [-0.6, -0.42], weak: [0.6, -0.42] },
    edge: { fn: [[-0.24, -0.24], [0.24, -0.24]], paddles: [[-0.64, -0.34, -24], [0.64, -0.34, 24]] },
    lightbar: '#2f6bff',
    view: { cam: [0, -1.4, 3.2], target: [0, 0.0, 0], fov: 30, tilt: 34 * DEG },
  },
};

// ------------------------------------------------------------------ geometry helpers
function islands(geometry) {
  const pos = geometry.attributes.position;
  const n = pos.count;
  const idx = geometry.index ? geometry.index.array : Uint32Array.from({ length: n }, (_, i) => i);
  // weld by position so UV seams don't split a part
  const rep = new Int32Array(n);
  const seen = new Map();
  for (let v = 0; v < n; v++) {
    const k = `${Math.round(pos.getX(v) * 1e5)},${Math.round(pos.getY(v) * 1e5)},${Math.round(pos.getZ(v) * 1e5)}`;
    const r = seen.get(k);
    if (r === undefined) { seen.set(k, v); rep[v] = v; } else rep[v] = r;
  }
  const par = Int32Array.from({ length: n }, (_, i) => i);
  const find = (x) => { while (par[x] !== x) { par[x] = par[par[x]]; x = par[x]; } return x; };
  const unite = (a, b) => { a = find(a); b = find(b); if (a !== b) par[b] = a; };
  for (let t = 0; t < idx.length; t += 3) { unite(rep[idx[t]], rep[idx[t + 1]]); unite(rep[idx[t]], rep[idx[t + 2]]); }
  const map = new Map();
  for (let t = 0; t < idx.length; t += 3) {
    const r = find(rep[idx[t]]);
    let isl = map.get(r);
    if (!isl) { isl = { tris: [], min: [Infinity, Infinity, Infinity], max: [-Infinity, -Infinity, -Infinity] }; map.set(r, isl); }
    for (let k = 0; k < 3; k++) {
      const v = idx[t + k];
      isl.tris.push(v);
      const p = [pos.getX(v), pos.getY(v), pos.getZ(v)];
      for (let d = 0; d < 3; d++) { if (p[d] < isl.min[d]) isl.min[d] = p[d]; if (p[d] > isl.max[d]) isl.max[d] = p[d]; }
    }
  }
  return [...map.values()].map((i) => ({
    ...i,
    center: i.min.map((m, d) => (m + i.max[d]) / 2),
    size: Math.max(...i.min.map((m, d) => i.max[d] - m)),
  }));
}

function subGeometry(src, indices) {
  const g = new THREE.BufferGeometry();
  for (const [name, attr] of Object.entries(src.attributes)) g.setAttribute(name, attr);
  g.setIndex(new THREE.BufferAttribute(Uint32Array.from(indices), 1));
  g.computeBoundingBox();
  g.computeBoundingSphere();
  return g;
}

// Press highlight: a tinted copy of the part drawn on top. Normal blending so it
// shows on white plastic too (additive would just saturate to white).
const glowMaterial = (color, depthTest = true, additive = false) => new THREE.MeshBasicMaterial({
  color, transparent: true, opacity: 0, blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending,
  depthWrite: false, depthTest, depthFunc: THREE.LessEqualDepth,
  polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
});

// ------------------------------------------------------------------ Pad3D
export class Pad3D {
  static supported() {
    try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')); } catch { return false; }
  }

  constructor(container) {
    this.container = container;
    this.ready = false;
    this.parts = new Map();
    this.accent = new THREE.Color('#3d7bff');
    this.rumble = [0, 0, 0, 0];
    this.orient = null;
    this.drag = { yaw: 0, pitch: 0 };
    this.edge = false;
    this.t = 0;

    const r = this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
    r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    r.outputColorSpace = THREE.SRGBColorSpace;
    r.toneMapping = THREE.ACESFilmicToneMapping;
    r.toneMappingExposure = 1.05;
    container.appendChild(r.domElement);

    this.scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(r);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(1.5, -1.2, 3.5);
    this.scene.add(key);
    const rim = new THREE.DirectionalLight(0x9db8ff, 0.8);
    rim.position.set(-2, 2.5, 1);
    this.scene.add(rim);

    this.camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
    // rig: view (drag) → gyro → shake → model
    this.viewRig = new THREE.Group();
    this.gyroRig = new THREE.Group();
    this.shakeRig = new THREE.Group();
    this.model = new THREE.Group();
    this.scene.add(this.viewRig);
    this.viewRig.add(this.gyroRig);
    this.gyroRig.add(this.shakeRig);
    this.shakeRig.add(this.model);

    this._bindDrag();
    this._ro = new ResizeObserver(() => this.resize());
    this._ro.observe(container);
  }

  async load(name = 'dualsense', onProgress) {
    const P = this.profile = PROFILES[name];
    const gltf = await new GLTFLoader().loadAsync(P.url, (e) => onProgress?.(e.total ? e.loaded / e.total : 0));
    const meshes = [];
    gltf.scene.traverse((o) => { if (o.isMesh) meshes.push(o); });

    const partData = new Map(); // key -> { rule, chunks: [{ src, material, indices }] , min, max }
    for (const mesh of meshes) {
      const mat = mesh.material;
      // Sketchfab exports these as BLEND; render opaque to avoid sorting artefacts.
      mat.transparent = false; mat.depthWrite = true; mat.alphaTest = 0.5;
      const body = [];
      for (const isl of islands(mesh.geometry)) {
        const rule = P.parts.find((p) =>
          Math.abs(isl.center[0] - p.at[0]) < p.tol && Math.abs(isl.center[1] - p.at[1]) < p.tol &&
          isl.center[2] > p.z[0] && isl.center[2] < p.z[1] && isl.size < (p.max ?? 0.32));
        if (!rule) { body.push(...isl.tris); continue; }
        let pd = partData.get(rule.key);
        if (!pd) { pd = { rule, chunks: [], min: [...isl.min], max: [...isl.max] }; partData.set(rule.key, pd); }
        pd.chunks.push({ src: mesh.geometry, material: mat, indices: isl.tris });
        for (let d = 0; d < 3; d++) { pd.min[d] = Math.min(pd.min[d], isl.min[d]); pd.max[d] = Math.max(pd.max[d], isl.max[d]); }
      }
      if (body.length) {
        const m = new THREE.Mesh(subGeometry(mesh.geometry, body), mat);
        m.userData.body = true;
        this.model.add(m);
      }
    }

    for (const [key, pd] of partData) this._makePart(key, pd);
    this._makeRings();
    this._makeTouch();
    this._makeEdgeExtras();
    this.setLightbar(P.lightbar, 0.85);

    this.viewRig.rotation.x = P.view.tilt;
    this.camera.fov = P.view.fov;
    this.camera.position.set(...P.view.cam);
    this.camera.lookAt(...P.view.target);
    this.resize();
    this.ready = true;
    this.missing = P.parts.filter((p) => !partData.has(p.key)).map((p) => p.key);
    if (this.missing.length) console.warn('[Pad3D] parts not found in model:', this.missing);
  }

  _makePart(key, pd) {
    const P = this.profile;
    const kind = pd.rule.kind || 'button';
    const c = pd.min.map((m, d) => (m + pd.max[d]) / 2);
    const pivot = new THREE.Group();
    if (kind === 'stick') pivot.position.set(c[0], c[1], P.stick.pivotZ);
    else if (kind === 'trigger') pivot.position.set(c[0], P.trigger.hingeY, P.trigger.hingeZ);
    else pivot.position.set(c[0], c[1], c[2]);
    const glows = [];
    for (const ch of pd.chunks) {
      const geo = subGeometry(ch.src, ch.indices);
      const m = new THREE.Mesh(geo, ch.material);
      m.position.copy(pivot.position).negate();
      pivot.add(m);
      const g = new THREE.Mesh(geo, glowMaterial(this.accent));
      g.position.copy(m.position);
      g.renderOrder = 2;
      pivot.add(g);
      glows.push(g.material);
    }
    this.model.add(pivot);
    this.parts.set(key, { key, kind, pivot, base: pivot.position.clone(), glows, glow: 0, target: 0, down: false, value: 0, x: 0, y: 0 });
  }

  _makeRings() {
    this.rings = {};
    for (const [k, [x, y]] of Object.entries(this.profile.motors)) {
      const list = [];
      for (let i = 0; i < 3; i++) {
        const m = new THREE.Mesh(new THREE.RingGeometry(0.9, 1, 64), glowMaterial(this.accent, false, true));
        m.position.set(x, y, 0.3);
        m.renderOrder = 5;
        this.shakeRig.add(m);
        list.push(m);
      }
      this.rings[k] = list;
    }
  }

  _makeTouch() {
    this.touchPts = [0, 1].map(() => {
      const m = new THREE.Mesh(new THREE.SphereGeometry(0.022, 20, 12), new THREE.MeshBasicMaterial({ color: this.accent, transparent: true, opacity: 0.95, depthTest: false }));
      m.renderOrder = 6;
      m.visible = false;
      this.model.add(m);
      return m;
    });
  }

  // DualSense Edge parts the base DualSense model doesn't have: Fn buttons and rear paddles.
  _makeEdgeExtras() {
    const E = this.profile.edge;
    if (!E) return;
    this.model.updateMatrixWorld(true);
    const bodies = this.model.children.filter((o) => o.userData.body);
    const ray = new THREE.Raycaster();
    const hit = (x, y, fromTop) => {
      ray.set(new THREE.Vector3(x, y, fromTop ? 3 : -3), new THREE.Vector3(0, 0, fromTop ? -1 : 1));
      return ray.intersectObjects(bodies, false)[0]?.point;
    };
    this.edgeGroup = new THREE.Group();
    this.edgeGroup.visible = false;
    this.model.add(this.edgeGroup);
    const add = (key, mesh, base) => {
      const pivot = new THREE.Group();
      pivot.position.copy(base);
      pivot.add(mesh);
      const glow = new THREE.Mesh(mesh.geometry, glowMaterial(this.accent, mesh.material.depthTest));
      glow.rotation.copy(mesh.rotation);
      glow.renderOrder = 7;
      pivot.add(glow);
      this.edgeGroup.add(pivot);
      this.parts.set(key, { key, kind: 'button', pivot, base: base.clone(), glows: [glow.material], glow: 0, target: 0, down: false, value: 0 });
    };
    E.fn.forEach(([x, y], i) => {
      const p = hit(x, y, true) || new THREE.Vector3(x, y, 0.24);
      const geo = new THREE.CapsuleGeometry(0.014, 0.05, 6, 12);
      const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0x15161a, roughness: 0.45, metalness: 0.1 }));
      m.rotation.z = Math.PI / 2;
      add(i ? 'x-fnr' : 'x-fnl', m, p.add(new THREE.Vector3(0, 0, 0.006)));
    });
    E.paddles.forEach(([x, y, rot], i) => {
      const p = hit(x, y, false) || new THREE.Vector3(x, y, -0.2);
      const geo = new THREE.CapsuleGeometry(0.035, 0.13, 6, 16);
      // rear paddles are hidden behind the body from this angle: draw them x-ray style
      const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: 0xaab3c5, transparent: true, opacity: 0.4, depthTest: false, depthWrite: false }));
      m.rotation.z = rot * DEG;
      m.renderOrder = 6;
      add(i ? 'x-backr' : 'x-backl', m, p.add(new THREE.Vector3(0, 0, -0.03)));
    });
  }

  _bindDrag() {
    const el = this.renderer.domElement;
    let last = null;
    el.addEventListener('pointerdown', (e) => { last = [e.clientX, e.clientY]; el.setPointerCapture(e.pointerId); el.classList.add('dragging'); });
    el.addEventListener('pointermove', (e) => {
      if (!last) return;
      this.drag.yaw += (e.clientX - last[0]) * 0.008;
      this.drag.pitch += (e.clientY - last[1]) * 0.008;
      this.drag.pitch = Math.max(-1.4, Math.min(1.4, this.drag.pitch));
      last = [e.clientX, e.clientY];
    });
    const end = () => { last = null; el.classList.remove('dragging'); };
    el.addEventListener('pointerup', end);
    el.addEventListener('pointercancel', end);
    el.addEventListener('dblclick', () => { this.drag.yaw = 0; this.drag.pitch = 0; });
  }

  resize() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    // keep the whole controller in frame on narrow screens
    this.camera.zoom = Math.min(1, (w / h) / 1.25);
    this.camera.updateProjectionMatrix();
  }

  // ---------------------------------------------------------------- input
  setAccent(css) {
    if (!css) return;
    this.accent.set(css.trim());
    for (const p of this.parts.values()) if (p.key !== 'lightbar') p.glows.forEach((g) => g.color.copy(this.accent));
    Object.values(this.rings || {}).flat().forEach((r) => r.material.color.copy(this.accent));
    this.touchPts?.forEach((t) => t.material.color.copy(this.accent));
  }
  setEdge(on) { if (this.edgeGroup) this.edgeGroup.visible = !!on; this.edge = !!on; }
  setButton(key, down, value = down ? 1 : 0) {
    const p = this.parts.get(key);
    if (!p) return;
    p.down = down; p.value = value;
  }
  setStick(side, x, y) {
    const p = this.parts.get(side === 'l' ? 10 : 11);
    if (p) { p.x = x; p.y = y; }
  }
  setTrigger(idx, v) {
    const p = this.parts.get(idx);
    if (p) { p.value = v; p.down = v > 0.05; }
  }
  setRumble(levels) { this.rumble = levels; }
  setOrientation(o) { this.orient = o; }
  setTouch(points) {
    const T = this.profile?.touchpad;
    if (!T) return;
    this.touchPts.forEach((m, i) => {
      const t = points?.[i];
      m.visible = !!t?.active;
      if (t?.active) m.position.set(T.x0 + (T.x1 - T.x0) * t.x, T.y0 + (T.y1 - T.y0) * t.y, 0.33);
    });
  }
  setLightbar(hex, opacity = 0.9) {
    const p = this.parts.get('lightbar');
    if (!p) return;
    p.glows.forEach((g) => { g.color.set(hex); g.opacity = opacity; });
    p.fixed = true;
  }

  // ---------------------------------------------------------------- frame
  render(dt = 1 / 60) {
    if (!this.ready) return;
    this.t += dt;
    const P = this.profile;
    const ease = 1 - Math.pow(0.0005, dt); // smooth, frame-rate independent

    for (const p of this.parts.values()) {
      if (p.fixed) continue;
      const pos = p.base.clone();
      let glowTarget = p.down ? 0.7 : 0;
      switch (p.kind) {
        case 'stick':
          p.pivot.rotation.set(p.y * P.stick.max, p.x * P.stick.max, 0);
          if (p.down) pos.z -= P.stick.click;
          if (!p.down) glowTarget = Math.min(0.35, Math.hypot(p.x, p.y) * 0.4);
          break;
        case 'trigger': {
          p.pivot.rotation.x = p.value * P.trigger.max;
          glowTarget = p.value * 0.6;
          const tr = this.rumble[p.key === 6 ? 2 : 3] || 0;
          if (tr > 0.01) glowTarget = Math.max(glowTarget, tr * (0.35 + 0.25 * Math.sin(this.t * 40)));
          break;
        }
        case 'bumper':
          if (p.down) pos.add(new THREE.Vector3(...P.bumper));
          break;
        case 'touchpad':
          if (p.down) pos.z -= P.press * 0.5;
          glowTarget = p.down ? 0.35 : 0;
          break;
        default:
          if (p.down) pos.z -= P.press;
      }
      p.pivot.position.lerp(pos, ease);
      p.glow += (glowTarget - p.glow) * ease;
      p.glows.forEach((g) => { g.opacity = p.glow; });
    }

    // rumble: shake + ripple rings at the grips
    const [s, w] = this.rumble;
    const amp = s * 0.016 + w * 0.008;
    if (amp > 0.0005) {
      this.shakeRig.position.set((Math.random() - 0.5) * amp, (Math.random() - 0.5) * amp, 0);
      this.shakeRig.rotation.z = (Math.random() - 0.5) * amp * 0.6;
    } else { this.shakeRig.position.set(0, 0, 0); this.shakeRig.rotation.z = 0; }
    for (const [k, v, speed] of [['strong', s, 1.1], ['weak', w, 2.2]]) {
      this.rings[k].forEach((r, i) => {
        const ph = (this.t * speed + i / 3) % 1;
        const sc = 0.03 + ph * 0.17;
        r.scale.set(sc, sc, sc);
        r.material.opacity = v > 0.01 ? (1 - ph) * v * 0.6 : 0;
      });
    }

    // orientation: gyro pose (or gentle parallax) + user drag
    const o = this.orient || { pitch: 0, yaw: 0, roll: 0 };
    // motion frame (X right, Y out of face, Z toward player) → model frame (X, Z, -Y)
    this.gyroRig.rotation.set(o.pitch * DEG, -o.roll * DEG, o.yaw * DEG, 'ZXY');
    this.viewRig.rotation.set(P.view.tilt + this.drag.pitch, this.drag.yaw, 0, 'YXZ');

    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    this._ro.disconnect();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
