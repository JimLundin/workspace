# Unified work conversation: Teams feasibility

Investigated on 2026-10-26 against Microsoft's API documentation, its source
Markdown, and unauthenticated first-party web response headers. This is a
feasibility report, not a production communication feed or a live send test.

The Graph adapter this report evaluated was retired on 2026-10-30. Workspace
reads and drafts Teams messages only in the signed-in browser; the Graph findings
remain as research.

## Product boundary

Workspace's proposed surface is one work conversation: incoming colleague
messages, the user's replies, agent requests/results, and actionable updates
share a representation. Each entry retains its provider, conversation identity,
sender, source revision, and reply destination. Related messages can group
together; reactions update their original message quietly. Agent assistance is
invoked for an identified exchange and its result stays attached there.

This follows the user's accepted direction. It does not introduce side-by-side
chat windows. Keep Workspace's native Python/Qt runtime and its isolated keyboard
process, as required by [AGENTS.md](../AGENTS.md).

## Decision

There are two materially different access routes:

1. **Microsoft Graph:** documented structured access can support a dependable
   feed and direct replies, but needs a separately registered/approved application
   and delegated sign-in. A user's existing Teams login does not itself provide
   a Graph token for Workspace. [1, 2]
2. **The user's signed-in Teams web tab:** normal Teams for Web access can use
   the user's account in a supported desktop browser. Workspace already has a
   consented browser connector that can inspect and interact with such a tab.
   This does not require registering a Workspace Graph application, but browser
   attachment and tenant policy still apply. It provides page interaction,
   not Microsoft's structured chat API. [3, 4; local connector: 5]

Start by checking the route actually available to the user. Where Graph setup
must wait, a read-only inspection of an explicitly chosen Teams web tab can
answer whether messages, sender labels, conversation identities, and update
state are exposed sufficiently for a limited feed. A normal browser login is
enough to use Teams for Web when the account/policy permits it; it is not enough
to assume that Workspace can reliably synchronize every chat in the background.

## Documented Graph capabilities

| Requirement | Supported capability | Permission / limitation |
| --- | --- | --- |
| Discover chats | `GET /chats` or `/me/chats`; expand `members` and `lastMessagePreview`; order by `lastMessagePreview/createdDateTime desc`; follow `@odata.nextLink`. | Delegated `Chat.ReadBasic` is sufficient for listing; `Chat.Read` also permits it. `$top` is at most 50. Expanded membership has documented limits, so a partial list must be identified. [6] |
| Identify unread chats | List-chats responses can contain `viewpoint.lastMessageReadDateTime`. Compare it with `lastMessagePreview.createdDateTime`. | `chatViewpoint` is currently supported by List chats, not by every chat GET. This is chat message read state, not a general Teams Activity-feed acknowledgment. [6, 7] |
| Read recent messages | `GET /chats/{chat-id}/messages`; up to 50 per page, descending creation/modification order. | Delegated `Chat.Read`; `Chat.ReadWrite` is a higher permission. Follow continuation links rather than assuming a first page is complete. [8] |
| Incremental reads within a chat | Filter `lastModifiedDateTime gt ...` with `$orderby=lastModifiedDateTime desc`. | `$filter` and `$orderby` must use the same property, or the filter is ignored. Creation-date filtering supports `lt`, not `gt`. This is paginated date filtering, not delegated delta tokens. [8] |
| Render sender and revisions | `from`, body/content type, attachments, mentions, importance, `etag`, `lastEditedDateTime`, `deletedDateTime`, and `reactions` are message properties. | Message IDs can repeat in different chats: key by chat and message ID. Bodies may be HTML. Reactions change `lastModifiedDateTime`, including when removed. [9] |
| Mark a chat read | `POST /chats/{chat-id}/markChatReadForUser`, with a `user` identity, returns `204`. | Available in **v1.0**, requires delegated **`Chat.ReadWrite`**. The request does not accept a chosen observed-message timestamp. Do not silently equate local dismissal with this whole-chat state change. [10] |
| Send a normal reply | `POST /chats/{chat-id}/messages` returns `201` and the created message. | Delegated `ChatMessage.Send`; `Chat.ReadWrite` is a higher permission. The chat must already exist; creation is a separate operation. [11] |
| All-chat delta/export reads | `/users/{id}/chats/getAllMessages[/delta]`. | **Application permissions only** (`Chat.Read.All` or higher); delegated sign-in is not supported. Do not select these as the existing personal public client's sync mechanism. [12, 13] |

