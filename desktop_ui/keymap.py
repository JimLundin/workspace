"""What each physical key does, per layer, as the key map window draws it; and the
words the layer indicator shows. Plain Python, read from the layout's own tables."""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Final

from contracts.hotkeys import ROUTES, Route
from contracts.members import every_member
from keyboard.firmware import CHORDS
from keyboard.layout import (
    BASE,
    COPY,
    CUT,
    ESCAPE,
    PASTE,
    PHYSICAL,
    REDO,
    TABLE,
    UNDO,
    Action,
    Chord,
    Command,
    Key,
    Layer,
    Mod,
    Scancode,
    TapHold,
    Unmapped,
    action,
    character,
    slot,
)
from protocol import App, Tool


def _row(first: int, names: str) -> tuple[tuple[Scancode, str], ...]:
    return tuple((Scancode(first + i), name) for i, name in enumerate(names.split()))


ROWS: Final = (
    ((Scancode(0x29), "\u00a7"), *_row(0x02, "1 2 3 4 5 6 7 8 9 0 + \u00b4")),
    _row(0x10, "Q W E R T Y U I O P \u00c5 \u00a8"),
    ((Scancode(0x3A), "Caps"), *_row(0x1E, "A S D F G H J K L \u00d6 \u00c4"), (Scancode(0x2B), "'")),
    ((Scancode(0x56), "<"), *_row(0x2C, "Z X C V B N M , . -")),
    ((Scancode(0x39), "Space"),),
)
"""The keyboard's letter block and Spacebar: scancode and Nordic keycap name."""

PHYSICAL_NAMES: Final = {scancode: name for row in ROWS for scancode, name in row}


@dataclass(frozen=True, slots=True)
class Shortcut:
    """Physical keycaps: a tap and, for a layer binding, its held thumb."""

    tap: str
    hold: str | None


CHORD_HOLD: Final = "Apps"
"""The Apps key, held for a request's letter: the laptop's Esc thumb or the Charybdis's Tab thumb."""


def shortcut(tool: Tool) -> Shortcut | None:
    """The first binding in Layer order, else the tool's firmware chord."""
    physical = PHYSICAL.cells()
    for layer in Layer:
        held = _holding(layer)
        if held is None:
            continue
        for cell, binding in enumerate(TABLE[layer]):
            if binding is tool:
                return Shortcut(PHYSICAL_NAMES[physical[cell]], PHYSICAL_NAMES[physical[held]])
    letter = CHORDS.get(tool)
    return Shortcut(letter, CHORD_HOLD) if letter is not None else None


def shortcut_hint(binding: Shortcut | None, *, compact: bool = False) -> str:
    """Use README keycap notation, shortened for the floating menu's trailing edge."""
    match binding:
        case Shortcut(tap, None):
            return tap
        case Shortcut(tap, hold):
            return f"{hold} {tap}" if compact else f"Hold {hold} + {tap}"
        case None:
            return ""


class Role(Enum):
    """What a key does, for its colour."""

    KEY = auto()
    MOD = auto()
    LAYER = auto()
    TOOL = auto()
    APP = auto()
    SPECIAL = auto()
    """The escape key: on/off and quit."""
    HELD = auto()
    """The thumb holding the layer shown."""
    BLANK = auto()


@dataclass(frozen=True, slots=True)
class Cap:
    physical: str
    """The keycap's own name (Nordic)."""
    label: str
    """What it does on this layer; for a tap-hold key, the tap."""
    hold: str
    """What it does held, if that's something else."""
    role: Role


