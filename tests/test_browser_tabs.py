"""Tab/group contracts, ownership choices and failures before browser effects."""

import threading
from pathlib import Path
from unittest import TestCase

from pydantic import TypeAdapter

from assistant.browser import MAX_OUTPUT
from assistant.browser_tabs import Call, Control, TabStrip
from assistant.browser_tools import GroupArguments, group_request
from assistant.browser_values import (
    STRIP_PAGE,
    BrowserError,
    BrowserStatus,
    CreateGroup,
    DefaultGroup,
    EditGroup,
    Group,
    GroupChanges,
    GroupRow,
    InGroup,
    Move,
    NewGroup,
    Opening,
    StripPage,
    StripQuery,
    Tab,
    TabRow,
    TabState,
    Ungrouped,
    opening,
    strip_page,
)
from assistant.llm import Json
from automation.actions import target
from tests.test_agent import ToolRig, durable
from tests.test_browser import WIRE, Channel, command, connected_browser, decoded, group_of, tab_of


def test_default_open_reuses_the_users_expanded_workspace_group_without_changing_it() -> None:
    title = "Workspace"
    first = Group(10, 1, title, "blue", collapsed=True, shared=False)
    expanded = Group(20, 2, title, "purple", collapsed=False, shared=False)
    state = TabState((), (first, expanded), (1, 2), 2)
    assert opening(state, DefaultGroup.WORKSPACE, None) == Opening(2, InGroup(20))
    assert opening(state, DefaultGroup.WORKSPACE, 1) == Opening(1, InGroup(10))
    assert expanded == Group(20, 2, title, "purple", collapsed=False, shared=False)
    assert opening(state, Ungrouped.TABS, None) == Opening(2, Ungrouped.TABS)
    with TestCase().assertRaisesRegex(BrowserError, "match"):
        opening(state, InGroup(10), 2)
    with TestCase().assertRaisesRegex(BrowserError, "group is closed"):
        opening(state, InGroup(30), None)


def test_default_open_does_not_add_work_to_other_or_shared_groups() -> None:
    state = TabState(
        (),
        (Group(10, 1, "Personal", "blue", collapsed=False, shared=False), Group(20, 1, "Workspace", "blue", collapsed=False, shared=True)),
        (1,),
        1,
    )
    assert opening(state, DefaultGroup.WORKSPACE, None) == Opening(1, NewGroup("Workspace", "blue", collapsed=True))
    with TestCase().assertRaisesRegex(BrowserError, "window is closed"):
        opening(state, DefaultGroup.WORKSPACE, 2)


def test_invalid_tab_edits_do_not_create_a_controller_or_change_any_tabs(tmp_path: Path) -> None:
    channel = Channel()
    browser = connected_browser(tmp_path / "unused", channel)
    cases: tuple[tuple[str, dict[str, Json]], ...] = (
        ("group", {}),
        ("group", {"tab_ids": [True]}),
        ("group", {"tab_ids": ["1"]}),
        ("group", {"tab_ids": [1], "collapsed": "yes"}),
        ("group", {"tab_ids": [1], "color": "invisible"}),
        ("group", {"group_id": True}),
        ("group", {"tab_ids": [1], "window_id": -1}),
        ("group", {"tab_ids": [1], "title": "x" * 301}),
        ("ungroup", {"tab_ids": []}),
        ("ungroup", {"tab_ids": list(range(201))}),
        ("tab", {"tab_id": 1, "action": "move"}),
        ("tab", {"tab_id": 1, "action": "pin", "index": 0}),
        # The WebUI mute API dereferences a missing extension and crashes Edge.
        ("tab", {"tab_id": 1, "action": "mute"}),
        ("tab", {"tab_id": 1, "action": "unmute"}),
        ("close", {"tab_ids": []}),
        ("close", {"group_id": -1}),
        ("close", {"target_id": "page", "tab_ids": [1]}),
        ("open", {"url": "about:blank", "group_id": "1"}),
        ("open", {"url": "about:blank", "target_id": "page", "group_id": 1}),
    )
    try:
        for operation, arguments in cases:
            # Invalid arguments are refused at the tool seam or before any browser command.
            with TestCase().assertRaises((ValueError, BrowserError)):
                browser.request(command(operation, **arguments), threading.Event())
            assert not channel.sent, (operation, arguments)
    finally:
        browser.close()


