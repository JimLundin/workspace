/* Layer 5: containers.

     <lg-scroll> …content… </lg-scroll>                 overlay scroll bars and edge fades
     <lg-popover> …menu… </lg-popover>                  .showBeside(element) / .hide()
     <lg-stack limit="3"></lg-stack>                    .push(card) / .clear()
     <lg-sidebar label="…"> …sections… </lg-sidebar>    .open, .toggle(); "toggle" event
     <lg-window heading="…" detail="…"> …content… <lg-inspector>…</lg-inspector> </lg-window>
                                                        .open; "close" event
     <lg-inspector label="…"> …content… </lg-inspector> .open; "close" and "toggle" events */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, define, clamp, Spring, motion } = LG;

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

  /* ── Popover: large glass beside its source, appearing from it. ─── */
  class Popover extends Element {
    build() { this.setAttribute("role", "menu"); LG.glass(this, { large: true }); }
    showBeside(source, { gap = 12 } = {}) {
      const box = source.getBoundingClientRect();
      Object.assign(this.style, { left: `${box.right + gap}px`, top: `${box.top - 6}px` });
      if (!this.hasAttribute("open")) {
        this.setAttribute("open", "");
        this.animate([{ opacity: 0, transform: "scale(.96) translateX(-6px)", filter: "blur(4px)" }, { opacity: 1, transform: "none", filter: "none" }], { duration: 220, easing: "cubic-bezier(.2,.8,.2,1)" });
      }
    }
    hide() { this.removeAttribute("open"); }
  }

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

  /* ── Sidebar: floats inset in the glass layer; a toggle stays in place while the
     sidebar slides out along the leading edge and back the same way. ── */
  class Sidebar extends Element {
    build() {
      this.setAttribute("role", "complementary");
      if (this.getAttribute("label")) this.setAttribute("aria-label", this.getAttribute("label"));
      LG.glass(this, { large: true, lens: false });
      const scroll = document.createElement("lg-scroll");
      scroll.append(...this.childNodes);
      this.append(scroll);
      this.button = document.createElement("button");
      this.button.className = "lg-side-toggle";
      this.button.innerHTML = '<lg-icon name="side"></lg-icon>';
      LG.glass(this.button, { lens: false, interactive: true });
      this.button.addEventListener("click", () => this.toggle());
      this.after(this.button);
      this.state = true;
      this.spring = new Spring(1, v => {
        this.style.transform = `translateX(${(v - 1) * (this.offsetWidth + 16)}px)`;
        this.style.opacity = clamp(v * 1.4, 0, 1);
        this.style.visibility = v < 0.01 ? "hidden" : "";
      }, motion.slide);
      this.label();
      new MutationObserver(() => LG.scheme(this.button, this.classList.contains("lg-light") ? "light" : this.classList.contains("lg-dark") ? "dark" : null)).observe(this, { attributes: true, attributeFilter: ["class"] });
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
  }

  /* ── Inspector: a floating column inset in its window. It slides in from the
     trailing edge and leaves the same way. Set .content to replace what it shows. ── */
  class Inspector extends Element {
    build() {
      this.setAttribute("role", "complementary");
      if (this.getAttribute("label")) this.setAttribute("aria-label", this.getAttribute("label"));
      LG.glass(this, { large: true });
      this.scroll = document.createElement("lg-scroll");
      this.scroll.append(...this.childNodes);
      const close = LG.fragment(LG.h("lg-button", { class: "lg-close", icon: "x", label: "Close details" }));
      close.addEventListener("click", () => { this.open = false; this.dispatchEvent(new Event("close")); });
      this.append(this.scroll, close);
      this.state = false;
      this.spring = new Spring(0, p => {
        this.style.transform = `translateX(${(1 - p) * (this.offsetWidth + 20)}px)`;
        this.style.opacity = clamp(p * 2, 0, 1);
      }, { damping: 0.9, response: 0.4 });
    }
    set content(html) { this.scroll.content = html; }
    get open() { return this.state; }
    set open(open) {
      if (open === this.state) return;
      this.state = open;
      if (open) { this.style.display = "block"; this.spring.set(0); this.spring.to(1); }
      else this.spring.to(0, { done: () => { if (!this.state) this.style.display = "none"; } });
      this.dispatchEvent(new Event("toggle", { bubbles: true }));
    }
  }

  /* ── Window: a solid content surface with large corners, window controls, a title,
     and scroll edge effects where content passes beneath floating controls. ── */
  class Window extends Element {
    build() {
      this.setAttribute("role", "dialog");
      if (this.getAttribute("heading")) this.setAttribute("aria-label", this.getAttribute("heading"));
      const chrome = LG.fragment(`<div class="lg-traffic"><button type="button" aria-label="Close" title="Close"></button><button type="button" aria-label="Minimise" title="Minimise"></button><button type="button" aria-label="Zoom" title="Zoom"></button></div>`);
      chrome.firstElementChild.addEventListener("click", () => { this.open = false; this.dispatchEvent(new Event("close")); });
      const title = document.createElement("div");
      title.className = "lg-title";
      title.innerHTML = `${LG.escape(this.getAttribute("heading") || "")}${this.getAttribute("detail") ? `<small>${LG.escape(this.getAttribute("detail"))}</small>` : ""}`;
      const edgeTop = document.createElement("div"); edgeTop.className = "lg-edge-top";
      const edgeBottom = document.createElement("div"); edgeBottom.className = "lg-edge-bottom";
      // Edges sit above the content and below the floating controls.
      const content = this.querySelector(":scope > :not(lg-island-bar):not(lg-inspector)");
      if (content) content.after(edgeTop, edgeBottom); else this.prepend(edgeTop, edgeBottom);
      this.append(chrome, title);
      // An open inspector moves the window's bottom bar into the remaining column.
      this.addEventListener("toggle", e => { if (e.target.tagName === "LG-INSPECTOR") this.toggleAttribute("inspecting", e.target.open); });
      this.state = false;
      this.spring = new Spring(0, p => {
        this.style.opacity = clamp(p * 1.5, 0, 1);
        this.style.transform = `translateX(-50%) translateY(${(1 - p) * -24}px) scale(${0.9 + 0.1 * p})`;
      }, { damping: 0.9, response: 0.42 });
    }
    get open() { return this.state; }
    set open(open) {
      if (open === this.state) return;
      this.state = open;
      if (open) { this.setAttribute("open", ""); this.spring.to(1); }
      else this.spring.to(0, { damping: 1, response: 0.3, done: () => { if (!this.state) this.removeAttribute("open"); } });
    }
  }

  define("lg-scroll", Scroll);
  define("lg-popover", Popover);
  define("lg-stack", Stack);
  define("lg-sidebar", Sidebar);
  define("lg-inspector", Inspector);
  define("lg-window", Window);
})();
