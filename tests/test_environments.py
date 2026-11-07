"""One environment per dependency lock: named by its bytes, ready only once built, rebuilt after a failure."""

from collections.abc import Sequence
from pathlib import Path

from environments import MARKER, DependencyError, Ran, ensure, location, prune, python, ready


class Builds:
    """A stand-in for venv and pip with real effects on disk: venv makes the folder."""

    def __init__(self, *, pip_code: int = 0) -> None:
        self.pip_code = pip_code
        self.commands: tuple[tuple[str, ...], ...] = ()

    def run(self, arguments: Sequence[str]) -> Ran:
        self.commands = (*self.commands, tuple(arguments))
        if arguments[1] == "venv":
            Path(arguments[-1]).mkdir(parents=True)
            return Ran(0, "")
        return Ran(self.pip_code, "ERROR: Could not fetch https://pypi.org/simple/pyside6/")


def lock(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "windows-py315.lock"
    path.write_bytes(text.encode("utf-8"))  # exact bytes: they name the environment
    return path


def test_an_environment_is_named_by_its_lock_and_built_once(tmp_path: Path) -> None:
    # Defects: two different locks share an environment (an install runs with the
    # other's packages), the same lock rebuilds every start, or pip is run without
    # the hashes and exact wheels the lock pins.
    root, builds = tmp_path / "environments", Builds()
    first = ensure(lock(tmp_path, "pydantic==2.0 --hash=sha256:aa\n"), root=root, run=builds.run, base=Path("python"), tool=Path("uv"))
    assert ready(first) and first == location(b"pydantic==2.0 --hash=sha256:aa\n", root)
    pip = builds.commands[1]
    assert pip[:3] == ("uv", "pip", "install") and "--require-hashes" in pip and "--no-deps" in pip and pip[pip.index("--only-binary") + 1] == ":all:"
    assert "--native-tls" in pip and pip[pip.index("--python") + 1] == str(python(first))
    assert ensure(lock(tmp_path, "pydantic==2.0 --hash=sha256:aa\n"), root=root, run=builds.run, base=Path("python"), tool=Path("uv")) == first
    assert len(builds.commands) == 2
    second = ensure(lock(tmp_path, "pydantic==2.1 --hash=sha256:bb\n"), root=root, run=builds.run, base=Path("python"), tool=Path("uv"))
    assert second != first and ready(first) and ready(second)


def test_a_failed_build_is_not_ready_and_the_next_one_starts_over(tmp_path: Path) -> None:
    # Defects: a build that pip failed (no network, a bad hash) is taken as ready,
    # the failure hides pip's reason, or a half-built folder blocks the retry.
    root, pinned = tmp_path / "environments", lock(tmp_path, "pyside6==6.10 --hash=sha256:cc\n")
    failing = Builds(pip_code=1)
    try:
        ensure(pinned, root=root, run=failing.run, base=Path("python"), tool=Path("uv"))
    except DependencyError as error:
        assert "pypi.org" in str(error)
    else:
        raise AssertionError("A failed pip install was reported as ready.")
    half = location(pinned.read_bytes(), root)
    assert half.is_dir() and not ready(half)
    (half / "leftover").write_text("from the failed build", encoding="utf-8")
    environment = ensure(pinned, root=root, run=Builds().run, base=Path("python"), tool=Path("uv"))
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
