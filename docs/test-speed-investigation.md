# Why the full Windows suite became slow

The [current browser lifetime structure](browser-test-lifetimes.md) removes four
more Edge launches and records the complete 7m 45s native cost budget. The
observations below retain their original source snapshots and timing limits.

## Retained six-minute full result and Teams fixture consolidation

The completed worker-overlap report mentioned below actually records
**359.686 seconds (6m 0s), 1109 passed, zero failed and five skips**.
This is a retained earlier snapshot, not a new full run after the current edits.
Its browser family consumed **88.418 seconds (24.6%)**. Broad production imports
consumed 10.090s, compilation 3.685s, and the two properties with their imports
5.227s (1.45%). The remaining cost is primarily real native fixtures and process,
HTTP and storage work; trimming tiny pure checks cannot remove minutes.

Four compatible Teams/activity browser scenarios now share one explicitly owned
disposable Edge process and localhost server. Each scenario loads a fresh real
document and constructs a new `TeamsWeb` owner. All **43 assertions** remain,
including identity/date evidence, idempotent activity handling, exact replies,
draft protection, stale routing, frozen-page recovery and launcher destinations.
The native activation assertion only accepts commands emitted by its current
call, and its extra native tab is closed before the next scenario. Independent
browser persistence, cancellation and attach/detach lifetimes remain in their
existing tests. Helper tracebacks identify the failing scenario; the executor
now counts this fixture as one test function, so pass counts are not coverage.

Sequential native observations from the same checkout:

| Variant | Bodies and fixtures | Editing command | Result |
| --- | ---: | ---: | --- |
| Original four lifecycles | 55.052s | 79.333s | Four functions passed |
| Shared lifecycle | 28.749s | 41.099s | All scenarios passed |
| Original repeated after sharing | 62.298s | Executor only: 62.787s | Four functions passed |

The first body comparison improved **47.8%**. Policy costs were also warmer in
the second command, so its entire 38.234s reduction cannot be attributed to
fixture sharing. The repeated original ran its unchanged source through the
same executor in a fresh native interpreter with an explicit source loader;
no imported functions or module globals were replaced. Removing
`open_activity`'s native activation in a disposable mutation copy was detected:
one mutation killed, zero survivors/timeouts/errors, with a passing baseline.

Detailed observations are in [test-speed-timings.json](test-speed-timings.json),
`communications_fixture_consolidation`. Raw reports and the repeated-original
harness live in Windows Temp `workspace-test-cost-probes/`; final source-bound
verification has a separate report. These workstation observations have variable
filesystem caches and do not predict a new full-suite total.

For iteration, use `Dev.cmd check` or `Dev.cmd watch` to select affected tests;
use `--tests` for a narrow contract while editing. Reserve full native runs for
broad changes and CI. The next largest retained costs are the runtime subprocess
family (39.437s) and UI Automation/computer fixtures (33.720s). Profile their
startup and native calls before changing their required isolation or assertions.

## Portable workers and the remaining browser cost

The next authoritative full baseline was **576.819 seconds (9m 37s)**:
1109 passed, zero failed and six reported skips. The previous changes saved
27.849 seconds overall; bodies and fixtures still consumed 545.218 seconds.
The two properties including their module imports took 15.332 seconds. The
browser family took 169.718 seconds. These timings rule out property generation
and tiny test functions as the main remaining bottleneck.

A paired native benchmark ran the same 152 functions from nine reviewed
modules through the unchanged test executor. One standard library process
worker took **123.493 seconds**, two took **60.860 seconds**, including worker
startup, SDK imports, real fixtures and shutdown; both had zero failures/skips.
The editing runner now overlaps those two workers with its sequential native
lane during broad native checks. The explicit module inventory in `check.py`
owns this decision; filenames do not automatically authorize concurrent effects.
Narrow checks avoid startup. Properties, full imports, final hashes, failure
aggregation and success-only receipts remain. Worker spans have a `worker:`
prefix and are excluded from nonoverlapping elapsed accounting. This benchmark
is not a predicted new full-suite total.

