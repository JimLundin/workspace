"""What each physical key does on each layer, built from a `contracts.keyboard.layout.Layout`
and checked as it is built: a key used twice, a layer without a board or a hold of
BASE raises `LayoutError`, so a broken layout never starts.
"""

from dataclasses import dataclass
from enum import Enum, auto

from contracts.keyboard.actions import Binding, Layer, TapHold
from contracts.keyboard.board import Hand
from contracts.keyboard.layout import Layout, LayoutError
from contracts.keyboard.physical import Scancode


class Unmapped(Enum):
    FREE = auto()
    """An explicitly permitted native function key."""
    BLOCKED = auto()
    """No binding: swallowed, does nothing."""


def _table(layout: Layout) -> frozendict[Layer, tuple[Binding, ...]]:
    if missing := tuple(layer.name for layer in Layer if layer not in layout.layers):
        raise LayoutError(f"the layout has no board for: {', '.join(missing)}")
    table = frozendict((layer, board.cells()) for layer, board in layout.layers.items())
    for layer, cells in table.items():
        for cell, bound in enumerate(cells):
            match bound:
                case TapHold(hold=Layer.BASE):
                    raise LayoutError(f"{layer.name} cell {cell} holds BASE, which is where keys are read while no layer is held")
                case _:
                    pass
    return table


def _slots(layout: Layout) -> frozendict[Scancode, int | Unmapped]:
    entries: tuple[tuple[Scancode, int | Unmapped], ...] = (
        *((key.scancode, cell) for cell, key in enumerate(layout.physical.cells())),
        *((key.scancode, Unmapped.BLOCKED) for key in layout.unused),
        *((key.scancode, Unmapped.FREE) for key in layout.function_keys),
    )
    slots = frozendict(entries)
    if len(slots) == len(entries):
        return slots
    # The first entry whose scancode an earlier one already took, named by what it was meant to be.
    first = frozendict((scancode, index) for index, (scancode, _) in reversed(tuple(enumerate(entries))))
    scancode, slot = next((scancode, slot) for index, (scancode, slot) in enumerate(entries) if first[scancode] != index)
    match slot:
        case int():
            raise LayoutError(f"physical key {scancode:#x} is used twice")
        case Unmapped.BLOCKED:
            raise LayoutError(f"blocked key {scancode:#x} is also in the layout")
        case Unmapped.FREE:
            raise LayoutError(f"function key {scancode:#x} is also in the layout")


@dataclass(frozen=True, slots=True)
class Bindings:
    """A layout's lookups: what each cell does on each layer, each cell's hand, and each scancode's cell."""

    table: frozendict[Layer, tuple[Binding, ...]]
    """Every layer flattened, by layer then cell."""
    hands: tuple[Hand, ...]
    """Each cell's hand: the half of the physical board its key is written in."""
    slots: frozendict[Scancode, int | Unmapped]
    """Scancode -> a cell or an explicitly permitted function key. Everything else is blocked."""

    @classmethod
    def of(cls, layout: Layout) -> Bindings:
        """`layout`'s lookups, or `LayoutError` if it is inconsistent."""
        return cls(_table(layout), tuple(side for side, _ in layout.physical.placed()), _slots(layout))

    def hand(self, cell: int) -> Hand:
        """The hand that presses key `cell`."""
        return self.hands[cell]

    def action(self, layer: Layer, cell: int) -> Binding:
        """What key `cell` does on `layer`."""
        return self.table[layer][cell]

    def actions(self, layer: Layer) -> tuple[Binding, ...]:
        """What every key does on `layer`, by cell."""
        return self.table[layer]

    def slot(self, scancode: Scancode) -> int | Unmapped:
        return self.slots.get(scancode, Unmapped.BLOCKED)

    def pictured(self, scancode: Scancode) -> bool:
        """A key the overlay shows: a layout key, or a blocked one (which lights to say so)."""
        return self.slots.get(scancode, Unmapped.FREE) is not Unmapped.FREE
