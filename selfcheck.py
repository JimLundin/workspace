"""selfcheck: is this copy of the workspace sound? Uses installed or bundled SDK dependencies.

    python selfcheck.py [FOLDER] [--fast | --native] [--changed-from BASE] [--durations N]
                        [--previous REPORT] [--stop-at-first-failure]

1. Every .py file compiles.
2. Every module imports (off Windows, the ones that need Windows are skipped).
3. Every test passes: functions named test_* in tests/test_*.py. A test may take
   `tmp_path` (a fresh folder); a test module may raise unittest.SkipTest.

Prints a report; exits 0 if sound, 1 if not. The keeper runs this on every change
before installing it, so the agent can't change it (see keeper.py).
The fast editing profile defers tests/test_windows_*.py. The native profile runs
only those modules: the keeper uses it when the agent's fast check already passed
for exactly the same source digest, so compiling, importing and the portable
tests are not repeated back to back. Any other install gets the full profile.
With --changed-from, a check runs only the test modules that import a file changed
from BASE, directly or through test helpers, and compiles and imports only changed
source. A changed asset in ASSET_READERS counts as a change to its readers; any other
non-Python change runs the whole profile. The full suite runs in CI.
With --previous, the modules that failed in that earlier report run first, alone,
so a retried fix that still fails says so in seconds. With --stop-at-first-failure
no module starts after one fails: an install check needs only a yes or no.

Discovered member values remain objects; the runner validates origin and the
supported keyword arguments before invoking a test.
"""

import argparse
import ast
import importlib
import inspect
import os
import subprocess
import sys
import tempfile
import time
import traceback
import unittest
from collections.abc import Iterable, Iterator, Mapping
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import FunctionType
from typing import Final, Protocol

lazy from pydantic import TypeAdapter

lazy from winapi.processes import ProcessJob

_WINDOWS_ONLY = ("WinDLL", "WINFUNCTYPE", "windll", "winreg", "msvcrt", "_winapi", "PySide6", "shiboken6", "win32more")
"""Signs that an import failed only because this isn't Windows."""


_ON_WINDOWS: bool = sys.platform == "win32"


class Profile(Enum):
    FULL = "full"
    """Compile and import all source, then run every test module."""
    FAST = "fast"
    """Compile and import all source, then run every module except tests/test_windows_*.py."""
    NATIVE = "native"
    """Only tests/test_windows_*.py: the rest of a source digest the fast profile passed."""


@dataclass(frozen=True, slots=True)
class Scope:
    """Which tests a check runs: a profile, optionally narrowed to a change from `base`."""

    profile: Profile
    base: Path | None = None
    """The running source the candidate changes; None runs the profile's whole suite."""
    first: frozenset[str] = frozenset()
    """Test modules (tests/test_x.py) to run before the rest: the ones that failed last time."""
    stop: bool = False
    """Start no module after one fails."""


FULL_SCOPE = Scope(Profile.FULL)
"""The keeper's default gate: every test module."""

_DOCUMENTS = ("docs/", ".github/", ".vscode/", "typings/", ".git")
"""Changes no test reads: documentation, repository and editor configuration, type stubs."""
_TEXT = frozenset({"AGENTS.md", "README.md", "GLOSSARY.md"})

ASSET_READERS: Final = frozendict(
    {
        "pyproject.toml": ("scripts/architecture.py", "scripts/quality.py", "scripts/source_analysis.py", "scripts/check.py"),
        "Dev.cmd": ("scripts/check.py", "scripts/deploy.py"),
        "scripts/dev.ps1": ("scripts/check.py", "scripts/deploy.py"),
        "StartWorkspace.cmd": ("environments.py",),
        "assistant/uia.ps1": ("assistant/uia.py",),
        "desktop_ui/fonts/": ("desktop_ui/components/typeface.py", "desktop_ui/components/text.py"),
        "tests/uia_fixture.ps1": ("tests/test_windows_computer.py",),
        # A sample log for `scripts.navigation_report --log`; no test reads it.
        "tests/navigation_report_fixture.jsonl": (),
    }
)
"""Each non-Python source file (or folder ending in /) and the source files that read it.

A changed asset counts as a change to its readers. Any other non-Python file, such as
a runtime pin, has unknown readers and selects every test.
"""


