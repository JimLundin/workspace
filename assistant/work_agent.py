"""Conversation controls backed by durable work in the supervised process.

UI callbacks enqueue immutable requests. This controller's observer owns all
journal and transport calls; the existing AgentWindow owns UI scheduling.
"""

import os
import queue
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import assert_never

lazy import automation.presentation
lazy from assistant import agent_session
lazy from assistant.activity import ContextSnapshot
lazy from assistant.agent_window import AgentWindow
lazy from assistant.feed_origin import FeedRequest
lazy from assistant.work_commands import AnswerTask, FollowUp, Redirect, Submit, WorkCommand
lazy from assistant.work_service import IdentifiedSubmission, Issued, WorkBridge, WorkService
lazy from assistant.work_snapshot import WorkSnapshot
lazy from automation.context import ContextStore
lazy from automation.execution import ApprovalReview, current_review, review_matches
lazy from automation.ipc import (
    Envelope,
    LogEvent,
    MeetingCommand,
    MeetingFailed,
    MeetingRequest,
    MeetingSucceeded,
    StartMeeting,
)
lazy from automation.routines import RoutineStore
lazy from automation.store import TaskStore
lazy from automation.task import (
    Approval,
    ApprovalDecision,
    Blocked,
    Completed,
    Failed,
    FeedHandoff,
    Interrupted,
    MeetingFollowup,
    Profile,
    Question,
    Reply,
    RequestKind,
    RequestSource,
    RoutineSource,
    Running,
    RunRef,
    Task,
    TaskStatus,
    Until,
    Waiting,
    WaitReason,
    answers,
    identifier,
    owns,
    requested,
    terminal,
    text,
)

type MeetingControl = Callable[[StartMeeting | MeetingCommand], MeetingSucceeded | MeetingFailed]


@dataclass(frozen=True, slots=True)
class StopConversation:
    conversation_id: str
    after: int


@dataclass(frozen=True, slots=True)
class Observe:
    completed: threading.Event


type Job = Issued | IdentifiedSubmission | StopConversation | Observe


def conversation_of(task: Task) -> str | None:
    match task.source:
        case RequestSource(conversation_id=conversation_id):
            return conversation_id
        case RoutineSource():
            return None


def in_conversation(task: Task, conversation_id: str | None) -> bool:
    return conversation_id is not None and conversation_of(task) == conversation_id


def active(task: Task) -> bool:
    match task.state:
        case TaskStatus.PAUSED | Waiting(Blocked() | Until()):
            return False
        case _:
            return not terminal(task.state)


def new_turn(previous: Task, task: Task) -> bool:
    """A changed goal, leaving a wait or a different run starts a fresh turn for the same task."""
    if task.goal_revision != previous.goal_revision:
        return True
    match previous.state, task.state:
        case Waiting(), Waiting():
            return False
        case Waiting(), _:
            return True
        case Running(run=before) | Interrupted(run=before), Running(run=after):
            return before != after
        case _:
            return False


def turn_ended(task: Task) -> bool:
    match task.state:
        case Waiting() | Completed() | Failed() | TaskStatus.PAUSED | TaskStatus.CANCELLED:
            return True
        case TaskStatus.READY | Running() | Interrupted():
            return False
        case _:
            assert_never(task.state)


def chronological(task: Task) -> tuple[float, str]:
    return task.created_at, task.id


def input_message(task: Task, review: ApprovalReview | None) -> agent_session.AgentRequest | None:
    """A redacted journal record cannot become an approvable conversation row."""
    match task.state:
        case Waiting(Question() as question):
            return agent_session.AgentRequest(question, question.detail, task.updated_at)
        case Waiting(Approval()):
            if review is not None and review_matches(task, review):
                return agent_session.AgentRequest(review.request, review.detail, task.updated_at)
            return None
        case _:
            return None


