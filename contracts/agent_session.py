"""Immutable conversation values and pure transitions for the agent timeline.

Clocks, IDs, locking, and widgets belong to the controller and its window.
Replaying the same events against a session always gives the same result.
"""

from dataclasses import dataclass, field, replace
from typing import Literal, assert_never

from contracts import action_text
from contracts.attention import AttentionSnapshot, context_of
from contracts.canvas_activity import CanvasRequest
from contracts.card_actions import OpenCanvas, encode
from contracts.feed_origin import FeedRequest
from contracts.presentation import (
    Answer,
    Done,
    Failed,
    Finished,
    LiveMessage,
    Problem,
    Progress,
    ReasoningSummary,
    Said,
    StreamState,
    Succeeded,
    ToolActivity,
    ToolStatus,
)
from contracts.recording_state import RecordingState
from contracts.task import Question, TextAnswer

type Result = Literal["Ready", "Stopped", "Needs attention"]


@dataclass(frozen=True, slots=True)
class Pending:
    pass


@dataclass(frozen=True, slots=True)
class Cancelled:
    pass


# The timeline row reuses the task's reply; a withdrawn request is cancelled.
type Resolved = TextAnswer | Cancelled
type RequestReply = Pending | Resolved


@dataclass(frozen=True, slots=True)
class ChatMessage:
    speaker: Literal["You", "Workspace", "Error"]
    text: str
    created_at: float
    source: FeedRequest | None = None


@dataclass(frozen=True, slots=True)
class MeetingMessage:
    recording_id: str
    text: str
    created_at: float


@dataclass(frozen=True, slots=True)
class AgentRequest:
    """A durable question in the timeline, with the person's reply."""

    request: Question
    detail: str
    created_at: float
    reply: RequestReply = Pending()

    @property
    def id(self) -> str:
        return self.request.id

    @property
    def text(self) -> str:
        return self.request.text


type Message = ChatMessage | MeetingMessage | AgentRequest | LiveMessage


@dataclass(frozen=True, slots=True)
class Begin:
    text: str
    at: float
    queued: bool = field(default=False, kw_only=True)
    source: FeedRequest | None = None


@dataclass(frozen=True, slots=True)
class Enqueued:
    text: str


@dataclass(frozen=True, slots=True)
class CanvasNotice:
    title: str
    target: str
    at: float


@dataclass(frozen=True, slots=True)
class CanvasAttention:
    observation: AttentionSnapshot


@dataclass(frozen=True, slots=True)
class SelectAttention:
    request: CanvasRequest | None


@dataclass(frozen=True, slots=True)
class StopRequested:
    pass


@dataclass(frozen=True, slots=True)
class Resolution:
    request_id: str
    reply: Resolved


@dataclass(frozen=True, slots=True)
class RecordingUpdated:
    state: RecordingState
    at: float


type Event = (
    Begin
    | Enqueued
    | Progress
    | Said
    | CanvasNotice
    | CanvasAttention
    | SelectAttention
    | Done
    | Problem
    | Finished
    | StopRequested
    | AgentRequest
    | Resolution
    | RecordingUpdated
    | LiveMessage
)


def pending(message: Message) -> bool:
    match message:
        case AgentRequest(reply=Pending()):
            return True
        case ChatMessage() | MeetingMessage() | AgentRequest() | Answer() | ReasoningSummary() | ToolActivity():
            return False
        case _:
            assert_never(message)


@dataclass(frozen=True, slots=True)
class Session:
    identity: str = ""
    generation: int = 0
    messages: tuple[Message, ...] = ()
    queued: tuple[str, ...] = ()
    activity: tuple[str, ...] = ()
    phase: Literal["idle", "running", "stopping"] = "idle"
    status: str = "Ready"
    last_said: str = ""
    result: Result = "Ready"
    recording: RecordingState = field(default_factory=RecordingState)
    attention: AttentionSnapshot = field(default_factory=AttentionSnapshot)
    selected_request: CanvasRequest | None = None

    @property
    def busy(self) -> bool:
        return self.phase != "idle"

    @property
    def stopping(self) -> bool:
        return self.phase == "stopping"

    @property
    def waiting(self) -> bool:
        return any(pending(message) for message in self.messages)

    @property
    def request(self) -> AgentRequest | None:
        """The pending question the person can answer now."""
        for message in self.messages:
            match message:
                case AgentRequest(reply=Pending()):
                    return message
                case _:
                    pass
        return None

    def all_text(self) -> str:
        return "\n\n".join(message_text(message) for message in self.messages)


