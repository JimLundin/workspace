# Liquid Glass study

31 October 2026. A design study for restyling Workspace in Apple's current
language. Interactive demo: [liquid-glass-demo.html](liquid-glass-demo.html)
(open in Edge; it has no dependencies). Nothing here changes the Qt runtime yet.
The first version is preserved as the `liquid-glass-prototype-v1` tag.

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
- Apple HIG: Live Activities (Dynamic Island presentations), the menu bar,
  tab bars, typography and SF Symbols.

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
| Typography | Segoe UI, 12 px | Inter, 13 px body, optical sizing, negative tracking on titles |
| Symbols | Hand-drawn Feather-style paths | Lucide at a 1.75 stroke, with a filled variant for active states |

The accent is system blue.

## Typeface

SF Pro is the right font only on Apple platforms. Apple's licence restricts the
San Francisco fonts to Apple platforms, and the HIG says not to embed system
fonts. A Windows app therefore needs a substitute. Inter 4 (SIL OFL 1.1) is the
closest open design: its proportions and x-height are near SF Pro's, and it has
an optical-size axis like SF's Text and Display cuts. The demo embeds its
73 KB Latin variable font. Qt can load it with `QFontDatabase.addApplicationFont`
and set the axis through `QFont.setVariableAxis`. Segoe UI Variable stays
available in the demo for comparison, but it reads as Windows.

Apple's tracking table tightens text as it grows: 0 at 12 pt, −0.08 pt at
13 pt and about −0.45 pt at 20 pt. Inter publishes a similar rule. Apply it per
size rather than as one letter-spacing value.

## Symbols

SF Symbols carry the same platform restriction, and the HIG prohibits
look-alikes in trademarked uses. The demo compares two open sets at toolbar
size. **Lucide** (ISC) at a 1.75 stroke matches Inter's medium weight best, and
its geometry is closest to SF's rounded terminals. **Phosphor** (MIT) has true
filled variants, like SF's `.fill` states, but its regular weight is slightly
light next to Inter. The recommendation is Lucide. Fill the microphone and
recording glyphs when they're active, and use a small rounded square for Stop,
as `stop.fill` does. Vendor only the paths Workspace uses into
`assistant/vector_icons.py`, which already renders SVG paths.

## Toolbar pattern

The demo's **Compare toolbar patterns** view runs one scenario through three
arrangements. The scenario is idle, dictate, transcribe, agent working,
meeting starts, dictate meanwhile, agent asks, keyboard layer, and done. For
each arrangement it measures how far the menu and inbox buttons move from their
idle position. Persistent controls that move under the pointer break spatial
memory: the HIG's familiarity principle says things that look the same should
live in the same place.

Apple's precedents:

- **Dynamic Island.** One activity uses the *compact* presentation: the same
  shape widens around the camera and reads as one piece of information. With
  several activities, one stays attached and the others *detach* as circular
  or oval minimal presentations. A long press *expands* it downward. Layout
  changes should move existing elements rather than remove and re-add them.
- **Liquid Glass bars.** iOS 26 tab bars and macOS 26 toolbars float inset from
  the edges as glass groups that merge and split. The tab bar's accessory moves
  inline when the bar minimizes. Apple replaced the edge-attached notch with the
  floating island.
- **Mac menu bar.** Status items sit at the screen edge, so a cursor thrown
  upward always hits them. iPhone Live Activities appear there on macOS 26.

Measured results (largest menu displacement over the scenario):

| Pattern | Floating | Attached | Behaviour |
| --- | --- | --- | --- |
| One capsule | 183 px | 183 px | Every activity widens the one shape |
| Glass groups | 233 px | 254 px | Each activity adds a pill; ambient never yields |
| Island | 91 px for the expanded question; 24 px settled; 0 px otherwise | same | Moments morph the centre; durations detach |

**Recommendation: the island, floating, with an edge-to-edge hit target.**

- *Morph for moments, detach for durations.* Dictation, transcription and a
  new question are short and hold attention, so they take over the centre
  island. Agent work, meeting recording and the keyboard layer last minutes and
  are independent, so each gets a detached minimal pill beside the inbox. This
  matches Workspace's existing rule that agent, recording and keyboard state are
  independent.
- *Keep information, reveal controls.* A minimal pill shows live state: a
  spinner, the recording timer or NAV. Hovering expands it to show its label and
  Stop. Dictation stops by clicking the island or with B, as today.
- *Questions expand.* A new question expands the island downward with its
  answers for five seconds. It then settles into an orange "Needs you" pill,
  and clicking that pill expands it again.
- *Anchor on the centre and give it a floor.* The island stays centred on the
  screen, and its minimum width is the idle readout. That keeps every moment at
  0 px displacement. The outermost detached pills are the only things that shift.
- *Float, keep the edge target.* Draw the glass 8 px below the edge, but let the
  transparent strip above each pill receive clicks. A cursor thrown against
  the top edge still lands on the nearest control.

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

- Should the lower-right agent phase bubbles remain? The expanded island could
  show the current phase instead, so agent progress would live in one place.
- Should the canvas window adopt macOS-style window controls, or keep window
  controls in its options menu?
