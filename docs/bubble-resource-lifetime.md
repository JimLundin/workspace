# Retained bubble surfaces

The feed uses one column width for proposals, conversations, standalone replies
and recording notices. The person's speech can use a smaller bubble. Long text
wraps and expands vertically within the work-area budget; narrow-screen tests
exercise that budget, rather than preserving text-sized reply silhouettes.
All native scenarios use the production `Card` renderer. `AgentToasts` accepts
desktop observations and a card factory at composition, so controlled pointer,
work-area and native-preparation scenarios need no global patching. Qt's own
painting and the native composition APIs remain trusted dependencies; tests
check our geometry, resource ownership and state decisions.

`AgentToasts` owns the native bubble windows and glass layers on Qt's thread.
Dismissal, expiry, pagination and conversation resets park those resources
instead of destroying them. Active and spare surfaces together are bounded by
`MAX_VISIBLE` (five). Surplus outgoing bubbles are reclaimed before acquiring
arrivals, so replacing a complete page cannot temporarily double the pool.
The spare collection is an immutable tuple; native resource mutation remains
local to its Qt owner. Shutdown closes every active and parked surface.

Parking clears content, text selections, identified steps and option buttons.
Binding a new item resets reading, geometry and disclosure state, while retaining
the native window, glass and reusable controls. Bubbles contain no editable reply
widgets; their tooltip directs the user to the agent voice-to-text button. Opening
one bubble collapses the previous one in a single shared layout update.

New entrance and exit transitions start after native preparation. Their
existing durations, curves and reduced-motion behavior remain in use. An exit
already in progress retains its clock across unrelated refreshes. Translation
updates native position without reshaping unchanged text and child controls;
size or details-height changes still lay out those contents.

Completed cards leave oldest first, with deadlines and simultaneous native exits
spaced by 250 ms. Older live cards pushed into the upper eight-line band retire
through the same resource owner; their hidden identities prevent later updates
from reviving them. Hover, expansion, pending input and recording protect cards.
History does not use the edge exit. Reduced motion parks exiting surfaces immediately.

The focused expiry, stack and native-owner campaigns detected all seven seeded
defects: reversed deadlines, independent deadlines, missing edge fading, missing
protection, reversed native exits, omitted retirement and revival after parking.
Each baseline passed; there were no survivors, timeouts or collection errors.
Reports are in Windows Temp as `workspace-expiry-mutations.json`,
`workspace-stack-mutations.json` and `workspace-exit-mutations.json`.

Each pooled card also owns its measurement documents, cleared on parking and
closed on shutdown. Measuring another card preserves its prepared paragraphs.
The shared text adapter rounds measurement budgets to Qt's whole logical pixels,
so fractional Windows scaling does not repeatedly reflow unchanged text.

One reusable precise timer advances card movement, text reveals, spinners and
automatic reading. Incoming observations preserve its deadline; native glass
publishes once per tick. An idle stack stops frame work. The work observer
prepares accepted answer/reasoning prose before posting to Qt, sharing immutable
spans through a cache bounded to eight recent bodies. Qt retains native document
ownership. [Current measurements](qt-animation-performance.md) cover these changes.

## Native measurements on 2026-10-28

The investigation used CPython 3.15.1, Qt 6.12 and GC enabled. Separate harness
processes exercised real offscreen native surfaces and fictional content, with
an instantaneous audio-level reader. No user speech or transcript was captured.
Windows remained shared with ongoing development, so absolute timings vary.

Alternating two sets of three bubbles previously recreated native resources
throughout the run. The eight first animation ticks were already past the
280 ms transition deadline; waveform gaps reached 3.51 seconds in that run.

After retention, the same workload created five native cards in total and none
after warming. The warmed event-loop maximum gap was 47.1 ms, waveform maximum
gap 102.3 ms, and median bubble animation interval 17.6 ms. The run produced
112 intermediate motion samples. Initial allocation remains: the maximum
waveform gap including pool filling was 311.8 ms. Retention removes repeated
construction; it does not promise that first-use allocation or arbitrary
desktop rendering can never delay a frame.

The disposable harness, frozen before/after sources and raw measurements are in
`%TEMP%\workspace-ui-investigation`; `performance_after.py` exercises the changed
source snapshot. This measurement covers Workspace bubble arrivals, not updates
originating solely in unrelated applications or actual microphone-start timing.

## Regression coverage

`tests/test_windows_bubble_lifecycle.py` exercises expiry and replacement through
the real notification owner, checking window reuse, cleared content and final
shutdown. It also advances the supplied clock during native preparation to
detect a transition expiring before its first tick, and checks that translation
does not invoke Workspace's child layout. The existing burst test verifies the
combined pool bound, hidden retired layers and their destruction at shutdown.
These tests cover Workspace lifecycle and scheduling choices; Qt and Python
resource primitives are trusted upstream.

The original retention campaign detected four focused seeded mutations: rebuilding
instead of borrowing a spare, starting motion from the pre-preparation clock,
hiding the reply editor without clearing its input state, and laying out child
contents on every translation. Both native campaigns had passing baselines,
with no surviving mutations, timeouts or collection errors. Their receipts are
`%TEMP%\workspace-bubble-mutations.json` and
`%TEMP%\workspace-bubble-card-mutations.json`.

The later voice-only bubble change retires the inline editor and its draft-reset
regression; input is now owned by the existing voice/agent path. Native interaction
checks cover the tooltip, read-only surface, exact option routing and exclusive
expansion.

Four follow-up seeded mutations were detected: removing the voice tooltip,
recreating an editable child, retaining the previously expanded bubble and
exposing an individual submit button for a multi-select question. All baselines
passed, with no survivors, timeouts or collection errors. Reports are in Temp as
`workspace-bubble-voice-mutations.json`, `workspace-bubble-expansion-mutations.json`
and `workspace-bubble-options-mutations.json`.
