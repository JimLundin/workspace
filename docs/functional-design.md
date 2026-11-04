# Functional design

Live requested agent activity appears in a bounded lower-right trail. One
requested outcome owns one card: public updates, actions and the final reply
stay together. Questions resume that same turn. Headings stay on
one elided line even when steps are opened. Completed cards expire oldest first.
Older cards pushed into the upper eight-line edge band begin their ordinary exit;
hover, expansion, pending input and recording protect them from that exit.
Hover also pauses the reading timeout. Full history retains the complete interaction.
Notification-owned background tasks stay quiet; their useful findings and
questions join the desktop card for their factual work context. Related canvas
contributions retain one desktop card even across different visual groups.
New connections keep an existing card's native identity. Requests expand in the
toolbar or notification card; canvas navigation is an explicit icon action.
Bubbles remain read-only; a tooltip directs replies to the agent voice button.
An expanded request selects its exact session/task owner for the spoken reply.
The canvas retains useful findings, sources, documents, drafts and clarifications.
Requests and execution history do not create work bubbles. Arrangement instructions
edit the existing canvas directly; substantive new work gets a meaningful context.
Closing the bubble hides it without stopping its worker; stopping is a separate action.
There is no standalone feed composer or manual filter window.

Workspace models domain alternatives like Rust enums: a union of frozen, slotted
dataclasses for variants with payloads, and `Enum` for variants without payloads.
`match` and `assert_never` make handlers explicit and let the type checkers find
missing cases when a union grows. `Literal` describes fixed external values.
Decisions are pure where practical, with effects owned by small controllers.

The main places to read are below. Process labels describe static loading from
the declared work and desktop entry modules; shared means both. Input labels the
isolated keyboard process. A shared module can also serve a separate helper
process, such as the browser host. Effect ownership stays in the last column.

