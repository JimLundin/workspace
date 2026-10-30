# Functional design

Live agent activity appears in a bounded lower-right trail. Each public update starts
a phase bubble, which grows with its tool calls. The newest phase expands and stays
opaque; earlier phases collapse, move upward and fade. Full history retains the
complete interaction. Clarification redirects take precedence over transient steps.
Bubbles remain read-only; a tooltip directs replies to the agent voice button.
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

The main places to read are:

| Module | Pure model and decisions | Effect owner |
| --- | --- | --- |
| `miryoku/firmware.py` | Firmware keyboard identity, immutable prior-layout intent and Ctrl+Alt letter voice-shortcut decisions | `winapi/keyboard_devices.py` observes attached device names; the keyboard message loop pauses remapping and restores prior intent outside key callbacks; `keyboard_language.py` keeps firmware output on English (US); `Keyboard` owns paired voice requests and immutable captured-key observations |
| `automation/personal_work.py`, `assistant/personal_work_service.py` | Work threads, source identity, bounded associations, remembered corrections, stale-edit rejection and model-plan reconciliation | `PersonalStore` validates transactional SQLite snapshots; `PersonalWork` owns polling, review scheduling, queued edits and immutable publication |
| `assistant/personal_work_sources.py`, `personal_work_model.py`, `personal_work_tools.py` | Validated observed browser evidence, bounded review input and agent work-catalog contracts | `BrowserSources` owns read-only Edge collection; `Correlator` owns a cancellable structured model request without action tools; `personal_work_panel.py` composes the native local canvas; `work_canvas_detail.py` owns revision-bound in-place drafts |
| `assistant/work_canvas_model.py`, `work_canvas_context.py`, `work_canvas_layout.py`, `work_canvas_gestures.py`, `canvas_activity.py` | Work as context, canonical contributions, arbitrary nested groups, shared source identity, nested bubbles on one native scene, arrangements/pins, substantive results, exact clarification routes, reply reconciliation and quiet attention policy | `WorkCanvas` in `work_canvas.py` is the single owner of the validated local SQLite document and its observation, attention, answer, continuation and gesture-commit policy; `Ui` marshals to Qt and renders its returned documents and announcements; `personal_work_panel.py` owns native pointer capture and previews, shared `ui_components/canvas_bubble.py` controls handle both containers and contributions; existing input/work handlers deliver answers |
| `assistant/ui_components/` | Shared bubble outline, palette/ink, text presentation, headings and controls | Native component owners paint Qt surfaces and adapt Windows window behavior; feature controllers consume components directly |
| `assistant/work_canvas_commands.py`, `work_canvas_tools.py`, `work_canvas.py` | Atomic structural edits, paged reads, editable fingerprints, bounded evidence-driven scheduling and durable run retention | `Ui` marshals bridge commands to Qt and refreshes the native panel after `WorkCanvas` confirms persistence; `App` constructs the one `WorkCanvas`, submits identified research or exact saved user instructions and recovers uncommitted bindings |
| `assistant/work_bridge_contracts.py`, `browser_documents.py` | Validated desktop bridge variants and document stream contracts | The bridge joins feed, catalog and canvas wire contracts without a feed-to-canvas import cycle; `Browser` owns authenticated CDP streams and exclusive bounded file collection |
| `assistant/work_window.py`, `work_canvas_window.py`, `ui_components/bubble.py`, `ui_components/text.py` | Current observations and bounded preview presentation | Desktop startup prepares the hidden native canvas; Qt retains group/header identities, materializes visible nested bubbles and shapes previews during viewport painting |
| `assistant/llm.py` | System, user, assistant, and tool-result message variants; request serialization | HTTP client functions |
| `assistant/agent_session.py` | Typed events, messages, agent request rows over the durable questions and approvals, session transitions, and presentation | `agent_window.py`, `agent_toasts.py`, `toast_card.py` |
| `assistant/agent.py`, `agent_toolsets.py`, `task_profiles.py`, `agent_execution.py` | Tool dispatch, approval and observation recording for one durable work claim; each task profile's toolset and execution (conversation, admitted desktop context, recovery and completion check) | `AgentExecution` selects the profile run and owns per-conversation SDK history, source drafts and run cleanup; `WorkExecution` owns the claim's effects |
| `assistant/agent_tools.py`, `desktop_tools.py`, `browser_tools.py`, `business_tools.py`, `self_change_tools.py`, `meeting_tools.py`, `feed_agent_tools.py`, `work_canvas_tools.py`, `personal_work_tools.py`, `task_tools.py` | Tool families: each `Tool` declares its schema, handler, read/change classification with resources, reconciliation proof, readback evidence and visible display; handlers describe each exact `Operation` to approval and effect | The agent composes the families over its `Session`; `Screen` and `SelfChange` own the latest screenshot and the source draft's check/install state |
| `automation/task.py`, `store.py` | Durable task, request profile, agent request, reply, action, and run variants; controls and stale-run decisions | `TaskStore` owns SQLite transactions and validates stored records |
| `automation/controller.py`, `execution.py`, `actions.py` | Work outcomes, recovery context, exact operations, observation evidence, reconciliation proof and verification decisions | `WorkController` owns execution lifetime; `Actions` owns cancellable effect coordination |
| `automation/routines.py`, `context.py` | Trigger occurrences, accepted handoffs, context relevance and freshness | The routine/context stores own persistence; `meeting_events.py` owns transcript delivery and startup scanning |
| `assistant/work_window.py`, `work_agent.py`, `work_service.py` | Work commands, immutable projections, conversation/task selection and meeting RPC acceptance | `WorkAgent` owns frontend observation and asynchronous UI delivery; `WorkService` composes journal/transport calls and RPC replies; `WorkWindow` schedules its native view |
| `automation/ipc.py`, `bridge.py` | Validated process messages and bounded event projections | Bridge client/server own authenticated byte transport; `automation/app.py` composes the native worker |
| `assistant/action_text.py` | Readable action targets and results, formatted before preview limits | `agent.py` publishes previews; session presentation handles raw payloads too |
| `assistant/notifications.py`, `notification_text.py`, `notification_reading.py`, `toast_style.py` | Grouped turns, attached results, optional steps, reading states, lifetimes, tints, and motion sampling | `agent_toasts.py`, `toast_card.py`, `qt_text.py`, `qt_ui.py`, `winapi/composition.py`, `winapi/appearance.py`, `winapi/notification_input.py` |
| `assistant/browser_values.py`, `browser_session.py`, `browser.py` | Browser ownership, immutable page/tab/group observations and command variants, group selection, typed paginated projections | `Browser`, `NativeSessions`, `Cdp`, `browser_tabs.TabStrip` and a cancellable connection wait |
| `assistant/recording_state.py` | Audio batches, stored observations, completion rules, retry policy, stale-update rejection, and recording controls | `meetings.py` and `meeting_store.py` |
| `assistant/meeting_followup.py`, `meeting_requests.py` | Frozen transcript bundles, exact citations, sourced actions and drafts, preparation identity | `meeting_followup_store.py` owns verified publications and revision-checked edits; `MeetingRequests` owns saved preparations |
| `assistant/meeting_workflow.py` | Catalog, work and package observations; identified edit commands and receipts | `MeetingWorkflow` owns background I/O; `meeting_panel.py` owns Qt selection, local edits and explicit handoff |
| `assistant/meeting_execution.py`, `meeting_tools.py`, `outlook.py` | Constrained meeting execution, bounded source reads and verified draft outcomes | The work process owns generation; `outlook.ps1` owns Outlook COM observation and draft operations |
| `assistant/teams.py` | Frozen device flow, polling deadlines, retry intervals and read/write requests | `Teams` owns the shared delegated Microsoft session; `SystemClock`, `TokenStore`, and `graph_http.Http` own clock, encrypted credentials and bounded transport |
| `assistant/web_apps.py`, `business_tools.py` | Typed app commands, exact task/chat/mail conversation identities, expected-value checks, private tool schemas and readback | `WebApps` uses the existing browser's wake/evaluate lifecycle and the applications' own controls; native browser fixtures verify task/chat/mail selection and draft preservation |
| `runtime.py` | Dependency ABI validation | `activate` |
| `assistant/control_policy.py` | Immutable native message actions and tray observations, menu projection, press-only control routing, startup ordering and queued file handoff | `AssistantApp` owns native interpretation, layout transport, UI feedback and worker lifetime |
| `assistant/activity.py` | Bounded window history reduced from a window or desktop-state observation | `ActivityTracker` and the Windows foreground reader |
| `assistant/communications.py` | Source identities, grouped pending chat tickets, captured handling revisions and reply evidence | `communications_service.py` owns encrypted settings/drafts/handling, collection and effects; `communications_browser.py` owns exact-chat and Activity DOM boundaries; `Ui` supplies source observations as agent context; canvas activity owns user attention |
| `assistant/inbox.py`, `feed_items.py`, `notifications.py`, `console_requests.py` | Optional history selection, shared agent/proposal bubble projection, bounded console requests and exact answer transitions | `agent_toasts.py` and `toast_card.py` own the read-only floating feed, history and action buttons; `console_inbox.py` owns the local hook transport and pending lifetime; `scripts/inbox_hook.py` returns supported CLI hook responses |
| `assistant/feed_triage.py` | Bounded source candidates, revision-bound grouped assessments, quiet/action/completed/dismissed dispositions, explicit feedback and stale-result rejection | `feed_triage_service.py` owns coalesced background model calls, DPAPI plan/preferences and authenticated local transport, with explicit server-construction and cancellable-wait dependencies; `feed_agent_tools.py` lets the main voice agent inspect and maintain the same plan; `Ui` retains immutable boards as agent context; ordinary arrivals do not become floating cards |
| `assistant/feed_origin.py`, `feed_items.py` | Source application identity, grouped provenance, formatted body spans and compact reaction counts | `feed_icons.py` owns native vector marks; `toast_card.py` anchors badges over the upper-left glass edge; the triage board keeps reaction counts quiet |
| `assistant/notification_sources.py` | Windows notice updates, their captured handling marks, the notification filter and the joined pending feed | `NotificationSources` owns the encrypted filter/handling store and native dismissal on Qt's thread, apart from the Teams worker; `feed_items.act` addresses it with the revisions a card rendered |
| `assistant/system_notices.py` | Native notification identities, quiet history baselines, banner coverage and validated timestamps | `winapi/notifications.py` owns observations and native dismissal; `notification_banners.py` owns the recoverable banner-setting lease; `desktop_bar.py` forwards observations to `Ui`, whose `notification_sources.py` owner keeps them |
| `assistant/monitor_layout.py`, `tiling.py`, `tiling_commands.py` | Monitor observations, window distribution and native window command mapping | `MonitorLayout` owns automatic redistribution; `GlazeWM` owns manager startup and ordinary window tiling |
| `assistant/shell_state.py` | Windows-key tap decisions | `shell_controls.py` owns taskbar recovery and a dedicated Windows-key message thread; keyboard callbacks post toggles and pass other input through |
| `assistant/geometry.py`, `panel.py`, `rich_text.py` | Geometry, preferences, and Markdown values | Qt views and preference files |

