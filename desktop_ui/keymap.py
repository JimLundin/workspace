"""What each physical key does, per layer, as the key map window draws it; and the
words the layer indicator shows. Plain Python, read from the layout the desktop is
handed (`KeyboardView`)."""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Final

from contracts.hotkeys import ROUTES, Route
from contracts.keyboard.actions import BLANK, Binding, Chord, Layer, TapHold
from contracts.keyboard.bindings import Bindings, Unmapped
from contracts.keyboard.chords import Chords
from contracts.keyboard.keys import Key, Mod
from contracts.keyboard.layout import Layout
from contracts.keyboard.physical import Laptop
from contracts.members import every_member
from protocol import App, Request, Tool

ROWS: Final = (
    (
        Laptop.SECTION,
        Laptop.N1,
        Laptop.N2,
        Laptop.N3,
        Laptop.N4,
        Laptop.N5,
        Laptop.N6,
        Laptop.N7,
        Laptop.N8,
        Laptop.N9,
        Laptop.N0,
        Laptop.PLUS,
        Laptop.ACUTE,
    ),
    (Laptop.Q, Laptop.W, Laptop.E, Laptop.R, Laptop.T, Laptop.Y, Laptop.U, Laptop.I, Laptop.O, Laptop.P, Laptop.ARING, Laptop.DIAERESIS),
    (
        Laptop.CAPS,
        Laptop.A,
        Laptop.S,
        Laptop.D,
        Laptop.F,
        Laptop.G,
        Laptop.H,
        Laptop.J,
        Laptop.K,
        Laptop.L,
        Laptop.OUMLAUT,
        Laptop.AUMLAUT,
        Laptop.APOSTROPHE,
    ),
    (Laptop.LESS, Laptop.Z, Laptop.X, Laptop.C, Laptop.V, Laptop.B, Laptop.N, Laptop.M, Laptop.COMMA, Laptop.PERIOD, Laptop.MINUS),
    (Laptop.SPACE,),
)
"""The keyboard's letter block and Spacebar, row by row, as the key map draws it."""

PHYSICAL_NAMES: Final = frozendict({key.scancode: key.legend for row in ROWS for key in row})
"""Each drawn key's keycap name, by the scancode the layout reports it with."""


@dataclass(frozen=True, slots=True)
class Shortcut:
    """Physical keycaps: a tap and, for a layer binding, its held thumb."""

    tap: str
    hold: str | None


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


CHORD_HOLD: Final = "Apps"
"""The Apps key, held for a request's letter: the laptop's Esc thumb or the Charybdis's Tab thumb."""

_CHORD_NAMES: Final = frozendict(
    {Chord.ctrl(Key.Z): "Undo", Chord.ctrl(Key.Y): "Redo", Chord.ctrl(Key.C): "Copy", Chord.ctrl(Key.V): "Paste", Chord.ctrl(Key.X): "Cut"}
)
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


@dataclass(frozen=True, slots=True)
class KeyboardView:
    """The layout as the desktop draws and names it: its lookups and each request's chord letter."""

    layout: Layout
    bindings: Bindings
    letters: frozendict[Request, str]
    """Each request's key under the Apps hold."""

    @classmethod
    def of(cls, layout: Layout) -> KeyboardView:
        """`layout` as the desktop reads it, or `LayoutError` if it is inconsistent."""
        bindings = Bindings.of(layout)
        return cls(layout, bindings, Chords.of(bindings).letters)

    def shortcut(self, tool: Tool) -> Shortcut | None:
        """The first binding in the held layers' order, else the tool's firmware chord."""
        physical = self.layout.physical.cells()
        for layer in Layer:
            held = self._holding(layer)
            if held is None:
                continue
            for cell, binding in enumerate(self.bindings.actions(layer)):
                if binding is tool:
                    return Shortcut(physical[cell].legend, physical[held].legend)
        letter = self.letters.get(tool)
        return Shortcut(letter, CHORD_HOLD) if letter is not None else None

    def describe(self, a: Binding) -> tuple[str, Role]:
        """A key's label and role, as drawn."""
        if a is BLANK:
            return "", Role.BLANK
        match a:
            case Key():
                return a.legend, Role.KEY
            case Chord(key, mods) if a in _CHORD_NAMES:
                return _CHORD_NAMES[a], Role.KEY
            case Chord(key) if a.only_shifted and (c := key.typed(shifted=True)):
                return c, Role.KEY
            case Chord(key, mods):
                return "+".join([*(m.legend for m in Mod if m in mods), key.legend]), Role.KEY
            case TapHold(tap):
                return self.describe(tap)
            case Mod():
                return a.legend, Role.MOD
            case Layer():
                return a.name.title(), Role.LAYER
            case Tool():
                return TOOL_NAMES[a], Role.TOOL
            case App():
                return a.name[:1].upper() + a.name[1:], Role.APP

    def _hold(self, a: Binding) -> str:
        match a:
            case Tool() if ROUTES[a] is Route.HOLD:
                return "hold"
            case TapHold(hold=Mod() as modifier):
                return modifier.legend
            case TapHold(hold=Layer() as layer):
                return layer.name.title()
            case _:
                return ""

    def _holding(self, layer: Layer) -> int | None:
        """The cell of the base layer's thumb that holds `layer`; None for the base layer itself."""
        base = self.bindings.actions(Layer.BASE)
        return next((cell for cell, a in enumerate(base) if isinstance(a, TapHold) and a.hold is layer), None)

    def _cap(self, layer: Layer, held: int | None, key: Laptop) -> Cap:
        """The cap for one physical key as `layer` has it, with `held` the cell holding that layer."""
        name = key.legend
        if key.scancode == self.layout.escape:
            return Cap(name, "On/off", "hold: quit", Role.SPECIAL)
        match self.bindings.slot(key.scancode):
            case Unmapped():
                return Cap(name, "", "", Role.BLANK)
            case int(cell) if cell == held:
                return Cap(name, layer.name.title(), "held", Role.HELD)
            case int(cell):
                a = self.bindings.action(layer, cell)
                label, role = self.describe(a)
                return Cap(name, label, self._hold(a), role)

    def keymap(self, layer: Layer) -> tuple[tuple[Cap, ...], ...]:
        """The keyboard, row by row, as `layer` has it."""
        held = self._holding(layer)
        return tuple(tuple(self._cap(layer, held, key) for key in row) for row in ROWS)


def indicator_text(layer: Layer, *, caps_word: bool) -> str | None:
    """What the layer indicator says; None: nothing to show. The base layer says nothing."""
    parts = [layer.name] if layer is not Layer.BASE else []
    if caps_word:
        parts.append("CAPS WORD")
    return " · ".join(parts) or None
