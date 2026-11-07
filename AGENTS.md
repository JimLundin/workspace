# Project scope

Workspace owns the Windows keyboard, dictation, assistant, floating desktop bar,
automation and the native Qt work canvas. [GLOSSARY.md](GLOSSARY.md) defines
its terms.
Keep its Python/Qt runtime. The embedded browser is out of scope; it will move to a separate project.
Use `workspace` for installation and data paths, environment variables, window
identifiers and new artifacts.

The active checkout is `C:\Users\Jim.Lundin\Projects\workspace`
(`/mnt/c/Users/Jim.Lundin/Projects/workspace` from WSL; `/home/jim/workspace`
links to it). Work on `main` there and run its native Windows tools. WSL git
cannot read worktrees created by Windows git; use `git.exe` for those.

Workspace is in its trial phase. Delete retired features, unused interfaces and
their tests. Legacy data and backwards compatibility are not requirements.

# Tests

- A test must catch a plausible defect in Workspace code. Name that defect in a
  comment before writing the test; if there is none, do not write it.
- Do not test Python, the standard library or a dependency's documented behavior.
- Patches and mocks are banned everywhere, tests included. Pass typed
  dependencies into effect owners and test with pure inputs, real local
  resources or concrete adapters. The architecture review enforces the ban.
- Use Hypothesis with bounded valid inputs for generated properties, in
  `tests/properties/`. Test our adapters, not a dependency's algorithms.
- A native test (`tests/test_windows_*.py`) must catch a defect only real
  Windows, Qt or a child process can show. A decision you can check with values
  is a portable test, even when the code it lives in is native.
- Tests have a time budget: 1.5 s in the editing check, 3 s for native tests.
  Before listing a slow test in `scripts/check_tiers.py` (with its reason, under
  the cap), remove the cause: real waits, sleeps and retry backoff have seams, and
  an expensive launch (Edge, a fixture window, a fresh interpreter) can be shared
  with the neighbouring test that starts the same thing.

# Design

- Keep the keyboard process isolated: `miryoku/` and everything it imports use
  only the standard library, `winapi` and the stdlib-only top-level modules
  (`config`, `protocol`, `usage`, `components`, `diagnostics`), never
  `assistant`, `desktop_ui`, `automation` or third-party packages. Measure key-event latency, allocation
  and GC with `scripts/benchmark_keyboard.py` before and after changing the
  hook, the engine or their shared dependencies.
- Validate external data where it enters a typed interface. Use a Pydantic
  `TypeAdapter` over existing typed shapes at IO boundaries instead of
  `json.loads`/`json.dumps` (the keyboard-side `usage.py` writer is the exception).
- No `Any`, `typing.cast`, `TypeIs`/`TypeGuard` assertions or type-checker
  suppressions in production code. For a poorly typed dependency, add a stub
  for only the API we use under `typings/`. Tests may cast fixtures narrowly.
- Model alternatives as unions of frozen, slotted dataclasses (or `Enum` without
  payloads) and handle them with `match` and `assert_never`. Make invalid states
  unconstructible: no `kind` field whose enum decides which other values are
  valid; give each kind its own type. A constant `Literal` tag that tells a
  stored union apart in JSON is fine.
- Translate an enum to values with a `Final[frozendict[Enum, Value]]` or a value
  on its members (see `desktop_ui.icons.COLOURS`), not a `match` that only
  returns one constant per member. Build a total table with
  `contracts.members.every_member`, which fails at import unless it names every
  member; the architecture review enforces the rule.
- When the enum's own module owns the values and each member has its own, make
  the values the members: `canvas_look.Role.TITLE = RoleType(14.0, 600, -0.084)`,
  read as `role.value`. Members that would share a value collapse into aliases,
  so keep a table for those and for values another layer owns (UI labels for a
  `winapi` enum).
- Don't reach into a sequence by position (`row[0]`, `pair[1]`, `items[-1]`):
  that value deserves a name. Unpack it, read a named field, or model the record
  (a typed row adapter instead of SQLite tuples). Looking up a key in a table
  (`COLOURS[state]`) is fine, and so is a slice that bounds a length.
- Use domain types with their bounds, not bare tuples: `desktop_ui.colour.Rgb`,
  `winapi.shapes.Point` and `Size`, not `tuple[int, int, int]`. The architecture
  review rejects a fixed tuple of only ints and floats.
- Give domain types the operators their arithmetic needs, so domain code reads
  natively: `point - origin` is a `winapi.shapes.Offset`, `point + offset` a
  `Point`, and `point in rect` replaces a `contains` call. Keep each coordinate
  space its own types (screen pixels, canvas scene, bar layout) and cross spaces
  with a named method, never an operator.
