from dataclasses import dataclass
from enum import Enum, auto
from typing import ClassVar

from keyboard.keys import Key, Mod
from protocol import Slot, Tool


class Layer(Enum):
    BASE = auto()
    NAV = auto()
    NUM = auto()
    SYM = auto()
    APPS = auto()

    @property
    def code(self) -> int:
        return tuple(Layer).index(self)

    @classmethod
    def coded(cls, code: int) -> Layer | None:
        layers = tuple(cls)
        return layers[code] if 0 <= code < len(layers) else None


type Hold = Mod | Layer
"""What a tap-hold key does while held: hold a modifier, or turn on a layer."""


@dataclass(frozen=True, slots=True)
class Chord:
    _SHIFT: ClassVar = frozenset({Mod.SHIFT})
    _CTRL: ClassVar = frozenset({Mod.CTRL})

    key: Key
    mods: frozenset[Mod]

    @classmethod
    def shifted(cls, key: Key) -> Chord:
        return cls(key, cls._SHIFT)

    @classmethod
    def ctrl(cls, key: Key) -> Chord:
        return cls(key, cls._CTRL)

    @property
    def only_shifted(self) -> bool:
        return self.mods == self._SHIFT

    @property
    def types(self) -> bool:
        return self.mods <= self._SHIFT


type Output = Key | Chord
"""What reaches Windows when a key is tapped. A bare Key is a chord without modifiers."""


@dataclass(frozen=True, slots=True)
class TapHold:
    tap: Output
    hold: Hold


type Action = Output | Mod | Layer | TapHold | Tool | Slot
"""What one key on one layer does. A Key or Chord is sent; a Mod or Layer is held
while the key is held; a Tool or Slot is a request to the desktop (see `protocol`)."""

BLANK = sentinel("BLANK")
"""A key with no action on a layer: pressing it does nothing."""

type Binding = Action | BLANK
"""What a layer binds a key to: an action, or nothing."""
