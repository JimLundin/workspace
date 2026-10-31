/* Molecule: <lg-card variant="solid|glass" heading meta time collapsed>.
   Children: slot="badge", slot="body", slot="actions", and any extra content. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, escape, define } = LG;

  const take = (el, slot) => [...el.children].filter(c => c.getAttribute("slot") === slot);

  /* One anatomy for solid content cards and glass notification cards. */
  class Card extends Element {
    build() {
      if (!this.hasAttribute("variant")) this.setAttribute("variant", "solid");
      const badge = take(this, "badge"), body = take(this, "body"), actions = take(this, "actions");
      const extra = [...this.children].filter(c => !badge.includes(c) && !body.includes(c) && !actions.includes(c));
      const head = document.createElement("div");
      head.className = "lg-head";
      head.innerHTML = `<div class="lg-titles"><div class="lg-title-row"><span class="lg-title">${escape(this.getAttribute("heading") || "")}</span>${this.getAttribute("time") ? `<span class="lg-time">${escape(this.getAttribute("time"))}</span>` : ""}</div>${this.getAttribute("meta") ? `<div class="lg-meta">${escape(this.getAttribute("meta"))}</div>` : ""}</div>`;
      head.prepend(...badge);
      head.querySelector(".lg-titles").append(...body);
      const more = document.createElement("div"); more.className = "lg-extra"; more.append(...extra);
      this.replaceChildren(head, ...(extra.length ? [more] : []), ...actions);
    }
  }

  define("lg-card", Card);
})();