Feed context refresh and source-date corrections reconsider automatic action and
quiet assessments. Explicit user quieting is a separate disposition and remains
handled across context, date and filtering changes. `feed_contracts.py` separates
public snapshots and handoff receipts from stored retry prompts;
`communications_state.py` owns saved communication contracts and `state_store.py`
serializes their immutable values at encrypted IO.

The curated side feed exposes at most three source work items, chosen by
importance and laid out with the highest priority at the top. Equal priorities
favor waiting work over newer arrivals. The complete plan stays in the triage
board for the voice agent; dismissing a visible proposal advances the next item
into view. Dismissal saves the exact observed revisions without completing work
or replying to its source. Polls, restart and preference edits preserve it; new
source evidence gets reviewed again. Storage failure leaves the proposal visible.
Dismissal sits fully inside the bubble at a fixed upper-right position, so
successive cards keep the same click target. Clicking a proposal bubble expands
or collapses its details. Source badges overlap
the upper-left edge of the bubble. Text and action rows use the full
inner width with symmetric padding. Collapsed curated cards reserve space for
their header and actions; crowded feeds show fewer cards instead of clipping controls. During card
resizing, text geometry uses the current visible width and its document wraps
to the actual Qt viewport, including the first frame after content changes.
The thin painted scroll indicator stays outside that viewport; the hidden
native scrollbar reserves no text gutter. Floating text explicitly clears the
application theme's padding and corner radius, so its viewport matches the
measured text area. Regression coverage applies the production theme.
Curated proposals place their meaningful title in the compact header beside
the app icon and right-aligned controls, with no duplicated title in the body.
Feed cards use a consistent width and a 13-point title. Compact titles
end in an ellipsis; expanding a card wraps the complete title above its details.
The full title remains available to accessibility and in a tooltip.
The title font explicitly overrides the global theme and matches measurement.
Clicking the bubble reveals details without a separate expand button; suggested
actions and the corner-aligned dismiss button keep their independent behavior.
Collapsed cards show the header, a bounded recommendation preview and one to
three concrete agent solutions, with the recommendation first. Native buttons and voice selection use
the same exact proposal revision and choice identity. Selecting a solution queues
an identified investigation or preparation task; repeated selection reuses that
identity. Source and model text cannot extend the fixed preparation scope into
sending, console approval or external changes. Queue acknowledgment is distinct
from completion, and a failed submission leaves choices available. Old proposals
without choices expose their saved agent recommendation as a preparation action,
and are reconsidered when their matching source evidence is present. This
presentation fallback does not fabricate live source evidence. An explicit disclosure
expands the summary, suggested action and captured source content whose revision
matches the proposal. Missing original evidence is labeled as unavailable.
Each pending chat message is its own evidence candidate. The model may group
messages only when they concern the same request; expansion never dumps an entire
chat merely because the request came from it. Request and suggested approach have
separate formatting. Meaningful rejection records the user's reason against the
captured proposal revision, distinct from dismissal and without sending a reply.
The agent considers refusals, corrections and no action as well as agreement.