# The view receives the immutable session itself, without a second state model.
type Snapshot = Session


def notice_text(title: str, target: str) -> str:
    return title + "\n\n[Open on canvas](" + encode(OpenCanvas(target)) + ")"


def transition(state: Session, event: Event) -> Session:
    match event:
        case CanvasAttention(observation):
            messages = tuple(
                message
                for message in state.messages
                if not (
                    isinstance(message, ChatMessage)
                    and message.source is not None
                    and message.source.identity.startswith("canvas:")
                    and message.source.identity.removeprefix("canvas:") in observation.hidden
                )
            )
            return replace(state, attention=observation, messages=messages)
        case SelectAttention(request):
            return replace(state, selected_request=request)
        case CanvasNotice(title, target, at):
            if target.removeprefix("canvas:") in state.attention.hidden:
                return state
            text = notice_text(title, target)
            notice = ChatMessage("Workspace", text, at, FeedRequest("canvas:" + target, title))
            context = context_of(state.attention, target)
            previous = next(
                (
                    index
                    for index, message in enumerate(state.messages)
                    if isinstance(message, ChatMessage)
                    and message.source is not None
                    and message.source.identity.startswith("canvas:")
                    and context_of(state.attention, message.source.identity) == context
                ),
                None,
            )
            messages = (
                (*state.messages, notice)
                if previous is None
                else tuple(notice if index == previous else message for index, message in enumerate(state.messages))
            )
            return replace(state, messages=messages)
        case Begin(text, at, queued=queued, source=source):
            return replace(
                state,
                generation=state.generation + 1,
                phase="running",
                status="Starting…",
                result="Ready",
                last_said="",
                queued=state.queued[1:] if queued else state.queued,
                messages=(*state.messages, ChatMessage("You", text.strip(), at, source)),
            )
        case Enqueued(text):
            return replace(state, queued=(*state.queued, text.strip()))
        case Progress(text):
            text = text.strip()
            status = state.status if state.stopping or state.waiting else "Thinking…" if text == "Waiting for the model..." else "Working…"
            return replace(state, status=status, activity=state.activity if text == "Waiting for the model..." else (*state.activity, text))
        case Said(text, at):
            text = text.strip()
            return replace(state, messages=(*state.messages, ChatMessage("Workspace", text, at)), last_said=text) if text else state
        case Done(text, at):
            text = text.strip()
            messages = (*state.messages, ChatMessage("Workspace", text, at)) if text and text != state.last_said else state.messages
            return replace(state, messages=messages, result="Stopped" if text.startswith("Stopped") else "Ready")
        case Problem(text, at):
            return replace(
                state, messages=(*state.messages, ChatMessage("Error", text.strip(), at)), status="Needs attention", result="Needs attention"
            )
        case Finished():
            return replace(state, phase="idle", queued=(), status=state.result, messages=tuple(interrupt(message) for message in state.messages))
        case StopRequested():
            return replace(state, queued=(), phase="stopping" if state.busy else state.phase, status="Stopping…" if state.busy else state.status)
        case AgentRequest():
            return replace(state, messages=(*state.messages, event), status="Waiting for your reply")
        case Resolution():
            return resolve(state, event)
        case RecordingUpdated(recording, at):
            return update_recording(state, recording, at)
        case Answer() | ReasoningSummary() | ToolActivity():
            return update_live(state, event)
        case _:
            assert_never(event)


def interrupt(message: Message) -> Message:
    match message:
        case Answer(state=StreamState.RUNNING) | ReasoningSummary(state=StreamState.RUNNING):
            return replace(message, state=StreamState.INTERRUPTED)
        case ToolActivity(outcome=ToolStatus.RUNNING):
            return replace(message, outcome=ToolStatus.CANCELLED)
        case _:
            return message


