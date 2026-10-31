/* Foundations: the icon registry. One set registers itself (see icons/fluent.js);
   `filled` variants mark active states, as SF Symbols' .fill does. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;

  /* Icons: one registered set; `filled` variants mark active states, as SF Symbols' .fill does. */
  let iconSet = null;
  LG.icons = { register(set) { iconSet = set; } };
  LG.iconSvg = (name, filled = false) => {
    // A small rounded square reads as Stop at toolbar size, like SF Symbols' stop.fill.
    if (name === "stop") return `<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="4.25" y="4.25" width="7.5" height="7.5" rx="1.8"/></svg>`;
    const body = (filled && iconSet.filled[name]) || iconSet.regular[name];
    if (!body) throw new Error(`Unknown icon: ${name}`);
    return `<svg viewBox="${iconSet.viewBox}" aria-hidden="true">${body}</svg>`;
  };
})();
