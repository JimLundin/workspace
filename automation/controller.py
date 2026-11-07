"""One executing task, durable controls, and volatile immutable observations.

The process must hold exclusive work ownership before starting this controller.
Each controller is one-shot and receives a fresh owner identity. Recovery is a
startup operation, never a lease sweeper for a peer that might still be alive.
"""

import math
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Protocol

from automation.execution import Log
from automation.store import MAX_PAGE, TaskStore
from cell import Cell
from contracts.task import Blocked, Claim, Outcome, RunRef, Task, Waiting, identifier, integer, owns


class Idle(Enum):
    NEW = auto()
    READY = auto()
    STOPPED = auto()


@dataclass(frozen=True, slots=True)
class Working:
    run: RunRef


@dataclass(frozen=True, slots=True)
class Stopping:
    run: RunRef


@dataclass(frozen=True, slots=True)
class Fault:
    reason: str


type Status = Idle | Working | Stopping | Fault


@dataclass(frozen=True, slots=True)
class ControllerSnapshot:
    status: Status
    tasks: tuple[Task, ...]


class Runner(Protocol):
    """Execute one claim; return only after its native resources are released."""

    def run_work(self, claim: Claim, store: TaskStore, log: Log, stop: threading.Event) -> Outcome: ...


@dataclass(frozen=True, slots=True)
class _Flight:
    claim: Claim
    stop: threading.Event
    result: Future[Outcome]
    thread: threading.Thread


def failure_text(error: BaseException) -> str:
    detail = str(error).replace("\0", "").strip()[:4_000]
    return f"{type(error).__name__}: {detail}" if detail else type(error).__name__


@dataclass(frozen=True, slots=True)
class _Controlled:
    snapshot: ControllerSnapshot = ControllerSnapshot(Idle.NEW, ())
    """The latest published value."""
    started: bool = False
    flight: _Flight | None = None
    """The run executing now."""


