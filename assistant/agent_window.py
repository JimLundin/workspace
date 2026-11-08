"""The agent session's thread-safe connection to the shared assistant UI thread.

Only immutable snapshots cross into the view. Model work and waiting for user
input stay on worker threads; notifications and history stay on the UI thread.
"""

import contextlib
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Protocol

from cell import Cell
from contracts.agent_session import (
    AgentRequest,
    Begin,
    Cancelled,
    CanvasAttention,
    CanvasNotice,
    Enqueued,
    Event,
    RecordingUpdated,
    Resolution,
    SelectAttention,
    Session,
    Snapshot,
    StopRequested,
    transition,
)
from contracts.attention import AttentionSnapshot
from contracts.canvas_activity import CanvasRequest
from contracts.feed_origin import FeedRequest
from contracts.presentation import Done, Finished, LiveMessage, Problem, Progress, Said
from contracts.publication import Post, Unavailable, ViewPublication
from contracts.recording_state import RecordingAction, RecordingState
from contracts.task import TextAnswer


class View(Protocol):
    """Used only on the UI thread."""

    def render(self, state: Snapshot) -> None: ...
    def show(self, *, focus: bool = False) -> None: ...
    def close(self) -> None: ...


class InputState(Enum):
    SHOWN = auto()
    # A reply was accepted; work owns it until it withdraws or restores the request.
    SUBMITTED = auto()


@dataclass(frozen=True, slots=True)
class _Projected:
    """The one durable request this view projects, and where its parsed reply goes."""

    message: AgentRequest
    reply: Callable[[TextAnswer], bool]
    state: InputState


@dataclass(frozen=True, slots=True)
class _Callbacks:
    """The effect owners this conversation drives, fixed when it is composed."""

    stop: Callable[[], None]
    problem: Callable[[str], None] | None
    reset: Callable[[], bool] | None
    submit: Callable[[str], None] | None
    waiting: Callable[[bool], None] | None
    recording: Callable[[RecordingAction], None] | None


@dataclass(frozen=True, slots=True)
class _Conversation:
    session: Session
    input: _Projected | None = None
    """The request shown in the view, until it is answered or cancelled."""


