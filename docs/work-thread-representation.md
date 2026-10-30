# Work threads on the local desktop canvas

29 October 2026. The user selected a canvas as the organizing surface for their
work. Workspace owns this native Python/Qt window. Edge supplies signed-in Teams,
Outlook and Kanban resources; the Workspace application is local. Shared
Workspace remains paused. The earlier browser study is historical exploration on
`prototype/work-thread-representation-20261029`, not the selected implementation.

## Representation

A work thread is a container for an ongoing outcome or responsibility. It supplies
its name, goal, current state and connections; classification does not create a
second bubble announcing that work exists. Emails, Teams conversations, Kanban
tickets, documents, notes, clarifications, research findings and drafts are the
contributions inside that context. Kanban uses a dedicated amber board badge.

The same canonical source can support several work contexts through explained
connections. It appears once on the shared canvas; connections lead between
related bubbles without opening a separate workspace. Arbitrary canvas groups can contain pieces,
work contexts and other groups. They can also live inside a work context. Moving
visual membership leaves factual source connections intact. Explicit grouping
takes precedence on the overview; cycles and conflicting parents are rejected.

Workspace's saved catalog owns work content, source identities, revisions and
corrections. The agent collects observed browser information and updates
connections. A separate canvas document owns groups, coordinates, pins,
notes, agent contributions and work-to-run bindings in
`%LOCALAPPDATA%\workspace\work\canvas.sqlite3`. Arrangement is absent from
agent review input. One native scene retains the complete arrangement.
Collapsing a group preserves its hidden pieces and pins.

Measured shelves arrange nested containers and their real bubble heights, using
the native viewport width at normal reading scale. Wider containers are placed
first. Zooming does not rearrange work. Expansion reflows automatic neighbours;
manually moved pieces stay pinned. Arrange preserves pins; Arrange all releases
pins on the shared canvas. Graphviz, NetworkX and Grandalf were assessed;
their native or numerical/general graph dependencies exceed this narrow ordered
containment policy. Python and Qt's layout/paint mechanics are trusted; tests
cover Workspace's membership, navigation, placement and native integration.

## Interaction

Use the Canvas button beside the menu on Workspace's floating toolbar. It opens
a dedicated native window with no tabs, maximized on first opening. Restore keeps
a smaller window through subsequent redirects. Drag bubbles to arrange them;
drag empty space or scroll a trackpad to pan, use Control + wheel or pinch to
zoom, and Center to orient yourself. One compact toolbar sits at the bottom
center: agent input, search, Center, clarifications, options and Close.
Search expands in the same bar when clicked or with Control + F. Escape closes
search, collapses selected inline details or contents, then closes the canvas. Close always exits the canvas.
Drag the toolbar background to move a restored window. Window controls live in
the options menu. Scene-anchored dots keep their visible size, using
coarser spacing at low zoom instead of shrinking a raster tile. Click a bubble
to open its details. Its title, upper-left badge,
outline and palette reuse the floating notification components.
Work context details show the goal, current situation and next step and allow
revision-bound editing.
A background update refreshes evidence while retaining unsaved editing fields.

The options menu collapses groups into compact previews or shows all
contents. Each container has a center control and a context menu; double-click
expands its ancestors and centers it on the same canvas. Neighboring work stays
present. New group creates a bubble inside the selected context; Group selected
piece moves a contribution or container into a chosen group.

Source details show observed content, connected work and an explanation for the
selected connection. Removing one connection retains the source, its other
connections and its placement. Open in Edge returns to the real source. To add a
connection, select its work bubble, choose Connect source to this work in the
options menu's Connections submenu, then select a source.
New work, notes and documents are available in Add; arrangement and source refresh
are also available in options. Search locates
bubbles by title. Agent tasks, settings and meetings open in a separate window
from the same menu; they do not occupy canvas tabs.

## Agent interaction

The bottom toolbar has a Hold N to speak hint and canvas controls, without an
agent text input, typing shortcut or send button. The voice hint's tooltip names
the selected context; clear the selection to ask about the whole canvas. Hold N
with Workspace's layout enabled and release to send. Submission saves
the user instruction and exact context before queueing an identified durable task.
A failed queue retains the instruction and retry identity. Requests are execution
directions, not canvas work items. Whole-canvas requests retain a nonvisual scope;
arrangement changes edit existing pieces directly. The agent places substantive
results in a meaningful existing context or creates a context for new work.
Questions stay in the selected context when one exists. Startup can recover the
exact saved instruction when its task was not committed. Old generated request
cards and action reports are removed while their useful children are preserved.

