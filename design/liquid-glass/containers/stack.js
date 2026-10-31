/* Container: <lg-stack limit="3">, transient glass cards. .push(card) and .clear(). */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, clamp, Spring, define } = LG;

  /* ── Stack: transient glass cards. The newest is opaque; earlier ones collapse to
     their heads and recede; beyond the limit they leave the way they came. ── */
  class Stack extends Element {
    build() { this.setAttribute("aria-live", "polite"); }
    push(card) {
      if (!(card instanceof HTMLElement)) card = LG.fragment(card);
      for (const c of this.children) c.setAttribute("collapsed", "");
      card.setAttribute("variant", "glass");
      this.append(card);
      LG.glass(card, { large: true, interactive: true });
      // Cards materialize from the trailing edge.
      new Spring(0, v => {
        // The entrance multiplies with the recede level, so a late frame can't undo a recede.
        card.style.opacity = clamp(v, 0, 1) * Number(card.dataset.lgRecede || 1);
        card.style.transform = `translateX(${(1 - v) * 40}px) scale(${0.94 + 0.06 * v})`;
        card.style.filter = v < 0.98 ? `blur(${(1 - clamp(v, 0, 1)) * 10}px)` : "";
      }, { damping: 0.82, response: 0.45 }).to(1);
      const limit = Number(this.getAttribute("limit") || 3), all = [...this.children];
      all.forEach((c, i) => {
        const age = all.length - 1 - i;
        if (age) { c.dataset.lgRecede = Math.max(0.35, 0.72 - age * 0.18); c.style.opacity = c.dataset.lgRecede; }
        if (age >= limit) c.animate([{ opacity: c.style.opacity }, { opacity: 0, transform: "translateX(40px) scale(.94)" }], { duration: 260, easing: "ease-in" }).onfinish = () => c.remove();
      });
      return card;
    }
    clear() { this.replaceChildren(); }
  }

  define("lg-stack", Stack);
})();
