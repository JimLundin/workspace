# UI pause inventory, 2026-10-28

Several distinct operations can delay the assistant's shared Qt event loop.
The feed-index fix removes one multi-second cause; it does not remove toolbar
geometry, long-reply processing or first-use surface costs. The next two
priorities are toolbar composition and long-reply formatting/allocation.

The subsequent [fixed-event delay ledger](workspace-ui-delay-ledger.md) tracks
each reduction against the same six workloads and 108 delivered updates. It
retains unsuccessful intermediate changes and outliers. The table below is the
initial inventory; the ledger holds current measurements and remaining work.

## What a pause means

The assistant's windows, input delivery, waveform display and animation timers
share one Qt thread. Synchronous work there delays all of them. That can look
like a rendering failure even when the expensive operation is Python source
projection, Markdown formatting, native window positioning or garbage collection.
These measurements do not demonstrate a GPU or Windows compositor defect.

The probe measures delivery of an unrelated precise 10 ms Qt timer. A reported
200 ms gap means it went about 190 ms longer than requested without running.
It is direct evidence of delayed event delivery, not a count of painted frames.
An action's duration is measured separately: Workspace sometimes calls
`processEvents()` during that action, allowing timers to run before it returns.
Do not add action durations, timer gaps and nested profile times together.

50 ms is a diagnostic threshold for obvious stalls. Staying below it does not
establish smooth 60 Hz rendering, which needs roughly 16.7 ms per frame. Idle
time between paint callbacks is not itself a stall; previous `paint_max_ms`
records must not be read that way.

## Prioritized inventory

Times below are unprofiled native Windows observations with GC enabled.
Repeated workloads have three runs; single-run controls are identified.
They establish repeatable triggers, not how often each happens in live use.

| Priority / status | Trigger | Observed delay | Attribution and next action |
| --- | --- | --- | --- |
| Fixed here | Refresh 100 updates, 300 retained handling records and 20 proposals | Pure projection **2,847.51 → 9.05 ms**; old warmed Qt gap **2,993.94 ms** | Repeated evidence/origin indexing and fingerprinting. One immutable index per projection, reused across consumers. Retain regression and native refresh check. |
| P1 | Recording capsule starts/stops while keyboard layout visibility changes | Fresh repeated maxima **193–223 ms**, plus one **1,394.58 ms** outlier; earlier combined-state run **489.17 ms** | Repeated glass synchronization/path creation during intermediate layout states. Profile built **96 composition paths for 14 trigger deliveries**, repeatedly constructing COM callback bindings. Coalesce final size/join/position changes; retain native path adapters/resources where their contracts allow. Attribute the larger outlier separately. |
| P1 | Keyboard mode capsule appears/disappears | Three maxima **74.26, 109.82, 191.03 ms** | Same geometry path; profile built **70 paths for 15 deliveries**. Include this trigger in the toolbar change, alongside recording and unchanged-frame cases. |
| P1 | A formatted reply grows to approximately 27 KB | Three maxima **208.29, 255.47, 408.79 ms** | Full-reply Markdown formatting and Qt text measurement grow with content. Profiles locate repeated `notification_text.spans`, `rich_text.formatted`, `Measure.prepare` and `Document.load`. Preserve and share a prepared immutable projection; avoid reparsing unchanged content during measurement and rendering. |
| P1 contributor | Garbage collection during that long-reply workload | Largest collections **99.42, 105.64, 154.71 ms** | Two repeats identify generation 2 collecting **24,434 objects**. This contributes to the reply gap, rather than representing an additional independent delay. Trace allocation/retention to its owner and reduce churn; keep GC enabled. This does not yet identify which objects caused the collection. |
| P2 | Entire feed conversation/sample state is replaced | Three maxima **99.40, 165.66, 215.75 ms**; actions themselves reach **456 ms** | Retained native surfaces prevent repeated full construction, but replacement still prepares text and updates windows. Profiling finds repeated native movement/reveal and layout/recolor work. Update only changed content/geometry and reuse prepared text; verify clearing, selection, scrolling and ownership. The sample switch also writes a tiny preview state file, so it is a scenario reproduction rather than a pure rendering benchmark. |
| P2 | Tool outcomes and reply content arrive together | One run: maximum **80.83 ms**, four gaps above 50 ms | Profile shows **126 tool recolors and 65 step placements for 15 deliveries**, alongside native window work. Inspect repeated `present`/`place`/`recolor` decisions and preserve unchanged elements. Keep copy targets, rich results and scroll behavior. |
| P2 | First presentation of the large feed fixture | New runs include **190.78–375.33 ms** gaps; earlier final implementation **490.96 ms** | First content/surface preparation remains after projection is cheap. Separate new-card, first text layout and glass costs; retain a bounded surface pool and consider preparation before visible interaction. This is different from the warmed refresh. |
| Fixed in rebased source | Replacing bubbles used to recreate all native resources | Earlier waveform gap **3.51 s**; retained-pool warmed Qt gap **47.1 ms**, initial waveform gap **311.8 ms** | Existing surface-retention work fixes repeated allocation and starts motion after preparation. Preserve it; residual replacement and first-use rows above describe what remains. See [bubble resource lifetime](bubble-resource-lifetime.md). |
| Fixed in rebased source | Toolbar timer read the microphone driver directly | Historical native level read **160.46 ms**; cached UI read maximum **0.100 ms** in later paired capture | Existing `AudioMeter` moves native reading to its worker. A blocked driver may delay sample freshness while UI event delivery continues. Real capture was not started by the new preview inventory. See [voice diagnostics](voice-diagnostics.md). |
| Control | Voice state alone changes between listening and ready | One fresh run maximum **36.38 ms**, no gap above 50 ms; earlier **45.86 ms** | Some frame cost remains; it did not reproduce the large stalls. Preserve the lightweight waveform path while changing toolbar composition. |
| Control | Inbox badge changes between hidden, 1, 12 and 99+ | One run maximum **32.40 ms**, no gap above 50 ms | Ordinary badge updates did not reproduce the large delays. Measure under combined source arrivals after the toolbar change. |
| Control | Small formatted reply streams | One run maximum **37.16 ms**, no gap above 50 ms; earlier **42.70 ms** | Small replies do not represent long-reply behavior. Keep both sizes in the performance workload. |
| Control | History/current-feed selection toggles on the small fixture | One run maximum **13.10 ms**, no gap above 50 ms | This fixture does not cover a large populated history or pagination. Extend that input before treating history as cleared. |
| Control | Toolbar and feed idle for 20 seconds | Maximum **16.69 ms**, no gap above 50 ms | Covers repeated material checks and the 15-second power poll with live shell/services disabled. It does not reproduce an unconditional idle Qt stall. |
| Separate latency | Construct a fresh isolated preview | Unprofiled constructors approximately **2.49–10.62 s**, plus module import time | Measured before the timer/event loop starts; not a recurring pause in an already-running application. Native creation and lazy imports are included. Profile startup and first opening separately; do not present these numbers as production startup duration. |
| Separate latency | Release dictation and wait for transcript | Historical endpoint requests **1.24–3.40 s**, excluding queue delay | Network/transcription latency, not evidence of Qt blocking. Capture/start/input-delivery delays have separate ownership and evidence in voice diagnostics. |

