/* Jarvis holographic avatar: a man made of light filaments (head + shoulders + chest).
 *
 * - The body (contours + hundreds of energy filaments) is pre-rendered ONCE into a sprite.
 * - Per frame only the head (it turns: yaw/pitch), a few animated energy pulses, the chest core
 *   and some sparkles are drawn, so it stays light on integrated graphics.
 * - The head is a real 3D mesh (male face, sculpted hair) rotated and projected every frame.
 * - look("left"|"right"|"up"|"down"|"center") turns the head; it comes back after a while.
 */
(() => {
  "use strict";
  const TAU = Math.PI * 2;

  function rng(seed) {
    let s = seed >>> 0;
    return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  }

  const LOOK = {
    left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1], center: [0, 0],
    "up-left": [-0.8, -0.7], "up-right": [0.8, -0.7], "down-left": [-0.8, 0.7], "down-right": [0.8, 0.7],
  };

  // ---- head geometry (avatar units: 1 = canvas height; x right, y down, z towards the viewer) ----
  // y -> [frontal half-width, front depth, back depth]. Square male jaw, chin forward.
  const PROFILE = [
    [-0.150, 0.000, 0.000, 0.000],
    [-0.146, 0.034, 0.030, 0.040],
    [-0.138, 0.056, 0.052, 0.066],
    [-0.122, 0.076, 0.073, 0.090],
    [-0.100, 0.089, 0.089, 0.108],
    [-0.070, 0.097, 0.101, 0.121],
    [-0.035, 0.100, 0.109, 0.126],
    [0.000, 0.099, 0.112, 0.120],
    [0.030, 0.097, 0.112, 0.106],
    [0.060, 0.095, 0.110, 0.086],
    [0.090, 0.091, 0.105, 0.062],
    [0.110, 0.084, 0.100, 0.044],
    [0.128, 0.068, 0.095, 0.028],
    [0.142, 0.049, 0.089, 0.014],
    [0.152, 0.031, 0.082, 0.004],
    [0.158, 0.000, 0.072, 0.000],
  ];
  const EXP = 2.4;   // superellipse exponent of the horizontal sections (flatter face than an ellipse)

  function profile(y) {
    if (y <= PROFILE[0][0]) return [0, 0, 0];
    for (let i = 1; i < PROFILE.length; i++) {
      const b = PROFILE[i];
      if (y <= b[0]) {
        const a = PROFILE[i - 1], k = (y - a[0]) / (b[0] - a[0]);
        return [a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k, a[3] + (b[3] - a[3]) * k];
      }
    }
    const last = PROFILE[PROFILE.length - 1];
    return [0, last[2], 0];
  }

  function smooth(a, b, v) {
    const t = Math.min(1, Math.max(0, (v - a) / (b - a)));
    return t * t * (3 - 2 * t);
  }

  const G = (dx, dy) => Math.exp(-(dx * dx + dy * dy));

  // Relief of the face (added to the depth of the front surface).
  function bump(x, y) {
    const ax = Math.abs(x);
    let z = 0;
    z += 0.009 * Math.exp(-(((y + 0.037) / 0.010) ** 2)) * Math.exp(-((Math.max(0, ax - 0.055) / 0.012) ** 2)); // brow ridge
    z -= 0.013 * G((ax - 0.038) / 0.021, (y + 0.012) / 0.013);                                               // eye sockets
    const k = Math.min(1, Math.max(0, (y + 0.03) / 0.072));
    const w = 0.008 + 0.011 * k;
    const fade = smooth(-0.04, -0.025, y) * (1 - smooth(0.04, 0.056, y));
    z += (0.004 + 0.027 * k ** 1.6) * fade * Math.exp(-((x / w) ** 2));                                      // nose
    z += 0.007 * G((ax - 0.017) / 0.008, (y - 0.047) / 0.007);                                               // nostril wings
    z += 0.006 * G((ax - 0.058) / 0.02, (y - 0.012) / 0.015);                                                // cheekbones
    z += 0.006 * G(x / 0.028, (y - 0.075) / 0.008);                                                          // upper lip
    z += 0.007 * G(x / 0.024, (y - 0.091) / 0.008);                                                          // lower lip
    z += 0.009 * G(x / 0.032, (y - 0.13) / 0.016);                                                           // chin
    return z;
  }

  // Depth of the front of the face at (x, y), consistent with the mesh.
  function frontZ(x, y) {
    const [A, Cf] = profile(y);
    if (A <= 0) return 0;
    const u = Math.min(1, Math.abs(x) / A);
    const cz = Math.pow(1 - Math.pow(u, EXP), 1 / EXP);
    return Cf * cz + bump(x, y) * smooth(0.2, 0.7, cz);
  }

  // Indices of the convex hull of the points (monotone chain).
  function convexHull(xs, ys, count) {
    const idx = Array.from({ length: count }, (_, i) => i).sort((a, b) => xs[a] - xs[b] || ys[a] - ys[b]);
    const cross = (o, a, b) => (xs[a] - xs[o]) * (ys[b] - ys[o]) - (ys[a] - ys[o]) * (xs[b] - xs[o]);
    const lower = [], upper = [];
    for (const i of idx) {
      while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], i) <= 0) lower.pop();
      lower.push(i);
    }
    for (let k = idx.length - 1; k >= 0; k--) {
      const i = idx[k];
      while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], i) <= 0) upper.pop();
      upper.push(i);
    }
    upper.pop();
    lower.pop();
    return lower.concat(upper);
  }


  // ---- torso geometry (same units; y = 0.415 is the base of the neck) ----
  // y -> [half-width, front depth]. Broad chest, V-taper to the waist.
  const TORSO = [
    [0.415, 0.068, 0.045],
    [0.440, 0.140, 0.055],
    [0.470, 0.235, 0.072],
    [0.500, 0.290, 0.085],
    [0.540, 0.312, 0.098],
    [0.600, 0.315, 0.108],
    [0.660, 0.306, 0.108],
    [0.720, 0.290, 0.100],
    [0.800, 0.262, 0.094],
    [0.880, 0.242, 0.092],
    [0.960, 0.234, 0.092],
    [1.100, 0.238, 0.092],
  ];

  function torsoProfile(y) {
    if (y <= TORSO[0][0]) return [TORSO[0][1], TORSO[0][2]];
    for (let i = 1; i < TORSO.length; i++) {
      const b = TORSO[i];
      if (y <= b[0]) {
        const a = TORSO[i - 1], k = (y - a[0]) / (b[0] - a[0]);
        const e = k * k * (3 - 2 * k);
        return [a[1] + (b[1] - a[1]) * e, a[2] + (b[2] - a[2]) * e];
      }
    }
    const last = TORSO[TORSO.length - 1];
    return [last[1], last[2]];
  }

  // Muscle relief of the front of the torso.
  function torsoRelief(x, y) {
    const ax = Math.abs(x);
    let z = 0;
    // Pectorals: thicker towards the lower border (the "shelf"), which rises towards the armpit.
    const lower = 0.668 - 0.075 * (ax / 0.28) ** 2;
    const t = (y - 0.48) / (lower - 0.48);
    if (t > 0 && t < 1.08) {
      const xf = smooth(0.004, 0.03, ax) * (1 - smooth(0.25, 0.3, ax));
      z += 0.032 * Math.pow(Math.min(1, t), 0.65) * (1 - smooth(0.9, 1.06, t)) * xf;
    }
    z -= 0.006 * Math.exp(-((x / 0.012) ** 2)) * smooth(0.46, 0.5, y) * (1 - smooth(0.66, 0.7, y)); // sternum groove
    z += 0.008 * Math.exp(-(((y - 0.466 - 0.0008 * (ax / 0.01) ** 1.2) / 0.007) ** 2)) * (1 - smooth(0.24, 0.29, ax)); // collarbones
    // Six-pack: three rows of rounded blocks + the lower abs.
    for (const yc of [0.735, 0.812, 0.893, 0.985]) {
      const h = yc > 0.95 ? 0.009 : 0.013;
      z += h * Math.exp(-((((ax - 0.05) / 0.036) ** 4) + (((y - yc) / (yc > 0.95 ? 0.05 : 0.031)) ** 4)));
    }
    z -= 0.004 * Math.exp(-((x / 0.006) ** 2)) * smooth(0.69, 0.72, y);              // linea alba
    // Obliques and serratus.
    z += 0.008 * Math.exp(-((((ax - 0.19) / 0.04) ** 2) + (((y - 0.86) / 0.07) ** 2)));
    for (let k = 0; k < 3; k++) z += 0.004 * Math.exp(-((((ax - 0.235) / 0.016) ** 2) + (((y - 0.672 - k * 0.034) / 0.01) ** 2)));
    return z;
  }

  // Depth of the front of the torso at (x, y).
  function torsoZ(x, y) {
    const [w, d] = torsoProfile(y);
    const u = Math.min(1, Math.abs(x) / w);
    const cz = Math.pow(1 - Math.pow(u, 2.6), 1 / 2.6);
    return d * cz + torsoRelief(x, y) * smooth(0.1, 0.6, cz);
  }

  class Avatar {
    constructor(canvas) {
      this.canvas = canvas;
      this.g = canvas.getContext("2d");
      this.yaw = 0; this.pitch = 0;
      this.targetYaw = 0; this.targetPitch = 0;
      this.lookUntil = 0;
      this.state = "boot";
      this.level = 0;
      this.flowSpeed = 1;
      this.glow = 0.8;
      this.lowPower = false;
      this.gazeX = 0; this.gazeY = 0; this.sacX = 0; this.sacY = 0;
      this.nextSaccade = 0; this.nextBlink = 2; this.blinkAt = -9; this.blink = 0;
      this.nextGlitch = 4; this.glitchUntil = 0; this.lastState = "boot";
    }

    // ---------------------------------------------------------------------------------------
    resize(H, lowPower) {
      this.lowPower = lowPower;
      const dpr = Math.min(window.devicePixelRatio || 1, lowPower ? 1 : 1.25);
      const cssH = H * 0.86, cssW = H * 1.25;
      const c = this.canvas;
      c.style.height = `${cssH}px`;
      c.style.width = `${cssW}px`;
      c.style.top = `${H * 0.035}px`;
      c.width = Math.max(2, Math.round(cssW * dpr));
      c.height = Math.max(2, Math.round(cssH * dpr));
      this.s = c.height;          // 1 unit = avatar height
      this.cx = c.width / 2;
      this.buildBody();
      this.buildSprites();
      this.buildHead();
      this.font = (getComputedStyle(document.documentElement).getPropertyValue("--mono") || "").trim() || "monospace";
      const cw = this.canvas.width, ch = this.canvas.height;
      // Bloom only around the head (the focal point): about 7x cheaper than the whole canvas.
      const bs = this.s;
      this.bloomBox = [Math.max(0, Math.round(this.cx - 0.24 * bs)), 0, Math.round(0.48 * bs), Math.round(0.46 * bs)];
      this.bloom = document.createElement("canvas");
      this.bloom.width = Math.max(2, this.bloomBox[2] >> 2); this.bloom.height = Math.max(2, this.bloomBox[3] >> 2);
      this.bloomFrame = 0;
      this.fx = document.createElement("canvas");
      this.fx.width = cw; this.fx.height = ch;
      const sl = document.createElement("canvas");
      sl.width = 2; sl.height = 3;
      const slg = sl.getContext("2d");
      slg.fillStyle = "#000"; slg.fillRect(0, 2, 2, 1);
      this.scanPattern = this.g.createPattern(sl, "repeat");
    }

    P(x, y) { return [this.cx + x * this.s, y * this.s]; }

    // Static body: a muscular male torso + arms as a 3D hologram, rendered ONCE into two sprites:
    // `shade` (dark solid silhouette, drawn normally) and `body` (light lines, drawn additively).
    buildBody() {
      const { s, cx } = this;
      const lp = this.lowPower;
      const W = this.canvas.width, H = this.canvas.height;
      const TILT = 0.3;                                   // camera slightly above: front bulges render lower
      const scr = (x, y, z) => [cx + x * s, (y + z * TILT) * s];
      this.flows = [];

      // ---- geometry --------------------------------------------------------------------
      const ARM = { a0: [0.345, 0.545], a1: [0.402, 1.07] };
      const armLen = Math.hypot(ARM.a1[0] - ARM.a0[0], ARM.a1[1] - ARM.a0[1]);
      const ad = [(ARM.a1[0] - ARM.a0[0]) / armLen, (ARM.a1[1] - ARM.a0[1]) / armLen];
      const an = [ad[1], -ad[0]];                          // points outward (right arm)
      const armR = (t) => {                                // radius along the arm (t<0 = shoulder cap)
        if (t < 0) return 0.074 * Math.sqrt(Math.max(0, 1 - (t / 0.13) ** 2));
        return 0.074 - 0.014 * smooth(0, 0.28, t) + 0.007 * Math.exp(-(((t - 0.42) / 0.12) ** 2))
          - 0.012 * smooth(0.55, 0.78, t) + 0.004 * smooth(0.82, 1, t);
      };
      const armCenter = (side, t) => [side * (ARM.a0[0] + ad[0] * armLen * t), ARM.a0[1] + ad[1] * armLen * t];
      // Is the torso point (x, y) hidden behind an arm?
      const behindArm = (x, y) => {
        const side = x < 0 ? -1 : 1;
        const px = Math.abs(x) - ARM.a0[0], py = y - ARM.a0[1];
        const t = (px * ad[0] + py * ad[1]) / armLen;
        if (t < -0.13 || t > 1.05) return false;
        const c = armCenter(1, t);
        return Math.hypot(Math.abs(x) - c[0], y - c[1]) < armR(t) * 0.97 && side !== 0;
      };

      // ---- dark silhouette (shade sprite) -----------------------------------------------
      const shade = document.createElement("canvas");
      shade.width = W; shade.height = H;
      const sg = shade.getContext("2d");
      const sil = new Path2D();
      const rowsY = [];
      for (let y = 0.415; y <= 1.08; y += 0.01) rowsY.push(y);
      sil.moveTo(...scr(-torsoProfile(rowsY[0])[0], rowsY[0], 0));
      for (const y of rowsY) sil.lineTo(...scr(-torsoProfile(y)[0], y, 0));
      for (let i = rowsY.length - 1; i >= 0; i--) sil.lineTo(...scr(torsoProfile(rowsY[i])[0], rowsY[i], 0));
      sil.closePath();
      const armPath = (side) => {
        const p = new Path2D();
        const pts = [];
        for (let t = -0.13; t <= 1.05; t += 0.02) {
          const c = armCenter(side, t), r = armR(t);
          pts.push([c[0] + side * an[0] * r, c[1] + an[1] * r]);
        }
        for (let t = 1.05; t >= -0.13; t -= 0.02) {
          const c = armCenter(side, t), r = armR(t);
          pts.push([c[0] - side * an[0] * r, c[1] - an[1] * r]);
        }
        p.moveTo(...scr(pts[0][0], pts[0][1], 0.05));
        for (const q of pts) p.lineTo(...scr(q[0], q[1], 0.05));
        p.closePath();
        return p;
      };
      const shadeGrad = sg.createLinearGradient(0, 0.42 * s, 0, 1.0 * s);
      shadeGrad.addColorStop(0, "rgba(4,10,34,0.82)");
      shadeGrad.addColorStop(0.7, "rgba(3,8,28,0.7)");
      shadeGrad.addColorStop(1, "rgba(3,8,28,0)");
      sg.fillStyle = shadeGrad;
      sg.fill(sil); sg.fill(armPath(-1)); sg.fill(armPath(1));
      this.shade = shade;

      // ---- light lines (body sprite) ----------------------------------------------------
      const body = document.createElement("canvas");
      body.width = W; body.height = H;
      const g = body.getContext("2d");
      g.globalCompositeOperation = "lighter";
      g.lineCap = "round";
      g.lineJoin = "round";
      const B = 4, ALPHA = [0.07, 0.12, 0.2, 0.32];
      const buckets = Array.from({ length: B }, () => new Path2D());
      const add = (a, b, facing) => {
        const k = Math.min(B - 1, Math.max(0, Math.floor((1 - facing) * B)));
        buckets[k].moveTo(a[0], a[1]); buckets[k].lineTo(b[0], b[1]);
      };
      const torsoFacing = (x, y) => {
        const e = 0.003;
        const dx = (torsoZ(x + e, y) - torsoZ(x - e, y)) / (2 * e), dy = (torsoZ(x, y + e) - torsoZ(x, y - e)) / (2 * e);
        return 1 / Math.hypot(dx, dy, 1);
      };
      const T = (x, y) => scr(x, y, torsoZ(x, y));

      // Torso rings (horizontal sections) and meridians.
      const ringStep = lp ? 0.02 : 0.0115, cols = lp ? 26 : 44;
      for (let y = 0.42; y <= 1.07; y += ringStep) {
        const w = torsoProfile(y)[0];
        let prev = null, prevVis = false;
        for (let i = 0; i <= cols; i++) {
          const x = -w + (2 * w * i) / cols;
          const vis = !behindArm(x, y);
          const p = T(x, y);
          if (prev && vis && prevVis) add(prev, p, torsoFacing(x - w / cols, y));
          prev = p; prevVis = vis;
        }
      }
      const merid = lp ? 12 : 22;
      for (let i = 0; i <= merid; i++) {
        const u = -1 + (2 * i) / merid;
        let prev = null, prevVis = false;
        for (let y = 0.42; y <= 1.07; y += 0.01) {
          const x = u * torsoProfile(y)[0] * 0.995;
          const vis = !behindArm(x, y);
          const p = T(x, y);
          if (prev && vis && prevVis) add(prev, p, torsoFacing(x, y));
          prev = p; prevVis = vis;
        }
      }
      // Arm rings and meridians (cylinders: front half visible).
      for (const side of [-1, 1]) {
        const armPoint = (t, th) => {
          const c = armCenter(side, t), r = armR(t);
          const x = c[0] + side * an[0] * r * Math.sin(th), y = c[1] + an[1] * r * Math.sin(th);
          return [scr(x, y, r * Math.cos(th) + 0.05), Math.cos(th)];
        };
        const steps = lp ? 10 : 16;
        for (let t = -0.12; t <= 1.05; t += lp ? 0.05 : 0.03) {
          let prev = null;
          for (let k = 0; k <= steps; k++) {
            const [p, f] = armPoint(t, -Math.PI / 2 + (Math.PI * k) / steps);
            if (prev) add(prev, p, f);
            prev = p;
          }
        }
        for (let k = 1; k < steps; k += 2) {
          const th = -Math.PI / 2 + (Math.PI * k) / steps;
          let prev = null;
          for (let t = -0.12; t <= 1.05; t += 0.02) {
            const [p, f] = armPoint(t, th);
            if (prev) add(prev, p, f);
            prev = p;
          }
        }
      }
      g.lineWidth = Math.max(0.6, 0.0011 * s);
      g.strokeStyle = "rgba(110,165,255,1)";
      for (let k = 0; k < B; k++) { g.globalAlpha = ALPHA[k]; g.stroke(buckets[k]); }

      // Bright anatomical contours.
      const glowLine = (path, width, alpha, flow) => {
        g.globalAlpha = alpha * 0.22; g.strokeStyle = "rgba(80,140,255,1)"; g.lineWidth = width * 4.5; g.stroke(path);
        if (!lp) { g.shadowColor = "rgba(90,150,255,1)"; g.shadowBlur = 0.01 * s; }
        g.globalAlpha = alpha; g.strokeStyle = "rgba(230,242,255,1)"; g.lineWidth = width; g.stroke(path);
        g.shadowBlur = 0;
        if (flow) this.flows.push(path);
      };
      const surf = (pts) => {                     // smooth curve through points on the torso surface
        const pr = pts.map(([x, y]) => T(x, y));
        const p = new Path2D();
        p.moveTo(pr[0][0], pr[0][1]);
        for (let k = 1; k < pr.length - 1; k++) {
          const last = k === pr.length - 2;
          p.quadraticCurveTo(pr[k][0], pr[k][1], last ? pr[k + 1][0] : (pr[k][0] + pr[k + 1][0]) / 2,
            last ? pr[k + 1][1] : (pr[k][1] + pr[k + 1][1]) / 2);
        }
        if (pr.length === 2) p.lineTo(pr[1][0], pr[1][1]);
        return p;
      };
      const lw = Math.max(1.1, 0.0028 * s);
      // Outline of the torso (trapezius, lats, waist) and of the arms.
      for (const side of [-1, 1]) {
        const edge = new Path2D();
        let first = true;
        for (let y = 0.416; y <= 1.07; y += 0.008) {
          const x = side * torsoProfile(y)[0];
          if (behindArm(x * 0.999, y)) { first = true; continue; }
          const p = scr(x, y, 0);
          if (first) { edge.moveTo(p[0], p[1]); first = false; } else edge.lineTo(p[0], p[1]);
        }
        glowLine(edge, lw * 1.1, 0.85, true);
        for (const o of [1, -1]) {
          const ap = new Path2D();
          for (let t = -0.13, i = 0; t <= 1.05; t += 0.02, i++) {
            const c = armCenter(side, t), r = armR(t);
            const p = scr(c[0] + o * side * an[0] * r, c[1] + o * an[1] * r, 0.05);
            if (i === 0) ap.moveTo(p[0], p[1]); else ap.lineTo(p[0], p[1]);
          }
          glowLine(ap, lw * (o > 0 ? 1.1 : 0.8), o > 0 ? 0.85 : 0.5, o > 0);
        }
        // Deltoid front border and biceps.
        const arm = (t, f) => { const c = armCenter(side, t), r = armR(t); return [c[0] - side * an[0] * r * f, c[1] - an[1] * r * f]; };
        const delt = new Path2D();
        [[-0.1, 0.2], [0.05, 0.55], [0.18, 0.2], [0.27, -0.45]].forEach(([t, f], i) => {
          const q = arm(t, f), p = scr(q[0], q[1], 0.11);
          if (i === 0) delt.moveTo(p[0], p[1]); else delt.lineTo(p[0], p[1]);
        });
        glowLine(delt, lw * 0.85, 0.6, false);
        const bic = new Path2D();
        [[0.3, -0.25], [0.42, -0.05], [0.55, -0.2], [0.68, -0.35]].forEach(([t, f], i) => {
          const q = arm(t, f), p = scr(q[0], q[1], 0.11);
          if (i === 0) bic.moveTo(p[0], p[1]); else bic.lineTo(p[0], p[1]);
        });
        glowLine(bic, lw * 0.7, 0.4, false);

        // Collarbone (S-shaped), trapezius ridge.
        glowLine(surf([[side * 0.03, 0.468], [side * 0.11, 0.459], [side * 0.19, 0.468], [side * 0.265, 0.488]]), lw, 0.8, true);
        // Pectoral: lower border (the shelf) curving up into the armpit, faint upper fibres.
        glowLine(surf([[side * 0.016, 0.648], [side * 0.08, 0.668], [side * 0.15, 0.665], [side * 0.22, 0.635], [side * 0.27, 0.585], [side * 0.29, 0.54]]), lw * 1.25, 0.95, true);
        glowLine(surf([[side * 0.03, 0.5], [side * 0.12, 0.505], [side * 0.22, 0.525], [side * 0.285, 0.535]]), lw * 0.6, 0.28, false);
        // Abs: outer edge, three tendinous lines, obliques and the V lines.
        glowLine(surf([[side * 0.094, 0.7], [side * 0.1, 0.78], [side * 0.098, 0.87], [side * 0.088, 0.96], [side * 0.07, 1.04]]), lw * 0.9, 0.7, true);
        for (const [y, curve] of [[0.772, 0.006], [0.852, 0.004], [0.935, 0.002]]) {
          glowLine(surf([[side * 0.012, y], [side * 0.05, y + curve], [side * 0.092, y - 0.004]]), lw * 0.85, 0.6, false);
        }
        glowLine(surf([[side * 0.215, 0.8], [side * 0.19, 0.9], [side * 0.14, 0.98], [side * 0.085, 1.05]]), lw * 0.8, 0.5, false);
        for (let k = 0; k < 3; k++) {  // serratus
          glowLine(surf([[side * 0.245, 0.665 + k * 0.034], [side * 0.212, 0.685 + k * 0.034]]), lw * 0.6, 0.38, false);
        }
      }
      // Sternum / linea alba and navel.
      glowLine(surf([[0, 0.475], [0, 0.58], [0, 0.68], [0, 0.8], [0, 0.9], [0, 0.965]]), lw * 0.8, 0.55, true);
      const nav = T(0, 0.982);
      g.globalAlpha = 0.5; g.strokeStyle = "rgba(220,235,255,1)"; g.lineWidth = lw * 0.7;
      g.beginPath(); g.ellipse(nav[0], nav[1], 0.006 * s, 0.009 * s, 0, 0, TAU); g.stroke();

      // Energy filaments sweeping out from the shoulders (the "energy cape").
      const R = rng(42);
      const colors = ["rgba(120,170,255,1)", "rgba(150,120,255,1)", "rgba(90,200,255,1)"];
      const capes = lp ? 10 : 26;
      for (let i = 0; i < capes; i++) {
        const side = i % 2 ? 1 : -1;
        const y0 = 0.5 + R() * 0.1;
        const pts = [[side * (0.36 + R() * 0.05), y0], [side * (0.48 + R() * 0.08), y0 - 0.05 + R() * 0.08],
          [side * (0.54 + R() * 0.06), y0 + 0.08 + R() * 0.22], [side * (0.6 + R() * 0.1), y0 + 0.25 + R() * 0.3]];
        const path = new Path2D();
        path.moveTo(...this.P(...pts[0]));
        path.bezierCurveTo(...this.P(...pts[1]), ...this.P(...pts[2]), ...this.P(...pts[3]));
        g.globalAlpha = 0.05 + R() * 0.14;
        g.strokeStyle = colors[i % 3];
        g.lineWidth = Math.max(0.6, 0.0016 * s);
        g.stroke(path);
        if (i % 6 === 0) this.flows.push(path);
      }
      // Sparkle dust on the body.
      for (let i = 0; i < (lp ? 90 : 220); i++) {
        const y = 0.45 + R() * 0.58, x = (R() * 2 - 1) * torsoProfile(y)[0];
        const [px, py] = T(x, y);
        g.globalAlpha = 0.12 + R() * 0.45;
        g.fillStyle = R() < 0.75 ? "#dbe9ff" : "#9f8bff";
        g.fillRect(px, py, R() < 0.9 ? 1 : 2, R() < 0.9 ? 1 : 2);
      }
      // Fade the bottom of the bust into the background.
      g.globalAlpha = 1;
      g.globalCompositeOperation = "destination-out";
      const fade = g.createLinearGradient(0, 0.8 * s, 0, s);
      fade.addColorStop(0, "rgba(0,0,0,0)");
      fade.addColorStop(1, "rgba(0,0,0,1)");
      g.fillStyle = fade;
      g.fillRect(0, 0.8 * s, W, 0.2 * s);
      this.body = body;
    }

    buildSprites() {
      const make = (r, stops) => {
        const c = document.createElement("canvas");
        c.width = c.height = Math.max(2, Math.ceil(r * 2));
        const g = c.getContext("2d");
        const grad = g.createRadialGradient(r, r, 0, r, r, r);
        for (const [o, col] of stops) grad.addColorStop(o, col);
        g.fillStyle = grad;
        g.fillRect(0, 0, r * 2, r * 2);
        return c;
      };
      const s = this.s;
      this.coreSprite = make(0.09 * s, [[0, "rgba(255,255,255,1)"], [0.15, "rgba(170,210,255,0.9)"], [0.5, "rgba(80,120,255,0.3)"], [1, "rgba(60,80,255,0)"]]);
      this.eyeSprite = make(0.05 * s, [[0, "rgba(220,240,255,1)"], [0.3, "rgba(90,170,255,0.7)"], [1, "rgba(40,90,255,0)"]]);
      this.sparkSprite = make(0.012 * s, [[0, "rgba(255,255,255,1)"], [0.3, "rgba(170,200,255,0.7)"], [1, "rgba(80,100,255,0)"]]);
      this.haloSprite = make(0.45 * s, [[0, "rgba(60,110,255,0.35)"], [0.5, "rgba(40,70,220,0.12)"], [1, "rgba(20,30,160,0)"]]);
      const R = rng(9);
      this.sparks = Array.from({ length: this.lowPower ? 12 : 36 }, () => ({ x: (R() - 0.5) * 0.9, y: 0.4 + R() * 0.55, v: 0.005 + R() * 0.02, p: R() * TAU }));
    }

    // ---------------------------------------------------------------------------------------
    look(direction, seconds = 12) {
      const v = LOOK[direction] || LOOK.center;
      this.targetYaw = v[0];
      this.targetPitch = v[1];
      this.lookUntil = direction === "center" ? 0 : performance.now() + seconds * 1000;
    }

    update(dt, t) {
      if (this.lookUntil && performance.now() > this.lookUntil) { this.targetYaw = 0; this.targetPitch = 0; this.lookUntil = 0; }
      const idleYaw = 0.05 * Math.sin(t * 0.37), idlePitch = 0.03 * Math.sin(t * 0.29);
      const listenTilt = this.state === "listening" ? -0.08 : 0;
      const k = Math.min(1, dt * 3.2);
      this.yaw += (this.targetYaw + idleYaw - this.yaw) * k;
      this.pitch += (this.targetPitch + idlePitch + listenTilt - this.pitch) * k;
      const flowTarget = { thinking: 4, speaking: 1.6, listening: 1.3, paused: 0.3 }[this.state] || 1;
      this.flowSpeed += (flowTarget - this.flowSpeed) * Math.min(1, dt * 2);
      const glowTarget = { listening: 1, speaking: 1, thinking: 0.95, paused: 0.45, error: 0.7, boot: 0.6 }[this.state] || 0.85;
      this.glow += (glowTarget - this.glow) * Math.min(1, dt * 2);

      // Eyes: small saccades, gaze leads the head, natural blinks.
      if (t > this.nextSaccade) {
        this.sacX = (Math.random() - 0.5) * 0.5;
        this.sacY = (Math.random() - 0.5) * 0.35;
        this.nextSaccade = t + 1.2 + Math.random() * 3;
      }
      const gx = Math.max(-1, Math.min(1, this.targetYaw * 0.8 + this.sacX * (1 - Math.abs(this.targetYaw))));
      const gy = Math.max(-1, Math.min(1, this.targetPitch * 0.8 + this.sacY * (1 - Math.abs(this.targetPitch))));
      const ke = Math.min(1, dt * 14);
      this.gazeX += (gx - this.gazeX) * ke;
      this.gazeY += (gy - this.gazeY) * ke;
      if (t > this.nextBlink) {
        this.blinkAt = t;
        this.nextBlink = t + 2.5 + Math.random() * 4.5;
      }
      const bt = (t - this.blinkAt) / 0.18;
      this.blink = bt >= 0 && bt < 1 ? Math.sin(bt * Math.PI) : 0;
    }

    // ---------------------------------------------------------------------------------------
    draw(t, dt, level) {
      this.update(dt, t);
      if (!this.body || this.canvas.width < 4) return;
      const { g, s, cx } = this;
      const voice = this.state === "speaking" ? level : this.state === "listening" ? level * 0.5 : 0;
      g.clearRect(0, 0, this.canvas.width, this.canvas.height);
      const breathe = Math.sin(t * 0.9);
      // Solid dark silhouette (hides the light waves behind the body), then light on top.
      g.save();
      g.translate(cx, 0.6 * s);
      g.scale(1 + 0.004 * breathe, 1 + 0.004 * breathe);
      g.translate(-cx, -0.6 * s + 0.002 * s * breathe);
      g.globalCompositeOperation = "source-over";
      g.globalAlpha = 1;
      g.drawImage(this.shade, 0, 0);
      g.restore();
      g.globalCompositeOperation = "lighter";

      // Soft halo behind the figure.
      g.globalAlpha = 0.55 * this.glow;
      const h = this.haloSprite;
      g.drawImage(h, cx - h.width / 2, 0.45 * s - h.height / 2);

      // Body sprite (slight breathing).
      g.save();
      g.translate(cx, 0.6 * s);
      const sc = 1 + 0.004 * breathe;
      g.scale(sc, sc);
      g.translate(-cx, -0.6 * s + 0.002 * s * breathe);
      g.globalAlpha = 0.85 * this.glow + 0.15;
      g.drawImage(this.body, 0, 0);
      g.restore();

      // Energy pulses running along some filaments.
      g.globalAlpha = 0.9 * this.glow;
      g.strokeStyle = "rgba(220,235,255,1)";
      g.lineWidth = Math.max(1, 0.0026 * s);
      g.setLineDash([0.03 * s, 0.25 * s]);
      g.lineDashOffset = -t * 0.12 * s * this.flowSpeed;
      for (const path of this.flows) g.stroke(path);
      g.setLineDash([]);

      // Chest core (pulses with the voice).
      const core = this.coreSprite;
      const coreScale = 0.38 + 0.05 * breathe + voice * 0.7 + (this.state === "thinking" ? 0.15 * Math.sin(t * 8) : 0);
      g.globalAlpha = Math.min(1, 0.55 + voice * 0.8) * this.glow;
      g.drawImage(core, cx - core.width * coreScale / 2, 0.585 * s - core.height * coreScale / 2, core.width * coreScale, core.height * coreScale);

      // Hexagonal power core: two counter-rotating hexagons + a ring of ticks, pulsing with the voice.
      {
        const ccy = 0.6 * s, R0 = (0.026 + voice * 0.012 + (this.state === "thinking" ? 0.004 * Math.sin(t * 8) : 0)) * s;
        const hex = (r, a0) => {
          const p = new Path2D();
          for (let k = 0; k <= 6; k++) {
            const a = a0 + k * TAU / 6;
            if (k === 0) p.moveTo(cx + Math.cos(a) * r, ccy + Math.sin(a) * r); else p.lineTo(cx + Math.cos(a) * r, ccy + Math.sin(a) * r);
          }
          return p;
        };
        const h1 = hex(R0, t * 0.5), h2 = hex(R0 * 0.6, -t * 0.8);
        g.lineWidth = Math.max(1, 0.0022 * s);
        g.globalAlpha = 0.3 * this.glow; g.strokeStyle = "rgba(80,170,255,1)"; g.lineWidth = Math.max(2, 0.008 * s); g.stroke(h1);
        g.globalAlpha = 0.9 * this.glow; g.strokeStyle = "rgba(210,240,255,1)"; g.lineWidth = Math.max(1, 0.002 * s); g.stroke(h1); g.stroke(h2);
        g.globalAlpha = 0.55 * this.glow;
        g.beginPath();
        for (let k = 0; k < 24; k++) {
          const a = k * TAU / 24 - t * 0.3, r1 = R0 * 1.45, r2 = R0 * (k % 6 === 0 ? 1.85 : 1.6);
          g.moveTo(cx + Math.cos(a) * r1, ccy + Math.sin(a) * r1); g.lineTo(cx + Math.cos(a) * r2, ccy + Math.sin(a) * r2);
        }
        g.stroke();
      }

      // Sparkles drifting upward.
      if (!this.lowPower) {
        for (const p of this.sparks) {
          p.y -= p.v * dt * this.flowSpeed;
          if (p.y < 0.38) p.y = 1.0;
          g.globalAlpha = (0.35 + 0.65 * Math.abs(Math.sin(t * 2 + p.p))) * this.glow;
          const sp = this.sparkSprite;
          g.drawImage(sp, cx + p.x * s - sp.width / 2, p.y * s - sp.height / 2);
        }
      }

      this.drawHead(t, voice);
      g.globalCompositeOperation = "lighter";
      this.drawCallouts(t, voice);
      this.postFX(t);
    }

    // ---- 3D head ---------------------------------------------------------------------------
    // A lat/long mesh of a male head (profile table + facial relief), rotated and projected each
    // frame. Faint mesh lines (brighter near the silhouette, like a hologram) + bright features.
    buildHead() {
      const rows = this.lowPower ? 16 : 26, cols = this.lowPower ? 22 : 36;
      const n = rows * cols;
      const P = new Float32Array(n * 3), N = new Float32Array(n * 3), hair = new Float32Array(n);
      const pw = (v, e) => Math.sign(v) * Math.pow(Math.abs(v), e);
      for (let i = 0; i < rows; i++) {
        const y = -0.15 + 0.308 * (1 - Math.cos(Math.PI * (i + 0.5) / rows)) / 2;
        const [A, Cf, Cb] = profile(y);
        for (let j = 0; j < cols; j++) {
          const ph = TAU * j / cols;                       // j = 0 is the front of the face
          const sx = pw(Math.sin(ph), 2 / EXP), cz = pw(Math.cos(ph), 2 / EXP);
          const x = A * sx;
          let z = (cz >= 0 ? Cf : Cb) * cz;
          if (cz > 0) z += bump(x, y) * smooth(0.2, 0.7, cz);
          const v = i * cols + j;
          P[v * 3] = x; P[v * 3 + 1] = y; P[v * 3 + 2] = z;
          const front = Math.max(0, Math.cos(ph));
          const hairY = -0.09 + 0.075 * Math.pow((1 - Math.cos(ph)) / 2, 0.7) - 0.022 * Math.pow(Math.sin(2 * ph), 2) * front;
          hair[v] = smooth(hairY + 0.008, hairY - 0.008, y);
        }
      }
      for (let i = 0; i < rows; i++) {
        for (let j = 0; j < cols; j++) {
          const a = (i * cols + (j + 1) % cols) * 3, b = (i * cols + (j - 1 + cols) % cols) * 3;
          const c = (Math.min(rows - 1, i + 1) * cols + j) * 3, d = (Math.max(0, i - 1) * cols + j) * 3;
          const ux = P[a] - P[b], uy = P[a + 1] - P[b + 1], uz = P[a + 2] - P[b + 2];
          const vx = P[c] - P[d], vy = P[c + 1] - P[d + 1], vz = P[c + 2] - P[d + 2];
          let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
          const v = (i * cols + j) * 3;
          if (nx * P[v] + ny * P[v + 1] + nz * P[v + 2] < 0) { nx = -nx; ny = -ny; nz = -nz; }
          const len = Math.hypot(nx, ny, nz) || 1;
          N[v] = nx / len; N[v + 1] = ny / len; N[v + 2] = nz / len;
        }
      }
      for (let v = 0; v < n; v++) {   // hair volume: push the hair area out a little
        const h = hair[v] * 0.005;
        P[v * 3] += N[v * 3] * h; P[v * 3 + 1] += N[v * 3 + 1] * h; P[v * 3 + 2] += N[v * 3 + 2] * h;
      }
      this.head = { rows, cols, n, P, N, hair, X: new Float32Array(n), Y: new Float32Array(n), F: new Float32Array(n) };
    }

    drawHead(t, voice) {
      const { g, s, cx } = this;
      const H = this.head;
      if (!H) return;
      const glow = this.glow;
      const ay = this.yaw * 0.62, ap = this.pitch * 0.38;
      const cY = Math.cos(ay), sY = Math.sin(ay), cP = Math.cos(ap), sP = Math.sin(ap);
      const HS = 1.12;                                  // head scale (proportion to the shoulders)
      const hx = this.yaw * 0.012, hy = 0.2 + this.pitch * 0.008;
      const proj = (x, y, z) => {
        const x1 = x * cY + z * sY, z1 = -x * sY + z * cY;
        const y2 = y * cP + z1 * sP, z2 = -y * sP + z1 * cP;
        const f = 1 / (1 - z2 * 0.8);
        return [cx + (hx + x1 * f * HS) * s, (hy + y2 * f * HS) * s, z2];
      };
      const facing = (nx, ny, nz) => -ny * sP + (-nx * sY + nz * cY) * cP;
      const face = (x, y, lift = 0.0015) => {   // point on the face surface -> [X, Y, depth, facing]
        const e = 0.002;
        const dx = (frontZ(x + e, y) - frontZ(x - e, y)) / (2 * e), dy = (frontZ(x, y + e) - frontZ(x, y - e)) / (2 * e);
        const l = Math.hypot(dx, dy, 1);
        const p = proj(x, y, frontZ(x, y) + lift);
        p.push(facing(-dx / l, -dy / l, 1 / l));
        return p;
      };

      // Project the mesh.
      const { rows, cols, n, P, N, hair, X, Y, F } = H;
      for (let v = 0; v < n; v++) {
        const k = v * 3, x = P[k], y = P[k + 1], z = P[k + 2];
        const x1 = x * cY + z * sY, z1 = -x * sY + z * cY;
        const y2 = y * cP + z1 * sP, z2 = -y * sP + z1 * cP;
        const f = 1 / (1 - z2 * 0.8);
        X[v] = cx + (hx + x1 * f * HS) * s; Y[v] = (hy + y2 * f * HS) * s;
        F[v] = facing(N[k], N[k + 1], N[k + 2]);
      }

      // Neck (behind the head): dark fill, side contours, sternocleidomastoid "V".
      const rimW = Math.max(1.4, 0.0042 * s);
      const nl = proj(-0.066, 0.08, -0.045), nr = proj(0.066, 0.08, -0.045);
      const neck = new Path2D();
      neck.moveTo(nl[0], nl[1]);
      neck.bezierCurveTo(nl[0], nl[1] + 0.09 * s, cx - 0.06 * s, 0.37 * s, cx - 0.07 * s, 0.435 * s);
      neck.lineTo(cx + 0.07 * s, 0.435 * s);
      neck.bezierCurveTo(cx + 0.06 * s, 0.37 * s, nr[0], nr[1] + 0.09 * s, nr[0], nr[1]);
      neck.closePath();
      g.globalCompositeOperation = "source-over";
      g.globalAlpha = 0.85;
      g.fillStyle = "rgba(4,10,34,1)";
      g.fill(neck);
      g.globalCompositeOperation = "lighter";
      for (const side of [-1, 1]) {
        const e = proj(side * 0.084, 0.055, -0.04);
        const scm = new Path2D();
        scm.moveTo(e[0], e[1]);
        scm.bezierCurveTo(e[0] - side * 0.004 * s, e[1] + 0.07 * s, cx + side * 0.03 * s, 0.43 * s, cx + side * 0.016 * s, 0.474 * s);
        g.globalAlpha = 0.18 * glow; g.lineWidth = rimW * 2.5; g.strokeStyle = "rgba(80,140,255,1)"; g.stroke(scm);
        g.globalAlpha = 0.55 * glow; g.lineWidth = rimW * 0.5; g.strokeStyle = "rgba(220,238,255,1)"; g.stroke(scm);
      }
      for (const side of [-1, 1]) {
        const a = proj(side * 0.066, 0.08, -0.045);
        const p = new Path2D();
        p.moveTo(a[0], a[1]);
        p.bezierCurveTo(a[0], a[1] + 0.09 * s, cx + side * 0.06 * s, 0.37 * s, cx + side * 0.07 * s, 0.435 * s);
        g.globalAlpha = 0.25 * glow; g.lineWidth = rimW * 4; g.strokeStyle = "rgba(80,140,255,1)"; g.stroke(p);
        g.globalAlpha = 0.85 * glow; g.lineWidth = rimW * 0.8; g.strokeStyle = "rgba(235,245,255,1)"; g.stroke(p);
      }
      g.lineWidth = Math.max(0.7, 0.0014 * s);
      g.strokeStyle = "rgba(120,170,255,1)";
      for (let k = 0; k < 3; k++) {
        g.globalAlpha = 0.14 * glow;
        g.beginPath();
        g.ellipse(cx + hx * s * (0.6 - k * 0.2), (0.35 + k * 0.028) * s, 0.062 * s, 0.013 * s, 0, 0.12 * Math.PI, 0.88 * Math.PI);
        g.stroke();
      }

      this.drawOrbits(t, voice, false, cx + hx * s, hy, HS);

      // Silhouette = smoothed convex hull of the projected mesh; dark visor fill.
      const hidx = convexHull(X, Y, n);
      const m = hidx.length;
      const sil = new Path2D();
      let qx = (X[hidx[m - 1]] + X[hidx[0]]) / 2, qy = (Y[hidx[m - 1]] + Y[hidx[0]]) / 2;
      sil.moveTo(qx, qy);
      for (let k = 0; k < m; k++) {
        const a = hidx[k], b = hidx[(k + 1) % m];
        sil.quadraticCurveTo(X[a], Y[a], (X[a] + X[b]) / 2, (Y[a] + Y[b]) / 2);
      }
      sil.closePath();
      const fc = proj(0, 0, 0.1);
      const fill = g.createRadialGradient(fc[0], fc[1], 0, fc[0], fc[1], 0.2 * s);
      fill.addColorStop(0, "rgba(18,40,100,1)");
      fill.addColorStop(0.55, "rgba(6,14,44,1)");
      fill.addColorStop(1, "rgba(2,5,18,1)");
      g.globalCompositeOperation = "source-over";
      g.globalAlpha = 0.94;
      g.fillStyle = fill;
      g.fill(sil);
      g.globalCompositeOperation = "lighter";

      // Mesh: 4 brightness buckets (brighter towards the edges), hair as swept-back strands.
      const B = 4, mesh = [], strands = [];
      for (let b = 0; b < B; b++) { mesh.push(new Path2D()); strands.push(new Path2D()); }
      const seg = (a, b, meridian) => {
        const f = (F[a] + F[b]) * 0.5;
        if (f <= 0.03) return;
        const bucket = Math.min(B - 1, Math.floor((1 - f) * B));
        const inHair = hair[a] + hair[b] > 1;
        const path = inHair ? (meridian ? strands[bucket] : null) : mesh[bucket];
        if (path) { path.moveTo(X[a], Y[a]); path.lineTo(X[b], Y[b]); }
      };
      for (let i = 0; i < rows; i++) {
        for (let j = 0; j < cols; j++) {
          const v = i * cols + j;
          seg(v, i * cols + (j + 1) % cols, false);
          if (i < rows - 1) seg(v, v + cols, true);
        }
      }
      const MESH_A = [0.06, 0.11, 0.2, 0.34], HAIR_A = [0.3, 0.38, 0.48, 0.6];
      g.lineWidth = Math.max(0.6, 0.0011 * s);
      g.strokeStyle = "rgba(110,170,255,1)";
      for (let b = 0; b < B; b++) { g.globalAlpha = MESH_A[b] * glow; g.stroke(mesh[b]); }
      g.lineWidth = Math.max(0.7, 0.0015 * s);
      g.strokeStyle = "rgba(150,185,255,1)";
      for (let b = 0; b < B; b++) { g.globalAlpha = HAIR_A[b] * glow; g.stroke(strands[b]); }

      // Point cloud: twinkling light points on the mesh vertices.
      if (!this.lowPower) {
        g.fillStyle = "rgba(200,235,255,1)";
        const ps = Math.max(1, 0.0016 * s);
        for (let v = 0; v < n; v += 2) {
          const f = F[v];
          if (f < 0.12) continue;
          const tw = 0.5 + 0.5 * Math.sin(t * 2.3 + v * 1.37);
          g.globalAlpha = glow * (0.12 + 0.45 * (1 - f) + 0.3 * tw) * (hair[v] > 0.5 ? 0.6 : 0.8);
          g.fillRect(X[v] - ps / 2, Y[v] - ps / 2, ps, ps);
        }
      }

      // Rim light.
      g.globalAlpha = 0.28 * glow; g.lineWidth = rimW * 5; g.strokeStyle = "rgba(80,140,255,1)"; g.stroke(sil);
      g.globalAlpha = 0.9 * glow; g.lineWidth = rimW; g.strokeStyle = "rgba(235,245,255,1)"; g.stroke(sil);

      // Scan band: slow sweep when idle, fast when thinking.
      const thinking = this.state === "thinking";
      const phase = (t * (thinking ? 0.9 : 0.16)) % 1;
      if (thinking || phase < 0.35) {
        const yy = (hy + (-0.16 + (thinking ? phase : phase / 0.35) * 0.33) * HS) * s;
        g.save();
        g.clip(sil);
        const band = g.createLinearGradient(0, yy - 0.02 * s, 0, yy + 0.004 * s);
        band.addColorStop(0, "rgba(90,160,255,0)");
        band.addColorStop(1, "rgba(150,210,255,0.5)");
        g.globalAlpha = (thinking ? 0.6 : 0.22) * glow;
        g.fillStyle = band;
        g.fillRect(cx - 0.2 * s, yy - 0.02 * s, 0.4 * s, 0.024 * s);
        g.restore();
      }

      // Facial features (curves on the face surface, faded when they turn away).
      const fw = Math.max(1.1, 0.0026 * s);
      const stroke = (pts, alpha, width = fw, halo = "rgba(90,160,255,1)", core = "rgba(235,246,255,1)") => {
        const pr = pts.map(([x, y]) => face(x, y));
        let vis = 0;
        for (const p of pr) vis += p[3];
        vis = Math.min(1, Math.max(0, (vis / pr.length - 0.05) * 2.2));
        if (vis < 0.02) return;
        const path = new Path2D();
        path.moveTo(pr[0][0], pr[0][1]);
        if (pr.length === 2) path.lineTo(pr[1][0], pr[1][1]);
        for (let k = 1; k < pr.length - 1; k++) {
          const last = k === pr.length - 2;
          path.quadraticCurveTo(pr[k][0], pr[k][1], last ? pr[k + 1][0] : (pr[k][0] + pr[k + 1][0]) / 2,
            last ? pr[k + 1][1] : (pr[k][1] + pr[k + 1][1]) / 2);
        }
        g.globalAlpha = alpha * vis * 0.3 * glow; g.lineWidth = width * 3.2; g.strokeStyle = halo; g.stroke(path);
        g.globalAlpha = alpha * vis * glow; g.lineWidth = width; g.strokeStyle = core; g.stroke(path);
      };
      const curve = (fn, steps = 8) => Array.from({ length: steps + 1 }, (_, i) => fn(i / steps));
      const err = this.state === "error";
      const listen = this.state === "listening" ? 1 : 0;
      const eyeCore = err ? "rgba(255,160,140,1)" : "rgba(225,245,255,1)";
      const eyeHalo = err ? "rgba(255,70,50,1)" : "rgba(70,170,255,1)";

      // Hairline.
      // Hairline: slightly receding at the temples (M shape).
      stroke(curve((u) => { const x = (u * 2 - 1) * 0.088; const a = Math.abs(x) / 0.088; return [x, -0.092 - 0.016 * Math.sin(Math.PI * Math.min(1, a * 1.25)) ** 2 + 0.03 * Math.max(0, a - 0.8) / 0.2]; }, 14), 0.5, fw * 0.9);

      for (const side of [-1, 1]) {
        // Brow: thick and fairly straight (male), raised a little while listening.
        const lift = listen * 0.003;
        stroke(curve((u) => [side * (0.013 + 0.055 * u), -0.031 - lift - 0.008 * Math.sin(Math.PI * (0.15 + u * 0.75)) + 0.004 * u]), 0.9, fw * 1.9);
        // Eyelids (with blinks).
        const b = this.blink;
        const lower = (u) => -0.0105 + 0.0052 * Math.sin(Math.PI * u);
        const upper = (u) => -0.0105 - 0.0088 * Math.pow(Math.sin(Math.PI * u), 0.85) - 0.0012 * u;
        const ex = (u) => side * (0.021 + 0.035 * u);
        stroke(curve((u) => [ex(u), upper(u) * (1 - b) + (lower(u) - 0.0008) * b]), 1, fw * 1.15, eyeHalo, eyeCore);
        stroke(curve((u) => [ex(u), lower(u)]), 0.45, fw * 0.8, eyeHalo, eyeCore);
        stroke(curve((u) => [ex(0.1 + u * 0.8), upper(0.1 + u * 0.8) - 0.0055 - 0.0012 * Math.sin(Math.PI * u)], 6), 0.22, fw * 0.7); // eyelid crease
        // Iris and pupil: they follow the gaze.
        if (b < 0.6) {
          const c = face(side * 0.0385 + this.gazeX * 0.0065, -0.0122 + this.gazeY * 0.0035, 0.002);
          const vis = Math.min(1, Math.max(0, c[3] * 2)) * (1 - b / 0.6);
          if (vis > 0.02) {
            const r = 0.0052 * HS * s / (1 - c[2] * 0.8);
            const bright = Math.min(1, 0.55 + listen * 0.3 + voice * 0.5);
            const es = this.eyeSprite, w = 0.03 * s, h = 0.018 * s;
            g.globalAlpha = vis * bright * glow * 0.65;
            g.drawImage(es, c[0] - w / 2, c[1] - h / 2, w, h);
            g.globalAlpha = vis * bright * glow;
            g.strokeStyle = eyeCore;
            g.lineWidth = Math.max(1, fw * 0.8);
            g.beginPath();
            g.ellipse(c[0], c[1], r * Math.max(0.3, Math.min(1, c[3] * 1.2)), r * 0.95, 0, 0, TAU);
            g.stroke();
            g.fillStyle = eyeCore;
            g.beginPath();
            g.arc(c[0], c[1], r * 0.35, 0, TAU);
            g.fill();
            // Futuristic iris: rotating segmented ring + horizontal lens flare.
            const rr = r * 1.6, sq = Math.max(0.3, Math.min(1, c[3] * 1.2));
            g.lineWidth = Math.max(0.8, fw * 0.55);
            for (let k = 0; k < 6; k++) {
              const a0 = t * (1.1 + listen * 1.5) * side + k * TAU / 6;
              g.beginPath();
              g.ellipse(c[0], c[1], rr * sq, rr, 0, a0, a0 + TAU / 13);
              g.stroke();
            }
            const fl = (0.03 + voice * 0.035 + listen * 0.012) * s;
            const flare = g.createLinearGradient(c[0] - fl, 0, c[0] + fl, 0);
            flare.addColorStop(0, "rgba(80,170,255,0)");
            flare.addColorStop(0.5, err ? "rgba(255,150,130,0.95)" : "rgba(180,230,255,0.95)");
            flare.addColorStop(1, "rgba(80,170,255,0)");
            g.globalAlpha = vis * bright * glow * 0.6;
            g.fillStyle = flare;
            g.fillRect(c[0] - fl, c[1] - 0.0008 * s, fl * 2, 0.0016 * s);
          }
        }
        // Nose side, cheekbone, smile line, jaw line.
        stroke([[side * 0.009, -0.024], [side * 0.011, 0.0], [side * 0.014, 0.026], [side * 0.019, 0.041]], 0.3, fw * 0.8);
        stroke([[side * 0.045, 0.011], [side * 0.068, 0.004], [side * 0.088, -0.006]], 0.28, fw * 0.8);
        stroke([[side * 0.022, 0.05], [side * 0.03, 0.066], [side * 0.034, 0.086]], 0.24, fw * 0.75);
        stroke([[side * 0.093, 0.03], [side * 0.093, 0.072], [side * 0.085, 0.104], [side * 0.064, 0.134], [side * 0.034, 0.151], [0, 0.157]], 0.42, fw * 0.9);
        // Temple circuit with a pulsing node.
        stroke([[side * 0.07, -0.07], [side * 0.08, -0.06], [side * 0.086, -0.052], [side * 0.09, -0.035]], 0.55, fw * 0.7, "rgba(120,120,255,1)");
        const node = face(side * 0.086, -0.052);
        const nv = Math.min(1, Math.max(0, node[3] * 2.5));
        if (nv > 0.02) {
          const sp = this.sparkSprite;
          g.globalAlpha = nv * (0.45 + 0.55 * Math.abs(Math.sin(t * 2.2 + side))) * glow;
          g.drawImage(sp, node[0] - sp.width * 0.6, node[1] - sp.height * 0.6, sp.width * 1.2, sp.height * 1.2);
        }
      }
      // Nose ridge (mostly visible in profile) and nostrils.
      stroke([[0, -0.028], [0, 0.0], [0, 0.03], [0, 0.046]], 0.15 + Math.abs(this.yaw) * 0.55, fw * 0.85);
      stroke([[-0.022, 0.046], [-0.016, 0.053], [-0.007, 0.0545], [0, 0.0565], [0.007, 0.0545], [0.016, 0.053], [0.022, 0.046]], 0.75, fw);
      // Mouth: opens with the voice.
      const open = Math.min(0.016, voice * 0.016);
      stroke([[-0.027, 0.081], [-0.016, 0.0745], [-0.006, 0.0728], [0, 0.0745], [0.006, 0.0728], [0.016, 0.0745], [0.027, 0.081]], 0.5, fw * 0.85);
      stroke([[-0.028, 0.082], [-0.012, 0.0812], [0, 0.0825], [0.012, 0.0812], [0.028, 0.082]], 0.9, fw);
      if (open > 0.0015) stroke([[-0.024, 0.082 + open * 0.5], [0, 0.082 + open], [0.024, 0.082 + open * 0.5]], 0.85, fw);
      stroke([[-0.022, 0.087 + open * 0.8], [0, 0.0965 + open], [0.022, 0.087 + open * 0.8]], 0.42, fw * 0.85);
      stroke([[-0.02, 0.128], [0, 0.1335], [0.02, 0.128]], 0.2, fw * 0.8);

      // Cyber panel seams: the face is made of plates (forehead, cheeks, chin) with glowing joints.
      const seamHalo = "rgba(70,200,255,1)", seamCore = "rgba(200,245,255,1)";
      stroke([[0, -0.138], [0, -0.115], [0, -0.092]], 0.55, fw * 0.7, seamHalo, seamCore);
      for (const side of [-1, 1]) {
        stroke([[side * 0.012, -0.05], [side * 0.045, -0.056], [side * 0.072, -0.063], [side * 0.084, -0.086], [side * 0.082, -0.112]], 0.5, fw * 0.65, seamHalo, seamCore);
        stroke([[side * 0.062, -0.004], [side * 0.072, 0.02], [side * 0.077, 0.05], [side * 0.085, 0.075], [side * 0.09, 0.095]], 0.55, fw * 0.65, seamHalo, seamCore);
        stroke([[side * 0.026, 0.006], [side * 0.043, 0.008], [side * 0.06, 0.002]], 0.32, fw * 0.55, seamHalo, seamCore);
        stroke([[side * 0.027, 0.06], [side * 0.038, 0.088], [side * 0.035, 0.117], [side * 0.017, 0.132], [0, 0.137]], 0.45, fw * 0.6, seamHalo, seamCore);
      }
      const sparkle = this.sparkSprite;
      const nodes = [[0, -0.092], [-0.072, -0.063], [0.072, -0.063], [-0.062, -0.004], [0.062, -0.004], [-0.09, 0.095], [0.09, 0.095], [0, 0.137]];
      for (let k = 0; k < nodes.length; k++) {
        const nd = face(nodes[k][0], nodes[k][1], 0.002);
        const v = Math.min(1, Math.max(0, nd[3] * 2.2));
        if (v < 0.05) continue;
        g.globalAlpha = v * glow * (0.3 + 0.7 * Math.abs(Math.sin(t * 2.4 + k * 1.7)));
        g.drawImage(sparkle, nd[0] - sparkle.width * 0.45, nd[1] - sparkle.height * 0.45, sparkle.width * 0.9, sparkle.height * 0.9);
      }
      // Forehead insignia: a glowing diamond, brighter with activity.
      {
        const act = Math.min(1, 0.4 + listen * 0.4 + voice + (this.state === "thinking" ? 0.5 * (0.5 + 0.5 * Math.sin(t * 6)) : 0));
        const dia = [[0, -0.087], [0.009, -0.076], [0, -0.065], [-0.009, -0.076]].map(([x, y]) => face(x, y, 0.002));
        const dv = Math.min(1, Math.max(0, dia[0][3] * 2));
        if (dv > 0.05) {
          const dp = new Path2D();
          dp.moveTo(dia[0][0], dia[0][1]);
          for (let k = 1; k < 4; k++) dp.lineTo(dia[k][0], dia[k][1]);
          dp.closePath();
          g.globalAlpha = dv * glow * act * 0.35; g.lineWidth = fw * 3; g.strokeStyle = "rgba(80,200,255,1)"; g.stroke(dp);
          g.globalAlpha = dv * glow * act * 0.5; g.fillStyle = "rgba(120,210,255,1)"; g.fill(dp);
          g.globalAlpha = dv * glow * act; g.lineWidth = fw * 0.8; g.strokeStyle = "rgba(225,250,255,1)"; g.stroke(dp);
        }
      }

      // Ears (more visible on the side turned towards the viewer).
      g.lineWidth = fw * 0.9;
      for (const side of [-1, 1]) {
        const vis = Math.min(1, Math.max(0, -side * sY * cP * 1.6 + 0.35));
        const pts = [[-0.032, 0.0], [-0.04, -0.016], [-0.024, -0.03], [0.012, -0.027], [0.038, -0.013], [0.044, -0.002]]
          .map(([y, z]) => proj(side * (profile(y)[0] + 0.007), y, z));
        const path = new Path2D();
        path.moveTo(pts[0][0], pts[0][1]);
        for (let k = 1; k < pts.length - 1; k++) {
          const last = k === pts.length - 2;
          path.quadraticCurveTo(pts[k][0], pts[k][1], last ? pts[k + 1][0] : (pts[k][0] + pts[k + 1][0]) / 2,
            last ? pts[k + 1][1] : (pts[k][1] + pts[k + 1][1]) / 2);
        }
        g.globalAlpha = 0.22 * vis * glow; g.lineWidth = fw * 3; g.strokeStyle = "rgba(90,160,255,1)"; g.stroke(path);
        g.globalAlpha = 0.75 * vis * glow; g.lineWidth = fw * 0.9; g.strokeStyle = "rgba(220,238,255,1)"; g.stroke(path);
      }
      this.drawOrbits(t, voice, true, cx + hx * s, hy, HS);
    }

    // Two 3D rings around the head (a halo above it, a collar around the neck). Their back half is
    // drawn before the head, their front half after it. The collar's ticks react to the voice.
    drawOrbits(t, voice, front, ox, hy, HS) {
      const { g, s } = this;
      const rings = [
        { y: 0.0, R: 0.195, tilt: 1.02, roll: 0.28, speed: 0.35, seg: 16, on: 0.6, w: 1.1, ticks: false },
        { y: 0.2, R: 0.21, tilt: 0.2, roll: 0, speed: -0.22, seg: 36, on: 0.42, w: 0.9, ticks: true },
      ];
      const N = this.lowPower ? 64 : 120;
      for (const ring of rings) {
        const ct = Math.cos(ring.tilt), st = Math.sin(ring.tilt), cr = Math.cos(ring.roll), sr = Math.sin(ring.roll);
        const oy = (hy + ring.y * HS) * s;
        const pts = [];
        for (let i = 0; i <= N; i++) {
          const a = (i / N) * TAU + t * ring.speed;
          const x = Math.cos(a) * ring.R, z = Math.sin(a) * ring.R;
          const px = x * HS * s, py = z * st * HS * s;
          pts.push([ox + px * cr - py * sr, oy + px * sr + py * cr, z * ct, i]);
        }
        const path = new Path2D();
        for (let i = 0; i < N; i++) {
          const a = pts[i], b = pts[i + 1];
          if ((a[2] >= 0) !== front) continue;
          if (((i / N) * ring.seg) % 1 > ring.on) continue;
          path.moveTo(a[0], a[1]); path.lineTo(b[0], b[1]);
        }
        const alpha = (front ? 0.85 : 0.3) * this.glow;
        g.globalAlpha = alpha * 0.3; g.lineWidth = ring.w * Math.max(2, 0.006 * s); g.strokeStyle = "rgba(70,170,255,1)"; g.stroke(path);
        g.globalAlpha = alpha; g.lineWidth = ring.w * Math.max(0.8, 0.0018 * s); g.strokeStyle = "rgba(200,238,255,1)"; g.stroke(path);
        if (ring.ticks) {   // audio-reactive ticks pointing outward
          const tp = new Path2D();
          for (let i = 0; i < N; i += 3) {
            const a = pts[i];
            if ((a[2] >= 0) !== front) continue;
            const dx = a[0] - ox, dy = a[1] - oy, l = Math.hypot(dx, dy) || 1;
            const amp = (0.004 + voice * 0.03 * (0.4 + 0.6 * Math.abs(Math.sin(i * 1.7 + t * 9)))) * s;
            tp.moveTo(a[0], a[1]); tp.lineTo(a[0] + dx / l * amp, a[1] + dy / l * amp * 0.6);
          }
          g.globalAlpha = alpha * 0.7; g.lineWidth = Math.max(0.8, 0.0015 * s); g.stroke(tp);
        }
        // A light running along the ring.
        const ang = t * (ring.speed * 3 + 0.6);
        const sx = Math.cos(ang) * ring.R, sz = Math.sin(ang) * ring.R;
        if ((sz * ct >= 0) === front) {
          const sp = this.sparkSprite;
          g.globalAlpha = (front ? 1 : 0.4) * this.glow;
          const px = sx * HS * s, py = sz * st * HS * s;
          g.drawImage(sp, ox + px * cr - py * sr - sp.width / 2, oy + px * sr + py * cr - sp.height / 2);
        }
      }
    }

    // Holographic labels with leader lines (state + voice meter).
    drawCallouts(t, voice) {
      const { g, s, cx } = this;
      const fs = Math.max(10, Math.round(0.019 * s));
      g.font = `600 ${fs}px ${this.font}`;
      g.textBaseline = "middle";
      const STATE = { idle: "STANDBY", listening: "LISTENING", thinking: "PROCESSING", speaking: "SPEAKING",
        error: "ERROR", paused: "PAUSED", boot: "BOOTING" };
      const col = this.state === "error" ? "rgba(255,140,120,1)" : "rgba(120,215,255,1)";
      const leader = (ax, ay, ex, ey, lx) => {
        g.globalAlpha = 0.55 * this.glow; g.strokeStyle = col; g.lineWidth = Math.max(0.8, 0.0012 * s);
        g.beginPath(); g.moveTo(ax, ay); g.lineTo(ex, ey); g.lineTo(lx, ey); g.stroke();
        g.globalAlpha = 0.9 * this.glow; g.fillStyle = col;
        g.beginPath(); g.arc(ax, ay, Math.max(1.5, 0.003 * s), 0, TAU); g.fill();
      };
      // Left: neural core state.
      const lx = cx - 0.42 * s, ly = 0.12 * s;
      leader(cx - 0.13 * s, 0.16 * s, cx - 0.22 * s, ly, lx + 0.16 * s);
      g.globalAlpha = 0.8 * this.glow; g.fillStyle = col; g.textAlign = "left";
      g.fillText("NEURAL CORE", lx, ly - fs * 1.1);
      g.globalAlpha = 0.95 * this.glow; g.fillStyle = "rgba(225,245,255,1)";
      const dots = this.state === "thinking" ? " " + ".".repeat(1 + Math.floor(t * 3) % 3) : "";
      g.fillText((STATE[this.state] || "ONLINE") + dots, lx, ly + fs * 0.1);
      g.globalAlpha = 0.7 * this.glow; g.fillStyle = col;
      g.fillText(`SYNC ${(98.2 + 1.4 * Math.sin(t * 0.7)).toFixed(1)}%`, lx, ly + fs * 1.3);
      // Right: voice link with a live meter.
      const rx = cx + 0.27 * s, ry = 0.3 * s;
      leader(cx + 0.11 * s, 0.33 * s, cx + 0.22 * s, ry, rx);
      g.globalAlpha = 0.8 * this.glow; g.fillStyle = col;
      g.fillText("VOICE LINK", rx, ry - fs * 1.1);
      for (let k = 0; k < 10; k++) {
        const hgt = (0.15 + Math.min(1, voice * (0.6 + 0.6 * Math.abs(Math.sin(k * 2.1 + t * 11))))) * fs * 1.2;
        g.globalAlpha = (0.35 + 0.6 * Math.min(1, voice * 2)) * this.glow;
        g.fillRect(rx + k * fs * 0.45, ry + fs * 0.6 - hgt, fs * 0.28, hgt);
      }
      g.globalAlpha = 0.7 * this.glow;
      g.fillText("FR · HENRI", rx, ry + fs * 1.4);
    }

    // Post effects: bloom (cheap, via a quarter-size copy), rare glitches, hologram scanlines.
    postFX(t) {
      const { g, canvas } = this;
      const W = canvas.width, H = canvas.height;
      g.globalCompositeOperation = "lighter";
      if (!this.lowPower && this.bloom) {
        const [bx, by, bw, bh] = this.bloomBox;
        if ((this.bloomFrame++ & 1) === 0) {   // refreshed every other frame
          const b = this.bloom.getContext("2d");
          b.globalCompositeOperation = "copy";
          b.drawImage(canvas, bx, by, bw, bh, 0, 0, this.bloom.width, this.bloom.height);
        }
        g.globalAlpha = 0.45 * this.glow;
        g.drawImage(this.bloom, bx, by, bw, bh);
      }
      if (this.state !== this.lastState) {
        if (this.state === "thinking" || this.state === "error") this.glitchUntil = t + 0.18;
        this.lastState = this.state;
      }
      if (!this.lowPower && t > this.nextGlitch) {
        this.glitchUntil = t + 0.1 + Math.random() * 0.12;
        this.nextGlitch = t + 6 + Math.random() * 8;
      }
      if (t < this.glitchUntil && this.fx) {
        const f = this.fx.getContext("2d");
        f.globalCompositeOperation = "copy";
        f.drawImage(canvas, 0, 0);
        g.globalCompositeOperation = "source-over";
        g.globalAlpha = 1;
        for (let k = 0; k < 5; k++) {
          const y = (0.02 + Math.random() * 0.55) * H, h = (0.004 + Math.random() * 0.018) * H;
          const dx = (Math.random() - 0.5) * 0.05 * W;
          g.clearRect(0, y, W, h);
          g.drawImage(this.fx, 0, y, W, h, dx, y, W, h);
        }
        g.globalCompositeOperation = "lighter";
        g.globalAlpha = 0.22;
        g.drawImage(this.fx, -0.004 * W, 0);
        g.drawImage(this.fx, 0.004 * W, 0);
      }
      // Scanlines (slowly scrolling) and a faint flicker.
      if (this.scanPattern) {
        g.globalCompositeOperation = "destination-out";
        g.globalAlpha = 0.2 + (Math.random() < 0.03 ? 0.15 : 0);
        g.save();
        g.translate(0, (t * 18) % 3);
        g.fillStyle = this.scanPattern;
        g.fillRect(0, -3, W, H + 3);
        g.restore();
      }
      g.globalAlpha = 1;
      g.globalCompositeOperation = "source-over";
    }
  }

  window.JarvisAvatar = Avatar;
})();
