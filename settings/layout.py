"""The keyboard layout Workspace runs: its timings, the physical keys it uses, and
the layers written on them. Only declarations, in the vocabulary of `contracts.keyboard.physical`,
`contracts.keyboard.keys`, `contracts.keyboard.actions` and `contracts.keyboard.board`, gathered into one
`contracts.keyboard.layout.Layout` that `keyboard.__main__` hands to the layout.
"""

from typing import Final

from contracts.keyboard.actions import BLANK, Binding, Chord, Layer, TapHold
from contracts.keyboard.board import Board, Row, Thumbs
from contracts.keyboard.keys import Key, Mod
from contracts.keyboard.layout import Layout, Timings, UsbIdentity
from contracts.keyboard.physical import Laptop
from protocol import Tool
from settings import apps

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


# ---- Shortcuts the layers send ----------------------------------------------------

UNDO, REDO, COPY, PASTE, CUT = Chord.ctrl(Key.Z), Chord.ctrl(Key.Y), Chord.ctrl(Key.C), Chord.ctrl(Key.V), Chord.ctrl(Key.X)

# ---- The layout ----------------------------------------------------------------
# Each row is written across the keyboard: the left hand's half, then the right
# hand's on the line below. Kept in columns by hand, so the formatter is told to
# leave this section alone.

