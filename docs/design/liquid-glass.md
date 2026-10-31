# Liquid Glass study

31 October 2026. A design study for restyling Workspace in Apple's current
language. Interactive demo: [liquid-glass-demo.html](liquid-glass-demo.html)
(open in Edge; it has no dependencies). Nothing here changes the Qt runtime yet.

## Sources

- Apple HIG: Materials, Color, Toolbars and Menus (Liquid Glass guidance
  revised 9 September 2025).
- Apple developer documentation: Liquid Glass overview and *Adopting Liquid
  Glass*.
- WWDC25 Liquid Glass sessions; WWDC26 *Principles of great design*
  ([session list](https://developer.apple.com/videos/wwdc2026/)). macOS 27 and
  iOS 27 keep Liquid Glass. WWDC26 added no new material guidance.
- *Designing Fluid Interfaces* (WWDC18) for springs, momentum and
  interruption.

## What the guidance says

1. **Two layers.** Liquid Glass is only for the functional layer: controls,
   bars, menus, popovers and sheets. Content (cards, rows and backgrounds) uses
   standard materials or solid surfaces. Don't place glass on glass.
2. **No inherent colour.** Glass takes its colour from the content beneath it.
   Labels and symbols are monochrome and vibrant. Small bars flip between
   light and dark with the content behind them. Larger surfaces are more
   opaque and follow the system appearance.
3. **Tint carries meaning.** Colour the background of a primary action or a
   status, never decoration, and only on a few controls at a time.
4. **Regular and clear variants.** Regular blurs and adjusts luminosity, and
   suits anything with text. Clear is for media backgrounds and needs a 35%
   dimming layer over bright content. Users can also choose a more opaque
   *Tinted* look.
5. **Concentric shapes.** Use capsules for controls. Nested radius = outer
   radius − inset. Windows and sheets have larger radii, and inset sheets let
   content show around them.
6. **Groups, not dividers.** Toolbar items that share a background form a
   group, and fixed spacing separates groups. Don't mix text and icons in one
   group. Scroll-edge effects replace hairline dividers.
7. **Fluid morphing.** Buttons morph into their menus. Glass shapes merge
   and split. Interactive glass flexes and lights up at the touch point. A
   toggle's knob becomes glass while held.
8. **Fallbacks.** Reduce Transparency makes glass frosted or solid. Increase
   Contrast gives near-solid surfaces with defined edges. Reduce Motion replaces
   morphs and springs with cross-fades.

## Applied to Workspace

| Surface | Today | Proposed |
| --- | --- | --- |
| Desktop bar | One lilac capsule fused to the screen edge with flared shoulders and internal dividers | Separate glass groups floating 8 px below the edge: controls, readout, inbox and auxiliary capsules. Spacing replaces dividers. Ink flips with the content beneath. Width changes spring and content materializes. Recording and keyboard capsules split out of the bar |
| "Needs you" | Label in the shared capsule | The readout capsule tinted orange: the bar's only coloured state |
| Controls menu | Qt `QMenu` with a solid background | Large glass morphing from the menu button, an icon per item, and an accent highlight row |
| Agent phase bubbles | Lilac bubbles with app palettes | Large regular glass, like macOS notifications. App identity moves to a rounded app badge. Earlier phases collapse and recede. Prominent glass marks the primary answer |
| Work canvas | Lilac-tinted dark window, lilac work bubbles | Neutral content layer with solid cards. App colour appears only in badges and the amber question card. The floating bottom toolbar is the only glass. Soft scroll-edge effects. An inset inspector with a concentric radius slides in from the trailing edge |
| Motion | 160 ms slides and fixed-duration animation | Critically damped springs by default. Bounce only after a throw. Pans project momentum and rubber-band at edges. Every transition can be interrupted |
| Typography | Segoe UI, 12 px | Segoe UI Variable (the Windows analogue of SF Pro's optical sizes), 13 px body, negative tracking on titles |

The current lilac identity stays available as an accent; the demo compares
it with system blue.

## What ports to Qt on Windows

`winapi/composition.py` already composes rounded host-backdrop glass behind
per-pixel Qt windows. That supports blurred desktop backdrops, tint layers,
arbitrary capsule outlines and shadows. QPainter can paint rim light, vibrant
ink, the pointer highlight and springs.

Edge refraction (the lensing at a glass rim) does not port to desktop
surfaces. Windows composition exposes no displacement effect, and Workspace
avoids desktop captures. The demo's *Edge refraction* switch shows the
shippable result without it. Inside the canvas window Workspace owns the
pixels, so refraction is possible there, but it would need a Qt Quick/RHI
shader path. Measure that before committing to it.

## Open decisions

- Should the bar detach from the screen edge, or keep the shoulder-flared
  attachment with glass styling?
- Accent: system blue or Workspace lilac?
- Should the canvas window adopt macOS-style window controls, or keep window
  controls in its options menu?
