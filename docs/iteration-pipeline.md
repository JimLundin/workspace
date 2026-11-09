# Checking and running changes

Run native commands from the checkout in PowerShell. `Dev.cmd` uses the Windows
`.venv` and adds native Git to PATH. `Dev.cmd setup` runs `uv sync --locked`:
it creates that `.venv` from the user-installed Python 3.15 with exactly
`uv.lock` plus the `dev` group; run it again after the lock changes. Workspace
itself runs from this checkout and `.venv`. Dependencies are declared in
`pyproject.toml` (exact versions in `[tool.uv] constraint-dependencies`); change
them there and run `uv lock`.

```powershell
.\Dev.cmd check
.\Dev.cmd check tests/test_meetings.py
.\Dev.cmd deploy
.\Dev.cmd lint assistant/meetings.py
.\Dev.cmd format assistant/meetings.py
.\Dev.cmd typecheck assistant/meetings.py
```

## Edit loop

Ruff owns linting and formatting. `Dev.cmd lint --fix .` applies safe fixes and
`Dev.cmd format .` formats the tree; CI checks both. Existing `fmt: off` regions
keep keyboard grids and tables readable.

`Dev.cmd typecheck` runs mypy (strict, configured in `[tool.mypy]`), the only
type checker; with file arguments it checks just those. `typings/` holds stubs
only for a dependency that ships no types (win32more).

## Code volume

`Dev.cmd volume` counts syntax nodes per area and lists the largest files
(`--top N`). Layout, comments, trailing commas and docstrings do not count, so
reformatting leaves the number alone and only removing code lowers it. Product
code is everything outside `tests/`, `scripts/` and `typings/`. Quote the
before/after product and test totals when a change cuts code.
`docs/volume.md` is the committed report: the pre-commit hook in `.githooks/`
(which `Dev.cmd setup` sets as `core.hooksPath`) rewrites it from what each
commit stages, and CI fails when it is stale.

## What `Dev.cmd check` does

1. It runs the architecture review (`scripts/architecture.py`), which parses
   source without importing it. The review enforces keyboard isolation,
   headless and UI-private owners, frozen and slotted data records, enum translations as
   tables rather than `match`, named types instead of fixed numeric tuples, no local container filled in a loop,
   no JavaScript in Python strings, no unused definitions, no two functions of
   the same structure, each Win32 function declared once, the reflection rules with their
   exact exceptions in `pyproject.toml`, and the ban on patch and mock
   frameworks in every source file.
2. It runs the interface review (`scripts/quality.py`): Ruff's FBT001, FBT002 and
   PLR0913 (at most five inputs), and the import rules for relative, inline and
   aliased imports and `__all__` forwarding. See the Design section of
   [AGENTS.md](../AGENTS.md).
3. It imports every production module, excusing a missing Windows-only
   dependency (Qt, Win32, WinRT) off Windows only.
4. It runs every test in this process, one at a time: generated tests
   (`tests/properties/`) first, before those imports, since Hypothesis reads
   constants from loaded modules, then the portable tests, then the native modules
   (`tests/test_windows_*.py`), which skip themselves off Windows. Test files
   or `tests/test_x.py::test_name` selectors given as arguments narrow the
   tests; the reviews and imports still run.
5. With `--standards`, which `Dev.cmd check` always passes, it runs whole-tree
   `ruff check`, `ruff format --check` and mypy beside the tests. Native
   tests wait for them: their fixtures have real deadlines, and mypy
   saturates the cores.

A failing test's captured stderr is printed with its traceback; a passing
test's stays quiet. The review and quality gates stop the check before any
import or test. `Dev.cmd check` takes about a minute on the four-core
development laptop. The reviews cache per-file observations under the system
temporary folder (`workspace-analysis`). CI runs `python -m scripts.check` on
Ubuntu and Windows, and the standards in their own job.

Generated tests live in `tests/properties/` and need the `test` extra
(`Dev.cmd setup` installs it, in the `dev` group).

## Running

`StartWorkspace.cmd` syncs `.venv` from `uv.lock` and starts the gateway, layout
and desktop with `launch.py`; the login shortcut runs it. After a
checked change, `Dev.cmd deploy` restarts them all (`launch.py restart`); name
programs to restart only those, as the tray's restart items do. Nothing
supervises the programs: a crashed one stays down until the next start, and a
bad change is undone by reverting its commit and restarting. Each program's
output goes to `%LOCALAPPDATA%\workspace\state\<name>.log`.
