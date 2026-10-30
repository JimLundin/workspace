"""Native agent capabilities with explicit desktop, human-input, and meeting owners.

Importing or constructing this module does not create the assistant UI, open a
microphone, or start a meeting. A worker supplies its own clipboard window and
bridges only the interactions whose owner remains in the assistant process.
"""

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Protocol

import keeper
import keeper_control
from protocol import MAGIC
from usage import DIRECTORY
from winapi.shapes import Rect, Window
lazy from assistant import commands, uia
lazy from assistant.browser import Browser, BrowserResult
lazy from assistant.browser_session import Product
lazy from assistant.geometry import Shot, fit, half
lazy from assistant.llm import Json
lazy from assistant.png import encode_png
lazy from assistant.recording_state import AudioSource
lazy from assistant.teams import Teams
lazy from assistant.textio import paste_text
lazy from winapi import clipboard, inputs, screen, system, windows

_EXTENDED_VKS: Final = frozenset({0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E, 0x5B, 0x5D, 0x90})
_PASTE_WAIT_S: Final = 0.4


class DesktopAccess(Protocol):
    """The native operations the agent needs from a desktop owner."""

    @property
    def owner(self) -> int: ...
    def capture(self, area: Rect, longest: int) -> tuple[bytes, Shot]: ...
    def paste(self, text: str) -> None: ...


class MeetingControl(Protocol):
    """Meeting capture stays with its current owner and can be reached remotely."""

    def start(self, source: AudioSource = "both", title: str = "Meeting") -> None: ...
    def stop(self) -> None: ...
    def retry(self) -> None: ...
    def recent(self) -> str: ...
    def describe(self) -> str: ...


class BrowserControl(Protocol):
    def request(self, operation: str, args: dict[str, Json], cancel: threading.Event) -> BrowserResult: ...
    def close(self) -> None: ...


class TeamsControl(Protocol):
    def request(self, operation: str, args: dict[str, Json], cancel: threading.Event) -> str: ...
    def cancel_sign_in(self) -> None: ...


class NativeDesktop:
    """Capture and paste for a worker's existing clipboard window, without a UI."""

    __slots__ = ("owner",)

    def __init__(self, owner: int) -> None:
        self.owner = owner

    def capture(self, area: Rect, longest: int) -> tuple[bytes, Shot]:
        width, height = fit(area.width, area.height, longest)
        return encode_png(width, height, screen.capture(area, width, height)), Shot(area, width, height)

    def paste(self, text: str) -> None:
        def shortcut() -> None:
            inputs.send_keys(
                [
                    inputs.KeyStroke(0xA2, down=True),
                    inputs.KeyStroke(0x56, down=True),
                    inputs.KeyStroke(0x56, down=False),
                    inputs.KeyStroke(0xA2, down=False),
                ],
                MAGIC,
            )

        paste_text(self.owner, text, clipboard, shortcut, lambda: time.sleep(_PASTE_WAIT_S))


def rectangle_data(area: Rect) -> dict[str, Json]:
    return {"x": area.left, "y": area.top, "width": area.width, "height": area.height}


@dataclass(frozen=True, slots=True)
class CaptureSources:
    """One physical-desktop observation for screenshot selection."""

    foreground: Rect | None
    desktop: Rect
    monitors: tuple[Rect, ...]
    window: Rect | None


class CaptureObservation(Protocol):
    def observe(self, handle: int) -> CaptureSources: ...


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


