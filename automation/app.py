"""The supervised Windows work process owns execution, never UI or audio.

The profile lease outlives the controller and all of its native cleanup. The
hidden window is created and destroyed on this process's main thread; WM_CLOSE
parks active work and drains its effects before returning to the keeper.
"""

import contextlib
import importlib
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

import keeper
import usage
from keeper import AUTOMATION_WINDOW
from usage import DIRECTORY
from winapi import screen, system, windows
from winapi.shapes import Window
lazy from assistant.activity import ContextSnapshot, Observation, Sample, observed
lazy from assistant.agent_execution import AgentExecution
lazy from assistant.agent_session import Begin, Done, Finished, LiveMessage, Problem, Progress, Said
lazy from assistant.browser import Browser
lazy from assistant.browser_session import Product
lazy from assistant.llm import Missing, Settings
lazy from assistant.machine import NativeDesktop, WinMachine
lazy from assistant.meeting_execution import MeetingWork
lazy from assistant.meeting_followup_store import FollowupStore
lazy from assistant.meeting_requests import MeetingRequests
lazy from assistant.outlook import OutlookDrafts
lazy from assistant.recording_state import AudioSource
lazy from automation import ipc
lazy from automation.bridge import BridgeServer, ProfileLease
lazy from automation.context import ContextStore, select_context
lazy from automation.controller import ControllerSnapshot, Fault, Idle, Stopping, WorkController, WorkExecution, Working
lazy from automation.execution import ApprovalReview, Log, Outcome
lazy from automation.routines import RoutineStore
lazy from automation.store import TaskStore
lazy from automation.task import Claim, RunRef, owns


def report(message: str, *, folder: Path = DIRECTORY / "work") -> None:
    """Operational diagnostics only; SDK and IPC payloads never enter this log."""
    with contextlib.suppress(OSError):
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "worker.log").open("a", encoding="utf-8") as file:
            file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


@dataclass(frozen=True, slots=True)
class MeetingRun:
    run: RunRef
    stop: threading.Event


class RemoteMeetings:
    """The execution thread delegates capture to its assistant-owned meeting service."""

    __slots__ = ("bridge", "current")

    def __init__(self, bridge: BridgeServer) -> None:
        self.bridge = bridge
        self.current: MeetingRun | None = None

    def request(self, operation: ipc.MeetingOperation) -> str:
        if self.current is None:
            raise OSError("No work run owns this meeting request.")
        return self.bridge.meeting(self.current.run, operation, self.current.stop)

    def start(self, source: AudioSource = "both", title: str = "Meeting") -> None:
        self.request(ipc.StartMeeting(source, title))

    def stop(self) -> None:
        self.request(ipc.MeetingCommand.STOP)

    def retry(self) -> None:
        self.request(ipc.MeetingCommand.RETRY)

    def recent(self) -> str:
        return self.request(ipc.MeetingCommand.LIST)

    def describe(self) -> str:
        return self.request(ipc.MeetingCommand.STATUS)


class DesktopContext:
    """Fresh foreground observations exclude both Workspace process owners."""

    __slots__ = ("bridge", "enabled")

    def __init__(self, bridge: BridgeServer, *, enabled: bool) -> None:
        self.bridge, self.enabled = bridge, enabled

    def snapshot(self) -> ContextSnapshot:
        now = time.time()
        if not self.enabled:
            return ContextSnapshot(now, "disabled")
        observation: Observation = "unavailable"
        try:
            handle = windows.foreground()
            if handle:
                observation = (
                    "workspace"
                    if windows.process_id(handle) in (os.getpid(), self.bridge.assistant_pid)
                    else Window(handle, windows.title(handle), windows.exe(handle), minimized=windows.is_minimized(handle))
                )
        except OSError:
            pass
        return observed(self.bridge.context(), Sample(observation, now, agent_active=True))


