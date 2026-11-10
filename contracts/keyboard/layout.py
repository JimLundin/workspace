"""The shape of a keyboard layout: which physical keys it owns, what each does on
each layer, and its timings. Declares no layout itself; `keyboard.__main__`
builds one and hands it in, and tests build their own.
"""

from dataclasses import dataclass

from contracts.keyboard.actions import Binding, Layer
from contracts.keyboard.board import Board
from contracts.keyboard.physical import Laptop, Scancode


class LayoutError(Exception):
    """The layout is inconsistent; raised when it is built, so a broken layout never starts."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Timings:
    """How long, in milliseconds, decides what a held key means."""

    tapping_term: int
    """Hold a tap-hold key longer than this and it becomes its modifier or layer."""
    streak: int
    """Typing streak: a home row mod pressed this soon after a typed character is a plain letter, sent on press."""
    quick_tap: int
    """Quick tap: tap a tap-hold key, then press it again within this long, and it is that key held down (so it repeats)."""
    quit_hold: int
    """Hold the escape key this long to quit."""


@dataclass(frozen=True, slots=True)
class UsbIdentity:
    """A USB device's vendor and product numbers."""

    vendor: int
    product: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Layout:
    """A whole layout: its physical keys, its layers and its timings."""

    physical: Board[Laptop]
    """The laptop keys the layout is written on, cell by cell."""
    unused: frozenset[Laptop]
    """Keys between and below the hands: blocked while the layout is on."""
    function_keys: frozenset[Laptop]
    """Physical keys that stay native while the layout is on."""
    native_keys: frozenset[int]
    """Virtual keys that stay native whichever physical key sends them."""
    layers: frozendict[Layer, Board[Binding]]
    """Every layer's board; a hold names another layer, never BASE."""
    escape: Scancode
    """Tap to switch the layout on or off; hold for `timings.quit_hold` to quit."""
    apps_key: int
    """The virtual key the firmware keyboard's Apps thumb sends."""
    firmware: UsbIdentity
    """The firmware keyboard, which suspends the layout while it is connected."""
    timings: Timings
