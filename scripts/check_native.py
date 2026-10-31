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
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from scripts.check_results import Results
from scripts.deploy_files import write
from scripts.development_paths import LIVE, TEMP

RUNNER = """import json, os, sys
from pathlib import Path
lazy from scripts.check import Selection, execute
lazy from scripts.check_native import NATIVE_RESULT
if __name__ == "__main__":
    configuration = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    root = Path(configuration["root"])
    os.chdir(root)
    os.environ["WORKSPACE_BUNDLED_RUNTIME"] = configuration["runtime"]
    sys.path.insert(0, str(root))
    selection = Selection(tuple(configuration["tests"]), tuple(configuration["changed"]), configuration["reason"])
    results = execute(selection, root)
    Path(configuration["output"]).write_bytes(NATIVE_RESULT.dump_json(results))
    sys.exit(bool(results.failures))
"""


NATIVE_RESULT = TypeAdapter(Results)


def windows_path(path: Path) -> str:
    if os.name == "nt":
        return str(path.absolute())
    return subprocess.run(["wslpath", "-w", str(path.absolute())], capture_output=True, text=True, check=True).stdout.strip()


def execute_native(
    root: Path,
    tests: tuple[str, ...],
    changed: tuple[str, ...],
    reason: str,
) -> Results:
    scratch = Path(tempfile.mkdtemp(prefix="workspace-native-check-", dir=TEMP))
    try:
        runner, configuration, output = scratch / "run.py", scratch / "configuration.json", scratch / "result.json"
        runner.write_text(RUNNER, encoding="utf-8")
        write(
            configuration,
            {
                "root": windows_path(root),
                "tests": tests,
                "changed": changed,
                "reason": reason,
                "output": windows_path(output),
                "runtime": windows_path(LIVE / ".runtime"),
            },
        )
        interpreter = sys.executable if os.name == "nt" else str(root / ".venv" / "Scripts" / "python.exe")
        result = subprocess.run([interpreter, "-B", windows_path(runner), windows_path(configuration)], cwd=scratch, check=False, timeout=600)
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