The next browser probe ran the actual recovery case and three native tab cases
against disposable profiles and fictional localhost pages. Its 90.876 seconds
included 56.252 seconds in 15 `browser_open` requests and 12.411 seconds in
browser close calls. Nested spans must not be summed. Recovery polling was
smaller than repeated CDP frame/context requests. The three compatible native
tab scenarios now share one lifecycle and explicitly restore their created
tabs between scenarios; all disconnect, grouping, identical-URL, cross-window,
activation and reload assertions remain. The first changed probe passed every
behavioral assertion but reported a native process-exit timeout during cleanup;
that failure remains visible and requires the final native run to pass.

Reproduction and raw observations are in Windows Temp
`workspace-test-cost-probes/portable_workers_probe.py`, `portable-workers-1.json`,
`portable-workers-2.json`, `browser_next_probe.py` and `browser-next-*.json`.
The completed full result is retained separately as
`workspace-native-portable-overlap-final.timings.json` and its success receipt.

## Latest full measurement and four ordered changes

The last complete run, before these four changes, took **604.668 seconds
(10m 5s)**: 1115 passed, one failed and six reported skips. The earlier native
run took 1143.67 seconds (19m 4s). This is an observed 47.1% reduction across
snapshots, not a controlled benchmark. The failed localhost Teams fixture is
fixed below; its single-tab reuse remains in production.

That snapshot had **1124 actual test functions in 122 modules**: 1122 ordinary
scenarios and two Hypothesis properties, configured for at most 100 examples
each. Runner passes count functions, not generated examples. Five opt-in E2E
functions were omitted through three module skips; three further functions
skipped. The properties plus their module imports took **8.641 seconds (1.43%)**.
They do not explain the ten-minute suite.

Complete attribution: test bodies/fixtures 540.240s (native 307.284s,
portable/property 232.956s), broad production imports 53.423s, compilation
5.652s, test-module imports 2.604s, remaining policy/manifests about 2.6s.
Only 109 functions taking at least one second consumed 416.599s; 692 functions
below 0.1s consumed 12.412s. The browser family consumed 153.145s and the
largest UI Automation case 37.946s.

The ordered investigation produced these changes:

| Area | Change and evidence |
| --- | --- |
| Browser | Removed five duplicate lifecycles: pagination shares the DOM/persistence browser; inactive screenshots share the attached-session browser; four navigation recoveries reload one explicitly owned localhost target. Recovery bodies observed 39.970s → 20.336s. All 15 browser/group cases passed. The before group had a late profile cleanup failure; warmed unchanged cases also improved, so this is not an isolated causal delta. |
| Imports | Broad editing checks now resolve the required SDK graph after properties and before the unchanged full import gate. Qt classifications fell 1437 → 286. Existing/SDK-first/existing fresh-process profiles took 63.599s / 17.897s / 18.394s; Qt source inspection took 43.621s / 0.279s / 1.401s. This removes cold-source-read exposure; warmed savings were only 0.497s. Narrow and Qt-only checks do not preload SDK. |
| UI Automation | Replaced 10,000 WPF lines with 12,001 quotes, retaining short multiline/UTF-8 input and both truncation boundaries. Whole scenario observed 39.989s → 19.250s, including warmer unaffected operations. Same fixture, same provider, one batch: old/new/old SetValue took 4.078s / 0.183s / 1.773s. Real IDs, 15 actions, password protection, failures, pagination and independent readback remain. |
| Publishing/storage | Two irrelevant action catalogs now use verified template rows: 410 catalog commits → eight, keeping the earlier unresolved outcomes on real public writes. The same two pagination bodies took 4.484s → 0.368s. Publication refusal bodies share one reset local repository: 9.077s → 5.704s; six baseline repositories → four. Real Git, candidate execution, durable ordering and remote readback remain. All 44 affected publication/store/action cases passed. |

The current inventory is **1117 functions in the same 122 modules**: 1115
ordinary scenarios plus two properties. Seven former functions were consolidated;
their assertions remain. No new complete suite was run after these changes and
no new full-suite total is claimed. Before/after whole scoped totals often select
different modules; compare their named bodies and the mechanism evidence.

