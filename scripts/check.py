"""Source-bound editing checks. The keeper's protected full gate is unchanged.

python -m scripts.check [--full | --native] [--standards] [--tests tests/test_x.py ...]
                       [--receipt /tmp/workspace-check.json]
"""

import argparse
import ast
import contextlib
import importlib
import inspect
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable
lazy from concurrent.futures import Future, ProcessPoolExecutor

from pydantic import TypeAdapter, ValidationError

from cell import Cell
from scripts.architecture import Report, dependencies, python_sources, review
from scripts.check_results import Failure, Results, Selection, raised, reported
from scripts.deploy_files import CheckedArchitecture, CheckReceipt, file_at, json_record, read, sha, source_map, write, write_receipt
from scripts.development_paths import PROFILE
from scripts.source_analysis import Cache, module_name
lazy from scripts import check_standards, check_tiers, quality, selfcheck
lazy from scripts.check_native import execute_lanes
lazy from scripts.native_desktop import current_name

ROOT = Path(__file__).resolve().parent.parent
DIRECT = "direct Python imports"
TEST_NAMES = TypeAdapter[list[str]](list[str])
WINDOWS_IMPORTS = ("WinDLL", "WINFUNCTYPE", "windll", "winreg", "msvcrt", "_winapi", "PySide6", "shiboken6", "win32more")


@dataclass(frozen=True, slots=True, kw_only=True)
class Options:
    full: bool
    native: bool
    standards: bool
    tests: tuple[str, ...]
    receipt: Path | None
    baseline: Path
    timings: Path | None


@runtime_checkable
class Test(Protocol):
    __module__: str

    def __call__(self, **arguments: Path) -> object: ...


def source_paths(root: Path = ROOT) -> tuple[str, ...]:
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root, capture_output=True, check=True)
    return tuple(sorted(set(os.fsdecode(result.stdout).split("\0")) - {""}))


def source_files(root: Path = ROOT) -> dict[str, str]:
    return {name: sha(path) for name in source_paths(root) if (path := file_at(root, name)).is_file()}


@dataclass(frozen=True, slots=True)
class SourceStamp:
    """A source file's size and modification time: a cheap identity for the final binding."""

    size: int
    modified_ns: int


def source_stamp(path: Path) -> SourceStamp | None:
    try:
        observed = os.stat(path)
    except FileNotFoundError:
        return None
    return SourceStamp(observed.st_size, observed.st_mtime_ns)


def source_stamps(root: Path = ROOT) -> frozendict[str, SourceStamp]:
    """Each present source file's stamp."""
    return frozendict((name, stamp) for name in source_paths(root) if (stamp := source_stamp(file_at(root, name))) is not None)


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
    if full or not previous or "uv.lock" in changed:
        return Selection(all_tests, changed, "full source checks" if full else "dependency pins or missing baseline")
    # Minimal source fixtures need no project/cache configuration.
    cache = Cache.bound(root) if (root / "pyproject.toml").is_file() else None
    tests = {
        name: dependencies(name, file_at(root, name).read_text(encoding="utf-8"), cache=cache)
        for name in current
        if name.startswith("tests/") and name.endswith(".py") and (root / name).is_file()
    }
    # The keeper's install check selects with the same function, so it reruns only
    # what this check would. Following production imports transitively selected most
    # of the suite for any core edit; the full suite runs with --full and in CI.
    affected = selfcheck.affected_tests(root, changed, tests)
    if affected is None:
        return Selection(all_tests, changed, "application asset has implicit dependencies")
    return Selection(tuple(name for name in all_tests if name in affected), changed, DIRECT)


def windows_only(error: BaseException) -> bool:
    match sys.platform, error:
        case platform, (ImportError() | AttributeError() | OSError()) if platform != "win32":
            return any(name in str(error) for name in WINDOWS_IMPORTS)
        case _:
            return False


