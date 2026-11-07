"""Durable work runs on the assistant's threads, never on its UI thread.

The worker holds the work folder's exclusive lease for the assistant's lifetime.
Starting it recovers every task a previous assistant left running from SQLite
before the assistant reports readiness. Execution reaches the assistant's
desktop and meeting owners through direct calls on its own thread.
"""

import contextlib
import importlib
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Final, assert_never

import usage
from automation.activity import ContextSnapshot
from automation.context import ContextStore, select_context
from automation.controller import ControllerSnapshot, Fault, Idle, Runner, Stopping, WorkController, Working
from automation.execution import Log
from automation.profile_lease import ProfileLease
from automation.store import TaskStore
from automation.work_folder import BROWSER_PROFILE
from cell import Cell
from contracts.presentation import LiveMessage, PresentationEvent, Problem, Progress, Said
from contracts.task import Claim, Outcome, RunRef, Task, owns
lazy from assistant.agent_execution import AgentExecution
lazy from assistant.browser import Browser
lazy from assistant.browser_session import Product
lazy from assistant.llm import Missing, Settings
lazy from assistant.machine import NativeDesktop, WinMachine
lazy from assistant.meeting_tools import MeetingOperation
lazy from assistant.task_profiles import GeneralEffects, Profiles, RequestContext
lazy from assistant.work_bridge_contracts import BRIDGE_RESPONSE, BridgeCommand, BridgeResponse
lazy from automation.self_review import ReviewingRunner

MAX_REGISTRATIONS: Final = 256
RESTARTS: Final = 3
"""Controller faults recovered within `RESTART_WINDOW_S` before the worker stays stopped."""
RESTART_WINDOW_S: Final = 600.0


def report(message: str, *, folder: Path) -> None:
    """Operational diagnostics only; SDK payloads never enter this log."""
    with contextlib.suppress(OSError):
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "worker.log").open("a", encoding="utf-8") as file:
            file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


@dataclass(frozen=True, slots=True)
class CallOwner:
    """The execution thread owns this run binding and cancellation handle."""

    run: RunRef
    stop: threading.Event


@dataclass(frozen=True, slots=True)
class OwnerCalls:
    """Execution binds its run; each call rechecks that the run still owns its task.

    The single execution thread sets and clears the binding around a run.
    """

    tasks: TaskStore
    desktop_owner: Callable[[BridgeCommand], BridgeResponse]
    meeting_owner: Callable[[MeetingOperation], str]
    _current: Cell[CallOwner | None] = field(default_factory=lambda: Cell[CallOwner | None](None), init=False, repr=False)

    def bind(self, owner: CallOwner | None) -> None:
        """Bind the run whose calls are allowed, or clear the binding."""
        self._current.set(owner)

    def _owned(self) -> None:
        current = self._current.get()
        if current is None:
            raise OSError("No work run owns this owner request.")
        task = self.tasks.get(current.run.task_id)
        if current.stop.is_set() or task is None or not owns(task, current.run):
            raise OSError("This work run no longer owns the owner request.")

    def desktop(self, command: BridgeCommand) -> str:
        self._owned()
        try:
            response = self.desktop_owner(command)
        except ValueError, TypeError:
            raise OSError("The desktop owner rejected an invalid request.") from None
        return BRIDGE_RESPONSE.dump_json(response).decode("utf-8")

    def request(self, operation: MeetingOperation) -> str:
        self._owned()
        return self.meeting_owner(operation)


@dataclass(frozen=True, slots=True)
class LiveLog:
    """A run's live presentation goes straight to the assistant's observer."""

    publish: Callable[[RunRef, PresentationEvent], None]
    run: RunRef

    def step(self, message: str, /) -> None:
        self.publish(self.run, Progress(message))

    def say(self, message: str, /) -> None:
        self.publish(self.run, Said(message, time.time()))

    def updates(self) -> Callable[[LiveMessage], None]:
        return lambda message: self.publish(self.run, message)

    def problem(self, message: str, /) -> None:
        self.publish(self.run, Problem(message, time.time()))

    def done(self, message: str, /) -> None:
        # The journal outcome completes work; the frontend observes it durably.
        pass


@dataclass(frozen=True, slots=True)
class BoundRunner:
    """Bind owner calls to the claimed run for the length of its execution."""

    runner: Runner
    calls: OwnerCalls

    def run_work(self, claim: Claim, store: TaskStore, log: Log, stop: threading.Event) -> Outcome:
        self.calls.bind(CallOwner(claim.run, stop))
        try:
            return self.runner.run_work(claim, store, log, stop)
        finally:
            self.calls.bind(None)


def _no_publication(_run: RunRef, _event: PresentationEvent) -> None:
    pass


def _nothing_to_close() -> None:
    pass


@dataclass(frozen=True, slots=True)
class _Working:
    runner: Runner | None = None
    publish: Callable[[RunRef, PresentationEvent], None] = _no_publication
    close_background: Callable[[], None] = _nothing_to_close
    controller: WorkController | None = None
    registrations: frozendict[str, ContextSnapshot | None] = frozendict()
    """The context each request was made in, until its run reads it; the oldest leave first."""
    faults: tuple[float, ...] = ()
    closing: bool = False


