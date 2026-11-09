"""What a key can do on a layer, and what a layer is. A bare Key, Mod or Layer is
itself an action: a Key is tapped, a Mod or Layer is held while the key is held.
Only the actions that need more than that get a type of their own. The layers
written in this vocabulary are `keyboard.settings.Layers`; `keyboard.bindings`
looks them up."""

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Self

from keyboard.board import Board
from keyboard.keys import Key, Mod
from protocol import App, Tool


class Layer(Enum):
    """A layer: a member whose value is its board. Declares no members, so
    `keyboard.settings.Layers` can: one per layer, the base layer among them."""

    _value_: Board[Binding]

    @property
    def board(self) -> Board[Binding]:
        return self.value

    @property
    def code(self) -> int:
        """The layer's place among its enum's members, as the indicator message sends it."""
        return tuple(type(self)).index(self)

    @classmethod
    def coded(cls, code: int) -> Self | None:
        """The layer the indicator message names, or None for a code no layer has."""
        layers = tuple(cls)
        return layers[code] if 0 <= code < len(layers) else None


type Hold = Mod | Board[Binding]
"""What a tap-hold key does while held: hold a modifier, or turn on the layer
whose board this is. A layer's board is how `keyboard.settings.Layers` names the
layers declared before it; `keyboard.bindings` finds the member."""


@dataclass(frozen=True, slots=True)
class Chord:
    """A key sent with modifiers held around it: Shift + 7 for `&`, Ctrl + Z for undo.
    Only modifiers that aren't already held are added, and only those are released."""

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
        """Shift and nothing else."""
        return self.mods == self._SHIFT

    @property
    def types(self) -> bool:
        """At most Shift: a typed character, not a shortcut."""
        return self.mods <= self._SHIFT


type Output = Key | Chord
"""What reaches Windows when a key is tapped. A bare Key is a chord without modifiers."""


@dataclass(frozen=True, slots=True)
class TapHold:
    """Tap = the output, hold = the `Hold`."""

    tap: Output
    hold: Hold


type Action = Output | Mod | Layer | TapHold | Tool | App
"""What one key on one layer does. A Key or Chord is sent; a Mod or Layer is held
while the key is held; a Tool or App is a request to the assistant (see `protocol`)."""

BLANK = sentinel("BLANK")
"""A key with no action on a layer: pressing it does nothing."""

type Binding = Action | BLANK
"""What a layer binds a key to: an action, or nothing."""
