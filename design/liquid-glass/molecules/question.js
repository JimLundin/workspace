/* Molecule: <lg-question heading meta>, an expanded island's question.
   Children: slot="badge", slot="body", and <lg-button> answers. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, escape, define } = LG;

  const take = (el, slot) => [...el.children].filter(c => c.getAttribute("slot") === slot);

  /* An expanded island's question: badge, title, meta, body and equal answer buttons. */
  class Question extends Element {
    build() {
      const badge = take(this, "badge"), body = take(this, "body"), actions = [...this.children].filter(c => c.tagName === "LG-BUTTON");
      const top = document.createElement("div");
      top.className = "lg-q-top";
      top.innerHTML = `<div class="lg-q-title">${escape(this.getAttribute("heading") || "")}</div>${this.getAttribute("meta") ? `<span class="lg-q-meta">${escape(this.getAttribute("meta"))}</span>` : ""}`;
      top.prepend(...badge);
      const text = document.createElement("div"); text.className = "lg-q-body"; text.append(...body);
      const row = document.createElement("div"); row.className = "lg-q-actions";
      for (const b of actions) { b.setAttribute("size", "large"); b.setAttribute("wide", ""); if (!b.hasAttribute("variant")) b.setAttribute("variant", "filled"); row.append(b); }
      this.replaceChildren(top, ...(body.length ? [text] : []), row);
    }
  }

  define("lg-question", Question);
})();