class VolatileLog:
    __slots__ = ("bridge", "run")

    def __init__(self, bridge: BridgeServer, run: RunRef) -> None:
        self.bridge, self.run = bridge, run

    def publish(self, event: ipc.PresentationEvent) -> None:
        try:
            self.bridge.publish(ipc.LogEvent(self.run, event))
        except ValueError:
            self.bridge.publish(ipc.Resync("A live update exceeded the transport bound; reload the durable work result."))

    def step(self, message: str, /) -> None:
        self.publish(Progress(message))

    def say(self, message: str, /) -> None:
        self.publish(Said(message, time.time()))

    def updates(self) -> Callable[[LiveMessage], None]:
        return self.publish

    def problem(self, message: str, /) -> None:
        self.publish(Problem(message, time.time()))

    def done(self, message: str, /) -> None:
        self.publish(Done(message, time.time()))


class NativeExecution:
    __slots__ = ("bridge", "contexts", "execution", "meetings")

    def __init__(
        self,
        execution: AgentExecution,
        bridge: BridgeServer,
        meetings: RemoteMeetings,
        contexts: ContextStore,
    ) -> None:
        self.execution, self.bridge, self.meetings, self.contexts = execution, bridge, meetings, contexts

    def run_work(self, claim: Claim, store: TaskStore, log: Log, stop: threading.Event) -> Outcome:
        self.meetings.current = MeetingRun(claim.run, stop)

        def review(preview: ApprovalReview) -> bool:
            try:
                return self.bridge.publish(ipc.ReviewEvent(claim.run, preview))
            except ValueError:
                return False

        try:
            context = self.bridge.invocation(claim.task.id)
            saved = select_context(self.contexts.list(), claim.task.prompt[:20_000], time.time()).describe()
            return self.execution.run_work(claim, store, log, stop, context=context, context_text=saved, review=review)
        finally:
            self.meetings.current = None


def _native_execution(settings: Settings | Missing, bridge: BridgeServer, hwnd: int, contexts: ContextStore) -> tuple[NativeExecution, WinMachine]:
    meetings = RemoteMeetings(bridge)
    browser = Browser(DIRECTORY / "browser-profile", source=Product.EDGE)
    machine = WinMachine(NativeDesktop(hwnd), meetings=meetings, browser=browser)
    context = DesktopContext(bridge, enabled=os.environ.get("WORKSPACE_AGENT_CONTEXT", "recent").lower() != "off")
    usable = settings if isinstance(settings, Settings) else Settings("", "", "", "", "", "", "")
    followups = bridge.folder / "meeting-followups"
    try:
        execution = AgentExecution(
            usable,
            machine,
            record=lambda details: usage.record("automation", "agent", details),
            report_error=lambda detail: report(detail, folder=bridge.folder),
            close_background=machine.close_background,
            context=context.snapshot,
            meeting=MeetingWork(MeetingRequests(followups), FollowupStore(followups / "packages"), OutlookDrafts(followups / "mail")),
        )
    except BaseException:
        machine.close_background()
        raise
    return NativeExecution(execution, bridge, meetings, contexts), machine