def import_changed(changed: tuple[str, ...], root: Path, load: Callable[[str], object] = importlib.import_module) -> Iterator[Failure]:
    """Compile each changed source and import the changed production modules, yielding each import failure.

    The loader belongs to the check runtime, shared with test discovery.
    """

    for name in changed:
        if not name.endswith((".py", ".pyw")) or not (root / name).exists():
            continue
        compile((root / name).read_text(encoding="utf-8"), name, "exec")
        if name.endswith(".py") and not name.startswith("tests/"):
            try:
                load(module_name(name))
            except Exception as error:
                if not windows_only(error):
                    yield raised(name, error)


def selected_tests(module: str, loaded: object, requested: str = "") -> Iterator[tuple[str, Test]]:
    for label, test in inspect.getmembers(loaded):
        if not label.startswith("test_") or (requested and label != requested):
            continue
        match test:
            case Test(__module__=str() as origin) if callable(test) and origin == module:
                yield label, test
            case _:
                pass


@dataclass(frozen=True, slots=True)
class Phases:
    """The durations of a check's phases, in the order they finish; each phase's time counts even when it raises."""

    _recorded: Cell[tuple[tuple[float, str], ...]] = field(default_factory=lambda: Cell[tuple[tuple[float, str], ...]](()), repr=False)

    @property
    def recorded(self) -> tuple[tuple[float, str], ...]:
        return self._recorded.get()

    @contextmanager
    def timed(self, label: str) -> Generator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            self._recorded.update(lambda recorded: (*recorded, (elapsed, label)))


class SourceRuntime(Protocol):
    """Runtime initialization and source loading owned by a check invocation."""

    def activate(self) -> None: ...
    def import_all(self, root: Path) -> Iterable[str]:
        """Import every production module, yielding a report of each that fails."""
        ...

    def load(self, module: str) -> object: ...


@dataclass(frozen=True, slots=True)
class NativeSourceRuntime:
    def activate(self) -> None:
        if sys.platform == "win32":
            # Bootstrap the private test process before broad SDK/Qt imports.
            # Mandatory policy gates have passed; protected gates stay intact.
            importlib.import_module("tests")

    def import_all(self, root: Path) -> Iterable[str]:
        return selfcheck.import_all(root)

    def load(self, module: str) -> object:
        return importlib.import_module(module)


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    portable: tuple[str, ...]
    sequential: tuple[str, ...]


WORKERS = 3
"""One per physical core left after the runner and the running Workspace on a four-core laptop."""
POOL_MINIMUM = 10
"""Fewer modules finish sooner here than workers can start: each imports the SDK first."""


def modules(tests: tuple[str, ...]) -> frozenset[str]:
    return frozenset(selector.partition("::")[0] for selector in tests)


def execution_plan(tests: tuple[str, ...]) -> ExecutionPlan:
    # Workers own no native windows: native modules stay in this process, after
    # the workers exit, as do strict-deadline modules.
    candidates = tuple(selector for selector in tests if not selector.startswith("tests/test_windows_"))
    if len(modules(candidates)) < POOL_MINIMUM:
        return ExecutionPlan((), tests)
    pooled = {selector for selector in candidates if selector.partition("::")[0] not in selfcheck.AFTER_WORKERS}
    # Known heavy modules lead the queue so they do not finish last.
    heavy = tuple(selector for name in selfcheck.PORTABLE for selector in tests if selector.partition("::")[0] == name and selector in pooled)
    portable = (*heavy, *(selector for selector in tests if selector in pooled and selector not in heavy))
    return ExecutionPlan(portable, tuple(name for name in tests if name not in pooled))


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


def step_failures(node: str, step: Callable[[Path], Iterable[str]], root: Path) -> Iterator[Failure]:
    """selfcheck's source step's free-text problems, as failures of node."""
    return (reported(node, problem) for problem in step(root))


