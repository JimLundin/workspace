/* Workspace in Liquid Glass: the desktop island bar, agent bubbles and the work canvas,
   built on the kit. Everything Workspace-specific lives here; the kit stays generic. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { $, $$, clamp, Spring, ui, icon } = LG;
  const body = document.body;

  const state = { moment: "none", agent: "off", recording: false, layer: false, inbox: true, wallpaper: "vivid", appearance: "dark" };
  const params = new URLSearchParams(location.search);
  for (const key of ["moment", "agent", "wallpaper", "appearance"]) if (params.has(key)) state[key] = params.get(key);
  for (const key of ["recording", "layer", "inbox"]) if (params.has(key)) state[key] = params.get(key) === "1";
  if (!params.has("appearance")) state.appearance = matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";

  const app = {
    workspace: { glyph: "✦", color: "linear-gradient(145deg,#7d6bff,#4b9dff)" },
    teams: { glyph: "T", color: "linear-gradient(145deg,#7b83eb,#4f52b2)" },
    outlook: { glyph: "O", color: "linear-gradient(145deg,#28a8ea,#0c64c4)" },
    kanban: { glyph: "K", color: "linear-gradient(145deg,#ffb340,#e08600)" },
    excel: { glyph: "X", color: "linear-gradient(145deg,#33c481,#107c41)" },
    note: { glyph: "✎", color: "linear-gradient(145deg,#ffd60a,#f2b705)" },
    question: { glyph: "?", color: "linear-gradient(145deg,#7d6bff,#4b9dff)" },
  };
  const badge = (name, small = false) => ui.app({ ...app[name], small });

  /* ── Live readings: recording clock and audio meter ───────────────── */
  let seconds = 125;
  const clock = total => {
    const h = total / 3600 | 0, m = (total / 60 | 0) % 60, s = String(total % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${String(m).padStart(2, "0")}:${s}`;
  };
  // Markup carries zeroed digits so a capsule keeps its identity; the timer writes the live value in place.
  const clockFact = () => `<span class="lg-fact lg-num" data-live="clock">${clock(seconds).replace(/\d/g, "0")}</span>`;
  const writeClocks = () => $$('[data-live="clock"]').forEach(el => { el.textContent = clock(seconds); });
  setInterval(() => {
    const before = clock(seconds).length;
    seconds++;
    // A longer reading needs a wider capsule; same-length readings update in place.
    if (clock(seconds).length !== before) renderBars(); else writeClocks();
  }, 1000);
  let phase = 0;
  (function meter() {
    phase += 0.16;
    $$('[data-live="audio"]').forEach(wave => [...wave.children].forEach((bar, i) => {
      const envelope = 0.35 + 0.65 * Math.abs(Math.sin(phase * 0.7 + i * 0.22));
      bar.style.height = `${3 + 12 * envelope * Math.abs(Math.sin(phase * 2.3 + i * 0.9) * Math.cos(phase * 0.9 + i * 0.3))}px`;
    }));
    setTimeout(meter, 60);
  })();

  /* ── Desktop bar ─────────────────────────────────────────────────────
     At rest the island shows the time and battery. Ongoing work joins the island's
     own leading and trailing slots (agent, recording), so it grows the centre.
     A moment (dictation, a question, the menu) takes the island over; ongoing work
     then detaches beside it. The inbox appears only while items wait. */
  const desktop = new LG.IslandBar($("#bar"), {
    order: ["layer", "agent", "island", "recording", "inbox"],
    view: desktopView,
    onAction: desktopAction,
  });
  Object.assign(desktop, { menuOpen: false, expandedQ: false, prevAgent: "off" });

  const agentLabel = "Comparing sheets";
  function desktopView(bar) {
    const views = [];
    const add = (zone, key, html, o = {}) => views.push({ zone, key, html, kind: "lg-text", ...o });
    const dictating = state.moment === "dictating", transcribing = state.moment === "transcribing";
    const asking = state.agent === "needs", working = state.agent === "working";
    if (asking && bar.prevAgent !== "needs") expandQuestion(bar);
    if (!asking) bar.expandedQ = false;
    bar.prevAgent = state.agent;
    const resting = !bar.menuOpen && state.moment === "none" && !asking;

    if (state.layer) add("lead", "layer", ui.fact("NAV", { icon: "kbd" }));
    if (!resting && !bar.menuOpen && working) add("lead", "agent", ui.spinner("Agent working"), { kind: "lg-min" });
    if (!resting && !bar.menuOpen && state.recording) add("trail", "recording", ui.dot() + clockFact());
    if (state.inbox) add("trail", "inbox", ui.button({ act: "inbox", icon: "bell", label: "Open your work feed, 3 items", title: "Your work feed · Hold V + T", badge: 3 }), { kind: "" });

    const expanded = (html, cls, width, radius) => add("island", "island", html, { kind: `lg-expanded ${cls}`, width, height: bar.measure("island", html, `lg-expanded ${cls}`, width).height, radius });
    if (bar.menuOpen) {
      const now = [];
      if (working) now.push(ui.nowRow({ glyph: ui.spinner("Agent working"), label: agentLabel, control: ui.stop("Stop agent work", "stop-agent") }));
      if (state.recording) now.push(ui.nowRow({ glyph: ui.dot(), label: "Recording", detail: clock(seconds), control: ui.stop("Stop recording", "stop-recording") }));
      expanded(ui.menu({ title: "Workspace", detail: "Layout on", now, items: [
        { act: "canvas", icon: "canvas", label: "Your work canvas" },
        { act: "feed", icon: "feed", label: "Your work feed", key: "V T" },
        { act: "record", icon: "rec", label: state.recording ? "Stop recording" : "Record a meeting" },
        "-",
        { act: "close-menu", icon: "map", label: "Keyboard map" },
        { act: "close-menu", icon: "overlay", label: "Keyboard overlay" },
        { act: "close-menu", icon: "task", label: "Windows taskbar", check: true },
        "-",
        { act: "close-menu", icon: "copy", label: "Copy latest transcript" },
        { sub: "tiling", icon: "tile", label: "Window tiling" },
        { act: "close-menu", icon: "gear", label: "Notification settings" },
      ] }), "", 272, 21);
    } else if (dictating) {
      add("island", "island", `<span class="lg-fact lg-mic">${icon("mic", { filled: true })}</span>${ui.wave()}${bar.hover === "island" ? ui.stop("Stop dictation", "stop-dictation") : ""}`);
    } else if (transcribing) {
      add("island", "island", ui.spinner("Transcribing"), { kind: "lg-min" });
    } else if (asking && bar.expandedQ) {
      expanded(ui.question({ badge: badge("workspace"), title: "Which sheet should the reply cover?", meta: "now", body: "Costs includes deferred licences; Revenue doesn't.",
        actions: [{ act: "answer", label: "Revenue", primary: true }, { act: "answer", label: "Costs" }, { act: "canvas", label: "Open on canvas" }] }), "", 372, 28);
    } else if (asking) {
      add("island", "island", `<span class="lg-fact" style="font-weight:600">Needs you</span><span class="lg-fact lg-quiet">Which sheet?</span>${icon("chevdown")}`, { tint: "lg-tint" });
    } else {
      const facts = ui.fact("10:22", { num: true }) + ui.fact("73%", { icon: "battery", num: true });
      add("island", "island", (working ? ui.slot(ui.spinner(`Agent working: ${agentLabel}`)) : "") + ui.slot(facts) + (state.recording ? ui.slot(ui.dot() + clockFact()) : ""));
    }
    return views;
  }

  function expandQuestion(bar) {
    bar.expandedQ = true;
    clearTimeout(bar.qTimer);
    // The question settles into its compact pill after a few seconds, unless the pointer rests on it.
    bar.qTimer = setTimeout(function settle() {
      if (bar.hover === "island") { bar.qTimer = setTimeout(settle, 600); return; }
      bar.expandedQ = false; bar.render();
    }, 5000);
  }

  function setMenu(open) {
    if (desktop.menuOpen === open) return;
    desktop.menuOpen = open;
    if (!open) $("#submenu").style.display = "none";
    desktop.render();
  }

  function desktopAction(action, { key, event }) {
    if (action === "press" && key === "island") {
      if (desktop.menuOpen) return;
      event.stopPropagation();
      if (state.moment === "dictating") return stopDictation();
      if (state.agent === "needs") { expandQuestion(desktop); return desktop.render(); }
      if (state.moment === "none") return setMenu(true);
      return;
    }
    if (desktop.menuOpen) setMenu(false);
    switch (action) {
      case "canvas": return openCanvas();
      case "feed": case "inbox": return runAgent();
      case "record": state.recording = !state.recording; break;
      case "answer": state.agent = "off"; bubbles.clear(); break;
      case "stop-agent": state.agent = "off"; break;
      case "stop-recording": state.recording = false; break;
      case "stop-dictation": return stopDictation();
      default: return;
    }
    sync();
  }
  function stopDictation() {
    state.moment = "transcribing"; sync();
    setTimeout(() => { if (state.moment === "transcribing") { state.moment = "none"; sync(); } }, 1600);
  }

  document.addEventListener("pointerdown", e => {
    if (desktop.menuOpen && !desktop.root.contains(e.target) && !e.target.closest("#submenu")) setMenu(false);
  });
  // Window tiling opens beside its menu item, as a submenu.
  const submenu = $("#submenu");
  LG.glass(submenu, { large: true });
  submenu.innerHTML = ui.menu({ items: [
    { act: "close-menu", label: "Spread windows across screens" }, "-",
    { act: "close-menu", label: "Focus left", key: "Alt ←" }, { act: "close-menu", label: "Focus right", key: "Alt →" },
    { act: "close-menu", label: "Float or tile the active window" }, { act: "close-menu", label: "Change split direction" },
    { act: "close-menu", label: "Pause automatic tiling" },
  ] });
  submenu.addEventListener("click", e => { if (e.target.closest("[data-act]")) setMenu(false); });
  document.addEventListener("pointerover", e => {
    const item = e.target.closest("#bar .lg-item");
    if (!item) return;
    if (item.dataset.sub !== "tiling") { submenu.style.display = "none"; return; }
    const box = item.getBoundingClientRect();
    Object.assign(submenu.style, { display: "block", left: `${box.right + 12}px`, top: `${box.top - 6}px` });
  });

  /* ── Agent bubbles ───────────────────────────────────────────────── */
  const bubbles = new LG.BubbleStack($("#phases"), { limit: 3 });
  let run = 0;
  function bubble({ who, title, meta = "now", body: text = "", calls = [], actions = [] }) {
    const html = ui.head({ app: badge(who), title, meta: "", body: text, trailing: `<span class="lg-meta">${meta}</span>` })
      + (calls.length ? `<div class="lg-calls">${calls.map(c => `<div class="lg-call lg-pending">${ui.spinner(c)}<span>${LG.escape(c)}</span></div>`).join("")}</div>` : "")
      + (actions.length ? `<div class="lg-actions">${actions.map(a => `<button class="lg-pill ${a.primary ? "lg-accent" : "lg-filled"}" data-act="${a.act}">${LG.escape(a.label)}</button>`).join("")}</div>` : "");
    return bubbles.push(html);
  }
  function finishCalls(el, step = 650) {
    const calls = $$(".lg-call", el);
    calls.forEach((c, i) => setTimeout(() => c.classList.remove("lg-pending"), 120 * (i + 1)));
    calls.forEach((c, i) => setTimeout(() => { $(".lg-spinner", c).outerHTML = `<span class="lg-ok">${icon("checkc")}</span>`; }, step * (i + 1)));
    return step * (calls.length + 1);
  }
  function runAgent() {
    const token = ++run, later = (ms, fn) => setTimeout(() => token === run && fn(), ms);
    bubbles.clear();
    state.agent = "working"; sync();
    const first = bubble({ who: "workspace", title: "Reading Anna's request", body: "Teams · Q4 budget review", calls: ["Read Teams conversation", "Find budget.xlsx in Outlook"] });
    later(finishCalls(first), () => {
      const second = bubble({ who: "excel", title: "Comparing both sheets", body: "budget.xlsx · Revenue and Costs", calls: ["Open budget.xlsx", "Compare totals across sheets"] });
      later(finishCalls(second), () => {
        bubble({ who: "workspace", title: "Which sheet should Anna's reply cover?", body: "Costs includes deferred licences; Revenue doesn't.",
          actions: [{ act: "answer", label: "Revenue", primary: true }, { act: "answer", label: "Costs" }, { act: "show", label: "Open on canvas" }] });
        state.agent = "needs"; sync();
      });
    });
  }
  $("#phases").addEventListener("click", e => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (!act) return;
    if (act === "show") { openCanvas(); select($("#c-question"), true); }
    bubbles.clear(); state.agent = "off"; sync();
  });

  /* ── Work canvas ─────────────────────────────────────────────────── */
  const win = $("#canvas"), scene = $("#scene"), world = $("#world");
  const groups = [
    { x: 120, y: 140, w: 740, h: 470, t: "Q4 budget review", s: "4 pieces" },
    { x: 940, y: 140, w: 380, h: 500, t: "Release 4.2", s: "3 pieces" },
  ];
  const cards = [
    { id: "c-work", g: 0, x: 40, y: 64, who: "workspace", t: "Q4 budget review", s: "Work context", html: `<dl class="kv"><dt>Goal</dt><dd>Send Anna reviewed totals by Thursday</dd><dt>Now</dt><dd>Waiting for your sheet choice</dd><dt>Next</dt><dd>Draft the reply with both totals</dd></dl>` },
    { id: "c-teams", g: 0, x: 380, y: 64, who: "teams", t: "Anna Berg", s: "Teams · 9:41", body: "Can you review the budget totals before Thursday? Both sheets are in budget.xlsx." },
    { id: "c-doc", g: 0, x: 380, y: 230, who: "excel", t: "budget.xlsx", s: "SharePoint · edited 2 h ago", body: "Revenue €4.81M · Costs €3.07M. Costs includes deferred licences." },
    { id: "c-question", g: 0, x: 40, y: 250, who: "question", t: "Which sheet should the reply cover?", s: "Question · waiting for you", q: true, html: `<div class="chips"><span class="chip primary">Revenue</span><span class="chip">Costs</span><span class="chip">Both</span></div>` },
    { id: "c-mail", g: 1, x: 40, y: 64, who: "outlook", t: "Release notes before Friday", s: "Outlook · Priya Shah", body: "The release review needs your comments on the changelog." },
    { id: "c-ticket", g: 1, x: 40, y: 210, who: "kanban", t: "REL-118 · Update changelog", s: "Kanban · In review", body: "Two items need wording from you." },
    { id: "c-note", g: 1, x: 40, y: 340, who: "note", t: "Draft reply ready", s: "Note from Workspace", body: "A short reply to Priya is ready for review." },
  ];
  const links = [["c-work", "c-teams"], ["c-teams", "c-doc"], ["c-doc", "c-question"], ["c-mail", "c-ticket"], ["c-ticket", "c-note"]];
  for (const g of groups) {
    const el = document.createElement("div"); el.className = "group";
    Object.assign(el.style, { left: `${g.x}px`, top: `${g.y}px`, width: `${g.w}px`, height: `${g.h}px` });
    el.innerHTML = `<div class="gtitle">${g.t}<small>${g.s}</small></div>`;
    world.append(el);
  }
  for (const c of cards) {
    // Canvas cards are content: the bubbles' anatomy on a solid surface.
    const el = document.createElement("div"); el.className = `lg-card${c.q ? " question" : ""}`; el.id = c.id;
    c.x += groups[c.g].x; c.y += groups[c.g].y;
    el.innerHTML = ui.head({ app: badge(c.who, true), title: c.t, meta: c.s, body: c.body || "" }) + (c.html || "");
    world.append(el); c.el = el;
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
    const off = canvasOpen && Math.hypot(cam.x - restCam().x, cam.y - restCam().y) > 120;
    if (off !== canvasBar.offCenter) { canvasBar.offCenter = off; canvasBar.render(); }
  }
  const bounds = () => ({ minX: scene.clientWidth - 1500 * cam.z, maxX: 160, minY: scene.clientHeight - 820 * cam.z, maxY: 120 });
  function centerCam(animated = true) { const r = restCam(); animated ? (camX.to(r.x), camY.to(r.y)) : (camX.set(r.x), camY.set(r.y)); }
  function history() {
    const h = [];
    return {
      add(x, y) { const t = performance.now(); h.push({ x, y, t }); while (h.length > 1 && t - h[0].t > 100) h.shift(); },
      velocity() { if (h.length < 2) return { vx: 0, vy: 0 }; const a = h[0], b = h.at(-1), dt = Math.max(1, b.t - a.t) / 1000; return { vx: (b.x - a.x) / dt, vy: (b.y - a.y) / dt }; },
    };
  }
  let drag = null;
  scene.addEventListener("pointerdown", e => {
    if (e.button !== 0) return;
    scene.setPointerCapture(e.pointerId);
    const hist = history(); hist.add(e.clientX, e.clientY);
    const card = cards.find(c => c.el === e.target.closest(".lg-card"));
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

  /* Canvas bar: the desktop bar's rule at the window's bottom edge.
     At rest the island holds three symbols (speak, search, more), no instructions:
     their tooltips carry them. A moment morphs the island; only temporary things sit beside it. */
  const canvasBar = new LG.IslandBar($("#cbar"), {
    edge: "bottom",
    order: ["recenter", "island", "questions"],
    view: canvasView,
    onAction: canvasAction,
  });
  Object.assign(canvasBar, { mode: "rest", query: "", working: false, offCenter: false });
  const scope = () => selected ? cards.find(c => c.el === selected).t : "the whole canvas";
  function canvasView(bar) {
    const views = [], add = (zone, key, html, o = {}) => views.push({ zone, key, html, kind: "", ...o });
    if (bar.offCenter && bar.mode === "rest") add("lead", "recenter", ui.button({ act: "center", icon: "center", label: "Recenter" }));
    switch (bar.mode) {
      case "menu": {
        const html = ui.menu({ title: "Work canvas", detail: "7 contexts", items: [
          { act: "search", icon: "search", label: "Search", key: "Ctrl F" }, { act: "center", icon: "center", label: "Center" }, { act: "close-menu", icon: "canvas", label: "Arrange" }, "-",
          { act: "close-menu", icon: "spark", label: "New work context" }, { act: "close-menu", icon: "copy", label: "New note" }, { act: "close-menu", icon: "edge", label: "Connect a source" }, "-",
          { act: "close-menu", icon: "tile", label: "Collapse groups" }, { act: "close-menu", icon: "gear", label: "Agent tasks and settings" }, { act: "close", icon: "x", label: "Close canvas" },
        ] });
        add("island", "island", html, { kind: "lg-expanded", width: 272, height: bar.measure("island", html, "lg-expanded", 272).height, radius: 21 });
        break;
      }
      case "search":
        add("island", "island", `<span class="lg-fact lg-quiet" style="padding-left:9px">${icon("search")}</span><input class="lg-field" placeholder="Search the canvas" aria-label="Search the canvas" value="${LG.escape(bar.query)}"><span style="width:12px"></span>`, { width: 300 });
        break;
      case "voice":
        add("island", "island", `<span class="lg-fact lg-mic" style="padding-left:9px">${icon("mic", { filled: true })}</span>${ui.wave()}${ui.stop("Send", "send")}`, { kind: "lg-text" });
        break;
      case "transcribing":
        add("island", "island", ui.spinner("Transcribing"), { kind: "lg-min" });
        break;
      default:
        add("island", "island", (bar.working ? ui.slot(`<span style="padding:0 4px 0 7px;display:inline-flex">${ui.spinner("Agent working")}</span>`) : "")
          + ui.button({ act: "speak", icon: "mic", label: `Speak about ${scope()}`, title: `Hold N to speak about ${scope()}` })
          + ui.button({ act: "search", icon: "search", label: "Search", title: "Search · Ctrl F" })
          + ui.button({ act: "menu", icon: "more", label: "Canvas options" }));
    }
    add("trail", "questions", ui.button({ act: "questions", icon: "q", label: "2 questions waiting", text: "2" }), { tint: "lg-tint" });
    return views;
  }
  function setMode(mode) {
    canvasBar.mode = mode;
    if (mode !== "search") { canvasBar.query = ""; cards.forEach(c => c.el.classList.remove("dim")); }
    canvasBar.render();
    if (mode === "search") requestAnimationFrame(() => canvasBar.contentOf("island")?.querySelector(".lg-field")?.focus());
  }
  function canvasAction(action, { event }) {
    if (canvasBar.mode === "menu" && action !== "press") setMode("rest");
    switch (action) {
      case "menu": event.stopPropagation(); return setMode("menu");
      case "search": return setMode("search");
      case "speak": return canvasBar.mode === "voice" ? send() : setMode("voice");
      case "send": return send();
      case "center": return centerCam();
      case "questions": return select($("#c-question"), true);
      case "close": return closeCanvas();
    }
  }
  function send() {
    setMode("transcribing");
    setTimeout(() => {
      canvasBar.working = true; setMode("rest");
      setTimeout(() => { canvasBar.working = false; canvasBar.render(); }, 4000);
    }, 1300);
  }
  $("#cbar").addEventListener("input", e => {
    if (!e.target.matches(".lg-field")) return;
    canvasBar.query = e.target.value;
    const q = e.target.value.trim().toLowerCase();
    cards.forEach(c => c.el.classList.toggle("dim", !!q && !(c.t + c.s).toLowerCase().includes(q)));
  });
  document.addEventListener("pointerdown", e => { if (canvasBar.mode === "menu" && !canvasBar.root.contains(e.target)) setMode("rest"); });
  // Holding N speaks; releasing sends.
  addEventListener("keydown", e => {
    if (!canvasOpen || e.repeat || e.key.toLowerCase() !== "n" || e.target.matches("input")) return;
    setMode("voice");
  });
  addEventListener("keyup", e => { if (canvasOpen && e.key.toLowerCase() === "n" && canvasBar.mode === "voice") send(); });

  let canvasOpen = false;
  const winSpring = new Spring(0, p => {
    win.style.opacity = clamp(p * 1.5, 0, 1);
    win.style.transform = `translateX(-50%) translateY(${(1 - p) * -24}px) scale(${0.9 + 0.1 * p})`;
  }, { damping: 0.9, response: 0.42 });
  function openCanvas() {
    setMenu(false);
    if (canvasOpen) return;
    canvasOpen = true; win.style.display = "block";
    $("#panel").open = false;
    canvasBar.refresh(); setMode("rest"); centerCam(false); drawLinks();
    winSpring.to(1);
  }
  function closeCanvas() {
    if (!canvasOpen) return;
    canvasOpen = false; select(null);
    winSpring.to(0, { damping: 1, response: 0.3, done: () => { if (!canvasOpen) win.style.display = "none"; } });
  }
  $("#closeLight").addEventListener("click", closeCanvas);

  /* Inspector: slides in from the trailing edge and leaves the same way; actions sit at the top. */
  const inspector = $("#inspector");
  LG.glass(inspector, { large: true });
  const inspectorSpring = new Spring(0, p => { inspector.style.transform = `translateX(${(1 - p) * 360}px)`; inspector.style.opacity = clamp(p * 2, 0, 1); }, { damping: 0.9, response: 0.4 });
  let selected = null;
  function select(el, center = false) {
    if (selected) selected.classList.remove("selected");
    selected = el;
    win.classList.toggle("inspecting", !!el);
    if (canvasOpen) canvasBar.render();
    if (!el) { inspectorSpring.to(0, { done: () => { if (!selected) inspector.style.display = "none"; } }); return; }
    el.classList.add("selected");
    const c = cards.find(k => k.el === el);
    const notes = ["Anna prefers totals rounded to thousands.", "Thursday's sign-off moved to 14:00.", "Costs tab added deferred licences on Monday.", "Last quarter's reply used the Revenue sheet.", "Priya reviews the same figures for the board pack.", "The Contoso renewal date is still open."];
    $("lg-scroll", inspector).viewport.innerHTML = `<button class="lg-btn insp-close" data-act="close-details" aria-label="Close details">${icon("x")}</button>
      ${badge(c.who)}<h2>${LG.escape(c.t)}</h2><div class="sub">${LG.escape(c.s)}</div>
      <div class="acts"><button class="lg-pill lg-accent">${icon("spark")}Ask about this</button><button class="lg-pill lg-filled">${icon("edge")}Open in Edge</button></div>
      <section><h3>Current situation</h3><div class="field">${c.q ? "Workspace compared both sheets. Costs includes deferred licences; Revenue doesn't. Anna asked for reviewed totals." : "Anna needs reviewed totals before Thursday's sign-off. Both sheets are in budget.xlsx."}</div></section>
      <section><h3>Next step</h3><div class="field">${c.q ? "Choose a sheet so Workspace can draft the reply." : "Draft a short reply with both totals for your review."}</div></section>
      <section><h3>Connected</h3>
        <div class="src">${badge("teams", true)}<div><div>Anna Berg</div><div class="sub" style="font-size:12px">Teams · asked for the review</div></div></div>
        <div class="src">${badge("excel", true)}<div><div>budget.xlsx</div><div class="sub" style="font-size:12px">Evidence for both totals</div></div></div>
      </section>
      <section><h3>Notes</h3>${notes.concat(notes).map(n => `<div class="note">${n}</div>`).join("")}</section>`;
    if (inspector.style.display !== "block") { inspector.style.display = "block"; inspectorSpring.set(0); }
    inspectorSpring.to(1);
    if (center) { const W = scene.clientWidth - 360, H = scene.clientHeight; camX.to(W / 2 - (c.x + 150) * cam.z); camY.to(H / 2 - (c.y + el.offsetHeight / 2) * cam.z); }
  }
  inspector.addEventListener("click", e => { if (e.target.closest('[data-act="close-details"]')) select(null); });

  addEventListener("keydown", e => {
    if (e.key === "Escape") {
      if (desktop.menuOpen) return setMenu(false);
      if (canvasOpen && canvasBar.mode !== "rest") return setMode("rest");
      if (selected) return select(null);
      if (canvasOpen) return closeCanvas();
    }
    if (e.key === "f" && e.ctrlKey && canvasOpen) { e.preventDefault(); setMode("search"); }
  });

  /* ── Study controls ──────────────────────────────────────────────── */
  const panel = $("#panel");
  panel.addEventListener("change", e => {
    const key = e.target.dataset.key;
    if (!key) return;
    state[key] = e.target.tagName === "LG-SWITCH" ? e.target.checked : e.target.value;
    if (key === "agent") bubbles.clear();
    sync();
  });
  $("#runAgent").addEventListener("click", runAgent);
  $("#openCanvas").addEventListener("click", () => canvasOpen ? closeCanvas() : openCanvas());

  /* Small glass reads the content beneath it; everything large follows the appearance. */
  function renderBars() {
    const beneath = state.wallpaper === "vivid" ? state.appearance : { light: "light", dark: "dark" }[state.wallpaper];
    LG.scheme($("#bar"), beneath);
    desktop.render();
    if (canvasOpen) canvasBar.render();
    writeClocks();
  }
  function sync() {
    body.dataset.wallpaper = state.wallpaper;
    body.dataset.appearance = state.appearance;
    for (const el of [panel, $("#phases"), win, submenu]) LG.scheme(el, state.appearance);
    for (const el of $$("[data-key]", panel)) {
      const value = state[el.dataset.key];
      if (el.tagName === "LG-SWITCH") { if (el.checked !== value) el.checked = value; }
      else if (el.value !== value) el.value = value;
    }
    renderBars();
  }

  /* Code behind the dark-app backdrop. */
  (function code() {
  const lines = [
    `<span class="k">from</span> dataclasses <span class="k">import</span> <span class="t">dataclass</span>`,
    `<span class="k">from</span> assistant.feed_origin <span class="k">import</span> <span class="t">App</span>`, ``,
    `<span class="c"># Glass has no colour of its own; tint carries meaning only.</span>`,
    `<span class="f">@dataclass</span>(<span class="v">frozen</span>=<span class="k">True</span>, <span class="v">slots</span>=<span class="k">True</span>)`,
    `<span class="k">class</span> <span class="t">Material</span>:`,
    `    <span class="v">fill</span>: <span class="t">float</span>`, `    <span class="v">blur</span>: <span class="t">float</span>`, `    <span class="v">rim</span>: <span class="t">float</span>`, ``,
    `<span class="k">def</span> <span class="f">material</span>(<span class="v">size</span>: <span class="t">Size</span>, <span class="v">look</span>: <span class="t">Look</span>) -> <span class="t">Material</span>:`,
    `    <span class="k">match</span> size, look:`,
    `        <span class="k">case</span> <span class="t">Size</span>.SMALL, <span class="t">Look</span>.CLEAR:`,
    `            <span class="k">return</span> <span class="t">Material</span>(<span class="n">0.20</span>, <span class="n">10</span>, <span class="n">0.9</span>)`,
    `        <span class="k">case</span> <span class="t">Size</span>.LARGE, <span class="t">Look</span>.CLEAR:`,
    `            <span class="k">return</span> <span class="t">Material</span>(<span class="n">0.66</span>, <span class="n">28</span>, <span class="n">0.9</span>)`,
    `        <span class="k">case</span> _, <span class="t">Look</span>.TINTED:`,
    `            <span class="k">return</span> <span class="t">Material</span>(<span class="n">0.86</span>, <span class="n">28</span>, <span class="n">0.6</span>)`, ``,
    `<span class="k">def</span> <span class="f">concentric</span>(<span class="v">outer</span>: <span class="t">float</span>, <span class="v">inset</span>: <span class="t">float</span>) -> <span class="t">float</span>:`,
    `    <span class="s">"""Nested corners share a centre."""</span>`,
    `    <span class="k">return</span> <span class="f">max</span>(<span class="n">0.0</span>, outer - inset)`, ``,
    `<span class="k">def</span> <span class="f">scheme_for</span>(<span class="v">luma</span>: <span class="t">float</span>) -> <span class="t">Scheme</span>:`,
    `    <span class="k">return</span> <span class="t">Scheme</span>.DARK <span class="k">if</span> luma &lt; <span class="n">0.5</span> <span class="k">else</span> <span class="t">Scheme</span>.LIGHT`,
  ];
  const all = [...lines, ...lines, ...lines];
  $("#src").innerHTML = all.join("\n"); $("#gutter").textContent = all.map((_, i) => i + 1).join("\n");
})();


  /* ── Start ──────────────────────────────────────────────────────── */
  sync();
  // Widths depend on the typeface: re-measure once it has loaded.
  document.fonts.ready.then(() => { desktop.refresh(); if (canvasOpen) canvasBar.refresh(); writeClocks(); });
  requestAnimationFrame(() => {
    if (params.has("canvas")) openCanvas();
    if (params.has("menu")) setMenu(true);
    if (params.has("run")) runAgent();
    if (params.has("select")) setTimeout(() => select($(`#${params.get("select")}`)), 50);
    if (params.get("sidebar") === "0") panel.open = false;
  });
  // For tests and measurement.
  window.workspaceDemo = { state, sync, desktop, canvasBar, openCanvas, select, setMenu, setSeconds: s => { seconds = s; renderBars(); } };
})();
