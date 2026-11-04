"""Validated browser observations and the browser tool's typed results."""

from collections.abc import Collection
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError

from automation.json_value import Json


class BrowserError(OSError):
    pass


class InterruptedError(BrowserError):
    """An operation must stop, including JavaScript still running in the browser."""


class DisconnectedError(BrowserError):
    """The transport ended; an interrupted action must not be replayed."""


class NavigationContextError(BrowserError):
    """A page navigation retired the execution context, while transport remains live."""


class NavigationLoadingError(BrowserError):
    """Navigation started but did not finish within the observation deadline."""


def navigation_context_error(message: str) -> bool:
    return any(
        phrase in message
        for phrase in (
            "Cannot find context with specified id",
            "Cannot find execution context",
            "Execution context was destroyed",
        )
    )


type Offset = Annotated[int, Field(strict=True, ge=0, le=20000)]
type Flag = Annotated[bool, Field(strict=True)]
type Text = Annotated[str, Field(strict=True)]


def decoded[T](shape: TypeAdapter[T], value: object, failure: str) -> T:
    """Validate a browser reply before any later step relies on it."""
    try:
        return shape.validate_python(value)
    except ValidationError as error:
        raise BrowserError(failure) from error


@dataclass(frozen=True, slots=True)
class Page:
    id: str
    title: str
    url: str


# The browser tool's results are typed records; optional fields left as None
# are omitted from the model's JSON.


@dataclass(frozen=True, slots=True)
class PageRow:
    id: str
    title: str
    url: str
    created_in_session: bool | None = field(default=None, kw_only=True)
    hidden: bool | None = field(default=None, kw_only=True)


@dataclass(frozen=True, slots=True)
class BrowserStatus:
    mode: Literal["stopped", "attached", "sign_in", "background"]
    tabs: tuple[PageRow, ...]
    browser: Literal["edge", "chrome"] | None = None
    setup: str | None = None
    total: int | None = None
    offset: int | None = None
    next_offset: int | None = None
    view: Literal["pages"] = "pages"


@dataclass(frozen=True, slots=True)
class SignInPage:
    target_id: str
    url: str
    message: str
    mode: Literal["sign_in"] = "sign_in"


@dataclass(frozen=True, slots=True)
class SnapshotOptions:
    prefix: str
    offset: int
    limit: int
    text_offset: int


@dataclass(frozen=True, slots=True)
class Control:
    id: str
    tag: str
    role: str
    type: str
    name: str
    value: str
    href: str
    disabled: bool = field(kw_only=True)
    checked: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Rendered:
    """The snapshot script's observation of one frame."""

    title: str
    url: str
    text: str
    text_offset: int
    text_total: int
    controls: tuple[Control, ...]
    offset: int
    total: int
    more_controls: bool = field(kw_only=True)
    scan_limited: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class FrameInfo:
    id: str
    url: str = ""
    name: str = ""
    loader_id: Annotated[str, Field(alias="loaderId")] = ""


@dataclass(frozen=True, slots=True)
class FrameTree:
    frame: FrameInfo
    children: Annotated[tuple[FrameTree, ...], Field(alias="childFrames")] = ()


# DevTools Protocol replies, validated where each command's result is used.


@dataclass(frozen=True, slots=True)
class FrameTreeReply:
    tree: Annotated[FrameTree, Field(alias="frameTree")]


@dataclass(frozen=True, slots=True)
class CreatedTarget:
    target_id: Annotated[str, Field(alias="targetId", strict=True, min_length=1)]


@dataclass(frozen=True, slots=True)
class TargetSession:
    session_id: Annotated[str, Field(alias="sessionId", strict=True, min_length=1)]


@dataclass(frozen=True, slots=True)
class World:
    context: Annotated[int, Field(alias="executionContextId", strict=True, ge=1, le=2**53)]


