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
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import TypeAdapter, ValidationError

from scripts.architecture import Report, dependencies, module_name, review
from scripts.deploy_files import file_at, read, sha, source_map, write
from scripts.development_paths import LIVE, PROFILE
lazy import selfcheck
lazy from runtime import activate
lazy from scripts import quality
lazy from scripts.check_native import execute_native

ROOT = Path(__file__).resolve().parent.parent
BROAD = frozenset({'keeper.py', 'selfcheck.py', 'runtime.py', 'workspace.pyw', 'config.py', 'protocol.py', 'pyproject.toml'})
TEST_NAMES = TypeAdapter[list[str]](list[str])
WINDOWS_IMPORTS = ('WinDLL', 'WINFUNCTYPE', 'windll', 'winreg', 'msvcrt', '_winapi', 'PySide6', 'shiboken6', 'win32more')


@dataclass(frozen=True, slots=True)
class Selection:
    tests: tuple[str, ...]
    changed: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class Options:
    full: bool
    native: bool
    tests: tuple[str, ...]
    receipt: Path | None
    baseline: Path


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
    python = {name: dependencies(name, file_at(root, name).read_text(encoding='utf-8')) for name in current if name.endswith(('.py', '.pyw'))}
    affected = {module_name(name) for name in changed if name.endswith(('.py', '.pyw'))}
    # Non-Python application assets have implicit users: run the whole source suite.
    if any(not name.endswith(('.py', '.pyw')) and not name.startswith(('docs/', '.github/')) and name not in ('AGENTS.md', 'README.md', 'GLOSSARY.md')
           for name in changed):
        return Selection(all_tests, changed, 'application asset has implicit dependencies')
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


def execute(selection: Selection, root: Path) -> tuple[int, int, tuple[str, ...], tuple[tuple[float, str], ...]]:
    # Same small test-function protocol as selfcheck, sequential on the shared desktop.
    activate()
    os.environ.pop('WORKSPACE_E2E', None)
    # This execution owner accumulates results locally: rebuilding tuples after
    # every test would copy a growing prefix. Only immutable tuples leave it.
    failures: list[str] = []
    timings: list[tuple[float, str]] = []
    passed = skipped = 0
    if selection.reason not in ('transitive Python import dependencies', 'explicit iteration scope'):
        selfcheck.compile_all(root, failures)
        if not failures:
            selfcheck.import_all(root, failures)
        if failures:
            return 0, 0, tuple(failures), tuple(timings)
    import_changed(selection.changed, root, failures)
    for selector in selection.tests:
        name, separator, requested_function = selector.partition("::")
        module = module_name(name)
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


def check_architecture(root: Path, current: dict[str, str]) -> Report:
    started = time.perf_counter()
    try:
        report = review(root, current)
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


def check_quality(root: Path, current: Mapping[str, str]) -> None:
    report = quality.check(root, current)
    if report.failures or report.stale:
        raise SystemExit(1)


def arguments(parser: argparse.ArgumentParser) -> Options:
    raw = dict(inspect.getmembers(parser.parse_args()))
    match raw:
        case {'full': bool() as full, 'native': bool() as native, 'tests': requested,
              'receipt': (Path() | None) as receipt, 'baseline': Path() as baseline}:
            if requested is None:
                return Options(full, native, (), receipt, baseline)
            try:
                return Options(full, native, tuple(TEST_NAMES.validate_python(requested, strict=True)), receipt, baseline)
            except ValidationError:
                pass
        case _:
            pass
    return parser.error('Invalid editing-check arguments.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--native', action='store_true', help='include affected native modules; Windows only, one runner')
    parser.add_argument('--tests', nargs='+', help='explicit test modules for an in-progress iteration')
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--baseline', type=Path, default=LIVE)
    args = arguments(parser)
    started = time.perf_counter()
    current = source_files()
    # Mandatory even for explicit --tests scopes; no application imports or
    # native effects before ownership and source policies have passed.
    architecture = check_architecture(ROOT, current)
    check_quality(ROOT, current)
    cache = PROFILE / 'deployment' / 'source.json'
    baseline = args.baseline if args.baseline.is_file() else cache if args.baseline == LIVE and cache.is_file() else None
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
    scope: dict[str, str | int] = {'profile': selection.reason, 'test_modules': len(selection.tests), 'changed_files': len(selection.changed)}
    print(json.dumps(scope), flush=True)
    if args.native and os.name != 'nt':
        passed, skipped, failures, timings = execute_native(ROOT, selection.tests, selection.changed, selection.reason)
    else:
        passed, skipped, failures, timings = execute(selection, ROOT)
    if source_files() != current:
        failures = (*failures, 'Working source changed during checks; no receipt written.')
    for failure in failures:
        print(failure)
    elapsed = time.perf_counter() - started
    print(f'{passed} passed, {len(failures)} failed, {skipped} skipped in {elapsed:.2f}s; source-bound editing profile')
    for seconds, name in sorted(timings, reverse=True)[:5]:
        print(f'{seconds:.3f}s {name}')
    if not failures and args.receipt:
        write(args.receipt, {'kind': 'workspace-edit-check-v1', 'files': current, 'tests': selection.tests,
                             'profile': selection.reason, 'platform': 'win32' if args.native else sys.platform, 'passed': passed, 'skipped': skipped,
                             'architecture': {'sources': len(architecture.sources), 'exceptions': len(architecture.exceptions)},
                             'elapsed_seconds': elapsed, 'checked_at_ns': time.time_ns()})
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
