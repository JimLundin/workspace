"""Cancellable effect ownership and a durable record before every consequential call."""

import contextlib
import hashlib
import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Protocol

from pydantic import ConfigDict, TypeAdapter

from automation.files import filesystem_path
from automation.json_value import Json
from automation.task import (
    Action,
    ActionNotApplied,
    ActionOutcome,
    ActionReturned,
    ActionSpec,
    ActionUncertain,
    ActionVerified,
    FileDigest,
    RunRef,
    Task,
    Verification,
    owns,
)

MAX_VERIFICATION_BYTES = 64 * 1024 * 1024
_ARGUMENTS = TypeAdapter(dict[str, Json], config=ConfigDict(allow_inf_nan=False))


class ActionError(Exception):
    """The effect cannot proceed or its outcome cannot be established."""


class ActionCancelledError(ActionError):
    pass


class LostRunError(ActionError):
    pass


class UncertainEffectError(ActionError):
    pass


class ActionJournal(Protocol):
    def get(self, task_id: str, /) -> Task | None: ...
    def begin_action(self, run: RunRef, action_id: str, specification: ActionSpec, *, at: float) -> Action | None: ...
    def finish_action(self, action_id: str, outcome: ActionOutcome, *, at: float) -> Action | None: ...
    def actions(self, task_id: str, *, limit: int = 100) -> tuple[Action, ...]: ...
    def unresolved_actions(self, task_id: str) -> tuple[Action, ...]: ...
    def unverified_actions(self, task_id: str) -> tuple[Action, ...]: ...
    def action_since(self, task_id: str, fingerprint: str, *, after: float) -> bool: ...


@dataclass(frozen=True, slots=True)
class Operation:
    """One exact tool operation: an approval reviews it and its effect records it.

    Tools describe the operation they will perform, including targets they
    resolved, so a grant can never cover arguments other than those executed.
    """

    tool: str
    payload: bytes

    @classmethod
    def of(cls, tool: str, arguments: Mapping[str, Json]) -> Operation:
        return cls(tool, _ARGUMENTS.dump_json(dict(arguments)))

    @property
    def arguments(self) -> dict[str, Json]:
        return _ARGUMENTS.validate_json(self.payload)

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.tool, self.arguments)


class Evidence(Enum):
    """What a successful inspection can prove about an earlier action."""

    NONE = auto()
    """Not an inspection of external state: waiting, questions, the action ledger."""
    GENERAL = auto()
    """A status or listing too general to establish an arbitrary script's result."""
    TARGETED = auto()


@dataclass(frozen=True, slots=True)
class Observation:
    resources: tuple[str, ...]
    evidence: Evidence = Evidence.TARGETED


@dataclass(frozen=True, slots=True)
class Change:
    resources: tuple[str, ...]

    def specification(self, operation: Operation, verification: Verification) -> ActionSpec:
        return ActionSpec(operation.tool, operation.tool.replace("_", " "), operation.fingerprint, self.resources, verification)


type Classification = Observation | Change
"""A tool family's decision for one operation; unknown effects are never inferred."""
type Plan = Observation | ActionSpec


def fingerprint(tool: str, arguments: Mapping[str, object]) -> str:
    """Bind a review or record to the exact operation without retaining its arguments."""
    values: dict[str, object] = dict(arguments)
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256((tool + "\0" + encoded).encode("utf-8")).hexdigest()


def target(kind: str, value: object) -> str:
    """Keep target identity for recovery without storing integration content."""
    return "target:" + kind + ":" + fingerprint(kind, {"value": value})


class Resources:
    """One process owns its effects; waiting for that owner is cancellable.

    The first runtime executes one task at a time. A shared gate also prevents
    separate execution adapters from interleaving foreground and clipboard
    operations. Resource names are retained for a later independent-work policy.
    """

    __slots__ = ("_gate",)

    def __init__(self) -> None:
        self._gate = threading.Lock()

    @contextlib.contextmanager
    def hold(self, selected: tuple[str, ...], cancel: threading.Event) -> Generator[None]:
        if cancel.is_set():
            raise ActionCancelledError("Stopped before acquiring execution resources.")
        if not selected:
            yield
            return
        while not self._gate.acquire(timeout=0.05):
            if cancel.is_set():
                raise ActionCancelledError("Stopped while waiting for execution resources.")
        try:
            if cancel.is_set():
                raise ActionCancelledError("Stopped before using execution resources.")
            yield
        finally:
            self._gate.release()


