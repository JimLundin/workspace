"""The keeper: the one part of Workspace that never changes itself.

It runs the layout and the assistant, and is the only writer of the installed
copy. When the agent or `Dev.cmd deploy` asks, it checks the change
(selfcheck.py), records the running version, installs the change and restarts
only the programs it affects. Each version is a commit in the keeper's own Git
repository beside its state, so undo checks out the version an install
replaced. A failed check prevents an installation. A change that doesn't start,
crashes during its ten-minute trial, or keeps crashing later is undone. Undo in
the tray menu rolls back the last installed change at any time.

So that a change can never break what undoes it, the agent can't edit the
protected files (`PROTECTED`); only a deploy changes them, and the keeper then
relaunches itself. What it runs is listed in the protected components.py. The
other programs talk to it through files: typed requests in its inbox (the
protected keeper_control.py), and a readiness marker each program writes once it's up.

    pythonw keeper.py        (workspace.pyw does this)
"""

import contextlib
import ctypes
import difflib
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from collections.abc import Callable, Generator
from ctypes import wintypes
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Final, Protocol, assert_never

from components import CATALOGUE, STATE_VARIABLE, Component, Entry, read_marker

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl
from restart_plan import Relaunch, RestartChildren, RestartPlan, Tree, restart_plan

# Bundled dependencies load only after `keeper.py` activates the runtime.
lazy from keeper_control import (
    ROLLBACK,
    Install,
    InstallChecking,
    InstallRefused,
    InstallResult,
    InstallStarted,
    Kept,
    Malformed,
    Pending,
    Request,
    Restart,
    Rollback,
    Trial,
    Undo,
    record_install,
    take,
)

LIVE: Final = Path(__file__).resolve().parent
"""Workspace's own folder: the version that runs."""
DIRECTORY: Final = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "workspace"
WORKSPACE: Final = DIRECTORY / "workspace"
"""Where the agent edits a copy of the source; installed from here."""


def state_for(workspace: Path) -> Path:
    """The keeper's state folder beside the install root it installs from."""
    return workspace.parent / "keeper"


def versions_for(workspace: Path) -> Path:
    """The keeper's version repository, beside the install root."""
    return workspace.parent / "versions.git"


STATE: Final = state_for(WORKSPACE)
REQUESTS: Final = STATE / "requests"
VERSIONS: Final = versions_for(WORKSPACE)
ROLLBACK_FILE: Final = "rollback.json"

PROTECTED: Final = frozenset(
    {"keeper.py", "selfcheck.py", "workspace.pyw", "runtime.py", "keeper_ui.py", "keeper_control.py", "components.py", "restart_plan.py"}
)
"""Files the agent can't change; a deploy that changes one relaunches the keeper."""

RELAUNCH: Final = "--relaunch"
"""workspace.pyw's argument when the keeper it replaces is still exiting."""
RELAUNCH_WAIT_S: Final = 60.0
START_S: Final = 30.0
"""How long a program gets to say it's ready."""
TRIAL_S: Final = 600.0
CHECK_S: Final = 600.0
"""A hang guard, not a budget: the full parallel selfcheck measured 266 s against 437 s
sequentially, which had outgrown the former 300 s limit and failed every install."""
CRASH_WINDOW_S: Final = 600.0
MAX_CRASHES: Final = 3
"""Restarts allowed within `CRASH_WINDOW_S`; one more crash and the keeper stops trying."""
CREATE_NO_WINDOW: Final = 0x0800_0000
DETACHED_PROCESS: Final = 0x0000_0008
CREATE_NEW_PROCESS_GROUP: Final = 0x0000_0200


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


def source_tree(root: Path) -> Tree:
    return Tree(root, frozenset(source_files(root)))


def source_diff(before: Path, after: Path) -> str:
    parts: list[str] = []
    for name in sorted(set(source_files(before)) | set(source_files(after))):
        old = (before / name).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if (before / name).exists() else []
        new = (after / name).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if (after / name).exists() else []
        parts.extend(difflib.unified_diff(old, new, f"running/{name}", f"candidate/{name}"))
    return "".join(parts)


