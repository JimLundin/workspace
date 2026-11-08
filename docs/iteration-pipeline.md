# Checking and running changes

Run native commands from the checkout in PowerShell. `Dev.cmd` uses the Windows
`.venv` and adds native Git to PATH. `Dev.cmd setup` runs `uv sync --locked`:
it creates that `.venv` from the user-installed Python 3.15 with exactly
`uv.lock` plus the `dev` group; run it again after the lock changes. Workspace
itself runs from this checkout and `.venv`. Dependencies are declared in
`pyproject.toml` (exact versions in `[tool.uv] constraint-dependencies`); change
them there and run `uv lock`.

```powershell
.\Dev.cmd check --tests tests/test_feed_triage.py
.\Dev.cmd deploy
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
`typings/typeshed.patch`, then runs Pyright. Pyright is the only type checker.

For feedback on save (`Dev.cmd setup` installs the watcher):

```powershell
.\Dev.cmd watch --tests tests/test_island_model.py
.\Dev.cmd preview
```

`watch` reruns the editing tier's affected tests in fresh processes after each
debounced save. `--native` adds the affected native modules and slow tests. `preview` restarts the real toolbar with sample data and inert
actions after each save; it starts no launcher, microphone, keyboard observer or
live communications. `watch --preview` runs the same preview beside the tests.

## Code volume

`Dev.cmd volume` counts syntax nodes per area and lists the largest files
(`--top N`). Layout, comments, trailing commas and docstrings do not count, so
reformatting leaves the number alone and only removing code lowers it. Product
code is everything outside `tests/`, `scripts/` and `typings/`. Quote the
before/after product and test totals when a change cuts code.

## What `Dev.cmd check` does

1. It runs the architecture review (`scripts/architecture.py`), which parses
   source without importing it. The review enforces keyboard isolation,
   headless and UI-private owners, frozen and slotted data records, enum translations as
   tables rather than `match`, named types instead of fixed numeric tuples, no local container filled in a loop, the reflection rules with their
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
   last source that tier passed (a receipt in
   `%LOCALAPPDATA%\workspace\development\checked`) and selects the test modules
   that import a changed module, directly or through test helpers. Pin changes,
   application assets and a missing baseline select the full source suite. A
   passing check records its source; a passing `--native` check records both
   tiers.

Checks have two tiers. The editing tier, the default, runs only portable tests:
it leaves out native modules (`tests/test_windows_*.py`) and the slow portable
tests listed in `SLOW` in `scripts/check_tiers.py`. In a narrow editing check
(direct imports, fewer than ten modules) a test that takes over 1.5 s fails the
check by name; make it faster or list it, with its reason, in `SLOW`. A native
test over 3 s fails `--native` and `--full` by name unless `NATIVE_SLOW` lists
it. Both lists have caps, so a new slow test means fixing another. `--native`
adds the affected native modules and the slow tests. `--full` runs everything, natively, and types
the whole tree: run it after broad native changes or before a merge.
CI runs the full suite with `python -m scripts.check --full`, which skips the native tier off Windows.

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
`%LOCALAPPDATA%\workspace\development\analysis`.

Generated tests live in `tests/properties/` and need the `test` extra
(`Dev.cmd setup` installs it, in the `dev` group).

## Running

`StartWorkspace.cmd` syncs `.venv` from `uv.lock` and starts the gateway, layout,
assistant and desktop with `launch.py`; the login shortcut runs it. After a
checked change, `Dev.cmd deploy` restarts them all (`launch.py restart`); name
programs to restart only those, as the tray's restart items do. Nothing
supervises the programs: a crashed one stays down until the next start, and a
bad change is undone by reverting its commit and restarting. Each program's
output goes to `%LOCALAPPDATA%\workspace\state\<name>.log`.
