"""Source-bound editing checks. The keeper's protected full gate is unchanged.

python -m scripts.check [--full] [--native] [--tests tests/test_x.py ...]
                       [--receipt /tmp/workspace-check.json]
"""

import argparse
import importlib
import inspect
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable, Generator, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable
lazy from concurrent.futures import ProcessPoolExecutor

from pydantic import TypeAdapter, ValidationError

from scripts.architecture import Report, dependencies, module_name, review
from scripts.check_results import Failure, Results, raised, reported
from scripts.deploy_files import CheckedArchitecture, CheckReceipt, file_at, read, sha, source_map, write, write_receipt
from scripts.development_paths import LIVE, PROFILE
from scripts.source_analysis import Cache
lazy import selfcheck
lazy from runtime import activate
lazy from scripts import quality
lazy from scripts.check_native import execute_native
lazy from scripts.native_desktop import current_name

ROOT = Path(__file__).resolve().parent.parent
BROAD = frozenset({"keeper.py", "components.py", "selfcheck.py", "runtime.py", "workspace.pyw", "config.py", "protocol.py", "pyproject.toml"})
TEST_NAMES = TypeAdapter[list[str]](list[str])
WINDOWS_IMPORTS = ("WinDLL", "WINFUNCTYPE", "windll", "winreg", "msvcrt", "_winapi", "PySide6", "shiboken6", "win32more")
# Reviewed effect owners: fake desktop adapters, private localhost endpoints,
# and per-function temporary stores. These modules never use the shared desktop
# or installed source. Explicit inventory, rather than filename inference, keeps
# new/native tests sequential until their effects have been reviewed.
# Heavier modules lead the queue. Reuse SDK-initialized workers for
# private journal/HTTP/process fixtures too; none acquire native UI or audio.
# docs/test-execution-ownership.md records the reviewed resource owners.
PORTABLE = (
    "tests/test_agent.py",
    "tests/test_meeting_followup.py",
    "tests/test_publishing.py",
    "tests/test_meeting_execution.py",
    "tests/test_architecture.py",
    "tests/test_meeting_workflow.py",
    "tests/test_quality.py",
    "tests/test_work_store.py",
    "tests/test_work_actions.py",
    "tests/test_outlook.py",
    "tests/test_meetings.py",
    "tests/test_selfcheck.py",
    "tests/test_computer_tools.py",
    "tests/test_work_execution.py",
    "tests/test_feed_triage_service.py",
    "tests/test_local_bridge.py",
    "tests/test_commands.py",
    "tests/test_meeting_events.py",
    "tests/test_project_context.py",
    "tests/test_llm.py",
    "tests/test_routines.py",
    "tests/test_background_agent.py",
    "tests/test_keeper.py",
    "tests/test_source_analysis.py",
    "tests/test_workspace.py",
    "tests/test_work_agent.py",
    "tests/test_features.py",
    "tests/test_work_submissions.py",
)
# Strict elapsed deadlines suffer under competing SDK/source work. All native
# modules run after these workers exit too, keeping their fixture costs stable.
AFTER_WORKERS = frozenset(
    {
        "tests/test_agent_streaming.py",
    }
)


@dataclass(frozen=True, slots=True)
class Selection:
    tests: tuple[str, ...]
    changed: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Options:
    full: bool
    native: bool
    tests: tuple[str, ...]
    receipt: Path | None
    baseline: Path
    timings: Path | None


@runtime_checkable
class Test(Protocol):
    __module__: str

    def __call__(self, **arguments: Path) -> object: ...


def source_files(root: Path = ROOT) -> dict[str, str]:
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root, capture_output=True, check=True)
    paths = sorted(set(os.fsdecode(result.stdout).split("\0")) - {""})
    return {name: sha(path) for name in paths if (path := file_at(root, name)).is_file()}


