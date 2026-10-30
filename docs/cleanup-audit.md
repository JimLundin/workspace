# Dependency and unused-code audit

Reviewed on 2026-10-29 using the native Windows Python 3.15 environment,
project import graphs, repository references, installed dependency metadata,
Ruff linting and Ruff formatting.

## Dependencies

Removed the unused `PySide6-WebEngine` runtime root and its exclusive
`PySide6-Addons` dependency. Repository imports and installed distribution
ownership confirm every consumed Qt module (Core, Gui, Widgets, Svg and Test)
belongs to `PySide6-Essentials`. Browser automation uses system Edge/CDP;
the embedded canvas belongs to Shared Workspace. Removed the retired WebEngine
renderer executable exemption from the bundle builder and replaced its test
with the current dependency extraction policy.

The remaining 49 locked packages are reachable from the used runtime roots
when Windows/Python markers and requested extras are evaluated. HTTPX and HTTPX2
are both required: Workspace's weather adapter uses HTTPX; the pinned
agent SDK requires HTTPX2. The interpreter pin stays unchanged; the reduced
dependency lock requires a rebuilt runtime bundle.

The rebuilt bundle removes 1,366 runtime files (432.4 MiB installed), shrinking
the final Downloads ZIP by about 164 MiB. The interpreter and every retained dependency
file have identical bytes; only the runtime wheel manifest changes.

`openai` and `pydantic` are imported directly by Workspace but were available
only through the agent SDK's transitive requirements. They are now declared
explicitly at their already bundled versions. This changes no runtime pin or
bundle footprint. Markdown, browser WebSocket, Qt, Windows SDK, Hypothesis and
Watchdog imports all have current product or development owners.

Removed `requirements/windows-py312.lock`: the sole interpreter pin selects
Python 3.15, and bundling derives its lockfile name from that pin. The bootstrap
still supports launching from system Python 3.12; it activates the bundled 3.15
runtime rather than consuming a 3.12 dependency environment.

## Unused code removed

Repository references confirmed these declarations have no callers:

- `assistant.app.pythonw`: superseded by the keeper's process launcher.
- `assistant.widgets.GestureHandle`: unused pointer-gesture widget.
- `winapi.desktop_shell.AppBar`, `Hotkeys`, and `Thumbnail`: retired desktop
  adapters, along with their structures, native bindings and constants.
- `winapi.system.ask_yes_no` and `set_event`: unused native wrappers and their
  exclusive bindings/constants.
- `winapi.windows.is_cloaked`, `client_size`, and `dark_titlebar`: unused public
  helpers and exclusive native bindings. Window enumeration still uses its
  private cloak check.

Removed the obsolete quality-migration entry for `GestureHandle.__init__`.
Package initializers, native callbacks and executable modules require review
beyond reference counts. `assistant.taskbar_guard` has no ordinary importer but
is launched with `python -m` by `launch_recovery_guard`; it remains necessary for
the currently owned taskbar-hiding behavior.

## Formatting and remaining debt

The initial configured Ruff lint passed, while formatting was broadly unapplied.
Applied Ruff's safe fixes and formatting across product code, scripts, tests and
consumed local stubs. Existing marked keyboard grids remain intact; vendored
typeshed remains excluded. The formatting pass preserved parsed code structure
after normalizing docstring indentation. Explicit helper removals, dependency
packaging and the combined feed-context feature were reviewed separately.

`Dev.cmd format` now uses the same Ruff configuration as CI's new formatting
check. VS Code recommends Ruff and formats Python on save with that extension.

The initial cleanup left a 264-entry signature/import migration baseline and six
architecture migration exceptions. The next migration phase below records the
implemented changes; formatting alone does not resolve this design debt.


## Combined feature review

After the concurrent feed-context feature completed, the two review axes found
remaining typed-boundary and refresh issues. Feed replies, public snapshots,
handoff receipts and encrypted state now retain immutable typed shapes until IO.
Automatic quiet assessments reconsider changed context; explicit user quiet
stays handled. Both full type checkers cover the combined tree.

The full native source check passed 1,130 tests with zero failures and five
skips; the 103 focused integration checks passed too. The two generated
quiet-refresh decision mutations were caught. Ruff lint/format, Mypy and
Pyright passed. Existing explained migration debt remains as documented above.

The rebuilt bundle's full protected selfcheck passed 1,122 tests with zero
failures and three skipped modules. Deployment staging coverage now uses a
real isolated Git checkout rather than assuming bundles contain `.git`.
An intermittent Edge screenshot failure passed three isolated repetitions
and the final full bundle run; the browser adapter was unchanged by cleanup.

Paired Windows Python 3.15.1 synthetic keyboard runs used five 100,000-event
rounds with GC enabled. Median event latency was 5.0 → 4.9 µs and median p99
was 22.5 → 20.4 µs. Both retained the same 1,943-byte traced peak, zero measured
GC collections and no assistant imports. The engine/hook/request-model AST is
unchanged; these noisy timings establish no speedup. Reports are retained in
Windows Temp as `workspace-cleanup-keyboard-before.json` and
`workspace-cleanup-keyboard-after.json`.

## Migration implementation

The next phase makes 48 Boolean-bearing signatures keyword-only, including
protocol implementations, native host adapters and their callers. Boolean fields
in 38 record types now require named construction too; positional match patterns
were adjusted alongside their constructors. Removed all 49 FBT001/FBT002 baseline
findings and eight stale oversized-signature entries. The baseline now has 207
entries: 204 oversized signatures and three bootstrap inline imports.

All six original architecture migrations are implemented. Pending input records
are replaced under the mailbox lock, and overlay and Windows-key transitions
return immutable observations to their effect owners. Overlay preferences and
positions use strict typed Pydantic IO. Its placement helper takes a real width/
height pair, and numeric argument bounds take a minimum/maximum pair, reducing
both interfaces to three inputs.

