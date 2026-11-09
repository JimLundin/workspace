"""What each physical key does on each layer, built from `keyboard.settings` and
checked once, when the module is imported: a key used twice fails the import, so a
broken layout never starts.
"""

from enum import Enum, auto
from typing import Final

from keyboard import settings
from keyboard.layout import Binding, Layer, Scancode


class LayoutError(Exception):
    """The layout is inconsistent; raised at import, never at runtime."""


_TABLE: Final[frozendict[Layer | None, tuple[Binding, ...]]] = frozendict(
    (layer, board.cells()) for layer, board in ((None, settings.BASE), *settings.LAYERS.items())
)
"""Every layer flattened, by layer (None: the base layer) then cell."""


def action(layer: Layer | None, cell: int) -> Binding:
    """What key `cell` does on `layer`."""
    return _TABLE[layer][cell]


def actions(layer: Layer | None) -> tuple[Binding, ...]:
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