def _new_session() -> Session:
    return Session(identity=uuid.uuid4().hex)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class AgentWindow:
    # This conversation owns one view, request lifetime and snapshot stream.
    # Its independent interaction callbacks are composed together here so a
    # caller can connect the actual effect owners before the first render.
    _callbacks: _Callbacks
    publication: ViewPublication[View]
    _log: Callable[[str], None]
    _conversation: Cell[_Conversation] = field(default_factory=lambda: Cell(_Conversation(_new_session())), init=False, repr=False)
    """Replaced whole under the lock."""
    lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _started: float = field(default_factory=time.monotonic, init=False)

    @classmethod
    def open(  # noqa: PLR0913 - one callback per window event
        cls,
        stop: Callable[[], None],
        *,
        post: Post,
        create_view: Callable[[AgentWindow], View],
        on_problem: Callable[[str], None] | None = None,
        on_reset: Callable[[], bool] | None = None,
        on_submit: Callable[[str], None] | None = None,
        on_waiting: Callable[[bool], None] | None = None,
        on_recording: Callable[[RecordingAction], None] | None = None,
        log: Callable[[str], None],
    ) -> AgentWindow:
        # The publication creates and renders the view only once posted, after the window below exists.
        def create() -> View:
            return create_view(window)

        def render(view: View | None) -> None:
            window._render(view)

        callbacks = _Callbacks(stop, on_problem, on_reset, on_submit, on_waiting, on_recording)
        window = cls(callbacks, ViewPublication(post, create, render, log=log), log)
        window.publication.post(window._prepare)
        return window

    @property
    def state(self) -> Session:
        return self._conversation.get().session

    @property
    def waiting(self) -> bool:
        with self.lock:
            return self.state.waiting

    def snapshot(self) -> Snapshot:
        """Observe the current immutable session under its owner lock."""
        with self.lock:
            return self.state

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
                self.problem("The agent session couldn't reach its view. Reopen Agent session to retry; details are in assistant.log.")
                return None
            case _:
                if created:
                    self._log(f"Agent conversation view ready in {time.monotonic() - self._started:.2f}s.")
                return opened

    def _render(self, view: View | None) -> None:
        with self.lock:
            state = self.state
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
            new_state = transition(self.state, event)
            self._conversation.set(replace(self._conversation.get(), session=new_state))
            waiting = self.state.waiting
            self.publication.changed()
        self._waiting_changed(before=was_waiting, after=waiting)

    def show(self, *, focus: bool = False) -> None:
        def reveal() -> None:
            if (view := self._open()) is not None:
                view.show(focus=focus)

        self.publication.post(reveal)

    def submit(self, text: str) -> bool:
        if not (text := text.strip()):
            return False
        with self.lock:
            if self.publication.closed or self.state.stopping:
                return False
            request = self.state.request
        if request is not None:
            return self.respond(request.id, TextAnswer(text))
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
        with contextlib.suppress(ValueError):
            self.respond(request.id, TextAnswer(text.strip()))
        return True

    def request_input(self, message: AgentRequest, reply: Callable[[TextAnswer], bool]) -> None:
        """Project an exact durable request without starting a waiting thread."""
        with self.lock:
            if self.publication.closed:
                return
            old = self._conversation.get().input
            if old is not None and old.message.id == message.id:
                if old.state is not InputState.SUBMITTED:
                    new_input = replace(old, reply=reply)
                    self._conversation.set(replace(self._conversation.get(), input=new_input))
                return
            new_input = _Projected(message, reply, InputState.SHOWN)
            self._conversation.set(replace(self._conversation.get(), input=new_input))
            was_waiting = self.state.waiting
            if old is not None:
                new_state = transition(self.state, Resolution(old.message.id, Cancelled()))
                self._conversation.set(replace(self._conversation.get(), session=new_state))
            new_state = transition(self.state, message)
            self._conversation.set(replace(self._conversation.get(), session=new_state))
            waiting = self.state.waiting
            self.publication.changed()
        self._waiting_changed(before=was_waiting, after=waiting)

    def withdraw_input(self) -> None:
        """Remove the projected request; durable state stays owned by work."""
        with self.lock:
            request = self._conversation.get().input
            if request is None:
                return
            self._conversation.set(replace(self._conversation.get(), input=None))
            was_waiting = self.state.waiting
            new_state = transition(self.state, Resolution(request.message.id, Cancelled()))
            self._conversation.set(replace(self._conversation.get(), session=new_state))
            waiting = self.state.waiting
            self.publication.changed()
        self._waiting_changed(before=was_waiting, after=waiting)

    def respond(self, identity: str, reply: TextAnswer, *, expected_session: str | None = None) -> bool:
        """Admit a reply to this request, optionally fenced to a captured session.

        Current-view actions identify the current request alone; delayed canvas
        replies also supply their saved session. Check that identity when admitting
        the request, then call its captured reply owner outside the session lock.
        """
        with self.lock:
            if expected_session is not None and self.state.identity != expected_session:
                return False
            request = self._conversation.get().input
            if self.publication.closed or request is None or request.message.id != identity or request.state is InputState.SUBMITTED:
                return False
            submitted = replace(request, state=InputState.SUBMITTED)
            self._conversation.set(replace(self._conversation.get(), input=submitted))
        accepted = False
        try:
            accepted = request.reply(reply)
        finally:
            if not accepted:
                with self.lock:
                    if self._conversation.get().input is submitted:
                        self._conversation.set(replace(self._conversation.get(), input=request))
        if not accepted:
            return False
        with self.lock:
            if self._conversation.get().input is not submitted:
                return True
            was_waiting = self.state.waiting
            new_state = transition(self.state, Resolution(identity, reply))
            self._conversation.set(replace(self._conversation.get(), session=new_state))
            waiting = self.state.waiting
            self.publication.changed()
        self._waiting_changed(before=was_waiting, after=waiting)
        return True

    def notify_canvas(self, title: str, target: str) -> None:
        self._event(CanvasNotice(title, target, time.time()))

    def canvas_attention(self, observation: AttentionSnapshot) -> None:
        if self.snapshot().attention != observation:
            self._event(CanvasAttention(observation))

    def select_attention(self, request: CanvasRequest | None) -> None:
        if self.snapshot().selected_request != request:
            self._event(SelectAttention(request))

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
            self._conversation.set(replace(self._conversation.get(), input=None))
            recording = self.state.recording
            new_state = Session(identity=uuid.uuid4().hex)
            self._conversation.set(replace(self._conversation.get(), session=new_state))
            if recording.phase not in ("idle", "saved", "interrupted"):
                new_state = transition(self.state, RecordingUpdated(recording, time.time()))
                self._conversation.set(replace(self._conversation.get(), session=new_state))
            self.publication.changed()

    def stop_recording(self) -> None:
        if self._callbacks.recording is not None:
            self._callbacks.recording("stop")

    def recording(self, state: RecordingState) -> None:
        self._event(RecordingUpdated(state, time.time()))

    def stopping(self) -> None:
        self.withdraw_input()
        self._event(StopRequested())

    def close(self) -> None:
        self.publication.close()
        with self.lock:
            self._conversation.set(replace(self._conversation.get(), input=None))
