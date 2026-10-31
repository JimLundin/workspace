"""Where the island bar's capsules sit: a pure frame from measured sizes and presence.

The island stays centred on the screen; lead capsules grow leftwards from it and
trail capsules rightwards. The gap between two neighbours belongs to the pair: the
full gap scaled by the less present of the two, so a capsule entering or leaving
opens and closes the space beside it smoothly. Each capsule also owns an edge strip
from the top of the screen down to its glass, so a pointer thrown against the edge
still lands on it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, assert_never

from assistant.island_model import Badge, Control, Glyph, Key, Marker, Part, Slot, Spinner, Text, Zone

# A 34 px capsule with a 3 px inset holds concentric 28 px controls.
HEIGHT: Final = 34
CONTROL: Final = 28
ICON: Final = 16
SPINNER: Final = 14
DOT: Final = 8
WAVE_BARS: Final = 18
WAVE: Final = WAVE_BARS * 4 - 2
PART_GAP: Final = 6
SLOT_GAP: Final = 12
TEXT_PAD: Final = 12
ICON_PAD: Final = 10


@dataclass(frozen=True, slots=True)
class Spot:
    """A part's horizontal place inside its capsule."""

    part: Part
    x: float
    width: float


@dataclass(frozen=True, slots=True)
class Content:
    width: float
    spots: tuple[Spot, ...]


def extent(part: Part, measure: Callable[[Text], float]) -> float:
    match part:
        case Text():
            return measure(part)
        case Glyph():
            return ICON
        case Spinner():
            return SPINNER
        case Badge():
            return 0  # It overlays the corner of the symbol before it.
        case Control():
            return CONTROL
        case Marker.WAVE:
            return WAVE
        case Marker.DOT:
            return DOT
        case _:
            assert_never(part)


def textual(part: Part) -> bool:
    match part:
        case Text():
            return True
        case _:
            return False


def arrange(slots: Sequence[Slot], measure: Callable[[Text], float]) -> Content:
    """Parts left to right with their gaps. A control at either end sits concentric, 3 px from the edge;
    content without text pads like an icon and is never narrower than a circle."""
    parts = tuple(part for slot in slots for part in slot)
    pad = TEXT_PAD if any(textual(part) for part in parts) else ICON_PAD
    inset = (HEIGHT - CONTROL) / 2

    def edge(part: Part) -> float:
        match part:
            case Control():
                return inset
            case _:
                return pad

    x = edge(parts[0]) if parts else pad
    spots: list[Spot] = []
    for index, slot in enumerate(slots):
        if index and slot:
            x += SLOT_GAP
        for position, part in enumerate(slot):
            width = extent(part, measure)
            if position and width:
                # Two readings side by side keep the space of separate facts.
                x += SLOT_GAP if textual(part) and textual(slot[position - 1]) else PART_GAP
            spots.append(Spot(part, x, width))
            x += width
    end = x + (edge(parts[-1]) if parts else pad)
    width = max(float(HEIGHT), end)
    shift = (width - end) / 2
    return Content(width, tuple(Spot(spot.part, spot.x + shift, spot.width) for spot in spots))


@dataclass(frozen=True, slots=True)
class Placed:
    """A capsule's measured size and its presence, from 0 (absent) to 1 (fully shown)."""

    key: Key
    zone: Zone
    width: float
    height: float
    presence: float = 1.0


@dataclass(frozen=True, slots=True)
class Box:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class Framed:
    key: Key
    box: Box
    strip: Box
    presence: float


@dataclass(frozen=True, slots=True)
class Metrics:
    width: float
    top: float = 8
    gap: float = 6


def present(value: float) -> float:
    return min(1.0, max(0.0, value))


def frame(placed: Sequence[Placed], metrics: Metrics) -> tuple[Framed, ...]:
    """Capsules in left-to-right order; absent ones (presence 0) take no space."""
    order = tuple(Key)

    def shown(capsule: Placed) -> float:
        return capsule.width * present(capsule.presence)

    def boxed(capsule: Placed, x: float) -> Framed:
        box = Box(x, metrics.top, shown(capsule), capsule.height)
        return Framed(capsule.key, box, Box(x, 0, box.width, metrics.top), present(capsule.presence))

    def zone(name: Zone) -> tuple[Placed, ...]:
        return tuple(sorted((c for c in placed if c.zone is name and c.presence > 0), key=lambda c: order.index(c.key)))

    islands = zone(Zone.ISLAND)
    if not islands:
        return ()
    island = islands[0]
    left = (metrics.width - shown(island)) / 2
    centre = boxed(island, left)

    def outward(capsules: tuple[Placed, ...], edge: float, *, leading: bool) -> tuple[Framed, ...]:
        framed: tuple[Framed, ...] = ()
        before = present(island.presence)
        for capsule in capsules:
            space = metrics.gap * min(before, present(capsule.presence))
            x = edge - space - shown(capsule) if leading else edge + space
            framed = (boxed(capsule, x), *framed) if leading else (*framed, boxed(capsule, x))
            edge = x if leading else x + shown(capsule)
            before = present(capsule.presence)
        return framed

    lead = outward(tuple(reversed(zone(Zone.LEAD))), left, leading=True)
    trail = outward(zone(Zone.TRAIL), left + shown(island), leading=False)
    return (*lead, centre, *trail)


def snap(framed: Sequence[Framed], scale: float) -> tuple[Framed, ...]:
    """Round every box to whole device pixels, so Qt and composition draw the same edges."""

    def device(box: Box) -> Box:
        x, y = round(box.x * scale), round(box.y * scale)
        return Box(
            x / scale, y / scale, round((box.x + box.width) * scale) / scale - x / scale, round((box.y + box.height) * scale) / scale - y / scale
        )

    return tuple(Framed(f.key, device(f.box), device(f.strip), f.presence) for f in framed)