| Module | Process | Pure model and decisions | Effect owner |
| --- | --- | --- | --- |
| `miryoku/firmware.py` | input | Firmware keyboard identity, immutable prior-layout intent and Ctrl+Shift+D/Ctrl+Shift+G voice-shortcut decisions | `winapi/keyboard_devices.py` observes attached device names; the keyboard message loop pauses remapping and restores prior intent outside key callbacks; `keyboard_language.py` keeps firmware output on English (US); `Keyboard` owns paired voice requests and immutable captured-key observations |
| `miryoku/hook_watch.py` | input | Whether raw keyboard input the hook never saw, and a probe it missed, mean Windows removed the hook | The hook stores each key's time; the keyboard message loop feeds raw input, probes, replaces the hook and ends holds the outage dropped. See [keyboard hook watchdog](keyboard-hook-watchdog.md) |
| `automation/personal_work.py`, `assistant/personal_work_store.py`, `personal_work_service.py` | shared: `personal_work.py`; desktop: store/service | Work threads, source identity, bounded associations, remembered corrections, stale-edit rejection and model-plan reconciliation | Desktop-owned `PersonalStore` in `personal_work_store.py` validates transactional SQLite snapshots; `PersonalWork` owns polling, review scheduling, constrained edit validation before queue admission and immutable publication; the work process shares the pure catalog contracts without loading its store |
| `assistant/personal_work_sources.py`, `personal_work_model.py`, `personal_work_tools.py` | desktop: sources/model; shared: `personal_work_tools.py` | Observed browser evidence from typed web-app results, bounded review input and agent work-catalog contracts, including the exact observed source-opening request | `BrowserSources` owns read-only Edge collection every 15 seconds, retries failed access after one minute and reconnects after a stopped native observation; manual refresh retries immediately. `Correlator` owns a cancellable structured model request without action tools; `App` chooses native reference opening or agent execution using the catalog-owned `source_request`; `work_canvas_panel.py` composes the native local canvas; `work_canvas_detail.py` owns revision-bound in-place drafts |
| `assistant/work_canvas_model.py`, `work_canvas_context.py`, `canvas_activity.py`, `work_canvas_edits.py`, `canvas_session.py`, `attention.py`; `desktop_ui/work_canvas_layout.py`, `work_canvas_gestures.py` | shared: model/context/activity; headless desktop owners: edits/session/attention; desktop: measured layout/gestures | Work contexts, shared contributions, nested groups, arrangements/pins, exact clarification routes and quiet attention | `assistant/work_canvas.py` owns the validated SQLite document and serializes observations, scheduling, answers and edits with its own reentrant lock. UI clients import `CanvasEdits` and immutable document/attention publications from `assistant/work_canvas_contracts.py`, without importing the concrete owner. Gesture code produces domain edit intents and native views own measurement and previews. |
| `desktop_ui/keymap_views.py`, `layer_indicator.py`, `dialogs.py` | desktop | Key map presentation and native dialog placement | `KeymapWindow`, `KeymapOverlay` and `Indicator` own their Qt widgets; `RegionPicker` and `AnswerWindow` own their dialogs; `AnswerWindow` posts updates through `DialogHost`; dialog presentation owns positioning and activation; `Ui` marshals calls to those owners |
| `desktop_ui/desktop_attention.py`, `attention.py` | desktop | Exact expanded-request selection, factual work/source grouping independent of canvas arrangement, speech targets, first-question inbox precedence, active-canvas interruption suppression and session-bound answer delivery from immutable `CanvasFocus` and waiting questions | `CanvasWindow` publishes focus and owns instruction, reply feedback, document, voice and meeting updates; `AgentWindow.snapshot()` reads the immutable session under its own lock; `Ui` executes decision variants on Qt and its one `_publish_canvas` handler fans out each owner publication, retaining late-view replay without repeating notices; conversation navigation is connected once through `configure_controls` |
| `desktop_ui/components/meaning.py`, `appearance.py`, `text.py`, `bubble.py` | desktop | Semantic tints and ink roles; scheme tokens and one glass recipe for capsules, menus, cards and the canvas bar; card anatomy and app glyphs | `text.color` and `text.face` adapt shades and type to Qt; `bubble` paints app badges and rim light; surface painters and composition render the shared recipe |
| `desktop_ui/island_model.py`, `island_layout.py`, `island_menu.py`, `island_motion.py`, `motion.py` | desktop | Bar views, capsule and menu layout, navigation and shared spring transitions (see `docs/toolbar-design.md`) | `DesktopBar` owns observations and timers; `island_surface.py` owns the Qt window and glass |
| `assistant/work_canvas_commands.py`, `work_canvas_tools.py`, `work_canvas.py` | shared: commands; work: tools; headless desktop owner: canvas | Atomic edits, paged reads, revision validation, bounded evidence scheduling and saved-before-queue bindings | `App` routes agent tools directly to the canvas owner and delivers work/catalog observations without Qt dispatch. Recovery queues missing tasks during composition. Prompt titles use the canvas owner's catalog observation, avoiding a lock dependency on `PersonalWork`. |
| `assistant/work_bridge_contracts.py`, `work_bridge.py`, `browser_documents.py` | shared: contracts/documents; desktop: `work_bridge.py` | Validated desktop owner variants, their routing to each owner and document stream contracts | The contracts join feed, catalog and canvas wire variants without a feed-to-canvas import cycle; `WorkOwners` routes each variant to its owner's typed handler, and `answer` validates desktop text and encodes its response; `Browser` owns authenticated CDP streams and exclusive bounded file collection |
| `assistant/work_snapshot.py`; `desktop_ui/work_canvas_window.py`, `work_canvas_view.py`, `components/canvas_look.py`, `components/canvas_bubble.py` | desktop | Current work observations, canvas surface roles and bounded previews | `Ui.configure_work` binds callbacks before publication and startup; canvas preparation and showing remain explicit. `canvas_look` paints content and toolbar surfaces, `CanvasBubble` supplies shared scene controls, and `work_canvas_view` shapes visible previews |
| `assistant/llm.py` | shared | System, user, assistant, and tool-result message variants; request serialization; four immutable workload sizes with one shared model mapping and independently configured sizes for quick jobs, the main agent, notification screening/research and source correlation | HTTP client functions and validated environment configuration entry |
| `assistant/sdk.py` | work | Validated named delegation batches, class choices, immutable child results and bounded child turns | The SDK owns each model/tool loop; the adapter owns one shared native-effect gate, independent stream cancellation, content-free child lifecycle updates and collection into the manager's conversation. Child loops reuse the task profile's tools and durable claim, without checkpointing or recursive delegation |
| `automation/presentation.py` | shared | Shared progress, result and live-row values | `automation/app.py` publishes live updates through `ipc.py`; the assistant synthesizes completion from durable outcomes and renders the timeline |
| `assistant/agent_session.py` | desktop | Typed events, messages, agent request rows over the durable questions, session transitions, and presentation | `agent_window.py`, `agent_toasts.py`, `toast_card.py` |
| `assistant/agent.py`, `task_profiles.py`, `agent_execution.py` | work | Tool dispatch and observation recording for one durable work claim; each task profile's toolset and execution (conversation, admitted desktop context, recovery and completion check) | `Profiles` selects the profile run and owns its dependencies, per-conversation SDK history and source drafts; `AgentExecution` owns metrics, error reporting and run cleanup; `WorkExecution` owns the claim's effects |
| `assistant/agent_tools.py`, `desktop_tools.py`, `browser_tools.py`, `business_tools.py`, `self_change_tools.py`, `meeting_tools.py`, `feed_agent_tools.py`, `work_canvas_tools.py`, `personal_work_tools.py`, `task_tools.py` | shared: `agent_tools.py`, `business_tools.py`, `personal_work_tools.py`; work: other listed tools | Tool families: each `Tool` declares its schema, handler, read/change classification with resources, reconciliation proof, readback evidence and visible display; handlers describe each exact `Operation` to its effect | The agent composes the families over its `Session`; `SelfChange` owns the source draft's check/install state |
| `automation/task.py`, `store.py` | shared | Durable task, request profile, agent request, reply, action, and run variants, each tagged by its `kind` or enum value; controls and stale-run decisions | `TaskStore` owns the task journal's queries and stores those records through strict Pydantic adapters; schema version 5 converts version 4 journals in place |
| `automation/journal.py` | shared | Schema versions: creation, ordered migration steps and refusal of unknown or unversioned journals | Every SQLite owner (task, context, personal-work, canvas and meeting journals) opens its file through one connection interface: write transactions, single read snapshots, rollback on any exception, one busy wait and durability policy, and reads that report an absent journal without creating it |
| `automation/controller.py`, `execution.py`, `actions.py` | work: controller; shared: execution/actions | Work outcomes, recovery context, exact operations, observation evidence, reconciliation proof and verification decisions | `WorkController` owns execution lifetime; `Actions` owns cancellable effect coordination |
| `automation/context.py` | shared | Context relevance and freshness | `ContextStore` owns persistence |
| `assistant/work_commands.py`, `work_snapshot.py`, `work_text.py`, `work_agent.py`, `work_service.py`, `owner_calls.py` | desktop | Work commands, the published work snapshot, readable task labels, conversation/task selection and volatile owner-call admission/result identities | `WorkAgent` owns frontend observation and asynchronous UI delivery; `WorkService` composes journal/transport calls; `OwnerDispatcher` owns one handler thread, bounded mailboxes and immutable pending/cache snapshots, rechecking the journal before each effect; the frontend observer alone sends replies; `WorkWindow` schedules its native view |
| `desktop_ui/window_layout.py`, `navigation.py`, `desktop_pager.py` | desktop | Monitor setups, declared window positions, overflow desktops and no-overlap placement; every navigation as one union decided into an effect and a record; the pager view and swipe (see `docs/window-placement.md`) | `ApplicationObserver`'s worker owns window polling, placement, virtual desktops through `winapi/virtual_desktops.py`, navigation effects and slot regions; `DesktopBar` shows its snapshots |
| `desktop_ui/view_publication.py` | desktop | One view per owner: coalesced renders, lazy creation with retry, a single confirmed close | `AgentWindow` and `WorkWindow` keep their immutable state and post through it; `Ui.close_windows` closes both and waits for each confirmation |
| `automation/ipc.py`, `outbox.py`, `bridge.py`, `profile_lease.py` | shared: IPC/outbox/bridge; work: profile lease | Validated process messages, typed meeting operations and bounded desktop-call text, plus immutable event retention/coalescing with explicit history loss | Bridge client/server own the one authenticated pipe and replace outbox snapshots under the server lock; `ProfileLease` owns the OS-released exclusive work-folder lock; `automation/app.py` composes the worker and its `OwnerCalls` adapter, binding calls to the current execution run and cancellation handle |
| `assistant/action_text.py` | shared | Readable action targets and results, formatted before preview limits | `agent.py` publishes previews; session presentation handles raw payloads too |
| `desktop_ui/agent_progress.py`, `notifications.py`, `notification_text.py`, `notification_reading.py`, `toast_stack.py`, `request_panel.py` | desktop | One stable desktop card per requested outcome/work context, complete inline requests in cards and the toolbar, optional canvas actions and agent turns; reading states and lifetimes; measured stack placement and synchronized frame springs | `AgentToasts` owns the card pool, shared measurement, frame clock, timers and history; `toast_card.Card` owns each native window and glass through `CardOwner` |
| `assistant/browser_requests.py`, `browser_values.py`, `browser_session.py`, `browser.py` | shared | Browser requests (one typed variant per operation, validated once at the browser tool seam), immutable page/tab/group observations, validated DevTools and tab-API replies, group selection, typed paginated projections | `Browser`, `NativeSessions`, `Cdp`, `browser_tabs.TabStrip`, the `browser_host` exchange of typed flat requests, and a cancellable connection wait |
| `assistant/recording_state.py` | shared | Audio batches, stored observations, completion rules, retry policy, stale-update rejection, and recording controls | `meetings.py` and `meeting_store.py` |
| `assistant/meeting_detection.py` | desktop | Immutable joined-call observations, saved opt-in, departure debounce, continuous thirty-second failure/recovery warning policy and manual-stop suppression | `meeting_browser.py` reads the existing approved Edge tabs without focus/navigation; `automatic_meetings.py` owns five-second polling, the encrypted preference and command serialization over the existing recorder; `App` routes manual starts/stops through it and `Ui` retains its toolbar-menu status. This uses the existing browser and recording dependencies: lifecycle decisions are Workspace policy, not a general-purpose polling library. |
| `assistant/web_apps.py`, `business_tools.py` | shared | Web-app operations, each declared once with its typed query, page script, application and typed result; exact task/chat/mail conversation identities and expected-value checks. The business family is the only model-tool adapter: private schemas, JSON text and typed readback confirmation | `WebApps` runs an operation through the browser's wake/evaluate lifecycle and the applications' own controls; `Browser.web_app` serializes it with other page work; native browser fixtures decode every script's real output with its result type |
| `runtime.py` | shared | Dependency ABI validation | `activate` |
| `assistant/hotkeys.py` | desktop | Every Tool's exhaustive behavior route and AI-settings gate, shared with the key map | `features.Assistant` dispatches every route through its desktop and assistant-control ports; requests arrive on the control thread and slow work is submitted |
| `assistant/control_policy.py` | desktop | Immutable native message actions and tray observations, menu projection, key-edge and captured menu-target decoding, startup ordering and queued file handoff | `AssistantApp` owns native interpretation, layout transport, UI feedback and worker lifetime; Qt menu choices post to its control thread and share the hotkey dispatcher |
| `automation/activity.py` | shared | Bounded window history reduced from a window or desktop-state observation, shared by both processes | `ActivityTracker` in `assistant/activity.py` and the work process's `DesktopContext` own sampling |
| `assistant/communications.py` | desktop | Teams' `Feed` observations, source identities, grouped pending chat tickets, captured handling revisions and reply evidence | `communications_service.py` owns encrypted settings/drafts/handling, collection and effects; `communications_browser.py` owns exact-chat and Activity DOM boundaries and reads chats with the Teams web-app operation's result type; `Ui` supplies source observations as agent context; canvas activity owns user attention |
| `assistant/feed_sources.py` | desktop | `PendingFeed` retains only the latest Teams and notice reports; one pending listing derives their ordered updates, handling revisions and notice filter. Source variants own their key, origin, attention and triage evidence | `Ui` marshals each report onto Qt's thread and hands `PendingFeed` to triage; routine arrivals never reach the floating bubbles. Every consumer reads the same list: `feed_triage_service.py` collects evidence and `feed_agent_tools.py` shows the voice agent the feed |
| `assistant/feed_triage.py` | desktop | Revision-bound grouped assessments with their captured origins, quiet/action/completed/dismissed dispositions, explicit feedback and stale-result rejection | `feed_triage_service.py` owns coalesced background model calls, DPAPI plan/preferences and the feed commands the desktop owner routes to it, with an explicit cancellable-wait dependency; `feed_agent_tools.py` lets the main voice agent inspect and maintain the same plan; ordinary arrivals do not become floating cards |
| `assistant/feed_origin.py` | shared | Source application identity and assessment provenance | `desktop_ui/vector_icons.py` owns native vector marks; canvas bubbles and the Workspace badge on floating bubbles paint them; the triage board keeps reaction counts quiet |
| `assistant/notification_sources.py` | desktop | Windows notice updates, loaded handling marks and the `NotificationFilter` definition | `NotificationSources` loads stored attention choices and retains notice observations on Qt's thread, apart from the Teams worker; routine observations preserve those choices and expose revised notices as pending |
| `assistant/notification_agent.py` | desktop | Reviewed actionable notification evidence, current source-revision/date selection, exact task IDs and stable prompts | `NotificationAgent` owns a separate admission thread for reviewed ACTION sources from Windows notices, Teams activities and unseen messages. Only current eligible revisions and dates enter quick tool-free screening; refused admissions retry on worker ticks. `WorkAgent.submit_identified` owns durable admission, replay and execution with the existing general tools. The agent investigates and executes actions covered by existing user authorization, recording useful findings in their canvas context. |
| `assistant/card_actions.py` | desktop | The open-canvas card action and its one `workspace://` encoding; any other link parses to nothing | `notification_text.py` and `agent_session.notice_text` build it; `rich_text.py` keeps only canvas redirects clickable in Markdown; `agent_toasts.py` follows the parsed action |
| `winapi/system_notices.py` | desktop | Native notification identities, quiet history baselines, banner coverage and validated timestamps | `winapi/notifications.py` owns native observations; `notification_banners.py` owns the recoverable banner-setting lease; `desktop_bar.py` forwards observations through `Ui.system_notices` to `NotificationSources` and the joined feed; the island has no individual-notice dismissal control |
| `desktop_ui/shell_state.py` | desktop | Windows-key tap decisions | `shell_controls.py` owns taskbar recovery and a dedicated Windows-key message thread; keyboard callbacks post toggles and pass other input through |
| `desktop_ui/shell_items.py`; `winapi/tray_host.py` | desktop | Pinned Outlook/Teams web-app slots claimed by Edge AppUserModelID, launch dedupe, stable running-app/window grouping, live tray registration updates, callback/version routing and popup geometry | `application_observer.py` reads Edge windows' AppUserModelIDs (`winapi/app_user_model.py`) and copies window icons off Qt; `shell_surface.py` owns scrollable icon sections; `TrayHost` forwards shell traffic to Explorer and owns its hidden proxy; the desktop bar composes their lifetimes and excludes the proxy from taskbar recovery |
| `assistant/geometry.py`; `desktop_ui/rich_text.py` | shared: geometry; desktop: rich text | Geometry and Markdown values | Native geometry adapters and Qt text views |