Public agent updates appear as temporary phase bubbles at the lower-right desktop
corner. Tool calls grow inside their current phase; the next update pushes earlier
phases upward, collapses them and reduces their opacity. The bounded trail keeps
one opaque bubble, and clarification redirects take precedence. Hover pauses
expiry; full interaction history remains available. These steps stay off the canvas.

The desktop Working label has the existing 300-degree/second linear arc spinner.
It stops when work ends; disabled Windows animations show a static arc. Busy frames
repaint the small status control without repositioning unchanged toolbar capsules.

The agent builds and connects information on the canvas autonomously. App arrivals
are context, not floating notifications. Clarification bubbles live alongside
the work and evidence. Their desktop prompts open the exact canvas location.
The toolbar bell counts pending questions and Hold V + T opens one directly.

The agent uses `work_canvas_read` and revision-bound `work_canvas_update` batches
to create notes/groups, move any known bubble into another, collapse containers
and arrange the shared canvas. Layout and expansion use null scope_id. Empty arrangement positions invoke
the same measured layout as the native controls. Reads page notes and activity;
edits never save that partial read back as a full document. Qt applies a validated
batch to its current document, saves all or nothing, and refreshes existing views
without opening a window. Background activity and automatic positions preserve
the edit token; user pins and structural edits invalidate it.

When a configured model sees new linked external evidence, Workspace queues a
quiet investigation automatically. At most three automatic investigations are
pending, with one active execution per work context. Repeated observations and
agent-written summaries or registered documents do not retrigger it. A waiting
question retains the same execution; later source changes wait for it to finish.
Completed contributions retain their work identity; the watcher keeps the latest
evidence cursor and unresolved/manual bindings. Startup recovers bindings whose
task was not committed, preserving redirected existing tasks.

Outlook document tools inventory rendered attachment controls and message links,
open an exact attachment preview, and collect an attachment with an observed URL
using Edge's authenticated network stream. Collection preserves existing files,
rejects HTML/sign-in responses and limits each file to 32 MiB. The returned path
and digest can then be registered and nested under the email or work.
Controls lacking a durable link remain references in their mail context while
the agent investigates preview/download controls. Version choices use observed
metadata and content; an unresolved meaningful ambiguity becomes a clarification
with candidate evidence kept on the canvas. Browser coverage remains limited
to rendered controls; fixture verification does not establish complete mailbox
or file-service coverage.

Clarifications show content-sized text and a Hold N to reply hint, without reply
editors or send buttons. Speech first targets the selected waiting question on
the visible canvas, through its exact session/request or task/request handler.
The same worker resumes; the canvas retains the answer. A failed task reply
receipt reopens its current question and keeps the previous spoken reply visible.
Rejected replies never become a new task or answer another question. Stale requests reject answers.
Other speech on the visible canvas creates an instruction in the selected context
or on the whole canvas. With the canvas hidden, speech uses the main conversation.
Restarted sessions close orphaned questions; durable task requests retain their
route and work connection across reopening. Approvals retain their existing
preview, identity and explicit-decision guards.

Dictation capture and transcription remain independent of background agent work.
Hold Space to dictate into the focused application, or Hold N to speak to the
agent; release sends. New agent instructions can queue while work continues.

Continue with agent resumes an existing blocked investigation through the durable
task controls. Active investigations and waiting questions keep their current
binding. When no unresolved investigation exists, it persists a work-to-run binding before
submitting research. Questions and useful research results use that binding.
Drafts are actual prepared content; a returned draft never claims an email was
sent. Execution attempts and effect acknowledgments remain in the task journal,
which retains their distinct states and complete ledger. Existing work state transitions and
attached research results provide a short canvas redirect
when the canvas is not active. Routine source and summary refreshes remain quiet.
Initial catalog loading establishes a silent baseline. Explicit agent history
retains the full work timeline without presenting app observations as alerts.

## UI ownership

`assistant/ui_components/` owns reusable native bubble surfaces, palette/ink,
text rendering, headings, controls, press feedback and common widgets. Feature
controllers consume those components directly; no forwarding compatibility
modules remain. The conversation bubbles and the canvas share the same painted
outline and solid fallback. Native desktop glass continues to belong to the
conversation window's compositor; the Qt scene uses the shared solid surface.

