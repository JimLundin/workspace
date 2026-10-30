"""Native save-to-feedback supervisor; tests and previews use fresh processes.

Watchdog owns recursive OS events. This owner batches events through a thread-safe
queue and serializes checks. Successful source receipts are the session baseline;
failed or superseded runs never advance it. No installed application is reloaded.
"""

import argparse
import contextlib
import importlib.util
import inspect
import os
import queue
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter
lazy from watchdog.events import FileSystemEvent, FileSystemMovedEvent
lazy from watchdog.observers import Observer

from scripts.development_paths import LIVE

ROOT = Path(__file__).resolve().parent.parent
IGNORED = frozenset(
    {
        ".git",
        ".venv",
        ".python",
        ".runtime",
        ".bundle-cache",
        ".hypothesis",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".pyright",
        "__pycache__",
        "dist",
        "node_modules",
    }
)
TRANSIENT = frozenset({".pyc", ".pyo", ".log", ".jsonl", ".tmp", ".swp", ".pending"})
type Surface = Literal["toolbar", "feed", "both"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Settings:
    full: bool = False
    native: bool = True
    tests: tuple[str, ...] = ()
    preview: Surface | None = None
    checks: bool = True
    once: bool = False
    stop_file: Path | None = None


SETTINGS = TypeAdapter[Settings](Settings)


def source_path(root: Path, value: str | bytes) -> Path | None:
    path = Path(os.fsdecode(value))
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    if any(part in IGNORED or part == ".." for part in relative.parts) or path.suffix in TRANSIENT or path.name.startswith((".env", "~")):
        return None
    return path


def preview_change(root: Path, paths: frozenset[Path]) -> bool:
    return any(
        path.relative_to(root).parts[0] != "tests" and path.suffix in (".py", ".pyw", ".yaml", ".svg", ".png", ".css")
        for path in paths
        if path != root
    )


class Events:
    """Watchdog's dispatch adapter; the observer thread only enqueues observations."""

    __slots__ = ("pending", "root")

    def __init__(self, root: Path, pending: queue.SimpleQueue[Path]) -> None:
        self.root, self.pending = root, pending

    def dispatch(self, event: FileSystemEvent) -> None:
        if event.event_type not in ("created", "modified", "moved", "deleted"):
            return
        if event.is_directory and event.event_type == "modified":
            return
        paths: tuple[str | bytes, ...]
        match event:
            case FileSystemMovedEvent(src_path=source, dest_path=destination):
                paths = (source, destination)
            case FileSystemEvent(src_path=source):
                paths = (source,)
        for value in paths:
            if (path := source_path(self.root, value)) is not None:
                self.pending.put(path)


def changes(pending: queue.SimpleQueue[Path], *, debounce: float = 0.25) -> frozenset[Path]:
    try:
        first = pending.get(timeout=0.25)
    except queue.Empty:
        return frozenset()
    # The batch is private to this drain; unioning a new frozen set for every OS
    # event would repeatedly copy the batch during editor save storms.
    batch = {first}
    deadline = time.monotonic() + debounce
    while True:
        try:
            batch.add(pending.get(timeout=max(0, deadline - time.monotonic())))
            deadline = time.monotonic() + debounce
        except queue.Empty:
            return frozenset(batch)


def check_command(settings: Settings, receipt: Path) -> tuple[str, ...]:
    baseline = receipt if receipt.is_file() else LIVE
    command: tuple[str, ...] = (sys.executable, "-B", "-m", "scripts.check", "--baseline", str(baseline), "--receipt", str(receipt))
    if settings.native:
        command += ("--native",)
    if settings.full:
        command += ("--full",)
    if settings.tests:
        command += ("--tests", *settings.tests)
    return command


def run_check(settings: Settings, receipt: Path) -> int:
    print("Checking latest source...", flush=True)
    with subprocess.Popen(check_command(settings, receipt), cwd=ROOT) as process:
        try:
            result = process.wait()
        except KeyboardInterrupt:
            # The console forwards Ctrl+C to the fresh checker too, allowing
            # its native fixtures to unwind before this supervisor exits.
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=10)
            if process.poll() is None:
                process.terminate()
            raise
    print("Watch baseline advanced." if result == 0 else "Check failed; keeping the last successful baseline.", flush=True)
    return result


