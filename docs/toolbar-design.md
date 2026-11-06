# The island bar

The bar is a row of glass capsules 8 px below the top of the primary screen.
Its centre holds only live activity and is empty at rest. Left of it is the
bar's only toolbar, the desktop pager: each desktop as its apps' icons,
overlapping left to right as they sit on screen. A desktop shows the apps its
layout puts there, running or not (a web app's symbol fills while it runs), and
any other app placed there. A click on an icon goes to that app, cycling its
windows or starting it, and so to its desktop; a right click lists its windows.
Canvas is desktop 1's icon. The current desktop is marked, an empty desktop
shows its number only while it is current, and holding the Apps key shows each
desktop's letter. One fixed capsule on
the right holds a keyboard icon while the keyboard types plainly (the layout
is off, or the Charybdis is connected), volume, Wi-Fi, the clock with the
battery, and processor and memory use. Activity never moves the fixed controls.

The resource readings are a processor and a memory symbol, each followed by
its percentage, right after the battery's, so the machine's readings sit
together at the capsule's right end. Each reserves "100%" so a changing value never moves the
cluster, and an unread value shows "—" rather than 0%. The status worker reads
them every 2 s; CPU is the busy share of processor time since the previous
reading. Disk, network and GPU are left out: on this laptop they are idle or
bursty, so a number there is mostly noise.

The right capsule is anchored to the screen's right edge. The pager yields to
activity: the island bounds where it ends, and it scrolls instead of dropping
desktops.

## What the bar shows

1. **The island is your point of attention.** Only a *moment* takes it over:
   dictation (live from you), a question (waiting on you) or a notice (news for
   you). Dictation wins over a question, and both win over a notice. A notice
   is the agent's finished reply, or a canvas finding or question it announces.
   Each is announced once. It waits while a higher moment or an open menu,
   request or bell list holds the island, then shows for 6 s
   (`island_moment.SHOWN`). It stays while the pointer is over it and collapses
   1.5 s after the pointer leaves. A notice that waited more than 30 s goes
   straight to the bell. Unread notices add to the bell's count.
2. **Activities run concurrently, each with one look.** Agent work is a
   spinner with its current phase. Transcription is three pulsing dots. A
   meeting recording is a red dot with its timer. During a moment they detach
   beside it as compact capsules. Under the pointer, agent work shows up to
   three earlier steps.
3. **Agent work keeps Stop visible.** Other stoppable activities show Stop
   under the pointer.
4. **Each fact has one owner.** Dictation and transcription come from the voice
   controller (`Desktop.busy`). The agent's phase and news come from its
   session (`island_agent`), the recording from meetings, and the inbox from
   pending questions and unread notices.
   Windows notifications never become notices.

| Situation | Island | Beside it |
| --- | --- | --- |
| Rest | Empty | Fixed controls only |
| Agent working | Spinner, phase and Stop | |
| A notice | Title and up to two lines, 340 px wide | Activities, detached |
| Dictating | The live microphone trace | Activities, detached |
| A question waits | "Needs you", tinted orange | Activities, detached |
| Items wait in the inbox | | A bell with a count |
| The bell list is open | Questions and the five latest notices | |

Pressing "Needs you" expands the island to show the question. Answer it by
holding **X + K**. The bell and **Hold X + M** open the inbox list. Pressing a
notice opens the canvas at its item. Notices never take keyboard focus.

## The controls menu

Pressing the clock or battery opens the menu in place. It holds a card per
running activity, toggles (Auto-record Teams, keyboard overlay, Windows
taskbar, window placement, dark when away), the Canvas tile, **Record a
meeting**, a volume slider, small tools (switch windows, copy transcript, key
map), the system tray icons, and links to Windows notification settings and the
tray menu. `desktop_ui/spec/controls.py` is the source of truth: its rows, their order, each cell's span, label and symbol. It reloads live like the other specs. Arrows move between
cells, Enter chooses, and Escape closes.

## Code

What the status capsule shows and in what order, and which side of the
island each activity steps aside to, are in `desktop_ui/spec/island.py`.
Every size the bar lays out and paints is in `desktop_ui/spec/sizes.py`.
Each spec is one frozen value that Pyright checks; the types in `ui_spec` and
beside their users check ranges and rules. The running bar re-imports its specs
when their files change (`ui_spec_watch`) and re-lays itself out, without a
restart. A spec that doesn't import or check is reported and the bar keeps its
last good one.

`island_moment`, `island_agent`, `island_model`, `island_menu`,
`island_layout`, `island_motion` and `plain_text` in `desktop_ui/` are pure
decisions. `DesktopBar` owns observations and timers, `island_surface` owns the
Qt window and its native glass, `shell_surface` draws the pager, and `request_panel` draws the expanded
request and inbox. `scripts/benchmark_island.py` measures frame cost.