Canvas document contracts are in `assistant/work_canvas_model.py`; context
projection, shared identity and navigation are in `work_canvas_context.py`.
Measured nested containers and scoped placement are in `work_canvas_layout.py`.
`canvas_activity.py` owns clarification
routing, reply reconciliation, quiet presentation and material-change policy.
`work_canvas.py`'s `WorkCanvas` is the single owner of the local document: it
saves every edit, observes work, sessions and the catalog, and returns the
documents and announcements that `Ui` renders. The panel never saves its rendered
copy. Each user edit is a `work_canvas_edits.py` intent that the owner applies to
the latest document, so an agent's update committed since the last render survives.
A measured layout is dropped when its view changed since that render; the next
render measures again. `work_canvas_view.py` owns native
spatial interaction, and `work_canvas_detail.py` owns in-place drafts and controls.
`work_canvas_window.py` owns the dedicated frame and optional administration
window. `personal_work_panel.py` composes these with the existing immutable
catalog and saved-work command interface.

The first implementation collects the information observed by the existing
browser adapters. It does not claim complete mailbox or Teams history coverage;
coverage follows signed-in rendered pages and their filters.


## Documents and nested bubbles

Documents are canonical sources with a dedicated green document badge. The +
menu adds a local file or an HTTPS document link; the agent can register either
through `work_items_add_document`. Local text/Markdown/CSV/log files supply a
bounded UTF-8 preview. Other formats retain their title and location and open
through Windows in their associated application. Registration does not edit,
copy or publish the document. Browser access remains external to Workspace.

Every content bubble can contain other bubbles, work contexts and named groups.
Right-click a bubble and choose Put inside another bubble, or select a piece and
use Put selected piece inside from +. Visual containment is saved independently
of factual work connections. Email and Teams conversation references retain
observed individual message sources as their contents; a work can reference
that conversation, a specific message, or both. Missing rendered bodies never
become invented messages. Outlook's adapter accepts individual mail only when
a rendered body has a distinct explicit message identity. Live selector coverage
still depends on Outlook's rendered version; unsupported bodies remain conversation
observations.

A content container starts compact. Show pieces expands that bubble, Hide
collapses it, and Open canvas navigates inside. Inline expansion reveals all
direct pieces at any depth. A focused canvas retains the root bubble and opens
at reading scale; Center fits the entire visible context when an overview is useful.
Work/group frames also have independent
disclosures. View-specific expansion, pins and unsaved native drafts survive
navigation. The location menu lists clickable ancestors, and Back returns through
the actual route, including when the same conversation supports multiple works.

## Opening and refresh cost

The toolbar's voice legend is a microphone beside a styled physical N keycap.
Instructions and the selected context appear in its tooltip; no visible sentence
or agent editor takes space in the toolbar. Holding N and releasing to send use
the existing speech route.

First reveal shows a compact 80-logical-pixel native indicator before construction
and rendering. Its lilac wheel rotates linearly once per 1.2 seconds through
Windows composition. The surface uses desktop glass's top-level composition
host and stays visible until the canvas viewport has painted its first frame;
native show returning does not complete presentation. Windows' reduced motion
preference leaves a static mark; unavailable composition uses the native wait
cursor. Cancellation and failure release the target too. Initial frame delivery
pauses Workspace's job timer so redirects resolve after the view exists;
reentrant reveals reuse the pending open. Reopening reuses the existing view
without this interlude.

Desktop startup prepares the hidden canvas using the current saved catalog and
paints its initial viewport once before exposing the toolbar. This keeps Qt's
first font/control setup outside the first canvas click. Preparation does not
show or focus the window. Headings share the floating bubble's font, elision and
expanded wrapping but paint directly on the graphics scene. Leaf bubbles create
no embedded title/disclosure widgets. Collapsed children are materialized only
when their scope becomes visible; search and agent redirects resolve catalog
identities before opening that scope. Existing bubbles, drafts and group headers
keep their native identity across publication, reopening and resize.

Group headers and disclosure controls paint directly on the scene. Qt caches
stable text and the grid; rich editors receive their final style and width before
loading source text. Unchanged publications skip projection and layout. Shared
source references have visible paths with their factual reasons on hover; collapsed
sources resolve to the visible containing bubble. Internal containment needs no
duplicate connection line. Execution failures preserve content-free error kinds
and stack locations in the worker log instead of discarding the diagnostic cause.

Compact previews reserve a stable bounded viewport, flatten whitespace and shape
only their visible lines when Qt paints them. Full source text remains in the
detail editor. Offscreen previews are culled by Graphics View.

The real saved catalog (14 work contexts, 21 sources) took 3.77 seconds on first
opening and 0.51–0.59 seconds when reopening the previous installation through
the desktop UI. After startup preparation the updated path measured 0.39–0.77 seconds
on first opening and 0.06–0.18 seconds when reopening. These are local diagnostic
measurements, not timing promises; an unprepared fresh Qt process still pays
native setup costs. Native regression checks cover hidden preparation, retained
group identities, deferred children, exact redirects and saved drafts.