def asset_readers(name: str) -> tuple[str, ...] | None:
    """The source files a changed non-Python file affects: none for documents, None when unknown."""
    if name.startswith(_DOCUMENTS) or name in _TEXT:
        return ()
    for asset, readers in ASSET_READERS.items():
        if name == asset or (asset.endswith("/") and name.startswith(asset)):
            return readers
    return None


def _files(root: Path) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for folder, directories, files in os.walk(root):
        directories[:] = [name for name in directories if not name.startswith(".") and name != "__pycache__"]
        for name in files:
            path = Path(folder) / name
            if not name.startswith(".") and path.suffix != ".pyc":
                found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


def changed_files(root: Path, base: Path) -> frozenset[str]:
    """Source files that differ between the candidate and the source it changes."""
    candidate, running = _files(root), _files(base)
    return frozenset(name for name in candidate.keys() | running.keys() if candidate.get(name) != running.get(name))


def _module(name: str) -> str:
    parts = name.removesuffix(".pyw").removesuffix(".py").split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imports(name: str, text: str) -> frozenset[str]:
    """Modules a source file imports, with their packages; relative imports resolved."""
    package = _module(name).split(".")
    if not name.endswith("__init__.py"):
        package = package[:-1]
    found: set[str] = set()
    for node in ast.walk(ast.parse(text, filename=name)):
        match node:
            case ast.Import(names=aliases):
                found.update(alias.name for alias in aliases)
            case ast.ImportFrom(module=module, names=aliases, level=level):
                prefix = ".".join(package[: len(package) - level + 1]) if level else ""
                origin = ".".join(part for part in (prefix, module or "") if part)
                found.add(origin)
                found.update(f"{origin}.{alias.name}" for alias in aliases)
            case _:
                pass
    return frozenset(module for name in found for module in _ancestors(name))


def _ancestors(module: str) -> Iterator[str]:
    parts = module.split(".")
    for end in range(1, len(parts) + 1):
        yield ".".join(parts[:end])


type Imports = Mapping[str, frozenset[str]]
"""Each test source file (tests/x.py) and the modules it imports, with their packages."""


def tests_imports(root: Path) -> dict[str, frozenset[str]]:
    """The imports of every test source file directly under tests/."""
    return {
        path.relative_to(root).as_posix(): imports(path.relative_to(root).as_posix(), path.read_text(encoding="utf-8"))
        for path in (root / "tests").glob("*.py")
    }


def module_inputs(found: Imports) -> dict[str, frozenset[str]]:
    """Each test module's inputs: itself, the test helpers it reaches, and the modules those import.

    Production imports are not followed further; the full suite runs in CI.
    """
    by_module = {_module(name): (name, modules) for name, modules in found.items()}
    helpers = frozenset(module for module, (name, _) in by_module.items() if not Path(name).name.startswith("test_"))
    result: dict[str, frozenset[str]] = {}
    for module in sorted(by_module.keys() - helpers):
        # Each module's input set grows locally; only the frozen set leaves.
        inputs = {module, *by_module[module][1]}
        while extra := {name for helper in inputs & helpers for name in by_module[helper][1]} - inputs:
            inputs |= extra
        result[by_module[module][0]] = frozenset(inputs)
    return result


def affected_tests(root: Path, changed: Iterable[str], found: Imports | None = None) -> frozenset[str] | None:
    """Test modules whose inputs include a changed module, or a reader of a changed asset.

    The one incremental selection: the keeper's install check and Dev.cmd check
    (which passes its cached `found`) both use it. None means every test: a
    changed non-Python file has unknown readers.
    """
    reached: set[str] = set()
    for name in changed:
        if name.endswith((".py", ".pyw")):
            reached.add(_module(name))
        elif (readers := asset_readers(name)) is None:
            return None
        else:
            reached.update(_module(reader) for reader in readers)
    if not reached:
        return frozenset()
    return frozenset(name for name, inputs in module_inputs(tests_imports(root) if found is None else found).items() if inputs & reached)


