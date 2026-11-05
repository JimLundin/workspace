# The island bar

The bar is a row of glass capsules 8 px below the top of the primary screen.
Its centre holds only live activity and is empty at rest. Left of it, one
capsule holds Canvas, then the Outlook and Teams web-app slots; the desktop
pager and the running apps follow in their own capsules. One fixed capsule on
the right holds the keyboard state when relevant (the layout switched off, or
a temporary layer held), then volume, Wi-Fi, and the clock with the battery.
Activity never moves the fixed controls.

The right capsule is anchored to the screen's right edge, so the keyboard
state widens it leftwards and the controls after it keep their places once it
settles. Nothing is reserved for the keyboard state at rest; while the capsule
springs to its new width, its content cross-fades centred in it, so the other
controls slide briefly. Canvas lives in the shell's pinned capsule, which
yields to activity: the island bounds where it ends, as it does for the pager
and running apps, and like them it has no edge strip to the top of the screen.

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
   session (`island_agent`), the recording from meetings, the inbox from
   pending questions and unread notices, and the layer from the keyboard.
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
holding **. + K**. The bell and **Hold . + X** open the inbox list. Pressing a
notice opens the canvas at its item. Notices never take keyboard focus.

## The controls menu

Pressing the clock or battery opens the menu in place. It holds a card per
running activity, toggles (Auto-record Teams, keyboard overlay, Windows
taskbar, window placement, dark when away), the Canvas tile, **Record a
meeting**, a volume slider, small tools (switch windows, copy transcript, key
map), the system tray icons, and links to Windows notification settings and the
tray menu. `island_menu.entries` is the source of truth. Arrows move between
cells, Enter chooses, and Escape closes.

## Code

`island_moment`, `island_agent`, `island_model`, `island_menu`,
`island_layout`, `island_motion` and `plain_text` in `desktop_ui/` are pure
decisions. `DesktopBar` owns observations and timers, `island_surface` owns the
Qt window and its native glass, `shell_surface` draws Canvas with the pinned
slots, the pager and the running apps, and `request_panel` draws the expanded
request and inbox. `scripts/benchmark_island.py` measures frame cost.
