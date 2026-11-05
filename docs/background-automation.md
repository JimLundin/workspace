# Background automation

Workspace prefers an application API, then background browser DOM operations,
then accessibility. The agent sends no synthetic mouse or keyboard input. All
tools use the same agent conversation and Stop control.

## Browser sessions

The agent owns a separate headless Edge instance and dedicated profile at
`%LOCALAPPDATA%\workspace\browser-profile`. It uses the existing `websockets`
dependency and CDP implementation; no browser bundle, Node.js, Playwright,
Selenium or extension is added. The agent tools cannot attach to the user's
personal Edge or Chrome.

The exclusive instance stays running between tasks. The agent inspects its page
list, reuses exact page IDs and closes pages once useful context is saved. Every
completed, suspended or failed execution releases the instance's research pages,
including script-created tabs, and leaves one idle blank page. The same process,
connection and cookies survive cleanup. Saved URLs and documents remain useful;
page IDs must be refreshed on a later run. Stop and shutdown close the owned
process tree, retaining its profile. Cleanup failures are reported explicitly.
Edge's policy-required `edge://force-signin/` page belongs to the browser and is
preserved; closing it would make Edge create it again.

| Tool | Use |
|---|---|
| `browser_open` | Open an HTTP(S) page or `about:blank` in the exclusive agent instance, or navigate an exact `target_id`. |
| `browser_tabs` | Inspect its current page IDs, titles and URLs without launching it. Follow `next_offset`; pages contain up to 40 tabs. |
| `browser_snapshot` | Read text and controls. Follow next offsets for more text, controls or frames. |
| `browser_action` | Click, fill, select an option, or check a native checkbox/radio. |
| `browser_evaluate` | Evaluate JavaScript in an isolated world; await promises and return bounded output. |
| `browser_screenshot` | Capture the agent viewport. |
| `browser_sign_in` | Open the dedicated profile visibly for credentials/MFA, then resume headless work with `browser_open`. |
| `browser_close` | Close an exact page after saving evidence; with no `target_id`, close the exclusive browser and retain its profile. |

A visible sign-in handoff survives ordinary run cleanup so the user can finish
MFA before continuing. Sites control session expiry; Workspace never copies
cookies or tokens between profiles. Managed Edge can force sign-in and sync into
new profiles, so this instance disables sync and extensions to keep its pages
exclusive to the agent. Showing a source to the user uses the desktop open tool.

The independent Teams/activity collectors still borrow the user's approved
signed-in Edge connection. Their browser attachment remains separate from the
agent toolset. Enable remote debugging at `edge://inspect/#remote-debugging` and
approve the browser-owned connection for those collectors. They preserve personal tabs when disconnecting. See
[browser session reuse](browser-session-reuse.md) for that connection's contract.

Use control IDs from the latest snapshot of the selected page and frame. A new
snapshot replaces that frame's IDs. Actions do not imply that the intended
workflow succeeded: read a fresh snapshot to verify the result. Main-page clicks
use CDP mouse events; frame clicks use the frame's DOM so local coordinates never
become desktop or main-page coordinates. Generic actions use the same bounded
wake/restore lifecycle as web-app operations, so inactive pages receive trusted
input without activating the native window. A disposable minimized Edge fixture
verifies the saved effect and unchanged window state. Open shadow roots are included. Sites
with closed shadow roots, inaccessible frames or canvas interfaces may require
custom JavaScript or screenshots.

The exclusive browser is started suspended, assigned to an owned Windows job
and then resumed. Normal closure waits for children; the job also terminates
them if the assistant crashes. The persistent profile retains sign-in data.

Snapshots and evaluated output are limited to 20,000 characters; oversized
snapshots and tab lists retain valid JSON and expose offsets. CDP replies
are capped at 16 MB and screenshots must have a valid, bounded PNG header.
Browser actions are never silently retried. After a timeout or Stop, inspect
state before repeating an action that could already have completed. Detachment
cannot roll back navigation, network requests or JavaScript already started in
a personal page. See [session reuse research](browser-session-reuse.md) for the
vendor references and profile-selection limitations.

## Teams

Teams work runs only in the signed-in browser through `teams_web_read`,
`teams_web_open_chat` and `teams_web_draft_reply`. Workspace has no Microsoft
Graph integration, app registration or stored Teams tokens; the earlier Graph
adapter was retired because the browser covers the same work without tenant
consent.

To record a Teams meeting, ask the assistant to start recording while the meeting
is open in the browser. `meeting_start` defaults to `source=both`, capturing the
Windows default microphone and playback device; `source=microphone` captures
only the room. `meeting_stop` ends capture and finishes transcription.
`meeting_status`, `meeting_list` and `meeting_retry` report progress, find saved
transcripts and retry pending audio. Match Teams' selected playback device to the
Windows default playback device. Capture continues independently of the agent
task until stopped or Workspace exits. Transcripts live under
`%LOCALAPPDATA%\workspace\meetings`; successfully transcribed audio is removed.

