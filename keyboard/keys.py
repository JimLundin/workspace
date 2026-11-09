"""The keys and modifiers the layout sends to Windows. The vocabulary is Windows':
each key carries its virtual key code, whether Windows sends it as extended,
what it types on US English, and the name its keycap shows."""

from dataclasses import dataclass, field
from enum import Enum


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
