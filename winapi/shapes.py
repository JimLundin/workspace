"""Plain value types the bindings return. No ctypes: importable anywhere."""

from dataclasses import dataclass, field
from typing import overload


@dataclass(frozen=True, slots=True)
class Offset:
    """How far one screen position lies from another, in physical pixels."""

    dx: int
    dy: int

    def __neg__(self) -> Offset:
        return Offset(-self.dx, -self.dy)


@dataclass(frozen=True, slots=True)
class Point:
    """A screen position in physical pixels; negative left of or above the primary monitor."""

    x: int
    y: int

    def __add__(self, offset: Offset) -> Point:
        return Point(self.x + offset.dx, self.y + offset.dy)

    @overload
    def __sub__(self, other: Point) -> Offset: ...
    @overload
    def __sub__(self, other: Offset) -> Point: ...
    def __sub__(self, other: Point | Offset) -> Offset | Point:
        match other:
            case Point(x=x, y=y):
                return Offset(self.x - x, self.y - y)
            case Offset(dx=dx, dy=dy):
                return Point(self.x - dx, self.y - dy)


@dataclass(frozen=True, slots=True)
class Size:
    """A width and height in physical pixels, neither negative."""

    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width < 0 or self.height < 0:
            raise ValueError(f"A size cannot be negative: {self.width} x {self.height}.")


@dataclass(frozen=True, slots=True)
class Rect:
    """A screen rectangle in physical pixels; `right` and `bottom` are exclusive."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def size(self) -> Size:
        return Size(self.width, self.height)

    def __contains__(self, point: Point) -> bool:
        return self.left <= point.x < self.right and self.top <= point.y < self.bottom


@dataclass(frozen=True, slots=True)
class Stop:
    offset: float
    color: str
    opacity: float


@dataclass(frozen=True, slots=True, kw_only=True)
class Lighting:
    """How light falls on every pane of a glass scene."""

    shadow_blur: float
    shadow_drop: float
    """The shadow's blur and how far it falls below the pane, in DIPs."""
    shadow_color: str
    rim_stroke: float
    """Twice the visible rim: half of the stroke lies outside the pane's clip."""
    rim_angle: float
    """The rim gradient's direction in CSS degrees (0 up, 90 right), brightest where it starts."""


@dataclass(frozen=True, slots=True)
class Veil:
    """How a pane's glass reads: its tint over the blurred desktop, its rim light and its shadow."""

    tint: str
    opacity: float
    rim: tuple[Stop, ...]
    shadow: float


@dataclass(frozen=True, slots=True)
class Pane:
    """One rounded pane, in device pixels within its scene; the radius is capped at half the height."""

    key: str
    bounds: Rect
    radius: float
    opacity: float
    veil: Veil


@dataclass(frozen=True, slots=True)
class Window:
    """A top-level window, as the taskbar would show it."""

    handle: int
    title: str
    exe: str
    """The program's file name, lowercase: `windowsterminal.exe`."""
    minimized: bool = field(kw_only=True)


def utf16_units(text: str) -> list[int]:
    """Windows types text as UTF-16 code units: two for characters past U+FFFF."""
    data = text.encode("utf-16-le")
    return [int.from_bytes(data[i : i + 2], "little") for i in range(0, len(data), 2)]


class InputRejectedError(OSError):
    """Windows accepted only part of an input batch; retrying could duplicate it."""

    def __init__(self, accepted: int, expected: int) -> None:
        self.accepted = accepted
        self.expected = expected
        super().__init__(f"Windows accepted {accepted} of {expected} input events. Switch the layout off with § in elevated applications.")


def require_input_count(sent: int, expected: int) -> None:
    """Reject partial input rather than silently losing keystrokes or clicks."""
    if sent != expected:
        raise InputRejectedError(sent, expected)
