"""Teams reconnects and actions must reuse one tab, without launching Edge."""

import threading
from pathlib import Path
from unittest import TestCase

from assistant.browser_values import BrowserError, PageRow
from assistant.communications_browser import TeamsWeb
from automation.json_value import Json
from tests.teams_fixture import Browser


def web(folder: Path) -> tuple[TeamsWeb, Browser]:
    browser = Browser((PageRow("existing", "", "https://teams.cloud.microsoft/v2/"),))
    return TeamsWeb(folder, browser=browser), browser


def test_reconnect_reuses_existing_teams_when_saved_target_has_expired(tmp_path: Path) -> None:
    # A stale CDP ID must not allocate another Teams tab on every reconnect.
    cancel = threading.Event()
    for _ in range(3):
        current, browser = web(tmp_path)
        assert current.connect("expired", cancel) == "existing"
        assert current.connect("existing", cancel) == "existing"
        assert browser.opens == ()
        current.close()


def test_activity_and_open_share_the_selected_teams_tab(tmp_path: Path) -> None:
    # Splitting inspection/activity from collection would create extra tabs.
    current, browser = web(tmp_path)
    cancel = threading.Event()
    current.connect("", cancel)
    identity = "19:one@thread.v2"
    document: Json = {"current": identity, "title": "Anna", "conversations": [], "messages": [], "editor_ready": True}
    browser.document = document
    assert current.activity(cancel).items == ()
    current.open(identity, cancel)
    assert browser.wakes == ("existing", "existing")
    assert browser.activations == ("existing",)
    assert browser.opens == ()


def test_connect_without_an_existing_teams_tab_does_not_open_one(tmp_path: Path) -> None:
    # Automatic recovery must not turn a closed Teams tab into more tabs.
    browser = Browser()
    current = TeamsWeb(tmp_path, browser=browser)
    with TestCase().assertRaisesRegex(BrowserError, "Open Teams"):
        current.connect("", threading.Event())
    assert browser.opens == ()
    current.close()


def test_visible_shared_tab_pauses_activity_before_navigation(tmp_path: Path) -> None:
    # Background Activity must not switch the page the user is currently reading.
    current, browser = web(tmp_path)
    cancel = threading.Event()
    current.connect("", cancel)
    browser.visibility = "visible"
    with TestCase().assertRaisesRegex(BrowserError, "paused"):
        current.activity(cancel)
    assert browser.wakes == () and browser.opens == ()
    current.close()
