# Liquid Glass kit

A component kit for interfaces in Apple's Liquid Glass language, for browsers and
web views. It's plain HTML, CSS and JavaScript, with no build step and no
dependencies, so pages work straight from disk.

- [gallery/index.html](gallery/index.html) shows every component, tier by tier.
- [demo/index.html](demo/index.html) is Workspace composed from the kit.
- The design decisions and their sources are in
  [docs/design/liquid-glass.md](../../docs/design/liquid-glass.md).

## Use

```html
<link rel="stylesheet" href="liquid-glass/liquid-glass.css">
<body class="lg-root lg-dark">
  <lg-island-bar id="bar" order="island inbox"></lg-island-bar>
  <script src="liquid-glass/liquid-glass.js"></script>
  <script>
    LiquidGlass.ready.then(LG => {
      const { h } = LG;
      const bar = document.querySelector("#bar");
      bar.view = () => [{ zone: "island", key: "island", kind: "text", content: h("lg-fact", { num: true }, "10:22") }];
      bar.render();
    });
  </script>
</body>
```

Put `lg-root` on the page or a container. Give each surface a scheme with
`lg-light` or `lg-dark`: small glass takes its scheme from the content beneath
it, while large glass follows the appearance.

## Tiers

Each tier is built only from the tiers before it.

| Tier | Components |
| --- | --- |
| Foundations | Tokens and schemes, the root and reset, the glass material, springs and motion presets, the element base, the `h()` markup helper, the icon registry |
| Atoms | `lg-icon`, `lg-button`, `lg-badge`, `lg-spinner`, `lg-dot`, `lg-wave`, `lg-fact`, `lg-kbd`, `lg-timer`, `lg-app`, `lg-field` |
| Controls | `lg-segmented`, `lg-switch` |
| Molecules | `lg-menu`, `lg-menu-item`, `lg-menu-separator`, `lg-live-row`, `lg-question`, `lg-card`, `lg-steps`, `lg-step`, `lg-section`, `lg-rows`, `lg-row`, `lg-field-row`, `lg-actions`, `lg-footnote` |
| Containers | `lg-scroll`, `lg-popover`, `lg-stack`, `lg-sidebar`, `lg-inspector`, `lg-window` |
| Bars | The capsule morph engine (`LiquidGlass.Capsule`), `lg-island-bar` |

Each component file starts with its usage: tag, attributes, slots, properties
and events.

## Files

```
liquid-glass.css      CSS entry: layer order and one import per component
liquid-glass.js       JS entry: one manifest, loaded in tier order; LiquidGlass.ready
foundations/          tokens.css base.css material.css · core.js icons.js material.js
atoms/                <name>.css + <name>.js per component
controls/             …
molecules/            …
containers/           …
bars/                 …
icons/fluent.js       the Fluent symbols the kit uses, and their licence
fonts/                Inter, and its licence
gallery/  demo/       pages built from the kit
tools/                check_structure.py
```

A component is a pair of files with the same name in its tier's folder, for
example `atoms/button.css` and `atoms/button.js`. Related small elements may
share a pair: `atoms/indicators.*` holds the spinner, dot and waveform.

## CSS

- **Cascade layers set precedence.** `liquid-glass.css` declares
  `@layer lg.foundations, lg.atoms, lg.controls, lg.molecules, lg.containers, lg.bars`,
  and imports each component stylesheet into its tier's layer. A later tier
  wins over an earlier one regardless of selector specificity, so a
  container's own rules always beat the base material. A host page's own
  unlayered CSS wins over the whole kit, so pages can adjust the kit without
  `!important`.
- **Element selectors style components; attributes carry state and variants.**
  For example: `lg-button[variant="accent"]`, `lg-switch[checked]`,
  `lg-step[state="done"]`. Internal parts use `lg-` prefixed classes
  (`.lg-cap`, `.lg-content`). Every class in a kit stylesheet is prefixed.
