"""The bar's specs as data: the layout reads every size from them, the menu reaches every command,
and the bar's composition places and hides its parts as the spec says."""

from dataclasses import asdict, replace

from desktop_ui.island_layout import SIZES, Bar, Capsule, MenuGrid, Metrics, Placed, Sizes, arrange, frame, tiles
from desktop_ui.island_menu import CONTROLS, Command, Item, Live, Menu, Toggle, entries
from desktop_ui.island_model import (
    ISLAND,
    Action,
    ActivitiesSpec,
    Activity,
    Control,
    Glyph,
    Key,
    Marker,
    Reading,
    StatusSpec,
    Text,
    Zone,
    island,
    order,
)
from tests import test_island_model
from tests.test_island_menu import RESTING


def doubled() -> Sizes:
    """Every size twice as large; the trace's bar count is a count, not a size."""
    capsule = {name: value * 2 for name, value in asdict(SIZES.capsule).items()}
    return Sizes(
        Bar(**{name: value * 2 for name, value in asdict(SIZES.bar).items()}),
        Capsule(**{**capsule, "wave_bars": SIZES.capsule.wave_bars}),
        MenuGrid(**{name: value * 2 for name, value in asdict(SIZES.menu).items()}),
    )


def test_every_size_the_bar_lays_out_comes_from_the_spec() -> None:
    # Defect: a size is still a literal in the layout, so editing the spec moves only
    # part of the bar and its parts drift out of alignment.
    base, large = SIZES, doubled()

    def width(text: Text) -> float:
        return 7.0 * len(text.text)

    def wide(text: Text) -> float:
        return 2 * width(text)

    rows = ((Marker.DOT, Text("Reading"), Control("stop", "Stop", Action.OPEN_MENU)),), ((Glyph("mic.fill"), Marker.DOT, Marker.DOTS),)
    for slots in rows:
        small, big = arrange(slots, width, base), arrange(slots, wide, large)
        assert (big.width, big.height) == (2 * small.width, 2 * small.height)
        assert [spot.x for spot in big.spots] == [2 * spot.x for spot in small.spots]
    capsules = (Placed(Key.ISLAND, Zone.ISLAND, 112, 34), Placed(Key.STATUS, Zone.RIGHT, 200, 34), Placed(Key.RECORDING, Zone.TRAIL, 40, 34))
    bars = ((base, capsules, 1000.0), (large, tuple(Placed(c.key, c.zone, 2 * c.width, 2 * c.height) for c in capsules), 2000.0))
    small_frame, big_frame = (frame(placed, Metrics(screen, s.bar.top, s.bar.gap, s.bar.edge), order(ISLAND)) for s, placed, screen in bars)
    assert [(f.box.x * 2, f.box.y * 2, f.box.width * 2) for f in small_frame] == [(f.box.x, f.box.y, f.box.width) for f in big_frame]
    menu = Menu(entries(RESTING, CONTROLS))
    pairs = zip(tiles(menu, base.menu), tiles(menu, large.menu), strict=True)
    assert all((2 * a.x, 2 * a.y, 2 * a.width, 2 * a.height) == (b.x, b.y, b.width, b.height) for a, b in pairs)


def test_every_menu_command_is_reachable_from_the_shipped_menu() -> None:
    # Defect: an edit to the menu spec drops a control, so its action is no longer
    # reachable from the menu at all.
    resting, busy = entries(RESTING, CONTROLS), entries(replace(RESTING, recording="00:10"), CONTROLS)
    choices = {cell.entry.choice for cell in (*resting, *busy) if isinstance(cell.entry, Item | Toggle)}
    stops = {cell.entry.stop for cell in busy if isinstance(cell.entry, Live)}
    assert choices | stops >= set(Command)


def test_editing_the_bar_composition_moves_and_hides_its_parts() -> None:
    # Defect: the spec is read but the bar still places activities and readings
    # where the code used to, so an edit to the composition changes nothing.
    moved = replace(ISLAND, activities=ActivitiesSpec(lead=(Activity.RECORDING, Activity.JOB), trail=()))
    assert order(moved)[:2] == (Key.RECORDING, Key.JOB)
    resting = test_island_model.RESTING
    recording = replace(resting, dictating=True, recording=replace(resting.recording, phase="recording", seconds=5))
    assert next(view for view in island(recording, moved) if view.key is Key.RECORDING).zone is Zone.LEAD
    quiet = replace(ISLAND, status=StatusSpec(((Reading.CLOCK, Reading.POWER, Reading.BATTERY),)))
    status = next(view for view in island(resting, quiet) if view.key is Key.STATUS)
    glyphs = {part.name for slot in status.slots for part in slot if isinstance(part, Glyph)}
    assert len(status.slots) == 1 and not glyphs & {"cpu", "memory", "speaker-unknown", "wifi-unknown"}
