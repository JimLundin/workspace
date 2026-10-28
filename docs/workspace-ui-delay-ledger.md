# Workspace UI delay reductions, 2026-10-28

The first step reduces repeated toolbar/native work. It does **not** establish
that the toolbar is consistently below the 50 ms diagnostic budget, or that
total UI delay falls in every run. The final catalog is worse than the first
toolbar candidate, principally during long replies and conversation replacement.
Those results remain in the ledger.

## What the total measures

The [machine-readable ledger](workspace-ui-delay-ledger.json) retains each run,
source hashes, complete catalogs and trace identities. Its total is
`sum(max(0, heartbeat_gap_ms - 50))` across six real Qt workloads, each with
exactly 18 public-action deliveries: **108 updates per catalog**. GC stays enabled.

This is accumulated excess over a diagnostic threshold, not total time spent
rendering or total unavailable time in live use. A precise, unrelated 10 ms timer
records event delivery. Gaps below 50 ms contribute zero; exceeding the threshold
does not identify the blocking operation by itself. Action durations, GC spans
and callback durations overlap these gaps and must not be added to the total.

Each fresh process settles for 1.5 seconds. The next update is scheduled 500 ms
after the previous action returns; observation ends 500 ms after the last action
returns. Construction/import costs precede measurement. "Warm" starts after the
second delivered action plus 100 ms; a later shape can still be first-use.

## Rolling totals

The baseline already contains the earlier **2,847.51 → 9.05 ms** pure projection
fix. That isolated operation has no measured pre-fix complete catalog, so its
reduction is kept separate rather than extrapolated into these totals.

| Source / measurement | Total excess above 50 ms | Warm excess | Observation windows |
| --- | ---: | ---: | --- |
| Baseline after projection fix, round 2 | 16,103.35 ms | 14,957.42 ms | 79.56 s |
| Batched publication + bounded paths + stacking observation, round 2 | 8,941.56 ms | 7,590.93 ms | 73.09 s |
| Fresh baseline control, round 8 | 3,986.93 ms | 3,275.72 ms | 66.06 s |
| Retained geometry + changed dimensions + bound interfaces, round 8 | 2,315.39 ms | 2,070.00 ms | 63.69 s |
| Final source, rounds 11/12 | **10,921.05 ms** | **9,627.18 ms** | 77.58 s |

These are shared-desktop observations, not isolated causal estimates. The same
baseline source varies substantially between rounds. Round 2 alternated source
variants per workload; round 8 ran the candidate catalog first, then baseline in
reverse workload order. The final source repeats the candidate after replacing
two JSON casts with `object` observations and existing validation. Its projection
run raised a Qt callback exception and is excluded; a successful round 12 retry
completes the catalog. The unsuccessful run is retained with its invalid reason.

The recorded sequence is **16.10 → 8.94 → 10.92 seconds**, with the round 8
candidate/control pair retained alongside it. This does not support a claim of
monotonic improvement. Intermediate coalescing/cache experiments and geometry
repeats, including regressions and one-second gaps, are also retained.

## Where delay remains

| Workload | Fresh baseline excess, round 8 | Final excess, rounds 11/12 | Final maximum gap | Next action |
| --- | ---: | ---: | ---: | --- |
| Recording/layout capsules | 1,196.25 ms | 205.41 ms | 130.83 ms | Native movement/show and consecutive Qt callbacks remain; preserve the outlier investigation. |
| Keyboard mode capsule | 237.48 ms | 22.37 ms | 60.33 ms | Same toolbar path; final warm maximum is 57.67 ms. |
| Growing formatted reply, approximately 27 KB | 1,122.87 ms | 4,554.72 ms | 575.38 ms | Share prepared text/layout inputs and investigate allocation lifetime. GC reached 230.86 ms inside this workload. |
| Conversation/sample replacement | 682.03 ms | 4,713.20 ms | 369.97 ms | Separate native movement/reveal and repeated content preparation; retain selection, clearing and surface ownership. |
| Tool result and reply updates together | 625.01 ms | 1,046.40 ms | 125.02 ms | Reduce repeated placement/recolor decisions after measuring them through the same input. |
| Feed/proposal refresh | 123.29 ms | 378.95 ms | 287.19 ms | First presentation remains; warmed maximum is 20.96 ms with zero excess. |

One later adjacent toolbar pair, round 9, measured capsule excess
**1,151.23 → 0 ms** and keyboard excess **1,354.15 → 0 ms**, with candidate
maxima **46.57 and 35.32 ms**. Other final/source-equivalent repeats still exceed
50 ms. A single successful repeat is insufficient to mark toolbar stalls fixed.

The final long-reply run collected **24,434 objects** in generation 2, matching
earlier repeats. This establishes recurring collection pressure; it does not
identify the objects' allocation owner. Allocation/object-lifetime measurement
is the next long-reply investigation, separately from untraced UI timing.

Fresh fixture constructors ranged from roughly 2.7 seconds to **26.45 seconds**
in these later runs. Imports are also recorded separately. Those costs occur
before heartbeat measurement, so they are first-opening/startup candidates rather
than entries added to recurring delay. They are not measured production startup.

