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
import traceback
import unittest
from collections.abc import Generator, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import TypeAdapter, ValidationError

from scripts.architecture import Report, dependencies, module_name, review
from scripts.deploy_files import file_at, read, sha, source_map, write
from scripts.development_paths import LIVE, PROFILE
from scripts.source_analysis import Cache
lazy import selfcheck
lazy from runtime import activate
lazy from scripts import quality
lazy from scripts.check_native import execute_native
lazy from concurrent.futures import ProcessPoolExecutor

ROOT = Path(__file__).resolve().parent.parent
BROAD = frozenset({'keeper.py', 'selfcheck.py', 'runtime.py', 'workspace.pyw', 'config.py', 'protocol.py', 'pyproject.toml'})
TEST_NAMES = TypeAdapter[list[str]](list[str])
WINDOWS_IMPORTS = ('WinDLL', 'WINFUNCTYPE', 'windll', 'winreg', 'msvcrt', '_winapi', 'PySide6', 'shiboken6', 'win32more')
# Reviewed effect owners: fake desktop adapters, private localhost endpoints,
# and per-function temporary stores. These modules never use the shared desktop
# or installed source. Explicit inventory, rather than filename inference, keeps
# new/native tests sequential until their effects have been reviewed.
# Heavier modules lead the queue. Two workers halved this exact group's measured
# elapsed time (123.49 -> 60.86s), including SDK startup and worker shutdown.
PORTABLE = (
    'tests/test_agent.py', 'tests/test_meeting_followup.py', 'tests/test_publishing.py',
    'tests/test_meeting_execution.py', 'tests/test_architecture.py', 'tests/test_meeting_workflow.py',
    'tests/test_quality.py', 'tests/test_work_store.py', 'tests/test_work_actions.py',
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
    result = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root,
                            capture_output=True, check=True)
    paths = sorted(set(os.fsdecode(result.stdout).split('\0')) - {''})
    return {name: sha(path) for name in paths if (path := file_at(root, name)).is_file()}


def select(root: Path, current: Mapping[str, str], previous: Mapping[str, str], *, full: bool = False, native: bool = False) -> Selection:
    changed = tuple(sorted(name for name in current.keys() | previous.keys() if current.get(name) != previous.get(name)))
    all_tests = tuple(name for name in current if name.startswith('tests/') and Path(name).name.startswith('test_') and name.endswith('.py')
                      and (native or not Path(name).name.startswith('test_windows_')))
    if full or not previous or any(name in BROAD or name.startswith('requirements/') for name in changed):
        return Selection(all_tests, changed, 'full source checks' if full else 'bootstrap/configuration or missing baseline')
    # Non-Python application assets have implicit users: run the whole source suite.
    if any(not name.endswith(('.py', '.pyw')) and not name.startswith(('docs/', '.github/')) and name not in ('AGENTS.md', 'README.md', 'GLOSSARY.md')
           for name in changed):
        return Selection(all_tests, changed, 'application asset has implicit dependencies')
    affected = {module_name(name) for name in changed if name.endswith(('.py', '.pyw'))}
    if not affected:
        return Selection((), changed, 'transitive Python import dependencies')
    # Cache ownership stays inside source selection; callers only choose
    # coverage. Minimal source fixtures need no project/cache configuration.
    cache = Cache(root) if (root / 'pyproject.toml').is_file() else None
    python = {name: dependencies(name, file_at(root, name).read_text(encoding='utf-8'), cache=cache)
              for name in current if name.endswith(('.py', '.pyw'))}
    while True:
        extra = {module_name(name) for name, imports in python.items() if imports & affected} - affected
        if not extra:
            break
        affected.update(extra)
    selected = tuple(name for name in all_tests if module_name(name) in affected)
    return Selection(selected, changed, 'transitive Python import dependencies')


def windows_only(error: BaseException) -> bool:
    match sys.platform, error:
        case platform, (ImportError() | AttributeError() | OSError()) if platform != 'win32':
            return any(name in str(error) for name in WINDOWS_IMPORTS)
        case _:
            return False


def import_changed(changed: tuple[str, ...], root: Path, failures: list[str]) -> None:

    for name in changed:
        if not name.endswith(('.py', '.pyw')) or not (root / name).exists():
            continue
        compile((root / name).read_text(encoding='utf-8'), name, 'exec')
        if name.endswith('.py') and not name.startswith('tests/'):
            try:
                importlib.import_module(module_name(name))
            except Exception as error:
                if not windows_only(error):
                    failures.append(f'{name} does not import\n{traceback.format_exc()}')


