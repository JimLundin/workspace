# Automatic Windows tiling

Research date: 2026-10-26. Source inspection is pinned to GlazeWM **v3.10.1**.
This document records verified upstream behavior and recommendations for Workspace;
it does not claim that every recommendation has been implemented or tested on
the user's desktop.

## Choice and integration boundary

GlazeWM manages ordinary native application windows in a tiling container tree.
New tiling windows are inserted beside the focused tiling window, or beside an
existing tiling window when a floating window has focus. Windows that cannot be
resized initialize as floating. Maximized windows can initialize as tiling;
already-fullscreen windows have a separate initialization path. This provides
automatic arrangement without requiring a shortcut for each window. [1]

Workspace should keep its Python/Qt runtime and desktop bar. GlazeWM remains a
separate executable controlled through its documented CLI/IPC boundary. Its
sample configuration launches Zebar and supplies many Alt-based shortcuts, so
copying that sample unchanged would introduce a competing bar and shortcuts.
Use a dedicated configuration with empty startup/shutdown commands, keybindings
and binding modes instead. [2, 3]

Recommendation: expose automatic tiling's running/paused state and occasional
actions in Workspace's existing controls menu. Keep the idle bar compact. Do not
bind ordinary letters, Spacebar, Shift or arrow keys merely to control the
manager; Workspace already owns keyboard handling and dictation.

Workspace now observes monitor geometry twice before redistributing visible tiles.
It allocates tiles in proportion to logical screen area, fills available large
screens first, and chooses vertical stacking for portrait displays. It preserves
the focused tile where possible and leaves hidden workspaces, floating windows,
minimized windows and active drags untouched. Automatic changes are limited to
startup and display changes for a manager Workspace owns. A manual rebalance is
available from the bar menu. F6 opens a searchable native window list, including
cloaked GlazeWM windows; `focus --container-id UUID` reveals the selected
window's workspace before focusing it.

## Packaging and startup

The v3.10.1 release workflow builds the Windows binaries with the `ui_access`
feature. The executable manifest consequently requests `uiAccess="true"`.
The standalone MSI installs the manager and watcher under
`%ProgramFiles%\glzr.io\GlazeWM`, with a distinct CLI executable at
`cli\glazewm.exe`. The standalone installer does not package Zebar. [4, 5, 6]

The CLI implements `start` by resolving the main executable in its directory
or parent directory and launching it through `cmd /C start "" ...`. Its source
explicitly uses this route because UIAccess applications cannot be started
directly with `CreateProcess`. Workspace uses `ShellExecuteExW` with the ordinary
`open` verb and `SEE_MASK_NOCLOSEPROCESS`, retaining the exact manager process
handle for readiness and shutdown. This follows the shell launch route while
avoiding ownership of only a short-lived startup helper. The watcher stays beside
the main executable; queries use the separate `cli\glazewm.exe`. Verify both the
owned process and IPC readiness, with a bounded timeout. [7, 8]

Windows' default UIAccess policy requires a trusted digital signature and a
secure installation location, such as Program Files, to grant UIAccess rights.
Microsoft states that an application failing the location/security restrictions
can start without those rights and then interacts only with applications at the
same or lower privilege level. Thus a private LocalAppData installation can
support ordinary windows, but must not be presented as equivalent to the MSI's
secure-location installation for managing elevated windows. Check actual startup
and arrangement on the target machine; `--help` alone does not verify this. Do
not disable Windows' UIAccess policy to accommodate a private installation. [9]

The private installation was verified on the target Windows machine: shell
startup returned the live manager handle, two disposable Qt windows tiled,
opening a third redistributed the space, and closing it expanded the survivors.
A Workspace-titled test window stayed ignored. Paused shutdown resumed the owned
manager, exited gracefully and left IPC unavailable. The installer preserves
the distinct main/CLI paths and retains the signed watcher. GlazeWM writes fatal
errors to `%USERPROFILE%\.glzr\glazewm\errors.log`.

## Independent configuration