## What changed in step one

`Pill` publishes final glass geometry through its Qt-owned, zero-delay single-shot
timer. Multiple join/size changes in one event turn no longer publish intermediate
native contours. Disposal stops pending publication.

Each `Glass` keeps at most eight recent native contour/scale paths in the standard
library's cache, cleared on close. It observes real window ordering before
stacking, retains native geometry and clip identities, and updates dimensions
and shadow parameters only when size/DPI changes. Shape changes still update
the retained path, clip and shadow mask correctly.

Native visual interfaces are bound once for the scene's lifetime. A separate
real-native size-setter benchmark measured median **0.50 → 0.13 ms per update**
through the SDK convenience property versus the regular `IVisual` interface.
That supports the interface choice; it is not a UI-gap reduction estimate.

Published records/identities use frozen, slotted records and tuples. Necessary
native mutation belongs to `Glass` and its UI/dispatcher thread; the cache's
bounded retention and release belong to that same owner. Python/cache mechanics
and native interface contracts are trusted upstream. Tests exercise Workspace's
publication, resource budget, geometry wiring, DPI decisions and cleanup.

All five touched runtime files contain no `Any`, casts or type suppressions.
Focused external SDK stubs preserve concrete consumed contracts. Mypy explicitly
enforces its no-`Any` rules for native composition, paths and toolbar surfaces;
strict Pyright checks the same source using the actual development interpreter.
The existing architecture gate requires frozen/slotted records and detects
concrete mutable collections nested inside their fields, with exact explained
exceptions. It does not claim to prove deep immutability behind opaque native
handles or to forbid every existing local mutable accumulator.

## Residual native timeline and additional failure

A separate, explicitly thread-filtered Qt/native trace, round 10, observed a
**64.70 ms** heartbeat gap while its longest Qt callback was **45.48 ms**. Multiple
movement/show, layout/animation and glass-publication callbacks ran consecutively.
Samples in those intervals locate `Pill.move_frame`, `Glass.position/show` and
native window operations. A gap can span several callbacks, even when each stays
below 50 ms. Nested Qt event spans overlap and must not be summed.

The native sampler observed only its own disposable preview's UI thread. Native
instruction decoding uses the explicit Unicode symbol API. The earlier native
trace's truncated symbol strings are unsuitable for exact function attribution.
Pinned Python 3.15 cProfile also records worker activity: cumulative queue/pixel
waits cannot be assigned to Qt. All tracing/profiling is excluded from formal
timing totals.

The roughly **0.86–1.32 second** outliers in intermediate rounds remain
unattributed. In one keyboard run, the gap was **952.29 ms**, while the largest
action was **34.44 ms** and GC reached **1.22 ms**. The successful native trace
did not capture an outlier of this size. It cannot determine whether those gaps
are native blocking, scheduling, worker/GIL contention or another queued callback.

The failed final projection run surfaced an additional correctness defect:
`AgentToasts.observe_pointer` iterates its live card dictionary and calls
`set_hover`, which can call `tick` and pump events. Nested work can change that
dictionary. This is source-supported reentrancy, not a measured explanation of
the one-second outlier. Fix it through a stable observation and explicit effect
ownership, with a real reentrant arrival/retirement regression; do not patch the
callback or hide its exception in the timing harness.

The [original inventory](qt-ui-pause-inventory.md) also retains unmeasured live
queue/lock contention, capture-start, history, multi-monitor/DPI, first-view
imports and presentation-only stalls. No claim that every possible pause has
been measured is supported.

## Validation and handoff

Four native regressions exercise final-state batching, bounded path retention
and release, actual stacking repair, and retained clip/path/shadow wiring across
contour, rounded and DPI changes. They use real Qt/Windows resources and regular
constructor dependencies. No new test mocks or patches are introduced.

Focused mutations cover bypassed batching, disabled cache, omitted release,
unconditional/stale stacking, omitted path/clip/mask updates and skipped resize
publication. All **nine mutations were detected**, with passing four-test
baselines and no survivors, timeouts or errors. Reports live in Windows Temp
under `workspace-qt-stalls-probes/workspace-toolbar-{batching,native}-mutations.json`;
their source/snapshot identities and individual results are retained in the JSON
ledger. Native checks and workloads run sequentially.

Affected validation passed **66 tests**, selecting notification/projection, triage validation,
toolbar state, the four new native regressions, native feed rendering and selected
native material/DPI/transitional-frame/shutdown checks. Its receipt is
`%TEMP%\workspace-toolbar-affected-check.json`. A final four-test native check
binds the source after converting the small test observation buffers to immutable
tuples; its receipt is `%TEMP%\workspace-toolbar-final-check.json`. This is an affected scope, with
the protected full selfcheck and CI gates unchanged.

This remains in `workspace-qt-stalls`, based on test-speed snapshot `1a1cafe`.
The coordinating agent owns combined-source integration, checking and Downloads
deployment. Apply the actual fix commits, preserve the source-snapshot commits
as investigation history, and issue a new receipt for the receiving checkout.
