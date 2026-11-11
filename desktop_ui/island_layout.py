"""Where the island bar's capsules sit: a pure frame from measured sizes and presence.

Permanent controls anchor right, and activity sits directly left of them.
Lead capsules sit left of the island and trail capsules right of it.
The gap between two neighbours belongs to the pair: the full gap scaled by
the less present of the two, so a capsule entering or leaving
opens and closes the space beside it smoothly. Each capsule's widget also spans the
strip from the top of the screen down to its glass, so a pointer thrown against the
edge still lands on it.
"""

from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from functools import reduce
from itertools import chain, groupby
from operator import add
from typing import assert_never

from desktop_ui.components.typeface import Font
from desktop_ui.island_menu import COLUMNS, Cell, Menu
from desktop_ui.island_model import Charge, Control, Glyph, Key, Marker, Part, Slot, Text, Zone
from winapi.shapes import Rect

# ---- the bar's sizes, in device-independent pixels (DIPs) -----------------------------
# Every size the bar lays out and paints is here, so a change applies everywhere it is used.


@dataclass(frozen=True, slots=True)
class Bar:
    top: float
    """From the screen's top edge to the capsules."""
    edge: float
    """From the screen's right edge to the right capsule."""
    gap: float
    """Between neighbouring capsules."""
    radius: float
    shadow: float
    """Room below and beside the capsules for their shadow."""
    pager_gap: float
    """From the pager to the leftmost capsule; the pager starts `edge` from the screen's left edge."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Capsule:
    height: float
    control: float
    """A concentric control: (height - control) / 2 from the capsule's edge."""
    icon: float
    dot: float
    """The recording dot."""
    dots: float
    """Transcription's three dots."""
    wave_bars: int
    wave_bar: float
    """One bar of the microphone trace..."""
    wave_gap: float
    """...and the space between two."""
    part_gap: float
    """Between the parts of one fact, such as a symbol and its reading."""
    slot_gap: float
    """Between separate facts."""
    text_pad: float
    """A capsule's ends when it holds text..."""
    icon_pad: float
    """...and when it holds only symbols."""
    ring_inset: float
    """The keyboard focus ring, inside the capsule's edge."""
    app_icon: float
    """An app's icon in the pager..."""
    app_gap: float
    """...and the gap between a desktop's icons."""
    current_dot: float
    """The radius of the dot under the current desktop."""

    @property
    def inset(self) -> float:
        """A control at either end sits concentric with the capsule."""
        return (self.height - self.control) / 2

    @property
    def wave(self) -> float:
        """The microphone trace: its bars and the gaps between them."""
        return self.wave_bars * (self.wave_bar + self.wave_gap) - self.wave_gap


@dataclass(frozen=True, slots=True, kw_only=True)
class MenuGrid:
    """The controls menu: a grid of tiles below the capsule's own row."""

    width: float
    radius: float
    pad: float
    head: float
    """The capsule's own row, above the grid."""
    track: float
    """One grid row; a tile spans whole tracks."""
    gutter: float
    """Between tiles; each tile keeps half on every side."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Markers:
    """How the live indicators draw inside the room `Capsule` gives them."""

    wave_floor: float
    """A silent bar's height..."""
    wave_reach: float
    """...and how much taller the loudest grows."""
    wave_corner: float
    halo: float
    """The radius of the glow around the recording dot."""
    dot_count: int
    """Transcription's dots, spread evenly across their room."""
    dots_radius: float
    dots_lift: float
    """How far a pulsing dot rises."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Cells:
    """The inside of the controls menu's tiles, from the tile's own edges."""

    corner: float
    lead: float
    """A row's symbol or label from the tile's leading edge."""
    trail: float
    """A shortcut key from the trailing edge."""
    symbol_x: float
    """A toggle's symbol circle, which is a control's size."""
    text_x: float
    """Where a toggle's text and the slider's bar start, past the symbol."""
    text_right: float
    """A toggle's text from the trailing edge."""
    label_x: float
    """Where a row's label starts, past its symbol."""
    label_right: float
    tool_top: float
    """A tool's symbol from the tile's top..."""
    caption_side: float
    caption_bottom: float
    """...and its caption from the sides and bottom."""
    slider_label_top: float
    slider_label: float
    """The slider label's line height."""
    track_bottom: float
    """The slider's bar from the tile's bottom..."""
    track_right: float
    track: float
    """...its thickness..."""
    track_corner: float
    knob: float
    """...and its knob's radius."""
    live_dot_x: float
    """An activity card's dot centre..."""
    live_dot: float
    """...and radius."""
    live_text_x: float
    live_text_right: float
    live_elide: float
    """The detail line's width, short of the tile's own."""
    stop_right: float
    """The card's Stop circle from the trailing edge."""
    tray_image: float
    """The largest a tray application's image draws, in DIPs: Windows' small-icon size."""
    month_head: float
    """The calendar's heading row, with its arrows..."""
    month_arrow: float
    """...each this wide..."""
    weekdays: float
    """...then the weekdays' row; the six weeks share what remains."""
    month_side: float
    """The days' columns from the tile's sides."""
    today: float
    """The radius of today's disc."""
    graph_head: float
    """A graph's name and reading above it..."""
    graph_line: float
    """...and its line's width."""
    signal_bar: float
    """A network's signal bar's width; four span a symbol."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Gauge:
    """The battery symbol: a rounded body with a nub on its right, filled to the charge."""

    width: float
    """The body and its nub."""
    height: float
    corner: float
    stroke: float
    """The body's outline."""
    inset: float
    """Between the outline and the fill."""
    nub: float
    """The nub's width..."""
    nub_height: float
    """...and height."""
    bolt: float
    """The charging bolt's height; its width follows."""
    knockout: float
    """The clear edge around the bolt, so it reads over the fill."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BarType:
    """The bar's text: readings, a leading reading, and quieter detail."""

    reading: Font
    strong: Font
    detail: Font


