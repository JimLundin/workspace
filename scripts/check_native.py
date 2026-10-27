"""Run selected source tests with the checkout's Windows development interpreter.

WSL owns source hashing and receipt binding. The native runner only imports the
selected source tree and executes its tests sequentially, without installing or
launching Workspace and without needing Git in the Downloads installation.
"""

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import StrictFloat, StrictInt, StrictStr, TypeAdapter, ValidationError

from scripts.deploy_files import write

LIVE = Path('/mnt/c/Users/Jim.Lundin/Downloads/workspace-sdk/workspace')
TEMP = Path('/mnt/c/Users/Jim.Lundin/AppData/Local/Temp')

RUNNER = '''import json, os, sys
from pathlib import Path
configuration = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
root = Path(configuration["root"])
os.environ["WORKSPACE_BUNDLED_RUNTIME"] = configuration["runtime"]
sys.path.insert(0, str(root))
from scripts.check import Selection, execute
selection = Selection(tuple(configuration["tests"]), tuple(configuration["changed"]), configuration["reason"])
passed, skipped, failures, timings = execute(selection, root)
Path(configuration["output"]).write_text(json.dumps({"passed": passed, "skipped": skipped,
    "failures": failures, "timings": timings}), encoding="utf-8")
sys.exit(bool(failures))
'''


@dataclass(frozen=True, slots=True)
class NativeResult:
    passed: StrictInt
    skipped: StrictInt
    failures: tuple[StrictStr, ...]
    timings: tuple[tuple[StrictFloat, StrictStr], ...]


NATIVE_RESULT = TypeAdapter[NativeResult](NativeResult)


def windows_path(path: Path) -> str:
    return subprocess.run(['wslpath', '-w', str(path.absolute())], capture_output=True, text=True, check=True).stdout.strip()


def execute_native(
    root: Path, tests: tuple[str, ...], changed: tuple[str, ...], reason: str,
) -> tuple[int, int, tuple[str, ...], tuple[tuple[float, str], ...]]:
    scratch = Path(tempfile.mkdtemp(prefix='workspace-native-check-', dir=TEMP))
    try:
        runner, configuration, output = scratch / 'run.py', scratch / 'configuration.json', scratch / 'result.json'
        runner.write_text(RUNNER, encoding='utf-8')
        write(configuration, {'root': windows_path(root), 'tests': tests, 'changed': changed, 'reason': reason,
                              'output': windows_path(output), 'runtime': windows_path(LIVE / '.runtime')})
        result = subprocess.run([str(root / '.venv' / 'Scripts' / 'python.exe'), '-B', windows_path(runner), windows_path(configuration)],
                                cwd=scratch, check=False, timeout=600)
        if not output.exists():
            raise RuntimeError('The Windows test process did not write its result; no receipt can be produced.')
        try:
            record = NATIVE_RESULT.validate_json(output.read_bytes())
        except ValidationError as error:
            raise ValueError('Invalid Windows check result.') from error
        if result.returncode and not record.failures:
            raise RuntimeError('Windows checks exited unsuccessfully; no success receipt can be produced.')
        return record.passed, record.skipped, record.failures, record.timings
    finally:
        shutil.rmtree(scratch)
