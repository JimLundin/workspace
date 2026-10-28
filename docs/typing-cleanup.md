# Typing and suppression cleanup, 2026-10-28

Workspace source and consumed local stubs contain no Pyright/Mypy suppression
comments, `noqa` comments, `TypeAlias` declarations or `io.open` calls. Aliases use
the native `type` statement. Path-based file owners use `Path.open`; descriptor
locks keep `os.open`. Vendored typeshed remains upstream code, including its own
suppression comments and compatibility declarations.

File-wide Pyright disables and Mypy overrides were replaced with typed native
prototypes, explicitly declared native fields, small consumed dependency stubs,
and validated JSON/SDK observations. Unknown data stays `object` until validated.
SDK history materializes validated one-shot content iterators so follow-up
requests retain the assistant answer and tool results. Fixture casts stay narrowly
scoped in tests. Existing unrelated production typing escapes remain migration
debt under AGENTS.md; this change removes checker suppressions throughout source.

Former lint comments were resolved by module-level imports, named typed
callbacks, extracted widget/lifecycle operations, and explicit dependency naming
configuration. The Python 3.12 bootstrap owners `keeper.py` and `selfcheck.py`
retain narrowly configured inline-import exceptions: candidate/runtime imports
must occur after activation. Protected runtime validation is unchanged.

Keyboard character mapping uses virtual-key values, preserving the letters I and
O after giving their enum members unambiguous names. Native measurements used
100,000 events over five rounds with GC enabled. Before/after median p50, p95,
p99, traced memory and collection evidence are recorded below. The keyboard
process continued to avoid importing the assistant. These shared-desktop timings
are evidence against a regression, not a precise speedup claim.

| Synthetic keyboard measurement | Before | After |
| --- | ---: | ---: |
| Median p50 | 6.2 µs | 4.3 µs |
| Median p95 | 16.3 µs | 11.1 µs |
| Median p99 | 33.0 µs | 15.3 µs |
| Traced peak / retained | 1,943 / 1,016 bytes | 1,943 / 1,016 bytes |
| Collections during latency measurement | 0 | 0 |

The focused notification-filter campaign detected four of five mutations, with
no timeouts or errors. The remaining mutation changes the standalone `Response`
filter; current `observe` construction always places responses inside a `Turn`,
so that branch is unreachable from its caller. One behavioral regression checks
completed-turn source/search filtering and active-turn reachability. No test of
the impossible standalone response was added.

Integration joined `investigate/qt-stalls` at `7e24d3f` to current main. Comparing
the final toolbar commit against main showed identical runtime behavior and
tests, with only obsolete relative imports/bootstrap interfaces differing; the
final handoff ledger was already identical. The ancestry merge retains current
source rather than replaying stale snapshot artifacts. Typing and pending
test-runner commits were rebased onto that merge before combined validation.
