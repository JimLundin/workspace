/* Molecules: <lg-menu heading detail>, <lg-menu-item icon act key check sub>, <lg-menu-separator>,
   and <lg-live-row label> with slot="glyph", slot="detail" and slot="control" children. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, escape, define } = LG;

  const take = (el, slot) => [...el.children].filter(c => c.getAttribute("slot") === slot);

  class Menu extends Element {
    build() {
      this.setAttribute("role", "menu");
      const heading = this.getAttribute("heading");
      if (heading) {
        const head = document.createElement("div");
        head.className = "lg-menu-head";
        head.innerHTML = `<b>${escape(heading)}</b><span>${escape(this.getAttribute("detail") || "")}</span>`;
        this.prepend(head);
      }
      // Live rows sit above the items, set apart by a separator.
      const rows = [...this.children].filter(c => c.tagName === "LG-LIVE-ROW");
      if (rows.length && rows.at(-1).nextElementSibling?.tagName === "LG-MENU-ITEM") rows.at(-1).after(document.createElement("lg-menu-separator"));
    }
  }

  class MenuItem extends Element {
    build() {
      this.text = this.textContent.trim();
      const icon = this.getAttribute("icon"), key = this.getAttribute("key");
      this.innerHTML = `<button type="button" role="menuitem">${icon ? `<lg-icon name="${escape(icon)}"></lg-icon>` : ""}<span>${escape(this.text)}</span>${key ? `<span class="lg-key">${escape(key)}</span>` : ""}${this.hasAttribute("check") ? '<span class="lg-check"><lg-icon name="check"></lg-icon></span>' : ""}${this.hasAttribute("sub") ? '<span class="lg-trailing"><lg-icon name="chev"></lg-icon></span>' : ""}</button>`;
      if (this.hasAttribute("sub")) this.firstElementChild.setAttribute("aria-haspopup", "menu");
    }
  }

  class MenuSeparator extends Element { update() { this.setAttribute("role", "separator"); } }

  /* A live row: an activity's glyph, label, detail and its own control. */
  class LiveRow extends Element {
    build() {
      const label = document.createElement("span");
      label.className = "lg-live-label";
      label.textContent = this.getAttribute("label") || "";
      this.prepend(...take(this, "glyph"), label);
      label.after(...take(this, "detail"), ...take(this, "control"));
    }
  }

  define("lg-menu", Menu);
  define("lg-menu-item", MenuItem);
  define("lg-menu-separator", MenuSeparator);
  define("lg-live-row", LiveRow);
})();
