"""Durable work runs on the assistant's threads, never on its UI thread.

The worker holds the work folder's exclusive lease for the assistant's lifetime.
Starting it recovers every task a previous assistant left running from SQLite
before the assistant reports readiness. Execution reaches the assistant's
desktop and meeting owners through direct calls on its own thread.
"""

import contextlib
import importlib
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
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
from contracts.presentation import LiveMessage, PresentationEvent, Problem, Progress, Said
from contracts.task import Claim, Outcome, RunRef, Task, owns
lazy from assistant.agent_execution import AgentExecution
lazy from assistant.browser import Browser
lazy from assistant.browser_session import Product
lazy from assistant.llm import Missing, Settings
lazy from assistant.machine import NativeDesktop, WinMachine
lazy from assistant.meeting_tools import MeetingOperation
lazy from assistant.publishing import DEFAULT_REMOTE, Landing
lazy from assistant.task_profiles import GeneralEffects, Profiles, RequestContext
lazy from assistant.work_bridge_contracts import BRIDGE_RESPONSE, BridgeCommand, BridgeResponse
lazy from assistant.workspace import Workspace
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


class OwnerCalls:
    """Execution binds its run; each call rechecks that the run still owns its task.

    The single execution thread sets and clears the binding around a run.
    """

    __slots__ = ("current", "desktop_owner", "meeting_owner", "tasks")

    def __init__(
        self,
        tasks: TaskStore,
        desktop: Callable[[BridgeCommand], BridgeResponse],
        meeting: Callable[[MeetingOperation], str],
    ) -> None:
        self.tasks, self.desktop_owner, self.meeting_owner = tasks, desktop, meeting
        self.current: CallOwner | None = None

    def _owned(self) -> None:
        current = self.current
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


class LiveLog:
    """A run's live presentation goes straight to the assistant's observer."""

    __slots__ = ("publish", "run")

    def __init__(self, publish: Callable[[RunRef, PresentationEvent], None], run: RunRef) -> None:
        self.publish, self.run = publish, run

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


class BoundRunner:
    """Bind owner calls to the claimed run for the length of its execution."""

    __slots__ = ("calls", "runner")

    def __init__(self, runner: Runner, calls: OwnerCalls) -> None:
        self.runner, self.calls = runner, calls

    def run_work(self, claim: Claim, store: TaskStore, log: Log, stop: threading.Event) -> Outcome:
        self.calls.current = CallOwner(claim.run, stop)
        try:
            return self.runner.run_work(claim, store, log, stop)
        finally:
            self.calls.current = None


class Worker:
    """Own the work lease, the invocation contexts and one controller at a time.

    A controller fault starts a fresh controller, which recovers interrupted
    tasks exactly as a new assistant would, up to `RESTARTS` times per window.
    """

    __slots__ = (
        "_close_background",
        "_closing",
        "_controller",
        "_faults",
        "_lease",
        "_lifecycle",
        "_lock",
        "_registrations",
        "folder",
        "publish",
        "runner",
        "tasks",
    )

    def __init__(self, tasks: TaskStore, folder: Path) -> None:
        self.tasks, self.folder = tasks, folder
        self.publish: Callable[[RunRef, PresentationEvent], None] = lambda _run, _event: None
        self.runner: Runner | None = None
        self._close_background: Callable[[], None] = lambda: None
        self._lease = ProfileLease(folder)
        self._lock = threading.Lock()
        self._lifecycle = threading.Lock()
        """Held while a controller starts or stops, so a fault restart never races shutdown."""
        self._controller: WorkController | None = None
        self._registrations: dict[str, ContextSnapshot | None] = {}
        self._faults: tuple[float, ...] = ()
        self._closing = False

    def start(self, runner: Runner, publish: Callable[[RunRef, PresentationEvent], None], close_background: Callable[[], None]) -> None:
        """Take the lease and recover before returning, so readiness follows recovery.

        `publish` receives each run's live updates; `close_background` releases the
        runner's native resources after work is parked.
        """
        self.runner, self.publish, self._close_background = runner, publish, close_background
        with self._lifecycle:
            try:
                self._lease.__enter__()
                self._start_controller(runner)
            except BaseException:
                with self._lock:
                    self._closing = True
                self._release()
                raise

    def _launch(self) -> None:
        with self._lifecycle:
            if self.runner is None or self._closing:
                return
            self._start_controller(self.runner)

    def _start_controller(self, runner: Runner) -> None:
        controller = WorkController(
            self.tasks,
            runner,
            owner=uuid.uuid4().hex,
            log=lambda claim: LiveLog(self.publish, claim.run),
            now=time.time,
            new_run_id=lambda: uuid.uuid4().hex,
            on_change=self._changed,
            on_error=self._problem,
        )
        with self._lock:
            self._controller = controller
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
            controller = self._controller
            now = time.monotonic()
            self._faults = (*(at for at in self._faults if now - at < RESTART_WINDOW_S), now)
            if self._closing or controller is None:
                return
            if len(self._faults) > RESTARTS:
                report("The work controller keeps failing; work stays saved until Workspace restarts.", folder=self.folder)
                return
        controller.wait()
        report("Restarting the work controller to recover saved work.", folder=self.folder)
        self._launch()

    def register(self, task_id: str, context: ContextSnapshot | None) -> None:
        """Keep the context a request was made in until its run reads it."""
        with self._lock:
            self._registrations[task_id] = context
            while len(self._registrations) > MAX_REGISTRATIONS:
                del self._registrations[next(iter(self._registrations))]

    def invocation(self, task_id: str) -> ContextSnapshot | None:
        with self._lock:
            return self._registrations.get(task_id)

    def wake(self) -> None:
        with self._lock:
            controller = self._controller
        if controller is not None:
            controller.wake()

    def close(self) -> None:
        """Park running work and release its resources before the lease."""
        with self._lifecycle:
            with self._lock:
                self._closing = True
                controller = self._controller
            try:
                if controller is not None:
                    controller.shutdown()
                    controller.wait()
            finally:
                self._release()

    def _release(self) -> None:
        try:
            self._close_background()
        finally:
            self._lease.close()


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
    browser = Browser(BROWSER_PROFILE, source=Product.EDGE)
    machine = WinMachine(NativeDesktop(hwnd), meetings=calls, browser=browser)

    def request(task: Task) -> RequestContext:
        saved = select_context(contexts.list(), task.prompt[:20_000], time.time()).describe()
        return RequestContext(worker.invocation(task.id), saved, context)

    usable = settings if isinstance(settings, Settings) else Settings("", "", "", "")
    landing = Landing(os.environ.get("WORKSPACE_GIT_REMOTE", DEFAULT_REMOTE), os.environ.get("WORKSPACE_GIT_BASE", "main"))
    try:
        execution = AgentExecution(
            usable,
            machine,
            Profiles(
                Workspace(standards=True),
                GeneralEffects(request, calls.desktop, contexts, landing),
            ),
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
