"""The laptop's physical keys: the scancode each sends and the Nordic keycap
printed on it. The layout places them in `keyboard.settings.PHYSICAL`."""

from dataclasses import dataclass
from enum import Enum
from typing import NewType

Scancode = NewType("Scancode", int)
"""A hardware scancode identifying a physical key."""


@dataclass(frozen=True, slots=True)
class Keycap:
    """A physical key: the scancode it sends and the name printed on it."""

    scancode: int
    legend: str


class Laptop(Enum):
    """The laptop's physical keys that the layout or the key map use, by their Nordic keycaps."""

    SECTION = Keycap(0x29, "§")
    N1 = Keycap(0x02, "1")
    N2 = Keycap(0x03, "2")
    N3 = Keycap(0x04, "3")
    N4 = Keycap(0x05, "4")
    N5 = Keycap(0x06, "5")
    N6 = Keycap(0x07, "6")
    N7 = Keycap(0x08, "7")
    N8 = Keycap(0x09, "8")
    N9 = Keycap(0x0A, "9")
    N0 = Keycap(0x0B, "0")
    PLUS = Keycap(0x0C, "+")
    ACUTE = Keycap(0x0D, "\u00b4")

    Q = Keycap(0x10, "Q")
    W = Keycap(0x11, "W")
    E = Keycap(0x12, "E")
    R = Keycap(0x13, "R")
    T = Keycap(0x14, "T")
    Y = Keycap(0x15, "Y")
    U = Keycap(0x16, "U")
    I = Keycap(0x17, "I")  # noqa: E741 - the key is the letter
    O = Keycap(0x18, "O")  # noqa: E741 - the key is the letter
    P = Keycap(0x19, "P")
    ARING = Keycap(0x1A, "Å")
    DIAERESIS = Keycap(0x1B, "¨")

    CAPS = Keycap(0x3A, "Caps")
    A = Keycap(0x1E, "A")
    S = Keycap(0x1F, "S")
    D = Keycap(0x20, "D")
    F = Keycap(0x21, "F")
    G = Keycap(0x22, "G")
    H = Keycap(0x23, "H")
    J = Keycap(0x24, "J")
    K = Keycap(0x25, "K")
    L = Keycap(0x26, "L")
    OUMLAUT = Keycap(0x27, "Ö")
    AUMLAUT = Keycap(0x28, "Ä")
    APOSTROPHE = Keycap(0x2B, "'")

    LESS = Keycap(0x56, "<")
    Z = Keycap(0x2C, "Z")
    X = Keycap(0x2D, "X")
    C = Keycap(0x2E, "C")
    V = Keycap(0x2F, "V")
    B = Keycap(0x30, "B")
    N = Keycap(0x31, "N")
    M = Keycap(0x32, "M")
    COMMA = Keycap(0x33, ",")
    PERIOD = Keycap(0x34, ".")
    MINUS = Keycap(0x35, "-")

    SPACE = Keycap(0x39, "Space")

    F1 = Keycap(0x3B, "F1")
    F2 = Keycap(0x3C, "F2")
    F3 = Keycap(0x3D, "F3")
    F4 = Keycap(0x3E, "F4")
    F5 = Keycap(0x3F, "F5")
    F6 = Keycap(0x40, "F6")
    F7 = Keycap(0x41, "F7")
    F8 = Keycap(0x42, "F8")
    F9 = Keycap(0x43, "F9")
    F10 = Keycap(0x44, "F10")
    F11 = Keycap(0x57, "F11")
    F12 = Keycap(0x58, "F12")

    @property
    def scancode(self) -> Scancode:
        return Scancode(self.value.scancode)

    @property
    def legend(self) -> str:
        return self.value.legend
