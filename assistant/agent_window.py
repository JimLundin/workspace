"""The agent session's thread-safe connection to the shared assistant UI thread.

Only immutable snapshots cross into the view. Model work and waiting for user
input stay on worker threads; notifications and history stay on the UI thread.
"""

import contextlib
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum, auto
from typing import Final, Protocol

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
from automation.presentation import Done, Finished, LiveMessage, Problem, Progress, Said
from automation.task import Approval, ApprovalDecision, Question, Reply, TextAnswer
from usage import DIRECTORY

VIEW_LOG: Final = DIRECTORY / "agent-ui.log"


def log_view(text: str) -> None:
    with contextlib.suppress(OSError):
        VIEW_LOG.parent.mkdir(parents=True, exist_ok=True)
        with VIEW_LOG.open("a", encoding="utf-8") as output:
            output.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")


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


class AgentWindow:
    __slots__ = (
        "__weakref__",
        "_create_view",
        "_input",
        "_pending",
        "_post",
        "_view",
        "closed",
        "closed_ready",
        "lock",
        "on_problem",
        "on_recording",
        "on_reset",
        "on_snapshot",
        "on_submit",
        "on_waiting",
        "on_work",
        "ready",
        "started",
        "state",
        "stop",
    )

    def __init__(
        self,
        stop: Callable[[], None],
        *,
        post: Callable[[Callable[[], None]], None],
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
        self.stop, self.on_problem, self.on_reset, self.on_submit = stop, on_problem, on_reset, on_submit
        self.on_waiting = on_waiting
        self.on_recording = on_recording
        self.on_work = on_work
        self.on_snapshot: Callable[[Snapshot], None] | None = on_snapshot
        self._input: _Projected | None = None
        self.state = Session(identity=uuid.uuid4().hex)
        self.lock = threading.RLock()
        self.ready = threading.Event()
        self.closed_ready = threading.Event()
        self.started = time.monotonic()
        self.closed = self._pending = False
        self._post, self._create_view = post, create_view
        self._view: View | None = None
        self._post(self._create)

    @property
    def waiting(self) -> bool:
        with self.lock:
            return self.state.waiting

    def _create(self) -> None:
        if self.closed or self._view is not None:
            return
        try:
            self._view = self._create_view(self)
            self._render()
            self.ready.set()
            log_view(f"Agent conversation view ready in {time.monotonic() - self.started:.2f}s.")
        except Exception:
            if self._view is not None:
                with contextlib.suppress(Exception):
                    self._view.close()
                self._view = None
            log_view(traceback.format_exc())
            self.problem("The agent panel couldn't open. Reopen Agent session to retry; details are in agent-ui.log.")

    def _render(self) -> None:
        with self.lock:
            self._pending = False
            state = self.state
        if not self.closed:
            if self.on_snapshot is not None:
                self.on_snapshot(state)
            if self._view is not None:
                self._view.render(state)

    def _changed(self) -> None:
        if not self._pending:
            self._pending = True
            self._post(self._render)

    def _event(self, event: Event) -> None:
        with self.lock:
            if self.closed:
                return
            was_waiting = self.state.waiting
            self.state = transition(self.state, event)
            waiting = self.state.waiting
            self._changed()
        if was_waiting != waiting and self.on_waiting is not None:
            self.on_waiting(waiting)

    def show(self, *, focus: bool = False) -> None:
        def reveal() -> None:
            if not self.closed:
                self._create()
                if self._view is not None:
                    self._view.show(focus=focus)

        self._post(reveal)

    def open_inbox(self) -> None:
        """Schedule current inbox access with native view creation on the UI thread."""

        def reveal() -> None:
            if not self.closed:
                self._create()
                if self._view is not None:
                    self._view.open_inbox()

        self._post(reveal)

    def submit(self, text: str) -> bool:
        if not (text := text.strip()):
            return False
        with self.lock:
            if self.closed or self.state.stopping:
                return False
            request = self.state.request
        match request:
            case AgentRequest(request=Question(id=identity)):
                return self.respond(identity, TextAnswer(text))
            case _:
                pass
        if self.on_submit is None:
            return False
        self.on_submit(text)
        return True

    def reply_by_voice(self, text: str) -> bool:
        """Consume a spoken reply to the pending request, or leave it as a task.

        Unrecognized or racing replies stay out of the task queue.
        """
        with self.lock:
            if self.closed or self.state.stopping:
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
            if self.closed:
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
            self._changed()
        if was_waiting != waiting and self.on_waiting is not None:
            self.on_waiting(waiting)

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
            self._changed()
        if was_waiting != waiting and self.on_waiting is not None:
            self.on_waiting(waiting)

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
            if self.closed or request is None or request.message.id != identity or request.state is InputState.SUBMITTED:
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
            self._changed()
        if was_waiting != waiting and self.on_waiting is not None:
            self.on_waiting(waiting)
        return True

    def show_work(self) -> None:
        if self.on_work is not None:
            self.on_work()

    def notify_canvas(self, title: str, target: str) -> None:
        self._event(CanvasNotice(title, target, time.time()))

    def settle_canvas(self, targets: frozenset[str]) -> None:
        self._event(CanvasSettled(targets))

    def new(self) -> bool:
        with self.lock:
            if self.closed or self.state.busy:
                return False
        return self.on_reset() if self.on_reset is not None else False

    def begin(self, task: str, stop: Callable[[], None], *, queued: bool = False, source: FeedRequest | None = None) -> None:
        self.stop = stop
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
        if self.on_problem is not None:
            self.on_problem(text)

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
            self._changed()

    def recording(self, state: RecordingState) -> None:
        self._event(RecordingUpdated(state, time.time()))

    def stopping(self) -> None:
        self.withdraw_input()
        self._event(StopRequested())

    def all_text(self) -> str:
        with self.lock:
            return self.state.all_text()

    def close(self) -> None:
        with self.lock:
            self.closed = True
            self._input = None
        self.ready.clear()

        def destroy() -> None:
            try:
                if self._view is not None:
                    self._view.close()
                    self._view = None
            finally:
                self.closed_ready.set()

        self._post(destroy)
