/* Layer 4: molecules, composed from atoms.

     <lg-menu heading="Workspace" detail="Layout on">
       <lg-live-row label="Recording"><lg-dot slot="glyph"></lg-dot><lg-timer slot="detail" since="…"></lg-timer>
         <lg-button slot="control" icon="stop" label="Stop recording" act="stop-recording"></lg-button></lg-live-row>
       <lg-menu-item icon="canvas" act="canvas">Your work canvas</lg-menu-item>
       <lg-menu-separator></lg-menu-separator>
       <lg-menu-item icon="tile" sub="tiling">Window tiling</lg-menu-item>
     </lg-menu>

     <lg-question heading="Which sheet?" meta="now">
       <lg-app slot="badge" glyph="✦"></lg-app><span slot="body">…</span>
       <lg-button variant="accent" act="answer">Revenue</lg-button><lg-button act="answer">Costs</lg-button>
     </lg-question>

     <lg-card variant="solid|glass" heading="Anna Berg" meta="Teams · 9:41" time="now">
       <lg-app slot="badge" …></lg-app><span slot="body">…</span> …extra content…
       <div slot="actions">…buttons…</div>
     </lg-card>

     <lg-steps><lg-step state="running">Read Teams conversation</lg-step></lg-steps>

     <lg-section heading="Toolbar">
       <lg-field-row label="Dictation"><lg-segmented>…</lg-segmented></lg-field-row>
       <lg-rows><lg-row label="Recording"><lg-switch></lg-switch></lg-row></lg-rows>
     </lg-section>

     <lg-actions><lg-button variant="filled">…</lg-button>…</lg-actions>   <lg-footnote>…</lg-footnote> */
