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
    [0.060, 0.093, 0.110, 0.086],
    [0.090, 0.086, 0.105, 0.062],
    [0.110, 0.076, 0.100, 0.044],
    [0.128, 0.060, 0.095, 0.028],
    [0.142, 0.042, 0.089, 0.014],
    [0.152, 0.024, 0.082, 0.004],
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
    }

    P(x, y) { return [this.cx + x * this.s, y * this.s]; }

    // Static body: contours + energy filaments, rendered once.
    buildBody() {
      const { s } = this;
      const body = document.createElement("canvas");
      body.width = this.canvas.width;
      body.height = this.canvas.height;
      const g = body.getContext("2d");
      g.globalCompositeOperation = "lighter";
      g.lineCap = "round";
      g.lineJoin = "round";
      const R = rng(42);
      this.flows = [];

      const glowStroke = (path, width, color, alpha, blur) => {
        g.globalAlpha = alpha * 0.25;
        g.strokeStyle = color;
        g.lineWidth = width * 5;
        g.stroke(path);
        g.globalAlpha = alpha;
        g.lineWidth = width;
        if (blur && !this.lowPower) { g.shadowColor = color; g.shadowBlur = blur; }
        g.strokeStyle = "rgba(235,245,255,1)";
        g.stroke(path);
        g.shadowBlur = 0;
        g.globalAlpha = 1;
      };
      const curve = (pts) => {
        const p = new Path2D();
        const [x0, y0] = this.P(...pts[0]);
        p.moveTo(x0, y0);
        for (let i = 1; i < pts.length; i += 3) {
          const a = this.P(...pts[i]), b = this.P(...pts[i + 1]), c = this.P(...pts[i + 2]);
          p.bezierCurveTo(a[0], a[1], b[0], b[1], c[0], c[1]);
        }
        return p;
      };
      const mirror = (pts) => pts.map(([x, y]) => [-x, y]);

      // Main contours (left side, mirrored).
      const contours = [
        // trapezius: neck base -> shoulder
        [[-0.058, 0.43], [-0.10, 0.455], [-0.22, 0.47], [-0.33, 0.53]],
        // shoulder -> arm
        [[-0.33, 0.53], [-0.41, 0.56], [-0.445, 0.66], [-0.44, 0.80], [-0.435, 0.88], [-0.43, 0.95], [-0.425, 1.02]],
        // collarbone
        [[-0.035, 0.475], [-0.09, 0.455], [-0.17, 0.465], [-0.25, 0.50]],
        // pectoral upper + lower
        [[-0.012, 0.565], [-0.10, 0.535], [-0.22, 0.55], [-0.275, 0.64]],
        [[-0.275, 0.64], [-0.25, 0.71], [-0.13, 0.73], [-0.02, 0.705]],
        // armpit / lat
        [[-0.30, 0.70], [-0.285, 0.80], [-0.27, 0.90], [-0.255, 1.02]],
        // abs hints
        [[-0.105, 0.80], [-0.07, 0.79], [-0.04, 0.79], [-0.015, 0.795]],
        [[-0.10, 0.89], [-0.07, 0.88], [-0.04, 0.88], [-0.015, 0.885]],
        // deltoid inner line
        [[-0.33, 0.56], [-0.37, 0.62], [-0.38, 0.68], [-0.37, 0.74]],
      ];
      for (const c of contours) {
        glowStroke(curve(c), Math.max(1.2, 0.0035 * s), "rgba(90,150,255,1)", 0.95, 0.012 * s);
        glowStroke(curve(mirror(c)), Math.max(1.2, 0.0035 * s), "rgba(90,150,255,1)", 0.95, 0.012 * s);
      }
      // Sternum.
      glowStroke(curve([[0, 0.49], [0, 0.6], [0, 0.8], [0, 1.0]]), Math.max(1, 0.0025 * s), "rgba(110,140,255,1)", 0.7, 0.01 * s);

      // Energy filaments flowing over the shoulders and chest.
      const colors = ["rgba(120,170,255,1)", "rgba(150,120,255,1)", "rgba(90,200,255,1)"];
      const count = this.lowPower ? 70 : 160;
      for (let i = 0; i < count; i++) {
        const side = R() < 0.5 ? -1 : 1;
        // Start along the neck base / trapezius, flow outward and down.
        const u = R();
        const x0 = side * (0.05 + u * 0.28), y0 = 0.43 + u * 0.1 + (R() - 0.5) * 0.02;
        const len = 0.12 + R() * 0.38;
        const bend = (R() - 0.3) * 0.25;
        const x3 = x0 + side * (0.05 + R() * 0.18), y3 = Math.min(1.05, y0 + len);
        const pts = [[x0, y0], [x0 + side * bend * 0.4, y0 + len * 0.3], [x3 - side * bend * 0.3, y3 - len * 0.35], [x3, y3]];
        const path = curve(pts);
        const alpha = 0.06 + R() * 0.22;
        g.globalAlpha = alpha;
        g.strokeStyle = colors[i % 3];
        g.lineWidth = Math.max(0.6, (0.4 + R() * 0.9) * 0.0018 * s);
        g.stroke(path);
        if (i % 9 === 0) this.flows.push(path);
      }
      // Long filaments sweeping out from the shoulders (the "energy cape").
      const capes = this.lowPower ? 14 : 34;
      for (let i = 0; i < capes; i++) {
        const side = i % 2 ? 1 : -1;
        const y0 = 0.5 + R() * 0.12;
        const pts = [[side * (0.25 + R() * 0.08), y0], [side * (0.42 + R() * 0.1), y0 - 0.06 + R() * 0.1],
          [side * (0.52 + R() * 0.08), y0 + 0.05 + R() * 0.25], [side * (0.6 + R() * 0.12), y0 + 0.2 + R() * 0.35]];
        const path = curve(pts);
        g.globalAlpha = 0.05 + R() * 0.16;
        g.strokeStyle = colors[(i + 1) % 3];
        g.lineWidth = Math.max(0.6, 0.0016 * s);
        g.stroke(path);
        if (i % 5 === 0) this.flows.push(path);
      }
      // Sparkle dust over the body.
      for (let i = 0; i < (this.lowPower ? 120 : 320); i++) {
        const x = (R() - 0.5) * 0.8, y = 0.42 + R() * 0.6;
        if (Math.abs(x) > 0.44 - (y < 0.53 ? (0.53 - y) * 3 : 0)) continue;
        const [px, py] = this.P(x, y);
        g.globalAlpha = 0.15 + R() * 0.6;
        g.fillStyle = R() < 0.7 ? "#dbe9ff" : "#9f8bff";
        g.fillRect(px, py, R() < 0.9 ? 1 : 2, R() < 0.9 ? 1 : 2);
      }
      // Fade the bottom of the bust into the background.
      g.globalAlpha = 1;
      g.globalCompositeOperation = "destination-out";
      const fade = g.createLinearGradient(0, 0.78 * s, 0, s);
      fade.addColorStop(0, "rgba(0,0,0,0)");
      fade.addColorStop(1, "rgba(0,0,0,1)");
      g.fillStyle = fade;
      g.fillRect(0, 0.78 * s, body.width, 0.22 * s);
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
      g.globalCompositeOperation = "lighter";
      const breathe = Math.sin(t * 0.9);

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
      const coreScale = 0.55 + 0.1 * breathe * 0.5 + voice * 0.9 + (this.state === "thinking" ? 0.15 * Math.sin(t * 8) : 0);
      g.globalAlpha = Math.min(1, 0.55 + voice * 0.8) * this.glow;
      g.drawImage(core, cx - core.width * coreScale / 2, 0.61 * s - core.height * coreScale / 2, core.width * coreScale, core.height * coreScale);

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
      g.globalAlpha = 1;
      g.globalCompositeOperation = "source-over";
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
      const hx = this.yaw * 0.012, hy = 0.19 + this.pitch * 0.008;
      const proj = (x, y, z) => {
        const x1 = x * cY + z * sY, z1 = -x * sY + z * cY;
        const y2 = y * cP + z1 * sP, z2 = -y * sP + z1 * cP;
        const f = 1 / (1 - z2 * 0.8);
        return [cx + (hx + x1 * f) * s, (hy + y2 * f) * s, z2];
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
        X[v] = cx + (hx + x1 * f) * s; Y[v] = (hy + y2 * f) * s;
        F[v] = facing(N[k], N[k + 1], N[k + 2]);
      }

      // Neck (behind the head).
      g.globalCompositeOperation = "lighter";
      const rimW = Math.max(1.4, 0.0042 * s);
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

      // Rim light.
      g.globalAlpha = 0.28 * glow; g.lineWidth = rimW * 5; g.strokeStyle = "rgba(80,140,255,1)"; g.stroke(sil);
      g.globalAlpha = 0.9 * glow; g.lineWidth = rimW; g.strokeStyle = "rgba(235,245,255,1)"; g.stroke(sil);

      // Scan band: slow sweep when idle, fast when thinking.
      const thinking = this.state === "thinking";
      const phase = (t * (thinking ? 0.9 : 0.16)) % 1;
      if (thinking || phase < 0.35) {
        const yy = (hy - 0.16 + (thinking ? phase : phase / 0.35) * 0.33) * s;
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
        stroke(curve((u) => [ex(u), lower(u)]), 0.5, fw * 0.8, eyeHalo, eyeCore);
        // Iris and pupil: they follow the gaze.
        if (b < 0.6) {
          const c = face(side * 0.0385 + this.gazeX * 0.0065, -0.0122 + this.gazeY * 0.0035, 0.002);
          const vis = Math.min(1, Math.max(0, c[3] * 2)) * (1 - b / 0.6);
          if (vis > 0.02) {
            const r = 0.006 * s / (1 - c[2] * 0.8);
            const bright = Math.min(1, 0.55 + listen * 0.3 + voice * 0.5);
            const es = this.eyeSprite, w = 0.04 * s, h = 0.026 * s;
            g.globalAlpha = vis * bright * glow * 0.9;
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
          }
        }
        // Nose side, cheekbone, smile line, jaw line.
        stroke([[side * 0.009, -0.024], [side * 0.011, 0.0], [side * 0.014, 0.026], [side * 0.019, 0.041]], 0.3, fw * 0.8);
        stroke([[side * 0.045, 0.011], [side * 0.068, 0.004], [side * 0.088, -0.006]], 0.28, fw * 0.8);
        stroke([[side * 0.022, 0.05], [side * 0.03, 0.066], [side * 0.034, 0.086]], 0.24, fw * 0.75);
        stroke([[side * 0.093, 0.03], [side * 0.089, 0.072], [side * 0.078, 0.104], [side * 0.056, 0.134], [side * 0.028, 0.151], [0, 0.156]], 0.4, fw * 0.9);
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
    }
  }

  window.JarvisAvatar = Avatar;
})();
