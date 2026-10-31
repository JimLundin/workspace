"""Edge's tab APIs, reached through a hidden, connection-owned Favorites page."""

import contextlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Literal, Protocol, assert_never

from pydantic import Field, TypeAdapter

from assistant.browser_values import (
    CREATED_TARGET,
    GROUP,
    TAB,
    TAB_STATE,
    TARGET_SESSION,
    BrowserError,
    ChangeTab,
    CloseGroup,
    CloseTabs,
    ClosureResult,
    Color,
    CreateGroup,
    DisconnectedError,
    EditGroup,
    Flag,
    Group,
    GroupRequest,
    Identifier,
    InGroup,
    InterruptedError,
    Move,
    MoveTab,
    NativeClosure,
    NewGroup,
    Opening,
    Tab,
    TabRequest,
    TabState,
    Ungrouped,
    UngroupResult,
    decoded,
    evaluated,
)
from assistant.llm import Json

_PROBE = """({ready: location.protocol === 'edge:' && location.hostname === 'favorites' &&
    typeof chrome.tabs?.query === 'function' && typeof chrome.tabGroups?.update === 'function', url: location.href})"""

_COMMAND = r"""async request => {
    const tab = t => ({tab_id:t.id, window_id:t.windowId, index:t.index, group_id:t.groupId,
        title:(t.title || '').slice(0,300), url:(t.pendingUrl || t.url || '').slice(0,1000),
        active:t.active, pinned:t.pinned, muted:!!t.mutedInfo?.muted});
    const group = g => ({group_id:g.id, window_id:g.windowId, title:(g.title || '').slice(0,300),
        color:g.color, collapsed:g.collapsed, shared:!!g.shared});
    if (location.protocol !== 'edge:' || location.hostname !== 'favorites')
        throw new Error('The Edge tab controller is no longer on its browser-owned page.');
    switch (request.operation) {
        case 'list': {
            const windows = await chrome.windows.getAll({windowTypes:['normal']});
            const last = windows.length ? await chrome.windows.getLastFocused({windowTypes:['normal']}) : null;
            return {tabs:(await chrome.tabs.query({})).map(tab), groups:(await chrome.tabGroups.query({})).map(group),
                windows:windows.map(w => w.id), last_window:last?.id ?? null};
        }
        case 'open': {
            if (request.group_id !== undefined) await chrome.tabGroups.get(request.group_id);
            const created = await chrome.tabs.create({url:request.url, active:false, windowId:request.window_id});
            try {
                if (request.group_id !== undefined) {
                    await chrome.tabs.group({tabIds:[created.id], groupId:request.group_id});
                } else if (request.new_group) {
                    const id = await chrome.tabs.group({tabIds:[created.id]});
                    await chrome.tabGroups.update(id, request.new_group);
                }
                return tab(await chrome.tabs.get(created.id));
            } catch (error) {
                // Only the blank tab created by this command is rolled back.
                try { await chrome.tabs.remove(created.id); }
                catch (_) { throw new Error(`Tab ${created.id} was created but grouping failed: ${error.message}`); }
                throw error;
            }
        }
        case 'group': {
            let id = request.group_id;
            if (id !== undefined) await chrome.tabGroups.get(id);
            // Resolve every ID before making any change; stale lists do not partially regroup tabs.
            await Promise.all(request.tab_ids.map(id => chrome.tabs.get(id)));
            if (request.tab_ids.length) {
                const options = {tabIds:request.tab_ids};
                if (id !== undefined) options.groupId = id;
                else if (request.window_id !== undefined) options.createProperties = {windowId:request.window_id};
                id = await chrome.tabs.group(options);
            }
            if (Object.keys(request.properties).length) await chrome.tabGroups.update(id, request.properties);
            if (request.move) await chrome.tabGroups.move(id, request.move);
            return group(await chrome.tabGroups.get(id));
        }
        case 'ungroup':
            await Promise.all(request.tab_ids.map(id => chrome.tabs.get(id)));
            await chrome.tabs.ungroup(request.tab_ids);
            return {tab_ids:request.tab_ids, group_id:-1};
        case 'tab': {
            await chrome.tabs.get(request.tab_id);
            switch (request.action) {
                case 'activate': {
                    const selected = await chrome.tabs.update(request.tab_id, {active:true});
                    await chrome.windows.update(selected.windowId, {focused:true});
                    break;
                }
                case 'pin': await chrome.tabs.update(request.tab_id, {pinned:true}); break;
                case 'unpin': await chrome.tabs.update(request.tab_id, {pinned:false}); break;
                case 'move': await chrome.tabs.move(request.tab_id, request.move); break;
                case 'reload': await chrome.tabs.reload(request.tab_id); break;
                default: throw new Error('Unknown tab action.');
            }
            return tab(await chrome.tabs.get(request.tab_id));
        }
        case 'close':
            await Promise.all(request.tab_ids.map(id => chrome.tabs.get(id)));
            await chrome.tabs.remove(request.tab_ids);
            return {closed_tab_ids:request.tab_ids};
        case 'close_group': {
            await chrome.tabGroups.get(request.group_id);
            const ids = (await chrome.tabs.query({groupId:request.group_id})).map(t => t.id);
            if (ids.length) await chrome.tabs.remove(ids);
            return {closed_tab_ids:ids, group_id:request.group_id};
        }
        default: throw new Error('Unknown tab operation.');
    }
}"""


