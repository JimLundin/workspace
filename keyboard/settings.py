"""The keyboard's chosen values: its timings, the physical keys it uses, and the
layout written on them. Only declarations, in the vocabulary of `keyboard.physical`,
`keyboard.keys`, `keyboard.actions` and `keyboard.board`; `keyboard.bindings`
builds the engine's lookups from these.
"""

from typing import Final

import config
from contracts.members import every_member
from keyboard.actions import BLANK, Binding, Chord, Layer, TapHold
from keyboard.board import Board, Row, Thumbs
from keyboard.keys import Key, Mod
from keyboard.physical import Laptop
from protocol import Tool

# ---- Timings ---------------------------------------------------------------------

TAPPING_TERM_MS: Final = 200
"""Hold a tap-hold key longer than this and it becomes its modifier or layer."""
STREAK_MS: Final = 150
"""Typing streak: a home row mod pressed this soon after a typed character is a
plain letter, sent on press."""
QUICK_TAP_MS: Final = 200
"""Quick tap: tap a tap-hold key, then press it again within this long, and it
is that key held down (so it repeats), not its modifier or layer."""
QUIT_HOLD_MS: Final = 2000
"""Hold the escape key this long to quit."""

# ---- The keys the layout owns ------------------------------------------------------

ESCAPE: Final = Laptop.SECTION.scancode
"""The escape key: the key left of 1, § on a Nordic keyboard."""

# The Charybdis Nano (3x5) Splinky: matched by its USB identity, independent of port.
FIRMWARE_VENDOR: Final = 0xA8F8
FIRMWARE_PRODUCT: Final = 0x1832
APPS_KEY: Final = 0xA5
"""Right Alt, which the Charybdis's Tab thumb holds (VIA mod-tap `MT(MOD_RALT, KC_TAB)`).
Its keymap uses no other Right Alt, and with the Charybdis connected Windows runs
English (US), where Right Alt is a plain Alt rather than AltGr."""


# ---- Short names used in the tables --------------------------------------------

# fmt: off
A, B, C, D, E, F, G, H, I, J, K, L, M = Key.A, Key.B, Key.C, Key.D, Key.E, Key.F, Key.G, Key.H, Key.I, Key.J, Key.K, Key.L, Key.M  # noqa: E741 - the letters by name
N, O, P, Q, R, S, T, U, V, W, X, Y, Z = Key.N, Key.O, Key.P, Key.Q, Key.R, Key.S, Key.T, Key.U, Key.V, Key.W, Key.X, Key.Y, Key.Z  # noqa: E741 - the letters by name
N0, N1, N2, N3, N4, N5, N6, N7, N8, N9 = Key.N0, Key.N1, Key.N2, Key.N3, Key.N4, Key.N5, Key.N6, Key.N7, Key.N8, Key.N9
GRAVE, MINUS, EQUAL, LBRACKET, RBRACKET, BACKSLASH = Key.GRAVE, Key.MINUS, Key.EQUAL, Key.LBRACKET, Key.RBRACKET, Key.BACKSLASH
SEMICOLON, QUOTE, COMMA, PERIOD, SLASH = Key.SEMICOLON, Key.QUOTE, Key.COMMA, Key.PERIOD, Key.SLASH
ESC, SPACE, TAB, ENTER, BACKSPACE, CAPS_LOCK = Key.ESC, Key.SPACE, Key.TAB, Key.ENTER, Key.BACKSPACE, Key.CAPS_LOCK
DELETE, INSERT, HOME, END, PAGE_UP, PAGE_DOWN = Key.DELETE, Key.INSERT, Key.HOME, Key.END, Key.PAGE_UP, Key.PAGE_DOWN
LEFT, UP, RIGHT, DOWN = Key.LEFT, Key.UP, Key.RIGHT, Key.DOWN
GUI, ALT, CTL, SFT = Mod.GUI, Mod.ALT, Mod.CTRL, Mod.SHIFT
NAV, NUM, SYM = Layer.NAV, Layer.NUM, Layer.SYM
# fmt: on

