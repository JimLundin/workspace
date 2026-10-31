"""The agent session's thread-safe connection to the shared assistant UI thread.

Only immutable snapshots cross into the view. Model work and waiting for user
input stay on worker threads; notifications and history stay on the UI thread.
"""

import contextlib
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum, auto
from typing import Protocol

from assistant.agent_session import (
    AgentRequest,
    Begin,
    Cancelled,
    CanvasNotice,
    CanvasSettled,
    Enqueued,
    Event,
    RecordingUpdated,
    Resolution,
    Session,
    Snapshot,
    StopRequested,
    transition,
)
from assistant.feed_origin import FeedRequest
from assistant.recording_state import RecordingAction, RecordingState
from assistant.view_publication import Post, Unavailable, ViewPublication, log_view
from automation.presentation import Done, Finished, LiveMessage, Problem, Progress, Said
from automation.task import Approval, ApprovalDecision, Question, Reply, TextAnswer


class View(Protocol):
    """Used only on the UI thread."""

    def render(self, state: Snapshot) -> None: ...
    def show(self, *, focus: bool = False) -> None: ...
    def open_inbox(self) -> None: ...
    def close(self) -> None: ...


class InputState(Enum):
    SHOWN = auto()
    # A native view acknowledged that this exact approval preview is visible.
    PRESENTED = auto()
    # A reply was accepted; work owns it until it withdraws or restores the request.
    SUBMITTED = auto()


@dataclass(frozen=True, slots=True)
class _Projected:
    """The one durable request this view projects, and where its parsed reply goes."""

    message: AgentRequest
    reply: Callable[[Reply], bool]
    state: InputState


def spoken_decision(text: str) -> ApprovalDecision | None:
    """Only the complete utterance "approve" or "decline" decides an approval."""
    match text.strip().casefold().rstrip(".!?").strip():
        case "approve":
            return ApprovalDecision.APPROVED
        case "decline":
            return ApprovalDecision.DECLINED
        case _:
            return None


@dataclass(frozen=True, slots=True)
class _Callbacks:
    """The effect owners this conversation drives, fixed when it is composed."""

    stop: Callable[[], None]
    problem: Callable[[str], None] | None
    reset: Callable[[], bool] | None
    submit: Callable[[str], None] | None
    waiting: Callable[[bool], None] | None
    recording: Callable[[RecordingAction], None] | None
    work: Callable[[], None] | None
    snapshot: Callable[[Snapshot], None] | None


