"""The in-process worker over real journals, leases and desktop owners."""

import queue
import threading
import unittest
from pathlib import Path

from assistant.agent_window import AgentWindow
from assistant.feed_contracts import FeedCommand, FeedRejected, SaveRule
from assistant.feed_triage_service import Triage
from assistant.meeting_tools import MeetingCommand, MeetingOperation
from assistant.work_agent import WorkAgent
from assistant.work_bridge import WorkOwners
from assistant.work_bridge_contracts import BridgeCommand, BridgeResponse, FeedResponse
from automation.activity import ContextSnapshot
from automation.context import ContextStore
from automation.execution import Log
from automation.profile_lease import ProfileLease
from automation.store import TaskStore
from automation.work_folder import WorkFolder
from automation.worker import CallOwner, OwnerCalls, Worker
from contracts.presentation import PresentationEvent, Progress
from contracts.task import Claim, Completed, Control, Interrupted, Outcome, RequestSource, Running, RunRef
from contracts.work_snapshot import WorkSnapshot
from tests.feed_fixture import no_canvas, no_personal_work
from tests.test_agent_window import Recording
from tests.test_feed_triage_service import MemoryStore
from tests.test_work_agent import invocation


class ParkedRunner:
    """Hold each claim until shutdown asks it to stop."""

    def __init__(self) -> None:
        self.claims: queue.Queue[Claim] = queue.Queue()

    def run_work(self, claim: Claim, store: TaskStore, log: Log, stop: threading.Event) -> Outcome:
        self.claims.put(claim)
        log.step("Awaiting shutdown.")
        assert stop.wait(10), "The worker did not stop its execution."
        return Completed("Returned while shutting down.", ())


def test_worker_recovers_saved_work_before_start_returns_and_parks_it_on_close(tmp_path: Path) -> None:
    # Defects: readiness before recovery of a previous assistant's run, a second
    # owner of the work folder, or shutdown that loses the running task's checkpoint.
    tasks = TaskStore(tmp_path / "work.sqlite3")
    tasks.submit("notes", "Meeting notes", "Prepare meeting notes.", RequestSource("conversation"), at=1)
    first = tasks.claim("dead-assistant", "abruptly-lost-run", at=2)
    assert first is not None
    tasks.progress(first.run, "Read and checked the transcript.", at=3)
    previous = first.run
    events: queue.Queue[tuple[RunRef, PresentationEvent]] = queue.Queue()
    for _ in range(2):
        released = threading.Event()
        runner = ParkedRunner()
        worker = Worker.leasing(tasks, tmp_path)
        worker.start(runner, lambda run, event: events.put((run, event)), released.set)
        try:
            started = tasks.get("notes")
            assert started is not None and not (isinstance(started.state, Running) and started.state.run == previous)
            claim = runner.claims.get(timeout=5)
            assert isinstance(claim.previous, Interrupted) and claim.previous.run == previous
            assert claim.task.checkpoint is not None and claim.task.checkpoint.summary == "Read and checked the transcript."
            assert events.get(timeout=5) == (claim.run, Progress("Awaiting shutdown."))
            with unittest.TestCase().assertRaises(OSError), ProfileLease(tmp_path):
                raise AssertionError("A second owner acquired the active work folder.")
        finally:
            worker.close()
        assert released.is_set()
        parked = tasks.get("notes")
        assert parked is not None and isinstance(parked.state, Interrupted) and parked.state.run == claim.run
        assert parked.checkpoint is not None and parked.checkpoint.summary == "Read and checked the transcript."
        previous = claim.run


class LinkedOwners:
    """The fixture's feed owner, recording each command it receives."""

    def __init__(self) -> None:
        self.triage = Triage.start(MemoryStore(), lambda _batch, _rules: "")
        self.operations: tuple[FeedCommand, ...] = ()
        self.desktop = WorkOwners(self.feed, no_personal_work, no_canvas)

    def feed(self, command: FeedCommand) -> FeedResponse:
        self.operations = (*self.operations, command)
        return self.triage.command(command)


def no_meetings(_operation: MeetingOperation) -> str:
    raise OSError("Meeting recording is unavailable.")


