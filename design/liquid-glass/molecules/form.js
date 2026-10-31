/* Molecules for panels: <lg-section heading>, <lg-rows>, <lg-row label>, <lg-field-row label>,
   <lg-actions> (buttons sharing a row) and <lg-footnote>. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, define } = LG;

  class Section extends Element {
    build() {
      const heading = this.getAttribute("heading");
      if (heading) { const h = document.createElement("h2"); h.textContent = heading; this.prepend(h); }
    }
  }
  class Rows extends Element {}
  class Row extends Element {
    build() {
      const label = document.createElement("span");
      label.textContent = this.getAttribute("label") || "";
      this.prepend(label);
      for (const control of this.querySelectorAll("lg-switch, lg-segmented")) if (!control.hasAttribute("aria-label")) control.setAttribute("aria-label", label.textContent);
    }
  }
  class FieldRow extends Element {
    build() {
      const label = document.createElement("span");
      label.className = "lg-field-label";
      label.textContent = this.getAttribute("label") || "";
      this.prepend(label);
    }
  }

  class Actions extends Element {}
  class Footnote extends Element {}

  define("lg-section", Section);
  define("lg-rows", Rows);
  define("lg-row", Row);
  define("lg-field-row", FieldRow);
  define("lg-actions", Actions);
  define("lg-footnote", Footnote);
})();
