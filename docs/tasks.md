# Open tasks

What's left after splitting the desktop from the assistant (November 2026).
Each task is meant to fit in one short session and ship as its own commits.
Delete a task when it's done.

## 1. Make checking fast

The keeper is gone (2026-11-07): Workspace runs from the checkout through
`launch.py`, and `Dev.cmd deploy` only restarts the programs. A check selects
tests against the source the same tier last passed.

Left:

- **Shrink the native tier** (user, 2026-11-08: native runs choke the whole
  machine and cause more trouble than they help). 26 `test_windows_*`
  modules, about 190 tests; the largest are `bindings` (41), `work_canvas`
  (28), `island_bar` (22), `recording` (13), `audio` (12) and
  `shell_sections` (12). For each test, keep it native only if it checks
  something that needs Windows or Qt itself (a hook, a window, a device);
  move a decision it checks into a pure function with a plain test, and drop
  what a plain test already covers. Don't run the native tier per change
  meanwhile; once per batch at most, for the modules a change can't be
  checked without.
- **Give the meeting service's 2 s publish pacing a seam.** It removes the
  three meeting tests from the slow lists.
- **Skip the Windows runner for pure test modules.** A small check is about 9 s
  end to end; about 5 s of that starts the Windows test runner and moves it
  onto a private desktop. Test modules that can't touch Qt or Win32 could run
  in the checker process itself. That is a judgement call on isolation.
- **An intermittent coordinator crash (`0xC0000409`) in the isolated selfcheck**
  (2026-11-07): three of six full runs died about 96 s in, while
  `test_windows_browser` drove Edge; the rest passed or failed that test with
  "Navigation is still loading". It isn't tied to one commit. The isolated
  launcher now reports the status instead of overflowing `os._exit`.
- **Investigate the three largest native tests:**
  - UIA (30 s);
  - managed Edge (26 s);
  - attached Edge (19 s).
- **The full native tier dies** (2026-11-07): `Dev.cmd check --native` with no
  native receipt (all 143 modules) fails after about 2.5 min with "The Windows
  test process did not write its result". It fails the same way at `166cd28`,
  so it predates the mutable-parameter work; small native selections pass.
- **A narrow check blames a cold openai import on one test.** `assistant.llm`
  imports openai lazily, so the check's SDK preload (`sdk_packages`, eager
  imports only) skips it, and the first `test_features` test that transcribes
  pays about 2–4 s (`test_a_second_talk_key_while_listening_is_ignored` fails
  the editing budget whenever `assistant/features.py` changes).
- **Move ruff and pyright to the dev group.** They sit in the runtime
  dependencies only because the agent's own checks needed them.

## 2. Check that each side survives the other's restart, live

