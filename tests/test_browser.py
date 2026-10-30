"""CDP transport failures and browser limits do not leave ambiguous side effects."""

import base64
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast
from unittest import TestCase

from websockets.sync.server import ServerConnection, serve

from assistant.browser import MAX_OUTPUT, Browser, web_url
from assistant.browser_session import MAX_RESPONSE, Attached, BrowserSession, Cdp, Managed, Product, Separate, Source
from assistant.browser_tabs import TabStrip
from assistant.browser_values import BrowserError, InterruptedError, NavigationContextError
from assistant.llm import Json

VIEWPORT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==",
)


def decoded(value: str) -> dict[str, Json]:
    result = cast(Json, json.loads(value))
    assert isinstance(result, dict)
    return result


class Channel:
    __slots__ = ("cancel", "closed", "replies", "sent")

    def __init__(self, *replies: str | bytes | Exception, cancel: threading.Event | None = None) -> None:
        self.replies = list(replies)
        self.sent: list[dict[str, Json]] = []
        self.closed = False
        self.cancel = cancel

    def send(self, message: str) -> None:
        self.sent.append(decoded(message))

    def recv(self, timeout: float) -> str | bytes:
        assert 0 < timeout <= 0.1
        if self.cancel is not None:
            self.cancel.set()
        result = self.replies.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self) -> None:
        self.closed = True

    @classmethod
    def results(cls, *results: dict[str, Json]) -> Channel:
        return cls(*(json.dumps(dict[str, Json](id=index, result=result)) for index, result in enumerate(results, 1)))


class ScriptedSessions:
    def __init__(self, *sessions: BrowserSession | Exception) -> None:
        self.sessions = list(sessions)
        self.opened: list[tuple[Source, bool]] = []

    def open(self, source: Source, cancel: threading.Event, *, visible: bool = False) -> BrowserSession:
        self.opened.append((source, visible))
        session = self.sessions.pop(0)
        if isinstance(session, Exception):
            raise session
        return session


