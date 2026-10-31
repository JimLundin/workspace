# Liquid Glass kit

A small HTML, CSS and JavaScript kit for interfaces in Apple's Liquid Glass
language, for browsers and web views. There's no build step and there are no
dependencies: open `demo/index.html` from disk to see Workspace built with it.
The design decisions and their sources are in
[docs/design/liquid-glass.md](../../docs/design/liquid-glass.md).

## Use

```html
<link rel="stylesheet" href="liquid-glass/liquid-glass.css">
<body class="lg-root lg-dark">
  …
  <script src="liquid-glass/src/core.js"></script>
  <script src="liquid-glass/src/material.js"></script>
  <script src="liquid-glass/src/capsule.js"></script>
  <script src="liquid-glass/src/island.js"></script>
  <script src="liquid-glass/src/ui.js"></script>
  <script src="liquid-glass/icons/fluent.js"></script>
  <script src="liquid-glass/src/controls.js"></script>
  <script src="liquid-glass/src/scroll.js"></script>
  <script src="liquid-glass/src/sidebar.js"></script>
  <script src="liquid-glass/src/stack.js"></script>
</body>
```

Scripts are classic scripts, not modules, so pages work from `file://` and in
web views without a server. Load them in this order; each one extends the
`window.LiquidGlass` namespace. `icons/fluent.js` must load after `ui.js`.

Put `lg-root` on the page or on a container. Set the scheme per surface with
`lg-light` or `lg-dark`, because small glass picks its scheme from the content
beneath it, while large glass follows the appearance.

## Pieces

| Piece | What it is |
| --- | --- |
| `liquid-glass.css` | Tokens, light and dark schemes, the glass material and every component's styles. Classes are prefixed `lg-` |
| `LiquidGlass.Spring` | Springs with Apple's damping ratio and response. Retargeting keeps the live value and velocity, so motion is interruptible. Presets live in `LiquidGlass.motion` |
| `LiquidGlass.glass(el, { large, lens, interactive })` | Applies the material. `lens` adds edge refraction; `interactive` adds the press flex and the light under the pointer |
| `LiquidGlass.Capsule` | A glass shape whose width and height spring between contents while the content cross-fades. Expanded content lays out at its final size, so text never reflows during the morph |
| `LiquidGlass.IslandBar` | A centred island with lead and trail zones. The host supplies a view function; the bar owns capsules, order, hover and click delegation |
| `LiquidGlass.ui` | Markup builders: buttons, facts, spinner, waveform, recording dot, menus with live rows, question cards, app badges and card anatomy |
| `LiquidGlass.icon(name, { filled })` | Fluent UI System Icons (MIT) at 16 px, with filled variants for active states |
| `<lg-segmented>`, `<lg-switch>` | Controls; the switch knob turns to glass while held |
| `<lg-scroll>` | Native scrolling with overlay scroll bars and edge fades |
| `<lg-sidebar>` | A floating sidebar with a toggle that stays put |
| `LiquidGlass.BubbleStack` | Transient glass bubbles; earlier ones collapse and recede |

## Rules the components encode

- **Glass is for the functional layer.** Bars, menus, bubbles, sidebars and
  inspectors are glass. Content uses `.lg-card`, a solid surface with the same
  anatomy.
- **Glass never sits on glass.** Buttons inside glass are filled
  (`.lg-pill.lg-filled`, `.lg-pill.lg-accent`, `.lg-q-btn`), and the sidebar
  toggle drops its glass while the sidebar is open.
- **Colour carries meaning.** `lg-tint` (orange) marks waiting attention and
  `lg-prominent` the primary action. Tinted glass takes its rim light from its
  own tint instead of white.
- **Concentric shapes.** A 34 px capsule with a 3 px inset holds 28 px controls.
  An expanded island uses 28 px corners and a 12 px inset around 32 px
  buttons. The inspector's radius is the window's 26 px less its 8 px inset.
- **The island.** At rest it holds the resting facts, and ongoing work joins its
  own leading and trailing slots. A moment (dictation, a question, a menu)
  takes the island over, and ongoing work then detaches beside it. Beside the
  island go only temporary or active things. Clicking the island acts on what
  it shows.
- **Scroll bars.** They follow macOS overlay scroll bars: hidden at rest,
  shown while content moves, and faded 0.9 s after it stops. Hovering
  thickens the thumb from 6 to 8 px and shows the track; the thumb drags and
  the track pages. An edge fades only when content lies beyond it, which hints
  that there's more. Scroll edge effects (`.lg-edge-top`, `.lg-edge-bottom`)
  go only where content passes under floating controls, one per edge.

## Platform notes

Edge refraction puts an SVG filter inside `backdrop-filter`. It's verified in
Chromium and in Edge 155 on Windows (61 fps on Intel Iris Xe). Where the engine
reports no support for that, the kit skips refraction and keeps the plain blur.
Other engines are untested.

## Licences

- Inter: SIL Open Font License 1.1 (`fonts/OFL.txt`).
- Fluent UI System Icons: MIT (`icons/LICENSE-fluent.txt`).
- SF Pro and SF Symbols are licensed for Apple platforms only and aren't used.
