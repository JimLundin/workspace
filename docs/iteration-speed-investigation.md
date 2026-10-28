# Faster development feedback: watch mode and reload feasibility

Investigated on 2026-10-28 against the current Windows checkout, official Python
and Qt documentation, and upstream package metadata/source. The recommended
development tooling is now implemented; the protected selfcheck/CI gates remain
unchanged. Usage is in [the iteration pipeline](iteration-pipeline.md).

The separate [full-suite cost investigation](test-speed-investigation.md) records
the later nineteen-minute run, bounded current measurements and remaining
attribution gaps. The focused-loop measurements below do not establish a faster
full suite.

## Implemented and measured

`Dev.cmd watch` runs affected checks on save in fresh processes and retains a
separate successful session baseline. `Dev.cmd preview` restarts sample toolbar
and feed views, retaining the selected sample state. Both use the pinned
development-only Watchdog dependency. In-process function patching was not added.

The same four toolbar tests took **30.15s before** and **2.90s with the cache
warm** afterward. The latter was a sequential native run with no other local
measurement/static-check process running. It used a temporary current-source
baseline to reproduce the earlier zero-changed-file scope before deployment.
Its phase timings were source hashing 0.535s, architecture 0.252s, quality 0.971s,
selection 0.001s, imports/test execution 0.568s, and final source hashing 0.496s.
A first run populating the new cache took 23.79s. These are individual workstation
observations across development snapshots, not a statistical speedup guarantee;
filesystem/CPU contention materially affects timings.

No-change and documentation-only selection now skips dependency-graph discovery,
while both policy gates still run. A changed Python source still uses cached
per-file imports to evaluate transitive affected tests. Tests verify that changed
imports, deleted model ownership, forbidden interfaces and damaged cache records
retain the uncached policy outcomes. The native watch integration verifies a
fresh imported value after a save, a rejected edit retaining its baseline, and
successful recovery on the following save. Preview integration verifies real
views, inert native menu actions, absent live services, and native resource
disposal. Complete preview launches measured 10.29s and 8.79s. A native
end-to-end save probe measured 10.494s to a fresh preview PID, with the old view
closed cleanly and sample scenario 2 retained. Installed application processes
remained separate. These are individual measurements, including native Qt/glass
initialization. [19]

## Full-suite cost and limits

The subsequent broad native run covered 122 modules: **1,108 passed, 5 failed,
4 skipped in 1,143.67s**. The five failures involved Edge screenshot/cancellation
or disposable-profile cleanup. Isolated retries also failed in browser cleanup;
they do not establish a passing full suite. All new development-tool checks and
the coordinated bubble/feed checks passed. Browser/Teams integration runs were
then stopped.

The 30.15s to 2.90s comparison above measures four focused checks. It does not
establish a faster full suite. The broad run's slowest cases included the reply
property (86.452s), copied-source SDK/Qt initialization (58.529s) and native UI
Automation integration (37.174s). Native process/browser fixtures need further
work; hot reload does not remove their execution cost.

Bounded probes measured the reply property at 1.086s with warm dependency caches.
An unprofiled cold-cache pair measured 4.290s with the default text strategy and
0.951s with a representative alphabet. The alphabet change was not adopted:
cold Unicode generation alone does not explain the broad run's 86s. Hypothesis
also scans loaded modules for constants, including dependencies from the bundled
runtime that its standard site-packages classification does not recognize.
The editing runner now executes generated domain tests before broad dependency
imports. Full compilation/import validation and all 100 generated examples are
retained. Its focused reply-property body measured 6.055s afterward; the complete
nine-check run took 60.18s, including first-use analysis-cache population after
the runner changed. This is evidence for a setup improvement, not a measured
new full-suite total.

Automatic feedback on save is feasible. The best first step is **watching changes
and running focused checks in fresh processes**, plus **a restartable UI preview**
for visual work. General in-process hot reload has substantial lifecycle and
Python 3.15 compatibility questions in this application. It would not reduce the
cost of running the complete test suite. [1, 2, 3]

## Initial investigation: pipeline and measurements

