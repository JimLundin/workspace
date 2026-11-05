"""The recording trigger reads real browser DOM without activating the meeting."""

import sys
import threading
import unittest
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("Native Teams DOM detection")

from assistant.browser import Browser
from assistant.browser_requests import Evaluate, Open
from assistant.meeting_browser import OBSERVE, PAGE_CALL
from tests.browser_fixture import fixture
from tests.native_browser_fixture import disposable, request

MIC = '<button data-tid="call-microphone">Mute</button>'
LEAVE = '<button data-tid="call-hangup">Leave</button>'
DURATION = '<span data-tid="call-duration">00:05</span>'


def test_in_call_controls_exclude_prejoin_lobby_and_hidden_stale_controls(tmp_path: Path) -> None:
    # Defects: opening chat, prejoin or lobby starts recording; cached hidden
    # controls look connected; observing a meeting brings its window forward.
    documents = {
        "/chat": "<title>Chat</title><span>Meeting in progress</span>",
        "/prejoin": MIC + LEAVE + DURATION + '<button data-tid="prejoin-join-button">Join now</button>',
        "/lobby": MIC + LEAVE + DURATION + '<div data-tid="lobby-screen">Waiting</div>',
        "/connected": "<title>Private meeting</title>" + MIC + LEAVE + DURATION,
        "/connecting": MIC + LEAVE + '<span data-tid="call-duration">--:--</span>',
        "/hidden": MIC + DURATION + '<div style="display:none">' + LEAVE + "</div>",
        "/left": MIC,
    }
    cancel = threading.Event()
    with disposable(Browser(tmp_path / "meeting-dom")) as browser, fixture(pages=documents) as url:
        # `open` runs the managed browser hidden; connecting it visibly first only
        # forced a relaunch whose slow Edge exit failed the test under load.
        page = request(browser, "open", url=url + "chat")
        target = str(page["target_id"])
        connection = browser.connection
        assert connection is not None
        window = connection.call("Browser.getWindowForTarget", {"targetId": target}, cancel)["windowId"]
        connection.call("Browser.setWindowBounds", {"windowId": window, "bounds": {"windowState": "minimized"}}, cancel)
        bounds = connection.call("Browser.getWindowBounds", {"windowId": window}, cancel)
        for name in documents:
            browser.request(Open(url.rstrip("/") + name, target), cancel)
            observed = PAGE_CALL.validate_json(browser.request(Evaluate(target, OBSERVE, timeout_seconds=3), cancel).text)
            assert observed.phase == ("connected" if name == "/connected" else "outside"), name
            assert connection.call("Browser.getWindowBounds", {"windowId": window}, cancel) == bounds
