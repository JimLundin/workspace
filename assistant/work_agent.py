"""Conversation controls backed by durable work on the worker's threads.

UI callbacks enqueue immutable requests. This controller's observer owns journal mutations,
worker notifications and live updates; the injected conversation output owns presentation and UI scheduling.
"""

import queue
import threading
import time
import traceback
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from typing import assert_never

from assistant.conversation_output import ConversationOutput
from cell import Cell
lazy import contracts.presentation
lazy from assistant.work_service import IdentifiedSubmission, Issued, Worker, WorkService
lazy from automation.activity import ContextSnapshot
lazy from automation.context import ContextStore
lazy from automation.store import TaskStore
lazy from contracts import agent_session
lazy from contracts.feed_origin import FeedRequest, Initiation
lazy from contracts.presentation import PresentationEvent
lazy from contracts.task import (
    Blocked,
    Completed,
    Failed,
    FeedHandoff,
    Interrupted,
    Profile,
    Question,
    RequestKind,
    RequestSource,
    Running,
    RunRef,
    SelfReview,
    Task,
    TaskStatus,
    TextAnswer,
    Until,
    Waiting,
    WaitReason,
    identifier,
    owns,
    requested,
    terminal,
    text,
)
lazy from contracts.work_commands import AnswerTask, Submit, WorkCommand
lazy from contracts.work_snapshot import WorkSnapshot


@dataclass(frozen=True, slots=True)
class StopConversation:
    conversation_id: str
    after: int


@dataclass(frozen=True, slots=True)
class Observe:
    completed: threading.Event


type Job = Issued | IdentifiedSubmission | StopConversation | Observe


def in_conversation(task: Task, conversation_id: str | None) -> bool:
    return task.source.conversation_id == conversation_id


def source_is_automatic(task: Task) -> bool:
    """Notification admission owns this durable identity namespace."""
    return isinstance(task.source.profile, FeedHandoff) and task.id.startswith("workspace-notification:")


def active(task: Task) -> bool:
    match task.state:
        case TaskStatus.PAUSED | Waiting(Blocked() | Until()):
            return False
        case _:
            return not terminal(task.state)


def new_turn(previous: Task, task: Task) -> bool:
    """A changed goal or execution break starts a turn; user input continues it."""
    if task.goal_revision != previous.goal_revision:
        return True
    match previous.state, task.state:
        case Waiting(), Waiting():
            return False
        case Waiting(Question()), _:
            return False
        case Waiting(), _:
            return True
        case Running(run=before) | Interrupted(run=before), Running(run=after):
            return before != after
        case _:
            return False


def turn_ended(task: Task) -> bool:
    match task.state:
        case Waiting(reason):
            match reason:
                case Blocked() | Until():
                    return True
                case Question():
                    return False
                case _:
                    assert_never(reason)
        case Completed() | Failed() | TaskStatus.PAUSED | TaskStatus.CANCELLED:
            return True
        case TaskStatus.READY | Running() | Interrupted():
            return False
        case _:
            assert_never(task.state)


def chronological(task: Task) -> tuple[float, str]:
    return task.created_at, task.id


def _drained[T](source: queue.Queue[T] | queue.SimpleQueue[T], limit: int) -> Iterator[T]:
    """Up to limit items already waiting, in queue order, without blocking."""
    for _ in range(limit):
        try:
            item = source.get_nowait()
        except queue.Empty:
            return
        yield item


def _identity() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True, slots=True)
class _Frontend:
    """The observer's state, replaced whole under the agent's lock."""

    snapshot: WorkSnapshot = field(default_factory=WorkSnapshot)
    conversation: str | None = None
    window: ConversationOutput | None = None
    thread: threading.Thread | None = None
    ordinary_pending: int = 0
    sequence: int = 0
    last_stop: StopConversation | None = None
    last_submission_source: str | None = None
    reported_running: bool = False
    pending: frozendict[str, str | None] = frozendict()
    """Submissions not yet observed in the journal, and their conversation."""
    queued: frozenset[str] = frozenset()
    settled: frozendict[str, int] = frozendict()
    """The revision of each task already presented."""
    started: bool = False
    """Whether this process has taken its first snapshot of existing work."""
    displayed: Task | None = None
    rejected_input: tuple[str, str] | None = None
    watch_groups: frozendict[str, frozenset[str]] = frozendict()
    watched: frozenset[str] = frozenset()
    live: Callable[[contracts.presentation.LiveMessage], None] | None = None


