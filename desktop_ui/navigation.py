"""Every way the user moves between windows and desktops, as one union decided purely.

Keys, the pager, toolbar clicks and the window switcher
each produce a navigation. `effect` turns it and the current world into one
effect for the application observer to carry out, and `destination` names the
desktop it leads to.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Final, assert_never

import protocol
from desktop_ui.shell_items import PinnedApp, next_window
from desktop_ui.window_layout import App, Placement, Program
from winapi.shapes import Rect


class Direction(Enum):
    LEFT = auto()
    RIGHT = auto()
    UP = auto()
    DOWN = auto()


@dataclass(frozen=True, slots=True)
class AppKey:
    """An app key: go to the app's window, cycling while it's already in front, or start it."""

    app: protocol.App


@dataclass(frozen=True, slots=True)
class CycleApp:
    """A toolbar application or slot: its next window, or launching a slot's web app that isn't open."""

    app: App


@dataclass(frozen=True, slots=True)
class ShowWindow:
    """One particular window, chosen from the toolbar's window list or the window switcher."""

    window: int


@dataclass(frozen=True, slots=True)
class SpatialFocus:
    direction: Direction


@dataclass(frozen=True, slots=True)
class JumpDesktop:
    """A desktop key or a click on the pager."""

    desktop: int


@dataclass(frozen=True, slots=True)
class Zoom:
    """Fill the focused window's monitor until pressed again or focus leaves it."""


type Navigation = AppKey | CycleApp | ShowWindow | SpatialFocus | JumpDesktop | Zoom


class Placing(Enum):
    TOGGLE_PAUSE = auto()
    NOW = auto()


type Order = Navigation | Placing
"""What the application observer is asked to do."""


KEYED: Final[frozendict[protocol.Tool, Order]] = frozendict(
    {
        protocol.Tool.FOCUS_LEFT: SpatialFocus(Direction.LEFT),
        protocol.Tool.FOCUS_RIGHT: SpatialFocus(Direction.RIGHT),
        protocol.Tool.FOCUS_UP: SpatialFocus(Direction.UP),
        protocol.Tool.FOCUS_DOWN: SpatialFocus(Direction.DOWN),
        protocol.Tool.DESKTOP_1: JumpDesktop(0),
        protocol.Tool.DESKTOP_2: JumpDesktop(1),
        protocol.Tool.DESKTOP_3: JumpDesktop(2),
        protocol.Tool.DESKTOP_4: JumpDesktop(3),
        protocol.Tool.DESKTOP_5: JumpDesktop(4),
        protocol.Tool.ZOOM: Zoom(),
        protocol.Tool.PLACEMENT_PAUSE: Placing.TOGGLE_PAUSE,
        protocol.Tool.PLACE_NOW: Placing.NOW,
    }
)
"""The order each navigation key gives; other tools give none."""


def keyed(tool: protocol.Tool) -> Order | None:
    return KEYED.get(tool)


@dataclass(frozen=True, slots=True)
class World:
    """What a navigation is decided against: the observer's latest view, refreshed with the foreground."""

    desktops: int
    current: int
    foreground: int
    windows: frozendict[App, tuple[int, ...]]
    """Every application's windows on every desktop, in the toolbar's stable order."""
    located: frozendict[int, int]
    """The desktop each window is on."""
    placement: Placement
    recent: tuple[int, ...]
    """Windows most recently in front first."""
    zoomed: int | None


@dataclass(frozen=True, slots=True)
class Focus:
    window: int


@dataclass(frozen=True, slots=True)
class Switch:
    desktop: int
    then: int | None
    """The window to focus there: the one last in front, if any."""


@dataclass(frozen=True, slots=True)
class Launch:
    app: protocol.Installed | PinnedApp


@dataclass(frozen=True, slots=True)
class ZoomIn:
    window: int


@dataclass(frozen=True, slots=True)
class ZoomOut:
    window: int


type Effect = Focus | Switch | Launch | ZoomIn | ZoomOut | None


def launcher(target: protocol.Installed | protocol.PinnedWeb) -> protocol.Installed | PinnedApp:
    match target:
        case protocol.Installed():
            return target
        case protocol.PinnedWeb(slot=slot):
            return PinnedApp(slot)
        case _:
            assert_never(target)


