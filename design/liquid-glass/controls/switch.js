/* Control: <lg-switch checked aria-label="…">. Its knob turns to glass while held.
   Dispatches a bubbling "change"; read .checked. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Spring, define } = LG;

  class Switch extends HTMLElement {
    connectedCallback() {
      if (this.knob) return;
      this.setAttribute("role", "switch");
      this.tabIndex = 0;
      this.knob = document.createElement("span");
      this.knob.className = "lg-knob";
      this.append(this.knob);
      this.spring = new Spring(this.checked ? 1 : 0, v => { this.knob.style.left = `${2 + 12 * v}px`; }, { damping: 0.7, response: 0.3 });
      this.spring.set(this.checked ? 1 : 0);
      this.setAttribute("aria-checked", this.checked);
      // The knob turns to glass while it's held.
      this.addEventListener("pointerdown", () => this.classList.add("lg-held"));
      this.addEventListener("pointerup", () => setTimeout(() => this.classList.remove("lg-held"), 160));
      this.addEventListener("pointerleave", () => this.classList.remove("lg-held"));
      const toggle = () => { this.checked = !this.checked; this.dispatchEvent(new Event("change", { bubbles: true })); };
      this.addEventListener("click", toggle);
      this.addEventListener("keydown", e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); toggle(); } });
    }
    get checked() { return this.hasAttribute("checked"); }
    set checked(on) {
      this.toggleAttribute("checked", on);
      this.setAttribute("aria-checked", on);
      if (this.spring) this.spring.to(on ? 1 : 0);
    }
  }

  define("lg-switch", Switch);
})();
