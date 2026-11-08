# Module map

Domain alternatives are unions of frozen, slotted dataclasses handled with
`match` and `assert_never`. Decisions are pure functions. Each effect (a
thread, file, network call or window) has one owner module. Logic reaches
Windows only through an interface: `miryoku.engine.Host` for the layout and
`assistant.features.Desktop` for key actions. Tests pass concrete adapters for
these.

## Processes

| Process | Entry | Owns |
| --- | --- | --- |
| Launcher | `StartWorkspace.cmd`, `launch.py` | Starts, stops and restarts the components from the checkout's `.venv`; it supervises nothing |
| AI connection | `gateway/__main__.py` | A loopback pass-through to the model provider; holds the key. Imports only `gateway`, `components` and `link` |
| Layout | `miryoku.pyw`, `miryoku/` | The keyboard hook and remapping. Standard library and `winapi/` only |
| Assistant | `assistant/__main__.py`, `assistant/` | Dictation and meeting recording, on a native message loop plus worker threads. No Qt and no UI |
| Desktop | `desktop/__main__.py`, `desktop_ui/` | The bar, tray, key map, overlay and window placement, on Qt's event loop. Reaches the assistant only through `desktop_ui.assistant_port` |

The desktop and the assistant never import each other, even indirectly (the
architecture review's `process-isolation` rule). They share only `contracts/`
(frozen values) and talk over `link/`: a loopback socket with a per-boot token,
carrying `contracts.desktop_link` messages. The assistant publishes states
(`VoiceChanged`, `JobChanged`, `RecordingChanged`, `MicLevel`, replayed to a
desktop that connects later) and events (`Notify`); the desktop sends commands
(`UseTool`, `Record`). The layout posts each request to its owner
(`protocol.owner`): app, window and switcher keys to the desktop, the rest to
the assistant; what the desktop shows (layer, chord, pressed keys) to the
desktop; the layout's state to both. Quit in the tray runs `launch.py stop`,
which asks each program to quit in reverse start order.

## Top-level modules

| Module | Role |
| --- | --- |
| `launch.py` | Starts, stops and restarts the components |
| `components.py` | The component catalogue: the gateway, layout, assistant and desktop, their windows, quit messages and endpoint files |
| `protocol.py` | Window messages from the layout to the desktop and the assistant, the `Tool` and `App` requests, and each request's owner (`Side`, `owner`) |
| `config.py` | User settings: apps, snippets, dark-screen delay |
| `cell.py` | `Cell`, the one class that reassigns: an owner's changing state |
| `usage.py`, `diagnostics.py` | The usage log and its failure details |
| `winapi/` | Typed Win32 and COM bindings: the only `ctypes` code |
| `link/` | Loopback links: published endpoints, framed messages, the server and client |

## `miryoku/`

`layout.py` holds the layer tables and settings, checked at import.
`engine.py` turns key events into actions. `win.py` owns the hook and message
loop. `firmware.py` recognizes the Charybdis keyboard and maps the
Ctrl+Alt+Shift chords (`CHORDS`). `hook_watch.py` detects when Windows silently
removes the hook and reinstalls it. Measure latency with
`scripts/benchmark_keyboard.py` before and after changing these.

## `assistant/`

| Modules | Role |
| --- | --- |
| `app.py`, `desktop.py` | Composition: the microphone, meetings and the `Desktop` adapter (typing and the clipboard) |
| `control.py`, `control_policy.py` | The control thread's decisions (events in, state and effects out) and its startup effects |
| `features.py`, `text.py` | What each tool key does, and making dictated text safe to type |
| `llm.py` | `Settings` from the environment, the SDK client and transcription through the gateway |
| `meetings.py`, `meeting_store.py`, `journal.py` | Meeting recording, its journal of queued audio and its Markdown transcript |
| `desktop_port.py` | What the assistant tells the desktop |
| `lifecycle.py` | Optional lifecycle measurements, and how a background owner stops |

## `contracts/`

The values the desktop and the assistant share, so either side imports them
without the other's effects. Contracts import only the standard library,
pydantic, `cell`, `protocol`, `winapi.shapes`, `winapi.pcm` and each other; the
architecture review's `contract-isolation` rule enforces it.

| Modules | Role |
| --- | --- |
| `desktop_link.py` | The messages between the desktop and the assistant, and their wire form |
| `status.py` | The tray's state and the bar's quick job |
| `recording_state.py`, `meetings.py`, `capture.py` | Meeting recording values, events and transcripts, and what a recording captures |
| `geometry.py`, `hotkeys.py` | Rectangle arithmetic, and every tool key's behaviour |
| `members.py` | Enum and `Literal` translation tables checked to name every value |

## `desktop_ui/`

| Modules | Role |
| --- | --- |
| `desktop_app.py`, `desktop_control.py`, `desktop_controls.py`, `assistant_port.py` | Composition, the desktop's control decisions, the tray menu, and what it asks of the assistant |
| `ui.py`, `qt_ui.py`, `qt_runtime.py`, `ui_control.py`, `job_queue.py`, `dialogs.py` | Qt dispatch, event-loop ownership and the views' decisions |
| `desktop_bar.py`, `bar_*.py`, `island_*.py`, `ambient.py`, `audio_meter.py` | The bar ([policy](toolbar-design.md)) and the readings it shows |
| `shell_*.py`, `desktop_pager.py`, `taskbar_guard.py` | The pager and app shelf, and the Windows taskbar |
| `application_observer.py`, `window_layout.py`, `navigation.py`, `navigation_log.py`, `window_switcher.py` | [Window placement](window-placement.md), navigation and its log |
| `key_hints.py`, `key_hint_overlay.py` | The letters drawn while an Apps key is held |
| `away_screens.py`, `keyboard_light.py`, `laptop_panel.py` | Dark screens, keyboard light and laptop panel while nobody is looking |
| `keymap*.py`, `overlay*.py`, `layer_indicator.py` | The key map, keyboard overlay and layer indicator |
| `tray.py`, `icons.py`, `report.py`, `view_publication.py` | The tray icon, the usage report and the view log |
| `components/`, `fonts/`, `colour.py`, `motion.py`, `*_icons.py` | Shared appearance, glass, controls, motion, icons and type |
| `ui_spec.py`, `ui_spec_watch.py`, `spec/` | The desktop's declarative specs (one frozen value per module: the bar's composition in `island.py`, sizes in `sizes.py`, the controls menu in `controls.py`, the tray menu in `tray.py`), validated and reloaded while it runs |

## `scripts/`

`check.py` runs the checks ([pipeline](iteration-pipeline.md)), with
`selection.py` choosing the tests a change affects, `check_tiers.py` the time
budgets and `check_native.py` the native runners. `architecture.py` and
`quality.py` are the reviews, `volume.py` counts code volume, and
`navigation_report.py` reads the navigation log.
