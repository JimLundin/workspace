"""Assistant control decisions and effect ordering, without application resources.

The native controller interprets immutable message actions. Menu observation,
layout transport, startup and queued file handoff have their own small interfaces;
tests use those same interfaces without constructing a partial assistant or UI.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Annotated, Final, Literal, Protocol, assert_never

from pydantic import BeforeValidator, ConfigDict, TypeAdapter

import protocol
from components import LAYOUT
from desktop_ui import ui_spec
from desktop_ui.keymap import shortcut, shortcut_hint
from miryoku.layout import Scancode
from protocol import App, LayoutState, Request, Tool
lazy from winapi.shell import MenuItem


class Menu(Enum):
    KEYMAP = 9
    TOGGLE_LAYOUT = 1
    RESTART_LAYOUT = 2
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
    RESTART_ASSISTANT = 18


@dataclass(frozen=True, slots=True, kw_only=True)
class MenuState:
    """The four observations that decide the tray's choices and labels."""

    layout: LayoutState | None
    overlay_enabled: bool
    agent_running: bool
    capturing: bool


# ---- the tray menu as data: `desktop_ui/spec/tray.toml` --------------------------------


def _by_name(value: object) -> object:
    """The spec names an action in lowercase (`stop_agent`); its id is the menu's own."""
    match value:
        case str() if value.upper() in Menu.__members__:
            return Menu[value.upper()]
        case _:
            return value


_SPEC = ConfigDict(extra="forbid")


@dataclass(frozen=True, slots=True)
class TrayAction:
    action: Annotated[Menu, BeforeValidator(_by_name)]
    label: str = ""
    """Its words; the layout and meeting items word their state themselves."""
    key: str = ""
    """A key hint at the trailing edge; the agent's come from the key map."""
    __pydantic_config__ = _SPEC


@dataclass(frozen=True, slots=True)
class Separator:
    separator: Literal[True]
    __pydantic_config__ = _SPEC


@dataclass(frozen=True, slots=True)
class TraySpec:
    """`tray.toml`: the tray menu's items, top to bottom."""

    items: tuple[TrayAction | Separator, ...]
    __pydantic_config__ = _SPEC


_TRAY = TypeAdapter(TraySpec)
TRAY_FILE: Final = "tray.toml"


def stated(action: Menu) -> bool:
    """Items whose words follow state, so the spec gives them none."""
    return action in (Menu.TOGGLE_LAYOUT, Menu.RESTART_LAYOUT, Menu.MEETING)


def tray_spec(folder: Path = ui_spec.SHIPPED) -> TraySpec:
    path = folder / TRAY_FILE
    loaded = ui_spec.load(path, _TRAY)
    actions = [item.action for item in loaded.items if isinstance(item, TrayAction)]
    for item in loaded.items:
        match item:
            case TrayAction(action=action, label=label) if stated(action) == bool(label):
                need = "takes no label: its words follow state" if label else "needs a label"
                raise ui_spec.SpecError(f"{path.name}: {action.name.lower()} {need}")
            case TrayAction() | Separator():
                pass
            case _:
                assert_never(item)
    if repeated := sorted({action.name.lower() for action in actions if actions.count(action) > 1}):
        raise ui_spec.SpecError(f"{path.name}: {', '.join(repeated)} appears more than once")
    return loaded


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
        case Menu.AGENT:
            return MenuItem(item.action.value, f"{item.label}\t{shortcut_hint(shortcut(Tool.AGENT_TYPED))}")
        case Menu.STOP_AGENT:
            return MenuItem(item.action.value, f"{item.label}\t{shortcut_hint(shortcut(Tool.STOP))}", enabled=state.agent_running)
        case Menu.KEYMAP | Menu.WORK | Menu.TASKBAR | Menu.TRANSCRIPTS | Menu.UNDO | Menu.USAGE | Menu.LOGS | Menu.RESTART_ASSISTANT | Menu.QUIT:
            return MenuItem(item.action.value, item.label + hint)
        case _:
            assert_never(item.action)


def tray(folder: Path = ui_spec.SHIPPED, kept: Path = ui_spec.KEPT) -> tuple[TraySpec, ui_spec.SpecError | None]:
    """The tray spec as it is now, read each time the menu opens, or its kept copy with why."""
    return ui_spec.or_kept(tray_spec, (TRAY_FILE,), folder, kept)


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
            report_error("Windows could not open this file. Choose Open meeting transcripts in All Workspace controls to find it.")

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
