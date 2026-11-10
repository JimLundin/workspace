# Open tasks

Each task is meant to fit in one short session and ship as its own commits.
Delete a task when it's done.

## 1. Make checking fast

Workspace runs from the checkout through `launch.py`, and `Dev.cmd deploy`
only restarts the programs. A check runs everything.

Left:

- **Give the meeting service's 2 s publish pacing a seam.** Two meeting
  tests wait through it on every check.
- **Move ruff and mypy to the dev group.** They still sit in the runtime
  dependencies, though nothing at runtime uses them.

## 2. Code policy pass: enforce the modelling decisions

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
  `desktop_ui.tray.TraySpec.colours`.
- **No append-to-a-mutable-container-in-a-loop.** Prefer comprehensions, tuples
  and generator expressions, and immutable data. Use `frozendict`, not `dict`,
  for mappings that leave their owner, with replacement instead of mutation.
- **Already in AGENTS.md; keep them enforced:**
  - no mocks or patches;
  - no `Any`, `cast` or `getattr`;
  - at most five parameters;
  - keyword-only booleans;
  - every test names its defect.
- **No pip.** uv manages every environment (`pyproject.toml` + `uv.lock`).

Written into AGENTS.md on 2026-11-07. The user chose fix first, then enforce:
each check goes live in the architecture review only once its rule has no
violations left, with no baseline of exceptions. `kind` fields, the
enum-translating `match`, bare numeric tuples, append in a loop and mutable
parameters are done and enforced in production code (`kind-field`,
`enum-translation`, `bare-tuple`, `loop-accumulation`, `mutable-parameter`);
tests aren't covered. Left:

5. **Every class a frozen dataclass; no reassignment** (user, 2026-11-07): the
   point is that nothing reassigns an attribute of ours. Owners of changing
   state hold a `cell.Cell` of a frozen state record and replace it whole; the
   keyboard follows the same model, benchmarked. Counted in production code on
   2026-11-07:
   Patterns for the owners still to come:
   - stateless adapters just take the decorator;
   - a defaulted input is a `default_factory` field;
   - a part built from inputs (a socket, a window, an icon, a thread) comes
     from a named classmethod (`Server.bind`, `AppWindow.create`,
     `Icon.draw`, `ViewThread.start`, `WinDesktop.following`);
   - a store creates its schema in `__post_init__`, which rebinds nothing;
   - a thread that runs the owner's own method isn't kept: it sets the
     owner's `finished` event on exit, and `close` waits on that.
   3. **Owners that rebind their own attributes**: done for `link`,
      `winapi`, `contracts`, `scripts`, `gateway`, `assistant`
      and every plain `desktop_ui` owner. Composition roots fold reported
      events: parts `report(event)`, a pure `transition(state, event) ->
      (state, effects)` decides, one `perform` carries effects out (user,
      2026-11-07: frozen everywhere is meant to make state explicit).
      **Avoid Cells unless necessary** (user, 2026-11-08: "make things more
      pure wherever possible"). A Cell stays only where outside code (an OS
      hook, a window procedure, Qt signals, another thread) reaches a
      long-lived owner and no loop of ours can carry the state. Otherwise:
      the run loop carries the state as a local
      (`application_observer.Worker`, the meeting journal); a value returns
      the next value (`EngineState`, `Modifiers`); closures
      replace late-bound Cells; threads aren't kept (started/finished
      events); flags are events, one-shot results are Futures, counters are
      `itertools.count`. 41 `Cell[` uses remain (2026-11-08). Left:
      - shared service state read by other threads (`Meetings`, link server
        and client): one Cell each; move their loop-private fields (poll
        times, cursors) into the run loops;
      - Qt and Win32 owners (`desktop_ui`, `winapi`): covered only by native
        tests, so do them with care, not blind;
      - dictated by a dependency: the desktop `Inbox` handler and the bar's
        `deliver` (bindings at the window-procedure boundary);
      Patterns that held up:
      - one record per owner works only where every writer holds the owner's
        lock (audit with a scan for unlocked `Cell` writes); state another
        thread writes under a different lock gets its own `Cell`;
      - an owner whose parts call back into it (a view publication, a window
        procedure, a server handler) gets them in a classmethod that binds them
        through a `Cell` holding the owner once it exists (`Gateway.listen`,
        `TrayHost.start`);
      - a test fixture that subclassed an owner becomes a rig holding a real
        owner (`Recording`); a test that assigned an owner's state uses an
        explicit seam or a test-side `Cell`.
      - The audio mixer's 160 000-sample ring stays one buffer written in
        place: copying it per 10 ms packet would cost about 64 MB/s.
   5. **Classes with an external base** (Qt widgets that rebind): set
      attributes only in `__init__` and keep changing state in a `Cell`.
   6. **The rule**: every class with no base (or only `Generic`) is a frozen,
      slotted dataclass, and no class rebinds an attribute outside `__init__`.
      `Cell` is its one exception besides what a dependency dictates. Also
      reject `object.__setattr__`. Some test fixtures still match the
      `plain-record` rule, which doesn't cover tests.