## Evidence and limitations

The retained [measurement data](qt-ui-pause-timings.json) contains each valid
run's timer percentiles, counts, action times, GC observations and separate
profile summaries. All content was fictional. The profile adds substantial
overhead, so its durations are used to locate work and its call counts to expose
repetition; its 286–575 ms timer gaps are not ordinary-runtime timings. Nested
event pumping and background/native operations complicate cumulative attribution.
The pinned Python 3.15 cProfile also records worker-thread activity. Its
cumulative durations include background queue/pixel waits and cannot be assigned
to Qt callbacks. Counts and source paths identify repeated work, but even these
must be interpreted with their actual thread ownership. Background pixel
sampling still runs on its worker. The later ledger uses explicitly
thread-filtered Qt/native tracing separately from unprofiled measurements.

The 1,394.58 ms capsule-run outlier exceeds its usual action costs. It is retained
as an **unattributed delay**: the current evidence cannot apportion it between
native work, OS scheduling and other work on the shared desktop. Repeating the
same workload usually produces much smaller maxima. Capture a native timeline
around that outlier before changing the design to address it.

The 10 ms timer does not measure physical display presentation, precise input
latency, or waveform sample freshness. The preview starts no microphone, native
keyboard hook, taskbar recovery, live Teams collector or model requests. Its
heartbeat demonstrates shared event-loop blocking in these real views; it does
not establish the production frequency of each trigger.

## Remaining inventory work

No finite preview run inventories every possible pause. The next live trace
should correlate content-free trigger labels, Qt callback spans, input/event
delivery, GC generations and native thread stacks. Keep sampling/profiling
separate from the uninstrumented timing baseline.

In particular, these paths still need measurements:

- Live communications/native-notice arrival through `Ui.observe_triage`, inbox
  counting and rendering together. `Triage.observe` collects sources while
  holding its lock; persistence/model-result publication also uses that lock.
  Lock contention is a source-evidenced candidate, not a measured pause here.