The feed is a work queue with accumulated context. `feed_work.py` reads relevant
fresh project notes and explicit preferences from the existing context store,
recent and linked tasks from the task journal, recorded task answers, and
short-lived app/title activity. Matching project history takes priority over
unrelated recent tasks within the context budget. `feed_triage_service.py` supplies that bounded
context to the configured agent model. `feed_research.py` uses the existing Agents
SDK for a bounded background investigation before options appear. Its tools can
retrieve topic-specific saved context, captured conversation history including own
and handled replies, relevant local text files/directories, and public web research.
It has no general agent, desktop control, write, send or console-answer tools.
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

`feed_history.py` owns immutable scoped decisions and exact handoffs. A selected
pill retains its preparation scope. `work_feed_reply` saves the user's actual
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
again at the bridge. `feed_triage.edited` is the single pure transition for explicit
board edits: it owns dispositions, rule preservation, reconciliation and the
recorded decision, so `Triage` only persists and publishes the result.
History stays in the same floating feed; the separate legacy panel is removed.
Source work never scrolls automatically; expanded overflow uses manual scrolling.
Typed input is available on explicit request and closes after submitting to Workspace.
The reply composer begins with one row and grows to four rows before scrolling.
Its submit action sits inside the same rounded surface, aligned with the last row.
Enter submits; Shift+Enter adds a line. Drafts and exact reply destinations are
preserved when other bubbles arrive.