The sections below retain the observations and proposal from before the
implementation. The implementation and current measurements are recorded above.

The existing editing runner already selects affected tests through transitive
imports and supports selecting individual tests. The development environment and
application are native Windows Python 3.15 with PySide6/Qt 6.12. Development reuses
the installed runtime rather than rebuilding it. [1, 2]

Two focused runs on the native checkout passed:

| Editing scope | Passed | Runner wall time | Test bodies |
| --- | ---: | ---: | ---: |
| `Dev.cmd check --tests tests/test_bar_model.py` | 4 | 30.15s | 0.04s combined |
| `tests/test_windows_tool_presentation.py::test_cli_call_remains_visible_and_updates_in_its_original_bubble` | 1 | 24.77s | 2.42s |

The second run used the same `scripts.check.main()` entry point and `--native`
with temporary timing wrappers around its phases. It ran sequentially, without
another local measurement running. No runner or application source was changed
for profiling. Its breakdown was:

| Phase | Seconds |
| --- | ---: |
| Initial complete source manifest | 0.45 |
| Architecture review | 4.79 |
| Quality/signature/import review | 7.22 |
| Dependency selection | 4.06 |
| Runtime activation, test imports and test execution | 7.75 |
| Final complete source manifest | 0.49 |

Importing the runner itself added 0.60s before its internal timer; total diagnostic
time was 25.37s. Architecture, quality and selection together took **16.07s**.
That is the largest measured fixed cost in this focused run. Test/import work
also matters: 5.33s of the 7.75s execution phase was outside the test body.
These are individual observations, not statistical benchmarks or current
full-suite timings. A watcher would automate these same waits unless the runner
also changes. [1; phase observations in this investigation]

Before this change, the three stages parsed Python sources separately:
`architecture.review()` builds ASTs, `quality.scan()` reads/parses them again,
and `check.select()` calls `dependencies()` to parse them again. Share parsed
source observations within a run, then assess content-keyed reuse between
watch iterations. Continue evaluating whole-graph ownership policies and exact
exceptions; changed configuration, source membership and tool versions must
invalidate affected cached analysis. Keep final source hashing and receipt
validation intact. This proposal is now implemented and measured above.
[1; implementation: 18]

The deployed manifest matched all 362 Git-listed source files before this note
was added, despite the extensive Git diff. Selection returned zero changed files
and zero affected tests. The comparison is against **deployed bytes**, not Git
HEAD. With one hash changed only in an in-memory baseline, the actual selector
returned 8 modules for `assistant/bar_model.py`, 11 for
`assistant/tool_call_view.py`, and all 118 eligible modules for `runtime.py`.
The first two scopes include 7 and 11 native modules respectively; native cases
remain sequential on the shared desktop. This verifies that affected selection
works, while showing why an explicit test/function scope helps during editing.
Bootstrap/configuration/pin changes and implicit application assets intentionally
fall back to broad checks. [1; selector observations in this investigation]

Recent existing successful native deployment receipts provide another cost:

| Stage receipt | Coordinator total | Outage, close to verified readiness |
| --- | ---: | ---: |
| `workspace-source-1793180762608107800` | 33.34s | 14.50s |
| `workspace-source-1793179059752275100` | 61.55s | 31.36s |

These receipts are under Windows `%TEMP%`, in each stage's `timings.json`.
The latest records preparation 13.87s, clean stop 6.15s, replacement 1.66s,
reload/readiness 6.81s and verification 4.86s. Its preceding editing receipt
records 89 passed, one skipped in 57.06s. Coordinator totals exclude the initial
source staging and preceding check; they are not complete save-to-visible times.
No extra deployment was performed to collect these observations. Older full-suite
measurements in [testing-audit.md](testing-audit.md) belong to earlier snapshots
and should not be treated as timings of today's full suite. [5; existing receipts]

## What can reload