XX = BLANK
ht = TapHold


sh, ctl = Chord.shifted, Chord.ctrl


UNDO, REDO, COPY, PASTE, CUT = ctl(Z), ctl(Y), ctl(C), ctl(V), ctl(X)

# ---- The layout ----------------------------------------------------------------
# Rows read across the keyboard: left hand, then right hand. Kept in columns by
# hand, so the formatter is told to leave this section alone.

# fmt: off
PHYSICAL: Final[Board[Laptop]] = Board(
    # The ISO laptop keyboard (Miryoku KMonad mapping: rows moved up one, reverse angle on the left, wide spacing).
    top=      Row((Laptop.N2,   Laptop.N3, Laptop.N4, Laptop.N5, Laptop.N6), (Laptop.N8, Laptop.N9, Laptop.N0,      Laptop.PLUS,    Laptop.ACUTE     )),
    home=     Row((Laptop.Q,    Laptop.W,  Laptop.E,  Laptop.R,  Laptop.T ), (Laptop.I,  Laptop.O,  Laptop.P,       Laptop.ARING,   Laptop.DIAERESIS )),
    bottom=   Row((Laptop.CAPS, Laptop.A,  Laptop.S,  Laptop.D,  Laptop.F ), (Laptop.K,  Laptop.L,  Laptop.OUMLAUT, Laptop.AUMLAUT, Laptop.APOSTROPHE)),
    thumbs=Thumbs((                        Laptop.X,  Laptop.C,  Laptop.V ), (Laptop.M,  Laptop.COMMA, Laptop.PERIOD)),
)

UNUSED: Final = frozenset({
    # Keys between and below the hands, and the Spacebar: blocked.
    Laptop.N1, Laptop.N7, Laptop.Y, Laptop.U, Laptop.G, Laptop.H, Laptop.J,
    Laptop.Z, Laptop.B, Laptop.N, Laptop.MINUS, Laptop.LESS, Laptop.SPACE,
})

FUNCTION_KEYS: Final = frozenset({
    Laptop.F1, Laptop.F2, Laptop.F3, Laptop.F4, Laptop.F5, Laptop.F6,
    Laptop.F7, Laptop.F8, Laptop.F9, Laptop.F10, Laptop.F11, Laptop.F12,
})
"""The physical F1-F12 row remains native while the layout is enabled."""

NATIVE_KEYS: Final = frozenset((
    *range(0x70, 0x88),  # F1-F24
    *range(0xAD, 0xB4),  # volume and media
    *range(0x25, 0x29),  # arrows
    0x10, 0x11, 0xA0, 0xA1, 0xA2, 0xA3, 0x5B, 0x5C,  # Shift, Ctrl, Windows
))  # fmt: skip
"""Virtual keys that stay native whichever physical key sends them: function and
media keys, arrows, and the physical Shift, Ctrl and Windows keys."""

BASE: Final[Board[Binding]] = Board(
    # Colemak-DH with home row mods (Win Alt Ctrl Shift).
    top=      Row((Q,          W,          F,          P,              B  ), (J,              L,                  U,          Y,          QUOTE     )),
    home=     Row((ht(A, GUI), ht(R, ALT), ht(S, CTL), ht(T, SFT),     G  ), (M,              ht(N, SFT),         ht(E, CTL), ht(I, ALT), ht(O, GUI))),
    bottom=   Row((Z,          X,          C,          D,              V  ), (K,              H,                  COMMA,      PERIOD,     SLASH     )),
    thumbs=Thumbs((                        ht(ESC, Layer.APPS), ht(SPACE, NAV), TAB     ), (ht(ENTER, SYM), ht(BACKSPACE, NUM), DELETE)),
)

