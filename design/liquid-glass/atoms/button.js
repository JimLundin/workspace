/* Atom: <lg-button icon="bell" label="Inbox" badge="3" act="inbox" variant="plain|filled|accent|glass" size="control|pill|large" wide>Text</lg-button>.
   Any element with an `act` attribute reports that action to the bar or container it sits in. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, escape, define } = LG;

  /* A button: an optional symbol, optional visible text (the element's text), an
     accessible label, and an optional badge. Variants: plain, filled, accent, glass. */
  class Button extends Element {
    static get observedAttributes() { return ["icon", "filled", "label", "title", "badge", "badge-tone", "disabled"]; }
    build() {
      this.text = this.textContent.trim();
      if (this.getAttribute("variant") === "glass") this.glassy = true;
      this.update();
    }
    update() {
      const icon = this.getAttribute("icon"), label = this.getAttribute("label") || this.text, badge = this.getAttribute("badge");
      this.toggleAttribute("icon-only", !!icon && !this.text);
      this.innerHTML = `<button type="button" aria-label="${escape(label)}" title="${escape(this.getAttribute("title") || label)}"${this.hasAttribute("disabled") ? " disabled" : ""}>${icon ? `<lg-icon name="${escape(icon)}"${this.hasAttribute("filled") ? " filled" : ""}></lg-icon>` : ""}${this.text ? `<span>${escape(this.text)}</span>` : ""}${badge ? `<lg-badge${this.getAttribute("badge-tone") ? ` tone="${escape(this.getAttribute("badge-tone"))}"` : ""}>${escape(badge)}</lg-badge>` : ""}</button>`;
      if (this.glassy) LG.glass(this.firstElementChild, { interactive: true, lens: false });
    }
    focus() { this.firstElementChild?.focus(); }
  }

  define("lg-button", Button);
})();
