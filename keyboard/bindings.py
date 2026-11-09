"""What each physical key does on each layer, built from `keyboard.settings` and
checked once, when the module is imported: a key used twice fails the import, so a
broken layout never starts.
"""

from enum import Enum, auto
from typing import Final

from keyboard import settings
from keyboard.layout import Action, Layer, Scancode


class LayoutError(Exception):
    """The layout is inconsistent; raised at import, never at runtime."""


_TABLE: Final[frozendict[Layer | None, tuple[Action, ...]]] = frozendict({
    None: settings.BASE.cells(),
    Layer.NAV: settings.NAV_LAYER.cells(),
    Layer.NUM: settings.NUM_LAYER.cells(),
    Layer.SYM: settings.SYM_LAYER.cells(),
    Layer.APPS: settings.APPS_LAYER.cells(),
})  # fmt: skip
"""Every layer flattened, by layer (None: the base layer) then cell."""


def action(layer: Layer | None, cell: int) -> Action:
    """What key `cell` does on `layer`."""
    return _TABLE[layer][cell]


def actions(layer: Layer | None) -> tuple[Action, ...]:
    """What every key does on `layer`, by cell."""
    return _TABLE[layer]


class Unmapped(Enum):
    FREE = auto()
    """An explicitly permitted native function key."""
    BLOCKED = auto()
    """No binding: swallowed, does nothing."""


def _build_slots() -> frozendict[Scancode, int | Unmapped]:
    entries: tuple[tuple[Scancode, int | Unmapped], ...] = (
        *((scancode, cell) for cell, scancode in enumerate(settings.PHYSICAL.cells())),
        *((scancode, Unmapped.BLOCKED) for scancode in settings.UNUSED),
        *((scancode, Unmapped.FREE) for scancode in settings.FUNCTION_KEYS),
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


def native_control(vk: int) -> bool:
    """Function and media keys, arrows, and the physical Shift, Ctrl and Windows keys stay native."""
    return 0x70 <= vk <= 0x87 or 0xAD <= vk <= 0xB3 or 0x25 <= vk <= 0x28 or vk in (0x10, 0x11, 0xA0, 0xA1, 0xA2, 0xA3, 0x5B, 0x5C)
