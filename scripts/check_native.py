"""Run selected source tests with the checkout's Windows development interpreter.

The coordinator owns source hashing and receipt binding. The native runner
imports the selected source tree and executes its reviewed plan, without
installing or launching Workspace or needing Git in the installed copy.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from scripts.check_results import Results, Selection
from scripts.development_paths import TEMP
lazy from scripts.check import DIRECT, combined_results, execute, worker_result
lazy from scripts.selection import NATIVE_LANES


@dataclass(frozen=True, slots=True, kw_only=True)
class NativeConfiguration:
    """The Windows runner's input; output is a Windows path."""

    selection: Selection
    output: str


NATIVE_CONFIGURATION = TypeAdapter(NativeConfiguration)
NATIVE_RESULT = TypeAdapter(Results)


def run_native(root: Path, configuration: Path) -> None:
    """Execute the configured selection in the Windows runner and publish its results."""
    settings = NATIVE_CONFIGURATION.validate_json(configuration.read_bytes(), strict=True)
    os.chdir(root)
    results = execute(settings.selection, root)
    Path(settings.output).write_bytes(NATIVE_RESULT.dump_json(results))
    raise SystemExit(bool(results.failures))


def lanes(selection: Selection) -> tuple[Selection | None, tuple[Selection, ...]]:
    """The main lane, if it has work, then the nonempty native lanes, which repeat no source review."""
    native = tuple(name for name in selection.tests if name.startswith("tests/test_windows_"))
    grouped = tuple(tuple(name for name in native if name.partition("::")[0] in lane) for lane in NATIVE_LANES)
    remaining = tuple(name for name in native if not any(name in group for group in grouped))
    separate = tuple(Selection(tests, (), DIRECT) for tests in (*grouped, remaining) if tests)
    main = Selection(tuple(name for name in selection.tests if name not in native), selection.changed, selection.reason)
    return (main if main.tests or main.changed or not separate else None), separate


def execute_lanes(root: Path, selection: Selection, settle: Callable[[], object]) -> Results:
    # Native lanes start after the main lane's portable workers exit and after
    # `settle` returns, so deadline-bound native fixtures never compete with the
    # pool or a whole-tree type check.
    main, separate = lanes(selection)
    first = (execute_native(root, main),) if main is not None else ()
    settle()
    with ThreadPoolExecutor(max_workers=max(1, len(separate))) as pool:
        following = tuple(worker_result(result) for result in pool.map(execute_native, (root,) * len(separate), separate))
    return combined_results((*first, *following))


def windows_path(path: Path) -> str:
    if os.name == "nt":
        return str(path.absolute())
    return subprocess.run(["wslpath", "-w", str(path.absolute())], capture_output=True, text=True, check=True).stdout.strip()


def execute_native(root: Path, selection: Selection) -> Results:
    scratch = Path(tempfile.mkdtemp(prefix="workspace-native-check-", dir=TEMP))
    try:
        configuration, output = scratch / "configuration.json", scratch / "result.json"
        configuration.write_bytes(NATIVE_CONFIGURATION.dump_json(NativeConfiguration(selection=selection, output=windows_path(output))))
        interpreter = sys.executable if os.name == "nt" else str(root / ".venv" / "Scripts" / "python.exe")
        # Run from root, so the runner imports the selected source tree.
        command = [interpreter, "-m", "scripts.check_native", windows_path(root), windows_path(configuration)]
        result = subprocess.run(command, cwd=root, check=False, timeout=600)
        if not output.exists():
            raise RuntimeError("The Windows test process did not write its result; no receipt can be produced.")
        try:
            record = NATIVE_RESULT.validate_json(output.read_bytes(), strict=True)
        except ValidationError as error:
            raise ValueError("Invalid Windows check result.") from error
        if result.returncode and not record.failures:
            raise RuntimeError("Windows checks exited unsuccessfully; no success receipt can be produced.")
        return record
    finally:
        shutil.rmtree(scratch)


if __name__ == "__main__":
    run_native(Path(sys.argv[1]), Path(sys.argv[2]))
