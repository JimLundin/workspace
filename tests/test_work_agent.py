"""Durable conversation behavior through real journals and public UI seams."""

import queue
import threading
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from assistant.agent_session import ChatMessage
from assistant.canvas_activity import CanvasRun, TaskRequest
from assistant.conversation_output import ConversationOutput
from assistant.work_agent import WorkAgent
from assistant.work_canvas import WorkCanvas, run_prompt
from assistant.work_commands import (
    AddPreference,
    AddProjectNote,
    AnswerTask,
    ControlTask,
    CreateRoutine,
    DisableRoutine,
    EnableRoutine,
    FollowUp,
    Redirect,
    RefreshApproval,
    RemoveContext,
    UpdatePreference,
    UpdateProjectNote,
    UpdateRoutine,
)
from assistant.work_snapshot import WorkSnapshot
from automation import ipc
from automation.activity import Activity, ContextSnapshot
from automation.bridge import BridgeClient, BridgeServer
from automation.context import ContextStore, Preference, ProjectNote
from automation.execution import ApprovalReview
from automation.ipc import (
    BridgeEvent,
    Envelope,
    LogEvent,
    MeetingCommand,
    Resync,
    ReviewEvent,
    StartMeeting,
)
from automation.personal_work import Catalog, SourceKind
from automation.presentation import Answer, Said, StreamState, Succeeded, ToolActivity
from automation.routines import Every, Once, RoutineStore
from automation.store import TaskStore
from automation.task import (
    Approval,
    ApprovalDecision,
    Blocked,
    Completed,
    Control,
    Question,
    RequestKind,
    RequestSource,
    Running,
    RunRef,
    SelfReview,
    Task,
    TaskStatus,
    TextAnswer,
    Waiting,
    owns,
)
from desktop_ui.notification_text import prepared_answer
from desktop_ui.notifications import Busy, Settled, Stack, Turn, TurnKey, Working, advance, body
from tests.personal_work_fixture import source
from tests.test_agent_window import RecordingWindow
from winapi.shapes import Window


class Clock:
    def __init__(self) -> None:
        self.value = 100.0
        self.lock = threading.Lock()

    def __call__(self) -> float:
        with self.lock:
            self.value += 1
            return self.value


class RecordingBridge:
    """Only replace the process boundary; SQLite and session transitions are real."""

    def __init__(
        self,
        *,
        on_register: Callable[[str], None] | None = None,
        on_poll: Callable[[], None] | None = None,
        on_wake: Callable[[], None] | None = None,
    ) -> None:
        self.epoch = "worker-one"
        self.sequence = 0
        self.online = True
        self.messages: queue.Queue[Envelope] = queue.Queue()
        self.registrations: list[tuple[str, ContextSnapshot | None, int]] = []
        self.contexts: list[ContextSnapshot] = []
        self.on_register = on_register
        self.on_poll = on_poll
        self.on_wake = on_wake
        self.closed = threading.Event()

    def connect(self) -> str:
        if not self.online:
            raise OSError("Fixture work process is offline.")
        return self.epoch

    def poll(self, limit: int = 64) -> tuple[Envelope, ...]:
        if self.on_poll is not None:
            self.on_poll()
        self.connect()
        batch: list[Envelope] = []
        for _ in range(limit):
            try:
                batch.append(self.messages.get_nowait())
            except queue.Empty:
                break
        return tuple(batch)

    def wake(self) -> None:
        self.connect()
        if self.on_wake is not None:
            self.on_wake()

    def register(self, task_id: str, context: ContextSnapshot | None, *, assistant_pid: int) -> None:
        self.registrations.append((task_id, context, assistant_pid))
        if self.on_register is not None:
            self.on_register(task_id)
        self.connect()

    def publish_context(self, context: ContextSnapshot, *, assistant_pid: int) -> None:
        self.contexts.append(context)
        self.connect()

    def respond(self, message: Envelope, result: ipc.Succeeded | ipc.Failed) -> bool:
        self.connect()
        raise AssertionError("Owner effects use the real pipe fixture.")

    def publish(self, payload: BridgeEvent, *, epoch: str | None = None) -> None:
        self.sequence += 1
        self.messages.put(Envelope(self.epoch if epoch is None else epoch, self.sequence, payload))

    def restart(self, epoch: str) -> None:
        self.epoch, self.sequence = epoch, 0

    def disconnect(self) -> None:
        self.online = False

    def reconnect(self) -> None:
        self.online = True

    def close(self) -> None:
        self.closed.set()


