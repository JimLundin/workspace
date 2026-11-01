"""Volatile owner identity, queued ownership, shutdown and desktop validation."""

import threading
import time
from dataclasses import replace
from pathlib import Path
from unittest import TestCase

from assistant.owner_calls import OwnerDispatcher, OwnerReply
from assistant.work_agent import WorkAgent
from assistant.work_bridge import WorkOwners, answer
from assistant.work_bridge_contracts import FeedResponse
from assistant.work_snapshot import WorkSnapshot
from automation import ipc
from automation.bridge import BridgeClient, BridgeServer
from automation.context import ContextStore
from automation.routines import RoutineStore
from automation.store import TaskStore
from automation.task import Control, RequestSource, RunRef, owns
from tests.feed_fixture import feed_unavailable, no_canvas, no_personal_work
from tests.test_agent_window import RecordingWindow


def active_task(folder: Path) -> tuple[TaskStore, RunRef]:
    tasks = TaskStore(folder / "work.sqlite3")
    tasks.submit("owner-task", "Owner task", "Inspect desktop work.", RequestSource("owner-chat"), at=1)
    claim = tasks.claim("owner-worker", "owner-run", at=2)
    assert claim is not None
    return tasks, claim.run


def message(run: RunRef, identity: str, call: ipc.OwnerCall) -> ipc.Envelope:
    return ipc.Envelope("owner-worker", 1, ipc.OwnerRequest(run, identity, call))


def received(dispatcher: OwnerDispatcher, wake: threading.Event, count: int) -> tuple[OwnerReply, ...]:
    replies: list[OwnerReply] = []
    deadline = time.monotonic() + 3
    while len(replies) < count:
        replies.extend(dispatcher.ready())
        if len(replies) >= count:
            break
        assert wake.wait(max(0, deadline - time.monotonic())), "The owner did not settle its admitted calls."
        wake.clear()
    return tuple(replies)


def test_inflight_and_completed_redelivery_never_repeat_effects_and_queued_runs_are_rechecked(tmp_path: Path) -> None:
    # Defects: repeating a call before/after reply, unbounded admission, or
    # executing queued work after its task loses the run.
    tasks, run = active_task(tmp_path)
    entered, release, wake = threading.Event(), threading.Event(), threading.Event()
    effects: list[ipc.OwnerCall] = []

    def handle(call: ipc.OwnerCall) -> ipc.OwnerResult:
        effects.append(call)
        entered.set()
        assert release.wait(3)
        return ipc.Succeeded("Committed once.")

    dispatcher = OwnerDispatcher(handle, tasks, wake)
    dispatcher.start()
    first = message(run, "first", ipc.MeetingCommand.STATUS)
    second = message(run, "queued", ipc.MeetingCommand.STOP)
    try:
        assert dispatcher.submit(first) is None and entered.wait(3)
        assert dispatcher.submit(replace(first, sequence=2)) is None
        assert dispatcher.submit(second) is None
        refused = dispatcher.submit(message(run, "overflow", ipc.MeetingCommand.RETRY))
        assert refused is not None and isinstance(refused.result, ipc.Failed) and "busy" in refused.result.reason
        tasks.control(run.task_id, Control.CANCEL, at=3)
        release.set()
        done, stale = received(dispatcher, wake, 2)
        assert done.result == ipc.Succeeded("Committed once.")
        assert isinstance(stale.result, ipc.Failed) and "no longer owns" in stale.result.reason
        repeated = dispatcher.submit(replace(first, sequence=3))
        assert repeated is not None and repeated.result == done.result
        assert effects == [ipc.MeetingCommand.STATUS] and not dispatcher.pending
    finally:
        release.set()
        dispatcher.close()
        assert dispatcher.wait(3)


def test_close_rejects_queued_effects_and_waits_for_the_executing_owner(tmp_path: Path) -> None:
    # Defect: shutting down an owner while its handler runs, or applying queued
    # desktop mutations after close has begun.
    tasks, run = active_task(tmp_path)
    entered, release, wake = threading.Event(), threading.Event(), threading.Event()
    effects: list[ipc.OwnerCall] = []

    def handle(call: ipc.OwnerCall) -> ipc.OwnerResult:
        effects.append(call)
        entered.set()
        assert release.wait(3)
        return ipc.Succeeded("Owner drained.")

    dispatcher = OwnerDispatcher(handle, tasks, wake)
    dispatcher.start()
    try:
        assert dispatcher.submit(message(run, "active", ipc.MeetingCommand.STATUS)) is None and entered.wait(3)
        assert dispatcher.submit(message(run, "queued", ipc.MeetingCommand.STOP)) is None
        dispatcher.close()
        assert not dispatcher.wait(0)
        refused = dispatcher.submit(message(run, "late", ipc.MeetingCommand.RETRY))
        assert refused is not None and isinstance(refused.result, ipc.Failed) and "stopping" in refused.result.reason
        release.set()
        done, stopped = received(dispatcher, wake, 2)
        assert done.result == ipc.Succeeded("Owner drained.")
        assert isinstance(stopped.result, ipc.Failed) and "stopping" in stopped.result.reason
        assert dispatcher.wait(3) and effects == [ipc.MeetingCommand.STATUS]
    finally:
        release.set()
        dispatcher.close()
        assert dispatcher.wait(3)


