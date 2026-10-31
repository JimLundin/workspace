/* Atom: <lg-icon name="mic" filled label="…">. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, define } = LG;

  class Icon extends Element {
    static get observedAttributes() { return ["name", "filled", "label"]; }
    update() {
      this.innerHTML = LG.iconSvg(this.getAttribute("name"), this.hasAttribute("filled"));
      const label = this.getAttribute("label");
      if (label) { this.setAttribute("role", "img"); this.setAttribute("aria-label", label); } else this.setAttribute("aria-hidden", "true");
    }
  }

  define("lg-icon", Icon);
})();