| Approach | Feasibility and limits | Recommendation |
| --- | --- | --- |
| Watch tests/checks and launch a fresh runner | Reuses the affected-test selector while avoiding stale Python objects. Watching does not itself make an individual check faster. | First implementation. |
| Restart an isolated UI preview on save | Current UI constructs Python QtWidgets. Existing toolbar tests instantiate `DesktopBar(native_shell=False)` without starting its notification/weather/status services, Windows-key observer or taskbar-recovery worker. Other native tests build the real feed with controlled data. The implemented preview uses these seams and adds an owned disposal/restart protocol. [4, 19] | Best visual feedback loop. |
| Restart the installed application | Existing deployment owns clean close, waiting for the keeper/children, source replacement and fresh readiness verification. It also updates/verifies the ZIP. [1, 5] | Useful after meaningful changes, but currently carries deployment costs. |
| Restart only the assistant, preserving layout/automation | The processes are already separate, but a normal successful assistant exit instructs the keeper to stop the entire group. The keeper exposes a layout-restart request, not an assistant-restart request. [6] | Possible future lifecycle feature; not available by wrapping a command. |
| Reload Python modules in place | `importlib.reload()` does not replace external `from`-import bindings or existing instances' class definitions; removed names can remain; extension initialization is not repeated; reload is not thread-safe. Workspace uses direct symbol imports, live Qt instances, queues and worker threads. [3, 7] | Avoid as the general development mechanism. |
| Patch function/method bodies with Jurigged | Can update existing functions/methods, but initializers are not rerun, changed attribute names can break objects, and closures/decorators have limits. Upstream CI inspected here covers Linux Python 3.9–3.13, not this Windows Python 3.15/PySide6 combination. [8] | Experimental only; verify compatibility before proposing adoption. |
| QML live reload | Qt's QML component cache can reload components after disposing old QML objects. Existing objects retain old types. This app uses Python QtWidgets rather than a QML view tree. [4, 9] | Does not apply without a UI rewrite. |
| Live stylesheet/visual-data refresh | QtWidgets already accept styles dynamically, and Workspace applies styles via `setStyleSheet`. Extracted visual data could be reapplied on the Qt thread without replacing application classes. Geometry, callbacks and initialization changes still need reconstruction/restart. [7, 10] | Optional later, if preview restart proves too slow. |

Qt requires GUI objects on the main thread and retains identity, parent ownership,
signals and queued events for live objects. Editing a Python class definition
does not provide the disposal/reconstruction protocol for those native resources.
Any preview should construct and dispose its own views through the existing Qt
initialization boundary, which deliberately resolves `ThreadPoolExecutor` before
loading PySide6. [7, 11]

The installed assistant's clean shutdown stops capture with `discard=True`,
closes communications/meeting/frontend workers and closes Qt. An autorestart
therefore cannot promise preservation of an active recording or transient UI
state. A watcher must not automatically interrupt the user's live work on each
save. A preview using fictional data avoids this product lifecycle. [7]

## Watcher dependency choices

Metadata was read from PyPI on the investigation date. Wheel tags and version
requirements establish distribution eligibility; they are not proof of runtime
operation on the project's exact interpreter. Watchdog was loaded from its
official wheel in Temp and exercised on native Windows; other candidates were
not smoke-tested. No package was installed during the initial research probe.
Implementation subsequently pinned Watchdog in the development extra and
installed it into the Windows development venv. Runtime pins are unchanged. [12]

