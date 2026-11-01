"""Toast stack layout and motion: measured sizes and timestamps in; placements and frames out."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, auto
from typing import Final

from assistant import motion
from assistant.notifications import MAX_VISIBLE, WIDTH
from winapi.shapes import Rect

MARGIN: Final = 16  # logical pixels between the stack and the work-area edge
GAP: Final = 10
RISE: Final = 16  # logical travel of an arriving, leaving or pushed card
PENDING_HEIGHT: Final = 480  # logical preference for pending input
HEIGHT: Final = 360


@dataclass(frozen=True, slots=True)
class Frame:
    y: float
    width: float
    height: float
    alpha: float
    details: float = 0


@dataclass(frozen=True, slots=True)
class Moving:
    """All five frame fields belong to one shared clock and spring response."""

    y: motion.Motion
    width: motion.Motion
    height: motion.Motion
    alpha: motion.Motion
    details: motion.Motion
    at: float


def start(frame: Frame, now: float) -> Moving:
    return Moving(
        motion.still(frame.y, motion.CARD),
        motion.still(frame.width, motion.CARD),
        motion.still(frame.height, motion.CARD),
        motion.still(frame.alpha, motion.CARD),
        motion.still(frame.details, motion.CARD),
        now,
    )


def retarget(moving: Moving, end: Frame) -> Moving:
    """Keep every field's current value and velocity when the slot changes."""
    return Moving(
        motion.toward(moving.y, end.y, motion.CARD),
        motion.toward(moving.width, end.width, motion.CARD),
        motion.toward(moving.height, end.height, motion.CARD),
        motion.toward(moving.alpha, end.alpha, motion.CARD),
        motion.toward(moving.details, end.details, motion.CARD),
        moving.at,
    )


def advance(moving: Moving, now: float) -> Moving:
    """Advance the synchronized frame from its observation's monotonic time."""
    seconds = now - moving.at
    if seconds <= 0:
        return moving
    return Moving(
        motion.settle(moving.y, seconds),
        motion.settle(moving.width, seconds),
        motion.settle(moving.height, seconds),
        motion.settle(moving.alpha, seconds),
        motion.settle(moving.details, seconds),
        now,
    )


def shown(moving: Moving) -> Frame:
    return Frame(moving.y.value, moving.width.value, moving.height.value, moving.alpha.value, moving.details.value)


def target(moving: Moving) -> Frame:
    return Frame(moving.y.target, moving.width.target, moving.height.target, moving.alpha.target, moving.details.target)


def resting(moving: Moving) -> bool:
    return all(motion.resting(field) for field in (moving.y, moving.width, moving.height, moving.alpha, moving.details))


@dataclass(frozen=True, slots=True)
class Measured:
    """One desired card's native measurement, in physical pixels."""

    preferred: int
    chrome: int  # header, hint and padding
    body: int
    priority: int


@dataclass(frozen=True, slots=True)
class Viewport:
    area: Rect
    scale: float
    line: int  # one scaled body line

    @property
    def margin(self) -> int:
        return round(MARGIN * self.scale)

    @property
    def gap(self) -> int:
        return round(GAP * self.scale)

    @property
    def rise(self) -> int:
        return round(RISE * self.scale)

    @property
    def width(self) -> int:
        return min(round(WIDTH * self.scale), max(1, self.area.width - self.margin * 2))


@dataclass(frozen=True, slots=True)
class Space:
    minimum: int
    preferred: int
    priority: int


@dataclass(frozen=True, slots=True)
class Column:
    cards: tuple[Measured, ...]  # desired cards in stack order
    retiring: tuple[int, ...]  # heights of retiring cards, newest first
    capacity: int


@dataclass(frozen=True, slots=True)
class Fit:
    heights: tuple[int, ...]  # aligned with Column.cards; zero leaves the viewport
    reserved: int  # leading retiring cards that keep their space; the owner releases the rest
    capacity: int  # below Column.capacity when the owner must project fewer cards and fit again


class Stacking(Enum):
    FEED = auto()  # opaque cards; retiring cards hold their space while they leave
    TRAIL = auto()  # live progress closes retiring space; lifetime owns its fade
    PUSH = auto()  # a trail arrival also lifts older phases above their prior top


@dataclass(frozen=True, slots=True)
class Active:
    height: int
    top: float  # the current top, or the top an unfinished motion is heading to


@dataclass(frozen=True, slots=True)
class Retiring:
    height: int


type Slot = Active | Retiring


@dataclass(frozen=True, slots=True)
class Placement:
    y: float
    alpha: float


def reservable(desired: int) -> int:
    """Active and retiring windows together stay within MAX_VISIBLE."""
    return max(0, MAX_VISIBLE - desired)


def space(card: Measured, viewport: Viewport) -> Space:
    # Two body lines carry the gist when space is short.
    preferred = min(card.preferred, round((PENDING_HEIGHT if card.priority == 2 else HEIGHT) * viewport.scale))
    return Space(min(preferred, card.chrome + min(card.body, viewport.line * 2 + 16)), preferred, card.priority)


def allocate(spaces: tuple[Space, ...], available: int) -> tuple[int, ...]:
    """Reserve readable previews, then give pending input and recent entries room.

    If even the previews cannot fit, the oldest low-priority entry leaves the
    viewport. Returning zero lets the owner retire it without reviving it later.
    """
    heights = [space.minimum for space in spaces]
    remaining = max(0, available) - sum(heights)

    def rank(index: int) -> tuple[int, int]:
        return spaces[index].priority, index

    ranked = sorted(range(len(spaces)), key=rank)
    for index in ranked:
        if remaining >= 0:
            break
        remaining += heights[index]
        heights[index] = 0
    for index in reversed(ranked):
        if heights[index]:
            extra = min(remaining, max(0, spaces[index].preferred - heights[index]))
            heights[index] += extra
            remaining -= extra
    return tuple(heights)


def fit(column: Column, viewport: Viewport) -> Fit:
    spaces = tuple(space(card, viewport) for card in column.cards)
    reserved = column.retiring[: reservable(len(spaces))]
    heights = allocate(spaces, _available(viewport, len(spaces) + len(reserved)) - sum(reserved))
    if 0 in heights and reserved:
        # Retiring bubbles cannot consume space needed by the next page.
        reserved = ()
        heights = allocate(spaces, _available(viewport, len(spaces)))
    if all(heights):
        return Fit(heights, len(reserved), column.capacity)
    return Fit(heights, len(reserved), max(1, min(column.capacity - 1, sum(height > 0 for height in heights))))


def frames(slots: Sequence[Slot], viewport: Viewport, stacking: Stacking) -> tuple[Placement, ...]:
    """Stack cards upward from the work area's bottom, newest first; one placement per active slot."""
    bottom: float = viewport.area.bottom - viewport.margin
    placed: tuple[Placement, ...] = ()
    for slot in slots:
        match slot:
            case Retiring(height):
                if stacking is Stacking.FEED:
                    bottom -= height + viewport.gap
            case Active(height, top):
                bottom -= height
                if stacking is not Stacking.FEED and placed:
                    bottom = min(bottom, top - (viewport.rise if stacking is Stacking.PUSH else 0))
                placed = (*placed, Placement(bottom, 1.0))
                bottom -= viewport.gap
    return placed


def _available(viewport: Viewport, cards: int) -> int:
    return viewport.area.height - viewport.margin * 2 - viewport.gap * max(0, cards - 1)
