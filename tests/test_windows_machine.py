"""The worker's machine is constructed without a microphone or assistant UI."""

import subprocess
import sys
import threading
import unittest
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("Windows machine ownership")

from pydantic import TypeAdapter

from assistant import browser
from assistant.agent_tools import Machine
from assistant.browser import BrowserResult
from assistant.browser_requests import BrowserRequest
from assistant.browser_session import Separate
from assistant.browser_values import PageList
from assistant.geometry import Shot
from assistant.machine import WinMachine
from assistant.meeting_tools import MeetingCommand, MeetingOperation, StartMeeting
from assistant.web_apps import TEAMS_READ, Located, TeamsPage, TeamsQuery, WebAppOperation
from automation.json_value import Json
from winapi.shapes import Rect


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
TEAMS_PAGE = TeamsPage("", "", (), (), editor_ready=False)


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
    match machine.background_browser:
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


def test_machine_import_and_construction_do_not_load_ui_or_audio() -> None:
    program = """
import os
import sys
from runtime import activate
activate()
from assistant.machine import NativeDesktop, WinMachine
from winapi import windows

owner = windows.create_hidden("workspace machine construction fixture")
try:
    machine = WinMachine(NativeDesktop(owner))
    assert windows.process_id(owner) == os.getpid()
    machine.close_background()
    for name in ("assistant.app", "assistant.desktop", "desktop_ui.ui", "winapi.audio",
                 "winapi.recording", "tkinter", "PySide6"):
        assert name not in sys.modules, name
finally:
    windows.destroy(owner)
assert not windows.exists(owner)
print("Constructed without UI or audio.")
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Constructed without UI or audio."