| Candidate | Windows/Python distribution and complete core dependency footprint | Integration cost |
| --- | --- | --- |
| `watchdog==6.0.0` core | Requires Python >=3.9; Windows x64 `py3-none-win_amd64` wheel. Core has no additional Python package dependencies. Its Windows backend uses ctypes and `ReadDirectoryChangesW`. The optional `watchmedo` CLI adds PyYAML. [12, 13] | Smallest independent watcher for a console supervisor. Use its event API; Workspace owns child shutdown/check selection. |
| `watchfiles==1.3.0` | Requires Python >=3.10; ships a Rust extension in a `cp310-abi3-win_amd64` wheel. Core graph is watchfiles → AnyIO → idna on Python 3.15, without extras. AnyIO 4.15.1 and idna 3.20 are already in this project's runtime lock. AnyIO's exceptiongroup and typing_extensions requirements apply only to older Python versions. [2, 12, 14] | Compact API; one new wheel when existing runtime versions are reused. Stable ABI eligibility is supported by CPython's ABI contract; an exact native smoke test remains necessary. [15] |
| Existing `QFileSystemWatcher` | Part of already installed QtCore; no new package. File watches cease after removal/rename, including common atomic-save patterns; directory/file re-registration is needed. Directory watching is not a recursive source-tree supervisor by itself. [16] | Suitable for a Qt preview watching a small explicit file set; less attractive for a whole-repo console runner. |
| `jurigged==0.6.1` | Core dependencies are blessed, codefind, ovld and watchdog. Current eligible metadata adds blessed → wcwidth + jinxed → ansicon on Windows; codefind 0.1.7, ovld 0.5.18, wcwidth 0.9.4 and ansicon declare no further core dependencies. Optional develoop adds giving/rich and their dependencies, outside this assessment. [8, 12] | Larger footprint and bytecode/object patching risks than a watcher. Not the first choice. |

`watchfiles.run_process` and `watchmedo auto-restart` are process supervisors.
Their shutdown implementations use signals and escalation to kill, rather than
Workspace's owned control windows and readiness protocol. Do not wrap
`workspace.pyw` in either and assume its keeper/keyboard/native children were
cleanly shut down. Use a dependency for change detection and retain Workspace's
native lifecycle owner for installed reloads. [5, 6, 17]

### Native watcher probe

On 2026-10-28, `watchdog==6.0.0` passed a bounded native file-event probe under
the checkout's `.venv\Scripts\python.exe`: CPython 3.15.1, MSC v.1951, 64-bit
AMD64, Windows 11 build 26100. The probe downloaded
`watchdog-6.0.0-py3-none-win_amd64.whl` from the file URL in official PyPI metadata,
verified its SHA-256 against that metadata, extracted it in Windows Temp, and
added the extracted folder only to that temporary process's import path. [12]

The selected `WindowsApiObserver` observed **create, modify, rename and delete**
events for a temporary text file. The event/cleanup portion took 0.85 seconds;
the observer stopped, its thread joined, and the probe directory was removed.
The temporary wheel and script were removed afterward. This establishes basic
native watcher operation on the actual interpreter. It does not measure repo
watching overhead or test storm/debounce behavior, recursive directory changes,
editor-specific atomic saves, or application restart. The subsequent integration
and preview restart checks are recorded above. [19]

## Initial implementation proposal

1. Reduce repeated source analysis and add a native `Dev.cmd watch` loop around
   the existing editing checker. Debounce
   saves, ignore dependency/runtime/cache/output directories, and run only one
   check at a time. Source edits during a check should schedule another run of
   the latest source; they must not produce a receipt for stale bytes. Support
   explicit test selection; preserve Windows `Dev.cmd check`'s existing native
   coverage by default. Keep a separate last-successful watch baseline so preview
   edits do not accumulate against the deployed baseline. The existing
   `--baseline` argument accepts a source receipt; advance that local baseline
   only after a successful, source-bound run. It does not establish deployment
   or substitute for broader final coverage. Keep broad CI and protected
   selfcheck intact. [1]
2. Add a separate preview command for the toolbar/feed with fixed fictional
   states. Start it in the development checkout with its own Qt process, controlled
   callbacks and no installed keeper, keyboard hook, microphone recording or live
   communication sends. Restart that preview on relevant saves. Reuse the real
   widgets and existing initialization/disposal seams. [4, 7, 11]
3. Measure save-to-result and save-to-visible-preview. Optimize the dominant
   measured phase before adding state-preserving hot patching. Assess an
   assistant-only restart only if preview scope is insufficient; it needs an
   explicit keeper transition and shutdown/readiness contract. [5, 6]

The first two steps are now implemented, with native watcher integration,
preview lifecycle and timing evidence recorded above. Assistant-only restart
remains a separate future lifecycle feature.

## Sources