@dataclass(frozen=True, slots=True)
class Navigated:
    error_text: Annotated[str, Field(alias="errorText")] = ""
    loader_id: Annotated[str, Field(alias="loaderId")] = ""


@dataclass(frozen=True, slots=True)
class Capture:
    data: Text


@dataclass(frozen=True, slots=True)
class ClosedTarget:
    success: Flag = False


CREATED_TARGET = TypeAdapter(CreatedTarget)
TARGET_SESSION = TypeAdapter(TargetSession)


@dataclass(frozen=True, slots=True)
class Frame:
    id: str
    url: str
    name: str


@dataclass(frozen=True, slots=True)
class Snapshot:
    """A bounded page observation with its frame list and continuation offsets."""

    target_id: str
    title: str
    url: str
    text: str
    text_offset: int
    text_total: int
    controls: tuple[Control, ...]
    offset: int
    total: int
    frames: tuple[Frame, ...]
    frame_offset: int
    frame_total: int
    next_frame_offset: int | None = None
    next_control_offset: int | None = None
    next_text_offset: int | None = None
    more_controls: bool = field(kw_only=True)
    scan_limited: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class ActionOptions:
    id: str
    action: Literal["click", "fill", "select", "check"]
    value: str
    checked: bool = field(kw_only=True)
    dom_click: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Point:
    """Where a click action found its control, in viewport coordinates."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class TargetInfo:
    type: str
    target_id: Annotated[str, Field(alias="targetId", min_length=1, max_length=128)]
    title: str = ""
    url: str = ""


@dataclass(frozen=True, slots=True)
class TargetList:
    targets: Annotated[tuple[TargetInfo, ...], Field(alias="targetInfos")]


_TARGETS = TypeAdapter(TargetList)


def pages_of(reply: object, *, hidden: Collection[str] = ()) -> tuple[Page, ...]:
    """Ordinary pages and owned hidden targets; other clients' non-page targets stay private."""
    try:
        targets = _TARGETS.validate_python(reply).targets
    except ValidationError as error:
        raise BrowserError("The browser did not provide a valid page list.") from error
    return tuple(
        Page(item.target_id, item.title[:300], item.url[:1000])
        for item in targets
        if item.type == "page" or (item.type == "other" and item.target_id in hidden)
    )


@dataclass(frozen=True, slots=True)
class Thrown:
    description: str


@dataclass(frozen=True, slots=True)
class ExceptionDetails:
    text: str = ""
    exception: Thrown | None = None


@dataclass(frozen=True, slots=True)
class RemoteObject:
    value: Json = None


@dataclass(frozen=True, slots=True)
class Evaluation:
    """A Runtime.evaluate reply: the returned value, or the script's exception."""

    result: RemoteObject = RemoteObject()
    failure: Annotated[ExceptionDetails | None, Field(alias="exceptionDetails")] = None


_EVALUATION = TypeAdapter(Evaluation)


def evaluated(reply: object, failed: str) -> Json:
    """The script's value; its exception, or `failed` without a description, becomes a BrowserError."""
    try:
        evaluation = _EVALUATION.validate_python(reply)
    except ValidationError as error:
        raise BrowserError("The browser returned an invalid script result.") from error
    match evaluation.failure:
        case ExceptionDetails(exception=Thrown(description)):
            raise BrowserError(description[:700])
        case ExceptionDetails(text=message):
            raise BrowserError((message or failed)[:700])
        case None:
            return evaluation.result.value


@dataclass(frozen=True, slots=True)
class PageList:
    """Connected pages, without connecting or requesting consent."""

    offset: int = 0
    limit: int = 20


@dataclass(frozen=True, slots=True)
class ClosePage:
    target_id: str


class CloseState(Enum):
    CLOSED = "closed"
    REQUESTED = "requested"


@dataclass(frozen=True, slots=True)
class PageClosure:
    target_id: str
    state: CloseState


class Disconnect(Enum):
    BROWSER = auto()


type Closure = ClosePage | Disconnect
