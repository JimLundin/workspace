"""Where every managed window goes: the monitor setups Workspace recognizes, the
declared desktop and screen region of each application in each setup, and the
pure placement of observed windows onto them.

Each declared application has an ordered list of places: a region of one
role's monitor on one desktop. Its windows fill the places in their stable
order, and windows beyond the last place share that place equally: side by side
in a landscape region, stacked in a portrait one. Every other application shares
the setup's one place for others, so a setup has exactly the desktops its layout
declares. Regions are exact fractions, so
neighbours' pixel edges are computed from the same value and meet without
overlapping.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
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


def assigned(monitors: Sequence[Monitor], setups: Setups) -> tuple[Setup, frozendict[Role, Monitor]] | None:
    """Match the connected monitors to a setup; any other set is the laptop alone, on its panel or the primary monitor."""
    if not monitors:
        return None
    panels = tuple(index for index, monitor in enumerate(monitors) if monitor.internal)
    laptop = panels[0] if len(panels) == 1 else next((index for index, monitor in enumerate(monitors) if monitor.primary), 0)
    externals = tuple(monitor for index, monitor in enumerate(monitors) if index != laptop)
    sizes = _ordered(monitor.area.size for monitor in externals)
    alone = (Setup.LAPTOP_ONLY, frozendict({Role.LAPTOP: monitors[laptop]}))
    if len(panels) != 1:
        return alone
    setup = next((setup for setup, wanted in setups.externals.items() if sizes == _ordered(wanted)), None)
    if setup is None:
        return alone
    roles = {setups.externals[setup][monitor.area.size]: monitor for monitor in externals}
    return setup, frozendict({Role.LAPTOP: monitors[laptop], **roles})


def screens(monitors: Sequence[Monitor], setups: Setups) -> Screens | None:
    match assigned(monitors, setups):
        case (setup, roles):
            return Screens(setup, frozendict((role, monitor.work) for role, monitor in roles.items()), setups.layouts[setup])
        case None:
            return None


def dark_when_away(monitors: Sequence[Monitor], setups: Setups) -> frozenset[Monitor]:
    """The recognized setup's protected external screens; an unrecognized set protects none."""
    match assigned(monitors, setups):
        case (setup, roles):
            return frozenset(monitor for role, monitor in roles.items() if role in setups.dark_when_away.get(setup, frozenset()))
        case None:
            return frozenset()


@dataclass(frozen=True, slots=True)
class Program:
    """An ordinary application, by its executable's lowercase file name."""

    exe: str


type App = PinnedApp | Program


@dataclass(frozen=True, slots=True)
class Region:
    """Exact fractions of a monitor's work area."""

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
"""An application's places in order; its windows beyond the last share that one."""


@dataclass(frozen=True, slots=True)
class Layout:
    """One setup's applications and their places, and where every other application goes."""

    places: frozendict[App, Places]
    others: Position
    """The place every application the layout doesn't name shares, in their stable order."""

    @property
    def desktops(self) -> int:
        """How many desktops the setup uses: exactly those its places name, counted from the first."""
        return 1 + max(position.desktop for places in (*self.places.values(), (self.others,)) for position in places)


@dataclass(frozen=True, slots=True)
class Setups:
    """The monitor setups Workspace recognizes and what each does with its screens."""

    externals: frozendict[Setup, frozendict[Size, Role]]
    """Each setup's external screens beside the laptop's own panel, by physical size."""
    layouts: frozendict[Setup, Layout]
    """Each application's places per setup, so no application is declared twice."""
    dark_when_away: frozendict[Setup, frozenset[Role]]
    """Each setup's external screens that turn dark while nobody is at the machine."""

    def __post_init__(self) -> None:
        """Every setup has its screens and its layout, so recognizing one always finds both."""
        every_member(Setup, self.externals)
        every_member(Setup, self.layouts)


@dataclass(frozen=True, slots=True)
class Screens:
    """The recognized setup, the work area of each of its roles' monitors, and its layout."""

    setup: Setup
    roles: frozendict[Role, Rect]
    layout: Layout


