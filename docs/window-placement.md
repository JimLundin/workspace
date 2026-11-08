# Window placement

Workspace gives every managed window a declared place for the connected
monitors. Windows never overlap. Apps that don't fit go on further Windows
virtual desktops, which Workspace creates and never removes.

## Setups and layouts

`desktop_ui/window_layout.py` matches the monitors to a setup. The laptop panel
is the monitor with a built-in output technology. External screens are matched
by physical size. Any other set of monitors counts as the laptop alone.

Desktop 1 is always the canvas, alone. An app can have several places; its
windows fill them in order and any beyond the last share that place.

| Setup | Screens besides the laptop | Desktop 1 | Desktop 2 | Desktop 3 | Desktop 4 | Desktop 5 |
| --- | --- | --- | --- | --- | --- | --- |
| Laptop only | None | Canvas | Outlook, Teams | Terminal, Terminal | Terminal, VS Code | Edge |
| Home | 3840×2160 (MAIN) | MAIN: Canvas | MAIN: Terminal ⅔, VS Code ⅓. Laptop: Teams | MAIN: Edge, Outlook | | |
| Work | 2560×1440 (ABOVE), 1440×2560 (SIDE) | ABOVE: Canvas | SIDE: Teams, Outlook. ABOVE: Terminal, VS Code. Laptop: Edge | | | |

`LAYOUTS` declares these places. Every undeclared app gets its own desktop
after the declared ones, filling the laptop, and keeps it while other apps come
and go.

## Rules

- Workspace manages resizable top-level windows of other programs. Dialogs and
  fixed-size windows keep their places.
- Nothing is ever minimized: every app has a place in every setup, on its own
  desktop if need be. A minimized window is restored into its place, on
  whichever desktop it belongs, so a change of monitors sorts every window.
  There is no minimize key.
- Several windows of one app share its region equally.
- Each poll moves windows that are out of place and leaves the rest alone. When
  the window in front is moved to another desktop (one just opened, such as the
  canvas or a new Teams window), Workspace switches there with it. A
  dragged window snaps back when the button is released. A maximized or minimized
  window is restored and placed.
- **⌃⌥⇧ X** pauses or resumes placement, and **⌃⌥⇧ D** places every window now.
- Zoom (**⌃⌥⇧ M**) fills the monitor with the focused window until you press it
  again or focus another window.

## Navigation