def update_live(state: Session, event: LiveMessage) -> Session:
    """Replace one live row without duplicating it when the final item arrives."""
    if not state.busy:
        return state
    match event:
        # Stopping keeps only completions of tools already running.
        case Answer() | ReasoningSummary() | ToolActivity(outcome=ToolStatus.RUNNING) if state.stopping:
            return state
        case Answer() | ReasoningSummary() | ToolActivity():
            pass
    for index, message in enumerate(state.messages):
        row = _live_row(message, event)
        if row is None:
            continue
        match row:
            case (
                Answer(state=StreamState.COMPLETE | StreamState.INTERRUPTED) | ReasoningSummary(state=StreamState.COMPLETE | StreamState.INTERRUPTED)
            ):
                return state
            case ToolActivity(outcome=Succeeded() | Failed() | ToolStatus.CANCELLED):
                return state
            case Answer() | ReasoningSummary() | ToolActivity():
                pass
        updated = replace(event, created_at=row.created_at)
        if updated == row:
            return state
        messages = (*state.messages[:index], updated, *state.messages[index + 1 :])
        break
    else:
        if state.stopping:
            return state
        messages = (*state.messages, event)
    match event:
        case Answer(text=text, state=StreamState.COMPLETE):
            return replace(state, messages=messages, last_said=text.strip())
        case Answer() | ReasoningSummary() | ToolActivity():
            return replace(state, messages=messages)


def _live_row(message: Message, event: LiveMessage) -> LiveMessage | None:
    """The live row this event updates: the same variant with the same identity."""
    match message, event:
        case (Answer(identity=row) as live, Answer(identity=update)) if row == update:
            return live
        case (ReasoningSummary(identity=row) as live, ReasoningSummary(identity=update)) if row == update:
            return live
        case (ToolActivity(identity=row) as live, ToolActivity(identity=update)) if row == update:
            return live
        case _:
            return None


def resolve(state: Session, event: Resolution) -> Session:
    for index, message in enumerate(state.messages):
        match message:
            case AgentRequest(reply=Pending()) if message.id == event.request_id:
                updated = replace(message, reply=event.reply)
                return replace(
                    state,
                    messages=(*state.messages[:index], updated, *state.messages[index + 1 :]),
                    status="Stopping…" if state.stopping else "Working…",
                )
            case _:
                pass
    return state


def update_recording(state: Session, recording: RecordingState, at: float) -> Session:
    if not recording.identity:
        return replace(state, recording=recording)
    empty = "No speech was transcribed." if recording.phase == "saved" else "The transcript will appear here as speech is transcribed."
    text = f"**{recording.title}**\n\n" + (recording.preview or empty)
    if recording.detail:
        text += "\n\n" + recording.detail
    match recording.phase:
        case "saved":
            text += "\n\n*Transcript saved. Use Open for the full text.*"
        case "interrupted":
            text += "\n\n*Open the transcript for the saved part.*"
        case "idle" | "starting" | "recording" | "stopping" | "finishing" | "paused":
            pass
        case _:
            assert_never(recording.phase)
    for index, message in enumerate(state.messages):
        match message:
            case MeetingMessage(recording_id=identity) if identity == recording.identity:
                messages = (
                    state.messages if message.text == text else (*state.messages[:index], replace(message, text=text), *state.messages[index + 1 :])
                )
                return replace(state, recording=recording, messages=messages)
            case _:
                pass
    return replace(state, recording=recording, messages=(*state.messages, MeetingMessage(recording.identity, text, at)))


def reply_text(reply: RequestReply) -> str:
    match reply:
        case Pending():
            return "pending"
        case TextAnswer(text):
            return text
        case Cancelled():
            return "cancelled"
        case _:
            assert_never(reply)


def activity_text(activity: ToolActivity) -> str:
    detail = action_text.arguments(activity.name, activity.detail)
    match activity.outcome:
        case ToolStatus.RUNNING | ToolStatus.CANCELLED:
            return detail
        case Succeeded(text):
            return "\n".join(part for part in (detail, action_text.result(activity.name, text)) if part)
        case Failed(text):
            return "\n".join(part for part in (detail, action_text.readable(text)) if part)
        case _:
            assert_never(activity.outcome)


def message_text(message: Message) -> str:
    parts: tuple[str, ...]
    match message:
        case ChatMessage(speaker, text):
            parts = (speaker, text)
        case Answer(text=text):
            parts = ("Workspace", text)
        case ReasoningSummary(text=text):
            parts = ("Reasoning summary", text)
        case ToolActivity(name=name):
            parts = (name, activity_text(message))
        case MeetingMessage(text=text):
            parts = ("Meeting", text)
        case AgentRequest(detail=detail, reply=TextAnswer(answer)):
            parts = ("You", message.text, detail, "answered", answer)
        case AgentRequest(detail=detail, reply=reply):
            parts = ("You", message.text, detail, reply_text(reply))
        case _:
            assert_never(message)
    return "\n".join(part for part in parts if part)
