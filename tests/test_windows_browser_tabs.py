"""Real Edge tab groups and native IDs, using only disposable browser profiles."""

import sys
import threading
import unittest
from pathlib import Path
from typing import cast

if sys.platform != "win32":
    raise unittest.SkipTest("Native Edge tab groups")

from assistant.browser import Browser, Product
from assistant.browser_session import NativeSessions
from assistant.browser_values import Group, Tab, group_of, tab_of

from .browser_fixture import fixture
from .test_browser import decoded
from .test_windows_browser import dispose, installed, request


def strip(browser: Browser) -> tuple[dict[int, Tab], dict[int, Group]]:
    page = request(browser, "tabs", view="strip", limit=40)
    rows, groups = page["tabs"], page["groups"]
    assert isinstance(rows, list) and isinstance(groups, list)
    tabs = tuple(tab_of(row) for row in rows)
    native_groups = tuple(group_of(group) for group in groups)
    return {tab.id: tab for tab in tabs}, {group.id: group for group in native_groups}


def test_native_tab_groups_ids_moves_and_disconnect_preserve_user_state(tmp_path: Path) -> None:
    installed()
    personal = Browser(tmp_path / "personal")
    attached = Browser(
        tmp_path / "unused", source=Product.EDGE,
        opener=NativeSessions(tmp_path / "unused", profiles=lambda _: personal.profile),
    )
    cancel = threading.Event()
    try:
        with fixture() as url:
            original = request(personal, "open", url=url)
            blank = request(personal, "open", url="about:blank")
            request(attached, "attach")
            before, _groups = strip(attached)
            active = {tab.id for tab in before.values() if tab.active}
            first = request(attached, "open", url=url)
            second = request(attached, "open", url="about:blank")
            first_id, second_id = cast(int, first["tab_id"]), cast(int, second["tab_id"])
            tabs, groups = strip(attached)
            group = groups[tabs[first_id].group_id]
            assert group.title == "Workspace" and group.collapsed and group.color == "blue"
            assert tabs[second_id].group_id == group.id
            assert {tab.id for tab in tabs.values() if tab.active} == active, (before, tabs)
            assert all(tabs[identity] == tab for identity, tab in before.items())
            assert tabs[first_id].url == url and tabs[second_id].url == "about:blank"
            assert first["target_id"] not in (original["target_id"], blank["target_id"])
            assert "Workspace browser fixture" in str(request(attached, "snapshot", target_id=first["target_id"]))
            control = attached.strip.control
            assert control is not None and all(tab.url != "edge://favorites/" for tab in tabs.values())

            # The user opens the group to collaborate. A reconnect must preserve it.
            request(attached, "group", group_id=group.id, collapsed=False)
            attached.request("close", {}, cancel)
            assert personal.connection is not None
            targets = personal.connection.call("Target.getTargets", {}, cancel)["targetInfos"]
            assert isinstance(targets, list) and all(not isinstance(target, dict) or target["targetId"] != control.target for target in targets)
            request(attached, "attach")
            third = request(attached, "open", url=url)
            tabs, groups = strip(attached)
            assert tabs[cast(int, third["tab_id"])].group_id == group.id and not groups[group.id].collapsed
            assert {tab.id for tab in tabs.values() if tab.active} == active, (before, tabs)
            assert len([item for item in groups.values() if item.title == "Workspace"]) == 1

            closed = request(attached, "close", group_id=group.id)
            assert closed["closed_count"] == 3
            tabs, groups = strip(attached)
            assert tabs == before and not groups
            assert personal.process is not None and personal.process.poll() is None
            assert not attached.profile.exists()

            # Each scenario restores its created tabs before the next one.
            identical_urls(attached, before)
            assert decoded(personal.request("tabs", {}, cancel).text)["tabs"]
            moves_between_windows(personal, attached, url)
            assert set(strip(attached)[0]) == set(before)
    finally:
        attached.close()
        dispose(personal)


def identical_urls(attached: Browser, before: dict[int, Tab]) -> None:
    cancel = threading.Event()
    first = request(attached, "open", url="about:blank")
    second = request(attached, "open", url="about:blank")
    first_id, second_id = cast(int, first["tab_id"]), cast(int, second["tab_id"])
    assert first_id != second_id and first["target_id"] != second["target_id"]
    changed = group_of(request(attached, "group", tab_ids=[second_id], title="Review", color="purple", collapsed=False))
    tabs, _groups = strip(attached)
    assert tabs[second_id].group_id == changed.id and tabs[first_id].group_id != changed.id
    result = request(attached, "ungroup", tab_ids=[second_id])
    assert result["group_id"] == -1
    assert tab_of(request(attached, "tab", tab_id=second_id, action="pin")).pinned
    assert not tab_of(request(attached, "tab", tab_id=second_id, action="unpin")).pinned
    request(attached, "tab", tab_id=second_id, action="move", index=-1)
    group = group_of(request(attached, "group", tab_ids=[first_id, second_id], title="Review", collapsed=True))
    renamed = group_of(request(attached, "group", group_id=group.id, title="Ready", color="green", index=-1))
    assert renamed.title == "Ready" and renamed.color == "green" and renamed.collapsed

    # Explicit group operations also accept tabs that Workspace did not create.
    user_id = next(tab.id for tab in before.values() if tab.active)
    request(attached, "group", group_id=group.id, tab_ids=[user_id], collapsed=False)
    assert strip(attached)[0][user_id].group_id == group.id
    request(attached, "ungroup", tab_ids=[user_id])
    closed = request(attached, "close", tab_ids=[second_id])
    assert closed["closed_tab_ids"] == [second_id]
    assert first_id in strip(attached)[0]
    attached.request("close", {"target_id": first["target_id"]}, cancel)
    tabs, _groups = strip(attached)
    assert set(tabs) == set(before), (before, tabs)
    assert tabs[user_id].url == before[user_id].url and tabs[user_id].active


def moves_between_windows(personal: Browser, attached: Browser, url: str) -> None:
    cancel = threading.Event()
    page = request(attached, "open", url=url)
    identity = cast(int, page["tab_id"])
    tabs, _groups = strip(attached)
    original_window = tabs[identity].window_id
    group_id = tabs[identity].group_id
    assert personal.connection is not None
    personal.connection.call("Target.createTarget", {"url": url + "spare", "background": True, "newWindow": True}, cancel)
    tabs, _groups = strip(attached)
    other = next(tab for tab in tabs.values() if tab.url == url + "spare")
    assert other.window_id != original_window
    active = {tab.window_id: tab.id for tab in tabs.values() if tab.active}

    moved = group_of(request(attached, "group", group_id=group_id, window_id=other.window_id, index=-1))
    assert moved.window_id == other.window_id and moved.collapsed
    tabs, _groups = strip(attached)
    assert tabs[identity].window_id == other.window_id
    assert {tab.window_id: tab.id for tab in tabs.values() if tab.active} == active

    moved_tab = tab_of(request(attached, "tab", tab_id=identity, action="move", window_id=original_window, index=-1))
    assert moved_tab.window_id == original_window and moved_tab.group_id == -1
    tabs, _groups = strip(attached)
    assert {tab.window_id: tab.id for tab in tabs.values() if tab.active} == active
    shown = tab_of(request(attached, "tab", tab_id=identity, action="activate"))
    assert shown.active and shown.id == identity
    reloaded = tab_of(request(attached, "tab", tab_id=identity, action="reload"))
    assert reloaded.id == identity and reloaded.url == url
    request(attached, "close", tab_ids=[identity, other.id])
