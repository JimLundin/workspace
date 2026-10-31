/* Liquid Glass kit loader: the single entry point for scripts.

     <link rel="stylesheet" href="liquid-glass/liquid-glass.css">
     <script src="liquid-glass/liquid-glass.js"></script>
     <script>LiquidGlass.ready.then(() => { … });</script>

   It loads every component in tier order, so each file only uses what earlier tiers
   define. Classic scripts, no modules: pages work from disk and inside web views.
   LiquidGlass.ready resolves once every element is defined and the kit's typeface has
   loaded, so first measurements use the right font.

   Adding a component: add its script here and its stylesheet in liquid-glass.css. */
(() => {
  "use strict";
  const MANIFEST = [
    "foundations/core.js", "foundations/icons.js", "foundations/material.js", "icons/fluent.js",
    "atoms/icon.js", "atoms/button.js", "atoms/badge.js", "atoms/indicators.js", "atoms/fact.js", "atoms/timer.js", "atoms/app.js", "atoms/field.js",
    "controls/segmented.js", "controls/switch.js",
    "molecules/menu.js", "molecules/question.js", "molecules/card.js", "molecules/steps.js", "molecules/form.js",
    "containers/scroll.js", "containers/popover.js", "containers/stack.js", "containers/sidebar.js", "containers/inspector.js", "containers/window.js",
    "bars/capsule.js", "bars/island-bar.js",
  ];
  const base = document.currentScript.src.replace(/[^/]*$/, "");
  const LG = (window.LiquidGlass = window.LiquidGlass || {});
  LG.ready = new Promise((resolve, reject) => {
    let pending = MANIFEST.length;
    for (const file of MANIFEST) {
      const script = document.createElement("script");
      script.src = base + file;
      script.async = false;  // dynamically inserted scripts then run in insertion order
      script.onload = () => {
        if (--pending) return;
        Promise.all(["500 12px", "600 14px"].map(f => document.fonts.load(`${f} "LG Inter"`))).catch(() => {}).then(() => resolve(LG));
      };
      script.onerror = () => reject(new Error(`Liquid Glass couldn't load ${file}`));
      document.head.append(script);
    }
  });
})();