Verified on 2026-11-06 (then through the keeper's `Restart`; now `launch.py restart`): restarting the
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

1. **Enum-translating `match`**: done 2026-11-07. 23 matches became tables
   built with `contracts.members.every_member`, which fails at import unless
   every member is present; the architecture review's `enum-translation` rule
   now rejects new ones.
2. **Bare numeric tuples**: done 2026-11-07. `winapi.shapes` gained `Point`,
   `Size` and `Offset`; single-owner shapes got their own frozen records. The
   review's `bare-tuple` rule rejects new ones in production code; 20 remain in
   test fixtures. Adding `Point` to the hook costs about 0.5 µs per key; the
   engine benchmark is unchanged.
3. **Append in a loop**: done 2026-11-07. 76 sites rewritten with
   comprehensions, generators and generator functions; the review's
   `loop-accumulation` rule rejects new ones. The keeper's 17 went with the
   keeper and `scripts/selfcheck`'s 11 were rewritten once it stopped being protected. 11 remain in tests, which the rule doesn't cover.
   `island_layout.arrange` is about 6 µs slower per call (a frozen step per
   part), negligible beside its font measurement.
4. **Mutable parameter types**: done 2026-11-07. 44 production sites: read-only
   ones take `Sequence`/`Mapping`/`Set`; the voice job notes its evidence on a
   `features.Progress` owner; the check's source steps yield their problems and
   a `check.Phases` owner times its phases. The review's `mutable-parameter`
   rule rejects new ones; `@override` methods are exempt, and four
   SDK/`gc.callbacks` signatures are exact exceptions. 18 remain in tests, which
   the rule doesn't cover.
5. **Every class a frozen dataclass; no reassignment** (user, 2026-11-07): the
   point is that nothing reassigns an attribute of ours. Owners of changing
   state hold a `cell.Cell` of a frozen state record and replace it whole; the
   keyboard follows the same model, benchmarked. Counted in production code on
   2026-11-07:
   1. **Classes that only held their inputs**: done. 29 became frozen records;
      the review's `plain-record` rule rejects new ones. `MemorySession` is an
      exact exception: the SDK's `Session` protocol needs writable attributes.
   2. **Classes that build state in `__init__` but never rebind**: done
      2026-11-07, 43 classes. Patterns, for the owners still to come:
      - stateless adapters just take the decorator;
      - a defaulted input is a `default_factory` field;
      - a part built from inputs (a socket, a window, an icon, a thread) comes
        from a named classmethod (`Server.bind`, `AppWindow.create`,
        `Icon.draw`, `ViewThread.start`, `WinDesktop.following`);
      - a store creates its schema in `__post_init__`, which rebinds nothing;
      - a thread that runs the owner's own method isn't kept: it sets the
        owner's `finished` event on exit, and `close` waits on that.
      `Conversations` holds its recent histories as a `frozendict` in a `Cell`.
   3. **Owners that rebind their own attributes** (85 classes, about 700
      sites), plus five from step 2 that mutate a held container or are written
      from outside: `meetings._Writer` (`bytearray`), `sdk.Timeline` (with its
      `TextBuffer` exception), `scripts.selfcheck.Lanes`, `worker.OwnerCalls`
      (`BoundRunner` sets `current`) and `benchmark_island.Clock`. Each gets a
      frozen state record in a `Cell`. Done 2026-11-07: `link`, `winapi`,
      `automation`, `contracts`, `scripts`, `gateway`, and `assistant`.
      **Composition roots fold reported events** (user, 2026-11-07: frozen
      everywhere is meant to make state explicit; hidden state, even when
      faster, is harder to follow in a language that tracks no side effects).
      Done 2026-11-08 for `AssistantApp` (`assistant.control`), `DesktopApp`
      (`desktop_ui.desktop_control`) and `Ui` (`desktop_ui.ui_control`): parts
      report facts or requests through one `report(event)`, never calling back
      into the root; a pure `transition(state, event) -> (state, effects)`
      decides, lazily; one `perform` carries effects out, and an effect may
      report a result as the next event (`Fold`). A request is its own effect.
      Done 2026-11-08 for every plain `desktop_ui` owner: `DesktopBar` (its
      model folds `bar_events`), `CanvasPanel`, `CanvasInteraction`,
      `CanvasWindow`, `WorkWindow`, the canvas details,
      `application_observer.Worker`, `KeymapOverlay` and the smaller views.
      Owners whose Cells held a reducible state machine: `WorkAgent` folds
      its presentation (`work_presentation.present`), the canvas gestures fold
      through `work_canvas_gestures.transition`, `DesktopBar` folds
      `bar_events`, and `Triage` keeps its decisions in pure board functions.
      `Communications` and the other service loops record I/O results and
      have no machine left to reduce.
      **Avoid Cells unless necessary** (user, 2026-11-08: "make things more
      pure wherever possible"). A Cell stays only where outside code (an OS
      hook, a window procedure, Qt signals, another thread) reaches a
      long-lived owner and no loop of ours can carry the state. Otherwise:
      the run loop carries the state as a local (`AssistantApp.run`,
      `application_observer.Worker`, the meeting journal); a value returns
      the next value (`EngineState`, `Modifiers`, `WindowsKeyTap`); closures
      replace late-bound Cells; threads aren't kept (started/finished
      events); flags are events, one-shot results are Futures, counters are
      `itertools.count`. Done 2026-11-08: about 111 `Cell[` uses down to 81,
      among them the assistant's control state, the observer, the keyboard
      engine (pure, and faster: p50 8.0 µs), seven thread Cells and `Ui`
      (six to one). Left:
      - shared service state read by other threads (`Communications`,
        `Triage`, `PersonalWork`, `Meetings`, `WorkAgent`, link server and
        client): one Cell each; move their loop-private fields (poll times,
        cursors) into the run loops;
      - Qt and Win32 owners (`desktop_ui`, `winapi`): covered only by native
        tests, so do them with the native-tier task above, not blind;
      - dictated by a dependency: `agent_history.History` (the SDK session),
        `contracts.publication`, the desktop `Inbox` handler and the bar's
        `deliver` (bindings at the window-procedure boundary);
      - `scripts.check.Phases` and the other script owners: with the next
        check-script change, since that needs the native tier.
      Patterns that held up:
      - one record per owner works only where every writer holds the owner's
        lock (audit with a scan for unlocked `Cell` writes); state another
        thread writes under a different lock gets its own `Cell`
        (`Communications._pending_drafts`);
      - read state through properties (`self.window`), not
        `self._state.get().window`, so pyright can narrow optionals;
      - an owner whose parts call back into it (a view publication, a window
        procedure, a server handler) gets them in a classmethod that binds them
        through a `Cell` holding the owner once it exists (`Gateway.listen`,
        `AgentWindow.open`, `TrayHost.start`);
      - a test fixture that subclassed an owner becomes a rig holding a real
        owner (`Recording`, `TriageFixture`); a test that assigned an owner's
        state uses an explicit seam (`Triage.set_board`) or a test-side `Cell`.
      - The audio mixer's 160 000-sample ring stays one buffer written in
        place: copying it per 10 ms packet would cost about 64 MB/s.
   4. **The keyboard** (`miryoku.win.Keyboard`, 36 sites, and the engine's
      mutable `Modifiers` and the record at `engine.py:193`): the same model,
      measured with `scripts/benchmark_keyboard.py` before and after. Keep an
      exact exception only if latency or allocation regresses.
      Done 2026-11-08: the engine is pure over `EngineState` (each key, timer
      and toggle takes the state and returns the next; a refused cleanup
      raises `UnreleasedError` carrying the cleared state), `Modifiers` and
      `WindowsKeyTap` are values, and `Keyboard` holds the engine state in
      its one hook-boundary Cell. Engine latency (5 × 100 000 synthetic
      events, GC on, no collections): mutable p50 4.7 µs, p99 27 µs; one Cell
      15.5 / 108 µs; pure 8.0 / 52 µs. Each `replace` of the 13-field record
      costs about 6 µs.
   5. **Classes with an external base** (22 Qt widgets rebind): set attributes
      only in `__init__` and keep changing state in a `Cell`.
   6. **The rule**: every class with no base (or only `Generic`) is a frozen,
      slotted dataclass, and no class rebinds an attribute outside `__init__`.
      `Cell` is its one exception besides what a dependency dictates. Also
      reject `object.__setattr__`. Six test fixtures still match the
      `plain-record` rule, which doesn't cover tests.
