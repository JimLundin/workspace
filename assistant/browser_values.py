"""Validated browser observations and pure choices for the agent's tab group."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Annotated, Literal, assert_never

from pydantic import Field, TypeAdapter, ValidationError

from automation.json_value import Json

MAX_ID = 2**31 - 1
type Color = Literal["grey", "blue", "red", "yellow", "green", "pink", "purple", "cyan", "orange"]
COLORS: tuple[Color, ...] = ("grey", "blue", "red", "yellow", "green", "pink", "purple", "cyan", "orange")


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


type Identifier = Annotated[int, Field(strict=True, ge=0, le=MAX_ID)]
"""A native tab, group or window ID."""
type GroupSelector = Annotated[int, Field(strict=True, ge=-1, le=MAX_ID)]
"""A group ID, or -1 for ungrouped tabs."""
type Position = Annotated[int, Field(strict=True, ge=-1, le=20000)]
"""A tab or group index within its window, or -1 for the end."""
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
    tab_id: int | None = None
    created_in_session: bool | None = field(default=None, kw_only=True)


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
    tab_id: int | None
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


def pages_of(reply: object) -> tuple[Page, ...]:
    """The browser's pages from a Target.getTargets reply; other target types are ignored."""
    try:
        targets = _TARGETS.validate_python(reply).targets
    except ValidationError as error:
        raise BrowserError("The browser did not provide a valid page list.") from error
    return tuple(Page(item.target_id, item.title[:300], item.url[:1000]) for item in targets if item.type == "page")


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


class DefaultGroup(Enum):
    WORKSPACE = auto()


class Ungrouped(Enum):
    TABS = auto()


@dataclass(frozen=True, slots=True)
class InGroup:
    id: int


@dataclass(frozen=True, slots=True)
class TabRow:
    """One native tab as the model sees it, with its page when Workspace knows it."""

    tab_id: int
    window_id: int
    index: int
    group_id: int
    title: str
    url: str
    target_id: str | None = None
    active: bool = field(kw_only=True)
    pinned: bool = field(kw_only=True)
    muted: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Tab:
    id: int
    window_id: int
    index: int
    group: InGroup | Ungrouped
    title: str
    url: str
    active: bool = field(kw_only=True)
    pinned: bool = field(kw_only=True)
    muted: bool = field(kw_only=True)

    @property
    def group_id(self) -> int:
        match self.group:
            case InGroup(identity):
                return identity
            case Ungrouped.TABS:
                return -1
            case _:
                assert_never(self.group)

    def row(self, target: str | None = None) -> TabRow:
        return TabRow(
            self.id,
            self.window_id,
            self.index,
            self.group_id,
            self.title,
            self.url,
            target,
            active=self.active,
            pinned=self.pinned,
            muted=self.muted,
        )


@dataclass(frozen=True, slots=True)
class TabReply:
    """A tab as Edge's tab API reports it."""

    tab_id: Identifier
    window_id: Identifier
    index: Identifier
    group_id: GroupSelector
    title: Text
    url: Text
    active: Flag = field(kw_only=True)
    pinned: Flag = field(kw_only=True)
    muted: Flag = field(kw_only=True)

    def tab(self) -> Tab:
        group = Ungrouped.TABS if self.group_id == -1 else InGroup(self.group_id)
        return Tab(
            self.tab_id,
            self.window_id,
            self.index,
            group,
            self.title[:300],
            self.url[:1000],
            active=self.active,
            pinned=self.pinned,
            muted=self.muted,
        )


@dataclass(frozen=True, slots=True)
class GroupRow:
    group_id: int
    window_id: int
    title: str
    color: Color
    collapsed: bool = field(kw_only=True)
    shared: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Group:
    id: int
    window_id: int
    title: str
    color: Color
    collapsed: bool = field(kw_only=True)
    shared: bool = field(kw_only=True)

    def row(self) -> GroupRow:
        return GroupRow(self.id, self.window_id, self.title, self.color, collapsed=self.collapsed, shared=self.shared)


