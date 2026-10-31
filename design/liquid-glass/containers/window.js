/* Container: <lg-window heading detail>, a solid content surface with window controls. .open; "close" event. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, clamp, Spring, define } = LG;

  /* ── Window: a solid content surface with large corners, window controls, a title,
     and scroll edge effects where content passes beneath floating controls. ── */
  class Window extends Element {
    build() {
      this.setAttribute("role", "dialog");
      if (this.getAttribute("heading")) this.setAttribute("aria-label", this.getAttribute("heading"));
      const chrome = LG.fragment(`<div class="lg-traffic"><button type="button" aria-label="Close" title="Close"></button><button type="button" aria-label="Minimise" title="Minimise"></button><button type="button" aria-label="Zoom" title="Zoom"></button></div>`);
      chrome.firstElementChild.addEventListener("click", () => { this.open = false; this.dispatchEvent(new Event("close")); });
      const title = document.createElement("div");
      title.className = "lg-title";
      title.innerHTML = `${LG.escape(this.getAttribute("heading") || "")}${this.getAttribute("detail") ? `<small>${LG.escape(this.getAttribute("detail"))}</small>` : ""}`;
      const edgeTop = document.createElement("div"); edgeTop.className = "lg-edge-top";
      const edgeBottom = document.createElement("div"); edgeBottom.className = "lg-edge-bottom";
      // Edges sit above the content and below the floating controls.
      const content = this.querySelector(":scope > :not(lg-island-bar):not(lg-inspector)");
      if (content) content.after(edgeTop, edgeBottom); else this.prepend(edgeTop, edgeBottom);
      this.append(chrome, title);
      // An open inspector moves the window's bottom bar into the remaining column.
      this.addEventListener("toggle", e => { if (e.target.tagName === "LG-INSPECTOR") this.toggleAttribute("inspecting", e.target.open); });
      this.state = false;
      this.spring = new Spring(0, p => {
        this.style.opacity = clamp(p * 1.5, 0, 1);
        this.style.transform = `translateX(-50%) translateY(${(1 - p) * -24}px) scale(${0.9 + 0.1 * p})`;
      }, { damping: 0.9, response: 0.42 });
    }
    get open() { return this.state; }
    set open(open) {
      if (open === this.state) return;
      this.state = open;
      if (open) { this.setAttribute("open", ""); this.spring.to(1); }
      else this.spring.to(0, { damping: 1, response: 0.3, done: () => { if (!this.state) this.removeAttribute("open"); } });
    }
  }

  define("lg-window", Window);
})();
