"""What Workspace puts back when the laptop's own panel comes back with the screens."""

from dataclasses import dataclass, field

from desktop_ui.laptop_panel import LaptopPanel
from winapi.panel_brightness import Level, Unavailable


@dataclass(slots=True)
class Panel:
    """A built-in panel's brightness, which a closed lid makes unreachable."""

    current: int
    open: bool = True
    sets: list[int] = field(default_factory=list[int])

    def level(self) -> Level | Unavailable:
        return Level(self.current) if self.open else Unavailable()

    def set_level(self, level: int) -> Level | Unavailable:
        if not self.open:
            return Unavailable()
        self.sets.append(level)
        self.current = level
        return Level(level)


def owner(panel: Panel) -> LaptopPanel:
    return LaptopPanel(panel)


def test_darkening_turns_the_panel_down_to_zero_and_restoring_puts_back_the_persons_level() -> None:
    # Defects: the panel is only dimmed part way, or restoring writes a fixed level instead of the person's.
    panel = Panel(current=70)
    dimmed = owner(panel).darken()
    assert panel.current == 0
    dimmed.restore()
    assert panel.current == 70


def test_darkening_twice_keeps_the_original_level_to_restore() -> None:
    # Defect: a second darkening reads 0 and remembers it, so the panel never comes back.
    panel = Panel(current=40)
    owner(panel).darken().darken().restore()
    assert panel.current == 40


def test_restoring_what_was_never_darkened_leaves_the_panel_alone() -> None:
    # Defect: a panel Workspace never dimmed gets a level it never read written to it.
    panel = Panel(current=55)
    owner(panel).restore()
    assert panel.sets == []


def test_a_panel_the_person_already_turned_to_zero_is_left_alone() -> None:
    # Defect: 0 is remembered as something to put back, and a later restore writes over a level they chose since.
    panel = Panel(current=0)
    owner(panel).darken().restore()
    assert panel.sets == []


def test_a_restore_refused_with_the_lid_closed_is_tried_again_once_the_panel_is_back() -> None:
    # Defect: the refused restore forgets the person's level, and the lid opens on a panel left at 0.
    panel = Panel(current=80)
    dimmed = owner(panel).darken()
    panel.open = False
    pending = dimmed.restore()
    assert panel.current == 0
    panel.open = True
    pending.restore()
    assert panel.current == 80


def test_a_closed_lid_while_darkening_writes_nothing_to_put_back() -> None:
    # Defect: an unreadable panel is still remembered as dimmed, and a later restore writes a guessed level.
    panel = Panel(current=60, open=False)
    untouched = owner(panel).darken()
    panel.open = True
    untouched.restore()
    assert panel.sets == []