def selected_tests(module: str, loaded: object, requested: str = '') -> Iterator[tuple[str, Test]]:
    for label, test in inspect.getmembers(loaded):
        if not label.startswith('test_') or (requested and label != requested):
            continue
        match test:
            case Test(__module__=str() as origin) if callable(test) and origin == module:
                yield label, test
            case _:
                pass


type Results = tuple[int, int, tuple[str, ...], tuple[tuple[float, str], ...]]


@contextmanager
def timed(label: str, timings: list[tuple[float, str]]) -> Generator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        timings.append((time.perf_counter() - started, label))


def execute(selection: Selection, root: Path) -> Results:
    phases: list[tuple[float, str]] = []
    with timed('phase:runtime activation', phases):
        activate()
    os.environ.pop('WORKSPACE_E2E', None)
    failures: list[str] = []
    broad = selection.reason not in ('transitive Python import dependencies', 'explicit iteration scope')
    if broad:
        with timed('phase:compile all source', phases):
            selfcheck.compile_all(root, failures)
        if failures:
            return 0, 0, tuple(failures), tuple(phases)
    # Hypothesis inspects loaded modules for local constants. Keep generated
    # domain checks ahead of the eager SDK/native import review, so bundled
    # dependencies do not become their generation catalog. Full compile/import
    # coverage and the final source binding still apply to this same run.
    generated = tuple(name for name in selection.tests if name.startswith('tests/properties/'))
    first = execute_tests(generated, root)
    if broad:
        with timed('phase:import all production modules', phases):
            # This phase already requires the SDK. Resolve its dependency graph
            # before Qt installs its per-module source-inspection callback.
            # Narrow/Qt-only checks never pay this preload; generic source
            # fixtures without the SDK keep their existing import inventory.
            import_changed(('assistant/sdk.py',), root, failures)
            selfcheck.import_all(root, failures)
    if not failures:
        with timed('phase:import changed source', phases):
            import_changed(selection.changed, root, failures)
    if failures:
        return first[0], first[1], (*first[2], *failures), (*phases, *first[3])
    remaining = tuple(name for name in selection.tests if not name.startswith('tests/properties/'))
    following = execute_overlapped(remaining, root) if broad else execute_tests(remaining, root)
    return first[0] + following[0], first[1] + following[1], (*first[2], *following[2]), (*phases, *first[3], *following[3])


def prepare_worker(root: Path) -> None:
    activate()
    os.environ.pop('WORKSPACE_E2E', None)
    # No properties run in these workers. Their selected SDK tests already need
    # this graph; resolving it before Qt avoids Qt's dependency-source inspection.
    if (root / 'assistant' / 'sdk.py').is_file():
        importlib.import_module('assistant.sdk')


def execute_overlapped(tests: tuple[str, ...], root: Path) -> Results:
    portable = tuple(selector for name in PORTABLE for selector in tests if selector.partition('::')[0] == name)
    # Worker startup is disproportionate for a small editing scope. Use this
    # only in broad native runs, where the desktop lane can hide that startup.
    if len(portable) < 2 or not any(name.startswith('tests/test_windows_') for name in tests):
        return execute_tests(tests, root)
    sequential = tuple(name for name in tests if name not in portable)
    phases: list[tuple[float, str]] = []
    results: list[Results] = []
    # The coordinator owns futures and ledgers until all children exit. Only
    # immutable Results cross the stdlib pool boundary; no desktop work is
    # submitted to it. Parent tests and each complete worker module keep their
    # ordinary executor, fixtures, assertions and failure protocol.
    with timed('phase:portable worker dispatch', phases):
        pool = ProcessPoolExecutor(max_workers=2, initializer=prepare_worker, initargs=(root,))
    try:
        with timed('phase:portable worker submission', phases):
            pending = tuple((name, pool.submit(execute_tests, (name,), root)) for name in portable)
        results.append(execute_tests(sequential, root))
        with timed('phase:portable worker completion', phases):
            for name, future in pending:
                try:
                    passed, skipped, failures, timings = future.result(timeout=240)
                    results.append((passed, skipped, failures, tuple((seconds, 'worker:' + label) for seconds, label in timings)))
                except Exception:
                    results.append((0, 0, (f'Portable worker failed for {name}\n{traceback.format_exc()}',), ()))
    finally:
        with timed('phase:portable worker shutdown', phases):
            pool.shutdown(wait=True, cancel_futures=True)
    return (sum(result[0] for result in results), sum(result[1] for result in results),
            tuple(failure for result in results for failure in result[2]),
            (*phases, *(duration for result in results for duration in result[3])))


