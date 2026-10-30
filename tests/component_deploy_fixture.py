"""Real child/file owners with a concrete desktop adapter for release checks.

Popen owns native handles. The fixture adapts that ownership to Release's handle
interface; it creates no keyboard hook, microphone or visible desktop window.
"""

import contextlib
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from collections.abc import Generator
from enum import Enum, auto
from pathlib import Path

from keeper import Keeper, Stage
from keeper_control import Control
from scripts.deploy_archive import repack
from scripts.deploy_files import files, sha
from scripts.deploy_policy import ROOTS
from scripts.deploy_processes import Process, process_id
from scripts.deploy_values import Prepared, Role
from scripts.deploy_windows import Release
from tests.test_keeper import FakeCheck


def runtime_folders(_folder: str, names: list[str]) -> tuple[str, ...]:
    return tuple(name for name in names if name in (".runtime",))


class SourceChange(Enum):
    ASSISTANT = auto()
    UNCHANGED = auto()


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

    def start(self, name: str) -> Child:
        with self.lock:
            role: Role
            match name:
                case "layout":
                    role = "miryoku"
                case "assistant":
                    role = "assistant"
                case "automation":
                    role = "automation"
                case _:
                    raise ValueError(name)
            ready = self.root / "profile" / "keeper" / ("ready-" + name)
            ready.unlink(missing_ok=True)
            stop = self.root / (name + "-stop-" + str(len(self.history)))
            source = self.root / "live" / (ROOTS[name].replace(".", "/") + ".py")
            created = time.time_ns() // 1_000_000
            process = subprocess.Popen((sys.executable, "-B", "-m", "tests.component_child", str(source), str(ready), str(stop)))
            child = Child(Process(process.pid, os.getpid(), role, sys.executable, created), process, stop)
            self.history = (*self.history, child)
            return child

    def observations(self) -> tuple[Child, ...]:
        with self.lock:
            return self.history

    def snapshot(self) -> str:
        raise AssertionError("The release owns source snapshots")

    def is_ready(self, name: str) -> bool:
        return (self.root / "profile" / "keeper" / ("ready-" + name)).is_file()

    def start_check(self) -> FakeCheck:
        return FakeCheck()

    def install(self) -> None:
        raise AssertionError("The release owns source replacement")

    def restore(self, version: str) -> None:
        raise AssertionError("The release owns rollback")

    def notify(self, text: str) -> None:
        raise AssertionError(text)

    def show_trial(self, summary: str | None) -> None:
        raise AssertionError("The deployment does not enter an agent update trial")


class ComponentRelease(Release):
    def __init__(self, root: Path, change: SourceChange = SourceChange.ASSISTANT, *, fail_copy: bool = False) -> None:
        self.stage, self.live, self.profile = root / "workspace-source-test", root / "live", root / "profile"
        self.state, self.archive = self.profile / "keeper", root / "bundle.zip"
        self.stage.mkdir()
        self.state.mkdir(parents=True)
        self.live.mkdir()
        for directory in (".runtime",):
            (self.live / directory).mkdir()
            (self.live / directory / "preserved").write_bytes(b"pinned runtime")
        for module in ROOTS.values():
            path = self.live / (module.replace(".", "/") + ".py")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("version = 'before'\n")
        old = files(self.live, skip_roots=(".runtime",))
        source = self.stage / "source"
        shutil.copytree(self.live, source, ignore=runtime_folders)
        if change is SourceChange.ASSISTANT:
            (source / "assistant" / "__main__.py").write_text("version = 'after'\n")
            (source / "added.py").write_text("value = 'new source'\n")
        self.wanted = files(source)
        cache = self.live / ".ruff_cache" / "CACHEDIR.TAG"
        cache.parent.mkdir()
        cache.write_bytes(b"unmanaged cache bytes")
        unrelated = {cache.relative_to(self.live).as_posix(): sha(cache)}
        with zipfile.ZipFile(self.archive, "w") as archive:
            for name in files(self.live):
                if name not in unrelated:
                    archive.write(self.live / name, "workspace/" + name)
        backup = self.stage / "backup"
        shutil.copytree(self.live, backup / "source", ignore=runtime_folders)
        shutil.copyfile(self.archive, backup / "previous-bundle.zip")
        repack(self.archive, self.stage / "new-bundle.zip", source, self.wanted)
        runtime = {name: value for name, value in files(self.live).items() if name.startswith((".runtime/",))}
        self.baseline: Prepared = {
            "stage_id": self.stage.name,
            "manifest_sha256": "0" * 64,
            "old_archive_sha256": sha(self.archive),
            "new_archive_sha256": sha(self.stage / "new-bundle.zip"),
            "runtime": runtime,
            "runtime_fingerprint": self.runtime_fingerprint(runtime),
            "runtime_audit_reused": False,
            "old_source": old,
            "source_before": old | unrelated,
            "unrelated_source": unrelated,
            "runtime_directory_ids": {},
            "prepared_at_ns": 0,
        }
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

    def prepared(self) -> Prepared:
        return self.baseline

    def prepare(self) -> None:
        pass

    def pins(self) -> None:
        pass

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