class WorkRig:
    def __init__(
        self,
        folder: Path,
        *,
        bridge: RecordingBridge | None = None,
        context: Callable[[], ContextSnapshot] | None = None,
        start: bool = True,
        on_snapshot: Callable[[WorkSnapshot], None] | None = None,
    ) -> None:
        # Folder, transport, context, startup and publication bind independent
        # fixture effects while preserving the frontend dependency interface.
        self.tasks = TaskStore(folder / "tasks.sqlite3")
        self.routines = RoutineStore(folder / "routines.sqlite3")
        self.saved_context = ContextStore(folder / "context.sqlite3")
        self.bridge = bridge or RecordingBridge()
        self.clock = Clock()
        self.windows: list[RecordingWindow] = []
        self.snapshots: list[WorkSnapshot] = []
        self.on_snapshot = on_snapshot
        self.errors: list[str] = []
        self.started: list[bool] = []
        self.finished: list[bool] = []
        self.agent = WorkAgent(
            self.tasks,
            self.routines,
            self.saved_context,
            self.bridge,
            self.create_window,
            on_snapshot=self.publish,
            on_done=lambda: self.finished.append(self.agent.running()),
            report_error=self.errors.append,
            on_start=lambda: self.started.append(self.agent.running()),
            context=context,
            clock=self.clock,
            assistant_pid=1234,
        )
        if start:
            self.agent.start_worker()

    def publish(self, snapshot: WorkSnapshot) -> None:
        self.snapshots.append(snapshot)
        if self.on_snapshot is not None:
            self.on_snapshot(snapshot)

    def create_window(self, agent: WorkAgent) -> RecordingWindow:
        window = RecordingWindow(agent.stop, on_submit=agent.start, on_reset=agent.new_conversation)
        self.windows.append(window)
        return window

    @property
    def panel(self) -> RecordingWindow:
        self.agent.prepare()
        return self.windows[0]

    def refresh(self) -> WorkSnapshot:
        assert self.agent.refresh().wait(5), "The observer did not finish its current journal and transport work."
        assert self.snapshots
        return self.snapshots[-1]

    def task(self, prompt: str) -> Task:
        return next(task for task in self.tasks.list_tasks() if task.prompt == prompt)

    def close(self) -> None:
        self.agent.close()
        assert self.agent.wait_closed(5)
        if self.windows:
            self.panel.paint()


@contextmanager
def work(folder: Path) -> Generator[WorkRig]:
    rig = WorkRig(folder)
    try:
        yield rig
    finally:
        rig.close()


def invocation(title: str) -> ContextSnapshot:
    window = Window(42, title, "workbook.exe", minimized=False)
    return ContextSnapshot(90, "active", (Activity(window, 80, 90, agent_active=False),))


def test_canvas_intake_and_questions_continue_when_presentation_is_unavailable(tmp_path: Path) -> None:
    # Defect: creating a conversation view fails before work state reaches the
    # canvas, preventing intake, durable clarification or accepted replies.
    tasks = TaskStore(tmp_path / "tasks.sqlite3")
    bridge = RecordingBridge()
    errors: list[str] = []
    clock = Clock()
    agent: WorkAgent

    def submit(run: CanvasRun) -> None:
        agent.watch(tuple(binding.task_id for binding in canvas.read().runs), owner="canvas")
        agent.submit_identified(run.task_id, run_prompt(run, canvas.title(run.work_id)), RequestKind.GENERAL)

    def unavailable(_agent: WorkAgent) -> ConversationOutput:
        raise RuntimeError("Fixture conversation presentation is unavailable")

    canvas = WorkCanvas(tmp_path / "canvas.sqlite3", submit, lambda _publication: None, autonomous=True)
    agent = WorkAgent(
        tasks,
        RoutineStore(tasks.path),
        ContextStore(tasks.path),
        bridge,
        unavailable,
        on_snapshot=canvas.observe_work,
        on_done=lambda: None,
        report_error=errors.append,
        clock=clock,
        assistant_pid=1234,
    )
    try:
        canvas.observe_catalog(Catalog(sources=(source(SourceKind.OUTLOOK),)))
        agent.start_worker()
        assert agent.refresh().wait(5)
        claim = tasks.claim("worker-one", "intake-run", at=clock())
        assert claim is not None and claim.task.id == canvas.read().runs[0].task_id
        tasks.finish(claim.run, Waiting(Question("owner", "Who owns this?", "Confirm the work owner.")), at=clock())
        assert agent.refresh().wait(5)
        assert canvas.waiting()[0].request == TaskRequest(claim.task.id, "owner")
        agent.command(AnswerTask(claim.task.id, "owner", TextAnswer("Contoso")))
        assert agent.refresh().wait(5)
        resumed = tasks.get(claim.task.id)
        assert resumed is not None and resumed.state is TaskStatus.READY
        assert not canvas.waiting() and len(tasks.list_tasks()) == 1
        assert errors and all("presentation is unavailable" in error for error in errors)
        assert not agent.snapshot().status
    finally:
        agent.close()
        assert agent.wait_closed(5)


