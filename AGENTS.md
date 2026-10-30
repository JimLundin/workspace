# Project scope

The active development checkout is `C:\Users\Jim.Lundin\Projects\workspace`
(`/mnt/c/Users/Jim.Lundin/Projects/workspace` from WSL). Edit this checkout and
run its native Windows tools. `/home/jim/workspace` links to this Windows checkout;
the original Linux tree is preserved at `/home/jim/workspace-linux-reference`.

Workspace owns the Windows keyboard, dictation, assistant, floating desktop bar,
automation and the native Qt work canvas
([docs/work-thread-representation.md](docs/work-thread-representation.md)).
Preserve its Python/Qt runtime. The embedded workspace browser belongs to
[Shared Workspace](https://github.com/JimLundin/shared-workspace), which is paused.

Workspace is in the trial phase. Refactor around current product behavior and
explicit ownership. Remove retired features, unused interfaces and their tests;
legacy data and backwards compatibility are not requirements for cleanup.

Iteration speed is a primary design constraint. Keep tests that detect meaningful
behavioral failures, consolidate overlapping coverage, and use focused mutation
campaigns to assess changed decisions. Investigate survivors before adding tests;
equivalent mutations and impossible inputs do not justify new coverage. Use
affected tests while editing, and keep broad native checks for broad changes.

Tests must exercise behavior or policy owned by Workspace. Do not test Python's
language semantics, built-ins, standard library, or a dependency's own behavior.
We trust Python and dependencies to test their own implementations. Do not add
tests to demonstrate that features such as lazy imports, generators, pattern
matching or dataclasses work. Record that trust as an assumption, not a test.
Use those tools in tests of our decisions, validation, integration wiring and
effect ownership. A test is justified by a plausible failure in our code; if it
only calls an external implementation and asserts its documented behavior,
remove it. Apply this rule when adding, reviewing or consolidating tests.
Before writing a test, name the plausible defect in Workspace code it detects;
if there is no such defect, omit the test.

Patches and mocks are disallowed throughout the codebase, including tests.
Pass explicit typed dependencies into effect owners; test decisions with pure
inputs, real local resources, or concrete adapters implementing those interfaces.
Do not replace imported functions, module globals, native bindings or instance
methods to control behavior. Assert observable behavior through the same interface
used by callers. The architecture review enforces the framework ban for every
source file, including explicit test selections.

Before maintaining custom general-purpose functionality, check whether a focused
dependency provides it. Assess its complete dependency footprint, supported
runtime and integration cost. Prefer a suitable small dependency; keep custom
code when available libraries require disproportionate overhead or broader
behavior changes. Test our domain decisions and adapters, leaving the library's
own algorithms to its upstream tests. For generated properties, use Hypothesis
with bounded valid inputs; read [docs/property-testing.md](docs/property-testing.md)
when adding a property or revisiting the audio-library decision.

Workspace is the product and repository name. Use `workspace` for installation/data
paths, environment variables, control-window identifiers and new artifacts.

# Design

- Immutable data is the default throughout code we write. Use frozen, slotted
  records, tuples and immutable mappings/sets; preserve immutability inside
  records too. Return new values instead of changing inputs or shared domain
  state. A frozen record containing a mutable collection is not immutable.
  Mutation requires a specific necessity, such as measured performance needs,
  native ownership constraints, or significant algorithmic overhead from an
  immutable implementation. Document the exact owner and necessity alongside
  its implementation, and record checker-covered exceptions in
  `tool.workspace.architecture.exceptions` in `pyproject.toml`. Convenience and
  existing usage alone are not necessities. Existing violations may have exact
  migration entries during the agreed gradual rollout; these are cleanup debt,
  not permission for new mutable data. Keep necessary mutation local to its
  owner and publish immutable observations. When introducing or changing an
  exception, read [docs/functional-design.md](docs/functional-design.md).
- Model domain alternatives like Rust enums: use unions of frozen, slotted
  dataclasses for variants with payloads and `Enum` for variants without payloads.
  Handle variants with `match` and `typing.assert_never` where exhaustive handling
  matters. Use `Literal` for fixed values in external contracts.
- Put decisions and state transitions in pure functions. Pass timestamps and
  observations in; return immutable values. Keep threads, locks, files, network
  calls, and UI updates in the modules that own those effects.
- Validate external data when it enters a typed interface. Use the variant's
  fields to express required data instead of unrelated flags and empty defaults.
- Application code works with typed domain values. Prefer Pydantic `TypeAdapter`
  over existing typed shapes for serialization, deserialization and validation
  at IO boundaries; introduce a model class only when it owns a real contract.
  JSON is a wire/storage format only; hand-built JSON contracts and direct
  `json.loads`/`json.dumps` in application code are forbidden. Existing uses are
  migration debt; replace them when changing their boundary.
- Use explicitly typed attributes and direct attribute access. Initialize fields
  in `__init__` and model optional state with typed unions. Do not use `hasattr`,
  `getattr`, or other string-based attribute access to work around missing types.
  Adapt external and native data into validated, typed interfaces at the boundary.
- Outside tests, forbid `typing.cast`, `Any`, custom `TypeIs`/`TypeGuard` assertions,
  type-checker suppressions and
  disabling type checks. Establish types through runtime validation and concrete
  interfaces. For a poorly typed dependency, write a local stub for only the API
  we consume; describe its actual contract, and validate unknown data before
  constructing domain values. Keep stubs under `typings/`, configured for both
  checkers. Existing production escapes are migration debt, not permission to
  add more. Tests may use narrowly scoped casts for fixtures.
- Prefer `match` for structural validation and domain alternatives. Destructure
  required fields and handle variants explicitly instead of introducing bare
  `isinstance` checks or predicate wrappers that assert a type.
- Input types require only the capabilities a function consumes: prefer
  `Iterable`, `Sequence`, `Mapping` or a small protocol over concrete containers.
  Return the most specific truthful type, including exact immutable records and
  variants. External observations remain `object` until validated.
- Boolean parameters on Workspace-owned interfaces must be keyword-only, and
  callers must name them. Apply this to generated record constructors too.
  Preserve required dependency/native signatures in their boundary adapters.
- Three input parameters is the default function design target, excluding
  `self`/`cls` and counting keyword-only parameters. A larger signature requires
  a clear interface reason documented alongside it. Split responsibilities or
  group a real domain concept; arbitrary options bags and variadic arguments
  do not resolve the smell. New oversized signatures are review warnings.
  When changing an existing signature or adding an interface exception, read
  [docs/code-quality-policies.md](docs/code-quality-policies.md) for the exact migration
  baseline and checker scope.
- Use absolute imports only. Import symbols from their owning module; forwarding
  re-exports are forbidden, including package-level shortcuts and compatibility
  aliases. Review indirect forwarding as well: static checks cannot establish
  every symbol's ownership. Avoid self-alias imports and cosmetic prefixes such
  as `Request as ConsoleRequest`;
  use module-qualified names to resolve collisions. A boundary adapter must own
  real validation, lifecycle or adaptation with an explicit contract. When
  changing an import exception or introducing an adapter, read
  [docs/code-quality-policies.md](docs/code-quality-policies.md).
- Declare imports at module level. Use Python 3.15's `lazy import` and
  `lazy from` when loading must wait for first use; inline imports inside
  functions or classes are forbidden. Keep required initialization order
  explicit at the effect owner. Launchers run directly on Python 3.15.
- Prefer generators and lazy pipelines when callers can consume values
  incrementally. Return `Iterator[T]` from generators. Materialize when the
  owner needs indexing, repeated traversal or an immutable snapshot; measure
  performance-critical choices rather than assuming lazy iteration is faster.
- Preserve the keyboard process's isolation from the assistant. Its bounded
  mutable buffers and direct updates use the same variant definitions as the
  rest of the code: convert native event flags to variants once, then reuse those
  events during buffering and replay. Measure key-event latency,
  allocation peaks, and GC with `scripts/benchmark_keyboard.py` before and after
  changing the hook, engine, or their shared dependencies. Keep GC enabled during
  measurement and keep event data acyclic: the live hook disables cyclic GC.
  Apply the same care to audio sample loops and buffer copying.
- Prefer Python 3.15's native annotation and type-alias syntax throughout,
  including launchers and runtime activation.
- When changing domain models or profiling input, read
  [docs/functional-design.md](docs/functional-design.md) for the module map and
  measurement scope.

# Iteration checks

For editing checks and Windows deployment, read
[docs/iteration-pipeline.md](docs/iteration-pipeline.md). Use
`Dev.cmd check` in Windows to select affected source tests; include
meaningful native checks for native behavior, sequentially on the shared desktop.
Use `--full` for broad changes. After final edits, write a source-bound receipt
with `--receipt "$env:TEMP\workspace-check.json"` and deploy with
`Dev.cmd deploy --check-receipt "$env:TEMP\workspace-check.json"`.
Keep the protected selfcheck gate and full CI checks unchanged. Do not rebuild the
runtime bundle or use the old temporary deployment helper for source-only edits.

# Committing work

Work is not done until it is committed and pushed. After the final check passes,
commit the checked working tree on the current branch, deploy, and push. Never
report a task as done, finished or ready while any part of it is uncommitted or
unpushed; report exactly what remains uncommitted and why.

- Commit in small steps that each describe one change. End every message with
  the attribution trailer the session provides.
- Work done in worktrees or by subagents is complete only once the coordinator
  has merged it into the user's branch, committed and pushed. Remove finished
  worktrees and merged branches; never leave the only copy of finished work in a
  worktree, a stash or an unpushed branch.
- When uncommitted work from earlier sessions is present, commit it as its own
  snapshot before committing new work on top, so both are recorded.

# Windows deployment

After each completed change, update the Windows Downloads copy as part of the
task. The user has authorized this sync and a reload whenever Workspace is already
running; no separate confirmation is needed.

- Deploy the checked working tree to
  `C:\Users\Jim.Lundin\Downloads\workspace-sdk\workspace`
  (`/mnt/c/Users/Jim.Lundin/Downloads/workspace-sdk/workspace` from WSL).
- Refresh `C:\Users\Jim.Lundin\Downloads\workspace-sdk-python315-win64.zip` too.
  Use the installed Windows Python 3.15; the archive contains no interpreter.
  Preserve `.runtime` when `.python-version` and the dependency lock in
  `requirements/` are unchanged; rebuild dependencies with `scripts/bundle.py`
  when either pin changes.
- Use the deployment coordinator's component plan and pause/resume handshake
  when that copy is running. Preserve unchanged children and the keeper; require
  clean exits from selected children before replacing their source. Supervisor,
  implicit asset or bootstrap changes use full `WM_CLOSE` shutdown and relaunch
  `workspace.pyw` with the installed Python's `pythonw.exe`. Leave a stopped copy stopped.
- Clear replaced modules' bytecode caches. Verify the deployed files and ZIP
  match the working tree. Verify fresh markers for restarted children and exact
  retained identities/markers for preserved children. Report any deployment or
  reload failure explicitly.