`desktop_ui/navigation.py` turns each chord, pager click or toolbar click into one
effect that `application_observer.py` carries out. App chords go to the app's
desktop and cycle its windows. Focus chords move to the neighbouring placed
window and cross monitors. Desktop chords go straight to their desktop; nothing cycles desktops. Each navigation is
also written to the [navigation log](#navigation-log).

## Dark when away

`DARK_WHEN_AWAY` names the screens to darken: Home's MAIN, an OLED.
`desktop_ui/away_screens.py` turns them off over DDC/CI (VCP D6) while the
session is locked or after `DARK_WHEN_IDLE_MINUTES` without input. A display
request from another program holds off the idle reason. Toggle it in the
controls menu.

At the same moments the Charybdis's backlight goes off over VIA, and the
laptop's own panel dims to brightness 0 over WMI (`desktop_ui/laptop_panel.py`).
Each puts back the setting the person had. The panel is an LCD, so 0 is its
darkest, not fully off: switching it off would mean turning off every display
through Windows, which on this laptop enters Modern Standby.

## Key hints

While either keyboard holds its Apps key (the laptop's X thumb, or the
Charybdis's Tab thumb), Workspace draws the letters on
the desktop itself, so the chords can be learned without the mouse:

- **A keycap badge** sits inside the top-left corner of each placed window on the
  current desktop, on every monitor. It shows the app's chord letter. When an
  app has several windows, the window the next press reaches takes the accent.
- **Focus letters** appear on the windows next to the focused one, with their
  arrow: **← N**, **↓ E**, **↑ I** or **→ O**.
- **The focused window** adds Zoom (**M**) as a quiet letter.

Releasing the Apps key hides everything. Windows on other desktops get no
badge; the pager's names list the apps on other desktops.

`desktop_ui/key_hints.py` decides the hints as a pure function of the
application observer's navigation world and the window in front. Each letter's
target comes from the same navigation decision that carries the chord out, so a
hint can't name a window the chord skips. The bar owns the hints and refreshes the window in
front on each 100 ms tick while the chord is held; `desktop_ui/key_hint_overlay.py`
paints them in the bar's material and shape: 26 px capsules with 20 px keycaps
in Inter 12 medium, glass as the thicker Qt-painted veil, solid, or high
contrast. Every badge is a click-through tool window that never activates.
Badge windows are pooled, and nothing runs while the hints are hidden.

## Navigation log

Navigation is time not spent working. The navigation log records each move
between windows, so the declared layouts can be changed to need fewer of them.
`desktop_ui/navigation_log.py` decides every entry with pure functions. The
application observer's worker is the only writer.

The log is `%LOCALAPPDATA%\workspace\navigation.jsonl`, next to `usage.jsonl`.
Each line is one JSON object, written through a Pydantic `TypeAdapter`. Before an
append, a file of 16 MB or more is renamed to `navigation.1.jsonl`, replacing
the previous one. A report reads `navigation.1.jsonl` and then
`navigation.jsonl`, oldest line first. The log is local only and always on.

Apps are named by program or pinned web app. The log never contains window
titles, window content or typed text.

### When an entry is written

- **A Workspace navigation.** Every navigation the dispatcher decides writes one
  entry, including one that moved nothing, such as spatial focus with no
  neighbour or a zoom. Its `to_*` fields are the dispatcher's target.
- **An external change.** Any other change of the foreground window writes one
  entry with `navigation` `external`. Changes to Workspace's own windows, such as the
  bar or the window switcher, aren't observed, so leaving the switcher counts
  from the window before it.

A Workspace navigation's own foreground change isn't logged a second time. For
up to 2 seconds after a focus or desktop switch, and 15 seconds after a launch,
the change it expects is absorbed: the target window, the first window on the
target desktop when no window was remembered there, or the launched app's
first window. A change in that time that is neither a click nor an Alt+Tab is
the shell passing focus during the switch, and is absorbed too. Focusing the
window already in front expects nothing.

An external change gets the first `cause` that applies:

1. `alt_tab`. The Alt+Tab switcher opened before the change and closed at most
   0.5 seconds before it. Windows the switcher brings forward while it is open
   aren't entries. When no change follows the close, the window in front at the
   close is the choice. Returning to the starting window writes nothing. A
   switcher open for 60 seconds without a close event counts as closed.
2. `mouse`. A mouse button was down when the change was delivered, or a window
   captured the mouse at most 0.5 seconds before it.
3. `other`. Anything else, such as a program taking focus by itself, a new
   window, a notification or another program's shortcut.

### Schema

Every field is present on every line, in this order. Times use the local
clock. `null` means the value isn't known.

| Field | Type | Meaning |
| --- | --- | --- |
| `time` | string | When Workspace decided the navigation or handled the change: ISO 8601 local time with microseconds and UTC offset, such as `2026-11-04T09:30:01.500000+01:00`. |
| `setup` | `"laptop_only"`, `"home"`, `"work"` or `null` | The monitor setup at the last poll. `null` before the first poll that found a monitor. |
| `navigation` | string | The navigation: `app_key`, `cycle_app`, `show_window`, `switcher_pick`, `spatial_focus`, `step_desktop`, `jump_desktop`, `pager_click`, `bar_scroll` or `zoom` for a Workspace navigation; `external` for any other change. |
| `cause` | string | For a Workspace navigation, its input: `key` (a chord, an app key or the window switcher), `pager`, `scroll` or `toolbar`. For `external`: `alt_tab`, `mouse` or `other`. |
| `from_app` | string or `null` | The app in front before: a program's lowercase executable file name, such as `code.exe`, or a pinned web app, `outlook` or `teams`. A window outside the taskbar, such as a dialog or a shell surface, is named by its program. `null` when unknown. |
| `to_app` | string or `null` | The app navigated to, named the same way. For a launch, the launched app. |
| `from_desktop` | integer or `null` | The 0-based virtual desktop index of the window in front before; 0 is desktop 1. |
| `to_desktop` | integer or `null` | The 0-based desktop index navigated to. An external change is on the desktop current at the next poll. |
| `other_desktop` | boolean | `from_desktop` and `to_desktop` are both known and differ. |
| `launched` | boolean | The navigation started an app that had no window. Always `false` for `external`. |
| `dwell_ms` | integer or `null` | How long the window in front before had been in front, in milliseconds, from its own foreground change to this entry. For `alt_tab`, it includes the time the switcher was open. `null` when that window was already in front when Workspace started. |

Decision: one hook thread, `winapi/win_events.py`, installs out-of-context
WinEvent hooks for `EVENT_SYSTEM_FOREGROUND`, `EVENT_SYSTEM_CAPTURESTART` and
`EVENT_SYSTEM_SWITCHSTART`/`SWITCHEND`, skipping Workspace's own process.
Out-of-context events are delivered while the hooking thread waits for
messages. The observer's worker waits on its order queue instead, so the hook
thread does nothing but wait and queue each event for the worker. The worker
owns the world the entries are built from. A foreground change makes the worker
poll first, so a new window is identified and placed before its entry is
decided. The bar's thread has a message loop, but would move window state across
threads.

Limit: the order of the Alt+Tab switcher's close and its chosen window's
foreground change hasn't been observed on this machine. Both orders give one
`alt_tab` entry.

### Navigation report

The navigation report turns the log into proposed layout changes. It only reads
the log and prints text; the user decides which change to make in `LAYOUTS`.

```
python -m scripts.navigation_report [--days N] [--setup home|work|laptop_only] [--log PATH]
```

It reads the last 7 days by default, from `navigation.1.jsonl` and then
`navigation.jsonl`. `--log` names another log, such as the fixture in
`tests/navigation_report_fixture.jsonl`. Each line is validated against the
[schema](#schema) through the log's own `TypeAdapter`. A line that isn't one
entry, or whose time has no UTC offset, is counted as malformed and skipped.
`scripts/navigation_analysis.py` decides everything with pure functions;
`scripts/navigation_report.py` reads the files and prints.

`EFFORT` and `DESKTOP_SWITCH` in `scripts/navigation_analysis.py` hold the
cost of one entry:

| Cause | Cost | On another desktop |
| --- | --- | --- |
| `key` | 1 | 2 |
| `alt_tab` | 3 | 4 |
| `mouse`, `pager`, `toolbar`, `scroll` | 4 | 5 |
| `other` | 0 | 0 |

`other` is a program taking focus, not the user's effort, so it costs nothing
and is listed separately. A key navigation that moved nothing, the same app on
the same desktop, still costs 1 and counts as wasted. A zoom or a cycle between
one app's windows keeps the app on purpose and isn't wasted.

The report has four sections, one block per setup. Entries without a setup are
shown as `unknown setup` and get no suggestions. Unknown apps are shown as
`(unknown)`.

1. **Totals.** Navigations and cost per hour in front, the share of each cause,
   desktop switches and wasted chords. Hours are the summed `dwell_ms` of the
   counted entries. An entry whose previous window was in front over 4 hours is
   away time: the rates leave it out, and the report says how many.
2. **App pairs.** The ten pairs with the highest round-trip cost, A to B and B to
   A together, with their count and how many crossed desktops.
3. **Reached without a chord.** The apps most often reached by mouse, Alt+Tab,
   the pager, the toolbar or scrolling. Each is a hint or binding gap.
4. **Suggestions.** The five single changes that would have cost least.

A suggestion replays the setup's logged entries against a candidate layout. A
declared app is on the candidate's desktop for it; any other app stays on the
desktop it was logged on. Each entry's desktop switch is re-derived from its
from and to apps' desktops. Each entry carries its own origin, so the replay
needs no consecutive history and survives setup filtering and restarts. The
replay assumes a chord for every target app that has one in `CHORDS` and keeps
the logged cause otherwise, so its cost can be lower than the logged cost in
the totals. Both costs of a suggestion come from the same replay, so a layout
identical to the current one saves exactly 0.

The candidates are single changes within the setup's `LAYOUTS` table:

- **Move** one app to another declared desktop. It keeps its role and region
  when they're free there, and otherwise fills the first monitor no app uses on
  that desktop. Moving an app onto the desktop of the app it alternates with
  most is one of these moves.
- **Swap** two apps' desktops, each keeping its role and region.
- **Exchange** two apps' whole positions, when swapping desktops alone would
  overlap.

A candidate that would overlap two apps on one desktop and monitor is skipped,
by placement's rule. Each suggestion shows the replayed cost before and after,
the saving per logged day, and the exact `LAYOUTS` lines to change, such as
`LAYOUTS[Setup.HOME][PinnedApp.TEAMS]: Position(0, Role.LAPTOP, FULL) -> Position(1, Role.MAIN, LEFT_HALF)`.
A saving per day is the saving divided by the calendar days that have entries.

## Virtual desktop adapter

`winapi/virtual_desktops.py` binds the shell's undocumented
`IVirtualDesktopManagerInternal` and `IApplicationViewCollection` with `ctypes`,
using interface IDs for Windows build 26100. On another build it fails to
connect, and placement stops while the bar keeps working. Windows of elevated
programs can't be moved.

Key hint badges sit at each window's placed rectangle; while placement is
paused, or for a zoomed window, that can differ from where the window is.