For a limited delegated feed, enumerate chats, poll each selected chat using
modification timestamps and overlap, follow validated continuation links, and
deduplicate by `(chat_id, message_id, revision)`. Keep independent watermarks
per chat; advance after the page set has completed. A newly edited or reacted-to
old message should update its original entry, not create a new interruption.
These are implementation recommendations derived from [8, 9], not a guarantee
of a complete offline change log. Deleted-message visibility, retention, gaps,
and tenant-specific behavior need live validation.

Recent-message previews help prioritize discovery but their creation-time sort
is insufficient alone to detect a reaction on an older message. A bounded
background sweep and reconnect catch-up remain necessary when polling. [6, 9]

Microsoft's current Teams limits include 1 request/second per delegated user for
list chats, 1 request/second per chat for listing messages, and 1 request/second
per user/chat for sends; other app/tenant limits also apply. Sustained traffic
must stay below limits. A `429` response includes `Retry-After`; honor it and
back off. [14, 15] These are ceilings, not suggested polling frequencies.

## Push delivery

The v1.0 subscription-create permission table supports delegated `Chat.Read`
or `Chat.ReadWrite` for `/chats/{id}/messages` and for
`/users/{id}/chats/getAllMessages`. The latter subscription support must not be
confused with the application-only **GET** export/delta endpoints. The Teams
how-to's user-level example still uses a beta subscription URL; use the v1.0
API permission table as the evidence and validate a real subscription before
depending on it. [16, 17]

Ordinary webhook delivery needs a publicly reachable HTTPS endpoint; localhost
alone is insufficient. Endpoint validation must return the decoded challenge
within ten seconds. Delivery endpoints must queue/respond quickly; Graph may
retry for up to four hours or drop notifications from persistently slow
endpoints. Subscriptions need renewal and catch-up after missed events. Teams
subscriptions longer than one hour require a lifecycle-notification URL; the
documented maximum chat-message subscription lifetime is three days. Rich
notifications require additional encryption handling. [17, 18, 19]

Current v1.0 documentation also adds `getVapidPublicKey` and Web Push subscription
fields for known browser push-service endpoints. This is a possible future
route without a hosted conventional webhook. Its suitability for Workspace's
native Qt runtime, browser push registration, tenant availability, lifecycle
handling and Teams delivery has **not** been demonstrated here. Do not require
a hosted server as the sole possible design, or assume browser push already
works. Initial polling is the smallest route to validate. [20, 21]

## Replies and read acknowledgments

A reply must capture an exact chat identity and intended text before sending,
and show the destination in the composer. Bind the returned message identity
to that attempt. Workspace's existing adapter already sends once; retain that
behavior. If a network timeout leaves the outcome uncertain, inspect messages
and report uncertainty rather than automatically posting again. A returned
message ID enables exact readback under `Chat.Read`; it does not supply an
idempotency key for a lost POST response. [8, 11; implementation: 22]

Local inbox acknowledgment, Windows toast dismissal, chat read state, and
Teams Activity-feed state are separate concepts. `markChatReadForUser` gives
a supported route for the chat read marker, but its documentation does not
establish that it clears reaction/activity badges, calendar notifications, or
every cause of client flashing. Test those outcomes individually. [7, 10, 23]

## Meeting invitations

Calendar access is separate from chat access. Event lists provide single events
and recurring series masters; use calendar view for expanded occurrences.
Basic event listing accepts delegated `Calendars.ReadBasic`, while more content
requires the appropriate calendar scope. Accepting an invitation uses
`POST /me/events/{id}/accept`, requires `Calendars.ReadWrite`, and defaults to
sending a response to the organizer. The action returns `202 Accepted`, so
readback is required before claiming an updated calendar state. [24, 25]

Meeting chat membership or notification text alone is not sufficient to infer
the exact calendar event, invitation state, cancellation, recurrence instance,
or permission to respond. Keep actionable calendar integration as a distinct
provider behind the same representation.

Microsoft's Teams settings expose calendar notification choices for invitations,
updates, cancellations and forwarded meetings, along with chat/channel
notification choices. These settings may solve some current noise before a
full calendar provider exists; inspect the installed client's options and
preserve upcoming-meeting reminders the user wants. [23]

## Notification dismissal and flashing

`UserNotificationListener` exposes Notification Center notices and individual
removal. It does not provide a general interface to every app's private badge,
popup, or original reply buttons. Workspace's existing notification observer
already implements local removal; it needs a conversation identity from a
structured provider to offer reliable inline Teams replies. [26; implementation:
27]

Windows documents `FlashWindowEx` with `FLASHW_STOP` as stopping current caption
or taskbar flashing and restoring the window's original state. This can be
tested against an identified Teams window without focusing it. It is not a
persistent application-wide prohibition: Teams may request another flash, and
the call does not set chat read state or acknowledge Teams Activity entries.
The return value is the previous active-caption state, not proof that a Teams
notification was cleared. Determine whether the user's symptom is native
flashing before implementing a suppression loop. [28, 29]