The real-device browser playback check captured 19.2 seconds, transcribed the
known spoken phrase through the configured provider, published its Markdown
transcript and verified removal of transcribed audio. A separate 62.6-second
capture stopped and published cleanly. Two device-policy defects found during
these checks are covered: comparing native positions with stream packet lengths
falsely reported microphone resets, and old timestamps on all-zero playback
packets falsely reported missing audio. True backwards clocks and late nonzero
audio still stop capture. This validates browser playback, capture and transcription;
it does not establish that a live Teams call connected. The web test-call button
received a verified trusted click but opened no call UI; the user's self-chat
offered no call control.

## Outlook and AIP Kanban agent tools

Outlook tools reuse the signed-in browser at `outlook.office.com`,
`outlook.office365.com` or `outlook.cloud.microsoft`. Obtain the exact page ID from
`browser_tabs`, opening the application with `browser_open` when needed. No Microsoft app IDs
or consent are required. These adapters use the English web
interface observed in the live apps; unexpected controls fail explicitly.

| Tool | Use |
|---|---|
| `outlook_web_read` | List rendered conversation IDs/previews and read the selected pane, including search scope, loading/truncation and draft presence. |
| `outlook_web_search` | Submit an Outlook search expression through its search box and return fresh rendered results. The existing search scope may be All folders. |
| `outlook_web_open_mail` | Select an exact conversation ID and wait for its confirmed reading pane and body. Opening can mark it read under Outlook's settings. |
| `outlook_web_draft_reply` | Prepare an unsent reply to the selected conversation, retaining Outlook's recipients and signature. The editor remains open for review. |

Conversation IDs can group multiple messages; they are not individual mail
IDs. Pagination covers rendered rows only. Scroll the list with generic browser
tools to load more, then read it again. Search scope is reported instead of silently
changed. Existing open drafts block search, selection and reply preparation.
The tools never click Send. Inspect the open editor and Outlook's autosave status
before closing a draft, and inspect an uncertain result before retrying.

`teams_web_read` returns rendered chat identities,
selected messages, authors and reactions in an explicit signed-in Teams page.
`teams_web_open_chat` selects a rendered chat by identity, independently of its
title. `teams_web_draft_reply` inserts an unsent reply only into the exact selected
chat's empty editor. Existing drafts are preserved. These tools use background
browser DOM work and do not activate the native tab. Recent/sidebar and rendered
message history are bounded; they are not a tenant-wide search or archive.

The Kanban adapter targets the observed AIP Kanban app at
`https://dev-team-kanban.fcg.palantirfoundry.com`. Obtain its exact page ID from
`browser_tabs`, opening the application with `browser_open` when needed. Multiple open board
tabs require an explicit selection. Workspace reuses the signed-in page without
copying credentials or calling undocumented Foundry APIs.

| Tool | Use |
|---|---|
| `kanban_board` | Return stable task IDs, titles, current columns and filters. Query and pagination apply to currently rendered cards without changing filters. |
| `kanban_read_task` | Open an exact task, read fields/description and bounded comments, dependencies and activity, then close its details. |
| `kanban_update_task` | Change one title, description, due date, estimate, labels or acceptance-criteria field. Requires its exact expected value and verifies saved readback. |
| `kanban_move_task` | Move an exact card from its expected column through the app's drag/drop handler, retaining the app's WIP/testing rules. |
| `kanban_comment` | Post a comment through the task editor and confirm visible readback. |

Existing task dialogs and comment drafts block conflicting operations. Missing
or ambiguous cards, changed fields/columns and unexpected origins are rejected.
The board's existing filters still limit discovery; absence from a filtered board
does not establish that a task does not exist. A failed save/move/post must be
inspected before retrying. Task readback and comments are bounded; generic browser
snapshots remain available for longer detail views. These adapters currently do
not create or delete tasks, attach files, or change assignees/reviewers.

New tool arguments/results remain in the agent's in-memory conversation; persistent
journals retain only redacted integration status and hashed target identities.
The same durable effect coordinator applies to these tools. HTTP, OAuth, Pydantic validation and DOM/event implementations are trusted
dependency/platform behavior; tests cover Workspace routing, selection, stale
state, draft preservation, output limits, cancellation and effect ownership.

## Validation and limits

Tests exercise real installed Edge against a local fixture: form controls, open
shadow roots, embedded frames, Trusted Types, screenshots, pagination, profile
persistence, visible sign-in handoff, stale IDs and cancellation. Attachment
tests reuse a disposable browser's saved session, keep its blank and existing
tabs intact, capture an attached page, and verify that cancellation only detaches.
A local pending WebSocket handshake verifies cancellation during the consent
wait. These tests do not connect to a personal browser or approve its dialog. Native tests
cover DPAPI and job cleanup. Local Teams, Outlook and Kanban fixtures verify each
web-app script's output against its result type; they use no real Microsoft
credentials or Teams messages.

Live Teams chat discovery was checked in an owned hidden page using the existing
sign-in: 24 rendered chats, no sign-in prompt, no added native tab and unchanged
tab selection. This does not verify every Teams operation or live Outlook/Kanban
writes. Native desktop apps
continue to use their APIs, accessibility or foreground input; they do not gain
a generic headless mode.
