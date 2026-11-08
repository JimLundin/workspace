"""The agent's machine owner over fake desktop, recording and browser owners."""

import threading
import unittest

from pydantic import TypeAdapter

from assistant import browser
from assistant.agent_tools import Machine
from assistant.browser import BrowserResult
from assistant.browser_requests import BrowserRequest
from assistant.browser_session import Separate
from assistant.browser_values import PageList
from assistant.machine import CaptureSources, WinMachine
from assistant.meeting_tools import MeetingCommand, MeetingOperation, StartMeeting
from assistant.web_apps import TEAMS_READ, Located, TeamsPage, TeamsQuery, WebAppOperation
from contracts.geometry import Shot, fit
from contracts.json_value import Json
from winapi.shapes import Rect

TEAMS_PAGE = TeamsPage("", "", (), (), editor_ready=False)


class Desktop:
    __slots__ = ("owner",)

    def __init__(self) -> None:
        self.owner = 0

    def capture(self, area: Rect, longest: int) -> tuple[bytes, Shot]:
        return b"capture", Shot(area, area.width, area.height)


class Recording:
    __slots__ = ("calls",)

    def __init__(self) -> None:
        self.calls: list[MeetingOperation] = []

    def request(self, operation: MeetingOperation) -> str:
        self.calls.append(operation)
        return "Recording owner status"


WIRE = TypeAdapter(dict[str, Json])


class Browser:
    __slots__ = ("calls", "failure")

    def __init__(self, failure: OSError | None = None) -> None:
        self.calls: list[str] = []
        self.failure = failure

    def request(self, request: BrowserRequest, cancel: threading.Event) -> BrowserResult:
        self.calls.append(f"request {request}")
        return BrowserResult("Browser observation", b"browser image")

    def web_app[Q: Located, R](self, operation: WebAppOperation[Q, R], query: Q, cancel: threading.Event) -> R:
        self.calls.append("web_app " + query.target_id)
        return operation.result.validate_python(TEAMS_PAGE)

    def close(self, *, keep_browser: bool = False) -> None:
        self.calls.append("close")
        if self.failure is not None:
            raise self.failure


def test_machine_uses_explicit_desktop_and_meeting_owners() -> None:
    # Defect: the machine rewrites the capture operation, drops the owner's
    # response, or fails to report an absent recording owner.
    desktop, recording = Desktop(), Recording()
    machine: Machine = WinMachine(desktop, browser=Browser(), meetings=recording)
    start = StartMeeting("microphone", "Planning")
    assert machine.meeting(start) == "Recording owner status"
    assert recording.calls[0] is start
    assert machine.meeting(MeetingCommand.STOP) == "Recording owner status"
    assert machine.meeting(MeetingCommand.RETRY) == "Recording owner status"
    assert machine.meeting(MeetingCommand.LIST) == "Recording owner status"
    assert recording.calls == [start, MeetingCommand.STOP, MeetingCommand.RETRY, MeetingCommand.LIST]
    try:
        WinMachine(desktop, browser=Browser()).meeting(MeetingCommand.STATUS)
    except OSError as error:
        assert str(error) == "Meeting recording is unavailable."
    else:
        raise AssertionError("A missing recording owner must be reported.")


def test_default_agent_browser_owns_an_exclusive_profile_without_launching() -> None:
    # Defect: composition silently attaches the agent to the user's Edge.
    machine = WinMachine(Desktop())
    match machine.browser:
        case browser.Browser(source=Separate.PROFILE, connection=None):
            pass
        case _:
            raise AssertionError("The agent must own its separate Edge profile.")
    assert machine.browse(PageList(), threading.Event())[0].startswith('{"mode":"stopped"')
    machine.close_background()


def test_machine_keeps_browser_cleanup_with_its_owner() -> None:
    browser = Browser(OSError("Browser disconnect failed"))
    machine = WinMachine(Desktop(), browser=browser)
    cancel = threading.Event()
    assert machine.browse(PageList(), cancel) == ("Browser observation", b"browser image")
    assert machine.web_app(TEAMS_READ, TeamsQuery("page"), cancel) == TEAMS_PAGE
    try:
        machine.close_background()
    except OSError as error:
        assert str(error) == "Browser disconnect failed"
    else:
        raise AssertionError("A failed disconnect must remain visible.")
    assert browser.calls == ["request PageList(offset=0, limit=20)", "web_app page", "close"]


def test_desktop_state_reports_the_real_monitors_windows_and_foreground() -> None:
    # Defect: the typed desktop observation drops or misassigns monitor and
    # window rows, so the model receives coordinates for the wrong surface.
    state = WIRE.validate_json(WinMachine(Desktop(), browser=Browser()).desktop_state())
    match state:
        case {"coordinates": "physical screen pixels", "monitors": [*monitors], "windows": [*rows], "foreground": int()}:
            assert monitors and sum(1 for monitor in monitors if isinstance(monitor, dict) and monitor["primary"] is True) == 1
            assert all(isinstance(row, dict) and isinstance(row["handle"], int) and isinstance(row["bounds"], dict) for row in rows)
        case _:
            raise AssertionError(f"Unexpected desktop observation: {state}")


def test_screenshot_sources_use_physical_bounds_and_scale_only_the_image() -> None:
    desktop = Rect(-1920, 0, 1920, 1080)
    left = Rect(-1920, 0, 0, 1080)
    work = Rect(-1700, 100, -900, 700)

    class CaptureDesktop(Desktop):
        def capture(self, area: Rect, longest: int) -> tuple[bytes, Shot]:
            size = fit(area.size, longest)
            return b"fixture", Shot(area, size.width, size.height)

    class Sources:
        # The fixture owns its current observation so availability can change
        # between two calls without replacing application/module attributes.
        def __init__(self) -> None:
            self.current = CaptureSources(left, desktop, (left, Rect(0, 0, 1920, 1080)), work)

        def observe(self, handle: int) -> CaptureSources:
            return self.current

    sources = Sources()
    machine = WinMachine(CaptureDesktop(), browser=Browser(), capture_sources=sources)
    _, shot = machine.screenshot(handle=7, longest=400)
    assert shot.area == work and (shot.width, shot.height) == (400, 300)
    assert machine.screenshot(monitor=0)[1].area == left
    assert machine.screenshot(monitor=-2)[1].area == desktop
    assert machine.screenshot(area=Rect(-2000, -100, -1000, 500))[1].area == Rect(-1920, 0, -1000, 500)
    sources.current = CaptureSources(None, desktop, (), None)
    with unittest.TestCase().assertRaisesRegex(OSError, "locked"):
        machine.screenshot()
