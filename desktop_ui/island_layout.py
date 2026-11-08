"""Where the island bar's capsules sit: a pure frame from measured sizes and presence.

Activity stays centred where space permits; permanent controls anchor right.
Lead capsules grow leftwards from activity and trail capsules rightwards.
The gap between two neighbours belongs to the pair: the full gap scaled by
the less present of the two, so a capsule entering or leaving
opens and closes the space beside it smoothly. Each capsule also owns an edge strip
from the top of the screen down to its glass, so a pointer thrown against the edge
still lands on it.
"""

from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from functools import reduce
from itertools import chain
from operator import add
from typing import assert_never

from desktop_ui import ui_spec
from desktop_ui.island_menu import COLUMNS, Cell, Menu
from desktop_ui.island_model import Control, Glyph, Key, Marker, Part, Slot, Text, Zone

# Every size comes from `ui_spec.Sizes` (`desktop_ui/spec/sizes.py`), which the
# desktop reloads while it runs; nothing here keeps a size of its own.


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
    height: float


@dataclass(frozen=True, slots=True)
class Tile:
    """A menu cell's place inside its expanded capsule, below the capsule's own row."""

    index: int
    cell: Cell
    x: float
    y: float
    width: float
    height: float


def tiles(menu: Menu, grid: ui_spec.MenuGrid) -> tuple[Tile, ...]:
    """Tracks include the gutter, which each cell splits around itself."""
    column = (grid.width - 2 * grid.pad) / COLUMNS
    return tuple(
        Tile(
            index,
            cell,
            grid.pad + cell.column * column + grid.gutter / 2,
            grid.pad + grid.head + cell.track * grid.track + grid.gutter / 2,
            cell.span * column - grid.gutter,
            cell.tracks * grid.track - grid.gutter,
        )
        for index, cell in enumerate(menu.cells)
    )


def expansion(menu: Menu, row: Content, grid: ui_spec.MenuGrid) -> Content:
    """A capsule expanded into the menu: its own row on top, right-aligned so it stays put as the capsule widens."""
    bottom = max((tile.y + tile.height + grid.gutter / 2 for tile in tiles(menu, grid)), default=grid.pad + grid.head)
    width = max(float(grid.width), row.width)
    spots = tuple(Spot(spot.part, spot.x + width - row.width, spot.width) for spot in row.spots)
    return Content(width, spots, bottom + grid.pad)


def extent(part: Part, measure: Callable[[Text], float], capsule: ui_spec.Capsule) -> float:
    match part:
        case Text(tone=tone, reserve=reserve):
            return max(measure(part), measure(Text(reserve, tone))) if reserve else measure(part)
        case Glyph():
            return capsule.icon
        case Control():
            return capsule.control
        case Marker.WAVE:
            return capsule.wave
        case Marker.DOT:
            return capsule.dot
        case Marker.DOTS:
            return capsule.dots
        case _:
            assert_never(part)


def textual(part: Part) -> bool:
    match part:
        case Text():
            return True
        case _:
            return False


@dataclass(frozen=True, slots=True)
class _Step:
    """A part's advance along the row: the gap before it, then its width."""

    part: Part
    gap: float
    width: float


def _steps(slots: Sequence[Slot], measure: Callable[[Text], float], capsule: ui_spec.Capsule) -> Iterator[_Step]:
    for index, slot in enumerate(slots):
        for position, part in enumerate(slot):
            width = extent(part, measure, capsule)
            if not position:
                yield _Step(part, capsule.slot_gap if index else 0.0, width)
            elif width:
                # Two readings side by side keep the space of separate facts.
                yield _Step(part, capsule.slot_gap if textual(part) and textual(slot[position - 1]) else capsule.part_gap, width)
            else:
                yield _Step(part, 0.0, width)


def _placed(steps: Iterable[_Step], start: float) -> Iterator[Spot]:
    """Each part where it lands: after its gap, then the row moves on by its width."""
    x = start
    for step in steps:
        x += step.gap
        yield Spot(step.part, x, step.width)
        x += step.width


