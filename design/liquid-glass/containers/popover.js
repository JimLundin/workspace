/* Container: <lg-popover>, large glass beside its source. .showBeside(element) and .hide(). */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, define } = LG;

  /* ── Popover: large glass beside its source, appearing from it. ─── */
  class Popover extends Element {
    build() { this.setAttribute("role", "menu"); LG.glass(this, { large: true }); }
    showBeside(source, { gap = 12 } = {}) {
      const box = source.getBoundingClientRect();
      Object.assign(this.style, { left: `${box.right + gap}px`, top: `${box.top - 6}px` });
      if (!this.hasAttribute("open")) {
        this.setAttribute("open", "");
        this.animate([{ opacity: 0, transform: "scale(.96) translateX(-6px)", filter: "blur(4px)" }, { opacity: 1, transform: "none", filter: "none" }], { duration: 220, easing: "cubic-bezier(.2,.8,.2,1)" });
      }
    }
    hide() { this.removeAttribute("open"); }
  }

  define("lg-popover", Popover);
})();