class LinkedRunner:
    """Once released, say progress, change a desktop owner, then complete."""

    def __init__(self, worker: Worker, calls: OwnerCalls) -> None:
        self.worker, self.calls = worker, calls
        self.contexts: list[ContextSnapshot | None] = []
        self.claimed, self.release = threading.Event(), threading.Event()

    def run_work(self, claim: Claim, store: TaskStore, log: Log, stop: threading.Event) -> Outcome:
        self.contexts.append(self.worker.invocation(claim.task.id))
        self.claimed.set()
        assert self.release.wait(5), "The test did not release live progress."
        log.say("Linked progress.")
        self.calls.bind(CallOwner(claim.run, stop))
        try:
            assert "Keep linked fixture updates quiet." in self.calls.desktop(SaveRule("Keep linked fixture updates quiet."))
        finally:
            self.calls.bind(None)
        return Completed("Linked result.", ())


def test_a_submission_runs_on_the_worker_and_its_output_reaches_the_conversation(tmp_path: Path) -> None:
    # Defects: the worker misses the request's context, live output never reaches
    # the conversation, owner calls skip the desktop owner, or completion needs a live event.
    tasks = TaskStore(WorkFolder(tmp_path).journal)
    panels: list[Recording] = []
    errors: list[str] = []
    completed = threading.Event()
    owners = LinkedOwners()
    agent: WorkAgent

    def window(agent: WorkAgent) -> AgentWindow:
        recording = Recording.of(agent.stop, on_submit=agent.start, on_reset=agent.new_conversation)
        panels.append(recording)
        return recording.window

    def published(snapshot: WorkSnapshot) -> None:
        if any(isinstance(task.state, Completed) for task in snapshot.tasks):
            completed.set()

    worker = Worker.leasing(tasks, tmp_path)
    agent = WorkAgent.open(
        tasks,
        ContextStore(tasks.path),
        worker,
        window,
        on_snapshot=published,
        on_done=lambda: None,
        report_error=errors.append,
        context=lambda: invocation("Linked workbook"),
    )
    calls = OwnerCalls(tasks, owners.desktop.handle, no_meetings)
    runner = LinkedRunner(worker, calls)
    agent.start_worker()
    worker.start(runner, agent.deliver, lambda: None)
    try:
        agent.start("Link check")
        # Live output is volatile: it reaches a conversation that already shows the run.
        assert runner.claimed.wait(5)
        assert agent.refresh().wait(5)
        assert isinstance(agent.snapshot().tasks[0].state, Running)
        runner.release.set()
        assert completed.wait(5), "The frontend did not publish the worker's durable completion."
        (finished,) = agent.snapshot().tasks
        assert finished.state == Completed("Linked result.", ())
        assert runner.contexts == [invocation("Linked workbook")]
        assert owners.triage.board.rules == ("Keep linked fixture updates quiet.",)
        assert agent.refresh().wait(5)
        text = panels[0].window.all_text()
        assert "Linked progress." in text and "Linked result." in text
        assert not errors
    finally:
        worker.close()
        agent.close()
        assert agent.wait_closed(5)
        owners.triage.close()
        for panel in panels:
            panel.paint()


def test_owner_calls_refuse_a_run_that_no_longer_owns_its_task(tmp_path: Path) -> None:
    # Defect: a cancelled run still changes desktop owners or records a meeting.
    tasks = TaskStore(tmp_path / "work.sqlite3")
    tasks.submit("task", "Task", "Task", RequestSource("conversation"), at=1)
    claim = tasks.claim("worker", "run", at=2)
    assert claim is not None
    received: list[BridgeCommand | MeetingOperation] = []

    def desktop(command: BridgeCommand) -> BridgeResponse:
        received.append(command)
        return FeedRejected("This fixture accepts no desktop commands.")

    def meeting(operation: MeetingOperation) -> str:
        received.append(operation)
        return "Recording."

    calls = OwnerCalls(tasks, desktop, meeting)
    calls.bind(CallOwner(claim.run, threading.Event()))
    assert calls.request(MeetingCommand.STATUS) == "Recording."
    assert tasks.control("task", Control.CANCEL, at=3) is not None
    with unittest.TestCase().assertRaisesRegex(OSError, "no longer owns"):
        calls.request(MeetingCommand.STATUS)
    with unittest.TestCase().assertRaisesRegex(OSError, "no longer owns"):
        calls.desktop(SaveRule("A cancelled run's rule."))
    assert received == [MeetingCommand.STATUS]
