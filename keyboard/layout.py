"""The keyboard's vocabulary: the laptop's physical keys, the keys and modifiers
sent to Windows, layers, actions and the board's shape. The layout written in it is `keyboard.settings`; what each key does is
`keyboard.bindings`.

A bare Key, Mod or Layer in a layout is itself an action: a Key is tapped, a Mod
or Layer is held while the key is held. Only the actions that need more than that
get a type of their own. The vocabulary is Windows': each key carries its virtual
key code, whether Windows sends it as extended, and what it types on US English.
A physical key (`Laptop`) carries the scancode it sends and its Nordic keycap.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import ClassVar, NewType

from protocol import App, Tool

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


@dataclass(frozen=True, slots=True)
class KeyCode:
    """A key as Windows knows it: its virtual key code, what it types on the US English
    layout (plain and with Shift; None for keys that don't type), whether Windows
    sends it with the "extended" flag (an E0 prefix), and the name its keycap shows
    where that isn't the capital of what it types."""

    vk: int
    plain: str | None = None
    shifted: str | None = None
    extended: bool = field(default=False, kw_only=True)
    named: str | None = field(default=None, kw_only=True)


class VirtualKey(Enum):
    """A key Windows is sent, by its `KeyCode`. Members live on the `Key` and `Mod` subclasses."""

    _value_: KeyCode

    @property
    def vk(self) -> int:
        return self.value.vk

    @property
    def extended(self) -> bool:
        return self.value.extended

    @property
    def legend(self) -> str:
        """The key as its keycap, the hints and the README write it: its name, else the capital it types."""
        code = self.value
        return code.named or (code.plain.upper() if code.plain else self.name.title())


class Key(VirtualKey):
    """A Windows virtual key the layout sends."""

    A = KeyCode(0x41, "a", "A")
    B = KeyCode(0x42, "b", "B")
    C = KeyCode(0x43, "c", "C")
    D = KeyCode(0x44, "d", "D")
    E = KeyCode(0x45, "e", "E")
    F = KeyCode(0x46, "f", "F")
    G = KeyCode(0x47, "g", "G")
    H = KeyCode(0x48, "h", "H")
    I = KeyCode(0x49, "i", "I")  # noqa: E741 - the key is the letter I
    J = KeyCode(0x4A, "j", "J")
    K = KeyCode(0x4B, "k", "K")
    L = KeyCode(0x4C, "l", "L")
    M = KeyCode(0x4D, "m", "M")
    N = KeyCode(0x4E, "n", "N")
    O = KeyCode(0x4F, "o", "O")  # noqa: E741 - the key is the letter O
    P = KeyCode(0x50, "p", "P")
    Q = KeyCode(0x51, "q", "Q")
    R = KeyCode(0x52, "r", "R")
    S = KeyCode(0x53, "s", "S")
    T = KeyCode(0x54, "t", "T")
    U = KeyCode(0x55, "u", "U")
    V = KeyCode(0x56, "v", "V")
    W = KeyCode(0x57, "w", "W")
    X = KeyCode(0x58, "x", "X")
    Y = KeyCode(0x59, "y", "Y")
    Z = KeyCode(0x5A, "z", "Z")
    N0 = KeyCode(0x30, "0", ")")
    N1 = KeyCode(0x31, "1", "!")
    N2 = KeyCode(0x32, "2", "@")
    N3 = KeyCode(0x33, "3", "#")
    N4 = KeyCode(0x34, "4", "$")
    N5 = KeyCode(0x35, "5", "%")
    N6 = KeyCode(0x36, "6", "^")
    N7 = KeyCode(0x37, "7", "&")
    N8 = KeyCode(0x38, "8", "*")
    N9 = KeyCode(0x39, "9", "(")
    GRAVE = KeyCode(0xC0, "`", "~")
    MINUS = KeyCode(0xBD, "-", "_")
    EQUAL = KeyCode(0xBB, "=", "+")
    LBRACKET = KeyCode(0xDB, "[", "{")
    RBRACKET = KeyCode(0xDD, "]", "}")
    BACKSLASH = KeyCode(0xDC, "\\", "|")
    SEMICOLON = KeyCode(0xBA, ";", ":")
    QUOTE = KeyCode(0xDE, "'", '"')
    COMMA = KeyCode(0xBC, ",", "<")
    PERIOD = KeyCode(0xBE, ".", ">")
    SLASH = KeyCode(0xBF, "/", "?")
    SPACE = KeyCode(0x20, " ", " ", named="Space")
    ESC = KeyCode(0x1B, named="Esc")
    TAB = KeyCode(0x09, named="Tab")
    ENTER = KeyCode(0x0D, named="Enter")
    BACKSPACE = KeyCode(0x08, named="Bksp")
    CAPS_LOCK = KeyCode(0x14, named="Caps")
    DELETE = KeyCode(0x2E, extended=True, named="Del")
    INSERT = KeyCode(0x2D, extended=True, named="Ins")
    HOME = KeyCode(0x24, extended=True, named="Home")
    END = KeyCode(0x23, extended=True, named="End")
    PAGE_UP = KeyCode(0x21, extended=True, named="PgUp")
    PAGE_DOWN = KeyCode(0x22, extended=True, named="PgDn")
    LEFT = KeyCode(0x25, extended=True, named="←")
    UP = KeyCode(0x26, extended=True, named="↑")
    RIGHT = KeyCode(0x27, extended=True, named="→")
    DOWN = KeyCode(0x28, extended=True, named="↓")
    MENU_MASK = KeyCode(0xE8)
    """Unassigned, so applications ignore it."""

    def typed(self, *, shifted: bool) -> str | None:
        """What the key types, or None for keys that don't type (arrows, Enter...)."""
        return self.value.shifted if shifted else self.value.plain

    def is_letter(self) -> bool:
        return Key.A.vk <= self.vk <= Key.Z.vk

    def continues_word(self) -> bool:
        """Keys that keep caps word going without being capitalised."""
        return Key.N0.vk <= self.vk <= Key.N9.vk or self in (Key.BACKSPACE, Key.DELETE)


class Mod(VirtualKey):
    """The left-hand modifier keys."""

    GUI = KeyCode(0x5B, extended=True, named="Win")
    ALT = KeyCode(0xA4, named="Alt")
    CTRL = KeyCode(0xA2, named="Ctrl")
    SHIFT = KeyCode(0xA0, named="Shift")


class Layer(Enum):
    """A layer reached by holding a key. With none held, keys come from the base layer."""

    NAV = auto()
    NUM = auto()
    SYM = auto()
    APPS = auto()
    """Every Workspace request: apps, desktops, focus, windows and voice."""


type Hold = Mod | Layer
"""What a tap-hold key does while held."""


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


# ---- Board shape ---------------------------------------------------------------


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
