# Native animation performance, 2026-11-01

Incoming observations no longer postpone animation frames. The fix covers the
shared Qt loop, toolbar transitions and indicators, card movement, text reveals,
spinners and automatic reading. Expensive reply preparation and repeated native
text reflow were separate contributors to whole-UI stalls.

## Ownership and confirmed causes

Durable model/tool work already runs in the supervised automation process. Its
desktop frontend and microphone reader run on background threads in the
assistant process. Qt owns every native window on that process's main thread.
Background threads still share its Python heap, GIL and garbage collector.

`EventLoop.watch` formerly restarted an active frame timer on every observation.
Updates arriving faster than its interval could prevent the timer from firing.
Cards also replaced their timer and closure every tick, pumped nested Qt events
and ran a separate continuous glass timer. Precise reusable timers now preserve
active deadlines, publish glass once per card tick and stop when idle. Timer
resolution covers continuous indicators as well as geometric motion.

`Ui.drain` formerly ran up to 64 jobs without an elapsed budget. It now yields
after 4 ms and prevents nested event pumping from entering the next queued job
before the current job completes. Individual jobs still run to completion.

Cards shared one scratch measurement document. Measuring a different card
discarded prepared paragraphs. Each bounded pooled card now owns its documents.
At 125% scaling, preparation and viewport fitting alternated between 294 and
293.6 logical pixels, forcing full reflow repeatedly. The shared text adapter
now uses the whole logical pixels that Qt's QWidget viewports actually provide.

The work observer prepares accepted answer/reasoning prose and durable completion
text before publishing it. Stream parsing also runs outside the frontend lock;
the captured publisher remains fenced to its session generation. Views reuse
immutable spans through the standard
library's cache, bounded to eight bodies. Markdown-it owns parsing; Workspace
owns its rendering adapter. The adapter only traverses descendants, so it drops
temporary parent links to release parser trees without accumulating cycles.
Native text documents stay on Qt. Disabling QTextDocument layout around each
edit was measured and rejected: reenabling it increased full-document reflow.

The waveform interpolates real observations between its 50 ms samples using the
precise frame loop. Indicator frames skip identical layout/glass publication.
Reduced motion retains direct sample display and stationary spinners.
Expanded menus also keep their working spinner on that loop after geometry
settles, invalidating only its 18-pixel glyph region. Previously the owner only
examined compact slots and stopped the expanded row's animation entirely.

A separate first-open failure briefly reported active, inactive, then active
within milliseconds. Immediate dismissal closed the menu before the scheduled
retraction, producing a misleading one-frame result. A UI-owned precise timer
now checks inactivity after 16 ms; regained activation cancels it. The native
regression checks both first opening and dismissal after a real focus transfer.

## Native evidence and limits

Fresh native Windows Python 3.15.1 / Qt 6.12 processes used fictional content,
production views and public observer/publication interfaces, with GC enabled.
Work streaming used the real WorkAgent observer, concrete local transport and
real temporary journals. Each workload delivered 18 updates. The reply grew to
approximately 27 KB. Measurements ran sequentially on the shared Windows machine.
An unrelated precise 10 ms timer measures event delivery, not physical display FPS.

| Workload | Before maximum gap | After maximum gap | Before / after p95 gap |
| --- | ---: | ---: | ---: |
| Work observer streaming a formatted reply | 501.75 ms | 150.01 ms | 146.51 / 21.60 ms |
| Tool results and reply updates together | 182.04 ms | 125.32 ms | 48.80 / 41.67 ms |
| Conversation/history mode changes | 183.94 ms | 118.02 ms | 15.19 / 17.20 ms |
| All eight preview states, including concurrent activities | 159.76 ms | 125.21 ms | 25.77 / 40.96 ms |

The longest Qt render callback in the final work-observer replay fell from
510.47 to 67.49 ms. Candidate repeats ranged from 46.39 to 144.77 ms, including
a collection during the latter.
The baseline's largest generation-2 collection took 146.81 ms and collected
12,064 objects; the final replay took 110.61 ms and collected none. Removing
parser cycles reduces retained garbage, but whole-heap scans can still suspend
Qt. Background preparation alone cannot eliminate that process-wide pause.

The preview replacement result is mixed: its repeated candidate runs had p95
gaps of 45.76 and 40.96 ms, versus 25.77 ms in the baseline. Continuous indicators
now run their frame loops, and desktop load varies. These results establish no
universal improvement for every event or a guaranteed 16 ms budget. First-use
native construction and canvas SQLite operations remain synchronous on Qt.

The toolbar replay additionally ran on the standard private test desktop to
separate native activation from user input. After the activation fix, all eight
expansion/retraction intervals showed 15–25 distinct heights, median frame
delivery was 16.04 ms, p95 was 20.78 ms and the maximum meter gap was 76.24 ms.
Its transition, meter-gap and median-cadence assertions passed. Earlier first
openings closed prematurely; those failed records remain retained.

## Reproduction and regression scope

Task probes and JSON evidence live in Windows Temp under
`workspace-ui-perf-probes`, with `workspace-ui-baseline-fast` containing the
unchanged starting production source from `ae18c2e8`. `work_bubbles.py` takes
source-root and output-path arguments; `general_motion.py` additionally takes
`replacement`, `tools` or `history`. `menu_focus.py` accepts `--output` and
`--check-cadence` and uses the standard isolated native desktop.

Native regressions exercise timer delivery under rapid observations, idle
resource ownership, per-card document retention, fractional-scale fitting,
waveform interpolation without redundant glass writes, queue fairness/FIFO and
first-open activation. The expanded-menu test observes native paint delivery as
well as changed pixels, so a forced screenshot cannot conceal missing updates.
The real-journal work test verifies that accepted streams
and durable results are prepared before the view consumes them. Python, Qt and
Markdown-it algorithms remain trusted; these cases test Workspace's wiring and
ownership decisions. Focused mutation reports use the `workspace-ui-*-mutations`
prefix in Windows Temp.

The native canvas/attention fixture waits across bounded queue turns before
asserting fully delivered publications. Its former single-drain assumption
produced four failures after queue fairness changed; all four passed against
the unchanged starting source and with the revised fixture. Their attention,
reply-routing and persistence assertions remain intact.

All thirteen focused seeded mutations were detected, with passing baselines and
no survivors, timeouts or errors. They cover frame deadlines, queue fairness and
serial execution, text width, background preparation, waveform continuity,
activation settling and native spinner repaint delivery. A stale expanded-title
assertion was also corrected to the existing one-line elision behavior; it failed
on the unchanged starting source before this performance work.
