"""The keeper: the one part of Workspace that never changes itself.

It runs the layout, assistant, and automation worker, and installs changes to
them: when the agent asks, it checks the change (selfcheck.py), keeps a copy of
the current version, installs, and restarts them. A failed check prevents an
installation. A change that doesn't start, crashes during its ten-minute trial,
or keeps crashing later is undone, back to the copy. During the trial a small window offers Keep and Undo,
usable with the mouse alone in case the change broke the keyboard.

So that a change can never break what undoes it, the agent can't edit this file,
selfcheck.py or workspace.pyw (`PROTECTED`), and the keeper uses a protected Qt dialog module. Its coordination uses only the
standard library. What it runs is listed in the protected components.py. The other
programs talk to it through files: requests in one folder, and a readiness marker
each program writes once it's up.

    pythonw keeper.py        (workspace.pyw does this)
"""

import contextlib
import ctypes
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from ctypes import wintypes
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Final, Protocol, TypedDict

from components import CATALOGUE, Component, Entry, read_marker

LIVE: Final = Path(__file__).resolve().parent
"""Workspace's own folder: the version that runs."""
DIRECTORY: Final = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "workspace"
STATE: Final = DIRECTORY / "keeper"
REQUESTS: Final = STATE / "requests"
WORKSPACE: Final = DIRECTORY / "workspace"
"""Where the agent edits a copy of the source; installed from here."""
VERSIONS: Final = DIRECTORY / "versions"
"""A copy of each version replaced by an install, newest last."""
KEPT_VERSIONS: Final = 20

PROTECTED: Final = frozenset({"keeper.py", "selfcheck.py", "workspace.pyw", "runtime.py", "keeper_ui.py", "keeper_control.py", "components.py"})
"""Files a change can't touch."""

START_S: Final = 30.0
"""How long a program gets to say it's ready."""
TRIAL_S: Final = 600.0
CHECK_S: Final = 300.0
CRASH_WINDOW_S: Final = 600.0
MAX_CRASHES: Final = 3
"""Restarts allowed within `CRASH_WINDOW_S`; one more crash and the keeper stops trying."""


# Standard-library codecs keep protected request/recovery IO usable without
# loading bundled dependencies. Typed wire fields are validated structurally.


class RequestData(TypedDict):
    action: str
    summary: str


class RecoveryData(TypedDict):
    version: str | None
    pending: bool


# ---- requests and readiness ------------------------------------------------------------


def ask(action: str, summary: str = "", *, folder: Path = REQUESTS) -> None:
    """Asks the keeper to `install` the workspace, `undo` the last install, `keep` a
    change on trial, or `restart_layout`."""
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns():020d}"
    temporary = folder / f"{name}.tmp"
    request: RequestData = {"action": action, "summary": summary}
    temporary.write_text(json.dumps(request), encoding="utf-8")
    temporary.replace(folder / f"{name}.json")  # appears whole, never half-written


def take_requests(*, folder: Path = REQUESTS) -> tuple[tuple[str, str], ...]:
    """Requests waiting, oldest first; each is taken once."""
    taken: list[tuple[str, str]] = []
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        with contextlib.suppress(OSError, ValueError):
            data: object = json.loads(path.read_text(encoding="utf-8"))
            match data:
                case {"action": str() as action, "summary": str() as summary}:
                    taken.append((action, summary))
                case _:
                    pass
        with contextlib.suppress(OSError):
            path.unlink()
    return tuple(taken)


# ---- versions on disk ------------------------------------------------------------------


def source_files(root: Path) -> list[str]:
    """Workspace's own files under `root`, as relative paths: not caches or history."""
    found: list[str] = []
    for folder, directories, files in os.walk(root):
        # Prune before descending: the bundled runtime contains thousands of non-source files.
        directories[:] = [name for name in directories if not name.startswith(".") and name != "__pycache__"]
        for name in (*directories, *files):
            if name.startswith(".") or name == "__pycache__":
                continue
            path = Path(folder) / name
            relative = path.relative_to(root)
            if path.is_symlink():
                raise OSError(f"Source links are not supported: {relative}")
            if path.suffix != ".pyc" and path.is_file():
                found.append(relative.as_posix())
    return sorted(found)