class PreviewProcess:
    """Own exactly one preview child and its clean-close control files."""

    __slots__ = ("folder", "process", "scratch", "surface")

    def __init__(self, scratch: Path, surface: Surface) -> None:
        self.scratch, self.surface = scratch, surface
        self.folder: Path | None = None
        self.process: subprocess.Popen[bytes] | None = None

    def restart(self) -> bool:
        self.close()
        self.folder = Path(tempfile.mkdtemp(prefix="preview-", dir=self.scratch))
        started = time.perf_counter()
        self.process = subprocess.Popen(
            (
                sys.executable,
                "-B",
                "-m",
                "scripts.preview",
                "--surface",
                self.surface,
                "--session",
                str(self.folder),
                "--state",
                str(self.scratch / "preview-state.json"),
            ),
            cwd=ROOT,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if (self.folder / "ready.json").is_file():
                print(f"Preview visible in {time.perf_counter() - started:.2f}s.", flush=True)
                return True
            if self.process.poll() is not None:
                print("Preview failed to start; the next relevant save will retry.", flush=True)
                return False
            time.sleep(0.05)
        self.close()
        print("Preview readiness timed out; the next relevant save will retry.", flush=True)
        return False

    def closed_by_user(self) -> bool:
        return self.process is not None and self.process.poll() == 0

    def close(self) -> None:
        if self.process is None:
            return
        if self.folder is not None and self.process.poll() is None:
            (self.folder / "stop").touch()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=5)
                print("Preview did not close cleanly; its isolated child was terminated.", flush=True)
        self.process = None


def supervise(settings: Settings, scratch: Path) -> int:
    receipt = scratch / "checked.json"
    pending: queue.SimpleQueue[Path] = queue.SimpleQueue()
    observer = Observer()
    observer.schedule(Events(ROOT, pending), str(ROOT), recursive=True)
    preview = PreviewProcess(scratch, settings.preview) if settings.preview is not None else None
    observer.start()
    try:
        preview_ready = preview.restart() if preview is not None else True
        result = run_check(settings, receipt) if settings.checks else 0
        if not preview_ready:
            result = 1
        print(f"Watching {ROOT}; Ctrl+C stops. Session receipt: {receipt}", flush=True)
        while not settings.once:
            if settings.stop_file is not None and settings.stop_file.exists():
                break
            if preview is not None and preview.closed_by_user():
                break
            batch = changes(pending)
            if not batch:
                continue
            if preview is not None and preview_change(ROOT, batch):
                preview_ready = preview.restart()
                if not settings.checks:
                    result = 0 if preview_ready else 1
            if settings.checks:
                result = run_check(settings, receipt)
            if not preview_ready:
                result = 1
        return result
    finally:
        try:
            observer.stop()
            observer.join(timeout=5)
        finally:
            if preview is not None:
                preview.close()
        if observer.is_alive():
            raise RuntimeError("The file observer did not stop.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests", nargs="+", default=())
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--source-only", dest="native", action="store_false")
    parser.add_argument("--preview", choices=("toolbar", "feed", "both"))
    parser.add_argument("--preview-only", dest="checks", action="store_false")
    parser.add_argument("--once", action="store_true", help="run one cycle and close; useful for smoke checks")
    parser.add_argument("--stop-file", type=Path, help="an optional automation control file")
    observed: dict[str, object] = dict(inspect.getmembers(parser.parse_args()))
    settings = SETTINGS.validate_python(observed)
    if settings.full and settings.tests:
        parser.error("--full and --tests select different profiles")
    if not settings.checks and settings.preview is None:
        parser.error("--preview-only needs --preview")
    if importlib.util.find_spec("watchdog") is None:
        parser.error("Install the development watcher: .venv\\Scripts\\python.exe -m pip install watchdog==6.0.0")
    try:
        with tempfile.TemporaryDirectory(prefix="workspace-watch-") as folder:
            result = supervise(settings, Path(folder))
    except KeyboardInterrupt:
        result = 0
        print("Watch stopped.", flush=True)
    raise SystemExit(result)


if __name__ == "__main__":
    main()
