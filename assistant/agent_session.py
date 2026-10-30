"""Immutable conversation values and pure transitions for the agent timeline.

Clocks, IDs, locking, and widgets belong to the controller and its window.
Replaying the same events against a session always gives the same result.
"""

from dataclasses import dataclass, field, replace
from typing import Literal, assert_never

from assistant import action_text
from assistant.card_actions import OpenCanvas, encode
from assistant.feed_origin import FeedRequest
from assistant.recording_state import RecordingState
from automation.presentation import (
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
from automation.task import Approval, ApprovalDecision, Question

type Result = Literal["Ready", "Stopped", "Needs attention"]


@dataclass(frozen=True, slots=True)
class Pending:
    pass


@dataclass(frozen=True, slots=True)
class Answered:
    text: str


@dataclass(frozen=True, slots=True)
class Cancelled:
    pass


type Resolved = Answered | ApprovalDecision | Cancelled
type Reply = Pending | Resolved


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
    """A durable question or approval in the timeline, with the person's reply.

    `detail` is what the person reviews: a question's detail, or the full live
    review of an approval's exact operation.
    """

    request: Question | Approval
    detail: str
    created_at: float
    reply: Reply = Pending()

    @property
    def id(self) -> str:
        return self.request.id

    @property
    def text(self) -> str:
        match self.request:
            case Question(text=text) | Approval(title=text):
                return text
            case _:
                assert_never(self.request)


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
class CanvasSettled:
    targets: frozenset[str]


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
    | CanvasSettled
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
    def question(self) -> AgentRequest | None:
        return next(
            (
                message
                for message in self.messages
                if isinstance(message, AgentRequest) and isinstance(message.request, Question) and pending(message)
            ),
            None,
        )

    def all_text(self) -> str:
        return "\n\n".join(message_text(message) for message in self.messages)


# The view receives the immutable session itself, without a second state model.
type Snapshot = Session


def notice_text(title: str, target: str) -> str:
    return title + "\n\n[Open on canvas](" + encode(OpenCanvas(target)) + ")"


def transition(state: Session, event: Event) -> Session:
    match event:
        case CanvasSettled(targets):
            identities = frozenset("canvas:" + target for target in targets)
            return replace(
                state,
                messages=tuple(
                    message
                    for message in state.messages
                    if not (isinstance(message, ChatMessage) and message.source is not None and message.source.identity in identities)
                ),
            )
        case CanvasNotice(title, target, at):
            text = notice_text(title, target)
            return replace(state, messages=(*state.messages, ChatMessage("Workspace", text, at, FeedRequest("canvas:" + target, title))))
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
        case AgentRequest(request=request):
            return replace(
                state, messages=(*state.messages, event), status="Waiting for your reply" if isinstance(request, Question) else "Needs your approval"
            )
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
    if not state.busy or (state.stopping and not isinstance(event, ToolActivity)):
        return state
    if state.stopping and isinstance(event, ToolActivity) and event.outcome is ToolStatus.RUNNING:
        return state
    for index, message in enumerate(state.messages):
        if (
            not isinstance(message, (Answer, ReasoningSummary, ToolActivity))
            or message.identity != event.identity
            or type(message) is not type(event)
        ):
            continue
        match message:
            case (
                Answer(state=StreamState.COMPLETE | StreamState.INTERRUPTED) | ReasoningSummary(state=StreamState.COMPLETE | StreamState.INTERRUPTED)
            ):
                return state
            case ToolActivity(outcome=Succeeded() | Failed() | ToolStatus.CANCELLED):
                return state
            case Answer() | ReasoningSummary() | ToolActivity():
                pass
        updated = replace(event, created_at=message.created_at)
        if updated == message:
            return state
        messages = (*state.messages[:index], updated, *state.messages[index + 1 :])
        break
    else:
        if state.stopping:
            return state
        messages = (*state.messages, event)
    last_said = event.text.strip() if isinstance(event, Answer) and event.state is StreamState.COMPLETE else state.last_said
    return replace(state, messages=messages, last_said=last_said)


def acceptable(request: Question | Approval, answer: str) -> bool:
    match request:
        case Question():
            return bool(answer.strip())
        case Approval():
            return answer in ("approve", "decline")
        case _:
            assert_never(request)


def resolution(message: AgentRequest, answer: str) -> Resolution:
    """The reply to an answer `acceptable` already admitted for this request."""
    match message.request:
        case Question():
            return Resolution(message.id, Answered(answer))
        case Approval():
            return Resolution(message.id, ApprovalDecision.APPROVED if answer == "approve" else ApprovalDecision.DECLINED)
        case _:
            assert_never(message.request)


def resolve(state: Session, event: Resolution) -> Session:
    for index, message in enumerate(state.messages):
        if not isinstance(message, AgentRequest) or message.id != event.request_id or not pending(message):
            continue
        match message.request, event.reply:
            case Question(), Answered() | Cancelled():
                pass
            case Approval(), ApprovalDecision() | Cancelled():
                pass
            case _:
                return state  # a response for another kind of input cannot resolve this one
        updated = replace(message, reply=event.reply)
        return replace(
            state, messages=(*state.messages[:index], updated, *state.messages[index + 1 :]), status="Stopping…" if state.stopping else "Working…"
        )
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
        if isinstance(message, MeetingMessage) and message.recording_id == recording.identity:
            messages = (
                state.messages if message.text == text else (*state.messages[:index], replace(message, text=text), *state.messages[index + 1 :])
            )
            return replace(state, recording=recording, messages=messages)
    return replace(state, recording=recording, messages=(*state.messages, MeetingMessage(recording.identity, text, at)))


def reply_text(reply: Reply) -> str:
    match reply:
        case Pending():
            return "pending"
        case Answered(text):
            return text
        case ApprovalDecision.APPROVED:
            return "approved"
        case ApprovalDecision.DECLINED:
            return "declined"
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


def message_body(message: Message) -> str:
    """The visible text of a timeline message."""
    match message:
        case ToolActivity():
            return activity_text(message)
        case ChatMessage() | Answer() | ReasoningSummary() | MeetingMessage() | AgentRequest():
            return message.text
        case _:
            assert_never(message)


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
        case AgentRequest(detail=detail, reply=Answered(answer)):
            parts = ("You", message.text, detail, "answered", answer)
        case AgentRequest(detail=detail, reply=reply):
            parts = ("You", message.text, detail, reply_text(reply))
        case _:
            assert_never(message)
    return "\n".join(part for part in parts if part)


@dataclass(frozen=True, slots=True)
class ApprovalControls:
    identity: str


@dataclass(frozen=True, slots=True)
class ResponseText:
    text: str


@dataclass(frozen=True, slots=True)
class Presentation:
    role: str
    style: Literal["plain", "error", "markdown"] = "markdown"
    detail: str = ""
    response: ApprovalControls | ResponseText | None = None
    muted: bool = field(default=False, kw_only=True)


def presentation(message: Message) -> Presentation:
    match message:
        case ChatMessage(speaker="You"):
            return Presentation("You", "plain")
        case ChatMessage(speaker="Error"):
            return Presentation("Error", "error")
        case ChatMessage():
            return Presentation("Agent")
        case Answer(state=state):
            return Presentation("Agent · interrupted" if state is StreamState.INTERRUPTED else "Agent")
        case ReasoningSummary(state=state):
            label = "Reasoning summary · interrupted" if state is StreamState.INTERRUPTED else "Reasoning summary"
            return Presentation(label, muted=True)
        case ToolActivity(name=name, outcome=outcome):
            match outcome:
                case ToolStatus.RUNNING:
                    status = "running"
                case Succeeded():
                    status = "done"
                case Failed():
                    status = "failed"
                case ToolStatus.CANCELLED:
                    status = "stopped"
                case _:
                    assert_never(outcome)
            return Presentation(f"{action_text.title(name)} · {status}", "plain", muted=True)
        case MeetingMessage():
            return Presentation("Meeting")
        case AgentRequest(request=Question(), detail=detail, reply=Pending()):
            return Presentation("Question", detail=detail)
        case AgentRequest(request=Approval(id=identity), detail=detail, reply=Pending()):
            return Presentation("Approval", detail=detail, response=ApprovalControls(identity))
        case AgentRequest(request=Question(), detail=detail, reply=Answered(text)):
            return Presentation("Question", detail=detail, response=ResponseText(text))
        case AgentRequest(request=request, detail=detail, reply=reply):
            role = "Question" if isinstance(request, Question) else "Approval"
            return Presentation(role, detail=detail, response=ResponseText(reply_text(reply).capitalize()))
        case _:
            assert_never(message)
