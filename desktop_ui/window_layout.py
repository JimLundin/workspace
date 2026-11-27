from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, auto
from fractions import Fraction

from contracts.members import every_member
from desktop_ui.shell_items import PinnedApp, Shelf
from winapi.screen import Monitor
from winapi.shapes import Point, Rect, Size, Window


class Role(Enum):
    LAPTOP = auto()
    MAIN = auto()
    """The large landscape external screen."""
    ABOVE = auto()
    """The landscape external screen above the laptop."""
    SIDE = auto()
    """The portrait external screen beside the others."""


class Setup(Enum):
    LAPTOP_ONLY = auto()
    HOME = auto()
    WORK = auto()


def _ordered(sizes: Iterable[Size]) -> tuple[Size, ...]:
    return tuple(sorted(sizes, key=lambda size: (size.width, size.height)))


def assigned(
    monitors: Sequence[Monitor], setups: Setups
) -> tuple[Setup, frozendict[Role, Monitor]] | None:
    if not monitors:
        return None
    panels = tuple(
        index for index, monitor in enumerate(monitors) if monitor.internal
    )
    laptop = (
        panels[0]
        if len(panels) == 1
        else next(
            (
                index
                for index, monitor in enumerate(monitors)
                if monitor.primary
            ),
            0,
        )
    )
    externals = tuple(
        monitor for index, monitor in enumerate(monitors) if index != laptop
    )
    sizes = _ordered(monitor.area.size for monitor in externals)
    alone = (Setup.LAPTOP_ONLY, frozendict({Role.LAPTOP: monitors[laptop]}))
    if len(panels) != 1:
        return alone
    setup = next(
        (
            setup
            for setup, wanted in setups.externals.items()
            if sizes == _ordered(wanted)
        ),
        None,
    )
    if setup is None:
        return alone
    roles = {
        setups.externals[setup][monitor.area.size]: monitor
        for monitor in externals
    }
    return setup, frozendict({Role.LAPTOP: monitors[laptop], **roles})


def screens(monitors: Sequence[Monitor], setups: Setups) -> Screens | None:
    match assigned(monitors, setups):
        case (setup, roles):
            return Screens(
                setup,
                frozendict(
                    (role, monitor.work) for role, monitor in roles.items()
                ),
                setups.layouts[setup],
            )
        case None:
            return None


def dark_when_away(
    monitors: Sequence[Monitor], setups: Setups
) -> frozenset[Monitor]:
    match assigned(monitors, setups):
        case (setup, roles):
            return frozenset(
                monitor
                for role, monitor in roles.items()
                if role in setups.dark_when_away.get(setup, frozenset())
            )
        case None:
            return frozenset()


@dataclass(frozen=True, slots=True)
class Program:
    exe: str


type App = PinnedApp | Program


@dataclass(frozen=True, slots=True)
class Region:
    left: Fraction
    top: Fraction
    width: Fraction
    height: Fraction


@dataclass(frozen=True, slots=True)
class Position:
    desktop: int
    """Zero-based, in Task View's order."""
    role: Role
    region: Region


type Places = tuple[Position, ...]
"""An application's places in order; its windows beyond the last share that one, with any app whose last place it also is."""


@dataclass(frozen=True, slots=True)
class Layout:
    places: frozendict[App, Places]
    others: Position
    """The place every application the layout doesn't name shares, in their stable order."""
    side_by_side: int | None = field(default=None, kw_only=True)
    """The most windows a place shows at once; more stack in layers on top, each layer sharing the place again. None shows them all."""

    def __post_init__(self) -> None:
        if self.side_by_side is not None and self.side_by_side < 1:
            raise ValueError("A place shows at least one window per layer.")

    @property
    def desktops(self) -> int:
        return 1 + max(
            position.desktop
            for places in (*self.places.values(), (self.others,))
            for position in places
        )


@dataclass(frozen=True, slots=True)
class Setups:
    externals: frozendict[Setup, frozendict[Size, Role]]
    """Each setup's external screens beside the laptop's own panel, by physical size."""
    layouts: frozendict[Setup, Layout]
    """Each application's places per setup, so no application is declared twice."""
    dark_when_away: frozendict[Setup, frozenset[Role]]
    """Each setup's external screens that turn dark while nobody is at the machine."""

    def __post_init__(self) -> None:
        every_member(Setup, self.externals)
        every_member(Setup, self.layouts)


@dataclass(frozen=True, slots=True)
class Screens:
    setup: Setup
    roles: frozendict[Role, Rect]
    layout: Layout


def managed(window: Window, *, resizable: bool, own: bool) -> bool:
    return resizable and not own and bool(window.exe)


@dataclass(frozen=True, slots=True)
class Group:
    app: App
    windows: tuple[int, ...]


def groups(shelf: Shelf, eligible: frozenset[int]) -> tuple[Group, ...]:
    pinned = (
        Group(
            slot.app,
            tuple(
                window.handle
                for window in slot.windows
                if window.handle in eligible
            ),
        )
        for slot in shelf.pinned
    )
    running = (
        Group(
            Program(app.identity),
            tuple(
                window.handle
                for window in app.windows
                if window.handle in eligible
            ),
        )
        for app in shelf.running
    )
    return tuple(group for group in (*pinned, *running) if group.windows)