def execute(selection: Selection, root: Path, runtime: SourceRuntime = NATIVE_SOURCE_RUNTIME) -> Results:
    phases = Phases()
    os.environ.pop("WORKSPACE_E2E", None)
    with phases.timed("phase:runtime activation"):
        runtime.activate()
    failures: tuple[Failure, ...] = ()
    # No separate compile phase: the architecture review and Ruff parse every
    # source before any test, and the import review compiles what it loads.
    broad = selection.reason not in (DIRECT, "explicit iteration scope")
    # Hypothesis inspects loaded modules for local constants. Keep generated
    # domain checks ahead of the eager SDK/native import review, so bundled
    # dependencies do not become their generation catalog. Full import
    # coverage and the final source binding still apply to this same run.
    generated = tuple(name for name in selection.tests if name.startswith("tests/properties/"))
    first = execute_tests(generated, root, runtime.load)
    if broad:
        with phases.timed("phase:import all production modules"):
            # This phase already requires the SDK. Resolve its dependency graph
            # before Qt installs its per-module source-inspection callback.
            # Narrow/Qt-only checks never pay this preload; generic source
            # fixtures without the SDK keep their existing import inventory.
            failures = (
                *import_changed(("assistant/sdk.py",), root, runtime.load),
                *step_failures("import all production modules", runtime.import_all, root),
            )
    if not failures:
        with phases.timed("phase:import changed source"):
            failures = tuple(import_changed(selection.changed, root, runtime.load))
    if not broad and not failures:
        # A cold SDK import costs about 2 s; paid here, the time budget does not
        # blame whichever selected test happens to use the SDK first.
        with phases.timed("phase:import the SDK"):
            for package in sdk_packages(selection.tests, root):
                runtime.load(package)
    if failures:
        return combined_results((first, Results(0, 0, failures, ())), phases.recorded)
    remaining = tuple(name for name in selection.tests if not name.startswith("tests/properties/"))
    following = execute_overlapped(remaining, root, runtime.load)
    return combined_results((first, following), phases.recorded)


SDK_PACKAGES = ("agents", "openai")


def eager_imports(text: str) -> frozenset[str]:
    """Modules a source file imports when it loads, with their packages; lazy imports load only when used."""
    found = frozenset(
        module
        for node in ast.parse(text).body
        for module in (
            tuple(alias.name for alias in node.names)
            if isinstance(node, ast.Import) and not node.is_lazy
            else (node.module, *(f"{node.module}.{alias.name}" for alias in node.names))
            if isinstance(node, ast.ImportFrom) and node.module is not None and not node.is_lazy
            else ()
        )
    )
    return frozenset(".".join(module.split(".")[:end]) for module in found for end in range(1, module.count(".") + 2))


def sdk_packages(tests: tuple[str, ...], root: Path) -> tuple[str, ...]:
    """The SDK packages the selected tests load as they import, directly or through Workspace modules.

    Only eager imports count: a module that reaches the SDK lazily (as `assistant.agent`
    does) loads it only when a test runs an agent, so most tests never pay its
    seconds-long import."""
    reached = frozenset(
        name.partition(".")[0]
        for imported in _eager_closure(frozenset(module_name(selector.partition("::")[0]) for selector in tests), root)
        for name in imported
    )
    return tuple(package for package in SDK_PACKAGES if package in reached)


def _module_imports(module: str, root: Path) -> frozenset[str]:
    """The eager imports of a Workspace module's source, or none for a module outside the tree."""
    base = root / module.replace(".", "/")
    path = next((candidate for candidate in (base.with_suffix(".py"), base / "__init__.py") if candidate.is_file()), None)
    return frozenset() if path is None else eager_imports(path.read_text(encoding="utf-8"))


def _eager_closure(modules: frozenset[str], root: Path) -> Iterator[frozenset[str]]:
    """The eager imports of every module reachable from modules, one breadth-first level at a time."""
    seen: frozenset[str] = frozenset()
    while modules:
        found = tuple(_module_imports(module, root) for module in sorted(modules))
        yield from found
        seen = seen | modules
        modules = frozenset[str]().union(*found) - seen


def prepare_worker(root: Path) -> None:
    # The SDK is not preloaded: it loads when a test first runs an agent (a few
    # seconds), and loading it before or after Qt took the same time warm.
    os.environ.pop("WORKSPACE_E2E", None)


