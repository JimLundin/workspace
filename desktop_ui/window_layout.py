"""Where every managed window goes: the monitor setups Workspace recognizes, the
declared desktop and screen region of each application in each setup, and the
pure placement of observed windows onto them.

Each declared application has an ordered list of places: a region of one
role's monitor on one desktop. Its windows fill the places in their stable
order, and windows beyond the last place share that place equally: side by side
in a landscape region, stacked in a portrait one. Every setup keeps the canvas
alone on the first desktop. Every other application gets a desktop of its own
after the declared ones, filling the laptop's work area, and keeps that desktop
while others come and go. Regions are exact fractions, so
neighbours' pixel edges are computed from the same value and meet without
overlapping.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from fractions import Fraction
from itertools import count

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


NO_EXTERNALS: frozendict[Size, Role] = frozendict()
EXTERNALS: frozendict[Setup, frozendict[Size, Role]] = frozendict(
    {
        Setup.LAPTOP_ONLY: NO_EXTERNALS,
        Setup.HOME: frozendict({Size(3840, 2160): Role.MAIN}),
        # Orientation, not arrangement, tells the two work screens apart.
        Setup.WORK: frozendict({Size(2560, 1440): Role.ABOVE, Size(1440, 2560): Role.SIDE}),
    }
)
"""Each setup's external screens beside the laptop's own panel, by physical size."""


DARK_WHEN_AWAY: frozendict[Setup, frozenset[Role]] = frozendict({Setup.HOME: frozenset({Role.MAIN})})
"""Each setup's external screens that turn dark while nobody is at the machine: the home 4K screen is an OLED."""


@dataclass(frozen=True, slots=True)
class Screens:
    """The recognized setup and the work area of each of its roles' monitors."""

    setup: Setup
    roles: frozendict[Role, Rect]


def _ordered(sizes: Iterable[Size]) -> tuple[Size, ...]:
    return tuple(sorted(sizes, key=lambda size: (size.width, size.height)))


def assigned(monitors: Sequence[Monitor]) -> tuple[Setup, frozendict[Role, Monitor]] | None:
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
    setup = next((setup for setup, wanted in EXTERNALS.items() if sizes == _ordered(wanted)), None)
    if setup is None:
        return alone
    roles = {EXTERNALS[setup][monitor.area.size]: monitor for monitor in externals}
    return setup, frozendict({Role.LAPTOP: monitors[laptop], **roles})


def screens(monitors: Sequence[Monitor]) -> Screens | None:
    match assigned(monitors):
        case (setup, roles):
            return Screens(setup, frozendict((role, monitor.work) for role, monitor in roles.items()))
        case None:
            return None


def dark_when_away(monitors: Sequence[Monitor]) -> frozenset[Monitor]:
    """The recognized setup's protected external screens; an unrecognized set protects none."""
    match assigned(monitors):
        case (setup, roles):
            return frozenset(monitor for role, monitor in roles.items() if role in DARK_WHEN_AWAY.get(setup, frozenset()))
        case None:
            return frozenset()


@dataclass(frozen=True, slots=True)
class Program:
    """An ordinary application, by its executable's lowercase file name."""

    exe: str


class WorkspaceView(Enum):
    """Workspace's own windows that have a place, as other applications do."""

    CANVAS = "canvas"


CANVAS_TITLE = "Workspace · Canvas"
"""The canvas window's title, which tells it apart from Workspace's other windows."""


type App = PinnedApp | Program | WorkspaceView

TERMINAL, CODE, EDGE = Program("windowsterminal.exe"), Program("code.exe"), Program("msedge.exe")
"""Ordinary Edge is every Edge window that isn't a pinned web app's."""


@dataclass(frozen=True, slots=True)
class Region:
    """Exact fractions of a monitor's work area."""

    left: Fraction
    top: Fraction
    width: Fraction
    height: Fraction


FULL = Region(Fraction(0), Fraction(0), Fraction(1), Fraction(1))
LEFT_HALF = Region(Fraction(0), Fraction(0), Fraction(1, 2), Fraction(1))
RIGHT_HALF = Region(Fraction(1, 2), Fraction(0), Fraction(1, 2), Fraction(1))
TOP_HALF = Region(Fraction(0), Fraction(0), Fraction(1), Fraction(1, 2))
BOTTOM_HALF = Region(Fraction(0), Fraction(1, 2), Fraction(1), Fraction(1, 2))
LEFT_TWO_THIRDS = Region(Fraction(0), Fraction(0), Fraction(2, 3), Fraction(1))
RIGHT_THIRD = Region(Fraction(2, 3), Fraction(0), Fraction(1, 3), Fraction(1))


@dataclass(frozen=True, slots=True)
class Position:
    desktop: int
    """Zero-based, in Task View's order."""
    role: Role
    region: Region


type Places = tuple[Position, ...]
"""An application's places in order; its windows beyond the last share that one."""

