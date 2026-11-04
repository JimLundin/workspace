"""Where every managed window goes: the monitor setups Workspace recognizes, the
declared desktop and screen region of each application in each setup, and the
pure placement of observed windows onto them.

Each declared application has one region of one role's monitor on one desktop.
Several windows of an application share its region equally: side by side in a
landscape region, stacked in a portrait one. Every other application gets a
desktop of its own after the declared ones, filling the laptop's work area, and
keeps that desktop while others come and go. Regions are exact fractions, so
neighbours' pixel edges are computed from the same value and meet without
overlapping.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, auto
from fractions import Fraction
from itertools import count

from desktop_ui.shell_items import PinnedApp, Shelf
from winapi.screen import Monitor
from winapi.shapes import Rect, Window


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


NO_EXTERNALS: frozendict[tuple[int, int], Role] = frozendict()
EXTERNALS: frozendict[Setup, frozendict[tuple[int, int], Role]] = frozendict(
    {
        Setup.LAPTOP_ONLY: NO_EXTERNALS,
        Setup.HOME: frozendict({(3840, 2160): Role.MAIN}),
        # Orientation, not arrangement, tells the two work screens apart.
        Setup.WORK: frozendict({(2560, 1440): Role.ABOVE, (1440, 2560): Role.SIDE}),
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


def assigned(monitors: Sequence[Monitor]) -> tuple[Setup, frozendict[Role, Monitor]] | None:
    """Match the connected monitors to a setup; any other set is the laptop alone, on its panel or the primary monitor."""
    if not monitors:
        return None
    panels = tuple(index for index, monitor in enumerate(monitors) if monitor.internal)
    laptop = panels[0] if len(panels) == 1 else next((index for index, monitor in enumerate(monitors) if monitor.primary), 0)
    externals = tuple(monitor for index, monitor in enumerate(monitors) if index != laptop)
    sizes = tuple(sorted((monitor.area.width, monitor.area.height) for monitor in externals))
    alone = (Setup.LAPTOP_ONLY, frozendict({Role.LAPTOP: monitors[laptop]}))
    if len(panels) != 1:
        return alone
    setup = next((setup for setup, wanted in EXTERNALS.items() if sizes == tuple(sorted(wanted))), None)
    if setup is None:
        return alone
    roles = {EXTERNALS[setup][(monitor.area.width, monitor.area.height)]: monitor for monitor in externals}
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


type App = PinnedApp | Program

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


LAYOUTS: frozendict[Setup, frozendict[App, Position]] = frozendict(
    {
        Setup.LAPTOP_ONLY: frozendict(
            {
                PinnedApp.OUTLOOK: Position(0, Role.LAPTOP, LEFT_HALF),
                PinnedApp.TEAMS: Position(0, Role.LAPTOP, RIGHT_HALF),
                TERMINAL: Position(1, Role.LAPTOP, LEFT_HALF),
                CODE: Position(1, Role.LAPTOP, RIGHT_HALF),
                EDGE: Position(2, Role.LAPTOP, FULL),
            }
        ),
        Setup.HOME: frozendict(
            {
                # Two terminals read Terminal | Terminal | Code across the 4K screen.
                TERMINAL: Position(0, Role.MAIN, LEFT_TWO_THIRDS),
                CODE: Position(0, Role.MAIN, RIGHT_THIRD),
                PinnedApp.TEAMS: Position(0, Role.LAPTOP, FULL),
                EDGE: Position(1, Role.MAIN, LEFT_HALF),
                PinnedApp.OUTLOOK: Position(1, Role.MAIN, RIGHT_HALF),
            }
        ),
        Setup.WORK: frozendict(
            {
                PinnedApp.TEAMS: Position(0, Role.SIDE, TOP_HALF),
                PinnedApp.OUTLOOK: Position(0, Role.SIDE, BOTTOM_HALF),
                TERMINAL: Position(0, Role.ABOVE, LEFT_HALF),
                CODE: Position(0, Role.ABOVE, RIGHT_HALF),
                EDGE: Position(0, Role.LAPTOP, FULL),
            }
        ),
    }
)
"""One position per application per setup, so no application is declared twice."""


def declared_desktops(setup: Setup) -> int:
    return 1 + max((position.desktop for position in LAYOUTS[setup].values()), default=-1)


def managed(window: Window, *, resizable: bool, own: bool) -> bool:
    """Workspace places resizable windows of other programs that aren't minimized; dialogs and fixed-size windows keep their own places."""
    return resizable and not own and not window.minimized and bool(window.exe)


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
    laptop = where.roles[Role.LAPTOP]

    def spot(group: Group) -> tuple[int, Rect, Region]:
        match declared.get(group.app):
            case Position(desktop=desktop, role=role, region=region):
                return desktop, where.roles[role], region
            case None:
                return extra[group.app], laptop, FULL

    spots = tuple((group, *spot(group)) for group in apps)
    return frozendict(
        (handle, Target(desktop, rect))
        for group, desktop, work, region in spots
        for handle, rect in zip(group.windows, split(work, region, len(group.windows)), strict=True)
    )


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
