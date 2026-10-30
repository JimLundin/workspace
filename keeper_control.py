"""Typed file handoff for pausing supervised children during source replacement.

The keeper owns the pause until an explicit matching resume. A failed coordinator
never starts children against a partly replaced tree. It runs directly on
the installed Python 3.15 with the keeper.
"""

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import TypeAdapter, ValidationError

from keeper import Program


@dataclass(frozen=True, slots=True)
class Pause:
    token: str
    components: tuple[Program, ...]
    action: Literal["pause"] = "pause"


@dataclass(frozen=True, slots=True)
class Resume:
    token: str
    action: Literal["resume"] = "resume"


@dataclass(frozen=True, slots=True)
class Paused:
    token: str
    components: tuple[Program, ...]
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
class Capability:
    keeper_pid: int
    version: Literal[1] = 1


REQUEST = TypeAdapter[Pause | Resume](Pause | Resume)
STATUS = TypeAdapter[Paused | Resumed | Refused](Paused | Resumed | Refused)
CAPABILITY = TypeAdapter[Capability](Capability)


class Supervisor(Protocol):
    def suspend(self, components: tuple[Program, ...]) -> bool: ...
    def resume(self, now: float) -> None: ...


def submit(folder: Path, request: Pause | Resume) -> None:
    """Publish one complete command; an existing command belongs to its sender."""
    temporary = folder / "component-command.pending"
    with temporary.open("xb") as stream:
        stream.write(REQUEST.dump_json(request))
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
            request = REQUEST.validate_json(path.read_bytes(), strict=True)
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