def pending_approval(rig: WorkRig, prompt: str = "Send the reviewed draft") -> tuple[Task, RunRef, ApprovalReview]:
    rig.agent.start(prompt)
    rig.refresh()
    claim = rig.tasks.claim("worker-one", "approval-run", at=rig.clock())
    assert claim is not None
    request = Approval("once", "Review the operation", "Sensitive operation; request its live preview.", "a" * 64)
    review = ApprovalReview(
        claim.task.id,
        0,
        request,
        "Send the reviewed draft",
        "Exact recipient and complete draft: private preview text.",
    )
    task = rig.tasks.finish(claim.run, Waiting(request), at=rig.clock())
    assert task is not None
    return task, claim.run, review


def test_queued_requests_persist_with_their_invocation_context_without_reopening_the_panel(tmp_path: Path) -> None:
    # Defect: an agent voice request is dropped while another task is running,
    # or queues under stale invocation context instead of preserving both tasks;
    # or a self-review captures desktop context its agent must not see.
    current = invocation("First workbook")
    rig = WorkRig(tmp_path, context=lambda: current)
    try:
        rig.agent.start("Summarize this")
        rig.refresh()
        first = rig.task("Summarize this")
        current = invocation("Second workbook")
        rig.agent.voice("And this one")
        rig.refresh()
        second = rig.task("And this one")
        assert first.source == second.source and isinstance(first.source, RequestSource)
        assert rig.bridge.registrations == [
            (first.id, invocation("First workbook"), 1234),
            (second.id, invocation("Second workbook"), 1234),
        ]
        assert rig.panel.state.queued == ("And this one",)
        rig.panel.paint()
        assert rig.panel.view.shown == [False]
        assert {task.prompt for task in TaskStore(rig.tasks.path).list_tasks()} == {"Summarize this", "And this one"}
        assert b"First workbook" not in rig.tasks.path.read_bytes(), "Activity snapshots must remain volatile."
        assert rig.agent.running() and rig.started == [True]
        rig.agent.submit_identified("review-task", "Review the previous task", SelfReview("previous-task"))
        rig.agent.submit_identified("routine-task", "Run the standing instruction", RequestKind.GENERAL)
        rig.refresh()
        assert rig.bridge.registrations[-2:] == [("review-task", None, 1234), ("routine-task", invocation("Second workbook"), 1234)]
    finally:
        rig.close()


def test_registration_precedes_claimable_submission_and_does_not_block_ui_commands(tmp_path: Path) -> None:
    entered, release = threading.Event(), threading.Event()
    store = TaskStore(tmp_path / "tasks.sqlite3")

    def register(identity: str) -> None:
        assert store.get(identity) is None
        entered.set()
        assert release.wait(5)

    rig = WorkRig(tmp_path, bridge=RecordingBridge(on_register=register))
    try:
        rig.agent.start("First request")
        assert entered.wait(5)
        # The observer is held at the process boundary. Both callbacks return
        # without waiting on that exchange, then shutdown drains them in order.
        rig.agent.start("Queued request")
        rig.agent.close()
        release.set()
        assert rig.agent.wait_closed(5)
        assert {task.prompt for task in store.list_tasks()} == {"First request", "Queued request"}
        assert all(task.state is TaskStatus.READY for task in store.list_tasks())
    finally:
        release.set()
        rig.close()