def test_native_observations_require_the_declared_field_types() -> None:
    tab = Tab(1, 2, 0, Ungrouped.TABS, "Page", "https://example.com", active=False, pinned=False, muted=False)
    source = WIRE.validate_json(TypeAdapter(TabRow).dump_json(tab.row(), exclude_none=True))
    assert tab_of(source) == tab
    for name, value in (("tab_id", True), ("active", "false"), ("group_id", -2), ("url", None)):
        with TestCase().assertRaises(BrowserError):
            tab_of({**source, name: value})
    with TestCase().assertRaises(BrowserError):
        tab_of({name: value for name, value in source.items() if name != "active"})
    group = Group(1, 2, "Workspace", "blue", collapsed=True, shared=False)
    row = WIRE.validate_json(TypeAdapter(GroupRow).dump_json(group.row()))
    assert group_of(row) == group
    with TestCase().assertRaises(BrowserError):
        group_of({**row, "collapsed": 1})


class FixedStrip(TabStrip):
    __slots__ = ("state",)

    def __init__(self, state: TabState) -> None:
        super().__init__()
        self.state = state

    def snapshot(self, call: Call, cancel: threading.Event) -> TabState:
        return self.state


def test_native_tab_pagination_keeps_ids_and_group_details_with_escaped_long_titles(tmp_path: Path) -> None:
    tabs = tuple(
        Tab(index, 1, index, InGroup(index // 2), "\x00" * 300, "https://example.com/" + "\x00" * 970, active=False, pinned=False, muted=False)
        for index in range(65)
    )
    groups = tuple(Group(index, 1, "\x00" * 300, "blue", collapsed=True, shared=False) for index in range(33))
    browser = connected_browser(tmp_path / "unused", Channel(), strip=FixedStrip(TabState(tabs, groups, (1,), 1)))
    browser.native_targets["last-page"] = 64
    offset = 0
    seen: list[int] = []
    try:
        while True:
            output = browser.request(command("tabs", **{"view": "strip", "offset": offset, "limit": 40}), threading.Event()).text
            assert len(output) <= MAX_OUTPUT
            data = decoded(output)
            rows, group_rows = data["tabs"], data["groups"]
            assert isinstance(rows, list) and isinstance(group_rows, list)
            page = tuple(tab_of(row) for row in rows)
            seen.extend(tab.id for tab in page)
            assert {group_of(group).id for group in group_rows} == {tab.group_id for tab in page}
            if "next_offset" not in data:
                assert isinstance(rows[-1], dict) and rows[-1]["target_id"] == "last-page"
                break
            next_offset = data["next_offset"]
            assert isinstance(next_offset, int) and next_offset > offset
            offset = next_offset
        assert seen == list(range(65))
    finally:
        browser.close()


def test_unavailable_native_apis_close_only_the_hidden_controller() -> None:
    commands: list[tuple[str, dict[str, Json]]] = []

    def call(method: str, params: dict[str, Json], cancel: threading.Event, *, session: str = "", timeout: float = 15) -> dict[str, Json]:
        commands.append((method, params))
        responses: dict[str, dict[str, Json]] = {
            "Target.createTarget": {"targetId": "hidden"},
            "Target.attachToTarget": {"sessionId": "control"},
            "Runtime.evaluate": {"result": {"value": {"ready": False}}},
            "Target.closeTarget": {"success": True},
        }
        return responses[method]

    strip = TabStrip(clock=iter((0.0, 6.0)).__next__)
    with TestCase().assertRaisesRegex(BrowserError, "native tab/group APIs"):
        strip.snapshot(call, threading.Event())
    assert commands[0] == ("Target.createTarget", {"url": "edge://favorites/", "background": True, "hidden": True})
    assert commands[-1] == ("Target.closeTarget", {"targetId": "hidden"}) and strip.control is None


def test_a_failed_group_change_is_not_replayed() -> None:
    commands: list[str] = []

    def call(method: str, params: dict[str, Json], cancel: threading.Event, *, session: str = "", timeout: float = 15) -> dict[str, Json]:
        commands.append(method)
        return {"exceptionDetails": {"text": "The group was changed, but its window was closed."}}

    strip = TabStrip()
    strip.control = Control("hidden", "session")
    with TestCase().assertRaisesRegex(BrowserError, "Inspect browser_tabs"):
        strip.group(call, group_request(GroupArguments(group_id=7, title="Research", window_id=8)), threading.Event())
    assert commands == ["Runtime.evaluate"]


def test_group_requests_fill_new_group_defaults_and_change_only_what_was_named() -> None:
    # Defect: a new group loses its Workspace defaults, an edit resets
    # unnamed properties, or a group is moved when no position was requested.
    created = group_request(GroupArguments(tab_ids=(2, 1, 2)))
    assert created == CreateGroup((2, 1), NewGroup("Workspace", "blue", collapsed=True), None, None)
    placed = group_request(GroupArguments(tab_ids=(1,), title="Review", color="red", collapsed=False, index=3, window_id=8))
    assert placed == CreateGroup((1,), NewGroup("Review", "red", collapsed=False), 8, Move(3, None))
    assert group_request(GroupArguments(group_id=7, title="Ready")) == EditGroup(7, (), GroupChanges("Ready", None, collapsed=None), None)
    assert group_request(GroupArguments(group_id=7, window_id=8)) == EditGroup(7, (), GroupChanges(None, None, collapsed=None), Move(-1, 8))
    assert group_request(GroupArguments(group_id=7, index=2)) == EditGroup(7, (), GroupChanges(None, None, collapsed=None), Move(2, None))
    with TestCase().assertRaises(BrowserError):
        group_request(GroupArguments())


def test_strip_filters_select_only_the_requested_window_and_group() -> None:
    # Defect: a filtered listing includes tabs from another window or group,
    # so a later reconciliation reads the wrong tab as the requested one.
    tabs = (
        Tab(1, 1, 0, InGroup(5), "a", "https://a.example", active=False, pinned=False, muted=False),
        Tab(2, 1, 1, Ungrouped.TABS, "b", "https://b.example", active=False, pinned=False, muted=False),
        Tab(3, 2, 0, InGroup(5), "c", "https://c.example", active=False, pinned=False, muted=False),
    )
    state = TabState(tabs, (Group(5, 1, "Workspace", "blue", collapsed=False, shared=False),), (1, 2), 1)

    def listed(window: int | None, group: InGroup | Ungrouped | None) -> tuple[int, ...]:
        page = strip_page(state, StripQuery(0, 40, window, group), "attached", {}, maximum=MAX_OUTPUT)
        return tuple(row.tab_id for row in page.tabs)

    assert listed(None, None) == (1, 2, 3)
    assert listed(1, None) == (1, 2)
    assert listed(None, InGroup(5)) == (1, 3)
    assert listed(1, Ungrouped.TABS) == (2,)


def test_only_a_complete_unfiltered_listing_proves_unlisted_tabs_closed(tmp_path: Path) -> None:
    # Defect: a paged or filtered listing marks every omitted tab or page as
    # closed, letting an unrelated observation reconcile a pending close.
    readback = ToolRig(work=durable(tmp_path)).agent.tools["browser_tabs"].readback
    row = TabRow(1, 1, 0, -1, "", "", active=False, pinned=False, muted=False)

    def strip(following: int | None) -> str:
        return STRIP_PAGE.dump_json(StripPage("attached", (row,), (), 1, 0, following), exclude_none=True).decode()

    def pages(following: int | None) -> str:
        return TypeAdapter(BrowserStatus).dump_json(BrowserStatus("attached", (), next_offset=following), exclude_none=True).decode()

    complete = target("browser-strip", "tabs")
    assert complete in readback({"view": "strip"}, strip(None)).resources
    for arguments in ({"view": "strip", "offset": 1}, {"view": "strip", "window_id": 1}, {"view": "strip", "group_id": -1}):
        assert complete not in readback(arguments, strip(None)).resources, arguments
    assert complete not in readback({"view": "strip"}, strip(1)).resources
    assert readback({}, pages(None)).resources == ("all:browser-page",)
    empty = STRIP_PAGE.dump_json(StripPage("attached", (), (), 0, 0), exclude_none=True).decode()
    assert readback({"view": "strip"}, empty).resources == (complete,)
    assert readback({}, pages(1)).resources == ()
    assert readback({"offset": 1}, pages(None)).resources == ()