def execute_overlapped(tests: tuple[str, ...], root: Path, load: Callable[[str], object] = importlib.import_module) -> Results:
    plan = execution_plan(tests)
    if not plan.portable:
        return execute_tests(plan.sequential, root, load)
    phases = Phases()
    # The coordinator owns futures and ledgers until all children exit. Only
    # immutable Results cross the stdlib pool boundary; no native module is
    # submitted to it. Each worker module keeps the ordinary executor, fixtures,
    # assertions and failure protocol.
    with phases.timed("phase:portable worker dispatch"):
        pool = ProcessPoolExecutor(max_workers=WORKERS, initializer=prepare_worker, initargs=(root,))
    try:
        with phases.timed("phase:portable worker submission"):
            pending = tuple((name, pool.submit(execute_tests, (name,), root)) for name in plan.portable)
        with phases.timed("phase:portable worker completion"):
            completed = tuple(_completed(name, future) for name, future in pending)
    finally:
        with phases.timed("phase:portable worker shutdown"):
            pool.shutdown(wait=True, cancel_futures=True)
    return combined_results((*completed, execute_tests(plan.sequential, root, load)), phases.recorded)


def _completed(name: str, future: Future[Results]) -> Results:
    """One portable worker's results, or its failure to report them."""
    try:
        return worker_result(future.result(timeout=240))
    except Exception as error:
        return Results(0, 0, (raised(name, error),), ())


@contextmanager
def scratch_directory() -> Generator[Path]:
    """The tmp_path fixture.

    Stores nest digest-named folders under it, so it stays shallow enough for
    Windows MAX_PATH; pytest's own tmp_path nests too deep for them.
    """
    with tempfile.TemporaryDirectory(prefix="workspace-edit-check-") as scratch:
        yield Path(scratch)


def execute_tests(tests: tuple[str, ...], root: Path, load: Callable[[str], object] = importlib.import_module) -> Results:
    # Same small test-function protocol as selfcheck, sequential within its owner.
    # Each module import and test reports its own immutable Results; this combines them.
    return combined_results(tuple(_test_results(tests, load)))


def _test_results(tests: tuple[str, ...], load: Callable[[str], object]) -> Iterator[Results]:
    """Import each selected module and run its tests in order, yielding each step's observation once it is timed."""
    for selector in tests:
        name, separator, requested_function = selector.partition("::")
        module = module_name(name)
        import_started = time.perf_counter()
        try:
            loaded = load(module)
        except unittest.SkipTest:
            yield Results(0, 1, (), ((time.perf_counter() - import_started, "module:" + module),))
            continue
        except Exception as error:
            skipped = windows_only(error)
            failures = () if skipped else (raised(name, error),)
            yield Results(0, int(skipped), failures, ((time.perf_counter() - import_started, "module:" + module),))
            continue
        yield Results(0, 0, (), ((time.perf_counter() - import_started, "module:" + module),))
        ran = tuple(
            _test_result(name, module, label, test) for label, test in selected_tests(module, loaded, requested_function if separator else "")
        )
        yield from ran
        if separator and not ran:
            yield Results(0, 0, (Failure(selector, "No test function matched", f"No test function matched {selector}"),), ())


def _test_result(name: str, module: str, label: str, test: Test) -> Results:
    sdk_loaded = "agents" in sys.modules
    started = time.perf_counter()
    # Expected diagnostics from passing tests, such as SDK warnings for a
    # deliberately broken stream, would bury real failures in the console.
    # This executor owns the buffer; only failing tests publish it.
    output = io.StringIO()
    try:
        parameters = inspect.signature(test).parameters
        if set(parameters) - {"tmp_path"}:
            raise TypeError("Only tmp_path fixtures are supported, as in selfcheck.")
        with contextlib.redirect_stderr(output), scratch_directory() as scratch:
            test(**({"tmp_path": scratch} if parameters else {}))
        passed, skipped, failures = 1, 0, ()
    except unittest.SkipTest:
        passed, skipped, failures = 0, 1, ()
    except Exception as error:
        passed, skipped, failures = 0, 0, (raised(f"{name}::{label}", error, output.getvalue()),)
    # The first test to run an agent loads the SDK (seconds, cold); that load is
    # a phase of this run, not the test's cost, so the budget never blames it.
    first_load = not sdk_loaded and "agents" in sys.modules
    elapsed = time.perf_counter() - started
    return Results(passed, skipped, failures, ((elapsed, f"phase:first SDK load in {module}.{label}" if first_load else module + "." + label),))


