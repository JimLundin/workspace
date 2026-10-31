/* Container: <lg-scroll>, native scrolling with overlay scroll bars and edge fades. Set .content to replace it. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, clamp, define } = LG;

  /* ── Scroll view ───────────────────────────────────────────────────
     The bar stays hidden at rest, appears while content moves, and fades after a
     moment. Hovering it thickens the thumb and shows its track; the thumb drags and
     the track pages. Edges with content beyond them fade softly. */
  const IDLE = 900;  // ms after the last scroll before the bar fades
  class Scroll extends Element {
    build() {
      this.viewport = document.createElement("div");
      this.viewport.className = "lg-viewport";
      this.viewport.tabIndex = -1;
      this.viewport.append(...this.childNodes);
      this.track = document.createElement("div");
      this.track.className = "lg-track";
      this.thumb = document.createElement("div");
      this.thumb.className = "lg-thumb";
      this.track.append(this.thumb);
      this.append(this.viewport, this.track);
      this.viewport.addEventListener("scroll", () => { this.layout(); this.wake(); }, { passive: true });
      new ResizeObserver(() => this.layout()).observe(this.viewport);
      new MutationObserver(() => this.layout()).observe(this.viewport, { childList: true, subtree: true });
      this.thumb.addEventListener("pointerdown", e => {
        e.preventDefault(); e.stopPropagation();
        this.thumb.setPointerCapture(e.pointerId);
        const start = e.clientY, from = this.viewport.scrollTop;
        const ratio = (this.viewport.scrollHeight - this.viewport.clientHeight) / Math.max(1, this.track.clientHeight - this.thumb.offsetHeight);
        this.classList.add("lg-dragging");
        const move = ev => { this.viewport.scrollTop = from + (ev.clientY - start) * ratio; };
        const up = () => { this.classList.remove("lg-dragging"); this.thumb.removeEventListener("pointermove", move); this.wake(); };
        this.thumb.addEventListener("pointermove", move);
        this.thumb.addEventListener("pointerup", up, { once: true });
      });
      // Clicking the track pages toward the pointer.
      this.track.addEventListener("pointerdown", e => {
        if (e.target !== this.track) return;
        const below = e.clientY > this.thumb.getBoundingClientRect().bottom;
        this.viewport.scrollBy({ top: (below ? 1 : -1) * this.viewport.clientHeight * 0.9, behavior: "smooth" });
      });
      requestAnimationFrame(() => this.layout());
    }
    // Replace the scrolled content.
    set content(html) { this.viewport.innerHTML = String(html); this.viewport.scrollTop = 0; }
    layout() {
      const { scrollTop, scrollHeight, clientHeight } = this.viewport;
      const scrollable = scrollHeight > clientHeight + 1;
      this.track.style.display = scrollable ? "" : "none";
      const fade = [];
      if (scrollable && scrollTop > 1) fade.push("top");
      if (scrollable && scrollTop + clientHeight < scrollHeight - 1) fade.push("bottom");
      this.dataset.fade = fade.join(" ");
      if (!scrollable) return;
      const trackHeight = this.track.clientHeight;
      const size = clamp(trackHeight * clientHeight / scrollHeight, 24, trackHeight);
      const top = (trackHeight - size) * scrollTop / (scrollHeight - clientHeight);
      Object.assign(this.thumb.style, { height: `${size}px`, top: `${top}px` });
    }
    wake() {
      this.classList.add("lg-scrolling");
      clearTimeout(this.idle);
      this.idle = setTimeout(() => this.classList.remove("lg-scrolling"), IDLE);
    }
  }

  define("lg-scroll", Scroll);
})();
