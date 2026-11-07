"""Workspace's dependencies: one virtual environment per dependency lock, built by uv.

`pyproject.toml` declares the dependencies and uv's lock (`uv.lock`) pins every
one of them, with hashes, for each platform. Each distinct lock gets its own
environment under `%LOCALAPPDATA%/workspace/environments/<hash of the lock>`,
built once from PyPI by `uv sync --locked`, which refuses a lock that no longer
matches `pyproject.toml`. uv keeps its own wheel cache, so rebuilding an
environment for an undo rarely downloads. An
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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ROOT: Final = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "workspace" / "environments"
"""Where environments live: outside the installed copy, so installs and undo never touch them."""
LOCK: Final = Path("uv.lock")
"""uv's lock, beside `pyproject.toml` in a copy of Workspace."""
MARKER: Final = "workspace-environment.json"
"""Written last: an environment without it is incomplete."""
_NO_WINDOW: Final = 0x08000000 if sys.platform == "win32" else 0


class DependencyError(OSError):
    """The environment for a lock could not be built; the message ends with the tool's own output."""


@dataclass(frozen=True, slots=True)
class Ran:
    code: int
    output: str


type Runner = Callable[[Sequence[str], Mapping[str, str]], Ran]
"""Runs a command to completion with extra environment variables: how `ensure` reaches uv."""


def native_run(arguments: Sequence[str], variables: Mapping[str, str]) -> Ran:
    done = subprocess.run(list(arguments), capture_output=True, text=True, check=False, env={**os.environ, **variables}, creationflags=_NO_WINDOW)
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


def uv() -> Path:
    """The uv executable: on PATH, or where uv's installer puts it."""
    found = shutil.which("uv")
    if found is not None:
        return Path(found)
    installed = Path.home() / ".local" / "bin" / ("uv.exe" if sys.platform == "win32" else "uv")
    if installed.is_file():
        return installed
    raise DependencyError("Workspace needs uv to install its dependencies: see https://docs.astral.sh/uv/ and start Workspace again.")


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


def ensure(project: Path, *, root: Path = ROOT, run: Runner = native_run, base: Path | None = None, tool: Path | None = None) -> Path:
    """The ready environment for the lock of the Workspace copy at `project`, built first if it isn't, by uv (`tool`).

    Raises DependencyError."""
    environment = location((project / LOCK).read_bytes(), root)
    if ready(environment):
        return environment
    shutil.rmtree(environment, ignore_errors=True)  # an unfinished build: start again
    # --native-tls: the Windows certificate store, so company TLS inspection is trusted.
    command = (
        str(tool if tool is not None else uv()), "sync", "--quiet", "--native-tls", "--locked", "--no-install-project",
        "--no-dev", "--python", str(base if base is not None else base_interpreter()), "--project", str(project),
    )  # fmt: skip
    _step(run(command, {"UV_PROJECT_ENVIRONMENT": str(environment)}), "install the locked dependencies from PyPI")
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    (environment / MARKER).write_text(json.dumps({"lock": environment.name, "python": version}), encoding="utf-8")
    return environment


def main() -> None:
    """`python environments.py ensure PROJECT`: build the environment of that copy's lock; exit 1 with uv's reason if it can't be."""
    match sys.argv[1:]:
        case ["ensure", project]:
            try:
                environment = ensure(Path(project))
            except DependencyError as error:
                sys.stdout.write(f"{error}\n")
                sys.exit(1)
            sys.stdout.write(f"Dependencies ready: {environment}\n")
        case ["python", project]:
            sys.stdout.write(f"{python(location((Path(project) / LOCK).read_bytes()))}\n")
        case _:
            sys.exit("usage: python environments.py ensure PROJECT | python PROJECT")


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