## Context and corrections

The canvas retains findings, document and web references, clarifications, drafts
and deliberate external changes. Browser navigation, fetch attempts, searches
and arbitrary shell commands remain in the execution ledger. Retired fetch
bubbles are removed from the saved canvas at startup and excluded from later
projections; their separate execution ledger remains available.
Unconnected references are collected in one collapsed container with working
source redirects. Questions inherit their work's navigation route. Canvas links
are retained by the native text formatter, and redirects reveal the exact bubble
at reading scale after Qt resolves the window geometry.

Work options include Dismiss work and This isn't my work. Dismissal remembers the
reason and source connections, hides the contained context and cancels its bound
research after the correction commits. Automatic reviews cannot recreate that
work from the same evidence. Dismissed work in the toolbar options restores the
same context; shared sources remain available in other work.

Web references retain an original HTTPS URL, factual title, bounded captured
evidence and observation time. They use a globe badge and Open original. An
excerpt is not a complete page archive; a local saved document can be nested
with the URL reference when preserving the full page matters. Original document
and page controls delegate directly to the desktop shell.

Containment projections reuse their source and parent lookups. Grid painting
uses Qt's repeating texture, with dot size regenerated for each zoom scale and
coarser spacing at low zoom. Texture alignment remains in scene coordinates.

A native 1920×1080 grid replay at zoom scales 0.9, 0.45 and 0.15 measured
median painting of 21.8, 15.2 and 9.6 ms before, and 3.9, 3.8 and 3.9 ms with
the texture. A frozen catalog of 15 work contexts, 35 sources and one retained
contribution still took 0.25–0.36 seconds to open in paired isolated processes;
the complete interaction measurements do not establish an overall speedup.
Qt window/editor painting and remaining synchronous work still contribute to
latency. The diagnostic inputs and reports are in Windows Temp under
`workspace-canvas-frozen-input.json` and `workspace-canvas-*-round-*.json`.


## Dragging and relationships

Containers and contributions share one native bubble interaction. Drag a bubble's
heading or free surface to move it; expanded containers move their contents as a
block, including saved hidden pieces. Drop onto another bubble to put it inside;
the target highlights before release and opens to show its new contents. Drop on
empty overview to remove visual containment, preserving factual source links.
Within a focused canvas, empty-space drops remain within the focused context.
Escape cancels a gesture before navigating back or closing.

Every bubble has the same options button and context menu, including over text
and embedded editors. The small ring on the right of its heading can be dragged
to another bubble to create a relationship. Connect to another bubble also lets
the user select an endpoint. Relationships have editable labels and can be removed
through their line or either endpoint's Relationships menu. Collapse projects
these lines onto visible containers while edits retain the original endpoints.
The agent uses revision-bound `link` and `unlink` edits to maintain the same lines.

Visual containment comes from the displayed hierarchy. A shared source's default
navigation path can differ from its current displayed owner; it must not cause
a normal drag to reparent or snap back. Pins anchor their owning frames so
expansion and navigation preserve absolute coordinates. Child positions stay
inside their owner; dragging out explicitly changes containment. Reparenting
releases the moved subtree's old scope pins so they cannot pull it back.

Gesture states, inputs and effects are frozen payload variants handled by `match`.
Qt owns mutable graphics, pointer capture and previews in
`personal_work_panel.py`; `WorkCanvas` persists one edit on release and the panel
performs one reflow. Pointer moves do not write SQLite or rebuild topology. Membership and
ancestry use immutable indexes with a bounded eight-entry `functools.lru_cache`,
keyed by catalog and editable structure, excluding geometry and cameras.
Stdlib grouping provides the index construction; native graph/layout dependencies
would broaden this containment policy without addressing its costs.

A paired Windows Python 3.15 measurement with 160 fictional work contexts and
320 sources measured cold projection at 113 → 17 ms, warm median projection at
106 → 3 ms, and median layout at 135 → 21 ms. Desktop load varies. The harness
and earlier baseline remain in Windows Temp as
`workspace-canvas-topology-profile.py` and `workspace-canvas-topology-before.txt`.
These algorithm measurements do not establish complete window-opening latency.

A frozen real-catalog replay (15 contexts, 35 sources, one contribution) measured
prepared window opening at 235 → 83 ms in one paired isolated run. Context exits
were 55–59 → 26–29 ms and detail expansion 69–76 → 49–68 ms. This single pair is
local evidence, not a latency guarantee; editor shaping and native window startup
still contribute. Content-free reports are
`workspace-canvas-installed-timing.json` and `workspace-canvas-development-timing.json`
in Windows Temp.