- UI job bursts: `_poll` allows up to 64 jobs per tick without a time budget.
  Measure queue age and callback duration before deciding whether to batch or
  limit work. Preview delivery is coalesced but uses its own queue owner.
- Large history/pagination, card expansion/collapse, scroll/copy selection,
  multi-monitor movement and DPI/material changes.
- Real capture-start, long native audio reads, worker/GIL contention and
  freshness of the waveform's latest sample.
- First opening of work/meeting views, late SDK imports, and shutdown/reload.
  The test-speed investigation's SDK-after-Qt import-hook cost is a separate
  first-use candidate; it is not proven to cause these repeated preview stalls.
- Display/DWM/GPU presentation stalls if the UI timer and input remain responsive
  while the screen stops updating. That requires native presentation evidence.

## Execution order and acceptance

1. **Toolbar geometry:** reproduce recording and keyboard changes through regular
   inputs. Reduce duplicate final-state/native binding work. Require a warmed
   timer budget below 50 ms over several runs, then inspect frame intervals;
   test joined contours, hit targets, final geometry and native resource cleanup.
2. **Long replies:** run small and 27 KB streaming fixtures. Share prepared
   spans/layout inputs, measure allocations separately, and inspect GC survivors
   and references. Preserve full text, UTF-16 selection, wrapping and scroll
   position. Use the same warmed budget and keep GC enabled.
3. **Replacement/tool updates and first use:** use the existing retained pool,
   avoid unchanged layout/recolor/window operations, and measure first use
   separately. Keep meaningful native interaction/lifecycle coverage.
4. **Live correlation:** explain the outlier and measure the remaining paths
   above before promising that all periodic stalls are gone.

## Reproduce and integrate

The disposable probe is
`%TEMP%\workspace-qt-stalls-probes\pause_inventory.py`. From this worktree:

```powershell
.\.venv\Scripts\python.exe "$env:TEMP\workspace-qt-stalls-probes\pause_inventory.py" capsules --output "$env:TEMP\workspace-capsules.json"
.\.venv\Scripts\python.exe "$env:TEMP\workspace-qt-stalls-probes\pause_inventory.py" long-stream --output "$env:TEMP\workspace-long-reply.json"
.\.venv\Scripts\python.exe "$env:TEMP\workspace-qt-stalls-probes\pause_inventory.py" capsules --profile --output "$env:TEMP\workspace-capsules-profile.json"
```

Each run uses production constructors and public actions, a 1.5-second settle
period and an eight-second measurement. Triggers run approximately every 500 ms.
Run desktop workloads sequentially. `idle --duration 20` covers several material
polls and the 15-second power poll, with native shell/services disabled. Use
`voice`, `keyboard`, `badge`, `stream`, `tools`, `reset`, `projection` and `history`
for the other scenarios. Invalid early streaming probe runs were discarded and
replaced by successful runs; they are absent from the retained data.

The original feed fix was rebased onto private snapshot `1a1cafe` of the other
agent's current test-speed work. Those 11 changed files include deterministic
feed debounce tests, shared feed fixtures, fictional Outlook command handling
and their timing reports. The shared source and index were not changed. The
integration additionally replaces the feed fixture's patches with explicit
cancellable-wait and server-construction dependencies; production timing stays
the same. Apply the final fix commit only, not the private snapshot commits.
Recheck the receiving checkout's combined source before coordinated deployment.

## Integration validation

The rebased source passed **72 affected tests** covering projection, notification
policy, handling, triage/date scheduling and native feed/bubble lifetime. Strict
Pyright reports zero errors and warnings for the four changed runtime modules;
Ruff passes for changed runtime and test files. The pure bounded projection
reproduction still passes, with median **9.29 ms** on the rebased source.

Two additional seeded mutations were detected by the shutdown regression:
ignoring the supplied debounce dependency, and ignoring its cancellation result.
Both passed baseline execution and had no survivors, timeouts or errors. The
original four projection/handling decision mutations remain documented in the
[feed investigation](qt-ui-stalls.md).

This integration uses an affected source/native scope. It does not claim a new
passing full suite; the previous full run's baseline/intermittent browser failures
remain recorded in the feed report. Final source binding uses Windows Temp receipt
`workspace-qt-stalls-rebased-check.json`. The subsequent rebase uses fresh
test-speed snapshot `f067107`, containing thirteen newer test-speed files and
portable-worker overlap. Both fix commits replayed cleanly; no application
runtime files changed through that rebase. The user then authorized local-main
integration. Downloads deployment remains with the coordinating agent's
combined-source check and deployment.