def prepare_candidate(source: Path, live: Path, candidate: Path, *, deploy: bool) -> None:
    """Freeze source for checks; only a deploy may change protected files."""
    copy_source(source, candidate)
    if deploy:
        return
    for name in PROTECTED:
        if (candidate / name).read_bytes() != (live / name).read_bytes():
            raise OSError(f"The protected file {name} was changed")


def _mirror(source: Path, target: Path, *, clear_caches: bool) -> None:
    """Makes `target`'s source files the same as `source`'s."""
    if clear_caches:
        for cache in target.rglob("__pycache__"):
            shutil.rmtree(cache)
    wanted = set(source_files(source))
    for name in source_files(target) if target.exists() else []:
        if name not in wanted:
            (target / name).unlink()
    for name in wanted:
        data = (source / name).read_bytes()
        destination = target / name
        if destination.is_file() and destination.read_bytes() == data:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


def copy_source(source: Path, target: Path) -> None:
    """Makes `target` an exact copy of `source`'s source files (for the agent's workspace)."""
    _mirror(source, target, clear_caches=False)


INSTALLED: Final = "refs/heads/installed"
"""The commit whose files the installed copy holds."""
_GIT: Final = (
    "--literal-pathspecs",
    "-c",
    "core.autocrlf=false",
    "-c",
    "core.hooksPath=",
    "-c",
    "user.name=Workspace keeper",
    "-c",
    "user.email=keeper@localhost",
)
_ATTRIBUTES: Final = b"* -text -filter -ident -export-subst -export-ignore\n"
"""Versions keep exact bytes: no line-ending, filter or archive attribute applies."""