@dataclass(frozen=True, slots=True, kw_only=True)
class Sizes:
    """Every size the island bar lays out and paints."""

    bar: Bar
    capsule: Capsule
    menu: MenuGrid
    markers: Markers
    gauge: Gauge
    cells: Cells
    type: BarType


@dataclass(frozen=True, slots=True)
class Spot:
    """A part's horizontal place inside its capsule, and the slot it belongs to."""

    part: Part
    x: float
    width: float
    slot: int


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


def tiles(menu: Menu, grid: MenuGrid) -> tuple[Tile, ...]:
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


def expansion(menu: Menu, row: Content, grid: MenuGrid) -> Content:
    """A capsule expanded into the menu: its own row on top, right-aligned so it stays put as the capsule widens."""
    # A tile's gutters cancel at the grid's last track.
    tracks = max((cell.track + cell.tracks for cell in menu.cells), default=0)
    bottom = grid.pad + grid.head + tracks * grid.track
    width = max(float(grid.width), row.width)
    spots = tuple(replace(spot, x=spot.x + width - row.width) for spot in row.spots)
    return Content(width, spots, bottom + grid.pad)


def extent(part: Part, measure: Callable[[Text], float], sizes: Sizes) -> float:
    capsule = sizes.capsule
    match part:
        case Text(tone=tone, reserve=reserve):
            return max(measure(part), measure(Text(reserve, tone))) if reserve else measure(part)
        case Glyph():
            return capsule.icon
        case Charge():
            return sizes.gauge.width
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
    slot: int


def _steps(slots: Sequence[Slot], measure: Callable[[Text], float], sizes: Sizes) -> Iterator[_Step]:
    capsule = sizes.capsule
    for index, slot in enumerate(slots):
        for position, part in enumerate(slot):
            width = extent(part, measure, sizes)
            if not position:
                yield _Step(part, capsule.slot_gap if index else 0.0, width, index)
            elif width:
                # Two readings side by side keep the space of separate facts.
                gap = capsule.slot_gap if textual(part) and textual(slot[position - 1]) else capsule.part_gap
                yield _Step(part, gap, width, index)
            else:
                yield _Step(part, 0.0, width, index)


def _placed(steps: Iterable[_Step], start: float) -> Iterator[Spot]:
    """Each part where it lands: after its gap, then the row moves on by its width."""
    x = start
    for step in steps:
        x += step.gap
        yield Spot(step.part, x, step.width, step.slot)
        x += step.width


def arrange(slots: Sequence[Slot], measure: Callable[[Text], float], sizes: Sizes) -> Content:
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

    steps = tuple(_steps(slots, measure, sizes))
    start = edge(parts[0]) if parts else pad
    spots = tuple(_placed(steps, start))
    # Added left to right like the placement, so the end matches the last part exactly.
    x = reduce(add, chain.from_iterable((step.gap, step.width) for step in steps), start)
    end = x + (edge(parts[-1]) if parts else pad)
    width = max(float(capsule.height), end)
    shift = (width - end) / 2
    return Content(width, tuple(replace(spot, x=spot.x + shift) for spot in spots), capsule.height)