@dataclass(frozen=True, slots=True)
class WorkAgent:
    # Journal and worker, view construction and independent frontend
    # callbacks compose one observer lifetime.
    _service: WorkService
    _create_window: Callable[[WorkAgent], ConversationOutput]
    on_snapshot: Callable[[WorkSnapshot], None] = field(kw_only=True)
    on_done: Callable[[], None] = field(kw_only=True)
    report_error: Callable[[str], None] = field(kw_only=True)
    on_start: Callable[[], None] | None = field(default=None, kw_only=True)
    context: Callable[[], ContextSnapshot] | None = field(default=None, kw_only=True)
    clock: Callable[[], float] = field(default=time.time, kw_only=True)
    identity: Callable[[], str] = field(default=_identity, kw_only=True)
    _state: Cell[_Frontend] = field(default_factory=lambda: Cell(_Frontend()), init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    # A Stop marker follows its accepted work in FIFO order. Between two
    # distinct Stop markers there is at least one ordinary command, so
    # 256 ordinary slots require at most 257 reserved control slots.
    _jobs: queue.Queue[Job] = field(default_factory=lambda: queue.Queue[Job](maxsize=513), init=False, repr=False)
    _wake: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _closing: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _closed: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _events: queue.SimpleQueue[tuple[RunRef, PresentationEvent]] = field(
        default_factory=queue.SimpleQueue[tuple[RunRef, PresentationEvent]], init=False, repr=False
    )

    @classmethod
    def open(  # noqa: PLR0913 - composition root for durable work
        cls,
        tasks: TaskStore,
        saved_context: ContextStore,
        worker: Worker,
        create_window: Callable[[WorkAgent], ConversationOutput],
        *,
        on_snapshot: Callable[[WorkSnapshot], None],
        on_done: Callable[[], None],
        report_error: Callable[[str], None],
        on_start: Callable[[], None] | None = None,
        context: Callable[[], ContextSnapshot] | None = None,
        clock: Callable[[], float] = time.time,
        identity: Callable[[], str] = _identity,
    ) -> WorkAgent:
        service = WorkService(tasks, saved_context, worker)
        return cls(
            service,
            create_window,
            on_snapshot=on_snapshot,
            on_done=on_done,
            report_error=report_error,
            on_start=on_start,
            context=context,
            clock=clock,
            identity=identity,
        )

    @property
    def window(self) -> ConversationOutput | None:
        return self._state.get().window

    @property
    def conversation(self) -> str | None:
        return self._state.get().conversation

    @property
    def displayed(self) -> Task | None:
        return self._state.get().displayed

    @property
    def rejected_input(self) -> tuple[str, str] | None:
        return self._state.get().rejected_input

    def start_worker(self) -> None:
        """Begin observation after the application has composed its callbacks."""
        with self._lock:
            if self._state.get().thread is None and not self._closing.is_set():
                thread = threading.Thread(target=self._observe, name="work frontend", daemon=True)
                self._state.set(replace(self._state.get(), thread=thread))
                thread.start()

    def _source(self, profile: Profile = RequestKind.GENERAL) -> RequestSource:
        if (conversation := self.conversation) is None:
            conversation = self.identity()
            self._state.set(replace(self._state.get(), conversation=conversation))
        return RequestSource(conversation, profile)

    def _enqueue(self, job: Issued | IdentifiedSubmission | Observe) -> bool:
        with self._lock:
            if self._closing.is_set() or self._state.get().ordinary_pending >= 256:
                return False
            try:
                self._jobs.put_nowait(job)
            except queue.Full:
                return False
            self._state.set(replace(self._state.get(), ordinary_pending=self._state.get().ordinary_pending + 1))
            self._state.set(replace(self._state.get(), sequence=self._state.get().sequence + 1))
            match job:
                case IdentifiedSubmission() | Issued(command=Submit()):
                    self._state.set(
                        replace(self._state.get(), pending=frozendict({**self._state.get().pending, job.identity: job.source.conversation_id}))
                    )
                    self._state.set(replace(self._state.get(), last_submission_source=job.source.conversation_id))
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
            case Submit() if self.context is not None:
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
            try:
                self._panel().problem(str(error))
            except Exception:
                self.report_error(traceback.format_exc())
            return
        if reveal:
            try:
                self._panel().show()
            except Exception:
                self.report_error(traceback.format_exc())

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
            case SelfReview():
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
            groups = dict(self._state.get().watch_groups)
            if watched:
                groups[owner] = watched
            else:
                groups.pop(owner, None)
            if len(groups) > 16:
                raise ValueError("At most 16 work views can retain tasks at once.")
            combined = frozenset(identity for group in groups.values() for identity in group)
            if len(combined) > 512:
                raise ValueError("At most 512 saved tasks can be watched across all work views.")
            self._state.set(replace(self._state.get(), watch_groups=frozendict(groups), watched=combined))
            self._wake.set()

    def snapshot(self) -> WorkSnapshot:
        """Read the latest immutable committed projection without journal I/O."""
        with self._lock:
            return self._state.get().snapshot

    def voice(self, text: str) -> None:
        if self.window is None or not self.window.reply_by_voice(text):
            self.start(text)

    def running(self) -> bool:
        with self._lock:
            return (self.conversation is not None and self.conversation in self._state.get().pending.values()) or any(
                active(task) and in_conversation(task, self.conversation) for task in self._state.get().snapshot.tasks
            )

    def _panel(self) -> ConversationOutput:
        with self._lock:
            if (window := self.window) is None:
                window = self._create_window(self)
                self._state.set(replace(self._state.get(), window=window))
            return window

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
            if self._closing.is_set() or self.conversation is None:
                return
            if self._state.get().last_submission_source != self.conversation and not any(
                in_conversation(task, self.conversation) and not terminal(task.state) for task in self._state.get().snapshot.tasks
            ):
                return
            stop = StopConversation(self.conversation, self._state.get().sequence)
            if stop == self._state.get().last_stop:
                return
            self._jobs.put_nowait(stop)
            self._state.set(replace(self._state.get(), last_stop=stop))
            self._wake.set()
            if self.window is not None:
                try:
                    self.window.stopping()
                except Exception:
                    self.report_error(traceback.format_exc())

    def new_conversation(self) -> bool:
        with self._lock:
            if self._closing.is_set():
                return False
            was_running = self._state.get().reported_running
            self._state.set(replace(self._state.get(), reported_running=False))
            new_conversation = self.identity()
            self._state.set(replace(self._state.get(), conversation=new_conversation))
            self._state.set(replace(self._state.get(), displayed=None, live=None))
            self._state.set(replace(self._state.get(), rejected_input=None))
            self._state.set(replace(self._state.get(), settled=frozendict(), queued=frozenset()))
            if self.window is not None:
                try:
                    self.window.reset()
                except Exception:
                    self.report_error(traceback.format_exc())
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
                try:
                    self.window.close()
                except Exception:
                    self.report_error(traceback.format_exc())
            if self._state.get().thread is None:
                # Commands may have arrived during composition, before startup.
                thread = threading.Thread(target=self._observe, name="work frontend shutdown", daemon=True)
                self._state.set(replace(self._state.get(), thread=thread))
                thread.start()

    def wait_closed(self, timeout: float | None = None) -> bool:
        return self._closed.wait(timeout)

    def _reply(self, task_id: str, request_id: str, reply: TextAnswer) -> bool:
        with self._lock:
            task = next((task for task in self._state.get().snapshot.tasks if task.id == task_id), None)
            request = requested(task) if task is not None else None
            if request is None or request.id != request_id:
                return False
            return self._enqueue(Issued(AnswerTask(task_id, request_id, reply), self.identity(), self._source(), None))

    def _request(self, task: Task, message: agent_session.AgentRequest) -> None:
        self._panel().request_input(message, lambda reply: self._reply(task.id, message.id, reply))

    def _clear_input(self) -> None:
        if self.window is not None:
            self.window.withdraw_input()

    def _display(self, task: Task) -> None:
        match task.source.profile:
            case FeedHandoff(item, title):
                initiation = Initiation.AUTOMATIC if source_is_automatic(task) else Initiation.REQUESTED
                source: FeedRequest | None = FeedRequest(item, title, initiation=initiation)
            case _:
                source = None
        previous = self.displayed
        if task == previous:
            return
        window = self._panel()
        if previous is None or previous.id != task.id:
            self._clear_input()
            window.begin(source.title if source is not None else task.prompt, queued=task.id in self._state.get().queued, source=source)
            self._state.set(replace(self._state.get(), queued=self._state.get().queued - {task.id}))
            new_live = window.updates()
            self._state.set(replace(self._state.get(), live=new_live))
        elif new_turn(previous, task):
            self._clear_input()
            if active(task):
                window.finish()
                window.begin(f"Continue: {task.title}", source=source)
                new_live = window.updates()
                self._state.set(replace(self._state.get(), live=new_live))
        self._state.set(replace(self._state.get(), displayed=task))
        if task.checkpoint is not None and (previous is None or previous.checkpoint != task.checkpoint):
            window.step(task.checkpoint.summary)
        self._display_status(task)

    def _display_status(self, task: Task) -> None:
        window = self._panel()
        if requested(task) is None:
            self._clear_input()
        match task.state:
            case TaskStatus.READY:
                window.step("Queued.")
            case Running():
                pass
            case Interrupted(_, reason):
                window.step(f"Recovering interrupted work: {reason}")
            case Waiting(reason):
                self._display_waiting(task, reason)
            case Completed(result, _):
                window.done(result)
            case Failed(reason):
                if source_is_automatic(task):
                    window.say(reason)
                else:
                    window.problem(reason)
            case TaskStatus.CANCELLED:
                window.done("Stopped.")
            case TaskStatus.PAUSED:
                window.say("Paused. Resume this task from Work.")
            case _:
                assert_never(task.state)
        if turn_ended(task):
            window.finish()
            self._state.set(replace(self._state.get(), queued=frozenset()))

    def _display_waiting(self, task: Task, reason: WaitReason) -> None:
        match reason:
            case Question() as question:
                self._request(task, agent_session.AgentRequest(question, question.detail, task.updated_at))
            case Blocked(explanation):
                if source_is_automatic(task):
                    self._panel().say(explanation)
                else:
                    self._panel().problem(explanation)
            case Until(_, explanation):
                self._panel().say(f"Waiting: {explanation}")
            case _:
                assert_never(reason)

    def _publish(self, snapshot: WorkSnapshot) -> None:
        """Publish durable state before attempting any presentation effect."""
        with self._lock:
            if self._closing.is_set():
                return
            was_running = self._state.get().reported_running
            self._state.set(replace(self._state.get(), snapshot=snapshot))
            if self.conversation is None:
                new_conversation = next(
                    (task.source.conversation_id for task in snapshot.tasks if not terminal(task.state)),
                    None,
                )
                self._state.set(replace(self._state.get(), conversation=new_conversation))
            is_running = self.running()
            self._state.set(replace(self._state.get(), reported_running=is_running))
        self.on_snapshot(snapshot)
        if not was_running and is_running and self.on_start is not None:
            self.on_start()
        elif was_running and not is_running:
            self.on_done()
        try:
            self._present(snapshot)
        except Exception:
            # A failed view must not change journal/transport availability or
            # prevent canvas intake. Retry presentation on the next observation.
            with self._lock:
                self._state.set(replace(self._state.get(), displayed=None, live=None))
            self.report_error(traceback.format_exc())

    def _present(self, snapshot: WorkSnapshot) -> None:
        with self._lock:
            if self._closing.is_set():
                return
            self._restore_reply(snapshot)
            tasks = sorted((task for task in snapshot.tasks if in_conversation(task, self.conversation)), key=chronological)
            task_ids = {task.id for task in tasks}
            new_settled = frozendict((identity, revision) for identity, revision in self._state.get().settled.items() if identity in task_ids)
            self._state.set(replace(self._state.get(), settled=new_settled))
            if not self._state.get().started:
                # Finished work is history at startup, not news: presenting it
                # replayed every old blocked or failed task as a warning balloon
                # and beep each time Workspace restarted.
                self._state.set(replace(self._state.get(), started=True))
                finished = ((task.id, task.revision) for task in tasks if not active(task))
                self._state.set(replace(self._state.get(), settled=frozendict({**self._state.get().settled, **dict(finished)})))
            if self.displayed is not None and self.displayed.id not in task_ids:
                self._state.set(replace(self._state.get(), displayed=None, live=None))
                self._clear_input()
                if self.window is not None:
                    self.window.finish()
                self._state.set(replace(self._state.get(), queued=frozenset()))
            selected = next((task for task in tasks if self.displayed is not None and task.id == self.displayed.id), None)
            candidates = [task for task in tasks if self._state.get().settled.get(task.id) != task.revision]
            while selected is not None or candidates:
                selected = selected if selected is not None else candidates[0]
                self._display(selected)
                if active(selected):
                    break
                self._state.set(replace(self._state.get(), settled=frozendict({**self._state.get().settled, selected.id: selected.revision})))
                candidates = [task for task in candidates if task.id != selected.id]
                selected = None
                self._state.set(replace(self._state.get(), displayed=None))
            for task in tasks:
                if (
                    active(task)
                    and (self.displayed is None or task.id != self.displayed.id)
                    and task.id not in self._state.get().queued
                    and len(self._state.get().queued) < 100
                ):
                    self._panel().queued(task.prompt)
                    self._state.set(replace(self._state.get(), queued=self._state.get().queued | {task.id}))

    def _restore_reply(self, snapshot: WorkSnapshot) -> None:
        if (rejected := self.rejected_input) is None:
            return
        task_id, request_id = rejected
        self._state.set(replace(self._state.get(), rejected_input=None))
        task = next((task for task in snapshot.tasks if task.id == task_id), None)
        request = requested(task) if task is not None else None
        # A failure is only recorded for the displayed task, and publishing restores it before redisplaying.
        if self.window is not None and task is not None and request is not None and request.id == request_id:
            self.window.withdraw_input()
            self.window.problem("That reply could not be saved. Please answer the current request again.")
            self._request(task, agent_session.AgentRequest(request, request.detail, task.updated_at))

    def _observed_ids(self) -> tuple[frozenset[str], frozenset[str]]:
        with self._lock:
            watched = self._state.get().watched
            # The displayed task owns any projected request; its reply needs that task observed.
            if self.displayed is not None and requested(self.displayed) is not None:
                watched = watched | {self.displayed.id}
            return watched, frozenset(self._state.get().pending)

    def _publish_unavailable(self) -> None:
        watched, pending = self._observed_ids()
        with self._lock:
            if self._closing.is_set():
                return
            snapshot = self._service.unavailable(self._state.get().snapshot, watched, pending)
            self._state.set(replace(self._state.get(), snapshot=snapshot))
        self.on_snapshot(snapshot)

    def deliver(self, run: RunRef, event: PresentationEvent) -> None:
        """A run's live update, from the worker's execution thread; the observer presents it.

        Ownership is decided here, when the run speaks: by the time the observer
        reads the journal the run may have finished, which keeps its output, or
        been superseded, which already dropped it.
        """
        try:
            task = self._service.tasks.get(run.task_id)
        except Exception:
            self.report_error(traceback.format_exc())
            return
        if task is not None and owns(task, run):
            self._events.put((run, event))
            self._wake.set()

    def _log(self, run: RunRef, event: PresentationEvent) -> bool:
        """Present the event if its run owns the displayed task; False leaves it unpresented."""
        try:
            return self._present_log(run, event)
        except Exception:
            self.report_error(traceback.format_exc())
            return True

    def _present_log(self, run: RunRef, event: PresentationEvent) -> bool:
        with self._lock:
            task = self.displayed
            if task is None or not owns(task, run) or self.window is None or self._closing.is_set():
                return False
            match event:
                case contracts.presentation.Progress(text):
                    self.window.step(text)
                    return True
                case contracts.presentation.Said(text, _):
                    self.window.say(text)
                    return True
                case contracts.presentation.Problem(text, _):
                    if source_is_automatic(task):
                        self.window.say(text)
                    else:
                        self.window.problem(text)
                    return True
                case contracts.presentation.Answer(text=text) | contracts.presentation.ReasoningSummary(text=text):
                    live = self._state.get().live
                    if live is None:
                        return True
                case contracts.presentation.ToolActivity():
                    if (live := self._state.get().live) is not None:
                        live(event)
                    return True
                case _:
                    assert_never(event)
        # The output adapter owns prose preparation outside the frontend lock.
        # The captured producer is fenced to its session generation.
        live(event)
        return True

    def _take_events(self) -> tuple[tuple[RunRef, PresentationEvent], ...]:
        return tuple(_drained(self._events, 512))

    def _jobs_ready(self) -> tuple[Observe, ...]:
        return tuple(self._applied_jobs())

    def _applied_jobs(self) -> Iterator[Observe]:
        """Apply up to 64 queued jobs in order, yielding the observations for the caller to run."""
        for job in _drained(self._jobs, 64):
            match job:
                case StopConversation():
                    pass
                case Issued() | IdentifiedSubmission() | Observe():
                    with self._lock:
                        self._state.set(replace(self._state.get(), ordinary_pending=self._state.get().ordinary_pending - 1))
            try:
                match job:
                    case Issued() | IdentifiedSubmission():
                        self._service.apply(job, at=self.clock())
                    case StopConversation(conversation_id):
                        self._service.stop_conversation(conversation_id, at=self.clock())
                    case Observe():
                        pass
                    case _:
                        assert_never(job)
            except Exception as error:
                self._service.failed(str(error) or "The work request could not be saved.")
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
                            self._state.set(
                                replace(
                                    self._state.get(),
                                    pending=frozendict((key, value) for key, value in self._state.get().pending.items() if key != job.identity),
                                )
                            )
                        case StopConversation() if self._state.get().last_stop == job:
                            self._state.set(replace(self._state.get(), last_stop=None))
                        case _:
                            pass
            if isinstance(job, Observe):
                yield job

    def _record_failure(self, job: Issued | IdentifiedSubmission) -> None:
        watched, _ = self._observed_ids()
        self._service.submission_failed(job, self._service.problem, watched=watched)
        match job:
            case Issued(command=AnswerTask(task_id=task_id, request_id=request_id)) as reply:
                self._service.reply_failed(reply, self._service.problem, watched=watched)
                with self._lock:
                    if self.displayed is not None and self.displayed.id == task_id:
                        self._state.set(replace(self._state.get(), rejected_input=(task_id, request_id)))
            case _:
                pass

    def _observe(self) -> None:
        try:
            while True:
                observed = self._jobs_ready()
                try:
                    if not self._closing.is_set():
                        # Events taken before the journal read were said before the
                        # state it shows: present those of the displayed run first,
                        # and those of a run this snapshot first displays after it.
                        events = self._take_events()
                        watched, pending = self._observed_ids()
                        snapshot = self._service.snapshot(watched=watched, pending=pending)
                        later = tuple((run, event) for run, event in events if not self._log(run, event))
                        self._publish(snapshot)
                        for run, event in later:
                            self._log(run, event)
                except Exception as error:
                    self._service.failed(str(error) or "Work could not be refreshed.")
                    self._publish_unavailable()
                    self.report_error(traceback.format_exc())
                finally:
                    for observation in observed:
                        observation.completed.set()
                if self._closing.is_set() and self._jobs.empty():
                    break
                if self._jobs.empty() and self._events.empty():
                    self._wake.wait(0.25)
                    self._wake.clear()
        finally:
            self._closed.set()
