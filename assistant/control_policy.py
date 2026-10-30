"""Assistant control decisions and effect ordering, without application resources.

The native controller interprets immutable message actions. Menu observation,
layout transport, startup and queued file handoff have their own small interfaces;
tests use those same interfaces without constructing a partial assistant or UI.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol

import keeper
import protocol
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
        MenuItem(Menu.ASK.value, "Ask…\tHold V + P"),
        MenuItem(Menu.AGENT.value, "Agent session\tHold V + L"),
        MenuItem(Menu.WORK.value, "Work…"),
        MenuItem(Menu.TASKBAR.value, "Toggle Windows taskbar\tWindows key"),
        MenuItem(Menu.STOP_AGENT.value, "Stop agent\tHold V + Ö", enabled=state.agent_running),
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
    window = effects.find_window(keeper.LAYOUT_WINDOW)
    return window is not None and effects.post(window, protocol.WM_TOGGLE_LAYOUT, 0, 0)


def initialize_controls(handle: int, start_workers: Callable[[], None], effects: StartupEffects) -> int:
    """Start owners before requesting state replay and announcing readiness."""
    timer = effects.start_timer(handle)
    start_workers()
    if (layout := effects.find_window(keeper.LAYOUT_WINDOW)) is not None:
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


class Action(Enum):
    OPEN_INBOX = "open inbox"
    SWITCH_WINDOWS = "switch windows"
    TOGGLE_MEETING = "toggle meeting"
    BALANCE_WINDOWS = "balance windows"


@dataclass(frozen=True, slots=True)
class FeatureRequest:
    request: Request
    down: bool = field(kw_only=True)


type ControlAction = PhysicalKey | Action | FeatureRequest


def control_event(event: WindowInput, apps: Sequence[App]) -> ControlAction | None:
    """Separate press-only UI actions from features that own both key edges."""
    match event:
        case WindowInput(message=protocol.WM_KEY_STATE, wparam=scancode, lparam=down):
            return PhysicalKey(Scancode(scancode), down=bool(down))
        case WindowInput(message=protocol.WM_REQUEST, wparam=code, lparam=down):
            request = protocol.decode(code, apps)
            match request:
                case Tool.WINDOW_SWITCHER:
                    return Action.SWITCH_WINDOWS if down else None
                case Tool.OPEN_INBOX:
                    return Action.OPEN_INBOX if down else None
                case Tool.MEETING_TOGGLE:
                    return Action.TOGGLE_MEETING if down else None
                case Tool.TILE_BALANCE:
                    return Action.BALANCE_WINDOWS if down else None
                case None:
                    return None
                case _:
                    return FeatureRequest(request, down=bool(down))
        case _:
            return None