class WinMachine:
    """What the agent's tools act on, done with Windows calls."""

    __slots__ = ("background_browser", "capture_sources", "desktop", "meetings", "open_target", "teams_client")

    def __init__(
        self,
        desktop: DesktopAccess,
        *,
        browser: BrowserControl | None = None,
        teams: TeamsControl | None = None,
        meetings: MeetingControl | None = None,
        capture_sources: CaptureObservation | None = None,
        open_target: Callable[[str], None] = open_file,
    ) -> None:
        # Each optional capability has its own owner; worker composition selects
        # transports independently of capture and meetings.
        self.desktop = desktop
        self.capture_sources: CaptureObservation = NativeCaptureObservation() if capture_sources is None else capture_sources
        self.open_target = open_target
        self.background_browser: BrowserControl = Browser(DIRECTORY / "browser-profile", source=Product.EDGE) if browser is None else browser
        self.teams_client: TeamsControl = Teams(DIRECTORY / "teams", environment=os.environ) if teams is None else teams
        self.meetings = meetings

    def meeting(self, operation: str, source: str = "both", title: str = "Meeting") -> str:
        if self.meetings is None:
            raise OSError("Meeting recording is unavailable.")
        if operation == "start":
            if source not in ("both", "microphone"):
                raise OSError("Meeting source must be both or microphone.")
            self.meetings.start("both" if source == "both" else "microphone", title)
        elif operation == "stop":
            self.meetings.stop()
        elif operation == "retry":
            self.meetings.retry()
        elif operation == "list":
            return self.meetings.recent()
        elif operation != "status":
            raise OSError("Unknown meeting action.")
        return self.meetings.describe()

    def browse(self, operation: str, arguments: dict[str, Json], cancel: threading.Event) -> tuple[str, bytes | None]:
        result = self.background_browser.request(operation, arguments, cancel)
        return result.text, result.image

    def teams(self, operation: str, arguments: dict[str, Json], cancel: threading.Event) -> str:
        return self.teams_client.request(operation, arguments, cancel)

    def close_background(self) -> None:
        try:
            self.background_browser.close()
        finally:
            self.teams_client.cancel_sign_in()

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
        x, y = inputs.cursor_position()
        data: dict[str, Json] = {
            "coordinates": "physical screen pixels",
            "foreground": windows.foreground(),
            "cursor": {"x": x, "y": y},
            "monitors": [
                {"index": index, "bounds": rectangle_data(monitor.area), "work": rectangle_data(monitor.work), "primary": monitor.primary}
                for index, monitor in enumerate(screen.monitors())
            ],
            "windows": [
                {
                    "handle": window.handle,
                    "title": window.title,
                    "app": window.exe,
                    "minimized": window.minimized,
                    "bounds": rectangle_data(windows.outer_rect(window.handle)),
                }
                for window in windows.windows()
            ],
        }
        return json.dumps(data, ensure_ascii=False)

    def window_action(self, handle: int, action: str, bounds: Rect | None = None) -> str:
        if not windows.exists(handle):
            raise OSError("The window is no longer available; list windows again.")
        if action == "close":
            if not system.post_message(handle, system.WM_CLOSE, 0, 0):
                raise OSError("Windows rejected the close request.")
            return "Close requested. Inspect the window for any unsaved-work dialog."
        if action in ("minimize", "maximize", "restore"):
            windows.show(handle, {"minimize": windows.SW_MINIMIZE, "maximize": windows.SW_MAXIMIZE, "restore": windows.SW_RESTORE}[action])
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
        state: dict[str, Json] = {
            "handle": handle,
            "bounds": rectangle_data(windows.outer_rect(handle)),
            "minimized": windows.is_minimized(handle),
            "maximized": windows.is_maximized(handle),
        }
        return json.dumps(state)

    def inspect_ui(self, request: dict[str, Json], cancel: threading.Event) -> tuple[int, str]:
        handle = request.get("handle") or windows.foreground()
        if not isinstance(handle, int) or not windows.exists(handle):
            return 1, "No accessible window is available; list windows again or unlock the desktop."
        return commands.powershell(uia.script({**request, "handle": handle}), timeout_s=20, cancel=cancel)

    def move_mouse(self, x: int, y: int) -> None:
        inputs.move_mouse(x, y, screen.virtual_screen(), MAGIC)

    def mouse_button(self, button: str, *, down: bool) -> None:
        inputs.mouse_button(button, MAGIC, down=down)

    def click(self, x: int, y: int, button: str, count: int) -> None:
        inputs.click(x, y, button, count, screen.virtual_screen(), MAGIC)

    def type_text(self, text: str) -> None:
        inputs.type_text(text, MAGIC)

    def paste_text(self, text: str) -> None:
        self.desktop.paste(text)

    def press_keys(self, strokes: list[tuple[int, bool]]) -> None:
        inputs.send_keys([inputs.KeyStroke(vk, down=down, extended=vk in _EXTENDED_VKS) for vk, down in strokes], MAGIC)

    def scroll(self, x: int, y: int, clicks: int, *, horizontal: bool = False) -> None:
        inputs.move_mouse(x, y, screen.virtual_screen(), MAGIC)
        inputs.scroll(clicks, MAGIC, horizontal=horizontal)

    def windows(self) -> list[Window]:
        return windows.windows()

    def focus(self, handle: int) -> bool:
        return windows.focus(handle)

    def get_clipboard(self) -> str | None:
        return clipboard.get_text(self.desktop.owner)

    def set_clipboard(self, text: str) -> None:
        clipboard.set_text(self.desktop.owner, text)

    def open(self, target: str) -> None:
        self.open_target(target)

    def install(self, summary: str) -> None:
        keeper_control.ask(keeper.REQUESTS, keeper_control.Install(summary))