All browser probes use disposable Edge profiles and localhost fictional pages.
They never navigate the user's signed-in browser or open real Teams tabs. The
localhost Teams fixture supplies Teams-looking metadata only at its connection
boundary. Explicit profile disposal uses the existing bounded native-release
retry, and persistent failures remain visible. The protected selfcheck/full CI
gates and runtime pins were not changed for these optimizations.

Detailed reports and exact selected scopes are retained in
[test-speed-timings.json](test-speed-timings.json). Reproduction/complete raw
profiles remain under Windows Temp `workspace-test-cost-probes/`, including
`import_order_comparison.py`, `profile_uia_after.py` and
`uia_value_comparison.py`. The last full report is
`workspace-full-after-overhead.timings.json` in Windows Temp. These measurements
include setup/cleanup, run sequentially on one workstation, and have varying
filesystem caches. Nested/cumulative profiler spans must not be added.

## Earlier investigation

Investigated on 2026-10-28 against the active checkout, recorded full-test history,
exact Qt/PySide6 6.12.0 upstream source, and the coordinating agent's completed
native probes. Bounded diagnostic cohorts ran sequentially after the coordinated
deployment; none launched Edge or the full suite. Historical/static inventories
and individual runs refer to different snapshots and are not a controlled benchmark.

**At this earlier point, about 910 seconds of the 1143.67-second run were unaccounted for.** Only
its five slowest body timings were retained: 234.102 seconds, or 20.5% of the total.
There is a context-sensitive SDK/Qt import cost and substantial test growth.
Current portable cohorts and warmed import-gate repeats are much faster than the
full run; they do not establish where all nineteen minutes went. Full timing retention is the
first requirement for a responsible whole-suite fix; it is now implemented for
editing runs that reach execution. [1–4]

## Applied overhead reductions

The blanket runtime audit in `tests/test_slots.py` was removed. It imported every
production module and used `inspect.getmembers` plus `__dictoffset__` to inspect
instance storage. This was unnecessary runtime work for declarations: the
required frozen/slotted data-record rule is already enforced from source by
`scripts/architecture.py`. No replacement test of Python's storage behavior was
added. Existing architecture tests cover the checker accepting/rejecting our
record declarations. [4,20]

A complete portable inventory finished 717 tests before its 180-second budget;
its remaining 191 functions then passed in a fresh process. The runtime slots
audit took 67.085s in that remainder. After deleting it, the identical other
190 behavioral cases passed in **44.911s**, versus **131.598s** for the cohort
with the audit. Removing eager runtime inspection also avoids its loaded-module
side effects; these are individual observations with filesystem/cache variation,
not a measured full-suite saving. The two initial inventory segments account for
908 unique completed functions, but their durations must not be combined as a
single-process suite benchmark. [20]

The next measured cost was repeated interpreter startup in the fictional Outlook
command fixture. Ordinary cases now call the handler directly with copied JSON
requests and real response files. The same handler remains executable in a child
process, used by the existing complete-body/durable-mailbox-boundary scenario.
All original assertions and modes remain: lost acknowledgment, wrong mailbox,
recipient/body corruption, edits/deletion, duplicate identities, and cancellation
while another owner holds the draft lock. No live Outlook or Teams is involved.
The Windows binding-sharing case and meeting workflows use the same fixture.
[20,21]

The same **17 Outlook cases** passed with body time **27.483s → 7.530s**. The
post-change editing command was 29.219s including preflight; its command total
is not directly comparable to the earlier body-only measurement. These changes
remove actual fixture work without reducing the behavioral assertions. A new
full native suite has not been run, so the nineteen-minute total is not claimed
to be fixed. [20]

Five feed-triage/date cases were measured before and after replacing elapsed
wall-clock debounce waits with explicitly released steps in the test fixture.
Their same-name body total fell **16.080s → 1.869s**; all 20 feed/date cases passed
after the change. The real worker, locks, authenticated HTTP requests and response
files remain. The coalescing case now also rejects a model call before the test
releases the debounce. The new-day case retains the real one-second periodic
wake path, so refresh cannot silently depend on another notification. Fixture
server shutdown polls at 20ms instead of the standard half second. The integrated
fixture supplies HTTP construction and cancellable waiting through `Triage`'s
explicit dependencies. Production retains its original delay and server behavior;
the fixture uses no patching. [22]