@dataclass(frozen=True, slots=True)
class WorkController:
    """Own execution threads while the task store owns durable decisions.

    start() recovers and publishes the initial snapshot synchronously. On
    return the process may report readiness. run() performs the same setup and
    serves on the caller's thread instead.

    Callbacks and log factories must be nonblocking, volatile adapters. The
    controller retains only its latest bounded snapshot, not a queue of model
    messages. GUI/IPC owners choose how to consume or coalesce observations.
    shutdown() requests cancellation promptly; wait() includes all execution
    cleanup and final publication. A caller must retain process ownership until
    wait() succeeds.
    """

    store: TaskStore
    execution: Runner
    owner: str = field(kw_only=True)
    log: Callable[[Claim], Log] = field(kw_only=True)
    now: Callable[[], float] = field(kw_only=True)
    new_run_id: Callable[[], str] = field(kw_only=True)
    on_change: Callable[[ControllerSnapshot], None] = field(kw_only=True)
    on_error: Callable[[str], None] = field(kw_only=True)
    poll_seconds: float = field(default=0.1, kw_only=True)
    limit: int = field(default=100, kw_only=True)
    _controlled: Cell[_Controlled] = field(default_factory=lambda: Cell(_Controlled()), init=False, repr=False)
    """Replaced whole under the lock."""
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _shutdown: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _wake: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _finished: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    """Set once a started controller has finished its cleanup and final publication."""

    def __post_init__(self) -> None:
        identifier(self.owner, "worker owner")
        integer(self.limit, "task snapshot limit", minimum=1, maximum=MAX_PAGE)
        if isinstance(self.poll_seconds, bool) or not math.isfinite(self.poll_seconds) or not 0 < self.poll_seconds <= 1:
            raise ValueError("Work polling must be between zero and one second.")

    def _flight(self) -> _Flight | None:
        return self._controlled.get().flight

    def _fly(self, flight: _Flight | None) -> None:
        """Record the run in flight; callers hold the lock."""
        self._controlled.update(lambda controlled: replace(controlled, flight=flight))

    def snapshot(self) -> ControllerSnapshot:
        """Read the latest published value without doing storage work."""
        with self._lock:
            return self._controlled.get().snapshot

    def start(self) -> None:
        """Recover under the caller's exclusive ownership, then serve in a thread."""
        self._prepare()
        try:
            threading.Thread(target=self._serve, name="work controller", daemon=True).start()
        except BaseException as error:
            self._close(error)
            raise

    def run(self) -> None:
        """Blocking alternative to start(), with the same ownership precondition."""
        self._prepare()
        self._serve()

    def wake(self) -> None:
        """Notify the controller after submissions, answers, or durable controls."""
        self._wake.set()

    def shutdown(self) -> None:
        """Park unfinished work; never turn application shutdown into cancellation."""
        self._shutdown.set()
        with self._lock:
            if (flight := self._flight()) is not None:
                flight.stop.set()
        self._wake.set()

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for this controller's execution cleanup and final callbacks."""
        with self._lock:
            started = self._controlled.get().started
        return self._finished.wait(timeout) if started else True

    def _prepare(self) -> None:
        with self._lock:
            if self._controlled.get().started:
                raise RuntimeError("A work controller can only be started once.")
            self._controlled.update(lambda controlled: replace(controlled, started=True))
        try:
            self.store.recover(self.owner, at=self.now())
            self._publish(Idle.READY)
        except BaseException as error:
            self._close(error)
            raise

    def _publish(self, status: Status) -> None:
        snapshot = ControllerSnapshot(status, self.store.list_tasks(limit=self.limit))
        with self._lock:
            if snapshot == self._controlled.get().snapshot:
                return
            self._controlled.update(lambda controlled: replace(controlled, snapshot=snapshot))
        self.on_change(snapshot)

    def _serve(self) -> None:
        error: BaseException | None = None
        try:
            while True:
                self._wake.clear()
                flight = self._flight()
                if flight is not None and flight.result.done():
                    self._settle(flight)
                    flight = None
                if self._shutdown.is_set():
                    break
                if flight is None:
                    claim = self.store.claim(self.owner, self.new_run_id(), at=self.now())
                    if claim is not None:
                        self._dispatch(claim)
                    else:
                        self._publish(Idle.READY)
                else:
                    task = self.store.get(flight.claim.task.id)
                    if task is None or not owns(task, flight.claim.run):
                        flight.stop.set()
                    self._publish(Stopping(flight.claim.run) if flight.stop.is_set() else Working(flight.claim.run))
                self._wake.wait(self.poll_seconds)
        except BaseException as caught:
            error = caught
            if not isinstance(caught, Exception):
                raise
        finally:
            self._close(error)

    def _dispatch(self, claim: Claim) -> None:
        stop = threading.Event()
        result: Future[Outcome] = Future()
        thread = threading.Thread(target=self._execute, args=(claim, stop, result), name="work execution", daemon=True)
        flight = _Flight(claim, stop, result, thread)
        with self._lock:
            if self._shutdown.is_set():
                stop.set()
            self._fly(flight)
        try:
            thread.start()
        except BaseException:
            with self._lock:
                self._fly(None)
            self.store.interrupt(claim.run, "Execution could not start.", at=self.now())
            raise
        self._publish(Stopping(claim.run) if stop.is_set() else Working(claim.run))

    def _execute(self, claim: Claim, stop: threading.Event, result: Future[Outcome]) -> None:
        try:
            # A run stopped before execution waits for a defined resume, rather than spinning.
            stopping = Waiting(Blocked("Workspace is stopping."))
            if stop.is_set():
                outcome: Outcome = stopping
            else:
                log = self.log(claim)
                outcome = stopping if stop.is_set() else self.execution.run_work(claim, self.store, log, stop)
            result.set_result(outcome)
        except BaseException as error:
            result.set_exception(error)
        finally:
            self._wake.set()

    def _settle(self, flight: _Flight) -> None:
        # Future completion means the execution adapter returned, while joining
        # also finishes the target's final notification before another claim.
        flight.thread.join()
        try:
            outcome = flight.result.result()
        except BaseException as error:
            self._report(failure_text(error))
            outcome = Waiting(Blocked("Execution failed. Inspect the task and resume when its blocker is resolved."))
        if self._shutdown.is_set():
            self.store.interrupt(flight.claim.run, "Workspace stopped before the task outcome was saved.", at=self.now())
        else:
            saved = self.store.finish(flight.claim.run, outcome, at=self.now())
            if saved is None:
                latest = self.store.get(flight.claim.task.id)
                if latest is not None and owns(latest, flight.claim.run):
                    raise RuntimeError("The task outcome was refused; execution has been stopped without claiming more work.")
        with self._lock:
            self._fly(None)
        self._publish(Idle.READY)

    def _report(self, reason: str) -> None:
        try:
            self.on_error(reason)
        except BaseException:
            # A broken error adapter must not hide the controller's Fault
            # snapshot or skip its execution cleanup.
            traceback.print_exc()

    def _close(self, error: BaseException | None) -> None:
        self._shutdown.set()
        reasons = [failure_text(error)] if error is not None else []
        flight = self._flight()
        try:
            if flight is not None:
                flight.stop.set()
                try:
                    self.store.interrupt(
                        flight.claim.run,
                        "The work controller stopped after an error." if reasons else "Workspace stopped before the task finished.",
                        at=self.now(),
                    )
                    self._publish(Stopping(flight.claim.run))
                except BaseException as parking_error:
                    reasons.append(failure_text(parking_error))
                finally:
                    flight.thread.join()
                    with self._lock:
                        self._fly(None)
            status: Status = Fault("\n".join(reasons)) if reasons else Idle.STOPPED
            try:
                self._publish(status)
            except BaseException as publication_error:
                reasons.append(failure_text(publication_error))
                fault = Fault("\n".join(reasons))
                with self._lock:
                    self._controlled.update(lambda controlled: replace(controlled, snapshot=ControllerSnapshot(fault, controlled.snapshot.tasks)))
            if reasons:
                self._report("\n".join(reasons))
        finally:
            self._finished.set()
