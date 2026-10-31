"""Bounded JSON frames for the volatile work/assistant process boundary.

Public presentation events and typed UI-owned requests cross this channel.
Payloads remain volatile; SDK objects and pickles never cross the boundary.
A request and a reply are the channel's two wire shapes. Each variant's `kind`
tags it; decoding refuses unknown fields and coerced or non-finite values.
"""

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Annotated, Final, Literal, assert_never

from pydantic import ConfigDict, Field, TypeAdapter

from automation.activity import Activity, ContextSnapshot
from automation.capture import AudioSource
from automation.execution import ApprovalReview
from automation.presentation import (
    Answer,
    Done,
    Finished,
    LiveMessage,
    Problem,
    Progress,
    ReasoningSummary,
    Said,
    ToolActivity,
)
from automation.task import RunRef, identifier, integer, text, timestamp

VERSION: Final = 2
MAX_FRAME: Final = 1_048_576
MAX_EVENTS: Final = 128
MAX_CONTEXT: Final = 128

# Frames are strict: a peer's JSON never coerces into another type or adds fields.
_WIRE = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)

type PresentationEvent = Progress | Said | Done | Problem | Finished | LiveMessage
type ProcessId = Annotated[int, Field(ge=1, le=2**32 - 1)]


def _moment(event: PresentationEvent) -> None:
    match event:
        case Said(at=at) | Done(at=at) | Problem(at=at) | Answer(created_at=at) | ReasoningSummary(created_at=at) | ToolActivity(created_at=at):
            timestamp(at, "event time")
        case Progress() | Finished():
            pass
        case _:
            assert_never(event)


@dataclass(frozen=True, slots=True)
class LogEvent:
    run: RunRef
    event: PresentationEvent
    kind: Literal["log"] = "log"

    def __post_init__(self) -> None:
        _moment(self.event)


@dataclass(frozen=True, slots=True)
class ReviewEvent:
    run: RunRef
    review: ApprovalReview
    kind: Literal["review"] = "review"

    def __post_init__(self) -> None:
        if self.run.task_id != self.review.task_id:
            raise ValueError("Review does not belong to its run.")


@dataclass(frozen=True, slots=True)
class StartMeeting:
    source: AudioSource
    title: str
    kind: Literal["start"] = "start"

    def __post_init__(self) -> None:
        text(self.title, "meeting title", maximum=240)


class MeetingCommand(Enum):
    STOP = "stop"
    RETRY = "retry"
    LIST = "list"
    STATUS = "status"


type MeetingOperation = StartMeeting | MeetingCommand


@dataclass(frozen=True, slots=True)
class MeetingRequest:
    run: RunRef
    request_id: str
    operation: MeetingOperation
    kind: Literal["meeting"] = "meeting"

    def __post_init__(self) -> None:
        identifier(self.request_id, "meeting request identity")


@dataclass(frozen=True, slots=True)
class MeetingSucceeded:
    text: str
    kind: Literal["succeeded"] = "succeeded"


@dataclass(frozen=True, slots=True)
class MeetingFailed:
    reason: str
    kind: Literal["failed"] = "failed"

    def __post_init__(self) -> None:
        text(self.reason, "meeting failure", maximum=8000)


type MeetingResult = MeetingSucceeded | MeetingFailed


@dataclass(frozen=True, slots=True)
class Resync:
    reason: str
    kind: Literal["resync"] = "resync"

    def __post_init__(self) -> None:
        text(self.reason, "resynchronization reason", maximum=1000)


type BridgeEvent = LogEvent | ReviewEvent | MeetingRequest | Resync


@dataclass(frozen=True, slots=True)
class Envelope:
    epoch: str
    sequence: int
    payload: BridgeEvent
    __pydantic_config__ = _WIRE

    def __post_init__(self) -> None:
        identifier(self.epoch, "worker epoch")
        integer(self.sequence, "event sequence", minimum=1)


@dataclass(frozen=True, slots=True)
class Hello:
    assistant_pid: ProcessId
    kind: Literal["hello"] = "hello"


@dataclass(frozen=True, slots=True)
class Poll:
    after: Annotated[int, Field(ge=0)]
    limit: Annotated[int, Field(ge=1, le=MAX_EVENTS)]
    kind: Literal["poll"] = "poll"


@dataclass(frozen=True, slots=True)
class Register:
    task_id: str
    context: ContextSnapshot | None
    assistant_pid: ProcessId
    kind: Literal["register"] = "register"

    def __post_init__(self) -> None:
        identifier(self.task_id, "task identity")


@dataclass(frozen=True, slots=True)
class PublishContext:
    context: ContextSnapshot
    assistant_pid: ProcessId
    kind: Literal["context"] = "context"


@dataclass(frozen=True, slots=True)
class MeetingResponse:
    run: RunRef
    request_id: str
    result: MeetingResult
    kind: Literal["response"] = "response"

    def __post_init__(self) -> None:
        identifier(self.request_id, "meeting request identity")


