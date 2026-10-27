# Checking and deploying small changes

The active checkout is `C:\Users\Jim.Lundin\Projects\workspace`. Run native
commands from that directory in PowerShell. `Dev.cmd` uses the Windows `.venv`,
adds native Git to PATH and activates the installed dependencies. The virtual
environment uses the existing Python 3.15.1 interpreter; development tools live
in its own site-packages. Qt 6.12 and application dependencies are reused from
the installed `.runtime` through a local `.pth` file. Neither runtime folder is
copied or rebuilt for development. Keep the Downloads client separate so edits
and test execution do not replace files in a running application.

`/home/jim/workspace` links to the active Windows checkout. The previous Linux
tree is preserved at `/home/jim/workspace-linux-reference`; use Windows tools for
ongoing work. The same eighteen native checks took 34.8 seconds from WSL source
and 13.3 seconds from identical Windows-local source in a paired measurement.

```powershell
.\Dev.cmd check --tests tests/test_feed_triage.py tests/test_windows_feed.py --receipt "$env:TEMP\workspace-check.json"
.\Dev.cmd deploy --check-receipt "$env:TEMP\workspace-check.json"
.\Dev.cmd lint assistant/feed_triage.py
.\Dev.cmd typecheck assistant/feed_triage.py
```

## Edit loop

Every `Dev.cmd check` first runs the source architecture review, including when
`--tests` selects individual behavioral checks. The review parses source without
importing the application. It enforces transitive keyboard isolation, immutable
dataclass defaults, concrete mutable-field and reflection restrictions, and exact
explained exceptions declared in `pyproject.toml`. Existing migration exceptions
are followed by the development Ruff signature gate: new Boolean positional
declarations block checks, and new interfaces over three inputs produce review
warnings. The gate also rejects new aliased imports, inline imports and direct forwarding exports.
Read [code-quality-policies.md](code-quality-policies.md) when changing a
signature or its exact migration entry. Architecture migration exceptions
are printed as cleanup debt. A policy failure stops before tests or a receipt.
The full protected selfcheck also exercises the review through its ordinary flat
test discovery. Source discovery and the class-slots policy recurse into nested
modules without scanning interpreter/dependency folders; deployed copies need no
Git checkout. Static checks do not prove deep immutability through arbitrary
aliases or objects, mathematical purity, or external-data validation; those also
require type checking and review under the policy in `AGENTS.md`.

Test review starts with the Workspace decision, policy or ownership failure a
case can detect. Direct Python/dependency behavior is outside the test surface.
The class-slots check enforces our declarations; native bundle and Qt startup
checks verify our selection and initialization order. Those remain owned
contracts even though their fixtures use Python and dependencies. Disposable
browser fixtures explicitly remove their profiles after closing the browser,
with a short bounded retry for late native file release; persistent cleanup
failures remain failures.

Generated tests live in `tests/properties/` and use the pinned `test` extra
(`python -m pip install -e ".[test]"` in the development environment). Editing
selection includes these nested modules through the same source dependencies;
CI runs them in addition to its existing protected selfcheck. The installed
selfcheck retains its flat suite and needs no Hypothesis runtime dependency.
Read [property-testing.md](property-testing.md) for the underlying-library
decision and property scope. Focus a campaign with, for example,
`Dev.cmd check --tests tests/properties/test_pcm.py`.

Consumed dependency declarations live in `typings/` and are loaded by both type
checkers. The editing runner validates native result schemas, and the release
file boundary validates record and hash schemas through the existing Pydantic
dependency. Bundle pins are validated as a frozen release record. These changes
replace casts in those boundaries; no custom type-assertion predicates are used.
The architecture configuration and complete native release receipts are validated
through consumed schemas too. Module-level lazy imports defer test machinery and
Windows-only effects until use, preserving the staged coordinator's import order.
The runner filters discovered test functions lazily and checks their origin and
supported signature before invocation. Broader legacy typing escapes remain
cleanup debt under the policy in `AGENTS.md`.
Failure and timing accumulators stay private to the execution owner; published
check results are tuples, including the validated native handoff.

1. Run `Dev.cmd check`. It compares source with the last
   deployed manifest and selects test modules through transitive Python imports,
   including relative imports, package initialization, static dynamic imports,
   test fixtures and deleted modules. Bootstrap/configuration/pin changes,
   application assets and a missing baseline fall back to the full source suite.
2. During implementation, narrow further with `--tests tests/test_feed_items.py`
   (or multiple files). A specific check can be selected with
   `tests/test_windows_runtime.py::test_shutdown_resolves_pending_and_late_ui_requests`.
   This is an explicit editing scope; it does not claim a
   full check. Run affected Windows integration tests sequentially on the installed
   interpreter when the change touches native behavior. `--native` includes those
   modules in the selection. From WSL it runs the selection once on the installed
   Windows interpreter automatically; no Git checkout in Downloads or temporary
   manual harness is needed. It never enables the opt-in desktop E2E suite.
3. After final edits, write a receipt with
   `Dev.cmd check --receipt "$env:TEMP\workspace-check.json"`.
   For a broad change use `--full`; the full source profile still compiles and
   imports every module. `--full --native` is the full native profile on Windows.
   CI and the keeper continue to run protected `selfcheck.py` with their existing
   full coverage. The editing receipt does not bypass the keeper's gate.