@dataclass(frozen=True, slots=True)
class Worker:
    """Own the work lease, the invocation contexts and one controller at a time.

    A controller fault starts a fresh controller, which recovers interrupted
    tasks exactly as a new assistant would, up to `RESTARTS` times per window.
    """

    tasks: TaskStore
    _lease: ProfileLease
    _working: Cell[_Working] = field(default_factory=lambda: Cell(_Working()), init=False, repr=False)
    """Replaced whole under the lock."""
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _lifecycle: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    """Held while a controller starts or stops, so a fault restart never races shutdown."""

    @classmethod
    def leasing(cls, tasks: TaskStore, folder: Path) -> Worker:
        return cls(tasks, ProfileLease(folder))

    @property
    def folder(self) -> Path:
        return self._lease.folder

    def start(self, runner: Runner, publish: Callable[[RunRef, PresentationEvent], None], close_background: Callable[[], None]) -> None:
        """Take the lease and recover before returning, so readiness follows recovery.

        `publish` receives each run's live updates; `close_background` releases the
        runner's native resources after work is parked.
        """
        with self._lock:
            self._working.update(lambda working: replace(working, runner=runner, publish=publish, close_background=close_background))
        with self._lifecycle:
            try:
                self._lease.__enter__()
                self._start_controller(runner)
            except BaseException:
                with self._lock:
                    self._working.update(lambda working: replace(working, closing=True))
                self._release()
                raise

    def _launch(self) -> None:
        with self._lifecycle:
            working = self._working.get()
            if working.runner is None or working.closing:
                return
            self._start_controller(working.runner)

    def _start_controller(self, runner: Runner) -> None:
        controller = WorkController(
            self.tasks,
            runner,
            owner=uuid.uuid4().hex,
            log=lambda claim: LiveLog(self._working.get().publish, claim.run),
            now=time.time,
            new_run_id=lambda: uuid.uuid4().hex,
            on_change=self._changed,
            on_error=self._problem,
        )
        with self._lock:
            self._working.update(lambda working: replace(working, controller=controller))
        controller.start()

    def _problem(self, reason: str) -> None:
        # Caller details may include exception payloads; keep only the exception type.
        name = reason.partition(":")[0].strip()
        kind = name[:80] if name.isidentifier() else "unknown"
        report(f"The work controller reported an error ({kind}).", folder=self.folder)

    def _changed(self, snapshot: ControllerSnapshot) -> None:
        match snapshot.status:
            case Fault():
                threading.Thread(target=self._restart, name="work controller restart", daemon=True).start()
            case Idle() | Working() | Stopping():
                pass
            case _:
                assert_never(snapshot.status)

    def _restart(self) -> None:
        with self._lock:
            now = time.monotonic()
            working = self._working.update(
                lambda working: replace(working, faults=(*(at for at in working.faults if now - at < RESTART_WINDOW_S), now))
            )
            controller = working.controller
            if working.closing or controller is None:
                return
            if len(working.faults) > RESTARTS:
                report("The work controller keeps failing; work stays saved until Workspace restarts.", folder=self.folder)
                return
        controller.wait()
        report("Restarting the work controller to recover saved work.", folder=self.folder)
        self._launch()

    def register(self, task_id: str, context: ContextSnapshot | None) -> None:
        """Keep the context a request was made in until its run reads it."""
        with self._lock:
            self._working.update(lambda working: replace(working, registrations=_registered(working.registrations, task_id, context)))

    def invocation(self, task_id: str) -> ContextSnapshot | None:
        with self._lock:
            return self._working.get().registrations.get(task_id)

    def wake(self) -> None:
        with self._lock:
            controller = self._working.get().controller
        if controller is not None:
            controller.wake()

    def close(self) -> None:
        """Park running work and release its resources before the lease."""
        with self._lifecycle:
            with self._lock:
                controller = self._working.update(lambda working: replace(working, closing=True)).controller
            try:
                if controller is not None:
                    controller.shutdown()
                    controller.wait()
            finally:
                self._release()

    def _release(self) -> None:
        try:
            self._working.get().close_background()
        finally:
            self._lease.close()


def _registered(
    registrations: frozendict[str, ContextSnapshot | None], task_id: str, context: ContextSnapshot | None
) -> frozendict[str, ContextSnapshot | None]:
    """`registrations` with `task_id`'s context, keeping the newest `MAX_REGISTRATIONS`."""
    entries = (*((key, value) for key, value in registrations.items() if key != task_id), (task_id, context))
    return frozendict(entries[-MAX_REGISTRATIONS:])


def native_runner(  # noqa: PLR0913 - the execution's independent owners
    settings: Settings | Missing,
    worker: Worker,
    calls: OwnerCalls,
    *,
    hwnd: int,
    contexts: ContextStore,
    context: Callable[[], ContextSnapshot],
) -> tuple[Runner, Callable[[], None]]:
    """The agent execution over the assistant's owners; the second value closes its browser."""
    browser = Browser.at(BROWSER_PROFILE, source=Product.EDGE)
    machine = WinMachine(NativeDesktop(hwnd), meetings=calls, browser=browser)

    def request(task: Task) -> RequestContext:
        saved = select_context(contexts.list(), task.prompt[:20_000], time.time()).describe()
        return RequestContext(worker.invocation(task.id), saved, context)

    usable = settings if isinstance(settings, Settings) else Settings("", "", "", "")
    try:
        execution = AgentExecution(
            usable,
            machine,
            Profiles.of(GeneralEffects(request, calls.desktop, contexts)),
            record=lambda details: usage.record("automation", "agent", details),
            report_error=lambda detail: report(detail, folder=worker.folder),
            close_background=machine.close_background,
        )
    except BaseException:
        machine.close_background()
        raise
    return ReviewingRunner(BoundRunner(execution, calls), datetime.now), machine.close_background


def warm_sdk(folder: Path) -> None:
    try:
        importlib.import_module("assistant.sdk")
    except Exception:
        report("The agent SDK could not be warmed; the next task will report its configuration state.", folder=folder)
