/* Container: <lg-inspector label>, a floating column inset in its window. .open, .content; "close" and "toggle" events. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, clamp, Spring, define } = LG;

  /* ── Inspector: a floating column inset in its window. It slides in from the
     trailing edge and leaves the same way. Set .content to replace what it shows. ── */
  class Inspector extends Element {
    build() {
      this.setAttribute("role", "complementary");
      if (this.getAttribute("label")) this.setAttribute("aria-label", this.getAttribute("label"));
      LG.glass(this, { large: true });
      this.scroll = document.createElement("lg-scroll");
      this.scroll.append(...this.childNodes);
      const close = LG.fragment(LG.h("lg-button", { class: "lg-close", icon: "x", label: "Close details" }));
      close.addEventListener("click", () => { this.open = false; this.dispatchEvent(new Event("close")); });
      this.append(this.scroll, close);
      this.state = false;
      this.spring = new Spring(0, p => {
        this.style.transform = `translateX(${(1 - p) * (this.offsetWidth + 20)}px)`;
        this.style.opacity = clamp(p * 2, 0, 1);
      }, { damping: 0.9, response: 0.4 });
    }
    set content(html) { this.scroll.content = html; }
    get open() { return this.state; }
    set open(open) {
      if (open === this.state) return;
      this.state = open;
      if (open) { this.style.display = "block"; this.spring.set(0); this.spring.to(1); }
      else this.spring.to(0, { done: () => { if (!this.state) this.style.display = "none"; } });
      this.dispatchEvent(new Event("toggle", { bubbles: true }));
    }
  }

  define("lg-inspector", Inspector);
})();