Session events include their timestamps. IDs and clocks are supplied by the
work controller, so a sequence of events can be replayed or branched
without changing its source state. Views receive the immutable session itself.
An agent request row projects the durable question or approval itself, with
the detail the person reviews and their reply: pending, answered, an approval
decision, or cancelled. A reply for the wrong request kind or an already
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

Consequential tools record an attempt after validation and any required
approval, immediately before their effect. The journal retains fingerprints
and bounded outcomes, without raw tool arguments or SDK histories. File writes
can be checked by destination and expected digest. Other unknown effects require
fresh observations before reconciliation. Completion checks the full action
record, independently of the UI's display page. A late callback cannot revive a
cancelled task or replace an already verified action with a weaker outcome.

Questions and redacted approval requests are durable. Full approval previews
remain volatile, tied to their run, goal revision, exact operation, and request
identity. A view must display the matching preview before approval is accepted.
After a lost preview, refreshing creates a new request identity. Local IPC uses
authenticated, bounded JSON byte frames with worker epochs and event cursors;
it never deserializes Python objects. UI, microphone, meeting capture and live
web-app pages remain with the assistant. The worker owns Teams, native actions
and its external-browser session; web-app operations cross typed RPC.

Standing instructions start disabled. An atomic accepted handoff separates an
authorized occurrence from an unaccepted one that disable or edit can invalidate.
Retrying a handoff submits the same routine occurrence, and missed intervals
coalesce. Transcript delivery follows final successful export, independently
of which recording owns the UI. Startup scanning repairs missed delivery and
baselines pre-existing completed transcripts on first installation. Saved
preferences and expiring project notes are explicit; fresh retrieval excludes
expired text while retaining its source for reinspection.

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
the attached result and expanded steps separately. Reasoning summaries never become notification text or
trigger text layout. Action previews format complete payloads before shortening
them, omit transport IDs and search controls, and leave the model's tool results
unchanged. Both conversation views use the same readable presentation.

