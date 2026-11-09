"""The keyboard's chosen values: its timings, the physical keys it uses, and the
layout written on them. Only declarations: the vocabulary is `keyboard.layout`,
and `keyboard.bindings` builds the engine's lookups from these.
"""

from typing import Final

import config
from keyboard.layout import Action, Board, Chord, Key, Layer, Mod, Row, Scancode, TapHold, Thumbs
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

ESCAPE: Final = Scancode(0x29)
"""The escape key (the key left of 1, § on a Nordic keyboard)."""

# The Charybdis Nano (3x5) Splinky: matched by its USB identity, independent of port.
FIRMWARE_KEYBOARD: Final = ("VID_A8F8", "PID_1832")
APPS_KEY: Final = 0xA5
"""Right Alt, which the Charybdis's Tab thumb holds (VIA mod-tap `MT(MOD_RALT, KC_TAB)`).
Its keymap uses no other Right Alt, and with the Charybdis connected Windows runs
English (US), where Right Alt is a plain Alt rather than AltGr."""


# ---- Short names used in the tables --------------------------------------------

# fmt: off
A, B, C, D, E, F, G, H, LETTER_I, J, K, L, M = Key.A, Key.B, Key.C, Key.D, Key.E, Key.F, Key.G, Key.H, Key.LETTER_I, Key.J, Key.K, Key.L, Key.M
N, LETTER_O, P, Q, R, S, T, U, V, W, X, Y, Z = Key.N, Key.LETTER_O, Key.P, Key.Q, Key.R, Key.S, Key.T, Key.U, Key.V, Key.W, Key.X, Key.Y, Key.Z
N0, N1, N2, N3, N4, N5, N6, N7, N8, N9 = Key.N0, Key.N1, Key.N2, Key.N3, Key.N4, Key.N5, Key.N6, Key.N7, Key.N8, Key.N9
GRAVE, MINUS, EQUAL, LBRACKET, RBRACKET, BACKSLASH = Key.GRAVE, Key.MINUS, Key.EQUAL, Key.LBRACKET, Key.RBRACKET, Key.BACKSLASH
SEMICOLON, QUOTE, COMMA, PERIOD, SLASH = Key.SEMICOLON, Key.QUOTE, Key.COMMA, Key.PERIOD, Key.SLASH
ESC, SPACE, TAB, ENTER, BACKSPACE, CAPS_LOCK = Key.ESC, Key.SPACE, Key.TAB, Key.ENTER, Key.BACKSPACE, Key.CAPS_LOCK
DELETE, INSERT, HOME, END, PAGE_UP, PAGE_DOWN = Key.DELETE, Key.INSERT, Key.HOME, Key.END, Key.PAGE_UP, Key.PAGE_DOWN
LEFT, UP, RIGHT, DOWN = Key.LEFT, Key.UP, Key.RIGHT, Key.DOWN
GUI, ALT, CTL, SFT = Mod.GUI, Mod.ALT, Mod.CTRL, Mod.SHIFT
NAV, NUM, SYM = Layer.NAV, Layer.NUM, Layer.SYM
# fmt: on

XX = None
ht, sc = TapHold, Scancode


sh, ctl = Chord.shifted, Chord.ctrl


UNDO, REDO, COPY, PASTE, CUT = ctl(Z), ctl(Y), ctl(C), ctl(V), ctl(X)

# ---- The layout ----------------------------------------------------------------
# Rows read across the keyboard: left hand, then right hand. Kept in columns by
# hand, so the formatter is told to leave this section alone.

# fmt: off
PHYSICAL: Final[Board[Scancode]] = Board(
    # Physical keys of the ISO laptop keyboard (Miryoku KMonad mapping: rows moved
    # up one, reverse angle on the left, wide spacing). Nordic keycaps on the right.
    top=      Row((sc(0x03), sc(0x04), sc(0x05), sc(0x06), sc(0x07)), (sc(0x09), sc(0x0A), sc(0x0B), sc(0x0C), sc(0x0D))),  # 2 3 4 5 6    | 8 9 0 + acute
    home=     Row((sc(0x10), sc(0x11), sc(0x12), sc(0x13), sc(0x14)), (sc(0x17), sc(0x18), sc(0x19), sc(0x1A), sc(0x1B))),  # Q W E R T    | I O P Å ¨
    bottom=   Row((sc(0x3A), sc(0x1E), sc(0x1F), sc(0x20), sc(0x21)), (sc(0x25), sc(0x26), sc(0x27), sc(0x28), sc(0x2B))),  # Caps A S D F | K L Ö Ä '
    thumbs=Thumbs((                    sc(0x2D), sc(0x2E), sc(0x2F)), (sc(0x32), sc(0x33), sc(0x34))),                      # X C V        | M , .
)

UNUSED: Final = frozenset(
    # Keys between and below the hands (1 7 Y U G H J Z B N - <) and the Spacebar: blocked.
    sc(code) for code in (0x02, 0x08, 0x15, 0x16, 0x22, 0x23, 0x24, 0x2C, 0x30, 0x31, 0x35, 0x39, 0x56)
)

