# The island bar

The bar is a row of glass capsules 8 px below the top of the primary screen.
Its island holds only live activity and is empty at rest; it sits directly left
of the fixed right capsule, one gap away. Left of it is the bar's only toolbar, the desktop pager: each desktop as its apps' icons,
side by side a small gap apart, left to right as they sit on screen. A desktop shows the apps its
layout puts there, running or not (a web app's symbol fills while it runs), and
any other app placed there. A click on an icon goes to that app, cycling its
windows or starting it, and so to its desktop; a right click lists its windows.
The current desktop is marked, an empty desktop
shows its number only while it is current, and holding the Apps key shows each
desktop's letter. One fixed capsule on
the right holds a keyboard icon while the keyboard types plainly (the layout
is off, or the Charybdis is connected), volume, Wi-Fi, the battery,
processor and memory use, and the day, date and time at the far right. Workspace's
own glyph leads it. Each reading opens its own panel (see below). Activity never
moves the fixed controls.

The capsule follows a menu bar's restraint: symbols drawn at the text's weight,
plain text for the clock, and the battery as a symbol filled to its charge
(red when low on its own power, a bolt cut into it while on mains power).
Each meter reads value first, then its symbol, as a menu bar's battery does.

Space alone separates things, with no dividers: every two of the right
capsule's readings sit one even gap apart, and in the pager a desktop's apps sit
close together while desktops sit a wider gap apart. The current desktop has a
dot under its apps, and the pointer lights only the app under it.

The resource readings are the processor's percentage and the gigabytes of
memory in use (the tooltip adds how many are installed), each before its
symbol and beside the battery's, so the machine's readings sit together, and the
clock closes the capsule at the screen's edge where it is easiest to find. Each
reserves its widest form ("100%", "00.0 GB") so a changing value never moves
the cluster, and its digits keep to the right of that room, against their
symbol. Each reading is its own slot, so every two sit the same gap apart. An unread value shows "—" rather than 0. The status worker reads
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

## The panels

Pressing a reading expands the capsule into that reading's panel, in place;
pressing another reading switches to its panel, and pressing the open one
closes it. The readings stay the panel's top row.

| Pressed | Panel |
| --- | --- |
| Workspace's glyph, the keyboard, or an activity | Workspace's controls: a card per running activity, toggles (keyboard overlay, window placement, dark when away), **Record a meeting**, a volume slider, small tools (switch windows, copy transcript, key map), the system tray icons, and links to Windows notification settings and the tray menu |
| The speaker | Its volume slider and Mute |
| Wi-Fi | The networks in range, the connected one first, each with its signal, name and state, and a link to Windows' Wi-Fi settings |
| Processor or memory | A line graph of each over the last two minutes, under its latest reading |
| The battery | Its charge over whether it charges or how long it lasts, and a link to Windows' power settings |
| The clock | The month, today on the accent; its arrows, or Left and Right, turn the months, and its heading, or Enter, returns to today |

A saved Wi-Fi network joins in place; any other opens Windows' Wi-Fi settings,
which own passwords and new networks. The networks are read only while their
panel is open. Windows lists them to desktop apps only while location services
are on for them; until then the panel offers the location settings instead.

`CONTROLS` in `desktop/bar.py` is the source of truth: each panel's rows, their
order, each cell's span, label and symbol; `ISLAND.status.opens` says which
panel each reading opens. Arrows move between cells, Enter chooses, and Escape
closes.

## Code

What the status capsule shows and in what order, and which side of the
island each activity steps aside to, are `ISLAND` in `desktop/bar.py`.
Every size the bar lays out and paints is `SIZES` there too. Each is one frozen
constant that mypy checks, in the shape the code that reads it declares
(`desktop_ui/island_model.py`, `island_menu.py`, `island_layout.py`), and
`desktop/__main__.py` hands them to the bar.

`island_model`, `island_menu`, `island_layout`, `island_motion`, `month` and
`bar_events` in `desktop_ui/` are pure decisions. `DesktopBar` owns
observations and timers, `island_surface` owns the Qt window and its native
glass, and `shell_surface` draws the pager.
