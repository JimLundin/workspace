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
  payloads) and handle them with `match` and `assert_never`.
- Prefer immutable values; mutate only inside the owner that needs it. Put
  decisions in pure functions and keep threads, files, network and UI in the
  modules that own those effects.
- Use direct typed attributes, not `getattr`/`hasattr`.
- Use absolute imports from the owning module, at module level. Use `lazy import`
  to defer loading. No re-exports or cosmetic aliases.
- Boolean parameters are keyword-only. Functions take at most five inputs; Ruff
  blocks more. Where a wider signature is genuinely needed, add
  `# noqa: PLR0913 - <reason>` on the `def` line. Never suppress a whole file.
- Modules listed under `tool.workspace.architecture.headless` in
  `pyproject.toml` must not import `desktop_ui` or Qt, even indirectly.
- Before writing general-purpose code, check for a small focused dependency and
  prefer it when its footprint and integration cost are reasonable.
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
Do not change the protected selfcheck gate or CI's full checks.

# Committing and deploying

Work is done only when it is committed, deployed and pushed. Changes with no
runtime effect (comments, docstrings, docs) need only commit and push.

- Commit in small steps, one change each, ending with the session's attribution
  trailer. Commit leftover uncommitted work from earlier sessions as its own
  snapshot first.
- Merge work from worktrees and subagents into the user's branch, then remove
  finished worktrees and branches. Never leave the only copy in a worktree, a
  stash or an unpushed branch.
- Deploy with `Dev.cmd deploy`; it needs no prior check run. The running keeper
  checks the tests the change affects, then installs it into
  `C:\Users\Jim.Lundin\AppData\Local\Programs\workspace-sdk\workspace` and restarts only
  what changed; a stopped copy just receives the files. The user has authorized
  this without asking. The ZIP changes only with `scripts/bundle.py`, which a
  `.python-version` or `requirements/` lock change requires. Report any refusal
  or undo.
- Report exactly what remains uncommitted, undeployed or unpushed, and why.