def execute_tests(tests: tuple[str, ...], root: Path) -> Results:
    # Same small test-function protocol as selfcheck, sequential within its owner.
    # Accumulators belong to this executor; only immutable observations leave it.
    failures: list[str] = []
    timings: list[tuple[float, str]] = []
    passed = skipped = 0
    for selector in tests:
        name, separator, requested_function = selector.partition("::")
        module = module_name(name)
        import_started = time.perf_counter()
        try:
            loaded = importlib.import_module(module)
        except unittest.SkipTest:
            skipped += 1
            continue
        except Exception as error:
            if windows_only(error):
                skipped += 1
            else:
                failures.append(traceback.format_exc())
            continue
        finally:
            timings.append((time.perf_counter() - import_started, 'module:' + module))
        matched = False
        for label, test in selected_tests(module, loaded, requested_function if separator else ''):
            matched = True
            started = time.perf_counter()
            try:
                parameters = inspect.signature(test).parameters
                if set(parameters) - {'tmp_path'}:
                    raise TypeError('Only tmp_path fixtures are supported, as in selfcheck.')
                with tempfile.TemporaryDirectory(prefix='workspace-edit-check-') as scratch:
                    test(**({'tmp_path': Path(scratch)} if parameters else {}))
                passed += 1
            except unittest.SkipTest:
                skipped += 1
            except Exception:
                failures.append(f'{module}.{label}\n{traceback.format_exc()}')
            finally:
                timings.append((time.perf_counter() - started, module + '.' + label))
        if separator and not matched:
            failures.append(f"No test function matched {selector}")
    return passed, skipped, tuple(failures), tuple(timings)


def check_architecture(root: Path, current: dict[str, str], cache: Cache) -> Report:
    started = time.perf_counter()
    try:
        report = review(root, current, cache=cache)
    except (ValueError, OSError, SyntaxError) as error:
        print(f'Architecture configuration/source failed: {error}')
        raise SystemExit(1) from error
    for finding in report.failures:
        print(finding.describe())
    if report.failures:
        raise SystemExit(1)
    print(f'Architecture: {len(report.sources)} Python sources, {len(report.exceptions)} exact exceptions; '
          f'{time.perf_counter() - started:.2f}s.', flush=True)
    for exception in report.exceptions:
        if exception.kind == 'migration':
            print(f'  Migration debt: {exception.module}.{exception.declaration}')
    return report


def check_quality(root: Path, current: Mapping[str, str], cache: Cache) -> None:
    report = quality.check(root, current, cache=cache)
    if report.failures or report.stale:
        raise SystemExit(1)


def arguments(parser: argparse.ArgumentParser) -> Options:
    raw = dict(inspect.getmembers(parser.parse_args()))
    match raw:
        case {'full': bool() as full, 'native': bool() as native, 'tests': requested,
              'receipt': (Path() | None) as receipt, 'baseline': Path() as baseline,
              'timings': (Path() | None) as timings}:
            if requested is None:
                return Options(full=full, native=native, tests=(), receipt=receipt, baseline=baseline, timings=timings)
            try:
                return Options(full=full, native=native, tests=tuple(TEST_NAMES.validate_python(requested, strict=True)),
                               receipt=receipt, baseline=baseline, timings=timings)
            except ValidationError:
                pass
        case _:
            pass
    return parser.error('Invalid editing-check arguments.')


