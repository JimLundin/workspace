"""How the island's capsules move between views: a pure value advanced by its owner's frames.

Each capsule springs its width toward its measured content and its presence
toward shown (1) or gone (0). A capsule arrives from zero presence and leaves
showing its last content until it has collapsed. When content changes, the new
content fades in over the previous one at its own measured size while the width
morphs between them.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Final

from desktop_ui.island_layout import Content, Placed
from desktop_ui.island_model import CapsuleView, Key, Part, Text
from desktop_ui.motion import Motion, Spring, jump, resting, settle, still, toward


@dataclass(frozen=True, slots=True, kw_only=True)
class Springs:
    """How each kind of capsule change moves."""

    morph: Spring
    """A capsule changing shape."""
    appear: Spring
    """A capsule arriving."""
    leave: Spring
    """A capsule leaving; critically damped, so it never passes zero."""
    fade: Spring
    """Content crossing over at its measured size."""


SPRINGS: Final = Springs(
    morph=Spring(0.86, 0.42),
    appear=Spring(0.78, 0.42),  # A little overshoot.
    leave=Spring(1.0, 0.3),
    fade=Spring(1.0, 0.2),
)
"""The bar's own springs; its owner passes them in, tests pass their own."""


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


def arrive(shown: Shown, springs: Springs, *, animate: bool) -> Moving:
    presence = toward(still(0.0, springs.appear), 1.0, springs.appear)
    width, height = still(shown.content.width, springs.morph), still(shown.content.height, springs.morph)
    return Moving(shown.view, shown.content, None, width, height, presence if animate else jump(presence, 1.0), still(1.0, springs.fade))


def outline(part: Part) -> object:
    """A part as far as cross-fading cares: a reading that changes its text updates in place."""
    match part:
        case Text(tone=tone):
            return (Text, tone)
        case _:
            return part


def follow(moving: Moving, shown: Shown, springs: Springs, *, animate: bool) -> Moving:
    width, height = toward(moving.width, shown.content.width, springs.morph), toward(moving.height, shown.content.height, springs.morph)
    presence = toward(moving.presence, 1.0, springs.appear)
    before, after = (tuple(outline(spot.part) for spot in content.spots) for content in (moving.content, shown.content))
    if before == after:
        fade, previous = moving.fade, moving.previous
    else:
        fade, previous = toward(still(0.0, springs.fade), 1.0, springs.fade), moving.content
    changed = Moving(shown.view, shown.content, previous, width, height, presence, fade)
    return changed if animate else rest(changed)


def depart(moving: Moving, springs: Springs, *, animate: bool) -> Moving:
    presence = toward(moving.presence, 0.0, springs.leave)
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


def retarget(motion: IslandMotion, shown: Iterable[Shown], springs: Springs, *, animate: bool) -> IslandMotion:
    """New targets for every capsule, continuing from where each is now.

    Capsules keep their left-to-right key order; departing ones stay until they've collapsed.
    """
    wanted = frozendict((each.view.key, each) for each in shown)
    current = frozendict((moving.key, moving) for moving in motion.capsules)

    def moved(key: Key) -> Moving | None:
        match (current.get(key), wanted.get(key)):
            case (Moving() as moving, Shown() as target):
                return follow(moving, target, springs, animate=animate)
            case (None, Shown() as target):
                return arrive(target, springs, animate=animate)
            case (Moving() as moving, None):
                return depart(moving, springs, animate=animate)
            case _:
                return None

    return IslandMotion(tuple(moving for key in Key if (moving := moved(key)) and not gone(moving)))


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