def test_offline_submissions_remain_durable_and_shutdown_preserves_them(tmp_path: Path) -> None:
    bridge = RecordingBridge()
    bridge.disconnect()
    rig = WorkRig(tmp_path, bridge=bridge)
    try:
        rig.agent.start("Save this request while offline")
        snapshot = rig.refresh()
        assert "reconnect" in snapshot.status
        assert rig.task("Save this request while offline").state is TaskStatus.READY
    finally:
        rig.close()
    assert bridge.closed.is_set()
    assert TaskStore(tmp_path / "tasks.sqlite3").list_tasks()[0].state is TaskStatus.READY


def test_stop_cancels_only_this_conversations_active_and_queued_tasks(tmp_path: Path) -> None:
    with work(tmp_path) as rig:
        unrelated = rig.tasks.submit("other-task", "Other work", "Other work", RequestSource("other-conversation"), at=rig.clock())
        rig.agent.new_conversation()
        rig.agent.start("First")
        rig.agent.start("Queued")
        rig.refresh()
        claim = rig.tasks.claim("worker-one", "first-run", at=rig.clock())
        assert claim is not None
        rig.agent.stop()
        rig.refresh()
        assert rig.task("First").state is TaskStatus.CANCELLED
        assert rig.task("Queued").state is TaskStatus.CANCELLED
        other = rig.tasks.get(unrelated.id)
        assert other is not None and isinstance(other.state, Running)
        assert not rig.agent.running() and rig.finished == [False]
        assert rig.panel.state.queued == ()


def test_new_chat_keeps_work_and_prevents_old_live_updates_entering_the_new_view(tmp_path: Path) -> None:
    with work(tmp_path) as rig:
        rig.agent.start("Previous conversation")
        rig.refresh()
        old = rig.task("Previous conversation")
        claim = rig.tasks.claim("worker-one", "old-run", at=rig.clock())
        assert claim is not None
        rig.refresh()
        assert rig.agent.new_conversation()
        rig.agent.start("Fresh conversation")
        rig.bridge.publish(LogEvent(claim.run, Said("Late previous response", rig.clock())))
        rig.refresh()
        new = rig.task("Fresh conversation")
        assert old.source != new.source
        assert "Late previous response" not in rig.panel.all_text()
        assert "Previous conversation" not in rig.panel.all_text()
        assert rig.tasks.get(old.id) is not None and len(rig.tasks.list_tasks()) == 2


def test_questions_resume_only_the_exact_waiting_task_and_voice_uses_the_same_route(tmp_path: Path) -> None:
    with work(tmp_path) as rig:
        rig.agent.start("Find the workbook")
        rig.refresh()
        claim = rig.tasks.claim("worker-one", "question-run", at=rig.clock())
        assert claim is not None
        rig.tasks.finish(claim.run, Waiting(Question("which-sheet", "Which sheet?", "Choose a sheet in this workbook.")), at=rig.clock())
        rig.refresh()
        assert rig.panel.waiting
        # Defect: work accepts an approval decision for a question, since the window does not check the kind.
        assert not rig.panel.respond("which-sheet", ApprovalDecision.DECLINED) and rig.panel.waiting
        rig.agent.voice("Use revenue")
        rig.refresh()
        task = rig.tasks.get(claim.task.id)
        assert task is not None and task.state is TaskStatus.READY
        assert len(rig.tasks.list_tasks()) == 1
        assert [response.reply for response in rig.tasks.responses(task.id)] == [TextAnswer("Use revenue")]
        assert not rig.panel.respond("which-sheet", TextAnswer("Late answer"))