class AgentWindow:
    __slots__ = (
        "__weakref__",
        "_callbacks",
        "_input",
        "_started",
        "lock",
        "publication",
        "state",
    )

    def __init__(
        self,
        stop: Callable[[], None],
        *,
        post: Post,
        create_view: Callable[[AgentWindow], View],
        on_problem: Callable[[str], None] | None = None,
        on_reset: Callable[[], bool] | None = None,
        on_submit: Callable[[str], None] | None = None,
        on_waiting: Callable[[bool], None] | None = None,
        on_recording: Callable[[RecordingAction], None] | None = None,
        on_work: Callable[[], None] | None = None,
        on_snapshot: Callable[[Snapshot], None] | None = None,
    ) -> None:
        # This conversation owns one view, request lifetime and snapshot stream.
        # Its independent interaction callbacks are composed together here so a
        # caller can connect the actual effect owners before the first render.
        self._callbacks = _Callbacks(stop, on_problem, on_reset, on_submit, on_waiting, on_recording, on_work, on_snapshot)
        self._input: _Projected | None = None
        self.state = Session(identity=uuid.uuid4().hex)
        self.lock = threading.RLock()
        self._started = time.monotonic()
        self.publication: ViewPublication[View] = ViewPublication(post, lambda: create_view(self), self._render)
        self.publication.post(self._prepare)

    @property
    def waiting(self) -> bool:
        with self.lock:
            return self.state.waiting

    def _prepare(self) -> None:
        self._open()

    def _open(self) -> View | None:
        """UI thread: the conversation view, created on first use."""
        created = not self.publication.ready.is_set()
        opened = self.publication.opened()
        match opened:
            case Unavailable.CLOSED:
                return None
            case Unavailable.FAILED:
                self.problem("The agent panel couldn't open. Reopen Agent session to retry; details are in agent-ui.log.")
                return None
            case _:
                if created:
                    log_view(f"Agent conversation view ready in {time.monotonic() - self._started:.2f}s.")
                return opened

    def _render(self, view: View | None) -> None:
        with self.lock:
            state = self.state
        if self._callbacks.snapshot is not None:
            self._callbacks.snapshot(state)
        if view is not None:
            view.render(state)

    def _waiting_changed(self, *, before: bool, after: bool) -> None:
        if before != after and self._callbacks.waiting is not None:
            self._callbacks.waiting(after)

    def _event(self, event: Event) -> None:
        with self.lock:
            if self.publication.closed:
                return
            was_waiting = self.state.waiting
            self.state = transition(self.state, event)
            waiting = self.state.waiting
            self.publication.changed()
        self._waiting_changed(before=was_waiting, after=waiting)

    def show(self, *, focus: bool = False) -> None:
        def reveal() -> None:
            if (view := self._open()) is not None:
                view.show(focus=focus)

        self.publication.post(reveal)

    def open_inbox(self) -> None:
        """Schedule current inbox access with native view creation on the UI thread."""

        def reveal() -> None:
            if (view := self._open()) is not None:
                view.open_inbox()

        self.publication.post(reveal)

    def submit(self, text: str) -> bool:
        if not (text := text.strip()):
            return False
        with self.lock:
            if self.publication.closed or self.state.stopping:
                return False
            request = self.state.request
        match request:
            case AgentRequest(request=Question(id=identity)):
                return self.respond(identity, TextAnswer(text))
            case _:
                pass
        if self._callbacks.submit is None:
            return False
        self._callbacks.submit(text)
        return True

    def reply_by_voice(self, text: str) -> bool:
        """Consume a spoken reply to the pending request, or leave it as a task.

        Unrecognized or racing replies stay out of the task queue.
        """
        with self.lock:
            if self.publication.closed or self.state.stopping:
                return True
            request = self.state.request
        if request is None:
            return False
        match request.request:
            case Question(id=identity):
                with contextlib.suppress(ValueError):
                    self.respond(identity, TextAnswer(text.strip()))
            case Approval(id=identity):
                decision = spoken_decision(text)
                if decision is not None:
                    self.respond(identity, decision)
                else:
                    self.say("Approval is still waiting. Hold N and say just “approve” or “decline”, then release to send.")
        return True

    def request_input(self, message: AgentRequest, reply: Callable[[Reply], bool]) -> None:
        """Project an exact durable request without starting a waiting thread."""
        with self.lock:
            if self.publication.closed:
                return
            old = self._input
            if old is not None and old.message.id == message.id:
                if old.state is not InputState.SUBMITTED:
                    self._input = replace(old, reply=reply)
                return
            self._input = _Projected(message, reply, InputState.SHOWN)
            was_waiting = self.state.waiting
            if old is not None:
                self.state = transition(self.state, Resolution(old.message.id, Cancelled()))
            self.state = transition(self.state, message)
            waiting = self.state.waiting
            self.publication.changed()
        self._waiting_changed(before=was_waiting, after=waiting)

    def withdraw_input(self) -> None:
        """Remove the projected request; durable state stays owned by work."""
        with self.lock:
            request = self._input
            if request is None:
                return
            self._input = None
            was_waiting = self.state.waiting
            self.state = transition(self.state, Resolution(request.message.id, Cancelled()))
            waiting = self.state.waiting
            self.publication.changed()
        self._waiting_changed(before=was_waiting, after=waiting)

    def input_presented(self, request_id: str) -> None:
        """A native view acknowledges that this exact approval preview is visible."""
        with self.lock:
            match self._input:
                case _Projected(message=AgentRequest(request=Approval(id=identity)), state=InputState.SHOWN) as request if identity == request_id:
                    self._input = replace(request, state=InputState.PRESENTED)
                case _:
                    pass

    def respond(self, identity: str, reply: Reply) -> bool:
        """Route a parsed reply to the exact durable request this view projects."""
        with self.lock:
            request = self._input
            if self.publication.closed or request is None or request.message.id != identity or request.state is InputState.SUBMITTED:
                return False
            if reply is ApprovalDecision.APPROVED and request.state is not InputState.PRESENTED:
                self.say("Open the current action preview before approving it.")
                return False
            submitted = self._input = replace(request, state=InputState.SUBMITTED)
        accepted = False
        try:
            accepted = request.reply(reply)
        finally:
            if not accepted:
                with self.lock:
                    if self._input is submitted:
                        self._input = request
        if not accepted:
            return False
        with self.lock:
            if self._input is not submitted:
                return True
            was_waiting = self.state.waiting
            self.state = transition(self.state, Resolution(identity, reply))
            waiting = self.state.waiting
            self.publication.changed()
        self._waiting_changed(before=was_waiting, after=waiting)
        return True

    def show_work(self) -> None:
        if self._callbacks.work is not None:
            self._callbacks.work()

    def notify_canvas(self, title: str, target: str) -> None:
        self._event(CanvasNotice(title, target, time.time()))

    def settle_canvas(self, targets: frozenset[str]) -> None:
        self._event(CanvasSettled(targets))

    def new(self) -> bool:
        with self.lock:
            if self.publication.closed or self.state.busy:
                return False
        return self._callbacks.reset() if self._callbacks.reset is not None else False

    def stop(self) -> None:
        self._callbacks.stop()

    def begin(self, task: str, *, queued: bool = False, source: FeedRequest | None = None) -> None:
        self._event(Begin(task, time.time(), queued=queued, source=source))

    def queued(self, task: str) -> None:
        self._event(Enqueued(task))

    def step(self, text: str) -> None:
        self._event(Progress(text))

    def say(self, text: str) -> None:
        self._event(Said(text, time.time()))

    def updates(self) -> Callable[[LiveMessage], None]:
        """Bind a producer to this request, so a late stream cannot enter another turn."""
        with self.lock:
            identity, generation = self.state.identity, self.state.generation

        def publish(message: LiveMessage) -> None:
            with self.lock:
                if self.state.identity == identity and self.state.generation == generation:
                    self._event(message)

        return publish

    def problem(self, text: str) -> None:
        self._event(Problem(text, time.time()))
        if self._callbacks.problem is not None:
            self._callbacks.problem(text)

    def done(self, text: str) -> None:
        self._event(Done(text, time.time()))

    def finish(self) -> None:
        self._event(Finished())

    def reset(self) -> None:
        with self.lock:
            self._input = None
            recording = self.state.recording
            self.state = Session(identity=uuid.uuid4().hex)
            if recording.phase not in ("idle", "saved", "interrupted"):
                self.state = transition(self.state, RecordingUpdated(recording, time.time()))
            self.publication.changed()

    def stop_recording(self) -> None:
        if self._callbacks.recording is not None:
            self._callbacks.recording("stop")

    def recording(self, state: RecordingState) -> None:
        self._event(RecordingUpdated(state, time.time()))

    def stopping(self) -> None:
        self.withdraw_input()
        self._event(StopRequested())

    def all_text(self) -> str:
        with self.lock:
            return self.state.all_text()

    def close(self) -> None:
        self.publication.close()
        with self.lock:
            self._input = None