6. **`kind` fields**: the migration below, then the check.
7. **Operators on domain types** (user, 2026-11-07): screen `Point`/`Offset`/`Rect`
   and canvas `ScenePoint`/`Box` have theirs. Still hand-written: the bar
   layout's `Box` scaled to a screen `Rect` (`island_surface`, `island_layout`),
   `Spot` spans shifted by `x + shift`, and the canvas drag's clamp of
   `Placement` coordinates.
8. **Enums over their values** (user, 2026-11-07, a pattern being tried):
   `canvas_look.Role` is the pilot. The navigation log's `Cause` literal (six
   causes, of which `navigation.Source` is three) would be better as one enum.
   Review each `every_member` table: keep it where members share a value or
   another layer owns the values.
9. **Every test names its defect**: checkable after all, as a `# Defect:`
   comment at the top of the body. 638 of 1,128 tests lack one; backfilling
   means judging each, and deleting a test that guards no plausible defect.
10. **Index access** (user, 2026-11-07): 262 constant-index reads (`row[0]`,
    `lines[-1]`) in 74 production files, mostly SQLite rows in
    `assistant.meeting_store` (41) and `automation.store` (35), which want typed
    row adapters. Dependency results (`sys.argv[1]`, `split(...)[0]`,
    `parents[1]`) have better spellings: argparse, `str.partition`, `.parent`.
    Constant slices (200) are mostly length bounds and stay allowed.
11. **Type-parameter defaults** (user, 2026-11-07): review the generic classes
    and aliases (`business_tools.Read`/`Interaction`/`Collection`/`Effect`,
    `browser_tools.Parser`, `state_store.SavedState`, `web_apps.WebAppOperation`)
    for a natural default, from how their uses specialize them.
12. **Lazy results** (user, 2026-11-07): 129 functions return a collection that
    only materializes a generator (107 `tuple`, 13 `frozendict`, 6 `frozenset`,
    3 `dict`), most in `desktop_ui.window_layout`, `automation.store`,
    `scripts.check`, `desktop_ui.island_menu` and `winapi.tray_host`. Each needs
    its callers checked: keep it where the value is stored, cached or reused.

Items 3–5 and 7–8 were added by the user on 2026-11-07: no loop-appending, no
function requiring mutable data, frozen dataclasses wherever possible (external
dependencies are exempt), operators on domain types, enums over their values.

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

## 4. Move inline JavaScript into real `.js` files

User, 2026-11-07: write actual JavaScript, not JavaScript in Python strings.
About 145 lines of it sit in production Python on 2026-11-07, mostly
`assistant.web_apps` (103) and `assistant.communications_browser` (24), with
a few in `browser_dom`, `meeting_browser` and `browser`. Each script becomes a
`.js` file beside its module, loaded once and parameterized through its
arguments (CDP `callFunctionOn` or a JSON-encoded argument) instead of
f-string interpolation; then the review can reject JavaScript in string literals.