def test_a_blocked_task_yields_to_queued_work_and_can_be_resumed_later(tmp_path: Path) -> None:
    with work(tmp_path) as rig:
        rig.agent.start("Wait for the workbook")
        rig.agent.start("Write the summary")
        rig.refresh()
        blocked = rig.tasks.claim("worker-one", "blocked-run", at=rig.clock())
        assert blocked is not None
        rig.tasks.finish(blocked.run, Waiting(Blocked("The workbook is locked.")), at=rig.clock())
        working = rig.tasks.claim("worker-one", "summary-run", at=rig.clock())
        assert working is not None
        rig.bridge.publish(LogEvent(working.run, Said("Writing the summary now", rig.clock())))
        rig.refresh()
        assert "The workbook is locked." in rig.panel.all_text()
        assert "Writing the summary now" in rig.panel.all_text()
        rig.tasks.finish(working.run, Completed("Summary saved", ()), at=rig.clock())
        rig.refresh()
        assert "Summary saved" in rig.panel.all_text() and not rig.agent.running()
        rig.agent.command(ControlTask(blocked.task.id, Control.RESUME))
        rig.refresh()
        assert rig.agent.running()


def test_a_restart_does_not_replay_finished_work_but_shows_new_changes(tmp_path: Path) -> None:
    # Detect startup presenting every old blocked task again as a fresh warning.
    with work(tmp_path) as rig:
        rig.agent.start("Old work")
        rig.refresh()
        old = rig.tasks.claim("worker-one", "old-run", at=rig.clock())
        assert old is not None
        rig.tasks.finish(old.run, Waiting(Blocked("The old blocker.")), at=rig.clock())
        rig.refresh()
    with work(tmp_path) as restarted:
        restarted.refresh()
        assert "The old blocker." not in restarted.panel.all_text()
        restarted.agent.start("New work")
        restarted.refresh()
        new = restarted.tasks.claim("worker-one", "new-run", at=restarted.clock())
        assert new is not None
        restarted.tasks.finish(new.run, Waiting(Blocked("The new blocker.")), at=restarted.clock())
        restarted.refresh()
        assert "The new blocker." in restarted.panel.all_text()


def test_redirect_fences_a_visible_old_question_and_keeps_the_new_goal(tmp_path: Path) -> None:
    with work(tmp_path) as rig:
        rig.agent.start("Original goal")
        rig.refresh()
        claim = rig.tasks.claim("worker-one", "question-run", at=rig.clock())
        assert claim is not None
        rig.tasks.finish(claim.run, Waiting(Question("old-question", "Which file?", "")), at=rig.clock())
        rig.refresh()
        rig.agent.command(Redirect(claim.task.id, "Changed goal"))
        rig.agent.command(AnswerTask(claim.task.id, "old-question", TextAnswer("An obsolete file")))
        snapshot = rig.refresh()
        task = rig.tasks.get(claim.task.id)
        assert task is not None and task.prompt == "Changed goal" and task.state is TaskStatus.READY
        assert rig.tasks.responses(task.id) == ()
        assert "no longer waiting" in snapshot.status
        assert not rig.panel.respond("old-question", TextAnswer("Late UI answer"))


def test_approvals_require_the_exact_live_preview_and_expire_on_worker_restart(tmp_path: Path) -> None:
    with work(tmp_path) as rig:
        task, run, review = pending_approval(rig)
        rig.refresh()
        assert not rig.panel.waiting and not rig.snapshots[-1].reviews
        rig.agent.command(AnswerTask(task.id, review.request.id, ApprovalDecision.APPROVED))
        assert "fresh preview" in rig.refresh().status
        assert rig.tasks.responses(task.id) == ()
        rig.bridge.publish(ReviewEvent(run, review))
        snapshot = rig.refresh()
        assert snapshot.reviews == (review,)
        assert review.detail in rig.panel.all_text()
        # This command arrives before another observer poll can update the UI.
        # The committing boundary must still discover the new worker epoch.
        rig.bridge.restart("worker-two")
        rig.agent.command(AnswerTask(task.id, review.request.id, ApprovalDecision.APPROVED))
        snapshot = rig.refresh()
        assert snapshot.reviews == () and rig.tasks.responses(task.id) == ()
        rig.agent.command(RefreshApproval(task.id, review.request.id))
        rig.refresh()
        refreshed = rig.tasks.get(task.id)
        assert refreshed is not None and refreshed.state is TaskStatus.READY
        assert rig.tasks.responses(task.id) == ()