@dataclass(frozen=True, slots=True)
class GroupReply:
    group_id: Identifier
    window_id: Identifier
    title: Text
    color: Color
    collapsed: Flag = field(kw_only=True)
    shared: Flag = field(kw_only=True)

    def group(self) -> Group:
        return Group(self.group_id, self.window_id, self.title[:300], self.color, collapsed=self.collapsed, shared=self.shared)


@dataclass(frozen=True, slots=True)
class TabState:
    tabs: tuple[Tab, ...]
    groups: tuple[Group, ...]
    windows: tuple[int, ...]
    last_window: int | None


@dataclass(frozen=True, slots=True)
class TabStateReply:
    tabs: Annotated[tuple[TabReply, ...], Field(max_length=20000)]
    groups: Annotated[tuple[GroupReply, ...], Field(max_length=20000)]
    windows: Annotated[tuple[Identifier, ...], Field(max_length=20000)]
    last_window: Identifier | None = None

    def state(self) -> TabState:
        return TabState(tuple(tab.tab() for tab in self.tabs), tuple(group.group() for group in self.groups), self.windows, self.last_window)


TAB = TypeAdapter(TabReply)
GROUP = TypeAdapter(GroupReply)
TAB_STATE = TypeAdapter(TabStateReply)


@dataclass(frozen=True, slots=True)
class NewGroup:
    title: str
    color: Color
    collapsed: bool = field(kw_only=True)


type Destination = DefaultGroup | Ungrouped | InGroup


def destination(selector: int | None) -> Destination:
    """A new tab's placement: the Workspace group by default, -1 for ungrouped, or an exact group."""
    match selector:
        case None:
            return DefaultGroup.WORKSPACE
        case -1:
            return Ungrouped.TABS
        case identity:
            return InGroup(identity)


@dataclass(frozen=True, slots=True)
class Opening:
    window_id: int
    group: NewGroup | InGroup | Ungrouped


def opening(state: TabState, requested: Destination, window: int | None) -> Opening:
    """Prefer the existing Workspace group; never re-collapse a group the user opened."""
    if window is not None and window not in state.windows:
        raise BrowserError("That normal browser window is closed. Refresh browser_tabs with view=strip.")
    match requested:
        case InGroup(identity):
            group = next((group for group in state.groups if group.id == identity), None)
            if group is None:
                raise BrowserError("That tab group is closed. Refresh browser_tabs with view=strip.")
            if window is not None and window != group.window_id:
                raise BrowserError("window_id must match the selected group's window.")
            return Opening(group.window_id, requested)
        case DefaultGroup.WORKSPACE:

            def priority(group: Group) -> tuple[bool, int]:
                return group.window_id != state.last_window, group.id

            groups = sorted(
                (
                    group
                    for group in state.groups
                    if group.title == "Workspace" and not group.shared and (window is None or group.window_id == window)
                ),
                key=priority,
            )
            if groups:
                return Opening(groups[0].window_id, InGroup(groups[0].id))
            chosen: NewGroup | Ungrouped = NewGroup("Workspace", "blue", collapsed=True)
        case Ungrouped.TABS:
            chosen = Ungrouped.TABS
        case _:
            assert_never(requested)
    selected = window if window is not None else state.last_window
    if selected is None or selected not in state.windows:
        raise BrowserError("Open a normal Edge window before creating an agent tab.")
    return Opening(selected, chosen)


@dataclass(frozen=True, slots=True)
class PageList:
    """Connected pages, without connecting or requesting consent."""

    offset: int = 0
    limit: int = 20


@dataclass(frozen=True, slots=True)
class StripQuery:
    """Edge's native tab strip, optionally filtered to one window or group."""

    offset: int
    limit: int
    window_id: int | None
    group: InGroup | Ungrouped | None