That 20-case run exposed **20.067s** in the first SDK-using feed-tool case. The
case now uses the existing registered-tool fixture, retaining real bridge reads,
feedback persistence, catalog membership and journal redaction assertions. SDK
conversation routing still has its ordinary scenarios in `tests/test_agent.py`.
Removing SDK startup from this focused scope improves its edit loop; the full
suite must still initialize the SDK for its own integration cases. [22]

With that tool-boundary change, the same 20 cases passed with summed bodies
**23.598s → 4.567s** and command totals **36.193s → 14.397s**. The feed-tool body
was 0.331s. Workstation/cache variation affects command totals, so these are
scoped observations. A bounded probe confirmed the changed case fails when a
feed catalog entry is removed and when its dispatch points to the time handler.
The probe changed only in-memory observations and left checkout source intact.
Its script is retained in Windows Temp `workspace-test-cost-probes/feed_boundary_probe.py`.
The measured report is `workspace-feed-overhead-local-tools.timings.json`; the
final receipt check has its own complete report. [22]

## What the evidence actually shows

| Observation | Scope | Result |
| --- | --- | --- |
| Older successful full native run | Historical source digest in `testing-timings.json` | 544 executed tests: 433 portable, 111 native; 120.424s total, 115.954s summed bodies. |
| Dependency refactor, Oct 22/23 | Another historical snapshot | 586 passed, 3 modules skipped, 132.840s. |
| Durable-work release, Oct 23 | Another snapshot, including since-retired UI | 794 passed, 3 modules skipped, 419.657s. |
| Latest broad native run, Oct 28 | Coordinator's completed result; complete timings not saved | 1108 passed, 5 Edge failures, 4 skipped; 1143.67s, 122 selected modules. |
| Current static inventory | Textual top-level `def test_*`; includes opt-in/skipped modules and two generated properties | 1124 functions in 123 modules: 905 portable/property, 219 native in 33 modules. |

Sources: [1–3]. Test bodies roughly doubled while full wall time grew **9.5×**.
Native definitions grew 111→219 and portable/property definitions 433→905.
Comparing exact textual names gives 649 additions and 69 removals/renames; that
is not 649 new independent behavioral contracts. The older 120-second run is
historical evidence, not the current suite's expected duration.

| Latest retained body timing | Seconds | Actual work |
| --- | ---: | --- |
| Generated pending-request property | 86.452 | 100 bounded Hypothesis examples over Workspace transitions. |
| Copied source / inherited SDK + Qt | 58.529 | Source copy, fresh `-S` interpreter, SDK/UI imports and real Qt loop construction. |
| Cross-process UI Automation | 37.174 | PowerShell fixture, control IDs from another process, batched actions and independent readback. |
| Native tab moves/windows/activation/reload | 26.757 | Disposable Edge, another attached browser client, real native-ID/group operations. |
| Identical-URL native tab IDs/grouping/closing | 25.190 | Another disposable Edge lifecycle and native adapter scenario. |

These account for 234.102s; the other **909.568s** include everything not retained,
not merely test bodies. The current runner starts each body timer after the test
module import; broader compile/production-import costs are outside those body
measurements. Its ordinary source receipts omit the detailed timings. [3,4]

The earlier 689.57s and later 1143.67s runs selected the same 122 modules with
different failures/skips. Current architecture took 0.27s, and quality reported
no new blocking warnings. The earlier editing-loop policy-cost investigation
does not explain this nineteen-minute run. [3]

## Current portable costs and a repeat of the actual import gate

These bounded diagnostic cohorts use the real editing executor and preserve all
completed timings. They omit policy preflight, which was measured separately,
and do not load native UI/browser tests. Bodies include their setup and cleanup.
Instrumentation writes content-free spans to Windows Temp. [19]

