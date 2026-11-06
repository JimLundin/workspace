# Open tasks

What's left after splitting the desktop from the assistant (November 2026).
Each task is meant to fit in one short session and ship as its own commits.
Delete a task when it's done.

## 1. Make checking and deploying fast

A deploy of a small change takes minutes. On 2026-11-06, deploying a
one-module assistant change took about 3 minutes, with the user waiting.

- **Check the change once.** `Dev.cmd deploy` runs the affected tests, about
  830 tests across 85 modules for a change near the shared code. The keeper
  then checks the change again before it installs. Decide which of the two
  checks owns what: for example, the keeper runs only the import and selfcheck
  smoke tests on a candidate the developer side already passed.
- **Narrow "affected".** A change in `assistant/` should not select desktop or
  layout tests. Since the split, the process-isolation rule guarantees the two
  sides share only `contracts`, `link` and `protocol`. Use the import closure
  per test module rather than per package, and report which edge pulled each
  module in.
- **Find the slow tests.** Profile the native tests. `test_windows_runtime`
  takes about 20 s, mostly two full fresh-interpreter runs. The two run-alone
  tests start a whole assistant and a whole desktop. Find out where the time
  goes: imports, Qt start-up or worker shutdown. Either make those faster or
  move the tests to CI only.
- **Review what each test guards.** Some tests still exercise behaviour the
  split moved, through fixtures written for the old single process (for
  example `tests/test_windows_bindings.py`'s fixture now models two windows).
  Remove tests whose defect can no longer occur, and merge tests that check the
  same thing at two levels.
- **Fix the two failing scope-bypass tests.** They fail in `--full` with
  `No module named 'selfcheck'`: `test_architecture` /
  `test_quality::test_explicit_test_scope_cannot_bypass_*`.
- **Stabilise the flaky browser test.**
  `test_windows_browser::test_managed_browser_dom_teams_persistence_and_cancellation`
  failed once in `--full` and passed alone.
- **Target:** a one-file change deploys in under 30 s.

## 2. Check that each side survives the other's restart, live

The automated tests already show that each side starts, reports ready and quits
without the other (`tests/test_windows_runtime.py`). What hasn't been checked on
the real install:

- restart the assistant while the desktop runs, and see the bar show
  "reconnecting" then replay the canvas;
- restart the desktop while an agent task runs, and see the task continue.

The keeper refuses `Restart` during the 10-minute trial after an install, so
run this outside a trial. Then add **Restart desktop** to the tray menu
(`desktop_ui/spec/tray.py` and `desktop_controls`); today only the layout and
the assistant have restart items.

## 3. Finish the immutability pass

Done: the controls menu flow, the menu spec checks, and the canvas toolbar's
tiles, groups and spec checks. Left:

- `desktop_ui/components/canvas_chrome.py` `show_sections`: it builds its tile
  list in a loop;
- `link/server.py` `Server._retained`: a mutable dict. Replace it with a
  `frozendict` swapped under the lock;
- `link/frames.py` `receive`: a chunk list. Read into a preallocated
  `bytearray`/`memoryview` instead, which also avoids the join;
- the rest of the code from this effort (`desktop_ui/desktop_app.py`,
  `assistant/desktop_port.py`, `assistant/desktop_commands.py`,
  `desktop_ui/assistant_port.py`): look for `list`/`dict`/`set` state and
  append-in-loop code, and use tuples, comprehensions and `frozendict`.

## 4. Replace `kind` fields with discriminated unions

Each kind should be its own type, so state can never be invalid. These still
discriminate by a field:

- `TextAnswer`'s kind;
- `CanvasRequest`, `TaskRequest` and `SessionRequest`.

They're stored in SQLite (the canvas document and the task journal), so the
stored JSON changes shape. Legacy data is not a requirement (AGENTS.md); drop
or rewrite old rows rather than reading both shapes.

## 5. Update the docs for the split

- `docs/functional-design.md`: the five programs (keeper, gateway, layout,
  assistant, desktop), what each owns, and what runs while another restarts.
- `README.md`: the programs the keeper runs, and that a desktop-only change
  restarts only the desktop.
- `docs/toolbar-design.md`: the specs in `desktop_ui/spec/` are the source of
  truth, and they reload live.