Pass the dedicated YAML path using `start --config PATH`. Without that argument,
GlazeWM uses `%USERPROFILE%\.glzr\glazewm\config.yaml` and creates a sample file
when missing. Preserve that personal configuration. The following is a compact
starting recommendation, based on the parsed schema and sample config. There is no
reserved gap: Workspace's compact bar overlays tiled windows, which reach every
screen edge and meet without spacing. Window borders are disabled and corners
are square. Inner and outer gaps remain configurable, including DPI scaling.
[2, 3, 10]

```yaml
general:
  startup_commands: []
  shutdown_commands: []
  config_reload_commands: []
  focus_follows_cursor: false
  hide_method: cloak

gaps:
  scale_with_dpi: true
  inner_gap: 0px
  outer_gap:
    top: 0px
    right: 0px
    bottom: 0px
    left: 0px

window_effects:
  focused_window:
    border: { enabled: false }
    corner_style: { enabled: true, style: square }
  other_windows:
    border: { enabled: false }
    corner_style: { enabled: true, style: square }

window_behavior:
  initial_state: tiling
  state_defaults:
    floating:
      centered: true
      shown_on_top: false

workspaces:
  - name: '1'
  - name: '2'
  - name: '3'

window_rules:
  - commands: ['ignore']
    match:
      - window_title:
          regex: '(?i)^workspace(?:\b| ·)'
        window_process:
          regex: '^pythonw?$'
  - commands: ['set-floating']
    match:
      - window_class: { equals: '#32770' }

binding_modes: []
keybindings: []
```

GlazeWM excludes invisible windows, child windows, `WS_EX_NOACTIVATE` windows
and `WS_EX_TOOLWINDOW` windows before running rules. It excludes owned windows
only if they lack `WS_CAPTION`, so a captioned, resizable owned dialog can still
be tiled. Workspace's tool/nonactivating glass surfaces already meet native
exclusions; the title-and-runtime rule is additional protection. The `#32770` floating rule
above protects conventional dialogs, but does not cover every app-specific
dialog implementation. Do not ignore all Python windows, which would also
exclude unrelated Python applications. [1]

The Workspace title predicate must share one match item with the Python runtime
predicate. A browser tab or terminal can display a Workspace title; excluding it
by title alone removes it from the managed tree. Later title changes do not
reconsider an ignored window, leaving the next managed window to fill its screen.
Workspace repairs only its exact generated title-only ignore stanza during owned
startup, preserving other configuration bytes and line endings. Existing borrowed
managers retain their configuration and lifetime. Restarting the owned manager
clears previously excluded ordinary application windows. Native reproduction on
the two unequal monitors found Edge and Terminal excluded while Code filled the
upper monitor; all three had the same Windows integrity and native query access.

Within one `match` item, process, title and class conditions combine with AND.
Separate items combine with OR. Unspecified fields match anything. Ordinary
string comparisons are case-sensitive; regexes can specify their own case
behavior. Rules default to manage/title-change events and run once. [3, 10]

## Commands and response validation

Run the packaged **CLI** executable, not an assumed same-named manager path.
The following argument forms are defined by the v3.10.1 command parser. [11]

| Purpose | CLI arguments |
| --- | --- |
| Launch with Workspace config | `start --config PATH` |
| Read pause state | `query paused` |
| Inspect managed windows | `query windows` |
| Inspect workspaces | `query workspaces` |
| Check running version | `query app-metadata` |
| Pause/resume automatic management | `command wm-toggle-pause` |
| Gracefully exit | `command wm-exit` |
| Reload YAML | `command wm-reload-config` |
| Focus a neighboring window | `command focus --direction left` |
| Move a window in the tree | `command move --direction right` |
| Change insertion direction | `command toggle-tiling-direction` |
| Float/retile the target window | `command toggle-floating` |
| Focus a workspace | `command focus --workspace 2` |

`command --id UUID ...` can target a specific container. This is useful when
opening Workspace's controls changes native focus: capture the intended target
before interacting with the menu rather than acting on an arbitrary new focus.
Commands and queries require a running manager. The default IPC port is 6123.
[11, 12]

CLI output is a response envelope containing `clientMessage`, `data`, `error`
and `success`. A rejected IPC command can still produce a successful process
exit: validate JSON and its `success` field, then validate the expected `data`
shape. In particular, `query paused` returns a **bare boolean** in `data`, not
an object such as `{ "isPaused": true }`. `query app-metadata` reports version,
not configuration path or process ownership. [13, 14]