| Fresh process | Passed | Process total | Summed test bodies | Largest body cost |
| --- | ---: | ---: | ---: | --- |
| Task store, actions, submissions | 54 | 14.823s | 13.503s | Input-capacity/Stop case 3.226s; two pagination cases 2.066s and 2.018s. |
| LLM and fake-desktop features | 55 | 4.973s | 3.896s | Unreachable-endpoint case 2.012s. |
| Agent | 46 | 21.294s | 18.814s | First SDK-using decline case 7.163s, including first-use imports. |
| Architecture, quality, source analysis, selfcheck, workspace, runtime, development | 47 | 22.703s | 20.291s | Uncached current-tree architecture review 4.760s; policy-gate subprocess 2.029s. |

**202 tests passed in 63.793s across four fresh processes.** This is 13 selected
modules, not the whole portable suite or a native full-suite estimate. Many tests
of ordinary decisions run in milliseconds; the larger observed bodies include
real storage, subprocesses, intentional waits and first-use imports. Removing ten
unused feature HTTP servers cannot save minutes when all 55 LLM/feature cases
currently finish in five seconds. [19]

The complete production import gate was also measured without tests, both in its
existing order and with the SDK resolved first. Every module imported successfully:

| Order | First process total | Later repeat total |
| --- | ---: | ---: |
| Existing broad-module order | 20.576s | 11.237s |
| SDK before broad-module imports | 10.345s | 10.064s |

The existing-order SDK import itself fell 10.855s→4.975s on the repeat; SDK-first
imports were 4.486s in the first process. Warm filesystem state and/or workstation
load explain much of the initial difference. The warmed gate difference is only
1.173s in these single repeats, not a demonstrated ten-second order improvement.
No production SDK preload was added on this evidence. The minimal Qt-first probe
below exposes a real source-inspection path, but it is not representative of the
already partially populated broad import graph. Neither gate result explains
~910 seconds of missing full-run attribution. [19]

The earlier 689.57s versus later 1143.67s full-run totals also show substantial
snapshot/environment variation. A future ordinary broad check needs complete
phase and module totals before assigning the remaining cost to native fixtures,
timeouts or machine load. The new diagnostic report makes that possible without
requesting another full run for this investigation. [3,4,19]

## Confirmed import-order cost: SDK behind Qt's feature hook

The coordinator's correctly activated native probes recorded:

| Probe | Wall time | Supporting evidence |
| --- | ---: | --- |
| SDK first: `assistant.sdk` | 9.9355s | 5.0469s CPU; loaded-module count 100→1503, **+1403 modules**. |
| Then Qt | 0.3402s | Import completed. |
| Qt first | 0.5246s | Module count 100→192. |
| Then SDK | Still incomplete when the whole probe reached its 30s timeout | Captured stack in Qt feature source scanning during SDK dependency imports. |

Sources: [5]. The timeout is a lower bound, not a completed SDK duration. These
are uncontrolled single observations, not a statistical benchmark. Earlier
`*-incomplete-runtime.json` probes had missing runtime activation and
`pywintypes` import failures; they are excluded from this comparison.

Exact upstream PySide6 6.12.0 explains the captured stack:

1. Signature initialization loads `shibokensupport.signature.loader` and calls
   `post_init()` after binding its callbacks. [6,7]
2. On CPython, `post_init()` installs
   `builtins.__import__ = builtins.__feature_import__`, preserving the old importer
   as `__orig_import__`. This happens even without any application
   `from __feature__ import ...` statement. [6]
3. C++ `feature_import` delegates ordinary imports to the original importer,
   then calls the Python `feature_imported` callback on successful imports. [7]
4. For modules not already classified, `feature_imported` calls
   `_mod_uses_pyside(module)`, which reads `inspect.getsource(module)` and searches
   the returned source for the literal `PySide6`. It records selection 0 for
   PySide users and -1 for others. A large new SDK import graph therefore incurs
   per-module source inspection after Qt loads. Already classified modules avoid
   this repeated source scan. [8]

The valid Qt-first probe captured
`feature._mod_uses_pyside → inspect.getsource → linecache/tokenize` while importing
SDK dependencies. This is a causal implementation path corroborating the
minimal-probe import-order regression, not proof it consumed all remaining ~910s.
The current warmed broad-gate repeats above show a much smaller difference.

No documented public hook-disable option was found in the exact 6.12.0 Python
feature/loader, C++ signature initialization/callback owners and feature docs:

- `feature.set_selection`/`reset` are described as internal selection controls;
  they do not remove the importer, and initialization itself scans modules. [8]
- Qt's public docs say overriding `builtins.__import__` is **not recommended**.
  Extending `__orig_import__` preserves the feature machinery. A private callback,
  importer or dictionary monkeypatch is not the recommended remedy. [9]
- `PYSIDE6_OPTION_PYTHON_ENUM` changes enum behavior;
  `PYSIDE_DISABLE_INTERNAL_QT_CONF` changes embedded Qt configuration/path setup.
  Neither controls this source-classification callback. [10]

The supported direction is **fully resolve required SDK dependencies before the
first Qt binding import in processes that require both**. Keep that sequencing
at the SDK+Qt execution/bootstrap owner. Do not force SDK imports into a Qt-only
preview or every generic Qt import: that would add the roughly ten-second SDK
baseline where it is unnecessary. Workspace's existing Qt boundary already
resolves `ThreadPoolExecutor` first for a separate Python-3.15 async-worker issue;
preserve it. Product startup/first-use tradeoffs require separate assessment,
since `app.run()` creates `Ui()` before its controller and some work is deferred.
[5,11]

## What bounded probes rule down

| Candidate | Valid native observation | Interpretation |
| --- | --- | --- |
| Source copying | 368 files / 5,927,987 bytes; 2.2919s copy + 0.2903s cleanup | Copying is a small part of the 58.529s copied-SDK body in this observation; inspect the child's imports/Qt lifetime. |
| SQLite setup/read/write | New TaskStore 0.0164s; 100 public writes 1.1041s; 100 reads 0.1816s | Hundreds of fixture writes can be reduced, but current evidence suggests seconds, not fifteen minutes. |
| Test dispatcher + Temp allocation | 200 fast real toolbar-model checks: 2.191s total, 1.49s imports; body/Temp work <0.71s | Unconditional Temp work is avoidable, unlikely the dominant unexplained cost. |
| Local HTTP fixture shutdown | Both fixtures already use `serve_forever(poll_interval=.02)` | 112 fixture sites do not imply 56s of default half-second idle shutdown. |

Sources: [3–5,12]. These probes differ from the full run in state/load and do not
establish exact phase subtraction or linear scaling. They prevent ranking
static fixture counts as though they were measured bottlenecks.

The property was also observed by the coordinator at 1.086s warm / 4.290s cold
in isolation, versus 86.452s in the broad context. Current helper code now runs
generated properties **before** broad SDK/native imports because Hypothesis
inspects loaded-module constants. This is a concrete context-sensitive lead and
a narrowly verified change, not demonstrated whole-suite resolution. Preserve
compile/import coverage and the full gate. [3,4]

## Priorities and concrete consolidation candidates

1. **Retain complete timing and failure evidence before the next broad run.**
   **Implemented:** every editing run that reaches execution writes a diagnostic JSON report,
   including test/import failures. It retains preflight, activation, compile, broad
   production import, changed import, each test-module import, every body and the
   unaccounted remainder. Bodies include setup/cleanup; they are not separately
   attributed internally. Success receipts remain success-only. Process termination
   before the report is written, activation failure and early policy rejection
   remain limitations. The old release receipt's Temp
   Windows selfcheck log is unavailable at its recorded path. No deletion plan
   can responsibly allocate the unknown ~910s from five durations. [2–4]
2. **Keep generated-first execution; treat further prewarming as scoped work.**
   The generated-first change is implemented and narrowly checked. The minimal
   Qt-first/SDK probe explains a real import-hook mechanism, but warmed broad
   repeats do not support a large gate speedup from another preload. Investigate
   cold-import order in the particular copied/native child that is expensive,
   rather than globally loading an unused SDK into UI-only checks. [4–8,11,19]
3. **Consolidate duplicated cold-start fixtures without collapsing distinct
   lifecycle contracts.** Copied-source SDK/Qt inheritance and fresh
   Qt/`asyncio.to_thread` initialization-order assertions can run in one relevant
   copied-source child. Keep controller-first and Qt-first shutdown paths,
   work/UI disposal acknowledgment and pending-request cancellation distinct:
   each detects a different owned failure. [13]
