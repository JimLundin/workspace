from dataclasses import dataclass
from enum import Enum, auto
from typing import Final

from contracts.hotkeys import ROUTES, Route
from contracts.members import every_member
from keyboard.actions import BLANK, Binding, Chord, Layer, TapHold
from keyboard.bindings import Bindings, Unmapped
from keyboard.chords import Chords
from keyboard.keys import Key, Mod
from keyboard.layout import Layout
from keyboard.physical import Laptop
from protocol import App, Slot, Target, Tool, reaching

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
    (
        Laptop.Q,
        Laptop.W,
        Laptop.E,
        Laptop.R,
        Laptop.T,
        Laptop.Y,
        Laptop.U,
        Laptop.I,
        Laptop.O,
        Laptop.P,
        Laptop.ARING,
        Laptop.DIAERESIS,
    ),
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
    (
        Laptop.LESS,
        Laptop.Z,
        Laptop.X,
        Laptop.C,
        Laptop.V,
        Laptop.B,
        Laptop.N,
        Laptop.M,
        Laptop.COMMA,
        Laptop.PERIOD,
        Laptop.MINUS,
    ),
    (Laptop.SPACE,),
)
"""The keyboard's letter block and Spacebar, row by row, as the key map draws it."""

PHYSICAL_NAMES: Final = frozendict(
    {key.scancode: key.legend for row in ROWS for key in row}
)
"""Each drawn key's keycap name, by the scancode the layout reports it with."""


@dataclass(frozen=True, slots=True)
class Shortcut:
    tap: str
    hold: str | None


def shortcut_hint(binding: Shortcut | None, *, compact: bool = False) -> str:
    match binding:
        case Shortcut(tap, None):
            return tap
        case Shortcut(tap, hold):
            return f"{hold} {tap}" if compact else f"Hold {hold} + {tap}"
        case None:
            return ""


class Role(Enum):
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
"""The Apps key, held for a request's letter: the Tab thumb, on the laptop or the Charybdis."""

_CHORD_NAMES: Final = frozendict(
    {
        Chord.ctrl(Key.Z): "Undo",
        Chord.ctrl(Key.Y): "Redo",
        Chord.ctrl(Key.C): "Copy",
        Chord.ctrl(Key.V): "Paste",
        Chord.ctrl(Key.X): "Cut",
    }
)
TOOL_NAMES: Final = every_member(Tool, {
    Tool.DICTATE: "Talk",
    Tool.ZOOM: "Zoom",
    Tool.FOCUS_LEFT: "Focus ←", Tool.FOCUS_DOWN: "Focus ↓", Tool.FOCUS_UP: "Focus ↑", Tool.FOCUS_RIGHT: "Focus →",
    Tool.LAYER_DOWN: "Layer ↓", Tool.LAYER_UP: "Layer ↑",
    Tool.DESKTOP_1: "Desk 1", Tool.DESKTOP_2: "Desk 2", Tool.DESKTOP_3: "Desk 3", Tool.DESKTOP_4: "Desk 4", Tool.DESKTOP_5: "Desk 5",
    Tool.PLACEMENT_PAUSE: "Pause place", Tool.PLACE_NOW: "Re-place",
    Tool.MEETING_TOGGLE: "Record", Tool.COPY_TRANSCRIPT: "Copy speech",
    Tool.DICTATE_TOGGLE: "Dictate toggle",
    Tool.WINDOW_SWITCHER: "Windows",
})  # fmt: skip


@dataclass(frozen=True, slots=True)
class KeyboardView:
    layout: Layout
    bindings: Bindings
    apps: tuple[App, ...]
    """The apps in the Apps layer's slots, in slot order."""
    letters: frozendict[Target, str]
    """Each target's key under the Apps hold; an empty slot has none."""

    @classmethod
    def of(cls, layout: Layout, apps: tuple[App, ...]) -> KeyboardView:
        bindings = Bindings.of(layout)
        reached = (
            (reaching(request, apps), letter)
            for request, letter in Chords.of(bindings).letters.items()
        )
        return cls(
            layout,
            bindings,
            apps,
            frozendict(
                (target, letter)
                for target, letter in reached
                if target is not None
            ),
        )

    def shortcut(self, tool: Tool) -> Shortcut | None:
        physical = self.layout.physical.cells()
        for layer in Layer:
            held = self._holding(layer)
            if held is None:
                continue
            for cell, binding in enumerate(self.bindings.actions(layer)):
                if binding is tool:
                    return Shortcut(
                        physical[cell].legend, physical[held].legend
                    )
        letter = self.letters.get(tool)
        return Shortcut(letter, CHORD_HOLD) if letter is not None else None

    def describe(self, a: Binding) -> tuple[str, Role]:
        if a is BLANK:
            return "", Role.BLANK
        match a:
            case Key():
                return a.legend, Role.KEY
            case Chord(key, mods) if a in _CHORD_NAMES:
                return _CHORD_NAMES[a], Role.KEY
            case Chord(key) if a.only_shifted and (
                c := key.typed(shifted=True)
            ):
                return c, Role.KEY
            case Chord(key, mods):
                return "+".join(
                    [*(m.legend for m in Mod if m in mods), key.legend]
                ), Role.KEY
            case TapHold(tap):
                return self.describe(tap)
            case Mod():
                return a.legend, Role.MOD
            case Layer():
                return a.name.title(), Role.LAYER
            case Tool():
                return TOOL_NAMES[a], Role.TOOL
            case Slot():
                match reaching(a, self.apps):
                    case App(name=name):
                        return name[:1].upper() + name[1:], Role.APP
                    case _:
                        return "", Role.BLANK

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
        base = self.bindings.actions(Layer.BASE)
        return next(
            (
                cell
                for cell, a in enumerate(base)
                if isinstance(a, TapHold) and a.hold is layer
            ),
            None,
        )

    def _cap(self, layer: Layer, held: int | None, key: Laptop) -> Cap:
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
        held = self._holding(layer)
        return tuple(
            tuple(self._cap(layer, held, key) for key in row) for row in ROWS
        )


def indicator_text(layer: Layer, *, caps_word: bool) -> str | None:
    parts = [layer.name] if layer is not Layer.BASE else []
    if caps_word:
        parts.append("CAPS WORD")
    return " · ".join(parts) or None