def select(root: Path, current: Mapping[str, str], previous: Mapping[str, str], *, full: bool = False, native: bool = False) -> Selection:
    changed = tuple(sorted(name for name in current.keys() | previous.keys() if current.get(name) != previous.get(name)))
    all_tests = tuple(
        name
        for name in current
        if name.startswith("tests/")
        and Path(name).name.startswith("test_")
        and name.endswith(".py")
        and (native or not Path(name).name.startswith("test_windows_"))
    )
    if full or not previous or any(name in BROAD or name.startswith("requirements/") for name in changed):
        return Selection(all_tests, changed, "full source checks" if full else "bootstrap/configuration or missing baseline")
    # Non-Python application assets have implicit users: run the whole source suite.
    if any(
        not name.endswith((".py", ".pyw")) and not name.startswith(("docs/", ".github/")) and name not in ("AGENTS.md", "README.md", "GLOSSARY.md")
        for name in changed
    ):
        return Selection(all_tests, changed, "application asset has implicit dependencies")
    affected = {module_name(name) for name in changed if name.endswith((".py", ".pyw"))}
    if not affected:
        return Selection((), changed, "transitive Python import dependencies")
    # Cache ownership stays inside source selection; callers only choose
    # coverage. Minimal source fixtures need no project/cache configuration.
    cache = Cache(root) if (root / "pyproject.toml").is_file() else None
    python = {
        name: dependencies(name, file_at(root, name).read_text(encoding="utf-8"), cache=cache) for name in current if name.endswith((".py", ".pyw"))
    }
    while True:
        extra = {module_name(name) for name, imports in python.items() if imports & affected} - affected
        if not extra:
            break
        affected.update(extra)
    selected = tuple(name for name in all_tests if module_name(name) in affected)
    return Selection(selected, changed, "transitive Python import dependencies")


def windows_only(error: BaseException) -> bool:
    match sys.platform, error:
        case platform, (ImportError() | AttributeError() | OSError()) if platform != "win32":
            return any(name in str(error) for name in WINDOWS_IMPORTS)
        case _:
            return False


def import_changed(changed: tuple[str, ...], root: Path, failures: list[Failure], load: Callable[[str], object] = importlib.import_module) -> None:
    # Changed source, its root and failure ledger identify one import review;
    # the loader belongs to the check runtime, shared with test discovery.

    for name in changed:
        if not name.endswith((".py", ".pyw")) or not (root / name).exists():
            continue
        compile((root / name).read_text(encoding="utf-8"), name, "exec")
        if name.endswith(".py") and not name.startswith("tests/"):
            try:
                load(module_name(name))
            except Exception as error:
                if not windows_only(error):
                    failures.append(raised(name, error))


def selected_tests(module: str, loaded: object, requested: str = "") -> Iterator[tuple[str, Test]]:
    for label, test in inspect.getmembers(loaded):
        if not label.startswith("test_") or (requested and label != requested):
            continue
        match test:
            case Test(__module__=str() as origin) if callable(test) and origin == module:
                yield label, test
            case _:
                pass


@contextmanager
def timed(label: str, timings: list[tuple[float, str]]) -> Generator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        timings.append((time.perf_counter() - started, label))


class SourceRuntime(Protocol):
    """Runtime initialization and source loading owned by a check invocation."""

    def activate(self) -> None: ...
    def compile(self, root: Path, failures: list[str]) -> None: ...
    def import_all(self, root: Path, failures: list[str]) -> None: ...
    def load(self, module: str) -> object: ...


class NativeSourceRuntime:
    def activate(self) -> None:
        activate()
        if sys.platform == "win32":
            # Bootstrap the private test process before broad SDK/Qt imports.
            # Mandatory policy gates have passed; protected gates stay intact.
            importlib.import_module("tests")

    def compile(self, root: Path, failures: list[str]) -> None:
        selfcheck.compile_all(root, failures)

    def import_all(self, root: Path, failures: list[str]) -> None:
        selfcheck.import_all(root, failures)

    def load(self, module: str) -> object:
        return importlib.import_module(module)


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    portable: tuple[str, ...]
    sequential: tuple[str, ...]