FUNCTION_KEYS: Final = frozenset(Scancode(code) for code in range(0x3B, 0x45)) | frozenset({Scancode(0x57), Scancode(0x58)})
"""The physical F1-F12 row remains native while the layout is enabled."""

BASE: Final[Board[Action | None]] = Board(
    # Colemak-DH with home row mods (Win Alt Ctrl Shift).
    top=      Row((Q,          W,          F,          P,              B  ), (J,              L,                  U,          Y,          QUOTE     )),
    home=     Row((ht(A, GUI), ht(R, ALT), ht(S, CTL), ht(T, SFT),     G  ), (M,              ht(N, SFT),         ht(E, CTL), ht(LETTER_I, ALT), ht(LETTER_O, GUI))),
    bottom=   Row((Z,          X,          C,          D,              V  ), (K,              H,                  COMMA,      PERIOD,     SLASH     )),
    thumbs=Thumbs((                        ht(ESC, Layer.APPS), ht(SPACE, NAV), TAB     ), (ht(ENTER, SYM), ht(BACKSPACE, NUM), DELETE)),
)

NAV_LAYER: Final[Board[Action | None]] = Board(
    # Hold the Space thumb.
    top=      Row((XX,   XX,  XX,  XX,  XX), (REDO,      PASTE,     COPY,      CUT,     UNDO )),
    home=     Row((GUI,  ALT, CTL, SFT, XX), (CAPS_LOCK, LEFT,      DOWN,      UP,      RIGHT)),
    bottom=   Row((XX,   XX,  XX,  XX,  XX), (INSERT,    HOME,      PAGE_DOWN, PAGE_UP, END  )),
    thumbs=Thumbs((           XX,  XX,  XX), (ENTER,     BACKSPACE, DELETE   )),
)

NUM_LAYER: Final[Board[Action | None]] = Board(
    # Hold the Backspace thumb.
    top=      Row((LBRACKET,  N7, N8,     N9, RBRACKET ), (XX, XX,  XX,  XX,  XX  )),  # [ 7 8 9 ]
    home=     Row((SEMICOLON, N4, N5,     N6, EQUAL    ), (XX, SFT, CTL, ALT, GUI )),  # ; 4 5 6 =
    bottom=   Row((GRAVE,     N1, N2,     N3, BACKSLASH), (XX, XX,  XX,  XX,  XX  )),  # ` 1 2 3 \
    thumbs=Thumbs((               PERIOD, N0, MINUS    ), (XX, XX,  XX )),             # . 0 -
)

SYM_LAYER: Final[Board[Action | None]] = Board(
    # Hold the Enter thumb.
    top=      Row((sh(LBRACKET),  sh(N7), sh(N8), sh(N9), sh(RBRACKET) ), (XX, XX,  XX,  XX,  XX  )),  # { & * ( }
    home=     Row((sh(SEMICOLON), sh(N4), sh(N5), sh(N6), sh(EQUAL)    ), (XX, SFT, CTL, ALT, GUI )),  # : $ % ^ +
    bottom=   Row((sh(GRAVE),     sh(N1), sh(N2), sh(N3), sh(BACKSLASH)), (XX, XX,  XX,  XX,  XX  )),  # ~ ! @ # |
    thumbs=Thumbs((                       sh(N9), sh(N0), sh(MINUS)    ), (XX, XX,  XX )),             # ( ) _
)

# The apps from config, ten slots in key order; slots past the end do nothing.
_APP: Final[tuple[Action | None, ...]] = (*config.APPS[:10], *[XX] * (10 - len(config.APPS[:10])))

APPS_LAYER: Final[Board[Action | None]] = Board(
    # Hold the Esc thumb (left outer). The only Workspace layer: apps on the left; desktops, focus and voice on the right.
    # The Charybdis reaches each request by holding Tab (Right Alt) and the base key at its place (`keyboard.firmware.CHORDS`).
    top=      Row((_APP[0],         _APP[1],               _APP[2],              _APP[3],         _APP[4]      ),
                  (Tool.DESKTOP_1,  Tool.DESKTOP_2,        Tool.DESKTOP_3,       Tool.DESKTOP_4,  Tool.DESKTOP_5)),
    home=     Row((_APP[5],         _APP[6],               _APP[7],              _APP[8],         _APP[9]      ),
                  (Tool.ZOOM,       Tool.FOCUS_LEFT,       Tool.FOCUS_DOWN,      Tool.FOCUS_UP,   Tool.FOCUS_RIGHT)),
    bottom=   Row((XX,              Tool.PLACEMENT_PAUSE,  Tool.WINDOW_SWITCHER, Tool.PLACE_NOW,  XX           ),
                  (XX,              Tool.DICTATE,          XX,                   Tool.COPY_TRANSCRIPT, Tool.DICTATE_TOGGLE)),
    # The Tab place stays empty: the Charybdis holds Tab for Apps, so it can't also be a chord.
    thumbs=Thumbs((XX,              Tool.MEETING_TOGGLE,   XX), (XX,              XX, XX)),
)
# fmt: on