def source_digest(root: Path) -> str:
    """Identify exactly which source bytes were frozen and checked."""
    digest = hashlib.sha256()
    for name in source_files(root):
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256((root / name).read_bytes()).digest())
    return digest.hexdigest()


def source_diff(before: Path, after: Path) -> str:
    parts: list[str] = []
    for name in sorted(set(source_files(before)) | set(source_files(after))):
        old = (before / name).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if (before / name).exists() else []
        new = (after / name).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if (after / name).exists() else []
        parts.extend(difflib.unified_diff(old, new, f"running/{name}", f"candidate/{name}"))
    return "".join(parts)


def prepare_candidate(workspace: Path, live: Path, candidate: Path, approve: Callable[[Path], bool] | None = None) -> bool:
    """Freeze source for checks, with an optional review when approval mode is enabled."""
    copy_source(workspace, candidate)
    for name in PROTECTED:
        if (candidate / name).read_bytes() != (live / name).read_bytes():
            raise OSError(f"The protected file {name} was changed")
    digest = source_digest(candidate)
    accepted = approve(candidate) if approve is not None else True
    if source_digest(candidate) != digest:
        raise OSError("The candidate changed during review; review it again")
    return accepted


def _mirror(source: Path, target: Path, *, protect: bool) -> None:
    """Makes `target`'s source files the same as `source`'s."""
    if protect:
        for cache in target.rglob("__pycache__"):
            shutil.rmtree(cache)
    keep = PROTECTED if protect else frozenset[str]()
    wanted = {f for f in source_files(source) if f not in keep}
    for name in source_files(target) if target.exists() else []:
        if name not in wanted and name not in keep:
            (target / name).unlink()
    for name in wanted:
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes((source / name).read_bytes())
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


def copy_source(source: Path, target: Path) -> None:
    """Makes `target` an exact copy of `source`'s source files (for the agent's workspace)."""
    _mirror(source, target, protect=False)


def snapshot(live: Path, versions: Path) -> str:
    """Copies the running version; the copy's name. Only the newest are kept."""
    versions.mkdir(parents=True, exist_ok=True)
    existing = sorted(p.name for p in versions.iterdir() if p.is_dir())
    number = int(existing[-1].split("-")[0]) + 1 if existing else 1
    name = f"{number:05d}-{datetime.now():%Y%m%d-%H%M%S}"
    _mirror(live, versions / name, protect=False)
    for old in existing[: max(0, len(existing) + 1 - KEPT_VERSIONS)]:
        shutil.rmtree(versions / old, ignore_errors=True)
    return name


def restore(version: Path, live: Path) -> None:
    _mirror(version, live, protect=True)


def install(workspace: Path, live: Path) -> None:
    _mirror(workspace, live, protect=True)


# ---- the keeper's logic ----------------------------------------------------------------


class Child(Protocol):
    def poll(self) -> int | None:
        """Its exit code once it has exited."""
        ...

    def stop(self) -> None: ...


class Check(Protocol):
    def result(self) -> tuple[bool, str] | None:
        """(passed, report) once finished."""
        ...

    def cancel(self) -> None: ...


class World(Protocol):
    """What the keeper does to the computer."""

    def start(self, name: Component) -> Child: ...
    def is_ready(self, name: Component) -> bool: ...
    def start_check(self) -> Check: ...
    def snapshot(self) -> str: ...
    def restore(self, version: str) -> None: ...
    def install(self) -> None: ...
    def notify(self, text: str) -> None: ...
    def show_trial(self, summary: str | None) -> None:
        """Shows the trial window for this change; None hides it."""


