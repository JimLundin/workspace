# Window placement

Workspace gives every managed window a declared place for the connected
monitors. Windows never overlap. Apps that don't fit go on further Windows
virtual desktops, which Workspace creates and never removes.

## Setups and layouts

`desktop_ui/window_layout.py` matches the monitors to a setup. The laptop panel
is the monitor with a built-in output technology. External screens are matched
by physical size. Any other set of monitors counts as the laptop alone.

| Setup | Screens besides the laptop | Desktop 1 | Desktop 2 | Desktop 3 |
| --- | --- | --- | --- | --- |
| Laptop only | None | Outlook, Teams | Terminal, VS Code | Edge |
| Home | 3840×2160 (MAIN) | MAIN: Terminal ⅔, VS Code ⅓. Laptop: Teams | MAIN: Edge, Outlook | |
| Work | 2560×1440 (ABOVE), 1440×2560 (SIDE) | SIDE: Teams, Outlook. ABOVE: Terminal, VS Code. Laptop: Edge | | |

`LAYOUTS` declares these positions. Every undeclared app gets its own desktop
after the declared ones, filling the laptop, and keeps it while other apps come
and go.

## Rules

- Workspace manages resizable, non-minimized top-level windows of other
  programs. Dialogs and fixed-size windows keep their places.
- Several windows of one app share its region equally.
- Each poll moves windows that are out of place and leaves the rest alone. A
  dragged window snaps back when the button is released. A maximized window is
  restored and placed.
- **⌃⌥⇧ X** pauses or resumes placement, and **⌃⌥⇧ D** places every window now.
- Zoom (**⌃⌥⇧ M**) fills the monitor with the focused window until you press it
  again or focus another window.

## Navigation

`desktop_ui/navigation.py` turns each chord, pager click or scroll into one
effect that `application_observer.py` carries out. App chords go to the app's
desktop and cycle its windows. Focus chords move to the neighbouring placed
window and cross monitors. Desktop chords don't wrap.

## Dark when away

`DARK_WHEN_AWAY` names the screens to darken: Home's MAIN, an OLED.
`desktop_ui/away_screens.py` turns them off over DDC/CI (VCP D6) while the
session is locked or after `DARK_WHEN_IDLE_MINUTES` without input. A display
request from another program holds off the idle reason. Toggle it in the
controls menu.

## Virtual desktop adapter

`winapi/virtual_desktops.py` binds the shell's undocumented
`IVirtualDesktopManagerInternal` and `IApplicationViewCollection` with `ctypes`,
using interface IDs for Windows build 26100. On another build it fails to
connect, and placement stops while the bar keeps working. Windows of elevated
programs can't be moved.
