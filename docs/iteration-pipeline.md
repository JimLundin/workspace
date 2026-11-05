# Checking and deploying changes

Run native commands from the checkout in PowerShell. `Dev.cmd` uses the Windows
`.venv`, adds native Git to PATH and reuses Qt and the application dependencies
from the installed `.runtime` through a local `.pth` file. The virtual
environment uses the user-installed Python 3.15.1. Keep the Downloads client
separate so edits and tests never replace files in the running application.

```powershell
.\Dev.cmd check --tests tests/test_feed_triage.py --receipt "$env:TEMP\workspace-check.json"
.\Dev.cmd deploy --check-receipt "$env:TEMP\workspace-check.json"
.\Dev.cmd lint assistant/feed_triage.py
.\Dev.cmd format assistant/feed_triage.py
.\Dev.cmd typecheck assistant/feed_triage.py
```

## Edit loop

Ruff owns linting and formatting. `Dev.cmd lint --fix .` applies safe fixes and
`Dev.cmd format .` formats the tree; CI checks both. Existing `fmt: off` regions
keep keyboard grids and tables readable.

`Dev.cmd typecheck` runs `python -m scripts.typecheck`, which builds the
gitignored `typings/.workspace-typeshed` from the installed Pyright and
`typings/typeshed-overrides/`, then runs Pyright. Pyright is the only type checker.

For feedback on save, install the development watcher once:

```powershell
.\.venv\Scripts\python.exe -m pip install watchdog==6.0.0
.\Dev.cmd watch --tests tests/test_island_model.py
.\Dev.cmd preview
```

`watch` reruns the editing tier's affected tests in fresh processes after each
debounced save. `--native` adds the affected native modules and slow tests. `preview` restarts the real toolbar with sample data and inert
actions after each save; it starts no keeper, microphone, keyboard observer or
live communications. `watch --preview` runs the same preview beside the tests.

## What `Dev.cmd check` does

1. It runs the architecture review (`scripts/architecture.py`), which parses
   source without importing it. The review enforces keyboard isolation,
   headless and UI-private owners, frozen and slotted data records, the reflection rules with their
   exact exceptions in `pyproject.toml`, and the ban on patch and mock
   frameworks in every source file.
2. It runs the interface review (`scripts/quality.py`): Ruff's FBT001, FBT002 and
   PLR0913 (at most five inputs), and the import rules for relative, inline and
   aliased imports and `__all__` forwarding. See the Design section of
   [AGENTS.md](../AGENTS.md).
3. With `--standards`, which `Dev.cmd check` always passes, it runs whole-tree
   `ruff check` and `ruff format --check` before tests, and Pyright over the
   changed Python files alongside the tests. `--full` and CI type the whole tree.
4. It runs the selected tests. Without `--tests` it compares source with the
   installed copy and selects the test modules that import a changed module,
   directly or through test helpers. Pin changes, application assets and a
   missing baseline select the full source suite.

Checks have two tiers. The editing tier, the default, runs only portable tests:
it leaves out native modules (`tests/test_windows_*.py`) and the slow portable
tests listed in `SLOW` in `scripts/check_tiers.py`. In a narrow editing check
(direct imports, fewer than ten modules) a test that takes over 1.5 s fails the
check by name; make it faster or add it to `SLOW`. `--native` adds the affected
native modules and the slow tests. `--full` runs everything, natively, and types
the whole tree: run it after changing native code and before a merge or deploy.
CI and the keeper also run the protected `selfcheck.py` full suite.

Any failure stops before a receipt. `--tests` runs exactly the named files and
`tests/test_x.py::test_name` selectors, with no time budget.

Execution order: one Windows runner on a private desktop takes the import
review and the portable modules (three worker processes once ten or more modules
are selected). A narrow check imports the SDK packages its tests reach as its own
phase first. After the runner exits, and in `--full` after whole-tree pyright
finishes, native modules run in four parallel runners, each on its own private desktop:
Edge, runtime launches, UIA and development tooling, and the rest together
(`NATIVE_LANES` in `scripts/check_native.py`). Native fixtures have real
deadlines; overlapping them with the pool or pyright made them fail.

Typical cost on the four-core development laptop, warm policy cache:
a one-file pure edit about 8 s, `--full` about 165 s (whole-tree pyright alone
takes 85 s). Editing `scripts/check.py`
or the policy reviews invalidates the analysis cache; the next check pays
about 80 s once.

Every check that reaches execution writes timing evidence to
`%LOCALAPPDATA%\workspace\development\timings\check-*.json`, or to the path given
with `--timings`. Each failure is listed with its node id and a short summary.
Editing checks cache per-file policy observations under
`%LOCALAPPDATA%\workspace\development\analysis`; the protected selfcheck uses no cache.

Generated tests live in `tests/properties/` and need the `test` extra
(`python -m pip install -e ".[test]"`).

## Receipts and deployment

After the final edit, write a receipt with
`Dev.cmd check --full --receipt "$env:TEMP\workspace-check.json"` and deploy with
`Dev.cmd deploy --check-receipt "$env:TEMP\workspace-check.json"`. The receipt
must match every source byte in the Git-listed working tree, and a receipt
written without the standards is refused. A changed runtime pin
(`.python-version` or `requirements/windows-py315.lock`) is refused too: rebuild
the bundle with `scripts/bundle.py` instead.

Deploy copies the checked files to a fresh folder in Windows Temp and sends the
running keeper the same install request the agent uses, naming that folder. The
keeper checks a frozen copy (the receipt stands for the portable tests, so only
the affected native modules run), records the running copy as a version, installs
the files and restarts only the programs the change affects. A change to a
protected file relaunches the keeper. Deploy waits for the keeper's result and
reports it; a refusal or undo fails the command. When no keeper is running,
deploy takes the keeper's lock and installs the files through the same version
store, and the copy stays stopped. The Downloads ZIP changes only when
`scripts/bundle.py` rebuilds it.
