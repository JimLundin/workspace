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
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import TypeAdapter
lazy from watchdog.events import FileSystemEvent, FileSystemMovedEvent
lazy from watchdog.observers import Observer

from cell import Cell

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


@dataclass(frozen=True, slots=True, kw_only=True)
class Settings:
    full: bool = False
    native: bool = False
    tests: tuple[str, ...] = ()
    preview: bool = False
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


@dataclass(frozen=True, slots=True)
class Events:
    """Watchdog's dispatch adapter; the observer thread only enqueues observations."""

    root: Path
    pending: queue.SimpleQueue[Path]

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
    # One frozen set from the whole burst, never a copy per OS event during editor save storms.
    return frozenset((first, *_arrivals(pending, debounce)))


def _arrivals(pending: queue.SimpleQueue[Path], debounce: float) -> Iterator[Path]:
    """Paths that keep arriving, each within `debounce` of the one before."""
    deadline = time.monotonic() + debounce
    while True:
        try:
            path = pending.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            return
        deadline = time.monotonic() + debounce
        yield path


def check_command(settings: Settings, receipt: Path) -> tuple[str, ...]:
    # Without its own receipt yet, the session starts from the check's last passing source.
    baseline = ("--baseline", str(receipt)) if receipt.is_file() else ()
    command: tuple[str, ...] = (sys.executable, "-B", "-m", "scripts.check", *baseline, "--receipt", str(receipt))
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


@dataclass(frozen=True, slots=True)
class _Child:
    folder: Path
    """The child's session folder: its readiness and stop files."""
    process: subprocess.Popen[bytes]


@dataclass(frozen=True, slots=True)
class PreviewProcess:
    """Own exactly one preview child and its clean-close control files."""

    scratch: Path
    _child: Cell[_Child | None] = field(default_factory=lambda: Cell[_Child | None](None), init=False, repr=False)

    def restart(self) -> bool:
        self.close()
        folder = Path(tempfile.mkdtemp(prefix="preview-", dir=self.scratch))
        started = time.perf_counter()
        process = subprocess.Popen(
            (
                sys.executable,
                "-B",
                "-m",
                "scripts.preview",
                "--session",
                str(folder),
                "--state",
                str(self.scratch / "preview-state.json"),
            ),
            cwd=ROOT,
        )
        self._child.set(_Child(folder, process))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if (folder / "ready.json").is_file():
                print(f"Preview visible in {time.perf_counter() - started:.2f}s.", flush=True)
                return True
            if process.poll() is not None:
                print("Preview failed to start; the next relevant save will retry.", flush=True)
                return False
            time.sleep(0.05)
        self.close()
        print("Preview readiness timed out; the next relevant save will retry.", flush=True)
        return False

    def closed_by_user(self) -> bool:
        child = self._child.get()
        return child is not None and child.process.poll() == 0

    def close(self) -> None:
        child = self._child.get()
        if child is None:
            return
        if child.process.poll() is None:
            (child.folder / "stop").touch()
            try:
                child.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.process.terminate()
                child.process.wait(timeout=5)
                print("Preview did not close cleanly; its isolated child was terminated.", flush=True)
        self._child.set(None)


def supervise(settings: Settings, scratch: Path) -> int:
    receipt = scratch / "checked.json"
    pending: queue.SimpleQueue[Path] = queue.SimpleQueue()
    observer = Observer()
    observer.schedule(Events(ROOT, pending), str(ROOT), recursive=True)
    preview = PreviewProcess(scratch) if settings.preview else None
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
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--preview", action="store_true", help="restart the toolbar preview after each save")
    parser.add_argument("--preview-only", dest="checks", action="store_false")
    parser.add_argument("--once", action="store_true", help="run one cycle and close; useful for smoke checks")
    parser.add_argument("--stop-file", type=Path, help="an optional automation control file")
    observed: dict[str, object] = dict(inspect.getmembers(parser.parse_args()))
    settings = SETTINGS.validate_python(observed)
    if settings.full and settings.tests:
        parser.error("--full and --tests select different profiles")
    if not settings.checks and not settings.preview:
        parser.error("--preview-only needs --preview")
    if importlib.util.find_spec("watchdog") is None:
        parser.error("Install the development watcher: Dev.cmd setup")
    try:
        with tempfile.TemporaryDirectory(prefix="workspace-watch-") as folder:
            result = supervise(settings, Path(folder))
    except KeyboardInterrupt:
        result = 0
        print("Watch stopped.", flush=True)
    raise SystemExit(result)


if __name__ == "__main__":
    main()