- Prefer immutable values; mutate only inside the owner that needs it. Build
  collections with comprehensions, generator expressions, generator functions and
  tuples, never by filling a mutable container in a loop (nor by rebinding an
  accumulator there). A loop is for a side effect, which has no place in a
  comprehension; even then, keep side effects out of loops where you can. The
  architecture review rejects a local container filled in a loop.
- Keep evaluation lazy: a function whose result is just a generator materialized
  (`return tuple(item for ...)`) returns an `Iterator` or is a generator, and the
  caller materializes when it must. Materialize where the value is stored in a
  record, cached, iterated more than once or handed to a dependency that needs
  a collection; return a `frozenset` or `frozendict` when callers look things up.
- No function requires mutable data. Parameters take immutable types (tuples,
  `frozendict`, frozen dataclasses, or `Sequence`/`Mapping`/`Iterable`), never
  `list`, `dict`, `set` or another mutable container. The architecture review
  enforces it; an `@override` method's base owns its signature.
- Define types as frozen, slotted dataclasses wherever possible; only an owner
  that genuinely holds changing state is a mutable class. Where a measured hot
  path needs cheaper construction, a `typing.NamedTuple` is the fallback: about
  twice as fast to build, but not smaller (64 bytes against a slotted
  dataclass's 48 for two fields), and it compares equal to any tuple with the
  same values, so two such types no longer tell each other apart at runtime. Signatures and types
  an external dependency dictates (Qt overrides, SDK callbacks, ctypes
  structures) are exempt from these rules. A mapping that leaves its owner
  is a `frozendict`, replaced rather than mutated (see
  `link.server.Server._retained`). Put decisions in pure functions and keep
  threads, files, network and UI in the modules that own those effects.
- Use direct typed attributes, not `getattr`/`hasattr`.
- Use absolute imports from the owning module, at module level. Use `lazy import`
  to defer loading. No re-exports or cosmetic aliases.
- Boolean parameters are keyword-only. Functions take at most five inputs; Ruff
  blocks more. Where a wider signature is genuinely needed, add
  `# noqa: PLR0913 - <reason>` on the `def` line. Never suppress a whole file.
- The desktop (`desktop_ui`, `desktop`) and the assistant (`assistant`, `automation`)
  never import each other, even indirectly; they share only `contracts`, and talk
  over `link` (`contracts.desktop_link`). The architecture review enforces it.
- Before writing general-purpose code, check for a small focused dependency and
  prefer it when its footprint and integration cost are reasonable.
- Use the type system's newer tools where they model the data better: PEP 695
  type parameters and `type` aliases, and type-parameter defaults (PEP 696,
  `class Read[Q: Located, R = str]`) for a generic usually specialized one way,
  instead of repeating the common arguments or adding a parallel alias.
- Pyright (strict) is the only type checker. The
  [module map](docs/functional-design.md) says which module owns what.

# Checking

Read [docs/iteration-pipeline.md](docs/iteration-pipeline.md). Scale checks to
the change. Comment, docstring and docs-only changes need no check. Otherwise use
`Dev.cmd check` for affected portable tests while editing and `--native` after
changing native code; keep `--full` for broad changes. Don't rerun a whole suite
to clear a flaky native test: rerun only what failed, and report it. A test over
the editing budget fails by name: speed it up or list it in
`scripts/check_tiers.py`. Run native checks sequentially on the shared desktop.
A passing check records the source it passed (`%LOCALAPPDATA%\workspace\development\checked`),
and the next check selects the tests affected since; the first check runs everything.
Change scripts under `scripts/` with `--native` before restarting, since the
editing tier skips the slow check-process tests. CI runs the full suite
(`python -m scripts.selfcheck`).

# Committing and running

Work is done only when it is committed, running and pushed. Changes with no
runtime effect (comments, docstrings, docs) need only commit and push.

- Commit in small steps, one change each, ending with the session's attribution
  trailer. Commit leftover uncommitted work from earlier sessions as its own
  snapshot first.
- Merge work from worktrees and subagents into the user's branch, then remove
  finished worktrees and branches. Never leave the only copy in a worktree, a
  stash or an unpushed branch.
- Workspace runs straight from this checkout's `.venv`: `StartWorkspace.cmd`
  (also the login shortcut) syncs the environment from `uv.lock` and runs
  `launch.py`, which starts the gateway, layout, assistant and desktop. After a
  checked change, `Dev.cmd deploy` restarts them (`launch.py restart [NAME]`
  restarts one); the user has authorized this without asking. Nothing
  supervises the programs or undoes a change: revert the commit and restart.
  After editing `pyproject.toml`, run `uv lock` and `Dev.cmd setup`. Never use
  pip; uv manages every environment.
- Report exactly what remains uncommitted, not restarted or unpushed, and why.
