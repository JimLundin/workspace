/* <lg-sidebar>: a macOS 26 sidebar. It floats inset in the glass layer, its
   content scrolls with overlay scroll bars, and a toggle stays in place while
   the sidebar slides out along the leading edge and back the same way.

     <lg-sidebar label="Study controls"> …content… </lg-sidebar>

   Set .open or call .toggle(); it dispatches "toggle" when its state changes. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { clamp, Spring } = LG;

  class Sidebar extends HTMLElement {
    connectedCallback() {
      if (this.button) return;
      this.setAttribute("role", "complementary");
      if (this.getAttribute("label")) this.setAttribute("aria-label", this.getAttribute("label"));
      LG.glass(this, { large: true, lens: false });
      const scroll = document.createElement("lg-scroll");
      scroll.append(...this.childNodes);
      this.append(scroll);
      this.button = document.createElement("button");
      this.button.className = "lg-side-toggle";
      this.button.innerHTML = LG.icon("side");
      LG.glass(this.button, { lens: false, interactive: true });
      this.button.addEventListener("click", () => this.toggle());
      this.after(this.button);
      this.state = true;
      this.spring = new Spring(1, v => {
        this.style.transform = `translateX(${(v - 1) * (this.offsetWidth + 16)}px)`;
        this.style.opacity = clamp(v * 1.4, 0, 1);
        this.style.visibility = v < 0.01 ? "hidden" : "";
      }, { damping: 0.9, response: 0.38 });
      this.label();
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
    // The toggle shares the sidebar's scheme.
    static get observedAttributes() { return ["class"]; }
    attributeChangedCallback() {
      if (!this.button) return;
      LG.scheme(this.button, this.classList.contains("lg-light") ? "light" : this.classList.contains("lg-dark") ? "dark" : null);
    }
  }
  customElements.define("lg-sidebar", Sidebar);
})();