_KEY_NAMES: Final = frozendict({
    Key.SPACE: "Space", Key.ENTER: "Enter", Key.BACKSPACE: "Bksp", Key.DELETE: "Del", Key.TAB: "Tab", Key.ESC: "Esc",
    Key.CAPS_LOCK: "Caps", Key.INSERT: "Ins", Key.HOME: "Home", Key.END: "End", Key.PAGE_UP: "PgUp", Key.PAGE_DOWN: "PgDn",
    Key.LEFT: "←", Key.RIGHT: "→", Key.UP: "↑", Key.DOWN: "↓",
})  # fmt: skip
_CHORD_NAMES: Final = frozendict({UNDO: "Undo", REDO: "Redo", COPY: "Copy", PASTE: "Paste", CUT: "Cut"})
_MOD_NAMES: Final = every_member(Mod, {Mod.GUI: "Win", Mod.ALT: "Alt", Mod.CTRL: "Ctrl", Mod.SHIFT: "Shift"})
TOOL_NAMES: Final = every_member(Tool, {
    Tool.DICTATE: "Talk",
    Tool.ZOOM: "Zoom",
    Tool.FOCUS_LEFT: "Focus ←", Tool.FOCUS_DOWN: "Focus ↓", Tool.FOCUS_UP: "Focus ↑", Tool.FOCUS_RIGHT: "Focus →",
    Tool.DESKTOP_1: "Desk 1", Tool.DESKTOP_2: "Desk 2", Tool.DESKTOP_3: "Desk 3", Tool.DESKTOP_4: "Desk 4", Tool.DESKTOP_5: "Desk 5",
    Tool.PLACEMENT_PAUSE: "Pause place", Tool.PLACE_NOW: "Re-place",
    Tool.MEETING_TOGGLE: "Record", Tool.COPY_TRANSCRIPT: "Copy speech",
    Tool.DICTATE_TOGGLE: "Dictate toggle",
    Tool.WINDOW_SWITCHER: "Windows",
})  # fmt: skip


def _output(key: Key, label: str | None = None) -> str:
    c = character(key, shifted=False)
    return label or _KEY_NAMES.get(key) or (c.upper() if c else key.name.title())


def describe(a: Action) -> tuple[str, Role]:
    """A key's label and role, as drawn."""
    match a:
        case Key():
            return _output(a), Role.KEY
        case Chord(key, mods) if a in _CHORD_NAMES:
            return _CHORD_NAMES[a], Role.KEY
        case Chord(key, mods) if mods == frozenset({Mod.SHIFT}) and (c := character(key, shifted=True)):
            return c, Role.KEY
        case Chord(key, mods):
            return "+".join([*(_MOD_NAMES[m] for m in Mod if m in mods), _output(key)]), Role.KEY
        case TapHold(tap):
            return describe(tap)
        case Mod():
            return _MOD_NAMES[a], Role.MOD
        case Layer():
            return a.name.title(), Role.LAYER
        case Command.NOTHING:
            return "", Role.BLANK
        case Tool():
            return TOOL_NAMES[a], Role.TOOL
        case App():
            return a.name[:1].upper() + a.name[1:], Role.APP


def _hold(a: Action) -> str:
    match a:
        case Tool() if ROUTES[a] is Route.HOLD:
            return "hold"
        case TapHold(hold=Mod() as modifier):
            return _MOD_NAMES[modifier]
        case TapHold(hold=Layer() as layer):
            return layer.name.title()
        case _:
            return ""


def _holding(layer: Layer | None) -> int | None:
    """The cell of the thumb that holds `layer`."""
    return next((cell for cell, a in enumerate(BASE.cells()) if isinstance(a, TapHold) and a.hold is layer), None)


def _cap(layer: Layer | None, held: int | None, scancode: Scancode, name: str) -> Cap:
    """The cap for one physical key as `layer` has it, with `held` the cell holding that layer."""
    if scancode == ESCAPE:
        return Cap(name, "On/off", "hold: quit", Role.SPECIAL)
    match slot(scancode):
        case Unmapped():
            return Cap(name, "", "", Role.BLANK)
        case int(cell) if cell == held and layer is not None:
            return Cap(name, layer.name.title(), "held", Role.HELD)
        case int(cell):
            a = action(layer, cell)
            label, role = describe(a)
            return Cap(name, label, _hold(a), role)


def keymap(layer: Layer | None) -> tuple[tuple[Cap, ...], ...]:
    """The keyboard, row by row, as `layer` (None: the base layer) has it."""
    held = _holding(layer) if layer is not None else None
    return tuple(tuple(_cap(layer, held, scancode, name) for scancode, name in row) for row in ROWS)


def indicator_text(layer: Layer | None, *, caps_word: bool) -> str | None:
    """What the layer indicator says; None: nothing to show."""
    parts = [layer.name] if layer else []
    if caps_word:
        parts.append("CAPS WORD")
    return " · ".join(parts) or None