class FileVerifier:
    """Inspect bounded file contents without retaining the contents themselves."""

    __slots__ = ("maximum",)

    def __init__(self, maximum: int = MAX_VERIFICATION_BYTES) -> None:
        if maximum < 0:
            raise ValueError("The verification bound cannot be negative.")
        self.maximum = maximum

    def verify(self, expected: FileDigest) -> ActionVerified | ActionUncertain:
        try:
            digest = hashlib.sha256()
            size = 0
            with filesystem_path(Path(expected.path)).open("rb") as source:
                while chunk := source.read(min(65_536, self.maximum - size + 1)):
                    size += len(chunk)
                    if size > self.maximum:
                        return ActionUncertain("The file exceeds the bounded verification size.")
                    digest.update(chunk)
            if digest.hexdigest() == expected.sha256:
                return ActionVerified(f"File content matches SHA-256 {expected.sha256}.")
            return ActionUncertain("The file does not match the intended content; inspect it before another write.")
        except OSError:
            return ActionUncertain("The intended file could not be inspected; its previous write remains uncertain.")


class Actions:
    __slots__ = ("clock", "identity", "journal", "resources", "run", "verifier")

    def __init__(
        self,
        journal: ActionJournal,
        run: RunRef,
        resources: Resources,
        *,
        clock: Callable[[], float] = time.time,
        identity: Callable[[], str] = lambda: uuid.uuid4().hex,
        verifier: FileVerifier | None = None,
    ) -> None:
        self.journal, self.run, self.resources = journal, run, resources
        self.clock, self.identity = clock, identity
        self.verifier = verifier if verifier is not None else FileVerifier()

    def unresolved(self) -> tuple[Action, ...]:
        return self.journal.unresolved_actions(self.run.task_id)

    def reconcile(self, cancel: threading.Event) -> tuple[Action, ...]:
        """A successful readback can resolve a lost file-write acknowledgement."""
        with self.resources.hold(("filesystem",), cancel):
            for action in self.unresolved():
                if isinstance(action.specification.verification, FileDigest):
                    outcome = self.verifier.verify(action.specification.verification)
                    if isinstance(outcome, ActionVerified):
                        self.journal.finish_action(action.id, outcome, at=self.clock())
        return self.unresolved()

    def execute[T](
        self,
        specification: Plan,
        perform: Callable[[], T],
        succeeded: Callable[[T], bool],
        cancel: threading.Event,
        *,
        verify: Callable[[T], ActionVerified | ActionUncertain | ActionNotApplied] | None = None,
    ) -> T:
        with self.resources.hold(specification.resources, cancel):
            if isinstance(specification, Observation):
                if cancel.is_set():
                    raise ActionCancelledError("Stopped before inspection.")
                return perform()
            if self.unresolved():
                raise UncertainEffectError("An earlier action has an uncertain outcome. Inspect and reconcile it before making another change.")
            action = self.journal.begin_action(self.run, self.identity(), specification, at=self.clock())
            if action is None:
                raise LostRunError("This execution no longer owns the task.")
            task = self.journal.get(self.run.task_id)
            if cancel.is_set() or task is None or not owns(task, self.run):
                self.journal.finish_action(action.id, ActionNotApplied("The task stopped before the effect began."), at=self.clock())
                raise ActionCancelledError("Stopped before the effect began.")
            try:
                result = perform()
            except BaseException:
                # Losing the result record cannot turn an uncertain operation
                # into a retry. Its durable pending record remains sufficient.
                with contextlib.suppress(OSError, sqlite3.Error):
                    self.journal.finish_action(
                        action.id,
                        ActionUncertain("The effect did not return a conclusive result."),
                        at=self.clock(),
                    )
                raise
            outcome: ActionOutcome
            if verify is not None:
                outcome = verify(result)
            elif not succeeded(result):
                outcome = ActionUncertain("The effect did not return a successful result; it may have partially completed.")
            elif isinstance(specification.verification, FileDigest):
                outcome = self.verifier.verify(specification.verification)
            else:
                outcome = ActionReturned(f"{specification.tool} returned successfully; verify the requested outcome from fresh state.")
            if self.journal.finish_action(action.id, outcome, at=self.clock()) is None:
                raise UncertainEffectError("The effect returned but its outcome could not be committed. Inspect it before another change.")
            # Preserve failed tool output so the model can inspect and reconcile
            # partial effects. Another mutation remains blocked by unresolved().
            return result