Qt owns the assistant's main thread, its expiry and animation callbacks, and all
assistant windows. A separate control thread creates the hidden Windows message
window and runs its message loop. `assistant/qt_ui.py` shares Windows composition
across assistant views without tying the application lifetime to a view.
`keeper_ui.py` owns the keeper's separate protected Qt event loop. The bundled
UI uses Qt; no GUI objects cross the keyboard process boundary.

Meeting follow-through shares the work journal and selected saved transcript
versions. Its owner queues catalog reads, preparation and revision-checked edits
off the UI thread, and closes before WorkAgent. The Meetings view retains raw
editor buffers by task, package version and artifact. Only the matching save
receipt clears a submitted edit; newer typing remains against the acknowledged
revision. Multiple saved packages require an explicit choice when no selection
is retained. Opening an email uses the saved draft file, after local edits have
been saved or explicitly reloaded.

The owner animates at most five cards, retargeting from current geometry. Each
notification fits its rendered content up to 360 logical pixels (280 for user
requests), independent of the history window. Headers, the stop icon and voice
hints contribute to that width. The pure `allocate` function reserves readable
previews and gives pending questions and recent messages the remaining height.
On very small work areas it removes older entries from the projection.
`qt_text.Document` measures Markdown using separate `QTextDocument` instances,
with the same fonts, paragraph margins and wrapping as the visible text. A line
that wraps at the maximum width already needs that width; shorter lines get an
exact pixel measurement. No visible window is resized for measurement.

Steps, result, header and footer get separate rectangles; viewports end on
complete display lines. All reply text remains in the native text document,
with no character cutoff. The result and steps have independent scroll positions
and small overflow markers. Steps use smaller type and a 200-logical-pixel
height budget, reserving room for the attached result. Collapsing only changes
the steps' viewport; the result retains its widget, selection and reading
position. `Frame` carries top, width, height, opacity and steps height together.
Every active card retargets on the same clock, so growing and shrinking neighbors
retain their gaps. Native positioning anchors the right edge; the text wraps at
its destination width, and the stop icon follows the visible right edge.
Unchanged frames do not repeat native movement after fractional DPI rounding.

`rich_text.changed_tail` preserves the unchanged styled prefix, including a
partially expanded span. Qt cursor offsets count UTF-16 units, so astral emoji
and closing Markdown preserve earlier text and selection. The display cursor
stays at its existing position when text arrives; new replies start at the top.
Recording previews explicitly follow their newest line after Qt resolves layout.
New reply text gets a bounded set of short-lived extra selections to reveal its
ink; later packets do not dim earlier text. Motion uses a 280 ms base and 160 ms
fast duration with `cubic-bezier(0.32, 0.72, 0, 1)`. Keyboard disclosure is immediate.
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
receipt rejects submission. Ui routes speech to the selected waiting question on
the visible canvas before the conversation handler; failed replies cannot become
new work. Dictation retains its independent capture and transcription path while
the durable agent runs or queues instructions.