def _selected(path: Path, profile: Profile) -> bool:
    native = path.name.startswith("test_windows_")
    match profile:
        case Profile.FULL:
            return True
        case Profile.FAST:
            return not native
        case Profile.NATIVE:
            return native


WORKERS = 4
# Reviewed effect owners: fake desktop adapters, private localhost endpoints,
# and per-function temporary stores. These modules never use the shared desktop
# or installed source, so they run in worker processes alongside the remaining
# portable modules. An explicit inventory, rather than filename inference, keeps
# new/native tests sequential until their effects have been reviewed; it lives
# in this protected file so a change cannot widen it for its own install check.
# Heavier modules lead the queue. The full sequential suite outgrew the keeper's
# check limit, so installs failed before any test could fail.
PORTABLE = (
    "tests/test_agent.py",
    "tests/test_publishing.py",
    "tests/test_architecture.py",
    "tests/test_quality.py",
    "tests/test_work_store.py",
    "tests/test_work_actions.py",
    "tests/test_meetings.py",
    "tests/test_selfcheck.py",
    "tests/test_computer_tools.py",
    "tests/test_work_execution.py",
    "tests/test_feed_triage_service.py",
    "tests/test_commands.py",
    "tests/test_project_context.py",
    "tests/test_llm.py",
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

NATIVE_LANES: Final = (
    # Each launches real Edge processes on disposable profiles.
    ("tests/test_windows_browser.py",),
    ("tests/test_windows_runtime.py", "tests/test_windows_test_desktop.py"),
    ("tests/test_windows_computer.py", "tests/test_windows_development.py"),
)
"""Slow native modules that wait on child processes and share no machine-wide state.

Each lane, and then the remaining native modules together, runs in its own process
on its own private desktop once the portable workers exit. Audio endpoints and the
keyboard hook stay in the remaining lane, so their modules never overlap. The lanes
live in this protected file so a change cannot widen them for its own install check.
"""


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
    # In memory: writing hundreds of scratch .pyc files cost several times the compilation.
    for path in _sources(root):
        try:
            compile(path.read_bytes(), str(path), "exec")
        except (SyntaxError, ValueError) as error:
            problems.append(f"doesn't compile: {path.relative_to(root).as_posix()}\n{error}")


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
            if not isinstance(test, FunctionType) or test.__module__ != name:  # Defined here, not imported.
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
    os.environ.pop("WORKSPACE_E2E", None)  # The SDK loads when a test first runs an agent, not up front.


@dataclass(frozen=True, slots=True)
class LaneOutcome:
    """A native lane process's combined result, written for the coordinating check."""

    passed: int
    skipped: int
    problems: tuple[str, ...]
    timings: tuple[tuple[float, str], ...]


def native_groups(root: Path, paths: list[Path]) -> tuple[list[list[Path]], list[Path]]:
    """The selected native modules of each lane (empty lanes omitted), and the remaining ones."""
    relative = {path: path.relative_to(root).as_posix() for path in paths}
    grouped = [[path for path in paths if relative[path] in lane] for lane in NATIVE_LANES]
    remaining = [path for path in paths if not any(relative[path] in lane for lane in NATIVE_LANES)]
    return [group for group in grouped if group], remaining


def run_lane(paths: list[Path], result: Path) -> bool:
    """Run one lane's modules here, in order, and write their combined outcome to `result`."""
    outcomes: list[Outcome] = []
    for path in paths:
        started = time.perf_counter()
        outcome = run_module(path)
        _progress(path, outcome, time.perf_counter() - started)
        outcomes.append(outcome)
    combined = LaneOutcome(
        sum(outcome[0] for outcome in outcomes),
        sum(outcome[1] for outcome in outcomes),
        tuple(problem for outcome in outcomes for problem in outcome[2]),
        tuple(timing for outcome in outcomes for timing in outcome[3]),
    )
    result.write_bytes(TypeAdapter(LaneOutcome).dump_json(combined))
    return not combined.problems


def _lane_failure(group: list[Path], text: str) -> Outcome:
    return 0, 0, (f"FAILED native lane ({', '.join(path.name for path in group)}): {text}",), ()


class Lanes:
    """Native lane processes running beside the coordinator, each on a private desktop of its own.

    Each process runs this protected runner, not the candidate's. It drops the
    inherited test desktop, so its first `import tests` gives it a private desktop
    of its own. A job owns them: a check that is cancelled or times out ends its
    lanes with it instead of leaving them running.
    """

    def __init__(self, root: Path, groups: list[list[Path]]) -> None:
        environment = {key: value for key, value in os.environ.items() if key != "WORKSPACE_TEST_DESKTOP"}
        self.scratch = tempfile.TemporaryDirectory(prefix="selfcheck-lanes-")
        self.job = _job()
        self.running: list[tuple[list[Path], Path, Path, subprocess.Popen[bytes]]] = []
        for index, group in enumerate(groups):
            result, log = Path(self.scratch.name) / f"lane-{index}.json", Path(self.scratch.name) / f"lane-{index}.txt"
            names = [path.relative_to(root).as_posix() for path in group]
            command = [sys.executable, os.path.abspath(__file__), str(root), "--modules", ",".join(names), "--result", str(result)]
            with log.open("wb") as output:
                process = subprocess.Popen(command, cwd=root, env=environment, stdout=output, stderr=subprocess.STDOUT)
            if self.job is not None:
                self.job.add(process.pid)
            self.running.append((group, result, log, process))

    def collect(self) -> list[Outcome]:
        """Wait for every lane and its outcome; a lane that died without a result fails."""
        outcomes: list[Outcome] = []
        try:
            for group, result, log, process in self.running:
                code = process.wait()
                report = log.read_text(encoding="utf-8", errors="replace")
                sys.stdout.write(report)
                sys.stdout.flush()
                try:
                    lane = TypeAdapter(LaneOutcome).validate_json(result.read_bytes())
                except OSError, ValueError:
                    outcomes.append(_lane_failure(group, f"exited {code} without a result\n{report[-2000:]}"))
                    continue
                outcomes.append((lane.passed, lane.skipped, lane.problems, lane.timings))
                if code and not lane.problems:
                    outcomes.append(_lane_failure(group, f"exited {code}"))
        finally:
            if self.job is not None:
                self.job.close()
            self.scratch.cleanup()
        return outcomes


def _job() -> ProcessJob | None:
    """A job that ends the lanes when this check ends; None off Windows."""
    return ProcessJob() if _ON_WINDOWS else None


def _progress(path: Path, outcome: Outcome, seconds: float) -> None:
    """One line per module as it finishes, so a timed-out install shows where it stopped."""
    sys.stdout.write(f"{seconds:7.1f}s {path.name}: {outcome[0]} passed, {len(outcome[2])} failed\n")
    sys.stdout.flush()


def test_paths(root: Path, profile: Profile, changed: frozenset[str] | None) -> list[Path]:
    """The profile's test modules, in name order, narrowed to those `changed` affects."""
    paths = [path for path in sorted((root / "tests").glob("test_*.py")) if _selected(path, profile)]
    affected = affected_tests(root, changed) if changed is not None else None
    return paths if affected is None else [path for path in paths if path.relative_to(root).as_posix() in affected]


def import_changed(root: Path, changed: frozenset[str], problems: list[str]) -> None:
    """Compile every changed Python file and import the changed production modules."""
    for name in sorted(changed):
        if not name.endswith((".py", ".pyw")) or not (root / name).is_file():
            continue
        try:
            compile((root / name).read_text(encoding="utf-8"), name, "exec")
        except SyntaxError as error:
            problems.append(f"doesn't compile: {name}\n{error}")
            continue
        module = _module(name)
        if name.endswith(".py") and not name.startswith("tests/") and name != "selfcheck.py":
            try:
                importlib.import_module(module)
            except Exception as error:
                if not _windows_only(error):
                    problems.append(f"doesn't import: {module}\n{''.join(traceback.format_exception(error))}")


def failed_modules(report: str) -> frozenset[str]:
    """The test modules an earlier report names as failed: `FAILED tests.test_x[.test_y]`."""
    return frozenset(
        f"tests/{line.removeprefix('FAILED tests.').split('.')[0].split()[0]}.py"
        for line in report.splitlines()
        if line.startswith("FAILED tests.test_")
    )


type Runs = tuple[list[Path], list[Path], list[Path], list[Path], list[Path]]
"""Leading (last time's failures), portable (workers), alongside (here, beside the
workers), later (after the workers) and native modules, each in run order."""


def partition(root: Path, paths: list[Path], first: frozenset[str]) -> Runs:
    """Which runner takes each selected module."""
    relative = {path: path.relative_to(root).as_posix() for path in paths}
    leading = [path for path in paths if relative[path] in first]
    rest = [path for path in paths if path not in leading]
    portable = [path for name in PORTABLE for path in rest if relative[path] == name]
    native = [path for path in rest if path.name.startswith("test_windows_")]
    later = [path for path in rest if relative[path] in AFTER_WORKERS and path not in native]
    alongside = [path for path in rest if path not in portable and path not in native and path not in later]
    return leading, portable, alongside, later, native


def run_tests(root: Path, problems: list[str], paths: list[Path], scope: Scope = FULL_SCOPE) -> tuple[int, int, tuple[tuple[float, str], ...]]:
    """Passed tests, skipped test modules and per-test timings.

    `scope.first` modules run first, alone. Then reviewed portable modules run on
    worker processes while the other non-native modules run here. Native modules
    run after the workers exit: in parallel lane processes when they span more than
    one lane, otherwise here. With `scope.stop`, nothing starts after a failure, and
    the modules left out are reported.
    """
    leading, portable, alongside, later, native = partition(root, paths, scope.first)
    # This coordinator owns the run's counters and ledgers; workers return
    # immutable outcomes only.
    outcomes: list[Outcome] = []
    ran: set[Path] = set()
    """The modules that ran, whichever runner ran them; a lane reports once for all of its modules."""

    def failed() -> bool:
        return scope.stop and any(outcome[2] for outcome in outcomes)

    def sequential(group: list[Path]) -> None:
        for path in group:
            if failed():
                return
            started = time.perf_counter()
            outcome = run_module(path)
            _progress(path, outcome, time.perf_counter() - started)
            outcomes.append(outcome)
            ran.add(path)

    sequential(leading)
    if len(portable) < 2:
        sequential([*portable, *alongside, *later])
    elif not failed():
        started = time.perf_counter()
        with ProcessPoolExecutor(max_workers=WORKERS, initializer=_prepare_worker, initargs=(str(root),)) as pool:
            pending = [(path, pool.submit(run_module, path)) for path in portable]
            sequential(alongside)
            for path, future in pending:
                if failed():
                    pool.shutdown(wait=True, cancel_futures=True)
                    break
                try:
                    outcome = future.result()
                except BrokenProcessPool:
                    # Some hosts refuse worker processes (CI's Windows runner denies the
                    # handle duplication spawning needs); those modules run here instead.
                    outcome = run_module(path)
                except Exception as error:
                    outcome = 0, 0, (f"FAILED tests.{path.stem} (in a worker)\n{''.join(traceback.format_exception(error))}",), ()
                _progress(path, outcome, time.perf_counter() - started)
                outcomes.append(outcome)
                ran.add(path)
        sequential(later)
    # The slow lanes run in their own processes while the coordinator runs the
    # remaining native modules itself, as it did before there were lanes.
    groups, remaining = native_groups(root, native)
    lanes = Lanes(root, groups) if groups and not failed() else None
    sequential(remaining if lanes is not None else native)
    if lanes is not None:
        outcomes.extend(lanes.collect())
        ran.update(path for group in groups for path in group)
    for _, _, found, _ in outcomes:
        problems.extend(found)
    if (left := len(paths) - len(ran)) and failed():
        problems.append(f"Stopped at the first failure: {left} affected test module{'' if left == 1 else 's'} not run.")
    measured = tuple(timing for outcome in outcomes for timing in outcome[3])
    return sum(outcome[0] for outcome in outcomes), sum(outcome[1] for outcome in outcomes), measured


def _enter(root: Path) -> None:
    """Make this fresh process import from `root`."""
    os.environ.pop("WORKSPACE_E2E", None)  # never the end-to-end tests: they'd start a second workspace
    sys.path.insert(0, str(root))
    os.chdir(root)


def check(root: Path, scope: Scope = FULL_SCOPE, durations: int = 0) -> tuple[bool, str]:
    """Whether the copy at `root` is sound, and a report. Imports from `root`, so run
    it in a process of its own (as `main` does)."""
    _enter(root)
    problems: list[str] = []
    timings: list[tuple[float, str]] = []
    profile = scope.profile
    changed = changed_files(root, scope.base) if scope.base is not None else None
    if profile is not Profile.NATIVE and changed is not None:
        started = time.perf_counter()
        import_changed(root, changed, problems)
        timings.append((time.perf_counter() - started, "compile and import changed source"))
    elif profile is not Profile.NATIVE:
        started = time.perf_counter()
        compile_all(root, problems)
        timings.append((time.perf_counter() - started, "compile all source"))
        if not problems:
            started = time.perf_counter()
            import_all(root, problems)
            timings.append((time.perf_counter() - started, "import all modules"))
    paths = test_paths(root, profile, changed)
    passed, skipped, measured = run_tests(root, problems, paths, scope) if not problems else (0, 0, ())
    timings.extend(measured)
    summary = f"{passed} passed, {len([p for p in problems if p.startswith('FAILED')])} failed, {skipped} module{'' if skipped == 1 else 's'} skipped"
    if scope.base is not None:
        summary += f", {len(paths)} affected test module{'' if len(paths) == 1 else 's'} (the full suite runs in CI)"
    if profile is Profile.FAST:
        deferred = len(list((root / "tests").glob("test_windows_*.py")))
        summary += f", {deferred} native module{'' if deferred == 1 else 's'} deferred (full checks run before install)"
    if durations:
        summary += "\nSlowest checks:\n" + "\n".join(f"{seconds:7.3f}s {name}" for seconds, name in sorted(timings, reverse=True)[:durations])
    return not problems, "\n\n".join([*problems, summary]) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", type=Path, default=Path(__file__).parent)
    profiles = parser.add_mutually_exclusive_group()
    profiles.add_argument("--fast", action="store_true", help="editing checks; defer Windows integration modules")
    profiles.add_argument("--native", action="store_true", help="only the Windows integration modules a passing fast check deferred")
    parser.add_argument("--durations", type=int, default=0, metavar="N", help="report the N slowest checks")
    parser.add_argument("--changed-from", type=Path, metavar="BASE", help="run only tests affected by changes from BASE")
    parser.add_argument("--previous", type=Path, metavar="REPORT", help="first run the modules that failed in this earlier report")
    parser.add_argument("--stop-at-first-failure", action="store_true", help="start no test module after one fails")
    parser.add_argument("--modules", default="", help=argparse.SUPPRESS)
    parser.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    match dict(inspect.getmembers(parser.parse_args())):
        case {
            "folder": Path() as folder,
            "fast": bool() as fast,
            "native": bool() as native,
            "durations": int() as durations,
            "changed_from": (Path() | None) as base,
            "previous": (Path() | None) as previous,
            "stop_at_first_failure": bool() as stop,
            "modules": str() as modules,
            "result": (Path() | None) as result,
        }:
            pass
        case _:
            parser.error("Invalid selfcheck arguments.")
    if result is not None:
        # A native lane that run_lanes started: exactly these modules, no source review.
        root = folder.resolve()
        _enter(root)
        sys.exit(0 if run_lane([root / name for name in modules.split(",")], result.resolve()) else 1)
    if durations < 0:
        parser.error("durations must be nonnegative")
    profile = Profile.FAST if fast else Profile.NATIVE if native else Profile.FULL
    try:
        first = failed_modules(previous.read_text(encoding="utf-8", errors="replace")) if previous is not None else frozenset[str]()
    except OSError:
        first = frozenset[str]()  # No earlier report: nothing failed before.
    ok, report = check(folder.resolve(), Scope(profile, base.resolve() if base is not None else None, first, stop=stop), durations)
    sys.stdout.write(report)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    # Worker processes re-run this script from the checked folder, so a relative
    # invocation path (CI's) must be resolved before check() changes directory.
    __file__ = os.path.abspath(__file__)
    main()