def choose(args: Options, current: Mapping[str, str], parser: argparse.ArgumentParser) -> Selection:
    deployed = PROFILE / 'deployment' / 'source.json'
    baseline = args.baseline if args.baseline.is_file() else deployed if args.baseline == LIVE and deployed.is_file() else None
    if baseline is not None:
        previous = source_map(read(baseline))
    else:
        previous = {name: sha(path) for name in current if (path := args.baseline / name).is_file()}
    # Include removed deployed Python modules so deletion propagates through imports.
    if baseline is None and args.baseline.exists():
        for folder in ('assistant', 'automation', 'miryoku', 'winapi', 'scripts', 'tests'):
            for path in (args.baseline / folder).glob('*.py'):
                name = path.relative_to(args.baseline).as_posix()
                if name not in current:
                    previous[name] = sha(path)
    selection = select(ROOT, current, previous, full=args.full, native=args.native)
    if args.tests and args.full:
        parser.error('--full and --tests select different profiles')
    if args.tests:
        requested = tuple(sorted(set(args.tests)))
        for selector in requested:
            name, separator, function = selector.partition('::')
            if name not in current or not name.startswith('tests/') or not Path(name).name.startswith('test_') or not name.endswith('.py'):
                parser.error('--tests must name existing test_*.py files under tests/, optionally followed by ::test_function')
            if separator and (not function.startswith('test_') or not function.isidentifier()):
                parser.error('A function selector must name one test_function')
        selection = Selection(requested, selection.changed, 'explicit iteration scope')
    return selection


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--native', action='store_true', help='include affected native modules; Windows only, one runner')
    parser.add_argument('--tests', nargs='+', help='explicit test modules for an in-progress iteration')
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--timings', type=Path, help='diagnostic cost report, retained on test/import failure')
    parser.add_argument('--baseline', type=Path, default=LIVE)
    args = arguments(parser)
    if args.timings is not None and args.receipt is not None and args.timings.absolute() == args.receipt.absolute():
        parser.error('Timing evidence and the success receipt need separate paths')
    started = time.perf_counter()
    # This coordinator owns the small mutable timing ledger. Published evidence
    # contains only scalar durations, source identities and immutable results.
    overhead: list[tuple[float, str]] = []
    with timed('phase:initial source manifest', overhead):
        current = source_files()
    cache = Cache(ROOT)
    # Mandatory even for explicit --tests scopes; no application imports or
    # native effects before ownership and source policies have passed.
    with timed('phase:architecture review', overhead):
        architecture = check_architecture(ROOT, current, cache)
    with timed('phase:quality review', overhead):
        check_quality(ROOT, current, cache)
    with timed('phase:baseline and test selection', overhead):
        selection = choose(args, current, parser)
    scope: dict[str, str | int] = {'profile': selection.reason, 'test_modules': len(selection.tests), 'changed_files': len(selection.changed)}
    print(json.dumps(scope), flush=True)
    if args.native and os.name != 'nt':
        passed, skipped, failures, timings = execute_native(ROOT, selection.tests, selection.changed, selection.reason)
    else:
        passed, skipped, failures, timings = execute(selection, ROOT)
    with timed('phase:final source manifest', overhead):
        final = source_files()
    if final != current:
        changed = tuple(name for name in sorted(final.keys() | current.keys()) if final.get(name) != current.get(name))
        failures = (*failures, 'Working source changed during checks; no receipt written. Changed: ' + ', '.join(changed))
    for failure in failures:
        print(failure)
    elapsed = time.perf_counter() - started
    observations = (*overhead, *timings)
    evidence = args.timings or PROFILE / 'development' / 'timings' / f'check-{time.time_ns()}.json'
    evidence.parent.mkdir(parents=True, exist_ok=True)
    # Separate from authorization: failed checks keep the complete diagnostic
    # report, while source-bound deployment receipts remain success-only.
    write(evidence, {'kind': 'workspace-check-timings-v1', 'files': current, 'tests': selection.tests,
                     'profile': selection.reason, 'passed': passed, 'failed': len(failures), 'skipped': skipped,
                     'elapsed_seconds': elapsed, 'durations': observations,
                     'worker_seconds': sum(seconds for seconds, label in observations if label.startswith('worker:')),
                     'unattributed_seconds': max(0.0, elapsed - sum(seconds for seconds, label in observations
                                                                  if not label.startswith('worker:')))})
    print(f'{passed} passed, {len(failures)} failed, {skipped} skipped in {elapsed:.2f}s; source-bound editing profile')
    print(f'Complete cost evidence: {evidence}', flush=True)
    for seconds, name in sorted((item for item in timings if not item[1].startswith(('phase:', 'module:', 'worker:module:'))), reverse=True)[:5]:
        print(f'{seconds:.3f}s {name}')
    if not failures and args.receipt:
        write(args.receipt, {'kind': 'workspace-edit-check-v1', 'files': current, 'tests': selection.tests,
                             'profile': selection.reason, 'platform': 'win32' if args.native else sys.platform, 'passed': passed, 'skipped': skipped,
                             'architecture': {'sources': len(architecture.sources), 'exceptions': len(architecture.exceptions)},
                             'elapsed_seconds': elapsed, 'checked_at_ns': time.time_ns()})
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
