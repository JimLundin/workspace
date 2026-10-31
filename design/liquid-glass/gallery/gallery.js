/* Gallery: each tier's components, composed only from the kit. */
window.LiquidGlass.ready.then(LG => {
  "use strict";
  const { $, $$, h, html } = LG;
  LG.audio.level = (i, t) => Math.abs(Math.sin(t * 7 + i * 0.8) * Math.cos(t * 2.3 + i * 0.3));

  // Foundations and atoms: apply the material where the markup asks for it.
  for (const el of $$("[data-glass]")) LG.glass(el, { large: el.dataset.glass === "large", interactive: el.classList.contains("swatch") });
  $("#timer").setAttribute("since", Date.now() - 125_000);
  const icons = ["menu", "canvas", "bell", "battery", "mic", "x", "kbd", "search", "center", "q", "more", "feed", "rec", "map", "overlay", "task", "copy", "tile", "gear", "chev", "chevdown", "check", "checkc", "edge", "spark", "side", "wifioff", "speaker", "cloud", "stop"];
  $("#icons").innerHTML = String(html(icons.map(name => h("figure", {}, [h("lg-icon", { name }), name]))));

  // Molecules.
  $("#menu").innerHTML = String(h("lg-menu", { heading: "Menu", detail: "Detail" }, [
    h("lg-live-row", { label: "Ongoing work" }, [h("lg-spinner", { slot: "glyph" }), h("lg-button", { slot: "control", icon: "stop", label: "Stop" })]),
    h("lg-live-row", { label: "Recording" }, [h("lg-dot", { slot: "glyph" }), h("lg-timer", { slot: "detail", since: Date.now() - 65_000 }), h("lg-button", { slot: "control", icon: "stop", label: "Stop recording" })]),
    h("lg-menu-item", { icon: "canvas" }, "Item with a symbol"),
    h("lg-menu-item", { icon: "feed", key: "Ctrl K" }, "With a shortcut"),
    h("lg-menu-item", { icon: "task", check: true }, "Checked"),
    h("lg-menu-separator"),
    h("lg-menu-item", { icon: "tile", sub: "more" }, "With a submenu"),
  ]));
  $("#question").innerHTML = String(h("lg-question", { heading: "Which sheet should the reply cover?", meta: "now" }, [
    h("lg-app", { slot: "badge", glyph: "✦", size: "medium" }), h("span", { slot: "body" }, "Costs includes deferred licences; Revenue doesn't."),
    h("lg-button", { variant: "accent" }, "Revenue"), h("lg-button", {}, "Costs"), h("lg-button", {}, "Later"),
  ]));
  const card = variant => h("lg-card", { variant, heading: "Anna Berg", meta: "Teams · 9:41", time: "now" }, [
    h("lg-app", { slot: "badge", glyph: "T", color: "linear-gradient(145deg,#7b83eb,#4f52b2)", size: variant === "solid" ? "small" : null }),
    h("span", { slot: "body" }, `A ${variant} card: the same anatomy in the ${variant === "solid" ? "content" : "functional"} layer.`),
  ]);
  $("#cards").innerHTML = String(html(card("solid"), card("glass")));
  LG.glass($("#cards lg-card[variant=glass]"), { large: true });
  $("#steps").innerHTML = String(html(h("h3", {}, "Steps"), h("lg-steps", {}, [h("lg-step", { state: "done" }, "Read the conversation"), h("lg-step", { state: "running" }, "Compare both sheets"), h("lg-step", { state: "pending" }, "Draft a reply")])));
  setTimeout(() => $("#steps lg-step[state=pending]")?.setAttribute("state", "running"), 1200);

  // Containers.
  $("#scroll").content = html(Array.from({ length: 30 }, (_, i) => h("lg-row", { label: `Row ${i + 1}` }, h("lg-switch", { checked: i % 3 === 0 }))));
  $("#pop").addEventListener("click", e => { const p = $("#popover"); p.hasAttribute("open") ? p.hide() : p.showBeside(e.currentTarget); });
  let pushed = 0;
  $("#push").addEventListener("click", () => {
    pushed++;
    $("#stack").push(h("lg-card", { heading: `Step ${pushed}`, time: "now" }, [h("lg-app", { slot: "badge", glyph: String(pushed) }), h("span", { slot: "body" }, "Earlier cards collapse and recede.")]));
  });
  $("#openWindow").addEventListener("click", () => { $("#window").open = true; $("#windowBar").render(); });
  $("#inspect").addEventListener("click", () => {
    const inspector = $("#inspector");
    inspector.content = html(h("lg-app", { glyph: "✦" }), h("h2", {}, "Inspector"), h("div", { class: "lg-sub" }, "Inset, concentric, scrollable"),
      h("lg-actions", { class: "lg-actions" }, [h("lg-button", { variant: "accent", size: "large" }, "Primary"), h("lg-button", { variant: "filled", size: "large" }, "Secondary")]),
      Array.from({ length: 16 }, (_, i) => h("div", { class: "lg-well", style: "margin-top:8px" }, `Detail ${i + 1}`)));
    inspector.open = true;
  });
  $("#windowBar").view = () => [{ zone: "island", key: "island", content: html(h("lg-button", { icon: "mic", label: "Speak" }), h("lg-button", { icon: "search", label: "Search" }), h("lg-button", { icon: "more", label: "More" })) }];

  // Bars: one island bar driven by a state the buttons pick.
  const bar = $("#bar");
  let mode = "rest";
  const since = Date.now() - 125_000;
  bar.view = b => {
    const v = [], add = (zone, key, content, more = {}) => v.push({ zone, key, content, kind: "text", ...more });
    const facts = h("lg-slot", {}, [h("lg-fact", { num: true }, "10:22"), h("lg-fact", { icon: "battery", num: true }, "73%")]);
    const busy = mode !== "rest";
    if (busy && mode !== "busy" && mode !== "menu") { add("lead", "agent", h("lg-spinner", { label: "Working" }), { kind: "min" }); add("trail", "recording", html(h("lg-dot"), h("lg-timer", { since }))); }
    add("trail", "inbox", h("lg-button", { icon: "bell", label: "Inbox", badge: 3 }), { kind: "icons" });
    if (mode === "dictate") add("island", "island", html(h("lg-fact", { icon: "mic", filled: true, tone: "mic" }), h("lg-wave", { live: true })));
    else if (mode === "ask") v.push(b.expanded("island", "island", h("lg-question", { heading: "Which sheet?", meta: "now" }, [h("lg-app", { slot: "badge", glyph: "✦", size: "medium" }), h("lg-button", { variant: "accent" }, "Revenue"), h("lg-button", {}, "Costs")]), 340, 28));
    else if (mode === "menu") v.push(b.expanded("island", "island", h("lg-menu", { heading: "Menu" }, [h("lg-live-row", { label: "Working" }, [h("lg-spinner", { slot: "glyph" }), h("lg-button", { slot: "control", icon: "stop", label: "Stop" })]), h("lg-menu-item", { icon: "canvas" }, "First item"), h("lg-menu-item", { icon: "gear" }, "Settings")]), 260, 21));
    else if (mode === "busy") add("island", "island", html(h("lg-slot", {}, h("lg-spinner", { label: "Working" })), facts, h("lg-slot", {}, [h("lg-dot"), h("lg-timer", { since })])));
    else add("island", "island", facts);
    return v;
  };
  bar.addEventListener("lg-action", e => { if (e.detail.action === "press" && mode === "rest") { mode = "menu"; bar.render(); } });
  $("#states").addEventListener("click", e => { const act = e.target.closest("[act]")?.getAttribute("act"); if (act) { mode = act; bar.render(); } });

  // Page: scheme and contents.
  const scheme = value => { LG.scheme(document.body, value); for (const el of [$("#side"), $("#window"), $("#popover")]) LG.scheme(el, value); };
  $("#scheme").addEventListener("change", e => scheme(e.target.value));
  scheme("dark");
  $("#side").addEventListener("click", e => { const act = e.target.closest("[act]")?.getAttribute("act"); if (act) $$(".tier")[Number(act.split("-")[1]) - 1].scrollIntoView({ behavior: "smooth" }); });
  document.fonts.ready.then(() => { bar.refresh(); });
  bar.render();
});
