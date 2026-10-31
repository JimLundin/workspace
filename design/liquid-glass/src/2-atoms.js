/* Layer 2: atoms.

     <lg-icon name="mic" filled></lg-icon>
     <lg-button icon="bell" label="Inbox" badge="3" act="inbox"></lg-button>
     <lg-button variant="accent" size="large" act="send">Send</lg-button>
     <lg-badge tone="orange">2</lg-badge>
     <lg-spinner label="Transcribing"></lg-spinner>   <lg-dot></lg-dot>   <lg-wave bars="18" live></lg-wave>
     <lg-fact icon="battery" num>73%</lg-fact>        <lg-timer since="1730370000000"></lg-timer>
     <lg-kbd>N</lg-kbd>   <lg-app glyph="T" color="…" size="small"></lg-app>
     <lg-field icon="search" placeholder="Search"></lg-field>

   Any element with an `act` attribute reports that action to the bar or container
   it sits in; see <lg-island-bar>. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, define, escape } = LG;

  class Icon extends Element {
    static get observedAttributes() { return ["name", "filled", "label"]; }
    update() {
      this.innerHTML = LG.iconSvg(this.getAttribute("name"), this.hasAttribute("filled"));
      const label = this.getAttribute("label");
      if (label) { this.setAttribute("role", "img"); this.setAttribute("aria-label", label); } else this.setAttribute("aria-hidden", "true");
    }
  }

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

  class Badge extends Element {}

  class Spinner extends Element {
    static get observedAttributes() { return ["label"]; }
    update() {
      const label = this.getAttribute("label") || "Working";
      this.setAttribute("role", "status"); this.setAttribute("aria-label", label); this.title = label;
    }
  }

  class Dot extends Element { update() { this.setAttribute("aria-hidden", "true"); } }

  /* Waveform. `live` bars follow LiquidGlass.audio.level(bar, time), which the host supplies
     from its audio meter; without one, the bars rest flat. */
  const live = new Set();
  let pump = null;
  LG.audio = { level: null };
  function animate() {
    const now = performance.now() / 1000;
    for (const wave of live) [...wave.children].forEach((bar, i) => {
      const level = LG.audio.level ? LG.clamp(LG.audio.level(i, now), 0, 1) : 0;
      bar.style.height = `${3 + 12 * level}px`;
    });
    pump = live.size ? setTimeout(animate, 60) : null;
  }
  class Wave extends Element {
    static get observedAttributes() { return ["bars"]; }
    update() { this.setAttribute("aria-hidden", "true"); this.innerHTML = "<i></i>".repeat(Number(this.getAttribute("bars") || 18)); }
    connectedCallback() {
      super.connectedCallback();
      if (this.hasAttribute("live")) { live.add(this); if (!pump) animate(); }
    }
    disconnectedCallback() { live.delete(this); }
  }

  /* A fact: a reading with an optional symbol. Attributes: icon, num, quiet, strong, tone. */
  class Fact extends Element {
    static get observedAttributes() { return ["icon"]; }
    build() { this.text = this.textContent.trim(); this.update(); }
    update() {
      const icon = this.getAttribute("icon");
      this.innerHTML = `${icon ? `<lg-icon name="${escape(icon)}"${this.hasAttribute("filled") ? " filled" : ""}></lg-icon>` : ""}${this.text ? `<span>${escape(this.text)}</span>` : ""}`;
    }
  }

  /* Elapsed time since `since` (epoch ms): mm:ss, then h:mm:ss after an hour.
     It dispatches a bubbling "lg-resize" when its reading changes length, so the
     capsule around it can re-measure. */
  LG.clock = total => {
    const h = total / 3600 | 0, m = (total / 60 | 0) % 60, s = String(total % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${String(m).padStart(2, "0")}:${s}`;
  };
  class Timer extends Element {
    static get observedAttributes() { return ["since"]; }
    update() {
      const reading = LG.clock(Math.max(0, Math.floor((Date.now() - Number(this.getAttribute("since") || Date.now())) / 1000)));
      const grew = this.reading !== undefined && this.reading.length !== reading.length;
      this.reading = reading;
      this.textContent = reading;
      if (grew) this.dispatchEvent(new Event("lg-resize", { bubbles: true }));
    }
    connectedCallback() {
      super.connectedCallback();
      this.update();
      clearInterval(this.ticker);
      this.ticker = setInterval(() => this.update(), 1000);
    }
    disconnectedCallback() { clearInterval(this.ticker); }
  }

  class Kbd extends Element {}

  class App extends Element {
    static get observedAttributes() { return ["glyph", "color"]; }
    update() {
      this.textContent = this.getAttribute("glyph") || "";
      const color = this.getAttribute("color");
      if (color) this.style.setProperty("--lg-app", color);
      this.setAttribute("aria-hidden", "true");
    }
  }

  /* A text field with an optional leading symbol. Native input events bubble from it. */
  class Field extends Element {
    build() {
      const icon = this.getAttribute("icon");
      this.innerHTML = `${icon ? `<lg-icon name="${escape(icon)}"></lg-icon>` : ""}<input type="text" placeholder="${escape(this.getAttribute("placeholder") || "")}" aria-label="${escape(this.getAttribute("label") || this.getAttribute("placeholder") || "")}" value="${escape(this.getAttribute("value") || "")}">`;
    }
    get value() { return this.querySelector("input")?.value ?? ""; }
    set value(v) { const input = this.querySelector("input"); if (input) input.value = v; }
    focus() { this.querySelector("input")?.focus(); }
  }

  define("lg-icon", Icon);
  define("lg-button", Button);
  define("lg-badge", Badge);
  define("lg-spinner", Spinner);
  define("lg-dot", Dot);
  define("lg-wave", Wave);
  define("lg-fact", Fact);
  define("lg-timer", Timer);
  define("lg-kbd", Kbd);
  define("lg-app", App);
  define("lg-field", Field);
})();
