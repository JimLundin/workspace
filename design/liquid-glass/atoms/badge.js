/* Atom: <lg-badge tone="orange">2</lg-badge>, a count over a control. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, define } = LG;

  class Badge extends Element {}

  define("lg-badge", Badge);
})();