# The apps from config, ten slots named by their chord letters; slots past the end do nothing.
_APPS: Final[tuple[Binding, ...]] = (*config.APPS[:10], *[XX] * (10 - len(config.APPS[:10])))
_Q, _W, _F, _P, _B, _A, _R, _S, _T, _G = _APPS

LAYERS: Final[frozendict[Layer, Board[Binding]]] = every_member(Layer, {
    Layer.NAV: Board(
        # Hold the Space thumb.
        top=      Row((XX,   XX,  XX,  XX,  XX), (REDO,      PASTE,     COPY,      CUT,     UNDO )),
        home=     Row((GUI,  ALT, CTL, SFT, XX), (CAPS_LOCK, LEFT,      DOWN,      UP,      RIGHT)),
        bottom=   Row((XX,   XX,  XX,  XX,  XX), (INSERT,    HOME,      PAGE_DOWN, PAGE_UP, END  )),
        thumbs=Thumbs((           XX,  XX,  XX), (ENTER,     BACKSPACE, DELETE   )),
    ),
    Layer.NUM: Board(
        # Hold the Backspace thumb.
        top=      Row((LBRACKET,  N7, N8,     N9, RBRACKET ), (XX, XX,  XX,  XX,  XX  )),  # [ 7 8 9 ]
        home=     Row((SEMICOLON, N4, N5,     N6, EQUAL    ), (XX, SFT, CTL, ALT, GUI )),  # ; 4 5 6 =
        bottom=   Row((GRAVE,     N1, N2,     N3, BACKSLASH), (XX, XX,  XX,  XX,  XX  )),  # ` 1 2 3 \
        thumbs=Thumbs((               PERIOD, N0, MINUS    ), (XX, XX,  XX )),             # . 0 -
    ),
    Layer.SYM: Board(
        # Hold the Enter thumb.
        top=      Row((sh(LBRACKET),  sh(N7), sh(N8), sh(N9), sh(RBRACKET) ), (XX, XX,  XX,  XX,  XX  )),  # { & * ( }
        home=     Row((sh(SEMICOLON), sh(N4), sh(N5), sh(N6), sh(EQUAL)    ), (XX, SFT, CTL, ALT, GUI )),  # : $ % ^ +
        bottom=   Row((sh(GRAVE),     sh(N1), sh(N2), sh(N3), sh(BACKSLASH)), (XX, XX,  XX,  XX,  XX  )),  # ~ ! @ # |
        thumbs=Thumbs((                       sh(N9), sh(N0), sh(MINUS)    ), (XX, XX,  XX )),             # ( ) _
    ),
    Layer.APPS: Board(
        # Hold the Esc thumb (left outer). The only Workspace layer: apps on the left; desktops, focus and voice on the right.
        # The Charybdis reaches each request by holding Tab (Right Alt) and the base key at its place (`keyboard.firmware.CHORDS`).
        top=      Row((_Q,              _W,                    _F,                   _P,              _B           ),
                      (Tool.DESKTOP_1,  Tool.DESKTOP_2,        Tool.DESKTOP_3,       Tool.DESKTOP_4,  Tool.DESKTOP_5)),
        home=     Row((_A,              _R,                    _S,                   _T,              _G           ),
                      (Tool.ZOOM,       Tool.FOCUS_LEFT,       Tool.FOCUS_DOWN,      Tool.FOCUS_UP,   Tool.FOCUS_RIGHT)),
        bottom=   Row((XX,              Tool.PLACEMENT_PAUSE,  Tool.WINDOW_SWITCHER, Tool.PLACE_NOW,  XX           ),
                      (XX,              Tool.DICTATE,          XX,                   Tool.COPY_TRANSCRIPT, Tool.DICTATE_TOGGLE)),
        # The Tab place stays empty: the Charybdis holds Tab for Apps, so it can't also be a chord.
        thumbs=Thumbs((XX,              Tool.MEETING_TOGGLE,   XX), (XX,              XX, XX)),
    ),
})
"""The board of each held layer; a Layer without one fails the import."""
# fmt: on
