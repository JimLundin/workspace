/* Workspace in Liquid Glass: the desktop island bar, agent cards and the work canvas,
   composed from kit elements. Only Workspace's behaviour and content live here. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { $, $$, clamp, Spring, h, html } = LG;
  const body = document.body;

  const state = { moment: "none", agent: "off", recording: false, layer: false, inbox: true, wallpaper: "vivid", appearance: "dark" };
  const params = new URLSearchParams(location.search);
  for (const key of ["moment", "agent", "wallpaper", "appearance"]) if (params.has(key)) state[key] = params.get(key);
  for (const key of ["recording", "layer", "inbox"]) if (params.has(key)) state[key] = params.get(key) === "1";
  if (!params.has("appearance")) state.appearance = matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  // The recording's start, so a re-rendered timer keeps counting from the same moment.
  let recordingSince = Date.now() - 125_000;

  const apps = {
    workspace: { glyph: "✦", color: "linear-gradient(145deg,#7d6bff,#4b9dff)" },
    teams: { glyph: "T", color: "linear-gradient(145deg,#7b83eb,#4f52b2)" },
    outlook: { glyph: "O", color: "linear-gradient(145deg,#28a8ea,#0c64c4)" },
    kanban: { glyph: "K", color: "linear-gradient(145deg,#ffb340,#e08600)" },
    excel: { glyph: "X", color: "linear-gradient(145deg,#33c481,#107c41)" },
    note: { glyph: "✎", color: "linear-gradient(145deg,#ffd60a,#f2b705)" },
    question: { glyph: "?", color: "linear-gradient(145deg,#7d6bff,#4b9dff)" },
  };
  const badge = (name, size) => h("lg-app", { slot: "badge", ...apps[name], size });

  // A synthetic microphone level for the demo's waveforms.
  LG.audio.level = (i, t) => {
    const envelope = 0.35 + 0.65 * Math.abs(Math.sin(t * 2.6 + i * 0.22));
    return envelope * Math.abs(Math.sin(t * 8.6 + i * 0.9) * Math.cos(t * 3.4 + i * 0.3));
  };

  /* ── Desktop bar ─────────────────────────────────────────────────────
     At rest the island shows the time and battery. Processing (transcription or agent
     work) takes its leading slot as a spinner, and a meeting recording its trailing
     slot. A moment (dictation, a question, the menu) takes the island over; processing
     and recording then detach beside it. The inbox appears only while items wait. */
  const desktop = $("#bar");
  Object.assign(desktop, { menuOpen: false, expandedQ: false, prevAgent: "off" });
  const agentPhase = "Comparing sheets";

  function processing() {
    const parts = [state.moment === "transcribing" && "Transcribing", state.agent === "working" && `Agent: ${agentPhase}`].filter(Boolean);
    return parts.length ? h("lg-spinner", { label: parts.join(" · ") }) : null;
  }
  const recordingFacts = () => html(h("lg-dot"), h("lg-timer", { since: recordingSince }));

  desktop.view = bar => {
    const views = [], add = (zone, key, content, more = {}) => views.push({ zone, key, content, kind: "text", ...more });
    const dictating = state.moment === "dictating", asking = state.agent === "needs";
    if (asking && bar.prevAgent !== "needs") expandQuestion();
    if (!asking) bar.expandedQ = false;
    bar.prevAgent = state.agent;
    const resting = !bar.menuOpen && !dictating && !asking;
    const spinner = processing();

    if (state.layer) add("lead", "layer", h("lg-fact", { icon: "kbd" }, "NAV"));
    if (!resting && !bar.menuOpen && spinner) add("lead", "agent", spinner, { kind: "min" });
    if (!resting && !bar.menuOpen && state.recording) add("trail", "recording", recordingFacts());
    if (state.inbox) add("trail", "inbox", h("lg-button", { icon: "bell", act: "inbox", label: "Open your work feed, 3 items", title: "Your work feed · Hold V + T", badge: 3 }), { kind: "icons" });

    if (bar.menuOpen) {
      views.push(bar.expanded("island", "island", h("lg-menu", { heading: "Workspace", detail: "Layout on" }, [
        state.agent === "working" && h("lg-live-row", { label: agentPhase }, [h("lg-spinner", { slot: "glyph", label: "Agent working" }), h("lg-button", { slot: "control", icon: "stop", act: "stop-agent", label: "Stop agent work" })]),
        state.recording && h("lg-live-row", { label: "Recording" }, [h("lg-dot", { slot: "glyph" }), h("lg-timer", { slot: "detail", since: recordingSince }), h("lg-button", { slot: "control", icon: "stop", act: "stop-recording", label: "Stop recording" })]),
        h("lg-menu-item", { icon: "canvas", act: "canvas" }, "Your work canvas"),
        h("lg-menu-item", { icon: "feed", act: "feed", key: "V T" }, "Your work feed"),
        h("lg-menu-item", { icon: "rec", act: "record" }, state.recording ? "Stop recording" : "Record a meeting"),
        h("lg-menu-separator"),
        h("lg-menu-item", { icon: "map", act: "close-menu" }, "Keyboard map"),
        h("lg-menu-item", { icon: "overlay", act: "close-menu" }, "Keyboard overlay"),
        h("lg-menu-item", { icon: "task", act: "close-menu", check: true }, "Windows taskbar"),
        h("lg-menu-separator"),
        h("lg-menu-item", { icon: "copy", act: "close-menu" }, "Copy latest transcript"),
        h("lg-menu-item", { icon: "tile", sub: "tiling" }, "Window tiling"),
        h("lg-menu-item", { icon: "gear", act: "close-menu" }, "Notification settings"),
      ]), 272, 21));
    } else if (dictating) {
      add("island", "island", html(h("lg-fact", { icon: "mic", filled: true, tone: "mic" }), h("lg-wave", { live: true }),
        bar.hover === "island" && h("lg-button", { icon: "stop", act: "stop-dictation", label: "Stop dictation" })));
    } else if (asking && bar.expandedQ) {
      views.push(bar.expanded("island", "island", h("lg-question", { heading: "Which sheet should the reply cover?", meta: "now" }, [
        badge("workspace", "medium"), h("span", { slot: "body" }, "Costs includes deferred licences; Revenue doesn't."),
        h("lg-button", { variant: "accent", act: "answer" }, "Revenue"), h("lg-button", { act: "answer" }, "Costs"), h("lg-button", { act: "canvas" }, "Open on canvas"),
      ]), 372, 28));
    } else if (asking) {
      add("island", "island", html(h("lg-fact", { strong: true }, "Needs you"), h("lg-fact", { quiet: true }, "Which sheet?"), h("lg-icon", { name: "chevdown" })), { tint: "attention" });
    } else {
      add("island", "island", html(
        spinner && h("lg-slot", {}, spinner),
        h("lg-slot", {}, [h("lg-fact", { num: true }, "10:22"), h("lg-fact", { icon: "battery", num: true }, "73%")]),
        state.recording && h("lg-slot", {}, recordingFacts())));
    }
    return views;
  };

  function expandQuestion() {
    desktop.expandedQ = true;
    clearTimeout(desktop.qTimer);
    // The question settles into its compact pill after a few seconds, unless the pointer rests on it.
    desktop.qTimer = setTimeout(function settle() {
      if (desktop.hover === "island") { desktop.qTimer = setTimeout(settle, 600); return; }
      desktop.expandedQ = false; desktop.render();
    }, 5000);
  }
  function setMenu(open) {
    if (desktop.menuOpen === open) return;
    desktop.menuOpen = open;
    if (!open) submenu.hide();
    desktop.render();
  }
  desktop.addEventListener("lg-action", ({ detail: { action, key, event } }) => {
    if (action === "press" && key === "island") {
      if (desktop.menuOpen) return;
      event.stopPropagation();
      if (state.moment === "dictating") return stopDictation();
      if (state.agent === "needs") { expandQuestion(); return desktop.render(); }
      return setMenu(true);
    }
    if (desktop.menuOpen) setMenu(false);
    switch (action) {
      case "canvas": return openCanvas();
      case "feed": case "inbox": return runAgent();
      case "record": state.recording = !state.recording; if (state.recording) recordingSince = Date.now(); break;
      case "answer": state.agent = "off"; phases.clear(); break;
      case "stop-agent": state.agent = "off"; break;
      case "stop-recording": state.recording = false; break;
      case "stop-dictation": return stopDictation();
      default: return;
    }
    sync();
  });
  function stopDictation() {
    state.moment = "transcribing"; sync();
    setTimeout(() => { if (state.moment === "transcribing") { state.moment = "none"; sync(); } }, 1600);
  }
  document.addEventListener("pointerdown", e => {
    if (desktop.menuOpen && !desktop.contains(e.target) && !e.target.closest("#submenu")) setMenu(false);
  });
  // Window tiling opens beside its menu item.
  const submenu = $("#submenu");
  submenu.addEventListener("click", e => { if (e.target.closest("[act]")) setMenu(false); });
  document.addEventListener("pointerover", e => {
    const item = e.target.closest("#bar lg-menu-item");
    if (!item) return;
    if (item.getAttribute("sub") === "tiling") submenu.showBeside(item); else submenu.hide();
  });

  /* ── Agent cards ─────────────────────────────────────────────────── */
  const phases = $("#phases");
  let run = 0;
  function phase({ who, heading, meta, steps = [], actions = [] }) {
    return phases.push(LG.fragment(h("lg-card", { variant: "glass", heading, time: "now" }, [
      badge(who), h("span", { slot: "body" }, meta),
      steps.length > 0 && h("lg-steps", {}, steps.map(s => h("lg-step", { state: "pending" }, s))),
      actions.length > 0 && h("lg-actions", { slot: "actions" }, actions.map(a => h("lg-button", { variant: a.primary ? "accent" : "filled", act: a.act }, a.label))),
    ])));
  }
  function playSteps(card, step = 650) {
    const steps = $$("lg-step", card);
    steps.forEach((s, i) => setTimeout(() => s.setAttribute("state", "running"), 120 * (i + 1)));
    steps.forEach((s, i) => setTimeout(() => s.setAttribute("state", "done"), step * (i + 1)));
    return step * (steps.length + 1);
  }
  function runAgent() {
    const token = ++run, later = (ms, fn) => setTimeout(() => token === run && fn(), ms);
    phases.clear();
    state.agent = "working"; sync();
    const first = phase({ who: "workspace", heading: "Reading Anna's request", meta: "Teams · Q4 budget review", steps: ["Read Teams conversation", "Find budget.xlsx in Outlook"] });
    later(playSteps(first), () => {
      const second = phase({ who: "excel", heading: "Comparing both sheets", meta: "budget.xlsx · Revenue and Costs", steps: ["Open budget.xlsx", "Compare totals across sheets"] });
      later(playSteps(second), () => {
        phase({ who: "workspace", heading: "Which sheet should Anna's reply cover?", meta: "Costs includes deferred licences; Revenue doesn't.",
          actions: [{ act: "answer", label: "Revenue", primary: true }, { act: "answer", label: "Costs" }, { act: "show", label: "Open on canvas" }] });
        state.agent = "needs"; sync();
      });
    });
  }
  phases.addEventListener("click", e => {
    const act = e.target.closest("[act]")?.getAttribute("act");
    if (!act) return;
    if (act === "show") { openCanvas(); select($("#c-question"), true); }
    phases.clear(); state.agent = "off"; sync();
  });

  /* ── Work canvas ─────────────────────────────────────────────────── */
  const win = $("#canvas"), scene = $("#scene"), world = $("#world"), inspector = $("#inspector");
  const groups = [
    { x: 120, y: 140, w: 740, h: 470, t: "Q4 budget review", s: "4 pieces" },
    { x: 940, y: 140, w: 380, h: 500, t: "Release 4.2", s: "3 pieces" },
  ];
  const cards = [
    { id: "c-work", g: 0, x: 40, y: 64, who: "workspace", t: "Q4 budget review", s: "Work context", extra: `<dl class="kv"><dt>Goal</dt><dd>Send Anna reviewed totals by Thursday</dd><dt>Now</dt><dd>Waiting for your sheet choice</dd><dt>Next</dt><dd>Draft the reply with both totals</dd></dl>` },
    { id: "c-teams", g: 0, x: 380, y: 64, who: "teams", t: "Anna Berg", s: "Teams · 9:41", body: "Can you review the budget totals before Thursday? Both sheets are in budget.xlsx." },
    { id: "c-doc", g: 0, x: 380, y: 230, who: "excel", t: "budget.xlsx", s: "SharePoint · edited 2 h ago", body: "Revenue €4.81M · Costs €3.07M. Costs includes deferred licences." },
    { id: "c-question", g: 0, x: 40, y: 250, who: "question", t: "Which sheet should the reply cover?", s: "Question · waiting for you", q: true, extra: `<div class="chips"><span class="chip primary">Revenue</span><span class="chip">Costs</span><span class="chip">Both</span></div>` },
    { id: "c-mail", g: 1, x: 40, y: 64, who: "outlook", t: "Release notes before Friday", s: "Outlook · Priya Shah", body: "The release review needs your comments on the changelog." },
    { id: "c-ticket", g: 1, x: 40, y: 210, who: "kanban", t: "REL-118 · Update changelog", s: "Kanban · In review", body: "Two items need wording from you." },
    { id: "c-note", g: 1, x: 40, y: 340, who: "note", t: "Draft reply ready", s: "Note from Workspace", body: "A short reply to Priya is ready for review." },
  ];
  const links = [["c-work", "c-teams"], ["c-teams", "c-doc"], ["c-doc", "c-question"], ["c-mail", "c-ticket"], ["c-ticket", "c-note"]];
  for (const g of groups) {
    const el = document.createElement("div"); el.className = "group";
    Object.assign(el.style, { left: `${g.x}px`, top: `${g.y}px`, width: `${g.w}px`, height: `${g.h}px` });
    el.innerHTML = `<div class="gtitle">${LG.escape(g.t)}<small>${LG.escape(g.s)}</small></div>`;
    world.append(el);
  }
  for (const c of cards) {
    // Canvas cards are content: the agent cards' anatomy on a solid surface.
    const el = LG.fragment(h("lg-card", { variant: "solid", id: c.id, class: c.q ? "question" : false, heading: c.t, meta: c.s }, [
      badge(c.who, "small"), c.body && h("span", { slot: "body" }, c.body), c.extra && LG.markup(c.extra),
    ]));
    world.append(el);
    c.el = el;
    c.x += groups[c.g].x; c.y += groups[c.g].y;
    c.sx = new Spring(c.x, v => { c.x = v; place(c); }, LG.motion.throw);
    c.sy = new Spring(c.y, v => { c.y = v; place(c); }, LG.motion.throw);
    place(c);
  }
  function place(c) { c.el.style.transform = `translate(${c.x}px, ${c.y}px)`; drawLinks(); }
  function drawLinks() {
    $("#links").innerHTML = links.map(([a, b]) => {
      const A = cards.find(c => c.id === a), B = cards.find(c => c.id === b);
      if (!A?.el?.offsetHeight || !B?.el?.offsetHeight) return "";
      const ah = A.el.offsetHeight, bh = B.el.offsetHeight, ax = A.x + 150, ay = A.y + ah / 2, bx = B.x + 150, by = B.y + bh / 2;
      if (Math.abs(bx - ax) > Math.abs(by - ay)) {
        const x1 = ax + 150 * Math.sign(bx - ax), x2 = bx - 150 * Math.sign(bx - ax), mx = (x1 + x2) / 2;
        return `<path d="M${x1} ${ay} C ${mx} ${ay}, ${mx} ${by}, ${x2} ${by}"/>`;
      }
      const y1 = ay + ah / 2 * Math.sign(by - ay), y2 = by - bh / 2 * Math.sign(by - ay), my = (y1 + y2) / 2;
      return `<path d="M${ax} ${y1} C ${ax} ${my}, ${bx} ${my}, ${bx} ${y2}"/>`;
    }).join("");
  }

  // Camera: pans follow 1:1, flings project momentum, edges rubber-band.
  const cam = { x: 0, y: 0, z: 1 };
  const camX = new Spring(0, v => { cam.x = v; applyCam(); }), camY = new Spring(0, v => { cam.y = v; applyCam(); });
  const restCam = () => ({ x: scene.clientWidth / 2 - 720 * cam.z, y: scene.clientHeight / 2 - 400 * cam.z });
  function applyCam() {
    world.style.transform = `translate(${cam.x}px, ${cam.y}px) scale(${cam.z})`;
    scene.style.backgroundSize = `${22 * cam.z}px ${22 * cam.z}px`;
    scene.style.backgroundPosition = `${cam.x}px ${cam.y}px`;
    // Recenter appears only once the view has left the work.
    const off = win.open && Math.hypot(cam.x - restCam().x, cam.y - restCam().y) > 120;
    if (off !== canvasBar.offCenter) { canvasBar.offCenter = off; canvasBar.render(); }
  }
  const bounds = () => ({ minX: scene.clientWidth - 1500 * cam.z, maxX: 160, minY: scene.clientHeight - 820 * cam.z, maxY: 120 });
  function centerCam(animated = true) { const r = restCam(); animated ? (camX.to(r.x), camY.to(r.y)) : (camX.set(r.x), camY.set(r.y)); }
  function pointerHistory() {
    const points = [];
    return {
      add(x, y) { const t = performance.now(); points.push({ x, y, t }); while (points.length > 1 && t - points[0].t > 100) points.shift(); },
      velocity() { if (points.length < 2) return { vx: 0, vy: 0 }; const a = points[0], b = points.at(-1), dt = Math.max(1, b.t - a.t) / 1000; return { vx: (b.x - a.x) / dt, vy: (b.y - a.y) / dt }; },
    };
  }
  let drag = null;
  scene.addEventListener("pointerdown", e => {
    if (e.button !== 0) return;
    scene.setPointerCapture(e.pointerId);
    const hist = pointerHistory(); hist.add(e.clientX, e.clientY);
    const card = cards.find(c => c.el === e.target.closest("lg-card"));
    if (card) { card.sx.set(card.x); card.sy.set(card.y); drag = { card, hist, sx: e.clientX, sy: e.clientY, ox: card.x, oy: card.y, moved: false }; }
    else { camX.set(cam.x); camY.set(cam.y); drag = { hist, sx: e.clientX, sy: e.clientY, ox: cam.x, oy: cam.y, moved: false }; }
  });
  scene.addEventListener("pointermove", e => {
    if (!drag) return;
    const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
    drag.hist.add(e.clientX, e.clientY);
    if (!drag.moved && Math.hypot(dx, dy) < 4) return;
    drag.moved = true;
    if (drag.card) { drag.card.el.classList.add("dragging"); drag.card.x = drag.ox + dx / cam.z; drag.card.y = drag.oy + dy / cam.z; place(drag.card); return; }
    scene.classList.add("panning");
    const b = bounds();
    let x = drag.ox + dx, y = drag.oy + dy;
    if (x > b.maxX) x = b.maxX + LG.rubberband(x - b.maxX, scene.clientWidth); if (x < b.minX) x = b.minX - LG.rubberband(b.minX - x, scene.clientWidth);
    if (y > b.maxY) y = b.maxY + LG.rubberband(y - b.maxY, scene.clientHeight); if (y < b.minY) y = b.minY - LG.rubberband(b.minY - y, scene.clientHeight);
    cam.x = x; cam.y = y; applyCam();
  });
  scene.addEventListener("pointerup", () => {
    if (!drag) return;
    const { vx, vy } = drag.hist.velocity();
    if (drag.card) {
      const c = drag.card; c.el.classList.remove("dragging");
      if (!drag.moved) select(c.el);
      else {
        // A thrown card carries a short glide and a little bounce, because momentum preceded it.
        c.sx.value = c.x; c.sy.value = c.y;
        c.sx.to(c.x + LG.project(vx / cam.z, 0.99), { velocity: vx / cam.z });
        c.sy.to(c.y + LG.project(vy / cam.z, 0.99), { velocity: vy / cam.z });
      }
    } else {
      scene.classList.remove("panning");
      if (!drag.moved) select(null);
      const b = bounds();
      camX.value = cam.x; camY.value = cam.y;
      camX.to(clamp(cam.x + LG.project(vx), b.minX, b.maxX), { velocity: vx, damping: 1, response: 0.55 });
      camY.to(clamp(cam.y + LG.project(vy), b.minY, b.maxY), { velocity: vy, damping: 1, response: 0.55 });
    }
    drag = null;
  });
  scene.addEventListener("wheel", e => {
    e.preventDefault();
    if (e.ctrlKey) {
      const r = scene.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
      const z = clamp(cam.z * Math.exp(-e.deltaY * 0.0025), 0.4, 1.8), k = z / cam.z;
      camX.set(mx - (mx - cam.x) * k); camY.set(my - (my - cam.y) * k); cam.z = z; applyCam();
    } else { camX.set(cam.x - e.deltaX); camY.set(cam.y - e.deltaY); }
  }, { passive: false });

  /* Canvas bar: the desktop bar's rule at the window's bottom edge. At rest the island
     holds three symbols (speak, search, more) and their tooltips carry the instructions.
     Transcription and agent work take its leading slot; only temporary things sit beside it. */
  const canvasBar = $("#cbar");
  Object.assign(canvasBar, { mode: "rest", query: "", working: false, transcribing: false, offCenter: false });
  let selected = null;
  const scope = () => selected ? cards.find(c => c.el === selected).t : "the whole canvas";
  canvasBar.view = bar => {
    const views = [], add = (zone, key, content, more = {}) => views.push({ zone, key, content, kind: "icons", ...more });
    if (bar.offCenter && bar.mode === "rest") add("lead", "recenter", h("lg-button", { icon: "center", act: "center", label: "Recenter" }));
    if (bar.mode === "menu") {
      views.push(bar.expanded("island", "island", h("lg-menu", { heading: "Work canvas", detail: "7 contexts" }, [
        h("lg-menu-item", { icon: "search", act: "search", key: "Ctrl F" }, "Search"),
        h("lg-menu-item", { icon: "center", act: "center" }, "Center"),
        h("lg-menu-item", { icon: "canvas", act: "close-menu" }, "Arrange"),
        h("lg-menu-separator"),
        h("lg-menu-item", { icon: "spark", act: "close-menu" }, "New work context"),
        h("lg-menu-item", { icon: "copy", act: "close-menu" }, "New note"),
        h("lg-menu-item", { icon: "edge", act: "close-menu" }, "Connect a source"),
        h("lg-menu-separator"),
        h("lg-menu-item", { icon: "tile", act: "close-menu" }, "Collapse groups"),
        h("lg-menu-item", { icon: "gear", act: "close-menu" }, "Agent tasks and settings"),
        h("lg-menu-item", { icon: "x", act: "close" }, "Close canvas"),
      ]), 272, 21));
    } else if (bar.mode === "search") {
      add("island", "island", h("lg-field", { icon: "search", placeholder: "Search the canvas", value: bar.query }), { kind: "text", width: 300 });
    } else if (bar.mode === "voice") {
      add("island", "island", html(h("lg-fact", { icon: "mic", filled: true, tone: "mic" }), h("lg-wave", { live: true }), h("lg-button", { icon: "stop", act: "send", label: "Send" })), { kind: "text" });
    } else {
      const labels = [bar.transcribing && "Transcribing", bar.working && "Agent working"].filter(Boolean);
      add("island", "island", html(
        labels.length > 0 && h("lg-slot", {}, h("lg-spinner", { label: labels.join(" · ") })),
        h("lg-button", { icon: "mic", act: "speak", label: `Speak about ${scope()}`, title: `Hold N to speak about ${scope()}` }),
        h("lg-button", { icon: "search", act: "search", label: "Search", title: "Search · Ctrl F" }),
        h("lg-button", { icon: "more", act: "menu", label: "Canvas options" })));
    }
    add("trail", "questions", h("lg-button", { icon: "q", act: "questions", label: "2 questions waiting" }, "2"), { tint: "attention" });
    return views;
  };
  function setMode(mode) {
    canvasBar.mode = mode;
    if (mode !== "search") { canvasBar.query = ""; cards.forEach(c => c.el.classList.remove("dim")); }
    canvasBar.render();
    if (mode === "search") requestAnimationFrame(() => canvasBar.content("island")?.querySelector("lg-field")?.focus());
  }
  canvasBar.addEventListener("lg-action", ({ detail: { action, event } }) => {
    if (canvasBar.mode === "menu" && action !== "press") setMode("rest");
    switch (action) {
      case "menu": event.stopPropagation(); return setMode("menu");
      case "search": return setMode("search");
      case "speak": return canvasBar.mode === "voice" ? send() : setMode("voice");
      case "send": return send();
      case "center": return centerCam();
      case "questions": return select($("#c-question"), true);
      case "close": win.open = false; return select(null);
    }
  });
  // Releasing the microphone transcribes in the island's leading slot; agent work continues there.
  function send() {
    canvasBar.transcribing = true; setMode("rest");
    setTimeout(() => {
      canvasBar.transcribing = false; canvasBar.working = true; canvasBar.render();
      setTimeout(() => { canvasBar.working = false; canvasBar.render(); }, 4000);
    }, 1300);
  }
  canvasBar.addEventListener("input", e => {
    canvasBar.query = e.target.value;
    const q = e.target.value.trim().toLowerCase();
    cards.forEach(c => c.el.classList.toggle("dim", !!q && !(c.t + c.s).toLowerCase().includes(q)));
  });
  document.addEventListener("pointerdown", e => { if (canvasBar.mode === "menu" && !canvasBar.contains(e.target)) setMode("rest"); });
  // Holding N speaks; releasing sends.
  addEventListener("keydown", e => {
    if (!win.open || e.repeat || e.key.toLowerCase() !== "n" || e.target.matches("input")) return;
    setMode("voice");
  });
  addEventListener("keyup", e => { if (win.open && e.key.toLowerCase() === "n" && canvasBar.mode === "voice") send(); });

  function openCanvas() {
    setMenu(false);
    if (win.open) return;
    win.open = true;
    panel.open = false;
    canvasBar.refresh(); setMode("rest"); centerCam(false); drawLinks();
  }
  win.addEventListener("close", () => select(null));

  /* Inspector: details for the selected card, with its actions at the top. */
  const notes = ["Anna prefers totals rounded to thousands.", "Thursday's sign-off moved to 14:00.", "Costs tab added deferred licences on Monday.", "Last quarter's reply used the Revenue sheet.", "Priya reviews the same figures for the board pack.", "The Contoso renewal date is still open."];
  function select(el, center = false) {
    if (selected) selected.classList.remove("selected");
    selected = el;
    if (win.open) canvasBar.render();
    if (!el) { inspector.open = false; return; }
    el.classList.add("selected");
    const c = cards.find(k => k.el === el);
    inspector.content = html(
      h("lg-app", { ...apps[c.who] }), h("h2", {}, c.t), h("div", { class: "lg-sub" }, c.s),
      h("lg-actions", { class: "lg-actions" }, [h("lg-button", { variant: "accent", size: "large", icon: "spark" }, "Ask about this"), h("lg-button", { variant: "filled", size: "large", icon: "edge" }, "Open in Edge")]),
      h("h3", {}, "Current situation"), h("div", { class: "lg-well" }, c.q ? "Workspace compared both sheets. Costs includes deferred licences; Revenue doesn't. Anna asked for reviewed totals." : "Anna needs reviewed totals before Thursday's sign-off. Both sheets are in budget.xlsx."),
      h("h3", {}, "Next step"), h("div", { class: "lg-well" }, c.q ? "Choose a sheet so Workspace can draft the reply." : "Draft a short reply with both totals for your review."),
      h("h3", {}, "Connected"),
      h("div", { class: "src" }, [h("lg-app", { ...apps.teams, size: "small" }), h("div", {}, [h("div", {}, "Anna Berg"), h("div", { class: "lg-sub" }, "Teams · asked for the review")])]),
      h("div", { class: "src" }, [h("lg-app", { ...apps.excel, size: "small" }), h("div", {}, [h("div", {}, "budget.xlsx"), h("div", { class: "lg-sub" }, "Evidence for both totals")])]),
      h("h3", {}, "Notes"), notes.concat(notes).map(n => h("div", { class: "note" }, n)));
    inspector.open = true;
    if (center) { const W = scene.clientWidth - 360, H = scene.clientHeight; camX.to(W / 2 - (c.x + 150) * cam.z); camY.to(H / 2 - (c.y + el.offsetHeight / 2) * cam.z); }
  }
  inspector.addEventListener("close", () => select(null));

  addEventListener("keydown", e => {
    if (e.key === "Escape") {
      if (desktop.menuOpen) return setMenu(false);
      if (win.open && canvasBar.mode !== "rest") return setMode("rest");
      if (selected) return select(null);
      if (win.open) { win.open = false; return select(null); }
    }
    if (e.key === "f" && e.ctrlKey && win.open) { e.preventDefault(); setMode("search"); }
  });

  /* ── Study controls ──────────────────────────────────────────────── */
  const panel = $("#panel");
  panel.addEventListener("change", e => {
    const key = e.target.dataset.key;
    if (!key) return;
    state[key] = e.target.tagName === "LG-SWITCH" ? e.target.checked : e.target.value;
    if (key === "agent") phases.clear();
    if (key === "recording" && state.recording) recordingSince = Date.now();
    sync();
  });
  $("#runAgent").addEventListener("click", runAgent);
  $("#openCanvas").addEventListener("click", () => { if (win.open) { win.open = false; select(null); } else openCanvas(); });

  /* Small glass reads the content beneath it; everything large follows the appearance. */
  function sync() {
    body.dataset.wallpaper = state.wallpaper;
    body.dataset.appearance = state.appearance;
    for (const el of [panel, phases, win, submenu]) LG.scheme(el, state.appearance);
    LG.scheme(desktop, state.wallpaper === "vivid" ? state.appearance : state.wallpaper);
    for (const el of $$("[data-key]", panel)) {
      const value = state[el.dataset.key];
      if (el.tagName === "LG-SWITCH") { if (el.checked !== value) el.checked = value; }
      else if (el.value !== value) el.value = value;
    }
    desktop.render();
    if (win.open) canvasBar.render();
  }

  /* ── Start ──────────────────────────────────────────────────────── */
  sync();
  // Widths depend on the typeface: re-measure once it has loaded.
  document.fonts.ready.then(() => { desktop.refresh(); if (win.open) canvasBar.refresh(); });
  requestAnimationFrame(() => {
    if (params.has("canvas")) openCanvas();
    if (params.has("menu")) setMenu(true);
    if (params.has("run")) runAgent();
    if (params.has("select")) setTimeout(() => select($(`#${params.get("select")}`)), 50);
    if (params.get("sidebar") === "0") panel.open = false;
  });
  // For tests and measurement.
  window.workspaceDemo = { state, sync, desktop, canvasBar, openCanvas, select, setMenu, startRecording: since => { recordingSince = since; sync(); } };
})();
