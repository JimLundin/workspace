# Workspace

A personal work environment for a Windows laptop: extract and run with installed
Python 3.15 and no admin installation. It changes itself: ask its agent for a new feature or a fix,
and it edits, tests, installs and reloads the change without asking again.
It undoes the update by itself if it fails. Four main processes:

- **the layout** (`miryoku/`): Colemak Mod-DH in the Miryoku style on the
  laptop's own ISO keyboard: home row mods, layers, caps word, snippets;
- **the assistant** (`assistant/`): dictation, app switching, window
  placement, and an agent, all through your company's OpenAI-style endpoint, with a floating control bar and tray controls;
- **the automation worker** (`automation/`): runs durable tasks and recovery
  independently of the conversation window;
- **the keeper** (`keeper.py`): runs the other three, restarts them if they crash,
  and installs the agent's changes to them (see *Changing Workspace*).

The browser/native [Shared Workspace](https://github.com/JimLundin/shared-workspace)
application is maintained separately. Workspace retains its Windows Python/Qt
implementation, including the keyboard, dictation, assistant and automation.

The project, launcher, installation directory and bundle are named Workspace.

The agent uses **OpenAI Agents SDK 0.24.0**. Every interface uses **Qt 6.12**:
the floating bar, conversation bubbles, History, Work, prompts,
keyboard overlays, and keeper dialogs. The assistant has one Qt event loop;
the keeper owns its own protected Qt UI. Workspace runs directly on installed Windows Python 3.15. The keyboard process uses only the standard library
and our typed Win32 bindings (`winapi/`), independently of the assistant.

## Start

1. Extract **`workspace-sdk-python315-win64.zip`** into a folder you can write to.
   Install **Windows x64 Python 3.15.1** once using the official installer, with
   the Python launcher enabled. It is already installed on this laptop. The ZIP
   includes matching agent and Qt dependencies in `.runtime`; keep that folder
   beside `StartWorkspace.cmd` and `workspace.pyw`. It contains no Python interpreter.
   Workspace requests **English (US)** while its layout is enabled and your configured
   **Colemak** layout when disabled or stopped. While the Charybdis Nano (3x5)
   Splinky firmware keyboard is connected, Workspace automatically pauses its
   remapping and keeps **English (US)**, including when Workspace exits. Unplugging
   it restores the previous laptop layout state. The device is identified by
   USB vendor/product ID (`A8F8:1832`), so changing USB ports works; other keyboards
   and the YubiKey do not trigger switching. Both keyboards use the selected mode.
   It rechecks attached keyboards and the foreground app every
   200 ms. Elevated applications may refuse the request. `WORKSPACE_COLEMAK_LAYOUT`
   can select a specific installed Windows layout ID; by default Workspace resolves
   the Colemak entry in your Windows input-language list.
2. Set these environment variables (Start → "Edit environment variables for your
   account"; no admin needed):

   | Variable | |
   |---|---|
   | `OPENAI_BASE_URL` | your endpoint, ending in `/v1` |
   | `OPENAI_API_KEY` | its key |
   | `WORKSPACE_CHAT_CLASS` | optional; default `small` (tidied dictation and dictated commands) |
   | `WORKSPACE_AGENT_CLASS` | optional; default `extra_large` (main agent, canvas investigation and self-modification) |
   | `WORKSPACE_NOTIFICATION_SCREEN_CLASS` | optional; default `small` (quick notification relevance screening) |
   | `WORKSPACE_NOTIFICATION_RESEARCH_CLASS` | optional; default `medium` (focused inbox research, including public lookups) |
   | `WORKSPACE_PERSONAL_WORK_CLASS` | optional; default `medium` (matching sources to ongoing work) |
   | `WORKSPACE_MODEL_SMALL` | optional; default `gpt-6-luna` |
   | `WORKSPACE_MODEL_MEDIUM` | optional; default `gpt-6.1-terra` |
   | `WORKSPACE_MODEL_LARGE` | optional; default `gpt-6.1-sol` |
   | `WORKSPACE_MODEL_EXTRA_LARGE` | optional; default `gpt-6-astra` |
   | `WORKSPACE_AGENT_REASONING_EFFORT` | optional; default `low` for quicker replies; use an effort supported by your selected model |
   | `WORKSPACE_AGENT_CONTEXT` | optional; default `recent`; set `off` to disable idle activity tracking and automatic request context |
   | `WORKSPACE_TRANSCRIBE_MODEL` | optional; default `gpt-4o-transcribe` |
   | `WORKSPACE_VOCABULARY` | optional; names and jargon to expect in dictation |
   | `WORKSPACE_LANGUAGE` | optional; `sv` or `en`, default detected |

   Without the first two the layout, snippets, apps and window keys still work;
   the AI keys tell you what's missing.

   Every `*_CLASS` accepts `small`, `medium`, `large` or `extra_large`. Roles and
   delegated subtasks share the same four model mappings. Choose a size for a
   role; change its `WORKSPACE_MODEL_*` value to select a different provider model
   for every use of that size. Restart Workspace after changing environment settings.
3. Turn on Settings → Privacy & security → Microphone → **Let desktop apps access
   your microphone**.
4. Double-click **`StartWorkspace.cmd`**. A dot appears in the tray. To start it at login,
   put a shortcut to it in `shell:startup` (Win+R).

Existing `workspace.pyw` shortcuts still work when Windows has a Python file
association, which must select Python 3.15. The bundle
does not change the system Python installation or file associations.
`pyw -3.15 miryoku.pyw` runs the layout alone, without the assistant
or keeper.

## What you see

- **Floating Workspace controls**: a small glass capsule showing local time, battery
  and weather when Windows location is available. Click the clock or power readings
  to open its menu.
  Holding Spacebar shows Listening with a real microphone
  waveform; stopping capture shows Transcribing until the request finishes.
  The capsules sit 8 pixels below the top screen edge. Volume and Wi-Fi have
  fixed status icons that change with their observed state, including unknown readings.
  Outer corners curve into the screen edge. Active segments join across their
  upper edge and slide in from above, returning upward when hidden. Reduced
  motion uses an immediate transition.
  It expands for dictation, transcription or agent work, and shows Stop only while
  the agent is running. Active recording has its own microphone/timer capsule.
  The centre is exclusively dynamic activity and is empty at idle. The fixed
  Canvas button sits at the far left, then the Outlook and Teams web slots, then
  running applications. The fixed
  right cluster reads keyboard when relevant, then
  a combined speaker/Wi-Fi/clock/power capsule at the far right. Battery percentage
  stays visible even when plugged in or full, with reserved reading widths to
  keep the status cluster stationary. The system tray's icons sit in the
  controls menu. Tooltips and accessible names retain
  control meanings and keyboard state. Work, recording-start,
  keyboard controls and other tools are available from the menu. The surface uses
  the same translucent material as agent messages.
  See [toolbar design](docs/toolbar-design.md) for the states and references.
- **Windows taskbar**: kept hidden while Workspace runs. Tap the **Windows key** to
  reveal it and open Start; tap it again to hide it. Win+E and other Windows-key
  combinations retain their usual behavior. The bar's menu also offers a
  taskbar toggle. Taskbars are restored when Workspace exits, including by an
  independent recovery helper if its process is terminated.

Workspace now represents personal work on a local Qt canvas using its conversation
bubble components. Edge supplies access to business resources. The separate
[Shared Workspace](https://github.com/JimLundin/shared-workspace) project and its
embedded browser are paused; Workspace retains its Windows desktop runtime.

- **The tray dot**: green: running, layout on · grey: layout off or not running ·
  red: listening · amber: working or waiting for your reply · blue: the agent is on a task. Hover for words;
  click for the menu. Actions with hotkeys show them alongside their names, using
  physical keycaps: **Hold V + L** means hold V (Tools), then tap L to open the agent.
  (Windows 11 may tuck it behind the ^ at first: drag it out.)
- **Layout: on/off** (tray menu): the status is also a toggle. Click it or tap
  **§** to switch; a checkmark means the layout is on. If the layout has quit,
  choose **Start layout** first.
  While the firmware keyboard is connected, the layout stays off and the toggle
  is ignored. Ordinary firmware output passes through; **Ctrl+Shift+D** holds
  dictation and **Ctrl+Shift+G** holds agent speech. Hold the right hand's
  home-row Ctrl+Shift modifiers, then hold D for dictation while speaking.
  For agent speech, hold the same modifiers and G.
  These are ordinary Miryoku keys; Space/Enter thumbs change layers when held.
  Releasing D or G finishes dictation or sends to the agent, even if the
  modifiers were released first. **Ctrl+Alt+Shift** plus a letter reaches
  navigation and apps, as on the laptop; see the keyboard chords below. No
  firmware update is needed.
- **Restart assistant** keeps the keyboard layout and automation running while
  the assistant and floating bar reload. Dictation stops with the assistant;
  unavailable shortcuts give a warning sound, and ordinary typing continues.
  **Restart automation** reloads that worker independently. **Quit Workspace**
  closes all components.
- **Keyboard overlay**: a faded, click-through key map near the bottom of the
  main screen. It stays visible while the layout is on and follows held or
  locked layers. Small labels identify the printed keycaps; large labels show
  their new outputs, with hold actions below. Keys light up while you press them,
  including every key held in a chord; quick taps leave a brief flash.
  Hide or show it with **Keyboard
  overlay** in the tray menu. Use the **Drag to move** handle above it to place it
  on any monitor; the keys remain click-through. Your position and visibility
  choice are remembered across restarts.
- **The layer indicator**, at the bottom of the screen: the layer you're holding or
  have locked (`NAV`, `NUM · locked`), and `CAPS WORD`. It flashes *Layout on/off*
  when you tap §. It can't be clicked and never takes the keyboard.
- **Key map** (tray menu): your keyboard drawn as each layer has it. Keys 1–6 or
  the buttons switch layer; the thumb holding the layer is highlighted.
- Sounds for layout on/off and caps word; a warning sound and a notification
  when something fails (with the reason).

## The keys

Physical keys are named by their Nordic keycaps.

| | |
|---|---|
| **§** | tap: layout on/off · hold 2 s: quit the layout |
| **Spacebar** | push-to-talk dictation, typed where the cursor is on release |
| **B** | toggle dictation; press again to stop and insert |
| **N** | hold to speak to the agent; release to send |
| **Ctrl+Alt+Shift** + a letter | navigation, apps and the window switcher; see the keyboard chords below |
| thumbs **X C V** | Esc · Space/**Nav** · Tab/**Tools** |
| thumbs **M , .** | Enter/**Sym** · Backspace/**Num** · Delete/**Apps** |

Use the physical **C** thumb key to type spaces; hold it for Nav. The physical
These physical voice buttons work on every layer while the layout is on. They
keep their voice action when a modifier is held; C remains the typing-space/Nav
thumb. Meeting recording is available in Workspace controls. Successful voice transcripts are copied to
the Windows clipboard before submission and retained in memory; **Copy latest
transcript** in the bar menu recovers them if input or clipboard access fails.
Transcription failures do not replace the saved text.

The **⌃⌥⇧ C** chord opens a searchable list of
windows across screens. Use arrow keys to select, Enter to switch,
and Escape to cancel. The normal Enter and
Escape thumb bindings work here. Minimized windows restore when focused.
Unbound physical keys are blocked while the layout is enabled. Physical **Shift**, **Ctrl**
and **arrow keys** remain native, including Shift+arrow selection. All function
keys, media controls and Windows key's taskbar action also remain native.
Turning the layout off restores the normal keyboard; other modifier and
navigation actions are available through the layout's home row and layers.

The dictation microphone is opened when Workspace starts and kept ready between
captures, so you can speak as soon as you press a talk key. When the Windows
default microphone changes, Workspace reopens it on the new default within a few
seconds, or at the next press; dictation and the bar's waveform share it. Dictation records only
while the key is held, and the microphone is released when Workspace quits. On release,
Workspace waits for Windows to return the complete recording before transcribing
it. A failed or incomplete buffer is reported instead of sending partial audio.

**Tools** (hold the Tab thumb, then the right hand):

**Hold V + T** expands the toolbar to present the pending agent request, just like
the toolbar bell. Its canvas icon opens the exact question. Without a pending
question the shortcut opens the canvas. It uses the physical keycaps with
Workspace's layout enabled.

| | | | |
|---|---|---|---|
| home **I O** | dictate, tidied (hold) | dictate a command (hold) | |
| bottom **K L Ö** | agent, by voice (hold) | agent, typed | stop the agent |
| thumb **M** | dictate (hold); B uses a toggle | | |

**Apps** (hold the Delete thumb, physical **.**):

| | | |
|---|---|---|
| thumbs **C V** | copy the latest transcript | start or stop meeting recording |
| right thumb **M** | agent speech toggle | |
| right **'** | dictation toggle | |

Navigation and apps are the keyboard chords below; the Apps layer keeps no
copy of them.

**Keyboard chords.** Navigation and apps are **Ctrl+Alt+Shift** plus a letter,
the same on the laptop layout and the Charybdis Nano. Hold the three home-row
mods with one hand: **R S T** on the left or **I E N** on the right. Tap the
letter with the other hand. The right-hand letters follow Miryoku's NAV
positions. The left-hand letters are the apps from `config.py`, in order.
Letters are the Colemak-DH letters both layouts type, so the same fingers do
the same thing on either keyboard. On the laptop, home-row mods on one hand
combine: press all three together and they wait for a letter from the other
hand; released without one, they type their letters. The laptop's physical Ctrl
and Shift keys don't count toward a chord. While the chord's modifiers are
held, on either keyboard, the bar's pager shows each target's chord. Workspace
swallows the letter's press and release, so no character is typed. The
modifiers themselves are released as usual, so none stays held. Other letters
and other modifier sets keep their usual meaning. Win is never part of a chord,
because Ctrl+Alt+Shift+Win is the Office key. Windows has no Ctrl+Alt+Shift
letter shortcuts. These app shortcuts give way to a chord: Word's **S** (Styles pane), Teams' **R** (report a problem), the Teams web
app's **C** and **B** (inline code and code block) and Excel for the web's
accessibility-menu **T** and **H**.

An app chord switches to the desktop where the app is placed and focuses its
window; pressed again it goes through the app's windows, and it starts the app
when it isn't running. Outlook and Teams are the toolbar's pinned web apps. The
focus chords move to the nearest placed window in that direction on the current
desktop, across monitors. Zoom fills the monitor with the focused window until
you press it again or focus another window. The desktop chords don't wrap.

| chord | does |
|---|---|
| ⌃⌥⇧ **N** | Focus ← |
| ⌃⌥⇧ **E** | Focus ↓ |
| ⌃⌥⇧ **I** | Focus ↑ |
| ⌃⌥⇧ **O** | Focus → |
| ⌃⌥⇧ **J** | Desk 1 |
| ⌃⌥⇧ **L** | Desk 2 |
| ⌃⌥⇧ **U** | Desk 3 |
| ⌃⌥⇧ **Y** | Desk 4 |
| ⌃⌥⇧ **K** | Desk ← |
| ⌃⌥⇧ **H** | Desk → |
| ⌃⌥⇧ **M** | Zoom |
| ⌃⌥⇧ **Q** | Terminal |
| ⌃⌥⇧ **W** | Browser |
| ⌃⌥⇧ **F** | Outlook |
| ⌃⌥⇧ **P** | Teams |
| ⌃⌥⇧ **B** | Files |
| ⌃⌥⇧ **A** | Code |
| ⌃⌥⇧ **R** | Notepad |
| ⌃⌥⇧ **S** | Excel |
| ⌃⌥⇧ **T** | Word |
| ⌃⌥⇧ **G** | PowerPoint |
| ⌃⌥⇧ **X** | Pause place |
| ⌃⌥⇧ **C** | Windows |
| ⌃⌥⇧ **D** | Re-place |
| ⌃⌥⇧ **V** | Min |

**Snippets**: type the trigger and it's replaced: `,,date` `,,time` `,,now`
`,,week` `,,shrug` `,,thx` `,,mvh` `,,br`. Add your own in `config.py`. Physical navigation, window changes, pointer movement
and injected workspace text reset a partially typed trigger.

## Window placement

Workspace puts each app's windows in a declared place for the connected
monitors: the laptop alone, home (the laptop and a 4K screen) or work (the
laptop with a landscape and a portrait 2560×1440 screen). Windows never
overlap; apps that don't fit go on further Windows virtual desktops, which
Workspace creates when needed. Dragging a window away snaps it back once you
let go. The bar's pager and the desktop chords switch between desktops. See
[window placement](docs/window-placement.md) for the layouts and rules.

## Windows notifications

Workspace reads Notification Center locally as context for the agent. Teams,
Outlook and other app arrivals do not create floating alerts or increase the
clarification count. The agent collects related information on the native canvas.
Desktop prompts ask for your input or point to an important canvas change.
Raw notification bodies stay in memory and are supplied to your configured AI
endpoint for triage. Preferences, source revision hashes and proposed work are
stored with Windows DPAPI encryption; notification bodies are not logged.

While notification access is allowed, Workspace suppresses registered apps'
native Windows banners using their **Show notification banners** setting. It
keeps notification delivery and Notification Center enabled. A registry lease
records the previous settings before changes, survives reloads, and restores
them on exit. Newly registered sources are reconciled on subsequent polls.
An entirely new source can display its first banner before that reconciliation;
Windows **Do not disturb** also covers that gap, subject to its priority rules.
App-drawn popups have separate settings. **Windows notification settings** in the
bar menu opens the system page. Notification access must be allowed on each machine;
the current Windows installation supports the listener without a packaged helper.
The listener exposes notification text and dismissal, but not every app's original
reply/action buttons. See [Windows shell integration](docs/windows-shell-integration.md).

## Meeting transcripts

The toolbar menu's **Auto-record Teams** toggle saves an opt-in for browser
meetings in the approved Edge debugging connection. **On** means the monitor
is armed; a red dot and advancing timer mean audio capture has actually started.
The monitor reads Teams' in-call microphone, Leave and duration controls every five seconds,
without navigating or activating your tab. Chat, prejoin and lobby do not start
capture. Leaving stops an automatic recording after a ten-second debounce.
Choosing Stop suppresses automatic restart for that call. Manual recordings
remain independent. If observation fails for thirty seconds, automatic capture
stops and the menu reports a connection problem. The “Automatic Teams recording
unavailable” warning appears once per continuous outage; thirty seconds of
healthy observations rearm it. Choose **Record a meeting** manually if needed.
Native Teams and other browsers are outside this trigger.

Choose **Record a meeting** from the tray or the agent timeline's **⋯** menu,
or tell the agent to start a meeting transcript. Recording continues until you
choose **Stop**, tell the agent to stop recording, or quit Workspace. A red tray
dot and a small elapsed-time bar show when capture is active. Other agent tasks
and the dedicated voice buttons keep working during a meeting.

The default records the **Windows default microphone and default playback
device** together, so it includes remote participants heard through that playback
device. For a room-only recording, choose **Record microphone only** in **⋯**.
An app using a different output device needs to use the Windows default output
to be included. Headphones prevent computer playback from also echoing through
the microphone. Speaker names are not inferred.

Timestamped text appears in the existing timeline in roughly 20–30 second
chunks, as requests finish. The timeline keeps a short recent preview; click the
recording bar or **Open** for the complete Markdown transcript. **Transcripts**
opens `%LOCALAPPDATA%\workspace\meetings`; each meeting has its own dated folder.
There is no five-minute limit or fixed meeting duration.
Brief microphone dropouts leave a gap at their original time; recording and
computer-audio capture continue from the next valid packet.

Only audio awaiting transcription is kept locally, in a recovery journal.
Successful chunks are replaced by text and their audio storage is erased and
reclaimed. Audio capture and network requests run independently. A connection
failure retries while capture continues; **Retry** resumes a paused transcript.
The pending-audio limit is 256 MiB (about 2 hours 20 minutes of untranscribed
speech). Reaching it stops capture visibly and retains the saved part instead of
using unlimited memory or disk space. Device errors also stop capture visibly.

Stop saves the final partial chunk and lets transcription finish. On quit, saved
pending audio is retained for transcription after the next launch. Recovery
does not resume capture from an old journal. With Auto-record Teams enabled,
a currently joined browser call can start a new recording after restart. A crash can
lose the most recent audio still in memory; committed text and
audio recover from the journal, including if a transcript-file write was interrupted.

This uses Windows WASAPI and the existing configured transcription endpoint;
there are no new dependencies. Chunk sizing and previous-chunk context follow
the [official OpenAI speech-to-text documentation](https://developers.openai.com/api/docs/guides/speech-to-text).

Open **Meetings** in Work to browse saved recordings and read their transcripts.

## The agent

Press **N** to start an agent request; press it again to stop and send. Voice
and typed requests use the existing saved work journal. **Hold V + Ö** stops the
agent and clears queued follow-ups. The toolbar's Canvas button opens your local
work surface; the agent collects evidence, maintains connections and builds on
work threads there.

Clarification bubbles live alongside their work on the canvas. Their desktop
card expands the complete request in place; the toolbar bell, **Needs you** and
**Hold V + T** expand the toolbar to present it too. **Hold N** to reply and release
to send; the same agent work resumes with your answer. A separate canvas icon
opens the exact question when you want its surrounding context. The bell counts
pending clarifications. Answered questions retain your context, and a rejected
submission keeps your reply available for retry.

Floating bubbles use the existing Windows glass, contrast and motion treatment.
They present questions and useful canvas findings or state changes. Routine app arrivals stay quiet after quick relevance screening.
One requested outcome keeps its updates, tools and final reply in one card.
Related notification work shares that card through its work context even when
the canvas arranges contributions separately. The trail holds at most three
cards, and completed cards expire after a reading delay. Questions remain until
answered or closed. Meeting recording retains its own control.
**Hold V + L** or **Agent session** opens explicit conversation history.

Workspace reuses one existing Teams tab on the approved Edge connection for
chat collection, Activity and opening conversations. Collection pauses while
that tab is visible. Reconnecting adopts an existing Teams tab if its saved ID
has expired. The connection host survives assistant reloads.
The first connection follows four chats; an unavailable chat keeps its place
while others continue updating. Complete account-scoped synchronization still
needs a supported API adapter.

Speak naturally to Workspace: “Continue the Atlas handoff” or “Find the emails
related to this migration.” The agent reads the saved work representation and
its exact source context before researching and updating it. Incoming content
is evidence; it does not authorize sends or command approvals. Outlook, Teams
and Kanban tools use their signed-in Edge pages and preserve existing drafts.
Rendered pages and active filters bound source coverage.

Handling an activity tries its exact **Mark as read** action and checks the
result. The source status reports an unconfirmed read action explicitly.
Handling a Windows notification dismisses that exact notification. Handling a
chat is local to Workspace and does not certify Teams desktop read badges or
flashing. Calendar invitations can be triaged or opened in their source;
accept/decline operations remain there.

Coverage includes rendered messages in followed chats and rendered Activity
rows, with bounded in-memory history. It does not provide all-chat unread counts
or complete older history. Reactions update their original message quietly.
Handled source identities and content fingerprints survive reloads.
Settings, your drafts and outgoing attempt evidence are saved under your Windows
account using DPAPI encryption. The communication cache keeps incoming bodies
in memory; context explicitly supplied to Workspace follows its usual saved-task
policy.
An uncertain reply is never resent automatically: inspect the chat, then choose
**I checked this in Teams** to allow another reply while retaining the evidence.
Starting **New chat** resets agent context and keeps the Teams projection.

Notifications stack in the right corner of the foreground window's monitor. Each bubble fits its content up to
360 logical pixels wide (280 for your requests), keeping its right edge anchored as it grows. Longer
entries share the available height, with space reserved for the
voice-reply hint. A small scroll marker shows progress through overflowing text.

The SDK loads in the background and the notification view is prepared on the
existing UI thread after Workspace starts. History widgets are created when you
open it. The source workspace is prepared only when a source tool is used.
Failed requests show the reason in a bubble and the timeline;
they also notify you and are recorded in
`assistant.log`. Agent tasks use the **extra-large size with low reasoning effort**
by default, mapped to GPT-6 Astra. `WORKSPACE_AGENT_CLASS` selects another size,
independently of dictation cleanup and background screening/research. The endpoint must
support the selected model through the Responses API.

File writes, commands, opening files, desktop control and self-updates run
without confirmation prompts. Requests to change Workspace authorize the agent to
edit its source and model settings, test the result, install it and reload.
The agent is instructed to publish or send messages only when you request that.
The **×** stop button remains available throughout the task.

The agent can work across desktop applications: inspect accessible controls,
read their text, fill fields, invoke buttons, select list items, toggle options,
expand menus and set sliders. It can also hover, click, drag with modifiers,
scroll in either direction, paste text, use keyboard shortcuts, and move,
resize, snap, minimize, maximize or close windows. Screenshots can cover a
window, monitor, region or the whole desktop. PowerShell supports working
directories and timeouts; Stop terminates its running command and child
processes. The agent can use installed applications' APIs and COM interfaces
through PowerShell when those suit the task.

For web tasks, the agent owns an **exclusive headless Edge instance**, separate
from the browser you view. Its profile lives at
`%LOCALAPPDATA%\workspace\browser-profile`. The instance stays running between
tasks and retains its own sign-ins. The agent lists its pages, reuses their IDs
and closes pages after saving useful context. Each completed, suspended or failed
run releases temporary pages and leaves one idle blank page. Stop and Workspace
exit close the owned process tree; the sign-in profile persists.

If authentication is needed, the agent opens its dedicated profile visibly for
you to complete sign-in or MFA. That handoff survives a suspended task; continuing
work returns to headless mode with the same profile. Cookies are never copied
from your personal browser. Sites still control session expiry and MFA. The
agent can read page text and controls, fill forms, handle frames and open shadow
roots, and capture browser screenshots. Sources requested for review open through
the desktop in your normal browser. See [background automation](docs/background-automation.md).

Teams and Outlook web tools use signed-in pages in the agent's dedicated profile.
Workspace has no Teams API integration; all Teams work runs in the browser. The agent can read/select Teams conversations, search/read
Outlook conversations and prepare unsent replies while preserving existing drafts
and Outlook signatures. The internal AIP Kanban tools read tasks, edit fields,
post comments and move cards with stale-state checks and saved readback, using the
app's existing validation and board filters.
See [background automation](docs/background-automation.md) for
permissions, tool details and current limitations.

While idle, Workspace keeps recent app and window-title changes in memory: up to
128 changes over the last 30 minutes. Each request receives recent activity and
a screenshot of the last work window when the request starts. This helps it
understand "this window" and "what I was just doing". Opening Workspace's timeline
does not replace that work window. Queued requests retain their own invocation
context; their screenshot is taken when they start running. Activity while the
agent is working is marked so it can distinguish its own actions.

The idle tracker collects no screenshots, keystrokes or clipboard history, and
makes no model calls. Request context goes to your configured endpoint and stays
in the conversation until **New chat** or exit; only the latest two screenshots
are retained. The idle activity buffer expires separately. Set
`WORKSPACE_AGENT_CONTEXT=off` and restart to turn off this automatic context.

Desktop automation uses the permissions of your Windows account. A locked
desktop or an elevated application can block screen capture and input. Some
applications expose few accessibility controls; the agent can use screenshots,
input or an application API instead. It checks results and reports an actual
blocker when Windows refuses access.

It stops after 80 steps (`AGENT_MAX_STEPS`). The task journal records each
consequential action and its outcome. Browser and Teams arguments and results stay
out of persistent journals and activity details, including form values and
sign-in codes.

The main agent can delegate independent work to **small**, **medium**, **large**
or **extra large** subagents, choosing the smallest suitable model for each task.
Their model IDs are configurable above; these are workload classes, not published
parameter counts. Up to four subagents run in parallel per delegation, each with
at most twelve model turns and the current task's tools.
They inherit the configured reasoning effort, so choose an effort supported by
all selected models. Child conversations are separate; the main agent supplies
their context, collects named results and owns the final answer and verification.
The timeline shows each child's class and status. Stop covers every child.
Computer actions remain serialized; work on the same desktop, tab, source draft
or document belongs to one agent because multi-call sequences are not exclusive.
Subagents cannot spawn further agents.

## Durable work

Open **Work…** from the tray or conversation menu. Voice and typed
requests use the same saved task journal. The
**Canvas** button beside the floating-toolbar menu opens a dedicated native
window for ongoing outcomes and responsibilities. Workspace automatically
connects related emails, Teams conversations and Kanban tickets, with a current summary, suggested next step
and an explanation for every connection. One source can support several pieces
of work. Create or edit work, mark it done, open its original sources, or remove
a wrong connection; automatic reviews remember removed connections. Work,
sources and personal notes share the canvas. Drag bubbles to arrange them, drag
empty space to pan, and use Control + wheel or the zoom controls to navigate.
Each bubble’s small expand control opens its details. **Continue with agent**
starts research attached to that work thread. Questions and results keep that
connection across reopening. Arrange groups connected work and evidence using
actual bubble sizes, including expanded details. Dragging pins a bubble; ordinary
reflow preserves it. The + menu also provides **Arrange all, including moved
bubbles**. Notes and positions are saved locally.

Collection reads the signed-in Edge pages without changing searches, board
filters, chat selection or drafts. Coverage follows rendered content; sources
that disappear from view keep their saved connections. Content changes trigger
bounded reviews using the configured personal-work size (medium by default).
**Refresh sources** requests a fresh review. Canvas edits update the personal representation; source controls
open the corresponding resource in Edge.

Choose **Agent tasks and settings** in the canvas’s **+** menu to open a separate
window for execution and supporting context:

- **Agent tasks** shows instructions, progress, questions, results, and verification
  evidence. Pause, resume, cancel, redirect a task, or create a follow-up.
- **Context** stores preferences and project notes you choose to save. Notes
  retain their source and expiry; expired text is excluded from fresh context.

Closing a view or choosing **New chat** keeps saved work. **Stop agent** cancels
the current conversation's active and queued tasks; individual tasks have their
own controls in Work. On restart, interrupted tasks recover from saved progress.
A task with an unknown action outcome checks what happened before repeating an
effect. Endpoint failures and other blockers wait for an explicit resume.

The worker executes one task at a time, and a task waiting for a reply releases
its execution slot. Questions survive restarts.

Completed transcripts trigger only after their final text has been saved.
Duplicate delivery creates one task, missed intervals coalesce, and disabling
an instruction prevents new handoffs. A handoff already accepted remains a
saved task that can be cancelled separately. Meeting-note outputs live under
`%LOCALAPPDATA%\workspace\work\work-results`, each in its task's folder.

## Changing Workspace

Ask the agent, by voice or typed: "add a snippet for my email address", "make
the indicator smaller", "add a key that opens my timesheet". It works on a copy
of the source in its own folder under `%LOCALAPPDATA%\workspace\workspaces`. Draft
edits stay available for follow-up requests in the same conversation, then:

1. **Check and fix**: every Python file, including the `.pyw` launchers, compiles.
   The agent imports changed modules and runs the tests its change affects,
   including Windows integration tests, on a fresh copy of its draft. It sees
   every failure the keeper would refuse, fixes it and checks again in the same
   task. When those tests pass, the bundled Ruff and pyright and the
   architecture and interface reviews check the draft as CI would, so a
   self-change cannot push errors to main. Ruff's signed binary is the bundle's
   only executable; pyright runs on the installed Node.js.
2. **Submit**: the agent sends the checked change to the keeper without a
   confirmation step.
3. **Verify**: the keeper checks its own frozen copy of the source: every module
   imports and the full suite, including Windows integrations, passes. Failed
   checks or changes to the candidate during checks prevent installation.
4. **Install and restart**: the keeper saves the current version and durable
   recovery state, installs the checked copy, clears old bytecode, and restarts
   the layout, assistant, and automation worker. File-write failures restore the previous version.
5. **A ten-minute trial**: a startup failure or a crash undoes the change, and
   quitting or rebooting during the trial restores the previous version on the
   next launch. After ten minutes without a crash the change stays.
6. **Merge**: the task commits the installed source to `main` in a fresh clone
   and pushes it. It refuses when `main` moved since the install's snapshot;
   the change then stays installed but unmerged until you merge it by hand.
7. **Later**, tray menu → Undo rolls back the last update, even after restarting.
   Repeated crashes restore the previous version too.

The last 20 versions are kept in `%LOCALAPPDATA%\workspace\versions`. The agent
can't change the protected keeper, runtime activation, checker, dialogs or component-control
modules. The keeper's protected dialogs use the pinned Qt dependency; its typed
request inbox, rollback record and component-control transport use Pydantic.
A request it can't read is refused with a notice. The `.runtime` dependency directory is also
protected and stay outside source snapshots and updates. Code and tests run with
your account permissions.

## Publishing the agent's changes to GitHub

Installed self-changes land on `main` automatically (step 6 above). For a change
you want to review first, ask the agent to "publish it to GitHub for review". Its
`publish_changes` tool freezes the workspace, runs the runtime checks, commits,
and pushes a new `workspace/agent-*` branch without installing it. That path never
force-pushes or updates `main`. Merge the branch on GitHub after review.

Publishing requires **Git for Windows on PATH** and credentials already set up
for the repository (for example through Git Credential Manager). The Windows bundle includes the SDK dependencies for the other features. A missing Git installation,
failed authentication, failed test or changed remote base produces an error and
stops the push. Credentials are not written into the source or journal.

Optional environment settings:

| Variable | Default |
|---|---|
| `WORKSPACE_GIT_REMOTE` | `https://github.com/JimLundin/workspace.git` |
| `WORKSPACE_GIT_BASE` | `main` |
| `WORKSPACE_GIT_AUTHOR_NAME` | `Workspace Agent` |
| `WORKSPACE_GIT_AUTHOR_EMAIL` | `workspace@localhost` |

The running source must match the selected remote base before publishing. After
merging, update the running source to that base; if you installed an unmerged
change, either select its published branch as the base or merge it first.

## Agent implementation

Workspace uses the [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents/quickstart)
through `assistant/sdk.py`. Its `Runner` owns model turns and tool execution;
`assistant/agent.py` dispatches Workspace's tools; each tool family
(`assistant/*_tools.py`) owns its tools' schemas, permissions and evidence.
A task's profile owns its execution and toolset in `assistant/task_profiles.py`:
a general request continues its conversation with the request's desktop context
and offers the whole desktop. The supervised
automation process owns execution, browser sessions, and the durable action
journal; the assistant owns views, human input, and audio capture. The SDK
uses your configured OpenAI-compatible
[Responses API](https://platform.openai.com/docs/api-reference/responses) endpoint
for agent tasks and tool calling, with streaming enabled.
The configured reasoning effort and `summary: "auto"` are sent on every agent request. Encrypted
reasoning and completed tool results stay in the conversation across turns.
Only public summary and response-text events reach the view. The SDK adapter
assembles content parts; immutable timeline entries replace each live row.
Publishers belong to one request, so late events cannot enter another turn.
Tools run
one at a time, enforced locally so endpoints that reject `parallel_tool_calls`
still work. `delegate_subtasks` is an SDK orchestration tool: it validates named
tasks and class choices, then starts independent `Runner` loops using the selected
configured models. All loops share the same effect gate and durable claim; child
loops receive only the profile's existing tools. Only the main conversation is
checkpointed, with the collected child results retained for follow-ups. Child
response text stays with the manager rather than appearing as its final answer.
The installed SDK owns loop execution, HTTP recovery and stream parsing;
Workspace owns class routing, bounds, cancellation and effect ownership.
Automatic request images and screenshot tool results share a limit
of two retained images.
Response storage and tracing are disabled. Quick chat and transcription still
use `assistant/llm.py` and their existing endpoints.

The notifications in `desktop_ui/agent_toasts.py` and conversation history
in the same floating feed share the main UI thread in `desktop_ui/ui.py` with
prompts, answers, reviews, the key map and overlays. Qt owns the event loop;
`desktop_ui/qt_ui.py` manages shared composition and UI timers. Closing a view
leaves that loop available to the remaining views. The hidden Windows message
window and its message loop have their own application control thread.
`desktop_ui/agent_window.py` owns the session controller and queues
immutable snapshots for painting through `desktop_ui/view_publication.py`, the
lifecycle it shares with the work window. The model and inline questions stay on worker
threads. `desktop_ui/notifications.py` projects bounded notifications with pure
lifetime transitions; expiry never removes session messages. Background updates
preserve keyboard focus; history preserves selection and scroll position.
`desktop_ui/toast_card.py` draws the text and controls on a per-pixel transparent
Qt surface. `winapi/composition.py` places native background blur and a soft
shadow beneath it, clipped to a 26-pixel rounded shape. The glass tracks Qt's
actual bounds after display scaling. `winapi/appearance.py` samples neighboring
background pixels on one bounded worker to select readable text and tint.
A shared timer rotates existing spinner shapes only while needed; it does not
rebuild the text. Reading timers also observe hover over transparent pixels.
`desktop_ui/components/text.py` measures Markdown in separate text documents before each
final card layout, so updates never resize visible windows just to measure text.
Agent messages render
Markdown headings, nested emphasis, lists and checklists, quotes, code blocks,
strikethrough and links. Tables use compact labelled rows to fit the narrow
timeline. Text stays selectable, code stays literal, and questions stay inline.
There is no browser runtime, local UI server or separate agent UI process.

`assistant/activity.py` samples foreground app/title changes once a second.
`assistant/commands.py` runs cancellable commands with bounded output.
`assistant/uia.py` and `assistant/uia.ps1` bridge the installed Windows UI
Automation API through PowerShell/.NET, scoped to a window with stable runtime
control identifiers. This adds no Python packages or browser dependencies.

The installed Python version is declared in `.python-version`; matching
Windows dependency artifacts are pinned in `requirements/windows-py315.lock`.
`.runtime/manifest.json` records the Python ABI and included dependency wheels.
The archive contains the Agents SDK, `markdown-it-py`, PySide6 Essentials,
Shiboken and the win32more Windows composition bindings, with their dependencies.
It contains no Python executable or standard library. `StartWorkspace.cmd` uses
`pyw -3.15` to start the installed interpreter directly. Runtime activation checks
the dependency ABI before loading native modules; children use the same installed
Python. Checks reuse the dependency folder and its Windows import hooks.
Changing either dependency pin requires rebuilding with `scripts/bundle.py`.

## Logs

All in `%LOCALAPPDATA%\workspace` (tray menu → Open logs folder):

| File | |
|---|---|
| `usage.jsonl` | which features were used, how long they took, whether they failed. Voice uses include held/audio durations, transcription/submission timing, and transcript/requested/submitted character counts; agent uses include preparation, first response and first tool timings. Never what you typed or said. Tray menu → **Usage report** lists every feature by use, and the ones never used, so they can go. |
| `work/work.sqlite3` | saved tasks, checkpoints, questions, action fingerprints and outcomes, and explicit context |
| `assistant.log`, `automation.log`, `layout.log` | problems and crashes |
| `work/worker.log` | bounded work-process diagnostics; automation failures point here |
| `agent-ui.log` | desktop view startup timing and errors |
| `keeper.log` | starts, installs, trials, undos |

What leaves the laptop: recordings (for transcription), dictated text you have
tidied or turned into a command, and the recent app/window context and request
screenshot when automatic context is enabled. These go to your configured
endpoint. The idle activity buffer is not written to disk.
Optional toolbar weather sends Windows coordinates rounded to a tenth of a degree
to Open-Meteo. It stores neither location nor weather on disk.
Task instructions and public progress/results are saved locally for recovery.
The action journal does not store arbitrary command text, browser/Teams
payloads, screenshots, credentials, encrypted reasoning, or raw SDK history.

## How it's built

```
keeper.py       runs the programs; installs, tries and undoes changes (protected)
selfcheck.py    compile, import, test: the gate every change passes (protected)
protocol.py     what the layout and the assistant say to each other (window messages)
config.py       your settings: apps, snippets, agent limits
usage.py        the usage log
winapi/         typed Win32 bindings: the only ctypes code
miryoku/        the layout: layout.py (the tables), engine.py (the logic), win.py
automation/     task.py and store.py (durable work), controller.py (execution),
                actions.py and execution.py (attempts and verification),
                context.py (saved knowledge),
                ipc.py, bridge.py, app.py (the supervised worker)
assistant/      llm.py (the endpoint), features.py (key actions), agent.py,
                agent_tools.py and *_tools.py (agent tool families),
                task_profiles.py (task execution), work_service.py (frontend IO),
                work_canvas_model.py, work_canvas_commands.py (shared contracts),
                desktop.py and app.py (native application composition)
desktop_ui/     ui.py and qt_ui.py (Qt dispatch and event-loop ownership),
                agent_session.py and agent_window.py (conversation presentation),
                agent_toasts.py and toast_card.py (floating feed and history),
                work_canvas.py and work_canvas_*.py (desktop canvas owner/views),
                work_panel.py and meeting_panel.py (work and meeting views),
                components/ and fonts/ (shared controls, appearance and typography)
```

The logic never calls Windows directly: the layout's engine goes through a
`Host`, the assistant's features through a `Desktop`, the agent through a
`Machine`, so behavior tests use explicit concrete adapters. The code is strictly typed, with no
`Any` outside the boundaries to untyped code (`winapi` for ctypes,
`desktop_ui` for GUI bindings,
`assistant/sdk.py` for SDK integration, and
`selfcheck.py` for looking inside modules). Data records use frozen dataclasses
with slots, checked from source. SDK lifecycle subclasses and Qt objects inherit
their libraries' storage. Tests exercise Workspace behavior and integration wiring.

## Development

On this laptop, develop in `C:\Users\Jim.Lundin\Projects\workspace` and use
`Dev.cmd` as described in [the iteration pipeline](docs/iteration-pipeline.md).
Use `main` in that single development checkout. The Linux path
`/home/jim/workspace` redirects to it.

Use `Dev.cmd watch` for affected tests on save, or narrow with
`Dev.cmd watch --tests tests/test_bar_model.py`. `Dev.cmd preview` restarts a real
toolbar/feed preview with sample data on save. Install the development-only
watcher with `.venv\Scripts\python.exe -m pip install watchdog==6.0.0`.
The [iteration pipeline](docs/iteration-pipeline.md) describes coverage, cached
source analysis, preview options and final check/deployment commands.

The canonical source is [JimLundin/workspace](https://github.com/JimLundin/workspace). Clone it and
run checks with Python 3.15 or later. Install source dependencies first:
`python -m pip install -e .`. The prebuilt Windows bundle needs no pip step.
Development tools are optional locally and required by CI.
The [functional design notes](docs/functional-design.md) explain the domain
models, effect owners, and keyboard performance measurements.
The source uses deferred annotations directly, `type` aliases and scoped generic
type parameters. It does not need `from __future__ import annotations`. Launchers
also require Python 3.15 and run in that interpreter without a handoff. On this
laptop, Windows `python`, `py` and double-clicked `.pyw` files use the user-installed
Python 3.15.1; the development `.venv` uses that installation and shares only
application dependencies with the Downloads bundle.

GitHub Actions checks Python 3.15 on Windows and Linux, plus
Pyright and Ruff on Windows with the native UI dependencies. Desktop end-to-end tests are available through the manual
**Windows desktop tests** workflow on a dedicated self-hosted Windows runner
labelled `workspace-desktop`; they take control of its keyboard and mouse.

If Windows refuses injected keys in an elevated application, the layout switches
off and passes physical keys through. Use the plain keyboard there, then tap §
to re-enable the layout when you return to a normal application.

## Tests

```
python selfcheck.py --fast --durations 10 # editing: defer Windows integration modules
python selfcheck.py --durations 10        # full gate, required before install
python -m pytest -q tests/test_pcm.py     # one area, with optional pytest installed
python -m scripts.typecheck && ruff check . && ruff format --check .
WORKSPACE_E2E=1 pytest tests/test_windows_*e2e.py
python scripts/bundle.py dist/workspace-sdk-python315-win64.zip
```

Both check profiles compile every Python source and import production modules.
`--fast` defers `tests/test_windows_*.py`; the keeper and CI use the full profile.
There is no pytest dependency in the installed bundle. CI runs the suite once
through selfcheck for each platform and checks the extracted Windows bundle too.

Inside an extracted Windows bundle, use `py -3.15 selfcheck.py` to run
checks with the installed interpreter. The bundle builder runs on Windows or
Linux and packages dependencies without downloading or embedding Python.

The `WORKSPACE_E2E=1` command runs on Windows only: it starts the real workspace, presses real
keys and drags the real mouse, and has the keeper install, undo and refuse
changes on a copy of Workspace (a few minutes, against a fake endpoint), so
leave the keyboard alone while it runs.

`tests/test_windows_agent_panel.py` exercises the actual Qt panel, including
queued input, inline responses, cancellation and updates while hidden.
`tests/test_windows_agent_toasts.py` exercises the Qt bubbles and native glass,
including attached results, text selection, scrolling, stop targets, display
scaling, reduced motion and cleanup.
