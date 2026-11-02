"""Assistant control decisions and effect ordering, without application resources.

The native controller interprets immutable message actions. Menu observation,
layout transport, startup and queued file handoff have their own small interfaces;
tests use those same interfaces without constructing a partial assistant or UI.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final, Protocol

import protocol
from components import LAYOUT
from desktop_ui.keymap import shortcut, shortcut_hint
from miryoku.layout import Scancode
from protocol import App, LayoutState, Request, Tool
lazy from winapi.shell import MenuItem


class Menu(Enum):
    KEYMAP = 9
    TOGGLE_LAYOUT = 1
    RESTART_LAYOUT = 2
    ASK = 3
    AGENT = 4
    STOP_AGENT = 5
    USAGE = 6
    LOGS = 7
    QUIT = 8
    UNDO = 10
    OVERLAY = 11
    MEETING = 12
    TRANSCRIPTS = 13
    WORK = 14
    TASKBAR = 15
    FOLLOWUPS = 17
    RESTART_ASSISTANT = 18
    RESTART_AUTOMATION = 19


@dataclass(frozen=True, slots=True, kw_only=True)
class MenuState:
    """The four observations that decide the tray's choices and labels."""

    layout: LayoutState | None
    overlay_enabled: bool
    agent_running: bool
    capturing: bool


def menu_items(state: MenuState) -> tuple[MenuItem, ...]:
    status = {None: "not running", LayoutState.ON: "on", LayoutState.OFF: "off", LayoutState.QUIT: "not running"}[state.layout]
    running = state.layout in (LayoutState.ON, LayoutState.OFF)
    return (
        MenuItem(
            Menu.TOGGLE_LAYOUT.value, f"Layout: {status}" + ("\tTap §" if running else ""), enabled=running, checked=state.layout is LayoutState.ON
        ),
        MenuItem(Menu.RESTART_LAYOUT.value, "Restart layout" if running else "Start layout"),
        MenuItem(Menu.OVERLAY.value, "Keyboard overlay", checked=state.overlay_enabled),
        MenuItem(Menu.KEYMAP.value, "Key map"),
        MenuItem(0),
        MenuItem(Menu.ASK.value, "Ask…\t" + shortcut_hint(shortcut(Tool.ASK))),
        MenuItem(Menu.AGENT.value, "Agent session\t" + shortcut_hint(shortcut(Tool.AGENT_TYPED))),
        MenuItem(Menu.WORK.value, "Work…"),
        MenuItem(Menu.TASKBAR.value, "Toggle Windows taskbar\tWindows key"),
        MenuItem(Menu.STOP_AGENT.value, "Stop agent\t" + shortcut_hint(shortcut(Tool.STOP)), enabled=state.agent_running),
        MenuItem(Menu.MEETING.value, "Stop recording" if state.capturing else "Record a meeting"),
        MenuItem(Menu.TRANSCRIPTS.value, "Transcripts"),
        MenuItem(Menu.FOLLOWUPS.value, "Meeting follow-up…"),
        MenuItem(0),
        MenuItem(Menu.UNDO.value, "Undo the last update"),
        MenuItem(Menu.USAGE.value, "Usage report"),
        MenuItem(Menu.LOGS.value, "Open logs folder"),
        MenuItem(0),
        MenuItem(Menu.RESTART_ASSISTANT.value, "Restart assistant"),
        MenuItem(Menu.RESTART_AUTOMATION.value, "Restart automation"),
        MenuItem(Menu.QUIT.value, "Quit Workspace"),
    )


class LayoutTransport(Protocol):
    def find_window(self, title: str) -> int | None: ...
    # Preserve HWND, message and both payload fields of the native wire contract.
    def post(self, handle: int, message: int, wparam: int, lparam: int) -> bool: ...


class StartupEffects(LayoutTransport, Protocol):
    def start_timer(self, handle: int) -> int: ...
    def ready(self) -> None: ...


def toggle_layout(effects: LayoutTransport) -> bool:
    window = effects.find_window(LAYOUT.window.title)
    return window is not None and effects.post(window, protocol.WM_TOGGLE_LAYOUT, 0, 0)


def initialize_controls(handle: int, start_workers: Callable[[], None], effects: StartupEffects) -> int:
    """Start owners before requesting state replay and announcing readiness."""
    timer = effects.start_timer(handle)
    start_workers()
    if (layout := effects.find_window(LAYOUT.window.title)) is not None:
        effects.post(layout, protocol.WM_QUERY_LAYOUT_STATE, 0, 0)
    effects.ready()
    return timer


def meeting_file_job(path: Path, open_file: Callable[[Path], None], report_error: Callable[[str], None]) -> Callable[[], None]:
    """Keep the canonical path and defer shell effects to the controller's worker."""

    def open_saved_file() -> None:
        try:
            open_file(path)
        except OSError:
            report_error("Windows could not open this file. You can still review it in Meetings.")

    return open_saved_file


@dataclass(frozen=True, slots=True, kw_only=True)
class OverlayChange:
    enabled: bool


class OverlayPreference(Protocol):
    def display_overlay(self, change: OverlayChange) -> None: ...
    def persist_overlay(self, change: OverlayChange) -> None: ...


def change_overlay(change: OverlayChange, effects: OverlayPreference) -> str | None:
    """Apply immediate feedback before persistence; preserve feedback on failure."""
    effects.display_overlay(change)
    try:
        effects.persist_overlay(change)
    except OSError:
        return "The overlay changed, but its setting couldn't be saved."
    return None


WM_TOOL_CHOSEN: Final = 0x8057
"""Menu -> assistant control thread: Tool value in wparam, target HWND in lparam (0 for foreground)."""


@dataclass(frozen=True, slots=True)
class WindowInput:
    """One native message observation; the HWND remains with its native owner."""

    message: int
    wparam: int
    lparam: int


@dataclass(frozen=True, slots=True)
class PhysicalKey:
    scancode: Scancode
    down: bool = field(kw_only=True)

    @property
    def reset(self) -> bool:
        return self.scancode == 0


@dataclass(frozen=True, slots=True)
class FeatureRequest:
    request: Request
    down: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class ChosenTool:
    """A Tool picked from a Workspace menu: press only, on the window that had the keyboard."""

    tool: Tool
    target: int | None


type ControlAction = PhysicalKey | FeatureRequest | ChosenTool


def control_event(event: WindowInput, apps: Sequence[App]) -> ControlAction | None:
    """Preserve key edges and the captured target of press-only menu choices."""
    match event:
        case WindowInput(message=protocol.WM_KEY_STATE, wparam=scancode, lparam=down):
            return PhysicalKey(Scancode(scancode), down=bool(down))
        case WindowInput(message=protocol.WM_REQUEST, wparam=code, lparam=down):
            request = protocol.decode(code, apps)
            match request:
                case None:
                    return None
                case _:
                    return FeatureRequest(request, down=bool(down))
        case WindowInput(message=message, wparam=code, lparam=target) if message == WM_TOOL_CHOSEN:
            try:
                tool = Tool(code)
            except ValueError:
                return None
            return ChosenTool(tool, target or None)
        case _:
            return None