def check_architecture(root: Path, current: Mapping[str, str], cache: Cache) -> Report:
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
    return report


def check_quality(root: Path, current: Mapping[str, str], cache: Cache) -> None:
    if quality.check(root, current, cache=cache):
        raise SystemExit(1)


def check_lint(root: Path) -> None:
    failures = check_standards.run((check_standards.LINT, check_standards.FORMAT), root)
    for failure in failures:
        print(failure.report)
    if failures:
        raise SystemExit(1)


CHECKED = PROFILE / "development" / "checked"
"""The last source each tier passed: a check selects what changed since, and a passing check records it."""


def checked(*, native: bool) -> Path:
    return CHECKED / ("native.json" if native else "portable.json")


def arguments(parser: argparse.ArgumentParser) -> Options:
    raw = dict(inspect.getmembers(parser.parse_args()))
    match raw:
        case {
            "full": bool() as full,
            "native": bool() as native,
            "standards": bool() as standards,
            "tests": requested,
            "receipt": (Path() | None) as receipt,
            "baseline": (Path() | None) as chosen,
            "timings": (Path() | None) as timings,
        }:
            baseline = chosen if chosen is not None else checked(native=native or full)
            if requested is None:
                return Options(full=full, native=native or full, standards=standards, tests=(), receipt=receipt, baseline=baseline, timings=timings)
            try:
                return Options(
                    full=full,
                    native=native or full,
                    standards=standards,
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
    baseline = args.baseline if args.baseline.is_file() else None
    previous: Mapping[str, str]
    if baseline is not None:
        previous = source_map(read(baseline))
    else:
        # Include removed deployed Python modules so deletion propagates through imports.
        removed = python_sources(args.baseline) if args.baseline.exists() else ()
        previous = {
            **{name: sha(path) for name in current if (path := args.baseline / name).is_file()},
            **{name: sha(args.baseline / name) for name in removed if name not in current},
        }
    selection = select(ROOT, current, previous, full=args.full, native=args.native)
    if not args.native:
        selection = check_tiers.editing(selection, ROOT)
    elif not args.full and (portable := checked(native=False)).is_file() and portable != args.baseline:
        # The native baseline picks the affected native modules; the source checks
        # (types, imports) need only what changed since the portable tier last
        # passed, which a native pass also records, so they never redo its work.
        since = source_map(read(portable))
        changed = tuple(sorted(name for name in current.keys() | since.keys() if current.get(name) != since.get(name)))
        selection = Selection(selection.tests, changed, selection.reason)
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
    write(evidence, json_record(COST_RECORD, record))
    print(f"{results.passed} passed, {len(failures)} failed, {results.skipped} skipped in {run.elapsed:.2f}s; source-bound editing profile")
    print(f"Complete cost evidence: {evidence}", flush=True)
    for seconds, name in sorted((item for item in observations if not item[1].startswith(("phase:", "module:", "worker:module:"))), reverse=True)[:5]:
        print(f"{seconds:.3f}s {name}")
    # A passing selected check records what it passed; a native one passed the portable tier too.
    recorded = (checked(native=False), checked(native=True)) if options.native else (checked(native=False),)
    receipts = (*((options.receipt,) if options.receipt else ()), *(() if options.tests else recorded))
    for receipt in receipts if not failures else ():
        write_receipt(
            receipt,
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
                standards=options.standards,
            ),
        )
    return bool(failures)


