# Liquid Glass study

31 October 2026. A design study for restyling Workspace in Apple's current
language. The design is built as a reusable component kit in its own
repository, [JimLundin/liquid-glass](https://github.com/JimLundin/liquid-glass),
which also carries the Workspace demo (`demo/index.html`, no dependencies or
build step). Nothing here changes the Qt runtime yet.

Earlier single-file versions are preserved as tags:

- `liquid-glass-prototype-v1`: the first study.
- `liquid-glass-prototype-v2`: the toolbar pattern comparison, with the
  alternative patterns and the accessibility switches.
- `liquid-glass-prototype-v3`: the island bar, the canvas island, Fluent and the
  sidebar, before the kit.

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
| Desktop bar | One lilac capsule fused to the screen edge with flared shoulders and internal dividers | A floating island alone at rest; only temporary or active things appear beside it. See *Toolbar pattern* |
| "Needs you" | Label in the shared capsule | The island expands into the question, then settles into an orange pill: the bar's only coloured state |
| Controls menu | Qt `QMenu` with a solid background | The island expands into the menu: large glass, an icon per item, an accent highlight row |
| Agent phase bubbles | Lilac bubbles with app palettes | Large regular glass, like macOS notifications. App identity moves to a rounded app badge. Earlier phases collapse and recede. Prominent glass marks the primary answer |
| Work canvas | Lilac-tinted dark window, lilac work bubbles | Neutral content layer with solid cards. App colour appears only in badges and the amber question card. The floating bottom toolbar is the only glass. Soft scroll-edge effects. An inset inspector with a concentric radius slides in from the trailing edge |
| Motion | 160 ms slides and fixed-duration animation | Critically damped springs by default. Bounce only after a throw. Pans project momentum and rubber-band at edges. Every transition can be interrupted |
| Typography | Segoe UI, 12 px | Inter: 12 px in the toolbar, 13 px body, optical sizing, negative tracking on titles |
| Symbols | Hand-drawn Feather-style paths | Lucide at a 1.75 stroke, with a filled variant for active states |

The accent is a soft blue, `#4B8FE8`: lighter and less saturated than system
blue `#0A84FF`. White text on it measures 3.3:1, against 3.65:1 on Apple's
own blue. A lighter mist blue, `#6A9FE0`, was considered; white text on it drops
to 2.75:1.

Decided and removed from the demo: the island pattern (the alternatives live
in the v2 tag), the floating edge, full transparency, motion and refraction,
the clear glass look, Inter and the soft blue accent. The demo no longer offers
switches for these.

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
look-alikes in trademarked uses. The demo's **Compare symbols side by side**
sheet draws six open sets at 16 px beside 12 px Inter, then at 2×:

| Set | Licence | Observation |
| --- | --- | --- |
| Lucide | ISC | 1.75 strokes; the closest weight match to Inter. No filled set |
| Phosphor | MIT | Regular and fill from one design, like SF's `.fill` states; slightly light |
| Tabler | MIT | 1.75 strokes with a filled subset; geometric, a little technical |
| Fluent | MIT | Microsoft's Windows 11 symbols, regular and filled; native to Windows, not to Apple |
| Material Symbols Rounded | Apache 2.0 | A variable system like SF Symbols (weight, fill, grade, optical size); shapes read as Google |
| Iconoir | MIT | Thin 1.6 strokes; elegant large, faint at 16 px |

SF Symbols match their weight to the adjacent text and switch to filled
variants for active states. No open set does both.

**Decision: Fluent** (MIT), Microsoft's Windows 11 symbols, using the 16 px
artwork drawn for toolbar size; only battery, cloud and Wi-Fi off fall back to
the 20 px grid. It looked thin at first because the 20 px artwork was being
scaled to 16 px. Fluent has true filled variants, used for active states such
as the dictation microphone. Stop is a small rounded square, as `stop.fill`
is. Vendor only the paths Workspace uses into `assistant/vector_icons.py`.

## Toolbar pattern

The `liquid-glass-prototype-v2` demo's **Compare toolbar patterns** view ran one scenario through three
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

Measured results (largest leading-button displacement over the scenario):

| Pattern | Floating | Attached | Behaviour |
| --- | --- | --- | --- |
| One capsule | 183 px | 183 px | Every activity widens the one shape |
| Glass groups | 231 px | 252 px | Each activity adds a pill; ambient never yields |
| Island | 0 px for durations; 31 px dictating; 70 px transcribing; 99 px question expanded | same | Moments resize the centre; durations detach |

**Decision: the island, floating, with an edge-to-edge hit target.**

- *Nothing persistent beside the island.* At rest the island stands alone.
  Things appear beside it only while they're temporary or active: the inbox
  while items wait, the keyboard layer, and ongoing work while a moment holds
  the island. Canvas moves into the island's menu as its first item. This
  follows the HIG's guidance to keep bars uncluttered, and Live Activities,
  which exist only while their activity runs.
- *Click the island to act on what it shows.* At rest it expands into the
  Workspace menu, while dictating it stops, and with a question it opens the
  answers. This follows the Dynamic Island, where tapping acts on the current
  activity.
- *Fit the moment.* Dictation shows the microphone and a short live waveform,
  and the island fits it. A fitted island moves the side buttons by half of
  each width change. That cost is accepted for moments that last seconds.
- *Transcription is processing, not a moment.* It shares the agent's spinner in
  the island's leading slot, with the clock still showing, instead of taking
  the whole island over. When transcription and agent work overlap, one spinner
  carries both in its label. The canvas island does the same after you speak.
- *Ongoing work joins the island.* Like a Live Activity's compact
  presentation, agent work takes the island's leading slot (a spinner) and a
  meeting recording its trailing slot (the red dot and timer), around the time
  and battery, so ongoing work grows the centre. A detached pill beyond the
  inbox read as unrelated to the island.
- *Moments push ongoing work out beside the island.* When dictation, a question
  or the menu takes the island over, the agent's spinner detaches to its left
  and the recording to its right, next to the island, as a second Live Activity
  detaches in the Dynamic Island. The inbox stays outermost. In the expanded
  menu, ongoing work appears as live rows at the top, each with its own Stop.
- *The keyboard layer is a mode, not work.* NAV sits as a detached pill on the
  leading side, like the macOS input menu.
- *The recording pill fits its reading.* The timer reads `mm:ss`, then `h:mm:ss`
  after an hour, and its capsule re-measures whenever the reading's length
  changes.
- *Questions expand.* A new question expands the island into a 372 px card with
  28 px corners, a 12 px inset and concentric 32 px answer buttons, for five
  seconds. It then settles into an orange "Needs you" pill that reopens it.
- *Float, keep the edge target.* Draw the glass 8 px below the edge, but let the
  transparent strip above each pill receive clicks. A cursor thrown against the
  top edge still lands on the nearest control.

## What the top bar shows

macOS 26 puts these in its menu bar:

- **Leading:** the Apple menu, then the active app's name and menus.
- **Trailing:** menu bar extras chosen by the person, then the system's Wi-Fi,
  battery, Control Center, Spotlight and Siri, and the date and time. Clicking
  the clock opens Notification Center and widgets. The input source can appear
  as its own extra.
- **Indicators:** while an app uses the microphone or camera, the system shows
  an orange or green privacy indicator. Screen recording, Now Playing and iPhone
  Live Activities add their own items.
- **Not there:** weather and other ambient information live in widgets. The
  menu bar holds controls, status and alerts.

Workspace's bar today (`assistant/bar_model.py`, `assistant/ambient.py`,
`assistant/desktop_bar.py`) and the proposed home for each item:

