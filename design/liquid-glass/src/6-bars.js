/* Layer 6: bars. The morphing capsule, and the island bar built from capsules.

     <lg-island-bar edge="top" order="layer agent island recording inbox"></lg-island-bar>

     bar.view = bar => [
       { zone: "island", key: "island", content: LiquidGlass.h("lg-fact", {}, "10:22"), kind: "text" },
       { zone: "trail", key: "inbox", content: …, tint: "attention" },
     ];
     bar.addEventListener("lg-action", e => e.detail);   // { action, key, event }
     bar.render();

   View fields: zone (lead | island | trail), key, content (markup), kind
   (icons | text | min | expanded), width and height (expanded content), radius,
   tint (attention | prominent). A click on an element with `act` reports that
   action; a click elsewhere on a capsule reports "press". bar.hover holds the
   key under the pointer, so a view can reveal controls on hover. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, define, clamp, Spring, motion } = LG;
  const KINDS = { icons: "", text: "lg-text", min: "lg-min", expanded: "lg-expanded" };
  const TINTS = { attention: "lg-tint", prominent: "lg-prominent" };

  // Measure markup as it would render inside a capsule of the same scheme, optionally at a fixed width.
  function measure(cap, html, kind, width) {
    const probe = document.createElement("div");
    probe.className = `lg-content ${kind}`;
    probe.style.cssText = `position:absolute;visibility:hidden;transition:none;${width ? `width:${width}px;` : ""}`;
    probe.innerHTML = html;
    const shell = document.createElement("div");
    // The shell keeps the capsule's type but not its material or centring, which would stretch the probe.
    shell.className = "lg-cap";
    shell.style.cssText = "position:fixed;left:-9999px;top:0;width:auto;height:auto";
    const scheme = cap.closest(".lg-light, .lg-dark");
    const wrap = document.createElement("div");
    wrap.className = `lg-root ${scheme?.classList.contains("lg-light") ? "lg-light" : scheme ? "lg-dark" : ""}`;
    shell.append(probe); wrap.append(shell); document.body.append(wrap);
    const box = probe.getBoundingClientRect();
    wrap.remove();
    return { width: Math.ceil(box.width), height: Math.ceil(box.height) };
  }

  /* Capsule: a glass shape whose size springs between contents while the content
     cross-fades and materializes. Entering and leaving capsules grow from and collapse
     to nothing, so neighbours slide rather than jump. */
  class Capsule {
    constructor(el) {
      this.el = el;
      this.markup = null;
      this.width = 0;
      this.shown = !el.hidden;
      this.radius = 28;
      this.size = { w: 0, p: this.shown ? 1 : 0 };
      const fit = () => { el.style.width = `${Math.max(0, this.size.w * clamp(this.size.p, 0, 1))}px`; };
      this.w = new Spring(0, v => { this.size.w = v; fit(); }, motion.morph);
      this.p = new Spring(this.size.p, v => {
        this.size.p = v; fit();
        let prev = el.previousElementSibling;
        while (prev && prev.hidden) prev = prev.previousElementSibling;
        const gap = parseFloat(getComputedStyle(el.parentElement).getPropertyValue("--lg-gap")) || 6;
        el.style.opacity = clamp(v * 1.6, 0, 1);
        el.style.transform = `scale(${0.6 + 0.4 * clamp(v, 0, 1.2)})`;
        el.style.marginLeft = prev ? `${gap * clamp(v, 0, 1)}px` : "0px";
        el.style.filter = v < 0.98 ? `blur(${(1 - clamp(v, 0, 1)) * 6}px)` : "";
      }, motion.appear);
      this.h = null;
      // Content that changes its own size (a timer gaining a digit) asks the capsule to re-measure.
      el.addEventListener("lg-resize", () => this.refit());
    }

    set(view, { instant = false } = {}) {
      const { content, width, height, radius = 28 } = view;
      const html = String(content), kind = KINDS[view.kind ?? "icons"] ?? "";
      const el = this.el;
      for (const [name, cls] of Object.entries(TINTS)) el.classList.toggle(cls, view.tint === name);
      this.radius = radius;
      // Height animates only for capsules that have expanded at least once; they return to the bar height.
      if (height !== undefined || this.h) {
        if (!this.h) this.h = new Spring(el.offsetHeight || 34, v => { el.style.height = `${v}px`; el.style.setProperty("--lg-r", `${Math.min(v / 2, this.radius)}px`); }, motion.appear);
        const to = height ?? (parseFloat(getComputedStyle(el).getPropertyValue("--lg-bar-h")) || 34);
        instant ? this.h.set(to) : this.h.to(to);
      }
      if (this.markup === html + kind) return null;
      this.markup = html + kind;
      this.kind = kind;
      const old = this.current();
      const next = document.createElement("div");
      next.className = `lg-content ${kind}`;
      next.innerHTML = html;
      const w = width ?? measure(el, html, kind).width;
      const centered = el.classList.contains("lg-centered");
      // Expanded content lays out at its final size from the start; the growing capsule reveals it.
      if (kind === "lg-expanded") Object.assign(next.style, { width: `${w}px`, left: `calc(50% - ${w / 2}px)`, right: "auto" });
      if (old && !instant) {
        // Leaving content keeps its size while it fades, so its text never reflows.
        const ow = old.offsetWidth;
        old.style.width = `${ow}px`;
        if (centered) Object.assign(old.style, { left: `calc(50% - ${ow / 2}px)`, right: "auto" });
        old.classList.add("lg-leaving");
        setTimeout(() => old.remove(), 200);
        next.classList.add("lg-entering");
        el.append(next);
        requestAnimationFrame(() => requestAnimationFrame(() => next.classList.remove("lg-entering")));
      } else {
        if (old) old.remove();
        el.append(next);
      }
      if (instant || !this.width) this.w.set(w); else this.w.to(w);
      this.width = w;
      return next;
    }

    current() { return LG.$(":scope > .lg-content:not(.lg-leaving)", this.el); }

    // Re-measure the live content in place, without replacing it.
    refit() {
      const content = this.current();
      if (!content || this.kind === "lg-expanded") return;
      const { right } = content.style;
      content.style.right = "auto";
      const w = content.offsetWidth;  // layout width: transforms and presses don't change it
      content.style.right = right;
      if (w !== this.width) { this.width = w; this.w.to(w); }
    }

    show(visible, { instant = false } = {}) {
      if (this.shown === visible) return;
      this.shown = visible;
      if (visible) { this.el.hidden = false; instant ? this.p.set(1) : this.p.to(1, { damping: 0.78 }); }
      else this.p.to(0, { damping: 1, response: 0.3, done: () => { if (!this.shown) this.el.hidden = true; } });
    }

    invalidate() { this.markup = null; }
  }
  Capsule.measure = measure;
  LG.Capsule = Capsule;

  /* The island bar: lead · island · trail. The island stays centred and zones grow
     outward from it. The bar owns capsules, their order, morphs, hover and clicks. */
  class IslandBar extends Element {
    build() {
      this.setAttribute("role", this.getAttribute("role") || "toolbar");
      this.capsules = new Map();
      this.hover = null;
      this.first = true;
      this.view = this.view || (() => []);
      this.zones = {};
      for (const name of ["lead", "island", "trail"]) {
        const zone = document.createElement("div");
        zone.className = `lg-zone lg-${name}`;
        this.append(zone);
        this.zones[name] = zone;
      }
      this.addEventListener("click", event => {
        const cap = event.target.closest(".lg-cap");
        if (!cap || !this.contains(cap)) return;
        const action = event.target.closest("[act]")?.getAttribute("act") || "press";
        this.dispatchEvent(new CustomEvent("lg-action", { detail: { action, key: cap.dataset.key, event } }));
      });
    }
    get order() { return (this.getAttribute("order") || "").split(/\s+/).filter(Boolean); }

    capsule(key) {
      if (this.capsules.has(key)) return this.capsules.get(key);
      const el = document.createElement("div");
      el.className = "lg-cap";
      el.dataset.key = key;
      el.hidden = true;
      LG.glass(el, { interactive: true });
      el.addEventListener("pointerenter", () => { clearTimeout(this.leaving); if (this.hover !== key) { this.hover = key; this.render(); } });
      el.addEventListener("pointerleave", () => { this.leaving = setTimeout(() => { this.hover = null; this.render(); }, 160); });
      const capsule = new Capsule(el);
      this.capsules.set(key, capsule);
      return capsule;
    }

    // Measure markup for a key's capsule, for views that size an expansion to its content.
    measure(key, content, kind, width) { return measure(this.capsule(key).el, String(content), KINDS[kind] ?? kind, width); }
    // A view that expands the island to fit its content at a given width.
    expanded(key, zone, content, width, radius) {
      return { zone, key, content, kind: "expanded", width, height: this.measure(key, content, "expanded", width).height, radius };
    }

    render() {
      if (!this.built) return;
      const views = this.view(this);
      const wanted = new Set(views.map(v => v.key));
      const order = this.order;
      const rank = key => { const i = order.indexOf(key); return i < 0 ? order.length : i; };
      for (const [name, zone] of Object.entries(this.zones)) {
        const mine = views.filter(v => v.zone === name);
        for (const v of mine) {
          const { el } = this.capsule(v.key);
          el.classList.toggle("lg-centered", name === "island");
          if (el.parentElement !== zone) zone.append(el);
        }
        // Move a capsule only when it's out of order: moving a node drops focus from anything inside it.
        [...zone.children].sort((a, b) => rank(a.dataset.key) - rank(b.dataset.key))
          .forEach((el, i) => { if (zone.children[i] !== el) zone.insertBefore(el, zone.children[i]); });
        for (const v of mine) {
          const capsule = this.capsule(v.key);
          capsule.set(v, { instant: this.first });
          capsule.show(true, { instant: this.first });
        }
      }
      for (const [key, capsule] of this.capsules) if (!wanted.has(key)) capsule.show(false);
      this.first = false;
    }

    // Re-measure everything, instantly, for example once fonts have loaded.
    refresh() {
      for (const capsule of this.capsules.values()) capsule.invalidate();
      this.first = true;
      this.render();
    }

    content(key) { return this.capsules.get(key)?.current() ?? null; }
  }
  define("lg-island-bar", IslandBar);
})();
