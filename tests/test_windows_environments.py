"""A real environment, built by the real uv from a real lock, runs its own interpreter."""

import subprocess
import sys
import unittest
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("Windows environments")

from environments import ensure, python, pythonw, ready, uv


def test_a_real_environment_from_a_dependency_free_project_runs_its_own_interpreter(tmp_path: Path) -> None:
    # Defects: uv sync can't build from a copy's pyproject and lock, the
    # interpreters are looked for in the wrong folder, or the environment's
    # interpreter still resolves to the base installation. No dependencies: no network.
    project = tmp_path / "workspace"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0"\nrequires-python = ">=3.15"\ndependencies = []\n\n[tool.uv]\npackage = false\n',
        encoding="utf-8",
    )
    subprocess.run([uv(), "lock", "--offline", "--project", project], check=True, capture_output=True, timeout=60)
    environment = ensure(project, root=tmp_path / "environments")
    assert ready(environment) and pythonw(environment).is_file()
    prefix = subprocess.run([python(environment), "-c", "import sys; print(sys.prefix)"], capture_output=True, text=True, check=True, timeout=30)
    assert Path(prefix.stdout.strip()).resolve() == environment.resolve()