def identity(target: protocol.Installed | PinnedApp) -> App:
    match target:
        case protocol.Installed(exe=exe):
            return Program(exe.lower())
        case PinnedApp():
            return target
        case _:
            assert_never(target)


def slot_launcher(app: App) -> PinnedApp | None:
    """Only a slot's web app can be launched from the toolbar; a running application always has windows."""
    match app:
        case PinnedApp():
            return app
        case Program():
            return None
        case _:
            assert_never(app)


def cycle(app: App, world: World, start: protocol.Installed | PinnedApp | None) -> Effect:
    handles = world.windows.get(app, ())
    if not handles:
        return Launch(start) if start is not None else None
    return Focus(next_window(handles, world.foreground))


def remembered(world: World, desktop: int) -> int | None:
    """The window to land on when arriving at a desktop: the one last in front there, else its first placed window."""
    placed = tuple(handle for handle, target in world.placement.items() if target.desktop == desktop)
    return next((handle for handle in world.recent if handle in placed), placed[0] if placed else None)


def arrive(world: World, desktop: int) -> Effect:
    if not 0 <= desktop < world.desktops or desktop == world.current:
        return None
    return Switch(desktop, remembered(world, desktop))


def nearest(world: World, direction: Direction) -> int | None:
    """The placed window on the current desktop closest in `direction` from the window in front; None when there is none."""
    here = tuple((handle, target.rect) for handle, target in world.placement.items() if target.desktop == world.current)
    origin = next((rect for handle, rect in here if handle == world.foreground), None)
    if origin is None:
        return None

    def score(rect: Rect) -> tuple[bool, int, int, int] | None:
        """Prefer the window sharing the most edge with the origin, then the closest, then the best centred."""
        horizontal = direction in (Direction.LEFT, Direction.RIGHT)
        overlap = (
            min(rect.bottom, origin.bottom) - max(rect.top, origin.top) if horizontal else min(rect.right, origin.right) - max(rect.left, origin.left)
        )
        off = (
            abs((rect.top + rect.bottom) - (origin.top + origin.bottom))
            if horizontal
            else abs((rect.left + rect.right) - (origin.left + origin.right))
        )
        match direction:
            case Direction.LEFT:
                gap = origin.left - rect.right
            case Direction.RIGHT:
                gap = rect.left - origin.right
            case Direction.UP:
                gap = origin.top - rect.bottom
            case Direction.DOWN:
                gap = rect.top - origin.bottom
            case _:
                assert_never(direction)
        return (overlap <= 0, -max(overlap, 0), gap, off) if gap >= 0 else None

    scored = tuple((ranked, handle) for handle, rect in here if handle != world.foreground and (ranked := score(rect)) is not None)
    return min(scored)[1] if scored else None


def effect(navigation: Navigation, world: World) -> Effect:
    match navigation:
        case AppKey(app=app):
            start = launcher(app.target)
            return cycle(identity(start), world, start)
        case CycleApp(app=app):
            return cycle(app, world, slot_launcher(app))
        case ShowWindow(window=window):
            return Focus(window)
        case SpatialFocus(direction=direction):
            target = nearest(world, direction)
            return Focus(target) if target is not None else None
        case JumpDesktop(desktop=desktop):
            return arrive(world, desktop)
        case Zoom():
            if world.zoomed is not None and world.zoomed == world.foreground:
                return ZoomOut(world.zoomed)
            return ZoomIn(world.foreground) if world.foreground in world.placement else None
        case _:
            assert_never(navigation)


def destination(chosen: Effect, world: World) -> int:
    """The desktop `chosen` leads to: a focused window's own, a switch's, else the current one."""
    match chosen:
        case Focus(window=window) | ZoomIn(window=window) | ZoomOut(window=window):
            return world.located.get(window, world.current)
        case Switch(desktop=desktop):
            return desktop
        case Launch() | None:
            return world.current
        case _:
            assert_never(chosen)


def zoom_after(zoomed: int | None, foreground: int) -> int | None:
    """A zoomed window keeps its zoom only while it stays in front; then its slot is restored."""
    return zoomed if zoomed == foreground else None
