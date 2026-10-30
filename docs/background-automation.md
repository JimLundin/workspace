# Background automation

Workspace prefers an application API, then background browser DOM operations,
then accessibility, and finally foreground mouse and keyboard input. All tools
use the same agent conversation and Stop control. The existing approval setting
applies; its default is `never`.

## Browser sessions

The Windows app defaults to the user's running, signed-in Edge, with Chrome
available through `browser_attach` or `browser_open`'s `browser` argument.
The tools use the existing `websockets` dependency and CDP implementation;
no browser bundle, Node.js, Playwright, Selenium or extension is added.

Open `edge://inspect/#remote-debugging` (Chrome: `chrome://inspect/#remote-debugging`)
in the intended browser and enable **Allow remote debugging for this browser
instance**. Keep it running and approve its connection dialog when Workspace
connects. The browser owns that consent and can request it again for a new
connection. Workspace reuses an established connection across operations and tasks.
Status checks never connect or trigger consent. A denied or blocked connection
does not launch a separate profile or change browser policy.

New Edge pages open in background tabs in a **Workspace** group in the existing
browser context. The first group is blue and collapsed. Later opens reuse it,
preserving its color and expanded state, including after Workspace reconnects.
The group's tabs remain accessible in the tab strip. Set `group_id=-1` for an
ordinary ungrouped tab, or provide another group ID or normal window ID.
Use an explicit existing `target_id` for a page whose tab-local state is needed.
Initial browser consent may bring its window forward; subsequent DOM actions
and viewport captures do not select a tab or move the desktop pointer.

| Tool | Use |
|---|---|
| `browser_attach` | Connect to the running signed-in `edge` or `chrome`; return current tabs. |
| `browser_open` | Open a background HTTP(S) page or `about:blank`, normally in Workspace's group, or navigate an explicit `target_id`. Optional `browser`: `edge`, `chrome`, or `separate`. |
| `browser_tabs` | Report connection/setup status. Default `view=pages` lists CDP page IDs. Edge's `view=strip` lists native tab IDs, windows, group membership, active/pinned/muted state and the listed tabs' groups. Follow `next_offset` for more tabs. |
| `browser_group` | Create a group from `tab_ids`, add tabs to `group_id`, edit its title/color/collapsed state, or move it using `index` and optional `window_id`. Unspecified existing properties stay unchanged. |
| `browser_ungroup` | Remove native `tab_ids` from their groups, keeping the tabs open. |
| `browser_tab` | Pin, unpin, reload or move a native `tab_id`. `activate` explicitly selects the tab and brings its window forward. |
| `browser_snapshot` | Read visible text and controls. Follow the returned next offsets for more text, controls or frames. |
| `browser_action` | Click, fill, select an option by value, or check a native checkbox/radio. |
| `browser_evaluate` | Evaluate a JavaScript expression in an isolated world; await promises and return bounded output. |
| `browser_screenshot` | Capture the browser viewport. Its coordinates are independent of desktop screenshots. |
| `browser_sign_in` | Open the dedicated profile visibly so the user can complete sign-in or MFA. |
| `browser_close` | Close a page's `target_id`, native `tab_ids`, or every tab in a `group_id`. With no selector, detach from a personal browser or close Workspace's separate browser. |

Native tab IDs and CDP page IDs are different identifiers. Use the pages view
for DOM tools and the strip view for tab/group management. Newly created group
tabs return both IDs. The integration identifies them by a unique temporary
blank-page URL before navigating; it never guesses an existing tab's identity
from its title or URL. Explicit native operations work on existing personal
tabs as well as agent tabs. Strip results can filter `window_id` or `group_id`
(`-1` means ungrouped); group metadata accompanies each page of matching tabs.
Tab batches contain up to 200 IDs and list pages up to 40 tabs.

Edge tab/group management uses the browser's built-in `tabs`, `tabGroups` and
`windows` APIs from a hidden `edge://favorites/` control page on the existing
approved CDP connection. That page is outside the tab strip and belongs to the
connection; disconnecting destroys it without closing ordinary tabs. No
extension is installed and no browser flags or policy settings are changed.
This WebUI API exposure was tested against Edge **155.0.4283.62**. A runtime probe
checks availability; unsupported versions return an error, with `group_id=-1`
available for ordinary background opening. Chrome retains its existing page
tools but does not expose this Edge control surface.

