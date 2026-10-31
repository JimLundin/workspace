/* Bars: <lg-island-bar edge="top|bottom" order="key key …">, a centred island with lead and trail zones.

     bar.view = bar => [{ zone: "island", key: "island", content, kind: "text", tint: "attention" }];
     bar.addEventListener("lg-action", e => e.detail);   // { action, key, event }
     bar.render();

   View fields: zone (lead | island | trail), key, content (markup), kind (icons | text |
   min | expanded), width and height (expanded content), radius, tint (attention |
   prominent). A click on an element with `act` reports that action; a click elsewhere on
   a capsule reports "press". bar.hover holds the key under the pointer. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, define, clamp } = LG;
  const { Capsule } = LG, { KINDS, measure } = Capsule;

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
      const capsule = new Capsule(el, { onPresence: () => this.space(el.parentElement) });
      this.capsules.set(key, capsule);
      return capsule;
    }

    /* Space a zone's capsules. The gap between neighbours belongs to the pair: it is the
       full gap scaled by the less present of the two, so a capsule sliding in or out opens
       and closes the space beside it smoothly, whichever side it's on. */
    space(zone) {
      if (!zone) return;
      const gap = parseFloat(getComputedStyle(this).getPropertyValue("--lg-gap")) || 6;
      let before = null;
      for (const el of zone.children) {
        if (el.hidden) continue;
        const presence = clamp(this.capsules.get(el.dataset.key).size.p, 0, 1);
        el.style.marginLeft = before === null ? "0px" : `${gap * Math.min(before, presence)}px`;
        before = presence;
      }
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
      // Order or visibility may have changed without any capsule animating.
      for (const zone of Object.values(this.zones)) this.space(zone);
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
