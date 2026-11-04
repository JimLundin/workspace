# The island bar

Workspace's desktop control surface is a floating island at the top of the
primary screen, in the Liquid Glass design
([design note](design/liquid-glass.md), kit at
[JimLundin/liquid-glass](https://github.com/JimLundin/liquid-glass)). The island
stays centred 8 px below the screen edge where space permits. Its centre contains
only live activity and is empty at idle. The icon-only Canvas button is the
furthest-left toolbar control, then the pinned Outlook and Teams slots, the
desktop pager and the running applications.
The fixed right cluster reads icon-only keyboard when relevant, then volume,
Wi-Fi and clock/power at the far right. The system tray's icons live in the
controls menu. Activity never moves the fixed controls. Tooltips and accessible
names preserve their meanings. Activity is bounded to the remaining space on
narrow screens; unfit capsules are omitted rather than overlapping hit targets.
App overflow scrolls.

## What the bar shows

The bar is the application's main surface: it is where Workspace shows what it
is doing for you. Its policy decides what may change it.

1. **The island is your point of attention.** Only a *moment* takes it over:
   something live from you (dictation) or waiting on you (a question). Dictation
   wins over a question; the question then waits beside it, tinted.
2. **Activities run concurrently, each with one identity wherever it shows.**
   Agent work is a ring spinner with its current phase. A quick job is three
   pulsing dots: transcription after dictation, or a rewrite or question about
   the selection or screen. A meeting recording is a red dot with its timer.
   They never stand in for each other, and any combination can run at once.
3. **Activities alone join the island.** The agent's spinner and phase lead,
   then a job's dots, and the recording last. During a moment they detach beside
   it as compact capsules; a detached agent keeps its phase in its label.
   Clock, power and device status never enter the activity centre.
4. **Pending clarifications are dynamic:** their bell sits beside activity,
   or near the centre by itself. Keyboard state is temporary but belongs to
   the fixed right cluster, with its layer/Colemak reading in the icon's label.
5. **Agent work keeps Stop visible**, so hovering does not change its width.
   Other stoppable activities reveal Stop under the pointer. A quick job has no Stop.
6. **Each fact has one owner, and only that owner changes it.** Dictation and
   quick jobs come from the voice controller (`Desktop.busy`), the agent's phase
   from its live session (the step it is running, or the heading of its latest
   reasoning summary), the recording from meetings, the inbox from pending
   questions and the layer from the keyboard. Routine notifications stay quiet.

| Situation | Island | Beside it |
| --- | --- | --- |
| Rest | Empty | Fixed navigation, volume, Wi-Fi and clock/power on the right |
| Agent working | Spinner, phase and Stop | — |
| Quick job | Pulsing dots | — |
| Meeting recording | Red dot and timer last; hovering reveals Stop | — |
| Dictating | The live microphone and its trace; no text | Agent, job and recording, detached |
| A question waits | "Needs you", tinted orange | Job and recording, detached |
| Items wait in the inbox | — | A bell with a count badge, last |
| Temporary layer or layout off | — | Keyboard icon in the right cluster; layer/Colemak in tooltip and accessible name |

"Starting…", "Stopping…" and "Saving…" replace the recording's timer; "Check
recording" turns it red and the detached capsule orange.

Pressing the right-hand clock/power readings expands that capsule into the
controls menu, still anchored 12 px from the right edge: 320 px wide with a
21 px radius. Its readings stay in place as its top row, in place of a heading.
The keyboard icon moves left with
its widening edge. Dynamic elements keep the centre; a question still expands
the centre island.

The menu is a grid of tiles on eight narrow columns, after the Control Center
pattern; tray icons take one column and other tiles span pairs:

| Section | Cells |
| --- | --- |
| Activities | One full-width card per running activity, with its reading and Stop |
| Settings and views | Auto-record, keyboard overlay, Windows taskbar, window placement and dark-when-away toggles beside Canvas and Feed tiles |
| Recording | Record a meeting, absent while one runs |
| Sound | The speaker level as a slider; its symbol shows mute |
| Tools | Switch windows, transcript and key map as small tiles |
| System tray | Each tray application's own icon, eight to a row, absent with no tray |
| Links | Windows notification settings and all Workspace controls |

The detached agent and recording capsules leave the bar while the menu is open.
Toggles show their state in an accent circle and words, and apply in place: the
menu stays open. Dark when away reads its idle delay, such as "External · 2 min
idle", while it's on. Dragging or pressing the slider sets the volume; the toolbar's
status worker applies the latest level, because Windows' audio interfaces need
a multithreaded COM apartment that Qt's thread cannot join.
Arrows move to the nearest cell in their direction; Up and Down wrap. On the
slider, Left and Right step the volume by 5%. Enter chooses, a letter jumps to
the next cell starting with it, and Escape closes the menu.
Menu cells do not inherit an Escape tooltip from the island.
Opening the menu takes the keyboard; a window tool, a quiet action or Escape hands
it back to the window that had it, a Workspace view keeps it, and clicking
elsewhere closes the menu without taking it back. Window tools act on the window
captured as the menu opened. Large glass is thicker than the capsules, so the
menu's text stays legible over any desktop.
The idle bar starts with native activation disabled, preserving the active
application before an icon click. Menu opening enables activation; closing
restores the idle policy.

Pressing the island while dictating stops dictation; pressing "Needs you"
expands the island to present the complete request. The bell and Hold V + T use
the same expansion. The request has voice guidance or explicit approval controls,
plus an optional canvas icon that opens the exact contribution. Reviewing a
request does not open the canvas. Escape or clicking elsewhere closes it.
The recording opens the canvas and the layer opens the key map.
The bell's badge reads `99+` above 99; its tooltip
and accessible name keep the exact count and the **Hold V + T** shortcut. Hold
V + T opens the same inbox while the layout is on, including when no bell shows.
Space holds dictation; B toggles dictation; N toggles agent speech.

Outlook and Teams on the web have fixed slots of their own, shown whether or
not they run. Each is a chromeless Edge app window (`msedge --app=<url>`) in the
user's own signed-in profile, not the desktop app and not the agent's background
tabs. A slot claims a window by Edge's AppUserModelID for that app, exactly or
followed by `.<profile>`; the ordinary Edge window reads `MSEdge` and stays with
the running applications, which never also show a slot's windows. Slots use the
Fluent mail and chat symbols in the bar's ink, filled while a window is open.
With windows, a slot behaves as an application below. Without one, clicking it
launches the app window; further clicks wait up to 15 seconds for that window
rather than opening another. A missing Edge is reported as a problem.
Slot windows lose Edge's caption so they read as part of Workspace. Edge paints
it inside the client area, so removing `WS_CAPTION` changes nothing; instead the
observer gives each window a region starting below the DWM caption-button bounds.
Each poll compares that region with the window's current one and rewrites it only
when the size or caption changed, since an applied region survives maximizing.
Slot windows are placed like every other managed window, measured by the part
their region leaves visible (see [window placement](window-placement.md)), and
keep their region on every desktop. Windows that stop being slots, and all of
them when Workspace exits, get their whole region back.

The desktop pager follows the slots in its own capsule: a previous chevron, one
number per desktop and a next chevron. The current desktop has the quiet
selection fill. Each number's tooltip and accessible name read the desktop and
the apps placed on it, such as "Desktop 1 (current) · windowsterminal, code,
Teams". While the Apps layer is held or locked, every target shows the physical
keycap that reaches it instead, read from the layout. A pager of one desktop is
hidden. A horizontal scroll over any capsule (tilt wheel, Shift+wheel or a
touchpad) steps one desktop per gesture; a gesture ends after 0.35 s without
wheel events. A switch made elsewhere, such as Win+Ctrl+arrow, shows within a
poll.

Running applications have one icon per executable, gathered from every desktop.
Clicking switches to that app, first switching to its desktop; further clicks
cycle its windows in a stable order. Right-click lists its current windows. A
background observer refreshes windows once per second and
copies newly seen icons away from Qt's animation and audio thread. The current
app has a quiet selection fill. The running section scrolls horizontally when crowded; the slots sit in their
own capsule and never scroll.
Its foreground stays transparent over the same native glass and rim as the
island; solid and high-contrast modes use the island's shared surface colours.

Tray icons come from live Windows registration messages, including tooltip,
image, visibility and callback/version changes. In the menu, a click or Enter
sends the registered application a left click and a right click opens its own
menu; either closes the controls menu without taking the keyboard back, so the
application receives it. While the menu is open, Workspace answers each icon's
position query with its cell; after it closes, the last positions stand, so a
flyout anchors where its icon was. The hidden native tray proxy forwards
shell messages to Explorer, broadcasts TaskbarCreated at startup/shutdown, and
is excluded from taskbar hiding and recovery. Closing Workspace removes it.
Registry history is not used to invent live icons.

Native fixtures cover real registration/update/removal, callback delivery,
popup position, restoration, legacy icon masks and scroll overflow. Pure checks
cover stable app/window order and tray field/version policy. The app/tray mutation
campaigns detected all five seeded defects, with passing baselines and no
survivors, timeouts or collection errors. Reports are in Windows Temp as
`workspace-app-mutations.json` and `workspace-tray-mutations.json`. A separate
live Windows probe observed three running-app groups and eight registered tray
icons; all eight tray images copied successfully. Python and Qt primitives,
Windows enumeration and icon painting remain trusted dependencies.

## Shape

Capsules are 34 px tall with fully round ends. A control is a 28 px circle,
concentric 3 px inside its capsule's edge. Text is Inter at 12 px, medium weight,
with tabular figures so a running timer keeps its width. Text content pads 12 px;
slots and side-by-side readings sit 12 px apart; a symbol sits 6 px from its text.
Icon-only content pads 10 px and is never narrower than a circle. Symbols are
16 px Fluent UI System Icons.

The slots, pager and running applications are capsules of such controls. The
end controls sit 3 px inside, and neighbours sit 6 px apart, so each control is
centred in a 34 px cell, as a lone control is in its own capsule. Their faces
match the symbols beside them. An application's icon shows at 16 px, copied at
the size the window supplies and drawn on whole device pixels. A desktop number
or keycap uses the text style, and a keycap wider than a circle widens its
control into a pill with the same 6 px inset as a symbol. The bar paints these
controls itself, so no stylesheet can resize them.

The bar owns the spacing between capsules: each neighbouring pair is 6 px apart,
scaled by the less present of the two, so a capsule entering or leaving opens and
closes the space beside it. Each capsule also owns a strip from the screen edge
down to its glass, so a pointer thrown against the top of the screen lands on it.
Edges snap to device pixels, shared by Qt and composition.

[Island states with the solid material](images/workspace-island.png): rest,
agent work, agent work under the pointer, a recording, dictation with a
recording and inbox, a waiting question, and a locked layer with a full inbox.

## Motion

Capsules move on springs, described as Apple does by a damping ratio and a
response: a width morphs at (0.86, 0.42 s), an arriving capsule grows from
nothing at (0.78, 0.42 s) with a little overshoot, and a leaving one collapses
critically damped at (1.0, 0.3 s), keeping its last content until it's gone.
Springs advance in closed form, so a stalled frame lands exactly where the
spring would be. Any change retargets from the value and velocity on screen;
a capsule called back while leaving reverses without a flicker. New parts fade
in over the previous ones at their own measured size, centred while the width
morphs; a reading whose text changes, such as the timer, updates in place.

The frame loop runs only while a spring moves or the spinner turns, and holds a
fine timer resolution only while springs move. Windows' reduced-motion setting
moves every capsule straight to its target, including mid-flight.

`scripts/benchmark_island.py` drives the real bar and glass through agent work with a
transcription, dictation beside both with a recording and inbox, a question and
rest. On this laptop a frame takes about 1.3 ms at the median and 3.2–3.8 ms at
the 95th percentile, and peaks at about 4 KB of transient allocation; no frames run
at rest. Bar code is about a quarter of that (0.3 ms median, 0.7 ms p95); the rest
is Qt's native painting and its layered-window flush.

Three measured choices keep it there. Glass writes go straight through IVisual's
COM slots: win32more's generic dispatch costs 44 µs per write, a slot call 2.2 µs.
Each capsule renders its still content once and blits it while its shape morphs;
spinners, dots and the trace repaint only their own rectangles. Immutable looks
are cached; each painter adapts their shades into its own native colours.

## Material

Glass has no colour of its own. Small glass takes its scheme from the desktop
beside the island, sampled off the UI thread: dark ink over a bright desktop, a
thin dark veil over a uniformly dark one, and a heavier veil over a mixed desktop
so small text stays legible. Colour appears only for meaning: orange when a
question waits, red for recording and a low battery, and the microphone's amber
while it listens. A rim light runs brightest along the upper-leading curve.

Windows' Reduce Transparency setting gives solid capsules. High contrast uses
the system window and text colours, swapping them on a tinted capsule so a
waiting question still stands out; every reading keeps the system foreground.

## Architecture

One screen-wide, translucent Qt window (titled "Workspace floating bar") holds a
child widget per capsule and a child button per control, so each keeps its
accessible name, tooltip and keyboard focus. Its transparent pixels pass clicks
through to the desktop; capsules paint an invisible hit fill. The glass host
behind it is layered and `WS_EX_TRANSPARENT`, with opacity initialized to 255,
so Windows skips it for input even when the target belongs to another process.
`WS_EX_NOREDIRECTIONBITMAP` keeps its pixels supplied by composition. One
composition window (`GlassScene`) holds a pooled group of native visuals per
capsule: a rounded clip, the blurred host backdrop, a tint, the rim and a shadow.
Expression animations derive the geometry, corner radius, rim and shadow from
each group's offset, size and opacity, so publishing a frame writes only those
three properties. Changes within one Qt turn publish one final glass frame, and
capsule changes never move a window.

`island_model` turns observations into capsule views, `island_menu` holds the
menu's entries and navigation, `island_layout` arranges parts, rows and capsules,
`island_motion` and `motion` carry capsules between views, and
`ui_components.appearance.look` decides how each reads. All are pure. `DesktopBar` owns the observations and timers, and
`island_surface` owns the Qt window and glass.

## Observations

Windows `GetSystemPowerStatus` supplies battery percentage, charging and external
power. Unknown readings show a dash; machines without a battery show AC. A battery
keeps its percentage visible even when full or plugged in, alongside the charger
symbol when powered. Reserved clock and battery widths keep the combined
speaker/Wi-Fi/clock/power capsule stable across readings.
Power refreshes every fifteen seconds; the clock follows the local minute.

Volume and Wi-Fi indicators are always visible in independent fixed slots.
The volume icon shows the observed default playback endpoint as unmuted or muted;
unavailable observations use a speaker with a question badge, never a mute icon.
Wi-Fi shows connected or disconnected association. Unavailable readings use a
Wi-Fi question badge; no adapter uses a Wi-Fi minus badge. They are indicators,
not buttons: the capsule's accessible name and tooltip carry both states, and
pressing anywhere on it opens the controls menu, whose sound slider sets the
volume. Connected Wi-Fi does not claim Internet reachability.
A background worker refreshes them once per second without opening an audio
stream or scanning for networks.

The microphone trace is 18 bars of real RMS levels, read every 50 ms only while
dictating, off Qt's thread. `waveInGetPosition` marks recorded data in the same
PCM buffer used for transcription; each read copies at most 40 ms. Silence stays
flat, and an unavailable meter doesn't simulate activity. Qt interpolates between
observed traces on its precise 16 ms frame loop, without repeating unchanged
layout or glass publication. Spinners use that loop too; incoming observations
preserve its next deadline. Reduced motion shows samples directly and holds
spinners still. No frame timer runs at rest. Native menu activation settles for
one frame before an inactive window dismisses its menu.

See [the native animation investigation](qt-animation-performance.md) for the
shared scheduling, text-layout and activation fixes and their measured limits.

## References

- [Apple: Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars):
  deliberate item selection, logical grouping and familiar symbols.
- [Apple: Live Activities](https://developer.apple.com/design/human-interface-guidelines/live-activities):
  compact, minimal and expanded presentations, and independent simultaneous activities.
- [Apple: Materials](https://developer.apple.com/design/human-interface-guidelines/materials):
  Liquid Glass for the functional layer, tint only for meaning.
