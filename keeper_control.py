"""The keeper's typed files: its inbox, its rollback target and the deployment pause.

Other programs ask the keeper for installs, undo, keep and restarts through its
inbox folder; a request it can't read is refused, never silently dropped. The
keeper owns a deployment pause until an explicit matching resume, so a failed
coordinator never starts children against a partly replaced tree. It runs
directly on the installed Python 3.15 with the keeper.
"""

import contextlib
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Protocol

from pydantic import TypeAdapter, ValidationError

from components import Component


@dataclass(frozen=True, slots=True)
class Install:
    """Check and install the agent's workspace; the summary titles its trial."""

    summary: str
    digest: str
    """The requested source digest; the keeper's install result names it."""
    checked: str | None
    """The source digest whose fast selfcheck passed, or None. When the keeper's frozen
    candidate has exactly this digest, only the deferred native modules run."""
    action: Literal["install"] = "install"


@dataclass(frozen=True, slots=True)
class Undo:
    action: Literal["undo"] = "undo"


@dataclass(frozen=True, slots=True)
class Keep:
    """End the current trial and keep the change."""

    action: Literal["keep"] = "keep"


@dataclass(frozen=True, slots=True)
class Restart:
    component: Component
    action: Literal["restart"] = "restart"


type Request = Install | Undo | Keep | Restart


@dataclass(frozen=True, slots=True)
class Malformed:
    """An inbox file that names no request the keeper knows; it is refused."""

    file: str
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Rollback:
    """The version the last install replaced; pending means restore it before starting."""

    version: str | None
    pending: bool


@dataclass(frozen=True, slots=True)
class Pause:
    token: str
    components: tuple[Component, ...]
    action: Literal["pause"] = "pause"


@dataclass(frozen=True, slots=True)
class Resume:
    token: str
    action: Literal["resume"] = "resume"


@dataclass(frozen=True, slots=True)
class Paused:
    token: str
    components: tuple[Component, ...]
    phase: Literal["paused"] = "paused"


@dataclass(frozen=True, slots=True)
class Resumed:
    token: str
    phase: Literal["resumed"] = "resumed"


@dataclass(frozen=True, slots=True)
class Refused:
    token: str
    reason: str
    phase: Literal["refused"] = "refused"


@dataclass(frozen=True, slots=True)
class InstallChecking:
    """The keeper accepted the install request and is checking its candidate."""

    digest: str
    stage: Literal["checking"] = "checking"


@dataclass(frozen=True, slots=True)
class InstallStarted:
    """The checked candidate is installed and its programs were started on trial."""

    digest: str
    summary: str
    version: str
    """The snapshot of the source this install replaced, under the keeper's versions folder."""
    stage: Literal["installed"] = "installed"


@dataclass(frozen=True, slots=True)
class InstallRefused:
    """The keeper did not install the request, or undid it; `reason` is what it showed the user."""

    digest: str
    reason: str
    stage: Literal["refused"] = "refused"


type InstallResult = InstallChecking | InstallStarted | InstallRefused
"""The keeper's latest install outcome, so the requesting task waits for it instead of guessing."""


@dataclass(frozen=True, slots=True)
class Capability:
    keeper_pid: int
    version: Literal[1] = 1


REQUEST = TypeAdapter[Request](Install | Undo | Keep | Restart)
ROLLBACK = TypeAdapter[Rollback](Rollback)
COMMAND = TypeAdapter[Pause | Resume](Pause | Resume)
STATUS = TypeAdapter[Paused | Resumed | Refused](Paused | Resumed | Refused)
CAPABILITY = TypeAdapter[Capability](Capability)
INSTALL_RESULT = TypeAdapter[InstallResult](InstallChecking | InstallStarted | InstallRefused)
INSTALL_RESULT_FILE: Final = "install-result.json"