Muting remains read-only in the tab metadata. Calling `tabs.update({muted:...})`
from a WebUI page crashes this Edge version: the Chromium implementation
dereferences `extension()->id()` although WebUI has no extension. The adapter
rejects mute/unmute before touching the browser. See
[the tabs implementation](https://github.com/chromium/chromium/blob/main/chrome/browser/extensions/api/tabs/tabs_api.cc).

Use control IDs from the latest snapshot of the selected page and frame. A new
snapshot replaces that frame's IDs. Actions do not imply that the intended
workflow succeeded: read a fresh snapshot to verify the result. Main-page clicks
use CDP mouse events; frame clicks use the frame's DOM so local coordinates never
become desktop or main-page coordinates. Open shadow roots are included. Sites
with closed shadow roots, inaccessible frames or canvas interfaces may require
custom JavaScript, screenshots or foreground automation.

Selecting `browser=separate` retains the optional isolated Edge workflow and its
profile at `%LOCALAPPDATA%\workspace\browser-profile`. `browser_sign_in` explicitly
selects that profile and opens it visibly. After sign-in, `browser_open` restarts
it headlessly and returns new page IDs. It has its own sign-ins; it does not
inherit the normal browser's session. Workspace never copies cookies or tokens
between profiles. MFA and company access policy may require further interaction.

CDP connects only to `127.0.0.1`, bypassing proxies. Attachment reads only the
bounded `DevToolsActivePort` discovery file; it never creates, rewrites or deletes
that file. The connection waits up to 60 seconds for browser consent. Stop closes
the pending socket promptly, although the browser controls its own dialog.
No `/json/version` probe is used, because the consent mode does not expose it.

Attached browsers and all their ordinary tabs survive Stop, disconnect and
Workspace exit. Only an explicitly selected target is navigated or closed; an
arbitrary personal blank tab is never reused. There is no artificial limit of
20 agent tabs. Attached page lists mark the current connection's new pages with
`created_in_session`. Closing by page ID uses the target lifecycle API directly,
so closing a tab does not depend on permission to attach to its page scripts.
It waits briefly for removal and returns `state=closed`, or `state=requested`
if the page remains open. Inspection can then handle any outstanding browser
dialog without sending the close again.

In separate mode, Workspace starts Edge suspended, assigns it to an owned job and
then resumes it. Stop and exit close that owned process tree. Normal closure
waits for child processes; the job also terminates them if Workspace crashes.
The separate profile's sign-in state persists.

Snapshots and evaluated output are limited to 20,000 characters; oversized
snapshots and tab lists retain valid JSON and expose offsets. CDP replies
are capped at 16 MB and screenshots must have a valid, bounded PNG header.
Browser actions are never silently retried. After a timeout or Stop, inspect
state before repeating an action that could already have completed. Detachment
cannot roll back navigation, network requests or JavaScript already started in
a personal page. See [session reuse research](browser-session-reuse.md) for the
vendor references and profile-selection limitations.

## Microsoft Graph setup

The adapter is installed without app IDs or a Microsoft sign-in. Configuration
and status checks make no network requests. It needs an approved **Microsoft
Entra public client application** whose tenant permits device-code sign-in and
the required delegated permissions. No client secret is used.

When the IDs are available, ask Workspace to configure Teams using the application
(client) ID and directory (tenant) ID. `teams_configure` saves them in
`%LOCALAPPDATA%\workspace\teams\config.json`. Alternatively, set
`WORKSPACE_GRAPH_CLIENT_ID` and `WORKSPACE_GRAPH_TENANT_ID` in the environment. Those
settings take precedence; conflicting saved configuration is rejected explicitly.

`teams_sign_in` returns a Microsoft verification URL and a short user code. Open
that URL, enter the code and complete sign-in and consent. Workspace can display it
in the regular browser with `open`. After completing it, use `teams_finish_sign_in` to save
the result. Stop cancels pending polling. Tenant policy may require administrator
consent or disallow this flow; the adapter reports Microsoft's refusal.

The delegated scopes are:

| Permission | Purpose |
|---|---|
| `User.Read` | Identify the signed-in user when creating a chat. |
| `User.ReadBasic.All` | Resolve recipients by name or email. |
| `Chat.Read` | List chats and read bounded message history for the requested work and result verification. |
| `Chat.Create` | Get or create a one-to-one chat. |
| `ChatMessage.Send` | Send the user's requested Teams message. |
| `offline_access` | Refresh the saved sign-in. |

This does not request application-wide message access or migration permissions.
Existing sign-ins granted only `Chat.ReadBasic` may require renewed Microsoft
consent before message readback is available. Outlook web uses the browser sign-in separately and requests no Graph scopes.

| Tool | Use |
|---|---|
| `teams_status` | Report configuration, saved sign-in and pending sign-in. |
| `teams_configure` | Save approved client and tenant IDs without authenticating. |
| `teams_sign_in` / `teams_finish_sign_in` | Start and finish delegated sign-in. |
| `teams_find_users` | Resolve a name, email or user principal name. |
| `teams_list_chats` | List recent chats with basic members and bounded pagination. |
| `teams_read_messages` | Read bounded history or one exact message in an identified chat to inspect the requested result. |
| `teams_open_chat` | Get or create a one-to-one chat for a resolved user ID. |
| `teams_send_message` | Send plain text to an identified chat when requested by the user. |
| `teams_sign_out` | Remove Workspace's stored API credentials; browser sign-in is separate. |

Access and refresh tokens are encrypted with Windows DPAPI for the current
account in `tokens.bin`. They never appear in tool results. Changing app IDs
clears old credentials and page cursors. User and chat pages use opaque in-memory
cursors; Graph pagination can only continue on the expected Microsoft host and
route. Large membership lists are marked as truncated. Sending is a single POST
with no automatic retry, including on a timeout or uncertain response.

## Outlook and AIP Kanban agent tools

Outlook tools reuse the signed-in browser at `outlook.office.com`,
`outlook.office365.com` or `outlook.cloud.microsoft`. Obtain the exact page ID from
`browser_tabs`, connecting with `browser_attach` when needed. No Microsoft app IDs
or additional Graph consent are required. These adapters use the English web
interface observed in the live apps; unexpected controls fail explicitly.

| Tool | Use |
|---|---|
| `outlook_web_read` | List rendered conversation IDs/previews and read the selected pane, including search scope, loading/truncation and draft presence. |
| `outlook_web_search` | Submit an Outlook search expression through its search box and return fresh rendered results. The existing search scope may be All folders. |
| `outlook_web_open_mail` | Select an exact conversation ID and wait for its confirmed reading pane and body. Opening can mark it read under Outlook's settings. |
| `outlook_web_draft_reply` | Prepare an unsent reply to the selected conversation, retaining Outlook's recipients and signature. The editor remains open for review. |

Conversation IDs can group multiple messages; they are not individual Graph mail
IDs. Pagination covers rendered rows only. Scroll the list with generic browser
tools to load more, then read it again. Search scope is reported instead of silently
changed. Existing open drafts block search, selection and reply preparation.
The tools never click Send. Inspect the open editor and Outlook's autosave status
before closing a draft, and inspect an uncertain result before retrying. The
existing local classic-Outlook/file draft workflow remains available for prepared
meeting packages.

For Teams without Graph setup, `teams_web_read` returns rendered chat identities,
selected messages, authors and reactions in an explicit signed-in Teams page.
`teams_web_open_chat` selects a rendered chat by identity, independently of its
title. `teams_web_draft_reply` inserts an unsent reply only into the exact selected
chat's empty editor. Existing drafts are preserved. These tools use background
browser DOM work and do not activate the native tab. Recent/sidebar and rendered
message history are bounded; they are not a tenant-wide search or archive.

The Kanban adapter targets the observed AIP Kanban app at
`https://dev-team-kanban.fcg.palantirfoundry.com`. Obtain its exact page ID from
`browser_tabs`, connecting with `browser_attach` when needed. Multiple open board
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
The same optional approval setting and durable effect coordinator apply to these
tools. HTTP, OAuth, Pydantic validation and DOM/event implementations are trusted
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
cover DPAPI and job cleanup. Controlled HTTP tests cover sign-in, consent denial,
refresh, page validation, output limits, cancellation, journal redaction and
single-attempt sends. They use no real Microsoft credentials or Teams messages.

Authenticated company-site automation and live Teams sending remain untested
until the approved app and user sign-in are configured. Native desktop apps
continue to use their APIs, accessibility or foreground input; they do not gain
a generic headless mode.

Microsoft references:

- [Device authorization grant](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code)
- [List users](https://learn.microsoft.com/en-us/graph/api/user-list?view=graph-rest-1.0)
- [List chats](https://learn.microsoft.com/en-us/graph/api/chat-list?view=graph-rest-1.0)
- [Create a chat](https://learn.microsoft.com/en-us/graph/api/chat-post?view=graph-rest-1.0)
- [Send a chat message](https://learn.microsoft.com/en-us/graph/api/chat-post-messages?view=graph-rest-1.0)
