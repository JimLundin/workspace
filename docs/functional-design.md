# Module map

Domain alternatives are unions of frozen, slotted dataclasses handled with
`match` and `assert_never`. Decisions are pure functions. Each effect (a
thread, file, network call or window) has one owner module. Logic reaches
Windows only through an interface: `miryoku.engine.Host` for the layout,
`assistant.features.Desktop` for key actions, and `assistant.agent_tools.Machine`
for the agent. Tests pass concrete adapters for these.

## Processes

| Process | Entry | Owns |
| --- | --- | --- |
| Keeper | `workspace.pyw`, `keeper.py` | Starts and restarts the components, checks and installs changes, trials and undo |
| AI connection | `gateway/__main__.py` | A loopback pass-through to the model provider; holds the key. Imports only `gateway`, `components` and `runtime`, so other deploys leave it running |
| Layout | `miryoku.pyw`, `miryoku/` | The keyboard hook and remapping. Standard library and `winapi/` only |
| Assistant | `assistant/__main__.py`, `assistant/`, `automation/` | Dictation, meetings, feeds, the canvas document and the agent, on a native message loop plus worker threads. No Qt and no UI |
| Desktop | `desktop/__main__.py`, `desktop_ui/` | The bar, tray, work canvas views, overlay and window placement, on Qt's event loop. Reaches the assistant only through `desktop_ui.assistant_port` |

The desktop and the assistant never import each other, even indirectly (the
architecture review's `process-isolation` rule). They share only `contracts/`
(frozen values) and talk over `link/`: a loopback socket with a per-boot token,
carrying `contracts.desktop_link` messages. The assistant publishes states
(replayed to a desktop that connects later) and events; the desktop sends
commands. The layout posts each request to its owner (`protocol.owner`): app,
window, inbox and switcher keys to the desktop, the rest to the assistant;
what the desktop shows (layer, chord, pressed keys) to the desktop; the
layout's state to both. A clean exit of the desktop (Quit in its tray) quits
Workspace; the assistant exits only when the keeper closes it.

The keeper and its helpers are protected: the agent can't change them, and a
deploy that changes one relaunches the keeper. A changed data file restarts the
programs that import its package; files under an entry's `live_assets` restart
nothing, because their program reloads them.

## Top-level modules

| Module | Role |
| --- | --- |
| `keeper.py` | Supervision, the install pipeline, trials, undo, and `Versions` (a Git repository of installed versions) |
| `keeper_control.py` | Typed keeper requests (`Install`, `Undo`, `Restart`) and their results |
| `components.py` | The component catalogue: the gateway, layout, assistant and desktop, their windows, readiness markers and endpoint files |
| `restart_plan.py` | Which components a change restarts, from both versions' import graphs |
| `selfcheck.py` | The compile, import and test gate every install passes |
| `protocol.py` | Window messages from the layout to the desktop and the assistant, the `Tool` and `App` requests, and each request's owner (`Side`, `owner`) |
| `config.py` | User settings: apps, snippets, agent step limit, dark-screen delay |
| `usage.py`, `diagnostics.py` | The usage log and its failure details |
| `runtime.py` | Activates the bundled `.runtime` dependencies |
| `winapi/` | Typed Win32 and COM bindings: the only `ctypes` code |

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
| `app.py`, `desktop.py`, `machine.py` | Composition: the tray, views, microphone, meetings and the `Desktop` and `Machine` adapters |
| `llm.py` | `Settings` from the environment, the SDK clients, transcription and one-shot questions |
| `features.py`, `control_policy.py` | What each key and tray menu entry does |
| `sdk.py`, `agent.py`, `agent_execution.py`, `task_profiles.py` | The Agents SDK boundary, the agent loop, and each task profile's tools and context |
| `agent_tools.py`, `*_tools.py` | Tool families: desktop, browser, business (Teams, Outlook, Kanban), canvas, meetings, tasks, self-change, self-review |
| `browser*.py`, `web_apps.py` | The agent's own Edge over CDP, and typed web-app operations |
| `feed_*.py`, `notification_*.py`, `communications*.py` | Teams and Windows notification sources, screening and triage |
| `personal_work_*.py` | Work threads collected from Outlook, Teams and Kanban |
| `work_canvas.py`, `canvas_*.py` | The canvas document's owner (`canvas.sqlite3`) |
| `meetings.py`, `meeting_*.py`, `automatic_meetings.py` | Meeting recording, its journal and transcript, and Teams auto-record |
| `workspace.py`, `publishing.py` | The agent's source copy, and landing or publishing its changes with Git |

## `automation/`

`store.py` and `journal.py` own `work.sqlite3`; `context.py` stores and
selects saved context. `controller.py`, `actions.py` and
`execution.py` run one task and record each consequential action before it
happens. `worker.py` runs work on the assistant's threads and holds the work
folder's lease. `self_review.py` decides when the agent reviews its own runs.
See [the durable-work decision](adr/0001-durable-work.md).

## `contracts/`

The values the desktop and the assistant share, so either side imports them
without the other's effects. Contracts import only the standard library,
pydantic, `protocol`, `winapi.shapes`, `winapi.pcm` and each other; the
architecture review's `contract-isolation` rule enforces it.

| Modules | Role |
| --- | --- |
| `task.py`, `presentation.py`, `json_value.py`, `action_text.py` | The task, run, checkpoint and action values, and how they read |
| `personal_work.py`, `work_documents.py`, `context.py`, `work_commands.py`, `work_snapshot.py` | Work threads, their documents, saved context, commands and the published work snapshot |
| `work_canvas_model.py`, `work_canvas_context.py`, `work_canvas_commands.py`, `work_canvas_edits.py`, `work_canvas_contracts.py`, `canvas_activity.py`, `canvas_session.py`, `attention.py` | The canvas document, its projection, edits and what needs attention |
| `agent_session.py`, `card_actions.py`, `feed_origin.py` | The agent session's snapshots and the actions its cards offer |
| `recording_state.py`, `meeting_detection.py`, `meeting_presentation.py`, `meetings.py`, `capture.py` | Meeting recording values and how they read |
| `geometry.py`, `hotkeys.py` | Rectangle arithmetic, and every tool key's behaviour |

## `desktop_ui/`

| Modules | Role |
| --- | --- |
| `ui.py`, `qt_ui.py`, `qt_runtime.py` | Qt dispatch and event-loop ownership |
| `desktop_bar.py`, `island_*.py`, `request_panel.py` | The bar ([policy](toolbar-design.md)) |
| `agent_window.py`, `agent_progress.py`, `view_publication.py` | The agent session controller and its snapshots |
| `work_canvas_*.py`, `work_window.py` | The canvas views |
| `application_observer.py`, `window_layout.py`, `navigation.py`, `desktop_pager.py` | [Window placement](window-placement.md) and navigation |
| `keymap*.py`, `overlay*.py`, `layer_indicator.py` | The key map, keyboard overlay and layer indicator |
| `components/`, `fonts/` | Shared appearance, controls and type |
| `ui_spec.py`, `ui_spec_watch.py`, `canvas_toolbar.py`, `spec/` | The desktop's declarative specs (one frozen value per module: the bar's composition in `island.py`, sizes in `sizes.py`, the controls menu in `controls.py`, the tray menu in `tray.py`, the canvas toolbar in `canvas.py`), validated and reloaded while it runs |
