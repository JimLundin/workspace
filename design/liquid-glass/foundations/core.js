/* Foundations: the namespace, markup helper, springs, motion presets, schemes and the element base.
   Every other file extends window.LiquidGlass. Classic script (no modules), so pages work
   straight from disk and inside web views. */
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
    // Tests may run motion faster; what users see always runs at timeScale 1.
    const dt = Math.min(0.064, (now - (last || now)) / 1000) * LG.timeScale;
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
  LG.timeScale = 1;
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
})();
