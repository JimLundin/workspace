/* Atom: <lg-app glyph="T" color="linear-gradient(…)" size="small|medium">, an app badge. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, define } = LG;

  class App extends Element {
    static get observedAttributes() { return ["glyph", "color"]; }
    update() {
      this.textContent = this.getAttribute("glyph") || "";
      const color = this.getAttribute("color");
      if (color) this.style.setProperty("--lg-app", color);
      this.setAttribute("aria-hidden", "true");
    }
  }

  define("lg-app", App);
})();
