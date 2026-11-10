"""The shape layers are written in: three rows and the thumbs, each split into
the left and right hand's halves, so every layer lines up with the physical keys."""

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum, auto
from typing import ClassVar


class Hand(Enum):
    """The hand a key is written under: the left or right half of a row."""

    LEFT = auto()
    RIGHT = auto()


@dataclass(frozen=True, slots=True)
class Row[CellT]:
    """One row across the keyboard: five keys for the left hand, five for the right."""

    left: tuple[CellT, CellT, CellT, CellT, CellT]
    right: tuple[CellT, CellT, CellT, CellT, CellT]


@dataclass(frozen=True, slots=True)
class Thumbs[CellT]:
    """The thumb keys: three per hand."""

    left: tuple[CellT, CellT, CellT]
    right: tuple[CellT, CellT, CellT]


@dataclass(frozen=True, slots=True)
class Board[CellT]:
    """The whole board, written the way it looks. Used for the physical keys
    (`Board[Laptop]`) and for every layer (`Board[Binding]`), so they line up."""

    SIZE: ClassVar = 36
    """Keys on the board: three rows of ten, plus six thumb keys."""

    top: Row[CellT]
    home: Row[CellT]
    bottom: Row[CellT]
    thumbs: Thumbs[CellT]

    def placed(self) -> Iterator[tuple[Hand, CellT]]:
        """All 36 keys in order, each with the half of the board it is written in:
        rows top to bottom, left to right, then thumbs."""
        for half in (self.top, self.home, self.bottom, self.thumbs):
            yield from ((Hand.LEFT, key) for key in half.left)
            yield from ((Hand.RIGHT, key) for key in half.right)

    def cells(self) -> tuple[CellT, ...]:
        """All 36 keys in `placed` order; a key's place in it is its cell."""
        return tuple(key for _, key in self.placed())