@dataclass(frozen=True, slots=True)
class Plotted:
    """A sample's place in a graph, inside its tile."""

    x: float
    y: float


def _read(sample: tuple[int, float | None]) -> bool:
    _, share = sample
    return share is not None


def plotted(shares: Sequence[float | None], capacity: int, box: Box) -> Iterator[tuple[Plotted, ...]]:
    """The samples' runs as lines across `box`: the newest at its right edge, each earlier one a
    step left, a share of 0 on its bottom and 1 on its top. An unread sample breaks the line."""
    step = box.width / max(1, capacity - 1)
    start = capacity - len(shares)

    def at(index: int, share: float) -> Plotted:
        return Plotted(box.x + (start + index) * step, box.y + box.height * (1 - share))

    for read, run in groupby(enumerate(shares), key=_read):
        if read:
            yield tuple(at(index, share) for index, share in run if share is not None)


def reading_at(content: Content, x: float) -> int | None:
    """The slot under `x` in `content`'s row: the one whose parts are nearest, so the
    gap between two readings splits halfway and the ends belong to the outer readings."""

    def distance(spot: Spot) -> float:
        return max(spot.x - x, x - spot.x - spot.width, 0.0)

    return min(content.spots, key=distance).slot if content.spots else None


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

    def on_device(self, scale: float) -> Rect:
        """The box in device pixels, each edge rounded on its own."""
        return Rect(round(self.x * scale), round(self.y * scale), round((self.x + self.width) * scale), round((self.y + self.height) * scale))

    def on_screen(self, outer: Rect, scale: float) -> Rect:
        """A window-relative box on screen in device pixels: its corner rounds from the window's, its extent from its size."""
        left, top = outer.left + round(self.x * scale), outer.top + round(self.y * scale)
        return Rect(left, top, left + round(self.width * scale), top + round(self.height * scale))


def on_pixels(value: float, scale: float) -> float:
    """A logical coordinate moved to the nearest whole device pixel at `scale`."""
    return round(value * scale) / scale


@dataclass(frozen=True, slots=True)
class Framed:
    key: Key
    box: Box
    presence: float


@dataclass(frozen=True, slots=True)
class Metrics:
    """The screen's width and the bar's own spacing (`Bar`)."""

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
        return Framed(capsule.key, box, present(capsule.presence))

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

    def outward(capsules: tuple[Placed, ...], edge: float, before: float, *, leading: bool) -> tuple[Framed, ...]:
        framed: tuple[Framed, ...] = ()
        for capsule in capsules:
            space = metrics.gap * min(before, present(capsule.presence))
            x = edge - space - shown(capsule) if leading else edge + space
            framed = (boxed(capsule, x), *framed) if leading else (*framed, boxed(capsule, x))
            edge = x if leading else x + shown(capsule)
            before = present(capsule.presence)
        return framed

    match zone(Zone.ISLAND):
        case (island, *_):
            presence = present(island.presence)
            lead = outward(tuple(reversed(zone(Zone.LEAD))), 0.0, presence, leading=True)
            trail = outward(zone(Zone.TRAIL), shown(island), presence, leading=False)
            dynamic = (*lead, boxed(island, 0.0), *trail)
        case _:
            dynamic = outward(zone(Zone.TRAIL), 0.0, 0.0, leading=False)
    if not dynamic:
        return right
    start = min(each.box.x for each in dynamic)
    end = max(each.box.x + each.box.width for each in dynamic)
    # Activity ends one gap before the right capsule; if it cannot fit, its start stays on screen.
    shift = max(-start, boundary - end)

    def bounded(each: Framed) -> Framed:
        x = max(0.0, each.box.x + shift)
        width = max(0.0, min(each.box.width, boundary - x))
        return Framed(each.key, Box(x, each.box.y, width, each.box.height), each.presence)

    return (*(bounded(each) for each in dynamic if each.box.x + shift < boundary), *right)


def snap(framed: Sequence[Framed], scale: float) -> tuple[Framed, ...]:
    """Round every box to whole device pixels, so Qt and composition draw the same edges."""

    def device(box: Box) -> Box:
        x, y = on_pixels(box.x, scale), on_pixels(box.y, scale)
        return Box(x, y, on_pixels(box.x + box.width, scale) - x, on_pixels(box.y + box.height, scale) - y)

    return tuple(Framed(f.key, device(f.box), f.presence) for f in framed)
