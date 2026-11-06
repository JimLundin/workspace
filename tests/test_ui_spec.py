"""The desktop's UI specs: the shipped values check, edits are refused by name, and
a reload re-runs a spec module from its file."""

import importlib.util
import sys
from dataclasses import asdict, replace
from pathlib import Path

from desktop_ui import ui_spec
from desktop_ui.island_layout import Metrics, Placed, arrange, frame, tiles
from desktop_ui.island_menu import CellSpec, CellsRow, Command, EntryId, Face, Item, Live, Menu, Toggle, entries, problems
from desktop_ui.island_model import (
    Action,
    ActivitiesSpec,
    Activity,
    Control,
    Glyph,
    Key,
    Marker,
    Reading,
    Spinner,
    StatusSpec,
    Text,
    Zone,
    island,
    island_problems,
    order,
)
from desktop_ui.spec.controls import CONTROLS
from desktop_ui.spec.island import ISLAND
from desktop_ui.spec.sizes import SIZES
from desktop_ui.ui_spec import Bar, Capsule, Detail, MenuGrid, Sizes, SpecError
from tests import test_island_model
from tests.test_island_menu import RESTING


def raised(build: object) -> str:
    """The message a spec value refuses itself with as it's built."""
    try:
        if callable(build):
            build()
    except ValueError as error:
        return str(error)
    raise AssertionError("The value was accepted.")


def test_the_shipped_specs_check() -> None:
    # Defect: a shipped spec breaks one of its own rules, so the desktop starts on a broken menu or bar.
    specs = ui_spec.bar_specs(reload=False)
    assert specs.sizes.capsule.height >= specs.sizes.capsule.control


def test_an_impossible_size_is_refused_by_name_as_it_is_built() -> None:
    # Defect: a negative gap or a control taller than its capsule reaches the layout,
    # and the bar draws overlapping or inside-out shapes instead of keeping its last good sizes.
    assert "gap must be at least 0" in raised(lambda: replace(SIZES.bar, gap=-6))
    assert "must fit its capsule" in raised(lambda: replace(SIZES.capsule, control=40))
    assert "track must be at least 1" in raised(lambda: replace(SIZES.menu, track=0))


def test_a_broken_spec_edit_is_reported_by_its_file_and_keeps_the_reader_running(tmp_path: Path) -> None:
    # Defect: a spec module that no longer runs (a typo, an impossible value) crashes
    # the bar's reload instead of raising a SpecError naming the file.
    path = tmp_path / "edited.py"
    path.write_text("from desktop_ui.ui_spec import Bar\nBAR = Bar(8, 12, 6, 17, 40)\n", encoding="utf-8")
    found = importlib.util.spec_from_file_location("workspace_spec_edit", path)
    assert found is not None and found.loader is not None
    module = importlib.util.module_from_spec(found)
    sys.modules[found.name] = module
    try:
        found.loader.exec_module(module)
        path.write_text("from desktop_ui.ui_spec import Bar\nBAR = Bar(8, 12, -6, 17, 40)\n", encoding="utf-8")
        try:
            ui_spec.fresh(module)
        except SpecError as error:
            assert str(error).startswith("workspace_spec_edit.py: bar: gap")
        else:
            raise AssertionError("The broken edit was accepted.")
    finally:
        del sys.modules[found.name]


def doubled() -> Sizes:
    """Every size twice as large; the trace's bar count is a count, not a size."""
    capsule = {name: value * 2 for name, value in asdict(SIZES.capsule).items()}
    return Sizes(
        Bar(**{name: value * 2 for name, value in asdict(SIZES.bar).items()}),
        Capsule(**{**capsule, "wave_bars": SIZES.capsule.wave_bars}),
        MenuGrid(**{name: value * 2 for name, value in asdict(SIZES.menu).items()}),
        Detail(**{name: value * 2 for name, value in asdict(SIZES.detail).items()}),
    )


def test_every_size_the_bar_lays_out_comes_from_the_spec() -> None:
    # Defect: a size is still a literal in the layout, so editing the spec moves only
    # part of the bar and its parts drift out of alignment.
    base, large = SIZES, doubled()

    def width(text: Text) -> float:
        return 7.0 * len(text.text)

    def wide(text: Text) -> float:
        return 2 * width(text)

    rows = ((Spinner("Agent"), Text("Reading"), Control("stop", "Stop", Action.OPEN_MENU)),), ((Glyph("bell"), Marker.DOT, Marker.DOTS),)
    for slots in rows:
        small, big = arrange(slots, width, base), arrange(slots, wide, large)
        assert (big.width, big.height) == (2 * small.width, 2 * small.height)
        assert [spot.x for spot in big.spots] == [2 * spot.x for spot in small.spots]
    capsules = (Placed(Key.ISLAND, Zone.ISLAND, 112, 34), Placed(Key.STATUS, Zone.RIGHT, 200, 34), Placed(Key.INBOX, Zone.TRAIL, 40, 34))
    bars = ((base, capsules, 1000.0), (large, tuple(Placed(c.key, c.zone, 2 * c.width, 2 * c.height) for c in capsules), 2000.0))
    small_frame, big_frame = (frame(placed, Metrics(screen, s.bar.top, s.bar.gap, s.bar.edge), order(ISLAND)) for s, placed, screen in bars)
    assert [(f.box.x * 2, f.box.y * 2, f.box.width * 2) for f in small_frame] == [(f.box.x, f.box.y, f.box.width) for f in big_frame]
    menu = Menu(entries(RESTING, CONTROLS))
    pairs = zip(tiles(menu, base.menu), tiles(menu, large.menu), strict=True)
    assert all((2 * a.x, 2 * a.y, 2 * a.width, 2 * a.height) == (b.x, b.y, b.width, b.height) for a, b in pairs)