4. Deploy with
   `Dev.cmd deploy --check-receipt "$env:TEMP\workspace-check.json"`.
   The receipt must match every source byte in the Git-listed working tree.
   Tests that change source, edits after checking and edits during staging or
   deployment prevent a success claim. Select meaningful tests for the change;
   a source-bound receipt establishes the stated coverage, not unrun tests.

Retired standalone notification, manual-inbox/history and native canvas UI
implementations, embedded canvas assets and their UI tests are removed. History uses the same floating
feed; console answers and approvals are tested through that feed. Shared panel controls and vector icons have independent modules. Current
work/meeting tools and their domain checks remain. GUI fixtures
suppress unnecessary foreground activation and leave the user's application alone.

## Mutation checks

Use focused mutations to assess decisions changed by a refactor:

```powershell
.\Dev.cmd mutate assistant/work_service.py --function submission_matches --tests tests/test_work_submissions.py --workers 1 --output "$env:TEMP\workspace-mutations.json"
```

The runner freezes source in disposable copies, requires a passing baseline,
and stops each mutant at its first failing test. Timeouts and collection errors
are reported separately from detected mutations. Choose the tests that exercise
the changed decision through its callers. Review survivors for missing scenarios,
redundant checks and equivalent behavior before adding tests. Keep reports in
Temp; test setup should batch large fixture catalogs instead of repeating
already-covered creation transactions.

## Source deployment

The coordinator creates a fresh `workspace-source-*` directory in Windows Temp.
It stages all source and validates hashes, unchanged runtime pins and ZIP paths.
It builds verified source/ZIP backups and a new ZIP while Workspace keeps running.
The new ZIP copies compressed runtime records byte-for-byte and writes a fresh
central directory. It replaces source records rather than accumulating stale
entries. Runtime decompression/recompression is absent from routine ZIP updates.

The first run audits runtime bytes against the old bundle. Later runs reuse that
audit only when the complete bundle SHA-256 and every runtime file's membership,
size and stat timestamps match the saved audit. A
changed observation forces another byte audit; pins changing require bundle.py.
This is a local performance cache, not a defense against deliberately forged
filesystem timestamps. Runtime folder identities are checked and never replaced.

After preparation, the native watcher proves the installed keeper/child group,
retains exact process handles, requests normal WM_CLOSE and checks clean exits.
It preserves the separately owned Edge connection host. Windows venv launchers
can report their shared base interpreter's executable path. The native CLI runs
one coordinator inside the verified staging cwd, with source checks before and
after. Only the exact Workspace development venv's VS Code Black language-server
command under the user's installed extension directory is also exempt from the
production process group; unrelated Python commands remain blocked. There is no PowerShell
startup per poll. With replacement locks held, it rechecks the baseline, replaces
only changed managed files, removes retired managed files, clears their bytecode
and verifies the replaced source. It launches immediately afterward. The prepared
ZIP is rechecked and atomically published after fresh visible readiness, keeping
archive I/O outside the interruption; final ZIP/runtime verification follows.
Installed-source receipts explicitly mark the ZIP as pending until publication.

A stopped copy stays stopped. Partial replacement failures before launch restore
verified before-images and conditionally relaunch the previous copy. Errors
following a launch preserve evidence and backups for inspection; they never
overwrite an active installation. A process crash cannot resume a used stage;
inspect its receipts/backups rather than blindly rerunning it.

Receipts include clean exits, changed/removed files, fresh readiness markers,
child identities, content-free lifecycle phase timings, runtime preservation, archive hash and per-phase timings.
`timings.json` measures outage from WM_CLOSE to verified readiness. A completed
stage can be reverified with `scripts.deploy verify --stage <WSL stage path>`.
Use `scripts/bundle.py` for runtime pin changes, not routine source edits.

## Measured baseline

The last three deployments through the former temporary helper took 256–335
seconds overall and 78–128 seconds from WM_CLOSE to verified readiness. The latest
was 334.78 seconds overall with 90.41 seconds of outage. Preparation repeatedly
inflated, hashed and recompressed the unchanged runtime; later phases repeated
runtime/ZIP audits, and each process poll launched PowerShell.

The new native inventory measured 0.033–0.059 seconds on the running installation.
The first focused check measured 4.57 seconds for eleven regression checks.
Before baseline-manifest reuse, the same focused check spent 21.21 seconds mainly
reading hundreds of deployed files across WSL. Runtime audit and source manifests
now live under `%LOCALAPPDATA%\workspace\deployment` after a verified deployment.

The final measured source deployment after native Python 3.15 lazy imports took
45.48 seconds overall, including 17.81 seconds of preparation, 4.68 seconds of
shutdown, 2.72 seconds of replacement, 17.51 seconds to visible desktop readiness
and 2.76 seconds of final verification. Outage was 24.79 seconds, versus 90.41
seconds previously. This run also corrected the bar readiness target to the
actual "Workspace floating bar" window. Application imports fell from 25.95 to
0.10 seconds; desktop glass initialization still adds first-use work. Qt's eager
ThreadPoolExecutor initialization order remains intact.

Full native SDK smoke checks remain expensive: a focused runtime-module run
spent 51 seconds in its explicit copied-source SDK initialization check. Select
individual lifecycle/appearance functions when that is the changed contract;
retain the SDK checks for runtime changes and full CI. Runtime metadata now uses
Windows directory-enumeration observations instead of opening each file to read
its ID (1.17 versus 4.61 seconds); runtime root IDs remain separately verified.
Pure filename validation is cached; filesystem/link checks are always fresh.
