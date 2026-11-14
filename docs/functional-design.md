# Module map

[architecture.html](architecture.html) draws this map: open it in a browser to zoom
from the programs to each part and its code (a snapshot; the code it embeds
is from the commit that wrote it).

Domain alternatives are unions of frozen, slotted dataclasses handled with
`match` and `assert_never`. Decisions are pure functions. Each effect (a
thread, file, network call or window) has one owner module. Logic reaches
Windows only through an interface: `keyboard.engine.Host` for the layout and
`assistant.features.Desktop` for key actions. Tests pass concrete adapters for
these.

## Processes

| Process | Entry | Owns |
| --- | --- | --- |
| Launcher | `StartWorkspace.cmd`, `launch.py` | Starts, stops and restarts the components from the checkout's `.venv`; it supervises nothing |
| AI connection | `gateway/__main__.py` | A loopback pass-through to the model provider; holds the key. Imports only `gateway`, `protocol` and `settings.programs` |
| Layout | `keyboard.pyw`, `keyboard/` | The keyboard hook and remapping. Standard library and `winapi/` only |
| Desktop | `desktop/__main__.py`, `desktop_ui/`, `assistant/` | The bar, tray, key map, overlay and window placement, dictation and meeting recording, on Qt's event loop, with worker threads for slow jobs. `desktop/` declares its values (`look.py`, `bar.py`, `windows.py`, `placement.py`) and `__main__.py` hands them, with `settings/`, to `desktop_ui` as one `DesktopSettings` |

The layout posts every request, what the desktop shows (layer, chord, pressed
keys) and its state to the desktop's control window. The desktop's fold
(`desktop_ui.desktop_control`) routes each key by its `contracts.hotkeys` route:
app, window and switcher keys and the meeting key to the desktop's own effects,
dictation and transcript keys to `assistant.features.Assistant`. What
dictation's and meetings' worker threads report arrives as events in the same
inbox. Quit in the tray runs `launch.py stop`, which asks each program to quit
in reverse start order.

## Top-level modules

| Module | Role |
| --- | --- |
| `launch.py` | Starts, stops and restarts the components |
| `protocol.py` | Window messages between the layout and the desktop, the `Tool` and `App` requests, and the shapes of the programs (`Programs`) and where they keep their state (`Places`) |
| `settings/` | The values the programs share, imported only by entry points: the apps (`apps.py`), the programs and their windows (`programs.py`) and the keyboard layout (`layout.py`) |
| `cell.py` | `Cell`, the one class that reassigns: an owner's changing state |
| `diagnostics.py` | Failure details for the programs' own logs |
| `winapi/` | Typed Win32 and COM bindings: the only `ctypes` code |

## `keyboard/`

The layout program, near the bottom of the layers: it uses only the
foundations. Its API, the layout's model the desktop draws, is the vocabulary
(`physical.py`, the laptop's keys, scancodes and keycaps; `keys.py`, the keys
and modifiers sent to Windows; `actions.py`, what a key does on a layer, its
app keys being slots the desktop fills; `board.py`, the rows and thumbs layers
are written in), `layout.py` (the shape of a `Layout`: its timings, physical
board and every layer, declaring none), `bindings.py` (the lookups built from a
layout, rejecting an inconsistent one) and `chords.py` (each Apps request by
its base key). `settings/layout.py` holds the layout Workspace runs,
and `__main__.py` hands it to `win.run`. `engine.py` turns key events into
actions. `win.py` owns the hook and message loop. `firmware.py` recognizes the
Charybdis keyboard and tracks its shortcuts. `hook_watch.py` detects when
Windows silently removes the hook and reinstalls it. Measure latency with
`scripts/benchmark_keyboard.py` before and after changing these.

## `assistant/`

| Modules | Role |
| --- | --- |
| `desktop.py` | The `Desktop` adapter: the microphone, typing and the clipboard |
| `features.py`, `text.py` | What each tool key does, and making dictated text safe to type |
| `llm.py` | `Settings` from the environment, the SDK client and transcription through the gateway |
| `meetings.py`, `meeting_store.py`, `journal.py` | Meeting recording, its journal of queued audio and its Markdown transcript |

## `contracts/`

Plain values the desktop, dictation, meetings and the layout's key map share,
without anyone's effects. Contracts import only the standard library,
pydantic, `cell`, `protocol`, `winapi.shapes`, `winapi.pcm` and each other; the
architecture review's `contract-isolation` rule enforces it.

| Modules | Role |
| --- | --- |
| `status.py` | The tray's state and the bar's quick job |
| `recording_state.py`, `meetings.py`, `capture.py` | Meeting recording values, events and transcripts, and what a recording captures |
| `geometry.py`, `hotkeys.py` | Rectangle arithmetic, and every tool key's behaviour |
| `endpoint.py` | The gateway's endpoint file, which the gateway writes and dictation reads |
| `members.py` | Enum and `Literal` translation tables checked to name every value |

## `desktop_ui/`

| Modules | Role |
| --- | --- |
| `desktop_app.py`, `desktop_settings.py`, `desktop_control.py`, `voice.py` | Composition and the views, the shape of what the desktop is handed, the desktop's control decisions and tray menu, and dictation, meetings and the microphone |
| `qt_ui.py`, `qt_runtime.py` | The Qt application, one-shot timers and the bar's frame loop |
| `desktop_bar.py`, `bar_*.py`, `island_*.py`, `ambient.py`, `month.py`, `audio_meter.py`, `live_marks.py` | The bar ([policy](toolbar-design.md)), the readings it shows and their panels |
| `dictation_marker.py`, `marker_window.py` | The dictation marker beside the caret: its steps, placement and window |
| `shell_*.py`, `desktop_pager.py`, `taskbar_guard.py` | The pager and app shelf, and the Windows taskbar |
| `application_observer.py`, `window_layout.py`, `navigation.py`, `window_switcher.py` | [Window placement](window-placement.md) and navigation |
| `key_hints.py`, `key_hint_overlay.py` | The letters drawn while an Apps key is held |
| `away_screens.py`, `keyboard_light.py`, `laptop_panel.py` | Dark screens, keyboard light and laptop panel while nobody is looking |
| `keymap*.py`, `overlay*.py`, `layer_indicator.py` | The key map, keyboard overlay and layer indicator |
| `tray.py`, `icons.py` | The tray icon |
| `components/`, `fonts/`, `colour.py`, `motion.py`, `*_icons.py` | Shared appearance, glass, controls, motion, icons and type |

## `scripts/`

`check.py` runs the checks ([pipeline](iteration-pipeline.md)).
`architecture.py` and `quality.py` are the reviews, sharing `source_analysis.py`'s
parsing and cache. `architecture.py` reads the tree and judges findings against
the declared exceptions; its rules live in the `*_rules.py` modules (imports,
constants, declarations, modelling, function scopes, records, usage and test
seams), which report `policy.py`'s `Finding`; `volume.py` counts code volume, and
`benchmark_keyboard.py` measures the keyboard hook.