def test_desktop_boundary_rejects_invalid_commands_and_reports_unavailable_owners() -> None:
    # Defect: passing undecoded external text to an owner, leaking boundary
    # exceptions or routing a meeting operation to a desktop handler.
    meetings: list[ipc.MeetingOperation] = []

    def meeting(call: ipc.MeetingOperation) -> ipc.OwnerResult:
        meetings.append(call)
        return ipc.Succeeded("Recorder answered.")

    def unavailable(_command: object) -> FeedResponse:
        raise OSError("Private owner failure.")

    owners = WorkOwners(feed_unavailable, no_personal_work, no_canvas)
    invalid = answer(ipc.DesktopCall('{"operation":"unknown"}'), owners, meeting)
    assert isinstance(invalid, ipc.Failed) and "invalid" in invalid.reason
    unavailable_result = answer(ipc.DesktopCall('{"operation":"read"}'), WorkOwners(unavailable, no_personal_work, no_canvas), meeting)
    assert isinstance(unavailable_result, ipc.Failed) and "unavailable" in unavailable_result.reason
    assert answer(ipc.MeetingCommand.STATUS, owners, meeting) == ipc.Succeeded("Recorder answered.")
    assert meetings == [ipc.MeetingCommand.STATUS]


def test_owner_payload_limit_counts_utf8_bytes_at_the_wire_boundary() -> None:
    # Defect: a character-count bound permits oversized non-ASCII desktop calls.
    call = ipc.DesktopCall("é" * (ipc.MAX_OWNER_BODY // 2))
    assert ipc.decode_event(ipc.encode_event(message(RunRef("task", "run"), "unicode", call))).payload == ipc.OwnerRequest(
        RunRef("task", "run"), "unicode", call
    )
    with TestCase().assertRaisesRegex(ValueError, "size"):
        ipc.DesktopCall(call.body + "é")
    with TestCase().assertRaisesRegex(ValueError, "size"):
        ipc.DesktopCall("")


def test_real_pipe_redelivery_keeps_the_observer_responsive_and_reports_expired_results(tmp_path: Path) -> None:
    # Defects: the handler blocks frontend observation, real pipe redelivery
    # repeats an in-flight/completed effect, or expired delivery hides uncertainty.
    tasks, run = active_task(tmp_path)
    entered, release, delivered = threading.Event(), threading.Event(), threading.Event()
    effects: list[ipc.OwnerCall] = []
    panels: list[RecordingWindow] = []
    errors: list[str] = []

    def current(reference: RunRef) -> bool:
        task = tasks.get(reference.task_id)
        return task is not None and owns(task, reference)

    def handle(call: ipc.OwnerCall) -> ipc.OwnerResult:
        effects.append(call)
        entered.set()
        assert release.wait(5)
        return ipc.Succeeded("Committed once.")

    def window(agent: WorkAgent) -> RecordingWindow:
        panel = RecordingWindow(agent.stop, on_submit=agent.start, on_reset=agent.new_conversation)
        panels.append(panel)
        return panel

    def published(snapshot: WorkSnapshot) -> None:
        if "expired" in snapshot.status:
            delivered.set()

    server = BridgeServer(tmp_path, epoch="a" * 32, wake=lambda: None, owns=current)
    agent = WorkAgent(
        tasks,
        RoutineStore(tasks.path),
        ContextStore(tasks.path),
        BridgeClient(tmp_path),
        window,
        on_snapshot=published,
        on_done=lambda: None,
        report_error=errors.append,
        owners=handle,
    )
    server.start()
    agent.start_worker()
    request = ipc.OwnerRequest(run, "redelivered", ipc.MeetingCommand.STATUS)
    try:
        assert agent.refresh().wait(3)
        assert server.publish(request) and entered.wait(3)
        assert server.publish(request)
        assert agent.refresh().wait(3), "The observer blocked on its owner handler."
        assert effects == [ipc.MeetingCommand.STATUS]
        release.set()
        assert delivered.wait(3), "An expired owner result was not shown as uncertain."
        assert server.publish(request)
        assert agent.refresh().wait(3)
        assert effects == [ipc.MeetingCommand.STATUS] and not errors
    finally:
        release.set()
        agent.close()
        assert agent.wait_closed(5)
        server.close()
        for panel in panels:
            panel.paint()
