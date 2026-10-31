/* Layer 1: foundations. The namespace, springs, the element base, markup helpers,
   the glass material and the icon registry. Classic script (no modules), so pages
   work straight from disk and inside web views. */
(() => {
  "use strict";
  const LG = (window.LiquidGlass = window.LiquidGlass || {});

  LG.$ = (selector, root = document) => root.querySelector(selector);
  LG.$$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  LG.clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  LG.escape = text => String(text).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  /* h(tag, attributes, children) builds markup for kit elements. Attribute values and
     string children are escaped; `true` writes a bare attribute; false, null and undefined
     omit it. Children may be strings (text), h() results, or arrays of them. */
  const RAW = Symbol("markup");
  const markup = html => ({ [RAW]: html, toString: () => html });
  const child = c => c == null || c === false ? "" : Array.isArray(c) ? c.map(child).join("") : c[RAW] !== undefined ? c[RAW] : LG.escape(c);
  LG.h = (tag, attributes = {}, children = []) => {
    const attrs = Object.entries(attributes).filter(([, v]) => v !== false && v != null)
      .map(([k, v]) => v === true ? ` ${k}` : ` ${k}="${LG.escape(v)}"`).join("");
    return markup(`<${tag}${attrs}>${child(children)}</${tag}>`);
  };
  LG.markup = markup;
  LG.html = (...parts) => markup(parts.map(child).join(""));
  // Parse markup into a single element.
  LG.fragment = html => { const t = document.createElement("template"); t.innerHTML = String(html); return t.content.firstElementChild; };

  // Apple's projection: where a flick comes to rest under exponential deceleration.
  LG.project = (velocity, rate = 0.998) => (velocity / 1000) * rate / (1 - rate);
  // Past a boundary, follow less the further the pointer goes.
  LG.rubberband = (overshoot, dimension, constant = 0.55) => (overshoot * dimension * constant) / (dimension + constant * Math.abs(overshoot));

  /* Springs use Apple's two designer parameters: damping ratio (1 = no overshoot)
     and response (seconds to reach the target). They retarget from the live value
     and velocity, so every animation can be interrupted. */
  const active = new Set();
  let last = 0;
  function tick(now) {
    const dt = Math.min(0.064, (now - (last || now)) / 1000);
    last = now;
    for (const spring of [...active]) spring.step(dt);
    if (active.size) requestAnimationFrame(tick);
    else last = 0;
  }
  class Spring {
    constructor(value, onUpdate, { damping = 1, response = 0.4 } = {}) {
      Object.assign(this, { value, target: value, velocity: 0, onUpdate, damping, response, done: null });
    }
    to(target, { velocity, damping, response, done } = {}) {
      this.target = target;
      this.done = done || null;
      if (velocity !== undefined) this.velocity = velocity;
      if (damping !== undefined) this.damping = damping;
      if (response !== undefined) this.response = response;
      if (!active.size) requestAnimationFrame(tick);
      active.add(this);
      return this;
    }
    set(value) {
      this.value = this.target = value;
      this.velocity = 0;
      active.delete(this);
      this.onUpdate(value);
      const done = this.done;
      this.done = null;
      if (done) done();
      return this;
    }
    step(dt) {
      const omega = (2 * Math.PI) / this.response, stiffness = omega * omega, friction = 2 * this.damping * omega;
      const steps = Math.ceil(dt * 240), h = dt / steps;
      for (let i = 0; i < steps; i++) {
        this.velocity += (-stiffness * (this.value - this.target) - friction * this.velocity) * h;
        this.value += this.velocity * h;
      }
      const scale = Math.max(1, Math.abs(this.target));
      if (Math.abs(this.velocity) < 0.002 * scale && Math.abs(this.value - this.target) < 0.0005 * scale) return this.set(this.target);
      this.onUpdate(this.value);
    }
  }
  LG.Spring = Spring;
  // True while any spring is in flight; tests and measurements wait for rest.
  LG.moving = () => active.size > 0;
  // Presets from Apple's fluid-interface guidance.
  LG.motion = {
    default: { damping: 1, response: 0.4 },
    morph: { damping: 0.86, response: 0.42 },
    appear: { damping: 0.8, response: 0.42 },
    throw: { damping: 0.8, response: 0.4 },
    slide: { damping: 0.9, response: 0.38 },
    press: { damping: 0.7, response: 0.22 },
    release: { damping: 0.55, response: 0.38 },
  };

  // A surface's scheme: small glass follows the content beneath, large glass the appearance.
  LG.scheme = (el, scheme) => {
    el.classList.toggle("lg-light", scheme === "light");
    el.classList.toggle("lg-dark", scheme === "dark");
  };

  /* Element base: kit elements render light DOM once, when first connected, and
     re-render when an observed attribute changes. */
  class Element extends HTMLElement {
    connectedCallback() {
      if (this.built) return;
      this.built = true;
      this.build();
    }
    attributeChangedCallback() { if (this.built) this.update(); }
    build() { this.update(); }
    update() {}
  }
  LG.Element = Element;
  LG.define = (name, constructor) => { if (!customElements.get(name)) customElements.define(name, constructor); };

  /* Icons: one registered set; `filled` variants mark active states, as SF Symbols' .fill does. */
  let iconSet = null;
  LG.icons = { register(set) { iconSet = set; } };
  LG.iconSvg = (name, filled = false) => {
    // A small rounded square reads as Stop at toolbar size, like SF Symbols' stop.fill.
    if (name === "stop") return `<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="4.25" y="4.25" width="7.5" height="7.5" rx="1.8"/></svg>`;
    const body = (filled && iconSet.filled[name]) || iconSet.regular[name];
    if (!body) throw new Error(`Unknown icon: ${name}`);
    return `<svg viewBox="${iconSet.viewBox}" aria-hidden="true">${body}</svg>`;
  };

  /* ── Material ─────────────────────────────────────────────────────
     Lens refraction: one displacement map per glass shape. R and G bend the backdrop
     toward the centre near the rim; B marks the rim band, where a sharper, bent view
     replaces the blurred centre. */
  let defs = null, next = 0;
  function host() {
    if (defs) return defs;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.setAttribute("aria-hidden", "true");
    svg.style.position = "absolute";
    defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    svg.append(defs); document.body.append(svg);
    return defs;
  }
  function lensMap(width, height, radius, bezel) {
    const scale = 0.5, w = Math.max(2, Math.round(width * scale)), h = Math.max(2, Math.round(height * scale));
    const canvas = document.createElement("canvas"); canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d"), image = ctx.createImageData(w, h), d = image.data;
    const hx = width / 2, hy = height / 2, r = Math.min(radius, hx, hy);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const px = (x + 0.5) / scale - hx, py = (y + 0.5) / scale - hy;
      const qx = Math.abs(px) - (hx - r), qy = Math.abs(py) - (hy - r);
      const ox = Math.max(qx, 0), oy = Math.max(qy, 0), outside = Math.hypot(ox, oy);
      const distance = outside + Math.min(Math.max(qx, qy), 0) - r;  // signed distance to the rounded edge
      let nx = 0, ny = 0;
      if (outside > 0) { nx = ox / outside; ny = oy / outside; } else if (qx > qy) nx = 1; else ny = 1;
      nx *= Math.sign(px) || 1; ny *= Math.sign(py) || 1;
      const t = LG.clamp(-distance / bezel, 0, 1), k = (1 - t) ** 2;
      const i = (y * w + x) * 4;
      d[i] = 128 - nx * k * 127; d[i + 1] = 128 - ny * k * 127; d[i + 2] = 255 * LG.clamp((1 - t) * 1.25, 0, 1); d[i + 3] = 255;
    }
    ctx.putImageData(image, 0, 0);
    return canvas.toDataURL();
  }
  function applyLens(el) {
    // Layout size, not the on-screen box: an entrance scale or press must not shrink the filter region.
    const width = el.offsetWidth, height = el.offsetHeight;
    if (width < 4 || height < 4) return;
    const key = `${width}x${height}`;
    if (el.dataset.lgLensKey === key) return;
    el.dataset.lgLensKey = key;
    const style = getComputedStyle(el);
    const radius = parseFloat(style.borderTopLeftRadius) || 0;
    const large = el.classList.contains("lg-large");
    const bezel = Math.min(height / 2, large ? 26 : 16), strength = large ? 70 : 48;
    const blur = parseFloat(style.getPropertyValue("--lg-blur")) || 10;
    const id = el.dataset.lgLens || (el.dataset.lgLens = `lg-lens-${next++}`);
    let filter = document.getElementById(id);
    if (!filter) { filter = document.createElementNS("http://www.w3.org/2000/svg", "filter"); filter.id = id; host().append(filter); }
    for (const [name, value] of Object.entries({ x: 0, y: 0, width, height, filterUnits: "userSpaceOnUse", primitiveUnits: "userSpaceOnUse", "color-interpolation-filters": "sRGB" })) filter.setAttribute(name, value);
    filter.innerHTML = `<feImage href="${lensMap(width, height, radius, bezel)}" x="0" y="0" width="${width}" height="${height}" preserveAspectRatio="none" result="m"/>
      <feGaussianBlur in="SourceGraphic" stdDeviation="${blur}" edgeMode="duplicate" result="soft"/>
      <feGaussianBlur in="SourceGraphic" stdDeviation="1.2" edgeMode="duplicate" result="crisp"/>
      <feDisplacementMap in="crisp" in2="m" scale="${strength}" xChannelSelector="R" yChannelSelector="G" result="bent"/>
      <feColorMatrix in="m" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 1 0 0" result="band"/>
      <feComposite in="bent" in2="band" operator="in" result="rim"/>
      <feComposite in="rim" in2="soft" operator="over"/>`;
    el.style.setProperty("--lg-lens", `url(#${id})`);
  }
  // Engines that can't put an SVG filter in backdrop-filter keep the plain blur.
  const refracts = CSS.supports("backdrop-filter", "url(#lg) blur(1px)") || CSS.supports("-webkit-backdrop-filter", "url(#lg) blur(1px)");
  const timers = new WeakMap();
  const observer = new ResizeObserver(entries => {
    for (const { target } of entries) {
      clearTimeout(timers.get(target));
      timers.set(target, setTimeout(() => applyLens(target), 90));
    }
  });

  /* Interactive glass lights up under the pointer and flexes when pressed. */
  function interactive(el) {
    if (el.dataset.lgInteractive) return;
    el.dataset.lgInteractive = "1";
    const flex = new Spring(1, value => { el.style.scale = value; }, LG.motion.release);
    el.addEventListener("pointermove", e => {
      const box = el.getBoundingClientRect();
      el.style.setProperty("--lg-px", `${e.clientX - box.left}px`);
      el.style.setProperty("--lg-py", `${e.clientY - box.top}px`);
    });
    el.addEventListener("pointerenter", () => el.style.setProperty("--lg-glow", 0.45));
    el.addEventListener("pointerleave", () => { el.style.setProperty("--lg-glow", 0); flex.to(1); });
    el.addEventListener("pointerdown", () => {
      el.style.setProperty("--lg-glow", 1);
      // Large surfaces barely flex; small controls give more.
      flex.to(el.offsetHeight > 60 ? 1.015 : 1.07, LG.motion.press);
    });
    addEventListener("pointerup", () => {
      if (flex.target === 1) return;
      el.style.setProperty("--lg-glow", 0.45);
      flex.to(1, LG.motion.release);
    });
  }

  /* Make an element glass. Options: large (menus, sheets, sidebars), lens (edge refraction), interactive. */
  LG.glass = (el, { large = false, lens = true, interactive: pressable = false } = {}) => {
    el.classList.add("lg-glass");
    el.classList.toggle("lg-large", large);
    if (lens && refracts) { el.classList.add("lg-lens"); observer.observe(el); }
    if (pressable) interactive(el);
    return el;
  };
})();
