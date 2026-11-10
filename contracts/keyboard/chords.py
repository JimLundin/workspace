"""Each Apps layer request by the base key at its place: the chord letters the desktop
draws and the shortcuts the Charybdis sends, from one layout's bindings."""

from dataclasses import dataclass

from contracts.keyboard.actions import Layer, TapHold
from contracts.keyboard.bindings import Bindings
from contracts.keyboard.board import Board
from contracts.keyboard.keys import Key
from contracts.keyboard.layout import LayoutError
from protocol import Request, Slot, Tool


def _base_key(bindings: Bindings, cell: int) -> Key | None:
    match bindings.action(Layer.BASE, cell):
        case Key() as key:
            return key
        case TapHold(tap=Key() as key):
            return key
        case _:
            return None


@dataclass(frozen=True, slots=True)
class Chords:
    """Each Apps layer request by the base key at its place: one map for both keyboards."""

    letters: frozendict[Request, str]
    """Each request's key under the Apps hold: the laptop's Apps layer, or the
    Charybdis's held Tab thumb, with the key its keymap sends there."""
    by_vk: frozendict[int, Request]
    """Each request by its key's virtual key, which both keyboards share."""

    @classmethod
    def of(cls, bindings: Bindings) -> Chords:
        """The layout's chords, or `LayoutError` if a request has no base key under it or two share one."""
        requests = tuple((cell, request) for cell in range(Board.SIZE) if isinstance(request := bindings.action(Layer.APPS, cell), Tool | Slot))
        chorded = tuple((key, request) for cell, request in requests if (key := _base_key(bindings, cell)))
        if len(chorded) != len(requests):
            raise LayoutError("an Apps layer request sits where the base layer has no key to chord")
        keys = frozendict(chorded)
        if len(keys) != len(chorded):
            repeated = next(key for index, (key, _) in enumerate(chorded) if key in frozendict(chorded[:index]))
            raise LayoutError(f"two Apps layer requests share the chord key {repeated.name}")
        return cls(frozendict({request: key.legend for key, request in keys.items()}), frozendict({key.vk: request for key, request in keys.items()}))

    def shortcut(self, vk: int, *, apps_held: bool) -> Request | None:
        """The request a fresh firmware key press makes while the Tab thumb holds Apps; other keys keep their meaning.

        Keys are matched by virtual key, so the host layout can't move them.
        """
        return self.by_vk.get(vk) if apps_held else None
