"""A real environment, built by the real venv and the base interpreter's pip, runs its own interpreter."""

import subprocess
import sys
import unittest
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("Windows environments")

from environments import ensure, python, pythonw, ready


def test_a_real_environment_from_an_empty_lock_runs_its_own_interpreter(tmp_path: Path) -> None:
    # Defects: venv without pip can't be filled by the base interpreter's pip, the
    # interpreters are looked for in the wrong folder, or the environment's
    # interpreter still resolves to the base installation. An empty lock needs no network.
    lock = tmp_path / "empty.lock"
    lock.write_bytes(b"# no packages\n")
    environment = ensure(lock, root=tmp_path / "environments")
    assert ready(environment) and pythonw(environment).is_file()
    prefix = subprocess.run([python(environment), "-c", "import sys; print(sys.prefix)"], capture_output=True, text=True, check=True, timeout=30)
    assert Path(prefix.stdout.strip()).resolve() == environment.resolve()
