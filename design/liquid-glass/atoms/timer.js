/* Atom: <lg-timer since="1730370000000">, an elapsed-time reading. A capsule around it follows its width. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, define } = LG;

  /* Elapsed time since `since` (epoch ms): mm:ss, then h:mm:ss after an hour. */
  LG.clock = total => {
    const h = total / 3600 | 0, m = (total / 60 | 0) % 60, s = String(total % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${String(m).padStart(2, "0")}:${s}`;
  };
  class Timer extends Element {
    static get observedAttributes() { return ["since"]; }
    update() {
      const reading = LG.clock(Math.max(0, Math.floor((Date.now() - Number(this.getAttribute("since") || Date.now())) / 1000)));
      if (this.textContent !== reading) this.textContent = reading;
    }
    connectedCallback() {
      super.connectedCallback();
      this.update();
      clearInterval(this.ticker);
      this.ticker = setInterval(() => this.update(), 1000);
    }
    disconnectedCallback() { clearInterval(this.ticker); }
  }

  define("lg-timer", Timer);
})();