class Versions:
    """The installed copy's versions, as commits in a bare repository the keeper owns.

    The installed copy needn't be a Git checkout. A version is committed from
    whichever folder holds its source files; `INSTALLED` names the one in place.
    """

    __slots__ = ("live", "repo")

    def __init__(self, repo: Path, live: Path) -> None:
        self.repo, self.live = repo, live

    def _git(self, *arguments: str, work_tree: Path | None = None, stdin: bytes = b"") -> bytes:
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        environment["GIT_INDEX_FILE"] = str(self.repo / "keeper.index")
        command = ["git", f"--git-dir={self.repo}", *([f"--work-tree={work_tree}"] if work_tree is not None else []), *_GIT, *arguments]
        result = subprocess.run(
            command, input=stdin, capture_output=True, env=environment, check=False, creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        if result.returncode != 0:
            raise OSError(f"git {arguments[0]} failed: {result.stderr.decode('utf-8', errors='replace').strip()[-500:]}")
        return result.stdout

    def _text(self, *arguments: str) -> str:
        return self._git(*arguments).decode("ascii").strip()

    def _ensure(self) -> None:
        if not (self.repo / "HEAD").is_file():
            self.repo.mkdir(parents=True, exist_ok=True)
            self._git("init", "--quiet", "--bare")
        (self.repo / "info").mkdir(exist_ok=True)
        if not (self.repo / "info" / "attributes").is_file() or (self.repo / "info" / "attributes").read_bytes() != _ATTRIBUTES:
            (self.repo / "info" / "attributes").write_bytes(_ATTRIBUTES)

    def installed(self) -> str | None:
        if not (self.repo / "HEAD").is_file():
            return None
        try:
            return self._text("rev-parse", "--verify", "--quiet", INSTALLED + "^{commit}")
        except OSError:
            return None

    def record(self, tree: Path, message: str) -> str:
        """Commit `tree`'s source files on top of the installed version; an unchanged tree is that version."""
        self._ensure()
        self._git("read-tree", "--empty")
        names = "\0".join(source_files(tree)).encode("utf-8")
        self._git("add", "--force", "--pathspec-from-file=-", "--pathspec-file-nul", work_tree=tree, stdin=names)
        snapshot = self._text("write-tree")
        parent = self.installed()
        if parent is not None and self._text("rev-parse", parent + "^{tree}") == snapshot:
            return parent
        return self._text("commit-tree", "--no-gpg-sign", snapshot, *(("-p", parent) if parent is not None else ()), "-m", message)

    def mark(self, version: str) -> None:
        self._git("update-ref", INSTALLED, version)

    def snapshot(self) -> str:
        """Record the installed copy as it is now, including edits made outside the keeper."""
        version = self.record(self.live, "The installed copy")
        self.mark(version)
        return version

    def export(self, version: str, target: Path) -> None:
        """Write `version`'s source files into an empty `target`."""
        archive = self._git("archive", "--format=tar", version)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(target, filter="data")

    def install(self, tree: Path, summary: str) -> str:
        version = self.record(tree, summary or "Install")
        _mirror(tree, self.live, clear_caches=True)
        self.mark(version)
        return version

    def restore(self, version: str) -> None:
        with tempfile.TemporaryDirectory(prefix="workspace-version-") as folder:
            self.export(version, Path(folder))
            _mirror(Path(folder), self.live, clear_caches=True)
        self.mark(version)


@contextlib.contextmanager
def exclusive(state: Path, *, wait_s: float = 0) -> Generator[bool]:
    """Hold the keeper's single-instance lock; False when a keeper or a deploy holds it."""
    state.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + wait_s
    with (state / "keeper.lock").open("a+b") as lock:
        while True:
            try:
                if sys.platform == "win32":
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(0.25)
        yield True


def install_stopped(source: Path, live: Path, summary: str, *, state: Path, versions: Path) -> str:
    """A deploy while no keeper runs: record and install `source` without starting anything.

    The caller holds `exclusive` on `state`, so no keeper starts during the copy.
    Returns the replaced version, which the tray's Undo restores later.
    """
    recovery = Recovery(state / ROLLBACK_FILE)
    match recovery.read():
        case Pending() | Trial():
            raise OSError("The keeper has an interrupted update to recover; start Workspace once, then deploy again.")
        case Kept():
            pass
    store = Versions(versions, live)
    previous = store.snapshot()
    store.install(source, summary)
    recovery.write(Kept(previous))
    return previous


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
    def start_check(self, install: Install) -> Check: ...
    def plan(self, version: str | None) -> RestartPlan:
        """What moving the installed copy to `version` restarts; None is the checked candidate."""
        ...

    def snapshot(self) -> str: ...
    def install(self, summary: str) -> None: ...
    def restore(self, version: str) -> None: ...
    def relaunch(self) -> None:
        """Start a new keeper from the installed copy; this one exits next."""
        ...

    def notify(self, text: str) -> None:
        """Interrupt the user: only when Workspace can't run without them."""
        ...

    def note(self, text: str) -> None:
        """Record an outcome without interrupting the user."""
        ...

    def record(self, result: InstallResult) -> None:
        """Publish the install outcome the requesting task waits for."""
        ...


class Stage(Enum):
    STARTING = auto()
    RUNNING = auto()
    CHECKING = auto()
    TRIAL = auto()


def unexpected_exit(code: int | None) -> bool:
    """A clean exit is the user quitting that program."""
    return code is not None and code != 0


class Recovery:
    """Durable rollback target and what a starting keeper must do with it."""

    __slots__ = ("path",)

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> Rollback:
        if not self.path.exists():
            return Kept(None)
        rollback = ROLLBACK.validate_json(self.path.read_bytes(), strict=True)
        match rollback:
            case Kept(version=None):
                return rollback
            case Kept(version=str() as version) | Pending(version=version) | Trial(version=version) if not version.isalnum():
                raise ValueError("Invalid rollback version")
            case _:
                return rollback

    def write(self, rollback: Rollback) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(ROLLBACK.dump_json(rollback))
        temporary.replace(self.path)


class Keeper:
    """Everything the keeper decides, driven by `request` and a regular `tick`."""

    __slots__ = (
        "check",
        "children",
        "crashes",
        "deadline",
        "digest",
        "done",
        "fresh",
        "recovery",
        "stage",
        "started",
        "summary",
        "undoable",
        "world",
    )

    def __init__(self, world: World, recovery: Recovery | None = None) -> None:
        self.recovery = recovery
        self.world = world
        self.children: dict[Component, Child] = {}
        self.stage = Stage.STARTING
        self.deadline = 0.0
        self.check: Check | None = None
        self.summary = ""
        self.digest: str | None = None
        """The source digest of the install being checked, started or on trial."""
        self.undoable: str | None = None
        """The version the last install replaced."""
        self.fresh = False
        """Starting a just-installed change (so failing to start undoes it)."""
        self.started: InstallStarted | None = None
        """The install result to publish once the fresh programs are ready."""
        self.crashes: list[float] = []
        self.done = False
        """The assistant was quit, or a new keeper takes over: this one should exit."""

    def recover(self) -> None:
        """Recover an interrupted install/trial before loading the live source."""
        if self.recovery is None:
            return
        match self.recovery.read():
            case Pending(version=version):
                self.undoable = version  # still undoable if this restore fails
                try:
                    plan: RestartPlan = self.world.plan(version)
                except OSError:
                    plan = RestartChildren(tuple(CATALOGUE))
                self.world.restore(version)
                self.undoable = None
                self.persist(Kept(None))
                self.world.notify("Update undone: the previous trial or installation was interrupted.")
                if plan is Relaunch.KEEPER:
                    self.relaunch()
            case Trial(version=version, started=started):
                self.undoable, self.fresh, self.started = version, True, started
                self.digest, self.summary = started.digest, started.summary
                self.persist(Pending(version))
            case Kept(version=version):
                self.undoable = version

    def persist(self, rollback: Rollback) -> None:
        if self.recovery is not None:
            self.recovery.write(rollback)

    def start(self, now: float, components: tuple[Component, ...] = tuple(CATALOGUE)) -> None:
        for name in CATALOGUE:
            if name in components:
                self.children[name] = self.world.start(name)
        self.stage, self.deadline = Stage.STARTING, now + START_S

    def stop(self, components: tuple[Component, ...] = tuple(CATALOGUE)) -> None:
        for name in reversed(CATALOGUE):
            if name in components and (child := self.children.pop(name, None)) is not None and child.poll() is None:
                child.stop()

    def stop_all(self) -> None:
        self.stop()
        self.children = {}

    def relaunch(self) -> None:
        self.stop_all()
        self.world.relaunch()
        self.done = True

    def request(self, request: Request | Malformed, now: float) -> None:
        match request:
            case Malformed(file=file, reason=reason):
                self.world.notify(f"Refused a request the keeper doesn't recognise ({file}).\n\n{reason}")
            case Install(summary=summary, digest=digest):
                if self.stage in (Stage.CHECKING, Stage.STARTING):
                    self.refuse(digest, "Busy installing; try again in a moment.")
                    return
                if self.stage is Stage.TRIAL:
                    self.persist(Kept(self.undoable))
                self.check = self.world.start_check(request)
                self.summary, self.digest = summary, digest
                self.world.record(InstallChecking(digest))
                self.stage, self.deadline = Stage.CHECKING, now + CHECK_S
            case Undo():
                if self.undoable is None:
                    self.world.notify("There's no update to undo.")
                else:
                    self.rollback("you undid it", now)
            case Restart(component=name):
                if self.stage is not Stage.RUNNING:
                    self.world.notify("Workspace is starting or updating; try the restart again in a moment.")
                    return
                self.stop((name,))
                self.start(now, (name,))
            case _:
                assert_never(request)

    def refuse(self, digest: str | None, reason: str) -> None:
        """Tell the task that asked for this install why it was not installed.

        The keeper exists to install, try and undo changes without the user; a
        pop-up for every refusal or undo made each self-change need attention.
        """
        self.world.note(reason)
        if digest is not None:
            self.world.record(InstallRefused(digest, reason))

    def tick(self, now: float) -> None:
        match self.stage:
            case Stage.CHECKING:
                self.checking(now)
            case Stage.STARTING:
                self.starting(now)
            case Stage.TRIAL:
                if any(unexpected_exit(child.poll()) for child in self.children.values()):
                    self.rollback("it crashed during its trial", now)
                    return
                self.running(now)  # quitting on purpose is handled as usual
                if now > self.deadline and not self.done:
                    self.persist(Kept(self.undoable))
                    self.stage = Stage.RUNNING
            case Stage.RUNNING:
                self.running(now)

    def checking(self, now: float) -> None:
        result = self.check.result() if self.check is not None else (False, "no check")
        if result is None:
            if now > self.deadline:
                if self.check is not None:
                    self.check.cancel()
                self.refuse(self.digest, "Not installed: the checks took too long.")
                self.stage = Stage.RUNNING
            return
        passed, report = result
        if not passed:
            self.refuse(self.digest, f"Not installed: the change failed its checks.\n\n{report[-3000:]}")
            self.stage = Stage.RUNNING
            return
        previous = self.undoable
        try:
            plan = self.world.plan(None)
            version = self.world.snapshot()
            self.undoable = version
            self.persist(Pending(version))  # write before stopping or changing any live file
        except OSError as error:
            self.undoable = previous
            self.refuse(self.digest, f"Not installed: couldn't save the rollback version. {error}")
            self.stage = Stage.RUNNING
            return
        assert self.digest is not None, "Checks only run for an install request."
        started = InstallStarted(self.digest, self.summary, version)
        try:
            match plan:
                case Relaunch.KEEPER:
                    self.stop_all()
                    self.world.install(self.summary)
                    self.persist(Trial(version, started))
                    self.relaunch()
                case RestartChildren(components=()):
                    self.world.install(self.summary)
                    self.persist(Kept(version))
                    self.world.record(started)
                    self.stage = Stage.RUNNING
                case RestartChildren(components=components):
                    self.stop(components)
                    self.world.install(self.summary)
                    self.fresh, self.started = True, started
                    self.start(now, components)
                case _:
                    assert_never(plan)
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
                if self.started is not None:
                    self.world.record(self.started)
            else:
                self.stage = Stage.RUNNING
            self.fresh, self.started = False, None

    def running(self, now: float) -> None:
        for name, child in list(self.children.items()):
            code = child.poll()
            if code is None:
                continue
            del self.children[name]
            if not unexpected_exit(code):
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
        version = self.undoable
        self.children = {name: child for name, child in self.children.items() if child.poll() is None}
        plan: RestartPlan = RestartChildren(tuple(CATALOGUE))
        if version is not None:
            self.persist(Pending(version))
            with contextlib.suppress(OSError):  # restore anyway and restart every child
                plan = self.world.plan(version)
        match plan:
            case Relaunch.KEEPER:
                self.stop_all()
            case RestartChildren(components=components):
                self.stop(components)
            case _:
                assert_never(plan)
        try:
            if version is not None:
                self.world.restore(version)
        except OSError as error:
            self.world.notify(f"Recovery needs another attempt: {error}. Restart Workspace to retry.")
            self.stop_all()
            self.done = True  # durable pending state lets the next launch retry
            return
        self.undoable = None
        self.persist(Kept(None))
        self.fresh, self.started = False, None
        self.crashes = []
        match plan:
            case Relaunch.KEEPER:
                self.relaunch()
            case RestartChildren(components=components):
                missing: tuple[Component, ...] = tuple(name for name in CATALOGUE if name in components or name not in self.children)
                self.start(now, missing)
            case _:
                assert_never(plan)
        self.refuse(self.digest, f"Update undone: {why}.")


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
    def notify(self, message: str) -> None: ...
    def run(self, tick: Callable[[], bool]) -> None: ...


def _log(text: str) -> None:
    with contextlib.suppress(OSError):
        DIRECTORY.mkdir(parents=True, exist_ok=True)
        with (DIRECTORY / "keeper.log").open("a", encoding="utf-8") as log:
            log.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")


def _pythonw() -> str:
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return str(candidate) if candidate.exists() else sys.executable


def console_python() -> str:
    """The console interpreter beside the running one, for checks started with CREATE_NO_WINDOW.

    Workspace runs under pythonw, which has no console, and the flag does nothing for
    it: every console program a check's tests started (git, PowerShell, Python) then
    opened its own visible window, hundreds per check. A console interpreter started
    with the flag owns one hidden console that all of those inherit instead.
    """
    candidate = Path(sys.executable).with_name("python.exe")
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

    def __init__(self, candidate: Path, checked: str | None) -> None:
        self.candidate = candidate
        self.digest = source_digest(candidate)
        self.deadline = time.monotonic() + CHECK_S
        STATE.mkdir(parents=True, exist_ok=True)
        self.output = STATE / "check.txt"
        # The agent's fast check already compiled, imported and ran every portable
        # test on these exact bytes; repeating that doubled each install's checks.
        # Only the tests the change affects; the full suite runs in CI.
        fast_checked = checked == self.digest
        profile: tuple[str, ...] = ("--native", "--changed-from", str(LIVE)) if fast_checked else ("--changed-from", str(LIVE))
        _log("checking the workspace: " + ("native modules after its passing fast check" if fast_checked else "the tests the change affects"))
        with self.output.open("wb") as out:
            self.process = subprocess.Popen(
                [console_python(), str(LIVE / "selfcheck.py"), str(candidate), *profile],
                stdout=out,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
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

    class WinWorld:
        __slots__ = ("candidate", "versions")

        def __init__(self) -> None:
            self.candidate = STATE / "candidate"
            self.versions = Versions(VERSIONS, LIVE)

        def start(self, name: Component) -> Child:
            component = CATALOGUE[name]
            marker = component.marker(STATE)
            marker.unlink(missing_ok=True)
            env = {**os.environ, "WORKSPACE_READY": str(marker), STATE_VARIABLE: str(STATE)}
            with (DIRECTORY / f"{name}.log").open("ab") as errors:
                process = subprocess.Popen([_pythonw(), "-m", component.module], cwd=LIVE, env=env, stderr=errors, creationflags=0x0800_0000)
            _log(f"started {name}")
            return Process(process, component, user32)

        def is_ready(self, name: Component) -> bool:
            # The keeper is the only starter and removes the marker first, so any
            # marker is this child's. A venv launcher's pid differs from its writer's.
            return read_marker(CATALOGUE[name].marker(STATE)) is not None

        def start_check(self, install: Install) -> Check:
            source = WORKSPACE if install.source is None else Path(install.source)
            prepare_candidate(source, LIVE, self.candidate, deploy=install.source is not None)
            return _Check(self.candidate, install.checked)

        def plan(self, version: str | None) -> RestartPlan:
            if version is None:
                return restart_plan(source_tree(LIVE), source_tree(self.candidate), PROTECTED)
            with tempfile.TemporaryDirectory(prefix="workspace-version-") as folder:
                self.versions.export(version, Path(folder))
                return restart_plan(source_tree(LIVE), source_tree(Path(folder)), PROTECTED)

        def snapshot(self) -> str:
            return self.versions.snapshot()

        def restore(self, version: str) -> None:
            _log(f"restoring {version}")
            self.versions.restore(version)

        def install(self, summary: str) -> None:
            _log(f"installing {self.versions.install(self.candidate, summary)}")

        def relaunch(self) -> None:
            _log("relaunching the keeper from the installed copy")
            environment = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "WORKSPACE_BUNDLED_RUNTIME")}
            subprocess.Popen(
                [_pythonw(), str(LIVE / "workspace.pyw"), RELAUNCH],
                cwd=LIVE,
                env=environment,
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            )

        def notify(self, text: str) -> None:
            _log(text)
            ui.notify(text)

        def note(self, text: str) -> None:
            _log(text)

        def record(self, result: InstallResult) -> None:
            if isinstance(result, InstallStarted):
                _log(f"on trial: {result.summary}")
            record_install(STATE, result)

    keeper = Keeper(WinWorld(), Recovery(STATE / ROLLBACK_FILE))
    keeper.recover()
    if not keeper.done:
        keeper.start(time.monotonic())

    def loop() -> bool:
        now = time.monotonic()
        for request in take(REQUESTS):
            _log(f"request {request}")
            try:
                keeper.request(request, now)
            except OSError as error:
                match request:
                    case Install(digest=digest):
                        # The task waiting on this install learns why instead of timing out.
                        keeper.refuse(digest, f"Request failed: {error}")
                    case _:
                        keeper.world.notify(f"Request failed: {error}")
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
