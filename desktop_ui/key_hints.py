from collections.abc import Iterator
from dataclasses import dataclass, field

import protocol
from desktop_ui.navigation import (
    AppKey,
    Direction,
    Focus,
    SpatialFocus,
    World,
    effect,
    identity,
    keyed,
    launcher,
    shown,
)
from protocol import Target, Tool
from winapi.shapes import Rect


@dataclass(frozen=True, slots=True)
class AppCap:
    letter: str
    next: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class DirectionCap:
    letter: str
    direction: Direction


@dataclass(frozen=True, slots=True)
class ActionCap:
    letter: str


type Keycap = AppCap | DirectionCap | ActionCap


@dataclass(frozen=True, slots=True)
class Badge:
    window: int
    rect: Rect
    """The window's placed rectangle, in physical pixels; the badge sits inside its top-right corner."""
    keycaps: tuple[Keycap, ...]


def reached(world: World, request: Target) -> int | None:
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


def placed(
    world: World, request: Target, letter: str
) -> Iterator[tuple[int, Keycap]]:
    match request:
        case protocol.App(target=target):
            handles = world.windows.get(identity(launcher(target)), ())
            following = reached(world, request)
            yield from (
                (
                    handle,
                    AppCap(
                        letter, next=len(handles) > 1 and handle == following
                    ),
                )
                for handle in handles
            )
        case Tool.ZOOM:
            yield world.foreground, ActionCap(letter)
        case Tool():
            match keyed(request), reached(world, request):
                case SpatialFocus(direction=direction), int(window):
                    yield window, DirectionCap(letter, direction)
                case _:
                    pass


def rank(keycap: Keycap) -> int:
    match keycap:
        case AppCap():
            return 0
        case DirectionCap():
            return 1
        case ActionCap():
            return 2


def hints(world: World, letters: frozendict[Target, str]) -> tuple[Badge, ...]:
    visible = shown(world)
    drawn = tuple(
        each
        for request, letter in letters.items()
        for each in placed(world, request, letter)
    )
    badges = (
        Badge(
            handle,
            target.rect,
            tuple(
                sorted(
                    (keycap for window, keycap in drawn if window == handle),
                    key=rank,
                )
            ),
        )
        for handle, target in world.placement.items()
        if handle in visible
    )
    return tuple(badge for badge in badges if badge.keycaps)