class WorkAgent:
    __slots__ = (
        "_closed",
        "_closing",
        "_conversation",
        "_create_window",
        "_displayed",
        "_displayed_review",
        "_jobs",
        "_last_stop",
        "_last_submission_source",
        "_live",
        "_lock",
        "_meeting_results",
        "_ordinary_pending",
        "_pending",
        "_queued",
        "_rejected_input",
        "_reported_running",
        "_sequence",
        "_service",
        "_settled",
        "_snapshot",
        "_thread",
        "_wake",
        "_watch_groups",
        "_watched",
        "clock",
        "context",
        "identity",
        "meeting",
        "on_done",
        "on_snapshot",
        "on_start",
        "report_error",
        "window",
    )

    def __init__(
        self,
        tasks: TaskStore,
        routines: RoutineStore,
        saved_context: ContextStore,
        bridge: WorkBridge,
        create_window: Callable[[WorkAgent], AgentWindow],
        *,
        on_snapshot: Callable[[WorkSnapshot], None],
        on_done: Callable[[], None],
        report_error: Callable[[str], None],
        on_start: Callable[[], None] | None = None,
        context: Callable[[], ContextSnapshot] | None = None,
        meeting: MeetingControl | None = None,
        clock: Callable[[], float] = time.time,
        identity: Callable[[], str] = lambda: uuid.uuid4().hex,
        assistant_pid: int | None = None,
    ) -> None:
        self._service = WorkService(tasks, routines, saved_context, bridge, assistant_pid=os.getpid() if assistant_pid is None else assistant_pid)
        self._create_window = create_window
        self.on_snapshot, self.on_done, self.report_error, self.on_start = on_snapshot, on_done, report_error, on_start
        self.context, self.meeting, self.clock, self.identity = context, meeting, clock, identity
        self._lock = threading.RLock()
        # A Stop marker follows its accepted work in FIFO order. Between two
        # distinct Stop markers there is at least one ordinary command, so
        # 256 ordinary slots require at most 257 reserved control slots.
        self._jobs: queue.Queue[Job] = queue.Queue(maxsize=513)
        self._ordinary_pending = self._sequence = 0
        self._last_stop: StopConversation | None = None
        self._last_submission_source: str | None = None
        self._wake, self._closing, self._closed = threading.Event(), threading.Event(), threading.Event()
        self._thread: threading.Thread | None = None
        self._conversation: str | None = None
        self._snapshot = WorkSnapshot()
        self._reported_running = False
        self._pending: dict[str, str | None] = {}
        self._queued: set[str] = set()
        self._settled: dict[str, int] = {}
        self._displayed: Task | None = None
        self._displayed_review: ApprovalReview | None = None
        self._rejected_input: tuple[str, str] | None = None
        self._watch_groups: dict[str, frozenset[str]] = {}
        self._watched: frozenset[str] = frozenset()
        self._live: Callable[[automation.presentation.LiveMessage], None] | None = None
        self._meeting_results: dict[tuple[str, RunRef, str], MeetingSucceeded | MeetingFailed] = {}
        self.window: AgentWindow | None = None

    def start_worker(self) -> None:
        """Begin observation after the application has composed its callbacks."""
        with self._lock:
            if self._thread is None and not self._closing.is_set():
                self._thread = threading.Thread(target=self._observe, name="work frontend", daemon=True)
                self._thread.start()

    def _source(self, profile: Profile = RequestKind.GENERAL) -> RequestSource:
        if self._conversation is None:
            self._conversation = self.identity()
        return RequestSource(self._conversation, profile)

    def _enqueue(self, job: Issued | IdentifiedSubmission | Observe) -> bool:
        with self._lock:
            if self._closing.is_set() or self._ordinary_pending >= 256:
                return False
            try:
                self._jobs.put_nowait(job)
            except queue.Full:
                return False
            self._ordinary_pending += 1
            self._sequence += 1
            match job:
                case IdentifiedSubmission() | Issued(command=Submit() | FollowUp()):
                    self._pending[job.identity] = job.source.conversation_id
                    self._last_submission_source = job.source.conversation_id
                case _:
                    pass
            self._wake.set()
        return True

    def command(self, command: WorkCommand) -> None:
        captured: ContextSnapshot | None = None
        match command:
            case AnswerTask(task_id=task_id, request_id=request_id):
                identifier(task_id, "reply task identity")
                identifier(request_id, "reply request identity")
            case Submit() | FollowUp() | Redirect() if self.context is not None:
                captured = self.context()
            case _:
                pass
        with self._lock:
            issued = Issued(command, self.identity(), self._source(), captured)
            if not self._enqueue(issued):
                raise ValueError("Work is closing or its input queue is full. Try the request again.")

    def start(self, text: str) -> None:
        if not (text := text.strip()):
            return
        reveal = not self.running()
        try:
            self.command(Submit(text))
        except ValueError as error:
            self._panel().problem(str(error))
            return
        if reveal:
            self._panel().show()

    def notify_canvas(self, title: str, target: str) -> None:
        self._panel().notify_canvas(title, target)

    def submit_identified(self, identity: str, prompt: str, profile: Profile) -> None:
        """Accept a caller-owned task ID so repeated submissions reuse the same task.

        The observer retains journal and transport ownership, just as it does
        for conversation commands. Returning means queued, not yet committed.
        """
        identity = identifier(identity, "task identity")
        prompt = text(prompt, "task prompt").strip()
        match profile:
            case MeetingFollowup():
                # Its agent sees only the selected recordings.
                captured = None
            case RequestKind.GENERAL | FeedHandoff():
                captured = self.context() if self.context is not None else None
            case _:
                assert_never(profile)
        with self._lock:
            if not self._enqueue(IdentifiedSubmission(identity, prompt, self._source(profile), captured)):
                raise ValueError("Work is closing or its input queue is full. Try the request again.")

    def watch(self, task_ids: tuple[str, ...], *, owner: str = "default") -> None:
        """Replace one view's interests while the observer retains their union."""
        owner = identifier(owner, "watch owner")
        watched = frozenset(identifier(identity, "watched task identity") for identity in task_ids)
        if len(watched) > 512:
            raise ValueError("At most 512 saved tasks can be watched at once.")
        with self._lock:
            if self._closing.is_set():
                raise ValueError("Work is closing.")
            groups = self._watch_groups.copy()
            if watched:
                groups[owner] = watched
            else:
                groups.pop(owner, None)
            if len(groups) > 16:
                raise ValueError("At most 16 work views can retain tasks at once.")
            combined = frozenset(identity for group in groups.values() for identity in group)
            if len(combined) > 512:
                raise ValueError("At most 512 saved tasks can be watched across all work views.")
            self._watch_groups, self._watched = groups, combined
            self._wake.set()

    def snapshot(self) -> WorkSnapshot:
        """Read the latest immutable committed projection without journal I/O."""
        with self._lock:
            return self._snapshot

    def voice(self, text: str) -> None:
        if self.window is None or not self.window.reply_by_voice(text):
            self.start(text)

    def running(self) -> bool:
        with self._lock:
            return (self._conversation is not None and self._conversation in self._pending.values()) or any(
                active(task) and in_conversation(task, self._conversation) for task in self._snapshot.tasks
            )

    def _panel(self) -> AgentWindow:
        with self._lock:
            if self.window is None:
                self.window = self._create_window(self)
            return self.window

    def prepare(self) -> None:
        self._panel()

    def show(self) -> None:
        self._panel().show(focus=True)

    def refresh(self) -> threading.Event:
        """Observe accepted commands and current journals without blocking the UI."""
        completed = threading.Event()
        if not self._enqueue(Observe(completed)):
            completed.set()
        return completed

    def stop(self) -> None:
        with self._lock:
            if self._closing.is_set() or self._conversation is None:
                return
            if self._last_submission_source != self._conversation and not any(
                in_conversation(task, self._conversation) and not terminal(task.state) for task in self._snapshot.tasks
            ):
                return
            stop = StopConversation(self._conversation, self._sequence)
            if stop == self._last_stop:
                return
            self._jobs.put_nowait(stop)
            self._last_stop = stop
            self._wake.set()
            if self.window is not None:
                self.window.stopping()

    def new_conversation(self) -> bool:
        with self._lock:
            if self._closing.is_set():
                return False
            was_running, self._reported_running = self._reported_running, False
            self._conversation = self.identity()
            self._displayed = self._displayed_review = self._live = None
            self._rejected_input = None
            self._settled.clear()
            self._queued.clear()
            if self.window is not None:
                self.window.reset()
            self._wake.set()
        if was_running:
            self.on_done()
        return True

    def close(self) -> None:
        """Drain accepted mutations and disconnect; user cancellation is separate."""
        with self._lock:
            if self._closing.is_set():
                return
            self._closing.set()
            self._wake.set()
            if self.window is not None:
                self.window.close()
            if self._thread is None:
                # Commands may have arrived during composition, before startup.
                self._thread = threading.Thread(target=self._observe, name="work frontend shutdown", daemon=True)
                self._thread.start()

    def wait_closed(self, timeout: float | None = None) -> bool:
        return self._closed.wait(timeout)

    def _reply(self, task_id: str, request_id: str, reply: Reply) -> bool:
        with self._lock:
            task = next((task for task in self._snapshot.tasks if task.id == task_id), None)
            request = requested(task) if task is not None else None
            if task is None or request is None or request.id != request_id or not answers(request, reply):
                return False
            if reply is ApprovalDecision.APPROVED and current_review(task, self._snapshot.reviews) is None:
                return False
            return self._enqueue(Issued(AnswerTask(task_id, request_id, reply), self.identity(), self._source(), None))

    def _request(self, task: Task, message: agent_session.AgentRequest) -> None:
        self._panel().request_input(message, lambda reply: self._reply(task.id, message.id, reply))

    def _clear_input(self) -> None:
        if self.window is not None:
            self.window.withdraw_input()

    def _display(self, task: Task, review: ApprovalReview | None) -> None:
        match task.source:
            case RequestSource(profile=FeedHandoff(item, title)):
                source: FeedRequest | None = FeedRequest(item, title)
            case RequestSource() | RoutineSource():
                source = None
        previous = self._displayed
        if task == previous and review == self._displayed_review:
            return
        window = self._panel()
        if previous is None or previous.id != task.id:
            self._clear_input()
            window.begin(source.title if source is not None else task.prompt, queued=task.id in self._queued, source=source)
            self._queued.discard(task.id)
            self._live = window.updates()
        elif new_turn(previous, task):
            self._clear_input()
            if active(task):
                window.finish()
                window.begin(f"Continue: {task.title}", source=source)
                self._live = window.updates()
        self._displayed, self._displayed_review = task, review
        if task.checkpoint is not None and (previous is None or previous.checkpoint != task.checkpoint):
            window.step(task.checkpoint.summary)
        self._display_status(task, review)

    def _display_status(self, task: Task, review: ApprovalReview | None) -> None:
        window = self._panel()
        if requested(task) is None:
            self._clear_input()
        match task.state:
            case TaskStatus.READY:
                window.step("Queued for the work process.")
            case Running():
                pass
            case Interrupted(_, reason):
                window.step(f"Recovering interrupted work: {reason}")
            case Waiting(reason):
                self._display_waiting(task, reason, review)
            case Completed(result, _):
                window.done(result)
            case Failed(reason):
                window.problem(reason)
            case TaskStatus.CANCELLED:
                window.done("Stopped.")
            case TaskStatus.PAUSED:
                window.say("Paused. Resume this task from Work.")
            case _:
                assert_never(task.state)
        if turn_ended(task):
            window.finish()
            self._queued.clear()

    def _display_waiting(self, task: Task, reason: WaitReason, review: ApprovalReview | None) -> None:
        match reason:
            case Question() | Approval():
                message = input_message(task, review)
                if message is not None:
                    self._request(task, message)
                else:
                    self._clear_input()
                    self._panel().say("An approval needs a fresh preview. Open Work to request it.")
            case Blocked(explanation):
                self._panel().problem(explanation)
            case Until(_, explanation):
                self._panel().say(f"Waiting: {explanation}")
            case _:
                assert_never(reason)

    def _publish(self, snapshot: WorkSnapshot) -> None:
        with self._lock:
            if self._closing.is_set():
                return
            was_running = self._reported_running
            self._snapshot = snapshot
            self._restore_reply(snapshot)
            if self._conversation is None:
                self._conversation = next(
                    (conversation for task in snapshot.tasks if (conversation := conversation_of(task)) is not None and not terminal(task.state)),
                    None,
                )
            tasks = sorted((task for task in snapshot.tasks if in_conversation(task, self._conversation)), key=chronological)
            task_ids = {task.id for task in tasks}
            self._settled = {identity: revision for identity, revision in self._settled.items() if identity in task_ids}
            if self._displayed is not None and self._displayed.id not in task_ids:
                self._displayed = self._displayed_review = self._live = None
                self._clear_input()
                if self.window is not None:
                    self.window.finish()
                self._queued.clear()
            selected = next((task for task in tasks if self._displayed is not None and task.id == self._displayed.id), None)
            candidates = [task for task in tasks if self._settled.get(task.id) != task.revision]
            while selected is not None or candidates:
                selected = selected if selected is not None else candidates[0]
                review = current_review(selected, snapshot.reviews)
                self._display(selected, review)
                if active(selected):
                    break
                self._settled[selected.id] = selected.revision
                candidates = [task for task in candidates if task.id != selected.id]
                selected = None
                self._displayed = None
            for task in tasks:
                if (
                    active(task)
                    and (self._displayed is None or task.id != self._displayed.id)
                    and task.id not in self._queued
                    and len(self._queued) < 100
                ):
                    self._panel().queued(task.prompt)
                    self._queued.add(task.id)
            is_running = self._reported_running = self.running()
        self.on_snapshot(snapshot)
        if not was_running and is_running and self.on_start is not None:
            self.on_start()
        elif was_running and not is_running:
            self.on_done()

    def _restore_reply(self, snapshot: WorkSnapshot) -> None:
        if self._rejected_input is None:
            return
        task_id, request_id = self._rejected_input
        self._rejected_input = None
        task = next((task for task in snapshot.tasks if task.id == task_id), None)
        request = requested(task) if task is not None else None
        # A failure is only recorded for the displayed task, and publishing restores it before redisplaying.
        if self.window is not None and task is not None and request is not None and request.id == request_id:
            review = current_review(task, snapshot.reviews)
            self.window.withdraw_input()
            message = input_message(task, review)
            if message is not None:
                self.window.problem("That reply could not be saved. Please answer the current request again.")
                self._request(task, message)

    def _observed_ids(self) -> tuple[frozenset[str], frozenset[str]]:
        with self._lock:
            watched = self._watched
            # The displayed task owns any projected request; its reply needs that task observed.
            if self._displayed is not None and requested(self._displayed) is not None:
                watched = watched | {self._displayed.id}
            return watched, frozenset(self._pending)

    def _publish_unavailable(self) -> None:
        watched, pending = self._observed_ids()
        with self._lock:
            if self._closing.is_set():
                return
            snapshot = self._service.unavailable(self._snapshot, watched, pending)
            self._snapshot = snapshot
        self.on_snapshot(snapshot)

    def _log(self, event: LogEvent) -> None:
        task = self._service.tasks.get(event.run.task_id)
        with self._lock:
            if task is None or not owns(task, event.run) or not in_conversation(task, self._conversation):
                return
            if self._displayed is None or self._displayed.id != task.id or self.window is None or self._closing.is_set():
                return
            match event.event:
                case automation.presentation.Progress(text):
                    self.window.step(text)
                case automation.presentation.Said(text, _):
                    self.window.say(text)
                case automation.presentation.Done():
                    pass  # A durable outcome, not a late live frame, completes work.
                case automation.presentation.Problem(text, _):
                    self.window.problem(text)
                case automation.presentation.Finished():
                    pass
                case automation.presentation.Answer() | automation.presentation.ReasoningSummary() | automation.presentation.ToolActivity():
                    if self._live is not None:
                        self._live(event.event)
                case _:
                    assert_never(event.event)

    def _meeting(self, message: Envelope, request: MeetingRequest) -> None:
        task = self._service.tasks.get(request.run.task_id)
        if task is None or not owns(task, request.run) or self._closing.is_set():
            return
        key = message.epoch, request.run, request.request_id
        result = self._meeting_results.get(key)
        if result is None:
            try:
                result = self.meeting(request.operation) if self.meeting is not None else MeetingFailed("Meeting controls are unavailable.")
            except Exception:
                self.report_error(traceback.format_exc())
                result = MeetingFailed("The meeting operation failed; see the assistant log.")
            if len(self._meeting_results) >= 128:
                self._meeting_results.pop(next(iter(self._meeting_results)))
            self._meeting_results[key] = result
        try:
            if not self._service.bridge.respond(message, result):
                self._service.problem = "The meeting request expired before its result was delivered. Check Recordings for its current state."
        except OSError, ValueError:
            self._service.problem = "The work process disconnected before confirming the meeting result. Check Recordings for its current state."

    def _jobs_ready(self) -> tuple[Observe, ...]:
        observed: list[Observe] = []
        for _ in range(64):
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                break
            match job:
                case StopConversation():
                    pass
                case Issued() | IdentifiedSubmission() | Observe():
                    with self._lock:
                        self._ordinary_pending -= 1
            try:
                match job:
                    case Issued() | IdentifiedSubmission():
                        self._service.apply(job, at=self.clock())
                    case StopConversation(conversation_id):
                        self._service.stop_conversation(conversation_id, at=self.clock())
                    case Observe():
                        observed.append(job)
                    case _:
                        assert_never(job)
            except Exception as error:
                self._service.problem = str(error) or "The work request could not be saved."
                match job:
                    case Issued() | IdentifiedSubmission():
                        self._record_failure(job)
                    case StopConversation() | Observe():
                        pass
                self.report_error(traceback.format_exc())
            finally:
                with self._lock:
                    match job:
                        case Issued() | IdentifiedSubmission():
                            self._pending.pop(job.identity, None)
                        case StopConversation() if self._last_stop == job:
                            self._last_stop = None
                        case _:
                            pass
        return tuple(observed)

    def _record_failure(self, job: Issued | IdentifiedSubmission) -> None:
        watched, _ = self._observed_ids()
        self._service.submission_failed(job, self._service.problem, watched=watched)
        match job:
            case Issued(command=AnswerTask(task_id=task_id, request_id=request_id)) as reply:
                self._service.reply_failed(reply, self._service.problem, watched=watched)
                with self._lock:
                    if self._displayed is not None and self._displayed.id == task_id:
                        self._rejected_input = task_id, request_id
            case _:
                pass

    def _observe(self) -> None:
        previous_context: ContextSnapshot | None = None
        try:
            while True:
                observed = self._jobs_ready()
                try:
                    if not self._closing.is_set():
                        current_context = self.context() if self.context is not None else None
                        if current_context is not None and current_context != previous_context:
                            self._service.publish_context(current_context)
                            previous_context = current_context
                        events = self._service.events(at=self.clock())
                        watched, pending = self._observed_ids()
                        self._publish(self._service.snapshot(at=self.clock(), watched=watched, pending=pending))
                        for event in events:
                            match event.payload:
                                case LogEvent() as log:
                                    self._log(log)
                                case MeetingRequest() as request:
                                    self._meeting(event, request)
                                case _:
                                    raise ValueError("Unexpected frontend event.")
                except Exception as error:
                    self._service.problem = str(error) or "Work could not be refreshed."
                    self._publish_unavailable()
                    self.report_error(traceback.format_exc())
                finally:
                    for observation in observed:
                        observation.completed.set()
                if self._closing.is_set() and self._jobs.empty():
                    break
                if self._jobs.empty():
                    self._wake.wait(0.25)
                    self._wake.clear()
        finally:
            try:
                self._service.bridge.close()
            finally:
                self._closed.set()