1. [Current iteration pipeline](iteration-pipeline.md),
   [editing runner](../scripts/check.py), [repository instructions](../AGENTS.md).
2. [Project dependencies](../pyproject.toml),
   [Windows runtime lock](../requirements/windows-py315.lock).
3. [CPython 3.15: importlib.reload](https://docs.python.org/3.15/library/importlib.html#importlib.reload).
4. [Toolbar construction](../assistant/desktop_bar.py),
   [toolbar native fixtures](../tests/test_windows_shell.py),
   [feed native fixtures](../tests/test_windows_feed.py).
5. [Native deployment close/install/readiness owner](../scripts/deploy_windows.py).
6. [Keeper child lifecycle and requests](../keeper.py).
7. [Assistant startup/shutdown](../assistant/app.py),
   [Qt UI thread/queue/disposal owner](../assistant/ui.py).
8. [Jurigged limitations](https://github.com/breuleux/jurigged/blob/master/README.md),
   [dependencies](https://github.com/breuleux/jurigged/blob/master/pyproject.toml),
   [tested interpreter/platform matrix](https://github.com/breuleux/jurigged/blob/master/.github/workflows/python-package.yml).
9. [Qt: QQmlEngine.clearComponentCache](https://doc.qt.io/qt-6/qqmlengine.html#clearComponentCache).
10. [Qt: QWidget.styleSheet](https://doc.qt.io/qt-6/qwidget.html#styleSheet-prop),
    [Workspace toolbar styling](../assistant/bar_surface.py).
11. [Qt: threads and QObjects](https://doc.qt.io/qt-6/threads-qobject.html),
    [QObject identity/ownership and queued events](https://doc.qt.io/qt-6/qobject.html),
    [Workspace Qt import boundary](../assistant/qt.py).
12. Versioned PyPI release metadata:
    [watchdog 6.0.0](https://pypi.org/pypi/watchdog/6.0.0/json),
    [watchfiles 1.3.0](https://pypi.org/pypi/watchfiles/1.3.0/json),
    [AnyIO 4.15.1](https://pypi.org/pypi/anyio/4.15.1/json),
    [idna 3.20](https://pypi.org/pypi/idna/3.20/json),
    [Jurigged 0.6.1](https://pypi.org/pypi/jurigged/0.6.1/json),
    [blessed 1.52.0](https://pypi.org/pypi/blessed/1.52.0/json),
    [codefind 0.1.7](https://pypi.org/pypi/codefind/0.1.7/json),
    [ovld 0.5.18](https://pypi.org/pypi/ovld/0.5.18/json),
    [wcwidth 0.9.4](https://pypi.org/pypi/wcwidth/0.9.4/json),
    [jinxed 2.1.0](https://pypi.org/pypi/jinxed/2.1.0/json),
    [ansicon 1.89.0](https://pypi.org/pypi/ansicon/1.89.0/json).
13. [Watchdog Windows backend](https://github.com/gorakhargosh/watchdog/blob/v6.0.0/src/watchdog/observers/winapi.py).
14. [Watchfiles project/API](https://watchfiles.helpmanual.io/).
15. [CPython 3.15: stable ABI compatibility](https://docs.python.org/3.15/c-api/stable.html).
16. [Qt: QFileSystemWatcher](https://doc.qt.io/qt-6/qfilesystemwatcher.html).
17. [Watchfiles process supervisor](https://github.com/samuelcolvin/watchfiles/blob/v1.3.0/watchfiles/run.py),
    [watchmedo process supervisor](https://github.com/gorakhargosh/watchdog/blob/v6.0.0/src/watchdog/tricks/__init__.py).
18. [Architecture analysis](../scripts/architecture.py),
    [quality analysis](../scripts/quality.py),
    [affected-test dependency parsing](../scripts/check.py).
19. [Content-bound analysis cache](../scripts/source_analysis.py),
    [watch supervisor](../scripts/watch.py), [preview owner](../scripts/preview.py),
    [analysis regressions](../tests/test_source_analysis.py),
    [native development integration](../tests/test_windows_development.py).