def execution_plan(tests: tuple[str, ...]) -> ExecutionPlan:
    portable = tuple(selector for name in PORTABLE for selector in tests if selector.partition("::")[0] == name)
    if len(portable) < 2 or not any(name.startswith("tests/test_windows_") for name in tests):
        return ExecutionPlan((), tests)
    return ExecutionPlan(portable, tuple(name for name in tests if name not in portable))


def worker_result(result: Results) -> Results:
    return Results(result.passed, result.skipped, result.failures, tuple((seconds, "worker:" + label) for seconds, label in result.durations))


def combined_results(results: tuple[Results, ...], phases: tuple[tuple[float, str], ...] = ()) -> Results:
    return Results(
        sum(result.passed for result in results),
        sum(result.skipped for result in results),
        tuple(failure for result in results for failure in result.failures),
        (*phases, *(duration for result in results for duration in result.durations)),
    )


NATIVE_SOURCE_RUNTIME = NativeSourceRuntime()


def step_failures(node: str, step: Callable[[Path, list[str]], None], root: Path) -> tuple[Failure, ...]:
    # selfcheck's source steps append free text to a ledger owned by this call.
    problems: list[str] = []
    step(root, problems)
    return tuple(reported(node, problem) for problem in problems)


def execute(selection: Selection, root: Path, runtime: SourceRuntime = NATIVE_SOURCE_RUNTIME) -> Results:
    phases: list[tuple[float, str]] = []
    os.environ.pop("WORKSPACE_E2E", None)
    with timed("phase:runtime activation", phases):
        runtime.activate()
    failures: list[Failure] = []
    broad = selection.reason not in ("transitive Python import dependencies", "explicit iteration scope")
    if broad:
        with timed("phase:compile all source", phases):
            failures.extend(step_failures("compile all source", runtime.compile, root))
        if failures:
            return Results(0, 0, tuple(failures), tuple(phases))
    # Hypothesis inspects loaded modules for local constants. Keep generated
    # domain checks ahead of the eager SDK/native import review, so bundled
    # dependencies do not become their generation catalog. Full compile/import
    # coverage and the final source binding still apply to this same run.
    generated = tuple(name for name in selection.tests if name.startswith("tests/properties/"))
    first = execute_tests(generated, root, runtime.load)
    if broad:
        with timed("phase:import all production modules", phases):
            # This phase already requires the SDK. Resolve its dependency graph
            # before Qt installs its per-module source-inspection callback.
            # Narrow/Qt-only checks never pay this preload; generic source
            # fixtures without the SDK keep their existing import inventory.
            import_changed(("assistant/sdk.py",), root, failures, runtime.load)
            failures.extend(step_failures("import all production modules", runtime.import_all, root))
    if not failures:
        with timed("phase:import changed source", phases):
            import_changed(selection.changed, root, failures, runtime.load)
    if failures:
        return combined_results((first, Results(0, 0, tuple(failures), ())), tuple(phases))
    remaining = tuple(name for name in selection.tests if not name.startswith("tests/properties/"))
    following = execute_overlapped(remaining, root) if broad else execute_tests(remaining, root, runtime.load)
    return combined_results((first, following), tuple(phases))


def prepare_worker(root: Path) -> None:
    activate()
    os.environ.pop("WORKSPACE_E2E", None)
    # No properties run in these workers. Their selected SDK tests already need
    # this graph; resolving it before Qt avoids Qt's dependency-source inspection.
    if (root / "assistant" / "sdk.py").is_file():
        importlib.import_module("assistant.sdk")


