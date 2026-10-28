# Functional design

A work interaction stays in one floating bubble: its source title and badge, thinking,
questions, pill options and final reply share the same card. Bubbles remain read-only;
a tooltip directs replies to the agent voice-to-text button. Only one bubble expands
at a time.
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
| `assistant/llm.py` | System, user, assistant, and tool-result message variants; request serialization | HTTP client functions |
| `assistant/agent_session.py` | Typed events, messages, questions, approvals, session transitions, and presentation | `agent_window.py`, `agent_input.py`, `agent_toasts.py`, `toast_card.py` |
| `assistant/agent_runner.py` | Tasks, FIFO queueing, completion, and stopping transitions | `AgentRunner` owns threads and views; `agent_execution.py` owns SDK history and turn cleanup |
| `automation/task.py`, `store.py` | Durable task, wait, reply, action, and run variants; controls and stale-run decisions | `TaskStore` owns SQLite transactions and validates stored records |
| `automation/controller.py`, `execution.py`, `actions.py` | Work outcomes, recovery context, action classification, and verification decisions | `WorkController` owns execution lifetime; `Actions` owns cancellable effect coordination |
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
| `assistant/teams.py` | Frozen device flow, polling deadlines, and retry intervals from clock observations | `Teams`, `SystemClock`, `TokenStore`, and `graph_http.Http` |
| `runtime.py` | Bootstrap handoff plan and dependency ABI validation | `execute_bootstrap`, `bootstrap`, and `activate` |
| `assistant/activity.py` | Bounded window history reduced from a window or desktop-state observation | `ActivityTracker` and the Windows foreground reader |
| `assistant/communications.py` | Source identities, grouped pending chat tickets, captured handling revisions and reply evidence | `communications_service.py` owns encrypted settings/drafts/handling, collection and effects; `communications_browser.py` owns exact-chat and Activity DOM boundaries; `agent_toasts.py` owns the personal work feed |
| `assistant/inbox.py`, `feed_items.py`, `notifications.py`, `console_requests.py` | Optional history selection, shared agent/proposal bubble projection, bounded console requests and exact answer transitions | `agent_toasts.py` and `toast_card.py` own the read-only floating feed, history and action buttons; `console_inbox.py` owns the local hook transport and pending lifetime; `scripts/inbox_hook.py` returns supported CLI hook responses |
| `assistant/feed_triage.py` | Bounded source candidates, revision-bound grouped assessments, quiet/action/completed/dismissed dispositions, explicit feedback and stale-result rejection | `feed_triage_service.py` owns coalesced background model calls, DPAPI plan/preferences and authenticated local transport; `feed_agent_tools.py` lets the main voice agent inspect and maintain the same plan; `Ui` publishes immutable boards to the floating conversation |
| `assistant/feed_origin.py`, `feed_items.py` | Source application identity, grouped provenance, formatted body spans and compact reaction counts | `feed_icons.py` owns native vector marks; `toast_card.py` anchors badges over the upper-left glass edge; the triage board keeps reaction counts quiet |
| `assistant/system_notices.py` | Native notification identities, quiet history baselines, banner coverage and validated timestamps | `winapi/notifications.py` owns observations and native dismissal; `notification_banners.py` owns the recoverable banner-setting lease; `desktop_bar.py` forwards observations; `native_feed.py` projects arrivals and local handling immediately while the Teams worker is occupied |
| `assistant/monitor_layout.py`, `tiling.py`, `tiling_commands.py` | Monitor observations, window distribution and native window command mapping | `MonitorLayout` owns automatic redistribution; `GlazeWM` owns manager startup and ordinary window tiling |
| `assistant/shell_state.py` | Windows-key tap decisions | `shell_controls.py` owns taskbar recovery and a dedicated Windows-key message thread; keyboard callbacks post toggles and pass other input through |
| `assistant/geometry.py`, `panel.py`, `rich_text.py` | Geometry, preferences, and Markdown values | Qt views and preference files |

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
Collapsed cards show the header and one to three concrete agent
solutions, with the recommendation first. Native buttons and voice selection use
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
History stays in the same floating feed; the separate legacy panel is removed.
Source work never scrolls automatically; expanded overflow uses manual scrolling.
Typed input is available on explicit request and closes after submitting to Workspace.
The reply composer begins with one row and grows to four rows before scrolling.
Its submit action sits inside the same rounded surface, aligned with the last row.
Enter submits; Shift+Enter adds a line. Drafts and exact reply destinations are
preserved when other bubbles arrive.

Session events include their timestamps. IDs and clocks are supplied by the
controller or input broker, so a sequence of events can be replayed or branched
without changing its source state. Views receive the immutable session itself.
Questions carry a pending, answered, or cancelled reply; approvals carry a
decision. A reply for the wrong request kind or an already resolved request
leaves the session unchanged.

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
interpreter excludes Tcl/Tk; no GUI objects cross the keyboard process boundary.

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
rotates existing spinner shapes without measuring text again.

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
same import resolution for affected-test selection. `tests/test_slots.py` uses
the inventory instead of immediate-package file lists. Application modules stay
in their current locations while this enforcement is established.

Immutable data is the repository default specified in `AGENTS.md`. All source
dataclasses require frozen slots; concrete mutable collection fields also require
an exact exception. Configuration records a rule, module, declaration, expression
and reason. Exceptions match normalized expressions, not shifting line numbers;
obsolete entries fail. A necessity is distinct from existing migration debt.
The measured keyboard engine buffers and private SDK fragment accumulators have
specific necessities. The remaining mailbox, overlay, Windows-key state, tool
arguments, volatile history and schema entries are explicit migration work, not
general permissions to introduce mutable data.

Synchronization handles remain with their effect owners. Frozen records can hold
those handles without mutable record fields. The task execution-flight and
pending-meeting records, conversation holder, benchmark options and usage values
now follow that pattern. Deeply immutable payloads still need review: an alias
or opaque object can hide mutation beyond what the syntax check recognizes.

## Keyboard variants

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

The taskbar's additional Windows-key hook has its own message thread too. A hook
on Qt's thread can delay all key delivery while that thread is busy: a native
regression reproduced a 316 ms wait before Windows skipped the unresponsive hook.
The dedicated owner handles input independently and posts taskbar toggles to Qt.
Opt-in native end-to-end checks keep the creator thread waiting while a separate
text field receives input; another check reads mapped typing and complete Unicode
dictation back from a disposable console. Readiness markers alone do not verify
that applications received input.

Physical Space now holds dictation, B toggles dictation, and N toggles agent
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
.python\python.exe scripts\benchmark_keyboard.py --root C:\path\to\baseline --output before.json
.python\python.exe scripts\benchmark_keyboard.py --output after.json
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
