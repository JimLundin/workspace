/* BubbleStack: transient glass bubbles. The newest is opaque; earlier ones
   collapse to their title and recede; beyond the limit they leave the way they came.

     const stack = new LiquidGlass.BubbleStack(root, { limit: 3 });
     const bubble = stack.push(html);   // returns the bubble element
     stack.clear(); */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { clamp, Spring } = LG;

  class BubbleStack {
    constructor(root, { limit = 3 } = {}) {
      Object.assign(this, { root, limit });
      root.classList.add("lg-stack");
      root.setAttribute("aria-live", "polite");
    }
    push(html) {
      for (const b of this.root.children) b.classList.add("lg-past");
      const bubble = document.createElement("div");
      bubble.className = "lg-bubble";
      bubble.innerHTML = html;
      LG.glass(bubble, { large: true, interactive: true });
      this.root.append(bubble);
      // Bubbles materialize from the trailing edge.
      new Spring(0, v => {
        bubble.style.opacity = clamp(v, 0, 1);
        bubble.style.transform = `translateX(${(1 - v) * 40}px) scale(${0.94 + 0.06 * v})`;
        bubble.style.filter = v < 0.98 ? `blur(${(1 - clamp(v, 0, 1)) * 10}px)` : "";
      }, { damping: 0.82, response: 0.45 }).to(1);
      this.recede();
      return bubble;
    }
    recede() {
      const all = [...this.root.children];
      all.forEach((b, i) => {
        const age = all.length - 1 - i;
        b.style.opacity = age === 0 ? 1 : Math.max(0.35, 0.72 - age * 0.18);
        if (age >= this.limit) {
          b.animate([{ opacity: b.style.opacity }, { opacity: 0, transform: "translateX(40px) scale(.94)" }], { duration: 260, easing: "ease-in" }).onfinish = () => b.remove();
        }
      });
    }
    clear() { this.root.replaceChildren(); }
  }
  LG.BubbleStack = BubbleStack;
})();