# fmt: off
PHYSICAL: Final[Board[Laptop]] = Board(
    # The ISO laptop keyboard (Miryoku KMonad mapping: rows moved up one, reverse angle on the left, wide spacing).
    top=      Row((Laptop.N2,    Laptop.N3,     Laptop.N4,       Laptop.N5,       Laptop.N6),
                  (Laptop.N8,    Laptop.N9,     Laptop.N0,       Laptop.PLUS,     Laptop.ACUTE)),
    home=     Row((Laptop.Q,     Laptop.W,      Laptop.E,        Laptop.R,        Laptop.T),
                  (Laptop.I,     Laptop.O,      Laptop.P,        Laptop.ARING,    Laptop.DIAERESIS)),
    bottom=   Row((Laptop.CAPS,  Laptop.A,      Laptop.S,        Laptop.D,        Laptop.F),
                  (Laptop.K,     Laptop.L,      Laptop.OUMLAUT,  Laptop.AUMLAUT,  Laptop.APOSTROPHE)),
    thumbs=Thumbs((                             Laptop.X,        Laptop.C,        Laptop.V),
                  (Laptop.M,     Laptop.COMMA,  Laptop.PERIOD)),
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

# ---- The layers ------------------------------------------------------------------

# The apps from settings.apps, ten slots named by their chord letters; slots past the end do nothing.
_APPS: Final[tuple[Binding, ...]] = (*apps.APPS[:10], *[BLANK] * (10 - len(apps.APPS[:10])))
_Q, _W, _F, _P, _B, _A, _R, _S, _T, _G = _APPS


LAYERS: Final[frozendict[Layer, Board[Binding]]] = frozendict({
    # Every layer's board; `contracts.keyboard.bindings` rejects a missing layer or a hold of BASE.
    Layer.BASE: Board(
        # What each key does while no layer is held: Colemak-DH with home row mods (Win Alt Ctrl Shift).
        top=      Row((Key.Q,                          Key.W,                              Key.F,                         Key.P,                          Key.B),
                      (Key.J,                          Key.L,                              Key.U,                         Key.Y,                          Key.QUOTE)),
        home=     Row((TapHold(Key.A, Mod.GUI),        TapHold(Key.R, Mod.ALT),            TapHold(Key.S, Mod.CTRL),      TapHold(Key.T, Mod.SHIFT),      Key.G),
                      (Key.M,                          TapHold(Key.N, Mod.SHIFT),          TapHold(Key.E, Mod.CTRL),      TapHold(Key.I, Mod.ALT),        TapHold(Key.O, Mod.GUI))),
        bottom=   Row((Key.Z,                          Key.X,                              Key.C,                         Key.D,                          Key.V),
                      (Key.K,                          Key.H,                              Key.COMMA,                     Key.PERIOD,                     Key.SLASH)),
        thumbs=Thumbs((                                                                    TapHold(Key.ESC, Layer.APPS),  TapHold(Key.SPACE, Layer.NAV),  Key.TAB),
                      (TapHold(Key.ENTER, Layer.SYM),  TapHold(Key.BACKSPACE, Layer.NUM),  Key.DELETE)),
    ),
    Layer.NAV: Board(
        # Hold the Space thumb.
        top=      Row((BLANK,          BLANK,          BLANK,          BLANK,        BLANK),
                      (REDO,           PASTE,          COPY,           CUT,          UNDO)),
        home=     Row((Mod.GUI,        Mod.ALT,        Mod.CTRL,       Mod.SHIFT,    BLANK),
                      (Key.CAPS_LOCK,  Key.LEFT,       Key.DOWN,       Key.UP,       Key.RIGHT)),
        bottom=   Row((BLANK,          BLANK,          BLANK,          BLANK,        BLANK),
                      (Key.INSERT,     Key.HOME,       Key.PAGE_DOWN,  Key.PAGE_UP,  Key.END)),
        thumbs=Thumbs((                                BLANK,          BLANK,        BLANK),
                      (Key.ENTER,      Key.BACKSPACE,  Key.DELETE)),
    ),
    Layer.NUM: Board(
        # Hold the Backspace thumb.
        top=      Row((Key.LBRACKET,   Key.N7,     Key.N8,      Key.N9,   Key.RBRACKET),   # [ 7 8 9 ]
                      (BLANK,          BLANK,      BLANK,       BLANK,    BLANK)),
        home=     Row((Key.SEMICOLON,  Key.N4,     Key.N5,      Key.N6,   Key.EQUAL),      # ; 4 5 6 =
                      (BLANK,          Mod.SHIFT,  Mod.CTRL,    Mod.ALT,  Mod.GUI)),
        bottom=   Row((Key.GRAVE,      Key.N1,     Key.N2,      Key.N3,   Key.BACKSLASH),  # ` 1 2 3 \
                      (BLANK,          BLANK,      BLANK,       BLANK,    BLANK)),
        thumbs=Thumbs((                            Key.PERIOD,  Key.N0,   Key.MINUS),      # . 0 -
                      (BLANK,          BLANK,      BLANK)),
    ),
    Layer.SYM: Board(
        # Hold the Enter thumb.
        top=      Row((Chord.shifted(Key.LBRACKET),   Chord.shifted(Key.N7),  Chord.shifted(Key.N8),  Chord.shifted(Key.N9),  Chord.shifted(Key.RBRACKET)),   # { & * ( }
                      (BLANK,                         BLANK,                  BLANK,                  BLANK,                  BLANK)),
        home=     Row((Chord.shifted(Key.SEMICOLON),  Chord.shifted(Key.N4),  Chord.shifted(Key.N5),  Chord.shifted(Key.N6),  Chord.shifted(Key.EQUAL)),      # : $ % ^ +
                      (BLANK,                         Mod.SHIFT,              Mod.CTRL,               Mod.ALT,                Mod.GUI)),
        bottom=   Row((Chord.shifted(Key.GRAVE),      Chord.shifted(Key.N1),  Chord.shifted(Key.N2),  Chord.shifted(Key.N3),  Chord.shifted(Key.BACKSLASH)),  # ~ ! @ # |
                      (BLANK,                         BLANK,                  BLANK,                  BLANK,                  BLANK)),
        thumbs=Thumbs((                                                       Chord.shifted(Key.N9),  Chord.shifted(Key.N0),  Chord.shifted(Key.MINUS)),      # ( ) _
                      (BLANK,                         BLANK,                  BLANK)),
    ),
    Layer.APPS: Board(
        # Hold the Esc thumb (left outer). The only Workspace layer: apps on the left; desktops, focus and voice on the right.
        # The Charybdis reaches each request by holding Tab (Right Alt) and the base key at its place (`keyboard.firmware.CHORDS`).
        # The Tab thumb stays empty: the Charybdis holds Tab for Apps, so it can't also be a chord.
        top=      Row((_Q,              _W,                    _F,                    _P,                    _B),
                      (Tool.DESKTOP_1,  Tool.DESKTOP_2,        Tool.DESKTOP_3,        Tool.DESKTOP_4,        Tool.DESKTOP_5)),
        home=     Row((_A,              _R,                    _S,                    _T,                    _G),
                      (Tool.ZOOM,       Tool.FOCUS_LEFT,       Tool.FOCUS_DOWN,       Tool.FOCUS_UP,         Tool.FOCUS_RIGHT)),
        bottom=   Row((BLANK,           Tool.PLACEMENT_PAUSE,  Tool.WINDOW_SWITCHER,  Tool.PLACE_NOW,        BLANK),
                      (BLANK,           Tool.DICTATE,          BLANK,                 Tool.COPY_TRANSCRIPT,  Tool.DICTATE_TOGGLE)),
        thumbs=Thumbs((                                        BLANK,                 Tool.MEETING_TOGGLE,   BLANK),
                      (BLANK,           BLANK,                 BLANK)),
    ),
})
# fmt: on

LAYOUT: Final = Layout(
    physical=PHYSICAL,
    unused=UNUSED,
    function_keys=FUNCTION_KEYS,
    native_keys=NATIVE_KEYS,
    layers=LAYERS,
    escape=ESCAPE,
    apps_key=APPS_KEY,
    firmware=UsbIdentity(FIRMWARE_VENDOR, FIRMWARE_PRODUCT),
    timings=Timings(tapping_term=TAPPING_TERM_MS, streak=STREAK_MS, quick_tap=QUICK_TAP_MS, quit_hold=QUIT_HOLD_MS),
)
"""The layout `keyboard.__main__` runs."""
