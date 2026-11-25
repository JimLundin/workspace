from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from desktop_ui.island_layout import Content, Placed
from desktop_ui.island_model import CapsuleView, Key, Part, Text
from desktop_ui.motion import (
    Motion,
    Spring,
    jump,
    resting,
    settle,
    still,
    toward,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Springs:
    morph: Spring
    """A capsule changing shape."""
    appear: Spring
    """A capsule arriving."""
    leave: Spring
    """A capsule leaving; critically damped, so it never passes zero."""
    fade: Spring
    """Content crossing over at its measured size."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Timing:
    pulse: float
    """Seconds per cycle of a quick job's pulsing dots..."""
    lag: float
    """...and how far, as a share of a cycle, each dot follows the one before it."""
    opaque_at: float
    """The presence at which a capsule's glass and content are fully opaque, before it reaches its full width."""
    wave_sample: float
    """Seconds between the microphone trace's samples; the wave moves across each one."""


@dataclass(frozen=True, slots=True)
class Shown:
    view: CapsuleView
    content: Content
    anchor: float = field(default=0.0, kw_only=True)
    """A panel's reading, as its centre's distance from the screen's right edge."""


@dataclass(frozen=True, slots=True)
class Moving:
    view: CapsuleView
    content: Content
    previous: Content | None
    width: Motion
    height: Motion
    presence: Motion
    fade: Motion
    anchor: Motion

    @property
    def key(self) -> Key:
        return self.view.key


@dataclass(frozen=True, slots=True)
class IslandMotion:
    capsules: tuple[Moving, ...] = ()


def arrive(shown: Shown, springs: Springs, *, animate: bool) -> Moving:
    presence = toward(still(0.0, springs.appear), 1.0, springs.appear)
    width, height = (
        still(shown.content.width, springs.morph),
        still(shown.content.height, springs.morph),
    )
    shape = presence if animate else jump(presence, 1.0)
    return Moving(
        shown.view,
        shown.content,
        None,
        width,
        height,
        shape,
        still(1.0, springs.fade),
        still(shown.anchor, springs.morph),
    )


def outline(part: Part) -> object:
    match part:
        case Text(tone=tone):
            return (Text, tone)
        case _:
            return part


def follow(
    moving: Moving, shown: Shown, springs: Springs, *, animate: bool
) -> Moving:
    width, height = (
        toward(moving.width, shown.content.width, springs.morph),
        toward(moving.height, shown.content.height, springs.morph),
    )
    presence = toward(moving.presence, 1.0, springs.appear)
    before, after = (
        tuple(outline(spot.part) for spot in content.spots)
        for content in (moving.content, shown.content)
    )
    if before == after:
        fade, previous = moving.fade, moving.previous
    else:
        fade, previous = (
            toward(still(0.0, springs.fade), 1.0, springs.fade),
            moving.content,
        )
    changed = Moving(
        shown.view,
        shown.content,
        previous,
        width,
        height,
        presence,
        fade,
        toward(moving.anchor, shown.anchor, springs.morph),
    )
    return changed if animate else rest(changed)


def depart(moving: Moving, springs: Springs, *, animate: bool) -> Moving:
    presence = toward(moving.presence, 0.0, springs.leave)
    return replace(
        moving, presence=presence if animate else jump(presence, 0.0)
    )


def rest(moving: Moving) -> Moving:
    return replace(
        moving,
        previous=None,
        width=jump(moving.width, moving.width.target),
        height=jump(moving.height, moving.height.target),
        presence=jump(moving.presence, moving.presence.target),
        fade=jump(moving.fade, 1.0),
        anchor=jump(moving.anchor, moving.anchor.target),
    )


def retarget(
    motion: IslandMotion,
    shown: Iterable[Shown],
    springs: Springs,
    *,
    animate: bool,
) -> IslandMotion:
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

    return IslandMotion(
        tuple(
            moving for key in Key if (moving := moved(key)) and not gone(moving)
        )
    )


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
            anchor=settle(moving.anchor, seconds),
            previous=None if resting(fade) else moving.previous,
        )
        for moving in motion.capsules
    )
    return IslandMotion(
        tuple(moving for moving in capsules if not gone(moving))
    )


def finish(motion: IslandMotion) -> IslandMotion:
    return IslandMotion(
        tuple(
            rest(moving)
            for moving in motion.capsules
            if moving.presence.target > 0
        )
    )


def settled(motion: IslandMotion) -> bool:
    return all(
        all(
            resting(spring)
            for spring in (
                moving.width,
                moving.height,
                moving.presence,
                moving.fade,
                moving.anchor,
            )
        )
        for moving in motion.capsules
    )


def placed(motion: IslandMotion, row: float) -> tuple[Placed, ...]:
    return tuple(
        Placed(
            moving.key,
            moving.view.zone,
            max(0.0, moving.width.value),
            max(row, moving.height.value),
            moving.presence.value,
            moving.anchor.value,
        )
        for moving in motion.capsules
    )
