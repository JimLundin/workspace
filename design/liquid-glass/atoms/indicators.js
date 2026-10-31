/* Atoms: live indicators. <lg-spinner label="Transcribing">, <lg-dot> (recording),
   <lg-wave bars="18" live> (audio, driven by LiquidGlass.audio.level). */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, define } = LG;

  class Spinner extends Element {
    static get observedAttributes() { return ["label"]; }
    update() {
      const label = this.getAttribute("label") || "Working";
      this.setAttribute("role", "status"); this.setAttribute("aria-label", label); this.title = label;
    }
  }

  class Dot extends Element { update() { this.setAttribute("aria-hidden", "true"); } }

  /* Waveform. `live` bars follow LiquidGlass.audio.level(bar, time), which the host supplies
     from its audio meter; without one, the bars rest flat. */
  const live = new Set();
  let pump = null;
  LG.audio = { level: null };
  function animate() {
    const now = performance.now() / 1000;
    for (const wave of live) [...wave.children].forEach((bar, i) => {
      const level = LG.audio.level ? LG.clamp(LG.audio.level(i, now), 0, 1) : 0;
      bar.style.height = `${3 + 12 * level}px`;
    });
    pump = live.size ? setTimeout(animate, 60) : null;
  }
  class Wave extends Element {
    static get observedAttributes() { return ["bars"]; }
    update() { this.setAttribute("aria-hidden", "true"); this.innerHTML = "<i></i>".repeat(Number(this.getAttribute("bars") || 18)); }
    connectedCallback() {
      super.connectedCallback();
      if (this.hasAttribute("live")) { live.add(this); if (!pump) animate(); }
    }
    disconnectedCallback() { live.delete(this); }
  }

  define("lg-spinner", Spinner);
  define("lg-dot", Dot);
  define("lg-wave", Wave);
})();
