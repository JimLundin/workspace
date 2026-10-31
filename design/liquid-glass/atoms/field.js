/* Atom: <lg-field icon="search" placeholder="Search" value="…">, a text field; native input events bubble. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, escape, define } = LG;

  /* A text field with an optional leading symbol. Native input events bubble from it. */
  class Field extends Element {
    build() {
      const icon = this.getAttribute("icon");
      this.innerHTML = `${icon ? `<lg-icon name="${escape(icon)}"></lg-icon>` : ""}<input type="text" placeholder="${escape(this.getAttribute("placeholder") || "")}" aria-label="${escape(this.getAttribute("label") || this.getAttribute("placeholder") || "")}" value="${escape(this.getAttribute("value") || "")}">`;
    }
    get value() { return this.querySelector("input")?.value ?? ""; }
    set value(v) { const input = this.querySelector("input"); if (input) input.value = v; }
    focus() { this.querySelector("input")?.focus(); }
  }

  define("lg-field", Field);
})();