No documented general Graph API for enumerating/clearing the user's complete
Teams Activity feed was established by this investigation. Documented chat-read
and calendar actions must not be presented as such an API.

## Login-based Teams web route

Microsoft supports Teams for Web on desktop Edge, Chrome, Firefox and Safari;
Edge/Chrome support is for their latest three versions. A supported browser and
normal company sign-in are the prerequisites for this first-party interface.
Some line-of-business apps also need third-party cookies. Microsoft describes
near feature parity with the desktop client; the web page can still carry its
own navigation/loading cost. [3, 30]

Workspace can borrow its existing, explicitly connected Edge tab: inspect recent
visible text and controls, navigate a selected chat, and eventually submit a
user-requested reply through that page. Use the browser's own sign-in/MFA flow
and retain the existing connector's connection-consent behavior. Browser login
credentials are not transferred into the Graph adapter. Microsoft's mandatory
`RemoteDebuggingAllowed` policy can disable remote debugging, so account login
alone does not establish that this connector can attach. [1, 4, 5]

Page interaction has a narrower reliability contract than Graph. The official
Teams for Web documentation does not promise a stable automation DOM or a
background feed exposing all chats. Virtualized lists, unopened conversations,
client navigation, reconnects and unread updates require an explicit read-only
probe and then scenario tests. Preserve source identities; notification titles
or human names alone are not sufficient reply-routing keys. These are
feasibility limits, not observations about this user's authenticated page.

An iframe inside another app is not established as a supported route. On
2026-10-26, unauthenticated requests to `https://teams.microsoft.com` and
`https://teams.cloud.microsoft` redirected to their `/v2/unsupported-browser`
page, whose response included `Content-Security-Policy: frame-ancestors 'none'`.
That demonstrates refusal to frame those responses, **not** the authenticated
client's full CSP or all browser/WebView behavior. Use a normal supported tab
with the existing connector; do not assume embedding or remove CSP protections.

## Current source gaps and first milestone

The Teams adapter at the time requested `User.Read`,
`User.ReadBasic.All`, `Chat.Read`, `Chat.Create`, `ChatMessage.Send` and
`offline_access`. It has configured-app/device-flow support and encrypted
credentials. It discards chat preview/read markers and message sender,
modification/deletion/reaction fields, reads at most twenty messages without
followable message-history cursors, and has no background sync or read-marker
action. [22] Existing normal Teams authentication does not fill these gaps.

The first complete milestone is:

1. Establish the available access route with read-only checks. For Graph,
   authenticate Workspace's own client and confirm granted scopes without printing
   tokens; for browser access, attach only through the existing consented route
   and identify the intended Teams tab.
2. Read recent updates from a small, explicit set of existing chats into typed
   observations. Retain exact sender, conversation, message and revision data;
   show limited coverage and stale/disconnected states honestly.
3. Project those observations alongside agent turns in one native conversation
   view. Group related activity, fold reactions into their original entries,
   and attach agent help/results to the selected source exchange.
4. Add exact-destination user replies after read-only synchronization works.
   Preserve drafts, single-attempt sends, uncertain outcomes and readback.
5. Validate local dismiss, Graph chat acknowledgment if granted, native flash
   suppression, and Teams Activity behavior as separate scenarios. Add calendar
   actions only once their independent access and identity mapping are proven.

Acceptance evidence should include reconnect without duplicate entries, catch-up
without missing known updates, a changed reaction updating one existing item,
draft persistence during new arrivals, exact reply routing, and an uncertain send
that cannot be repeated silently. Live sends require the user's intended message;
the current research sends none.

## Local follow-up

After the research, the user confirmed Teams web was signed in and approved
Workspace's browser connection. A read-only probe successfully attached to one
`teams.cloud.microsoft` tab and observed rendered messages, conversation-shaped
DOM identities and a reply editor. This establishes that the login-based page
inspection route works on the current laptop. It does not establish all-chat
synchronization, exact send routing, read-state changes or suppression of the
reported flashing. No messages were sent or private message bodies saved.

The [first milestone and local evidence](unified-work-conversation-first-milestone.md)
capture those observations, the interaction prototype and the native
implementation scope. The available route is now the consented browser session;
Workspace Graph app access still needs arranging.

## Sources