## Presentation ownership

`desktop_ui` owns native views (including the notification-area `Tray`), presentation records and projections, layout,
motion, view publication, the Qt event loop, shared controls and bundled fonts.
`assistant/work_canvas.py` owns the local canvas document and applies user and
agent commands independently of Qt. Conversation values, attention, interaction
links and edit intents belong to `assistant`; native views consume those values.
`Ui` publishes render requests and submits commands through `CanvasEdits` in
`assistant/work_canvas_contracts.py`; it imports no concrete work/canvas owner.

`assistant` owns agent execution and tool families, dictation and meeting behavior,
application effects and shared work contracts. `assistant/app.py` composes these
owners with `desktop_ui.ui.Ui`; `assistant/work_agent.py` adapts durable worker
observations to the injected `ConversationOutput` interface. Durable snapshot
publication precedes presentation; presentation failures do not change journal
or transport availability. The Qt adapter owns prose preparation and rendering.
Agent execution stays in the
supervised automation process. Neither the worker nor the keyboard may import
any `desktop_ui` module, including through package initialization. The source architecture review enforces those import routes.
Python language features and dependency algorithms remain upstream trust;
Workspace tests cover its SDK/Qt startup ordering, effect ownership and visible behavior.

## Feed and meeting passes

The Personal work feed has one triage pass in the desktop process:

