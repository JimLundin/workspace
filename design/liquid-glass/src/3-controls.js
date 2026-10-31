/* Layer 3: controls. <lg-segmented> and <lg-switch>.

     <lg-segmented value="dark"><button value="light">Light</button><button value="dark">Dark</button></lg-segmented>
     <lg-switch checked aria-label="Inbox items"></lg-switch>

   Both dispatch a bubbling "change" event; read .value or .checked. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Spring } = LG;
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

  customElements.define("lg-segmented", Segmented);
  customElements.define("lg-switch", Switch);
})();
