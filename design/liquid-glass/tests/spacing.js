/* Bar spacing invariants, checked across every transition between every state.

   States: each subset of two lead and two trail capsules, with a short or a long
   island (2^4 × 2 = 32). Transitions: every ordered pair of states (1024), so every
   order of arrival is covered: a capsule appearing before, after or between ones
   already shown. Results land in window.lgTest = { done, passed, failures, transitions }. */
LiquidGlass.ready.then(LG => {
  "use strict";
  const { h, html } = LG;
  const bar = document.getElementById("bar");
  const out = document.getElementById("result");
  const TOLERANCE = 0.5;   // px
  LG.timeScale = 10;       // motion runs ten times faster; the geometry it reaches is the same

  const KEYS = ["lead-far", "lead-near", "trail-near", "trail-far"];
  const states = [];
  for (let mask = 0; mask < 16; mask++) for (const long of [false, true]) states.push({ mask, long });
  const label = s => `${KEYS.filter((_, i) => s.mask & (1 << i)).join("+") || "island only"}${s.long ? " (long island)" : ""}`;

  let current = states[0];
  bar.view = () => {
    const views = [{ zone: "island", key: "island", kind: "text", content: html(h("lg-fact", { num: true }, current.long ? "10:22 · 73% · Comparing sheets" : "10:22")) }];
    KEYS.forEach((key, i) => {
      if (!(current.mask & (1 << i))) return;
      views.push({ zone: key.startsWith("lead") ? "lead" : "trail", key, kind: "text", content: h("lg-fact", {}, key) });
    });
    return views;
  };

  const gap = parseFloat(getComputedStyle(bar).getPropertyValue("--lg-gap"));
  // Visible capsules left to right, by layout box. Hidden ones take no space. The entrance
  // and press scales are centred visual effects, not spacing, so undo them around the centre.
  const layout = () => [...bar.querySelectorAll(".lg-cap")].filter(el => !el.hidden && el.offsetWidth > 0.5)
    .map(el => { const r = el.getBoundingClientRect(), left = r.left + (r.width - el.offsetWidth) / 2; return { key: el.dataset.key, left, right: left + el.offsetWidth }; })
    .sort((a, b) => a.left - b.left);

  const failures = [];
  const fail = (from, to, message) => { if (failures.length < 50) failures.push(`${label(from)} → ${label(to)}: ${message}`); };
  const frame = () => new Promise(requestAnimationFrame);

  async function transition(from, to) {
    current = from; bar.refresh();                     // arrive at `from` instantly
    await frame();
    current = to; bar.render();                        // then animate to `to`
    for (let i = 0; i < 400 && (LG.moving() || i < 2); i++) {
      await frame();
      const caps = layout();
      for (let j = 1; j < caps.length; j++) {
        const space = caps[j].left - caps[j - 1].right;
        if (space < -TOLERANCE) return fail(from, to, `${caps[j - 1].key} and ${caps[j].key} overlap by ${(-space).toFixed(1)} px mid-transition`);
      }
    }
    await new Promise(r => setTimeout(r, 30));
    const caps = layout();
    const expected = ["island", ...KEYS.filter((_, i) => to.mask & (1 << i))].sort();
    const shown = caps.map(c => c.key).sort();
    if (shown.join() !== expected.join()) return fail(from, to, `shows ${shown.join(", ")}; expected ${expected.join(", ")}`);
    for (let j = 1; j < caps.length; j++) {
      const space = caps[j].left - caps[j - 1].right;
      if (Math.abs(space - gap) > TOLERANCE) return fail(from, to, `${caps[j - 1].key} and ${caps[j].key} are ${space.toFixed(1)} px apart at rest; expected ${gap} px`);
    }
  }

  (async () => {
    await frame();
    let count = 0;
    for (const from of states) for (const to of states) {
      await transition(from, to);
      if (++count % 64 === 0) out.textContent = `Running… ${count} of ${states.length ** 2} transitions`;
    }
    const passed = failures.length === 0;
    window.lgTest = { done: true, passed, failures, transitions: count };
    out.className = passed ? "pass" : "fail";
    out.textContent = passed ? `Passed: ${count} transitions, every gap ${gap} px at rest and no overlap on any frame.` : `Failed (${failures.length}${failures.length === 50 ? "+" : ""}):\n${failures.join("\n")}`;
    LG.timeScale = 1;
  })();
});