def editing_budget(args: Options, selection: Selection, results: Results) -> tuple[Failure, ...]:
    """Budget failures: a narrow automatic editing check holds every test to the editing
    budget, and any run with native modules holds them to the native budget. --tests
    names tests on purpose, so it is exempt."""
    narrow = not args.native and not args.tests and selection.reason == DIRECT and len(modules(selection.tests)) < POOL_MINIMUM
    editing = check_tiers.over_budget(results.durations) if narrow else ()
    native = check_tiers.over_native_budget(results.durations) if args.native and not args.tests else ()
    return (*editing, *native)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--native", action="store_true", help="also run affected native modules and slow tests; --full implies it")
    parser.add_argument("--standards", action="store_true", help="also apply the whole-tree Ruff and pyright standards; Dev.cmd check does")
    parser.add_argument("--tests", nargs="+", help="explicit test modules for an in-progress iteration")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--timings", type=Path, help="diagnostic cost report, retained on test/import failure")
    parser.add_argument("--baseline", type=Path, help="a receipt or source folder to select changes from; the tier's last passing check by default")
    args = arguments(parser)
    if args.timings is not None and args.receipt is not None and args.timings.absolute() == args.receipt.absolute():
        parser.error("Timing evidence and the success receipt need separate paths")
    started = time.perf_counter()
    # Published evidence contains only scalar durations, source identities and immutable results.
    overhead = Phases()
    with overhead.timed("phase:initial source manifest"):
        stamps = source_stamps()
        current = source_files()
    cache = Cache.bound(ROOT)
    if args.standards:
        with overhead.timed("phase:lint standards"):
            check_lint(ROOT)
    # Selection parses source without importing it, so it may precede the reviews.
    with overhead.timed("phase:baseline and test selection"):
        selection = choose(args, current, parser)
    # The type checkers overlap the policy reviews and test execution. Their
    # failures block the receipt like test failures; an earlier policy failure
    # ends their process trees on exit. Editing checks type only changed files.
    present = tuple(name for name in selection.changed if name in current)
    standards = check_standards.TYPES if args.full else check_standards.changed_types(present)
    types = check_standards.background(standards, ROOT) if args.standards else nullcontext(check_standards.unchecked)
    with types as typed:
        # Mandatory even for explicit --tests scopes; no application imports or
        # native effects before ownership and source policies have passed.
        with overhead.timed("phase:architecture review"):
            architecture = check_architecture(ROOT, current, cache)
        with overhead.timed("phase:quality review"):
            check_quality(ROOT, current, cache)
        scope: dict[str, str | int] = {"profile": selection.reason, "test_modules": len(selection.tests), "changed_files": len(selection.changed)}
        print(json.dumps(scope), flush=True)
        # Desktop isolation may relaunch the executor. Keep policy review, source
        # identity and receipt publication in this coordinator, outside that handoff.
        # Plain tests own no windows: with no native module selected they run here,
        # without starting the Windows runner or moving it to a private desktop.
        native = any(name.startswith("tests/test_windows_") for name in selection.tests)
        if os.name == "nt" and current_name() == os.environ.get("WORKSPACE_TEST_DESKTOP"):
            results = execute(selection, ROOT)
        elif native and (os.name == "nt" or args.native):
            # Whole-tree pyright saturates the cores; native fixtures wait for it.
            results = execute_lanes(ROOT, selection, typed if args.full else check_standards.unchecked)
        else:
            results = execute(selection, ROOT)
        with overhead.timed("phase:type standards"):
            results = combined_results((results, Results(0, 0, (*typed(), *editing_budget(args, selection, results)), ())))
    with overhead.timed("phase:final source manifest"):
        # Stamps taken before hashing: unchanged stamps mean unchanged bytes. Re-hashing
        # every file after the tests cost up to 15 s under post-run file contention.
        final = current if source_stamps() == stamps else source_files()
    if final != current:
        changed = tuple(name for name in sorted(final.keys() | current.keys()) if final.get(name) != current.get(name))
        message = "Working source changed during checks; no receipt written."
        results = combined_results((results, Results(0, 0, (Failure("working source", message, f"{message} Changed: " + ", ".join(changed)),), ())))
    elapsed = time.perf_counter() - started
    run = CheckRun(frozendict(current), selection, combined_results((results,), overhead.recorded), architecture, elapsed)
    raise SystemExit(publish_check(args, run))


if __name__ == "__main__":
    main()
