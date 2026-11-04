# Window placement

Workspace gives every managed window a declared place on each monitor setup.
Windows never overlap. When the screens can't hold everything side by side, the
extra apps go on further Windows virtual desktops, the ones Task View shows.
Workspace owns placement; GlazeWM is retired.

## Setups

`desktop_ui/window_layout.py` matches the connected monitors to a setup. The
laptop's own panel is the monitor whose display path reports a built-in output
technology (`DISPLAYCONFIG_OUTPUT_TECHNOLOGY_INTERNAL`, embedded DisplayPort or
embedded UDI). The externals are matched by physical size, so roles follow
orientation rather than arrangement.

| Setup | Monitors besides the laptop panel | Roles |
| --- | --- | --- |
| Laptop only | None | LAPTOP |
| Home | One 3840×2160 landscape screen | LAPTOP, MAIN |
| Work | One 2560×1440 landscape and one 1440×2560 portrait screen | LAPTOP, ABOVE, SIDE |

Any other set of monitors is treated as the laptop alone, on its panel (or the
primary monitor when no single panel is reported). Other monitors stay empty.

Observed at home on 2026-11-04: the laptop panel is `\\.\DISPLAY1`,
1920×1200 at 120 DPI, primary, at (0, 0). The 4K screen is `\\.\DISPLAY2`,
3840×2160 at 144 DPI, at (1920, −269). Both work areas equal their monitors
because Workspace hides the taskbar.

## Dark external screens while away

The home 4K screen is an OLED, so neither the Windows lock screen nor a still
desktop may stay on it while nobody is looking. `DARK_WHEN_AWAY` in
`desktop_ui/window_layout.py` declares which roles of a setup go dark: Home's
MAIN. Work's screens and any unrecognized set stay lit. Only the laptop panel
shows the lock screen.

`desktop_ui/away_screens.py` darkens the protected screens for either of two
reasons, and restores them once neither holds:

- **Locked.** The bar's hidden shell-controls window registers for session
  notifications; `WTS_SESSION_LOCK` darkens at once and `WTS_SESSION_UNLOCK`
  ends the reason. Input on the lock screen doesn't wake the screen.
- **Idle.** No keyboard or mouse input for `DARK_WHEN_IDLE_MINUTES` in
  `config.py` (2 by default, whole minutes from 1 to 60, checked at startup).
  The next input wakes the screen. Unlocking while still idle past the delay
  keeps it dark.

A program asking Windows to keep the display on, such as a playing video or a
call, holds off the idle reason, and so does a Workspace meeting recording. A
display request that starts while the screen is idle-dark wakes it. The lock
darkens regardless.

A screen goes dark by DDC/CI power mode (VCP D6) 4 and comes back with 1, only
on the screens this owner turned off. Requests are made only when the first
reason begins or the last one ends, never on every poll: a screen that refuses
to come back on stays recorded and is tried again at the next restore or when
Workspace closes. Closing Workspace turns its darkened screens back on. If
Workspace starts behind the lock screen, such as after a crash, it darkens the
protected screens then.

`winapi/monitor_power.py` opens physical-monitor handles when it acts. When
those don't answer, it uses handles opened while unlocked, reopened after each
display change. Each `dark_when_away` usage record says the power mode, the
reason (`locked`, `idle`, or `close`), the idle seconds, the screens and how
many requests needed the kept handles.

Workspace doesn't change Windows' lock, screen-saver or power settings, and
doesn't simulate input. The machine's `InactivityTimeoutSecs` policy still
locks the session on its own schedule.

Decision: DDC/CI instead of a display topology change. Measured on this machine:
`SetDisplayConfig` from the locked user session returns `ERROR_ACCESS_DENIED`.
D6=4 turned the 4K screen dark and D6=1 brought it back, while
`SM_CMONITORS` stayed 2: Windows still counts the screen as connected, so
placement keeps its windows there. Each request took about 65 ms and
runs on the bar's thread. The laptop panel doesn't answer DDC/CI.

Decision: poll idleness on the bar's 100 ms observation tick, not its frame
loop, with no thread of its own. `winapi/presence.py` reads `GetLastInputInfo`
against `GetTickCount64`, modulo the 32-bit wrap of the last-input tick, and
the system execution state's `ES_DISPLAY_REQUIRED` from
`CallNtPowerInformation(SystemExecutionState)`. Measured on 2026-11-04: the two
reads cost about 2 µs and 21 µs. The execution state showed `ES_DISPLAY_REQUIRED`
while another process held `SetThreadExecutionState(ES_CONTINUOUS |
ES_DISPLAY_REQUIRED)` or a `PowerSetRequest(PowerRequestDisplayRequired)`
request, and cleared when it exited; a system-only request left it clear. The
wake costs at most one tick plus one DDC/CI request per screen.

Turn it off or on with **Dark when away** in the controls menu; its detail
shows the delay. It starts on with each Workspace launch.

## Layouts

Each app has one position per setup: a desktop, a role and a region of that
role's work area. One table, `LAYOUTS`, declares them.

| Setup | Desktop | Placement |
| --- | --- | --- |
| Laptop only | 1 | Outlook left half, Teams right half |
| Laptop only | 2 | Terminal left half, VS Code right half |
| Laptop only | 3 | Edge full screen |
| Home | 1 | MAIN: Terminal left two thirds, VS Code right third. LAPTOP: Teams full |
| Home | 2 | MAIN: Edge left half, Outlook right half |
| Work | 1 | SIDE: Teams top half, Outlook bottom half. ABOVE: Terminal left half, VS Code right half. LAPTOP: Edge full |

