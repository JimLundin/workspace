# The island bar

The bar is a row of glass capsules 8 px below the top of the primary screen.
Its centre holds only live activity and is empty at rest. Left of it is the
bar's only toolbar, the desktop pager: each desktop as its apps' icons,
overlapping left to right as they sit on screen. A desktop shows the apps its
layout puts there, running or not (a web app's symbol fills while it runs), and
any other app placed there. A click on an icon goes to that app, cycling its
windows or starting it, and so to its desktop; a right click lists its windows.
The current desktop is marked, an empty desktop
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

1. **The island is your point of attention.** Only dictation, live from you,
   takes it over, as the live microphone trace. Pressing it stops dictation.
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
running activity, toggles (keyboard overlay, Windows taskbar, window
placement, dark when away), **Record a meeting**, a volume slider, small tools (switch windows, copy transcript, key
map), the system tray icons, and links to Windows notification settings and the
tray menu. `CONTROLS` in `desktop_ui/island_menu.py` is the source of truth: its rows, their order, each cell's span, label and symbol. Arrows move between
cells, Enter chooses, and Escape closes.

## Code

What the status capsule shows and in what order, and which side of the
island each activity steps aside to, are `ISLAND` in `desktop_ui/island_model.py`.
Every size the bar lays out and paints is `SIZES` in `desktop_ui/island_layout.py`.
Each is one frozen constant that Pyright checks, beside the code that reads it.

`island_model`, `island_menu`, `island_layout`, `island_motion` and
`bar_events` in `desktop_ui/` are pure decisions. `DesktopBar` owns
observations and timers, `island_surface` owns the Qt window and its native
glass, and `shell_surface` draws the pager.