(() => {
  "use strict";
  const LG = window.LiquidGlass;
  const { Element, define, escape } = LG;
  const take = (el, slot) => [...el.children].filter(c => c.getAttribute("slot") === slot);

  class Menu extends Element {
    build() {
      this.setAttribute("role", "menu");
      const heading = this.getAttribute("heading");
      if (heading) {
        const head = document.createElement("div");
        head.className = "lg-menu-head";
        head.innerHTML = `<b>${escape(heading)}</b><span>${escape(this.getAttribute("detail") || "")}</span>`;
        this.prepend(head);
      }
      // Live rows sit above the items, set apart by a separator.
      const rows = [...this.children].filter(c => c.tagName === "LG-LIVE-ROW");
      if (rows.length && rows.at(-1).nextElementSibling?.tagName === "LG-MENU-ITEM") rows.at(-1).after(document.createElement("lg-menu-separator"));
    }
  }

  class MenuItem extends Element {
    build() {
      this.text = this.textContent.trim();
      const icon = this.getAttribute("icon"), key = this.getAttribute("key");
      this.innerHTML = `<button type="button" role="menuitem">${icon ? `<lg-icon name="${escape(icon)}"></lg-icon>` : ""}<span>${escape(this.text)}</span>${key ? `<span class="lg-key">${escape(key)}</span>` : ""}${this.hasAttribute("check") ? '<span class="lg-check"><lg-icon name="check"></lg-icon></span>' : ""}${this.hasAttribute("sub") ? '<span class="lg-trailing"><lg-icon name="chev"></lg-icon></span>' : ""}</button>`;
      if (this.hasAttribute("sub")) this.firstElementChild.setAttribute("aria-haspopup", "menu");
    }
  }

  class MenuSeparator extends Element { update() { this.setAttribute("role", "separator"); } }

  /* A live row: an activity's glyph, label, detail and its own control. */
  class LiveRow extends Element {
    build() {
      const label = document.createElement("span");
      label.className = "lg-live-label";
      label.textContent = this.getAttribute("label") || "";
      this.prepend(...take(this, "glyph"), label);
      label.after(...take(this, "detail"), ...take(this, "control"));
    }
  }

  /* An expanded island's question: badge, title, meta, body and equal answer buttons. */
  class Question extends Element {
    build() {
      const badge = take(this, "badge"), body = take(this, "body"), actions = [...this.children].filter(c => c.tagName === "LG-BUTTON");
      const top = document.createElement("div");
      top.className = "lg-q-top";
      top.innerHTML = `<div class="lg-q-title">${escape(this.getAttribute("heading") || "")}</div>${this.getAttribute("meta") ? `<span class="lg-q-meta">${escape(this.getAttribute("meta"))}</span>` : ""}`;
      top.prepend(...badge);
      const text = document.createElement("div"); text.className = "lg-q-body"; text.append(...body);
      const row = document.createElement("div"); row.className = "lg-q-actions";
      for (const b of actions) { b.setAttribute("size", "large"); b.setAttribute("wide", ""); if (!b.hasAttribute("variant")) b.setAttribute("variant", "filled"); row.append(b); }
      this.replaceChildren(top, ...(body.length ? [text] : []), row);
    }
  }

  /* One anatomy for solid content cards and glass notification cards. */
  class Card extends Element {
    build() {
      if (!this.hasAttribute("variant")) this.setAttribute("variant", "solid");
      const badge = take(this, "badge"), body = take(this, "body"), actions = take(this, "actions");
      const extra = [...this.children].filter(c => !badge.includes(c) && !body.includes(c) && !actions.includes(c));
      const head = document.createElement("div");
      head.className = "lg-head";
      head.innerHTML = `<div class="lg-titles"><div class="lg-title-row"><span class="lg-title">${escape(this.getAttribute("heading") || "")}</span>${this.getAttribute("time") ? `<span class="lg-time">${escape(this.getAttribute("time"))}</span>` : ""}</div>${this.getAttribute("meta") ? `<div class="lg-meta">${escape(this.getAttribute("meta"))}</div>` : ""}</div>`;
      head.prepend(...badge);
      head.querySelector(".lg-titles").append(...body);
      const more = document.createElement("div"); more.className = "lg-extra"; more.append(...extra);
      this.replaceChildren(head, ...(extra.length ? [more] : []), ...actions);
    }
  }

  class Steps extends Element {}
  /* A step: pending (hidden), running (spinner) or done (check). */
  class Step extends Element {
    static get observedAttributes() { return ["state"]; }
    build() { this.text = this.textContent.trim(); this.update(); }
    update() {
      const state = this.getAttribute("state") || "pending";
      const glyph = state === "done" ? '<span class="lg-done"><lg-icon name="checkc"></lg-icon></span>' : `<lg-spinner label="${escape(this.text)}"></lg-spinner>`;
      this.innerHTML = `${glyph}<span>${escape(this.text)}</span>`;
    }
  }

  class Section extends Element {
    build() {
      const heading = this.getAttribute("heading");
      if (heading) { const h = document.createElement("h2"); h.textContent = heading; this.prepend(h); }
    }
  }
  class Rows extends Element {}
  class Row extends Element {
    build() {
      const label = document.createElement("span");
      label.textContent = this.getAttribute("label") || "";
      this.prepend(label);
      for (const control of this.querySelectorAll("lg-switch, lg-segmented")) if (!control.hasAttribute("aria-label")) control.setAttribute("aria-label", label.textContent);
    }
  }
  class FieldRow extends Element {
    build() {
      const label = document.createElement("span");
      label.className = "lg-field-label";
      label.textContent = this.getAttribute("label") || "";
      this.prepend(label);
    }
  }

  define("lg-menu", Menu);
  define("lg-menu-item", MenuItem);
  define("lg-menu-separator", MenuSeparator);
  define("lg-live-row", LiveRow);
  define("lg-question", Question);
  define("lg-card", Card);
  define("lg-steps", Steps);
  define("lg-step", Step);
  define("lg-section", Section);
  define("lg-rows", Rows);
  define("lg-row", Row);
  define("lg-field-row", FieldRow);
  define("lg-actions", class extends Element {});
  define("lg-footnote", class extends Element {});
})();
