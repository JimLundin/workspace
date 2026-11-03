"""selfcheck: is this copy of the workspace sound? Uses installed or bundled SDK dependencies.

    python selfcheck.py [FOLDER] [--fast] [--durations N]

1. Every .py file compiles.
2. Every module imports (off Windows, the ones that need Windows are skipped).
3. Every test passes: functions named test_* in tests/test_*.py. A test may take
   `tmp_path` (a fresh folder); a test module may raise unittest.SkipTest.

Prints a report; exits 0 if sound, 1 if not. The keeper runs this on every change
before installing it, so the agent can't change it (see keeper.py).
The optional fast editing profile defers tests/test_windows_*.py. The keeper
always uses the default full profile. Both profiles compile and import all source.

Discovered member values remain objects; the runner validates origin and the
supported keyword arguments before invoking a test.
"""

import argparse
import importlib
import inspect
import os
import py_compile
import sys
import tempfile
import time
import traceback
import unittest
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Protocol

import runtime

_WINDOWS_ONLY = ("WinDLL", "WINFUNCTYPE", "windll", "winreg", "msvcrt", "_winapi", "PySide6", "shiboken6", "win32more")
"""Signs that an import failed only because this isn't Windows."""


_ON_WINDOWS: bool = sys.platform == "win32"

WORKERS = 4
# Reviewed effect owners: fake desktop adapters, private localhost endpoints,
# and per-function temporary stores. These modules never use the shared desktop
# or installed source, so they run in worker processes alongside the remaining
# portable modules. An explicit inventory, rather than filename inference, keeps
# new/native tests sequential until their effects have been reviewed; it lives
# in this protected file so a change cannot widen it for its own install check.
# Heavier modules lead the queue. docs/test-execution-ownership.md records the
# reviewed resource owners. The full sequential suite outgrew the keeper's
# check limit, so installs failed before any test could fail.
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
# Strict elapsed deadlines suffer under competing SDK/source work. These and all
# native modules run after the workers exit, keeping their fixture costs stable.
AFTER_WORKERS = frozenset({"tests/test_agent_streaming.py"})


def _windows_only(error: BaseException) -> bool:
    return not _ON_WINDOWS and isinstance(error, (ImportError, AttributeError, OSError)) and any(w in str(error) for w in _WINDOWS_ONLY)


def _sources(root: Path) -> Iterator[Path]:
    # Do not enumerate bundled interpreters and dependencies just to discard them.
    for folder, directories, files in os.walk(root):
        directories[:] = sorted(name for name in directories if not name.startswith((".", "__pycache__")))
        for name in sorted(files):
            path = Path(folder) / name
            if path.suffix in (".py", ".pyw") and not name.startswith((".", "__pycache__")):
                yield path


def _modules(root: Path) -> Iterator[str]:
    """Top-level modules, and every module of every top-level package (tests excepted)."""
    for path in _sources(root):
        relative = path.relative_to(root).with_suffix("")
        parts = relative.parts
        if parts[0] == "tests" or path.name == "selfcheck.py" or path.suffix == ".pyw":
            continue
        if len(parts) == 1 or (root / parts[0] / "__init__.py").exists():
            yield ".".join(p for p in parts if p != "__init__") if parts[-1] == "__init__" else ".".join(parts)


def compile_all(root: Path, problems: list[str]) -> None:
    with tempfile.TemporaryDirectory() as scratch:
        for i, path in enumerate(_sources(root)):
            try:
                py_compile.compile(str(path), cfile=os.path.join(scratch, f"{i}.pyc"), doraise=True)
            except py_compile.PyCompileError as error:
                problems.append(f"doesn't compile: {path.relative_to(root).as_posix()}\n{error.msg}")


def import_all(root: Path, problems: list[str]) -> None:
    for name in _modules(root):
        try:
            importlib.import_module(name)
        except Exception as error:
            if not _windows_only(error):
                problems.append(f"doesn't import: {name}\n{''.join(traceback.format_exception(error))}")


class Test(Protocol):
    def __call__(self, **arguments: Path) -> object: ...


def _call(test: Test) -> None:
    arguments: dict[str, Path] = {}
    for name in inspect.signature(test).parameters:
        if name != "tmp_path":
            raise TypeError(f"selfcheck can only give a test tmp_path, not {name}")
        with tempfile.TemporaryDirectory(prefix="selfcheck-") as scratch:
            arguments[name] = Path(scratch)
            test(**arguments)
            return
    test(**arguments)


type Outcome = tuple[int, int, tuple[str, ...], tuple[tuple[float, str], ...]]
"""Passed tests, skipped modules, problems and per-test timings of one module run."""


def run_module(path: Path) -> Outcome:
    """Load one test module from the current tree and run its tests."""
    passed = skipped = 0
    problems: list[str] = []
    timings: list[tuple[float, str]] = []
    name = f"tests.{path.stem}"
    try:
        module = importlib.import_module(name)
    except unittest.SkipTest:
        return 0, 1, (), ()
    except Exception as error:
        if _windows_only(error):
            return 0, 1, (), ()
        return 0, 0, (f"FAILED {name} (while loading)\n{''.join(traceback.format_exception(error))}",), ()
    members: dict[str, object] = vars(module)
    for attribute, test in sorted(members.items()):
        if attribute.startswith("test_") and callable(test):
            origin: object = getattr(test, "__module__", None)
            if origin != name:
                continue
            invoke: Test = test
            started = time.perf_counter()
            try:
                _call(invoke)
                passed += 1
            except unittest.SkipTest:
                pass
            except Exception as error:
                problems.append(f"FAILED {name}.{attribute}\n{''.join(traceback.format_exception(error))}")
            finally:
                timings.append((time.perf_counter() - started, f"{name}.{attribute}"))
    return passed, skipped, tuple(problems), tuple(timings)