class Stage(Enum):
    STARTING = auto()
    RUNNING = auto()
    CHECKING = auto()
    TRIAL = auto()
    PAUSED = auto()


def restarted(action: str) -> Component | None:
    """The component a `restart_<name>` request names."""
    return next((name for name in CATALOGUE if action == f"restart_{name}"), None)


def unexpected_exit(name: str, code: int | None) -> bool:
    """Only the layout and assistant have a user-requested normal exit."""
    return code is not None and (code != 0 or name == "automation")


class RefusedCheck:
    __slots__ = ()

    def result(self) -> tuple[bool, str]:
        return False, "The user cancelled the review."

    def cancel(self) -> None:
        pass


class Recovery:
    """Durable rollback target; pending means restore before starting any child."""

    __slots__ = ("path",)

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> tuple[str | None, bool]:
        if not self.path.exists():
            return None, False
        raw: object = json.loads(self.path.read_text(encoding="utf-8"))
        match raw:
            case {"version": str() as version, "pending": bool() as pending}:
                if not version or Path(version).name != version or version in (".", ".."):
                    raise ValueError("Invalid rollback version")
                return version, pending
            case {"version": None, "pending": bool() as pending}:
                return None, pending
            case _:
                raise ValueError("Invalid update recovery state")

    def write(self, version: str | None, *, pending: bool) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        data: RecoveryData = {"version": version, "pending": pending}
        temporary.write_text(json.dumps(data), encoding="utf-8")
        temporary.replace(self.path)


