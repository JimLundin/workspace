"""The keyboard's vocabulary: keys, modifiers, layers, actions and the board's
shape. The layout written in it is `keyboard.settings`; what each key does is
`keyboard.bindings`.

A bare Key, Mod or Layer in a layout is itself an action: a Key is tapped, a Mod
or Layer is held while the key is held. Only the actions that need more than that
get a type of their own. The vocabulary is Windows': each key carries its virtual
key code, whether Windows sends it as extended, and what it types on US English.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import ClassVar, NewType

from protocol import App, Tool

Scancode = NewType("Scancode", int)
"""A hardware scancode identifying a physical key."""


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
    LETTER_I = KeyCode(0x49, "i", "I")
    J = KeyCode(0x4A, "j", "J")
    K = KeyCode(0x4B, "k", "K")
    L = KeyCode(0x4C, "l", "L")
    M = KeyCode(0x4D, "m", "M")
    N = KeyCode(0x4E, "n", "N")
    LETTER_O = KeyCode(0x4F, "o", "O")
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
    (`Board[Scancode]`) and for every layer (`Board[Binding]`), so they line up."""

    SIZE: ClassVar = 36
    """Keys on the board: three rows of ten, plus six thumb keys."""

    top: Row[CellT]
    home: Row[CellT]
    bottom: Row[CellT]
    thumbs: Thumbs[CellT]

    def cells(self) -> tuple[CellT, ...]:
        """All 36 keys in order: rows top to bottom, left to right, then thumbs."""
        rows = (self.top, self.home, self.bottom)
        return (
            *(key for row in rows for key in (*row.left, *row.right)),
            *self.thumbs.left,
            *self.thumbs.right,
        )


def is_left_hand(cell: int) -> bool:
    """Which hand key number `cell` belongs to (the numbering `Board.cells` uses)."""
    return cell % 10 < 5 if cell < 30 else cell < 33