4. **Reduce overlapping native render setup.** Feed collapsed-title,
   crowded-title, production-theme and title-click cases repeat label-size and
   hidden-detail assertions. Consolidate normal/crowded/themed variants under one
   fixture while retaining ellipsis/tooltip/click expansion and style restoration.
   Tool-element identity/status/copy and CLI-visible cases repeat the same
   Running→Failed/retained-invocation path; combine copy-target, literal/font,
   rich-result and placement assertions. Keep wheel/input routing, selection
   retention, glass ownership and retired-surface reuse: pure model tests cannot
   replace those native contracts. This is source-evidenced overlap with an
   unmeasured speed benefit, not demonstrated mutation-equivalent deletion. [14]
5. **Remove unused HTTP fixtures; deepen feature effect boundaries.** At least ten
   feature scenarios start an endpoint yet make no requests: short tap, shutdown,
   incomplete capture, no selection/area/prompt, app focus/launch, window
   arrangement, missing credentials and tiling. Keep their decisions/assertions
   with inert settings. For actual sending feature cases, a focused transcription/
   chat effect adapter can avoid repeating transport setup. Retain representative
   feature wiring and LLM/SDK request-shape, streaming, timeout and failure cases.
   Current static repetition is 112 endpoint call sites in 18 modules; it is an
   ownership improvement, not a proved dominant speed win. [12,15]
6. **Batch irrelevant storage catalog setup.** Store pagination setup creates 105
   later actions with begin+finish (210 separate durable writes); WorkExecution's
   old-unverified-action case creates another 100 (200 writes). Keep both
   important defects: store query/completion fencing versus WorkExecution outcome
   adaptation. Seed only irrelevant later verified actions in one transaction.
   Existing `seed_tasks` already batches the 1110-row/1000-row task catalogs.
   The measured 100-write cost makes this a likely seconds-level optimization.
   Keep real independent connections for atomic claims, rollback, corruption,
   reopen and uncertainty recovery; preserve `synchronous=FULL`. [5,16]

Also avoid creating Temp directories for tests with no `tmp_path`: 656/1124
static declarations need none, while the editing runner creates one for every
body; protected selfcheck already allocates only when required. The bounded
200-test result indicates a small optimization. [3,4]

Native browser persistence/reopen, pending-JavaScript cancellation, attach/
consent, identical-URL native IDs and cross-window movement are distinct
Workspace adapter contracts. Reuse a disposable browser only across compatible
scenarios with explicitly reset tab/page state. Five Edge failures justify
recovery/cleanup investigation, not removing those contracts. Cross-process UIA
already batches commands while keeping independent control-ID/readback scopes.
Its 37.174s cost is real, but re-batching is not an untouched opportunity. [17]

No recommendation requires weaker CI/selfcheck, global fake stores, private Qt
patches or tests of Python/dependency semantics. Each consolidation should name
its retained Workspace defect; focused mutation evidence can assess changed
coverage after implementation. The historical audio/engine mutation audit is
explicitly not a whole-project redundancy score. [1,18]

## Sources

1. [Historical audit](testing-audit.md), [per-test timings](testing-timings.json).
2. [Dependency-refactor checks](dependency-refactor-checks.json),
   [Oct 23 release checks](agentic-release-checks.json).
3. Coordinator's already-completed Oct 28 full/isolated/200-case observations.
   Full result: 1108 passed / 5 Edge failures / 4 skipped, 1143.67s; complete
   timing artifact not retained. Earlier 689.57s result selected the same 122
   modules. These full runs were not repeated during the bounded investigation.
4. [Editing executor](../scripts/check.py), [protected fixture protocol](../selfcheck.py),
   [bounded generation](../tests/properties/generation.py).
5. Valid native probe artifacts under Windows Temp `workspace-test-cost-probes/`:
   [SDK first](/mnt/c/Users/Jim.Lundin/AppData/Local/Temp/workspace-test-cost-probes/sdk-first.json),
   [Qt first](/mnt/c/Users/Jim.Lundin/AppData/Local/Temp/workspace-test-cost-probes/qt-first.json),
   [store](/mnt/c/Users/Jim.Lundin/AppData/Local/Temp/workspace-test-cost-probes/store.json),
   [copy](/mnt/c/Users/Jim.Lundin/AppData/Local/Temp/workspace-test-cost-probes/copy.json).