def test_a_menu_edit_that_overflows_repeats_or_mislooks_is_refused() -> None:
    # Defect: a menu edit puts a row past the grid's edge, places an entry twice (two
    # cells, one action), shows a toggle as a slider or leaves a cell without words,
    # and the menu draws it anyway instead of keeping the last good layout.
    def found(*cells: CellSpec) -> tuple[str, ...]:
        return problems(replace(CONTROLS, rows=(*CONTROLS.rows, CellsRow(4, cells))))

    assert any(
        "span 9 of the menu's 8 columns" in each
        for each in found(CellSpec(EntryId.RECORD, Face.WIDE, 5, "A", "mic"), CellSpec(EntryId.CANVAS, Face.TILE, 4, "B", "canvas"))
    )
    assert any("overlay is already placed" in each for each in found(CellSpec(EntryId.OVERLAY, Face.TOGGLE, 4, "Overlay", "layers")))
    assert any("can't show as slider" in each for each in found(CellSpec(EntryId.OVERLAY, Face.SLIDER, 4, "Overlay", "layers")))
    assert any("needs a label and an icon" in each for each in found(CellSpec(EntryId.KEYMAP, Face.TOOL, 2)))
    assert "spans 1 to 8 columns" in raised(lambda: CellSpec(EntryId.KEYMAP, Face.TOOL, 9, "Key map", "keyboard"))


def test_every_menu_command_is_reachable_from_the_shipped_menu() -> None:
    # Defect: an edit to the menu spec drops a control, so its action is no longer
    # reachable from the menu at all.
    resting, busy = entries(RESTING, CONTROLS), entries(replace(RESTING, agent="Reading", recording="00:10"), CONTROLS)
    choices = {cell.entry.choice for cell in (*resting, *busy) if isinstance(cell.entry, Item | Toggle)}
    stops = {cell.entry.stop for cell in busy if isinstance(cell.entry, Live)}
    assert choices | stops >= set(Command)


def test_editing_the_bar_composition_moves_and_hides_its_parts() -> None:
    # Defect: the spec is read but the bar still places activities and readings
    # where the code used to, so an edit to the composition changes nothing.
    moved = replace(ISLAND, activities=ActivitiesSpec(lead=(Activity.RECORDING, Activity.AGENT, Activity.JOB), trail=(Activity.INBOX,)))
    assert order(moved)[:3] == (Key.RECORDING, Key.AGENT, Key.JOB)
    resting = test_island_model.RESTING
    recording = replace(resting, agent=test_island_model.WORKING, dictating=True, recording=replace(resting.recording, phase="recording", seconds=5))
    assert next(view for view in island(recording, moved) if view.key is Key.RECORDING).zone is Zone.LEAD
    quiet = replace(ISLAND, status=StatusSpec(((Reading.CLOCK, Reading.POWER, Reading.BATTERY),)))
    status = next(view for view in island(resting, quiet) if view.key is Key.STATUS)
    glyphs = {part.name for slot in status.slots for part in slot if isinstance(part, Glyph)}
    assert len(status.slots) == 1 and not glyphs & {"cpu", "memory", "speaker-unknown", "wifi-unknown"}


def test_a_bar_edit_that_loses_or_repeats_a_part_is_refused() -> None:
    # Defect: an activity left out of both sides never shows, one listed twice is
    # drawn twice, or a reading repeats in the status capsule.
    lost = replace(ISLAND, activities=ActivitiesSpec(lead=(Activity.AGENT, Activity.JOB), trail=(Activity.RECORDING,)))
    assert "activities: inbox is placed 0 times" in island_problems(lost)
    twice = replace(
        ISLAND, activities=ActivitiesSpec(lead=(Activity.AGENT, Activity.JOB), trail=(Activity.RECORDING, Activity.INBOX, Activity.AGENT))
    )
    assert "activities: agent is placed 2 times" in island_problems(twice)
    clock = replace(ISLAND, status=StatusSpec(((Reading.CLOCK,), (Reading.CLOCK, Reading.BATTERY))))
    assert "status: clock appears more than once" in island_problems(clock)