def managed(window: Window, *, resizable: bool, own: bool) -> bool:
    """Workspace places resizable windows of other programs, minimized or not; dialogs and fixed-size windows keep their own places.

    Every app has a place in every setup, so a minimized window is only a window out of place.
    """
    return resizable and not own and bool(window.exe)


@dataclass(frozen=True, slots=True)
class Group:
    """One application's managed windows, in their stable order."""

    app: App
    windows: tuple[int, ...]


def groups(shelf: Shelf, eligible: frozenset[int]) -> tuple[Group, ...]:
    """The shelf's applications with their managed windows, keeping the shelf's stable window order."""
    pinned = (Group(slot.app, tuple(window.handle for window in slot.windows if window.handle in eligible)) for slot in shelf.pinned)
    running = (Group(Program(app.identity), tuple(window.handle for window in app.windows if window.handle in eligible)) for app in shelf.running)
    return tuple(group for group in (*pinned, *running) if group.windows)


@dataclass(frozen=True, slots=True)
class Target:
    desktop: int
    rect: Rect
    """Where the window's drawn edges go, in physical pixels."""


type Placement = frozendict[int, Target]
NOWHERE: Placement = frozendict()


def place(where: Screens, apps: Sequence[Group]) -> Placement:
    """Each managed window's desktop and rectangle; undeclared applications' windows share the layout's place for others."""
    declared = where.layout.places
    others = tuple(handle for group in apps if group.app not in declared for handle in group.windows)

    def targets(windows: Sequence[int], places: Places) -> Iterator[tuple[int, Target]]:
        # Each place before the last holds one window; the last holds the rest, split equally.
        alone, shared, last = windows[: len(places) - 1], windows[len(places) - 1 :], places[-1]
        for handle, position in zip(alone, places, strict=False):
            yield handle, Target(position.desktop, pixels(where.roles[position.role], position.region))
        for handle, rect in zip(shared, split(where.roles[last.role], last.region, len(shared)), strict=True):
            yield handle, Target(last.desktop, rect)

    named = (pair for group in apps if (places := declared.get(group.app)) for pair in targets(group.windows, places))
    return frozendict((*named, *targets(others, (where.layout.others,))))


def _corner(rects: Iterable[Rect]) -> Point | None:
    """The top-left corner of the leftmost rectangle, then the topmost; None for none."""
    return min((Point(rect.left, rect.top) for rect in rects), key=lambda point: (point.x, point.y), default=None)


def _declared_corners(where: Screens, desktop: int) -> frozendict[App, Point]:
    """Where each app the setup declares on this desktop first sits."""
    return frozendict(
        (app, corner)
        for app, places in where.layout.places.items()
        if (corner := _corner(pixels(where.roles[place.role], place.region) for place in places if place.desktop == desktop))
    )


def reading_order(where: Screens | None, windows: Mapping[App, Sequence[int]], placement: Placement, desktop: int) -> tuple[App, ...]:
    """The desktop's apps as they read on screen, by their leftmost window and then its top.

    An app the setup declares on the desktop is listed even when it isn't running,
    at its first place there, so every desktop shows what belongs on it.
    """
    placed: frozendict[App, Point] = frozendict(
        (app, corner)
        for app, handles in windows.items()
        if (corner := _corner(t.rect for h in handles if (t := placement.get(h)) and t.desktop == desktop))
    )
    declared = _declared_corners(where, desktop) if where is not None else frozendict[App, Point]()
    corners = frozendict({**placed, **{app: corner for app, corner in declared.items() if app not in placed}})
    return tuple(sorted(corners, key=lambda app: (corners[app].x, corners[app].y)))


def split(work: Rect, region: Region, parts: int) -> tuple[Rect, ...]:
    """`parts` equal rectangles filling the region: columns when it's landscape, rows when it's portrait."""
    across = region.width * work.width >= region.height * work.height
    return tuple(
        pixels(
            work,
            Region(region.left + region.width * index / parts, region.top, region.width / parts, region.height)
            if across
            else Region(region.left, region.top + region.height * index / parts, region.width, region.height / parts),
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
