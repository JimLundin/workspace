"""The desktop's control decisions: the tray menu, the layout's messages, the overlay preference.

The native controller interprets immutable message actions. Menu observation,
layout transport, startup and queued file handoff have their own small interfaces;
tests use those same interfaces without constructing a partial assistant or UI.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Final, Protocol, assert_never

import protocol
from components import LAYOUT
from desktop_ui import ui_spec
from miryoku.layout import Scancode
from protocol import App, LayoutState, Request, Tool
lazy import desktop_ui.spec.tray
lazy from winapi.shell import MenuItem


class Menu(Enum):
    KEYMAP = 9
    TOGGLE_LAYOUT = 1
    RESTART_LAYOUT = 2
    USAGE = 6
    LOGS = 7
    QUIT = 8
    OVERLAY = 11
    MEETING = 12
    TRANSCRIPTS = 13
    TASKBAR = 15
    RESTART_ASSISTANT = 18
    RESTART_DESKTOP = 19


@dataclass(frozen=True, slots=True, kw_only=True)
class MenuState:
    """The three observations that decide the tray's choices and labels."""

    layout: LayoutState | None
    overlay_enabled: bool
    capturing: bool


# ---- the tray menu as data: `desktop_ui/spec/tray.py` ----------------------------------


@dataclass(frozen=True, slots=True)
class TrayAction:
    action: Menu
    label: str = ""
    """Its words; the layout and meeting items word their state themselves."""
    key: str = ""
    """A key hint at the trailing edge."""


@dataclass(frozen=True, slots=True)
class Separator:
    pass


@dataclass(frozen=True, slots=True)
class TraySpec:
    """`spec/tray.py`: the tray menu's items, top to bottom."""

    items: tuple[TrayAction | Separator, ...]


def stated(action: Menu) -> bool:
    """Items whose words follow state, so the spec gives them none."""
    return action in (Menu.TOGGLE_LAYOUT, Menu.RESTART_LAYOUT, Menu.MEETING)


def tray_problems(spec: TraySpec) -> tuple[str, ...]:
    """A label where the item words its state, none where it needs one, or an item listed twice."""
    actions = [item.action for item in spec.items if isinstance(item, TrayAction)]
    worded = tuple(
        f"{item.action.name.lower()} {'takes no label: its words follow state' if item.label else 'needs a label'}"
        for item in spec.items
        if isinstance(item, TrayAction) and stated(item.action) == bool(item.label)
    )
    repeated = tuple(
        f"{action.name.lower()} appears more than once" for action in sorted(set(actions), key=lambda each: each.value) if actions.count(action) > 1
    )
    return (*worded, *repeated)


def tray(*, reload: bool = True) -> TraySpec:
    """The tray spec as its module says now, run again from its file as the menu opens."""
    if reload:
        ui_spec.fresh(desktop_ui.spec.tray)
    return ui_spec.checked("tray.py", desktop_ui.spec.tray.TRAY, tray_problems(desktop_ui.spec.tray.TRAY))


def tray_item(item: TrayAction, state: MenuState) -> MenuItem:
    """One item as it reads in `state`: its words, hint, and whether it's enabled or checked."""
    running = state.layout in (LayoutState.ON, LayoutState.OFF)
    hint = f"\t{item.key}" if item.key else ""
    match item.action:
        case Menu.TOGGLE_LAYOUT:
            status = "on" if state.layout is LayoutState.ON else "off" if state.layout is LayoutState.OFF else "not running"
            text = f"Layout: {status}" + ("\tTap §" if running else "")
            return MenuItem(item.action.value, text, enabled=running, checked=state.layout is LayoutState.ON)
        case Menu.RESTART_LAYOUT:
            return MenuItem(item.action.value, "Restart layout" if running else "Start layout")
        case Menu.MEETING:
            return MenuItem(item.action.value, "Stop recording" if state.capturing else "Record a meeting")
        case Menu.OVERLAY:
            return MenuItem(item.action.value, item.label + hint, checked=state.overlay_enabled)
        case (Menu.KEYMAP | Menu.TASKBAR | Menu.TRANSCRIPTS | Menu.USAGE | Menu.LOGS) | Menu.RESTART_ASSISTANT | Menu.RESTART_DESKTOP | Menu.QUIT:
            return MenuItem(item.action.value, item.label + hint)
        case _:
            assert_never(item.action)


def menu_items(state: MenuState, spec: TraySpec) -> tuple[MenuItem, ...]:
    def shown(item: TrayAction | Separator) -> MenuItem:
        match item:
            case TrayAction():
                return tray_item(item, state)
            case Separator():
                return MenuItem(0)
            case _:
                assert_never(item)

    return tuple(shown(item) for item in spec.items)


class LayoutTransport(Protocol):
    def find_window(self, title: str) -> int | None: ...
    # Preserve HWND, message and both payload fields of the native wire contract.
    def post(self, handle: int, message: int, wparam: int, lparam: int) -> bool: ...


def toggle_layout(effects: LayoutTransport) -> bool:
    window = effects.find_window(LAYOUT.window.title)
    return window is not None and effects.post(window, protocol.WM_TOGGLE_LAYOUT, 0, 0)


WM_TOOL_CHOSEN: Final = 0x8057
"""Bar menu -> desktop control window: Tool value in wparam, target HWND in lparam (0 for foreground)."""


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
    """A Tool picked from a Workspace menu: press only."""

    tool: Tool


type ControlAction = PhysicalKey | FeatureRequest | ChosenTool


def control_event(event: WindowInput, apps: Sequence[App]) -> ControlAction | None:
    """Preserve key edges and press-only menu choices."""
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
        case WindowInput(message=message, wparam=code) if message == WM_TOOL_CHOSEN:
            try:
                tool = Tool(code)
            except ValueError:
                return None
            return ChosenTool(tool)
        case _:
            return None
