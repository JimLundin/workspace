/* Control: <lg-segmented value="dark"><button value="light">Light</button>…</lg-segmented>.
   Dispatches a bubbling "change"; read .value. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Spring, define } = LG;

  const slide = { damping: 0.82, response: 0.34 };

  class Segmented extends HTMLElement {
    connectedCallback() {
      if (this.thumb) return;
      this.setAttribute("role", "radiogroup");
      this.thumb = document.createElement("span");
      this.thumb.className = "lg-thumb";
      this.prepend(this.thumb);
      this.x = new Spring(0, v => { this.thumb.style.left = `${v}px`; }, slide);
      this.w = new Spring(0, v => { this.thumb.style.width = `${v}px`; }, slide);
      this.addEventListener("click", e => {
        const button = e.target.closest("button[value]");
        if (!button || button.value === this.value) return;
        this.value = button.value;
        this.dispatchEvent(new Event("change", { bubbles: true }));
      });
      // Re-measure when the control resizes or the typeface loads, without animating.
      new ResizeObserver(() => this.sync(true)).observe(this);
      document.fonts.ready.then(() => this.sync(true));
    }
    get value() { return this.getAttribute("value"); }
    set value(value) { this.setAttribute("value", value); this.sync(false); }
    sync(instant) {
      if (!this.thumb) return;
      const button = this.querySelector(`button[value="${CSS.escape(this.value ?? "")}"]`);
      for (const b of this.querySelectorAll("button[value]")) { b.setAttribute("role", "radio"); b.setAttribute("aria-checked", b === button); }
      this.thumb.style.visibility = button ? "" : "hidden";
      if (!button) return;
      instant ? (this.x.set(button.offsetLeft), this.w.set(button.offsetWidth)) : (this.x.to(button.offsetLeft), this.w.to(button.offsetWidth));
    }
  }

  define("lg-segmented", Segmented);
})();