1. `communications_browser.py` → `communications_service.py`: Teams observations become a `communications.Feed`.
2. `desktop_bar.py` → `notification_sources.py`: Windows notices, handling marks and the Notification filter become `Notices`.
3. `ui.py` → `feed_sources.observe`: the latest reports update `PendingFeed`; `listed` and `triage_evidence` derive its pending Feed sources.
4. `feed_triage_service.Triage.observe` → `feed_triage.py`: reconcile the revision-bound board using the assessment and command shapes in `feed_contracts.py`.
5. `feed_work.py` and `feed_research.py`: supply bounded context and read-only investigation to the assessment model.
6. `feed_agent_tools.py` → `automation/app.py` `OwnerCalls.desktop` → `work_bridge.py`: voice commands reach `Triage.command`; `feed_history.py` owns their decisions and handoffs.

The quick chat model screens current source revisions before read-only research.
Screening has no tools, one turn and a twenty-second deadline; its result must
cover the exact candidate batch. Quiet, hidden and reaction-only sources do not
enter automatic work. Research investigates actionable candidates, and admission
uses only current reviewed actions from today's feed. Source content remains
untrusted evidence: existing tasks supply action scope;
arrivals themselves supply no new permission. Exact content revisions reuse
their durable task on polling and restart. Observation times are excluded from
the captured prompt so reacquiring the source cannot conflict with its saved task.
Queue admission and duplicate ownership use the existing work frontend and journal;
Python, Pydantic and SQLite algorithms remain trusted. Screening reuses the existing
SDK and quick-model setting without a new scheduling or storage dependency.

`feed_origin.py` supplies shared source-application vocabulary for the canvas and bubbles.
`automation/bridge.py` carries owner calls on the authenticated work pipe;
`work_agent.py` admits them and `owner_calls.py` dispatches them to desktop handlers.

Automatic meeting observation updates its status on every poll, but warns only
after thirty seconds of continuous unavailability. It warns once per outage;
thirty seconds of uninterrupted ready observations rearm the next warning.
`meeting_detection.py` owns those pure transitions, while
`automatic_meetings.AutomaticAttention` owns callback delivery from poll heartbeats.

Native meeting intake is shared with the work canvas: `automation/meetings.py`
owns immutable event periods and conversation batches; `meeting_store.py` owns
the authoritative journal and bounded snapshots. `meetings.py` publishes
canvas observations for every journal at startup and on each update. `PersonalWork` records
native `MeetingSource` metadata and wakes its worker, while `WorkCanvas` owns
serialized intake/research dispatch and durable contribution fingerprints.
The agent reads full conversation pages through `work_items_meeting`; the Qt
detail owner reads the same journal interface. Neither catalog nor view copies
audio or the complete transcript. Python, SQLite and Pydantic algorithms are
trusted; checks cover Workspace's timing, identity, page selection and wiring.

Capture runs `meeting_tools.py` → `MeetingOperation` in `automation/ipc.py` → `automation/app.py` `OwnerCalls.request` → `AssistantApp.meeting_command` in `assistant/app.py` → `meetings.py`, `meeting_store.py` and `recording_state.py`. `automation/capture.py` names the audio source.