def arrange(slots: Sequence[Slot], measure: Callable[[Text], float], sizes: ui_spec.Sizes) -> Content:
    """Parts left to right with their gaps. A control at either end sits concentric with the capsule;
    content without text pads like an icon and is never narrower than a circle.
    """
    capsule = sizes.capsule
    parts = tuple(part for slot in slots for part in slot)
    pad = capsule.text_pad if any(textual(part) for part in parts) else capsule.icon_pad
    inset = capsule.inset

    def edge(part: Part) -> float:
        match part:
            case Control():
                return inset
            case _:
                return pad

    steps = tuple(_steps(slots, measure, capsule))
    start = edge(parts[0]) if parts else pad
    spots = tuple(_placed(steps, start))
    # Added left to right like the placement, so the end matches the last part exactly.
    x = reduce(add, chain.from_iterable((step.gap, step.width) for step in steps), start)
    end = x + (edge(parts[-1]) if parts else pad)
    width = max(float(capsule.height), end)
    shift = (width - end) / 2
    return Content(width, tuple(Spot(spot.part, spot.x + shift, spot.width) for spot in spots), capsule.height)


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
    """The screen's width and the bar's own spacing (`ui_spec.Bar`)."""

    width: float
    top: float
    gap: float
    edge: float


def present(value: float) -> float:
    return min(1.0, max(0.0, value))


def frame(placed: Sequence[Placed], metrics: Metrics, order: Sequence[Key]) -> tuple[Framed, ...]:
    """Capsules in `order`, left to right; absent ones (presence 0) take no space."""

    def shown(capsule: Placed) -> float:
        return capsule.width * present(capsule.presence)

    def boxed(capsule: Placed, x: float) -> Framed:
        box = Box(x, metrics.top, shown(capsule), capsule.height)
        return Framed(capsule.key, box, Box(x, 0, box.width, metrics.top), present(capsule.presence))

    def position(capsule: Placed) -> int:
        return order.index(capsule.key)

    def zone(name: Zone) -> tuple[Placed, ...]:
        return tuple(sorted((c for c in placed if c.zone is name and c.presence > 0), key=position))

    right: tuple[Framed, ...] = ()
    edge = max(0.0, metrics.width - metrics.edge)
    for capsule in reversed(zone(Zone.RIGHT)):
        width = shown(capsule)
        if width > edge:
            continue  # Omit an unfit capsule rather than overlap another hit target.
        edge -= width
        right = (boxed(capsule, edge), *right)
        edge = max(0.0, edge - metrics.gap)
    boundary = edge if right else metrics.width
    islands = zone(Zone.ISLAND)
    if not islands:
        dynamic: tuple[Framed, ...] = ()
        edge = min(metrics.width / 2, boundary)
        for capsule in zone(Zone.TRAIL):
            width = min(shown(capsule), max(0.0, boundary - edge))
            if width > 0:
                box = Box(edge, metrics.top, width, capsule.height)
                dynamic += (Framed(capsule.key, box, Box(edge, 0, width, metrics.top), present(capsule.presence)),)
                edge += width + metrics.gap
        return (*dynamic, *right)
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
    dynamic = (*lead, centre, *trail)
    start = min(each.box.x for each in dynamic)
    end = max(each.box.x + each.box.width for each in dynamic)
    shift = max(-start, min(0.0, boundary - end))

    def bounded(each: Framed) -> Framed:
        x = max(0.0, each.box.x + shift)
        width = max(0.0, min(each.box.width, boundary - x))
        return Framed(each.key, Box(x, each.box.y, width, each.box.height), Box(x, 0, width, metrics.top), each.presence)

    return (*(bounded(each) for each in dynamic if each.box.x + shift < boundary), *right)


def snap(framed: Sequence[Framed], scale: float) -> tuple[Framed, ...]:
    """Round every box to whole device pixels, so Qt and composition draw the same edges."""

    def device(box: Box) -> Box:
        x, y = round(box.x * scale), round(box.y * scale)
        return Box(
            x / scale, y / scale, round((box.x + box.width) * scale) / scale - x / scale, round((box.y + box.height) * scale) / scale - y / scale
        )

    return tuple(Framed(f.key, device(f.box), device(f.strip), f.presence) for f in framed)
