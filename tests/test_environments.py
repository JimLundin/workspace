"""One environment per uv lock: named by its bytes, ready only once built, rebuilt after a failure."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from environments import LOCK, MARKER, DependencyError, Ran, ensure, location, prune, ready


class Builds:
    """A stand-in for `uv sync` with its real effect on disk: it makes the environment it is pointed at."""

    def __init__(self, *, code: int = 0) -> None:
        self.code = code
        self.commands: tuple[tuple[str, ...], ...] = ()

    def run(self, arguments: Sequence[str], variables: Mapping[str, str]) -> Ran:
        self.commands = (*self.commands, tuple(arguments))
        Path(variables["UV_PROJECT_ENVIRONMENT"]).mkdir(parents=True, exist_ok=True)
        return Ran(self.code, "error: Failed to fetch: `https://pypi.org/simple/pyside6-essentials/`")


def project(tmp_path: Path, lock: str) -> Path:
    folder = tmp_path / "workspace"
    folder.mkdir(exist_ok=True)
    (folder / LOCK).write_bytes(lock.encode("utf-8"))  # exact bytes: they name the environment
    return folder


def build(folder: Path, root: Path, runner: Builds) -> Path:
    return ensure(folder, root=root, run=runner.run, base=Path("python"), tool=Path("uv"))


def test_an_environment_is_named_by_its_lock_and_built_once(tmp_path: Path) -> None:
    # Defects: two different locks share an environment (an install runs with the
    # other's packages), the same lock rebuilds every start, or uv may update the
    # lock, install the dev group, or miss the company's certificates.
    root, builds = tmp_path / "environments", Builds()
    first = build(project(tmp_path, "version = 1 # pydantic 2.0\n"), root, builds)
    assert ready(first) and first == location(b"version = 1 # pydantic 2.0\n", root)
    (sync,) = builds.commands
    assert sync[:2] == ("uv", "sync") and {"--locked", "--no-dev", "--no-install-project", "--native-tls"} <= set(sync)
    assert build(project(tmp_path, "version = 1 # pydantic 2.0\n"), root, builds) == first
    assert len(builds.commands) == 1
    second = build(project(tmp_path, "version = 1 # pydantic 2.1\n"), root, builds)
    assert second != first and ready(first) and ready(second)


def test_a_failed_build_is_not_ready_and_the_next_one_starts_over(tmp_path: Path) -> None:
    # Defects: a build uv failed (no network, a stale lock) is taken as ready,
    # the failure hides uv's reason, or a half-built folder blocks the retry.
    root, folder = tmp_path / "environments", project(tmp_path, "version = 1 # pyside6\n")
    try:
        build(folder, root, Builds(code=2))
    except DependencyError as error:
        assert "pypi.org" in str(error)
    else:
        raise AssertionError("A failed uv sync was reported as ready.")
    half = location((folder / LOCK).read_bytes(), root)
    assert half.is_dir() and not ready(half)
    (half / "leftover").write_text("from the failed build", encoding="utf-8")
    environment = build(folder, root, Builds())
    assert ready(environment) and not (environment / "leftover").exists()


def test_a_marker_for_another_lock_is_not_ready(tmp_path: Path) -> None:
    # Defect: a folder copied or renamed from another lock's environment is trusted as this one.
    environment = tmp_path / "abcdef0123456789"
    environment.mkdir()
    (environment / MARKER).write_text('{"lock": "0000000000000000"}', encoding="utf-8")
    assert not ready(environment)


def test_prune_keeps_only_the_named_environments(tmp_path: Path) -> None:
    # Defects: pruning deletes the running or the undo environment, or leaves old ones to fill the disk.
    root = tmp_path / "environments"
    live, undo, old = (root / name for name in ("live", "undo", "old"))
    for folder in (live, undo, old):
        folder.mkdir(parents=True)
    assert prune(frozenset({live, undo}), root) == (old,)
    assert live.is_dir() and undo.is_dir() and not old.exists()
    assert prune(frozenset(), tmp_path / "absent") == ()
