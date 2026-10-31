/* Atoms: readings. <lg-fact icon="battery" num quiet strong tone="mic">73%</lg-fact> and <lg-kbd>N</lg-kbd>. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, escape, define } = LG;

  /* A fact: a reading with an optional symbol. Attributes: icon, num, quiet, strong, tone. */
  class Fact extends Element {
    static get observedAttributes() { return ["icon"]; }
    build() { this.text = this.textContent.trim(); this.update(); }
    update() {
      const icon = this.getAttribute("icon");
      this.innerHTML = `${icon ? `<lg-icon name="${escape(icon)}"${this.hasAttribute("filled") ? " filled" : ""}></lg-icon>` : ""}${this.text ? `<span>${escape(this.text)}</span>` : ""}`;
    }
  }

  class Kbd extends Element {}

  define("lg-fact", Fact);
  define("lg-kbd", Kbd);
})();