class Command(Enum):
    WAKE = "wake"


type Operation = Hello | Poll | Register | PublishContext | MeetingResponse | Command


@dataclass(frozen=True, slots=True)
class Request:
    epoch: str
    client: str
    operation: Operation

    def __post_init__(self) -> None:
        identifier(self.epoch, "worker epoch")
        identifier(self.client, "bridge client")


@dataclass(frozen=True, slots=True)
class Accepted:
    epoch: str
    accepted: bool = field(kw_only=True)
    kind: Literal["accepted"] = "accepted"


@dataclass(frozen=True, slots=True)
class Batch:
    epoch: str
    events: Annotated[tuple[Envelope, ...], Field(max_length=MAX_EVENTS)]
    kind: Literal["batch"] = "batch"

    def __post_init__(self) -> None:
        previous = 0
        for event in self.events:
            if event.epoch != self.epoch or event.sequence <= previous:
                raise ValueError("Unordered or stale bridge events.")
            previous = event.sequence


@dataclass(frozen=True, slots=True)
class Rejected:
    reason: str
    kind: Literal["rejected"] = "rejected"

    def __post_init__(self) -> None:
        text(self.reason, "bridge rejection", maximum=1000)


type Reply = Accepted | Batch | Rejected


@dataclass(frozen=True, slots=True)
class _RequestFrame:
    version: int
    request: Request
    __pydantic_config__ = _WIRE


@dataclass(frozen=True, slots=True)
class _ReplyFrame:
    version: int
    reply: Reply
    __pydantic_config__ = _WIRE


_REQUEST = TypeAdapter(_RequestFrame)
_REPLY = TypeAdapter(_ReplyFrame)
_EVENT = TypeAdapter(Envelope)


def _bounded(context: ContextSnapshot) -> ContextSnapshot:
    """Only the recent, truncated window history crosses the boundary."""
    recent = tuple(
        replace(activity, window=replace(activity.window, title=activity.window.title[:1000], exe=activity.window.exe[:256]))
        for activity in context.recent[-MAX_CONTEXT:]
    )
    return replace(context, recent=recent)


def _observed(context: ContextSnapshot) -> None:
    captured = timestamp(context.captured, "context time")
    if len(context.recent) > MAX_CONTEXT:
        raise ValueError("Too much desktop context.")
    for activity in context.recent:
        _activity(activity, captured)


def _activity(activity: Activity, captured: float) -> None:
    window = activity.window
    integer(window.handle, "window handle", maximum=2**64 - 1)
    text(window.title, "window title", maximum=1000, empty=True)
    text(window.exe, "window program", maximum=256, empty=True)
    started, seen = timestamp(activity.started), timestamp(activity.seen)
    if started > seen or seen > captured:
        raise ValueError("Invalid context time ordering.")


def _sent(operation: Operation) -> Operation:
    match operation:
        case Register(context=ContextSnapshot() as context):
            return replace(operation, context=_bounded(context))
        case PublishContext(context=context):
            return replace(operation, context=_bounded(context))
        case Hello() | Poll() | Register() | MeetingResponse() | Command():
            return operation
        case _:
            assert_never(operation)


def _received(operation: Operation) -> None:
    match operation:
        case Register(context=ContextSnapshot() as context) | PublishContext(context=context):
            _observed(context)
        case Hello() | Poll() | Register() | MeetingResponse() | Command():
            pass
        case _:
            assert_never(operation)


def _bounded_frame(frame: bytes) -> bytes:
    if not frame or len(frame) > MAX_FRAME:
        raise ValueError("Invalid IPC frame length.")
    return frame


def _version(version: int) -> None:
    if version != VERSION:
        raise ValueError("Unsupported IPC version.")


def encode_event(message: Envelope) -> bytes:
    """The event as a batch carries it, checked against the same decoder."""
    frame = _EVENT.dump_json(message)
    decode_event(frame)
    return frame


def decode_event(frame: bytes) -> Envelope:
    return _EVENT.validate_json(_bounded_frame(frame))


def encode_request(request: Request) -> bytes:
    sent = replace(request, operation=_sent(request.operation))
    frame = _REQUEST.dump_json(_RequestFrame(VERSION, sent))
    decode_request(frame)
    return frame


def decode_request(frame: bytes) -> Request:
    received = _REQUEST.validate_json(_bounded_frame(frame))
    _version(received.version)
    _received(received.request.operation)
    return received.request


def encode_reply(reply: Reply) -> bytes:
    frame = _REPLY.dump_json(_ReplyFrame(VERSION, reply))
    if len(frame) > MAX_FRAME:
        raise ValueError("IPC frame is too large.")
    decode_reply(frame)
    return frame


def decode_reply(frame: bytes) -> Reply:
    received = _REPLY.validate_json(_bounded_frame(frame))
    _version(received.version)
    return received.reply
