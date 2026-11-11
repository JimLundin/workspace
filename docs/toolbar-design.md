# The island bar

The bar is a row of glass capsules 8 px below the top of the primary screen.
Its island holds only live activity and is empty at rest; it sits directly left
of the fixed right capsule, one gap away. Left of it is the bar's only toolbar, the desktop pager: each desktop as its apps' icons,
overlapping left to right as they sit on screen. A desktop shows the apps its
layout puts there, running or not (a web app's symbol fills while it runs), and
any other app placed there. A click on an icon goes to that app, cycling its
windows or starting it, and so to its desktop; a right click lists its windows.
The current desktop is marked, an empty desktop
shows its number only while it is current, and holding the Apps key shows each
desktop's letter. One fixed capsule on
the right holds a keyboard icon while the keyboard types plainly (the layout
is off, or the Charybdis is connected), volume, Wi-Fi, the battery,
processor and memory use, and the clock at the far right behind a clock symbol. Activity never moves the fixed controls.

A hairline rule divides the right capsule's groups (the keyboard, volume and
Wi-Fi; processor, memory and power; the clock) and stands between each two
desktops in the pager, so neighbouring symbols read as separate facts.

The resource readings are a processor and a memory symbol, each followed by
its percentage, right after the battery's, so the machine's readings sit
together, and the clock closes the capsule at the screen's edge where it is easiest to find. Each reserves "100%" so a changing value never moves the
cluster, and an unread value shows "—" rather than 0%. The status worker reads
them every 2 s; CPU is the busy share of processor time since the previous
reading. Disk, network and GPU are left out: on this laptop they are idle or
bursty, so a number there is mostly noise.

The right capsule is anchored to the screen's right edge. The pager yields to
activity: the island bounds where it ends, and it scrolls instead of dropping
desktops.

## What the bar shows

1. **The island is your point of attention.** Dictation shows where you
   dictate: the dictation marker beside the caret (see
   [GLOSSARY](../GLOSSARY.md)). Only when there is nothing to mark, as when
   you dictate from Workspace's own windows, does dictation take over the
   island as the live microphone trace. Pressing it stops dictation.
2. **Activities run concurrently, each with one look.** Transcription is three
   pulsing dots. A meeting recording is a red dot with its timer. While you
   dictate they detach beside the island as compact capsules.
3. **Stoppable activities show Stop under the pointer.**
4. **Each fact has one owner.** Dictation and transcription come from the
   dictation keys (`assistant.features`), the recording from meetings. Windows
   notifications never show in the bar.

| Situation | Island | Beside it |
| --- | --- | --- |
| Rest | Empty | Fixed controls only |
| Transcribing or recording | The activity | |
| Dictating | The live microphone trace | Activities, detached |

## The controls menu

Pressing the clock or battery opens the menu in place. It holds a card per
running activity, toggles (keyboard overlay, window
placement, dark when away), **Record a meeting**, a volume slider, small tools (switch windows, copy transcript, key
map), the system tray icons, and links to Windows notification settings and the
tray menu. `CONTROLS` in `desktop/bar.py` is the source of truth: its rows, their order, each cell's span, label and symbol. Arrows move between
cells, Enter chooses, and Escape closes.

## Code

What the status capsule shows and in what order, and which side of the
island each activity steps aside to, are `ISLAND` in `desktop/bar.py`.
Every size the bar lays out and paints is `SIZES` there too. Each is one frozen
constant that mypy checks, in the shape the code that reads it declares
(`desktop_ui/island_model.py`, `island_menu.py`, `island_layout.py`), and
`desktop/__main__.py` hands them to the bar.

`island_model`, `island_menu`, `island_layout`, `island_motion` and
`bar_events` in `desktop_ui/` are pure decisions. `DesktopBar` owns
observations and timers, `island_surface` owns the Qt window and its native
glass, and `shell_surface` draws the pager.
