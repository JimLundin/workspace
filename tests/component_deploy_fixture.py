"""Real child/file owners with a concrete desktop adapter for release checks.

Popen owns native handles. The fixture adapts that ownership to Release's handle
interface; it creates no keyboard hook, microphone or visible desktop window.
"""

import contextlib
import os
import subprocess
import sys
import threading
import time
import zipfile
from collections.abc import Generator, Mapping
from enum import Enum, auto
from pathlib import Path

from components import CATALOGUE, Component, read_marker, started_ms
from keeper import Keeper, Stage
from keeper_control import Control, InstallResult
from scripts.deploy_files import PINS, files, sha, write, zip_files
from scripts.deploy_processes import Process, process_id
from scripts.deploy_values import Config
from scripts.deploy_windows import Release
from tests.test_keeper import FakeCheck


def staged(stage: Path, source: Mapping[str, bytes]) -> tuple[Config, dict[str, str]]:
    """A stage's payload, manifest and configuration as staging writes them for checked source."""
    with zipfile.ZipFile(stage / "source.zip", "x", zipfile.ZIP_DEFLATED) as archive:
        for name, data in source.items():
            archive.writestr("workspace/" + name, data)
    wanted = zip_files(stage / "source.zip")
    write(stage / "source.json", {"files": wanted})
    config: Config = {
        "kind": "workspace-source-only-v2",
        "stage_id": stage.name,
        "live_windows": "",
        "archive_windows": "",
        "profile_windows": "",
        "helpers": {},
        "source_manifest_sha256": sha(stage / "source.json"),
        "payload_sha256": sha(stage / "source.zip"),
        "check_sha256": "",
        "pins": {name: wanted[name] for name in PINS},
        "created_at_ns": 0,
    }
    return config, wanted


class SourceChange(Enum):
    ASSISTANT = auto()
    UNCHANGED = auto()


# A venv's python.exe is a launcher with its own pid; children must be the
# interpreter process that writes their readiness marker.
INTERPRETER = str(Path(sys.base_prefix) / "python.exe")


def entry_source(root: Path, name: Component) -> Path:
    return root / CATALOGUE[name].module / "__main__.py"


class Child:
    def __init__(self, identity: Process, process: subprocess.Popen[bytes], stop: Path) -> None:
        self.identity = identity
        self.process = process
        self.stop_path = stop

    def poll(self) -> int | None:
        return self.process.poll()

    def stop(self) -> None:
        self.stop_path.touch()
        self.process.wait(timeout=10)


