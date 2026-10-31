/* Molecules: <lg-steps> and <lg-step state="pending|running|done">, an agent's tool calls. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, escape, define } = LG;

  class Steps extends Element {}
  /* A step: pending (hidden), running (spinner) or done (check). */
  class Step extends Element {
    static get observedAttributes() { return ["state"]; }
    build() { this.text = this.textContent.trim(); this.update(); }
    update() {
      const state = this.getAttribute("state") || "pending";
      const glyph = state === "done" ? '<span class="lg-done"><lg-icon name="checkc"></lg-icon></span>' : `<lg-spinner label="${escape(this.text)}"></lg-spinner>`;
      this.innerHTML = `${glyph}<span>${escape(this.text)}</span>`;
    }
  }

  define("lg-steps", Steps);
  define("lg-step", Step);
})();
