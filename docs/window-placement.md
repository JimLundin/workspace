# Window placement

Workspace gives every managed window a declared place for the connected
monitors. Windows never overlap. Each setup uses exactly the Windows virtual
desktops its layout names: Workspace creates any that are missing and removes
any after them, whose leftover windows fall back to the last one kept.

## Setups and layouts

`desktop_ui/window_layout.py` matches the monitors to a setup. The laptop panel
is the monitor with a built-in output technology. External screens are matched
by physical size. Any other set of monitors counts as the laptop alone.

Desktops count from the first in Task View. An app can have several places;
its windows fill them in order and any beyond the last share that place.

| Setup | Screens besides the laptop | Desktop 1 | Desktop 2 | Desktop 3 | Desktop 4 | Desktop 5 |
| --- | --- | --- | --- | --- | --- | --- |
| Laptop only | None | Outlook, Teams | Terminal, Terminal | VS Code | Edge | Others |
| Home | 3840×2160 (MAIN) | MAIN: Terminal, VS Code, sharing it equally. Laptop: Edge | MAIN: Outlook, Teams. Laptop: others | | | |
| Work | 2560×1440 (ABOVE), 1440×2560 (SIDE) | SIDE: VS Code. ABOVE: Terminal. Laptop: Edge | ABOVE: Outlook, Teams. Laptop: others | | | |

`desktop/placement.py` declares these places. Every app a layout doesn't name
goes to its place for others, where the windows of all such apps share the
region in their stable order, so an undeclared app never adds a desktop.

## Rules

- Workspace manages resizable top-level windows of other programs. Dialogs and
  fixed-size windows keep their places.
- Nothing is ever minimized: every app has a place in every setup, in the
  place for others if need be. A minimized window is restored into its place, on
  whichever desktop it belongs, so a change of monitors sorts every window.
  There is no minimize key.
- Several windows of one app share its region equally. Apps given the same
  region share it the same way, every window an equal part, in the layout's order.
- An app's windows keep their order while they stay open. Windows first seen
  together, as at startup, are ordered by where they sit (desktop, then left,
  then top). So a restart of Workspace, or of a program that restores its
  windows where they were, leaves every window in its place.
- Each poll moves windows that are out of place and leaves the rest alone. When
  the window in front is moved to another desktop (one just opened, such as a
  new Teams window), Workspace switches there with it. A
  dragged window snaps back when the button is released. A maximized or minimized
  window is restored and placed.
- **⌃⌥⇧ J** pauses or resumes placement, and **⌃⌥⇧ D** places every window now.
- Zoom (**⌃⌥⇧ M**) fills the monitor with the focused window until you press it
  again or focus another window.

## Navigation

`desktop_ui/navigation.py` turns each chord, pager click or toolbar click into one
effect that `application_observer.py` carries out. App chords go to the app's
desktop and cycle its windows. Focus chords move to the neighbouring placed
window and cross monitors. Desktop chords go straight to their desktop; nothing cycles desktops.

## Dark when away

`DARK_WHEN_AWAY` names the screens to darken: Home's MAIN, an OLED.
`desktop_ui/away_screens.py` turns them off over DDC/CI (VCP D6) while the
session is locked, and back on at unlock; nothing is polled, so walking away is
covered by Windows locking the session after its own timeout. Toggle it in
Workspace's controls (press its glyph on the bar).

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

## Virtual desktop adapter

`winapi/virtual_desktops.py` binds the shell's undocumented
`IVirtualDesktopManagerInternal` and `IApplicationViewCollection` with `ctypes`,
using interface IDs for Windows build 26100. On another build it fails to
connect, and placement stops while the bar keeps working. Windows of elevated
programs can't be moved.

Key hint badges sit at each window's placed rectangle; while placement is
paused, or for a zoomed window, that can differ from where the window is.