6. [Qt v6.12.0 signature/loader.py](https://github.com/pyside/pyside-setup/blob/v6.12.0/sources/shiboken6/shibokenmodule/files.dir/shibokensupport/signature/loader.py),
   `post_init` lines 148–159.
7. [Qt v6.12.0 signature.cpp](https://github.com/pyside/pyside-setup/blob/v6.12.0/sources/shiboken6/libshiboken/signature/signature.cpp),
   `feature_import` lines 301–340;
   [signature initialization](https://github.com/pyside/pyside-setup/blob/v6.12.0/sources/shiboken6/libshiboken/signature/signature_globals.cpp).
8. [Qt v6.12.0 feature.py](https://github.com/pyside/pyside-setup/blob/v6.12.0/sources/shiboken6/shibokenmodule/files.dir/shibokensupport/feature.py),
   classification 135–173, internal controls 175–196.
9. [Qt v6.12.0 feature documentation](https://github.com/pyside/pyside-setup/blob/v6.12.0/sources/pyside6/doc/developer/feature-motivation.rst),
   overriding importer 268–277;
   [published official docs](https://doc.qt.io/qtforpython-6/developer/feature-motivation.html).
10. [Qt v6.12.0 enum options](https://github.com/pyside/pyside-setup/blob/v6.12.0/sources/pyside6/doc/developer/enumfeatures_doc.rst),
    [internal Qt configuration](https://github.com/pyside/pyside-setup/blob/v6.12.0/sources/pyside6/libpyside/pyside.cpp), around 901.
11. [Qt import owner](../assistant/qt.py), [SDK boundary](../assistant/sdk.py),
    [startup owner](../assistant/app.py).
12. [HTTP fixture](../tests/fake_endpoint.py), [local browser fixture](../tests/browser_fixture.py).
13. [Mixed/copied-source native runtime cases](../tests/test_windows_runtime.py).
14. [Native fixture](../tests/test_windows_agent_toasts.py),
    [feed cases](../tests/test_windows_feed.py), [tool cases](../tests/test_windows_tool_presentation.py),
    [native resource ownership](../tests/test_windows_bubble_lifecycle.py).
15. [Feature rig/cases](../tests/test_features.py), [feature effect coupling](../assistant/features.py),
    [LLM contracts](../tests/test_llm.py), [tool vs SDK rig](../tests/test_agent.py).
16. [Store cases](../tests/test_work_store.py), [WorkExecution pagination](../tests/test_work_actions.py),
    [transaction owner](../automation/store.py), [batch seeding](../tests/work_fixture.py).
17. [Native browser](../tests/test_windows_browser.py), [native IDs/groups](../tests/native_browser_tabs.py),
    [UIA scopes/batching](../tests/test_windows_computer.py).
18. [Mutation evidence](testing-mutations.json), [owned-property scope](property-testing.md),
    [project test policy](../AGENTS.md).
19. [Retained bounded timing observations](test-speed-timings.json); diagnostic
    harness and complete import-span logs in Windows Temp `workspace-test-cost-probes/`.

Installed PySide6 and shiboken6 version files both report 6.12.0. Fetched GitHub
v6.12.0 feature/loader sources match Qt code.qt.io branch 6.12.0. The installed
signature helpers are embedded in the distribution; they were not imported or
extracted during this source investigation.

20. [Retained overhead-removal observations](test-speed-timings.json),
    `overhead_reduction`; complete incremental logs remain in Windows Temp
    `workspace-test-cost-probes/`.
21. [Fictional command handler](../tests/outlook_fixture.py),
    [draft policy and retained child-process scenario](../tests/test_outlook.py),
    [native binding-sharing case](../tests/test_windows_outlook.py).

22. Feed waiting/bridge observations retained in [timing data](test-speed-timings.json),
    `feed_overhead_reduction`; the final full report is in Windows Temp
    `workspace-feed-overhead-final.timings.json`. [Fixture](../tests/feed_fixture.py).