- **Tokens only.** Colours, sizes and motion come from `--lg-*` custom
  properties in `foundations/tokens.css`. Schemes swap the token values; a
  component never hard-codes a light or dark colour.
- **The base reset has zero specificity** (`:where()`), so component rules
  never fight it.

## JavaScript

- **Classic scripts, one namespace.** Every file is an immediately invoked
  function that extends `window.LiquidGlass`. Modules aren't used because
  browsers block them on `file://`. The loader runs files in manifest order.
- **Custom elements render light DOM.** They extend `LiquidGlass.Element`:
  `build()` runs once on first connection, and `update()` runs when an
  observed attribute changes. Light DOM keeps kit CSS and host CSS in one
  cascade.
- **Actions are declarative.** Any element with `act="…"` reports that action
  to the bar or container it sits in; `lg-island-bar` dispatches `lg-action`
  with `{ action, key, event }`.
- **Markup is built with `LiquidGlass.h(tag, attributes, children)`,** which
  escapes text and attribute values. `true` writes a bare attribute; `false`,
  `null` and `undefined` omit it.
- **Motion uses `LiquidGlass.Spring`.** Springs take Apple's damping ratio and
  response, and retarget from the live value and velocity, so every animation
  can be interrupted. Presets live in `LiquidGlass.motion`.

## Adding a component

1. Choose the lowest tier that holds everything it uses.
2. Create `<tier>/<name>.css` and `<tier>/<name>.js`. Start the script with its
   usage comment, and register elements with `LiquidGlass.define`.
3. Add one `@import` to `liquid-glass.css`, in the tier's `layer()`, and one
   path to the manifest in `liquid-glass.js`, under its tier.
4. Show it in `gallery/index.html`.
5. Run `python design/liquid-glass/tools/check_structure.py`. It fails when a
   file is missing from an entry point, the tiers are out of order, or a
   stylesheet uses an unprefixed class.

## Rules the components encode

- **Glass is for the functional layer.** Bars, menus, cards in the stack,
  sidebars and inspectors are glass. Content uses `lg-card variant="solid"`,
  which has the same anatomy.
- **Glass never sits on glass.** Buttons inside glass are plain, filled or
  accent, and the sidebar toggle drops its glass while the sidebar is open.
- **Colour carries meaning.** The `attention` tint (orange) marks waiting
  attention, and `prominent` marks the primary action. Tinted glass takes its
  rim light from its own tint.
- **Concentric shapes.** A 34 px capsule with a 3 px inset holds 28 px controls.
  An expanded island uses 28 px corners around 32 px buttons inset by 12 px.
  An inspector's radius is its window's 26 px less its 8 px inset.
- **The island.** At rest it holds the resting facts. Processing (a spinner) and
  a recording join its leading and trailing slots. A moment (dictation, a
  question, a menu) takes the island over, and ongoing work then detaches
  beside it. Only temporary or active things sit beside the island. Clicking
  the island acts on what it shows.
- **Text never reflows mid-morph.** Expanded content lays out at its final size
  and the growing capsule reveals it. Leaving content keeps its size while it
  fades. A capsule follows its content's real width as it changes, whether a
  timer gains a digit or a font arrives after first paint.
- **Scroll bars** follow macOS overlay scroll bars: hidden at rest, shown while
  content moves, faded 0.9 s after it stops, thicker on hover, draggable, with
  a track that pages. Edges fade only when content lies beyond them.

## Platform notes

Edge refraction puts an SVG filter inside `backdrop-filter`. It's verified in
Chromium and in Edge 155 on Windows (61 fps on Intel Iris Xe). Where the engine
reports no support, the kit skips refraction and keeps the plain blur. Other
engines are untested.

## Licences

- Inter: SIL Open Font License 1.1 (`fonts/OFL.txt`).
- Fluent UI System Icons: MIT (`icons/LICENSE-fluent.txt`).
- SF Pro and SF Symbols are licensed for Apple platforms only and aren't used.
