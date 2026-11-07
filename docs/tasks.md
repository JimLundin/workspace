# Open tasks

What's left after splitting the desktop from the assistant (November 2026).
Each task is meant to fit in one short session and ship as its own commits.
Delete a task when it's done.

## 1. Make checking and deploying fast

Done:

- The keeper's install check runs the modules that failed last time first and
  stops at the first failure (`--previous`, `--stop-at-first-failure`). A failing
  deploy used to run all of its roughly 830 tests, about 3 minutes, before
  saying no.
- The run-alone tests (`tests/test_windows_run_alone.py`) are selected by
  changes to either side's composition, and no longer by keeper changes.
- The two scope-bypass tests pass again.
- Every recorded failure says where it was raised (`scripts/check_results.raised`).

Measured on 2026-11-06:

- a one-file desktop or layout change installs in 8–23 s;
- a change to a protected file takes about 60 s to check, then relaunches
  everything.

Test pass (2026-11-07): `--full` went from 291 s to 187 s (measured before the native lanes and the SDK change). Each slow test now
carries its reason in `scripts/check_tiers.py`, under caps, and a native test
over 3 s fails by name.

Left:

- **Give the meeting service's 2 s publish pacing a seam.** It removes the
  three meeting tests from the slow lists.
- **Skip the Windows runner for pure test modules.** A small check is about 9 s
  end to end; about 5 s of that starts the Windows test runner and moves it
  onto a private desktop. Test modules that can't touch Qt or Win32 could run
  in the checker process itself. That is a judgement call on isolation.
- **The SDK now loads only when a test runs an agent** (done 2026-11-07).
  33 of 117 portable modules used to pay 3–8 s for it on every check.
- **Investigate the three largest native tests:**
  - UIA (30 s);
  - managed Edge (26 s);
  - attached Edge (19 s).
- **Dependencies are installed, not bundled** (done 2026-11-07).
  `environments.py` builds one venv per `uv.lock` with `uv sync --locked`; the keeper and every
  program run its interpreter. A lock change deploys through the keeper, and undo
  switches environments.
  - uv also manages CI and the dev `.venv` from the same universal `uv.lock`;
    pip is no longer used anywhere.

## 2. Check that each side survives the other's restart, live

Verified on 2026-11-06 through the keeper's `Restart`: restarting the
assistant left the desktop's process running and its link reconnected to the
new assistant, and restarting the desktop left the assistant running and the
new desktop connected. Still to watch by eye: the bar showing "reconnecting"
then replaying the canvas, and an agent task continuing through a desktop
restart.

## 3. Code policy pass: enforce the modelling decisions, then replace `kind` fields

Decisions the user made, to write into AGENTS.md and enforce in the architecture
or quality review wherever a rule can be checked mechanically:

- **No `kind` fields.** Model alternatives as discriminated unions where each
  kind is its own frozen, slotted type, so an invalid state can't be
  constructed. A constant `Literal` tag for JSON is fine; an enum field that
  decides which values are valid is not. The list below is the migration.
- **Domain types with bounds, not bare tuples.** Example: `desktop_ui.colour.Rgb`,
  not `tuple[int, int, int]`.
- **Translate an enum with a mapping or a value on its members, not a `match`.**
  Use `Final[frozendict[Enum, Value]]` or the member's value. Example:
  `desktop_ui.icons.COLOURS`.
- **No append-to-a-mutable-container-in-a-loop.** Prefer comprehensions, tuples
  and generator expressions, and immutable data. Use `frozendict`, not `dict`,
  for mappings that leave their owner, with replacement instead of mutation
  (for example, `link.server.Server._retained`).
- **Already in AGENTS.md; keep them enforced:**
  - no mocks or patches;
  - no `Any`, `cast` or `getattr`;
  - at most five parameters;
  - keyword-only booleans;
  - every test names its defect.
- **No pip.** uv manages every environment (`pyproject.toml` + `uv.lock`).

Written into AGENTS.md on 2026-11-07. The user chose fix first, then enforce:
each check goes live in the architecture review only once its rule has no
violations left, with no baseline of exceptions. Counted in production code on
2026-11-07:

1. **Enum-translating `match`** (22): a `match` whose cases are only enum members,
   each returning or assigning one constant (a literal, a member or a
   constructor of literals). Mechanical; first. Mappings lose Pyright's
   exhaustiveness, so build them through one helper that fails at import
   unless every member is present.
2. **Bare numeric tuples** (33): `tuple[int, ...]`/`tuple[float, ...]` with fixed
   arity, mostly `desktop_ui.overlay`, `desktop_ui.window_layout` and `winapi`.
   The Win32 boundary shapes need domain types in `winapi.shapes`.
3. **Append in a loop** (83 production, 15 tests). Includes the architecture
   review's deliberate worklists, which need a rewrite rather than an exception.
4. **Mutable parameter types** (41 production, 26 tests): `list`/`dict`/`set`
   and friends in a parameter annotation. Only dependency-dictated callbacks
   (SDK hooks, `gc.callbacks`) are exempt.
5. **Plain classes that could be frozen dataclasses** (about 86 candidates): a
   class with no base that never assigns to `self` outside `__init__`. The check
   must also reject mutable attribute types, since some candidates mutate a held
   container instead.
6. **`kind` fields**: the migration below, then the check.

Items 3–5 were added by the user on 2026-11-07: no loop-appending, no function
requiring mutable data, frozen dataclasses wherever possible; external
dependencies are exempt.

"Every test names its defect" can't be checked mechanically (1,103 tests carry
the defect only in their names); it stays a review rule.

Then replace the enum `kind` fields:

The `kind: Literal["…"]` fields (`TextAnswer`, `TaskRequest`, `SessionRequest`
and about 60 others) are not the problem. Each is already its own frozen type;
the constant `Literal` is only the JSON tag that tells a stored union apart. The
problem is a single type whose enum `kind` decides which values are valid:

- `contracts.personal_work.WorkSource` (`kind: SourceKind`). `MEETING` is
  constructible but always rejected, and each application's URL rules hide in
  `__post_init__`. Split it into `TeamsSource`, `OutlookSource`, `KanbanSource`,
  `DocumentSource` and `WebPageSource` beside the existing `MeetingSource`.
  About 33 sites match on `SourceKind`, but only two build a `WorkSource`
  (`personal_work_sources.observed_source` and `PersonalStore`'s document
  intake). Keep the stored JSON identical: give each new type
  `kind: Literal[SourceKind.X]` and the same field names, so existing catalog rows
  validate into the right type. The catalog is one blob that
  `CATALOG.validate_json` rejects whole, so a changed shape would hide all of
  the user's saved work.
- `assistant.feed_sources` (`kind: SourceKind`, twice);
- `assistant.feed_contracts` (`kind: SolutionKind`);
- `assistant.feed_history` (`kind: DecisionKind`);
- `assistant.communications` (`kind: UpdateKind`);
- `assistant.browser_host` (`kind: str`).
- also found by the scan, to sort into migrations or plain display tags:
  `assistant.feed_triage.Solution` (`SolutionKind`),
  `desktop_ui.canvas_toolbar.Bubble`, `desktop_ui.keymap.Cap`,
  `desktop_ui.navigation_log.Entry` (each `Kind`) and
  `diagnostics.FailureInfo` (`kind: str`).

Take one type per session, `WorkSource` first.