LAYOUTS: frozendict[Setup, frozendict[App, Places]] = frozendict(
    {
        Setup.LAPTOP_ONLY: frozendict(
            {
                WorkspaceView.CANVAS: (Position(0, Role.LAPTOP, FULL),),
                PinnedApp.OUTLOOK: (Position(1, Role.LAPTOP, LEFT_HALF),),
                PinnedApp.TEAMS: (Position(1, Role.LAPTOP, RIGHT_HALF),),
                # Two terminals on desktop 3; the third works beside Code on desktop 4.
                TERMINAL: (Position(2, Role.LAPTOP, LEFT_HALF), Position(2, Role.LAPTOP, RIGHT_HALF), Position(3, Role.LAPTOP, LEFT_HALF)),
                CODE: (Position(3, Role.LAPTOP, RIGHT_HALF),),
                EDGE: (Position(4, Role.LAPTOP, FULL),),
            }
        ),
        Setup.HOME: frozendict(
            {
                WorkspaceView.CANVAS: (Position(0, Role.MAIN, FULL),),
                # Two terminals read Terminal | Terminal | Code across the 4K screen.
                TERMINAL: (Position(1, Role.MAIN, LEFT_TWO_THIRDS),),
                CODE: (Position(1, Role.MAIN, RIGHT_THIRD),),
                PinnedApp.TEAMS: (Position(1, Role.LAPTOP, FULL),),
                EDGE: (Position(2, Role.MAIN, LEFT_HALF),),
                PinnedApp.OUTLOOK: (Position(2, Role.MAIN, RIGHT_HALF),),
            }
        ),
        Setup.WORK: frozendict(
            {
                WorkspaceView.CANVAS: (Position(0, Role.ABOVE, FULL),),
                PinnedApp.TEAMS: (Position(1, Role.SIDE, TOP_HALF),),
                PinnedApp.OUTLOOK: (Position(1, Role.SIDE, BOTTOM_HALF),),
                TERMINAL: (Position(1, Role.ABOVE, LEFT_HALF),),
                CODE: (Position(1, Role.ABOVE, RIGHT_HALF),),
                EDGE: (Position(1, Role.LAPTOP, FULL),),
            }
        ),
    }
)
"""Each application's places per setup, so no application is declared twice."""


def first_places(setup: Setup) -> frozendict[App, Position]:
    """Each declared application's first place: where navigation first finds it."""
    return frozendict((app, places[0]) for app, places in LAYOUTS[setup].items())


def declared_desktops(setup: Setup) -> int:
    return 1 + max((position.desktop for places in LAYOUTS[setup].values() for position in places), default=-1)


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


def place(where: Screens, apps: Sequence[Group], previous: Placement) -> Placement:
    """Each managed window's desktop and rectangle; the previous placement keeps undeclared applications on their desktops."""
    declared = LAYOUTS[where.setup]
    extra = overflow(tuple(group for group in apps if group.app not in declared), previous, declared_desktops(where.setup))

    def targets(group: Group) -> Iterator[tuple[int, Target]]:
        places = declared.get(group.app) or (Position(extra[group.app], Role.LAPTOP, FULL),)
        # Each place before the last holds one window; the last holds the rest, split equally.
        alone, shared, last = group.windows[: len(places) - 1], group.windows[len(places) - 1 :], places[-1]
        for handle, position in zip(alone, places, strict=False):
            yield handle, Target(position.desktop, pixels(where.roles[position.role], position.region))
        for handle, rect in zip(shared, split(where.roles[last.role], last.region, len(shared)), strict=True):
            yield handle, Target(last.desktop, rect)

    return frozendict(pair for group in apps for pair in targets(group))


def _corner(rects: Iterable[Rect]) -> Point | None:
    """The top-left corner of the leftmost rectangle, then the topmost; None for none."""
    return min((Point(rect.left, rect.top) for rect in rects), key=lambda point: (point.x, point.y), default=None)


def _declared_corners(where: Screens, desktop: int) -> frozendict[App, Point]:
    """Where each app the setup declares on this desktop first sits."""
    return frozendict(
        (app, corner)
        for app, places in LAYOUTS[where.setup].items()
        if (corner := _corner(pixels(where.roles[place.role], place.region) for place in places if place.desktop == desktop)) is not None
    )


def reading_order(where: Screens | None, windows: Mapping[App, Sequence[int]], placement: Placement, desktop: int) -> tuple[App, ...]:
    """The desktop's apps as they read on screen, by their leftmost window and then its top.

    An app the setup declares on the desktop is listed even when it isn't running,
    at its first place there, so every desktop shows what belongs on it.
    """
    placed: frozendict[App, Point] = frozendict(
        (app, corner)
        for app, handles in windows.items()
        if (corner := _corner(t.rect for h in handles if (t := placement.get(h)) is not None and t.desktop == desktop)) is not None
    )
    declared = _declared_corners(where, desktop) if where is not None else frozendict[App, Point]()
    corners = frozendict({**placed, **{app: corner for app, corner in declared.items() if app not in placed}})
    return tuple(sorted(corners, key=lambda app: (corners[app].x, corners[app].y)))


def overflow(apps: Sequence[Group], previous: Placement, first: int) -> frozendict[App, int]:
    """One desktop per undeclared application from `first` on: each keeps its previous one, and newcomers take the lowest free ones."""
    claims = sorted(
        (desktop, order, group.app)
        for order, group in enumerate(apps)
        if (desktop := next((previous[handle].desktop for handle in group.windows if handle in previous), None)) is not None and desktop >= first
    )
    kept = tuple(claim for index, claim in enumerate(claims) if index == 0 or claims[index - 1][0] != claim[0])
    taken = frozenset(desktop for desktop, _, _ in kept)
    newcomers = tuple(group.app for group in apps if all(app != group.app for _, _, app in kept))
    free = (desktop for desktop in count(first) if desktop not in taken)
    return frozendict({**{app: desktop for desktop, _, app in kept}, **dict(zip(newcomers, free, strict=False))})


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