Conversation history now has one execution-owned storage handle retaining
immutable validated item bytes. SDK reads parse fresh collections, and existing
screenshot trimming and volatile reasoning retention remain at the SDK boundary.
Tool schemas and arguments retain immutable validated bytes too, with explicit
Pydantic conversions in the HTTP/SDK and effect adapters. The generic tool
argument getters and manually declared tool contracts still need a separate
typed-contract migration. Browser/storage/bootstrap typing escapes and the
remaining wide signatures also remain debt; the architecture checker cannot
establish their complete interface design.

The remaining architecture exceptions describe specific necessities: measured
keyboard engine/modifier state, private SDK streaming buffers, native OSError
inspection and protected test-origin inspection. None is a migration exception.

Paired Windows Python 3.15.1 measurements used five 100,000-event rounds with GC
enabled. Engine median latency was 6.1 → 5.8 µs and median p99 was 28.1 → 25.4 µs;
traced peak live memory was 1,943 → 2,191 bytes. Actual Windows-key dispatch with
native structure reads and inert forwarding/Qt effects measured 4.0 → 6.5 µs
median and 10.4 → 22.1 µs median p99; traced peak was 672 → 1,056 bytes. Both
paths had zero measured GC collections; the keyboard imported no assistant code.
Worst observed events were 15.752 → 11.732 ms for the engine and 13.200 →
17.983 ms for dispatch. Shared desktop/CPU load varies; these establish no
speedup or bound on OS scheduling. The immutable dispatch adds small per-event
allocation, without copying the keyboard engine's buffers. Reports are retained
in Windows Temp as `workspace-migration-keyboard-paired-before.json`,
`workspace-migration-keyboard-after.json`,
`workspace-migration-shell-paired-before.json` and
`workspace-migration-shell-after.json`.

The combined migration/component-restart checkpoint passed 1,142 native tests,
with zero failures and five skips, plus full Pyright/Mypy and global Ruff lint/
format. Stage `workspace-source-1793259180827585400` verified Downloads source and
ZIP with unchanged runtime directories: 48.433 seconds overall and 22.894 seconds
of one-time full outage. A live assistant restart preserved the keyboard,
automation worker and keeper identities while replacing the assistant.
Ruff explicitly enforces LF alongside the project-wide formatting policy.


## Boundary and bootstrap follow-through

The boundary batch removes another fifteen migration entries: dated activity and
retention interfaces, HTTP request parameters, Teams Graph calls, panel placement,
interpreter/launch observations, the process/window target, and all three bootstrap
inline imports. The former keeper message prototype is now an explicitly reviewed
fixed Win32 interface; its native implementation and end-to-end fixture preserve
the same ABI. The catalog contains 191 migrations and three reviewed fixed
interfaces. Its reporting distinguishes those two kinds, and interface status
cannot grant Boolean/import exceptions or cover a changed signature.

The saved panel monitor hint and activity context now use typed Pydantic contracts.
Retired pin/dock/transparency/rail options, unused preference saving and geometry
helpers, their test-only coverage and the unused view `remember` flag are removed.
Teams POST payloads have separate chat-creation and plain-text-message contracts.
The keeper no longer asserts a DLL interface with `typing.cast`; native prototypes
carry pointer-sized HWND/WPARAM/LPARAM values. Candidate runtime selection is
explicit at selfcheck, and launcher composition owns the singleton lock and Qt.
Standard-library bootstrap JSON remains necessary before bundled dependencies
can be loaded or trusted; it uses structural validation rather than casts.

The broader manual tool contracts, browser/CDP, durable storage, console/IPC and
Teams authentication/reply shapes still require migration. Exact remaining wide
signatures are reviewed individually against their callers; real domain concepts
are grouped, while required ABIs and independent effect dependencies retain a
specific explanation. Verification receipts and paired keyboard measurements are
retained in Windows Temp for each completed deployment.

The deployment ownership correction was verified separately in stage
`workspace-source-1793260657874256300`: an unchanged-source sync retained all four
core identities and readiness markers, refreshed the ZIP and preserved the
runtime, with 37.407 seconds overall and zero keyboard outage. Preserved local
pytest/Ruff caches no longer count as deleted managed application assets.

The final panel review retained only the saved monitor hint consumed by the
floating conversation. Missing, malformed or invalid coordinates select the
default monitor; preview and native fixtures still supply explicit bounds.
Both seeded quality-classification mutations were killed by the existing policy
regressions (two killed, no survivors/errors/timeouts).

Native Windows Python 3.15.1 keyboard evidence for this batch is in Temp as
`workspace-boundary-keyboard-before.json` and
`workspace-boundary-keyboard-after.json`. Five 100,000-event rounds kept GC enabled.
The engine and hook source hashes are unchanged; only keeper/runtime changed in
the benchmarked source set. Traced peak stayed at 2,191 bytes, with zero collections
and no assistant imports. Median event latency was 12.1 → 6.3 µs; median p99 was
103.6 → 27.7 µs; worst observed latency was 57,565.1 → 32,753.4 µs. Desktop load
varied substantially, so these timings establish no speedup or native hook
latency guarantee. Native integration checks cover the actual boundaries.

Python 3.12 is still the registered system interpreter on this machine; Python
3.15.1 is private to Workspace's bundle and development environment.
`StartWorkspace.cmd` launches bundled 3.15 directly. The standard-library-only
bootstrap remains parseable on 3.12 so existing `.pyw` file associations can hand
off to that same bundled interpreter; application code and dependencies run on
3.15. This is a launcher constraint, not a second supported application runtime.