def execute_overlapped(tests: tuple[str, ...], root: Path) -> Results:
    plan = execution_plan(tests)
    if not plan.portable:
        return execute_tests(plan.sequential, root)
    alongside = tuple(name for name in plan.sequential if not name.startswith("tests/test_windows_") and name.partition("::")[0] not in AFTER_WORKERS)
    following = tuple(name for name in plan.sequential if name not in alongside)
    phases: list[tuple[float, str]] = []
    results: list[Results] = []
    # The coordinator owns futures and ledgers until all children exit. Only
    # immutable Results cross the stdlib pool boundary; no desktop work is
    # submitted to it. Parent tests and each complete worker module keep their
    # ordinary executor, fixtures, assertions and failure protocol.
    with timed("phase:portable worker dispatch", phases):
        pool = ProcessPoolExecutor(max_workers=4, initializer=prepare_worker, initargs=(root,))
    try:
        with timed("phase:portable worker submission", phases):
            pending = tuple((name, pool.submit(execute_tests, (name,), root)) for name in plan.portable)
        results.append(execute_tests(alongside, root))
        with timed("phase:portable worker completion", phases):
            for name, future in pending:
                try:
                    results.append(worker_result(future.result(timeout=240)))
                except Exception as error:
                    results.append(Results(0, 0, (raised(name, error),), ()))
    finally:
        with timed("phase:portable worker shutdown", phases):
            pool.shutdown(wait=True, cancel_futures=True)
    results.append(execute_tests(following, root))
    return combined_results(tuple(results), tuple(phases))


@contextmanager
def scratch_directory() -> Generator[Path]:
    """The tmp_path fixture shared with mutation sessions.

    Stores nest digest-named folders under it, so it stays shallow enough for
    Windows MAX_PATH; pytest's own tmp_path nests too deep for them.
    """
    with tempfile.TemporaryDirectory(prefix="workspace-edit-check-") as scratch:
        yield Path(scratch)


def execute_tests(tests: tuple[str, ...], root: Path, load: Callable[[str], object] = importlib.import_module) -> Results:
    # Same small test-function protocol as selfcheck, sequential within its owner.
    # Accumulators belong to this executor; only immutable observations leave it.
    failures: list[Failure] = []
    timings: list[tuple[float, str]] = []
    passed = skipped = 0
    for selector in tests:
        name, separator, requested_function = selector.partition("::")
        module = module_name(name)
        import_started = time.perf_counter()
        try:
            loaded = load(module)
        except unittest.SkipTest:
            skipped += 1
            continue
        except Exception as error:
            if windows_only(error):
                skipped += 1
            else:
                failures.append(raised(name, error))
            continue
        finally:
            timings.append((time.perf_counter() - import_started, "module:" + module))
        matched = False
        for label, test in selected_tests(module, loaded, requested_function if separator else ""):
            matched = True
            started = time.perf_counter()
            try:
                parameters = inspect.signature(test).parameters
                if set(parameters) - {"tmp_path"}:
                    raise TypeError("Only tmp_path fixtures are supported, as in selfcheck.")
                with scratch_directory() as scratch:
                    test(**({"tmp_path": scratch} if parameters else {}))
                passed += 1
            except unittest.SkipTest:
                skipped += 1
            except Exception as error:
                failures.append(raised(f"{name}::{label}", error))
            finally:
                timings.append((time.perf_counter() - started, module + "." + label))
        if separator and not matched:
            failures.append(Failure(selector, "No test function matched", f"No test function matched {selector}"))
    return Results(passed, skipped, tuple(failures), tuple(timings))


def check_architecture(root: Path, current: dict[str, str], cache: Cache) -> Report:
    started = time.perf_counter()
    try:
        report = review(root, current, cache=cache)
    except (ValueError, OSError, SyntaxError) as error:
        print(f"Architecture configuration/source failed: {error}")
        raise SystemExit(1) from error
    for finding in report.failures:
        print(finding.describe())
    if report.failures:
        raise SystemExit(1)
    print(
        f"Architecture: {len(report.sources)} Python sources, {len(report.exceptions)} exact exceptions; {time.perf_counter() - started:.2f}s.",
        flush=True,
    )
    for exception in report.exceptions:
        if exception.kind == "migration":
            print(f"  Migration debt: {exception.module}.{exception.declaration}")
    return report