Moving these modules into packages remains follow-up work to the process-ownership
decision in [#54](https://github.com/JimLundin/workspace/issues/54).

## Runtime behavior

Feed context refresh and source-date corrections reconsider automatic action and
quiet assessments. Explicit user quieting is a separate disposition and remains
handled across context, date and filtering changes. `feed_contracts.py` separates
public snapshots and handoff receipts from stored retry prompts;
`communications_state.py` owns saved communication contracts and `state_store.py`
serializes their immutable values at encrypted IO.

Routine arrivals stay quiet: the floating bubbles only direct the person to the
canvas and report important changes. The triage plan
belongs to the voice agent, which reads, dismisses, chooses solutions and
answers through `feed_agent_tools.py`. Dismissal saves the exact observed
revisions without completing work or replying to its source. Polls, restart and
preference edits preserve it; new source evidence gets reviewed again. Each
solution keeps the exact proposal revision and choice identity, and choosing it
queues an identified investigation or preparation task; repeated selection reuses
that identity. Source and model text cannot extend the fixed preparation scope
into sending, approval or external changes. Queue acknowledgment is
distinct from completion. Each pending chat message is its own evidence
candidate. The model may group messages only when they concern the same request.
Meaningful rejection records the user's reason against the captured proposal
revision, distinct from dismissal and without sending a reply. The agent
considers refusals, corrections and no action as well as agreement.

The feed is a work queue with accumulated context. `feed_work.py` reads relevant
fresh project notes and explicit preferences from the existing context store,
recent and linked tasks from the task journal, recorded task answers, and
short-lived app/title activity. Matching project history takes priority over
unrelated recent tasks within the context budget. `feed_triage_service.py` supplies that bounded
context to the configured agent model. `feed_research.py` uses the existing Agents
SDK for a bounded background investigation before options appear. Its tools can
retrieve topic-specific saved context, captured conversation history including own
and handled replies, relevant local text files/directories, and public web research.
It has no general agent, desktop control, write or send tools.
Hosted web research runs only when requested; a provider failure returns an explicit
access limitation to the investigation rather than discarding local work. Binary
and Office documents are explicitly unavailable through the text-file adapter.
The SDK owns tool orchestration; no new runtime dependencies are needed.
Suggestions include verified findings, source references, prepared content and
meaningful tradeoffs, while identifying inaccessible or uncertain evidence.
The run stops on shutdown and has a twelve-turn/three-minute overall limit.
Task state, saved context or captured conversation changes invalidate open
recommendations; handled work stays handled. A changed review recipe refreshes
cached recommendations when their sources are available.

`feed_history.py` owns immutable scoped decisions and exact handoffs. A chosen
solution retains its preparation scope. `work_feed_reply` saves the user's actual
instruction before queueing a task that can act within that instruction's scope.
An instruction to draft still authorizes a draft. Each reply identity belongs to
one exact item, captured revision and text; retries reuse its original prompt.
A failed save starts no work, while a failed queue retains the retryable decision.
The latest 200 feed decisions are retained in encrypted feed storage; durable task
requests, replies, effects and results remain in the existing task journal.
Future feed reviews read these outcomes without converting one-off choices into
standing preferences. Queue acknowledgment is distinct from task completion.
`feed_contracts.py` defines immutable IO shapes, validated and serialized with
Pydantic `TypeAdapter`; application decisions operate on typed values. Every feed
operation is one `FeedCommand` variant, validated by the agent tool adapter and
again at the desktop owner boundary. `feed_triage.edited` is the single pure transition for explicit
board edits: it owns dispositions, rule preservation, reconciliation and the
recorded decision, so `Triage` only persists the result.
History stays in the same floating feed; the separate legacy panel is removed.
Typed input is available on explicit request and closes after submitting to Workspace.
The reply composer begins with one row and grows to four rows before scrolling.
Its submit action sits inside the same rounded surface, aligned with the last row.
Enter submits; Shift+Enter adds a line. Drafts and exact reply destinations are
preserved when other bubbles arrive.

Session events include their timestamps. IDs and clocks are supplied by the
work controller, so a sequence of events can be replayed or branched
without changing its source state. Views receive the immutable session itself.
An agent request row projects the durable question itself, with its detail
and the person's reply: pending, answered or cancelled. A reply for an already
resolved request leaves the session unchanged.

The legacy task controller accepts an execution adapter and a window factory. Its
immutable `Active` state carries the current task and pending tasks with their
invocation context; `Stopping` discards the queue until completion. The execution
adapter owns mutable SDK history, workspace, telemetry, and cancellation cleanup.
Each run has its own completion event, including its completion callback, so a
later startup cannot observe the previous worker's completion. Application
composition supplies the concrete machine, native view, and observation reader.

The application now submits durable work through `WorkAgent`. Conversation
identity stays separate from task identity. UI callbacks enqueue commands;
one frontend observer commits them and publishes immutable snapshots. Neither
closing a view nor resetting its conversation deletes a task. The keyboard
still communicates only with the assistant and imports no automation module.

Work views subscribe by task identity through a bounded replacement set.
Subscriptions and snapshot reads perform no caller-side journal I/O. The
observer merges watched tasks with the recent overview. Failed reads retain
the last known tasks and publish explicit unconfirmed submissions; they cannot
establish that a commit never happened. Exact retries preserve the original
request context, and a conflicting identity cannot control an unrelated task.
Reply failures carry their task, question, and attempt identities. A fresh
journal observation must confirm that exact question is still waiting before
a view reoffers it; an old receipt cannot resolve a later attempt.

The separately supervised work process acquires exclusive ownership before
startup recovery. `TaskStore` atomically claims one task, and its `RunRef` fences
progress, answers, and completion. A pause or cancellation retires the claim
immediately; the controller waits for that execution's cleanup before starting
another. Shutdown parks work as interrupted. Live endpoint failures wait for
explicit resume so one unavailable task cannot spin or hold up unrelated work.

Consequential tools record an attempt after validation, immediately before
their effect. The journal retains fingerprints
and bounded outcomes, without raw tool arguments or SDK histories. File writes
can be checked by destination and expected digest. Other unknown effects require
fresh observations before reconciliation. Completion checks the full action
record, independently of the UI's display page. A late callback cannot revive a
cancelled task or replace an already verified action with a weaker outcome.

Questions are durable. Local IPC uses
authenticated, bounded JSON byte frames with worker epochs and event cursors;
it never deserializes Python objects. Meeting and desktop owner calls use this same
pipe. Desktop text is bounded to 64,000 UTF-8 bytes and validated through the
existing desktop adapters. Owner calls and their results remain volatile; each
owner's durable store and the task journal retain the truth (ADR-0001).

The owner dispatcher admits at most two calls, one executing and one queued,
while the frontend continues polling and processing commands. It rechecks the
journal's run immediately before the handler and retains the latest 128 results
by worker epoch, run and request identity. In-flight and completed redelivery
reuse that invocation instead of repeating an effect. Closing rejects queued
calls and drains the active result before disconnecting. Assistant shutdown waits
up to twelve seconds for the dispatcher, retaining personal work, feed, meetings
and Qt throughout; canvas commands have an eight-second Qt wait. A failed drain
stops teardown with an explicit error.

UI, microphone, meeting capture and live
web-app pages remain with the assistant. The worker owns Teams, native actions
and its external-browser session; web-app operations cross typed RPC.

Saved preferences and expiring project notes are explicit; fresh retrieval
excludes expired text while retaining its source for reinspection.

Live replies and reasoning summaries carry an identity and stream state; tools
carry a working, succeeded, failed, or cancelled outcome. The session replaces
these values in place within its immutable message tuple and preserves each
entry's timestamp. Completed entries reject late updates. The SDK boundary
owns the mutable text fragments and only publishes public response text and
reasoning summaries. Request-bound publishers reject events from an earlier
turn or a reset conversation before they reach the pure transition.

Notifications retain the last observed content separately from the visible
stack, so an expired reply does not reappear on an unrelated session update.
Current conversation entries stay while work or pending input is active;
completion starts monotonic reading timers. Hovering preserves their remaining
duration. Overflowing entries use `Held.READING` until their last line is shown,
then receive the ordinary expiry delay. `Waiting`, `Scrolling`, `Paused` and
`Finished` carry a pixel offset; time, content height and reading pace enter a
pure transition. Replies take turns, and waiting replies retain their lifetime.
Reduced motion advances pages with an overlapping line and keeps a manually
chosen starting position. None of these presentation transitions remove conversation messages.
`Entry` uses the session index as its stable key; an answered question adds a
`Response` keyed by that question's index. `Turn` groups these immutable entries
under a stable `TurnKey(request)`, immediately after its user request. Its state
is `Working(generation, phase, queued)` or `Settled.FINISHED | STOPPED | ATTENTION`.
The `Busy` enum distinguishes thinking, waiting, and stopping. `results` keeps
the latest reply and pending input attached; `steps` contains earlier replies,
resolved questions and action activity. An answered question stays with its
response until another reply supersedes it. Follow-ups cannot acquire an earlier
turn's entries or revive its expired terminal state. `notification_text` formats
the attached result and expanded steps separately. Raw reasoning rows do not create cards; public summary updates change the existing outcome card. Action previews format complete payloads before shortening
them, omit transport IDs and search controls, and leave the model's tool results
unchanged. Both conversation views use the same readable presentation.

Qt owns the assistant's main thread, its expiry and animation callbacks, and all
assistant windows. A separate control thread creates the hidden Windows message
window and runs its message loop. `desktop_ui/qt_ui.py` shares Windows composition
across assistant views without tying the application lifetime to a view.
`keeper_ui.py` owns the keeper's separate protected Qt event loop. The bundled
UI uses Qt; no GUI objects cross the keyboard process boundary.

The Meetings view reads the recording archive when it is shown and lists saved
recordings with their transcripts.

The owner animates at most five cards. Retargeting keeps current geometry and
velocity. Each notification fits its rendered content up to 360 logical pixels
(280 for user requests), independent of the history window. Headers, the stop
icon and voice hints contribute to that width. The pure `allocate` function reserves readable
previews and gives pending questions and recent messages the remaining height.
On very small work areas it removes older entries from the projection.
`ui_components.text.Document` measures Markdown using separate `QTextDocument`
instances, with the same fonts, paragraph margins and wrapping as the visible
text. A line that wraps at the maximum width already needs that width; shorter lines get an
exact pixel measurement. No visible window is resized for measurement.

Steps, result, header and footer get separate rectangles; viewports end on
complete display lines. All reply text remains in the native text document,
with no character cutoff. The result and steps have independent scroll positions
and small overflow markers. Steps use smaller type and a 200-logical-pixel
height budget, reserving room for the attached result. Collapsing only changes
the steps' viewport; the result retains its widget, selection and reading
position. `toast_stack.Frame` carries top, width, height, opacity and steps height
together. Its five springs share one critically damped response and clock, so
growing and shrinking neighbors retain their gaps through interruptions and
retirement. Native positioning anchors the right edge; the text wraps at
its destination width, and the stop icon follows the visible right edge.
Unchanged frames do not repeat native movement after fractional DPI rounding.

`rich_text.changed_tail` preserves the unchanged styled prefix, including a
partially expanded span. Qt cursor offsets count UTF-16 units, so astral emoji
and closing Markdown preserve earlier text and selection. The display cursor
stays at its existing position when text arrives; new replies start at the top.
Recording previews explicitly follow their newest line after Qt resolves layout.
New reply text gets a bounded set of short-lived extra selections to reveal its
ink; later packets do not dim earlier text. Floating frames use the shared spring
model with damping 1.0 and response 0.32 s; the text reveal keeps its 160 ms fade.
Keyboard disclosure and Windows reduced motion place frames immediately.
The frame timer accounts for drawing time and requests Windows' finer timer
resolution only while movement, text reveals or smooth reading run. Reduced
motion, opening history and closing release that request. A shared callback
rotates existing spinner shapes without measuring text again. The desktop bar
uses that same loop for agent work and transcription. Static busy frames do not
reposition unchanged capsules, and Windows reduced motion retains a static arc.

The native canvas keeps one scene. Focusing a bubble expands its ancestors and
centers that bubble without replacing neighboring work or maintaining a second
camera history. Its bottom toolbar contains canvas controls and a microphone/N
keycap legend; hold/release instructions and the selected context live in its tooltip.
There is no agent text editor or typing shortcut. CanvasResearch and CanvasInstruction
are immutable intent variants stored with the run binding. Instructions save before
queueing; retries reuse the saved identity and startup preserves the exact direction.
Results and clarification requests can belong to any bubble, including a root
instruction, through the same containment projection.

Clarification details use measured, selectable labels and a Hold N voice hint.
Qt owns their compact height and the previous visible spoken reply when a task
receipt rejects submission. `desktop_attention.py` directs speech to the selected
waiting question on the visible canvas before the conversation handler; `Ui`
executes that decision through the view and answer owners, and failed replies cannot become
new work. Dictation retains its independent capture and transcription path while
the durable agent runs or queues instructions.

Canvas session replies retain their session identity through the attention
decision. `AgentWindow.respond` checks that identity while admitting the request
under its lock, so a reset between observation and delivery cannot redirect an
old reply into a later session that reuses the request id. The captured request's
reply callback runs outside the lock, preserving retry and effect ownership.

First canvas reveal presents an 80-logical-pixel nonactivating indicator before
creating or rendering the view. `ui_components/canvas_loading.py` owns its
transient lifetime. `winapi/composition_spinner.py` uses a top-level
NOREDIRECTIONBITMAP host; Windows supplies the rounded surface
and rotates the wheel independently of Qt. Reduced motion retains a static mark;
unavailable composition uses the native wait cursor. Ui pauses its job timer
during initial native frame delivery, keeping redirects outside construction.
WorkWindow retains loading after native show returns. `ui_components/paint_ready.py`
acknowledges the viewport's actual first paint on the following event turn, after
the backing store has flushed. Presentation, cancellation and failure release
the native target before its dispatcher. Later reveals reuse the canvas without
another indicator. Hidden preparation stays hidden. Wheel animation requires no
timer-driven Qt painting or background thread.

Qt supplies a per-pixel transparent foreground. `winapi.composition` uses
win32more bindings and one `glass_host` constructor for card and island glass.
The nonactivating host combines `WS_EX_LAYERED` with `WS_EX_TRANSPARENT`, so
Windows skips its entire surface for input across processes; `HTTRANSPARENT`
alone only passes input within one thread. Layered opacity is initialized to
255, while `WS_EX_NOREDIRECTIONBITMAP` leaves the backdrop, tint, rim and shadow
pixels with composition. The host sits directly below the Qt foreground.
A Windows host backdrop brush is clipped to a rounded
rectangle with a 26-logical-pixel radius. A matching visual-surface mask supplies
the native soft shadow. The layer follows the foreground's final physical
rectangle after Qt paints, including at fractional DPI; it updates geometry only
when size or scale changes. Rendering uses neither a color key nor desktop images.
The solid fallback has the same rounded shape. A 1/255 foreground alpha gives
empty areas and icon padding real hit targets; rounded corners and the shadow
pass clicks through. The stop icon adds no background in any state.

Blue user and lilac assistant tints use 22% opacity over uniform backgrounds;
foreground ink remains opaque. `Frost.LIGHT` uses light ink over dark backgrounds,
`BRIGHT` uses dark ink over light backgrounds, and `SMOKED` uses an 82% tint for
mixed or unavailable observations. Captions remain inside the same surface.
High-contrast mode uses the system foreground and background colors; disabling
Windows transparency selects solid surfaces. `FrostSampler` owns one background
worker and one pending batch. Four neighboring pixel reads never block the UI.
The pointer observer submits at most every 750 ms, rejects observations for old
bounds, and defers material changes during geometry or text animation. No captured
image is retained. Recoloring resolves text layout before restoring scroll offsets.

A bounded pointer observer preserves hover-to-pause over the transparent glass.
A UI-owned mouse hook routes only vertical wheel events inside overflowing card
bounds. Its dedicated thread forwards a bounded queue without waiting for UI
work; other input passes through. The hook is removed when no scrolling cards
remain, and the thread closes with the view. Motion, pointer observation and
window creation stay in the assistant process.

External browser ownership is `Stopped | Managed | Attached`. A managed variant
carries the process, optional Windows job and visibility. An attached variant
identifies the borrowed browser; closing it only disconnects CDP. The source
selection persists separately across disconnects. Workspace-created target IDs are tracked
apart from personal tabs for session metadata; navigation and explicit tab closure
use the requested ID. Pending consent is a single WebSocket connection, whose
socket is closed on cancellation. Status inspection never starts that connection.

`BrowserSession` pairs a connection with its ownership. `Browser` obtains it
through `SessionOpener`; `NativeSessions` owns endpoint discovery, consent and
process creation. The same `connect`/`close` interface is used by callers and
tests. Attached sessions only disconnect; managed sessions close and reap the
owned process by default. The agent owns an exclusive managed Edge profile;
run-end cleanup releases every research page, including script-created and
blank pages, while retaining its process, connection and cookies. It creates a
fresh idle page and preserves Edge's mandatory profile sign-in screen. A visible
sign-in handoff survives suspended work; Stop and shutdown reap the process.
The independent collection adapters still borrow the personal browser.
Tab mutation waits use the clock supplied to `TabStrip`.

Browser page, tab and group state uses frozen, slotted dataclasses. Tab edits,
group creation/changes, placement and closure use payload variants; required
data lives on its variant. `TypedDict` defines structured tool responses and
native command wire shapes, with `Literal` values for fixed protocol fields.
Raw JSON is decoded and validated at the transport boundary. Tool and future UI
projections can share the concrete state and response types. Group selection
and pagination are pure functions of observations and arguments. The Edge tab
controller owns one hidden Favorites page, whose API calls remain separate from
ordinary page DOM evaluation. `OpenHidden` creates an explicitly requested
invisible page in the personal browser's existing context; `Browser` publishes
its immutable owned-ID set and closes those exact pages on release. Hidden pages
receive an explicit layout viewport but have no capture surface in Windows Edge;
screenshot requests fail before starting a stalled CDP copy. Only explicit
activation brings an ordinary tab forward; default opens reuse Workspace's group
without changing its expanded state.

Recording state is a projection for the UI. The journal can still be absent
while a capture starts. Publication decisions use immutable observations read
by the recording worker. The worker applies the result under its existing lock,
including the checks that prevent an older observation from undoing progress.
SQLite transactions, audio buffer ownership, and capture shutdown remain the
responsibility of their existing effect owners. A transcription batch reads its
audio, completion flag and prior text in one SQLite snapshot, so capture cannot
finish between queries and pair the finished flag with an incomplete tail.
The read transaction ends before audio assembly or network work.

`MeetingArchive` keeps creation and reopening on the same storage/publication
policy. `Meetings` accepts that archive and a transcription operation; retry
decisions return a delay with the new failure count or an exhausted state.
The worker retains cancellation and wait ownership. Teams similarly captures
configuration at composition and passes clock observations to device-flow
decisions, while the HTTP adapter owns request deadlines and cancellation.

Frozen dataclasses are shallow: nested state also uses immutable values such as
tuples, bytes, and other frozen dataclasses. External JSON and operating-system
results are validated when they enter the domain. Threading events, native
handles, SDK-owned histories, and mutable buffers retain a single explicit owner.

## Executable ownership and immutability

`scripts/architecture.py` owns recursive source inventory, import resolution and
policy reports. Editing checks supply their Git-listed snapshot; the deployed
full check can review the filesystem without Git. `scripts/check.py` uses the
same import resolution for affected-test selection. Data-record declarations are
checked from source; the retired runtime instance-storage audit is not required.
Presentation modules live in `desktop_ui`; agent behavior and shared contracts
live in `assistant`. Exact `headless` declarations reject transitive imports of
`desktop_ui` and Qt from the work frontend, canvas owner and their domain values. Source review follows both packages after module moves.

The `desktop_only` declaration keeps the entire `desktop_ui` package and
`assistant/personal_work_store.py` outside the import closure of
`automation.__main__`, including lazy imports and package initializers. The
review reports the import route to a desktop owner. Every other module is shared.

Immutable data is the repository default specified in `AGENTS.md`. All source
dataclasses require frozen slots; concrete mutable collection fields also require
an exact exception. Configuration records a rule, module, declaration, expression
and reason. Exceptions match normalized expressions, not shifting line numbers;
obsolete entries fail.
The measured keyboard engine buffers and private SDK fragment accumulators have
specific necessities. The former mailbox, overlay, Windows-key state, tool
arguments, volatile history and schema migration entries are resolved: decisions
and observations are immutable, with mutation retained at their effect owners.

Synchronization handles remain with their effect owners. Frozen records can hold
those handles without mutable record fields. The task execution-flight and
pending-owner records, conversation holder, benchmark options and usage values
now follow that pattern. Deeply immutable payloads still need review: an alias
or opaque object can hide mutation beyond what the syntax check recognizes.

## Keyboard variants

With the Charybdis attached, Ctrl+Shift+D holds dictation and Ctrl+Shift+G
holds agent speech, using Miryoku's right-hand home-row modifiers and plain left-hand letters.
Layer thumbs and home-row tap-hold letters cannot reliably stay down for speech.
Native modifier observations reuse the keyboard owner's existing bounded
`native_releases` set; captured voice keys are immutable `VoiceShortcut | ConsumedKey`
variants. Repeats never restart voice, releasing modifiers first does not end it,
and a voice key already typing stays native. Unplug, hook recovery and shutdown finish
owned voice requests while retaining swallowed physical releases. Generated input
cannot arm or finish these shortcuts. Ordinary firmware keys remain native.
Python's frozen records and tuple behavior are trusted; tests exercise this
Workspace-owned routing and lifecycle policy through `KeyboardSystem`.

The keyboard uses the same data definitions. Layout actions are an `Action`
union; the engine's mapped key events are `KeyDown | KeyUp`, each carrying a
cell and timestamp. `Decision.TAP` and `Decision.HOLD` name the two tap-hold
outcomes. The last completed tap is a frozen `LastTap` record.

`Engine.on_key` accepts native scancode, direction, and timestamp fields. Once a
key is mapped to a layout cell, it becomes one event variant. The engine handles
that variant with `match` and reuses the same object when buffering or replaying
it. Raw Windows flags stay in the input adapter; ordinary boolean properties,
such as whether caps word is enabled, remain booleans.

The engine owns bounded mutable state and sends effects through `Host`. Its
handler updates held keys and modifiers in place. Using enum-style data does not
require constructing a new engine state or a list of effects for every press.

Each engine accepts a frozen `Configuration`. Construction snapshots action
tables in built-in `frozendict`, freezes snippet definitions, validates timing,
and precomputes the longest trigger. The default configuration is built once.
Event handling reads it without rebuilding tables or wrapping each event in a
new controller state. An empty snippet set keeps the typing buffer empty.

## Keyboard and audio performance

The keyboard hook and engine run in the layout process. Durable agent/model work
runs in the automation process. Qt, microphone services and the background work
frontend run in the assistant process. The frontend prepares accepted answer and
reasoning spans before posting immutable observations to Qt; native documents
remain with their views. These frontend threads still share Python's heap, GIL
and collector with Qt. Each process has its own heap and collector, so assistant
collections cannot stop the keyboard interpreter, although the processes still
share CPU and other operating-system resources.

The keeper owns independent child restarts. Its protected event loop consumes
typed keeper requests (install, undo, keep, restart) and pause/resume commands
through `keeper_control.py`, refusing unreadable requests visibly; source replacement
keeps the keeper and unaffected children alive. The protected, standard-library
`components.py` catalogue names each child once, with its entry module, control
window, quit message, shutdown budget and readiness marker; the keeper, the
release owner and each child read it. `scripts/deploy_policy.py` makes
the restart selection from immutable manifests and both versions' import graphs.
The release owner verifies clean selected exits and retained process identities,
then requires every readiness marker to name the observed process (id and
creation time) of its component, replaced or retained. A child writes its
marker in place, so a reader sees no marker, an empty one or the complete one;
readers poll and treat an empty or unreadable marker as not yet ready. Renaming
a finished temporary file over the name is avoided: on Windows a reader that
opens the name while the rename still holds it gets a sharing violation. Failed
replacement restores only changed source before resuming. The protected full
selfcheck and trial-based agent update path keep their checks and rollback: an
agent install whose exact source digest passed the agent's affected check
repeats only its native modules, and any other install runs the full selfcheck.
Assistant unavailability produces shortcut feedback without disabling the keyboard
engine or replaying missed actions. Dictation still belongs to the assistant.

The taskbar's additional Windows-key hook has its own message thread too. A hook
on Qt's thread can delay all key delivery while that thread is busy: a native
regression reproduced a 316 ms wait before Windows skipped the unresponsive hook.
The dedicated owner handles input independently and posts taskbar toggles to Qt.
Opt-in native end-to-end checks keep the creator thread waiting while a separate
text field receives input; another check reads mapped typing and complete Unicode
dictation back from a disposable console. Readiness markers alone do not verify
that applications received input.

Physical Space now holds dictation, B toggles dictation, and N holds agent
speech on every layer. A frozen capture records its initiating request, tool,
identity and timestamp, so a Space release cannot end B's capture. The assistant
owns a one-second window-message watchdog at the existing five-minute audio
limit; shutdown discards active capture. Start, queued completion and failure
records correlate in the usage log without retaining speech content.

Keyboard recovery disables remapping before cleanup and lets physical input
through even when cleanup raises. Engine teardown clears state and attempts all
releases independently. The native host retains Workspace output ownership until
a key-up succeeds, including transient chord modifiers and rejected key-down
attempts. Its existing timer retries only those key-ups, bounded to five ticks.
Re-enabling first requires pending Workspace releases to succeed. Hook callbacks
save scalar failure evidence with file/line/function locations; diagnostic file
I/O runs on a subsequent timer tick. Exception and traceback objects never live
in pending state. Partial input rejection includes explicit accepted/requested
event counts. Voice submission failures preserve the last transcript and explain
clipboard recovery; they never retry insertion blindly.

The live hook already collects and freezes startup objects, then disables cyclic
GC until shutdown. Event data must remain acyclic under that policy. Benchmarks
deliberately enable GC to expose collection pressure rather than hide it behind
the live loop's guard.

The keyboard's fixed tables, bounded mutable state, and direct buffer updates
are deliberate. An immutable dataclass is useful for a layout description;
copying the full keyboard state on each press would need measured justification.
The same distinction applies to immutable audio formats and mutable sample
buffers. Keyboard variants use the existing allocation point for mapped events;
indicator refreshes and some other paths also allocate small objects. Audio
sample loops keep their existing buffer ownership.

Run the keyboard benchmark in a fresh process using the same Python build for
both revisions:

```powershell
.venv\Scripts\python.exe scripts\benchmark_keyboard.py --root C:\path\to\baseline --output before.json
.venv\Scripts\python.exe scripts\benchmark_keyboard.py --output after.json
```

The workload covers plain typing, home-row rolls, modifiers, layers, repeat,
voice keys, and tap-hold timers without sending input. It uses GC normally and
reports latency percentiles, maximum observed latency, collection counts and
pauses, and peak traced live memory. Inputs and timing storage are allocated
before timing; allocation tracing runs separately so it does not distort the
latency measurements. Peak live memory is not cumulative allocation churn.

Compare the distributions over multiple rounds and retain the worst observed
latency. The benchmark also records source hashes and whether the engine imported
the assistant. It measures engine decisions with a silent host; native hook,
`SendInput`, and operating-system scheduling require separate desktop evidence.

For the 2026-10-29 firmware-keyboard change, three native Python 3.15.1
10,000-event rounds measured median/p99 engine latency of 12.9/61.1 µs before
and 8.4/47.8 µs after, with the same 2,191-byte traced peak, no GC collections,
and no assistant imports. The engine is unchanged; desktop load prevents a
speedup claim. Reports are `workspace-keyboard-before.json` and
`workspace-keyboard-after.json` in Windows Temp. A separate 200-observation run
with the connected Charybdis measured a 79.1 µs median and 1,358.6 µs maximum
for device enumeration and identity selection with GC enabled. This runs on
the 200 ms message-loop timer, outside key callbacks. Win32 owns enumeration;
tests cover Workspace's device selection, suspension, output releases, language
selection, and restoration policy rather than the OS enumeration algorithm.

For the 2026-10-28 import-ownership cleanup, paired native Windows Python 3.15.1
runs used five 100,000-event rounds against the original and current engine.
Median latency was 7.4 → 6.5 µs and median p99 was 42.7 → 38.3 µs. Both retained
the same 1,943-byte traced peak, no measured GC collections and no assistant
imports. Desktop load varies, so these timings establish no speedup. The engine's
non-import AST is unchanged. Full reports are in Windows Temp as
`workspace-keyboard-imports-paired-before.json` and
`workspace-keyboard-imports-paired-after.json`.

For the 2026-10-26 voice/recovery change, five 100,000-event rounds compared the
prior deployed source with the changed engine under the same Linux Python 3.15.1
build. Median event latency was 3.244 → 3.350 µs; median p99 was
10.730 → 11.618 µs; the worst observed event was 491.556 → 400.947 µs.
Traced peak live memory stayed at 1,943 bytes, with zero GC collections and no
assistant imports. These are synthetic engine measurements; native output
ownership and Windows scheduling require the separate boundary and desktop
checks described above.

Tabbed window groups were removed on 2026-10-26. Startup, window navigation,
keyboard commands and desktop surfaces use ordinary windows directly.
Workspace no longer creates native tile slots, hides selected apps, changes their
caption styles, or runs group polling and crash-recovery companions.

After group removal, the same synthetic workload measured 2.925 µs median
latency and 9.071 µs median p99, with the same 1,943-byte peak and zero GC
collections.


## Bootstrap and request-boundary migration

The activated launcher composes `keeper_ui.launch` with `keeper.main`. The UI
owner acquires the singleton file lock before creating Qt, then retains that
lock through the keeper loop. The keyboard imports the component catalogue,
not the keeper. Its direct executable entry activates the runtime
before module-level guarded UI imports. All launchers run directly on Python
3.15; Windows associations use the installed interpreter, while the portable
command launcher uses `pyw -3.15` without a Python handoff. No interpreter is
embedded in the installation or ZIP.

`selfcheck.check` passes the selected candidate root to runtime activation. An
adjacent candidate runtime takes precedence over the inherited runtime, even
when selfcheck itself was launched from another source tree. Dependency manifest
and recovery parsing use standard-library JSON and structural validation because
they must remain usable before loading or trusting bundled Pydantic/Qt. Unknown
manifest fields stay objects; ABI fields are validated before activation. The
keeper's native function prototypes preserve pointer-sized handles and message
payloads, replacing the former unprototyped DLL assertion.

Panel storage validates the saved bounds used to select the conversation monitor.
Retired pin/display options, preference saving and unused panel fitting/docking
helpers are removed; native toast placement remains with its active view.
Activity `Sample` binds the observation, time and agent state;
`Policy` owns retention and whether collection is enabled. Public activity
context has an immutable typed projection until its JSON serialization boundary.
