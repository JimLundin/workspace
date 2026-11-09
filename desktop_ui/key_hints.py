"""What the screen shows while either keyboard holds its Apps key: the request letters.

Each placed window on the current desktop carries a badge with its app's letter
and, beside the focused window, the focus letter that reaches it. The focused
window adds Zoom. Badges ask the navigation decision itself where
each letter leads, so a hint can't name a window the chord wouldn't reach.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field

import protocol
from desktop_ui.navigation import AppKey, Direction, Focus, SpatialFocus, World, effect, identity, keyed, launcher
from keyboard.firmware import CHORDS
from protocol import Request, Tool
from winapi.shapes import Rect


@dataclass(frozen=True, slots=True)
class AppCap:
    """The app's chord letter; `next` marks which of its several windows the next press reaches."""

    letter: str
    next: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class DirectionCap:
    """The focus chord that moves from the focused window to this one."""

    letter: str
    direction: Direction


@dataclass(frozen=True, slots=True)
class ActionCap:
    """A chord acting on the focused window, shown quietly."""

    letter: str


type Keycap = AppCap | DirectionCap | ActionCap


@dataclass(frozen=True, slots=True)
class Badge:
    window: int
    rect: Rect
    """The window's placed rectangle, in physical pixels; the badge sits inside its top-left corner."""
    keycaps: tuple[Keycap, ...]


def reached(world: World, request: Request) -> int | None:
    """The window this chord focuses now, as the navigation decision carries it out."""
    match request:
        case protocol.App():
            navigation: AppKey | SpatialFocus = AppKey(request)
        case Tool():
            match keyed(request):
                case SpatialFocus() as spatial:
                    navigation = spatial
                case _:
                    return None
    match effect(navigation, world):
        case Focus(window=window):
            return window
        case _:
            return None


def placed(world: World, request: Request, letter: str) -> Iterator[tuple[int, Keycap]]:
    """The windows this chord's letter is drawn on, each with its keycap."""
    match request:
        case protocol.App(target=target):
            handles = world.windows.get(identity(launcher(target)), ())
            following = reached(world, request)
            yield from ((handle, AppCap(letter, next=len(handles) > 1 and handle == following)) for handle in handles)
        case Tool.ZOOM:
            yield world.foreground, ActionCap(letter)
        case Tool():
            match keyed(request), reached(world, request):
                case SpatialFocus(direction=direction), int(window):
                    yield window, DirectionCap(letter, direction)
                case _:
                    pass


def rank(keycap: Keycap) -> int:
    """A badge reads its app's letter, then the focus letters reaching it, then the quiet actions."""
    match keycap:
        case AppCap():
            return 0
        case DirectionCap():
            return 1
        case ActionCap():
            return 2


def hints(world: World) -> tuple[Badge, ...]:
    """The badges while the chord is held."""
    drawn = tuple(each for request, letter in CHORDS.items() for each in placed(world, request, letter))
    badges = (
        Badge(handle, target.rect, tuple(sorted((keycap for window, keycap in drawn if window == handle), key=rank)))
        for handle, target in world.placement.items()
        if target.desktop == world.current
    )
    return tuple(badge for badge in badges if badge.keycaps)
