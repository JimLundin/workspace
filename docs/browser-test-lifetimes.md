# Native browser test lifetimes

The full native run at `8ad1808` took 465.34 seconds. Browser integration
accounted for 118.62 seconds, runtime subprocess integration for 46.73 seconds,
UI Automation/PowerShell for 28.95 seconds, and other native UI/integrations
for 102.95 seconds. Other portable tests took 123.50 seconds, properties
10.59 seconds, and runner phases/module imports 33.83 seconds. The remaining
0.16 seconds was unattributed. Concurrent worker work is excluded from this
nonoverlapping wall-time budget.

A separate browser probe explains why lifetimes matter: two Edge shutdowns
spent 21.34 seconds waiting for native process/job exit, compared with
4.77 seconds launching. Browser-close acknowledgments took only 0.048 seconds.
That probe took 31.64 seconds; its numbers cannot be substituted into the
earlier full run because native exit latency varies substantially.

## Ownership structure

[The native browser tests](../tests/test_windows_browser.py) now own three
scenario groups. [The fixture module](../tests/native_browser_fixture.py)
scopes disposable profile cleanup and fresh attached clients to those groups.
No resource cache survives a test function.

| Group | Before: Edge launches | After: Edge launches | Required lifecycle behavior |
| --- | ---: | ---: | --- |
| Managed DOM, persistence, Teams/activity and cancellation | 4 | 2 | Close/reopen proves saved storage; cancellation runs last and reaps the process. |
| Attached DOM/screenshots, native tabs/groups/moves and cancellation | 3 | 1 | Each client detaches; the same disposable personal browser and original tabs survive. |
| Visible sign-in to background handoff | 2 | 2 | Changing browser mode retains its required restart and dedicated profile. |
| Total | 9 | 5 | Four redundant launches and their shutdowns are removed. |

DOM snapshots retain fresh capture/control identifiers. Teams scenarios navigate
to fresh localhost documents and construct fresh Teams state; navigation recovery
also receives a fresh request-tracing adapter. The activation assertion examines
only commands from its current operation. Its extra target is explicitly closed.

Attached scenarios construct separate Browser clients against the same personal
profile. The screenshot scenario first proves detach leaves its created tab
open, then explicitly closes that tab. The tab/group scenario requires exactly
two ungrouped personal tabs at entry, restores them, and closes its extra window.
The next client must retain the same live personal process. Attached cancellation
then verifies that the original blank tab remains readable.

[Native tab scenarios](../tests/native_browser_tabs.py) and
[Teams/activity scenarios](../tests/native_communications_browser.py) are helpers
called by the owning groups. Their former test-module wrappers are removed so
flat selfcheck discovery and pytest execute each scenario only once. The cohort
has six discovered functions in place of ten, retaining all 128 original assert
expressions plus checks for the shared fixture's entry state and process identity.
Tracebacks retain named scenario helpers; an earlier failure stops the remaining
scenarios in that group, while the other groups still execute independently.

## Verification

Use native Windows Python directly:

```powershell
.\.venv\Scripts\python.exe -m scripts.check --native --tests tests/test_windows_browser.py
```

Both the protected installed selfcheck and the editing runner retain their
existing function protocol; no pytest fixture dependency was introduced.
Ruff and strict Pyright check the changed modules. Real isolated-source mutation
probes detected omitted screenshot-tab cleanup, a borrowed client's cleanup
terminating the personal browser, and cancellation leaving the managed client
connected. Each failure was observed through the grouped callers. No function
or native implementation was patched in a running process.

The first grouped check had an intermittent Edge screenshot failure before
shared scenario state was used. A subsequent complete lifecycle probe passed
all six functions and observed exactly five launches. Unchanged sign-in timings
also varied substantially (4.9–15.7 seconds), so a single run is insufficient
to assign a precise wall-time improvement to the fixture refactor.
The original-source comparison exceeded its 150-second probe timeout and is
excluded from performance comparisons. The fixed reduction in launches is
verified independently of those timing observations.

Full-run evidence remains in Windows Temp as
`workspace-current-full.timings.json` and `workspace-full-accounting.json`;
the individual monotonic observations are in `workspace-test-cost-probes/`.
The successful grouped lifecycle probe and mutation evidence use
`workspace-browser-group-spans.json` and `workspace-browser-mutations.json`.