def test_wrong_run_and_old_epoch_previews_cannot_authorize_a_waiting_operation(tmp_path: Path) -> None:
    with work(tmp_path) as rig:
        task, run, review = pending_approval(rig)
        rig.bridge.publish(ReviewEvent(RunRef(task.id, "wrong-run"), review))
        rig.bridge.publish(ReviewEvent(run, review), epoch="old-worker")
        assert rig.refresh().reviews == ()
        rig.bridge.publish(ReviewEvent(run, review))
        assert rig.refresh().reviews == (review,)
        assert not rig.panel.respond(review.request.id, ApprovalDecision.APPROVED)
        rig.panel.input_presented(review.request.id)
        rig.agent.voice("Approve.")
        rig.refresh()
        assert [response.reply for response in rig.tasks.responses(task.id)] == [ApprovalDecision.APPROVED]
        assert rig.snapshots[-1].reviews == ()


def test_streaming_rejects_superseded_runs_and_completion_comes_from_the_journal(tmp_path: Path) -> None:
    # Defect: publishing an accepted reply leaves Markdown preparation to Qt,
    # freezing unrelated animations on both streaming and durable completion.
    prepared_answer.cache_clear()
    with work(tmp_path) as rig:
        rig.agent.start("Check the outcome")
        rig.refresh()
        claim = rig.tasks.claim("worker-one", "first-run", at=rig.clock())
        assert claim is not None
        rig.bridge.publish(LogEvent(claim.run, Answer("reply", "Current streamed text", rig.clock(), StreamState.RUNNING)))
        rig.refresh()
        assert "Current streamed text" in rig.panel.all_text()
        misses = prepared_answer.cache_info().misses
        assert "".join(span.text for span in prepared_answer("Current streamed text")) == "Current streamed text"
        assert prepared_answer.cache_info().misses == misses
        rig.tasks.control(claim.task.id, Control.PAUSE, at=rig.clock())
        rig.tasks.control(claim.task.id, Control.RESUME, at=rig.clock())
        resumed = rig.tasks.claim("worker-one", "resumed-run", at=rig.clock())
        assert resumed is not None
        rig.bridge.publish(LogEvent(claim.run, Said("Stale run text", rig.clock())))
        rig.bridge.publish(LogEvent(resumed.run, Said("Resumed run text", rig.clock())))
        rig.refresh()
        assert "Stale run text" not in rig.panel.all_text() and "Resumed run text" in rig.panel.all_text()
        rig.tasks.finish(resumed.run, Completed("Verified durable result", ("Output exists",)), at=rig.clock())
        rig.refresh()
        assert "Verified durable result" in rig.panel.all_text()
        misses = prepared_answer.cache_info().misses
        assert "".join(span.text for span in prepared_answer("Verified durable result")) == "Verified durable result"
        assert prepared_answer.cache_info().misses == misses
        rig.refresh()
        count = sum(isinstance(message, ChatMessage) and message.text == "Verified durable result" for message in rig.panel.state.messages)
        assert count == 1 and not rig.agent.running() and rig.finished == [False]