| Item | Today | Proposed |
| --- | --- | --- |
| Workspace menu | Leading button | The island at rest; clicking it expands the menu |
| Canvas | Leading button beside the menu | First item in the island menu |
| Clock | Resting readout | Island at rest |
| Battery | Resting readout; hidden above 95% on power | Island at rest, same rule |
| Weather | Resting readout | Removed. macOS keeps weather in widgets, and the bar's own rule is "Only active work earns space in the desktop toolbar." |
| Speakers unmuted | Alert glyph in the readout | Island at rest, as an exception glyph |
| Wi-Fi disconnected | Alert glyph in the readout | Island at rest, as an exception glyph |
| Inbox | Bell with count, hidden at zero | Trailing pill with count while items wait; hidden at zero |
| Listening | Microphone, waveform, Stop | Island moment: orange microphone (Apple's microphone-in-use colour) and waveform; Stop on hover or by clicking the island |
| Transcribing | Spinner | Spinner in the island's leading slot, shared with agent work |
| Agent working | "Working" and Stop in the main capsule | Spinner in the island's leading slot; detaches beside the island during a moment; the island menu shows the phase and Stop |
| Needs input | "Needs you" in the main capsule | Island expands into the question, then settles into the orange pill |
| Meeting recording | Separate capsule: timer and Stop | Red dot and timer in the island's trailing slot; detaches beside the island during a moment; the island menu shows Stop. "Starting…", "Stopping…" and "Saving…" replace the timer; "Check recording" tints the pill orange |
| Keyboard layer or Colemak | Separate capsule | Detached minimal pill on the leading side, like the macOS input menu |
| Tiling tab strip | Joins the ambient capsule on the primary screen | Out of scope here. The island should stay centred, with the strip running along the edge around it |

## Sidebar

The demo's controls take the form of a macOS 26 sidebar, the pattern a future
Workspace sidebar should follow:

- It floats in the Liquid Glass layer, inset 8 px from the screen edges, with
  24 px corners. Content extends beneath it.
- A sidebar toggle stays in the same place whether the sidebar shows or not.
  The HIG asks for a show/hide button on macOS. Hiding slides the sidebar out
  along the leading edge, and showing returns it the same way, instead of
  collapsing it into a card. Over the open sidebar the toggle is a plain
  symbol, so glass never sits on glass. Once the sidebar hides, the toggle
  gains its own glass.
- Actions sit at the top. The HIG warns against putting critical actions at the
  bottom of a sidebar, where a moved window can hide them.
- At most two levels of hierarchy: short title-case section headers (Toolbar,
  Surroundings, Symbols) over grouped rows, with a soft scroll-edge fade
  instead of hard clipping.

The agent phase bubbles stay as they are: earlier phases fade and recede as
new ones arrive.

## Appearance and the toolbar

Small glass follows the content beneath it, not the system setting: the HIG
says toolbars and tab bars adapt between light and dark to the underlying
content, and the macOS menu bar flips its text with the wallpaper. Large
surfaces (menus, cards, the canvas, the sidebar) follow the system appearance.
The demo's wallpaper now has light and dark variants that follow the
appearance, as macOS's dynamic wallpapers do, so in light mode the island turns
light because the desktop beneath it does. Over a dark app it stays dark in
either mode.

## Work canvas

The canvas toolbar follows the desktop bar's rule, anchored to the window's
bottom edge:

- *One island at rest, without instructions.* Three symbols: speak, search and
  more. Their tooltips carry the instructions ("Hold N to speak about the whole
  canvas" or about the selected context), because the gesture is learned once.
  Clicking the microphone starts listening and clicking again sends; holding N
  does the same. Search and more expand the island; the menu grows upward.
- *Moments morph the island.* Ctrl+F turns it into a search field; speaking
  shows the microphone, a live waveform and Send; release shows the
  transcription spinner. Ongoing agent work joins the island's leading slot.
- *Only temporary things sit beside it.* A tinted Questions pill with its count
  while questions wait, and a Recenter button only after the view leaves the
  work, as Maps shows its location button.
- *No duplicate Close.* The window's own close control closes the canvas.
- *The toolbar belongs to the content column*, so it recentres beside an open
  inspector.

The inspector stays a floating glass column inset from the window, with
corners concentric to it. Its actions (Ask about this, Open in Edge) now sit
under the title instead of at the bottom, following the sidebar guidance.

Canvas cards are content, so they use a solid material. Agent phase bubbles
and notifications are functional UI, so they're glass. Both share one anatomy:
app badge, title, meta line and body. Workspace's canvas today reuses the
floating notification bubble; under Liquid Glass it should reuse the same
component with the content material.

## Scroll bars

Apple's guidance: a scroll view has no appearance of its own; a translucent
scroll indicator appears once scrolling starts and shows the position in the
content; scrolling keeps its elastic behaviour; cut-off content hints that
there's more; scroll edge effects go only where content passes under floating
controls, one per view. On macOS the indicator is the overlay scroll bar.

The kit's `<lg-scroll>` follows that. Bars are hidden at rest, appear while
content moves and fade 0.9 s after it stops. Hovering thickens the 6 px thumb
to 8 px and shows the track; the thumb drags and the track pages. An edge fades
only when content lies beyond it. The sidebar and the inspector use it. In Qt
this maps to a transient `QScrollBar` overlay rather than today's always-visible
6 px handles.

## Components

The kit encodes these rules as pre-built custom
elements in six tiers, each built only from the tiers before it:
foundations, atoms, controls, molecules, containers and bars. Every component
is a CSS and JS pair in its tier's folder. One stylesheet entry imports each
component into its tier's cascade layer, so precedence follows the tiers
rather than selector specificity. One script entry loads everything in tier
order. `tools/check_structure.py` fails when a component isn't wired into
both entries. The gallery shows each tier on its own; the Workspace demo
composes the elements and holds only Workspace's behaviour and content. The
kit's README documents the conventions and how to add a component.

Rules that became explicit while building it:

- *Glass never sits on glass.* Buttons inside the sidebar, the inspector and
  the agent cards are filled, not glass.
- *Rim light follows the tint.* On tinted glass the rim fades to a faint return
  at the trailing foot instead of a white glare.
- *Text never reflows mid-morph.* Expanded content lays out at its final size,
  and a capsule follows its content's width whenever it changes, so a growing
  timer or a late font pushes its neighbours out instead of overlapping them.

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


- Should the canvas window adopt macOS-style window controls, or keep window
  controls in its options menu?
