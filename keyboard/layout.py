"""The keyboard's vocabulary: keys, modifiers, layers, actions and the board's
shape. The layout written in it is `keyboard.settings`; what each key does is
`keyboard.bindings`.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import ClassVar, Final, NewType

from protocol import App, Tool

Scancode = NewType("Scancode", int)
"""A hardware scancode identifying a physical key."""


# ---- Vocabulary ----------------------------------------------------------------
# A bare Key, Mod or Layer in a layout is itself an action: a Key is tapped, a
# Mod or Layer is held while the key is held. Only the actions that need more
# than that get a type of their own. The vocabulary is Windows': keys are virtual
# key codes, and know whether Windows treats them as extended.


class Key(Enum):
    """A Windows virtual key (US English layout). The value is the VK code."""

    A = 0x41
    B = 0x42
    C = 0x43
    D = 0x44
    E = 0x45
    F = 0x46
    G = 0x47
    H = 0x48
    LETTER_I = 0x49
    J = 0x4A
    K = 0x4B
    L = 0x4C
    M = 0x4D
    N = 0x4E
    LETTER_O = 0x4F
    P = 0x50
    Q = 0x51
    R = 0x52
    S = 0x53
    T = 0x54
    U = 0x55
    V = 0x56
    W = 0x57
    X = 0x58
    Y = 0x59
    Z = 0x5A
    N0 = 0x30
    N1 = 0x31
    N2 = 0x32
    N3 = 0x33
    N4 = 0x34
    N5 = 0x35
    N6 = 0x36
    N7 = 0x37
    N8 = 0x38
    N9 = 0x39
    GRAVE = 0xC0
    MINUS = 0xBD
    EQUAL = 0xBB
    LBRACKET = 0xDB
    RBRACKET = 0xDD
    BACKSLASH = 0xDC
    SEMICOLON = 0xBA
    QUOTE = 0xDE
    COMMA = 0xBC
    PERIOD = 0xBE
    SLASH = 0xBF
    ESC = 0x1B
    SPACE = 0x20
    TAB = 0x09
    ENTER = 0x0D
    BACKSPACE = 0x08
    CAPS_LOCK = 0x14
    DELETE = 0x2E
    INSERT = 0x2D
    HOME = 0x24
    END = 0x23
    PAGE_UP = 0x21
    PAGE_DOWN = 0x22
    LEFT = 0x25
    UP = 0x26
    RIGHT = 0x27
    DOWN = 0x28
    MENU_MASK = 0xE8
    """Unassigned, so applications ignore it."""

    @property
    def vk(self) -> int:
        vk: int = self.value
        return vk

    @property
    def extended(self) -> bool:
        """Windows sends these with the "extended" flag (they have an E0 prefix)."""
        return self in EXTENDED_KEYS

    def is_letter(self) -> bool:
        return Key.A.vk <= self.vk <= Key.Z.vk

    def continues_word(self) -> bool:
        """Keys that keep caps word going without being capitalised."""
        return Key.N0.vk <= self.vk <= Key.N9.vk or self in (Key.BACKSPACE, Key.DELETE)


EXTENDED_KEYS: Final = frozenset({Key.DELETE, Key.INSERT, Key.HOME, Key.END, Key.PAGE_UP, Key.PAGE_DOWN, Key.LEFT, Key.UP, Key.RIGHT, Key.DOWN})


class Mod(Enum):
    """The left-hand modifier keys. The value is the VK code."""

    GUI = 0x5B
    ALT = 0xA4
    CTRL = 0xA2
    SHIFT = 0xA0

    @property
    def vk(self) -> int:
        vk: int = self.value
        return vk

    @property
    def extended(self) -> bool:
        return self is Mod.GUI


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

    key: Key
    mods: frozenset[Mod]

    @classmethod
    def shifted(cls, key: Key) -> Chord:
        return cls(key, _SHIFT)

    @classmethod
    def ctrl(cls, key: Key) -> Chord:
        return cls(key, _CTRL)

    @property
    def only_shifted(self) -> bool:
        """Shift and nothing else: a typed character, not a shortcut."""
        return self.mods == _SHIFT

    @property
    def types(self) -> bool:
        """At most Shift: a typed character, not a shortcut."""
        return self.mods <= _SHIFT


_SHIFT: Final = frozenset({Mod.SHIFT})
_CTRL: Final = frozenset({Mod.CTRL})

type Output = Key | Chord
"""What reaches Windows when a key is tapped. A bare Key is a chord without modifiers."""


class Command(Enum):
    """Things the engine does itself, rather than sending a key."""

    NOTHING = auto()


@dataclass(frozen=True, slots=True)
class TapHold:
    """Tap = the output, hold = the `Hold`."""

    tap: Output
    hold: Hold


type Action = Output | Mod | Layer | TapHold | Command | Tool | App
"""What one key on one layer does. A Key or Chord is sent; a Mod or Layer is held
while the key is held; a Tool or App is a request to the assistant (see `protocol`)."""


@dataclass(frozen=True, slots=True)
class Typed:
    """What a key types on the US English layout, plain and with Shift."""

    plain: str
    shifted: str


CHARACTERS: Final[frozendict[Key, Typed]] = frozendict({
    **{key: Typed(chr(key.value).lower(), chr(key.value)) for key in Key if key.is_letter()},
    **{Key[f"N{d}"]: Typed(str(d), ")!@#$%^&*("[d]) for d in range(10)},
    Key.GRAVE: Typed("`", "~"), Key.MINUS: Typed("-", "_"), Key.EQUAL: Typed("=", "+"),
    Key.LBRACKET: Typed("[", "{"), Key.RBRACKET: Typed("]", "}"), Key.BACKSLASH: Typed("\\", "|"),
    Key.SEMICOLON: Typed(";", ":"), Key.QUOTE: Typed("'", '"'), Key.COMMA: Typed(",", "<"),
    Key.PERIOD: Typed(".", ">"), Key.SLASH: Typed("/", "?"), Key.SPACE: Typed(" ", " "),
})  # fmt: skip
"""The character each key types on the US English layout."""


def character(key: Key, *, shifted: bool) -> str | None:
    """What a key types, or None for keys that don't type (arrows, Enter...)."""
    typed = CHARACTERS.get(key)
    return None if typed is None else typed.shifted if shifted else typed.plain


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
    (`Board[Scancode]`) and for every layer (`Board[Action]`), so they line up."""

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
