"""The keeper's typed files: its inbox, its install results and its rollback target.

The agent and `Dev.cmd deploy` ask the keeper for installs, and the tray for
undo and restarts, through its inbox folder; a request it can't read is refused,
never silently dropped. It runs directly on the installed Python 3.15 with the keeper.
"""

import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

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
    source: str | None = None
    """A deploy's staged folder, which may change protected files; None is the agent's workspace."""
    action: Literal["install"] = "install"


@dataclass(frozen=True, slots=True)
class Undo:
    action: Literal["undo"] = "undo"


@dataclass(frozen=True, slots=True)
class Restart:
    component: Component
    action: Literal["restart"] = "restart"


type Request = Install | Undo | Restart


@dataclass(frozen=True, slots=True)
class Malformed:
    """An inbox file that names no request the keeper knows; it is refused."""

    file: str
    reason: str


@dataclass(frozen=True, slots=True)
class InstallChecking:
    """The keeper accepted the install request and is checking its candidate."""

    digest: str
    stage: Literal["checking"] = "checking"


@dataclass(frozen=True, slots=True)
class InstallStarted:
    """The checked candidate is installed and the programs it restarted came up; its trial runs."""

    digest: str
    summary: str
    version: str
    """The commit of the version this install replaced, in the keeper's version store."""
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
class Kept:
    """Nothing to recover; `version` is what Undo restores, if anything."""

    version: str | None
    phase: Literal["kept"] = "kept"


@dataclass(frozen=True, slots=True)
class Pending:
    """An install or trial was interrupted: restore `version` before starting any program."""

    version: str
    phase: Literal["pending"] = "pending"


@dataclass(frozen=True, slots=True)
class Trial:
    """The keeper relaunched into a fresh install: start it on trial, undoing to `version`."""

    version: str
    started: InstallStarted
    """Published once the relaunched programs are ready."""
    phase: Literal["trial"] = "trial"


type Rollback = Kept | Pending | Trial


REQUEST = TypeAdapter[Request](Install | Undo | Restart)
ROLLBACK = TypeAdapter[Rollback](Kept | Pending | Trial)
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