def connected_browser(
    path: Path,
    channel: Channel,
    *,
    owner: Attached | Managed | None = None,
    strip: TabStrip | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Browser:
    owner = owner if owner is not None else Attached(Product.EDGE)
    source = owner.product if isinstance(owner, Attached) else Separate.PROFILE
    browser = Browser(path, source=source, opener=ScriptedSessions(BrowserSession(Cdp(channel, clock=clock), owner)), strip=strip)
    browser.connect(threading.Event(), visible=isinstance(owner, Managed) and owner.visible)
    return browser


def screenshot_channel() -> Channel:
    return Channel.results(
        {"targetInfos": [{"type": "page", "targetId": "fixture"}]},
        {"sessionId": "page-session"},
        {},
        {"data": base64.b64encode(VIEWPORT_PNG).decode("ascii")},
        {},
    )


def test_background_activity_restores_focus_even_when_the_action_is_cancelled(tmp_path: Path) -> None:
    channel = Channel.results({"targetInfos": [{"type": "page", "targetId": "fixture"}]}, {"sessionId": "page-session"}, {}, {}, {})
    browser = connected_browser(tmp_path, channel)
    cancel = threading.Event()
    try:
        with TestCase().assertRaisesRegex(InterruptedError, "Action stopped"), browser.awake("fixture", cancel):
            cancel.set()
            raise InterruptedError("Action stopped")
        changes = [item["params"] for item in channel.sent if item["method"] == "Emulation.setFocusEmulationEnabled"]
        assert changes == [{"enabled": True}, {"enabled": False}]
        assert browser.connection is not None
    finally:
        browser.close()


def test_background_activity_resumes_a_frozen_page_before_running_work(tmp_path: Path) -> None:
    """Detect focus emulation being used without resuming the page's lifecycle."""

    class FrozenPage(Channel):
        # This native-page adapter owns its lifecycle observation for one test.
        __slots__ = ("running",)

        def __init__(self) -> None:
            super().__init__(
                *Channel.results(
                    {"targetInfos": [{"type": "page", "targetId": "fixture"}]},
                    {"sessionId": "page-session"},
                    {},
                    {},
                    {},
                ).replies
            )
            self.running = False

        def send(self, message: str) -> None:
            super().send(message)
            command = decoded(message)
            if command["method"] == "Page.setWebLifecycleState" and command["params"] == {"state": "active"}:
                self.running = True

    channel = FrozenPage()
    browser = connected_browser(tmp_path, channel)
    try:
        with browser.awake("fixture", threading.Event()):
            assert channel.running, "Background work began while its native page was frozen."
        assert all(command["method"] != "Target.activateTarget" for command in channel.sent)
    finally:
        browser.close()


def test_cdp_ignores_events_and_late_replies_and_preserves_session() -> None:
    channel = Channel('{"method":"Page.loadEventFired"}', '{"id":99,"result":{}}', TimeoutError(), '{"id":1,"result":{"value":42}}')
    cdp = Cdp(channel)
    assert cdp.call("Runtime.evaluate", {"expression": "21*2"}, threading.Event(), session="page-session") == {"value": 42}
    assert channel.sent == [{"id": 1, "method": "Runtime.evaluate", "params": {"expression": "21*2"}, "sessionId": "page-session"}]
    cdp.close()
    assert channel.closed


def test_cdp_cancellation_and_timeout_never_repeat_an_action() -> None:
    stop = threading.Event()
    channel = Channel('{"method":"Page.loadEventFired"}', cancel=stop)
    with TestCase().assertRaisesRegex(InterruptedError, "may already have completed"):
        Cdp(channel).call("Input.dispatchMouseEvent", {}, stop)
    assert len(channel.sent) == 1
    channel = Channel()
    with TestCase().assertRaisesRegex(InterruptedError, "Stopped"):
        Cdp(channel).call("Page.navigate", {}, stop)
    assert not channel.sent
    with TestCase().assertRaisesRegex(BrowserError, "timed out"):
        Cdp(channel).call("Runtime.evaluate", {}, threading.Event(), timeout=0)
    assert len(channel.sent) == 1


def test_slow_page_keeps_the_connection_and_accepts_the_next_response(tmp_path: Path) -> None:
    channel = Channel.results(
        {"targetInfos": [{"type": "page", "targetId": "fixture"}]},
        {"sessionId": "page-session"},
        {"frameTree": {"frame": {"id": "main"}}},
        {"executionContextId": 1},
        {"result": {"value": "late reply"}},
        {"targetInfos": [{"type": "page", "targetId": "fixture"}]},
    )

    def clock() -> float:
        return 20.0 if channel.sent and channel.sent[-1]["method"] == "Runtime.evaluate" else 0.0

    browser = connected_browser(tmp_path, channel, clock=clock)
    connection = browser.connection
    try:
        with TestCase().assertRaisesRegex(BrowserError, "timed out") as raised:
            browser.request("evaluate", {"target_id": "fixture", "expression": "1"}, threading.Event())
        assert not isinstance(raised.exception, InterruptedError)
        assert browser.connection is connection and not channel.closed
        assert decoded(browser.request("tabs", {}, threading.Event()).text)["mode"] == "attached"
        assert [call["method"] for call in channel.sent].count("Runtime.evaluate") == 1
    finally:
        browser.close()


def test_cdp_rejects_malformed_oversized_and_error_replies() -> None:
    for response, message in (
        ("not JSON", "invalid data"),
        ("[]", "unexpected response"),
        ('{"id":1,"error":{"message":"Page is closed"}}', "Page is closed"),
        ("x" * (MAX_RESPONSE + 1), "size limit"),
    ):
        with TestCase().assertRaisesRegex(BrowserError, message):
            Cdp(Channel(response)).call("Page.getFrameTree", {}, threading.Event())


def test_retired_page_context_does_not_close_or_repeat_a_browser_request() -> None:
    channel = Channel('{"id":1,"error":{"message":"Cannot find context with specified id"}}', '{"id":2,"result":{"value":42}}')
    cdp = Cdp(channel)
    try:
        with TestCase().assertRaises(NavigationContextError):
            cdp.call("Runtime.evaluate", {"expression": "read()"}, threading.Event(), session="page")
        assert not channel.closed
        assert cdp.call("Runtime.evaluate", {"expression": "read()"}, threading.Event(), session="page") == {"value": 42}
        assert len(channel.sent) == 2
    finally:
        cdp.close()


def test_cdp_refuses_non_loopback_debugging_and_proxy_use() -> None:
    for uri in ("ws://localhost:9222/", "wss://127.0.0.1:9222/", "ws://example.com/", "ws://user:pass@127.0.0.1:9222/", "ws://[broken"):
        with TestCase().assertRaisesRegex(BrowserError, "loopback"):
            Cdp.connect(uri)
    connected = threading.Event()

    def accept(connection: ServerConnection) -> None:
        connected.set()
        for _message in connection:
            raise AssertionError("The proxy-bypass check must not send a browser command.")

    # A separate process owns its proxy environment. This observes our real
    # transport choosing a direct connection even when loopback is not exempt.
    with serve(accept, "127.0.0.1", 0, ping_interval=None, close_timeout=0.5) as server:
        port = cast(tuple[str, int], server.socket.getsockname())[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            environment = dict(os.environ)
            for name in (
                "http_proxy",
                "https_proxy",
                "all_proxy",
                "ws_proxy",
                "wss_proxy",
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "WS_PROXY",
                "WSS_PROXY",
            ):
                environment[name] = "http://127.0.0.1:1"
            environment["no_proxy"] = environment["NO_PROXY"] = ""
            script = (
                "from assistant.browser_session import Cdp\n"
                f"connection = Cdp.connect('ws://127.0.0.1:{port}/devtools/browser/fixture')\n"
                "connection.close()\n"
            )
            result = subprocess.run([sys.executable, "-c", script], check=False, env=environment, capture_output=True, text=True, timeout=10)
            assert result.returncode == 0, result.stderr
            assert connected.is_set(), "The browser transport did not reach its local endpoint."
        finally:
            server.shutdown()
            thread.join(timeout=2)


def test_browser_initialization_and_status_do_not_launch_or_create_a_profile(tmp_path: Path) -> None:
    browser = Browser(tmp_path / "profile")
    assert decoded(browser.request("tabs", {}, threading.Event()).text) == {"mode": "stopped", "tabs": []}
    assert not browser.profile.exists()
    stop = threading.Event()
    stop.set()
    with TestCase().assertRaisesRegex(InterruptedError, "Stopped"):
        browser.request("open", {"url": "https://example.com"}, stop)
    assert browser.process is None and not browser.profile.exists()


def test_browser_accepts_web_pages_but_not_embedded_credentials_or_local_schemes() -> None:
    for url in ("https://example.com/a?q=1", "http://127.0.0.1:12345/", "about:blank"):
        assert web_url(url) == url
    for url in ("file:///c:/secret", "javascript:alert(1)", "https://user:secret@example.com", "https://example.com/\nsecret", "https://[broken"):
        with TestCase().assertRaises(BrowserError):
            web_url(url)


def test_browser_snapshot_limits_keep_valid_json_and_progress_offsets(tmp_path: Path) -> None:
    source: dict[str, Json] = {
        "title": "Fixture",
        "url": "https://example.com",
        "text": "\x00" * 6000,
        "text_offset": 0,
        "text_total": 7000,
        "controls": [
            {"id": str(i), "tag": "a", "role": "", "type": "", "name": "n" * 300, "value": "", "href": "", "disabled": False, "checked": False}
            for i in range(100)
        ],
        "offset": 4,
        "total": 104,
        "more_controls": False,
        "scan_limited": False,
    }
    channel = Channel.results(
        {"targetInfos": [{"type": "page", "targetId": "fixture"}]},
        {"sessionId": "page-session"},
        {"frameTree": {"frame": {"id": "main", "url": "https://example.com"}}},
        {"executionContextId": 1},
        {"result": {"value": source}},
    )
    browser = connected_browser(tmp_path, channel)
    output = browser.request("snapshot", {"target_id": "fixture", "offset": 4}, threading.Event()).text
    assert len(output) <= MAX_OUTPUT
    page = decoded(output)
    assert page["more_controls"] and page["next_text_offset"] == len(cast(str, page["text"]))
    assert page["controls"]
    assert page["next_control_offset"] == 4 + len(cast(list[Json], page["controls"]))


def test_browser_screenshot_resets_focus_before_returning_the_image(tmp_path: Path) -> None:
    channel = screenshot_channel()
    browser = connected_browser(tmp_path, channel)
    try:
        result = browser.request("screenshot", {"target_id": "fixture"}, threading.Event())
        assert result.image == VIEWPORT_PNG
        assert "viewport" in result.text
        assert not channel.replies, "The focus reset must be acknowledged before the image is returned."
        assert not channel.closed and browser.connection is not None
        assert [(call["method"], call["params"], call.get("sessionId")) for call in channel.sent[2:]] == [
            ("Emulation.setFocusEmulationEnabled", {"enabled": True}, "page-session"),
            ("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}, "page-session"),
            ("Emulation.setFocusEmulationEnabled", {"enabled": False}, "page-session"),
        ]
    finally:
        browser.close()


def test_browser_bad_screenshot_resets_focus_before_reporting_a_tool_error(tmp_path: Path) -> None:
    for data in ("invalid base64!", "aGVsbG8="):
        channel = Channel.results(
            {"targetInfos": [{"type": "page", "targetId": "fixture"}]},
            {"sessionId": "page-session"},
            {},
            {"data": data},
            {},
        )
        browser = connected_browser(tmp_path, channel)
        try:
            with TestCase().assertRaisesRegex(BrowserError, "invalid"):
                browser.request("screenshot", {"target_id": "fixture"}, threading.Event())
            assert not channel.replies and channel.sent[-1]["params"] == {"enabled": False}
            assert browser.connection is not None and not channel.closed
        finally:
            browser.close()


def test_browser_capture_failure_is_preserved_after_successful_focus_reset(tmp_path: Path) -> None:
    channel = screenshot_channel()
    channel.replies[3] = '{"id":4,"error":{"message":"Screenshot capture failed"}}'
    browser = connected_browser(tmp_path, channel)
    try:
        with TestCase().assertRaisesRegex(BrowserError, "^Screenshot capture failed$"):
            browser.request("screenshot", {"target_id": "fixture"}, threading.Event())
        assert not channel.replies and channel.sent[-1]["params"] == {"enabled": False}
        assert browser.connection is not None and not channel.closed
        assert [call["method"] for call in channel.sent].count("Page.captureScreenshot") == 1
    finally:
        browser.close()


def test_browser_failed_focus_enable_still_resets_without_capturing(tmp_path: Path) -> None:
    channel = screenshot_channel()
    channel.replies[2:] = ['{"id":3,"error":{"message":"Focus enable failed"}}', '{"id":4,"result":{}}']
    browser = connected_browser(tmp_path, channel)
    try:
        with TestCase().assertRaisesRegex(BrowserError, "^Focus enable failed$"):
            browser.request("screenshot", {"target_id": "fixture"}, threading.Event())
        assert not channel.replies and channel.sent[-1]["params"] == {"enabled": False}
        assert "Page.captureScreenshot" not in [call["method"] for call in channel.sent]
        assert browser.connection is not None and not channel.closed
    finally:
        browser.close()


def test_browser_failed_focus_reset_discards_the_image_and_detaches_a_personal_browser(tmp_path: Path) -> None:
    channel = screenshot_channel()
    channel.replies[4] = '{"id":5,"error":{"message":"Focus reset failed"}}'
    browser = connected_browser(tmp_path, channel)
    with TestCase().assertRaisesRegex(BrowserError, "^Focus reset failed$"):
        browser.request("screenshot", {"target_id": "fixture"}, threading.Event())
    assert not channel.replies and channel.closed
    assert browser.connection is None and not browser.sessions
    assert decoded(browser.request("tabs", {}, threading.Event()).text)["mode"] == "stopped"
    assert "Browser.close" not in [call["method"] for call in channel.sent]


def test_browser_preserves_focus_reset_failure_when_owned_process_cleanup_also_fails(tmp_path: Path) -> None:
    class FinishedProcess:
        __slots__ = ()
        pid = 42

        def poll(self) -> int | None:
            return 0

        def wait(self, timeout: float) -> int:
            assert timeout > 0
            return 0

        def kill(self) -> None:
            raise AssertionError("An exited browser must not be killed.")

    class FailedJobCleanup:
        __slots__ = ()

        def close(self) -> None:
            raise OSError("The owned browser processes did not finish exiting in time.")

    channel = screenshot_channel()
    channel.replies[4] = '{"id":5,"error":{"message":"Focus reset failed"}}'
    channel.replies.append('{"id":6,"result":{}}')
    browser = connected_browser(tmp_path, channel, owner=Managed(FinishedProcess(), FailedJobCleanup(), visible=False))
    with TestCase().assertRaisesRegex(BrowserError, "^Focus reset failed$") as failure:
        browser.request("screenshot", {"target_id": "fixture"}, threading.Event())
    assert any("owned browser processes did not finish exiting" in note for note in failure.exception.__notes__)
    assert not channel.replies and channel.closed
    assert browser.connection is None and not browser.sessions
    assert [call["method"] for call in channel.sent].count("Browser.close") == 1


def test_browser_preserves_the_primary_failure_when_focus_reset_also_fails(tmp_path: Path) -> None:
    for primary in ("enable", "capture"):
        channel = screenshot_channel()
        if primary == "enable":
            channel.replies[2:] = [
                '{"id":3,"error":{"message":"Primary failure"}}',
                '{"id":4,"error":{"message":"Focus reset failed"}}',
            ]
        else:
            channel.replies[3:] = [
                '{"id":4,"error":{"message":"Primary failure"}}',
                '{"id":5,"error":{"message":"Focus reset failed"}}',
            ]
        browser = connected_browser(tmp_path, channel)
        with TestCase().assertRaisesRegex(BrowserError, "^Primary failure$") as failure:
            browser.request("screenshot", {"target_id": "fixture"}, threading.Event())
        assert any("Focus reset failed" in note for note in failure.exception.__notes__)
        assert not channel.replies and channel.closed and browser.connection is None
        assert "Browser.close" not in [call["method"] for call in channel.sent]


def test_browser_canceled_capture_closes_only_its_owned_browser(tmp_path: Path) -> None:
    class Process:
        __slots__ = ("waited",)
        pid = 42

        def __init__(self) -> None:
            self.waited = False

        def poll(self) -> int | None:
            return None

        def wait(self, timeout: float) -> int:
            assert timeout > 0
            self.waited = True
            return 0

        def kill(self) -> None:
            raise AssertionError("The owned browser closed gracefully; it must not be killed again.")

    class CancelCaptureChannel(Channel):
        __slots__ = ("stop",)

        def __init__(self, stop: threading.Event) -> None:
            super().__init__(
                *Channel.results({"targetInfos": [{"type": "page", "targetId": "fixture"}]}, {"sessionId": "page-session"}, {}).replies,
                '{"id":5,"result":{}}',
            )
            self.stop = stop

        def recv(self, timeout: float) -> str | bytes:
            if self.sent[-1]["method"] == "Page.captureScreenshot":
                self.stop.set()
                return '{"method":"Page.loadEventFired"}'
            return super().recv(timeout)

    process = Process()
    for owner in (Attached(Product.EDGE), Managed(process, None, visible=False)):
        stop = threading.Event()
        channel = CancelCaptureChannel(stop)
        browser = connected_browser(tmp_path, channel, owner=owner)
        with TestCase().assertRaisesRegex(InterruptedError, "may already have completed"):
            browser.request("screenshot", {"target_id": "fixture"}, stop)
        assert stop.is_set() and channel.closed and browser.connection is None
        assert not browser.sessions
        methods = [call["method"] for call in channel.sent]
        assert methods.count("Page.captureScreenshot") == 1
        assert methods.count("Browser.close") == int(isinstance(owner, Managed))
        assert process.waited == isinstance(owner, Managed)
        browser.close()


def test_closing_a_tab_does_not_require_page_scripting_access(tmp_path: Path) -> None:
    channel = Channel(
        '{"id":1,"result":{"targetInfos":[{"type":"page","targetId":"settings","url":"edge://settings"}]}}',
        '{"id":2,"result":{"success":true}}',
        '{"id":3,"result":{"targetInfos":[]}}',
    )
    browser = connected_browser(tmp_path / "unused", channel)
    try:
        closed = decoded(browser.request("close", {"target_id": "settings"}, threading.Event()).text)
        assert closed == {"target_id": "settings", "state": "closed"}
        assert [command["method"] for command in channel.sent] == ["Target.getTargets", "Target.closeTarget", "Target.getTargets"]
    finally:
        browser.close()


def test_close_waits_for_removal_without_repeating_the_request(tmp_path: Path) -> None:
    targets: dict[str, Json] = {"targetInfos": [{"type": "page", "targetId": "closing", "url": "about:blank"}]}
    replies: tuple[Json, ...] = (targets, {"success": True}, targets, {"targetInfos": []})
    channel = Channel(*(json.dumps(dict[str, Json](id=index, result=reply)) for index, reply in enumerate(replies, 1)))
    browser = connected_browser(tmp_path / "unused", channel)
    try:
        result = decoded(browser.request("close", {"target_id": "closing"}, threading.Event()).text)
        assert result["state"] == "closed"
        assert [command["method"] for command in channel.sent].count("Target.closeTarget") == 1
    finally:
        browser.close()


def test_browser_waits_for_the_root_after_job_termination_instead_of_killing_it_twice(tmp_path: Path) -> None:
    class ExitingProcess:
        __slots__ = ("job_closed",)
        pid = 42

        def __init__(self) -> None:
            self.job_closed = False

        def poll(self) -> int | None:
            return None  # Windows has not signalled the process handle yet.

        def wait(self, timeout: float) -> int:
            if not self.job_closed or timeout < 5:
                raise subprocess.TimeoutExpired("fixture", timeout)
            return 0  # Job termination can precede the process handle's exit signal.

        def kill(self) -> None:
            raise PermissionError("Windows refuses a second termination while a process is exiting.")

    process = ExitingProcess()

    class Job:
        __slots__ = ()

        def close(self) -> None:
            process.job_closed = True

    browser = connected_browser(tmp_path / "profile", Channel.results({}), owner=Managed(process, Job(), visible=False))
    browser.close()
    assert process.job_closed


def test_browser_allows_normal_shutdown_before_forcing_its_owned_job(tmp_path: Path) -> None:
    """Detect a grace period that interrupts a browser already closing normally."""

    class ClosingProcess:
        # This adapter owns one pending exit and publishes its exit observation.
        __slots__ = ("returncode",)
        pid = 42

        def __init__(self) -> None:
            self.returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float) -> int:
            if self.returncode is None:
                if timeout < 3:
                    raise subprocess.TimeoutExpired("closing fixture", timeout)
                self.returncode = 0
            return self.returncode

        def kill(self) -> None:
            raise AssertionError("A normally closing owned browser must not be killed.")

    process = ClosingProcess()

    class Job:
        # Keep the termination observation local to this fixture lifetime.
        __slots__ = ("closed", "terminated_running_root")

        def __init__(self) -> None:
            self.terminated_running_root = False
            self.closed = False

        def close(self) -> None:
            self.closed = True
            if process.poll() is None:
                self.terminated_running_root = True
                process.returncode = 1

    job = Job()
    browser = connected_browser(tmp_path / "profile", Channel.results({}), owner=Managed(process, job, visible=False))
    browser.close()
    assert process.poll() == 0 and job.closed and not job.terminated_running_root
