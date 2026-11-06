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
| Assistant | `assistant/__main__.py` | Everything else, on one Qt event loop plus worker threads |

The keeper and its helpers are protected: the agent can't change them, and a
deploy that changes one relaunches the keeper. A changed data file restarts the
programs that import its package; files under an entry's `live_assets` restart
nothing, because their program reloads them.

## Top-level modules

| Module | Role |
| --- | --- |
| `keeper.py` | Supervision, the install pipeline, trials, undo, and `Versions` (a Git repository of installed versions) |
| `keeper_control.py` | Typed keeper requests (`Install`, `Undo`, `Restart`) and their results |
| `components.py` | The component catalogue: the layout and the assistant, their windows and readiness markers |
| `restart_plan.py` | Which components a change restarts, from both versions' import graphs |
| `selfcheck.py` | The compile, import and test gate every install passes |
| `protocol.py` | Window messages between the layout and the assistant, and the `Tool` and `App` requests |
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
| `features.py`, `hotkeys.py`, `control_policy.py` | What each key and tray menu entry does |
| `sdk.py`, `agent.py`, `agent_execution.py`, `task_profiles.py` | The Agents SDK boundary, the agent loop, and each task profile's tools and context |
| `agent_tools.py`, `*_tools.py` | Tool families: desktop, browser, business (Teams, Outlook, Kanban), canvas, meetings, tasks, self-change, self-review |
| `browser*.py`, `web_apps.py` | The agent's own Edge over CDP, and typed web-app operations |
| `feed_*.py`, `notification_*.py`, `communications*.py` | Teams and Windows notification sources, screening and triage |
| `personal_work_*.py` | Work threads collected from Outlook, Teams and Kanban |
| `work_canvas*.py`, `canvas_*.py`, `attention.py` | The canvas document (`canvas.sqlite3`), its edits and what needs attention |
| `meetings.py`, `meeting_*.py`, `automatic_meetings.py` | Meeting recording, its journal and transcript, and Teams auto-record |
| `workspace.py`, `publishing.py` | The agent's source copy, and landing or publishing its changes with Git |

## `automation/`

`task.py` holds the task, run, checkpoint and action values. `store.py` and
`journal.py` own `work.sqlite3`. `controller.py`, `actions.py` and
`execution.py` run one task and record each consequential action before it
happens. `worker.py` runs work on the assistant's threads and holds the work
folder's lease. `self_review.py` decides when the agent reviews its own runs.
See [the durable-work decision](adr/0001-durable-work.md).

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
| `ui_spec.py`, `ui_spec_watch.py`, `spec/` | The desktop's declarative specs (sizes in `tokens.toml`, the controls menu in `controls.toml`), validated and reloaded while it runs |
