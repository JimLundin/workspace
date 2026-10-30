"""Measured native canvas containers, nested shelves and scoped user placements.

Qt supplies measured rectangles. General graph libraries add native/numerical
runtime dependencies without helping this narrow containment policy. Membership
belongs to work_canvas_context; this module only places its immutable scene.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace

from assistant.work_canvas_context import CanvasScene, ContextGroup, descendants
from assistant.work_canvas_model import CanvasViewState, Placement


@dataclass(frozen=True, slots=True)
class Size:
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    def overlaps(self, other: Box) -> bool:
        return (
            self.x < other.x + other.width + 32
            and other.x < self.x + self.width + 32
            and self.y < other.y + other.height + 32
            and other.y < self.y + self.height + 32
        )


@dataclass(frozen=True, slots=True)
class Measurements:
    sizes: frozendict[str, Size]
    width: float


@dataclass(frozen=True, slots=True)
class ContextBounds:
    identity: str
    box: Box


@dataclass(frozen=True, slots=True)
class Arrangement:
    state: CanvasViewState
    frames: tuple[ContextBounds, ...]


@dataclass(frozen=True, slots=True)
class Block:
    identity: str
    size: Size
    placements: tuple[Placement, ...]
    frames: tuple[ContextBounds, ...] = ()


def shifted(block: Block, position: Placement) -> Block:
    return replace(
        block,
        placements=tuple(replace(p, x=p.x + position.x, y=p.y + position.y) for p in block.placements),
        frames=tuple(replace(frame, box=replace(frame.box, x=frame.box.x + position.x, y=frame.box.y + position.y)) for frame in block.frames),
    )


def shelf(blocks: Iterable[Block], width: float) -> Iterator[Block]:
    x, y, bottom = 0.0, 0.0, 0.0
    for block in blocks:
        if x and x + block.size.width > width:
            x, y = 0.0, bottom + 48
        yield shifted(block, Placement(block.identity, x, y))
        bottom = max(bottom, y + block.size.height)
        x += block.size.width + 48


@dataclass(frozen=True, slots=True)
class LayoutSpace:
    measurements: Measurements
    saved: frozendict[str, Placement]
    pinned: frozenset[str]


def group_block(group: ContextGroup, measurements: Measurements) -> Block:
    saved: frozendict[str, Placement] = frozendict()
    return arranged_group(group, LayoutSpace(measurements, saved, frozenset()))


def arranged_group(group: ContextGroup, space: LayoutSpace) -> Block:
    measurements = space.measurements
    own = group.content
    if not group.expanded:
        if own is not None:
            return Block(group.id, measurements.sizes[own.id], (Placement(own.id, 0, 0),))
        size = Size(380, 184)
        return Block(group.id, size, (Placement(group.id, 0, 0),), (ContextBounds(group.id, Box(0, 0, size.width, size.height)),))
    cards = tuple(Block(item.id, measurements.sizes[item.id], (Placement(item.id, 0, 0),)) for item in group.items)
    children = tuple(arranged_group(child, space) for child in group.children)
    widest = max((block.size.width for block in (*children, *cards)), default=332)
    if own is not None:
        widest = max(widest, measurements.sizes[own.id].width)
    width = min(measurements.width - 48, widest * 2 + 48) if children or len(cards) >= 5 else widest
    header = measurements.sizes[own.id].height + 32 if own is not None else 172
    anchor = space.saved.get(group.id, Placement(group.id, 0, 0))
    blocks = (*children, *cards)
    pinned = tuple(
        shifted(
            block, Placement(block.identity, max(24, space.saved[block.identity].x - anchor.x), max(header, space.saved[block.identity].y - anchor.y))
        )
        for block in blocks
        if block.identity in space.pinned and block.identity in space.saved
    )
    occupied = tuple(Box(block.placements[0].x, block.placements[0].y, block.size.width, block.size.height) for block in pinned)
    nested = pinned
    for block in shelf((block for block in blocks if block.identity not in space.pinned or block.identity not in space.saved), max(widest, width)):
        candidate = Placement(block.identity, block.placements[0].x + 24, block.placements[0].y + header)
        position = clear_obstacles(candidate, block.size, occupied)
        placed = shifted(block, Placement(block.identity, position.x - block.placements[0].x, position.y - block.placements[0].y))
        nested = (*nested, placed)
        occupied = (*occupied, Box(placed.placements[0].x, placed.placements[0].y, placed.size.width, placed.size.height))
    body_width = max((block.placements[0].x + block.size.width for block in nested), default=356)
    body_height = max((block.placements[0].y + block.size.height for block in nested), default=header + 42)
    size = Size(max(body_width + 24, widest + 48), body_height + 24)
    frames = (ContextBounds(group.id, Box(0, 0, size.width, size.height)), *(frame for block in nested for frame in block.frames))
    anchor = Placement(group.id, 0, 0)
    return Block(group.id, size, (anchor, *(p for block in nested for p in block.placements)), frames)


def clear_obstacles(position: Placement, size: Size, occupied: tuple[Box, ...]) -> Placement:
    while True:
        bounds = Box(position.x, position.y, size.width, size.height)
        bottom = max((other.y + other.height + 48 for other in occupied if bounds.overlaps(other)), default=None)
        if bottom is None:
            return position
        position = replace(position, y=bottom)


def layout(scene: CanvasScene, state: CanvasViewState, measurements: Measurements) -> Arrangement:
    groups = tuple(group for root in scene.groups for group in descendants(root))
    known_cards = frozenset(item.id for group in groups for item in group.pieces) | frozenset(item.id for item in scene.items)
    identities = known_cards | frozenset(group.id for group in groups)
    pinned = state.pinned & identities
    saved = frozendict((p.id, p) for p in state.placements)
    space = LayoutSpace(measurements, saved, pinned)
    blocks: tuple[Block, ...] = (
        *(arranged_group(group, space) for group in scene.groups),
        *(Block(item.id, measurements.sizes[item.id], (Placement(item.id, 0, 0),)) for item in scene.items),
    )
    frames: tuple[ContextBounds, ...] = ()
    positions: tuple[Placement, ...] = ()
    # A pin also anchors its owning frames; otherwise reflow would change the
    # parent origin and invalidate the child's saved absolute coordinates.
    anchored = pinned | frozenset(
        group.id for group in groups if any(child.id in pinned or any(item.id in pinned for item in child.pieces) for child in descendants(group))
    )
    root_boxes = tuple(
        Box(saved[block.identity].x, saved[block.identity].y, block.size.width, block.size.height)
        for block in blocks
        if block.identity in anchored and block.identity in saved
    )
    x, y, bottom = 0.0, 64.0, 64.0

    def block_width(block: Block) -> float:
        return block.size.width

    for block in sorted(blocks, key=block_width, reverse=True):
        if x and x + block.size.width > measurements.width:
            x, y = 0.0, bottom + 64
        anchor = saved.get(block.identity, Placement(block.identity, x, y))
        if block.identity not in anchored:
            anchor = clear_obstacles(anchor, block.size, root_boxes)
        placed = shifted(block, anchor)
        positions = (*positions, *placed.placements)
        frames = (*frames, *placed.frames)
        height = block.size.height
        root_boxes = (*root_boxes, Box(anchor.x, anchor.y, block.size.width, height))
        bottom = max(bottom, anchor.y + height)
        x += block.size.width + 64
    visible = frozenset(position.id for position in positions)
    hidden = tuple(position for position in state.placements if position.id in identities and position.id not in visible)
    return Arrangement(replace(state, placements=(*positions, *hidden), pinned=pinned), frames)