@dataclass(frozen=True, slots=True)
class StripPage:
    mode: Literal["attached", "sign_in", "background"]
    tabs: tuple[TabRow, ...]
    groups: tuple[GroupRow, ...]
    total: int
    offset: int
    next_offset: int | None = None
    view: Literal["strip"] = "strip"
    browser: Literal["edge"] = "edge"


STRIP_PAGE = TypeAdapter(StripPage)


def strip_page(
    state: TabState,
    query: StripQuery,
    mode: Literal["attached", "sign_in", "background"],
    targets: Mapping[str, int],
    *,
    maximum: int,
) -> StripPage:
    """Project an immutable observation into a bounded, typed response for tools or UI."""
    known = {identity: target for target, identity in targets.items()}
    tabs = tuple(
        tab
        for tab in state.tabs
        if (query.window_id is None or tab.window_id == query.window_id) and (query.group is None or tab.group == query.group)
    )
    page = tabs[query.offset : query.offset + query.limit]
    while True:
        result = StripPage(
            mode,
            tuple(tab.row(known.get(tab.id)) for tab in page),
            tuple(item.row() for item in state.groups if any(tab.group_id == item.id for tab in page)),
            len(tabs),
            query.offset,
            query.offset + len(page) if query.offset + len(page) < len(tabs) else None,
        )
        if len(STRIP_PAGE.dump_json(result, exclude_none=True).decode()) <= maximum:
            return result
        if len(page) <= 1:
            raise BrowserError("The browser tab summary exceeded its output limit.")
        page = page[:-1]


@dataclass(frozen=True, slots=True)
class GroupChanges:
    """Only the properties the request names; the others keep their current values."""

    title: str | None
    color: Color | None
    collapsed: bool | None = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Move:
    index: int
    window_id: int | None


@dataclass(frozen=True, slots=True)
class CreateGroup:
    tab_ids: tuple[int, ...]
    style: NewGroup
    window_id: int | None
    move: Move | None


@dataclass(frozen=True, slots=True)
class EditGroup:
    group_id: int
    tab_ids: tuple[int, ...]
    changes: GroupChanges
    move: Move | None


type GroupRequest = CreateGroup | EditGroup


class TabAction(Enum):
    ACTIVATE = "activate"
    PIN = "pin"
    UNPIN = "unpin"
    RELOAD = "reload"


@dataclass(frozen=True, slots=True)
class ChangeTab:
    tab_id: int
    action: TabAction


@dataclass(frozen=True, slots=True)
class MoveTab:
    tab_id: int
    move: Move


type TabRequest = ChangeTab | MoveTab


@dataclass(frozen=True, slots=True)
class UngroupTabs:
    tab_ids: tuple[int, ...]


type TabEdit = GroupRequest | TabRequest | UngroupTabs


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


@dataclass(frozen=True, slots=True)
class CloseTabs:
    tab_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CloseGroup:
    group_id: int


class Disconnect(Enum):
    BROWSER = auto()


type NativeClosure = CloseTabs | CloseGroup
type Closure = ClosePage | NativeClosure | Disconnect


@dataclass(frozen=True, slots=True)
class ClosedTabs:
    closed_tab_ids: tuple[int, ...]
    closed_count: int
    group_id: int | None = None


@dataclass(frozen=True, slots=True)
class ClosureResult:
    request: NativeClosure
    tab_ids: tuple[int, ...]

    def row(self) -> ClosedTabs:
        match self.request:
            case CloseGroup(identity):
                return ClosedTabs(self.tab_ids[:200], len(self.tab_ids), identity)
            case CloseTabs():
                return ClosedTabs(self.tab_ids[:200], len(self.tab_ids))
            case _:
                assert_never(self.request)


@dataclass(frozen=True, slots=True)
class UngroupResult:
    tab_ids: tuple[int, ...]
    group_id: Literal[-1] = -1