class Keeper:
    """Everything the keeper decides, driven by `request` and a regular `tick`."""

    __slots__ = ("check", "children", "crashes", "deadline", "done", "fresh", "recovery", "stage", "summary", "suspended", "undoable", "world")

    def __init__(self, world: World, recovery: Recovery | None = None) -> None:
        self.recovery = recovery
        self.world = world
        self.children: dict[Component, Child] = {}
        self.stage = Stage.STARTING
        self.deadline = 0.0
        self.check: Check | None = None
        self.summary = ""
        self.undoable: str | None = None
        """The version the last install replaced."""
        self.fresh = False
        """Starting a just-installed change (so failing to start undoes it)."""
        self.crashes: list[float] = []
        self.done = False
        self.suspended: tuple[Component, ...] = ()
        """The assistant was quit: the keeper should exit."""

    def recover(self) -> None:
        """Recover an interrupted install/trial before loading the live source."""
        if self.recovery is None:
            return
        version, pending = self.recovery.read()
        self.undoable = version
        if pending and version is not None:
            self.world.restore(version)
            self.undoable = None
            self.persist(pending=False)
            self.world.notify("Update undone: the previous trial or installation was interrupted.")

    def persist(self, *, pending: bool) -> None:
        if self.recovery is not None:
            self.recovery.write(self.undoable, pending=pending)

    def start(self, now: float) -> None:
        for name in CATALOGUE:
            self.children[name] = self.world.start(name)
        self.stage, self.deadline = Stage.STARTING, now + START_S

    def stop_all(self) -> None:
        for name in reversed(CATALOGUE):
            if (child := self.children.get(name)) is not None and child.poll() is None:
                child.stop()
        self.children = {}

    def request(self, action: str, summary: str, now: float) -> None:
        if self.stage is Stage.PAUSED:
            self.world.notify("Source replacement is in progress; try again after the reload.")
            return
        match action:
            case "install":
                if self.stage in (Stage.CHECKING, Stage.STARTING):
                    self.world.notify("Busy installing; try again in a moment.")
                    return
                if self.stage is Stage.TRIAL:
                    self.persist(pending=False)
                    self.world.show_trial(None)
                self.check, self.summary = self.world.start_check(), summary
                self.stage, self.deadline = Stage.CHECKING, now + CHECK_S
            case "keep":
                if self.stage is Stage.TRIAL:
                    self.persist(pending=False)
                    self.stage = Stage.RUNNING
                    self.world.show_trial(None)
            case "undo":
                if self.undoable is None:
                    self.world.notify("There's no update to undo.")
                else:
                    self.rollback("you undid it", now)
            case _ if (name := restarted(action)) is not None:
                if self.stage is not Stage.RUNNING:
                    self.world.notify("Workspace is starting or updating; try the restart again in a moment.")
                    return
                if (child := self.children.pop(name, None)) is not None and child.poll() is None:
                    child.stop()
                self.children[name] = self.world.start(name)
                self.stage, self.deadline = Stage.STARTING, now + START_S
            case _:
                pass

    def suspend(self, components: tuple[Component, ...]) -> bool:
        """Stop only selected children; retain supervision ownership during IO."""
        if self.stage is not Stage.RUNNING or len(set(components)) != len(components):
            return False
        if any(name not in self.children for name in components):
            return False
        self.suspended = components
        self.stage = Stage.PAUSED
        for name in reversed(CATALOGUE):
            if name in components:
                child = self.children.pop(name)
                if child.poll() is None:
                    child.stop()
        return True

    def resume(self, now: float) -> None:
        """Start paused children only after the coordinator verified replacement."""
        for name in CATALOGUE:
            if name in self.suspended:
                self.children[name] = self.world.start(name)
        self.suspended = ()
        self.stage, self.deadline = Stage.STARTING, now + START_S

    def tick(self, now: float) -> None:
        match self.stage:
            case Stage.PAUSED:
                if (assistant := self.children.get("assistant")) is not None and assistant.poll() == 0:
                    self.stop_all()
                    self.done = True
            case Stage.CHECKING:
                self.checking(now)
            case Stage.STARTING:
                self.starting(now)
            case Stage.TRIAL:
                if any(unexpected_exit(name, child.poll()) for name, child in self.children.items()):
                    self.rollback("it crashed during its trial", now)
                    return
                self.running(now)  # quitting on purpose is handled as usual
                if now > self.deadline and not self.done:
                    self.persist(pending=False)
                    self.stage = Stage.RUNNING
                    self.world.show_trial(None)
            case Stage.RUNNING:
                self.running(now)

    def checking(self, now: float) -> None:
        result = self.check.result() if self.check is not None else (False, "no check")
        if result is None:
            if now > self.deadline:
                if self.check is not None:
                    self.check.cancel()
                self.world.notify("Not installed: the checks took too long.")
                self.stage = Stage.RUNNING
            return
        passed, report = result
        if not passed:
            self.world.notify(f"Not installed: the change failed its checks.\n\n{report[-3000:]}")
            self.stage = Stage.RUNNING
            return
        previous = self.undoable
        try:
            version = self.world.snapshot()
            self.undoable = version
            self.persist(pending=True)  # write before stopping or changing any live file
        except OSError as error:
            self.undoable = previous
            self.world.notify(f"Not installed: couldn't save the rollback version. {error}")
            self.stage = Stage.RUNNING
            return
        try:
            self.stop_all()
            self.world.install()
            self.fresh = True
            self.start(now)
        except OSError as error:
            self.rollback(f"installation failed: {error}", now)

    def starting(self, now: float) -> None:
        failed = any(child.poll() is not None for child in self.children.values()) or now > self.deadline
        if failed and self.fresh and self.undoable is not None:
            self.rollback("it didn't start", now)
        elif failed:
            self.world.notify("Workspace didn't start properly; see the logs.")
            self.stage = Stage.RUNNING
        elif all(self.world.is_ready(name) for name in self.children):
            if self.fresh:
                self.stage, self.deadline = Stage.TRIAL, now + TRIAL_S
                self.world.show_trial(self.summary)
            else:
                self.stage = Stage.RUNNING
            self.fresh = False

    def running(self, now: float) -> None:
        for name, child in list(self.children.items()):
            code = child.poll()
            if code is None:
                continue
            del self.children[name]
            if not unexpected_exit(name, code):
                if name == "assistant":  # Quit in the tray menu: everything stops
                    self.stop_all()
                    self.done = True
                    return
                continue  # the layout quit on purpose: it stays stopped until asked
            self.crashes = [t for t in self.crashes if now - t < CRASH_WINDOW_S] + [now]
            if len(self.crashes) > MAX_CRASHES:
                if self.undoable is not None:
                    self.rollback("it kept crashing", now)
                else:
                    self.world.notify(f"The {name} keeps crashing, so it's stopped. See {name}.log.")
                return
            self.children[name] = self.world.start(name)

    def rollback(self, why: str, now: float) -> None:
        on_trial = self.stage is Stage.TRIAL
        version = self.undoable
        self.persist(pending=True)
        self.stop_all()
        try:
            if version is not None:
                self.world.restore(version)
        except OSError as error:
            self.world.notify(f"Recovery needs another attempt: {error}. Restart Workspace to retry.")
            self.done = True  # durable pending state lets the next launch retry
            return
        self.undoable = None
        self.persist(pending=False)
        self.fresh = False
        self.start(now)
        self.crashes = []
        self.world.notify(f"Update undone: {why}.")
        if on_trial:
            self.world.show_trial(None)


