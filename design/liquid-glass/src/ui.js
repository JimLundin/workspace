/* Markup builders for the kit's content: icons, facts, live indicators, menus,
   question cards and the card anatomy shared by solid cards and glass bubbles.
   Builders return HTML strings so views can hand them straight to capsules.
   Text arguments are escaped; `html` arguments are trusted markup. */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const esc = LG.escape;

  /* Icons: one registered set; `filled` variants mark active states, as SF Symbols' .fill does. */
  let set = null;
  LG.icons = { register(icons) { set = icons; } };
  LG.icon = (name, { filled = false, label = "" } = {}) => {
    // A small rounded square reads as Stop at toolbar size, like SF Symbols' stop.fill.
    if (name === "stop") return `<svg class="lg-icon" viewBox="0 0 16 16" ${label ? `role="img" aria-label="${esc(label)}"` : 'aria-hidden="true"'}><rect x="4.25" y="4.25" width="7.5" height="7.5" rx="1.8"/></svg>`;
    const body = (filled && set.filled[name]) || set.regular[name];
    if (!body) throw new Error(`Unknown icon: ${name}`);
    return `<svg class="lg-icon" viewBox="${set.viewBox}" ${label ? `role="img" aria-label="${esc(label)}"` : 'aria-hidden="true"'}>${body}</svg>`;
  };
  const icon = LG.icon;

  const ui = (LG.ui = {});

  ui.button = ({ act, icon: name, label, title = label, filled = false, badge = null, text = null }) =>
    `<button class="lg-btn${text ? " lg-label" : ""}" data-act="${esc(act)}" aria-label="${esc(label)}" title="${esc(title)}">${name ? icon(name, { filled }) : ""}${text ? `<span>${esc(text)}</span>` : ""}${badge != null ? `<span class="lg-badge">${esc(badge)}</span>` : ""}</button>`;
  ui.stop = (label, act = "stop") => ui.button({ act, icon: "stop", label });
  ui.fact = (text, { icon: name = null, quiet = false, num = false } = {}) =>
    `<span class="lg-fact${quiet ? " lg-quiet" : ""}${num ? " lg-num" : ""}">${name ? icon(name) : ""}${text ? `<span>${esc(text)}</span>` : ""}</span>`;
  ui.spinner = label => `<span class="lg-spinner" role="status" aria-label="${esc(label)}" title="${esc(label)}"></span>`;
  ui.dot = () => `<span class="lg-dot" aria-hidden="true"></span>`;
  ui.wave = (bars = 18) => `<span class="lg-wave" data-live="audio" aria-hidden="true">${"<i></i>".repeat(bars)}</span>`;
  ui.slot = html => `<span class="lg-slot">${html}</span>`;

  /* Menu: { title, detail, now: [{ html }], items: [{ act, icon, label, key, check, sub } | "-"] } */
  ui.menu = ({ title = null, detail = "", now = [], items = [] }) => `<div class="lg-menu">
    ${title ? `<div class="lg-menu-head"><b>${esc(title)}</b><span>${esc(detail)}</span></div>` : ""}
    ${now.map(row => `<div class="lg-now">${row.html}</div>`).join("")}${now.length ? '<div class="lg-sep"></div>' : ""}
    ${items.map(item => item === "-" ? '<div class="lg-sep"></div>' : `<button class="lg-item" ${item.act ? `data-act="${esc(item.act)}"` : ""} ${item.sub ? `data-sub="${esc(item.sub)}"` : ""}>${item.icon ? icon(item.icon) : ""}<span>${esc(item.label)}</span>${item.key ? `<span class="lg-key">${esc(item.key)}</span>` : ""}${item.check ? `<span class="lg-check">${icon("check")}</span>` : ""}${item.sub ? `<span class="lg-trailing">${icon("chev")}</span>` : ""}</button>`).join("")}
  </div>`;
  // A live row: activity glyph, label, detail and its own control.
  ui.nowRow = ({ glyph, label, detail = "", control = "" }) => ({ html: `${glyph}<span class="lg-now-label">${esc(label)}</span>${detail ? `<span class="lg-now-detail">${esc(detail)}</span>` : ""}${control}` });

  /* Question card: { badge, title, meta, body, actions: [{ act, label, primary }] } */
  ui.question = ({ badge, title, meta = "", body = "", actions = [] }) => `<div class="lg-question">
    <div class="lg-q-top">${badge}<div class="lg-q-title">${esc(title)}</div>${meta ? `<span class="lg-q-meta">${esc(meta)}</span>` : ""}</div>
    ${body ? `<div class="lg-q-body">${esc(body)}</div>` : ""}
    <div class="lg-q-actions">${actions.map(a => `<button class="lg-q-btn${a.primary ? " lg-primary" : ""}" data-act="${esc(a.act)}">${esc(a.label)}</button>`).join("")}</div>
  </div>`;

  /* App badge: a rounded square with a glyph or letter. `color` is any CSS background. */
  ui.app = ({ glyph, color, small = false }) => `<div class="lg-app${small ? " lg-small" : ""}" style="--lg-app:${color}">${esc(glyph)}</div>`;

  /* Card anatomy, shared by solid content cards and glass bubbles. `html` adds trusted content below the body. */
  ui.head = ({ app, title, meta = "", body = "", trailing = "" }) => `<div class="lg-head">${app}<div class="lg-titles">
    <div style="display:flex;gap:8px;align-items:baseline"><span class="lg-title" style="flex:1">${esc(title)}</span>${trailing}</div>
    ${meta ? `<div class="lg-meta">${esc(meta)}</div>` : ""}${body ? `<div class="lg-body">${esc(body)}</div>` : ""}</div></div>`;
})();