class Call(Protocol):
    def __call__(
        self,
        method: str,
        params: dict[str, Json],
        cancel: threading.Event,
        *,
        session: str = "",
        timeout: float = 15,
    ) -> dict[str, Json]: ...


@dataclass(frozen=True, slots=True)
class Control:
    target: str
    session: str


# Commands for the controller script. Absent optional fields are omitted from
# its JSON, which the script reads as "not requested".


@dataclass(frozen=True, slots=True)
class MoveData:
    index: int
    window_id: Annotated[int | None, Field(serialization_alias="windowId")] = None


@dataclass(frozen=True, slots=True)
class StyleData:
    title: str | None = None
    color: Color | None = None
    collapsed: bool | None = field(default=None, kw_only=True)


@dataclass(frozen=True, slots=True)
class ListCommand:
    operation: Literal["list"] = "list"


@dataclass(frozen=True, slots=True)
class OpenCommand:
    url: str
    window_id: int
    group_id: int | None = None
    new_group: StyleData | None = None
    operation: Literal["open"] = "open"


@dataclass(frozen=True, slots=True)
class GroupCommand:
    tab_ids: tuple[int, ...]
    properties: StyleData
    group_id: int | None = None
    window_id: int | None = None
    move: MoveData | None = None
    operation: Literal["group"] = "group"


@dataclass(frozen=True, slots=True)
class TabCommand:
    tab_id: int
    action: Literal["activate", "pin", "unpin", "reload", "move"]
    move: MoveData | None = None
    operation: Literal["tab"] = "tab"


@dataclass(frozen=True, slots=True)
class UngroupCommand:
    tab_ids: tuple[int, ...]
    operation: Literal["ungroup"] = "ungroup"


@dataclass(frozen=True, slots=True)
class CloseTabsCommand:
    tab_ids: tuple[int, ...]
    operation: Literal["close"] = "close"


@dataclass(frozen=True, slots=True)
class CloseGroupCommand:
    group_id: int
    operation: Literal["close_group"] = "close_group"


type NativeCommand = ListCommand | OpenCommand | GroupCommand | TabCommand | UngroupCommand | CloseTabsCommand | CloseGroupCommand
_COMMANDS = TypeAdapter[NativeCommand](NativeCommand)


@dataclass(frozen=True, slots=True)
class Probe:
    ready: Flag


@dataclass(frozen=True, slots=True)
class UngroupReply:
    tab_ids: tuple[Identifier, ...]
    group_id: Literal[-1]


@dataclass(frozen=True, slots=True)
class Closed:
    closed_tab_ids: Annotated[tuple[Identifier, ...], Field(max_length=20000)]


_PROBE_REPLY = TypeAdapter(Probe)
_UNGROUPED = TypeAdapter(UngroupReply)
_CLOSED = TypeAdapter(Closed)
_INVALID = "Edge's tab controller returned an unexpected result. Inspect browser_tabs with view=strip before retrying."


def move_data(move: Move) -> MoveData:
    return MoveData(move.index, move.window_id)


def group_command(request: GroupRequest) -> GroupCommand:
    match request:
        case CreateGroup(identities, style, window, move):
            properties = StyleData(style.title, style.color, collapsed=style.collapsed)
            return GroupCommand(identities, properties, window_id=window, move=None if move is None else move_data(move))
        case EditGroup(identity, identities, changes, move):
            properties = StyleData(changes.title, changes.color, collapsed=changes.collapsed)
            return GroupCommand(identities, properties, group_id=identity, move=None if move is None else move_data(move))
        case _:
            assert_never(request)


def tab_command(request: TabRequest) -> TabCommand:
    match request:
        case ChangeTab(identity, action):
            return TabCommand(identity, action.value)
        case MoveTab(identity, move):
            return TabCommand(identity, "move", move_data(move))
        case _:
            assert_never(request)


