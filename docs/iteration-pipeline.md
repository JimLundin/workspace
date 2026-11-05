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

`watch` reruns affected tests, including native tests, in fresh processes after
each debounced save. `--source-only` leaves native modules out of automatic
selection. `preview` restarts the real toolbar with sample data and inert
actions after each save; it starts no keeper, microphone, keyboard observer or
live communications. `watch --preview` runs the same preview beside the tests.

## What `Dev.cmd check` does

1. It runs the architecture review (`scripts/architecture.py`), which parses
   source without importing it. The review enforces keyboard isolation, the
   work process's isolation from desktop-only owners, headless and UI-private
   owners, frozen and slotted data records, the reflection rules with their
   exact exceptions in `pyproject.toml`, and the ban on patch and mock
   frameworks in every source file.
2. It runs the interface review (`scripts/quality.py`): Ruff's FBT001, FBT002 and
   PLR0913 (at most five inputs), and the import rules for relative, inline and
   aliased imports and `__all__` forwarding. See
   [code-quality-policies.md](code-quality-policies.md).
3. With `--standards`, which `Dev.cmd check` always passes, it runs whole-tree
   `ruff check` and `ruff format --check` before tests, and Pyright over the
   changed Python files alongside the tests. `--full` and CI type the whole tree.
4. It runs the selected tests. Without `--tests` it compares source with the last
   deployed manifest and selects the test modules that import a changed module,
   directly or through test helpers. Pin changes, application assets and a
   missing baseline select the full source suite.

Any failure stops before a receipt. `--tests` accepts files and
`tests/test_x.py::test_name` selectors. `--native` includes the Windows
integration modules, which run sequentially on a private desktop so their
windows never appear on the user's screen. `--full` runs everything; CI and the
keeper also run the protected `selfcheck.py` full suite.

Every check that reaches execution writes timing evidence to
`%LOCALAPPDATA%\workspace\development\timings\check-*.json`, or to the path given
with `--timings`. Each failure is listed with its node id and a short summary.
Editing checks cache per-file policy observations under
`%LOCALAPPDATA%\workspace\development\analysis`; the protected selfcheck uses no cache.

Generated tests live in `tests/properties/` and need the `test` extra
(`python -m pip install -e ".[test]"`). See [property-testing.md](property-testing.md).

## Receipts and deployment

After the final edit, write a receipt with
`Dev.cmd check --receipt "$env:TEMP\workspace-check.json"` (add `--full` for a
broad change) and deploy with
`Dev.cmd deploy --check-receipt "$env:TEMP\workspace-check.json"`. The receipt
must match every source byte in the Git-listed working tree, and a receipt
written without the standards is refused. Use `scripts/bundle.py` only when
`.python-version` or `requirements/windows-py315.lock` changes.

The deployment coordinator stages the checked source in Windows Temp, then
computes which components the change affects from both versions' imports.
Assistant-only changes keep the keyboard and automation running. Supervisor,
bootstrap or implicit asset changes stop everything with `WM_CLOSE` and relaunch
`workspace.pyw`. For a selective deployment the keeper pauses only the selected
children, requires their clean exits, and blocks other requests until resume.
The coordinator replaces only changed managed files, clears their bytecode,
verifies them, restarts or resumes, waits for fresh readiness markers, and then
publishes the new ZIP. A failure before launch restores the previous files and
relaunches the previous copy. A stopped copy stays stopped.

Receipts in each stage record clean exits, changed and removed files, readiness
markers, preserved process identities and phase timings. Reverify a completed
stage with `python -m scripts.deploy verify --stage <stage path>`.
