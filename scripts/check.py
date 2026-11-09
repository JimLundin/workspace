"""Every check, every time: the policy reviews, every production import, then every test.

    python -m scripts.check [--standards] [tests/test_x.py[::test_name] ...]

Named test files narrow only which tests run; the reviews and imports always run.
Native modules (tests/test_windows_*.py) skip themselves off Windows.
"""

import argparse
import contextlib
import importlib
import inspect
import io
import subprocess
import sys
import tempfile
import time
import traceback
import unittest
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from scripts import quality
from scripts.architecture import python_sources, review
from scripts.source_analysis import Cache, module_name

ROOT = Path(__file__).resolve().parent.parent
WINDOWS_IMPORTS = ("WinDLL", "WINFUNCTYPE", "windll", "winreg", "msvcrt", "_winapi", "PySide6", "shiboken6", "win32more")
"""Signs that an import failed only because this isn't Windows."""
STANDARDS = frozendict(
    {
        "ruff check": (sys.executable, "-m", "ruff", "check", "--no-fix", "."),
        "ruff format": (sys.executable, "-m", "ruff", "format", "--check", "."),
        "pyright": (sys.executable, "-m", "scripts.typecheck", "--threads", "--pythonpath", sys.executable),
    }
)
"""The whole-tree standards --standards runs beside the tests; CI's standards job runs them too."""


class Status(Enum):
    PASSED = "passed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class Failed:
    """A failed test, import or standard, with its complete console report."""

    node: str
    report: str


type Outcome = Status | Failed


@runtime_checkable
class Test(Protocol):
    __module__: str

    def __call__(self, **arguments: Path) -> object: ...


def windows_only(error: BaseException) -> bool:
    """Whether an import failed only because this isn't Windows; on Windows nothing is excused."""
    match sys.platform, error:
        case platform, ImportError() | AttributeError() | OSError() if platform != "win32":
            return any(name in str(error) for name in WINDOWS_IMPORTS)
        case _:
            return False


def failed(node: str, error: BaseException, output: str = "") -> Failed:
    captured = f"\nCaptured stderr:\n{output}" if output else ""
    return Failed(node, f"{node}\n{''.join(traceback.format_exception(error))}{captured}")


def import_failures(root: Path) -> Iterator[Failed]:
    """Import every production module: top-level modules and every module of a top-level package."""
    for name in python_sources(root):
        parts = Path(name).parts
        if name.endswith(".py") and parts[0] != "tests" and (len(parts) == 1 or (root / parts[0] / "__init__.py").is_file()):
            try:
                importlib.import_module(module_name(name))
            except Exception as error:
                if not windows_only(error):
                    yield failed(f"import {module_name(name)}", error)


def module_outcomes(selector: str) -> Iterator[Outcome]:
    """Import one test module and run its tests in order, or only the one `path::test_name` names."""
    path, separator, requested = selector.partition("::")
    module = module_name(path)
    try:
        loaded = importlib.import_module(module)
    except unittest.SkipTest:
        yield Status.SKIPPED
        return
    except Exception as error:
        yield Status.SKIPPED if windows_only(error) else failed(path, error)
        return
    tests = tuple(
        (label, test)
        for label, test in inspect.getmembers(loaded)
        if label.startswith("test_") and label == (requested or label) and isinstance(test, Test) and callable(test) and test.__module__ == module
    )
    if separator and not tests:
        yield Failed(selector, f"No test function matched {selector}")
    yield from (test_outcome(f"{path}::{label}", test) for label, test in tests)


def test_outcome(node: str, test: Test) -> Outcome:
    # Expected diagnostics from passing tests, such as SDK warnings for a
    # deliberately broken stream, would bury real failures; only failing tests publish them.
    output = io.StringIO()
    try:
        parameters = inspect.signature(test).parameters
        if set(parameters) - {"tmp_path"}:
            raise TypeError("Only tmp_path fixtures are supported.")
        # A shallow scratch folder: stores nest digest-named folders under it within Windows MAX_PATH.
        with contextlib.redirect_stderr(output), tempfile.TemporaryDirectory(prefix="workspace-check-") as scratch:
            test(**({"tmp_path": Path(scratch)} if parameters else {}))
    except unittest.SkipTest:
        return Status.SKIPPED
    except Exception as error:
        return failed(node, error, output.getvalue())
    return Status.PASSED


def standard_failures(name: str, command: tuple[str, ...]) -> tuple[Failed, ...]:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    return () if result.returncode == 0 else (Failed(name, f"{name} failed:\n{(result.stdout + result.stderr).strip()}"),)


def collected(standards: tuple[Future[tuple[Failed, ...]], ...]) -> Iterator[Failed]:
    for standard in standards:
        yield from standard.result()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--standards", action="store_true", help="also apply whole-tree Ruff and Pyright, as Dev.cmd check does")
    parser.add_argument("tests", nargs="*", help="run only these test files or tests/test_x.py::test_name selectors")
    args = parser.parse_args()
    started = time.perf_counter()
    # No application import or native effect before the source policies pass.
    cache = Cache.bound(ROOT)
    findings = review(ROOT, cache=cache).failures
    for finding in findings:
        print(finding.describe())
    if findings or quality.check(ROOT, cache=cache):
        raise SystemExit(1)
    tests = tuple[str, ...](args.tests) or tuple(
        name for name in python_sources(ROOT) if name.startswith("tests/") and Path(name).name.startswith("test_")
    )
    native = tuple(name for name in tests if name.startswith("tests/test_windows_"))
    generated = tuple(name for name in tests if name.startswith("tests/properties/"))
    portable = tuple(name for name in tests if name not in native and name not in generated)
    with ThreadPoolExecutor() as pool:
        standards = tuple(pool.submit(standard_failures, name, command) for name, command in STANDARDS.items()) if args.standards else ()
        outcomes = (
            # Hypothesis inspects loaded modules for constants: generated tests run before every production import.
            *(outcome for name in generated for outcome in module_outcomes(name)),
            *import_failures(ROOT),
            *(outcome for name in portable for outcome in module_outcomes(name)),
            # Native fixtures have real deadlines: they wait for whole-tree Pyright, which saturates the cores.
            *collected(standards),
            *(outcome for name in native for outcome in module_outcomes(name)),
        )
    failures = tuple(outcome for outcome in outcomes if isinstance(outcome, Failed))
    for failure in failures:
        print(failure.report)
    passed, skipped = outcomes.count(Status.PASSED), outcomes.count(Status.SKIPPED)
    print(f"{passed} passed, {len(failures)} failed, {skipped} skipped in {time.perf_counter() - started:.1f}s")
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
