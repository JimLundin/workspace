/* Liquid Glass material: edge refraction and press response. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { clamp, Spring, motion } = LG;

  /* Lens refraction: one displacement map per glass shape. R and G bend the
     backdrop toward the centre near the rim; B marks the rim band, where a
     sharper, bent view replaces the blurred centre. */
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
  function map(width, height, radius, bezel) {
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
      const t = clamp(-distance / bezel, 0, 1), k = (1 - t) ** 2;
      const i = (y * w + x) * 4;
      d[i] = 128 - nx * k * 127; d[i + 1] = 128 - ny * k * 127; d[i + 2] = 255 * clamp((1 - t) * 1.25, 0, 1); d[i + 3] = 255;
    }
    ctx.putImageData(image, 0, 0);
    return canvas.toDataURL();
  }
  function apply(el) {
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
    filter.innerHTML = `<feImage href="${map(width, height, radius, bezel)}" x="0" y="0" width="${width}" height="${height}" preserveAspectRatio="none" result="m"/>
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
      timers.set(target, setTimeout(() => apply(target), 90));
    }
  });

  /* Interactive glass lights up under the pointer and flexes when pressed. */
  function interactive(el) {
    if (el.dataset.lgInteractive) return;
    el.dataset.lgInteractive = "1";
    const flex = new Spring(1, value => { el.style.scale = value; }, motion.release);
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
      flex.to(el.offsetHeight > 60 ? 1.015 : 1.07, motion.press);
    });
    addEventListener("pointerup", () => {
      if (flex.target === 1) return;
      el.style.setProperty("--lg-glow", 0.45);
      flex.to(1, motion.release);
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
  LG.interactive = interactive;
})();