class TabStrip:
    """Own one hidden helper, never a visible user tab or an extension installation."""

    __slots__ = ("clock", "control")

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.control: Control | None = None

    @staticmethod
    def _evaluate(call: Call, session: str, expression: str, cancel: threading.Event) -> Json:
        result = call("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True}, cancel, session=session)
        try:
            return evaluated(result, "Tab operation failed.")
        except BrowserError as error:
            raise BrowserError(f"{error} Inspect browser_tabs with view=strip before repeating a change.") from error

    def _ensure(self, call: Call, cancel: threading.Event) -> Control:
        if self.control is not None:
            return self.control
        created = call("Target.createTarget", {"url": "edge://favorites/", "background": True, "hidden": True}, cancel)
        target = decoded(CREATED_TARGET, created, "Edge did not create its hidden tab controller.").target_id
        try:
            attached = call("Target.attachToTarget", {"targetId": target, "flatten": True}, cancel)
            session = decoded(TARGET_SESSION, attached, "Edge did not attach its tab controller.").session_id
            deadline = self.clock() + 5
            while True:
                try:
                    probe = decoded(_PROBE_REPLY, self._evaluate(call, session, _PROBE, cancel), "Edge's tab controller is not ready.")
                    if probe.ready:
                        self.control = Control(target, session)
                        return self.control
                except InterruptedError, DisconnectedError:
                    raise
                except BrowserError:
                    pass  # Only this read-only probe retries while the initial context loads.
                if self.clock() >= deadline:
                    raise BrowserError(
                        "This Edge version does not expose its native tab/group APIs. "
                        "Use browser_open with group_id=-1 for an ordinary background tab."
                    )
                if cancel.wait(0.05):
                    raise InterruptedError("Stopped while preparing Edge tab controls.")
        except BaseException:
            with contextlib.suppress(OSError):
                call("Target.closeTarget", {"targetId": target}, threading.Event(), timeout=1)
            raise

    def _command(self, call: Call, request: NativeCommand, cancel: threading.Event) -> Json:
        control = self._ensure(call, cancel)
        return self._evaluate(
            call, control.session, f"({_COMMAND})({_COMMANDS.dump_json(request, exclude_none=True, by_alias=True).decode()})", cancel
        )

    def snapshot(self, call: Call, cancel: threading.Event) -> TabState:
        return decoded(TAB_STATE, self._command(call, ListCommand(), cancel), _INVALID).state()

    def open(self, call: Call, url: str, plan: Opening, cancel: threading.Event) -> Tab:
        match plan.group:
            case InGroup(identity):
                request = OpenCommand(url, plan.window_id, group_id=identity)
            case NewGroup(title, color, collapsed=collapsed):
                request = OpenCommand(url, plan.window_id, new_group=StyleData(title, color, collapsed=collapsed))
            case Ungrouped.TABS:
                request = OpenCommand(url, plan.window_id)
            case _:
                assert_never(plan.group)
        return decoded(TAB, self._command(call, request, cancel), _INVALID).tab()

    def group(self, call: Call, request: GroupRequest, cancel: threading.Event) -> Group:
        return decoded(GROUP, self._command(call, group_command(request), cancel), _INVALID).group()

    def tab(self, call: Call, request: TabRequest, cancel: threading.Event) -> Tab:
        return decoded(TAB, self._command(call, tab_command(request), cancel), _INVALID).tab()

    def ungroup(self, call: Call, identities: tuple[int, ...], cancel: threading.Event) -> UngroupResult:
        result = decoded(_UNGROUPED, self._command(call, UngroupCommand(identities), cancel), _INVALID)
        if result.tab_ids != identities:
            raise BrowserError("The browser did not confirm the ungrouped tabs. Inspect browser_tabs before retrying.")
        return UngroupResult(identities)

    def close(self, call: Call, request: NativeClosure, cancel: threading.Event) -> ClosureResult:
        command: CloseTabsCommand | CloseGroupCommand
        match request:
            case CloseTabs(identities):
                command = CloseTabsCommand(identities)
            case CloseGroup(identity):
                command = CloseGroupCommand(identity)
            case _:
                assert_never(request)
        closed = decoded(_CLOSED, self._command(call, command, cancel), _INVALID).closed_tab_ids
        match request:
            case CloseTabs(identities) if closed != identities:
                raise BrowserError("The browser did not confirm the closed tabs. Inspect browser_tabs before retrying.")
            case _:
                return ClosureResult(request, closed)