def record_install(folder: Path, result: InstallResult) -> None:
    """Replace the keeper's install result whole; a reader never sees half of it."""
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / f"{INSTALL_RESULT_FILE}.{time.time_ns()}.tmp"
    temporary.write_bytes(INSTALL_RESULT.dump_json(result))
    temporary.replace(folder / INSTALL_RESULT_FILE)


def install_result(folder: Path) -> InstallResult | None:
    """The latest install result, or None while there is none or it can't be read yet."""
    try:
        return INSTALL_RESULT.validate_json((folder / INSTALL_RESULT_FILE).read_bytes(), strict=True)
    except OSError, ValidationError:
        return None


class Supervisor(Protocol):
    def suspend(self, components: tuple[Component, ...]) -> bool: ...
    def resume(self, now: float) -> None: ...


def ask(folder: Path, request: Request) -> None:
    """Leave one request in the keeper's inbox; it appears whole, never half-written."""
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns():020d}"
    temporary = folder / f"{name}.tmp"
    temporary.write_bytes(REQUEST.dump_json(request))
    temporary.replace(folder / f"{name}.json")


def take(folder: Path) -> Iterator[Request | Malformed]:
    """Waiting requests, oldest first. Each is delivered once, after its file is removed."""
    for path in sorted(folder.glob("*.json")) if folder.exists() else ():
        try:
            data = path.read_bytes()
            path.unlink()
        except OSError:
            continue  # held by another process; the next poll retries it
        try:
            received: Request | Malformed = REQUEST.validate_json(data, strict=True)
        except ValidationError as error:
            received = Malformed(path.name, str(error))
        yield received


def submit(folder: Path, request: Pause | Resume) -> None:
    """Publish one complete command; an existing command belongs to its sender."""
    temporary = folder / "component-command.pending"
    with temporary.open("xb") as stream:
        stream.write(COMMAND.dump_json(request))
    try:
        destination = folder / "component-command.json"
        if destination.exists():
            raise RuntimeError("Another component command is pending.")
        temporary.rename(destination)
    finally:
        temporary.unlink(missing_ok=True)


class Control:
    """Own command consumption and the current deployment's exclusive pause."""

    __slots__ = ("folder", "paused", "pending")

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.paused: Paused | None = None
        # Retain the immutable acknowledgment after effects commit, so a
        # Windows reader blocking replacement cannot cause repeated effects.
        self.pending: Paused | Resumed | Refused | None = None
        folder.mkdir(parents=True, exist_ok=True)
        capability = folder / "component-capability.pending"
        capability.write_bytes(CAPABILITY.dump_json(Capability(os.getpid())))
        capability.replace(folder / "component-capability.json")

    def publish(self) -> bool:
        if self.pending is None:
            return True
        temporary = self.folder / "component-status.pending"
        try:
            temporary.write_bytes(STATUS.dump_json(self.pending))
            temporary.replace(self.folder / "component-status.json")
        except PermissionError:
            return False
        self.pending = None
        return True

    def poll(self, supervisor: Supervisor, now: float) -> None:
        if not self.publish():
            return
        path = self.folder / "component-command.json"
        if not path.exists():
            return
        try:
            request = COMMAND.validate_json(path.read_bytes(), strict=True)
            path.unlink()
        except ValidationError:
            with contextlib.suppress(PermissionError, FileNotFoundError):
                path.unlink()
            return
        except FileNotFoundError, PermissionError:
            return
        status: Paused | Resumed | Refused
        match request:
            case Pause(token=token, components=components):
                if self.paused is not None or not supervisor.suspend(components):
                    status = Refused(token, "The keeper is busy or the component selection is invalid.")
                else:
                    status = Paused(token, components)
                    self.paused = status
            case Resume(token=token):
                if self.paused is None or self.paused.token != token:
                    status = Refused(token, "This coordinator does not own the pause.")
                else:
                    supervisor.resume(now)
                    self.paused = None
                    status = Resumed(token)
        self.pending = status
        self.publish()