def run(
    settings: Settings | Missing,
    *,
    folder: Path = DIRECTORY / "work",
    execution: WorkExecution | None = None,
    ready: Callable[[], None] = keeper.ready,
    title: str = AUTOMATION_WINDOW,
) -> None:
    """Own one profile until all work is parked and native resources are released.

    The optional execution and readiness adapters are also used by native
    process tests with a real journal, real pipe, and isolated clipboard HWND.
    """
    with ProfileLease(folder), contextlib.ExitStack() as cleanup:
        screen.use_physical_pixels()
        hwnd = windows.create_hidden(title)
        cleanup.callback(windows.destroy, hwnd)
        tasks = TaskStore(folder / "work.sqlite3")
        routines, contexts = RoutineStore(tasks.path), ContextStore(tasks.path)
        routines.ensure_meeting_notes(at=time.time())
        shutdown = threading.Event()
        controller: WorkController

        def run_owns(reference: RunRef) -> bool:
            task = tasks.get(reference.task_id)
            return task is not None and owns(task, reference)

        def wake() -> None:
            controller.wake()

        bridge = BridgeServer(folder, epoch=uuid.uuid4().hex, wake=wake, owns=run_owns)
        cleanup.callback(bridge.close)
        if execution is None:
            execution, machine = _native_execution(settings, bridge, hwnd, contexts)
            cleanup.callback(machine.close_background)
        events = WorkEvents(bridge, folder, hwnd)
        controller = WorkController(
            tasks,
            execution,
            owner=bridge.discovery.epoch,
            log=events.log,
            now=time.time,
            new_run_id=lambda: uuid.uuid4().hex,
            on_change=events.changed,
            on_error=events.problem,
        )

        cleanup.callback(stop_work, controller, bridge)

        bridge.start()
        controller.start()  # Synchronous exclusive-owner recovery precedes readiness.
        worker_options: dict[str, object] = {"problem": events.problem}
        thread = threading.Thread(
            target=maintain_routines,
            args=(bridge, routines, tasks, controller, shutdown),
            kwargs=worker_options,
            name="standing work",
            daemon=True,
        )
        thread.start()
        warmup: threading.Thread | None = None

        try:
            ready()
            if isinstance(settings, Settings) and settings.api_key:
                warmup = threading.Thread(target=warm_sdk, args=(folder,), name="work SDK warmup", daemon=True)
                warmup.start()
            for message in system.messages():
                if message.hwnd == hwnd and message.message == system.WM_CLOSE:
                    break
        finally:
            shutdown.set()
            controller.shutdown()
            thread.join()
            if warmup is not None:
                warmup.join()
        if events.failed.is_set():
            raise OSError("The work process stopped after an operational failure.")


class WorkEvents:
    """The work process owns failure signalling and sequential run observations.

    Previous-run identity changes in this observer so it can publish exactly one
    Finished event when the controller leaves a run. Callers see native/log effects.
    """

    __slots__ = ("bridge", "failed", "folder", "hwnd", "previous")

    def __init__(self, bridge: BridgeServer, folder: Path, hwnd: int) -> None:
        self.bridge, self.folder, self.hwnd = bridge, folder, hwnd
        self.failed = threading.Event()
        self.previous: RunRef | None = None

    def problem(self, reason: str) -> None:
        # Caller details may include exception payloads; retain only an
        # operational marker here and expose durable task state separately.
        self.failed.set()
        report("The work process encountered an error and is stopping for recovery.", folder=self.folder)
        system.post_message(self.hwnd, system.WM_CLOSE, 0, 0)

    def changed(self, snapshot: ControllerSnapshot) -> None:
        active: RunRef | None
        match snapshot.status:
            case Working(reference) | Stopping(reference):
                active = reference
            case Fault():
                active = None
                self.problem("Work controller failed.")
            case Idle():
                active = None
            case _:
                assert_never(snapshot.status)
        if self.previous is not None and active != self.previous:
            self.bridge.publish(ipc.LogEvent(self.previous, Finished()))
        self.previous = active

    def log(self, claim: Claim) -> Log:
        result = VolatileLog(self.bridge, claim.run)
        result.publish(Begin(claim.task.prompt, time.time()))
        return result


def stop_work(controller: WorkController, bridge: BridgeServer) -> None:
    controller.shutdown()
    try:
        bridge.close()
    finally:
        controller.wait()


def warm_sdk(folder: Path) -> None:
    try:
        importlib.import_module("assistant.sdk")
    except Exception:
        report("The agent SDK could not be warmed; the next task will report its configuration state.", folder=folder)


def maintain_routines(
    bridge: BridgeServer,
    routines: RoutineStore,
    tasks: TaskStore,
    controller: WorkController,
    shutdown: threading.Event,
    *,
    problem: Callable[[str], None],
) -> None:
    """Poll this process's transport/store, waking its controller until shutdown.

    These six dependencies bind the worker to the same owned transport, durable
    routine and task stores, controller, shutdown lifetime and native failure dispatcher.
    """
    while not shutdown.is_set():
        try:
            if bridge.wait(0):
                problem("Work transport exited.")
                return
            now = time.time()
            routines.scan_files(now)
            if routines.dispatch(tasks, now=now):
                controller.wake()
        except Exception:
            problem("Routine polling failed.")
            return
        shutdown.wait(1)
