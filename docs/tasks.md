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

Left:

- **Run native modules in parallel in the keeper's check.** They run one at a
  time, after the portable workers. In a keeper-touching check, three of them
  took 16, 13 and 11 s back to back. The developer check already runs native
  lanes on private desktops (`scripts/check_native.py`); the keeper's
  `selfcheck.py` needs the same, without importing `scripts/`.
- **Speed up the slow end-to-end tests.**
  `test_windows_browser::test_managed_browser_dom_teams_persistence_and_cancellation`
  takes about 30 s against real Edge. It timed out once under the parallel
  `--full` load and passed three times alone; its next failure will record
  where it timed out. `test_windows_runtime`'s copied-bundle and keeper-cleanup
  tests take 7 s and 6 s.
- **Review what each test guards.** Remove tests whose defect can no longer
  occur since the split, and merge tests that check the same thing at two levels.
- **Close the selection gaps.** Tests that drive a subprocess select nothing
  through their own imports. The run-alone module now imports what its
  interpreters run; look for other such modules (`test_windows_self_change_e2e`,
  `test_windows_development`).

## 2. Check that each side survives the other's restart, live

Verified on 2026-11-06 through the keeper's `Restart`: restarting the
assistant left the desktop's process running and its link reconnected to the
new assistant, and restarting the desktop left the assistant running and the
new desktop connected. Still to watch by eye: the bar showing "reconnecting"
then replaying the canvas, and an agent task continuing through a desktop
restart.

## 3. Replace enum `kind` fields with one type per kind

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

Take one type per session, `WorkSource` first.
