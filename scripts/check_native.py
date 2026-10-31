"""Run selected source tests with the checkout's Windows development interpreter.

The coordinator owns source hashing and receipt binding. The native runner
imports the selected source tree and executes its reviewed plan, without
installing or launching Workspace or needing Git in the Downloads installation.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from scripts.check_results import Results, Selection
from scripts.development_paths import LIVE, TEMP
lazy from scripts.check import execute

RUNNER = """import sys
from pathlib import Path
lazy from scripts.check_native import run_native
if __name__ == "__main__":
    sys.path.insert(0, sys.argv[1])
    run_native(Path(sys.argv[1]), Path(sys.argv[2]))
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class NativeConfiguration:
    """The Windows runner's input; output and runtime are Windows paths."""

    selection: Selection
    output: str
    runtime: str


NATIVE_CONFIGURATION = TypeAdapter(NativeConfiguration)
NATIVE_RESULT = TypeAdapter(Results)


def run_native(root: Path, configuration: Path) -> None:
    """Execute the configured selection in the Windows runner and publish its results."""
    settings = NATIVE_CONFIGURATION.validate_json(configuration.read_bytes(), strict=True)
    os.chdir(root)
    os.environ["WORKSPACE_BUNDLED_RUNTIME"] = settings.runtime
    results = execute(settings.selection, root)
    Path(settings.output).write_bytes(NATIVE_RESULT.dump_json(results))
    raise SystemExit(bool(results.failures))


def windows_path(path: Path) -> str:
    if os.name == "nt":
        return str(path.absolute())
    return subprocess.run(["wslpath", "-w", str(path.absolute())], capture_output=True, text=True, check=True).stdout.strip()


def execute_native(root: Path, selection: Selection) -> Results:
    scratch = Path(tempfile.mkdtemp(prefix="workspace-native-check-", dir=TEMP))
    try:
        runner, configuration, output = scratch / "run.py", scratch / "configuration.json", scratch / "result.json"
        runner.write_text(RUNNER, encoding="utf-8")
        configuration.write_bytes(
            NATIVE_CONFIGURATION.dump_json(
                NativeConfiguration(selection=selection, output=windows_path(output), runtime=windows_path(LIVE / ".runtime"))
            )
        )
        interpreter = sys.executable if os.name == "nt" else str(root / ".venv" / "Scripts" / "python.exe")
        result = subprocess.run(
            [interpreter, "-B", windows_path(runner), windows_path(root), windows_path(configuration)], cwd=scratch, check=False, timeout=600
        )
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
