"""What each physical key does on each layer, built from `keyboard.settings` and
checked once, when the module is imported: a key used twice fails the import, so a
broken layout never starts.
"""

from enum import Enum, auto
from typing import Final

from keyboard import settings
from keyboard.actions import Binding, Layer, TapHold
from keyboard.board import Board, Hand
from keyboard.keys import Mod
from keyboard.physical import Scancode


class LayoutError(Exception):
    """The layout is inconsistent; raised at import, never at runtime."""


_TABLE: Final[frozendict[Layer, tuple[Binding, ...]]] = frozendict((layer, layer.board.cells()) for layer in settings.Layers)
"""Every layer flattened, by layer then cell."""


def layer_of(board: Board[Binding]) -> Layer:
    """The layer whose board a hold names. Every hold is checked at import, so this always finds one."""
    return next(each for each in settings.Layers if each.board is board)


def held(hold: Mod | Board[Binding]) -> Mod | Layer:
    """What a tap-hold key holds: its modifier, or the layer its board belongs to."""
    return hold if isinstance(hold, Mod) else layer_of(hold)


def _check_holds() -> None:
    boards = tuple(each.board for each in settings.Layers)
    for each in settings.Layers:
        for cell, bound in enumerate(_TABLE[each]):
            match bound:
                case TapHold(hold=Board() as board) if not any(board is known for known in boards):
                    raise LayoutError(f"{each.name} cell {cell} holds a board that is no member of settings.Layers")
                case _:
                    pass


_check_holds()


_HANDS: Final = tuple(side for side, _ in settings.PHYSICAL.placed())
"""Each cell's hand: the half of `settings.PHYSICAL` its key is written in."""


def hand(cell: int) -> Hand:
    """The hand that presses key `cell`."""
    return _HANDS[cell]


def action(layer: Layer, cell: int) -> Binding:
    """What key `cell` does on `layer`."""
    return _TABLE[layer][cell]


def actions(layer: Layer) -> tuple[Binding, ...]:
    """What every key does on `layer`, by cell."""
    return _TABLE[layer]


class Unmapped(Enum):
    FREE = auto()
    """An explicitly permitted native function key."""
    BLOCKED = auto()
    """No binding: swallowed, does nothing."""


def _build_slots() -> frozendict[Scancode, int | Unmapped]:
    entries: tuple[tuple[Scancode, int | Unmapped], ...] = (
        *((key.scancode, cell) for cell, key in enumerate(settings.PHYSICAL.cells())),
        *((key.scancode, Unmapped.BLOCKED) for key in settings.UNUSED),
        *((key.scancode, Unmapped.FREE) for key in settings.FUNCTION_KEYS),
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


_SLOTS: Final = _build_slots()
"""Scancode -> a binding or explicitly permitted function key. Everything else is blocked."""


def slot(scancode: Scancode) -> int | Unmapped:
    return _SLOTS.get(scancode, Unmapped.BLOCKED)


def pictured(scancode: Scancode) -> bool:
    """A key the overlay shows: a layout key, or a blocked one (which lights to say so)."""
    return _SLOTS.get(scancode, Unmapped.FREE) is not Unmapped.FREE