def test_approval_and_resumed_action_keep_one_notification_card(tmp_path: Path) -> None:
    # Defect: ending the UI turn at each approval cancels its running action row,
    # then resuming creates a second card alongside the falsely stopped card.
    with work(tmp_path) as rig:
        rig.agent.start("Open the workbook")
        rig.refresh()
        claim = rig.tasks.claim("worker-one", "first-run", at=rig.clock())
        assert claim is not None
        rig.bridge.publish(LogEvent(claim.run, ToolActivity("open", "open_file", "budget.xlsx", rig.clock())))
        rig.refresh()
        stack = advance(Stack(), rig.panel.snapshot(), 100)
        request = Approval("open-approval", "Open this workbook?", "budget.xlsx", "a" * 64)
        review = ApprovalReview(claim.task.id, 0, request, "Open the workbook", "budget.xlsx")
        rig.tasks.finish(claim.run, Waiting(request), at=rig.clock())
        rig.bridge.publish(ReviewEvent(claim.run, review))
        rig.refresh()
        stack = advance(stack, rig.panel.snapshot(), 101)
        assert len(stack.toasts) == 1
        waiting = stack.toasts[0].content
        assert isinstance(waiting, Turn) and isinstance(waiting.state, Working) and waiting.state.phase is Busy.WAITING
        rig.panel.input_presented(request.id)
        assert rig.panel.respond(request.id, ApprovalDecision.APPROVED)
        rig.refresh()
        stack = advance(stack, rig.panel.snapshot(), 102)
        resumed = rig.tasks.claim("worker-one", "resumed-run", at=rig.clock())
        assert resumed is not None
        rig.bridge.publish(LogEvent(resumed.run, ToolActivity("open", "open_file", "budget.xlsx", rig.clock(), Succeeded("Opened"))))
        rig.bridge.publish(LogEvent(resumed.run, Answer("reply", "The workbook is open.", rig.clock(), StreamState.COMPLETE)))
        rig.refresh()
        rig.tasks.finish(resumed.run, Completed("The workbook is open.", ("Window is visible",)), at=rig.clock())
        rig.refresh()
        stack = advance(stack, rig.panel.snapshot(), 103)
        assert [toast.key for toast in stack.toasts] == [TurnKey(0)]
        finished = stack.toasts[0].content
        assert isinstance(finished, Turn) and finished.state is Settled.FINISHED
        assert body(finished) == "The workbook is open."
        actions = tuple(message for message in rig.panel.snapshot().messages if isinstance(message, ToolActivity))
        assert len(actions) == 1 and actions[0].outcome == Succeeded("Opened")
        assert "stopped" not in rig.panel.all_text().lower()


def test_routine_and_context_commands_persist_without_implicit_enablement(tmp_path: Path) -> None:
    with work(tmp_path) as rig:
        rig.agent.command(CreateRoutine("Prepare notes", "Read the completed transcript", Once(1_000)))
        rig.agent.command(AddPreference("Tone", "Concise", "User"))
        rig.agent.command(AddProjectNote("Workspace", "Use the shared journal", "User", 3600))
        snapshot = rig.refresh()
        routine = snapshot.routines[0].routine
        preference = next(record for record in snapshot.context if isinstance(record, Preference))
        note = next(record for record in snapshot.context if isinstance(record, ProjectNote))
        assert not routine.enabled
        rig.agent.command(UpdateRoutine(routine.id, routine.revision, "Prepare daily notes", "Summarize new work", Every(1_000, 3600)))
        rig.agent.command(EnableRoutine(routine.id))
        rig.agent.command(UpdatePreference(preference.id, "Tone", "Detailed", "User correction"))
        rig.agent.command(UpdateProjectNote(note.id, "Workspace", "Use the durable journal", "User correction", 7200))
        snapshot = rig.refresh()
        updated = snapshot.routines[0].routine
        assert updated.enabled and updated.title == "Prepare daily notes"
        assert rig.saved_context.get(preference.id) == next(record for record in snapshot.context if isinstance(record, Preference))
        assert any(isinstance(record, Preference) and record.value == "Detailed" for record in snapshot.context)
        assert any(isinstance(record, ProjectNote) and record.text == "Use the durable journal" for record in snapshot.context)
        rig.agent.command(DisableRoutine(routine.id))
        rig.agent.command(RemoveContext(note.id))
        rig.refresh()
        reopened = RoutineStore(tmp_path / "routines.sqlite3").get(routine.id)
        assert reopened is not None and not reopened.enabled
        assert ContextStore(tmp_path / "context.sqlite3").get(note.id) is None
        assert not rig.errors


def test_follow_up_retains_related_context_and_user_controls_survive_reopening(tmp_path: Path) -> None:
    # Defect: a follow-up inherits a self-review's constrained profile,
    # so it runs without the general desktop context.
    with work(tmp_path) as rig:
        rig.agent.submit_identified("original-report", "Prepare the original report", SelfReview("previous-task"))
        rig.refresh()
        claim = rig.tasks.claim("worker-one", "report-run", at=rig.clock())
        assert claim is not None
        rig.tasks.finish(claim.run, Completed("Report is saved at output/report.md", ()), at=rig.clock())
        rig.agent.command(FollowUp(claim.task.id, "Add a one-page summary"))
        rig.refresh()
        follow_up = next(task for task in rig.tasks.list_tasks() if task.id != claim.task.id)
        assert isinstance(claim.task.source, RequestSource) and claim.task.source.profile == SelfReview("previous-task")
        assert follow_up.source == RequestSource(claim.task.source.conversation_id) and "output/report.md" in follow_up.prompt
        assert "Add a one-page summary" in follow_up.prompt
        rig.agent.command(ControlTask(follow_up.id, Control.PAUSE))
        rig.refresh()
        paused = TaskStore(tmp_path / "tasks.sqlite3").get(follow_up.id)
        assert paused is not None and paused.state is TaskStatus.PAUSED
        rig.agent.command(ControlTask(follow_up.id, Control.RESUME))
        rig.refresh()
        resumed = rig.tasks.get(follow_up.id)
        assert resumed is not None and resumed.state is TaskStatus.READY


