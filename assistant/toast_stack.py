"""Toast stack layout: measured card sizes in; heights, capacity, releases and frames out."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, auto
from typing import Final

from assistant.agent_progress import TRAIL_ALPHA
from assistant.notifications import MAX_VISIBLE, WIDTH
from winapi.shapes import Rect

MARGIN: Final = 16  # logical pixels between the stack and the work-area edge
GAP: Final = 10
RISE: Final = 16  # logical travel of an arriving, leaving or pushed card
PENDING_HEIGHT: Final = 480  # logical preference for pending input
HEIGHT: Final = 360


class Preview(Enum):
    LINES = auto()  # two body lines carry the gist when space is short
    COMPLETE = auto()  # a collapsed assessment keeps its complete title


@dataclass(frozen=True, slots=True)
class Measured:
    """One desired card's native measurement, in physical pixels."""

    preferred: int
    chrome: int  # header, hint and padding
    body: int
    priority: int
    preview: Preview


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
    TRAIL = auto()  # live progress fades older phases and closes retiring space
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
    match card.preview:
        case Preview.COMPLETE:
            return Space(min(card.preferred, card.chrome + card.body), card.preferred, card.priority)
        case Preview.LINES:
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
    if all(heights) or column.capacity == 1:
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
                if stacking is Stacking.FEED:
                    alpha = 1.0
                else:
                    if placed:
                        bottom = min(bottom, top - (viewport.rise if stacking is Stacking.PUSH else 0))
                    alpha = TRAIL_ALPHA[min(len(placed), len(TRAIL_ALPHA) - 1)]
                placed = (*placed, Placement(bottom, alpha))
                bottom -= viewport.gap
    return placed


def _available(viewport: Viewport, cards: int) -> int:
    return viewport.area.height - viewport.margin * 2 - viewport.gap * max(0, cards - 1)