# ---- on Windows ------------------------------------------------------------------------


class _User32(Protocol):
    def FindWindowW(self, cls: str | None, title: str) -> int: ...
    def PostMessageW(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        """The Win32 message ABI requires a window, message and two payload words."""
        ...


class _Function[T](Protocol):
    """The stdcall prototype validates ABI arguments and fixes the scalar result."""

    def __call__(self, *args: object) -> T: ...


class WindowsUser32:
    """Keep pointer-sized handles at the native boundary, before Qt owns the loop."""

    __slots__ = ("find", "post")

    def __init__(self) -> None:
        library = ctypes.WinDLL("user32", use_last_error=True)
        self.find: _Function[int | None] = ctypes.WINFUNCTYPE(wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)(("FindWindowW", library))
        self.post: _Function[int] = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)(
            ("PostMessageW", library)
        )

    def FindWindowW(self, cls: str | None, title: str) -> int:
        return self.find(cls, title) or 0

    def PostMessageW(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        """The Win32 message ABI requires the window, message and two payload words."""
        return self.post(hwnd, message, wparam, lparam)


class Ui(Protocol):
    def approve(self, diff: str) -> bool: ...
    def notify(self, message: str) -> None: ...
    def show_trial(self, summary: str | None, choose: Callable[[str], None]) -> None: ...
    def poll_components(self, supervisor: Keeper, now: float) -> None: ...
    def run(self, tick: Callable[[], bool]) -> None: ...


def _log(text: str) -> None:
    with contextlib.suppress(OSError):
        DIRECTORY.mkdir(parents=True, exist_ok=True)
        with (DIRECTORY / "keeper.log").open("a", encoding="utf-8") as log:
            log.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")


def _pythonw() -> str:
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return str(candidate) if candidate.exists() else sys.executable


class Process:
    """A program the keeper started. Stopping asks it to quit (so the layout lets go
    of held keys) and only then ends it."""

    __slots__ = ("component", "process", "user32")

    def __init__(self, process: subprocess.Popen[bytes], component: Entry, user32: _User32) -> None:
        self.process: subprocess.Popen[bytes] = process
        self.component: Entry = component
        self.user32: _User32 = user32

    def poll(self) -> int | None:
        return self.process.poll()

    def stop(self) -> None:
        window = self.component.window
        if hwnd := self.user32.FindWindowW(window.window_class, window.title):
            self.user32.PostMessageW(hwnd, self.component.quit_message, 0, 0)
        try:
            self.process.wait(timeout=self.component.shutdown_s)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


class _Check:
    __slots__ = ("candidate", "deadline", "digest", "output", "process")

    def __init__(self, candidate: Path) -> None:
        self.candidate = candidate
        self.digest = source_digest(candidate)
        self.deadline = time.monotonic() + CHECK_S
        STATE.mkdir(parents=True, exist_ok=True)
        self.output = STATE / "check.txt"
        with self.output.open("wb") as out:
            self.process = subprocess.Popen(
                [_pythonw(), str(LIVE / "selfcheck.py"), str(candidate)], stdout=out, stderr=subprocess.STDOUT, creationflags=0x0800_0000
            )

    def cancel(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()

    def result(self) -> tuple[bool, str] | None:
        code = self.process.poll()
        if code is None:
            if time.monotonic() > self.deadline:
                self.cancel()
                return False, "Runtime checks timed out."
            return None
        if source_digest(self.candidate) != self.digest:
            return False, "The candidate changed during its checks; prepare and check it again."
        return code == 0, self.output.read_text(encoding="utf-8", errors="replace")


def main(ui: Ui) -> None:
    user32 = WindowsUser32()
    choices: list[str] = []

    def approve(candidate: Path) -> bool:
        return ui.approve(source_diff(LIVE, candidate))

    class WinWorld:
        __slots__ = ("candidate",)

        def __init__(self) -> None:
            self.candidate = STATE / "candidate"

        def start(self, name: Component) -> Child:
            component = CATALOGUE[name]
            marker = component.marker(STATE)
            marker.unlink(missing_ok=True)
            env = {**os.environ, "WORKSPACE_READY": str(marker)}
            with (DIRECTORY / f"{name}.log").open("ab") as errors:
                process = subprocess.Popen([_pythonw(), "-m", component.module], cwd=LIVE, env=env, stderr=errors, creationflags=0x0800_0000)
            _log(f"started {name}")
            return Process(process, component, user32)

        def is_ready(self, name: Component) -> bool:
            # The keeper is the only starter and removes the marker first, so any
            # marker is this child's. A venv launcher's pid differs from its writer's.
            return read_marker(CATALOGUE[name].marker(STATE)) is not None

        def start_check(self) -> Check:
            _log("checking the workspace")
            review = approve if os.environ.get("WORKSPACE_AGENT_APPROVALS", "never").lower() == "ask" else None
            if not prepare_candidate(WORKSPACE, LIVE, self.candidate, review):
                return RefusedCheck()
            return _Check(self.candidate)

        def snapshot(self) -> str:
            return snapshot(LIVE, VERSIONS)

        def restore(self, version: str) -> None:
            _log(f"restoring {version}")
            restore(VERSIONS / version, LIVE)

        def install(self) -> None:
            _log("installing the workspace")
            install(self.candidate, LIVE)

        def notify(self, text: str) -> None:
            _log(text)
            ui.notify(text)

        def show_trial(self, summary: str | None) -> None:
            _log(f"on trial: {summary}" if summary else "trial over")
            ui.show_trial(summary, choices.append)

    keeper = Keeper(WinWorld(), Recovery(STATE / "recovery.json"))
    keeper.recover()
    keeper.start(time.monotonic())

    def loop() -> bool:
        now = time.monotonic()
        try:
            ui.poll_components(keeper, now)
        except OSError as error:
            _log(f"component control error: {error}")
        for action, summary in [*((c, "") for c in choices), *take_requests()]:
            _log(f"request {action} {summary}")
            try:
                keeper.request(action, summary, now)
            except OSError as error:
                keeper.world.notify(f"Request failed: {error}")
        choices.clear()
        try:
            keeper.tick(now)
        except OSError as error:
            _log(f"keeper error: {error}")
        return keeper.done

    ui.run(loop)


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("the keeper runs on Windows")

    from runtime import activate

    activate()

    from keeper_ui import launch

    launch(STATE, main)
