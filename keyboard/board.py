from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum, auto
from typing import ClassVar


class Hand(Enum):
    LEFT = auto()
    RIGHT = auto()


@dataclass(frozen=True, slots=True)
class Row[CellT]:
    left: tuple[CellT, CellT, CellT, CellT, CellT]
    right: tuple[CellT, CellT, CellT, CellT, CellT]


@dataclass(frozen=True, slots=True)
class Thumbs[CellT]:
    left: tuple[CellT, CellT, CellT]
    right: tuple[CellT, CellT, CellT]


@dataclass(frozen=True, slots=True)
class Board[CellT]:
    SIZE: ClassVar = 36
    """Keys on the board: three rows of ten, plus six thumb keys."""

    top: Row[CellT]
    home: Row[CellT]
    bottom: Row[CellT]
    thumbs: Thumbs[CellT]

    def placed(self) -> Iterator[tuple[Hand, CellT]]:
        for half in (self.top, self.home, self.bottom, self.thumbs):
            yield from ((Hand.LEFT, key) for key in half.left)
            yield from ((Hand.RIGHT, key) for key in half.right)

    def cells(self) -> tuple[CellT, ...]:
        return tuple(key for _, key in self.placed())