Apps are identified by executable (`windowsterminal.exe`, `code.exe`,
`msedge.exe`) and by the pinned web apps' AppUserModelIDs. Ordinary Edge is every
Edge window that isn't Outlook's or Teams' app window.

## Rules

- Workspace manages top-level taskbar windows that have a sizing border and
  aren't minimized. Dialogs, fixed-size windows, minimized windows and
  Workspace's own windows keep their places.
- Several windows of one app share its region equally: side by side in a
  landscape region, stacked in a portrait one. Two terminals at home read
  Terminal | Terminal | Code across the 4K screen.
- Every undeclared app gets a desktop of its own after the declared ones,
  filling the laptop's work area. It keeps that desktop while other apps open
  and close; a newcomer takes the lowest free one.
- Region edges are exact fractions, so neighbours' pixel edges come from the
  same value. A Hypothesis property checks that no two windows on one desktop
  overlap, for every setup and any earlier placement.
- Each poll converges windows on their desktop and visible rectangle. A window
  already in place is not touched. Invisible DWM borders are added back on, so
  the drawn edges meet exactly. A pinned web-app window is placed by the part its
  caption region leaves visible.
- A maximized managed window is restored and placed. A window being dragged or
  resized is left alone until the left button is released, then snaps back.
- Display changes re-run placement on the next poll.
- Workspace creates missing desktops. It never removes one.

Pause or resume placement from the controls menu or with the **⌃⌥⇧ X** chord.
The **⌃⌥⇧ D** chord puts every window back now and ends a zoom.

## Navigation

Every navigation is one variant of `desktop_ui/navigation.py`'s union and
carries its input source: key, pager, scroll or toolbar. A pure decision
turns it and the observer's world into one effect, and into a record of the
desktop and app it came from and went to and whether it launched. The
application observer carries the effect out and writes the record to the
[navigation log](#navigation-log).

Key navigation is the Ctrl+Alt+Shift chords, the same on both keyboards:
`miryoku/firmware.py`'s `CHORDS` table maps each request to its letter, and the
README lists them. On the laptop the layout's home row mods hold Ctrl+Alt+Shift.
The letters below are the chord letters.

- **App chords** (left-hand letters) go to the app's placed desktop and focus
  its window. Repeated taps cycle its windows; an app that isn't running is
  started. Outlook and Teams are the pinned web apps, launched like their
  toolbar slots.
- **Spatial focus** (**N E I O**) moves to the
  placed window on the current desktop that shares the most edge with the
  focused one in that direction, then the closest. It crosses monitors and
  doesn't wrap.
- **Desktop chords**: **K** and **H** step to the previous and next desktop and
  stop at the ends. **J**, **L**, **U** and **Y** jump to desktops 1 to 4. Arriving
  focuses the window last used there.
- **Zoom** (**M**) fills the focused window's monitor. Placement leaves it alone
  until the key is pressed again or focus leaves the window.
- **The pager** after the toolbar's pinned slots shows each desktop and marks the
  current one. Its names list the apps placed there. While either keyboard
  holds Ctrl+Alt+Shift, each target shows its chord's letter, such as **L**,
  since the held Ctrl+Alt+Shift completes it. A horizontal scroll over the bar
  steps one desktop per gesture.
- **The toolbar** shows apps from every desktop. Clicking one on another
  desktop switches there before focusing it.

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
  entry with `kind` `external`. Changes to Workspace's own windows, such as the
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
| `kind` | string | The navigation: `app_key`, `cycle_app`, `show_window`, `switcher_pick`, `spatial_focus`, `step_desktop`, `jump_desktop`, `pager_click`, `bar_scroll` or `zoom` for a Workspace navigation; `external` for any other change. |
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

## Virtual desktop adapter

`winapi/virtual_desktops.py` lists, creates and switches desktops and reads or
moves any program's window. The documented `IVirtualDesktopManager` reads a
window's desktop. Moving another process's window, creating and switching need
the shell's undocumented `IVirtualDesktopManagerInternal` and
`IApplicationViewCollection`. A window on another desktop is cloaked by the
shell, as the shell's hidden hosts are; only the first has a desktop, which is
how the observer tells them apart.

Decision: bind these interfaces directly through their COM method tables with
`ctypes`, as `winapi/composition.py` and `winapi/recording.py` already do,
instead of adding pyvda 0.6.0. pyvda would add itself and comtypes 1.4.17 to the
runtime bundle and need a bundle rebuild. comtypes emits a FutureWarning on
Python 3.15, and both packages are untyped, so a local stub would still be
needed. Workspace consumes a dozen methods on one Windows build. The direct
binding is under 200 lines with no new dependency. The interface IDs and method
order come from pyvda 0.6.0's table for build 26100. Measured on this machine
(build 26100): reading a window's desktop takes about 0.1 ms, and observing the
desktop list about 3 ms. Moving another process's window worked without
switching desktops. Slot 23 (`SwitchDesktopWithAnimation` in pyvda's table)
crashed with an access violation, so switching uses `SwitchDesktop`.

## Limits

- The internal interfaces change between Windows builds. On another build the
  adapter fails to connect: the toolbar still works and placement stops, rather
  than calling a wrong method. Supporting a new build means adding its interface
  IDs and method order.
- An Explorer restart disconnects the interfaces; the observer reconnects on the
  next poll.
- An app with a large minimum size can't shrink to a narrow share of its region,
  so many windows of one app can overlap in practice.
- Windows of elevated programs can't be moved from Workspace's unelevated
  process.
- A window moved between monitors with different DPI settles on the next poll,
  after the app rescales itself.
- The work layout is checked only by tests with literal monitor geometry; it
  needs the two 2560×1440 screens connected to verify on the desktop.
