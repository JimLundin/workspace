"""Workspace's dependencies: one virtual environment per dependency lock, built by pip.

The pinned, hashed lock (`requirements/windows-py315.lock`) names every
third-party package exactly. Each distinct lock gets its own environment under
`%LOCALAPPDATA%/workspace/environments/<hash of the lock>`, built once from PyPI:
a venv without pip, filled by the base interpreter's pip (`pip --python`). An
environment is ready only once its marker is written, last; a build that failed
or was interrupted has no marker, and the next `ensure` builds it again from
scratch. Undoing a dependency change switches back to the previous lock's
environment, still on disk.

Standard library only: the keeper (and `workspace.pyw`, before anything else)
imports this module to find the interpreter it should be running.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ROOT: Final = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "workspace" / "environments"
"""Where environments live: outside the installed copy, so installs and undo never touch them."""
LOCK: Final = Path("requirements") / "windows-py315.lock"
"""The lock, relative to a copy of Workspace."""
MARKER: Final = "workspace-environment.json"
"""Written last: an environment without it is incomplete."""
_NO_WINDOW: Final = 0x08000000 if sys.platform == "win32" else 0


class DependencyError(OSError):
    """The environment for a lock could not be built; the message ends with the tool's own output."""


@dataclass(frozen=True, slots=True)
class Ran:
    code: int
    output: str


type Runner = Callable[[Sequence[str]], Ran]
"""Runs a command to completion: how `ensure` reaches venv and pip."""


def native_run(arguments: Sequence[str]) -> Ran:
    done = subprocess.run(list(arguments), capture_output=True, text=True, check=False, creationflags=_NO_WINDOW)
    return Ran(done.returncode, done.stdout + done.stderr)


def digest(lock: bytes) -> str:
    return hashlib.sha256(lock).hexdigest()[:16]


def location(lock: bytes, root: Path = ROOT) -> Path:
    """The environment a lock's exact bytes name."""
    return root / digest(lock)


def python(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def pythonw(environment: Path) -> Path:
    """The windowless interpreter, for programs with no console."""
    return environment / "Scripts/pythonw.exe" if sys.platform == "win32" else python(environment)


def base_interpreter() -> Path:
    """The installed Python the environments are made from, even when called from inside one."""
    return Path(sys.base_prefix) / ("python.exe" if sys.platform == "win32" else f"bin/python{sys.version_info.major}.{sys.version_info.minor}")


def ready(environment: Path) -> bool:
    """Whether a build of this environment finished: its marker names it."""
    try:
        marker: object = json.loads((environment / MARKER).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return False
    match marker:
        case {"lock": str() as lock}:
            return lock == environment.name
        case _:
            return False


def running_in(environment: Path) -> bool:
    """Whether this process's interpreter is the environment's."""
    return Path(sys.prefix).resolve() == environment.resolve()


def _step(ran: Ran, doing: str) -> None:
    if ran.code != 0:
        raise DependencyError(f"Couldn't {doing} (exit {ran.code}).\n{ran.output[-3000:]}")


def ensure(lock: Path, *, root: Path = ROOT, run: Runner = native_run, base: Path | None = None) -> Path:
    """The ready environment for `lock`, built first if it isn't. Raises DependencyError."""
    environment = location(lock.read_bytes(), root)
    if ready(environment):
        return environment
    shutil.rmtree(environment, ignore_errors=True)  # an unfinished build: start again
    interpreter = str(base if base is not None else base_interpreter())
    _step(run((interpreter, "-m", "venv", "--without-pip", str(environment))), "create the environment")
    command = (
        interpreter, "-m", "pip", "--python", str(python(environment)), "install",
        "--no-deps", "--require-hashes", "--only-binary=:all:", "--disable-pip-version-check", "--no-input",
        "-r", str(lock),
    )  # fmt: skip
    _step(run(command), "install the pinned dependencies from PyPI")
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    (environment / MARKER).write_text(json.dumps({"lock": environment.name, "python": version}), encoding="utf-8")
    return environment


def main() -> None:
    """`python environments.py ensure LOCK`: build the lock's environment; exit 1 with pip's reason if it can't be."""
    match sys.argv[1:]:
        case ["ensure", lock]:
            try:
                environment = ensure(Path(lock))
            except DependencyError as error:
                sys.stdout.write(f"{error}\n")
                sys.exit(1)
            sys.stdout.write(f"Dependencies ready: {environment}\n")
        case _:
            sys.exit("usage: python environments.py ensure LOCK")


def prune(keep: frozenset[Path], root: Path = ROOT) -> tuple[Path, ...]:
    """Delete every environment except `keep`; the ones removed."""
    if not root.is_dir():
        return ()
    kept = frozenset(path.resolve() for path in keep)
    removed = tuple(path for path in sorted(root.iterdir()) if path.is_dir() and path.resolve() not in kept)
    for path in removed:
        shutil.rmtree(path, ignore_errors=True)
    return removed


if __name__ == "__main__":
    main()
