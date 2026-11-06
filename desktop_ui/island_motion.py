"""How the island's capsules move between views: a pure value advanced by its owner's frames.

Each capsule springs its width toward its measured content and its presence
toward shown (1) or gone (0). A capsule arrives from zero presence and leaves
showing its last content until it has collapsed. When content changes, the new
content fades in over the previous one at its own measured size while the width
morphs between them.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace

from desktop_ui.island_layout import Content, Placed
from desktop_ui.island_model import CapsuleView, Key, Part, Text
from desktop_ui.motion import APPEAR, FADE, LEAVE, MORPH, Motion, jump, resting, settle, still, toward


@dataclass(frozen=True, slots=True)
class Shown:
    """A view the bar wants on screen, with its measured content."""

    view: CapsuleView
    content: Content


@dataclass(frozen=True, slots=True)
class Moving:
    view: CapsuleView
    content: Content
    previous: Content | None  # Fading out under `content`, until the fade rests.
    width: Motion
    height: Motion
    presence: Motion
    fade: Motion

    @property
    def key(self) -> Key:
        return self.view.key


@dataclass(frozen=True, slots=True)
class IslandMotion:
    capsules: tuple[Moving, ...] = ()


def arrive(shown: Shown, *, animate: bool) -> Moving:
    presence = toward(still(0.0, APPEAR), 1.0, APPEAR)
    width, height = still(shown.content.width, MORPH), still(shown.content.height, MORPH)
    return Moving(shown.view, shown.content, None, width, height, presence if animate else jump(presence, 1.0), still(1.0, FADE))


def outline(part: Part) -> object:
    """A part as far as cross-fading cares: a reading that changes its text updates in place."""
    match part:
        case Text(tone=tone, strong=strong):
            return (Text, tone, strong)
        case _:
            return part


def follow(moving: Moving, shown: Shown, *, animate: bool) -> Moving:
    width, height = toward(moving.width, shown.content.width, MORPH), toward(moving.height, shown.content.height, MORPH)
    presence = toward(moving.presence, 1.0, APPEAR)
    before, after = (tuple(outline(spot.part) for spot in content.spots) for content in (moving.content, shown.content))
    if before == after:
        fade, previous = moving.fade, moving.previous
    else:
        fade, previous = toward(still(0.0, FADE), 1.0, FADE), moving.content
    changed = Moving(shown.view, shown.content, previous, width, height, presence, fade)
    return changed if animate else rest(changed)


def depart(moving: Moving, *, animate: bool) -> Moving:
    presence = toward(moving.presence, 0.0, LEAVE)
    return replace(moving, presence=presence if animate else jump(presence, 0.0))


def rest(moving: Moving) -> Moving:
    return replace(
        moving,
        previous=None,
        width=jump(moving.width, moving.width.target),
        height=jump(moving.height, moving.height.target),
        presence=jump(moving.presence, moving.presence.target),
        fade=jump(moving.fade, 1.0),
    )


def retarget(motion: IslandMotion, shown: Iterable[Shown], *, animate: bool) -> IslandMotion:
    """New targets for every capsule, continuing from where each is now.

    Capsules keep their left-to-right key order; departing ones stay until they've collapsed.
    """
    wanted = frozendict((each.view.key, each) for each in shown)
    current = frozendict((moving.key, moving) for moving in motion.capsules)

    def moved(key: Key) -> Moving | None:
        match (current.get(key), wanted.get(key)):
            case (Moving() as moving, Shown() as target):
                return follow(moving, target, animate=animate)
            case (None, Shown() as target):
                return arrive(target, animate=animate)
            case (Moving() as moving, None):
                return depart(moving, animate=animate)
            case _:
                return None

    return IslandMotion(tuple(moving for key in Key if (moving := moved(key)) is not None and not gone(moving)))


def gone(moving: Moving) -> bool:
    return moving.presence.target == 0 and resting(moving.presence)


def advance(motion: IslandMotion, seconds: float) -> IslandMotion:
    capsules = tuple(
        replace(
            moving,
            width=settle(moving.width, seconds),
            height=settle(moving.height, seconds),
            presence=settle(moving.presence, seconds),
            fade=(fade := settle(moving.fade, seconds)),
            previous=None if resting(fade) else moving.previous,
        )
        for moving in motion.capsules
    )
    return IslandMotion(tuple(moving for moving in capsules if not gone(moving)))


def finish(motion: IslandMotion) -> IslandMotion:
    """Every capsule where it's headed, at once: departing capsules are gone."""
    return IslandMotion(tuple(rest(moving) for moving in motion.capsules if moving.presence.target > 0))


def settled(motion: IslandMotion) -> bool:
    return all(all(resting(spring) for spring in (moving.width, moving.height, moving.presence, moving.fade)) for moving in motion.capsules)


def placed(motion: IslandMotion, row: float) -> tuple[Placed, ...]:
    """Each capsule's current frame; none is shorter than a capsule's `row` height."""
    return tuple(
        Placed(moving.key, moving.view.zone, max(0.0, moving.width.value), max(row, moving.height.value), moving.presence.value)
        for moving in motion.capsules
    )