def check_quality(root: Path, current: Mapping[str, str], cache: Cache) -> None:
    report = quality.check(root, current, cache=cache)
    if report.failures or report.stale:
        raise SystemExit(1)


def arguments(parser: argparse.ArgumentParser) -> Options:
    raw = dict(inspect.getmembers(parser.parse_args()))
    match raw:
        case {
            "full": bool() as full,
            "native": bool() as native,
            "tests": requested,
            "receipt": (Path() | None) as receipt,
            "baseline": Path() as baseline,
            "timings": (Path() | None) as timings,
        }:
            if requested is None:
                return Options(full=full, native=native, tests=(), receipt=receipt, baseline=baseline, timings=timings)
            try:
                return Options(
                    full=full,
                    native=native,
                    tests=tuple(TEST_NAMES.validate_python(requested, strict=True)),
                    receipt=receipt,
                    baseline=baseline,
                    timings=timings,
                )
            except ValidationError:
                pass
        case _:
            pass
    return parser.error("Invalid editing-check arguments.")


def choose(args: Options, current: Mapping[str, str], parser: argparse.ArgumentParser) -> Selection:
    deployed = PROFILE / "deployment" / "source.json"
    baseline = args.baseline if args.baseline.is_file() else deployed if args.baseline == LIVE and deployed.is_file() else None
    if baseline is not None:
        previous = source_map(read(baseline))
    else:
        previous = {name: sha(path) for name in current if (path := args.baseline / name).is_file()}
    # Include removed deployed Python modules so deletion propagates through imports.
    if baseline is None and args.baseline.exists():
        for folder in ("assistant", "automation", "miryoku", "winapi", "scripts", "tests"):
            for path in (args.baseline / folder).glob("*.py"):
                name = path.relative_to(args.baseline).as_posix()
                if name not in current:
                    previous[name] = sha(path)
    selection = select(ROOT, current, previous, full=args.full, native=args.native)
    if args.tests and args.full:
        parser.error("--full and --tests select different profiles")
    if args.tests:
        requested = tuple(sorted(set(args.tests)))
        for selector in requested:
            name, separator, function = selector.partition("::")
            if name not in current or not name.startswith("tests/") or not Path(name).name.startswith("test_") or not name.endswith(".py"):
                parser.error("--tests must name existing test_*.py files under tests/, optionally followed by ::test_function")
            if separator and (not function.startswith("test_") or not function.isidentifier()):
                parser.error("A function selector must name one test_function")
        selection = Selection(requested, selection.changed, "explicit iteration scope")
    return selection


@dataclass(frozen=True, slots=True)
class CheckRun:
    """One completed check's immutable source, scope, policy and cost evidence."""

    files: frozendict[str, str]
    selection: Selection
    results: Results
    architecture: Report
    elapsed: float


# Records outlive their console output; bound what a failure contributes.
NODE_LIMIT = 300
SUMMARY_LIMIT = 500


@dataclass(frozen=True, slots=True)
class RecordedFailure:
    """A failure's node id and bounded exception summary; no tracebacks or environment."""

    node: str
    summary: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CostRecord:
    """The diagnostic check record, retained whether or not the check passed."""

    files: frozendict[str, str]
    tests: tuple[str, ...]
    profile: str
    passed: int
    failed: int
    skipped: int
    failures: tuple[RecordedFailure, ...]
    elapsed_seconds: float
    durations: tuple[tuple[float, str], ...]
    worker_seconds: float
    unattributed_seconds: float
    kind: Literal["workspace-check-timings-v1"] = "workspace-check-timings-v1"


COST_RECORD = TypeAdapter(CostRecord)