class World:
    """Own subprocess lifetimes; publish immutable snapshots across threads."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.history: tuple[Child, ...] = ()
        self.lock = threading.RLock()

    def start(self, name: Component) -> Child:
        with self.lock:
            marker = CATALOGUE[name].marker(self.root / "profile" / "keeper")
            marker.unlink(missing_ok=True)
            stop = self.root / (name + "-stop-" + str(len(self.history)))
            source = entry_source(self.root / "live", name)
            command = (INTERPRETER, "-B", "-m", "tests.component_child", str(source), str(self.loaded(name)), str(stop))
            process = subprocess.Popen(command, env={**os.environ, "WORKSPACE_READY": str(marker)})
            child = Child(Process(process.pid, os.getpid(), name, INTERPRETER, started_ms(process.pid)), process, stop)
            self.history = (*self.history, child)
            return child

    def loaded(self, name: Component) -> Path:
        """Where a child records the entry source it loaded."""
        return self.root / ("loaded-" + name)

    def observations(self) -> tuple[Child, ...]:
        with self.lock:
            return self.history

    def snapshot(self) -> str:
        raise AssertionError("The release owns source snapshots")

    def is_ready(self, name: Component) -> bool:
        return read_marker(CATALOGUE[name].marker(self.root / "profile" / "keeper")) is not None

    def start_check(self, checked: str | None) -> FakeCheck:
        return FakeCheck()

    def install(self) -> None:
        raise AssertionError("The release owns source replacement")

    def restore(self, version: str) -> None:
        raise AssertionError("The release owns rollback")

    def notify(self, text: str) -> None:
        raise AssertionError(text)

    def note(self, text: str) -> None:
        pass

    def record(self, result: InstallResult) -> None:
        raise AssertionError(result)

    def show_trial(self, summary: str | None) -> None:
        raise AssertionError("The deployment does not enter an agent update trial")


class ComponentRelease(Release):
    def __init__(self, root: Path, change: SourceChange = SourceChange.ASSISTANT, *, fail_copy: bool = False) -> None:
        self.stage, self.live, self.profile = root / "workspace-source-test", root / "live", root / "profile"
        self.state, self.archive = self.profile / "keeper", root / "bundle.zip"
        self.stage.mkdir()
        self.state.mkdir(parents=True)
        self.live.mkdir()
        (self.live / ".runtime").mkdir()
        (self.live / ".runtime" / "preserved").write_bytes(b"pinned runtime")
        for name in PINS:
            (self.live / name).parent.mkdir(parents=True, exist_ok=True)
            (self.live / name).write_text(name + " pin\n")
        for name in CATALOGUE:
            path = entry_source(self.live, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("version = 'before'\n")
        with zipfile.ZipFile(self.archive, "w") as archive:
            for listed in files(self.live):
                archive.write(self.live / listed, "workspace/" + listed)
        source = {name: (self.live / name).read_bytes() for name in files(self.live, skip_roots=(".runtime",))}
        if change is SourceChange.ASSISTANT:
            source |= {"assistant/__main__.py": b"version = 'after'\n", "added.py": b"value = 'new source'\n"}
        self.config, self.wanted = staged(self.stage, source)
        self._baseline = None
        cache = self.live / ".ruff_cache" / "CACHEDIR.TAG"
        cache.parent.mkdir()
        cache.write_bytes(b"unmanaged cache bytes")
        self.world = World(root)
        self.keeper = Keeper(self.world)
        self.control = Control(self.state)
        self.keeper.start(time.monotonic())
        self.finished = threading.Event()
        self.fail_copy = fail_copy
        self.copies = 0
        self.failure: Exception | None = None
        self.supervisor = threading.Thread(target=self.supervise)
        self.supervisor.start()
        deadline = time.monotonic() + 15
        while self.keeper.stage is not Stage.RUNNING:
            if time.monotonic() >= deadline:
                self.close()
                raise AssertionError("Disposable children did not become ready")
            time.sleep(0.01)

    def supervise(self) -> None:
        try:
            while not self.finished.wait(0.01):
                self.control.poll(self.keeper, time.monotonic())
                self.keeper.tick(time.monotonic())
        except Exception as error:
            self.failure = error

    def close(self) -> None:
        self.finished.set()
        self.supervisor.join(timeout=15)
        for child in self.world.observations():
            if child.poll() is None:
                child.stop()
        assert self.failure is None, self.failure

    def inventory(self) -> tuple[Process, ...]:
        supervisor = Process(os.getpid(), 1, "keeper", sys.executable, 1)
        children = tuple(child.identity for child in self.world.observations() if child.poll() is None)
        return tuple(sorted((supervisor, *children), key=process_id))

    def opened(self, row: Process) -> int:
        assert row in self.inventory()
        return row.pid

    def exit_code(self, handle: int) -> int | None:
        if handle == os.getpid():
            return None
        return next(child.poll() for child in self.world.observations() if child.identity.pid == handle)

    def close_handle(self, handle: int) -> None:
        pass

    def hwnd(self, title: str, window_class: str | None = None) -> tuple[int, int]:
        assistant = next((row for row in self.inventory() if row.role == "assistant"), None)
        return (assistant.pid, assistant.pid) if assistant is not None else (0, 0)

    def window_visible(self, handle: int) -> bool:
        return bool(handle)

    @contextlib.contextmanager
    def exclusive(self) -> Generator[None]:
        stopped = self.shutdown_receipt()
        self.retained_inventory(stopped)
        yield
        self.retained_inventory(stopped)

    def copy(self, source: Path, destination: Path) -> None:
        self.copies += 1
        if self.fail_copy and self.copies == 2:
            raise OSError("injected replacement failure")
        super().copy(source, destination)