First canvas reveal presents an 80-logical-pixel nonactivating indicator before
creating or rendering the view. `ui_components/canvas_loading.py` owns its
transient lifetime. `winapi/composition_spinner.py` uses the same top-level
NOREDIRECTIONBITMAP host as desktop glass; Windows supplies the rounded surface
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
win32more bindings to create a separate, nonactivating, input-transparent HWND
directly below it. A Windows host backdrop brush is clipped to a rounded
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
owned process. Tab mutation waits use the clock supplied to `TabStrip`.

Browser page, tab and group state uses frozen, slotted dataclasses. Tab edits,
group creation/changes, placement and closure use payload variants; required
data lives on its variant. `TypedDict` defines structured tool responses and
native command wire shapes, with `Literal` values for fixed protocol fields.
Raw JSON is decoded and validated at the transport boundary. Tool and future UI
projections can share the concrete state and response types. Group selection
and pagination are pure functions of observations and arguments. The Edge tab
controller owns one hidden Favorites page, whose API calls remain separate from
ordinary page DOM evaluation. Only explicit activation brings a tab forward;
default opens reuse Workspace's group without changing its expanded state.

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
Application modules stay
in their current locations while this enforcement is established.

Immutable data is the repository default specified in `AGENTS.md`. All source
dataclasses require frozen slots; concrete mutable collection fields also require
an exact exception. Configuration records a rule, module, declaration, expression
and reason. Exceptions match normalized expressions, not shifting line numbers;
obsolete entries fail. A necessity is distinct from existing migration debt.
The measured keyboard engine buffers and private SDK fragment accumulators have
specific necessities. The former mailbox, overlay, Windows-key state, tool
arguments, volatile history and schema migration entries are resolved: decisions
and observations are immutable, with mutation retained at their effect owners.

Synchronization handles remain with their effect owners. Frozen records can hold
those handles without mutable record fields. The task execution-flight and
pending-meeting records, conversation holder, benchmark options and usage values
now follow that pattern. Deeply immutable payloads still need review: an alias
or opaque object can hide mutation beyond what the syntax check recognizes.

## Keyboard variants

With the Charybdis attached, Ctrl+Alt+D holds dictation and Ctrl+Alt+G
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
See [testing through explicit dependencies](testing-dependencies.md) for the
replacement tests and before/after keyboard measurements.

## Keyboard and audio performance

The keyboard hook and engine run in the layout process. The agent and UI run in
the assistant process, with a separate Python heap and garbage collector. Agent
collections cannot stop the keyboard interpreter, although both processes still
share CPU and other operating-system resources.

The keeper owns independent child restarts. Its protected event loop consumes
typed pause/resume commands through `keeper_control.py`; source replacement
keeps the keeper and unaffected children alive. The protected, standard-library
`components.py` catalogue names each child once, with its entry module, control
window, quit message, shutdown budget and readiness marker; the keeper, the
release owner and each child read it. `scripts/deploy_policy.py` makes
the restart selection from immutable manifests and both versions' import graphs.
The release owner verifies clean selected exits and retained process identities,
then requires every readiness marker to name the observed process (id and
creation time) of its component, replaced or retained. Failed
replacement restores only changed source before resuming. The protected full
selfcheck and trial-based agent update path keep their full checks and rollback.
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
keyboard commands and desktop surfaces use ordinary GlazeWM windows directly.
Workspace no longer creates native tile slots, hides selected apps, changes their
caption styles, or runs group polling and crash-recovery companions.

After group removal, the same synthetic workload measured 2.925 µs median
latency and 9.071 µs median p99, with the same 1,943-byte peak and zero GC
collections. Tiling startup now belongs to `MonitorLayout`, independently of
any tab-group controller.


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

Graph transport accepts one immutable HTTP request and an independently owned
cancellation event. Its bounded generic JSON-object responses stay at the
transport boundary; Teams validates the fields it consumes. Graph reads and
writes are explicit immutable alternatives. Chat creation and message bodies
have distinct typed Pydantic wire shapes; neither retains mutable request data.

Panel storage validates the saved bounds used to select the conversation monitor.
Retired pin/display options, preference saving and unused panel fitting/docking
helpers are removed; native toast placement remains with its active view.
Activity `Sample` binds the observation, time and agent state;
`Policy` owns retention and whether collection is enabled. Public activity
context has an immutable typed projection until its JSON serialization boundary.
