/* Jarvis holographic avatar: a man made of light filaments (head + shoulders + chest).
 *
 * - The body (contours + hundreds of energy filaments) is pre-rendered ONCE into a sprite.
 * - Per frame only the head (it turns: yaw/pitch), a few animated energy pulses, the chest core
 *   and some sparkles are drawn, so it stays light on integrated graphics.
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

      // Hair strands (short, swept back) - stored, drawn with the head.
      this.hair = Array.from({ length: this.lowPower ? 10 : 22 }, () => ({
        x: (R() - 0.5) * 0.17, y: -0.115 - R() * 0.02, len: 0.06 + R() * 0.06, curl: (R() - 0.5) * 0.04, a: 0.25 + R() * 0.5,
      }));
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

    drawHead(t, voice) {
      const { g, s, cx } = this;
      const yaw = this.yaw, pitch = this.pitch;
      const hx = yaw * 0.032, hy = 0.19 + pitch * 0.02;
      const X = (x) => cx + (hx + x) * s, Y = (y) => (hy + y) * s;
      const rimWidth = Math.max(1.4, 0.0042 * s);

      // Neck (connects the head to the body sprite).
      g.globalCompositeOperation = "lighter";
      g.strokeStyle = "rgba(235,245,255,1)";
      for (const side of [-1, 1]) {
        const p = new Path2D();
        p.moveTo(X(side * 0.05), Y(0.12));
        p.bezierCurveTo(X(side * 0.052), Y(0.17), cx + side * 0.056 * s, 0.39 * s, cx + side * 0.058 * s, 0.43 * s);
        g.globalAlpha = 0.25 * this.glow; g.lineWidth = rimWidth * 4; g.strokeStyle = "rgba(80,140,255,1)"; g.stroke(p);
        g.globalAlpha = 0.9 * this.glow; g.lineWidth = rimWidth * 0.8; g.strokeStyle = "rgba(235,245,255,1)"; g.stroke(p);
      }

      // Head silhouette (male: squarer jaw).
      const head = new Path2D();
      head.moveTo(X(0), Y(-0.16));
      head.bezierCurveTo(X(0.075), Y(-0.16), X(0.11), Y(-0.11), X(0.108), Y(-0.03));
      head.bezierCurveTo(X(0.106), Y(0.03), X(0.1), Y(0.07), X(0.085), Y(0.1));
      head.bezierCurveTo(X(0.07), Y(0.13), X(0.04), Y(0.155), X(0), Y(0.158));
      head.bezierCurveTo(X(-0.04), Y(0.155), X(-0.07), Y(0.13), X(-0.085), Y(0.1));
      head.bezierCurveTo(X(-0.1), Y(0.07), X(-0.106), Y(0.03), X(-0.108), Y(-0.03));
      head.bezierCurveTo(X(-0.11), Y(-0.11), X(-0.075), Y(-0.16), X(0), Y(-0.16));

      // Dark faceplate (fills the head, the "face" is a smooth visor).
      g.globalCompositeOperation = "source-over";
      g.globalAlpha = 0.92;
      const vx = yaw * 0.05, vy = pitch * 0.045;
      const visor = g.createRadialGradient(X(vx), Y(vy), 0, X(vx), Y(vy), 0.17 * s);
      visor.addColorStop(0, "rgba(14,30,80,1)");
      visor.addColorStop(0.6, "rgba(4,10,34,1)");
      visor.addColorStop(1, "rgba(2,4,16,1)");
      g.fillStyle = visor;
      g.fill(head);

      g.globalCompositeOperation = "lighter";
      // Rim light.
      g.globalAlpha = 0.28 * this.glow; g.lineWidth = rimWidth * 5; g.strokeStyle = "rgba(80,140,255,1)"; g.stroke(head);
      g.globalAlpha = 0.95 * this.glow; g.lineWidth = rimWidth; g.strokeStyle = "rgba(235,245,255,1)"; g.stroke(head);

      // Visor sheen: a vertical highlight that moves with the head (shows where he looks).
      const sheenX = X(vx * 1.25);
      const sheen = g.createLinearGradient(sheenX - 0.02 * s, 0, sheenX + 0.02 * s, 0);
      sheen.addColorStop(0, "rgba(60,120,255,0)");
      sheen.addColorStop(0.5, "rgba(110,170,255,0.35)");
      sheen.addColorStop(1, "rgba(60,120,255,0)");
      g.globalAlpha = 1;
      g.fillStyle = sheen;
      g.save(); g.clip(head);
      g.fillRect(sheenX - 0.02 * s, Y(-0.12 + vy), 0.04 * s, 0.25 * s);
      if (this.state === "thinking") {
        const band = Y(-0.15 + ((t * 0.35) % 1) * 0.32);
        g.fillStyle = "rgba(120,180,255,0.18)";
        g.fillRect(X(-0.12), band, 0.24 * s, 0.012 * s);
      }
      g.restore();

      // Eyes: two glowing slits that follow the gaze.
      const eyeY = Y(-0.005 + vy * 1.1);
      const eyeBright = Math.min(1, 0.45 + (this.state === "listening" ? 0.35 : 0) + voice * 0.7) * this.glow;
      const err = this.state === "error";
      for (const side of [-1, 1]) {
        const near = side * Math.sign(yaw || 1) > 0 ? 1 : 0;
        const squeeze = 1 - Math.abs(yaw) * (near ? 0.15 : 0.55);
        const ex = X(vx * 1.1 + side * 0.04 * squeeze);
        const len = 0.028 * s * squeeze;
        g.globalAlpha = eyeBright * 0.8;
        const es = this.eyeSprite;
        g.drawImage(es, ex - es.width * 0.35, eyeY - es.height * 0.18, es.width * 0.7, es.height * 0.36);
        g.globalAlpha = eyeBright;
        g.strokeStyle = err ? "rgba(255,110,90,1)" : "rgba(235,248,255,1)";
        g.lineWidth = Math.max(1.5, 0.006 * s);
        g.lineCap = "round";
        g.beginPath(); g.moveTo(ex - len / 2, eyeY); g.lineTo(ex + len / 2, eyeY); g.stroke();
      }
      // Mouth line, opening slightly with the voice.
      const my = Y(0.088 + vy * 0.6), mx = X(vx * 1.2);
      const open = voice * 0.012 * s;
      g.globalAlpha = (0.25 + voice * 0.7) * this.glow;
      g.strokeStyle = "rgba(170,210,255,1)";
      g.lineWidth = Math.max(1, 0.003 * s);
      g.beginPath(); g.moveTo(mx - 0.022 * s, my - open / 2); g.lineTo(mx + 0.022 * s, my - open / 2);
      if (open > 1) { g.moveTo(mx - 0.018 * s, my + open / 2); g.lineTo(mx + 0.018 * s, my + open / 2); }
      g.stroke();

      // Far ear appears when the head turns.
      if (Math.abs(yaw) > 0.15) {
        const side = -Math.sign(yaw);
        const ex = X(side * 0.106);
        g.globalAlpha = Math.min(1, (Math.abs(yaw) - 0.15) * 1.5) * 0.8 * this.glow;
        g.strokeStyle = "rgba(200,225,255,1)";
        g.lineWidth = Math.max(1, 0.003 * s);
        g.beginPath();
        g.moveTo(ex, Y(-0.03));
        g.bezierCurveTo(ex + side * 0.018 * s, Y(-0.025), ex + side * 0.018 * s, Y(0.03), ex, Y(0.035));
        g.stroke();
      }

      // Short hair swept back.
      g.lineWidth = Math.max(1, 0.0022 * s);
      for (const hs of this.hair) {
        g.globalAlpha = hs.a * this.glow;
        g.strokeStyle = "rgba(200,220,255,1)";
        const x0 = X(hs.x + yaw * 0.015), y0 = Y(hs.y + 0.005);
        g.beginPath();
        g.moveTo(x0, y0);
        g.quadraticCurveTo(x0 + (hs.curl - yaw * 0.02) * s, y0 - hs.len * 0.4 * s, x0 + (hs.curl * 1.5 - yaw * 0.03) * s, y0 - hs.len * 0.2 * s + 0.02 * s);
        g.stroke();
      }
    }
  }

  window.JarvisAvatar = Avatar;
})();