def publish_check(options: Options, run: CheckRun) -> bool:
    results = run.results
    failures, observations = results.failures, results.durations
    for failure in failures:
        print(failure.report)
    evidence = options.timings or PROFILE / "development" / "timings" / f"check-{time.time_ns()}.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    record = CostRecord(
        files=run.files,
        tests=run.selection.tests,
        profile=run.selection.reason,
        passed=results.passed,
        failed=len(failures),
        skipped=results.skipped,
        failures=tuple(RecordedFailure(failure.node[:NODE_LIMIT], failure.summary[:SUMMARY_LIMIT]) for failure in failures),
        elapsed_seconds=run.elapsed,
        durations=observations,
        worker_seconds=sum(seconds for seconds, label in observations if label.startswith("worker:")),
        unattributed_seconds=max(0.0, run.elapsed - sum(seconds for seconds, label in observations if not label.startswith("worker:"))),
    )
    write(evidence, COST_RECORD.dump_python(record, mode="json"))
    print(f"{results.passed} passed, {len(failures)} failed, {results.skipped} skipped in {run.elapsed:.2f}s; source-bound editing profile")
    print(f"Complete cost evidence: {evidence}", flush=True)
    for seconds, name in sorted((item for item in observations if not item[1].startswith(("phase:", "module:", "worker:module:"))), reverse=True)[:5]:
        print(f"{seconds:.3f}s {name}")
    if not failures and options.receipt:
        write_receipt(
            options.receipt,
            CheckReceipt(
                files=frozendict(run.files),
                tests=run.selection.tests,
                profile=run.selection.reason,
                platform="win32" if options.native else sys.platform,
                passed=results.passed,
                skipped=results.skipped,
                architecture=CheckedArchitecture(sources=len(run.architecture.sources), exceptions=len(run.architecture.exceptions)),
                elapsed_seconds=run.elapsed,
                checked_at_ns=time.time_ns(),
            ),
        )
    return bool(failures)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--native", action="store_true", help="include affected native modules; Windows only, one runner")
    parser.add_argument("--tests", nargs="+", help="explicit test modules for an in-progress iteration")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--timings", type=Path, help="diagnostic cost report, retained on test/import failure")
    parser.add_argument("--baseline", type=Path, default=LIVE)
    args = arguments(parser)
    if args.timings is not None and args.receipt is not None and args.timings.absolute() == args.receipt.absolute():
        parser.error("Timing evidence and the success receipt need separate paths")
    started = time.perf_counter()
    # This coordinator owns the small mutable timing ledger. Published evidence
    # contains only scalar durations, source identities and immutable results.
    overhead: list[tuple[float, str]] = []
    with timed("phase:initial source manifest", overhead):
        current = source_files()
    cache = Cache(ROOT)
    # Mandatory even for explicit --tests scopes; no application imports or
    # native effects before ownership and source policies have passed.
    with timed("phase:architecture review", overhead):
        architecture = check_architecture(ROOT, current, cache)
    with timed("phase:quality review", overhead):
        check_quality(ROOT, current, cache)
    with timed("phase:baseline and test selection", overhead):
        selection = choose(args, current, parser)
    scope: dict[str, str | int] = {"profile": selection.reason, "test_modules": len(selection.tests), "changed_files": len(selection.changed)}
    print(json.dumps(scope), flush=True)
    # Desktop isolation may relaunch the executor. Keep policy review, source
    # identity and receipt publication in this coordinator, outside that handoff.
    if os.name == "nt" and current_name() == os.environ.get("WORKSPACE_TEST_DESKTOP"):
        results = execute(selection, ROOT)
    elif os.name == "nt" or args.native:
        results = execute_native(ROOT, selection.tests, selection.changed, selection.reason)
    else:
        results = execute(selection, ROOT)
    with timed("phase:final source manifest", overhead):
        final = source_files()
    if final != current:
        changed = tuple(name for name in sorted(final.keys() | current.keys()) if final.get(name) != current.get(name))
        message = "Working source changed during checks; no receipt written."
        results = combined_results((results, Results(0, 0, (Failure("working source", message, f"{message} Changed: " + ", ".join(changed)),), ())))
    elapsed = time.perf_counter() - started
    run = CheckRun(frozendict(current), selection, combined_results((results,), tuple(overhead)), architecture, elapsed)
    raise SystemExit(publish_check(args, run))


if __name__ == "__main__":
    main()
