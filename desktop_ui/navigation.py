from dataclasses import dataclass
from enum import Enum, auto
from typing import Final, assert_never

import protocol
from desktop_ui.shell_items import PinnedApp, next_window
from desktop_ui.window_layout import App, Placement, Program, stack
from winapi.shapes import Rect


class Direction(Enum):
    LEFT = auto()
    RIGHT = auto()
    UP = auto()
    DOWN = auto()


@dataclass(frozen=True, slots=True)
class AppKey:
    app: protocol.App


@dataclass(frozen=True, slots=True)
class CycleApp:
    app: App


@dataclass(frozen=True, slots=True)
class ShowWindow:
    window: int


@dataclass(frozen=True, slots=True)
class SpatialFocus:
    direction: Direction


@dataclass(frozen=True, slots=True)
class StepLayer:
    step: int
    """Layers up (positive) or down; it wraps round the stack."""


@dataclass(frozen=True, slots=True)
class JumpDesktop:
    desktop: int


@dataclass(frozen=True, slots=True)
class Zoom: ...


type Navigation = (
    AppKey
    | CycleApp
    | ShowWindow
    | SpatialFocus
    | StepLayer
    | JumpDesktop
    | Zoom
)


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
        protocol.Tool.LAYER_UP: StepLayer(1),
        protocol.Tool.LAYER_DOWN: StepLayer(-1),
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


def launcher(
    target: protocol.Installed | protocol.PinnedWeb,
) -> protocol.Installed | PinnedApp:
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
    match app:
        case PinnedApp():
            return app
        case Program():
            return None
        case _:
            assert_never(app)


def cycle(
    app: App, world: World, start: protocol.Installed | PinnedApp | None
) -> Effect:
    handles = world.windows.get(app, ())
    if not handles:
        return Launch(start) if start is not None else None
    return Focus(next_window(handles, world.foreground))


def remembered(world: World, desktop: int) -> int | None:
    placed = tuple(
        handle
        for handle, target in world.placement.items()
        if target.desktop == desktop
    )
    return next(
        (handle for handle in world.recent if handle in placed),
        placed[0] if placed else None,
    )


def arrive(world: World, desktop: int) -> Effect:
    if not 0 <= desktop < world.desktops or desktop == world.current:
        return None
    return Switch(desktop, remembered(world, desktop))


def shown(world: World) -> frozenset[int]:
    """The placed windows on the current desktop that no layer covers: each stack shows the layer of its window last in front, or its bottom one."""
    order = (world.foreground, *world.recent)

    def front(handle: int) -> int:
        layers = stack(world.placement, handle)
        return next(
            (
                depth
                for window in order
                for depth, layer in enumerate(layers)
                if window in layer
            ),
            0,
        )

    return frozenset(
        handle
        for handle, target in world.placement.items()
        if target.desktop == world.current
        and (not (layer := target.layer) or layer.depth == front(handle))
    )


def climb(world: World, step: int, *, wrap: bool) -> int | None:
    """The window at the focused one's spot, or the nearest to it, on the layer `step` layers up."""
    layers = stack(world.placement, world.foreground)
    here = next(
        (
            (depth, layer.index(world.foreground))
            for depth, layer in enumerate(layers)
            if world.foreground in layer
        ),
        None,
    )
    if here is None:
        return None
    depth, spot = here
    to = (depth + step) % len(layers) if wrap else depth + step
    if to == depth or not 0 <= to < len(layers):
        return None
    above = layers[to]
    return above[min(spot, len(above) - 1)]


def nearest(world: World, direction: Direction) -> int | None:
    visible = shown(world)
    here = tuple(
        (handle, target.rect)
        for handle, target in world.placement.items()
        if handle in visible
    )
    origin = next(
        (rect for handle, rect in here if handle == world.foreground), None
    )
    if origin is None:
        return None

    def score(rect: Rect) -> tuple[bool, int, int, int] | None:
        horizontal = direction in (Direction.LEFT, Direction.RIGHT)
        overlap = (
            min(rect.bottom, origin.bottom) - max(rect.top, origin.top)
            if horizontal
            else min(rect.right, origin.right) - max(rect.left, origin.left)
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

    scored = tuple(
        (ranked, handle)
        for handle, rect in here
        if handle != world.foreground and (ranked := score(rect)) is not None
    )
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
            if target is None and direction in (Direction.UP, Direction.DOWN):
                upward = direction is Direction.UP
                target = climb(world, 1 if upward else -1, wrap=False)
            return Focus(target) if target is not None else None
        case StepLayer(step=step):
            target = climb(world, step, wrap=True)
            return Focus(target) if target is not None else None
        case JumpDesktop(desktop=desktop):
            return arrive(world, desktop)
        case Zoom():
            if world.zoomed is not None and world.zoomed == world.foreground:
                return ZoomOut(world.zoomed)
            return (
                ZoomIn(world.foreground)
                if world.foreground in world.placement
                else None
            )
        case _:
            assert_never(navigation)


def destination(chosen: Effect, world: World) -> int:
    match chosen:
        case (
            Focus(window=window)
            | ZoomIn(window=window)
            | ZoomOut(window=window)
        ):
            return world.located.get(window, world.current)
        case Switch(desktop=desktop):
            return desktop
        case Launch() | None:
            return world.current
        case _:
            assert_never(chosen)


def zoom_after(zoomed: int | None, foreground: int) -> int | None:
    return zoomed if zoomed == foreground else None
