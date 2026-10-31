/* Container: <lg-sidebar label>, a floating sidebar with a toggle that stays put. .open, .toggle(); "toggle" event. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, clamp, Spring, motion, define } = LG;

  /* ── Sidebar: floats inset in the glass layer; a toggle stays in place while the
     sidebar slides out along the leading edge and back the same way. ── */
  class Sidebar extends Element {
    build() {
      this.setAttribute("role", "complementary");
      if (this.getAttribute("label")) this.setAttribute("aria-label", this.getAttribute("label"));
      LG.glass(this, { large: true, lens: false });
      const scroll = document.createElement("lg-scroll");
      scroll.append(...this.childNodes);
      this.append(scroll);
      this.button = document.createElement("button");
      this.button.className = "lg-side-toggle";
      this.button.innerHTML = '<lg-icon name="side"></lg-icon>';
      LG.glass(this.button, { lens: false, interactive: true });
      this.button.addEventListener("click", () => this.toggle());
      this.after(this.button);
      this.state = true;
      this.spring = new Spring(1, v => {
        this.style.transform = `translateX(${(v - 1) * (this.offsetWidth + 16)}px)`;
        this.style.opacity = clamp(v * 1.4, 0, 1);
        this.style.visibility = v < 0.01 ? "hidden" : "";
      }, motion.slide);
      this.label();
      new MutationObserver(() => LG.scheme(this.button, this.classList.contains("lg-light") ? "light" : this.classList.contains("lg-dark") ? "dark" : null)).observe(this, { attributes: true, attributeFilter: ["class"] });
    }
    get open() { return this.state; }
    set open(open) {
      if (open === this.state) return;
      this.state = open;
      this.spring.to(open ? 1 : 0);
      this.label();
      this.dispatchEvent(new Event("toggle"));
    }
    toggle() { this.open = !this.open; }
    label() {
      const text = this.state ? "Hide sidebar" : "Show sidebar";
      this.button.setAttribute("aria-label", text);
      this.button.setAttribute("aria-expanded", this.state);
      this.button.title = text;
      // Over the open sidebar the toggle is a plain symbol: glass never sits on glass.
      this.button.classList.toggle("lg-flat", this.state);
    }
  }

  define("lg-sidebar", Sidebar);
})();
