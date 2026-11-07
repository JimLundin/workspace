"""Native agent capabilities with explicit desktop and meeting owners.

Importing or constructing this module does not create the assistant UI, open a
microphone, or start a meeting. A worker supplies its own clipboard window and
bridges only the interactions whose owner remains in the assistant process.
"""

import os
import threading
from collections.abc import Callable
from dataclasses import KW_ONLY, dataclass, field, replace
from typing import Literal, Protocol

from pydantic import TypeAdapter

from automation.work_folder import BROWSER_PROFILE
from winapi.shapes import Rect
lazy from assistant import commands, uia
lazy from assistant.browser import Browser, BrowserResult
lazy from assistant.browser_requests import BrowserRequest
lazy from assistant.browser_session import Separate
lazy from assistant.meeting_tools import MeetingOperation
lazy from assistant.png import encode_png
lazy from assistant.uia import UiRequest
lazy from assistant.web_apps import Located, WebAppOperation
lazy from contracts.geometry import Shot, fit, half
lazy from winapi import clipboard, screen, system, windows


class DesktopAccess(Protocol):
    """The native operations the agent needs from a desktop owner."""

    @property
    def owner(self) -> int: ...
    def capture(self, area: Rect, longest: int) -> tuple[bytes, Shot]: ...


class MeetingControl(Protocol):
    """Meeting capture stays with its current owner and can be reached remotely."""

    def request(self, operation: MeetingOperation) -> str: ...


class BrowserControl(Protocol):
    def request(self, request: BrowserRequest, cancel: threading.Event) -> BrowserResult: ...
    def web_app[Q: Located, R](self, operation: WebAppOperation[Q, R], query: Q, cancel: threading.Event) -> R: ...
    def close(self, *, keep_browser: bool = False) -> None: ...


@dataclass(frozen=True, slots=True)
class NativeDesktop:
    """Capture for a worker's existing clipboard window, without a UI."""

    owner: int

    def capture(self, area: Rect, longest: int) -> tuple[bytes, Shot]:
        size = fit(area.size, longest)
        return encode_png(size.width, size.height, screen.capture(area, size.width, size.height)), Shot(area, size.width, size.height)


@dataclass(frozen=True, slots=True)
class Bounds:
    x: int
    y: int
    width: int
    height: int


def bounds_of(area: Rect) -> Bounds:
    return Bounds(area.left, area.top, area.width, area.height)


@dataclass(frozen=True, slots=True)
class MonitorRow:
    index: int
    bounds: Bounds
    work: Bounds
    primary: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class WindowRow:
    handle: int
    title: str
    app: str
    bounds: Bounds
    minimized: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class DesktopState:
    """The desktop tool's observation, in physical screen pixels."""

    foreground: int
    monitors: tuple[MonitorRow, ...]
    windows: tuple[WindowRow, ...]
    coordinates: Literal["physical screen pixels"] = "physical screen pixels"


@dataclass(frozen=True, slots=True)
class WindowState:
    handle: int
    bounds: Bounds
    minimized: bool = field(kw_only=True)
    maximized: bool = field(kw_only=True)


_DESKTOP = TypeAdapter(DesktopState)
_WINDOW = TypeAdapter(WindowState)


@dataclass(frozen=True, slots=True)
class CaptureSources:
    """One physical-desktop observation for screenshot selection."""

    foreground: Rect | None
    desktop: Rect
    monitors: tuple[Rect, ...]
    window: Rect | None


class CaptureObservation(Protocol):
    def observe(self, handle: int) -> CaptureSources: ...


@dataclass(frozen=True, slots=True)
class NativeCaptureObservation:
    def observe(self, handle: int) -> CaptureSources:
        foreground = windows.foreground()
        if not foreground:
            return CaptureSources(None, Rect(0, 0, 0, 0), (), None)
        selected = windows.visible_rect(handle) if handle and windows.exists(handle) and not windows.is_minimized(handle) else None
        return CaptureSources(
            screen.monitor_of(foreground).area, screen.virtual_screen(), tuple(monitor.area for monitor in screen.monitors()), selected
        )


def open_file(target: str) -> None:
    os.startfile(target)


def _background_browser() -> BrowserControl:
    return Browser(BROWSER_PROFILE, source=Separate.PROFILE)