1. [Microsoft Graph: Get access on behalf of a user](https://learn.microsoft.com/en-us/graph/auth-v2-user).
2. [Microsoft identity platform: Device authorization grant](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code).
3. [Microsoft: Teams for Web](https://learn.microsoft.com/en-us/microsoftteams/teams-client-web).
4. [Microsoft Edge: RemoteDebuggingAllowed policy](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-browser-policies/remotedebuggingallowed).
5. [Workspace: Existing browser session reuse](browser-session-reuse.md) and [background connector/setup](background-automation.md).
6. [Microsoft Graph v1.0: List chats](https://learn.microsoft.com/en-us/graph/api/chat-list?view=graph-rest-1.0).
7. [Microsoft Graph v1.0: chatViewpoint](https://learn.microsoft.com/en-us/graph/api/resources/chatviewpoint?view=graph-rest-1.0).
8. [Microsoft Graph v1.0: List chat messages](https://learn.microsoft.com/en-us/graph/api/chat-list-messages?view=graph-rest-1.0).
9. [Microsoft Graph v1.0: chatMessage resource](https://learn.microsoft.com/en-us/graph/api/resources/chatmessage?view=graph-rest-1.0).
10. [Microsoft Graph v1.0: markChatReadForUser](https://learn.microsoft.com/en-us/graph/api/chat-markchatreadforuser?view=graph-rest-1.0).
11. [Microsoft Graph v1.0: Send message in chat](https://learn.microsoft.com/en-us/graph/api/chat-post-messages?view=graph-rest-1.0).
12. [Microsoft Graph v1.0: All-chat message delta](https://learn.microsoft.com/en-us/graph/api/chatmessage-delta?view=graph-rest-1.0).
13. [Microsoft Graph v1.0: Get all messages across user chats](https://learn.microsoft.com/en-us/graph/api/chats-getallmessages?view=graph-rest-1.0).
14. [Microsoft Graph: Teams throttling limits](https://learn.microsoft.com/en-us/graph/throttling-limits#microsoft-teams-service-limits), verified against the [first-party Teams include](https://github.com/microsoftgraph/microsoft-graph-docs-contrib/blob/main/includes/throttling-teams.md).
15. [Microsoft Graph: Throttling guidance](https://learn.microsoft.com/en-us/graph/throttling).
16. [Microsoft Graph v1.0: Create subscription permission table](https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions?view=graph-rest-1.0).
17. [Microsoft Graph: Teams message change notifications](https://learn.microsoft.com/en-us/graph/teams-changenotifications-chatmessage).
18. [Microsoft Graph: Receive notifications through webhooks](https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks).
19. [Microsoft Graph v1.0: Subscription lifetime](https://learn.microsoft.com/en-us/graph/api/resources/subscription?view=graph-rest-1.0#subscription-lifetime), verified against its [first-party include](https://github.com/microsoftgraph/microsoft-graph-docs-contrib/blob/main/concepts/includes/change-notifications-subscription-lifetime.md).
20. [Microsoft Graph v1.0: getVapidPublicKey](https://learn.microsoft.com/en-us/graph/api/subscription-getvapidpublickey?view=graph-rest-1.0).
21. [Microsoft Graph v1.0: Subscription properties, including Web Push fields](https://learn.microsoft.com/en-us/graph/api/resources/subscription?view=graph-rest-1.0#properties).
22. Workspace: the Teams Graph adapter, since retired.
23. [Microsoft Support: Manage Teams notifications](https://support.microsoft.com/en-us/office/manage-notifications-in-microsoft-teams-1cc31834-5fe5-412b-8edb-43fecc78413d).
24. [Microsoft Graph v1.0: List calendar events](https://learn.microsoft.com/en-us/graph/api/user-list-events?view=graph-rest-1.0).
25. [Microsoft Graph v1.0: Accept an event](https://learn.microsoft.com/en-us/graph/api/event-accept?view=graph-rest-1.0).
26. [Microsoft: Notification listener](https://learn.microsoft.com/en-us/windows/apps/design/shell/tiles-and-notifications/notification-listener).
27. [Workspace: Notification implementation and established platform limits](windows-shell-integration.md).
28. [Microsoft: FlashWindowEx](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-flashwindowex).
29. [Microsoft: FLASHWINFO flags](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-flashwinfo).
30. [Microsoft: Teams hardware and web browser requirements](https://learn.microsoft.com/en-us/microsoftteams/hardware-requirements-for-the-teams-app).

API permissions and details were checked in the first-party
[Microsoft Graph documentation repository](https://github.com/microsoftgraph/microsoft-graph-docs-contrib)
including the generated permission-table includes, not inferred from SDK tool
names. Graph consent, background coverage, direct-send behavior and notification
state changes still need live validation beyond the local read-only page probe.