def _prepare_worker(root: str) -> None:
    sys.path.insert(0, root)
    os.chdir(root)
    os.environ.pop("WORKSPACE_E2E", None)
    runtime.activate(root=Path(root))
    sys.modules.pop("runtime", None)
    if (Path(root) / "assistant" / "sdk.py").is_file():
        # Resolve the SDK graph before Qt installs its per-module source inspection.
        importlib.import_module("assistant.sdk")


def _progress(path: Path, outcome: Outcome, seconds: float) -> None:
    """One line per module as it finishes, so a timed-out install shows where it stopped."""
    sys.stdout.write(f"{seconds:7.1f}s {path.name}: {outcome[0]} passed, {len(outcome[2])} failed\n")
    sys.stdout.flush()


def run_tests(root: Path, problems: list[str], *, fast: bool = False, timings: list[tuple[float, str]] | None = None) -> tuple[int, int]:
    """Passed tests, and skipped test modules.

    Reviewed portable modules run on worker processes while the other non-native
    modules run here; native modules run after the workers exit, one at a time.
    """
    paths = [path for path in sorted((root / "tests").glob("test_*.py")) if not (fast and path.name.startswith("test_windows_"))]
    relative = {path: path.relative_to(root).as_posix() for path in paths}
    portable = [path for name in PORTABLE for path in paths if relative[path] == name]
    following = [path for path in paths if path.name.startswith("test_windows_") or relative[path] in AFTER_WORKERS]
    alongside = [path for path in paths if path not in portable and path not in following]
    # This coordinator owns the run's counters and ledgers; workers return
    # immutable outcomes only.
    outcomes: list[Outcome] = []

    def sequential(group: list[Path]) -> None:
        for path in group:
            started = time.perf_counter()
            outcome = run_module(path)
            _progress(path, outcome, time.perf_counter() - started)
            outcomes.append(outcome)

    if len(portable) < 2:
        sequential([*portable, *alongside, *following])
    else:
        started = time.perf_counter()
        with ProcessPoolExecutor(max_workers=WORKERS, initializer=_prepare_worker, initargs=(str(root),)) as pool:
            pending = [(path, pool.submit(run_module, path)) for path in portable]
            sequential(alongside)
            for path, future in pending:
                try:
                    outcome = future.result()
                except Exception as error:
                    outcome = 0, 0, (f"FAILED tests.{path.stem} (in a worker)\n{''.join(traceback.format_exception(error))}",), ()
                _progress(path, outcome, time.perf_counter() - started)
                outcomes.append(outcome)
        sequential(following)
    for _, _, found, measured in outcomes:
        problems.extend(found)
        if timings is not None:
            timings.extend(measured)
    return sum(outcome[0] for outcome in outcomes), sum(outcome[1] for outcome in outcomes)


def check(root: Path, *, fast: bool = False, durations: int = 0) -> tuple[bool, str]:
    """Whether the copy at `root` is sound, and a report. Imports from `root`, so run
    it in a process of its own (as `main` does)."""
    os.environ.pop("WORKSPACE_E2E", None)  # never the end-to-end tests: they'd start a second workspace
    sys.path.insert(0, str(root))
    os.chdir(root)
    runtime.activate(root=root)
    candidate_runtime = root / "runtime.py"
    if candidate_runtime.is_file() and candidate_runtime.resolve() != Path(runtime.__file__).resolve():
        # This checker owns a fresh process. Drop only its preloaded bootstrap
        # cache entry so import_all executes the selected copy's runtime too.
        sys.modules.pop("runtime", None)
    problems: list[str] = []
    timings: list[tuple[float, str]] = []
    started = time.perf_counter()
    compile_all(root, problems)
    timings.append((time.perf_counter() - started, "compile all source"))
    if not problems:
        started = time.perf_counter()
        import_all(root, problems)
        timings.append((time.perf_counter() - started, "import all modules"))
    passed, skipped = run_tests(root, problems, fast=fast, timings=timings if durations else None) if not problems else (0, 0)
    summary = f"{passed} passed, {len([p for p in problems if p.startswith('FAILED')])} failed, {skipped} module{'' if skipped == 1 else 's'} skipped"
    if fast:
        deferred = len(list((root / "tests").glob("test_windows_*.py")))
        summary += f", {deferred} native module{'' if deferred == 1 else 's'} deferred (full checks run before install)"
    if durations:
        summary += "\nSlowest checks:\n" + "\n".join(f"{seconds:7.3f}s {name}" for seconds, name in sorted(timings, reverse=True)[:durations])
    return not problems, "\n\n".join([*problems, summary]) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", type=Path, default=Path(__file__).parent)
    parser.add_argument("--fast", action="store_true", help="editing checks; defer Windows integration modules")
    parser.add_argument("--durations", type=int, default=0, metavar="N", help="report the N slowest checks")
    match dict(inspect.getmembers(parser.parse_args())):
        case {"folder": Path() as folder, "fast": bool() as fast, "durations": int() as durations}:
            pass
        case _:
            parser.error("Invalid selfcheck arguments.")
    if durations < 0:
        parser.error("durations must be nonnegative")
    ok, report = check(folder.resolve(), fast=fast, durations=durations)
    sys.stdout.write(report)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
