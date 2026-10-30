# Qt event-loop stalls, 2026-10-28

The subsequent [prioritized pause inventory](qt-ui-pause-inventory.md) separates
toolbar geometry, long-reply formatting/GC, feed replacement, first use and
unattributed delays. It retains repeated native timing evidence and concrete
next actions. This feed fix has been rebased onto private snapshot `1a1cafe` of
the coordinating agent's test-speed work; the shared checkout remains untouched.
The [fixed-event delay ledger](workspace-ui-delay-ledger.md) records subsequent
toolbar changes and total measured stall excess across the inventory workloads.

The assistant can stall its entire Qt thread when the personal work feed changes.
The confirmed cause is repeated source projection before rendering: each proposal
rebuilds the complete evidence and application-origin indexes. Notification
projection then builds those proposals again for the side feed. Handling scans
also reconstruct a Windows update's identity for every handling record.

This investigation and fix are isolated in `workspace-qt-stalls`, on branch
`investigate/qt-stalls`. The starting source snapshot is `d8d4956`; it includes the
current uncommitted UI work, including retained bubble surfaces and the background
audio meter. The shared checkout and Downloads deployment were not modified.

## Reproduction and measured cause

Measurements used native Windows CPython 3.15.1 and Qt 6.12 with GC enabled.
Fixtures contain fictional content and stay below Workspace's existing limits:
100 source updates, 300 handling records and 20 proposals. The microphone,
keyboard hooks, taskbar recovery and communications collection were not started
by the UI fixture. The existing preview composes real views through their regular
constructor inputs.

The focused pure reproduction invokes `assistant.notifications.observe` three
times with that snapshot. It asserts a median below 50 ms and failed on the
starting source:

| Notification projection | Median |
| --- | ---: |
| Starting source | 2,847.51 ms |
| Shared indexes, initial validation | 14.09 ms |
| Final native `frozendict` implementation | 9.05 ms |

The original notification projection rebuilds evidence 40 times for these 20
proposals. Its cost is incurred on the Qt thread, before text measurement,
painting or native glass composition. The fixture exercises retained handling
records whose identities match a source but whose revisions have since changed;
the updated source must remain pending.

A separate real-Qt replay changes the same feed and proposal board, measuring an
unrelated precise 10 ms timer. On the starting source the maximum timer gap was
3,035.46 ms, including a warmed gap of 2,993.94 ms. The nominal seven-second run
took 10.94 seconds because work delayed event delivery. The fixed initial replay
had a warmed maximum of 20.12 ms. First-use native setup still caused a 321.14 ms
gap in that fixed run; this change does not remove first-use rendering costs.
The final native `frozendict` replay had a 51.16 ms warmed maximum and a 490.96 ms
first-use maximum. It missed the strict 50 ms diagnostic budget by 1.16 ms;
the multi-second projection stalls were removed, while native setup and some
frame delays remain. Absolute timings vary on the shared Windows desktop.

A read-only 20-second sample of the actual deployed assistant found the same
path: 925 of 1,228 successfully captured main-thread stacks were inside proposal
construction. The sampler missed 38.6% of attempts, so those counts identify a
real active path but should not be interpreted as precise CPU percentages or
the duration of an individual stall. The capture contains stack locations only.

## Change and ownership

`feed_items.proposal_index` creates one immutable snapshot of evidence and
projected work items. `proposal` consumes that explicit evidence mapping; origins
are captured on the assessment itself. `notifications.observe` passes its projected work items into the source
feed observation, so attached agent turns and side-feed cards share the same
validated candidate objects. Direct source-feed observation builds its own index
once when no projection is supplied. Indexes use Python 3.15's native `frozendict`.
There is no cross-snapshot cache or shared mutable state.

`Feed.pending_update` computes the current update's identity and revision once
before examining handling records. Exact source identity and revision remain
the dismissal policy. Existing stale-revision and mixed-source tests retain
their role.

Pyright 1.1.414 is the latest release on both package registries but ships an
incorrect native constructor initializer. Both checkers use the supported
[Python 3.15 typeshed override](../typings/.workspace-typeshed/README.md), preserving the
upstream standard-library contracts with that single declaration corrected.

The new regression exercises the real notification projection with several
proposals, shared evidence and an attached agent turn. It failed before the fix
because the turn and another proposal reconstructed the same candidate. It
asserts that they retain the same immutable evidence object and that all exact
source content and attachment identities survive. It uses no mocks or patches.
Python's frozen mapping and hashing implementations are trusted upstream.

## Other measured costs

An idle preview's 10 ms timer had a maximum gap of 17.47 ms. Streaming a small
reply alone stayed below 50 ms. Changing only voice state stayed below 50 ms in
its timer measurement, with native glass making each state update slower.
Changing toolbar capsule composition repeatedly produced 200–490 ms pauses;
one instrumented seven-second run rebuilt 67 native composition paths.

Exploratory glass, synchronization and event-pump variations did not eliminate
those toolbar stalls. In particular, simply removing `processEvents()` worsened
responsiveness. No such runtime change is part of this fix. Further toolbar work
needs its own native reproduction and interface design. This investigation
establishes a whole-thread feed stall and fixes its repeated projection cost;
it does not attribute every desktop pause to that cost.

## Validation and handoff

The native editing check passed 51 tests across feed projection, notification
policy, handling, native feed interaction and bubble lifetime. Ruff and strict
Pyright checks passed for the changed modules. Four focused mutations were
detected: removing the shared projection handoff, changing source-identity
matching, changing revision matching and combining those decisions with `or`.
Both campaigns had passing baselines and no survivors, timeouts or errors.

The subsequent full native run completed with 1,115 passed, two failed and six
skipped. The attached-browser screenshot test passed on a focused retry but
failed again when combined with the affected feed checks; its fixture is unstable. The
fictional Teams reconnect fixture failed again; the same test failed at the same
reconnect call on the untouched starting snapshot. Its browser implementation
and fixture files match that snapshot byte-for-byte. This is a known baseline
failure, and no passing full-run receipt is claimed. The final receipt selects
the affected feed/native tests. Browser fixture failures remain recorded outside
that receipt's explicit scope.

Strict Pyright reports zero errors and warnings for all three changed runtime
modules. Strict Mypy reports no issues for the changed feed-projection module.
The typeshed copy was compared with its upstream source: only `builtins.pyi`
differs, by removal of the incorrect initializer declaration.

Task-owned probes and raw records live in Windows Temp:

- `workspace-qt-stalls-probes/_feed_stall_probe.py`: focused pure reproduction.
- `workspace-qt-stalls-probes/feed_ui_probe.py`: real Qt replay, with ordinary
  constructor inputs and no dependency patching.
- `workspace-qt-stalls-before`: frozen starting source for differential runs.
- `workspace-feed-ui-before.json`, `workspace-feed-ui-after.json`: timer evidence.
- `workspace-qt-projection-mutations.json`, `workspace-qt-handling-mutations.json`.
- `workspace-ui-live-stacks.txt`: read-only live sampling evidence.

Run a saved probe from this worktree in native PowerShell, using the development
interpreter and `runpy.run_path(..., run_name='__main__')`; the UI probe takes
`before` or `after` as its first script argument. Its source imports resolve from
the current directory. For the differential starting run, change the current
directory to `%TEMP%\workspace-qt-stalls-before` while keeping the same native
interpreter and runtime dependencies.

Deployment is intentionally left to the agent coordinating the shared checkout.
Apply only the final fix commit, rather than the two source-snapshot commits.
Recheck and issue a receipt in the receiving checkout before deploying its
combined source.
