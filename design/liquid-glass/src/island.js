/* IslandBar: a centred island with lead and trail zones beside it.
   The host describes what to show with a view function; the bar owns the
   capsules, their morphs and order, hover, and click delegation.

     const bar = new LiquidGlass.IslandBar(root, {
       edge: "top",                         // "bottom" grows expansions upward
       order: ["layer", "island", "inbox"], // stable left-to-right order of keys
       view: bar => [{ zone: "island", key: "island", html, kind, width, height, radius, tint }],
       onAction: (action, { key, event, bar }) => {},
     });
     bar.render();

   A click on an element with data-act reports that action; a click elsewhere on a
   capsule reports "press". Hover is available to the view as bar.hover (a key). */
(() => {
  "use strict";
  const LG = window.LiquidGlass;

  class IslandBar {
    constructor(root, { edge = "top", order = [], view, onAction = () => {} }) {
      Object.assign(this, { root, order, view, onAction, hover: null, capsules: new Map(), first: true });
      root.classList.add("lg-bar");
      root.classList.toggle("lg-up", edge === "bottom");
      this.zones = {};
      for (const name of ["lead", "island", "trail"]) {
        const zone = document.createElement("div");
        zone.className = `lg-zone lg-${name}`;
        root.append(zone);
        this.zones[name] = zone;
      }
      root.addEventListener("click", event => {
        const cap = event.target.closest(".lg-cap");
        if (!cap || !root.contains(cap)) return;
        const action = event.target.closest("[data-act]")?.dataset.act || "press";
        this.onAction(action, { key: cap.dataset.key, event, bar: this });
      });
    }

    capsule(key) {
      if (this.capsules.has(key)) return this.capsules.get(key);
      const el = document.createElement("div");
      el.className = "lg-cap";
      el.dataset.key = key;
      el.hidden = true;
      LG.glass(el, { interactive: true });
      el.addEventListener("pointerenter", () => { clearTimeout(this.leaving); if (this.hover !== key) { this.hover = key; this.render(); } });
      el.addEventListener("pointerleave", () => { this.leaving = setTimeout(() => { this.hover = null; this.render(); }, 160); });
      const capsule = new LG.Capsule(el);
      this.capsules.set(key, capsule);
      return capsule;
    }

    // Measure markup for a capsule key, for views that size an expansion to its content.
    measure(key, html, kind, width) { return LG.Capsule.measure(this.capsule(key).el, html, kind, width); }

    render() {
      const views = this.view(this);
      const wanted = new Set(views.map(v => v.key));
      const rank = key => { const i = this.order.indexOf(key); return i < 0 ? this.order.length : i; };
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

    contentOf(key) { return this.capsules.get(key) && LG.$(":scope > .lg-content:not(.lg-leaving)", this.capsules.get(key).el); }
  }
  LG.IslandBar = IslandBar;
})();