@dataclass(frozen=True, slots=True)
class Layer:
    place: Rect
    """The whole place whose layers stack, in physical pixels; it tells one stack from another."""
    depth: int
    """Zero for the bottom layer, counting up."""


@dataclass(frozen=True, slots=True)
class Target:
    desktop: int
    rect: Rect
    """Where the window's drawn edges go, in physical pixels."""
    layer: Layer | None = None
    """Its layer, when its place holds more windows than one layer shows."""


type Placement = frozendict[int, Target]
NOWHERE: Placement = frozendict()


def place(where: Screens, apps: Sequence[Group]) -> Placement:
    declared = where.layout.places
    windows = frozendict((group.app, group.windows) for group in apps)
    others = tuple(
        handle
        for group in apps
        if group.app not in declared
        for handle in group.windows
    )
    alone = (
        (
            handle,
            Target(
                position.desktop,
                pixels(where.roles[position.role], position.region),
            ),
        )
        for app, places in declared.items()
        for handle, position in zip(
            windows.get(app, ()), places[:-1], strict=False
        )
    )
    lasts = (
        *(
            (places[-1], windows.get(app, ())[len(places) - 1 :])
            for app, places in declared.items()
        ),
        (where.layout.others, others),
    )
    shared = frozendict(
        (
            last,
            tuple(
                handle
                for position, rest in lasts
                if position == last
                for handle in rest
            ),
        )
        for last, _ in lasts
    )

    def split_up(
        position: Position, handles: Sequence[int]
    ) -> Iterator[tuple[int, Target]]:
        work = where.roles[position.role]
        stacked = layers(handles, where.layout.side_by_side)
        whole = pixels(work, position.region)
        for depth, layer in enumerate(stacked):
            for handle, rect in zip(
                layer, split(work, position.region, len(layer)), strict=True
            ):
                yield (
                    handle,
                    Target(
                        position.desktop,
                        rect,
                        Layer(whole, depth) if len(stacked) > 1 else None,
                    ),
                )

    return frozendict(
        (
            *alone,
            *(
                pair
                for position, handles in shared.items()
                for pair in split_up(position, handles)
            ),
        )
    )


def layers(
    handles: Sequence[int], side_by_side: int | None
) -> tuple[tuple[int, ...], ...]:
    width = side_by_side or max(len(handles), 1)
    return tuple(
        tuple(handles[start : start + width])
        for start in range(0, len(handles), width)
    )


def _corner(rects: Iterable[Rect]) -> Point | None:
    return min(
        (Point(rect.left, rect.top) for rect in rects),
        key=lambda point: (point.x, point.y),
        default=None,
    )


def _declared_corners(where: Screens, desktop: int) -> frozendict[App, Point]:
    return frozendict(
        (app, corner)
        for app, places in where.layout.places.items()
        if (
            corner := _corner(
                pixels(where.roles[place.role], place.region)
                for place in places
                if place.desktop == desktop
            )
        )
    )


def reading_order(
    where: Screens | None,
    windows: Mapping[App, Sequence[int]],
    placement: Placement,
    desktop: int,
) -> tuple[App, ...]:
    placed: frozendict[App, Point] = frozendict(
        (app, corner)
        for app, handles in windows.items()
        if (
            corner := _corner(
                t.rect
                for h in handles
                if (t := placement.get(h)) and t.desktop == desktop
            )
        )
    )
    declared = (
        _declared_corners(where, desktop)
        if where is not None
        else frozendict[App, Point]()
    )
    corners = frozendict(
        {
            **placed,
            **{
                app: corner
                for app, corner in declared.items()
                if app not in placed
            },
        }
    )
    return tuple(
        sorted(corners, key=lambda app: (corners[app].x, corners[app].y))
    )


def stack(placement: Placement, window: int) -> tuple[tuple[int, ...], ...]:
    """The window's stack, its layers bottom first, each in placement order; empty when its place isn't layered."""
    if not (target := placement.get(window)) or not (layer := target.layer):
        return ()
    members = tuple(
        (handle, below.depth)
        for handle, other in placement.items()
        if (below := other.layer)
        and other.desktop == target.desktop
        and below.place == layer.place
    )
    return tuple(
        tuple(handle for handle, at in members if at == depth)
        for depth in range(1 + max(at for _, at in members))
    )


def mates(placement: Placement, window: int) -> tuple[int, ...]:
    """The other windows of the window's layer, which come up with it."""
    return next(
        (
            tuple(handle for handle in shown if handle != window)
            for shown in stack(placement, window)
            if window in shown
        ),
        (),
    )


def split(work: Rect, region: Region, parts: int) -> tuple[Rect, ...]:
    across = region.width * work.width >= region.height * work.height
    return tuple(
        pixels(
            work,
            Region(
                region.left + region.width * index / parts,
                region.top,
                region.width / parts,
                region.height,
            )
            if across
            else Region(
                region.left,
                region.top + region.height * index / parts,
                region.width,
                region.height / parts,
            ),
        )
        for index in range(parts)
    )


def pixels(work: Rect, region: Region) -> Rect:
    def edge(origin: int, length: int, fraction: Fraction) -> int:
        return origin + round(length * fraction)

    return Rect(
        edge(work.left, work.width, region.left),
        edge(work.top, work.height, region.top),
        edge(work.left, work.width, region.left + region.width),
        edge(work.top, work.height, region.top + region.height),
    )
