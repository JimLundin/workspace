"""Immutable vector contours shared by Qt foregrounds and native composition masks."""

from dataclasses import dataclass
from enum import Enum, auto


@dataclass(frozen=True, slots=True)
class Move:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class Line:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class Curve:
    ax: float
    ay: float
    bx: float
    by: float
    x: float
    y: float


class End(Enum):
    CLOSE = auto()


type Contour = tuple[Move | Line | Curve | End, ...]
