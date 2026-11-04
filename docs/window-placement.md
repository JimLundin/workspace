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

## Dark external screens while locked

The home 4K screen is an OLED, so the Windows lock screen must not stay on it.
`DARK_WHEN_LOCKED` in `desktop_ui/window_layout.py` declares which roles of a
setup go dark while the session is locked: Home's MAIN. Work's screens and any
unrecognized set stay lit. Only the laptop panel shows the lock screen.

The bar's hidden shell-controls window registers for session notifications.
On `WTS_SESSION_LOCK`, `desktop_ui/locked_screens.py` sets DDC/CI power mode
(VCP D6) to 4 on the protected screens; on `WTS_SESSION_UNLOCK` it sets 1 again,
only on the screens it turned off. A screen that refuses to come back on stays
recorded and is tried again at the next unlock or when Workspace closes.
Closing Workspace turns its darkened screens back on. If Workspace starts behind
the lock screen, such as after a crash, it darkens the protected screens then.

`winapi/monitor_power.py` opens physical-monitor handles when it acts. When
those don't answer, it uses handles opened while unlocked, reopened after each
display change. Each usage record says how many requests needed the kept ones.

Decision: DDC/CI instead of a display topology change. Measured on this machine:
`SetDisplayConfig` from the locked user session returns `ERROR_ACCESS_DENIED`.
D6=4 turned the 4K screen dark and D6=1 brought it back, while
`SM_CMONITORS` stayed 2: Windows still counts the screen as connected, so
placement keeps its windows there. Each request took about 65 ms and
runs on the bar's thread. The laptop panel doesn't answer DDC/CI.

Turn it off or on with **Dark when locked** in the controls menu. It starts on
with each Workspace launch.

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
application observer carries the effect out and hands the record to a callback,
ready for a navigation log.

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
