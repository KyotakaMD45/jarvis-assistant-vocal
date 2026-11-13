/* Jarvis HUD - reproduction of reference_ui.png, driven by live events from Python (SSE).
 *
 * Performance (Intel UHD 620 target):
 * - the starfield/nebula is drawn ONCE into a static canvas (no per-frame cost);
 * - the light waves render at half resolution and are scaled up by CSS (soft glow for free);
 * - every ring of the core is a pre-rendered sprite, only rotated/scaled per frame;
 * - frames are capped (30 FPS, 20 in low power) and stop when the window is hidden;
 * - if frames get slow, low power mode switches on by itself.
 */
(() => {
  "use strict";

  const TOKEN = new URLSearchParams(location.search).get("token") || "";
  const $ = (id) => document.getElementById(id);
  const TAU = Math.PI * 2;

  const app = {
    state: "boot",
    level: 0,        // raw audio level from Python (mic when listening, voice when speaking)
    smooth: 0,       // smoothed level
    fps: 30,
    lowPower: false,
    H: innerHeight,
    W: innerWidth,
  };

  // Per-state animation targets (the scene eases between them).
  const TARGETS = {
    boot:      { spin: 0.4, wave: 0.6, pulse: 0.0, glow: 0.7, bars: 0.6 },
    idle:      { spin: 1.0, wave: 1.0, pulse: 0.0, glow: 0.85, bars: 1.0 },
    listening: { spin: 1.6, wave: 1.1, pulse: 0.5, glow: 1.0, bars: 1.0 },
    thinking:  { spin: 7.0, wave: 2.6, pulse: 0.0, glow: 0.95, bars: 0.6 },
    speaking:  { spin: 1.4, wave: 1.3, pulse: 1.0, glow: 1.0, bars: 1.0 },
    error:     { spin: 0.6, wave: 0.7, pulse: 0.0, glow: 0.6, bars: 0.4 },
    paused:    { spin: 0.3, wave: 0.5, pulse: 0.0, glow: 0.45, bars: 0.25 },
  };
  const apex = window.KnullApex ? new window.KnullApex() : null;   // agent-orb style
  if (apex) document.body.classList.add("apex");
  const LABELS = {
    boot: "STARTING", idle: apex ? "STANDBY" : "SPEAK NOW", listening: apex ? "LISTENING" : "SPEAK NOW", thinking: "THINKING",
    speaking: "SPEAKING", error: "ERROR · OPEN SYS", paused: "MIC PAUSED",
  };
  const cur = { ...TARGETS.boot };

  // Deterministic random numbers (same sky every launch).
  function rng(seed) {
    let s = seed >>> 0;
    return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  }
  function makeCanvas(w, h) {
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.ceil(w));
    c.height = Math.max(1, Math.ceil(h));
    return c;
  }
  const smoothstep = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

  // =====================================================================================
  // 1. Starfield + nebula: drawn once per window size
  // =====================================================================================
  function drawSpace() {
    const c = $("space");
    const W = (c.width = innerWidth);
    const H = (c.height = innerHeight);
    const g = c.getContext("2d");
    const R = rng(7);

    g.fillStyle = "#00020a";
    g.fillRect(0, 0, W, H);
    // Deep blue glow brighter around the core, darker corners (as in the reference).
    let grad = g.createRadialGradient(W / 2, H * 0.44, 0, W / 2, H * 0.44, Math.max(W, H) * 0.75);
    grad.addColorStop(0, "rgba(10, 42, 140, 0.9)");
    grad.addColorStop(0.16, "rgba(5, 24, 90, 0.85)");
    grad.addColorStop(0.45, "rgba(2, 10, 44, 0.8)");
    grad.addColorStop(0.85, "rgba(0, 3, 16, 0.7)");
    grad.addColorStop(1, "rgba(0, 2, 12, 0)");
    g.fillStyle = grad;
    g.fillRect(0, 0, W, H);

    // Nebula clouds: soft additive blobs, denser bottom-left / bottom-right / around the core.
    g.globalCompositeOperation = "lighter";
    const zones = [[0.12, 0.72], [0.88, 0.72], [0.5, 0.44], [0.25, 0.25], [0.78, 0.3], [0.5, 0.85]];
    for (let i = 0; i < 70; i++) {
      const z = zones[i % zones.length];
      const x = (z[0] + (R() - 0.5) * 0.35) * W;
      const y = (z[1] + (R() - 0.5) * 0.35) * H;
      const r = (0.04 + R() * 0.16) * Math.max(W, H);
      const a = 0.015 + R() * 0.035;
      const cyan = R() < 0.3;
      grad = g.createRadialGradient(x, y, 0, x, y, r);
      grad.addColorStop(0, cyan ? `rgba(60,150,255,${a})` : `rgba(30,80,230,${a})`);
      grad.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = grad;
      g.fillRect(x - r, y - r, r * 2, r * 2);
    }
    // Dark dust lanes give the nebula its texture.
    g.globalCompositeOperation = "source-over";
    for (let i = 0; i < 40; i++) {
      const x = R() * W, y = R() * H, r = (0.03 + R() * 0.1) * Math.max(W, H);
      grad = g.createRadialGradient(x, y, 0, x, y, r);
      grad.addColorStop(0, `rgba(0, 3, 16, ${0.08 + R() * 0.12})`);
      grad.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = grad;
      g.fillRect(x - r, y - r, r * 2, r * 2);
    }
    // Stars: many tiny ones, some medium with a halo, a few bright glints with spikes.
    g.globalCompositeOperation = "lighter";
    const tiny = Math.round((W * H) / 2400);
    for (let i = 0; i < tiny; i++) {
      const x = R() * W, y = R() * H;
      const a = 0.15 + R() * 0.7;
      g.fillStyle = R() < 0.7 ? `rgba(200,225,255,${a})` : `rgba(120,170,255,${a})`;
      const s = R() < 0.85 ? 1 : 1.6;
      g.fillRect(x, y, s, s);
    }
    for (let i = 0; i < 38; i++) {
      const x = R() * W, y = R() * H, r = 1 + R() * 1.8;
      grad = g.createRadialGradient(x, y, 0, x, y, r * 2.5);
      grad.addColorStop(0, "rgba(255,255,255,0.95)");
      grad.addColorStop(0.3, "rgba(140,190,255,0.5)");
      grad.addColorStop(1, "rgba(40,90,255,0)");
      g.fillStyle = grad;
      g.fillRect(x - r * 2.5, y - r * 2.5, r * 5, r * 5);
    }
    for (let i = 0; i < 6; i++) {
      const x = R() * W, y = R() * H * 0.95, r = 2 + R() * 2.5;
      grad = g.createRadialGradient(x, y, 0, x, y, r * 4);
      grad.addColorStop(0, "rgba(255,255,255,1)");
      grad.addColorStop(0.15, "rgba(170,210,255,0.7)");
      grad.addColorStop(1, "rgba(40,100,255,0)");
      g.fillStyle = grad;
      g.fillRect(x - r * 4, y - r * 4, r * 8, r * 8);
      g.strokeStyle = "rgba(170,210,255,0.35)";
      g.lineWidth = 1;
      g.beginPath();
      g.moveTo(x - r * 5, y); g.lineTo(x + r * 5, y);
      g.moveTo(x, y - r * 5); g.lineTo(x, y + r * 5);
      g.stroke();
    }
    // Futuristic floor: perspective grid fading toward the horizon (static).
    g.globalCompositeOperation = "lighter";
    const horizon = H * 0.62, vanishX = W / 2;
    g.lineWidth = 1;
    for (let i = -22; i <= 22; i++) {
      const xBottom = vanishX + i * (W / 14);
      const grd = g.createLinearGradient(0, horizon, 0, H);
      grd.addColorStop(0, "rgba(40,120,255,0)");
      grd.addColorStop(1, "rgba(40,120,255,0.10)");
      g.strokeStyle = grd;
      g.beginPath(); g.moveTo(vanishX + i * 6, horizon); g.lineTo(xBottom, H); g.stroke();
    }
    for (let k = 1; k <= 12; k++) {
      const y = horizon + (H - horizon) * Math.pow(k / 12, 2.2);
      g.strokeStyle = `rgba(40,120,255,${0.015 + 0.07 * (k / 12)})`;
      g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke();
    }
    grad = g.createLinearGradient(0, 0, W, 0);
    grad.addColorStop(0, "rgba(40,130,255,0)");
    grad.addColorStop(0.5, "rgba(80,170,255,0.35)");
    grad.addColorStop(1, "rgba(40,130,255,0)");
    g.fillStyle = grad;
    g.fillRect(0, horizon, W, 1);

    // Vignette.
    g.globalCompositeOperation = "source-over";
    grad = g.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.4, W / 2, H / 2, Math.max(W, H) * 0.8);
    grad.addColorStop(0, "rgba(0,0,0,0)");
    grad.addColorStop(1, "rgba(0,0,8,0.6)");
    g.fillStyle = grad;
    g.fillRect(0, 0, W, H);
  }

  // =====================================================================================
  // 2. Light waves (half resolution)
  // =====================================================================================
  const STRANDS = [
    // amplitude (fraction of H), cycles across the width, speed (rad/s), phase, vertical offset
    [0.060, 1.15, 0.22, 0.4, -0.010], [0.075, 0.85, -0.16, 2.1, 0.006], [0.050, 1.65, 0.28, 4.0, -0.004],
    [0.085, 1.05, 0.14, 5.2, 0.012], [0.040, 2.20, -0.30, 1.3, 0.0], [0.065, 1.35, 0.19, 3.3, -0.014],
    [0.030, 2.70, 0.36, 0.9, 0.008],
  ];
  const waves = { canvas: $("waves"), g: null, cy: 0, glowGrad: null, coreGrad: null, sparks: [], spark: null };

  function setupWaves() {
    const H = app.H, W = app.W;
    const c = waves.canvas;
    const bandH = H * 0.36;
    c.style.top = `${H * 0.44 - bandH / 2}px`;
    c.style.height = `${bandH}px`;
    c.width = Math.ceil(W / 2);
    c.height = Math.ceil(bandH / 2);
    waves.g = c.getContext("2d");
    waves.cy = c.height / 2;
    const g = waves.g;
    waves.glowGrad = g.createLinearGradient(0, 0, c.width, 0);
    waves.coreGrad = g.createLinearGradient(0, 0, c.width, 0);
    for (const [stop, a] of [[0, 0.3], [0.25, 0.75], [0.5, 1], [0.75, 0.75], [1, 0.3]]) {
      waves.glowGrad.addColorStop(stop, `rgba(30,120,255,${0.28 * a})`);
      waves.coreGrad.addColorStop(stop, `rgba(160,215,255,${1 * a})`);
    }
    // Sparkle sprite.
    const s = makeCanvas(24, 24);
    const sg = s.getContext("2d");
    const grad = sg.createRadialGradient(12, 12, 0, 12, 12, 12);
    grad.addColorStop(0, "rgba(255,255,255,1)");
    grad.addColorStop(0.25, "rgba(160,215,255,0.8)");
    grad.addColorStop(1, "rgba(40,110,255,0)");
    sg.fillStyle = grad;
    sg.fillRect(0, 0, 24, 24);
    waves.spark = s;
    const R = rng(3);
    waves.sparks = Array.from({ length: 14 }, (_, i) => ({ strand: i % STRANDS.length, x: R(), v: 0.02 + R() * 0.05, p: R() * TAU }));
  }

  function strandY(i, x, t, amp, W) {
    const [a, k, v, ph, off] = STRANDS[i];
    const cx = W / 2;
    // Strands pinch toward the core's horizontal axis and spread out toward the edges.
    const env = 0.18 + 0.82 * smoothstep(W * 0.06, W * 0.42, Math.abs(x - cx));
    const h = waves.canvas.height * 2 / 0.36; // full-resolution H
    return waves.cy + (off * h + a * h * env * amp * Math.sin((x / W) * k * TAU + ph + t * v * cur.wave)) / 2;
  }

  function drawWaves(t) {
    const g = waves.g, c = waves.canvas, W = c.width;
    g.clearRect(0, 0, c.width, c.height);
    g.globalCompositeOperation = "lighter";
    g.lineCap = "round";
    const amp = 1.35 + app.smooth * 0.7 * cur.pulse;
    const count = app.lowPower ? 4 : STRANDS.length;
    const step = app.lowPower ? 10 : 6;
    for (let i = 0; i < count; i++) {
      g.beginPath();
      for (let x = 0; x <= W + step; x += step) {
        const y = strandY(i, x, t, amp, W);
        if (x === 0) g.moveTo(x, y); else g.lineTo(x, y);
      }
      if (!app.lowPower) {
        g.strokeStyle = waves.glowGrad;
        g.lineWidth = 5;
        g.stroke();
      }
      g.strokeStyle = waves.coreGrad;
      g.lineWidth = i % 3 === 0 ? 1.3 : 0.8;
      g.stroke();
    }
    if (!app.lowPower) {
      for (const s of waves.sparks) {
        s.x = (s.x + s.v * cur.wave / app.fps) % 1;
        const x = s.x * W;
        const y = strandY(s.strand, x, t, amp, W);
        g.globalAlpha = 0.55 + 0.45 * Math.sin(t * 3 + s.p);
        g.drawImage(waves.spark, x - 6, y - 6, 12, 12);
      }
      g.globalAlpha = 1;
    }
  }

  // =====================================================================================
  // 3. The core (sprites pre-rendered at the current size)
  // =====================================================================================
  const orb = { canvas: $("orb"), g: null, size: 0, S: {}, angles: [0, 0, 0] };

  function sprite(size, draw) {
    const c = makeCanvas(size, size);
    const g = c.getContext("2d");
    g.translate(size / 2, size / 2);
    draw(g);
    return c;
  }

  function setupOrb() {
    const H = app.H;
    const dpr = Math.min(devicePixelRatio || 1, app.lowPower ? 1 : 1.25);
    const cssSize = H * 0.66;
    const c = orb.canvas;
    c.style.width = c.style.height = `${cssSize}px`;
    c.style.top = `${H * 0.44 - cssSize / 2}px`;
    c.width = c.height = Math.round(cssSize * dpr);
    orb.g = c.getContext("2d");
    orb.size = c.width;
    const u = c.width / 0.66;                 // 1 unit = window height in canvas pixels
    const blur = app.lowPower ? 0 : 1;
    const S = {};
    const blue = (a) => `rgba(70,170,255,${a})`;

    // Large blue haze behind the core.
    S.haze = sprite(c.width, (g) => {
      const r = 0.33 * u;
      const grad = g.createRadialGradient(0, 0, 0, 0, 0, r);
      grad.addColorStop(0, "rgba(90,180,255,0.75)");
      grad.addColorStop(0.25, "rgba(40,120,255,0.45)");
      grad.addColorStop(0.6, "rgba(20,70,220,0.15)");
      grad.addColorStop(1, "rgba(10,40,180,0)");
      g.fillStyle = grad;
      g.fillRect(-r, -r, r * 2, r * 2);
    });
    // Outer "ruler" band with ticks (rotates slowly).
    S.ruler = sprite(c.width, (g) => {
      // Soft band behind the ticks.
      g.lineWidth = 0.022 * u;
      g.strokeStyle = "rgba(40,130,255,0.16)";
      g.beginPath(); g.arc(0, 0, 0.183 * u, 0, TAU); g.stroke();
      g.strokeStyle = blue(0.8);
      g.lineWidth = Math.max(1, 0.0018 * u);
      for (const r of [0.172, 0.194]) { g.beginPath(); g.arc(0, 0, r * u, 0, TAU); g.stroke(); }
      g.strokeStyle = blue(0.7);
      for (let i = 0; i < 144; i++) {
        const a = (i / 144) * TAU;
        const r0 = 0.176 * u, r1 = (i % 4 === 0 ? 0.19 : 0.186) * u;
        g.beginPath(); g.moveTo(Math.cos(a) * r0, Math.sin(a) * r0); g.lineTo(Math.cos(a) * r1, Math.sin(a) * r1); g.stroke();
      }
      g.strokeStyle = blue(0.7);
      g.beginPath(); g.arc(0, 0, 0.16 * u, 0, TAU); g.stroke();
    });
    // Dashed ring just inside the gold ring (rotates the other way).
    S.dashed = sprite(c.width, (g) => {
      g.strokeStyle = blue(0.6);
      g.lineWidth = Math.max(1, 0.0022 * u);
      g.setLineDash([0.012 * u, 0.008 * u]);
      g.beginPath(); g.arc(0, 0, 0.126 * u, 0, TAU); g.stroke();
      g.setLineDash([]);
      g.strokeStyle = blue(0.35);
      g.beginPath(); g.arc(0, 0, 0.152 * u, 0, TAU); g.stroke();
    });
    // Crosshair + faint diagonal spokes (static).
    S.cross = sprite(c.width, (g) => {
      g.strokeStyle = blue(0.75);
      g.lineWidth = Math.max(1, 0.0018 * u);
      const L = 0.205 * u;
      g.beginPath(); g.moveTo(-L, 0); g.lineTo(L, 0); g.moveTo(0, -L); g.lineTo(0, L); g.stroke();
      g.strokeStyle = blue(0.18);
      for (let i = 0; i < 4; i++) {
        const a = Math.PI / 4 + (i * Math.PI) / 2;
        g.beginPath(); g.moveTo(Math.cos(a) * 0.03 * u, Math.sin(a) * 0.03 * u); g.lineTo(Math.cos(a) * 0.13 * u, Math.sin(a) * 0.13 * u); g.stroke();
      }
      // Bright marks where the crosshair meets the gold ring.
      g.strokeStyle = "rgba(255,240,200,0.95)";
      g.lineWidth = Math.max(1.5, 0.003 * u);
      for (let i = 0; i < 4; i++) {
        const a = (i * Math.PI) / 2;
        g.beginPath();
        g.moveTo(Math.cos(a) * 0.128 * u, Math.sin(a) * 0.128 * u);
        g.lineTo(Math.cos(a) * 0.152 * u, Math.sin(a) * 0.152 * u);
        g.stroke();
      }
    });
    // Golden ring with glow.
    S.gold = sprite(c.width, (g) => {
      const r = 0.14 * u;
      g.lineWidth = 0.032 * u;
      g.strokeStyle = "rgba(255,170,30,0.2)";
      g.beginPath(); g.arc(0, 0, r, 0, TAU); g.stroke();
      g.lineWidth = 0.011 * u;
      g.strokeStyle = "rgba(255,190,50,0.45)";
      g.beginPath(); g.arc(0, 0, r, 0, TAU); g.stroke();
      if (blur) { g.shadowColor = "rgba(255,200,60,0.95)"; g.shadowBlur = 0.012 * u; }
      g.lineWidth = 0.0055 * u;
      g.strokeStyle = "rgba(255,226,140,1)";
      g.beginPath(); g.arc(0, 0, r, 0, TAU); g.stroke();
    });
    // Concentric inner circles over a blue glowing disk (pulse with the voice).
    S.inner = sprite(c.width, (g) => {
      const disk = g.createRadialGradient(0, 0, 0, 0, 0, 0.136 * u);
      disk.addColorStop(0, "rgba(60,160,255,0.55)");
      disk.addColorStop(0.6, "rgba(30,110,255,0.35)");
      disk.addColorStop(0.92, "rgba(40,130,255,0.5)");
      disk.addColorStop(1, "rgba(40,130,255,0)");
      g.fillStyle = disk;
      g.beginPath(); g.arc(0, 0, 0.136 * u, 0, TAU); g.fill();
      g.lineWidth = Math.max(1, 0.0022 * u);
      for (const [r, a] of [[0.086, 0.85], [0.066, 0.7], [0.045, 0.6], [0.105, 0.5], [0.122, 0.45]]) {
        g.strokeStyle = blue(a);
        g.beginPath(); g.arc(0, 0, r * u, 0, TAU); g.stroke();
      }
    });
    // Bright core.
    S.core = sprite(c.width, (g) => {
      const r = 0.075 * u;
      const grad = g.createRadialGradient(0, 0, 0, 0, 0, r);
      grad.addColorStop(0, "rgba(255,255,255,1)");
      grad.addColorStop(0.1, "rgba(220,245,255,0.95)");
      grad.addColorStop(0.3, "rgba(90,190,255,0.6)");
      grad.addColorStop(1, "rgba(30,110,255,0)");
      g.fillStyle = grad;
      g.fillRect(-r, -r, r * 2, r * 2);
    });
    // Two bright scanning arcs on the outer band (rotate faster than the ruler).
    S.scan = sprite(c.width, (g) => {
      g.lineWidth = Math.max(1.5, 0.004 * u);
      g.lineCap = "round";
      for (const [start, len] of [[0, 0.55], [Math.PI, 0.35]]) {
        const grad = g.createLinearGradient(-0.2 * u, 0, 0.2 * u, 0);
        grad.addColorStop(0, "rgba(120,200,255,0.9)");
        grad.addColorStop(1, "rgba(120,200,255,0.9)");
        g.strokeStyle = grad;
        if (blur) { g.shadowColor = "rgba(90,180,255,0.9)"; g.shadowBlur = 0.01 * u; }
        g.beginPath(); g.arc(0, 0, 0.2 * u, start, start + len); g.stroke();
      }
    });
    // Small bright spark that races around the gold ring while thinking.
    S.spark = sprite(Math.round(0.05 * u), (g) => {
      const r = 0.025 * u;
      const grad = g.createRadialGradient(0, 0, 0, 0, 0, r);
      grad.addColorStop(0, "rgba(255,255,240,1)");
      grad.addColorStop(0.3, "rgba(255,220,120,0.7)");
      grad.addColorStop(1, "rgba(255,180,40,0)");
      g.fillStyle = grad;
      g.fillRect(-r, -r, r * 2, r * 2);
    });
    orb.S = S;
    orb.u = u;
  }

  function drawImageRot(g, img, cx, cy, angle, scale, alpha) {
    g.save();
    g.globalAlpha = alpha;
    g.translate(cx, cy);
    if (angle) g.rotate(angle);
    if (scale !== 1) g.scale(scale, scale);
    g.drawImage(img, -img.width / 2, -img.height / 2);
    g.restore();
  }

  function drawOrb(t, dt) {
    const g = orb.g, S = orb.S, c = orb.size / 2;
    g.clearRect(0, 0, orb.size, orb.size);
    g.globalCompositeOperation = "lighter";
    const breathe = app.state === "idle" || app.state === "boot" ? 0.025 * Math.sin(t * 1.4) : 0;
    const voice = app.smooth * cur.pulse;
    orb.angles[0] += 0.05 * cur.spin * dt;
    orb.angles[1] -= 0.09 * cur.spin * dt;
    orb.angles[2] += 1.8 * cur.spin * dt;

    drawImageRot(g, S.haze, c, c, 0, 1 + breathe * 2 + voice * 0.25, 0.75 * cur.glow);
    drawImageRot(g, S.ruler, c, c, orb.angles[0], 1, 0.9 * cur.glow);
    drawImageRot(g, S.dashed, c, c, orb.angles[1], 1, 0.9 * cur.glow);
    drawImageRot(g, S.scan, c, c, orb.angles[0] * 4, 1, 0.75 * cur.glow);
    drawImageRot(g, S.cross, c, c, 0, 1, 0.9 * cur.glow);
    drawImageRot(g, S.gold, c, c, 0, 1 + voice * 0.02, 0.85 + 0.15 * cur.glow);
    drawImageRot(g, S.inner, c, c, 0, 1 + breathe + voice * 0.14, 0.9 * cur.glow);
    drawImageRot(g, S.core, c, c, 0, 1 + breathe * 3 + voice * 0.6, 0.95);
    if (app.state === "thinking") {
      const r = 0.14 * orb.u;
      for (let i = 0; i < 2; i++) {
        const a = orb.angles[2] + i * Math.PI;
        drawImageRot(g, S.spark, c + Math.cos(a) * r, c + Math.sin(a) * r, 0, 1, 0.9);
      }
    }
    g.globalCompositeOperation = "source-over";
  }

  // =====================================================================================
  // 4. Voice bars around the microphone
  // =====================================================================================
  const bars = { canvas: $("bars"), g: null, heights: [], live: [] };

  function setupBars() {
    const c = bars.canvas;
    const r = c.getBoundingClientRect();
    c.width = Math.round(r.width);
    c.height = Math.round(r.height);
    bars.g = c.getContext("2d");
    // A fixed pattern like the reference: mostly short bars with a few tall spikes.
    const R = rng(11);
    bars.heights = Array.from({ length: 30 }, (_, i) => {
      const spike = [4, 9, 13, 20, 26].includes(i) ? 0.95 : 0;
      return Math.max(spike, 0.15 + R() * 0.45);
    });
    bars.live = bars.heights.map(() => 0);
  }

  function drawBars(t) {
    const g = bars.g, c = bars.canvas, W = c.width, H = c.height;
    const cx = W / 2, cy = H / 2, unit = app.H;
    g.clearRect(0, 0, W, H);
    const gap = 0.04 * unit, span = 0.235 * unit, dotsTo = 0.36 * unit;
    const n = bars.heights.length, step = span / n, maxH = H * 0.5;
    const reactive = app.state === "listening" || app.state === "speaking";
    const lv = Math.min(1, app.smooth * 1.4);

    // Dotted guide line beyond the bars, fading out.
    g.fillStyle = "#ffd24a";
    for (let side = -1; side <= 1; side += 2) {
      for (let d = gap + span; d < dotsTo; d += 0.0085 * unit) {
        g.globalAlpha = 0.9 * (1 - (d - gap - span) / (dotsTo - gap - span));
        g.fillRect(cx + side * d - 1, cy - 1, 2, 2);
      }
    }
    g.globalAlpha = 1;
    g.strokeStyle = "#ffd447";
    g.lineWidth = Math.max(1.5, 0.0033 * unit);
    g.shadowColor = "rgba(255,200,40,0.9)";
    g.shadowBlur = app.lowPower ? 0 : 6;
    g.beginPath();
    for (let i = 0; i < n; i++) {
      let target;
      if (reactive) {
        // React to the live level, with a per-bar flicker so it looks like a real waveform.
        const flick = 0.45 + 0.55 * Math.abs(Math.sin(i * 1.7 + t * 11) * Math.cos(i * 0.6 - t * 7));
        // Keep the reference's shape (spikes and short bars), scaled by the live level.
        target = Math.max(0.08, bars.heights[i] * (0.35 + lv * 1.25 * flick));
      } else if (app.state === "thinking") {
        target = 0.12 + 0.5 * Math.max(0, Math.sin(t * 6 - i * 0.45));
      } else {
        target = bars.heights[i] * (0.85 + 0.15 * Math.sin(t * 1.3 + i));
      }
      target = Math.min(1, target) * cur.bars;
      bars.live[i] += (target - bars.live[i]) * 0.35;
      const h = Math.max(1.5, bars.live[i] * maxH);
      for (let side = -1; side <= 1; side += 2) {
        const x = cx + side * (gap + i * step);
        g.moveTo(x, cy - h);
        g.lineTo(x, cy + h);
      }
    }
    g.stroke();
    g.shadowBlur = 0;
    // Thin baseline through the bars.
    g.globalAlpha = 0.7;
    g.fillRect(cx - gap - span, cy - 0.5, span, 1);
    g.fillRect(cx + gap, cy - 0.5, span, 1);
    g.globalAlpha = 1;
  }

  // =====================================================================================
  // Frame loop (FPS cap + automatic low power)
  // =====================================================================================
  let last = 0, frames = 0, slow = 0, work = 0, windowStart = performance.now(), clock = 0;

  function frame(now) {
    requestAnimationFrame(frame);
    if (now - last < 1000 / app.fps - 2) return;
    const dt = Math.min(0.1, (now - last) / 1000 || 1 / 30);
    last = now;
    clock += dt;
    const t0 = performance.now();

    const target = TARGETS[app.state] || TARGETS.idle;
    const k = Math.min(1, dt * 3);
    for (const key in target) cur[key] += (target[key] - cur[key]) * k;
    const lv = app.level;
    app.smooth += (lv - app.smooth) * (lv > app.smooth ? Math.min(1, dt * 16) : Math.min(1, dt * 5));

    if (apex) {
      apex.draw(clock, dt, app.smooth, app.state);
    } else {
      drawWaves(clock);
      drawOrb(clock, dt);
    }
    drawBars(clock);

    const cost = performance.now() - t0;
    work += cost;
    frames++;
    if (cost > 24) slow++;
    if (now - windowStart >= 2000) {
      const fps = (frames * 1000) / (now - windowStart);
      $("st-fps").textContent = `${fps.toFixed(0)} FPS · ${(work / frames).toFixed(1)} ms${app.lowPower ? " · LOW" : ""}`;
      window.__hudPerf = { fps, avgMs: work / frames, slow, lowPower: app.lowPower };
      if (!app.lowPower && slow > frames * 0.3) {
        setLowPower(true);
        addLog("system", "Rendering is slow on this PC: low power mode enabled automatically.");
      }
      frames = 0; slow = 0; work = 0; windowStart = now;
    }
  }

  function setLowPower(on) {
    app.lowPower = on;
    app.fps = on ? 20 : Math.max(app.fps, 30);
    $("btn-lowpower").textContent = `LOW POWER: ${on ? "ON" : "OFF"}`;
    $("btn-lowpower").classList.toggle("on", on);
    if (apex) apex.layout(app.W, app.H, on); else setupOrb();
  }

  function layout() {
    app.H = innerHeight;
    app.W = innerWidth;
    if (apex) {
      apex.layout(app.W, app.H, app.lowPower);
    } else {
      drawSpace();
      setupWaves();
      setupOrb();
    }
    setupBars();
  }
  let resizeTimer = 0;
  addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(layout, 200); });

  // =====================================================================================
  // State, label, panels, log
  // =====================================================================================
  const label = $("label");
  let labelTimer = 0;

  function setState(state) {
    app.state = state in TARGETS ? state : "idle";
    $("mic").classList.toggle("active", app.state === "listening");
    clearTimeout(labelTimer);
    label.classList.remove("caption");
    label.textContent = LABELS[app.state] || app.state.toUpperCase();
    label.classList.toggle("dim", app.state === "paused");
  }

  function showCaption(text) {
    if (!text) return;
    label.classList.add("caption");
    label.classList.remove("dim");
    label.textContent = text;
    clearTimeout(labelTimer);
    labelTimer = setTimeout(() => setState(app.state), 6000);
  }

  const logEl = $("log");
  const entries = new Map();
  const WHO = { user: "YOU", jarvis: "JARVIS", system: "SYSTEM" };
  function addLog(role, text, id) {
    const el = document.createElement("div");
    el.className = `entry ${role}`;
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = WHO[role] || role.toUpperCase();
    const body = document.createElement("span");
    body.className = "text";
    body.textContent = text || "";
    el.append(who, body);
    const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
    logEl.appendChild(el);
    while (logEl.children.length > 80) logEl.removeChild(logEl.firstChild);
    if (atBottom) logEl.scrollTop = logEl.scrollHeight;
    if (id) entries.set(id, body);
  }
  function appendLog(id, text) {
    const body = entries.get(id);
    if (body) body.textContent += text;
  }

  function setField(id, text, cls) {
    const el = $(id);
    el.textContent = text;
    el.className = cls || "";
  }
  function onStatus(s) {
    if (s.model) { setField("st-model", s.model); $("top-ai").textContent = s.model; }
    if (s.voice) setField("st-voice", s.voice, s.voice.includes("OFFLINE") ? "warn" : "ok");
    if (s.mic) {
      setField("st-mic", s.mic, s.mic === "ACTIVE" ? "ok" : s.mic === "MUTED" ? "" : s.mic === "PAUSED" ? "warn" : "bad");
      const paused = s.mic === "PAUSED";
      $("btn-listen").textContent = `MIC: ${paused ? "PAUSED" : "ON"}`;
      $("btn-listen").classList.toggle("on", !paused);
    }
    if (s.network) setField("st-network", s.network, s.network === "ONLINE" ? "ok" : "bad");
    if (s.wake) setField("st-wake", s.wake);
    if (s.model) {
      const provider = s.model.split(" ")[0].toLowerCase();
      document.querySelectorAll("#providers button").forEach((b) => b.classList.toggle("on", b.dataset.provider === provider));
    }
  }
  function onStats(s) {
    $("cpu-val").textContent = s.cpu == null ? "--" : `${Math.round(s.cpu)}%`;
    $("ram-val").textContent = s.ram == null ? "--" : `${Math.round(s.ram)}% · ${s.ram_used_gb}/${s.ram_total_gb} GB`;
    $("bat-val").textContent = s.battery == null ? (s.charging ? "AC" : "--") : `${s.battery}%${s.charging ? " ⚡" : ""}`;
  }
  setInterval(() => {
    const d = new Date();
    const hm = d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    $("clock").textContent = hm;
    $("top-time").textContent = d.toLocaleTimeString("fr-FR");
    $("ov-time").textContent = d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    $("ov-date").textContent = d.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" }).toUpperCase();
    $("top-date").textContent = d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" }).toUpperCase();
  }, 1000);

  // Panels: one open at a time.
  function togglePanel(name) {
    document.querySelectorAll(".panel").forEach((p) => {
      const show = p.id === `panel-${name}` && p.hidden;
      p.hidden = !show;
      if (show) { const input = p.querySelector("input"); if (input) setTimeout(() => input.focus(), 30); }
    });
    document.querySelectorAll(".controls button[data-panel]").forEach((b) => {
      b.classList.toggle("on", b.dataset.panel === name && !$(`panel-${name}`).hidden);
    });
  }
  function closePanels() {
    document.querySelectorAll(".panel").forEach((p) => (p.hidden = true));
    document.querySelectorAll(".controls button[data-panel]").forEach((b) => b.classList.remove("on"));
  }

  // =====================================================================================
  // Talking to Python
  // =====================================================================================
  async function post(path, body) {
    try {
      const r = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Jarvis-Token": TOKEN },
        body: JSON.stringify(body),
      });
      if (!r.ok) addLog("system", `Request rejected (${r.status}).`);
    } catch {
      addLog("system", "Apex is not reachable.");
    }
  }
  const action = (name, value) => post("/api/action", { action: name, value: value || "" });
  const command = (text) => post("/api/command", { text });

  document.querySelectorAll(".controls button").forEach((b) => {
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      if (b.dataset.panel) togglePanel(b.dataset.panel);
      else if (b.dataset.action) action(b.dataset.action);
    });
  });
  document.querySelectorAll(".panel button[data-action]").forEach((b) => b.addEventListener("click", () => action(b.dataset.action)));
  document.querySelectorAll("#providers button").forEach((b) => b.addEventListener("click", () => action("switch_ai", b.dataset.provider)));
  $("btn-lowpower").addEventListener("click", () => setLowPower(!app.lowPower));
  $("mic").addEventListener("click", (e) => { e.stopPropagation(); action("listen"); });
  $("command-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("command");
    if (input.value.trim()) command(input.value.trim());
    input.value = "";
  });
  $("web-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("web-query");
    if (input.value.trim()) { command(`cherche ${input.value.trim()}`); closePanels(); }
    input.value = "";
  });
  document.querySelectorAll(".panel").forEach((p) => p.addEventListener("click", (e) => e.stopPropagation()));
  document.addEventListener("click", closePanels);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePanels();
    const typing = document.activeElement && document.activeElement.tagName === "INPUT";
    if (e.code === "Space" && !typing) { e.preventDefault(); action("listen"); }
  });

  function finishBoot() {
    document.body.classList.add("ready");
    if (app.state === "boot") setState("idle");
  }
  setTimeout(finishBoot, 6000); // never stay invisible

  function handle(msg) {
    switch (msg.type) {
      case "config":
        app.fps = Math.max(10, Math.min(60, msg.fps || 30));
        if (msg.low_power) setLowPower(true);
        break;
      case "boot": addLog("system", (msg.ok === false ? "[FAIL] " : "[ OK ] ") + msg.text); break;
      case "ready": finishBoot(); break;
      case "state": setState(msg.state); if (msg.state === "error") document.body.classList.add("ready"); break;
      case "level": app.level = Math.max(0, Math.min(1, msg.value || 0)); break;
      case "partial": if (app.state === "listening") showCaption(msg.text); break;
      case "log":
        addLog(msg.role, msg.text, msg.id);
        if (msg.role === "user" && msg.text) showCaption(`« ${msg.text} »`);
        if (msg.role !== "system") transcriptAdd(msg.role, msg.text || "", msg.id);
        break;
      case "log_append": appendLog(msg.id, msg.text); transcriptAppend(msg.id, msg.text); break;
      case "tool": if (apex) apex.activate(msg.name); break;
      case "qr": showQr(msg.png, msg.url); break;
      case "stats": onStats(msg); break;
      case "status": onStatus(msg); break;
      default: break;
    }
  }
  // iPhone pairing QR code (closes by itself after 3 minutes).
  let qrTimer = 0;
  function showQr(png, url) {
    $("qr-img").src = `data:image/png;base64,${png}`;
    $("qr-url").textContent = url || "";
    $("qr").hidden = false;
    clearTimeout(qrTimer);
    qrTimer = setTimeout(() => { $("qr").hidden = true; }, 180000);
  }
  $("qr-close").addEventListener("click", () => { $("qr").hidden = true; });

  // Last exchange, bottom-left (agent-orb style).
  const transcript = $("transcript");
  const tEntries = new Map();
  function transcriptAdd(role, text, id) {
    const p = document.createElement("p");
    p.className = role;
    const who = document.createElement("b");
    who.textContent = role === "user" ? "VOUS" : "APEX";
    const body = document.createElement("span");
    body.textContent = text;
    p.append(who, body);
    transcript.appendChild(p);
    while (transcript.children.length > 2) transcript.removeChild(transcript.firstChild);
    if (id) tEntries.set(id, body);
  }
  function transcriptAppend(id, text) {
    const body = tEntries.get(id);
    if (body) body.textContent += text;
  }

  window.__hudHandle = handle; // debugging/tests

  function connect() {
    const source = new EventSource(`/events?token=${encodeURIComponent(TOKEN)}`);
    source.onopen = () => { $("disconnected").hidden = true; };
    source.onmessage = (e) => { try { handle(JSON.parse(e.data)); } catch (err) { console.error(err); } };
    source.onerror = () => { $("disconnected").hidden = false; };
  }

  layout();
  setState("boot");
  connect();
  requestAnimationFrame(frame);
})();