## Pause, ownership and shutdown

Pausing changes manager state; resuming queues a redraw of the container tree.
It does not restore window positions from before tiling. While paused,
`run_command` ignores every command except `wm-toggle-pause`, including
`wm-exit`. Therefore graceful shutdown of an owned paused manager must first
resume it, then issue `wm-exit`, and verify it actually exits. A successful JSON
response alone cannot distinguish this paused-command no-op. [15, 16]

Recommendation: only stop a manager instance Workspace launched. If IPC is already
available, treat that manager as externally owned and preserve its config and
lifecycle. Record process identity and the launch config for owned instances;
do not infer ownership from version or process name. Any pause/resume policy
for an externally owned instance should preserve its prior state.

On graceful exit, GlazeWM emits an exiting event and runs shutdown commands.
Dropping its state redraws managed windows at their current intended rectangles,
shows them, restores taskbar visibility, clears custom borders and returns
transparency to opaque. This reveals windows from other workspaces; it does
**not** restore their original pre-tiling geometry. The separate Windows watcher
also shows tracked windows and resets those effects when IPC closes
unexpectedly. Keep the watcher available and prefer normal exit over terminating
both processes. [8, 16, 17, 18]

## Sources

1. [Window eligibility, initialization and insertion](https://github.com/glzr-io/glazewm/blob/v3.10.1/packages/wm/src/commands/window/manage_window.rs).
2. [Upstream sample configuration](https://github.com/glzr-io/glazewm/blob/v3.10.1/resources/assets/sample-config.yaml).
3. [Parsed configuration schema and defaults](https://github.com/glzr-io/glazewm/blob/v3.10.1/packages/wm-common/src/parsed_config.rs).
4. [Release packaging workflow](https://github.com/glzr-io/glazewm/blob/v3.10.1/.github/workflows/package.yaml) and [feature selection during build](https://github.com/glzr-io/glazewm/blob/v3.10.1/.github/workflows/build.yaml).
5. [Executable manifest construction](https://github.com/glzr-io/glazewm/blob/v3.10.1/packages/wm/build.rs).
6. [Standalone MSI contents and installation paths](https://github.com/glzr-io/glazewm/blob/v3.10.1/resources/wix/standalone.wxs).
7. [CLI startup helper](https://github.com/glzr-io/glazewm/blob/v3.10.1/packages/wm-cli/src/main.rs).
8. [Manager lifecycle and watcher startup](https://github.com/glzr-io/glazewm/blob/v3.10.1/packages/wm/src/main.rs).
9. [Microsoft: Only elevate UIAccess applications installed in secure locations](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/security-policy-settings/user-account-control-only-elevate-uiaccess-applications-that-are-installed-in-secure-locations).
10. [Config loading and rule matching](https://github.com/glzr-io/glazewm/blob/v3.10.1/packages/wm/src/user_config.rs).
11. [CLI command definitions](https://github.com/glzr-io/glazewm/blob/v3.10.1/packages/wm-common/src/app_command.rs).
12. [IPC address](https://github.com/glzr-io/glazewm/blob/v3.10.1/packages/wm-common/src/ipc.rs).
13. [CLI response handling and exit behavior](https://github.com/glzr-io/glazewm/blob/v3.10.1/packages/wm-cli/src/lib.rs).
14. [IPC response construction and query data](https://github.com/glzr-io/glazewm/blob/v3.10.1/packages/wm/src/ipc_server.rs).
15. [Pause transition and resume redraw](https://github.com/glzr-io/glazewm/blob/v3.10.1/packages/wm/src/commands/general/toggle_pause.rs).
16. [Paused command handling and graceful cleanup](https://github.com/glzr-io/glazewm/blob/v3.10.1/packages/wm/src/wm.rs).
17. [Native state restoration on drop](https://github.com/glzr-io/glazewm/blob/v3.10.1/packages/wm/src/wm_state.rs).
18. [Windows watcher recovery](https://github.com/glzr-io/glazewm/blob/v3.10.1/packages/wm-watcher/src/main.rs).