@dataclass(frozen=True, slots=True)
class WinMachine:
    """What the agent's tools act on, done with Windows calls."""

    # Each keyword is an independent effect owner (browser, meeting capture,
    # capture observation, file opening). The worker selects each transport
    # separately; no record groups them more truthfully.
    desktop: DesktopAccess
    _: KW_ONLY
    browser: BrowserControl = field(default_factory=_background_browser)
    meetings: MeetingControl | None = None
    capture_sources: CaptureObservation = field(default_factory=NativeCaptureObservation)
    open_target: Callable[[str], None] = open_file

    def meeting(self, operation: MeetingOperation) -> str:
        if self.meetings is None:
            raise OSError("Meeting recording is unavailable.")
        return self.meetings.request(operation)

    def browse(self, request: BrowserRequest, cancel: threading.Event) -> tuple[str, bytes | None]:
        result = self.browser.request(request, cancel)
        return result.text, result.image

    def web_app[Q: Located, R](self, operation: WebAppOperation[Q, R], query: Q, cancel: threading.Event) -> R:
        return self.browser.web_app(operation, query, cancel)

    def close_background(self, *, keep_browser: bool = False) -> None:
        self.browser.close(keep_browser=keep_browser)

    def run_powershell(
        self,
        command: str,
        timeout_s: float,
        *,
        cwd: str | None = None,
        cancel: threading.Event | None = None,
    ) -> tuple[int, str]:
        return commands.powershell(command, cwd=cwd, timeout_s=timeout_s, cancel=cancel)

    def screenshot(self, *, area: Rect | None = None, handle: int = 0, monitor: int = -1, longest: int = 1280) -> tuple[bytes, Shot]:
        sources = self.capture_sources.observe(handle)
        if sources.foreground is None:
            raise OSError("The interactive desktop is unavailable or locked.")
        if area is None:
            if handle:
                if sources.window is None:
                    raise OSError("The requested window is closed or minimized; inspect or restore it first.")
                area = sources.window
            elif monitor == -2:
                area = sources.desktop
            elif monitor >= 0:
                if monitor >= len(sources.monitors):
                    raise OSError("That monitor is unavailable; call desktop_state for current monitor indexes.")
                area = sources.monitors[monitor]
            else:
                area = sources.foreground
        desktop = sources.desktop
        area = Rect(max(area.left, desktop.left), max(area.top, desktop.top), min(area.right, desktop.right), min(area.bottom, desktop.bottom))
        if area.width <= 0 or area.height <= 0:
            raise OSError("The requested area is outside the desktop.")
        return self.desktop.capture(area, longest)

    def desktop_state(self) -> str:
        state = DesktopState(
            windows.foreground(),
            tuple(
                MonitorRow(index, bounds_of(monitor.area), bounds_of(monitor.work), primary=monitor.primary)
                for index, monitor in enumerate(screen.monitors())
            ),
            tuple(
                WindowRow(window.handle, window.title, window.exe, bounds_of(windows.outer_rect(window.handle)), minimized=window.minimized)
                for window in windows.windows()
            ),
        )
        return _DESKTOP.dump_json(state).decode()

    def window_action(self, handle: int, action: str, bounds: Rect | None = None) -> str:
        if not windows.exists(handle):
            raise OSError("The window is no longer available; list windows again.")
        if action == "close":
            if not system.post_message(handle, system.WM_CLOSE, 0, 0):
                raise OSError("Windows rejected the close request.")
            return "Close requested. Inspect the window for any unsaved-work dialog."
        if action in ("maximize", "restore"):
            windows.show(handle, {"maximize": windows.SW_MAXIMIZE, "restore": windows.SW_RESTORE}[action])
        else:
            if windows.is_maximized(handle) or windows.is_minimized(handle):
                windows.show(handle, windows.SW_RESTORE)
            if action in ("snap_left", "snap_right"):
                bounds = half(
                    screen.monitor_of(handle).work,
                    "left" if action == "snap_left" else "right",
                    windows.outer_rect(handle),
                    windows.visible_rect(handle),
                )
            if bounds is None:
                raise OSError("Moving a window requires bounds.")
            windows.move(handle, bounds)
        state = WindowState(
            handle, bounds_of(windows.outer_rect(handle)), minimized=windows.is_minimized(handle), maximized=windows.is_maximized(handle)
        )
        return _WINDOW.dump_json(state).decode()

    def inspect_ui(self, request: UiRequest, cancel: threading.Event) -> tuple[int, str]:
        handle = request.handle or windows.foreground()
        if not windows.exists(handle):
            return 1, "No accessible window is available; list windows again or unlock the desktop."
        return commands.powershell(uia.script(replace(request, handle=handle)), timeout_s=20, cancel=cancel)

    def get_clipboard(self) -> str | None:
        return clipboard.get_text(self.desktop.owner)

    def set_clipboard(self, text: str) -> None:
        clipboard.set_text(self.desktop.owner, text)

    def open(self, target: str) -> None:
        self.open_target(target)