def test_reconnecting_reprojects_a_durable_question_without_showing_a_hidden_view(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.sqlite3")
    store.submit("recovered-task", "Recover my request", "Recover my request", RequestSource("recovered-conversation"), at=10)
    claim = store.claim("old-worker", "saved-question-run", at=20)
    assert claim is not None
    store.finish(claim.run, Waiting(Question("saved-question", "Where should I save it?", "Provide a folder.")), at=30)
    with work(tmp_path) as rig:
        rig.refresh()
        assert rig.panel.waiting
        rig.panel.paint()
        assert rig.panel.view.shown == []
        rig.bridge.publish(Resync("Worker reconnected"))
        rig.refresh()
        assert rig.panel.submit("Use the project folder")
        rig.refresh()
        assert [response.reply for response in store.responses("recovered-task")] == [TextAnswer("Use the project folder")]


def test_real_bridge_delivers_context_live_output_and_meeting_results_to_the_frontend(tmp_path: Path) -> None:
    folder = tmp_path / "ipc"
    folder.mkdir()
    tasks = TaskStore(tmp_path / "tasks.sqlite3")
    clock = Clock()
    windows: list[RecordingWindow] = []
    errors: list[str] = []
    operations: list[StartMeeting | MeetingCommand] = []

    def current_run(run: RunRef) -> bool:
        task = tasks.get(run.task_id)
        return task is not None and owns(task, run)

    def window(agent: WorkAgent) -> RecordingWindow:
        result = RecordingWindow(agent.stop, on_submit=agent.start, on_reset=agent.new_conversation)
        windows.append(result)
        return result

    def meeting(operation: ipc.OwnerCall) -> ipc.Succeeded:
        assert isinstance(operation, (StartMeeting, MeetingCommand))
        operations.append(operation)
        return ipc.Succeeded("The current recording is active.")

    server = BridgeServer(folder, epoch="1" * 32, wake=lambda: None, owns=current_run)
    agent = WorkAgent(
        tasks,
        RoutineStore(tmp_path / "routines.sqlite3"),
        ContextStore(tmp_path / "context.sqlite3"),
        BridgeClient(folder),
        window,
        on_snapshot=lambda _: None,
        on_done=lambda: None,
        report_error=errors.append,
        context=lambda: invocation("Shared workbook"),
        owners=meeting,
        clock=clock,
        assistant_pid=1234,
    )
    server.start()
    agent.start_worker()
    try:
        agent.start("Inspect my current workbook")
        assert agent.refresh().wait(5)
        task = tasks.list_tasks()[0]
        assert server.invocation(task.id) == invocation("Shared workbook")
        assert server.context() == invocation("Shared workbook") and server.assistant_pid == 1234
        claim = tasks.claim("worker-one", "real-bridge-run", at=clock())
        assert claim is not None
        assert server.publish(LogEvent(claim.run, Said("Authenticated progress reached the conversation.", clock())))
        assert agent.refresh().wait(5)
        assert "Authenticated progress reached the conversation." in windows[0].all_text()
        with ThreadPoolExecutor(max_workers=1) as pool:
            response = pool.submit(server.call, claim.run, MeetingCommand.STATUS, threading.Event(), timeout_s=3)
            assert response.result(timeout=5) == "The current recording is active."
        assert operations == [MeetingCommand.STATUS] and not errors
    finally:
        agent.close()
        assert agent.wait_closed(5)
        server.close()
        assert server.wait(5)
        for panel in windows:
            panel.paint()
