# The island bar

Workspace's desktop control surface is a floating island at the top of the
primary screen, in the Liquid Glass design
([design note](design/liquid-glass.md), kit at
[JimLundin/liquid-glass](https://github.com/JimLundin/liquid-glass)). The island
stays centred 8 px below the screen edge. Only temporary or active things sit
beside it, and every capsule acts on what it shows.

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
3. **At rest, activities join the island.** The agent's spinner and phase lead,
   then a job's dots, the time and battery, and the recording last. During a
   moment they detach beside the island as compact capsules in the same order;
   a detached agent keeps its phase in its label.
4. **Only temporary or active things sit beside the island:** the keyboard layer
   before it, the inbox after it while items wait. Nothing persistent, nothing
   decorative.
5. **Each activity that can stop reveals Stop under the pointer.** A quick job
   can't be stopped, so it has no Stop.
6. **Each fact has one owner, and only that owner changes it.** Dictation and
   quick jobs come from the voice controller (`Desktop.busy`), the agent's phase
   from its live session (the step it is running, or the heading of its latest
   reasoning summary), the recording from meetings, the inbox from triage and
   the layer from the keyboard. Notifications are cards, never bar content.

| Situation | Island | Beside it |
| --- | --- | --- |
| Rest | Time and battery, with speaker and Wi-Fi alerts before them | — |
| Agent working | Spinner and phase lead; hovering reveals Stop | — |
| Quick job | Pulsing dots before the time | — |
| Meeting recording | Red dot and timer last; hovering reveals Stop | — |
| Dictating | The live microphone and its trace; no text | Agent, job and recording, detached |
| A question waits | "Needs you", tinted orange | Job and recording, detached |
| Items wait in the inbox | — | A bell with a count badge, last |
| Temporary layer or layout off | — | The layer name (or Colemak), first |

"Starting…", "Stopping…" and "Saving…" replace the recording's timer; "Check
recording" turns it red and the detached capsule orange.

Pressing the island at rest expands it into the controls menu: 272 px wide with a
21 px radius, its rows concentric inside it. Running activities lead as live rows
with their own Stop, the agent's with its phase; the detached agent and recording
capsules leave the bar while the menu is open. The canvas comes first, then the feed and recording, the
keyboard, and the desktop tools. Window tiling discloses its items in place.
Arrows wrap and skip separators, Right and Left open and close tiling, Enter
chooses, a letter jumps to the next row starting with it, and Escape closes.
Opening the menu takes the keyboard; a window tool, a quiet toggle or Escape hands
it back to the window that had it, a Workspace view keeps it, and clicking
elsewhere closes the menu without taking it back. Window tools act on the window
captured as the menu opened. Large glass is thicker than the capsules, so the
menu's text stays legible over any desktop.

Pressing the island while dictating stops dictation; pressing "Needs you"
opens the question. The recording opens the canvas, the layer opens the key map
and the bell opens the inbox. The bell's badge reads `99+` above 99; its tooltip
and accessible name keep the exact count and the **Hold V + T** shortcut. Hold
V + T opens the same inbox while the layout is on, including when no bell shows.
Space holds dictation; B toggles dictation; N toggles agent speech.

## Shape

Capsules are 34 px tall with fully round ends. A control is a 28 px circle,
concentric 3 px inside its capsule's edge. Text is Inter at 12 px, medium weight,
with tabular figures so a running timer keeps its width. Text content pads 12 px;
slots and side-by-side readings sit 12 px apart; a symbol sits 6 px from its text.
Icon-only content pads 10 px and is never narrower than a circle. Symbols are
16 px Fluent UI System Icons.

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
spinners, dots and the trace repaint only their own rectangles. Looks and colours
are cached values, so a frame builds only its motion records.

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
through to the desktop; capsules paint an invisible hit fill. Behind it, one
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
above 95% while plugged in hides its percentage and keeps the charger symbol.
Power refreshes every fifteen seconds; the clock follows the local minute.

The speaker and Wi-Fi alerts show an unmuted default playback endpoint and Wi-Fi
adapters with none associated. Unknown readings and absent adapters imply no fault.
A background worker refreshes them once per second without opening an audio
stream or scanning for networks.

The microphone trace is 18 bars of real RMS levels, read every 50 ms only while
dictating, off Qt's thread. `waveInGetPosition` marks recorded data in the same
PCM buffer used for transcription; each read copies at most 40 ms. Silence stays
flat, and an unavailable meter doesn't simulate activity. The spinner turns on the
existing frame loop only while work runs; reduced motion holds it still. No frame
timer runs at rest.

## References

- [Apple: Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars):
  deliberate item selection, logical grouping and familiar symbols.
- [Apple: Live Activities](https://developer.apple.com/design/human-interface-guidelines/live-activities):
  compact, minimal and expanded presentations, and independent simultaneous activities.
- [Apple: Materials](https://developer.apple.com/design/human-interface-guidelines/materials):
  Liquid Glass for the functional layer, tint only for meaning.