7. **Operators on domain types** (user, 2026-11-07): screen `Point`/`Offset`/`Rect`
   have theirs. Still hand-written: the bar layout's `Box` scaled to a screen
   `Rect` (`island_surface`, `island_layout`) and `Spot` spans shifted by
   `x + shift`.
8. **Enums over their values** (user, 2026-11-07, a pattern being tried): review
   each `every_member` table: keep it where members share a value or another
   layer owns the values.
9. **Every test names its defect**: checkable after all, as a `# Defect:`
   comment at the top of the body. Many tests lack one; backfilling means
   judging each, and deleting a test that guards no plausible defect.
10. **Index access** (user, 2026-11-07): constant-index reads (`row[0]`,
    `lines[-1]`) in production code, mostly SQLite rows in
    `assistant.meeting_store`, which want typed row adapters. Dependency
    results (`sys.argv[1]`, `split(...)[0]`, `parents[1]`) have better
    spellings: argparse, `str.partition`, `.parent`. Constant slices are
    mostly length bounds and stay allowed.
11. **Lazy results** (user, 2026-11-07): functions that return a collection
    that only materializes a generator, most in `desktop_ui.window_layout`,
    `scripts.check`, `desktop_ui.island_menu` and `winapi.tray_host`. Each
    needs its callers checked: keep it where the value is stored, cached or
    reused.

## 3. Find what degrades the Charybdis

Since about 2026-11-06 the Charybdis Nano 3x5 (Splinky RP2040 halves, QMK with
VIA, firmware rev 2.00) degrades after a while: the second half flickers, the
trackball updates slowly and keys need a longer press. Replugging clears it,
so it's state in the keyboard or in Windows' view of it. It is plugged into
the Acer X32 X3's USB hub (Realtek RTS5411), beside the Shure MVX2U.
Ruled out on 2026-11-08, each after a replug, with the keyboard fine after:
230 VIA effect off/on toggles (one second, then 0.1 s apart); three DDC/CI
off/on cycles of the monitor whose hub it's on; microphone streaming (only
short dictations near either episode); the layout process (idle, 19 MB, its
live state clean: firmware mode, nothing held). The user noticed the first
episode while the keyboard code was being changed (the layout's engine and
hook records, deployed 02:30 and 10:30).
Diagnostics in `$TEMP/frozen-scan`: `keyboard_diag.py LABEL` (cursor update
rate while moving the ball, VIA round-trip time; healthy: about 690 updates/s,
1.1 ms median gap, VIA 4 ms), `layout_state.py` (the layout's live state, via
`sys.remote_exec`), and `via_watch.py` (VIA timing every 30 s, to date the
onset). Next time it degrades, run both before replugging.
Fixed meanwhile: a restart while dark no longer saves "off" as the effect to
restore.
A short episode at about 18:38 on 2026-11-08 cleared by itself: the left half
flickered and the polling rate dropped. `via_watch` wasn't running (its log
stops at 13:51). It came right after checks on this machine: a full check with
its native tier 18:30–18:33, a native rerun of `test_windows_ambient` (it
round-trips the default speaker endpoint's level; the Shure MVX2U shares the
keyboard's hub) 18:33–18:34, then four editing checks 18:35–18:38. Worth
testing next: run the native audio tests alone with `via_watch` on, and
compare load alone (an editing check) against them.

## 4. Values handed in, not declared by libraries

Done on 2026-11-10: entry points supply the choices (AGENTS.md); `entry-data`
and `program-isolation` keep the structure. The `library-constant` rule was
dropped the same day: it pushed wording, timings and facts into data. Left:

- **Widen `constants` to `desktop_ui`.** 23 findings: the desktop reads kept
  facts across its modules (`EMPTY_SHELF`, `NOWHERE`, `ROUTES`,
  `PHYSICAL_NAMES`, the icon artwork, `pcm.RATE`) with bare names or out of
  behaviour modules.
- **`Scancode` is applied midway, not where scancodes come from.** Either type
  it at the source (`KeyEvent.scancode`, `Keycap.scancode`) or drop it and use
  `Laptop` past the hook. Leaning towards dropping it.
- **Separate Windows' facts, our layout and the Charybdis.** Move `Key` and
  `Mod` to `winapi` (their keycap names may stay in `keyboard`), and move the
  Charybdis's USB identity and Apps key out of `settings.layout`'s `Layout`
  into a firmware record of their own.
