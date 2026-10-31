# Checking and deploying small changes

The active checkout is `C:\Users\Jim.Lundin\Projects\workspace`. Run native
commands from that directory in PowerShell. `Dev.cmd` uses the Windows `.venv`,
adds native Git to PATH and activates the installed dependencies. The virtual
environment uses the user-installed Python 3.15.1 interpreter; development tools live
in its own site-packages. Qt 6.12 and application dependencies are reused from
the installed `.runtime` through a local `.pth` file. The dependency folder is not
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
.\Dev.cmd format assistant/feed_triage.py
.\Dev.cmd format --check .
.\Dev.cmd typecheck assistant/feed_triage.py
```

## Edit loop

Ruff owns Python formatting as well as linting. Run `Dev.cmd lint --fix .` for
safe lint fixes and `Dev.cmd format .` for repository-wide formatting; CI checks
both. VS Code uses the Ruff extension for Python format-on-save. Existing
`fmt: off`/`fmt: skip` regions preserve keyboard grids and intentional tables;
vendored typeshed remains excluded by the shared Ruff configuration.
Launchers and runtime activation use the same Python 3.15 Ruff target as the
application. Windows `python`, `py` and `.pyw` associations select the user-installed
3.15 interpreter; `StartWorkspace.cmd` selects it with `pyw -3.15`.
The Downloads installation and ZIP contain no private interpreter. No launcher starts an older Python and hands off to another process.

For continuous feedback, install the small development-only watcher once:

```powershell
.\.venv\Scripts\python.exe -m pip install watchdog==6.0.0
.\Dev.cmd watch --tests tests/test_bar_model.py
.\Dev.cmd preview
```

`watch` runs affected tests by default, including native tests on Windows.
`--tests` accepts the same files and `::test_function` selectors as `check`;
`--source-only` omits native modules from automatic selection. Saves are debounced
and checks run sequentially in fresh processes. An edit during a check queues the
latest source; failures and superseded checks keep the previous successful session
baseline. That baseline lives in Windows Temp, separately from the deployed
manifest, and is removed when the watch session ends. Finish with the ordinary
source-bound final check and deployment commands below.

`preview` watches and restarts real toolbar/feed widgets with sample data and
inert actions. Its selector retains the sample state across restarts. It starts
no keeper, microphone, keyboard observer, live communications or taskbar recovery
worker. The preview's native-only menu actions are inert too. Closing the preview
control window or pressing Ctrl+C closes its views and stops the watcher.
Use `Dev.cmd preview --preview toolbar` or `--preview feed` to narrow the surface;
`Dev.cmd watch --preview both` combines checks with a preview. Saves to production
Python/UI assets restart the preview; test/docs saves only trigger checks.
Watch and preview tasks are also available in VS Code. These development processes
are separately classified so they can coexist with source deployment.

Editing checks cache immutable per-file policy findings and import dependencies
under `%LOCALAPPDATA%\workspace\development\analysis`. Keys bind source content,
file identity, checkout, Python/Pydantic versions, analysis code and project
configuration; quality keys also bind fresh Ruff diagnostics. Whole-graph keyboard
ownership, model membership, migration baselines and exact exceptions are still
evaluated every run. Source hashes are still checked before and after execution.
Missing/damaged cached records are recomputed. The protected full selfcheck uses
no disk cache; CI coverage and runtime pins are unchanged. Shared bounded AST
parsing and grouping Ruff diagnostics also reduce work in the first analysis.

The native editing coordinator reviews source once, before handing test execution
to a child that owns desktop isolation. The child can relaunch without repeating
the policy gates; initial/final hashes and the validated result still bind the
success receipt. A check already on the verified private desktop executes
directly, so watcher checks avoid an extra executor startup. Generated domain checks run before the editing runner's broad
dependency import review. The isolated desktop observer defers the native SDK
until it is needed by the launcher. Hypothesis examines loaded modules for
constants; loading the complete
native SDK first also feeds bundled dependency sources into that work. Compilation,
the complete broad import review and final source binding still run. This reduces
one setup cost; native process/browser fixtures remain expensive.
The broad editing import phase resolves the required SDK before Qt can inspect
its new dependency sources. This applies only when that phase already imports
all production modules; narrow/Qt-only checks do not acquire the SDK. The
protected import gate remains unchanged and import failures still block.


Every editing check that reaches execution retains full cost evidence, including on test or
import failure, under `%LOCALAPPDATA%\workspace\development\timings\check-*.json`.
Use `--timings "$env:TEMP\workspace-cost.json"` to choose the destination. Reports
contain source identities, the selected scope, all phase/test-module import/test
body durations, counts and unattributed overhead. Bodies include fixture setup
and cleanup. Evidence excludes source/response content
and exception messages. It is separate from the success-only deployment receipt.
Runner startup before its timer, report-writing cost, early preflight failures
and interrupted processes are outside this accounting. See the [full-suite investigation](test-speed-investigation.md)
for measured portable costs and the limits of current full-run attribution.

Broad native editing checks run twenty-nine explicitly reviewed isolated test modules
through four standard-library process workers before the single sequential
desktop-test lane. Their private files, localhost transports and fake desktop
adapters allow that overlap; [execution ownership](test-execution-ownership.md)
records the additional resource review; new modules stay sequential until reviewed.
All native fixtures and the strict overall-deadline HTTP
module run after the workers exit, avoiding contention during provider startup
and short elapsed budgets. Properties still run first, before SDK/native imports,
and narrow editing checks
keep their existing executor without worker startup. Workers finish and exit
before source validation and any deployment. The protected full gate is unchanged.

Worker module/body durations use the `worker:` prefix and may overlap parent
spans. `worker_seconds` is aggregate child work, not elapsed time; unattributed
overhead excludes those overlapping spans. Parent phase/body durations remain
nonoverlapping. The paired 152-function worker benchmark took 123.49 seconds
with one worker and 60.86 seconds with two, including startup and shutdown.

Every `Dev.cmd check` first runs the source architecture review, including when
`--tests` selects individual behavioral checks. The review parses source without
importing the application. It enforces transitive keyboard isolation, immutable
dataclass defaults, concrete mutable-field and reflection restrictions, and exact
explained exceptions declared in `pyproject.toml`. It also rejects patch/mock
frameworks and monkeypatch fixtures across production and test source; explicit
test selections cannot bypass this check. Existing migration exceptions
are followed by the development Ruff signature gate: new Boolean positional
declarations block checks, and new interfaces over three inputs produce review
warnings. The gate also rejects relative imports, new aliased imports, inline
imports and direct forwarding exports.
Read [code-quality-policies.md](code-quality-policies.md) when changing a
signature or its exact migration entry. Architecture migration exceptions
are printed as cleanup debt. A policy failure stops before tests or a receipt.
The full protected selfcheck also exercises the review through its ordinary flat
test discovery. Source discovery and the static data-record declaration checks recurse into nested
modules without scanning interpreter/dependency folders; deployed copies need no
Git checkout. Static checks do not prove deep immutability through arbitrary
aliases or objects, mathematical purity, or external-data validation; those also
require type checking and review under the policy in `AGENTS.md`.

Test review starts with the Workspace decision, policy or ownership failure a
case can detect. Direct Python/dependency behavior is outside the test surface.
The static architecture check enforces frozen, slotted data-record declarations.
Native bundle and Qt startup checks verify our selection and initialization order. Those remain owned
contracts even though their fixtures use Python and dependencies. Disposable
browser fixtures explicitly remove their profiles after closing the browser,
with a short bounded retry for late native file release; persistent cleanup
failures remain failures.
Three explicitly owned browser groups share compatible native lifetimes: managed
DOM/Teams/persistence/cancellation, attached DOM/screenshots/tabs/cancellation,
and sign-in handoff. They use five Edge launches in place of nine. Teams state
and documents reset between scenarios; attached clients detach independently and
their extra tabs/groups are removed before continuing. Required persistence and
mode-change restarts, cancellation, and native ownership assertions remain.
Run the groups with native Python directly:
`python -m scripts.check --native --tests tests/test_windows_browser.py`.
See [browser ownership and timing evidence](browser-test-lifetimes.md). UIA
truncation uses a boundary-sized quote-heavy value rather than 10,000 WPF lines;
short multiline input and independent process readback remain. Pagination
catalogs batch irrelevant verified action rows; important effects and durable
failure/recovery checks still use public writes and independent connections.


Draft policy tests use a fictional command handler with real JSON response files.
One complete draft scenario runs that same handler in a subprocess; other cases
avoid starting Python for every simulated mail operation. The draft identity,
commit ordering, lost acknowledgment, edited/deleted items and recipient checks
still run, including Windows sharing behavior. The blanket runtime slots audit
was removed; Python instance-storage behavior is trusted.

Feed-triage fixtures keep real worker threads, locks and authenticated HTTP
requests. Tests explicitly release debounce steps instead of waiting 1.5 seconds
per step; the local fixture server uses a short idle shutdown poll. The daily
refresh case still exercises the real periodic wake without a new observation.
The fixture supplies the real server adapter and cancellable wait dependency
through `Triage` construction; it does not patch native events or module globals.
Feed context/reply checks use the existing task and context stores, real local
HTTP and the registered agent tools. They verify saved-before-queue ownership,
exact reply retries after restart, stale-item rejection, contextual model wiring
and outcome/answer retrieval. Pydantic's own parsing algorithms are trusted.
Feed-tool cases use the registered tool boundary; the general SDK conversation
scenarios remain in `tests/test_agent.py`.

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
2. During implementation, narrow further with `--tests tests/test_feed_triage.py`
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
feed; approvals are tested through that feed. Shared panel controls and vector icons have independent modules. Current
work/meeting tools and their domain checks remain. Ordinary Windows tests attach
to a private desktop before their fixtures import, so real Qt/WPF/browser windows
do not flash on the user's screen. Native children share that desktop. The
explicit desktop E2E opt-in retains its interactive behavior; selection and the
protected full gate are unchanged. See the [UI ownership audit](native-ui-test-audit.md)
for retained surfaces and the removed unused review dialog. Keep native checks
sequential because other session resources are still shared.

## Mutation checks

Use focused mutations to assess decisions changed by a refactor:

```powershell
.\Dev.cmd mutate assistant/work_service.py --function submission_matches --tests tests/test_work_submissions.py --workers 1 --output "$env:TEMP\workspace-mutations.json"
```

The runner freezes source in disposable copies, requires a passing baseline,
and stops each mutant at its first failing test. Each mutant runs pytest through
`scripts/mutation_session.py`, which activates the bundled runtime and test
desktop with the edit check's own runtime owner and uses its shallow `tmp_path`.
A campaign can therefore select any test that `Dev.cmd check` runs, including
SDK and pywin32 tests. Mutations execute tests, so run them sequentially on the
shared desktop like other native checks. Timeouts and collection errors
are reported separately from detected mutations. Choose the tests that exercise
the changed decision through its callers. Review survivors for missing scenarios,
redundant checks and equivalent behavior before adding tests. Keep reports in
Temp; test setup should batch large fixture catalogs instead of repeating
already-covered creation transactions.

To seed exact mutants instead, list them in a TOML file and pass
`--replacements`. Each `before` fragment must match the source exactly once.
Use literal strings (`'...'`, or `'''...'''` across lines, which drops a
newline right after the opening delimiter), so quotes and backslashes reach
the runner unchanged:

```toml
[[replacement]]
before = 'return "uncertain"'
after = 'return "verified"'
```

```powershell
.\Dev.cmd mutate assistant/action_text.py --replacements "$env:TEMP\seeds.toml" --tests tests/test_action_text.py --output "$env:TEMP\workspace-mutations.json"
```

Fragments never travel on the command line: Windows quoting through `Dev.cmd`
and PowerShell strips embedded double quotes.

## Source deployment

The coordinator creates a fresh `workspace-source-*` directory in Windows Temp.
It stages all source and validates hashes, unchanged Python/dependency pins and ZIP paths.
It builds verified source/ZIP backups and a new ZIP while Workspace keeps running.
The new ZIP copies compressed runtime records byte-for-byte and writes a fresh
central directory. It replaces source records rather than accumulating stale
entries. Runtime decompression/recompression is absent from routine ZIP updates.

The first run audits runtime bytes against the old bundle. Later runs reuse that
audit only when the complete bundle SHA-256 and every runtime file's membership,
size and stat timestamps match the saved audit. A
changed observation forces another byte audit; pins changing require bundle.py.
This is a local performance cache, not a defense against deliberately forged
filesystem timestamps. The dependency folder identity is checked and never replaced.

After preparation, the coordinator computes affected components from both source
versions' transitive imports, including package initialization. Selection compares
managed source: preserved unrelated files such as pytest/Ruff caches do not count
as removed application assets. Assistant-only changes preserve the keyboard and
automation. Shared dependencies restart every
consumer; supervisor/bootstrap and implicit application asset changes require a
full stop. A running keeper without the component-control capability also uses
the full stop, so the first deployment of this feature restarts all components.

The keeper allows assistant and automation up to 60 seconds after WM_CLOSE to
release their owned resources. Assistant cleanup includes a personal-work join
bounded at 20 seconds; a five-second keeper deadline could terminate it before
cleanup completed. Input retains its five-second stop allowance. Deployment
still requires zero exit codes and blocks source replacement after a forced stop.

The native watcher proves the installed keeper/child group and retains exact
process handles. Selective deployment asks the keeper to pause selected children
and verifies their clean exits while retained processes stay unchanged. The keeper
blocks competing update/restart requests until a matching resume. Full deployment
requests normal WM_CLOSE and checks every core process's clean exit.
Windows readers can briefly deny command deletion or acknowledgment replacement.
The protected control owner retries on later ticks and retains committed
acknowledgments, so retries never repeat a pause or restart.
It preserves the separately owned Edge connection host.
Windows venv launchers
can report their shared base interpreter's executable path. The native CLI runs
one coordinator inside the verified staging cwd, with source checks before and
after. Only the exact Workspace development venv's VS Code Black language-server
command under the user's installed extension directory is also exempt from the
production process group; unrelated Python commands remain blocked. There is no PowerShell
startup per poll. With replacement locks for stopped owners held, it rechecks the baseline, replaces
only changed managed files, removes retired managed files, clears their bytecode
and verifies the replaced source. It resumes selected children or relaunches the
full group immediately afterward. Only restarted children require fresh readiness
markers; retained children must keep their exact process identities and marker
timestamps. The prepared
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
`timings.json` measures interruption from the close/pause request to verified
readiness, and records zero keyboard outage when its process is preserved. A completed
stage can be reverified with `scripts.deploy verify --stage <WSL stage path>`.
Use `scripts/bundle.py` for dependency pin changes, not routine source edits.
Removing the retired `.python` installation uses the same full clean shutdown,
verified before-images, managed removal and ZIP publication as a source release.
The coordinator finds installed script roots and descendants even though their
Python executable lives outside Downloads; unrelated Python apps are excluded.

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
