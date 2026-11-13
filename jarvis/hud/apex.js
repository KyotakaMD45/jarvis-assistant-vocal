/* Apex HUD, "agent orb" style (layout inspired by the MIT-licensed APEX-UI project by
 * Ruben Mouradian / Reznikov Engineering - see CREDITS.md; no code or branding copied):
 * teal backdrop with circuit traces, a golden ring around a cyan particle core, and the
 * assistant's real capabilities as nodes that light up when Apex uses them.
 *
 * Everything static (backdrop, traces, ring) is pre-rendered once per window size; each frame
 * only draws the particle core, the node links and a few glows.
 */
(() => {
  "use strict";
  const TAU = Math.PI * 2;

  // Capabilities shown around the core, and the commands (tool names) that light them up.
  const NODES = [
    { id: "ai", label: "IA", tools: [], color: "cyan" },
    { id: "messages", label: "Messages", tools: ["send_message"], color: "gold" },
    { id: "web", label: "Web", tools: ["web_search", "open_website", "ask_web_ai"], color: "cyan" },
    { id: "apps", label: "Applications", tools: ["open_app", "close_app"], color: "gold" },
    { id: "music", label: "Musique", tools: ["play_music", "media_control", "volume"], color: "cyan" },
    { id: "screen", label: "Écran", tools: ["screen_look", "click_element", "fill_field", "window_control"], color: "cyan" },
    { id: "keyboard", label: "Clavier", tools: ["keyboard_shortcut", "type_text"], color: "gold" },
    { id: "text", label: "Texte", tools: ["selected_text", "read_clipboard"], color: "cyan" },
    { id: "system", label: "Système", tools: ["system_control", "system_info", "windows_settings"], color: "gold" },
    { id: "files", label: "Fichiers", tools: ["search_files", "empty_recycle_bin"], color: "cyan" },
    { id: "reminders", label: "Rappels", tools: ["set_reminder", "set_timer", "list_reminders", "clear_reminders", "tell_time", "tell_date"], color: "gold" },
    { id: "voice", label: "Voix", tools: ["learn_voice", "forget_voice", "voice_test"], color: "cyan" },
  ];
  const COLORS = {
    cyan: { ring: "rgba(64,214,255,1)", glow: "rgba(40,180,255,0.55)", text: "#dff6ff" },
    gold: { ring: "rgba(255,180,60,1)", glow: "rgba(255,160,40,0.5)", text: "#ffe9c4" },
  };

  function rng(seed) {
    let s = seed >>> 0;
    return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  }
  function canvas(w, h) {
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.ceil(w));
    c.height = Math.max(1, Math.ceil(h));
    return c;
  }

  class KnullApex {
    constructor() {
      this.space = document.getElementById("space");
      this.orb = document.getElementById("orb");
      this.web = document.getElementById("web");
      this.gWeb = this.web.getContext("2d");
      this.gOrb = this.orb.getContext("2d");
      this.activity = Object.fromEntries(NODES.map((n) => [n.id, 0]));
      this.spin = 0;
      this.swirl = 0;
    }

    // ---------------------------------------------------------------------------------------
    layout(W, H, lowPower) {
      this.W = W; this.H = H; this.lowPower = lowPower;
      this.dpr = Math.min(devicePixelRatio || 1, lowPower ? 1 : 1.5);
      // Orb: same place as the classic HUD (centre at 44 % of the height).
      this.cx = W / 2; this.cy = H * 0.44;
      this.R = H * 0.205;                       // golden ring radius (CSS px)
      const size = Math.round(this.R * 2.9);
      this.orbSize = size;
      const o = this.orb;
      o.style.width = o.style.height = `${size}px`;
      o.style.top = `${this.cy - size / 2}px`;
      o.width = o.height = Math.round(size * this.dpr);
      const w = this.web;
      w.style.width = `${W}px`; w.style.height = `${H}px`;
      w.width = Math.round(W * this.dpr); w.height = Math.round(H * this.dpr);
      this.placeNodes();
      this.drawBackdrop();
      this.buildRing();
      this.buildParticles();
    }

    placeNodes() {
      // Two arcs (left and right of the ring), leaving the top and bottom free.
      const { cx, cy, R } = this;
      const left = NODES.filter((_, i) => i % 2 === 0), right = NODES.filter((_, i) => i % 2 === 1);
      const place = (list, side) => list.forEach((n, i) => {
        const t = list.length === 1 ? 0.5 : i / (list.length - 1);
        const ang = (side < 0 ? Math.PI : 0) + side * (-0.95 + t * 1.9) * -1;
        const rad = R * (1.55 + 0.18 * Math.sin(i * 1.7 + (side > 0 ? 1 : 0)));
        n.x = cx + Math.cos(ang) * rad;
        n.y = cy + Math.sin(ang) * rad * 0.92;
        n.side = side;
      });
      place(left, -1);
      place(right, 1);
    }

    // Static backdrop: teal gradient, faint grid, circuit traces from each node to the edges.
    drawBackdrop() {
      const { W, H } = this, d = this.dpr;
      const c = this.space;
      c.width = Math.round(W * d); c.height = Math.round(H * d);
      c.style.width = `${W}px`; c.style.height = `${H}px`;
      const g = c.getContext("2d");
      g.scale(d, d);
      const bg = g.createRadialGradient(this.cx, this.cy, 0, this.cx, this.cy, Math.hypot(W, H) * 0.6);
      bg.addColorStop(0, "#0d2a3b");
      bg.addColorStop(0.45, "#081a27");
      bg.addColorStop(1, "#02070c");
      g.fillStyle = bg;
      g.fillRect(0, 0, W, H);
      // Grid
      g.strokeStyle = "rgba(90,190,255,0.05)";
      g.lineWidth = 1;
      const step = H * 0.045;
      g.beginPath();
      for (let x = (W / 2) % step; x < W; x += step) { g.moveTo(x, 0); g.lineTo(x, H); }
      for (let y = (H / 2) % step; y < H; y += step) { g.moveTo(0, y); g.lineTo(W, y); }
      g.stroke();
      // Circuit traces: from each node towards the nearest side, with one right-angle step.
      const R = rng(7);
      g.lineWidth = Math.max(1, H * 0.0016);
      for (const n of NODES) {
        for (let k = 0; k < 2; k++) {
          const dir = n.side;
          const y0 = n.y + (k ? (R() - 0.5) * H * 0.08 : 0);
          const x1 = n.x + dir * (H * 0.04 + R() * H * 0.08);
          const y1 = y0 + (R() - 0.5) * H * 0.06;
          const x2 = dir < 0 ? H * 0.025 + R() * W * 0.06 : W - H * 0.025 - R() * W * 0.06;
          g.strokeStyle = `rgba(70,200,255,${0.16 + R() * 0.14})`;
          g.beginPath();
          g.moveTo(n.x + dir * H * 0.022, n.y);
          g.lineTo(x1, n.y);
          g.lineTo(x1 + dir * Math.abs(y1 - n.y), y1);
          g.lineTo(x2, y1);
          g.stroke();
          g.fillStyle = "rgba(90,220,255,0.75)";
          g.beginPath(); g.arc(x2, y1, H * 0.004, 0, TAU); g.fill();
        }
      }
      // A few loose traces for depth
      for (let i = 0; i < 10; i++) {
        const x = R() * W, y = R() * H;
        if (Math.hypot(x - this.cx, y - this.cy) < this.R * 1.9) continue;
        g.strokeStyle = `rgba(70,200,255,${0.06 + R() * 0.08})`;
        g.beginPath(); g.moveTo(x, y); g.lineTo(x + (R() - 0.5) * W * 0.25, y); g.stroke();
      }
      // Vignette
      const v = g.createRadialGradient(this.cx, this.cy, H * 0.3, this.cx, this.cy, Math.hypot(W, H) * 0.65);
      v.addColorStop(0, "rgba(0,0,0,0)");
      v.addColorStop(1, "rgba(0,0,0,0.55)");
      g.fillStyle = v;
      g.fillRect(0, 0, W, H);
    }

    // Golden ring + inner rings, pre-rendered (drawn each frame with a little breathing).
    buildRing() {
      const d = this.dpr, R = this.R * d, size = this.orb.width;
      const c = canvas(size, size), g = c.getContext("2d");
      const m = size / 2;
      // outer halo
      const halo = g.createRadialGradient(m, m, R * 0.85, m, m, R * 1.35);
      halo.addColorStop(0, "rgba(255,170,40,0)");
      halo.addColorStop(0.35, "rgba(255,170,40,0.18)");
      halo.addColorStop(1, "rgba(255,170,40,0)");
      g.fillStyle = halo;
      g.fillRect(0, 0, size, size);
      // thin cyan inner rings
      g.strokeStyle = "rgba(80,200,255,0.25)";
      g.lineWidth = Math.max(1, R * 0.006);
      for (const k of [0.62, 0.8, 0.9]) { g.beginPath(); g.arc(m, m, R * k, 0, TAU); g.stroke(); }
      // golden ring with glow
      g.save();
      if (!this.lowPower) { g.shadowColor = "rgba(255,170,40,0.95)"; g.shadowBlur = R * 0.12; }
      const gold = g.createLinearGradient(m - R, m - R, m + R, m + R);
      gold.addColorStop(0, "#ffd77a");
      gold.addColorStop(0.5, "#ffae2e");
      gold.addColorStop(1, "#ffcf63");
      g.strokeStyle = gold;
      g.lineWidth = R * 0.045;
      g.beginPath(); g.arc(m, m, R, 0, TAU); g.stroke();
      g.restore();
      g.strokeStyle = "rgba(255,236,190,0.9)";
      g.lineWidth = Math.max(1, R * 0.01);
      g.beginPath(); g.arc(m, m, R, 0, TAU); g.stroke();
      // tick marks just outside the ring
      g.strokeStyle = "rgba(255,200,110,0.35)";
      g.lineWidth = Math.max(1, R * 0.006);
      for (let i = 0; i < 120; i++) {
        const a = (i / 120) * TAU, r1 = R * 1.06, r2 = R * (i % 10 === 0 ? 1.11 : 1.08);
        g.beginPath(); g.moveTo(m + Math.cos(a) * r1, m + Math.sin(a) * r1); g.lineTo(m + Math.cos(a) * r2, m + Math.sin(a) * r2); g.stroke();
      }
      this.ring = c;
      // soft cyan glow for the core
      const glow = canvas(R * 1.6, R * 1.6), gg = glow.getContext("2d"), h = glow.width / 2;
      const gr = gg.createRadialGradient(h, h, 0, h, h, h);
      gr.addColorStop(0, "rgba(120,240,255,0.55)");
      gr.addColorStop(0.35, "rgba(40,170,255,0.18)");
      gr.addColorStop(1, "rgba(20,90,200,0)");
      gg.fillStyle = gr;
      gg.fillRect(0, 0, glow.width, glow.height);
      this.coreGlow = glow;
    }

    buildParticles() {
      const n = this.lowPower ? 450 : 1100;
      const R = rng(11);
      this.parts = [];
      for (let i = 0; i < n; i++) {
        // Volumetric cloud: denser in the middle, a few strays outside.
        const u = R(), v = R();
        const th = TAU * u, ph = Math.acos(2 * v - 1);
        const r = Math.pow(R(), 0.55) * (R() < 0.08 ? 1.15 : 0.9);
        this.parts.push({ x: Math.sin(ph) * Math.cos(th) * r, y: Math.cos(ph) * r, z: Math.sin(ph) * Math.sin(th) * r,
                          s: 0.6 + R() * 1.1, w: R() * TAU });
      }
    }

    // ---------------------------------------------------------------------------------------
    activate(tool) {
      for (const n of NODES) if (n.tools.includes(tool)) this.activity[n.id] = 1;
    }

    draw(t, dt, level, state) {
      if (!this.ring) return;
      const thinking = state === "thinking", speaking = state === "speaking", listening = state === "listening";
      if (thinking) this.activity.ai = Math.max(this.activity.ai, 0.8);
      for (const k in this.activity) this.activity[k] = Math.max(0, this.activity[k] - dt * 0.35);
      this.spin += dt * (thinking ? 1.6 : speaking ? 0.7 : 0.35);
      this.swirl += dt * (thinking ? 2.5 : 0.3);
      this.drawOrb(t, level, state);
      this.drawLinks(t, state);
    }

    drawOrb(t, level, state) {
      const g = this.gOrb, d = this.dpr, size = this.orb.width, m = size / 2;
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.clearRect(0, 0, size, size);
      const voice = state === "speaking" ? level : state === "listening" ? level * 0.6 : 0;
      const breathe = 1 + 0.015 * Math.sin(t * 1.3) + voice * 0.03;
      g.globalCompositeOperation = "lighter";
      g.globalAlpha = state === "paused" ? 0.5 : 1;
      g.drawImage(this.ring, m - (size * breathe) / 2, m - (size * breathe) / 2, size * breathe, size * breathe);
      // Orbiting dots on the ring
      const R = this.R * d;
      for (let i = 0; i < 3; i++) {
        const a = t * (0.35 + i * 0.12) + i * 2.1;
        const x = m + Math.cos(a) * R * 1.0, y = m + Math.sin(a) * R * 1.0;
        g.fillStyle = "rgba(255,230,170,0.95)";
        g.beginPath(); g.arc(x, y, R * 0.018, 0, TAU); g.fill();
      }
      // Core glow
      const cg = this.coreGlow, gs = (0.9 + voice * 0.5) * breathe;
      g.globalAlpha = 0.85;
      g.drawImage(cg, m - (cg.width * gs) / 2, m - (cg.height * gs) / 2, cg.width * gs, cg.height * gs);
      // Particle core: a rotating volumetric cloud.
      const radius = R * (0.6 + voice * 0.14 + (state === "listening" ? 0.02 * Math.sin(t * 6) : 0));
      const ca = Math.cos(this.spin), sa = Math.sin(this.spin), tilt = 0.35, ct = Math.cos(tilt), st = Math.sin(tilt);
      const px = Math.max(1.2, R * 0.0105);
      g.globalAlpha = 1;
      for (const p of this.parts) {
        let x = p.x, y = p.y, z = p.z;
        if (state === "thinking") { const k = Math.sin(this.swirl + p.w) * 0.08; x += k * y; y -= k * x; }
        const x1 = x * ca + z * sa, z1 = -x * sa + z * ca;
        const y2 = y * ct - z1 * st, z2 = y * st + z1 * ct;
        const f = 1 / (1.6 - z2 * 0.5);
        const sx = m + x1 * radius * f * 1.4, sy = m + y2 * radius * f * 1.4;
        const a = Math.max(0.12, Math.min(1, 0.5 + z2 * 0.5 + (state === "speaking" ? voice * 0.5 : 0)));
        const tw = 0.75 + 0.25 * Math.sin(t * 3 + p.w);
        g.fillStyle = state === "error" ? `rgba(255,120,110,${a * tw})` : `rgba(110,235,255,${a * tw})`;
        const s = px * p.s * f;
        g.fillRect(sx - s / 2, sy - s / 2, s, s);
      }
      g.globalCompositeOperation = "source-over";
      g.globalAlpha = 1;
    }

    drawLinks(t, state) {
      const g = this.gWeb, d = this.dpr;
      g.setTransform(d, 0, 0, d, 0, 0);
      g.clearRect(0, 0, this.W, this.H);
      const { cx, cy, R, H } = this;
      const fontPx = Math.round(H * 0.019);
      g.font = `500 ${fontPx}px Bahnschrift, "Segoe UI", sans-serif`;
      g.textBaseline = "middle";
      for (const n of NODES) {
        const act = this.activity[n.id];
        const col = COLORS[n.color];
        // Link to the ring (a soft curve), brighter when the node is active.
        const ang = Math.atan2(n.y - cy, n.x - cx);
        const ex = cx + Math.cos(ang) * R * 1.03, ey = cy + Math.sin(ang) * R * 1.03;
        const mx = (n.x + ex) / 2 + Math.sin(ang) * R * 0.15, my = (n.y + ey) / 2 - Math.cos(ang) * R * 0.15;
        g.strokeStyle = `rgba(90,210,255,${0.16 + act * 0.6})`;
        g.lineWidth = Math.max(1, H * 0.0013) * (1 + act);
        g.beginPath(); g.moveTo(n.x, n.y); g.quadraticCurveTo(mx, my, ex, ey); g.stroke();
        if (act > 0.05) {   // a pulse running towards the core
          const k = (t * 1.6 + n.x * 0.001) % 1;
          const qx = (1 - k) * (1 - k) * n.x + 2 * (1 - k) * k * mx + k * k * ex;
          const qy = (1 - k) * (1 - k) * n.y + 2 * (1 - k) * k * my + k * k * ey;
          g.fillStyle = `rgba(200,250,255,${act})`;
          g.beginPath(); g.arc(qx, qy, H * 0.004, 0, TAU); g.fill();
        }
        // Node: glowing ring
        const r = H * (0.0105 + act * 0.003);
        g.save();
        if (!this.lowPower) { g.shadowColor = col.glow; g.shadowBlur = H * (0.012 + act * 0.02); }
        g.strokeStyle = col.ring;
        g.globalAlpha = 0.65 + act * 0.35;
        g.lineWidth = Math.max(1.5, H * 0.0028);
        g.beginPath(); g.arc(n.x, n.y, r, 0, TAU); g.stroke();
        if (act > 0.05) { g.fillStyle = col.glow; g.beginPath(); g.arc(n.x, n.y, r * 0.55, 0, TAU); g.fill(); }
        g.restore();
        // Label
        g.globalAlpha = 0.72 + act * 0.28;
        g.fillStyle = col.text;
        g.textAlign = n.side < 0 ? "right" : "left";
        g.fillText(n.label, n.x + n.side * -1 * -H * 0.022, n.y - (n.side < 0 ? 0 : 0));
        g.globalAlpha = 1;
      }
    }
  }

  window.KnullApex = KnullApex;
})();
