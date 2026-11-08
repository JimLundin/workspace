"""The desktop's UI as data: the values in `desktop_ui/spec/`, and their checks.

Each spec module holds one frozen value built from typed dataclasses: the sizes
here, the menus in `island_menu`, the bar's composition in `island_model` and
the tray in `desktop_controls`.
Pyright checks a spec's shape and names; each type checks its own ranges as it
is built; the `problems` checks catch what a type can't say, such as an action
placed twice.

The keeper restarts nothing when a spec module changes. The bar re-imports its
specs when their files change (`ui_spec_watch`); the tray re-imports its own
as it opens. A spec that fails to import or check
raises `SpecError` naming its file, and the reader keeps the spec it has.
"""

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Final

from desktop_ui.island_menu import ControlsSpec, problems
from desktop_ui.island_model import IslandSpec, island_problems
lazy from desktop_ui.spec import controls, island, sizes

FOLDER: Final = Path(__file__).resolve().parent / "spec"
"""The spec modules installed with this copy of Workspace."""


class SpecError(Exception):
    """A spec that can't be used; the message names its file."""


def at_least(owner: str, floor: float, **values: float) -> None:
    """Refuse a size below `floor`, naming it, as the spec's value is built."""
    if low := [name for name, value in values.items() if value < floor]:
        raise ValueError(f"{owner}: {', '.join(low)} must be at least {floor:g}")


@dataclass(frozen=True, slots=True)
class Bar:
    top: float
    """From the screen's top edge to the capsules."""
    edge: float
    """From the screen's right edge to the right capsule."""
    gap: float
    """Between neighbouring capsules."""
    radius: float
    shadow: float
    """Room below and beside the capsules for their shadow."""

    def __post_init__(self) -> None:
        at_least("bar", 0, top=self.top, edge=self.edge, gap=self.gap, radius=self.radius, shadow=self.shadow)


@dataclass(frozen=True, slots=True, kw_only=True)
class Capsule:
    height: float
    control: float
    """A concentric control: (height - control) / 2 from the capsule's edge."""
    icon: float
    dot: float
    """The recording dot."""
    dots: float
    """Transcription's three dots."""
    wave_bars: int
    part_gap: float
    """Between the parts of one fact, such as a symbol and its reading."""
    slot_gap: float
    """Between separate facts."""
    text_pad: float
    """A capsule's ends when it holds text..."""
    icon_pad: float
    """...and when it holds only symbols."""

    def __post_init__(self) -> None:
        at_least("capsule", 1, height=self.height, control=self.control, icon=self.icon, dot=self.dot, dots=self.dots)
        at_least("capsule", 1, wave_bars=self.wave_bars)
        at_least("capsule", 0, part_gap=self.part_gap, slot_gap=self.slot_gap, text_pad=self.text_pad, icon_pad=self.icon_pad)
        if self.control > self.height:
            raise ValueError("capsule: a control must fit its capsule's height")

    @property
    def inset(self) -> float:
        """A control at either end sits concentric with the capsule."""
        return (self.height - self.control) / 2

    @property
    def wave(self) -> float:
        """The microphone trace: two-pixel bars, two pixels apart."""
        return self.wave_bars * 4 - 2


@dataclass(frozen=True, slots=True, kw_only=True)
class MenuGrid:
    """The controls menu: a grid of tiles below the capsule's own row."""

    width: float
    radius: float
    pad: float
    head: float
    """The capsule's own row, above the grid."""
    track: float
    """One grid row; a tile spans whole tracks."""
    gutter: float
    """Between tiles; each tile keeps half on every side."""

    def __post_init__(self) -> None:
        at_least("menu", 1, width=self.width, head=self.head, track=self.track)
        at_least("menu", 0, radius=self.radius, pad=self.pad, gutter=self.gutter)


@dataclass(frozen=True, slots=True)
class Sizes:
    """`spec/sizes.py`: every size the island bar lays out and paints."""

    bar: Bar
    capsule: Capsule
    menu: MenuGrid


@dataclass(frozen=True, slots=True)
class Specs:
    """Every spec the bar reads, re-imported together so a reload applies all or none."""

    sizes: Sizes
    controls: ControlsSpec
    island: IslandSpec


def fresh(module: ModuleType) -> None:
    """Run a spec module again from its file; any failure is its edit's."""
    found = module.__spec__
    if found is None or found.loader is None:
        raise SpecError(f"{module.__name__}: not loaded from a file")
    try:
        # Running the module's loader again re-reads its file into the same module,
        # as reload does, without depending on how the module was found.
        found.loader.exec_module(module)
    except Exception as error:
        raise SpecError(f"{module.__name__.rsplit('.', 1)[-1]}.py: {error}") from error


def checked[T](name: str, value: T, found: tuple[str, ...]) -> T:
    if found:
        raise SpecError(f"{name}: {found[0]}")
    return value


def bar_specs(*, reload: bool = True) -> Specs:
    """The bar's specs as their modules say now; `reload` runs them again from their files first."""
    if reload:
        for module in (sizes, controls, island):
            fresh(module)
    return Specs(
        sizes.SIZES,
        checked("controls.py", controls.CONTROLS, problems(controls.CONTROLS)),
        checked("island.py", island.ISLAND, island_problems(island.ISLAND)),
    )
